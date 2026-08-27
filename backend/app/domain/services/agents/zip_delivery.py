"""ZIP-only delivery helper.

When a .zip archive is among a task's deliverables, the user expects ONLY the
archive — the individual files inside it (html, css, js, ...) are already
bundled and must not be delivered a second time next to it.

Two delivery paths merge attachments independently, so both consume this
helper:
  • ExecutionAgent.summarize()          — the model's own attachment list
  • AgentTaskRunner final-summary sweep — every file written by tools during
    the run (artifact scan) appended to the final message

The helper inspects each delivered .zip in the sandbox (python zipfile
one-liner) and drops sibling attachments that are members of one of the
archives:
  • full-path match — attachment == <zip_dir>/<member> (zip built with
    `zip -r bundle.zip site` from the parent directory)
  • basename match  — attachment basename appears as a member basename AND
    the attachment lives under the zip's parent tree (zip built from inside
    the project dir, members relative to it)

Other .zip attachments and non-member files (e.g. the research summary .md)
are always kept. On any inspection failure the list is returned unchanged —
a broken safety net must never block delivery.
"""

import logging
import shlex
from typing import List

from app.domain.models.file import FileInfo

logger = logging.getLogger(__name__)


def _parse_members(output: str):
    """Parse zip member names from a sandbox one-liner output."""
    names = set()
    for line in (output or "").splitlines():
        name = line.strip()
        if not name or name.startswith("ZIP_ERR:"):
            continue
        names.add(name)
    return names


def _is_zip_member(
    path: str, member_names: set, member_basenames: set, zip_dirs: set
) -> bool:
    if path.lower().endswith(".zip"):
        return False  # never drop other archives
    if path in member_names:
        return True
    under_zip_dir = any(path.startswith(zd + "/") for zd in zip_dirs)
    return under_zip_dir and path.rsplit("/", 1)[-1] in member_basenames


async def drop_zip_member_attachments(
    sandbox, attachments: List[FileInfo]
) -> List[FileInfo]:
    """Return `attachments` minus any file already bundled inside a
    delivered .zip. `sandbox` must expose `exec_command(session_id,
    exec_dir, command)` (the Sandbox protocol)."""
    zip_paths = [
        a.file_path
        for a in attachments
        if a.file_path and a.file_path.lower().endswith(".zip")
    ]
    if not zip_paths:
        return attachments

    member_names: set = set()
    for zp in zip_paths:
        script = (
            "import zipfile\n"
            "try:\n"
            f"    z = zipfile.ZipFile({zp!r})\n"
            "    print('\\n'.join(n for n in z.namelist() "
            "if not n.endswith('/')))\n"
            "except Exception as e:\n"
            "    print('ZIP_ERR:' + str(e))\n"
        )
        command = f"python3 -c {shlex.quote(script)}"
        try:
            result = await sandbox.exec_command("zip-inspect", "/tmp", command)
            if not (result and getattr(result, "success", False)):
                continue
            data = getattr(result, "data", None)
            output = data.get("output", "") if isinstance(data, dict) else ""
            member_names |= _parse_members(output)
        except Exception as exc:
            logger.warning("Zip member inspection failed for %s: %s", zp, exc)

    if not member_names:
        return attachments

    member_basenames = {n.rsplit("/", 1)[-1] for n in member_names}
    zip_dirs = {zp.rsplit("/", 1)[0] for zp in zip_paths if "/" in zp}

    kept = [
        a
        for a in attachments
        if not (a.file_path and _is_zip_member(
            a.file_path, member_names, member_basenames, zip_dirs
        ))
    ]
    dropped = len(attachments) - len(kept)
    if dropped:
        logger.info(
            "ZIP-only delivery: dropped %d bundled member file(s) already inside %s",
            dropped,
            zip_paths,
        )
    return kept
