import logging
from typing import Optional, BinaryIO

from app.domain.models.tool_result import ToolResult
from app.domain.external.browser import Browser

logger = logging.getLogger(__name__)


class UserScopedSandbox:
    """Per-user filesystem isolation wrapper around the shared ReplitSandbox singleton.

    Because Replit runs a single container with one shared sandbox process,
    all users would otherwise share the same filesystem namespace (/home/runner/).
    This wrapper gives each user their own working directory:

        /home/runner/users/{user_id}/          ← user's home
        /home/runner/users/{user_id}/upload/   ← file upload landing zone

    All Sandbox protocol methods are delegated unchanged to the inner singleton.
    The only behavioural difference is:
    - `upload_dir` and `user_home` properties return user-specific paths.
    - `setup_user_home()` creates those directories on first use.

    The wrapper is intentionally thin — it does NOT redirect arbitrary paths
    chosen by the agent inside the shell; that is controlled via the system prompt
    which tells the agent to work inside `user_home`.
    """

    def __init__(self, sandbox, user_id: str) -> None:
        self._inner = sandbox
        self._user_id = user_id
        self._user_home = f"/home/runner/users/{user_id}"
        self._upload_dir = f"/home/runner/users/{user_id}/upload"

    # ------------------------------------------------------------------
    # User-specific properties
    # ------------------------------------------------------------------

    @property
    def user_home(self) -> str:
        """The user's isolated working directory inside the sandbox."""
        return self._user_home

    @property
    def upload_dir(self) -> str:
        """Directory where user-uploaded files are placed in the sandbox."""
        return self._upload_dir

    async def setup_user_home(self) -> None:
        """Create user home and upload directories (idempotent, safe to call multiple times)."""
        try:
            await self._inner._run_admin_cmd(
                f"mkdir -p '{self._upload_dir}' && chmod 750 '{self._user_home}'"
            )
            logger.info("UserScopedSandbox: home ready at %s", self._user_home)
        except Exception as exc:
            logger.warning("UserScopedSandbox: failed to create home for user %s: %s", self._user_id, exc)

    # ------------------------------------------------------------------
    # Sandbox protocol — all delegated to the inner singleton
    # ------------------------------------------------------------------

    async def ensure_sandbox(self) -> None:
        return await self._inner.ensure_sandbox()

    async def exec_command(
        self,
        session_id: str,
        exec_dir: str,
        command: str,
    ) -> ToolResult:
        return await self._inner.exec_command(session_id, exec_dir, command)

    async def view_shell(self, session_id: str, console: bool = False) -> ToolResult:
        return await self._inner.view_shell(session_id, console)

    async def wait_for_process(
        self, session_id: str, seconds: Optional[int] = None
    ) -> ToolResult:
        return await self._inner.wait_for_process(session_id, seconds)

    async def write_to_process(
        self, session_id: str, input_text: str, press_enter: bool = True
    ) -> ToolResult:
        return await self._inner.write_to_process(session_id, input_text, press_enter)

    async def kill_process(self, session_id: str) -> ToolResult:
        return await self._inner.kill_process(session_id)

    async def file_write(
        self,
        file: str,
        content: str,
        append: bool = False,
        leading_newline: bool = False,
        trailing_newline: bool = False,
        sudo: Optional[bool] = False,
    ) -> ToolResult:
        return await self._inner.file_write(
            file, content, append, leading_newline, trailing_newline, sudo
        )

    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        sudo: bool = False,
    ) -> ToolResult:
        return await self._inner.file_read(file, start_line, end_line, sudo)

    async def file_exists(self, path: str) -> ToolResult:
        return await self._inner.file_exists(path)

    async def file_delete(self, path: str) -> ToolResult:
        return await self._inner.file_delete(path)

    async def file_move(self, source: str, destination: str) -> ToolResult:
        return await self._inner.file_move(source, destination)

    async def file_copy(self, source: str, destination: str) -> ToolResult:
        return await self._inner.file_copy(source, destination)

    async def file_list(self, path: str) -> ToolResult:
        return await self._inner.file_list(path)

    async def file_replace(
        self, file: str, old_str: str, new_str: str, sudo: bool = False
    ) -> ToolResult:
        return await self._inner.file_replace(file, old_str, new_str, sudo)

    async def file_search(
        self, file: str, regex: str, sudo: bool = False
    ) -> ToolResult:
        return await self._inner.file_search(file, regex, sudo)

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        return await self._inner.file_find(path, glob_pattern)

    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: Optional[str] = None,
    ) -> ToolResult:
        return await self._inner.file_upload(file_data, path, filename)

    async def file_download(self, path: str) -> BinaryIO:
        return await self._inner.file_download(path)

    async def destroy(self) -> bool:
        return await self._inner.destroy()

    async def get_browser(self) -> Browser:
        return await self._inner.get_browser()

    # ------------------------------------------------------------------
    # Properties required by the Sandbox protocol
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._inner.id

    @property
    def cdp_url(self) -> str:
        return self._inner.cdp_url

    @property
    def vnc_url(self) -> str:
        return self._inner.vnc_url

    # ------------------------------------------------------------------
    # Class-level factory methods (not used on wrapper — use inner sandbox)
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls):
        raise NotImplementedError(
            "Call ReplitSandbox.create() then wrap with UserScopedSandbox(sandbox, user_id)"
        )

    @classmethod
    async def get(cls, id: str):
        raise NotImplementedError(
            "Call ReplitSandbox.get(id) then wrap with UserScopedSandbox(sandbox, user_id)"
        )
