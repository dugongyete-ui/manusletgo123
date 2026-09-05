"""Unit tests for the workspace operating-manual scaffold
(`infrastructure.external.sandbox.workspace_scaffold`):

- collect_manual_files() maps the repo manual/ dir (25 core files + skills)
- build_scaffold_script() embeds every file and stays idempotent via the
  version marker
- scaffold_workspace_manual() takes the fast path when the marker matches,
  writes + executes the script otherwise, and never raises on failure
"""

from types import SimpleNamespace

import pytest

from app.infrastructure.external.sandbox.workspace_scaffold import (
    MANUAL_VERSION,
    build_scaffold_script,
    collect_manual_files,
    scaffold_workspace_manual,
)


class _FakeSandbox:
    """Records calls; simulates marker content and exec output."""

    def __init__(
        self,
        user_home: str = "/home/runner",
        marker_content: str = "",
        exec_output: str = "MANUAL_WROTE 35",
        exec_success: bool = True,
    ):
        self.user_home = user_home
        self._marker = marker_content
        self._exec_output = exec_output
        self._exec_success = exec_success
        self.written: dict = {}
        self.execs: list = []

    async def file_read(self, file, start_line=None, end_line=None, sudo=False):
        if file.endswith("AGENTS.md"):
            return SimpleNamespace(
                success=bool(self._marker),
                data={"content": self._marker, "file": file},
            )
        return SimpleNamespace(success=False, data=None)

    async def file_write(self, file, content, *a, **k):
        self.written[file] = content
        return SimpleNamespace(success=True, data={"file": file})

    async def exec_command(self, session_id, exec_dir, command):
        self.execs.append((session_id, exec_dir, command))
        return SimpleNamespace(
            success=self._exec_success,
            data={"output": self._exec_output, "returncode": 0},
        )


# ── source collection ────────────────────────────────────────────────────────


def test_manual_source_complete():
    files = collect_manual_files()
    expected_core = [
        "AGENTS.md", "README.md", "SOUL.md", "IDENTITY.md", "MISSION.md",
        "RULES.md", "INSTRUCTIONS.md", "CONTEXT.md", "MEMORY.md", "TOOLS.md",
        "WORKFLOW.md", "TASKS.md", "SKILLS.md", "CAPABILITIES.md",
        "STANDARDS.md", "STYLE.md", "DESIGN.md", "BRAND.md", "CONTENT.md",
        "RESEARCH.md", "CODING.md", "TESTING.md", "DEPLOYMENT.md",
        "SECURITY.md", "PROJECT.md",
    ]
    for name in expected_core:
        assert name in files, f"missing manual file: {name}"
    skills = [k for k in files if k.startswith("skills/") and k.endswith("SKILL.md")]
    assert len(skills) >= 10, f"expected >= 10 skills, got {len(skills)}"
    assert f"manual-version: {MANUAL_VERSION}" in files["AGENTS.md"]


def test_script_contains_every_file_and_marker_logic():
    files = collect_manual_files()
    script = build_scaffold_script("/home/runner", files)
    assert "/home/runner/project" in script
    assert "MANUAL_WROTE" in script
    assert "MANUAL_SKIP" in script
    for rel in (
        "AGENTS.md",
        "skills/webdev-readme-fullstack/SKILL.md",
        "skills/pptx/SKILL.md",
        "Rancangan_Notifikasi_User_melalui_Chat.md",
        "RULES.md",
    ):
        assert rel.replace("/", "\\/") in script or rel in script


# ── scaffold behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_path_when_marker_current():
    sb = _FakeSandbox(marker_content=f"manual-version: {MANUAL_VERSION}")
    ok = await scaffold_workspace_manual(sb, "/home/runner")
    assert ok is True
    assert sb.written == {}
    assert sb.execs == []


@pytest.mark.asyncio
async def test_full_path_writes_and_executes():
    sb = _FakeSandbox(marker_content="")   # fresh workspace
    ok = await scaffold_workspace_manual(sb, "/home/runner")
    assert ok is True
    assert "/tmp/dzeck_ws_manual_scaffold.py" in sb.written
    assert len(sb.execs) == 1
    session_id, exec_dir, command = sb.execs[0]
    assert exec_dir == "/home/runner"
    assert "python3 /tmp/dzeck_ws_manual_scaffold.py" in command


@pytest.mark.asyncio
async def test_old_version_marker_triggers_rewrite():
    sb = _FakeSandbox(marker_content="manual-version: 0")
    ok = await scaffold_workspace_manual(sb, "/home/runner")
    assert ok is True
    assert sb.written, "old version must be re-scaffolded"


@pytest.mark.asyncio
async def test_exec_failure_never_raises():
    sb = _FakeSandbox(marker_content="", exec_success=False)
    ok = await scaffold_workspace_manual(sb, "/home/runner")
    assert ok is False


@pytest.mark.asyncio
async def test_missing_home_returns_false():
    sb = _FakeSandbox()
    assert await scaffold_workspace_manual(sb, None) is False


def test_real_script_is_valid_python():
    """The generated script must parse — a syntax error would break every
    fresh workspace (fail-open hides it, the manual would never land)."""
    import ast

    files = collect_manual_files()
    script = build_scaffold_script("/home/runner", files)
    ast.parse(script)  # raises on syntax error


def test_binary_assets_travel_base64():
    """Small binary skill assets (tarballs, PDF showcases) must survive the
    text scaffold: embedded as 'b64:' and decoded by the generated script."""
    import ast
    import base64

    files = collect_manual_files()
    blob = files.get("skills/artifacts-builder/scripts/shadcn-components.tar.gz")
    assert blob and blob.startswith("b64:"), "shadcn tarball missing from scaffold"
    raw = base64.b64decode(blob[4:])
    assert raw[:2] == b"\x1f\x8b", "not a gzip payload (corrupt b64 embed)"
    # the generated scaffold script must carry the decode branch
    script = build_scaffold_script("/home/runner", files)
    assert "b64decode" in script
    assert "open(p, 'wb')" in script
    ast.parse(script)
