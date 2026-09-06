"""Contract tests for manual/prompt skill-path clarity.

Regression (session 59ead2b2b5e24be1, 2026-09-06): the agent read
project/AGENTS.md, then tried file_read project/skills/SKILLS.md because
the prose said "`skills/` contains playbooks … the index is in SKILLS.md"
— path ambiguity. The read failed ("File does not exist"), the tier
guidance never loaded, no build skill was opened, and the "full stack
production website" came out as a 6-file skeleton.

These tests pin the fix from three sides:

1. every manual/prompt mention of the index gives an EXPLICIT path
   (project/SKILLS.md), and says the copy at project/skills/SKILLS.md
   is identical — so any path an agent guesses resolves;
2. TASKS.md no longer references retired skill folders (fullstack-web-app,
   static-landing-page) — every skill name it names must exist on disk;
3. the scaffold actually materialises the index at BOTH paths.
"""

from pathlib import Path

MANUAL = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "domain"
    / "services"
    / "agents"
    / "manual"
)


def _manual_text(name: str) -> str:
    return (MANUAL / name).read_text(encoding="utf-8")


# ── 1. explicit index paths in every touchpoint ─────────────────────────────


def test_system_prompt_names_index_path():
    from app.domain.services.prompts.system import SYSTEM_PROMPT

    assert "project/SKILLS.md" in SYSTEM_PROMPT
    assert "project/skills/SKILLS.md" in SYSTEM_PROMPT
    # the old ambiguous sentence must be gone
    assert "The index with load tiers is in SKILLS.md" not in SYSTEM_PROMPT


def test_execution_prompt_names_index_path():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    assert "project/SKILLS.md" in EXECUTION_SYSTEM_PROMPT
    assert "project/skills/SKILLS.md" in EXECUTION_SYSTEM_PROMPT
    assert "project/skills/<name>/SKILL.md" in EXECUTION_SYSTEM_PROMPT


def test_agents_md_names_index_path():
    text = _manual_text("AGENTS.md")
    assert "project/SKILLS.md" in text
    assert "project/skills/SKILLS.md" in text
    # ambiguous legacy sentence is retired
    assert "The index with load tiers is in SKILLS.md" not in text


def test_skills_md_declares_its_own_location():
    text = _manual_text("SKILLS.md")
    assert "project/SKILLS.md" in text
    assert "project/skills/SKILLS.md" in text
    # how-to step names the exact per-skill path
    assert "project/skills/<name>/SKILL.md" in text


def test_instructions_and_readme_name_index_path():
    assert "project/SKILLS.md" in _manual_text("INSTRUCTIONS.md")
    assert "project/skills/<name>/SKILL.md" in _manual_text("INSTRUCTIONS.md")
    assert "project/SKILLS.md" in _manual_text("README.md")
    assert "project/skills/SKILLS.md" in _manual_text("README.md")


# ── 2. TASKS.md references only skills that exist ──────────────────────────


def test_tasks_md_references_live_skills_only():
    text = _manual_text("TASKS.md")
    for retired in ("fullstack-web-app", "static-landing-page"):
        assert retired not in text, f"TASKS.md still names retired skill {retired}"
    for live in (
        "webdev-readme-fullstack",
        "webdev-readme-static",
        "data-analysis",
    ):
        assert live in text, f"TASKS.md should point build/data tasks at {live}"
        assert (MANUAL / "skills" / live / "SKILL.md").is_file(), (
            f"TASKS.md references {live} but the skill folder is missing"
        )


def test_agents_md_skill_count_matches_disk():
    text = _manual_text("AGENTS.md")
    on_disk = sorted(
        p.parent.name
        for p in (MANUAL / "skills").glob("*/SKILL.md")
    )
    assert "50 focused playbooks" in text
    assert len(on_disk) == 50, f"manual claims 50 skills, disk has {len(on_disk)}"


def test_skills_index_lists_every_skill_on_disk():
    """The index table and the skills/ folder must stay in lockstep — a
    missing row means the agent never discovers the skill; an extra row
    means it file_reads a folder that does not exist."""
    index = _manual_text("SKILLS.md")
    on_disk = sorted(p.parent.name for p in (MANUAL / "skills").glob("*/SKILL.md"))
    for name in on_disk:
        assert f"| {name} " in index, f"SKILLS.md index missing skill: {name}"


# ── 3. the scaffold materialises both index paths ──────────────────────────


def test_scaffold_carries_both_index_paths():
    from app.infrastructure.external.sandbox.workspace_scaffold import (
        MANUAL_VERSION,
        build_scaffold_script,
        collect_manual_files,
    )

    files = collect_manual_files()
    assert files.get("skills/SKILLS.md") == files.get("SKILLS.md")
    script = build_scaffold_script("/home/runner", files)
    assert "skills/SKILLS.md" in script
    # version tracking lives in the hidden dotfile, not visible manual text
    assert files.get(".manual-version") == str(MANUAL_VERSION)
    assert "manual-version" not in files["AGENTS.md"]
