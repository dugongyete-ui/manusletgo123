"""E2B cloud sandbox — per-user fully isolated execution environment.

Each Dzeck session backed by E2B gets its own Firecracker microVM:
its own filesystem, its own shell, its own Chromium instance (own cookies and
profile). Nothing is shared with other users, so cross-account leakage of
files, shell state, or browser sessions is impossible by construction.

Key engineering notes (all verified empirically against e2b SDK 2.x):

1. V8 renderer OOM fix — E2B microVMs ship with a small amount of RAM and the
   default kernel overcommit policy. V8's pointer-compression cage wants a
   4 GB *virtual* reservation; without overcommit the reservation fails and
   every Chromium renderer dies instantly:
       "V8 process OOM (Failed to reserve virtual memory for CodeRange)"
   The renderer being dead is why *browser-process* CDP commands
   (Browser.getVersion / Target.getTargets / Page.navigate) responded while
   every *renderer* command (Page.enable / Runtime.evaluate) hung forever.
   Fix: `sudo sysctl -w vm.overcommit_memory=1` on every (re)boot of the VM.

2. CDP over the public proxy — Chrome's DevTools HTTP handler rejects requests
   whose Host header is not localhost/an IP (DNS-rebinding protection), so the
   E2B edge proxy domain gets a 500. A tiny nginx site inside the VM rewrites
   Host to "localhost" and proxies to 127.0.0.1:9222. Chrome builds the
   webSocketDebuggerUrl from the Host header (ws://localhost/...), so we fetch
   /json/version through the proxy ourselves and re-bind the returned path to
   the public `wss://{port-host}` URL before handing it to playwright.

3. Pause/resume — a paused sandbox stops consuming compute quota. Empirically
   pause behaves like a freeze/thaw: disk AND the process tree (Chromium, Xvfb,
   x11vnc, websockify) survive. `ensure_sandbox()` is still an idempotent
   bootstrap that re-applies the sysctl, verifies every service and relaunches
   whatever is missing — so both freeze-style and kill-style pauses are safe.
   The task runner pauses the VM after the final summary (quota saver) and the
   next message auto-resumes via get() → AsyncSandbox.connect().

4. Live view / takeover — GUI Chromium renders into an Xvfb display; x11vnc
   shares that display and websockify bridges RFB to WebSocket on port 6080.
   `vnc_url` returns the E2B-proxied wss URL; the backend VNC websocket pipes
   it to the noVNC frontend, so the mouse-icon takeover works exactly like on
   Replit. Verified live at ~290/478 MB RAM with all services running.
   CRITICAL: the Xvfb screen must be depth 24. noVNC ALWAYS sends
   SetPixelFormat requesting a 24bpp truecolor client format, and x11vnc
   (Debian build) silently never answers framebuffer-update requests when it
   would have to convert from a 16bpp display to that client format — the
   viewer then shows a black screen forever (verified empirically; the
   handshake still succeeds, so probes pass while the screen stays black).
   Depth 24 makes the client format the native one and updates flow.
   `ensure_sandbox()` therefore also checks the root depth of a running Xvfb
   and replaces depth-16 servers left by older bootstraps.

5. Fallback contract — every public method may raise; the
   HybridSandboxFactory catches failures (quota/auth/network) and transparently
   falls back to the shared Replit sandbox so user tasks never crash.
"""

import asyncio
import io
import logging
import re
import time
from typing import Optional, BinaryIO

import httpx

from app.core.config import get_settings
from app.domain.external.browser import Browser
from app.domain.models.tool_result import ToolResult
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser

logger = logging.getLogger(__name__)

# Internal ports inside the E2B VM
_CHROME_DEBUG_PORT = 9222
_CDP_PROXY_PORT = 9223  # nginx Host-rewrite proxy → chrome
_VNC_RFB_PORT = 5900   # x11vnc RFB port (local only)
_VNC_WS_PORT = 6080    # websockify — VNC over WebSocket, exposed via E2B proxy
_X_DISPLAY = ":99"     # Xvfb virtual display for GUI Chromium + VNC

_SETUP_FLAG = "/home/user/.dzeck_env_ready"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\[()][0-9;]*")

