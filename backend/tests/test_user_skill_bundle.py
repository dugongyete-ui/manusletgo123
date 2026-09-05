"""Pins the USER-PROVIDED skill bundle (verbatim paste + env adaptation).

The user supplied the skill files and demanded a FAITHFUL paste: their files,
complete, with only (a) Manus -> Dzeck branding, (b) /home/ubuntu paths ->
this workspace, (c) platform tools that don't exist here remapped (pnpm,
webdev_execute_sql, manus-upload-file, Forge envs, OAuth, Maps proxy).
These tests keep that contract enforceable: every user file is present and
COMPLETE (the periodic-updates trim regression is guarded by line count +
section census), the orchestration addendum and the user's communication
design doc landed in the manual, and no platform-mismatch references
survive anywhere.
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
    "web-design-engineer",
    "webdev-readme-fullstack",
    "webdev-readme-static",
    "webdev-llm-integration",
    "webdev-image-generation",
    "webdev-file-storage",
    "webdev-maps-integration",
    "webdev-owner-notifications",
    "webdev-periodic-updates",
    "dzeck-pptx",
    "persistent-computing",
    "skill-creator",
    "tts-prompter",
    "typst-pdf-maker",
]

REPLACED_DEFAULTS = ["fullstack-web-app", "static-landing-page"]
# folder names the previous (over-adapted) install used — must be gone now
OLD_FOLDERS = ["webdev-fullstack", "webdev-static", "slides-pptx"]

# References that MUST NOT survive anywhere in the manual: they describe a
# platform this sandbox is not (mismatch = agent calls tools that don't
# exist). NOTE: "webdev_init_project" is intentionally allowed — it appears
# only inside the user's own frontmatter descriptions, which are pasted
# verbatim per their instruction.
FORBIDDEN_SNIPPETS = [
    "webdev_execute_sql",
    "manus-upload-file",
    "/manus-storage/",
    "/home/ubuntu/skills/",
    "BUILT_IN_FORGE_API",
    "VITE_APP_ID",
    "OAUTH_SERVER_URL",
    "vite-plugin-manus-runtime",
    "packageManager",
]
# pnpm is not installed in this sandbox — npm is the package manager.
FORBIDDEN_CMD_SNIPPETS = ["pnpm install", "pnpm test", "pnpm drizzle-kit", "pnpm run"]

# The user's original line counts — installed files must stay COMPLETE
# (allow small deltas for the honest env-adaptation notes, never a trim).
MIN_LINES = {
    "web-design-engineer": 490,       # user original: 491
    "webdev-readme-fullstack": 840,   # user original: 854
    "webdev-readme-static": 683,      # user original: 693
    "webdev-periodic-updates": 270,   # user original: 275 (was trimmed to 144!)
    "webdev-llm-integration": 145,    # user original: 146
    "dzeck-pptx": 275,                # user original: 279
    "persistent-computing": 95,       # user original: 98
    "skill-creator": 235,             # user original: 236
    "tts-prompter": 245,              # user original: 247
    "typst-pdf-maker": 190,           # user original: 192
}


def _skill_text(skill: str) -> str:
    return (MANUAL / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


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


@pytest.mark.parametrize("skill", REPLACED_DEFAULTS + OLD_FOLDERS)
def test_replaced_default_gone(skill: str) -> None:
    assert not (MANUAL / "skills" / skill).exists()


@pytest.mark.parametrize("skill,min_lines", sorted(MIN_LINES.items()))
def test_user_skill_not_trimmed(skill: str, min_lines: int) -> None:
    """Regression guard: the user's files must be pasted COMPLETE — never
    trimmed to a rewritten digest (the periodic-updates 275 -> 144 trim is
    the exact failure this prevents)."""
    lines = _skill_text(skill).count("\n") + 1
    assert lines >= min_lines, f"{skill}: {lines} lines < {min_lines} (trimmed?)"


def test_periodic_updates_keeps_every_user_section() -> None:
    """The full section census of the user's original (§1-§5c) must survive."""
    text = _skill_text("webdev-periodic-updates")
    for section in (
        "## 1. Pick the right cron type",
        "## 2. Facts (apply to BOTH flavors)",
        "## 3. End-user-driven Heartbeat",
        "## 4. Variants",
        "### 4a. Project-level Heartbeat",
        "### 4b. AGENT cron",
        "### 4c. Owner UI",
        "## 5. References",
        "### 5a. Site SDK",
        "### 5b. Sandbox CLI",
        "### 5c. Legacy projects",
        "createHeartbeatJob",
        "HeartbeatJobInfo",
        "buildCronUser",
        "CRON_OPEN_ID_PREFIX",
    ):
        assert section in text, f"section lost: {section}"


def test_orchestration_manual_file_exists() -> None:
    p = MANUAL / "ORCHESTRATION.md"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    # The loop-discipline contract from the user's addendum — pasted verbatim
    # (original H1 restored, not renamed to the file's own name)
    assert text.startswith("# Agent Orchestration Addendum")
    assert "Circuit Breaker" in text
    assert "PHASE 5 - REPORT" in text
    # referenced from the entry point + the workflow
    assert "ORCHESTRATION.md" in (MANUAL / "AGENTS.md").read_text(encoding="utf-8")
    assert "ORCHESTRATION.md" in (MANUAL / "WORKFLOW.md").read_text(encoding="utf-8")


def test_user_communication_design_doc_pasted() -> None:
    """The user's Rancangan (natural chat communication design) must be in
    the manual root, verbatim, and discoverable from AGENTS.md."""
    p = MANUAL / "Rancangan_Notifikasi_User_melalui_Chat.md"
    assert p.is_file(), "user's communication design doc missing from manual"
    text = p.read_text(encoding="utf-8")
    for marker in (
        "user_communication_module",
        "when_to_notify",
        "when_to_ask",
        "message_content",
        "naturalness_rules",
        "timing_and_frequency",
        "communication_decision_algorithm",
    ):
        assert marker in text, f"design doc section lost: {marker}"
    assert "Rancangan_Notifikasi_User_melalui_Chat.md" in (
        MANUAL / "AGENTS.md"
    ).read_text(encoding="utf-8")


def test_skills_index_lists_tiers() -> None:
    text = (MANUAL / "SKILLS.md").read_text(encoding="utf-8")
    for skill in (
        "web-design-engineer",
        "webdev-readme-fullstack",
        "webdev-readme-static",
        "webdev-periodic-updates",
        "dzeck-pptx",
    ):
        assert skill in text, f"SKILLS.md missing: {skill}"
    assert "Feature skills" in text


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
    text = _skill_text("webdev-readme-fullstack")
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
    # the user's integration table survives COMPLETE (no filtered rows)
    for row in (
        "webdev-llm-integration",
        "webdev-voice-transcription",
        "webdev-image-generation",
        "webdev-file-storage",
        "webdev-maps-integration",
        "webdev-data-api",
        "webdev-owner-notifications",
        "webdev-periodic-updates",
        "webdev-custom-dockerfile",
        "webdev-ssr-conversion",
    ):
        assert row in text, f"integration table row lost: {row}"


def test_collect_manual_files_sees_everything() -> None:
    files = collect_manual_files()
    assert "ORCHESTRATION.md" in files
    assert "Rancangan_Notifikasi_User_melalui_Chat.md" in files
    for skill in USER_SKILLS:
        assert f"skills/{skill}/SKILL.md" in files
    for old in REPLACED_DEFAULTS + OLD_FOLDERS:
        assert f"skills/{old}/SKILL.md" not in files
