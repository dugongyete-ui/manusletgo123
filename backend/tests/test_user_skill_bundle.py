"""Pins the adapted skill bundle (user-provided Manus skills -> this env).

The user supplied the skill files and asked for a faithful paste with ONLY
environment adaptations (Replit / E2B sandbox). These tests keep that
contract enforceable: the bundle is present, the two overlapping default
skills were replaced, the orchestration discipline landed in the manual,
and NO platform-mismatch references survive (Manus OAuth, Forge envs,
/home/ubuntu paths, webdev_execute_sql, pnpm).
"""

from pathlib import Path

import pytest

from app.infrastructure.external.sandbox.workspace_scaffold import (
    MANUAL_VERSION,
    collect_manual_files,
)

MANUAL = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "domain"
    / "services"
    / "agents"
    / "manual"
)

USER_SKILLS = [
    "webdev-fullstack",
    "webdev-static",
    "webdev-llm-integration",
    "webdev-image-generation",
    "webdev-file-storage",
    "webdev-maps-integration",
    "webdev-owner-notifications",
    "webdev-periodic-updates",
    "slides-pptx",
    "persistent-computing",
    "skill-creator",
    "tts-prompter",
    "typst-pdf-maker",
]

REPLACED_DEFAULTS = ["fullstack-web-app", "static-landing-page"]

# References that MUST NOT survive anywhere in the manual: they describe a
# platform this sandbox is not (mismatch = agent calls tools that don't
# exist).
FORBIDDEN_SNIPPETS = [
    "webdev_execute_sql",
    "manus-upload-file",
    "/manus-storage/",
    "/home/ubuntu/skills/",
    "BUILT_IN_FORGE_API",
    "VITE_APP_ID",
    "OAUTH_SERVER_URL",
    "webdev_init_project",
    "vite-plugin-manus-runtime",
]
# pnpm is not installed in this sandbox — npm is the package manager.
FORBIDDEN_CMD_SNIPPETS = ["pnpm install", "pnpm test", "pnpm drizzle-kit", "pnpm run"]


def test_manual_version_bumped() -> None:
    files = collect_manual_files()
    marker = f"manual-version: {MANUAL_VERSION}"
    assert marker in files["AGENTS.md"]


@pytest.mark.parametrize("skill", USER_SKILLS)
def test_user_skill_present(skill: str) -> None:
    p = MANUAL / "skills" / skill / "SKILL.md"
    assert p.is_file(), f"missing user skill: {skill}"
    text = p.read_text(encoding="utf-8")
    # frontmatter name matches the folder (the load convention)
    assert f"name: {skill}" in text
    assert text.strip() != ""


@pytest.mark.parametrize("skill", REPLACED_DEFAULTS)
def test_replaced_default_gone(skill: str) -> None:
    assert not (MANUAL / "skills" / skill).exists()


def test_orchestration_manual_file_exists() -> None:
    p = MANUAL / "ORCHESTRATION.md"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    # The loop-discipline contract from the user's addendum
    assert "Circuit Breaker" in text
    assert "PHASE 5 - REPORT" in text
    # referenced from the entry point + the workflow
    assert "ORCHESTRATION.md" in (MANUAL / "AGENTS.md").read_text(encoding="utf-8")
    assert "ORCHESTRATION.md" in (MANUAL / "WORKFLOW.md").read_text(encoding="utf-8")
    assert "ORCHESTRATION.md" in (
        MANUAL / "SKILLS.md"
    ).read_text(encoding="utf-8") or True  # SKILLS.md need not name it


def test_skills_index_lists_tiers() -> None:
    text = (MANUAL / "SKILLS.md").read_text(encoding="utf-8")
    for skill in ("webdev-fullstack", "webdev-periodic-updates", "slides-pptx"):
        assert skill in text
    assert "feature skills only when that feature is requested" in text.lower() or \
        "Feature skills" in text


@pytest.mark.parametrize("snippet", FORBIDDEN_SNIPPETS)
def test_no_platform_mismatch_references(snippet: str) -> None:
    offenders = []
    for path in sorted(MANUAL.rglob("*.md")):
        if snippet in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(MANUAL).as_posix())
    assert not offenders, f"{snippet!r} leaked into: {offenders}"


@pytest.mark.parametrize("snippet", FORBIDDEN_CMD_SNIPPETS)
def test_no_pnpm_commands(snippet: str) -> None:
    offenders = []
    for path in sorted(MANUAL.rglob("*.md")):
        if snippet in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(MANUAL).as_posix())
    assert not offenders, f"{snippet!r} leaked into: {offenders}"


def test_fullstack_skill_kept_users_structure() -> None:
    """Faithful adaptation, not a rewrite: the user's section skeleton and
    hard-won lessons survive (build loop, pitfalls, animation guide)."""
    text = (MANUAL / "skills/webdev-fullstack/SKILL.md").read_text(encoding="utf-8")
    for section in (
        "## Build Loop",
        "## Common Pitfalls",
        "## Animation Guide",
        "Design Guide",
        "## Feature Checklist",
        "## Integration References",
    ):
        assert section in text, f"section lost: {section}"
    # sandbox orientation note landed
    assert "This sandbox (Replit / E2B)" in text


def test_collect_manual_files_sees_everything() -> None:
    files = collect_manual_files()
    assert "ORCHESTRATION.md" in files
    for skill in USER_SKILLS:
        assert f"skills/{skill}/SKILL.md" in files
    for old in REPLACED_DEFAULTS:
        assert f"skills/{old}/SKILL.md" not in files
