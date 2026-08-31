"""Server-side auto-bundling of multi-file deliverables into ONE .zip.

The execution prompt TELLS the model to package multi-file builds as a
single archive, but models drift: they forget, run out of budget mid-zip,
or attach loose members anyway (observed live: a ChatGPT-clone build
delivered 15+ individual cards including .js.map and a 426KB
package-lock.json). This module is the deterministic net at the final
summary:

    attachments without any .zip  AND  >= MIN_MEMBERS non-document files
        -> create ONE archive inside the sandbox (python zipfile — the zip
           binary is not guaranteed on every host)
        -> return [the archive] + standalone documents (.md/.txt/...)

Plus archive sanitisation for the 426MB-zip quota incident:

    a delivered zip above MAX_CLEAN_ZIP_BYTES whose members include junk
    dirs (node_modules, .git, caches, venvs) is REBUILT member-by-member
    (streamed, 1MB chunks) without the junk — the bloated original never
    reaches storage. (Live incident: the model zipped a project WITH
    node_modules; the 426MB "chatgpt-clone.zip" exhausted the 512MB Atlas
    quota and blocked writes cluster-wide.)

Design notes:
- Documents (reports, summaries) are delivered as files, never zipped into
  the bundle — "kalo file .MD txt dll tidak perlu" (user request).
- When the members share one project directory the archive contains the
  WHOLE directory (with junk excluded) — files the model forgot to list
  still reach the user. Scattered members are zipped flat with collision
  handling.
- Junk & secrets never enter any archive: node_modules, .git, caches,
  venvs, .env, *.pyc, *.log.
- Fail-open: on ANY error the original attachment list is returned
  unchanged — a broken safety net must never block delivery.

Both delivery paths consume this helper:
  - AgentTaskRunner final-summary sweep (artifact scan merge)
  - ExecutionAgent.summarize (the model's own attachment list)
"""

import logging
import shlex
from typing import List, Optional, Tuple

from app.domain.models.file import FileInfo

logger = logging.getLogger(__name__)

# Deliverables that stand on their own and are never zipped into the bundle.
_DOC_EXTS = frozenset({
    ".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".rtf",
})

# Minimum non-document files before bundling kicks in. Two files that
# belong together (index.html + style.css) is a project per the packaging
# rules; a single asset stays standalone.
_MIN_MEMBERS = 2

# Hard excludes mirrored from DEPLOYMENT.md / packaging-delivery skill.
_EXCLUDE_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "coverage", ".cache", ".pytest_cache",
})
_EXCLUDE_FILES = frozenset({".env", ".DS_Store"})
_EXCLUDE_EXTS = (".pyc", ".log")

_MAX_ARCHIVE_FILES = 500

# An archive larger than this gets inspected for junk (node_modules etc.).
# The observed incident: the model zipped a project WITH node_modules → a
# 426MB "chatgpt-clone.zip" hit GridFS and blew the 512MB Atlas quota,
# blocking every write cluster-wide. Legitimately huge files (videos)
# contain no junk members and pass through untouched.
_MAX_CLEAN_ZIP_BYTES = 50 * 1024 * 1024

_INSPECT_SCRIPT = (
    "import os, zipfile\n"
    "p = {path!r}\n"
    "print('ZIP_SIZE', os.path.getsize(p) if os.path.exists(p) else -1)\n"
    "try:\n"
    "    z = zipfile.ZipFile(p)\n"
    "    print('\\n'.join(n for n in z.namelist() if not n.endswith('/')))\n"
    "except Exception as e:\n"
    "    print('ZIP_ERR:' + str(e))\n"
)

_REBUILD_SCRIPT = (
    "import os, zipfile\n"
    f"EX_DIRS = {sorted(_EXCLUDE_DIRS)!r}\n"
    "src, dst = {src!r}, {dst!r}\n"
    "with zipfile.ZipFile(src) as zin, "
    "zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:\n"
    "    for info in zin.infolist():\n"
    "        if info.is_dir():\n"
    "            continue\n"
    "        parts = info.filename.split('/')\n"
    "        if any(p in EX_DIRS for p in parts[:-1]):\n"
    "            continue\n"
    "        with zin.open(info) as rf, "
    "zout.open(info.filename, 'w') as wf:\n"
    "            while True:\n"
    "                chunk = rf.read(1024 * 1024)\n"
    "                if not chunk:\n"
    "                    break\n"
    "                wf.write(chunk)\n"
    "print('REBUILT', dst, os.path.getsize(dst))\n"
)


