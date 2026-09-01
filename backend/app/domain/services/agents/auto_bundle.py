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
    """Zip a scattered list of files PRESERVING each file's directory
    structure (arcname = path relative to the group's longest shared
    directory prefix). No shared prefix → collision-safe basenames.

    Live incident (session fbfcb72d): the flat variant produced an archive
    whose extraction scattered 37 files into the user's face with no
    directories ("saat saya extract ... tidak ada folder sesuai masing
    masing, mentah gitu aja") — structure-preserving arcnames are the fix.
    """
    return (
        "import os, zipfile\n"
        f"EX_DIRS = {sorted(_EXCLUDE_DIRS)!r}\n"
        f"SKIP_FILES = {sorted(_EXCLUDE_FILES)!r}\n"
        f"SKIP_EXTS = {tuple(_EXCLUDE_EXTS)!r}\n"
        f"files, out, cap = {file_paths!r}, {zip_path!r}, {_MAX_ARCHIVE_FILES}\n"
        "base = os.path.dirname(files[0])\n"
        "try:\n"
        "    cp = os.path.commonpath(files)\n"
        "    base = cp if os.path.isdir(cp) else os.path.dirname(cp)\n"
        "except Exception:\n"
        "    pass\n"
        "seen, n = set(), 0\n"
        "with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:\n"
        "    for p in files:\n"
        "        if not os.path.isfile(p):\n"
        "            continue\n"
        "        arc = os.path.relpath(p, base).replace(os.sep, '/')\n"
        "        if arc.startswith('../'):\n"
        "            arc = os.path.basename(p)\n"
        "        stem, i = arc, 1\n"
        "        while arc in seen:\n"
        "            stem, ext = os.path.splitext(stem)\n"
        "            arc = stem + '_' + str(i) + ext\n"
        "            i += 1\n"
        "        seen.add(arc)\n"
        "        z.write(p, arc)\n"
        "        n += 1\n"
        "        if n >= cap:\n"
        "            break\n"
        "print('BUNDLE_WROTE', out, n, os.path.getsize(out) if n else 0)\n"
    )


# ── Flat-archive restructure net ────────────────────────────────────────────
# Live incident (session fbfcb72d, 2026-09-01): the model zipped its build
# FLAT — members were bare basenames — so extracting scattered every file at
# the top level with no directories. The FOLD net then appended loose sweep
# files with collision-renamed basenames (favicon_1.svg, index_1.html) and
# the archive even carried a real .env. The user: "saat saya extract ...
# tidak ada folder sesuai masing masing, mentah gitu aja".
#
# Rebuild trigger (either):
#   * every member is flat (no directory component) — structure lost, or
#   * any member is hard junk / a secret (.env, *.pid, *.log, lockfiles).
#
# Rebuild strategy — the REAL sandbox tree is the source of truth (the
# MetaGPT ProjectRepo idea: files always live in a repo tree; archives are
# just its projection). One sandbox script:
#   1. index the user home (junk dirs + platform scaffolding skipped)
#   2. resolve each flat member's basename back to its real path
#      (ranking deprioritises build outputs; `name_1.ext` fold-renames are
#      un-renamed; collisions fall through to the next candidate)
#   3. re-emit the archive with structure-preserving arcnames —
#      `project/<app>/x` becomes `<app>/x` (the DEPLOYMENT.md convention:
#      unzipping creates ONE clean project directory), other files keep
#      their home-relative path
#   4. members that resolve nowhere are copied from the original archive
#      (nothing is lost); junk/secret members are dropped
# Fail-open: on ANY error the original attachment list is returned.

