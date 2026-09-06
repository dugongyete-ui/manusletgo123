"""Contract tests: a build NEVER starts without reading its skills.

Regression (session d7521d68d5e246a9, 2026-09-06 06:48 "AI Astro"):
the plan's first step said only "Membaca panduan kerja (AGENTS.md)" —
the executor read AGENTS.md, then went straight to npm init / express
skeleton. project/SKILLS.md was never opened, no build skill was ever
read, and the "full stack production website" was a 6-file placeholder.
The fix is a three-gate design:

  GATE 1 (planner)  — the plan's first build step NAMES the skill files
  GATE 2 (executor) — SKILL GATE in the execution system prompt overrides
                      step text: no skill read, no first project file
  GATE 3 (manual)   — AGENTS.md states the read is MANDATORY
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


# ── GATE 1: planner names the skills ────────────────────────────────────────


def test_planner_mandates_named_skill_read():
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    assert "MUST orient AND load the playbook" in CREATE_PLAN_PROMPT
    assert "explicitly names the skill files to read" in CREATE_PLAN_PROMPT
    assert "The executor follows the step text literally" in CREATE_PLAN_PROMPT
    # the self-test line catches a plan that forgot the skills
    assert "does NOT name the skill files to read" in CREATE_PLAN_PROMPT
    # single-file / conversational work is still exempt (no skill tax)
    assert "skip the manual read and the skill read" in CREATE_PLAN_PROMPT


def test_planner_carries_full_skill_cheat_sheet():
    """The planner can only name skills it can see — the whole index
    rides inside the prompt, generated from the manual SKILLS.md."""
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    rows = [l for l in CREATE_PLAN_PROMPT.splitlines() if l.startswith("- ") and " [" in l]
    on_disk = sorted(p.parent.name for p in (MANUAL / "skills").glob("*/SKILL.md"))
    named = {r.split(" [")[0][2:] for r in rows}
    assert named == set(on_disk), (
        f"planner cheat sheet out of sync with disk: "
        f"missing={set(on_disk) - named} extra={named - set(on_disk)}"
    )
    # key routing anchors for website builds are all present
    for skill in (
        "web-design-engineer",
        "webdev-readme-fullstack",
        "webdev-readme-static",
        "webdev-llm-integration",
        "webapp-testing",
        "pptx",
    ):
        assert any(r.startswith(f"- {skill} ") for r in rows), skill


def test_planner_routes_are_format_safe():
    """Injected rows must never carry braces — they travel inside a
    template that is .format()-ed at runtime with {message}."""
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    tail = CREATE_PLAN_PROMPT.split("AVAILABLE SKILLS", 1)[1]
    routes = tail.split("Return format", 1)[0]
    assert "{" not in routes and "}" not in routes
    # and the runtime format still substitutes cleanly
    filled = CREATE_PLAN_PROMPT.format(message="x", attachments="")
    assert "x" in filled


def test_planner_typical_website_routing_is_spelled_out():
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    assert "web-design-engineer" in CREATE_PLAN_PROMPT
    assert "webdev-readme-fullstack or webdev-readme-static" in CREATE_PLAN_PROMPT
    assert "webdev-llm-integration" in CREATE_PLAN_PROMPT


def test_update_plan_folds_skill_read_into_new_build_steps():
    from app.domain.services.prompts.planner import UPDATE_PLAN_PROMPT

    assert "fold" in UPDATE_PLAN_PROMPT
    assert "project/skills/<name>/SKILL.md" in UPDATE_PLAN_PROMPT


# ── GATE 2: executor SKILL GATE overrides step text ─────────────────────────


def test_execution_system_prompt_has_skill_gate():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    assert "SKILL GATE" in EXECUTION_SYSTEM_PROMPT
    assert "overrides step text" in EXECUTION_SYSTEM_PROMPT
    assert "BEFORE writing the first file" in EXECUTION_SYSTEM_PROMPT
    assert "does not mention skills" in EXECUTION_SYSTEM_PROMPT
    assert "read first, then build" in EXECUTION_SYSTEM_PROMPT
    # the gate points at the dual-path index
    assert "project/SKILLS.md" in EXECUTION_SYSTEM_PROMPT
    assert "project/skills/SKILLS.md" in EXECUTION_SYSTEM_PROMPT


# ── GATE 3: the manual itself states MANDATORY ──────────────────────────────


def test_agents_md_skill_read_is_mandatory():
    text = (MANUAL / "AGENTS.md").read_text(encoding="utf-8")
    assert "MANDATORY before the first" in text
    # reading is mandatory AND the work must follow the skill
    assert "the work must then FOLLOW the skill" in text
    # routing combo spelled out so orientation alone can pick skills
    assert "web-design-engineer" in text
    assert "webdev-readme-fullstack" in text
    assert "webdev-readme-static" in text
    assert "webdev-llm-integration" in text


def test_system_prompt_calls_build_skill_read_mandatory():
    from app.domain.services.prompts.system import SYSTEM_PROMPT

    assert "MANDATORY before any matching build" in SYSTEM_PROMPT


def test_marker_matches_scaffold_version():
    from app.infrastructure.external.sandbox.workspace_scaffold import (
        MANUAL_VERSION,
        collect_manual_files,
    )

    files = collect_manual_files()
    text = (MANUAL / "AGENTS.md").read_text(encoding="utf-8")
    # the manual the agent reads is professionally clean: no version text,
    # staleness tracked only by the hidden .manual-version dotfile
    assert "manual-version" not in text
    assert files.get(".manual-version") == str(MANUAL_VERSION)
