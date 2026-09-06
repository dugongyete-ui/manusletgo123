"""Scaffold the per-user workspace operating manual (project/ folder).

Every user workspace ships with an operating manual under
``{user_home}/project/``:

    project/AGENTS.md           entry point — how the agent works
    project/SOUL.md ...         behaviour core (identity, rules, workflow…)
    project/skills/<name>/SKILL.md   focused playbooks

The source of truth is the repo directory
``backend/app/domain/services/agents/manual/`` (plain .md files, git
diffable). This module copies it INTO the sandbox at user-home setup —
one code path for both providers (shared Replit container and E2B microVM)
because it only speaks the sandbox protocol (file_write + exec_command):

  1. quick marker check — file_read the hidden project/.manual-version
     file; if it matches the current version, everything is already in
     place (fast path: one sandbox call). The manual files themselves
     carry NO version text — the agent-facing AGENTS.md stays clean; the
     hidden dotfile is the only staleness marker.
  2. otherwise: build ONE self-contained python script embedding all
     manual files as JSON, write it to /tmp (a shared-allowed scratch
     path), execute it. The script is idempotent and rewrites the manual
     only when the version differs.

Failure policy: log + continue. A missing manual must never break task
creation — the system prompt references it, the agent degrades gracefully
("file not found" reads as an honest limit, not a crash).
"""

import base64
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# backend/app/infrastructure/external/sandbox/workspace_scaffold.py
#   -> backend/app/domain/services/agents/manual/
_MANUAL_DIR = (
    Path(__file__).resolve().parents[3]
    / "domain"
    / "services"
    / "agents"
    / "manual"
)

MANUAL_VERSION = 13
_VERSION_FILE = ".manual-version"          # hidden — never visible manual text
_VERSION_VALUE = str(MANUAL_VERSION)
_SCRIPT_PATH = "/tmp/dzeck_ws_manual_scaffold.py"
_SESSION_ID = "ws-manual-scaffold"

# Binary assets up to this size travel base64-embedded in the scaffold
# script ("b64:" prefix). Anything larger (e.g. the canvas-design font
# pack) is skipped — the text scaffold must stay cheap for every fresh
# workspace.
_MAX_BINARY_BYTES = 512 * 1024


