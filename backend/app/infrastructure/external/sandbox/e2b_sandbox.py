import asyncio
import base64
import os
import io
import logging
from typing import Optional, BinaryIO
import httpx
from e2b import Sandbox as E2BSandboxSDK
from e2b.sandbox.commands.command_handle import CommandExitException
from app.domain.external.sandbox import Sandbox, Browser
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser
from app.core.config import get_settings
from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

# The E2B template runs as ubuntu user; translate root-only paths to user home
_ROOT_PATH_PREFIXES = ("/root",)
_UBUNTU_HOME = "/home/ubuntu"

# Session used internally for one-shot admin commands
_SYS_BASE_SESSION = "__sys__"


def _translate_exec_dir(exec_dir: str) -> str:
    """
    The E2B sandbox runs as user 'ubuntu' (no root access).
    Translate any path under /root to the equivalent under /home/ubuntu.
    """
    for prefix in _ROOT_PATH_PREFIXES:
        if exec_dir == prefix or exec_dir.startswith(prefix + "/"):
            return _UBUNTU_HOME + exec_dir[len(prefix):]
    return exec_dir


class E2BSandbox(Sandbox):
    """
    E2B Sandbox implementation.

    The custom E2B template runs the same FastAPI sandbox API (port 8080),
    Chrome CDP (port 9222), and VNC/websockify (port 5901) as the Docker image.
    All sandbox operations proxy through the sandbox HTTP API — identical in
    interface to DockerSandbox but reached via E2B's public HTTPS tunnel.

    Key differences from Docker:
    - Docker sandbox runs as root; E2B template runs as 'ubuntu' user.
      exec_dir paths under /root are transparently remapped to /home/ubuntu.
    - Chrome may need to be installed on first use because Ubuntu 22.04
      replaced chromium-browser with a snap stub. The create() classmethod
      installs Google Chrome in the background so the supervisor can start it.
    """

    def __init__(self, e2b_sandbox: E2BSandboxSDK):
        self.e2b_sandbox = e2b_sandbox
        self.client = httpx.AsyncClient(timeout=600)
        self._id = e2b_sandbox.sandbox_id
        # E2B exposes ports via HTTPS tunnels; get_host() returns the hostname.
        self.base_url = f"https://{e2b_sandbox.get_host(8080)}"
        self._vnc_url = f"wss://{e2b_sandbox.get_host(5901)}"
        self._cdp_url = f"https://{e2b_sandbox.get_host(9222)}"
        logger.info(
            "E2B Sandbox initialised: id=%s base_url=%s vnc=%s cdp=%s",
            self._id, self.base_url, self._vnc_url, self._cdp_url,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_admin_cmd(self, cmd: str, timeout: int = 30) -> str:
        """
        Run a one-shot admin command directly via the E2B SDK's built-in
        commands.run() — this bypasses the custom sandbox shell HTTP API
        entirely, so it works even when that service is not yet ready or
        has output-reader issues.

        Falls back to the legacy HTTP shell API if the SDK call fails.
        """
        # ── Primary path: E2B SDK commands.run() ─────────────────────────
        try:
            result = await asyncio.to_thread(
                self.e2b_sandbox.commands.run,
                cmd,
                timeout=float(timeout),
            )
            output = (result.stdout or "") + (result.stderr or "")
            logger.debug("SDK admin cmd exit=%s output_len=%d", result.exit_code, len(output))
            return output
        except CommandExitException as ce:
            # Non-zero exit — command ran but failed; still return stdout+stderr
            # so callers can inspect output (e.g. check for "PLAYWRIGHT_OK")
            output = (ce.stdout or "") + (ce.stderr or "")
            logger.debug(
                "SDK admin cmd exit=%d (non-zero) output_len=%d",
                ce.exit_code, len(output),
            )
            return output
        except Exception as sdk_exc:
            logger.warning(
                "SDK commands.run failed (%s): %s — falling back to shell HTTP API",
                cmd[:60], sdk_exc,
            )

        # ── Fallback: legacy custom shell HTTP API ────────────────────────
        session = f"{_SYS_BASE_SESSION}_{os.urandom(4).hex()}"
        try:
            await self._exec_raw(session, _UBUNTU_HOME, cmd)
            await self._wait_raw(session, timeout)
            await asyncio.sleep(2.0)
            view = await self._view_raw(session)
            data = view.data
            if data is None:
                return ""
            if isinstance(data, dict):
                output = str(data.get("output", "") or "")
                if not output:
                    await asyncio.sleep(2.0)
                    view2 = await self._view_raw(session)
                    data2 = view2.data or {}
                    if isinstance(data2, dict):
                        output = str(data2.get("output", "") or "")
                return output
            return str(data or "")
        except Exception as exc:
            logger.warning("Fallback admin cmd failed (%s): %s", cmd[:60], exc)
            return ""

    async def _exec_raw(self, session_id: str, exec_dir: str, command: str) -> ToolResult:
        """Direct exec_command without path translation (for internal use)."""
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/exec",
            json={"id": session_id, "exec_dir": exec_dir, "command": command},
        )
        return ToolResult(**response.json())

    async def _wait_raw(self, session_id: str, seconds: Optional[int] = None) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/wait",
            json={"id": session_id, "seconds": seconds},
        )
        return ToolResult(**response.json())

    async def _view_raw(self, session_id: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/view",
            json={"id": session_id, "console": False},
        )
        return ToolResult(**response.json())

    async def _fix_chrome(self) -> None:
        """
        Install a working Chromium/Chrome binary and restart the supervisord
        chrome service.

        Strategy (in order):
          0. Diagnostic echo — verify shell exec pipeline is functional.
          1. Playwright install — downloads bundled Chromium, most reliable.
          2. Google Chrome apt-repo — add Google's repo and install.
          3. Direct .deb download — fallback for restricted networks.
        """
        # ── Step 0: sanity-check the shell exec pipeline ─────────────────
        diag = await self._run_admin_cmd(
            "echo DIAG_START; "
            "whoami; "
            # Check for any usable Chrome/Chromium binary
            "ls /usr/bin/google-chrome /usr/bin/playwright-chromium "
            "   /usr/bin/chromium-browser /usr/bin/chromium 2>&1; "
            # Check pre-installed Playwright Chromium (new template)
            "PWCHROME=$(find /opt/playwright-browsers -name 'chrome' -type f "
            "           2>/dev/null | head -1); "
            "echo PW_PREINSTALLED=$PWCHROME; "
            "pip3 show playwright 2>/dev/null | grep -q 'Version' && echo PW_PKG_OK || echo PW_PKG_MISSING; "
            "curl -sSf --connect-timeout 5 https://dl.google.com/robots.txt 2>&1 | head -1",
            timeout=20,
        )
        logger.info("Chrome fix diagnostic: %s", diag[:600] if diag else "(empty — shell exec broken!)")

        if not diag:
            logger.error(
                "Shell exec is not returning output — Chrome cannot be installed at runtime. "
                "Rebuild the e2b template (sandbox/e2b.Dockerfile) with Google Chrome pre-installed."
            )
            return

        # A *real* usable Chrome binary exists if:
        # (a) google-chrome is present (apt install, new Dockerfile)
        # (b) playwright-chromium symlink exists (new Dockerfile layer 5)
        # (c) Playwright Chromium binary found in /opt/playwright-browsers
        has_real_chrome = (
            ("google-chrome" in diag and "No such file" not in diag.split("PW_PREINSTALLED")[0])
            or "playwright-chromium" in diag.split("No such file")[0]
            or ("PW_PREINSTALLED=" in diag and "PW_PREINSTALLED=\n" not in diag
                and "PW_PREINSTALLED= " not in diag)
        )

        if has_real_chrome:
            logger.info("Usable Chrome/Chromium binary found — skipping download, just restarting…")
        else:
            # ── Step 1: Playwright (most reliable — no snap/apt issues) ───
            # In the new Dockerfile, playwright is pre-installed as a system
            # package.  If the pip package is missing we install it first,
            # then download/link the Chromium binary.
            logger.info("Attempting Playwright Chromium install…")
            pw_out = await self._run_admin_cmd(
                # Install playwright Python package if not already present.
                # Try sudo --break-system-packages first (Ubuntu 22.04+), then
                # --user as final fallback.
                "python3 -c 'import playwright' 2>/dev/null || "
                "  (sudo pip3 install --quiet --break-system-packages playwright 2>&1 "
                "   || pip3 install --quiet --break-system-packages playwright 2>&1 "
                "   || pip3 install --quiet --user playwright 2>&1) | tail -3; "
                # Install Chromium browser binary to /opt/playwright-browsers
                # (PLAYWRIGHT_BROWSERS_PATH set in environment so it lands in the
                # right place for both root and ubuntu user).
                "export PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers; "
                "sudo mkdir -p /opt/playwright-browsers; "
                "(sudo python3 -m playwright install chromium 2>&1 "
                " || python3 -m playwright install chromium 2>&1) | tail -5; "
                # Create symlink so supervisord chrome command can find the binary
                "CHROME=$(find /opt/playwright-browsers /root/.cache /home "
                "         -name 'chrome' -type f 2>/dev/null | head -1); "
                "echo FOUND=$CHROME; "
                "[ -n \"$CHROME\" ] "
                "  && sudo chmod +x \"$CHROME\" "
                "  && sudo ln -sf \"$CHROME\" /usr/bin/playwright-chromium "
                "  && sudo ln -sf \"$CHROME\" /usr/bin/chromium-browser "
                "  && sudo chmod -R a+rX /opt/playwright-browsers "
                "  && echo PLAYWRIGHT_OK",
                timeout=360,
            )
            logger.info("Playwright install: %s", pw_out[:500] if pw_out else "(empty)")

            if "PLAYWRIGHT_OK" not in (pw_out or ""):
                # ── Step 2: Google Chrome apt-repo ──────────────────────
                logger.warning("Playwright failed — trying Google Chrome apt-repo…")
                apt_out = await self._run_admin_cmd(
                    "curl -fSL --connect-timeout 15 https://dl.google.com/linux/linux_signing_key.pub "
                    "| sudo gpg --batch --yes --dearmor "
                    "-o /usr/share/keyrings/google-chrome.gpg 2>&1 && "
                    "echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] "
                    "http://dl.google.com/linux/chrome/deb/ stable main' "
                    "| sudo tee /etc/apt/sources.list.d/google-chrome.list > /dev/null && "
                    "sudo apt-get update -qq 2>&1 | tail -3 && "
                    "sudo apt-get install -y --no-install-recommends google-chrome-stable 2>&1 | tail -5 && "
                    "sudo ln -sf /usr/bin/google-chrome /usr/bin/chromium-browser && "
                    "echo CHROME_APT_OK",
                    timeout=240,
                )
                logger.info("apt-repo install: %s", apt_out[:500] if apt_out else "(empty)")

                if "CHROME_APT_OK" not in (apt_out or ""):
                    # ── Step 3: Direct .deb download ────────────────────
                    logger.warning("apt-repo failed — trying direct .deb download…")
                    deb_out = await self._run_admin_cmd(
                        "curl -fSL --connect-timeout 30 "
                        "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb "
                        "-o /tmp/chrome.deb && "
                        "sudo dpkg -i /tmp/chrome.deb 2>&1 | tail -5; "
                        "sudo apt-get install -f -y 2>&1 | tail -3 || true; "
                        "sudo ln -sf /usr/bin/google-chrome /usr/bin/chromium-browser || true; "
                        "echo CHROME_DEB_DONE",
                        timeout=240,
                    )
                    logger.info("deb install: %s", deb_out[:500] if deb_out else "(empty)")

        # ── Patch supervisord.conf in-place ──────────────────────────────
        # Ensure --user-data-dir, --remote-allow-origins=*, and singleton
        # lock cleanup are all present. These may be absent in older template
        # builds. Each patch is guarded so it is idempotent.
        patch_out = await self._run_admin_cmd(
            # 1) Add --user-data-dir if missing
            "grep -q 'user-data-dir' /app/supervisord.conf || "
            "sudo sed -i 's|--remote-debugging-port=8222|"
            "--user-data-dir=/tmp/chrome-profile "
            "--remote-debugging-port=8222|g' /app/supervisord.conf; "
            # 2) Add --remote-allow-origins=* if missing
            "grep -q 'remote-allow-origins' /app/supervisord.conf || "
            "sudo sed -i 's|--remote-debugging-port=8222|"
            "--remote-debugging-port=8222 --remote-allow-origins=*|g' "
            "/app/supervisord.conf; "
            "echo CONF_PATCHED; "
            # 3) Remove the invalid --display=:1 CLI flag (DISPLAY is set via env)
            "sudo sed -i '/--display=:1/d' /app/supervisord.conf 2>/dev/null || true; "
            # 4) Remove singleton lock so next Chrome start owns the debug port
            "rm -rf /tmp/chrome-profile/SingletonLock "
            "/tmp/chrome-profile/SingletonCookie "
            "/tmp/chrome-profile/SingletonSocket 2>/dev/null; "
            "echo LOCK_CLEANED",
            timeout=15,
        )
        logger.info("supervisord.conf patch: %s", patch_out[:300] if patch_out else "(empty)")

        # ── Deploy CDP proxy (replaces socat on port 9222) ────────────────
        # Chrome's DNS-rebinding protection rejects HTTP requests where the
        # Host header is not localhost or an IP address.  E2B tunnels always
        # set a host like 9222-<id>.e2b.app, which Chrome rejects.
        # The CDP proxy rewrites the Host header → localhost:8222 for every
        # incoming HTTP/WebSocket request, and also rewrites ws://localhost
        # URLs in HTTP response bodies to wss://EXTERNAL so browser_use can
        # connect to the WebSocket debugger from outside the sandbox.
        await self._deploy_cdp_proxy()

        # ── Restart supervisord chrome + cdpproxy services ────────────────
        restart_out = await self._run_admin_cmd(
            "sudo supervisorctl -c /app/supervisord.conf stop services:chrome 2>&1; "
            "sleep 1; "
            "sudo supervisorctl -c /app/supervisord.conf reread 2>&1; "
            "sudo supervisorctl -c /app/supervisord.conf update 2>&1; "
            "sudo supervisorctl -c /app/supervisord.conf start services:chrome 2>&1; "
            "sleep 4; "
            "sudo supervisorctl -c /app/supervisord.conf status 2>&1",
            timeout=30,
        )
        logger.info("Chrome supervisor restart: %s", restart_out[:400] if restart_out else "(empty)")

    async def _deploy_cdp_proxy(self) -> None:
        """
        Deploy the CDP Host-header proxy (cdp_proxy.py) to the sandbox and
        ensure supervisord manages it instead of socat on port 9222.

        Idempotent — safe to call on both old (socat) and new (cdpproxy)
        template builds.
        """
        proxy_script = (
            "#!/usr/bin/env python3\n"
            '"""CDP Host-header proxy for E2B sandboxes (auto-deployed at runtime)."""\n'
            "import asyncio, re, sys\n"
            'CHROME_HOST="127.0.0.1"; CHROME_PORT=8222; PROXY_PORT=9222\n'
            "EXTERNAL_HOST=sys.argv[1] if len(sys.argv)>1 else \"\"\n"
            "async def _pipe(r,w):\n"
            "    try:\n"
            "        while True:\n"
            "            d=await r.read(65536)\n"
            "            if not d: break\n"
            "            w.write(d); await w.drain()\n"
            "    except: pass\n"
            "    finally:\n"
            "        try: w.close()\n"
            "        except: pass\n"
            "def _rewrite(body,ext):\n"
            "    if not ext: return body\n"
            "    b=ext.encode()\n"
            '    body=body.replace(b"ws://localhost:8222",b"wss://"+b)\n'
            '    body=body.replace(b"ws://localhost/",b"wss://"+b+b"/")\n'
            "    return body\n"
            "def _fix_cl(resp,nb,ob):\n"
            "    if len(nb)==len(ob): return resp\n"
            '    sep=resp.find(b"\\r\\n\\r\\n")\n'
            "    if sep<0: return resp\n"
            '    h=re.sub(rb"(?i)content-length:\\s*\\d+",b"Content-Length: "+str(len(nb)).encode(),resp[:sep])\n'
            '    return h+b"\\r\\n\\r\\n"+nb\n'
            "async def _handle(cr,cw):\n"
            "    global EXTERNAL_HOST\n"
            "    try:\n"
            '        buf=b""\n'
            '        while b"\\r\\n\\r\\n" not in buf:\n'
            "            c=await asyncio.wait_for(cr.read(4096),30)\n"
            "            if not c: return\n"
            "            buf+=c\n"
            '        sep=buf.index(b"\\r\\n\\r\\n"); raw=buf[:sep]; tail=buf[sep+4:]\n'
            "        ws=False; nl=[]\n"
            '        for ln in raw.split(b"\\r\\n"):\n'
            '            if ln.lower().startswith(b"host:"):\n'
            "                orig=ln[5:].strip().decode(errors=\"replace\")\n"
            '                if not EXTERNAL_HOST and orig and "localhost" not in orig:\n'
            "                    EXTERNAL_HOST=orig\n"
            '                    print(f"CDPproxy: learned ext={EXTERNAL_HOST}",flush=True)\n'
            '                nl.append(b"Host: localhost:8222")\n'
            "            else:\n"
            '                if b"websocket" in ln.lower(): ws=True\n'
            "                nl.append(ln)\n"
            "        xr,xw=await asyncio.wait_for(asyncio.open_connection(CHROME_HOST,CHROME_PORT),10)\n"
            '        xw.write(b"\\r\\n".join(nl)+b"\\r\\n\\r\\n"+tail); await xw.drain()\n'
            "        if ws:\n"
            "            await asyncio.gather(_pipe(cr,xw),_pipe(xr,cw),return_exceptions=True); return\n"
            '        resp=b""\n'
            "        try:\n"
            "            while True:\n"
            "                ch=await asyncio.wait_for(xr.read(65536),20)\n"
            "                if not ch: break\n"
            "                resp+=ch\n"
            '                if b"\\r\\n\\r\\n" not in resp: continue\n'
            '                he=resp.index(b"\\r\\n\\r\\n"); hl=resp[:he].lower()\n'
            '                ci=hl.find(b"content-length:")\n'
            "                if ci>=0:\n"
            '                    cl=int(hl[ci:].split(b"\\r\\n")[0].split(b":")[1].strip())\n'
            "                    if len(resp)>=he+4+cl: break\n"
            "        except asyncio.TimeoutError: pass\n"
            '        if b"\\r\\n\\r\\n" in resp:\n'
            '            he=resp.index(b"\\r\\n\\r\\n"); ob=resp[he+4:]; nb=_rewrite(ob,EXTERNAL_HOST)\n'
            "            resp=_fix_cl(resp,nb,ob)\n"
            "        cw.write(resp); await cw.drain()\n"
            "        try: xw.close()\n"
            "        except: pass\n"
            "    except: pass\n"
            "    finally:\n"
            "        try: cw.close()\n"
            "        except: pass\n"
            "async def main():\n"
            '    srv=await asyncio.start_server(_handle,"0.0.0.0",PROXY_PORT)\n'
            "    print(f\"CDPproxy :9222->8222 ext={EXTERNAL_HOST or '(auto)'}\",flush=True)\n"
            "    async with srv: await srv.serve_forever()\n"
            "asyncio.run(main())\n"
        )
        # Use base64 to safely write the proxy script — avoids heredoc quoting issues
        proxy_b64 = base64.b64encode(proxy_script.encode()).decode()
        write_out = await self._run_admin_cmd(
            f"echo '{proxy_b64}' | base64 -d | sudo tee /app/cdp_proxy.py > /dev/null "
            "&& sudo chmod +x /app/cdp_proxy.py && echo PROXY_WRITTEN",
            timeout=10,
        )
        logger.info("CDP proxy write: %s", write_out[:200] if write_out else "(empty)")

        # Patch supervisord.conf: replace [program:socat] with [program:cdpproxy]
        # and update the group line.  All ops are idempotent.
        conf_patch = (
            # Kill any running socat on 9222
            "sudo pkill -f 'socat TCP-LISTEN:9222' 2>/dev/null || true; "
            # If conf has [program:socat], replace with [program:cdpproxy]
            "python3 -c \""
            "import re,subprocess;"
            "conf=open('/app/supervisord.conf').read();"
            "if '[program:socat]' in conf:"
            "  conf=re.sub(r'\\[program:socat\\].*?(?=\\[|\\Z)',"
            "    '[program:cdpproxy]\\n"
            "command=python3 /app/cdp_proxy.py\\n"
            "autostart=true\\nautorestart=true\\n"
            "stdout_logfile=/tmp/cdpproxy.log\\n"
            "stderr_logfile=/tmp/cdpproxy_err.log\\n"
            "priority=30\\nstartsecs=2\\n\\n',"
            "    conf,flags=re.DOTALL);"
            "conf=re.sub(r'programs=([^\\n]+)',"
            "  lambda m: 'programs='+','.join(dict.fromkeys("
            "    x.strip() for x in m.group(1).replace('socat','cdpproxy').split(',') if x.strip())),"
            "  conf);"
            "open('/app/supervisord.conf','w').write(conf);"
            "print('CONF_PATCHED');"
            "\" 2>&1; "
            # Reload supervisord so new config takes effect (restarts all services cleanly)
            "sudo supervisorctl -c /app/supervisord.conf reread 2>&1; "
            "sudo supervisorctl -c /app/supervisord.conf update 2>&1; "
            "sleep 2; "
            "sudo supervisorctl -c /app/supervisord.conf status services:cdpproxy 2>&1 || true; "
            "echo PROXY_SETUP_DONE"
        )
        proxy_out = await self._run_admin_cmd(conf_patch, timeout=20)
        logger.info("CDP proxy setup: %s", proxy_out[:400] if proxy_out else "(empty)")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _wait_for_chrome_running(self, max_wait: int = 90) -> bool:
        """
        Poll supervisord until Chrome shows as RUNNING.

        Returns True if Chrome reached RUNNING within max_wait seconds,
        False otherwise.  Called after _fix_chrome() completes.
        """
        interval = 3
        attempts = max(1, max_wait // interval)
        for i in range(attempts):
            try:
                response = await self.client.get(
                    f"{self.base_url}/api/v1/supervisor/status"
                )
                tool_result = ToolResult(**response.json())
                for svc in (tool_result.data or []):
                    if svc.get("name") == "chrome" and svc.get("statename") == "RUNNING":
                        logger.info("Chrome is now RUNNING after fix")
                        return True
                logger.info(
                    "Waiting for Chrome to start after fix (%d/%d)…", i + 1, attempts
                )
            except Exception as exc:
                logger.debug("Chrome-ready poll error: %s", exc)
            await asyncio.sleep(interval)
        logger.warning("Chrome did not reach RUNNING within %ds", max_wait)
        return False

    async def ensure_sandbox(self) -> None:
        """
        Wait for ALL sandbox services (including Chrome) to become RUNNING.

        If Chrome is FATAL (snap stub issue on Ubuntu 22.04) we install
        Google Chrome, then wait for it to start.  We do not return until
        Chrome is RUNNING so that the browser tool works immediately.

        Also handles Chrome stuck in BACKOFF: if Chrome has been in BACKOFF
        for too many consecutive attempts, we trigger the same fix routine.
        """
        # Phase 1 — wait for core services (app, xvfb, cdpproxy, x11vnc, websockify)
        # These are fast and typically ready within 30 s.
        max_retries = 40
        retry_interval = 2
        chrome_fix_attempted = False
        chrome_backoff_count = 0
        # Trigger fix after Chrome has been stuck in BACKOFF for this many polls
        chrome_backoff_threshold = 5

        for attempt in range(max_retries):
            try:
                response = await self.client.get(
                    f"{self.base_url}/api/v1/supervisor/status"
                )
                response.raise_for_status()
                tool_result = ToolResult(**response.json())
                if not tool_result.success:
                    await asyncio.sleep(retry_interval)
                    continue

                services = tool_result.data or []
                if not services:
                    await asyncio.sleep(retry_interval)
                    continue

                chrome_state = "UNKNOWN"
                non_running_non_chrome: list[str] = []

                for svc in services:
                    name = svc.get("name", "?")
                    state = svc.get("statename", "")
                    if name == "chrome":
                        chrome_state = state
                    elif state != "RUNNING":
                        non_running_non_chrome.append(f"{name}({state})")

                if non_running_non_chrome:
                    logger.info(
                        "Waiting for services (attempt %d/%d): %s",
                        attempt + 1, max_retries, non_running_non_chrome,
                    )
                    await asyncio.sleep(retry_interval)
                    continue

                # All non-chrome services are RUNNING
                if chrome_state == "RUNNING":
                    # Check whether the CDP proxy is running (new template) or
                    # socat is still in place (old template).  If the proxy is
                    # absent or socat is present we deploy/switch it now so
                    # that browser_use can connect via the external HTTPS tunnel.
                    svc_names = {s.get("name", "") for s in services}
                    needs_proxy = (
                        "cdpproxy" not in svc_names
                        or "socat" in svc_names
                    )
                    if needs_proxy:
                        logger.info(
                            "Chrome RUNNING but CDP proxy not yet deployed "
                            "(services=%s) — deploying now…", svc_names
                        )
                        await self._deploy_cdp_proxy()
                    logger.info(
                        "All %d services RUNNING — sandbox fully ready", len(services)
                    )
                    return

                # Track consecutive BACKOFF polls
                if chrome_state == "BACKOFF":
                    chrome_backoff_count += 1
                else:
                    chrome_backoff_count = 0

                # Trigger fix when Chrome is FATAL or stuck in BACKOFF too long
                should_fix = (
                    chrome_state == "FATAL"
                    or (chrome_state == "BACKOFF" and chrome_backoff_count >= chrome_backoff_threshold)
                )

                if should_fix and not chrome_fix_attempted:
                    chrome_fix_attempted = True
                    logger.info(
                        "Core services RUNNING but Chrome is %s (backoff_count=%d) — "
                        "installing/fixing Google Chrome (blocking)…",
                        chrome_state, chrome_backoff_count,
                    )
                    await self._fix_chrome()
                    # Now wait for Chrome to actually reach RUNNING state
                    await self._wait_for_chrome_running(max_wait=90)
                    return

                # Chrome is in a transient state (STARTING, BACKOFF, etc.)
                logger.info(
                    "Core services RUNNING, waiting for Chrome (%s) attempt %d/%d "
                    "(backoff_count=%d)",
                    chrome_state, attempt + 1, max_retries, chrome_backoff_count,
                )
                await asyncio.sleep(retry_interval)

            except Exception as exc:
                logger.warning(
                    "ensure_sandbox attempt %d/%d failed: %s",
                    attempt + 1, max_retries, exc,
                )
                await asyncio.sleep(retry_interval)

        logger.error(
            "Sandbox services failed to become ready after %d attempts (%ds)",
            max_retries, max_retries * retry_interval,
        )

    async def destroy(self) -> bool:
        """Kill the E2B sandbox and close the HTTP client."""
        try:
            if self.client:
                await self.client.aclose()
            await asyncio.to_thread(self.e2b_sandbox.kill)
            logger.info("E2B sandbox %s destroyed", self._id)
            return True
        except Exception as exc:
            logger.error("Failed to destroy E2B sandbox %s: %s", self._id, exc)
            return False

    async def get_browser(self) -> Browser:
        """Return a Browser connected to the sandbox Chrome via CDP."""
        settings = get_settings()
        engine = (settings.browser_engine or "browser_use").lower().strip()
        if engine == "browser_use":
            logger.info("Using BrowserUseBrowser (CDP: %s)", self.cdp_url)
            return BrowserUseBrowser(self.cdp_url)
        logger.info("Using PlaywrightBrowser (CDP: %s)", self.cdp_url)
        return PlaywrightBrowser(self.cdp_url)

    # ------------------------------------------------------------------
    # Shell operations
    # ------------------------------------------------------------------

    async def exec_command(
        self,
        session_id: str,
        exec_dir: str,
        command: str,
    ) -> ToolResult:
        """
        Execute a shell command.  exec_dir paths under /root are remapped to
        /home/ubuntu because the E2B template runs as user 'ubuntu'.
        """
        translated = _translate_exec_dir(exec_dir)
        if translated != exec_dir:
            logger.debug("exec_dir remapped: %s -> %s", exec_dir, translated)
        return await self._exec_raw(session_id, translated, command)

    async def view_shell(
        self,
        session_id: str,
        console: bool = False,
    ) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/view",
            json={"id": session_id, "console": console},
        )
        return ToolResult(**response.json())

    async def wait_for_process(
        self,
        session_id: str,
        seconds: Optional[int] = None,
    ) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/wait",
            json={"id": session_id, "seconds": seconds},
        )
        return ToolResult(**response.json())

    async def write_to_process(
        self,
        session_id: str,
        input_text: str,
        press_enter: bool = True,
    ) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/write",
            json={"id": session_id, "input": input_text, "press_enter": press_enter},
        )
        return ToolResult(**response.json())

    async def kill_process(self, session_id: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/kill",
            json={"id": session_id},
        )
        return ToolResult(**response.json())

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    async def file_write(
        self,
        file: str,
        content: str,
        append: bool = False,
        leading_newline: bool = False,
        trailing_newline: bool = False,
        sudo: bool = False,
    ) -> ToolResult:
        file = _translate_exec_dir(file)
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/write",
            json={
                "file": file,
                "content": content,
                "append": append,
                "leading_newline": leading_newline,
                "trailing_newline": trailing_newline,
                "sudo": sudo,
            },
        )
        return ToolResult(**response.json())

    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: bool = False,
    ) -> ToolResult:
        file = _translate_exec_dir(file)
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/read",
            json={
                "file": file,
                "start_line": start_line,
                "end_line": end_line,
                "sudo": sudo,
            },
        )
        return ToolResult(**response.json())

    async def file_exists(self, path: str) -> ToolResult:
        """Check whether a path exists via shell."""
        path = _translate_exec_dir(path)
        output = await self._run_admin_cmd(
            f"test -e '{path}' && echo __exists__ || echo __absent__"
        )
        exists = "__exists__" in output and "__absent__" not in output
        return ToolResult(
            success=True,
            message="File exists check completed",
            data={"exists": exists},
        )

    async def file_delete(self, path: str) -> ToolResult:
        """Delete a file or directory via shell."""
        path = _translate_exec_dir(path)
        await self._run_admin_cmd(f"rm -rf '{path}'")
        return ToolResult(
            success=True,
            message=f"Deleted: {path}",
            data={"path": path},
        )

    async def file_list(self, path: str) -> ToolResult:
        """List directory contents via shell."""
        path = _translate_exec_dir(path)
        output = await self._run_admin_cmd(f"ls -la '{path}'")
        return ToolResult(
            success=True,
            message="Directory listed",
            data={"listing": output},
        )

    async def file_replace(
        self,
        file: str,
        old_str: str,
        new_str: str,
        sudo: bool = False,
    ) -> ToolResult:
        file = _translate_exec_dir(file)
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/replace",
            json={"file": file, "old_str": old_str, "new_str": new_str, "sudo": sudo},
        )
        return ToolResult(**response.json())

    async def file_search(
        self,
        file: str,
        regex: str,
        sudo: bool = False,
    ) -> ToolResult:
        file = _translate_exec_dir(file)
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/search",
            json={"file": file, "regex": regex, "sudo": sudo},
        )
        return ToolResult(**response.json())

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        path = _translate_exec_dir(path)
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/find",
            json={"path": path, "glob": glob_pattern},
        )
        return ToolResult(**response.json())

    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: Optional[str] = None,
    ) -> ToolResult:
        path = _translate_exec_dir(path)
        files = {"file": (filename or "upload", file_data, "application/octet-stream")}
        data = {"path": path}
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/upload",
            files=files,
            data=data,
        )
        return ToolResult(**response.json())

    async def file_download(self, path: str) -> BinaryIO:
        path = _translate_exec_dir(path)
        response = await self.client.get(
            f"{self.base_url}/api/v1/file/download",
            params={"path": path},
        )
        response.raise_for_status()
        return io.BytesIO(response.content)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def ip(self) -> str:
        return self.base_url

    @property
    def cdp_url(self) -> str:
        return self._cdp_url

    @property
    def vnc_url(self) -> str:
        return self._vnc_url

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls) -> "E2BSandbox":
        """
        Create a new E2B sandbox from the configured custom template.

        After creation, starts Chrome installation in the background so it
        is available by the time the agent first needs the browser tool.
        """
        settings = get_settings()
        api_key = settings.e2b_api_key
        template_id = settings.e2b_template_id
        ttl_minutes = settings.sandbox_ttl_minutes or 30
        timeout_seconds = ttl_minutes * 60

        logger.info(
            "Creating E2B sandbox: template=%s timeout=%ds",
            template_id, timeout_seconds,
        )
        e2b_sandbox = await asyncio.to_thread(
            E2BSandboxSDK.create,
            template=template_id,
            api_key=api_key,
            timeout=timeout_seconds,
        )
        return cls(e2b_sandbox)

    @classmethod
    async def get(cls, id: str) -> "E2BSandbox":
        """Reconnect to an existing E2B sandbox by ID."""
        settings = get_settings()
        api_key = settings.e2b_api_key
        logger.info("Connecting to existing E2B sandbox: %s", id)
        e2b_sandbox = await asyncio.to_thread(
            E2BSandboxSDK.connect,
            sandbox_id=id,
            api_key=api_key,
        )
        return cls(e2b_sandbox)
