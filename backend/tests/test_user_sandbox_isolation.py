"""Unit tests for UserScopedSandbox hard path isolation (Replit fallback path).

These verify the Layer-2 defence: on the shared Replit sandbox, every file
operation must be constrained to the user's own home (plus /tmp scratch).
Cross-user access — direct, via traversal, or via shell command — is blocked.
"""

import asyncio
import io

import pytest

from app.infrastructure.external.sandbox.user_sandbox import (
    SandboxAccessDenied,
    UserScopedSandbox,
)
from app.domain.models.tool_result import ToolResult


class RecordingSandbox:
    """Fake inner sandbox recording every call for assertion."""

    shared = True

    def __init__(self):
        self.calls = []

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append(("exec", exec_dir, command))
        return ToolResult(success=True)

    async def file_read(self, file, start_line=None, end_line=None, sudo=False):
        self.calls.append(("read", file))
        return ToolResult(success=True, data={"content": "x"})

    async def file_write(self, file, content, append=False, leading_newline=False,
                         trailing_newline=False, sudo=False):
        self.calls.append(("write", file))
        return ToolResult(success=True)

    async def file_delete(self, path):
        self.calls.append(("delete", path))
        return ToolResult(success=True)

    async def file_list(self, path):
        self.calls.append(("list", path))
        return ToolResult(success=True, data={"entries": []})

    async def file_exists(self, path):
        self.calls.append(("exists", path))
        return ToolResult(success=True, data={"exists": True})

    async def file_move(self, source, destination):
        self.calls.append(("move", source, destination))
        return ToolResult(success=True)

    async def file_copy(self, source, destination):
        self.calls.append(("copy", source, destination))
        return ToolResult(success=True)

    async def file_find(self, path, glob_pattern):
        self.calls.append(("find", path, glob_pattern))
        return ToolResult(success=True, data={"files": []})

    async def file_upload(self, file_data, path, filename=None):
        self.calls.append(("upload", path))
        return ToolResult(success=True)

    async def file_download(self, path):
        self.calls.append(("download", path))
        return io.BytesIO(b"x")

    async def file_replace(self, file, old_str, new_str, sudo=False):
        self.calls.append(("replace", file))
        return ToolResult(success=True)

    async def file_search(self, file, regex, sudo=False):
        self.calls.append(("search", file))
        return ToolResult(success=True)

    async def setup_user_home(self):
        self.calls.append(("setup_home",))

    async def ensure_sandbox(self):
        pass

    async def get_browser(self):
        return None

    async def view_shell(self, session_id, console=False):
        return ToolResult(success=True)

    async def wait_for_process(self, session_id, seconds=None):
        return ToolResult(success=True)

    async def write_to_process(self, session_id, input_text, press_enter=True):
        return ToolResult(success=True)

    async def kill_process(self, session_id):
        return ToolResult(success=True)

    async def destroy(self):
        return True


USER = "user123"
OTHER = "victim999"
HOME = f"/home/runner/users/{USER}"
OTHER_HOME = f"/home/runner/users/{OTHER}"


@pytest.fixture(autouse=True)
def fixed_user_home_root(monkeypatch):
    """Pin user_home_root so tests do not depend on the host .env."""
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("S", (), {"user_home_root": "/home/runner/users"})(),
    )


@pytest.fixture
def inner():
    return RecordingSandbox()


@pytest.fixture
def sandbox(inner):
    return UserScopedSandbox(inner, USER)


def test_read_own_home_allowed(sandbox, inner):
    result = asyncio.run(sandbox.file_read(f"{HOME}/notes.txt"))
    assert result.success
    assert ("read", f"{HOME}/notes.txt") in inner.calls


def test_read_other_users_home_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_read(f"{OTHER_HOME}/secret.txt"))
    assert not result.success
    assert "Access denied" in result.message
    assert not any(c[0] == "read" for c in inner.calls)


def test_write_other_users_home_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_write(f"{OTHER_HOME}/pwn.txt", "malicious"))
    assert not result.success
    assert not any(c[0] == "write" for c in inner.calls)


def test_delete_other_users_home_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_delete(f"{OTHER_HOME}/important.zip"))
    assert not result.success
    assert not any(c[0] == "delete" for c in inner.calls)


def test_traversal_escape_blocked(sandbox, inner):
    # ../ escape from own home into sibling user dir
    sneaky = f"{HOME}/../{OTHER}/secret.txt"
    result = asyncio.run(sandbox.file_read(sneaky))
    assert not result.success
    assert not any(c[0] == "read" for c in inner.calls)