def collect_manual_files() -> Dict[str, str]:
    """{relative_posix_path: content} for every manual file (sorted, stable).

    The skills index SKILLS.md is emitted TWICE on purpose: once at the
    manual root (canonical, next to AGENTS.md) and once inside skills/ —
    agents reading prose like "skills/ contains playbooks, the index is
    SKILLS.md" reliably guess project/skills/SKILLS.md, so both paths must
    resolve to the same content (the scaffold regenerates them together,
    they can never drift).
    """
    files: Dict[str, str] = {}
    if not _MANUAL_DIR.is_dir():
        logger.warning(
            "Workspace manual source dir missing: %s — scaffolding skipped",
            _MANUAL_DIR,
        )
        return files
    for path in sorted(_MANUAL_DIR.rglob("*")):
        if not path.is_file() or path.name == "__init__.py":
            continue
        rel = path.relative_to(_MANUAL_DIR).as_posix()
        try:
            files[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # binary asset (tarball, PDF showcase, …) — embed small ones
            try:
                raw = path.read_bytes()
                if len(raw) > _MAX_BINARY_BYTES:
                    logger.warning(
                        "Workspace manual: skip large binary %s (%d bytes)",
                        rel, len(raw),
                    )
                    continue
                files[rel] = "b64:" + base64.b64encode(raw).decode("ascii")
            except Exception as exc:
                logger.warning(
                    "Workspace manual: skip unreadable file %s: %s", rel, exc
                )
        except Exception as exc:
            logger.warning("Workspace manual: skip unreadable file %s: %s", rel, exc)
    # duplicate the skills index so BOTH project/SKILLS.md and
    # project/skills/SKILLS.md resolve (see docstring)
    if "SKILLS.md" in files:
        files["skills/SKILLS.md"] = files["SKILLS.md"]
    # hidden staleness marker — the visible manual (AGENTS.md etc.) is
    # kept free of version text (professional, user-facing); freshness
    # is tracked by this dotfile alone
    files[_VERSION_FILE] = _VERSION_VALUE
    return files


_ROOT_FILES_CACHE: list = []


def manual_root_filenames() -> frozenset:
    """Filenames of the manual's root-level files (no subdirs), cached.

    The delivery guards use this to separate the manual's own files
    (project/AGENTS.md, project/WORKFLOW.md, …) from task output that
    happens to sit in project/ — a build's own project/report.md is NOT
    in this set and stays deliverable. Content is never read here: only
    names, so the cache is cheap and safe to build lazily.
    """
    global _ROOT_FILES_CACHE
    if not _ROOT_FILES_CACHE:
        names = []
        if _MANUAL_DIR.is_dir():
            for path in _MANUAL_DIR.iterdir():
                if path.is_file() and path.name != "__init__.py":
                    names.append(path.name)
        _ROOT_FILES_CACHE = sorted(names)
    return frozenset(_ROOT_FILES_CACHE)


def build_scaffold_script(user_home: str, files: Dict[str, str]) -> str:
    """Self-contained python script that (re)writes the manual into the
    sandbox. Idempotent via the hidden .manual-version file.

    It also PRUNES stale skill folders: any directory under
    project/skills/ that is not in the manifest gets removed, so the
    sandbox exactly mirrors the current manual (skills/ is 100%
    scaffold-owned — AGENTS.md forbids task output there). Skill folders
    dropped from the manual (e.g. dzeck-pptx) must not linger and mislead
    the agent into reading outdated playbooks.
    """
    payload = json.dumps(files, ensure_ascii=False)
    return (
        "import base64, json, os, shutil\n"
        f"FILES = json.loads({payload!r})\n"
        f"TARGET = {user_home.rstrip('/') + '/project'!r}\n"
        f"VERSION = {_VERSION_VALUE!r}\n"
        f"marker_path = os.path.join(TARGET, {_VERSION_FILE!r})\n"
        "try:\n"
        "    with open(marker_path, encoding='utf-8') as f:\n"
        "        existing = f.read().strip()\n"
        "except Exception:\n"
        "    existing = ''\n"
        "if existing == VERSION:\n"
        "    print('MANUAL_SKIP', len(FILES))\n"
        "else:\n"
        "    n = 0\n"
        "    for rel, content in FILES.items():\n"
        "        p = os.path.join(TARGET, rel)\n"
        "        d = os.path.dirname(p)\n"
        "        if d:\n"
        "            os.makedirs(d, exist_ok=True)\n"
        "        if isinstance(content, str) and content.startswith('b64:'):\n"
        "            with open(p, 'wb') as f:\n"
        "                f.write(base64.b64decode(content[4:]))\n"
        "        else:\n"
        "            with open(p, 'w', encoding='utf-8') as f:\n"
        "                f.write(content)\n"
        "        n += 1\n"
        "    expected = {rel.split('/')[1] for rel in FILES\n"
        "                if rel.startswith('skills/') and '/' in rel[len('skills/'):]}\n"
        "    skills_dir = os.path.join(TARGET, 'skills')\n"
        "    pruned = 0\n"
        "    if os.path.isdir(skills_dir):\n"
        "        for name in os.listdir(skills_dir):\n"
        "            full = os.path.join(skills_dir, name)\n"
        "            if os.path.isdir(full) and name not in expected:\n"
        "                shutil.rmtree(full, ignore_errors=True)\n"
        "                pruned += 1\n"
        "    print('MANUAL_WROTE', n, 'MANUAL_PRUNED', pruned)\n"
    )


def _version_current(result) -> bool:
    if not (result and getattr(result, "success", False)):
        return False
    data = getattr(result, "data", None)
    content = ""
    if isinstance(data, dict):
        content = data.get("content", "") or ""
    return content.strip() == _VERSION_VALUE


async def scaffold_workspace_manual(sandbox, user_home: Optional[str]) -> bool:
    """Ensure {user_home}/project/ exists with the current manual version.

    Returns True when the manual is present (already or freshly written).
    Never raises — failures degrade to a missing manual.
    """
    try:
        if not user_home:
            return False
        files = collect_manual_files()
        if not files or "AGENTS.md" not in files:
            return False

        marker_file = f"{user_home.rstrip('/')}/project/{_VERSION_FILE}"
        try:
            existing = await sandbox.file_read(marker_file, 1, 2)
            if _version_current(existing):
                return True  # fast path: up to date
        except Exception:
            pass  # first scaffold (or read unsupported) — fall through

        script = build_scaffold_script(user_home, files)
        write = await sandbox.file_write(_SCRIPT_PATH, script)
        if not (write and getattr(write, "success", False)):
            logger.warning(
                "Workspace manual: could not stage scaffold script — skipped"
            )
            return False

        result = await sandbox.exec_command(
            _SESSION_ID,
            user_home,
            f"python3 {_SCRIPT_PATH} && rm -f {_SCRIPT_PATH}",
        )
        ok = bool(result and getattr(result, "success", False))
        output = ""
        if ok:
            data = getattr(result, "data", None)
            output = data.get("output", "") if isinstance(data, dict) else ""
        if ok and ("MANUAL_WROTE" in output or "MANUAL_SKIP" in output):
            logger.info(
                "Workspace manual scaffolded for %s (%d files, version %d)",
                user_home, len(files), MANUAL_VERSION,
            )
            return True

        # exec sessions report "still running" after ~5s — the write may
        # still complete; verify via the version file before declaring
        # failure.
        try:
            final = await sandbox.file_read(marker_file, 1, 2)
            if _version_current(final):
                logger.info("Workspace manual verified after slow exec")
                return True
        except Exception:
            pass
        logger.warning(
            "Workspace manual scaffold exec failed for %s: %s",
            user_home,
            (output or getattr(result, "message", ""))[:200] if result else "no result",
        )
        return False
    except Exception as exc:
        logger.warning("Workspace manual scaffold error: %s", exc)
        return False
