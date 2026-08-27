import logging
import posixpath
import re
from typing import Optional, BinaryIO

from app.domain.models.tool_result import ToolResult
from app.domain.external.browser import Browser

logger = logging.getLogger(__name__)


class SandboxAccessDenied(PermissionError):
    """Raised internally when a path outside the user's workspace is used."""


class UserScopedSandbox:
    """Per-user filesystem isolation wrapper around the shared ReplitSandbox singleton.

    Because Replit runs a single container with one shared sandbox process,
    all users would otherwise share the same filesystem namespace (/home/runner/).
    This wrapper gives each user their own working directory:

        /home/runner/users/{user_id}/          ← user's home
        /home/runner/users/{user_id}/upload/   ← file upload landing zone

    Hard filesystem isolation (Layer 1) is provided by the E2B provider — each
    user gets a whole microVM. This wrapper is the Layer 2 defence for the
    shared-Replit fallback: every file operation path is validated against
    the user's home (+ /tmp scratch) and REJECTED otherwise, so one account
    can never read, write, or delete another account's files even when the
    LLM tries (deliberately or through prompt injection).

    Shell `exec_command` working directories are validated the same way, and
    command strings referencing another user's home directory are blocked.
    """

    # Paths every user may touch in addition to their own home: /tmp is the
    # standard scratch area and is world-writable by design.
    _SHARED_ALLOWED = ("/tmp",)

    # Regex over a raw command string: any reference to the per-user root
    # that is NOT this user's own home is blocked (e.g.
    # `/home/runner/users/<other_id>/...`). Conservative on purpose.
    _OTHER_USER_HOME_RE = None  # compiled per-instance (needs user id)

    def __init__(self, sandbox, user_id: str) -> None:
        self._inner = sandbox
        self._user_id = user_id
        # Root is configurable (default matches Replit's /home/runner). Other
        # environments where /home/runner cannot be created (no permission to
        # mkdir under /home) can point this at a writable location via the
        # USER_HOME_ROOT env var — keeping behaviour identical on Replit.
        from app.core.config import get_settings
        root = getattr(get_settings(), "user_home_root", None) or "/home/runner/users"
        self._user_home = f"{root}/{user_id}"
        self._upload_dir = f"{self._user_home}/upload"
        # Escaped for regex: block /<root>/<other_id> references in commands.
        root_escaped = re.escape(root)
        self._other_user_re = re.compile(
            rf"{root_escaped}/(?!{re.escape(user_id)}(?:/|\b|$))[A-Za-z0-9_-]+"
        )

    # ------------------------------------------------------------------
    # Path validation (hard isolation for the shared-Replit fallback)
    # ------------------------------------------------------------------

    def _normalize(self, path: str) -> str:
        """Resolve relative paths and `..` traversal into an absolute path."""
        p = (path or "").strip()
        if not p:
            return ""
        if not p.startswith("/"):
            p = posixpath.join(self._user_home, p)
        # normpath collapses ./ and ../ (lexically — no symlink resolution,
        # but the sandbox shell resolves symlinks under these roots rarely;
        # belt-and-braces is that other users' dirs are chmod 750)
        return posixpath.normpath(p)

    def _check_path(self, path: str, op: str) -> str:
        """Validate a path; returns the normalized path or raises SandboxAccessDenied."""
        norm = self._normalize(path)
        if not norm:
            raise SandboxAccessDenied("Empty path")
        allowed = (self._user_home,) + self._SHARED_ALLOWED
        if not any(norm == a or norm.startswith(a + "/") for a in allowed):
            raise SandboxAccessDenied(
                f"Access denied ({op}): '{path}' is outside your workspace "
                f"({self._user_home}). Cross-user file access is not permitted."
            )
        return norm

    def _denied_result(self, op: str, path: str, exc: Exception) -> ToolResult:
        logger.warning(
            "UserScopedSandbox BLOCKED %s on %r for user %s: %s",
            op, path, self._user_id, exc,
        )
        return ToolResult(
            success=False,
            message=str(exc),
            data={"error": "access_denied", "path": path},
        )

    def _check_command(self, command: str) -> None:
        """Block shell commands that directly reference another user's home."""
        if self._other_user_re.search(command or ""):
            raise SandboxAccessDenied(
                "Access denied: command references another user's directory. "
                "Each account has an isolated workspace."
            )

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
            # Verify the directories actually exist — mkdir can fail silently
            # (e.g. no permission to create /home/runner on non-Replit hosts)
            # and the agent would then be told to work in a directory that
            # does not exist.
            check = await self._inner._run_admin_cmd(
                f"test -d '{self._upload_dir}' && echo HOME_OK || echo HOME_MISSING"
            )
            if "HOME_OK" in check:
                logger.info("UserScopedSandbox: home ready at %s", self._user_home)
            else:
                logger.warning(
                    "UserScopedSandbox: home %s could NOT be created — the agent "
                    "prompt references a non-existent directory. Set USER_HOME_ROOT "
                    "to a writable path.",
                    self._user_home,
                )
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
        try:
            exec_dir = self._check_path(exec_dir or self._user_home, "exec_dir")
        except SandboxAccessDenied as exc:
            return self._denied_result("exec", exec_dir, exc)
        try:
            self._check_command(command)
        except SandboxAccessDenied as exc:
            return self._denied_result("exec-command", command[:100], exc)
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
        try:
            file = self._check_path(file, "write")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_write", file, exc)
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
        try:
            file = self._check_path(file, "read")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_read", file, exc)
        return await self._inner.file_read(file, start_line, end_line, sudo)

    async def file_exists(self, path: str) -> ToolResult:
        try:
            path = self._check_path(path, "exists")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_exists", path, exc)
        return await self._inner.file_exists(path)

    async def file_delete(self, path: str) -> ToolResult:
        """Delete a file/directory (validated: user home or /tmp only)."""
        try:
            path = self._check_path(path, "delete")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_delete", path, exc)
        return await self._inner.file_delete(path)

    async def file_move(self, source: str, destination: str) -> ToolResult:
        """Move/rename a file/directory (both endpoints validated)."""
        try:
            source = self._check_path(source, "move-source")
            destination = self._check_path(destination, "move-dest")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_move", f"{source} → {destination}", exc)
        return await self._inner.file_move(source, destination)

    async def file_copy(self, source: str, destination: str) -> ToolResult:
        """Copy a file/directory (both endpoints validated)."""
        try:
            source = self._check_path(source, "copy-source")
            destination = self._check_path(destination, "copy-dest")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_copy", f"{source} → {destination}", exc)
        return await self._inner.file_copy(source, destination)

    async def file_list(self, path: str) -> ToolResult:
        """List a directory (validated)."""
        try:
            path = self._check_path(path, "list")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_list", path, exc)
        return await self._inner.file_list(path)

    async def file_replace(
        self, file: str, old_str: str, new_str: str, sudo: bool = False
    ) -> ToolResult:
        try:
            file = self._check_path(file, "replace")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_replace", file, exc)
        return await self._inner.file_replace(file, old_str, new_str, sudo)

    async def file_search(
        self, file: str, regex: str, sudo: bool = False
    ) -> ToolResult:
        try:
            file = self._check_path(file, "search")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_search", file, exc)
        return await self._inner.file_search(file, regex, sudo)

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        try:
            path = self._check_path(path, "find")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_find", path, exc)
        return await self._inner.file_find(path, glob_pattern)

    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: Optional[str] = None,
    ) -> ToolResult:
        try:
            path = self._check_path(path, "upload")
        except SandboxAccessDenied as exc:
            return self._denied_result("file_upload", path, exc)
        return await self._inner.file_upload(file_data, path, filename)

    async def file_download(self, path: str) -> BinaryIO:
        path = self._check_path(path, "download")
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