async def _exec_output(sandbox, command: str) -> str:
    """Run a sandbox python one-liner; return its stdout ('' on failure)."""
    result = await sandbox.exec_command(
        "auto-bundle", "/tmp", f"python3 -c {shlex.quote(command)}"
    )
    if not (result and getattr(result, "success", False)):
        return ""
    data = getattr(result, "data", None)
    return data.get("output", "") if isinstance(data, dict) else ""


def _member_has_junk(member: str) -> bool:
    """True when any path SEGMENT of the archive member is a junk dir."""
    segments = member.split("/")
    return any(s in _EXCLUDE_DIRS for s in segments[:-1])


async def sanitize_oversized_archives(
    sandbox, attachments: List[FileInfo]
) -> List[FileInfo]:
    """Rebuild delivered archives that bloated with junk (node_modules,
    caches, venvs) — the 426MB-zip quota incident.

    A zip above _MAX_CLEAN_ZIP_BYTES is inspected: if any member path
    contains a junk segment, the archive is REBUILT member-by-member
    (streamed, 1MB chunks) without the junk, and the attachment is swapped
    to the clean archive. Zips with no junk, small zips, and non-zips pass
    through untouched. Fail-open on every error.
    """
    try:
        out: List[FileInfo] = []
        for a in attachments:
            p = (a.file_path or "").strip()
            if not p.lower().endswith(".zip"):
                out.append(a)
                continue
            output = await _exec_output(
                sandbox, _INSPECT_SCRIPT.format(path=p)
            )
            size = -1
            for line in output.splitlines():
                if line.startswith("ZIP_SIZE"):
                    try:
                        size = int(line.split()[1])
                    except (ValueError, IndexError):
                        pass
                    break
            if 0 <= size < _MAX_CLEAN_ZIP_BYTES:
                out.append(a)
                continue
            if size < 0:
                out.append(a)  # stat failed — don't touch what we can't see
                continue
            members = [
                ln.strip() for ln in output.splitlines()
                if ln.strip() and not ln.startswith(("ZIP_", "ZIP_ERR:"))
            ]
            has_junk = any(_member_has_junk(m) for m in members)
            if not has_junk:
                logger.info(
                    "Auto-bundle: large archive %s (%.0fMB) carries no junk "
                    "members — delivered untouched",
                    p, size / 1048576,
                )
                out.append(a)
                continue
            stem = p[:-4]
            clean_path = f"{stem}-clean.zip"
            rebuild = await _exec_output(
                sandbox, _REBUILD_SCRIPT.format(src=p, dst=clean_path)
            )
            if "REBUILT" not in rebuild:
                logger.warning(
                    "Auto-bundle: junk-archive rebuild failed for %s — "
                    "delivering the original (size %.0fMB)",
                    p, size / 1048576,
                )
                out.append(a)
                continue
            clean_name = (a.filename or p.rsplit("/", 1)[-1])[:-4] + "-clean.zip"
            logger.info(
                "Auto-bundle: rebuilt bloated archive %s (%.0fMB → %s) — "
                "junk excluded, quota protected",
                p, size / 1048576, rebuild.strip().split()[-1],
            )
            out.append(FileInfo(file_path=clean_path, filename=clean_name))
        return out
    except Exception as exc:
        logger.warning("Archive sanitize failed (delivering as-is): %s", exc)
        return attachments


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


def split_docs_members(attachments: List[FileInfo]) -> Tuple[List[FileInfo], List[FileInfo]]:
    """Split attachments into (standalone documents, bundle members)."""
    docs: List[FileInfo] = []
    members: List[FileInfo] = []
    for a in attachments:
        p = (a.file_path or "").strip()
        if p and _ext(p) in _DOC_EXTS:
            docs.append(a)
        else:
            members.append(a)
    return docs, members


def _common_parent(paths: List[str]) -> Optional[str]:
    """Deepest directory shared by every path (None when only "/" or
    nothing is shared)."""
    if not paths:
        return None
    split = [p.split("/") for p in paths]
    depth = min(len(s) for s in split)
    common: List[str] = []
    for i in range(depth):
        seg = split[0][i]
        if all(s[i] == seg for s in split):
            common.append(seg)
        else:
            break
    while common and common[-1] == "":
        common.pop()
    if len(common) < 2:
        return None
    return "/" + "/".join(common[1:]) if common and common[0] == "" else "/".join(common)


