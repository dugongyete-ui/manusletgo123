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
        """Run a one-shot admin command and return stdout output."""
        session = f"{_SYS_BASE_SESSION}_{os.urandom(4).hex()}"
        try:
            await self._exec_raw(session, _UBUNTU_HOME, cmd)
            await self._wait_raw(session, timeout)
            view = await self._view_raw(session)
            return str(view.data or "")
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
        Install Google Chrome and fix the chromium-browser snap stub.

        Ubuntu 22.04 ships chromium-browser as a snap stub that fails in
        containers. This method downloads google-chrome-stable and creates
        a symlink so supervisord's chrome program finds a working binary,
        then restarts the chrome service.
        """
        logger.info("Chrome is not running — installing Google Chrome...")
        install_script = (
            "curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb "
            "-o /tmp/chrome.deb && "
            "sudo dpkg -i /tmp/chrome.deb 2>/dev/null; "
            "sudo apt-get install -f -y 2>/dev/null || true; "
            "sudo ln -sf /usr/bin/google-chrome /usr/bin/chromium-browser 2>/dev/null || true; "
            "sudo supervisorctl -c /tmp/supervisord.conf start chrome 2>/dev/null || "
            "sudo supervisorctl -c /etc/supervisor/conf.d/supervisord.conf start chrome 2>/dev/null || true"
        )
        output = await self._run_admin_cmd(install_script, timeout=120)
        logger.info("Chrome install output: %s", output[:300] if output else "(empty)")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_sandbox(self) -> None:
        """
        Wait for the sandbox services to become RUNNING.

        Non-Chrome services (app, xvfb, socat, x11vnc, websockify) must all
        be RUNNING. If Chrome is FATAL we attempt to install and start it,
        but we do not block the caller on Chrome availability — the shell and
        file tools work without Chrome.
        """
        max_retries = 30
        retry_interval = 2
        chrome_fix_attempted = False

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

                chrome_fatal = False
                non_running_non_chrome: list[str] = []

                for svc in services:
                    name = svc.get("name", "?")
                    state = svc.get("statename", "")
                    if state == "RUNNING":
                        continue
                    if name == "chrome":
                        if state == "FATAL":
                            chrome_fatal = True
                    else:
                        non_running_non_chrome.append(f"{name}({state})")

                if not non_running_non_chrome:
                    # All non-chrome services are running
                    if chrome_fatal and not chrome_fix_attempted:
                        chrome_fix_attempted = True
                        logger.info("Core services RUNNING; fixing Chrome in background...")
                        asyncio.create_task(self._fix_chrome())
                    elif not chrome_fatal:
                        logger.info("All %d services RUNNING — sandbox fully ready", len(services))
                    else:
                        logger.info(
                            "Core services RUNNING (Chrome fix in progress) — sandbox ready for shell/file"
                        )
                    return

                logger.info(
                    "Waiting for services (attempt %d/%d): %s",
                    attempt + 1, max_retries, non_running_non_chrome,
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
        api_key = os.getenv("E2B_API_KEY")
        template_id = os.getenv("E2B_TEMPLATE_ID", "1gsznx7zzecjwwwghuzw")
        ttl_minutes = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
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
        api_key = os.getenv("E2B_API_KEY")
        logger.info("Connecting to existing E2B sandbox: %s", id)
        e2b_sandbox = await asyncio.to_thread(
            E2BSandboxSDK.connect,
            sandbox_id=id,
            api_key=api_key,
        )
        return cls(e2b_sandbox)
