"""Self-healing guard for the compiled frontend (frontend/dist).

Why this exists
---------------
uvicorn serves ``frontend/dist`` straight from disk and the deployment has
NO build step in its startup path. A reprovision / snapshot restore can
silently roll that folder back to an older build — observed in production:
the dist was restored from BEFORE the collapsible-prompt / copy-button /
long-prompt-layout fixes, so users suddenly saw the old broken chat UI
while the git source still contained every fix ("yang tadinya sudah bagus
jadi jelek lagi").

How it works
------------
On application startup the guard compares the mtime of
``frontend/dist/index.html`` with the newest source file under
``frontend/src`` (+ ``index.html``, ``package.json``, ``vite.config.*``).
When the dist is missing or older than the sources, a rebuild runs in a
background thread. Everything is fail-open:

* build failure  -> the existing (stale) dist keeps serving, error logged;
* missing tools  -> same, error logged;
* the guard NEVER blocks or crashes application startup.

Build command candidates (first that works wins):
``pnpm --dir <frontend> run build`` -> ``npm --prefix <frontend> run build``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Allow a couple of seconds of clock skew / checkout granularity before a
# perfectly fresh dist is called "stale".
_MTIME_TOLERANCE_SECONDS = 2.0

_BUILD_TIMEOUT_SECONDS = 600  # vite build is ~25s here; headroom for cold pnpm

_guard_lock = threading.Lock()
_rebuild_running = False


def default_frontend_dir() -> Path:
    """frontend/ directory next to the backend package (repo-relative)."""
    return Path(__file__).resolve().parents[3] / "frontend"


def _source_watch_files(frontend_dir: Path) -> list[Path]:
    """Source locations whose changes must be reflected in a fresh build."""
    roots: list[Path] = []
    src = frontend_dir / "src"
    if src.is_dir():
        roots.append(src)
    for name in ("index.html", "package.json", "vite.config.ts", "vite.config.js", "postcss.config.js", "tailwind.config.js"):
        candidate = frontend_dir / name
        if candidate.is_file():
            roots.append(candidate)
    return roots


def newest_source_mtime(frontend_dir: Path) -> Optional[float]:
    """Newest mtime among watched frontend sources (None when nothing found)."""
    newest: Optional[float] = None
    for root in _source_watch_files(frontend_dir):
        try:
            if root.is_file():
                mtime = root.stat().st_mtime
                newest = mtime if newest is None else max(newest, mtime)
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                # node_modules never lives under src/, but be safe anyway
                dirnames[:] = [d for d in dirnames if d != "node_modules"]
                for filename in filenames:
                    try:
                        mtime = (Path(dirpath) / filename).stat().st_mtime
                    except OSError:
                        continue
                    newest = mtime if newest is None else max(newest, mtime)
        except OSError as exc:
            logger.debug("frontend guard: cannot scan %s (%s)", root, exc)
    return newest


def dist_is_stale(frontend_dir: Path) -> bool:
    """True when the compiled dist is missing or older than the sources.

    Pure filesystem check — trivially unit-testable, never raises.
    """
    try:
        dist_index = frontend_dir / "dist" / "index.html"
        if not dist_index.is_file():
            return True
        newest_src = newest_source_mtime(frontend_dir)
        if newest_src is None:
            return False  # no sources found — nothing to compare against
        dist_mtime = dist_index.stat().st_mtime
        return dist_mtime + _MTIME_TOLERANCE_SECONDS < newest_src
    except OSError as exc:
        logger.debug("frontend guard: stat failed (%s) — treating as fresh", exc)
        return False


def rebuild_frontend(frontend_dir: Path, timeout: int = _BUILD_TIMEOUT_SECONDS) -> bool:
    """Run the frontend build (blocking). Returns True when dist is fresh."""
    commands = (
        ["pnpm", "--dir", str(frontend_dir), "run", "build"],
        ["npm", "--prefix", str(frontend_dir), "run", "build"],
    )
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except FileNotFoundError:
            logger.warning("frontend guard: %s not available — trying next", cmd[0])
            continue
        except subprocess.TimeoutExpired:
            logger.warning("frontend guard: %s timed out after %ss", " ".join(cmd), timeout)
            continue
        if result.returncode == 0 and (frontend_dir / "dist" / "index.html").is_file():
            logger.info("frontend guard: rebuilt dist via %s", " ".join(cmd[:3]))
            return True
        logger.warning(
            "frontend guard: build failed (rc=%s) via %s — stderr tail: %s",
            result.returncode,
            " ".join(cmd[:3]),
            (result.stderr or "")[-400:],
        )
    return False


def ensure_fresh_frontend(frontend_dir: Optional[Path] = None) -> bool:
    """Rebuild the frontend when its dist is stale — without blocking startup.

    Returns True when a rebuild was *started* (or already running), False
    when the dist was already fresh. Never raises.
    """
    global _rebuild_running
    try:
        frontend = frontend_dir or default_frontend_dir()
        if not dist_is_stale(frontend):
            return False

        with _guard_lock:
            if _rebuild_running:
                return True
            _rebuild_running = True

        def _worker() -> None:
            global _rebuild_running
            try:
                logger.warning(
                    "frontend guard: frontend/dist is stale or missing — rebuilding "
                    "(the app keeps serving the old build until the fresh one lands)"
                )
                ok = rebuild_frontend(frontend)
                if not ok:
                    logger.error(
                        "frontend guard: rebuild FAILED — serving the existing dist. "
                        "Fix manually with: cd frontend && pnpm run build"
                    )
            finally:
                with _guard_lock:
                    _rebuild_running = False

        threading.Thread(target=_worker, name="frontend-dist-guard", daemon=True).start()
        return True
    except Exception as exc:  # pragma: no cover — fail-open by contract
        logger.error("frontend guard: unexpected error (%s) — ignoring", exc)
        return False