_RESTRUCTURE_SCRIPT = '''import os, re, sys, zipfile

ZIP, OUT, HOME = {zip_path!r}, {out_path!r}, {home!r}
EX_DIRS = {ex_dirs!r}
JUNK_NAMES = {junk_names!r}
JUNK_EXTS = {junk_exts!r}
BUILD_SEGS = ("dist", "build", "out", ".next", ".output")


def is_junk(name):
    parts = [p for p in name.split("/") if p]
    if not parts:
        return True
    if any(p in EX_DIRS for p in parts[:-1]):
        return True
    base = parts[-1]
    if base in JUNK_NAMES:
        return True
    if base.startswith(".env."):
        return not base.endswith((".example", ".sample", ".template"))
    return base.endswith(JUNK_EXTS)


with zipfile.ZipFile(ZIP) as z:
    infos = [i for i in z.infolist() if not i.is_dir()]

flat = [i for i in infos if "/" not in i.filename]
junky = any(is_junk(i.filename) for i in infos)
if not flat and not junky:
    print("STRUCTURE_OK")
    sys.exit(0)

# 1. index the real tree (junk + platform scaffolding skipped)
index = {{}}
seen_files = 0
for dp, dn, fn in os.walk(HOME):
    dn[:] = [d for d in dn if d not in EX_DIRS]
    for f in fn:
        seen_files += 1
        if seen_files > 6000:
            break
        if f in JUNK_NAMES or f.endswith(JUNK_EXTS):
            continue
        rel = os.path.relpath(os.path.join(dp, f), HOME).replace(os.sep, "/")
        segs = rel.split("/")
        if segs[0] == "project" and len(segs) <= 2:
            continue  # platform manual root files — never deliverables
        index.setdefault(f, []).append(rel)
    if seen_files > 6000:
        break


# 1b. dominant-root vote: ambiguous basenames (index.html exists in many
# projects) must prefer the tree where the majority of members live —
# otherwise leftovers from OTHER sessions hijack the resolution.
def unrename(base):
    stem, dot, ext = base.rpartition(".")
    m = re.match(r"^(.*)_\\d+$", stem)
    if m and dot:
        return m.group(1) + "." + ext
    return base


def cands_for(base):
    return index.get(base) or index.get(unrename(base)) or []


root_votes = {{}}
for info in flat:
    if is_junk(info.filename):
        continue
    roots = {{c.split("/")[0] for c in cands_for(info.filename)}}
    if not roots:
        continue
    if len(roots) == 1:
        r = roots.pop()
        root_votes[r] = root_votes.get(r, 0) + 2  # unambiguous: strong vote
    else:
        for r in roots:
            root_votes[r] = root_votes.get(r, 0) + 1
dominant = max(root_votes, key=root_votes.get) if root_votes else None


def rank(cands):
    def key(rel):
        segs = rel.split("/")
        build_pen = sum(1 for s in segs[:-1] if s.lower() in BUILD_SEGS)
        dom_pen = 0 if (dominant and segs[0] == dominant) else 1
        return (dom_pen, build_pen, len(segs), len(rel))

    return sorted(cands, key=key)


plan = []
seen_arc = set()
for info in infos:
    if "/" in info.filename:
        if is_junk(info.filename):
            continue
        plan.append((info.filename, None, info))
        seen_arc.add(info.filename)

for info in flat:
    base = info.filename
    if is_junk(base):
        continue
    cands = cands_for(base)
    if not cands:
        plan.append((base, None, info))
        continue
    chosen = None
    for c in rank(cands):
        arc = c[len("project/"):] if c.startswith("project/") else c
        if arc not in seen_arc:
            chosen = (arc, os.path.join(HOME, c))
            break
    if chosen is None:
        plan.append((base, None, info))
    else:
        plan.append((chosen[0], chosen[1], None))
        seen_arc.add(chosen[0])

if not plan:
    print("RESTRUCTURED", OUT, 0, len(flat))
    sys.exit(0)

n = 0
with zipfile.ZipFile(ZIP) as zin, zipfile.ZipFile(
    OUT, "w", zipfile.ZIP_DEFLATED
) as zout:
    for arc, src, info in plan:
        if src:
            zout.write(src, arc)
        else:
            with zin.open(info) as rf, zout.open(arc, "w") as wf:
                while True:
                    chunk = rf.read(1024 * 1024)
                    if not chunk:
                        break
                    wf.write(chunk)
        n += 1
print("RESTRUCTURED", OUT, n, len(flat))
'''

# Hard-junk member names mirrored from delivery_hygiene (import avoided to
# keep this module import-cycle free — values are validated by tests).
_JUNK_MEMBER_NAMES = frozenset({
    ".env", ".ds_store", ".npmrc", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "poetry.lock",
    "pipfile.lock", "composer.lock", "gemfile.lock", ".python-version",
    ".tool-versions",
})
_JUNK_MEMBER_EXTS = (".pid", ".log", ".pyc", ".pyo", ".tsbuildinfo", ".tmp")


async def restructure_flat_archives(
    sandbox, attachments: List[FileInfo]
) -> List[FileInfo]:
    """Rebuild delivered .zip archives that lost their folder structure or
    carry junk/secret members. See the module notes above the
    ``_RESTRUCTURE_SCRIPT`` for the full rationale. Fail-open: on any
    error the original list is returned unchanged.
    """
    try:
        home = (getattr(sandbox, "user_home", None) or "").rstrip("/")
        if not home:
            return attachments
        out: List[FileInfo] = []
        for a in attachments:
            p = (a.file_path or "").strip()
            if not p.lower().endswith(".zip"):
                out.append(a)
                continue
            script = _RESTRUCTURE_SCRIPT.format(
                zip_path=p,
                out_path=f"{p[:-4]}-structured.zip",
                home=home,
                ex_dirs=sorted(_EXCLUDE_DIRS),
                junk_names=sorted(_JUNK_MEMBER_NAMES),
                junk_exts=_JUNK_MEMBER_EXTS,
            )
            result = await sandbox.exec_command(
                "zip-restructure", "/tmp", f"python3 -c {shlex.quote(script)}"
            )
            output = ""
            if result and getattr(result, "success", False):
                data = getattr(result, "data", None)
                output = data.get("output", "") if isinstance(data, dict) else ""
            if "STRUCTURE_OK" in output:
                out.append(a)
                continue
            if "RESTRUCTURED" not in output:
                logger.warning(
                    "Zip restructure: rebuild failed for %s (%s) — "
                    "delivering the original archive",
                    p, (output or getattr(result, "message", ""))[:200],
                )
                out.append(a)
                continue
            # RESTRUCTURED <out_path> <count> <flat_count>: never swap to
            # an empty archive.
            try:
                count = int(output.strip().split()[2])
            except (ValueError, IndexError):
                count = 0
            if count <= 0:
                logger.warning(
                    "Zip restructure: rebuild came back empty for %s — "
                    "delivering the original archive",
                    p,
                )
                out.append(a)
                continue
            structured_path = f"{p[:-4]}-structured.zip"
            structured_name = (a.filename or p.rsplit("/", 1)[-1])
            logger.info(
                "Zip restructure: rebuilt flat/junky archive %s into %s — "
                "members now mirror the real project tree",
                p, structured_path,
            )
            out.append(
                FileInfo(file_path=structured_path, filename=structured_name)
            )
        return out
    except Exception as exc:
        logger.warning(
            "Zip restructure failed (delivering as-is): %s", exc
        )
        return attachments


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
