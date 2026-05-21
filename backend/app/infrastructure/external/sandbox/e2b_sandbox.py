import asyncio
import os
import io
import logging
from typing import Optional, BinaryIO
import httpx
from e2b import Sandbox as E2BSandboxSDK
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
        Run a one-shot admin command in the sandbox shell and return stdout.

        The sandbox shell service starts an async output-reader coroutine via
        ``asyncio.create_task``.  Because the sandbox's event loop never yields
        between ``process.wait()`` completing and our follow-up ``view`` call,
        the output-reader has no chance to flush stdout before we read it back.

        Sleeping briefly between the ``wait`` and ``view`` calls gives the
        *sandbox's* event loop an idle window to run that output-reader task.
        """
        session = f"{_SYS_BASE_SESSION}_{os.urandom(4).hex()}"
        try:
            await self._exec_raw(session, _UBUNTU_HOME, cmd)
            await self._wait_raw(session, timeout)
            # Yield time to the sandbox event loop so its async output-reader
            # coroutine can flush the subprocess stdout pipe before we read it.
            await asyncio.sleep(2.0)
            view = await self._view_raw(session)
            data = view.data
            if data is None:
                return ""
            if isinstance(data, dict):
                # ShellViewResult.model_dump() → {"output":"…","session_id":"…","console":…}
                output = str(data.get("output", "") or "")
                # If still empty, the output-reader may have needed more time.
                if not output:
                    await asyncio.sleep(2.0)
                    view2 = await self._view_raw(session)
                    data2 = view2.data or {}
                    if isinstance(data2, dict):
                        output = str(data2.get("output", "") or "")
                return output
            return str(data or "")
        except Exception as exc:
            logger.warning("Admin cmd failed (%s): %s", cmd[:60], exc)
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
            "ls /usr/bin/chrom* /usr/bin/google-chrome* 2>&1; "
            "curl -sSf --connect-timeout 5 https://dl.google.com/robots.txt 2>&1 | head -1",
            timeout=20,
        )
        logger.info("Chrome fix diagnostic: %s", diag[:400] if diag else "(empty — shell exec broken!)")

        if not diag:
            logger.error(
                "Shell exec is not returning output — Chrome cannot be installed at runtime. "
                "Rebuild the e2b template (sandbox/e2b.Dockerfile) with Google Chrome pre-installed."
            )
            return

        # Check if a *real* Google Chrome binary exists (not the Ubuntu snap stub).
        # The snap stub at /usr/bin/chromium-browser is just a shell script that calls
        # snap, which doesn't work in containers.  We only skip install if the genuine
        # google-chrome binary is present.
        has_real_chrome = (
            "google-chrome" in diag
            and "No such file" not in diag
        )
        if has_real_chrome:
            logger.info("Google Chrome already installed — skipping download, just restarting…")
        else:
            # ── Step 1: Playwright (most reliable — no snap/apt issues) ───
            logger.info("Attempting Playwright Chromium install…")
            pw_out = await self._run_admin_cmd(
                "pip3 install --quiet playwright 2>&1 | tail -3 && "
                "python3 -m playwright install chromium 2>&1 | tail -5 && "
                "CHROME=$(find /root/.cache /home/ubuntu/.cache -name 'chrome' -type f 2>/dev/null | head -1); "
                "echo FOUND=$CHROME; "
                "[ -n \"$CHROME\" ] && sudo ln -sf \"$CHROME\" /usr/bin/chromium-browser && echo PLAYWRIGHT_OK",
                timeout=300,
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

        # ── Restart supervisord chrome service ────────────────────────────
        # Chrome is in [group:services] so supervisorctl needs "services:chrome"
        restart_out = await self._run_admin_cmd(
            "sudo supervisorctl -c /app/supervisord.conf start services:chrome 2>&1; "
            "sleep 2; "
            "sudo supervisorctl -c /app/supervisord.conf status services:chrome 2>&1",
            timeout=30,
        )
        logger.info("Chrome supervisor restart: %s", restart_out[:300] if restart_out else "(empty)")

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
        # Phase 1 — wait for core services (app, xvfb, socat, x11vnc, websockify)
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
        await self._run_admin_cmd(f"rm -rf '{path}'")
        return ToolResult(
            success=True,
            message=f"Deleted: {path}",
            data={"path": path},
        )

    async def file_list(self, path: str) -> ToolResult:
        """List directory contents via shell."""
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
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/search",
            json={"file": file, "regex": regex, "sudo": sudo},
        )
        return ToolResult(**response.json())

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
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
        files = {"file": (filename or "upload", file_data, "application/octet-stream")}
        data = {"path": path}
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/upload",
            files=files,
            data=data,
        )
        return ToolResult(**response.json())

    async def file_download(self, path: str) -> BinaryIO:
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
