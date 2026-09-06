"""Contract tests: the FULLSTACK production bar (v0/Lovable doctrine).

Regression (session 2b3a406902e04fdf "AI Astroni"): the skill gates
worked — AGENTS.md + all 4 build skills were read — but the executor then
ignored the skill's template blueprint and took the lazy path (plain
Express + Vite, in-memory/no DB, no auth, no real LLM call). The build
came out "simple banget" instead of the v0/Replit-Agent/Lovable quality
the user expects. Root cause: nothing in the prompts FORBADE the
shortcut — the skill described the template, but a minimal build also
"satisfied" the step text.

Fix: an explicit FULLSTACK BAR in all three prompt layers + the
webdev-readme-fullstack skill itself, imported from the
x1xhlol/system-prompts-and-models-of-ai-tools corpus (v0 "Data
Persistence and Storage" + "Color System"/"Typography", Lovable design
doctrine).
"""

import re
from pathlib import Path

MANUAL = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "domain"
    / "services"
    / "agents"
    / "manual"
)


def _flat(text: str) -> str:
    """Collapse whitespace so wrapped lines still match."""
    return re.sub(r"\s+", " ", text)

FORBIDDEN_SHORTCUTS = (
    "NEVER localStorage",      # v0: never client-side storage for app data
    "canned",                  # never random/canned AI responses
    "mock auth",               # v0: never mock authentication
)
REQUIRED_BARS = (
    "bcrypt",
    "drizzle",
    "tRPC",
    "HTTP-only",
    "end-to-end",
)


# ── executor carries the absolute bar ───────────────────────────────────────


def test_execution_prompt_has_fullstack_bar():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    p = _flat(EXECUTION_SYSTEM_PROMPT)
    assert "FULLSTACK BAR" in p
    assert "production-quality bar" in p
    assert "You are not making a demo; you are shipping the product" in p
    for probe in FORBIDDEN_SHORTCUTS:
        assert probe in p, probe
    for probe in REQUIRED_BARS + ("FULLSTACK BAR",):
        assert probe in p, probe


def test_execution_prompt_has_v0_design_bar():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    assert "DESIGN BAR" in EXECUTION_SYSTEM_PROMPT
    assert "3-5 colors" in EXECUTION_SYSTEM_PROMPT
    assert "Max 2 font families" in EXECUTION_SYSTEM_PROMPT
    assert "mobile-first" in EXECUTION_SYSTEM_PROMPT
    assert "No placeholder images" in EXECUTION_SYSTEM_PROMPT


# ── planner plans the full application, not a 2-phase sketch ───────────────


def test_planner_makes_every_website_request_fullstack():
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    assert "EVERY website/app request is a FULLSTACK build" in CREATE_PLAN_PROMPT
    assert "frontend + backend + database + auth" in CREATE_PLAN_PROMPT
    # the full phase coverage is spelled out
    for phase in ("database schema", "core feature end-to-end", "browser verification"):
        assert phase in CREATE_PLAN_PROMPT, phase
    assert "toy demo" in CREATE_PLAN_PROMPT
    # static exception stays explicit
    assert "static page" in CREATE_PLAN_PROMPT


# ── system prompt sets the product expectation ─────────────────────────────


def test_system_prompt_states_product_level():
    from app.domain.services.prompts.system import SYSTEM_PROMPT

    assert "FULLSTACK BAR" in SYSTEM_PROMPT
    assert "v0/Lovable/Replit Agent" in SYSTEM_PROMPT
    assert "never canned responses" in SYSTEM_PROMPT
    assert "not tutorial demos" in SYSTEM_PROMPT


# ── the skill itself opens with the non-negotiable bar ─────────────────────


def test_fullstack_skill_carries_non_negotiable_bar():
    text = _flat(
        (MANUAL / "skills" / "webdev-readme-fullstack" / "SKILL.md").read_text(
            encoding="utf-8"
        )
    )
    assert "Non-negotiable build bar" in text
    assert "build FAILURE" in text
    for probe in FORBIDDEN_SHORTCUTS + ("in-memory", "placeholder"):
        assert probe in text, probe
    for probe in REQUIRED_BARS:
        assert probe in text, probe
    # it still carries the original template blueprint below the bar
    assert "React 19 + Tailwind 4 + Express 4 + tRPC 11" in text
    assert "drizzle-orm + better-sqlite3" in text


# ── manual files carry the doctrine ────────────────────────────────────────


def test_coding_and_design_manuals_carry_the_doctrine():
    coding = _flat((MANUAL / "CODING.md").read_text(encoding="utf-8"))
    assert "Fullstack bar" in coding
    assert "NEVER localStorage" in coding
    assert "canned responses" in coding
    design = _flat((MANUAL / "DESIGN.md").read_text(encoding="utf-8"))
    assert "Web design bar (v0 doctrine)" in design
    assert "3-5 colors" in design
    assert "No placeholder images" in design


def test_agents_md_names_the_fullstack_bar():
    text = _flat((MANUAL / "AGENTS.md").read_text(encoding="utf-8"))
    assert "FULLSTACK BAR" in text
    assert "v0/Lovable production bar" in text
    assert "never canned responses" in text
