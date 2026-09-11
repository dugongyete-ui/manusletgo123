"""Contract tests for the Task 59 skill import (Manus skills zip → Dzeck).

The zip (manus-skills-2026-09-11.zip) shipped 37 skill folders. 13 were
already installed in adapted form (kept), 13 were skipped as irrelevant
without platform tooling (Manus API/config, gws CLI, workflow MCP, slides
MCP, builtin-llm proxy, data APIs, API Hub, Manus OAuth, music tool,
dockerfile deploy, Aug-2026 service-change support, automation routing),
and 11 were installed fresh:

    deep-research, finance-pro-playbooks, game-dev, image-processing,
    imagegen, read-special-images, technical-writing,
    webdev-readme-mobile, webdev-readme-mobile-backend,
    webdev-ssr-conversion, webdev-voice-transcription

These tests pin the import quality bar:
1. the 11 skills exist, frontmatter name == folder name;
2. NO case-insensitive "manus" anywhere in the whole manual tree — a
   leaked platform name in agent-facing docs is both unprofessional and
   a routing hazard (the agent may try to call manus-* tooling);
3. no platform tokens the sandbox cannot honour (BUILT_IN_FORGE env vars,
   webdev_* managed tools, /manus-storage/, /home/ubuntu/skills layout);
4. every skill a new SKILL.md references by path actually exists on disk
   (no dangling cross-references to skipped skills);
5. the planner-visible index (SKILLS.md) and system prompt carry the new
   count (61).
"""

from pathlib import Path
import re

BACKEND = Path(__file__).resolve().parents[1]
MANUAL = BACKEND / "app" / "domain" / "services" / "agents" / "manual"

IMPORTED = [
    "deep-research",
    "finance-pro-playbooks",
    "game-dev",
    "image-processing",
    "imagegen",
    "read-special-images",
    "technical-writing",
    "webdev-readme-mobile",
    "webdev-readme-mobile-backend",
    "webdev-ssr-conversion",
    "webdev-voice-transcription",
]

# Tokens that only exist on the Manus platform — their presence in the
# manual would make the agent call tooling this sandbox does not have.
PLATFORM_TOKENS = [
    "BUILT_IN_FORGE",
    "VITE_APP_ID",
    "OAUTH_SERVER_URL",
    "VITE_OAUTH_PORTAL_URL",
    "OWNER_OPEN_ID",
    "manus-storage",
    "manus-upload-file",
    "manus-webdev",
    "manus-logs",
    "webdev_execute_sql",
    "webdev_init_project",
    "webdev_add_feature",
    "webdev_restart_server",
    "webdev_take_screenshot",
    "webdev_save_checkpoint",
    "webdev_request_secrets",
    "manus.space",
    "api.manus.ai",
    "/home/ubuntu/skills",
    "/home/ubuntu/manus-slides",
]

# Skills the import deliberately skipped — nothing may reference them.
SKIPPED = [
    "manus-api",
    "manus-config",
    "gws-best-practices",
    "workflow-composer",
    "webdev-custom-dockerfile",
    "webdev-data-api",
    "webdev-manus-oauth",
    "builtin-llm-models",
    "data-api",
    "music-prompter",
    "slides",
    "automation-and-scheduling",
    "data-backup-restoration",
]


def _all_manual_files():
    for p in MANUAL.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".md", ".py", ".sh", ".ts", ".tsx", ".yaml", ".yml", ".txt", ".json"}:
            yield p


def test_imported_skills_exist_with_matching_frontmatter():
    for name in IMPORTED:
        skill = MANUAL / "skills" / name / "SKILL.md"
        assert skill.is_file(), f"missing imported skill: {name}"
        m = re.match(r"^---\nname:\s*([A-Za-z0-9_-]+)", skill.read_text(encoding="utf-8"))
        assert m, f"{name}: no frontmatter name"
        assert m.group(1) == name, f"{name}: frontmatter name is {m.group(1)!r}"


def test_no_manus_mentions_anywhere_in_manual():
    """The brand name must never leak into agent-facing manual text."""
    leaks = [
        str(p.relative_to(MANUAL))
        for p in _all_manual_files()
        if "manus" in p.read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert not leaks, f"manus mentions leaked into: {leaks}"


def test_no_platform_tokens_in_imported_skills():
    for name in IMPORTED:
        for p in (MANUAL / "skills" / name).rglob("*"):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for tok in PLATFORM_TOKENS:
                assert tok not in text, f"{name}/{p.name} still references {tok!r}"


def test_no_references_to_skipped_skills():
    """A reference to a skipped skill is a dead path the agent will
    file_read and fail on. Only skill-shaped references count (backticked
    name or skills/<name>/ path) — plain English words like "slides" in
    "apply themes to slides, docs" must not trip this."""
    for p in _all_manual_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for skipped in SKIPPED:
            assert f"`{skipped}`" not in text, (
                f"{p.relative_to(MANUAL)} references skipped skill {skipped}"
            )
            assert f"skills/{skipped}/" not in text, (
                f"{p.relative_to(MANUAL)} references skipped skill path {skipped}"
            )


def test_game_dev_adaptations_file_renamed():
    """game-dev's adaptation layer must carry the Dzeck name and its
    overrides must point at sandbox equivalents, not Manus WebDev."""
    adapt = MANUAL / "skills" / "game-dev" / "references" / "dzeck-adaptations.md"
    assert adapt.is_file(), "dzeck-adaptations.md missing"
    assert not (MANUAL / "skills" / "game-dev" / "references" / "manus-adaptations.md").exists()
    text = adapt.read_text(encoding="utf-8")
    assert "image_generate" in text, "art step must route to image_generate"
    assert "packaging-delivery" in text, "delivery must route to the zip skill"
    assert "webdev-readme-static" in text, "host shell must route to the static scaffold skill"


def test_mobile_backend_doctrine_matches_sandbox():
    """mobile-backend must teach the sandbox reality: SQLite, user-supplied
    keys, local-disk storage — not platform-injected anything."""
    text = (MANUAL / "skills" / "webdev-readme-mobile-backend" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "This sandbox (Replit / E2B)" in text
    assert "SQLite" in text
    assert "LLM_API_KEY" in text
    assert "`/uploads/`" in text
    # the MySQL listings remain as pattern reference, not as the required DB
    assert "pattern reference" in text


def test_index_and_prompt_carry_new_count():
    index = (MANUAL / "SKILLS.md").read_text(encoding="utf-8")
    assert "61 playbooks" in index
    for name in IMPORTED:
        assert f"| {name} " in index, f"SKILLS.md index missing {name}"

    from app.domain.services.prompts.system import SYSTEM_PROMPT

    assert "61 focused playbooks" in SYSTEM_PROMPT


def test_scaffold_version_bumped():
    from app.infrastructure.external.sandbox.workspace_scaffold import (
        MANUAL_VERSION,
        collect_manual_files,
    )

    assert MANUAL_VERSION == 15
    files = collect_manual_files()
    for name in IMPORTED:
        assert f"skills/{name}/SKILL.md" in files, f"scaffold missing {name}"
