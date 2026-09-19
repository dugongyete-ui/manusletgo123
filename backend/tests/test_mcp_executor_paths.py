"""MCP executor ↔ sandbox environment consistency (regression).

User report (session fe205b952ea242b3, z.ai deployment, provider=local):
webdev_init_project hard-coded /home/user/<name> — the E2B home layout —
while the shared sandbox serves each user from /home/z/users/<uid>. The tool
then reported project_dir /home/user/dzeck-landing-page to the model, the
model trusted it, and every subsequent shell command "jumped" to a phantom
E2B path (ls /home/user → No such file or directory).

Contract under test:
  1. Every executor-built path resolves from sandbox.user_home (the REAL
     environment) — when E2B is off, no /home/user may ever appear in a
     command, a payload, or a returned path.
  2. sandbox.user_home wins; settings.user_home_root is the fallback; /tmp
     the last resort — never a foreign provider literal.
  3. webdev_init_project verifies the scaffold artifact before reporting
     success (transport success ≠ command success).
  4. Project names / checkpoint ids are sanitized (no traversal).
"""

import asyncio
import json
from typing import Any, Dict, List

from app.domain.models.tool_result import ToolResult
from app.domain.services.manus_registry.mcp_executor import ManusMCPExecutor

REAL_HOME = "/home/z/users/4d1Us4jb9wKaOd4a3raPlA"


class ScopedSandbox:
    """Sandbox double exposing user_home like UserScopedSandbox does."""

    def __init__(self, user_home: str = REAL_HOME, output: str = "",
                 returncode: int = 0):
        self.user_home = user_home
        self.calls: List[Dict[str, Any]] = []
        self.output = output
        self.returncode = returncode

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append({"session_id": session_id, "exec_dir": exec_dir,
                           "command": command})
        # Emulate the verify probe: the artifact exists when the scaffold
        # command ran with returncode 0.
        if "test -f" in command and "__scaffold_ok__" in command:
            out = ("__scaffold_ok__" if self.returncode == 0
                   else "__scaffold_missing__")
        else:
            out = self.output
        return ToolResult(
            success=True, message="Command executed",
            data={"session_id": session_id, "exec_dir": exec_dir,
                  "command": command, "status": "completed",
                  "returncode": self.returncode, "output": out},
        )


class BareSandbox(ScopedSandbox):
    """Shared sandbox WITHOUT user_home (raw ReplitSandbox-like)."""


def _data(payload: Dict[str, Any]) -> Dict[str, Any]:
    assert payload["success"], payload
    return payload["data"]


# ── 1. webdev_init_project resolves the REAL home ────────────────────────────

def test_webdev_init_project_uses_real_sandbox_home():
    sb = ScopedSandbox()
    ex = ManusMCPExecutor(sandbox=sb)
    payload = asyncio.run(ex.execute("webdev_init_project", {
        "brief": "buat proyek", "name": "dzeck-landing-page",
        "scaffold": "web-static", "title": "Dzeck", "description": "x",
    }))
    data = _data(payload)
    assert data["project_dir"] == f"{REAL_HOME}/dzeck-landing-page"
    scaffold_cmd = sb.calls[0]["command"]
    assert f"mkdir -p {REAL_HOME}/dzeck-landing-page" in scaffold_cmd
    assert "/home/user" not in scaffold_cmd
    # cwd pinned to the resolved workspace root, not "" and not /home/user
    assert sb.calls[0]["exec_dir"] == REAL_HOME
    # verify probe ran against the same real path
    assert f"test -f {REAL_HOME}/dzeck-landing-page/index.html" in sb.calls[1]["command"]


def test_webdev_init_project_reports_failure_when_scaffold_missing():
    sb = ScopedSandbox(returncode=1)  # mkdir failed (e.g. permission denied)
    ex = ManusMCPExecutor(sandbox=sb)
    payload = asyncio.run(ex.execute("webdev_init_project", {
        "brief": "b", "name": "proj", "scaffold": "web-static",
        "title": "T", "description": "D",
    }))
    # The tool must NOT claim success with a fabricated path.
    assert not payload["success"]
    assert "did not land" in payload["error"]["message"]
    assert REAL_HOME in payload["error"]["message"]
    assert "project_dir" not in json.dumps(payload.get("data") or {})


# ── 2. fallback chain when the sandbox exposes no user_home ────────────────

def test_workspace_root_falls_back_to_settings_root():
    sb = BareSandbox(user_home=None)  # raw shared sandbox, no wrapper
    ex = ManusMCPExecutor(sandbox=sb)
    from app.core.config import get_settings
    expected = (get_settings().user_home_root or "/tmp").rstrip("/")
    assert ex._workspace_root() == expected
    assert "/home/user" != ex._workspace_root()


def test_webdev_dir_sanitizes_name():
    sb = ScopedSandbox()
    ex = ManusMCPExecutor(sandbox=sb)
    # traversal collapses into ONE safe component under the real home —
    # the path can never escape {user_home} no matter what the model sends
    assert ex._webdev_dir({"name": "../../etc/passwd"}) == \
        f"{REAL_HOME}/etc-passwd"
    assert ex._webdev_dir({"name": "My App!"}) == f"{REAL_HOME}/My-App"


# ── 3. checkpoints / sql / screenshot live in the real home ────────────────

def test_webdev_checkpoint_paths_stay_in_real_home():
    sb = ScopedSandbox()
    ex = ManusMCPExecutor(sandbox=sb)
    asyncio.run(ex.execute("webdev_save_checkpoint", {
        "brief": "c", "name": "proj",
    }))
    cmd = sb.calls[0]["command"]
    assert f"{REAL_HOME}/.webdev/checkpoints" in cmd
    assert "/home/user" not in cmd


def test_webdev_rollback_sanitizes_checkpoint_id():
    sb = ScopedSandbox()
    ex = ManusMCPExecutor(sandbox=sb)
    asyncio.run(ex.execute("webdev_rollback_checkpoint", {
        "brief": "r", "name": "proj", "checkpoint_id": "20260919-010101",
    }))
    cmd = sb.calls[0]["command"]
    assert f"{REAL_HOME}/.webdev/checkpoints/20260919-010101.tar.gz" in cmd
    assert f" -C {REAL_HOME} " in cmd


def test_webdev_execute_sql_default_db_in_real_home():
    sb = ScopedSandbox(output="[]")
    ex = ManusMCPExecutor(sandbox=sb)
    payload = asyncio.run(ex.execute("webdev_execute_sql", {
        "brief": "q", "query": "SELECT 1",
    }))
    data = _data(payload)
    assert data["database"] == f"{REAL_HOME}/webdev/data.db"
    assert "/home/user" not in sb.calls[0]["command"]


def test_generate_image_default_path_in_real_home():
    class StubImageToolkit:
        async def image_generate(self, prompt, size=None, model=None):
            return ToolResult(success=True, data={"url": "https://img.example/x.png"})

        async def image_download(self, url, file_path):
            return ToolResult(success=True, data={"saved": file_path})

    ex = ManusMCPExecutor(sandbox=ScopedSandbox(), image_toolkit=StubImageToolkit())
    payload = asyncio.run(ex.execute("generate_image", {
        "brief": "gambar", "images": [{"prompt": "kucing"}],
    }))
    data = _data(payload)
    assert data["saved_path"] == f"{REAL_HOME}/generated_image.png"
    assert "/workspace" not in json.dumps(data)
