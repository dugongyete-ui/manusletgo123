"""Contract tests: the PRODUCT QUALITY BAR + SKILL COMPLIANCE doctrine.

History: Task 56 added a FULLSTACK BAR (v0/Lovable doctrine) after
session 2b3a406902e04fdf produced a lazy build. The user then found
that bar TOO aggressive ("hardcore"): it forced the AI-chat fullstack
pattern onto every website request and read unnaturally. Task 57
replaced it with a scoped, natural doctrine:

- PRODUCT QUALITY BAR — build what was asked, at product quality.
  App-like requests (accounts, persistent data, chat, dashboard) get
  the fullstack template; content-style requests (company profile,
  landing, portfolio) get a polished front-end with NO bolted-on
  backend; AI features only when requested.
- SKILL COMPLIANCE — reading a skill is step zero; the deliverable
  must then FOLLOW it (workflow, structure, acceptance criteria). A
  pptx built outside the pptx skill's pipeline is not a finished pptx.
- The visible manual carries NO version text ("manual-version" was
  unprofessional) — staleness is tracked by the hidden
  project/.manual-version dotfile.
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
    "never localStorage",     # never client-side storage for app data
    "canned",                 # never canned AI responses
    "mock auth",              # never mock authentication
)
REQUIRED_BARS = (
    "bcrypt",
    "drizzle",
    "tRPC",
    "HTTP-only",
    "end-to-end",
)
SCOPE_RULES = (
    "app-like requests",
    "Content-style requests",
    "webdev-readme-static",
    "only when the request includes them",
)


# ── executor: scoped quality bar + skill compliance ─────────────────────────


def test_execution_prompt_has_product_quality_bar():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    p = _flat(EXECUTION_SYSTEM_PROMPT)
    assert "PRODUCT QUALITY BAR" in p
    assert "build what was asked, at product quality" in p
    assert "Never add machinery the request never asked for" in p
    for probe in FORBIDDEN_SHORTCUTS + SCOPE_RULES:
        assert probe in p, probe
    for probe in REQUIRED_BARS:
        assert probe in p, probe


def test_execution_prompt_has_skill_compliance():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    p = _flat(EXECUTION_SYSTEM_PROMPT)
    assert "SKILL COMPLIANCE" in p
    assert "a read skill is a contract, not a checkbox" in p
    assert "the work must then FOLLOW that skill" in p
    assert "the step is not done while the skill is violated" in p
    # the pptx example the user called out is spelled out
    assert "outside the pptx skill's pipeline" in p
    # conflict rule: the skill wins over contradicting step text
    assert "CONFLICT RULE" in p
    assert "the SKILL wins" in p
    assert "do not blindly execute a plan step that violates" in p


def test_execution_prompt_forbids_server_databases():
    """No PostgreSQL/MySQL daemon exists in the sandbox — prisma-style
    server-DB migrations must be forbidden up front."""
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    p = _flat(EXECUTION_SYSTEM_PROMPT)
    assert "NO database server" in p
    assert "will fail forever" in p
    assert "file-based SQLite (drizzle) is the required" in p


def test_execution_prompt_counts_command_variants_as_same_failure():
    """Circuit breaker hardening: output errors count as failures even
    when the tool call 'succeeded'; flag/path variants of one failing
    command are the SAME problem."""
    from app.domain.services.prompts.execution import EXECUTION_PROMPT

    p = _flat(EXECUTION_PROMPT)
    assert "VARIANTS of the same failing command" in p
    assert "are the SAME problem" in p
    assert "After two or three failing variants, stop retrying" in p


def test_execution_prompt_has_v0_design_bar():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    assert "DESIGN BAR" in EXECUTION_SYSTEM_PROMPT
    assert "3-5 colors" in EXECUTION_SYSTEM_PROMPT
    assert "Max 2 font families" in EXECUTION_SYSTEM_PROMPT
    assert "mobile-first" in EXECUTION_SYSTEM_PROMPT
    assert "No placeholder images" in EXECUTION_SYSTEM_PROMPT


# ── planner: the plan matches the request, not a fixed template ────────────


def test_planner_scales_the_build_to_the_request():
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    p = _flat(CREATE_PLAN_PROMPT)
    assert "match the plan to what the request actually needs" in p
    # app-like → fullstack with the real phases spelled out
    assert "FULLSTACK builds" in p
    assert "frontend + backend + database + auth" in p
    for phase in ("database schema", "core feature end-to-end", "browser verification"):
        assert phase in p, phase
    # content-style → static template, never inflated
    assert "webdev-readme-static" in p
    assert "do NOT bolt a database, auth, or AI features" in p
    assert "static page" in p
    assert "toy demo" in p
    # AI features load their skill ONLY when requested
    assert "only when the request actually includes them" in p
    # the verify phase checks the deliverable against each skill
    assert "verifies the deliverable against each loaded skill's requirements" in p


def test_planner_must_mirror_the_skills_stack():
    """Session 1303b902a2d54516: the plan read the fullstack skill, then
    invented Next.js+Prisma+PostgreSQL — a stack with no DB server that
    burned the whole budget in a prisma-migrate retry spiral. The plan
    must use the named skill's stack verbatim and never plan a DB
    server that does not exist in the sandbox."""
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    p = _flat(CREATE_PLAN_PROMPT)
    assert "prescribed stack VERBATIM" in p
    assert "Next.js/Prisma/PostgreSQL are NOT this workspace's template" in p
    assert "NO database server" in p
    assert "server-DB migrations will fail forever" in p
    assert "file-based SQLite unless the user provides a real DATABASE_URL" in p


# ── system prompt: product expectation + compliance ─────────────────────────


def test_system_prompt_states_product_level():
    from app.domain.services.prompts.system import SYSTEM_PROMPT

    p = _flat(SYSTEM_PROMPT)
    assert "product-quality bar scaled to the request" in p
    assert "v0/Lovable/Replit Agent" in p
    assert "never canned responses" in p
    assert "not tutorial demos" in p
    assert "Never add machinery the request never asked for" in p
    # compliance sentence lives in the system prompt too
    assert "the work must then FOLLOW them" in p


# ── the fullstack skill: scoped bar, calm language ──────────────────────────


def test_fullstack_skill_carries_scoped_build_bar():
    text = _flat(
        (MANUAL / "skills" / "webdev-readme-fullstack" / "SKILL.md").read_text(
            encoding="utf-8"
        )
    )
    assert "Build bar for app-like requests" in text
    assert "webdev-readme-static" in text  # content sites routed away
    assert "NO database server" in text  # no PostgreSQL/MySQL daemon here
    assert "Prisma + PostgreSQL is NOT this template" in text
    for probe in ("localStorage", "in-memory", "placeholder"):
        assert probe in text, probe
    for probe in REQUIRED_BARS:
        assert probe in text, probe
    # it still carries the original template blueprint below the bar
    assert "React 19 + Tailwind 4 + Express 4 + tRPC 11" in text
    assert "drizzle-orm + better-sqlite3" in text


# ── manual files carry the doctrine, scoped and natural ────────────────────


def test_coding_and_design_manuals_carry_the_doctrine():
    coding = _flat((MANUAL / "CODING.md").read_text(encoding="utf-8"))
    assert "Build bar for web apps" in coding
    assert "Scale the architecture to what the request actually needs" in coding
    assert "never localStorage" in coding
    assert "canned responses" in coding
    assert "webdev-readme-static" in coding
    assert "NO database server" in coding
    design = _flat((MANUAL / "DESIGN.md").read_text(encoding="utf-8"))
    assert "Web design bar (v0 doctrine)" in design
    assert "3-5 colors" in design
    assert "No placeholder images" in design


def test_agents_md_states_scope_and_compliance():
    text = _flat((MANUAL / "AGENTS.md").read_text(encoding="utf-8"))
    assert "the work must then FOLLOW the skill" in text
    assert "no database server" in text
    assert "the skill wins" in text
    assert "webdev-readme-static" in text
    assert "webdev-readme-fullstack" in text
    assert "never canned responses" in text


# ── the visible manual is professionally clean: no version text ─────────────


def test_no_version_text_in_visible_manual():
    """The user called the old 'manual-version: 12' line unprofessional —
    staleness tracking must stay in the hidden dotfile only."""
    from app.infrastructure.external.sandbox.workspace_scaffold import (
        collect_manual_files,
    )

    files = collect_manual_files()
    assert files.get(".manual-version"), "hidden version file missing"
    for rel, content in files.items():
        if rel.endswith(".md"):
            assert "manual-version" not in content, f"version text leaked into {rel}"
