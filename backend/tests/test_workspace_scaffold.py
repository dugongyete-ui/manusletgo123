"""Unit tests for the workspace operating-manual scaffold
(`infrastructure.external.sandbox.workspace_scaffold`):

- collect_manual_files() maps the repo manual/ dir (25 core files + skills)
- build_scaffold_script() embeds every file and stays idempotent via the
  hidden .manual-version file (the visible manual carries NO version text)
- scaffold_workspace_manual() takes the fast path when the version matches,
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
        if file.endswith(".manual-version"):
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
    # staleness marker lives in a HIDDEN file, never in visible manual text
    assert files[".manual-version"] == str(MANUAL_VERSION)
    assert "manual-version" not in files["AGENTS.md"]
    assert "version" not in files["AGENTS.md"].split("\n")[2]


def test_script_contains_every_file_and_marker_logic():
    files = collect_manual_files()
    script = build_scaffold_script("/home/runner", files)
    assert "/home/runner/project" in script
    assert "MANUAL_WROTE" in script
    assert "MANUAL_SKIP" in script
    # idempotence check runs on the hidden version file, not AGENTS.md
    assert "'.manual-version'" in script
    assert "if existing == VERSION" in script
    # stale-skill pruning: the sandbox must mirror the manifest exactly
    assert "MANUAL_PRUNED" in script
    assert "rmtree" in script
    for rel in (
        "AGENTS.md",
        "skills/webdev-readme-fullstack/SKILL.md",
        "skills/pptx/SKILL.md",
        "Rancangan_Notifikasi_User_melalui_Chat.md",
        "RULES.md",
    ):
        assert rel.replace("/", "\\/") in script or rel in script


def test_index_duplicated_into_skills_dir():
    """Agents reading prose like 'skills/ … index is SKILLS.md' guess
    project/skills/SKILLS.md — the scaffold must place the index at BOTH
    project/SKILLS.md and project/skills/SKILLS.md (same content).
    Regression: session 59ead2b2b5e24be1 died on
    'File does not exist: …/project/skills/SKILLS.md' and never loaded a
    build skill afterwards.
    """
    files = collect_manual_files()
    assert "SKILLS.md" in files, "root index missing from manual"
    assert "skills/SKILLS.md" in files, "skills/ copy of the index missing"
    assert files["skills/SKILLS.md"] == files["SKILLS.md"]
    # the copy must not be mistaken for a skill folder payload entry
    skills = [k for k in files if k.startswith("skills/") and k.endswith("/SKILL.md")]
    assert "skills/SKILLS.md" not in skills


def test_scaffold_roundtrip_prunes_stale_skill_dirs(tmp_path):
    """Execute the real generated script against a fake workspace:
    stale skill folders (e.g. dzeck-pptx) must be pruned, current skills
    written, the index present at BOTH paths, and task output OUTSIDE
    skills/ (e.g. project/ai-chat-web/) must survive untouched."""
    import subprocess
    import sys

    user_home = tmp_path / "home"
    project = user_home / "project"
    (project / "skills" / "dzeck-pptx").mkdir(parents=True)
    (project / "skills" / "dzeck-pptx" / "SKILL.md").write_text("STALE", encoding="utf-8")
    (project / "ai-chat-web").mkdir(parents=True)
    (project / "ai-chat-web" / "index.html").write_text("<html>task output</html>", encoding="utf-8")

    files = collect_manual_files()
    script = build_scaffold_script(str(user_home), files)
    # the payload is ~4MB — too big for a argv; stage it as a file like the
    # real scaffold does (file_write to /tmp, then exec)
    staged = tmp_path / "scaffold.py"
    staged.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(staged)], capture_output=True, text=True, timeout=180
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "MANUAL_WROTE" in proc.stdout

    # stale skill folder gone, real skills present, index at both paths
    assert not (project / "skills" / "dzeck-pptx").exists()
    assert (project / "skills" / "pptx" / "SKILL.md").is_file()
    assert (project / "SKILLS.md").is_file()
    assert (project / "skills" / "SKILLS.md").is_file()
    assert (
        (project / "skills" / "SKILLS.md").read_text(encoding="utf-8")
        == (project / "SKILLS.md").read_text(encoding="utf-8")
    )
    # binary skill asset survived the trip
    assert (project / "skills" / "artifacts-builder" / "scripts" / "shadcn-components.tar.gz").is_file()
    # task output outside skills/ is never touched
    assert (project / "ai-chat-web" / "index.html").read_text(encoding="utf-8") == "<html>task output</html>"
    # hidden version file reflects the current version; visible manual is clean
    assert (project / ".manual-version").read_text(encoding="utf-8").strip() == str(MANUAL_VERSION)
    assert "manual-version" not in (project / "AGENTS.md").read_text(encoding="utf-8")


# ── scaffold behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_path_when_marker_current():
    sb = _FakeSandbox(marker_content=str(MANUAL_VERSION))
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
    sb = _FakeSandbox(marker_content="0")   # stale version dotfile
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