def _build_dir_script(project_dir: str, zip_path: str) -> str:
    """Zip the WHOLE project directory (junk excluded), preserving the
    top-level folder inside the archive."""
    return (
        "import os, zipfile\n"
        f"EX_DIRS = {sorted(_EXCLUDE_DIRS)!r}\n"
        f"SKIP_FILES = {sorted(_EXCLUDE_FILES)!r}\n"
        f"SKIP_EXTS = {tuple(_EXCLUDE_EXTS)!r}\n"
        f"root, out, cap = {project_dir!r}, {zip_path!r}, {_MAX_ARCHIVE_FILES}\n"
        "n = 0\n"
        "with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:\n"
        "    for dp, dn, fn in os.walk(root):\n"
        "        dn[:] = [d for d in dn if d not in EX_DIRS]\n"
        "        for f in fn:\n"
        "            if f in SKIP_FILES or f.endswith(SKIP_EXTS):\n"
        "                continue\n"
        "            arc = os.path.relpath(os.path.join(dp, f), os.path.dirname(root))\n"
        "            z.write(os.path.join(dp, f), arc)\n"
        "            n += 1\n"
        "            if n >= cap:\n"
        "                break\n"
        "        if n >= cap:\n"
        "            break\n"
        "print('BUNDLE_WROTE', out, n, os.path.getsize(out) if n else 0)\n"
    )


def _build_files_script(file_paths: List[str], zip_path: str) -> str:
    """Zip a scattered list of files, flat, with basename collision handling."""
    return (
        "import os, zipfile\n"
        f"files, out = {file_paths!r}, {zip_path!r}\n"
        "seen, n = set(), 0\n"
        "with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:\n"
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
        "        n += 1\n"
        "print('BUNDLE_WROTE', out, n, os.path.getsize(out) if n else 0)\n"
    )


async def auto_bundle_deliverables(
    sandbox, attachments: List[FileInfo]
) -> List[FileInfo]:
    """Return `attachments` with multi-file builds collapsed into ONE .zip.

    Pass-through when: a .zip is already among them, fewer than
    _MIN_MEMBERS non-document files exist, or anything fails (fail-open).
    `sandbox` must expose exec_command(session_id, exec_dir, command).
    """
    try:
        if not attachments:
            return attachments
        if any(
            (a.file_path or "").lower().endswith(".zip") for a in attachments
        ):
            return attachments  # an archive already leads the delivery

        docs, members = split_docs_members(attachments)
        member_paths = [m.file_path for m in members if m.file_path]
        if len(member_paths) < _MIN_MEMBERS:
            return attachments

        home = getattr(sandbox, "user_home", None)
        parent = _common_parent(member_paths)
        # Whole-directory bundling only when the shared parent is a real
        # project dir (not the home root itself, not outside it).
        project_dir = None
        if (
            parent
            and home
            and parent.rstrip("/") != home.rstrip("/")
            and parent.startswith(home.rstrip("/") + "/")
        ):
            project_dir = parent

        if project_dir:
            zip_name = project_dir.rstrip("/").rsplit("/", 1)[-1] + ".zip"
            zip_path = f"{home.rstrip('/')}/{zip_name}"
            script = _build_dir_script(project_dir, zip_path)
            # Docs INSIDE the project dir (README.md, docs/*.md) are project
            # members — the whole-dir walk bundles them. Only docs OUTSIDE
            # the project (the standalone report) ship next to the archive.
            standalone_docs = [
                d for d in docs
                if not (
                    d.file_path
                    and d.file_path.startswith(project_dir.rstrip("/") + "/")
                )
            ]
        else:
            zip_name = "project.zip"
            zip_path = f"{(home or member_paths[0].rsplit('/', 1)[0]).rstrip('/')}/{zip_name}"
            script = _build_files_script(member_paths, zip_path)
            standalone_docs = docs

        result = await sandbox.exec_command(
            "auto-bundle", "/tmp", f"python3 -c {shlex.quote(script)}"
        )
        ok = bool(result and getattr(result, "success", False))
        output = ""
        if ok:
            data = getattr(result, "data", None)
            output = data.get("output", "") if isinstance(data, dict) else ""
        if not ok or "BUNDLE_WROTE" not in output:
            logger.warning(
                "Auto-bundle: archive creation failed (%s) — delivering "
                "unbundled list",
                (output or getattr(result, "message", ""))[:200],
            )
            return attachments

        # Script prints BUNDLE_WROTE <path> <count> <bytes>: count must be > 0
        try:
            parts = output.strip().split()
            count = int(parts[2]) if len(parts) >= 3 else 0
        except (ValueError, IndexError):
            count = 0
        if count <= 0:
            logger.warning("Auto-bundle: archive came back empty — delivering unbundled list")
            return attachments

        bundle = FileInfo(file_path=zip_path, filename=zip_name)
        logger.info(
            "Auto-bundle: %d loose file(s) collapsed into %s (%d members) — "
            "delivering archive + %d document(s)",
            len(member_paths), zip_path, count, len(standalone_docs),
        )
        return [bundle] + standalone_docs
    except Exception as exc:
        logger.warning("Auto-bundle failed (delivering unbundled list): %s", exc)
        return attachments