def test_traversal_to_root_blocked(sandbox, inner):
    sneaky = f"{HOME}/../../../../etc/passwd"
    result = asyncio.run(sandbox.file_read(sneaky))
    assert not result.success


def test_tmp_scratch_allowed(sandbox, inner):
    result = asyncio.run(sandbox.file_read("/tmp/build.log"))
    assert result.success
    assert ("read", "/tmp/build.log") in inner.calls


def test_tmp_traversal_into_users_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_read("/tmp/../../home/runner/users/victim999/x"))
    assert not result.success


def test_system_paths_blocked(sandbox, inner):
    for path in ("/etc/passwd", "/root/.ssh/id_rsa", "/home/runner/workspace/x",
                 "/var/log/auth.log", "/home/runner/users"):
        result = asyncio.run(sandbox.file_read(path))
        assert not result.success, f"{path} should be blocked"


def test_move_between_users_blocked(sandbox, inner):
    # stealing: move victim file into own home
    result = asyncio.run(sandbox.file_move(f"{OTHER_HOME}/secret.txt", f"{HOME}/stolen.txt"))
    assert not result.success
    assert not any(c[0] == "move" for c in inner.calls)
    # exfiltration: move own file into victim home
    result = asyncio.run(sandbox.file_move(f"{HOME}/a.txt", f"{OTHER_HOME}/b.txt"))
    assert not result.success


def test_copy_between_users_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_copy(f"{OTHER_HOME}/data.csv", f"{HOME}/data.csv"))
    assert not result.success
    assert not any(c[0] == "copy" for c in inner.calls)


def test_list_other_users_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_list(OTHER_HOME))
    assert not result.success


def test_find_other_users_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_find("/home/runner/users", "*.txt"))
    assert not result.success


def test_upload_into_other_users_blocked(sandbox, inner):
    result = asyncio.run(sandbox.file_upload(io.BytesIO(b"x"), f"{OTHER_HOME}/evil.sh"))
    assert not result.success


def test_download_from_other_users_blocked(sandbox, inner):
    with pytest.raises(SandboxAccessDenied):
        asyncio.run(sandbox.file_download(f"{OTHER_HOME}/secret.txt"))


def test_exec_dir_validation(sandbox, inner):
    result = asyncio.run(sandbox.exec_command("s1", OTHER_HOME, "ls"))
    assert not result.success
    assert not any(c[0] == "exec" for c in inner.calls)


def test_exec_command_referencing_other_user_blocked(sandbox, inner):
    cmd = f"cat {OTHER_HOME}/secret.txt"
    result = asyncio.run(sandbox.exec_command("s1", HOME, cmd))
    assert not result.success
    assert "another user" in result.message
    assert not any(c[0] == "exec" for c in inner.calls)


def test_exec_command_own_home_referencing_allowed(sandbox, inner):
    cmd = f"ls {HOME}"
    result = asyncio.run(sandbox.exec_command("s1", HOME, cmd))
    assert result.success
    assert ("exec", HOME, cmd) in inner.calls


def test_exec_command_general_paths_allowed(sandbox, inner):
    """Legit commands without other-user references still pass through."""
    result = asyncio.run(sandbox.exec_command("s1", HOME, "pip install pandas && python x.py"))
    assert result.success


def test_relative_path_resolves_into_own_home(sandbox, inner):
    result = asyncio.run(sandbox.file_read("notes.txt"))
    assert result.success
    assert ("read", f"{HOME}/notes.txt") in inner.calls


def test_normalize_collapses_traversal():
    class _NoInner:
        pass
    sbx = UserScopedSandbox.__new__(UserScopedSandbox)
    sbx._user_home = HOME
    assert sbx._normalize("a/../b") == f"{HOME}/b"
    assert sbx._normalize("/tmp/x/../y") == "/tmp/y"


def test_check_path_raises_for_blocked():
    sbx = UserScopedSandbox.__new__(UserScopedSandbox)
    sbx._user_home = HOME
    with pytest.raises(SandboxAccessDenied):
        sbx._check_path(f"{OTHER_HOME}/x", "read")
    # own home + tmp pass
    assert sbx._check_path(f"{HOME}/x", "read") == f"{HOME}/x"
    assert sbx._check_path("/tmp/x", "read") == "/tmp/x"
