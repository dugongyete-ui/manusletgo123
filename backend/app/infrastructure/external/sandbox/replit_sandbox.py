import asyncio
import io
import logging
import os
from typing import Optional, BinaryIO

import httpx

from app.domain.external.sandbox import Sandbox, Browser
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser
from app.core.config import get_settings
from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

_SYS_BASE_SESSION = "__sys__"


class ReplitSandbox(Sandbox):
    """
    Replit-local Sandbox implementation.

    All sandbox services (xvfb, Chrome, x11vnc, websockify, FastAPI sandbox API)
    run as permanent processes inside the Replit container managed by supervisord.

    This is a singleton: create() and get() both return the same global instance.
    There are no remote tunnels — all URLs point to localhost.
    """

    _instance: Optional["ReplitSandbox"] = None
    _instance_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        settings = get_settings()
        self.client = httpx.AsyncClient(timeout=600)
        self._id = "replit-local"
        self.base_url = getattr(settings, "sandbox_base_url", None) or "http://localhost:8080"
        self._vnc_url = getattr(settings, "sandbox_vnc_url", None) or "ws://localhost:5901"
        self._cdp_url = getattr(settings, "sandbox_cdp_url", None) or "http://localhost:8222"
        logger.info(
            "ReplitSandbox initialised: base_url=%s vnc=%s cdp=%s",
            self.base_url, self._vnc_url, self._cdp_url,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_admin_cmd(self, cmd: str, timeout: int = 30) -> str:
        """Run a one-shot admin command via the sandbox shell HTTP API.

        NOTE: exec_dir must be a directory that ALWAYS exists and is writable
        for the sandbox process user. "/root" fails with a permission error when
        the sandbox runs as a non-root user, which silently broke every caller
        of this helper (file_exists, setup_user_home, warmup) — hence "/tmp".
        """
        session = f"{_SYS_BASE_SESSION}_{os.urandom(4).hex()}"
        try:
            # The exec endpoint waits up to 5 s internally and returns the
            # output directly when the command completes fast — use that first.
            exec_resp = await self.client.post(
                f"{self.base_url}/api/v1/shell/exec",
                json={"id": session, "exec_dir": "/tmp", "command": cmd},
            )
            exec_data = exec_resp.json() if exec_resp.status_code == 200 else {}
            if not exec_data.get("success"):
                logger.warning(
                    "Admin cmd exec failed (%s): %s",
                    cmd[:60], exec_data.get("message", exec_resp.status_code),
                )
                return ""
            exec_result = exec_data.get("data") or {}
            if (
                isinstance(exec_result, dict)
                and exec_result.get("status") == "completed"
                and exec_result.get("output") is not None
            ):
                return str(exec_result.get("output") or "")

            # Long-running command — wait for it, then read the session output.
            try:
                await self.client.post(
                    f"{self.base_url}/api/v1/shell/wait",
                    json={"id": session, "seconds": timeout},
                )
            except Exception:
                pass
            await asyncio.sleep(0.3)
            view_resp = await self.client.post(
                f"{self.base_url}/api/v1/shell/view",
                json={"id": session, "console": False},
            )
            if view_resp.status_code != 200:
                logger.warning(
                    "Admin cmd view failed (%s): HTTP %s",
                    cmd[:60], view_resp.status_code,
                )
                return ""
            data = view_resp.json()
            if not data.get("success"):
                logger.warning("Admin cmd view error (%s): %s", cmd[:60], data.get("message"))
                return ""
            result = data.get("data", {})
            if isinstance(result, dict):
                return str(result.get("output", "") or "")
            return str(result or "")
        except Exception as exc:
            logger.warning("Admin cmd failed (%s): %s", cmd[:60], exc)
            return ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_sandbox(self) -> None:
        """
        Poll the sandbox supervisor status endpoint until all services are RUNNING.
        This is a simple poll — no Chrome installation or CDP proxy deployment needed
        because those services are pre-installed in the Replit container.
        """
        max_retries = 20
        retry_interval = 2

        for attempt in range(max_retries):
            try:
                response = await self.client.get(
                    f"{self.base_url}/api/v1/supervisor/status"
                )
                response.raise_for_status()
                tool_result = ToolResult(**response.json())
                if not tool_result.success:
                    if attempt % 5 == 0:
                        logger.info(
                            "ensure_sandbox: waiting for API (attempt %d/%d)…",
                            attempt + 1, max_retries,
                        )
                    await asyncio.sleep(retry_interval)
                    continue

                services = tool_result.data or []
                if not services:
                    await asyncio.sleep(retry_interval)
                    continue

                non_running = [
                    f"{s.get('name', '?')}({s.get('statename', '?')})"
                    for s in services
                    if s.get("statename") != "RUNNING"
                ]
                if not non_running:
                    logger.info(
                        "All %d sandbox services RUNNING — sandbox ready", len(services)
                    )
                    return

                if attempt % 5 == 0 or attempt < 3:
                    logger.info(
                        "Waiting for services (attempt %d/%d): %s",
                        attempt + 1, max_retries, non_running,
                    )
            except Exception as exc:
                if attempt % 5 == 0 or attempt < 3:
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
        """No-op — the Replit sandbox is a permanent process and is never destroyed."""
        logger.info("ReplitSandbox.destroy() called — no-op (permanent process)")
        return True

    async def warmup_packages(self) -> None:
        """
        Pre-install all common Python packages and system tools inside the sandbox
        so the AI agent can use them immediately without wasting task time on installs.

        Uses a flag file /tmp/.sandbox_warmed_up to skip reinstall on subsequent
        warmup calls within the same container lifetime.
        """
        flag = "/tmp/.sandbox_warmed_up"
        check = await self._run_admin_cmd(
            f"test -f {flag} && echo ALREADY || echo NEEDED", timeout=5
        )
        if "ALREADY" in check:
            logger.info("Sandbox packages already warmed up — skipping")
            return

        logger.info("Starting sandbox package warmup…")

        # ── System packages (apt) ──────────────────────────────────────────
        apt_packages = " ".join([
            "poppler-utils",    # pdftotext command
            "ffmpeg",           # audio/video processing
            "imagemagick",      # image conversion
            "curl", "wget",     # network utilities
            "unzip", "zip",     # archive tools
        ])
        await self._run_admin_cmd(
            f"apt-get update -qq && apt-get install -y -qq {apt_packages} 2>&1 | tail -3",
            timeout=120,
        )
        logger.info("apt warmup done")

        # ── Python packages (pip) — batched for speed ──────────────────────
        pip_batches = [
            # Document processing (most common)
            "python-pptx pdfplumber python-docx pandas openpyxl xlrd",
            # Data science & visualization
            "numpy matplotlib seaborn plotly scipy",
            # PDF tools
            "reportlab pypdf2 PyMuPDF",
            # Web scraping & HTTP
            "beautifulsoup4 lxml requests aiohttp",
            # Image processing
            "Pillow",
            # Media & download
            "yt-dlp pydub",
            # Utilities
            "certifi qrcode[pil] markdown tabulate tqdm colorama",
            # Search
            "duckduckgo-search",
            # Data formats
            "toml pyyaml jsonschema",
            # Code & text
            "pygments rich",
        ]

        for batch in pip_batches:
            result = await self._run_admin_cmd(
                f"pip3 install -q --disable-pip-version-check {batch} 2>&1 | tail -2",
                timeout=180,
            )
            logger.info("pip batch done: %s … result: %s", batch[:50], result[:80] if result else "ok")

        # Mark as complete
        await self._run_admin_cmd(
            f"echo 'warmed_up' > {flag} && echo OK",
            timeout=5,
        )
        logger.info("Sandbox package warmup complete ✓")

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
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/exec",
            json={"id": session_id, "exec_dir": exec_dir, "command": command},
        )
        return ToolResult(**response.json())

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
        out = await self._run_admin_cmd(
            f"test -e '{path}' && echo __exists__ || echo __absent__"
        )
        exists = "__exists__" in out and "__absent__" not in out
        return ToolResult(
            success=True,
            message="File exists check completed",
            data={"exists": exists},
        )

    async def file_delete(self, path: str) -> ToolResult:
        """Delete a file/directory via the sandbox file API (real, verified)."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/file/delete",
                json={"path": path},
            )
            data = response.json()
            if response.status_code != 200 or not data.get("success"):
                return ToolResult(
                    success=False,
                    message=f"Failed to delete {path}: {data.get('message', response.status_code)}",
                )
            return ToolResult(
                success=True,
                message=f"Deleted: {path}",
                data=data.get("data") or {"path": path},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to delete {path}: {exc}")

    async def file_move(self, source: str, destination: str) -> ToolResult:
        """Move/rename a file/directory via the sandbox file API (real, verified)."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/file/move",
                json={"source": source, "destination": destination},
            )
            data = response.json()
            if response.status_code != 200 or not data.get("success"):
                return ToolResult(
                    success=False,
                    message=f"Failed to move {source} → {destination}: {data.get('message', response.status_code)}",
                )
            return ToolResult(
                success=True,
                message=f"Moved: {source} → {destination}",
                data=data.get("data") or {"source": source, "destination": destination},
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to move {source} → {destination}: {exc}"
            )

    async def file_copy(self, source: str, destination: str) -> ToolResult:
        """Copy a file/directory via the sandbox file API (real, verified)."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/file/copy",
                json={"source": source, "destination": destination},
            )
            data = response.json()
            if response.status_code != 200 or not data.get("success"):
                return ToolResult(
                    success=False,
                    message=f"Failed to copy {source} → {destination}: {data.get('message', response.status_code)}",
                )
            return ToolResult(
                success=True,
                message=f"Copied: {source} → {destination}",
                data=data.get("data") or {"source": source, "destination": destination},
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=f"Failed to copy {source} → {destination}: {exc}"
            )

    async def file_list(self, path: str) -> ToolResult:
        """List a directory via the sandbox file API (real, verified)."""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/file/list",
                json={"path": path},
            )
            data = response.json()
            if response.status_code != 200 or not data.get("success"):
                return ToolResult(
                    success=False,
                    message=f"Failed to list directory {path}: {data.get('message', response.status_code)}",
                )
            result_data = data.get("data") or {}
            entries = result_data.get("entries", [])
            # Human-readable multi-line listing (name, type, size) for the LLM.
            lines = [
                f"{e.get('type', 'file'):4s} {str(e.get('size', 0)):>10s}  {e.get('name', '')}"
                for e in entries
            ]
            listing = "\n".join(lines)
            return ToolResult(
                success=True,
                message=f"Directory listed: {len(entries)} entry(ies)",
                data={"listing": listing, "entries": entries},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to list directory {path}: {exc}")

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
    def cdp_url(self) -> str:
        return self._cdp_url

    @property
    def vnc_url(self) -> str:
        return self._vnc_url

    # ------------------------------------------------------------------
    # Factory class methods — singleton pattern
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls) -> "ReplitSandbox":
        """Return the global singleton ReplitSandbox instance, creating it if needed."""
        async with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                logger.info("ReplitSandbox singleton created")
            return cls._instance

    @classmethod
    async def get(cls, id: str) -> "ReplitSandbox":
        """Return the global singleton ReplitSandbox instance (id is ignored)."""
        async with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                logger.info("ReplitSandbox singleton created via get()")
            return cls._instance
