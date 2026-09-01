"""Deterministic delivery hygiene nets — the final merge choke point.

Why this exists
---------------
Live incident (session fbfcb72d, 2026-09-01): the model's ChatGPT-clone
build was auto-bundled into ONE ``project.zip`` — but the artifact sweep
had ALSO collected 14 files the model never listed: Vite template scrap
(``counter.ts``/``main.ts``/``style.css``), build outputs
(``client/dist/**``, ``server/dist/index.js``), and runtime junk
(``server.pid``, ``server.log``, a 200KB ``package-lock.json``). None of
them were members of the zip, so the ZIP-only member filter correctly
kept them — and the user received 16 cards next to the archive
("kalo sudah dibungkus jadi zip, ngapain semuanya dikirim juga").

Two nets close the gap, both fail-open:

1. ``drop_junk_attachments`` — HARD junk never reaches the user, whether
   the model listed it or the sweep found it: pid/log/lockfiles, ``.env``,
   bytecode, caches, VCS internals. These are never deliverables.

2. ``fold_loose_files_into_archive`` — when a .zip leads the delivery,
   every remaining loose NON-document file is appended INTO that archive
   (collision-safe basenames) and removed from the card list. The user
   receives the archive + at most standalone documents (.md/.txt/...).
   Nothing is lost — the files live inside the zip instead of spamming
   the chat. When the append fails the loose files stay (fail-open).
"""

from __future__ import annotations

import logging
import shlex
from typing import List

from app.domain.models.file import FileInfo
from app.domain.services.agents.auto_bundle import _DOC_EXTS, _EXCLUDE_DIRS

logger = logging.getLogger(__name__)

# Lockfiles are build plumbing, not deliverables (a 200KB package-lock.json
# shipped as a card next to the archive in the live incident).
_JUNK_BASENAMES = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "poetry.lock", "pipfile.lock", "composer.lock", "gemfile.lock",
    ".env", ".ds_store", ".npmrc", ".python-version", ".tool-versions",
})

# Extensions that mark runtime/build junk in ANY directory.
_JUNK_EXTS = (".pid", ".log", ".pyc", ".pyo", ".tsbuildinfo", ".tmp")

# Directory SEGMENTS that mark junk anywhere in the path (mirrors
# auto_bundle._EXCLUDE_DIRS plus tooling caches).
_JUNK_DIR_SEGMENTS = frozenset(_EXCLUDE_DIRS) | {
    ".idea", ".vscode", ".turbo", ".parcel-cache",
}

_FOLD_SCRIPT = (
    "import os, zipfile\n"
    "zip_path, files = {zip_path!r}, {files!r}\n"
    "with zipfile.ZipFile(zip_path) as z:\n"
    "    existing = {{os.path.basename(n) for n in z.namelist()"
    " if not n.endswith('/')}}\n"
    "seen, added = set(existing), 0\n"
    "with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as z:\n"
    "    for p in files:\n"
    "        if not os.path.isfile(p):\n"
    "            continue\n"
    "        base = os.path.basename(p)\n"
    "        arc, i = base, 1\n"
    "        while arc in seen:\n"
    "            stem, ext = os.path.splitext(base)\n"
    "            arc = stem + '_' + str(i) + ext\n"
    "            i += 1\n"
    "        seen.add(arc)\n"
    "        z.write(p, arc)\n"
    "        added += 1\n"
    "print('FOLD_WROTE', zip_path, added)\n"
)


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


def is_junk_path(path: str) -> bool:
    """True when the path is hard junk that must never be delivered."""
    p = (path or "").strip()
    if not p:
        return False
    name = p.rsplit("/", 1)[-1].lower()
    if name in _JUNK_BASENAMES:
        return True
    if name.startswith(".env."):
        # .env.local / .env.production carry secrets — junk. But the
        # template variants (.env.example / .env.sample) are deliverables.
        if not name.endswith((".example", ".sample", ".template")):
            return True
    if name.endswith(_JUNK_EXTS):
        return True
    segments = [s.lower() for s in p.split("/") if s]
    return any(s in _JUNK_DIR_SEGMENTS for s in segments[:-1])


def drop_junk_attachments(attachments: List[FileInfo]) -> List[FileInfo]:
    """Remove hard-junk attachments (pid/log/lockfiles/.env/caches).

    Applies to BOTH the model's own list and the sweep merge — a
    ``server.pid`` card is noise no matter who listed it. Never raises.
    """
    try:
        kept = [a for a in attachments if not is_junk_path(a.file_path or "")]
        dropped = [
            (a.filename or a.file_path) for a in attachments
            if is_junk_path(a.file_path or "")
        ]
        if dropped:
            logger.info(
                "Delivery hygiene: dropped %d junk file(s) from the final "
                "list: %s", len(dropped), dropped,
            )
        return kept
    except Exception as exc:  # pragma: no cover — fail-open by contract
        logger.warning("Junk filter failed (delivering as-is): %s", exc)
        return attachments


async def fold_loose_files_into_archive(
    sandbox, attachments: List[FileInfo]
) -> List[FileInfo]:
    """When a .zip leads the delivery, append remaining loose NON-document
    files INTO that archive and keep the documents loose.

    Returns ``[archives + folded-into-zip] + [standalone documents]``.
    ``sandbox`` must expose ``exec_command(session_id, exec_dir, command)``.
    Fail-open: when the append command fails the list is returned unchanged
    (loose files stay — a broken net must never block delivery).
    """
    try:
        zip_paths = [
            a.file_path for a in attachments
            if (a.file_path or "").lower().endswith(".zip")
        ]
        if not zip_paths:
            return attachments

        target_zip = zip_paths[0]
        loose = [
            a for a in attachments
            if a.file_path
            and not (a.file_path or "").lower().endswith(".zip")
            and _ext(a.file_path) not in _DOC_EXTS
        ]
        if not loose:
            return attachments

        loose_paths = [a.file_path for a in loose]
        script = _FOLD_SCRIPT.format(zip_path=target_zip, files=loose_paths)
        command = f"python3 -c {shlex.quote(script)}"
        result = await sandbox.exec_command("delivery-fold", "/tmp", command)
        ok = bool(result and getattr(result, "success", False))
        output = ""
        if ok:
            data = getattr(result, "data", None)
            output = data.get("output", "") if isinstance(data, dict) else ""
        if not ok or "FOLD_WROTE" not in output:
            logger.warning(
                "Delivery fold: archive append failed (%s) — delivering the "
                "loose file(s) as cards instead",
                (output or getattr(result, "message", ""))[:200],
            )
            return attachments

        folded_names = [
            a.filename or (a.file_path or "").rsplit("/", 1)[-1] for a in loose
        ]
        logger.info(
            "ZIP-only delivery: folded %d loose non-document file(s) into %s "
            "(delivered as archive members, not cards): %s",
            len(loose), target_zip, folded_names,
        )
        # Keep: every archive (the target now carries the folded members)
        # + the standalone documents.
        kept = [
            a for a in attachments
            if (a.file_path or "").lower().endswith(".zip")
            or _ext(a.file_path or "") in _DOC_EXTS
        ]
        return kept
    except Exception as exc:
        logger.warning(
            "Delivery fold failed (delivering loose files as cards): %s", exc
        )
        return attachments