_NGINX_CDP_CONF = """server {{
    listen {_port};
    location / {{
        proxy_pass http://127.0.0.1:{_chrome_port};
        proxy_set_header Host localhost;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""


class E2BSandbox:
    """Sandbox protocol implementation backed by one E2B microVM.

    `shared = False` marks this sandbox as already user-isolated so the domain
    service skips the UserScopedSandbox wrapper (which only makes sense around
    the shared Replit sandbox).
    """

    shared = False

    # Which execution provider this sandbox runs on — drives the provider-
    # conditional system prompt ("e2b" vs "replit") so the agent is always
    # told the truth about its environment (OS, user, paths, tools).
    provider = "e2b"

    # Cache wrappers by raw sandbox id so repeated get() calls reuse the same
    # shell-session bookkeeping within a backend process.
    _registry: dict[str, "E2BSandbox"] = {}
    _registry_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Live-view (takeover) viewer accounting.
    # While a user is watching the takeover screen the VM must NOT be
    # paused (pause freezes every process → the screen dies mid-view). The
    # VNC websocket route marks viewer connect/disconnect here; the task
    # runner skips its post-run pause while viewers are connected, and the
    # last viewer leaving schedules a delayed re-pause so quota is not
    # burned by an abandoned live view.
    # ------------------------------------------------------------------
    _vnc_viewers: dict[str, int] = {}   # raw sandbox id -> viewer count
    _ACTIVITY_WINDOW = 180.0            # every tool call keeps the VM "busy" this long
    _REPAUSE_POLL = 15.0                # idle-poll interval after the last viewer leaves
    _REPAUSE_GIVEUP = 900.0             # never poll longer than 15 minutes

    def __init__(self, sbx) -> None:
        self._sbx = sbx
        self._raw_id = sbx.sandbox_id
        self._id = f"e2b:{self._raw_id}"
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrapped = False
        self._activity_until = 0.0
        # session_id -> {handle, started_at}
        self._shell_sessions: dict[str, dict] = {}
        # Manus-style per-session console history (ps1/command/output), mirroring
        # the Replit sandbox API so shell_view renders identically on both
        # providers (the UI tool panel and the aux /sessions/{id}/shell endpoint
        # both read these records).
        self._shell_consoles: dict[str, list[dict]] = {}
        # Accumulated (ANSI-clean) output across every command of a session —
        # view_shell's `output` field, like the Replit shell transcript.
        self._shell_outputs: dict[str, str] = {}
        self._http = httpx.AsyncClient(timeout=30)

    def _console_record(self, session_id: str, command: str, cwd: str) -> dict:
        """Append a fresh console record for a command; returns the record."""
        records = self._shell_consoles.setdefault(session_id, [])
        record = {"ps1": f"user@e2b:{cwd} $", "command": command, "output": ""}
        records.append(record)
        return record

    def _accumulate_output(self, session_id: str, output: str) -> str:
        """Append command output to the session transcript and return it."""
        total = (self._shell_outputs.get(session_id, "") + output).lstrip("\n")
        self._shell_outputs[session_id] = total
        return total

    # ------------------------------------------------------------------
    # Live-view viewer hooks (called by the VNC websocket route)
    # ------------------------------------------------------------------

    def has_vnc_viewers(self) -> bool:
        """True while at least one takeover viewer is connected."""
        return E2BSandbox._vnc_viewers.get(self._raw_id, 0) > 0

    def vnc_viewer_connected(self) -> None:
        E2BSandbox._vnc_viewers[self._raw_id] = (
            E2BSandbox._vnc_viewers.get(self._raw_id, 0) + 1
        )
        logger.info(
            "E2B live view: viewer connected to %s (total %d)",
            self.id,
            E2BSandbox._vnc_viewers[self._raw_id],
        )

    async def vnc_viewer_disconnected(self) -> None:
        remaining = E2BSandbox._vnc_viewers.get(self._raw_id, 0) - 1
        if remaining > 0:
            E2BSandbox._vnc_viewers[self._raw_id] = remaining
            logger.info(
                "E2B live view: viewer left %s (%d remain)", self.id, remaining
            )
            return
        E2BSandbox._vnc_viewers.pop(self._raw_id, None)
        logger.info(
            "E2B live view: last viewer left %s — re-pause scheduled", self.id
        )
        asyncio.create_task(E2BSandbox._repause_when_idle(self._raw_id))

    @classmethod
    async def _repause_when_idle(cls, raw_id: str) -> None:
        """Pause the VM shortly after the last live-view viewer leaves.

        Waits until agent activity ceases (every tool call refreshes
        ``_activity_until``) so a running task is never frozen mid-flight —
        its own post-run pause handles the final state. Gives up after 15
        minutes so a stuck task can never pin this loop forever.
        """
        deadline = time.monotonic() + cls._REPAUSE_GIVEUP
        while time.monotonic() < deadline:
            await asyncio.sleep(cls._REPAUSE_POLL)
            if cls._vnc_viewers.get(raw_id, 0) > 0:
                return  # a viewer came back
            wrapper = cls._registry.get(raw_id)
            if wrapper is None:
                return  # already paused / removed
            if time.monotonic() >= wrapper._activity_until:
                await wrapper.pause()
                logger.info(
                    "E2B live view: sandbox e2b:%s re-paused after viewer left",
                    raw_id,
                )
                return

    # ------------------------------------------------------------------
    # Factory / lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _api_key(cls) -> Optional[str]:
        return get_settings().e2b_api_key

    @classmethod
    async def create(cls) -> "E2BSandbox":
        from e2b import AsyncSandbox

        settings = get_settings()
        timeout = max(60, int(settings.e2b_sandbox_timeout or 3600))
        sbx = await AsyncSandbox.create(
            api_key=cls._api_key(), timeout=timeout
        )
        wrapper = cls(sbx)
        cls._registry[sbx.sandbox_id] = wrapper
        logger.info("E2BSandbox created: %s", wrapper.id)
        await wrapper.ensure_sandbox()
        return wrapper

    # E2B control-plane calls (connect/resume, pause, set_timeout) have been
    # observed to hang indefinitely when the platform is slow — connect while
    # holding the class-wide registry lock once DEADLOCKED the whole agent
    # (every other sandbox operation blocked on the lock forever). All three
    # calls are therefore bounded with asyncio.wait_for.
    _CONNECT_TIMEOUT = 90
    _PAUSE_TIMEOUT = 30
    _SET_TIMEOUT_CALL = 15

    @classmethod
    async def get(cls, id: str) -> "E2BSandbox":
        """Reconnect to an existing (possibly paused) E2B sandbox by id.

        `id` may carry the "e2b:" prefix used in session.sandbox_id. Raises on
        failure — the caller (HybridSandboxFactory) falls back gracefully.
        """
        from e2b import AsyncSandbox

        raw = id.removeprefix("e2b:")
        async with cls._registry_lock:
            cached = cls._registry.get(raw)
            if cached is not None:
                return cached
        # Connect OUTSIDE the registry lock (double-checked below):
        # AsyncSandbox.connect auto-resumes a paused microVM and can hang on
        # the E2B control plane — holding the class lock during that hang
        # stalled every other sandbox operation (total agent deadlock).
        try:
            sbx = await asyncio.wait_for(
                AsyncSandbox.connect(raw, api_key=cls._api_key()),
                timeout=cls._CONNECT_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"E2B connect to {raw} timed out after {cls._CONNECT_TIMEOUT}s"
            ) from exc
        async with cls._registry_lock:
            cached = cls._registry.get(raw)
            if cached is not None:
                # Another coroutine won the race — drop our duplicate client
                # handle (harmless: it is an API client, not the VM itself).
                return cached
            wrapper = cls(sbx)
            cls._registry[raw] = wrapper
        logger.info("E2BSandbox reconnected: %s", wrapper.id)
        await wrapper.ensure_sandbox()
        return wrapper

    async def destroy(self) -> bool:
        try:
            await self._sbx.kill()
        except Exception as exc:
            logger.warning("E2BSandbox.destroy(%s) failed: %s", self.id, exc)
        self._registry.pop(self._raw_id, None)
        return True

    async def pause(self) -> bool:
        """Pause the microVM so it stops consuming E2B compute quota.

        Empirically (verified live): pause acts like a freeze/thaw — the full
        process tree (Chromium, Xvfb, x11vnc, websockify) and every file on
        disk survive. The next E2BSandbox.get() reconnects, which auto-resumes
        the VM in a few seconds. The wrapper is dropped from the registry so
        the reconnect builds a fresh one instead of touching a stale handle.
        """
        try:
            await asyncio.wait_for(self._sbx.pause(), timeout=self._PAUSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("E2BSandbox.pause(%s) timed out after %ss", self.id, self._PAUSE_TIMEOUT)
            return False
        except Exception as exc:
            logger.warning("E2BSandbox.pause(%s) failed: %s", self.id, exc)
            return False
        self._registry.pop(self._raw_id, None)
        self._bootstrapped = False
        logger.info("E2BSandbox paused (quota saver): %s", self.id)
        return True

    # ------------------------------------------------------------------
    # Idempotent bootstrap (safe after every pause/resume)
    # ------------------------------------------------------------------

    async def ensure_sandbox(self) -> None:
        # Heartbeat: while the agent actively uses tools the VM counts as busy,
        # so the post-viewer re-pause never freezes a task mid-flight.
        self._activity_until = time.monotonic() + self._ACTIVITY_WINDOW
        async with self._bootstrap_lock:
            if self._bootstrapped:
                # keepalive only — cheap
                try:
                    await asyncio.wait_for(
                        self._sbx.set_timeout(
                            max(60, int(get_settings().e2b_sandbox_timeout or 3600))
                        ),
                        timeout=self._SET_TIMEOUT_CALL,
                    )
                except Exception:
                    pass
                return
            try:
                await self._bootstrap()
                self._bootstrapped = True
            except Exception as exc:
                raise RuntimeError(f"E2B sandbox bootstrap failed: {exc}") from exc

    async def _cmd(self, command: str, timeout: float = 60) -> str:
        """Run a quick command, returning stdout (empty string on failure)."""
        try:
            result = await self._sbx.commands.run(command, timeout=timeout)
            return result.stdout or ""
        except Exception as exc:
            logger.debug("E2B cmd failed (%s): %s", command[:60], exc)
            return ""

    async def _bootstrap(self) -> None:
        settings = get_settings()
        try:
            await asyncio.wait_for(
                self._sbx.set_timeout(
                    max(60, int(settings.e2b_sandbox_timeout or 3600))
                ),
                timeout=self._SET_TIMEOUT_CALL,
            )
        except Exception:
            pass

        # 1. THE V8 fix — kernel state resets on resume, apply every time.
        await self._cmd("sudo sysctl -w vm.overcommit_memory=1")
        await self._cmd("sudo sysctl -w vm.max_map_count=1048576")

        # 2. One-time package install (survives pause via disk flag).
        flag = await self._cmd(f"test -f {_SETUP_FLAG} && echo YES || echo NO")
        if "YES" not in flag:
            logger.info(
                "E2B: installing chromium + nginx + VNC stack (first boot of %s)…",
                self.id,
            )
            install = await self._cmd(
                "sudo apt-get update -qq && sudo apt-get install -y -qq "
                "chromium nginx-light zip unzip xvfb x11vnc websockify "
                ">/dev/null 2>&1; echo OK",
                timeout=420,
            )
            if "OK" not in install:
                raise RuntimeError("apt install chromium/nginx/vnc failed")
            await self._cmd(f"echo ready > {_SETUP_FLAG}")

        # 3. Xvfb virtual display up AND at depth 24? (GUI Chromium renders
        #    into it and the VNC server shares it — one display serves both CDP
        #    tools and the live-view / takeover screen). Guard with `pgrep -x`
        #    so the check never matches its own sh -c wrapper.
        #    Depth MUST be 24: noVNC always requests a 24bpp client pixel
        #    format and x11vnc silently drops framebuffer updates when it
        #    would have to convert from a 16bpp display — black takeover
        #    screen. See module docstring note 4.
        depth = (
            await self._cmd(
                f"DISPLAY={_X_DISPLAY} xdpyinfo 2>/dev/null "
                "| grep -m1 'depth of root window' | grep -o '[0-9]*'"
            )
        ).strip()
        xvfb_up = await self._cmd("pgrep -x Xvfb >/dev/null && echo UP || echo DOWN")
        if "UP" not in xvfb_up or depth != "24":
            if "UP" in xvfb_up:
                logger.info(
                    "E2B: replacing depth-%s Xvfb with depth-24 server (%s)",
                    depth or "?",
                    self.id,
                )
            # Killing X also kills chromium + x11vnc (they exit when the
            # display dies); the checks below relaunch them on the fresh
            # display. `; true` keeps pkill's exit code from failing the cmd.
            await self._cmd(
                "pkill -x Xvfb; pkill -x x11vnc; pkill -x chromium; true"
            )
            await asyncio.sleep(1)
            await self._cmd(
                f"nohup Xvfb {_X_DISPLAY} -screen 0 1024x768x24 -nolisten tcp "
                ">/tmp/xvfb.log 2>&1 & echo LAUNCHED"
            )
            await asyncio.sleep(1)

        # 4. Chromium up? (relaunch when needed — processes may not survive
        #    every pause edge case). GUI mode on the Xvfb display: the SAME
        #    instance serves the agent's CDP tools, browser_view screenshots
        #    AND the user's VNC takeover — verified live, RAM ≈ 290/478 MB.
        chrome_up = await self._cmd(
            f"curl -sf --max-time 3 http://127.0.0.1:{_CHROME_DEBUG_PORT}/json/version >/dev/null && echo UP || echo DOWN"
        )
        if "UP" not in chrome_up:
            await self._launch_chromium()

        # 5. VNC server + WebSocket bridge up? (live view / user takeover)
        x11vnc_up = await self._cmd("pgrep -x x11vnc >/dev/null && echo UP || echo DOWN")
        if "UP" not in x11vnc_up:
            await self._cmd(
                f"nohup x11vnc -display {_X_DISPLAY} -rfbport {_VNC_RFB_PORT} "
                "-nopw -shared -forever -quiet >/tmp/x11vnc.log 2>&1 & echo LAUNCHED"
            )
            await asyncio.sleep(1)
        ws_up = await self._cmd(
            f"ss -ltn | grep -q ':{_VNC_WS_PORT} ' && echo UP || echo DOWN"
        )
        if "UP" not in ws_up:
            await self._cmd(
                f"nohup websockify {_VNC_WS_PORT} localhost:{_VNC_RFB_PORT} "
                ">/tmp/websockify.log 2>&1 & echo LAUNCHED"
            )
            await asyncio.sleep(1)

        # 6. nginx Host-rewrite proxy up?
        proxy_up = await self._cmd(
            f"curl -sf --max-time 3 http://127.0.0.1:{_CDP_PROXY_PORT}/json/version >/dev/null && echo UP || echo DOWN"
        )
        if "UP" not in proxy_up:
            conf = _NGINX_CDP_CONF.format(
                _port=_CDP_PROXY_PORT, _chrome_port=_CHROME_DEBUG_PORT
            )
            await self._sbx.files.write("/tmp/cdp_proxy.conf", conf)
            await self._cmd(
                "sudo mv /tmp/cdp_proxy.conf /etc/nginx/sites-enabled/cdp_proxy "
                "&& sudo nginx -t >/dev/null 2>&1 "
                "&& (sudo nginx 2>/dev/null || sudo service nginx reload) && sleep 1; echo NGINX"
            )
            for _ in range(10):
                up = await self._cmd(
                    f"curl -sf --max-time 2 http://127.0.0.1:{_CDP_PROXY_PORT}/json/version >/dev/null && echo UP || echo DOWN"
                )
                if "UP" in up:
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("nginx CDP proxy did not come up inside E2B VM")

        # 7. Working dirs for the agent.
        await self._cmd("mkdir -p /home/user/upload && chmod 700 /home/user")

        logger.info("E2B sandbox ready: %s", self.id)

    async def _launch_chromium(self) -> None:
        """Relaunch Chromium inside the VM and wait (bounded) for its CDP."""
        await self._cmd(
            # --restore-last-session: after a pause/resume cycle chromium
            # reopens the tabs the agent was working on, so the takeover
            # view shows the real pages instead of about:blank.
            "rm -f /home/user/chrome-profile/SingletonLock "
            "/home/user/chrome-profile/SingletonCookie "
            "/home/user/chrome-profile/SingletonSocket; "
            f"env DISPLAY={_X_DISPLAY} nohup chromium --no-sandbox --disable-gpu "
            "--disable-dev-shm-usage --renderer-process-limit=2 "
            # BackForwardCache keeps a frozen renderer per navigation alive in
            # RAM — on a ~0.5 GB microVM that thrashes kswapd and stalls every
            # CDP call. Disabling it trades a little back/forward speed for
            # stable latency.
            "--disable-features=BackForwardCache "
            "--window-size=1024,768 --restore-last-session "
            f"--remote-debugging-port={_CHROME_DEBUG_PORT} "
            "--remote-debugging-address=127.0.0.1 --remote-allow-origins=* "
            "--user-data-dir=/home/user/chrome-profile "
            ">/tmp/chrome.log 2>&1 & echo LAUNCHED"
        )
        # wait for CDP to answer (bounded)
        for _ in range(20):
            up = await self._cmd(
                f"curl -sf --max-time 2 http://127.0.0.1:{_CHROME_DEBUG_PORT}/json/version >/dev/null && echo UP || echo DOWN"
            )
            if "UP" in up:
                return
            await asyncio.sleep(1)
        raise RuntimeError("Chromium CDP did not come up inside E2B VM")

    async def _heal_chrome(self) -> None:
        """Mid-task browser heal: detect a dead in-VM Chromium and relaunch it.

        Passed as the ``heal_hook`` to BrowserUseBrowser — when the CDP proxy
        answers 502 (proxy alive, browser dead), the browser layer calls this
        so a crashed Chromium self-heals instead of failing the whole task.
        Raises when the relaunch does not come up, which the caller treats as
        one more failed retry (it keeps its own retry budget).
        """
        chrome_up = await self._cmd(
            f"curl -sf --max-time 3 http://127.0.0.1:{_CHROME_DEBUG_PORT}/json/version >/dev/null && echo UP || echo DOWN"
        )
        if "UP" in chrome_up:
            return  # transient proxy hiccup — nothing to heal
        logger.warning("E2B chromium is DOWN mid-task — relaunching (browser heal)")
        await self._launch_chromium()
        logger.info("E2B chromium heal: CDP is UP again")

    # ------------------------------------------------------------------
    # Browser (CDP over public wss proxy)
    # ------------------------------------------------------------------

    async def _cdp_ws_url(self) -> str:
        host = self._sbx.get_host(_CDP_PROXY_PORT)
        resp = await self._http.get(f"https://{host}/json/version", timeout=20)
        resp.raise_for_status()
        ver = resp.json()
        ws_path = ver["webSocketDebuggerUrl"].split("/devtools", 1)[1]
        return f"wss://{host}/devtools{ws_path}"

    async def get_browser(self) -> Browser:
        settings = get_settings()
        engine = (settings.browser_engine or "browser_use").lower().strip()
        url = await self._cdp_ws_url()
        if engine == "browser_use":
            logger.info("E2B: BrowserUseBrowser via CDP proxy (%s)", self.id)
            return BrowserUseBrowser(url, heal_hook=self._heal_chrome)
        logger.info("E2B: PlaywrightBrowser via CDP proxy (%s)", self.id)
        return PlaywrightBrowser(url)

    # ------------------------------------------------------------------
    # Shell sessions (mirror the Replit sandbox HTTP API semantics)
    # ------------------------------------------------------------------

    def _ansi_clean(self, text: str) -> str:
        return _ANSI_RE.sub("", text or "")

    def _waiter_outcome(self, waiter) -> tuple:
        """Return (result, exc) for a DONE waiter task; (None, None) if cancelled.

        The e2b SDK poisons handle.wait() once its internal stream iteration is
        cancelled (it re-raises the stored CancelledError — a BaseException, so
        `except Exception` never catches it). To stay safe we never cancel the
        waiter: exec/wait poll it with asyncio.wait() instead of wait_for().
        """
        if waiter is None or waiter.cancelled():
            return None, None
        exc = waiter.exception()
        if exc is not None:
            return None, exc
        return waiter.result(), None

    def _completed_result(
        self,
        session_id: str,
        record: dict,
        result=None,
        exc: Exception | None = None,
        accumulate: bool = True,
    ) -> ToolResult:
        """Build the completed ToolResult from a finished command, updating the
        session console record and transcript exactly once."""
        if exc is not None:
            # CommandExitException (non-zero exit) or any SDK failure that
            # still carries captured stdout/stderr.
            exit_code = getattr(exc, "exit_code", None)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or ""
            if exit_code is None:
                exit_code = 1
        else:
            exit_code = getattr(result, "exit_code", 0) or 0
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
        output = self._ansi_clean(stdout + (("\n" + stderr) if stderr else ""))
        record["output"] = output
        total = self._accumulate_output(session_id, output) if accumulate else self._shell_outputs.get(session_id, "")
        return ToolResult(
            success=True,
            message="Command execution completed",
            data={
                "session_id": session_id,
                "status": "completed",
                "returncode": exit_code,
                "output": total,
            },
        )

    async def exec_command(
        self,
        session_id: str,
        exec_dir: str,
        command: str,
    ) -> ToolResult:
        await self.ensure_sandbox()
        cwd = exec_dir or "/home/user"
        # Console record is appended BEFORE running so even long-running
        # commands show up in shell_view with an empty output that fills in.
        record = self._console_record(session_id, command, cwd)
        try:
            # kill any previous process on this session (Replit semantics:
            # re-exec on the same id replaces the process; console history
            # is preserved, exactly like the Replit sandbox service)
            old = self._shell_sessions.pop(session_id, None)
            if old and old.get("handle") is not None:
                try:
                    await old["handle"].kill()
                except Exception:
                    pass
            # stdin=True keeps a stdin pipe open on the process — required for
            # write_to_process (interactive commands), matching the Replit
            # sandbox that always spawns processes with stdin=PIPE.
            handle = await self._sbx.commands.run(
                command, background=True, cwd=cwd, stdin=True
            )
        except Exception as exc:
            # cwd may not exist (agent guessed a path) — retry in home
            try:
                cwd = "/home/user"
                handle = await self._sbx.commands.run(
                    command, background=True, cwd=cwd, stdin=True
                )
            except Exception as exc2:
                return ToolResult(
                    success=False,
                    message=f"Command execution failed: {exc2 or exc}",
                    data={"session_id": session_id, "status": "failed"},
                )
        # ONE persistent waiter task per exec — polled (never cancelled) by
        # exec_command's 5s window and by later shell_wait calls. Cancelling
        # wait() mid-stream permanently poisons the SDK handle.
        waiter = asyncio.ensure_future(handle.wait())
        self._shell_sessions[session_id] = {
            "handle": handle,
            "waiter": waiter,
            "consumed": False,
        }

        # Give quick commands up to 5s to finish (mirrors the Replit API that
        # waits ~5s and returns completed output directly).
        done, _ = await asyncio.wait({waiter}, timeout=5)
        if done:
            self._shell_sessions[session_id]["consumed"] = True
            result, exc = self._waiter_outcome(waiter)
            return self._completed_result(session_id, record, result, exc)
        partial = self._ansi_clean(handle.stdout or "")
        record["output"] = partial
        total = self._accumulate_output(session_id, partial)
        return ToolResult(
            success=True,
            message="Command started",
            data={
                "session_id": session_id,
                "status": "running",
                "returncode": None,
                "output": total,
            },
        )

    def _session(self, session_id: str):
        entry = self._shell_sessions.get(session_id)
        return (entry or {}).get("handle")

    async def view_shell(self, session_id: str, console: bool = False) -> ToolResult:
        """Session transcript + console records.

        Response data mirrors the Replit sandbox /shell/view shape exactly
        ({output, session_id, console}) — the aux endpoint
        POST /sessions/{id}/shell builds ShellViewResponse(output, session_id,
        console) from it and the task runner reads data['console'] to fill
        ShellToolContent for the UI tool panel. Missing keys there are what
        made shell tool views render BLANK on E2B.
        """
        entry = self._shell_sessions.get(session_id)
        if entry is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={
                    "status": "not_found",
                    "output": "",
                    "session_id": session_id,
                    "console": [],
                },
            )
        handle = entry.get("handle")
        try:
            stdout = handle.stdout or ""
            stderr = handle.stderr or ""
        except Exception:
            stdout = stderr = ""
        output = self._ansi_clean(
            stdout + (("\n" + stderr) if stderr else "")
        )
        records = self._shell_consoles.get(session_id, [])
        if output and records:
            # Live-refresh the newest record so view catches output that
            # arrived after the exec call returned (same as Replit's
            # get_console_records which appends streamed output).
            if handle.exit_code is None or not records[-1]["output"]:
                records[-1]["output"] = output
        total = self._shell_outputs.get(session_id, "")
        # Session transcript = accumulated history; fall back to live output.
        if not total:
            total = output
        return ToolResult(
            success=True,
            message="Shell session output",
            data={
                "status": "completed",
                "output": total,
                "session_id": session_id,
                "console": list(records) if console else [],
            },
        )

    async def wait_for_process(
        self, session_id: str, seconds: Optional[int] = None
    ) -> ToolResult:
        entry = self._shell_sessions.get(session_id)
        if entry is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found", "returncode": None, "output": None},
            )
        wait_secs = min(max(seconds or 60, 1), 600)
        records = self._shell_consoles.get(session_id, [])
        record = records[-1] if records else {}
        waiter = entry.get("waiter")
        handle = entry.get("handle")

        if waiter is not None and waiter.done():
            # Already finished — consume it. Accumulate into the transcript
            # ONLY if nobody consumed this waiter before (exec_command's 5s
            # window already accumulated its own completion; re-accumulating
            # would duplicate the output).
            was_consumed = entry.get("consumed", False)
            entry["consumed"] = True
            result, exc = self._waiter_outcome(waiter)
            return self._completed_result(
                session_id, record, result, exc, accumulate=not was_consumed
            )

        if waiter is None:
            # Legacy/no waiter — best effort from live handle output.
            output = self._ansi_clean(getattr(handle, "stdout", "") or "")
            return ToolResult(
                success=True,
                message="Process completed",
                data={
                    "session_id": session_id,
                    "status": "completed",
                    "returncode": getattr(handle, "exit_code", None) or 0,
                    "output": output or self._shell_outputs.get(session_id, ""),
                },
            )

        done, _ = await asyncio.wait({waiter}, timeout=wait_secs)
        if done:
            # Mark consumed BEFORE building the result so the accumulation
            # happens exactly once for this command.
            entry["consumed"] = True
            result, exc = self._waiter_outcome(waiter)
            return self._completed_result(session_id, record, result, exc)

        # Still running after the wait window.
        output = self._ansi_clean(handle.stdout or "")
        if records and output:
            records[-1]["output"] = output
        return ToolResult(
            success=True,
            message="Process still running",
            data={
                "session_id": session_id,
                "status": "running",
                "returncode": None,
                "output": output,
            },
        )

    async def write_to_process(
        self, session_id: str, input_text: str, press_enter: bool = True
    ) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"status": "not_found"},
            )
        data = input_text + ("\n" if press_enter else "")
        try:
            await handle.send_stdin(data)
        except Exception as exc:
            return ToolResult(
                success=False,
                message=f"Failed to write to process: {exc}",
                data={"status": "failed"},
            )
        return ToolResult(
            success=True,
            message="Input written",
            data={"session_id": session_id, "status": "completed"},
        )

    async def kill_process(self, session_id: str) -> ToolResult:
        handle = self._session(session_id)
        if handle is None:
            return ToolResult(
                success=False,
                message=f"No active shell session: {session_id}",
                data={"session_id": session_id, "status": "not_found"},
            )
        try:
            await handle.kill()
        except Exception:
            pass
        self._shell_sessions.pop(session_id, None)
        return ToolResult(
            success=True,
            message="Process terminated",
            data={"session_id": session_id, "status": "completed"},
        )

    # ------------------------------------------------------------------
    # File operations (E2B envd filesystem API + shell fallbacks)
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(path: str) -> str:
        path = (path or "").strip()
        if not path.startswith("/"):
            path = f"/home/user/{path}"
        # collapse .. and .
        parts = []
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/" + "/".join(parts)

    async def file_write(
        self,
        file: str,
        content: str,
        append: bool = False,
        leading_newline: bool = False,
        trailing_newline: bool = False,
        sudo: Optional[bool] = False,
    ) -> ToolResult:
        path = self._norm(file)
        if leading_newline:
            content = "\n" + content
        if trailing_newline:
            content = content + "\n"
        try:
            if append and content:
                # append via shell to avoid reading big files into memory
                esc = content.replace("'", "'\\''")
                out = await self._cmd(
                    f"mkdir -p \"$(dirname '{path}')\" && printf '%s' '{esc}' >> '{path}' && echo WROTE",
                    timeout=30,
                )
                if "WROTE" not in out:
                    raise RuntimeError("append failed")
            else:
                parent = "/".join(path.split("/")[:-1]) or "/"
                try:
                    await self._sbx.files.make_dir(parent)
                except Exception:
                    pass
                await self._sbx.files.write(path, content)
            return ToolResult(
                success=True,
                message=f"File written: {path}",
                # Same keys as the Replit FileWriteResult model.
                data={"file": path, "bytes_written": len(content.encode("utf-8"))},
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to write {path}: {exc}"
            )

    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: bool = False,
    ) -> ToolResult:
        path = self._norm(file)
        try:
            content = await self._sbx.files.read(path, format="text")
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to read {path}: {exc}"
            )
        if content is None:
            content = ""
        lines = content.splitlines()
        if start_line is not None or end_line is not None:
            start = start_line or 0
            end = end_line if end_line is not None else len(lines)
            content = "\n".join(lines[start:end])
        if len(content) > 10000:
            content = content[:10000] + "(truncated)"
        # `file` key is REQUIRED: the aux endpoint POST /sessions/{id}/file
        # builds FileViewResponse(content, file) from this data — missing key
        # made file tool views 500 / render blank on E2B.
        return ToolResult(
            success=True,
            message="File read successfully",
            data={"content": content, "file": path},
        )

    async def file_exists(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            exists = await self._sbx.files.exists(p)
        except Exception:
            exists = "YES" in await self._cmd(f"test -e '{p}' && echo YES || echo NO")
        return ToolResult(
            success=True,
            message="File exists check completed",
            data={"exists": bool(exists)},
        )

    async def file_delete(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            await self._sbx.files.remove(p)
            return ToolResult(success=True, message=f"Deleted: {p}")
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to delete {p}: {exc}")

    async def file_move(self, source: str, destination: str) -> ToolResult:
        src, dst = self._norm(source), self._norm(destination)
        try:
            await self._sbx.files.rename(src, dst)
            return ToolResult(
                success=True, message=f"Moved: {src} → {dst}"
            )
        except Exception:
            out = await self._cmd(
                f"mkdir -p \"$(dirname '{dst}')\" && mv '{src}' '{dst}' && echo OK",
                timeout=30,
            )
            if "OK" in out:
                return ToolResult(success=True, message=f"Moved: {src} → {dst}")
            return ToolResult(
                success=False, message=f"Failed to move {src} → {dst}"
            )

    async def file_copy(self, source: str, destination: str) -> ToolResult:
        src, dst = self._norm(source), self._norm(destination)
        out = await self._cmd(
            f"mkdir -p \"$(dirname '{dst}')\" && cp -r '{src}' '{dst}' && echo OK",
            timeout=60,
        )
        if "OK" in out:
            return ToolResult(success=True, message=f"Copied: {src} → {dst}")
        return ToolResult(success=False, message=f"Failed to copy {src} → {dst}")

    async def file_list(self, path: str) -> ToolResult:
        p = self._norm(path)
        try:
            entries = await self._sbx.files.list(p)
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to list directory {p}: {exc}"
            )
        norm_entries = []
        for e in entries or []:
            name = getattr(e, "name", None) or ""
            etype = getattr(e, "type", None)
            type_str = "dir" if str(etype).upper().endswith("DIRECTORY") or str(etype).upper() == "DIR" else "file"
            size = getattr(e, "size", None) or 0
            norm_entries.append(
                {"name": name, "type": type_str, "size": int(size or 0)}
            )
        listing = "\n".join(
            f"{e['type']:4s} {str(e['size']):>10s}  {e['name']}" for e in norm_entries
        )
        return ToolResult(
            success=True,
            message=f"Directory listed: {len(norm_entries)} entry(ies)",
            data={"listing": listing, "entries": norm_entries},
        )

    async def file_replace(
        self, file: str, old_str: str, new_str: str, sudo: bool = False
    ) -> ToolResult:
        read = await self.file_read(file)
        if not read.success or not isinstance(read.data, dict):
            return ToolResult(
                success=False,
                message=f"Failed to read {file} for replacement",
            )
        content = read.data.get("content", "")
        if old_str not in content:
            return ToolResult(
                success=False,
                message=f"String not found in {file}",
            )
        new_content = content.replace(old_str, new_str)
        write = await self.file_write(file, new_content)
        if not write.success:
            return write
        path = self._norm(file)
        return ToolResult(
            success=True,
            message=f"Replaced {content.count(old_str)} occurrence(s) in {file}",
            # Same keys as the Replit FileReplaceResult model.
            data={"file": path, "replaced_count": content.count(old_str)},
        )

    async def file_search(
        self, file: str, regex: str, sudo: bool = False
    ) -> ToolResult:
        path = self._norm(file)
        esc_regex = regex.replace("'", "'\\''")
        out = await self._cmd(
            f"grep -nE '{esc_regex}' '{path}' | head -50; true", timeout=30
        )
        # Parse grep -n output into the same shape as the Replit
        # FileSearchResult model: matches (content lines) + line_numbers.
        matches: list[str] = []
        line_numbers: list[int] = []
        for line in (out or "").splitlines():
            if ":" in line:
                lineno_str, _, text = line.partition(":")
                try:
                    line_numbers.append(int(lineno_str))
                    matches.append(text)
                    continue
                except ValueError:
                    pass
            if line.strip():
                matches.append(line)
        return ToolResult(
            success=True,
            message="Search completed",
            data={
                "file": path,
                "matches": matches or [],
                "line_numbers": line_numbers,
            },
        )

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        p = self._norm(path)
        esc_glob = glob_pattern.replace("'", "'\\''")
        out = await self._cmd(
            f"find '{p}' -maxdepth 4 -name '{esc_glob}' 2>/dev/null | head -100; true",
            timeout=30,
        )
        files = [line for line in (out or "").splitlines() if line.strip()]
        return ToolResult(
            success=True,
            message=f"Found {len(files)} file(s)",
            # Same keys as the Replit FileFindResult model.
            data={"path": p, "files": files},
        )

    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: Optional[str] = None,
    ) -> ToolResult:
        p = self._norm(path)
        if not p.endswith("/") and filename:
            # path is a directory → join filename
            if "YES" in await self._cmd(f"test -d '{p}' && echo YES || echo NO"):
                p = f"{p}/{filename}"
        # Accept both file-like objects (BinaryIO) and raw bytes —
        # image_download passes bytes directly, which previously crashed with
        # "'bytes' object has no attribute 'read'".
        data = file_data.read() if hasattr(file_data, "read") else file_data
        try:
            parent = "/".join(p.split("/")[:-1]) or "/"
            try:
                await self._sbx.files.make_dir(parent)
            except Exception:
                pass
            await self._sbx.files.write(p, data)
            return ToolResult(
                success=True,
                message=f"Uploaded: {p}",
                # Same keys as the Replit FileUploadResult model.
                data={"file_path": p, "file_size": len(data), "success": True},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Upload failed: {exc}")

    async def file_download(self, path: str) -> BinaryIO:
        p = self._norm(path)
        data = await self._sbx.files.read(p, format="bytes")
        return io.BytesIO(data)

    # ------------------------------------------------------------------
    # UserScopedSandbox compatibility (own VM → own home)
    # ------------------------------------------------------------------

    async def setup_user_home(self) -> None:
        await self._cmd("mkdir -p /home/user/upload")

    @property
    def user_home(self) -> str:
        return "/home/user"

    @property
    def upload_dir(self) -> str:
        return "/home/user/upload"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def cdp_url(self) -> str:
        try:
            host = self._sbx.get_host(_CDP_PROXY_PORT)
            return f"wss://{host}"
        except Exception:
            return ""

    @property
    def vnc_url(self) -> str:
        """VNC-over-WebSocket URL for the live view / user takeover screen.

        The VM runs x11vnc (sharing the Xvfb display that GUI Chromium renders
        into) bridged to WebSocket by websockify on _VNC_WS_PORT. The backend
        /sessions/{id}/vnc endpoint connects to this wss URL through the E2B
        public proxy and pipes RFB bytes to the noVNC frontend. Verified live:
        RFB 003.008 handshake + framebuffer survive pause/resume.
        """
        try:
            host = self._sbx.get_host(_VNC_WS_PORT)
            return f"wss://{host}"
        except Exception:
            return ""
