"""Environment-adaptive deployment of the manus-* shell tool binaries.

The 16 allowlisted shell tools live as small Python executables in a
directory OUTSIDE the sandbox's protected paths (the sandbox refuses to
execute anything under a protected directory). Where that directory lives
depends on the host environment:

  - z.ai sandbox : /home/z/manus_tools_bin        (env pins it explicitly)
  - Replit       : /home/runner/manus_tools_bin   (outside /home/runner/workspace)
  - generic VPS  : sibling of the users' home root

Hardcoding one absolute path made deployments crash on any other host
(the z.ai path simply does not exist on Replit). Resolution rules, in order:

  1. explicit MANUS_TOOLS_BIN_DIR env (backend/.env)
  2. ``<parent of user_home_root>/manus_tools_bin``
     (user_home_root defaults to /home/runner/users → /home/runner/manus_tools_bin)
  3. ``<parent of this repo>/manus_tools_bin`` when (2) is protected/unwritable
  4. ``~/.manus_tools_bin`` as the last resort

The binaries themselves SHIP WITH THE REPO (sandbox/manus_tools_bin_repo/,
the canonical copy) and are auto-deployed into the resolved directory on
first use — idempotent, content-hashed, no manual build step, no Docker,
no privilege requirements. That is what makes a fresh Replit/VPS boot
work without crashing.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
from typing import Optional

logger = logging.getLogger(__name__)

# (binary name, library function) — mirrors sandbox/manus_tools_bin_repo/build_bins.sh
_DISPATCHERS = [
    ("manus-md-to-pdf", "md_to_pdf"),
    ("manus-analyze-pptx", "analyze_pptx"),
    ("manus-analyze-video", "analyze_video"),
    ("manus-render-diagram", "render_diagram"),
    ("manus-upload-file", "upload_file"),
    ("manus-webdev-logs", "webdev_logs"),
    ("manus-config", "config"),
    ("manus-heartbeat", "heartbeat"),
    ("manus-channel", "channel"),
    ("manus-export-slides", "export_slides"),
    ("manus-speech-to-text", "speech_to_text"),
    ("manus-token-local-proxy", "token_local_proxy"),
    ("manus-mcp-cli", "mcp_cli"),
    ("manus-touchpoint", "touchpoint"),
    ("manus-touchpoint-fuse", "touchpoint_fuse"),
    ("manus-tools", "self_test"),
]

_DISPATCHER_TEMPLATE = """#!/usr/bin/env python3
import sys
from manus_tool_lib import {func}, crash_guard
sys.exit(crash_guard("{name}")({func})(sys.argv[1:]))
"""


def _repo_canonical_dir() -> str:
    """Canonical source copy shipped with the repository."""
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "..",
        "sandbox", "manus_tools_bin_repo",
    ))


def _protected_paths() -> list[str]:
    """Protected directories the sandbox refuses to touch (never deploy there)."""
    try:
        from app.core.config import get_settings
        raw = getattr(get_settings(), "sandbox_protected_paths", "") or ""
    except Exception:  # pragma: no cover — settings unavailable in some tests
        raw = os.environ.get("SANDBOX_PROTECTED_PATHS", "")
    paths = [p.strip() for sep in (":", ",") for p in raw.replace(",", ":").split(":")]
    return [os.path.realpath(os.path.abspath(p)) for p in paths if p]


def _is_protected(path: str) -> bool:
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except Exception:  # pragma: no cover
        return False
    for protected in _protected_paths():
        if resolved == protected or resolved.startswith(protected + os.sep):
            return True
    return False


def _writable(path: str) -> bool:
    """Whether ``path`` (existing or creatable) can be written by this user."""
    probe = path
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return os.access(probe, os.W_OK)


def resolve_manus_tools_bin_dir() -> str:
    """Pick the deployment directory for this host (no filesystem changes)."""
    # 1) explicit env
    explicit = os.environ.get("MANUS_TOOLS_BIN_DIR", "").strip()
    if explicit:
        return explicit

    # 2) sibling of the users' home root — matches every known layout
    try:
        from app.core.config import get_settings
        home_root = get_settings().user_home_root
    except Exception:  # pragma: no cover
        home_root = os.environ.get("USER_HOME_ROOT", "/home/runner/users")
    candidate = os.path.join(os.path.dirname(os.path.abspath(home_root)),
                             "manus_tools_bin")
    if not _is_protected(candidate) and _writable(candidate):
        return candidate

    # 3) sibling of the repository root (outside the repo = outside protection)
    canonical = os.path.abspath(_repo_canonical_dir())
    # canonical = <repo>/sandbox/manus_tools_bin_repo → repo root is 2 levels up
    repo_root = os.path.dirname(os.path.dirname(canonical))
    candidate = os.path.join(os.path.dirname(repo_root), "manus_tools_bin")
    if not _is_protected(candidate) and _writable(candidate):
        return candidate

    # 4) last resort: the current user's home
    return os.path.join(os.path.expanduser("~"), ".manus_tools_bin")


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _deployment_current(src_dir: str, dst_dir: str) -> bool:
    """True when dst already mirrors the canonical copy (content-hashed)."""
    try:
        lib_dst = os.path.join(dst_dir, "manus_tool_lib.py")
        lib_src = os.path.join(src_dir, "manus_tool_lib.py")
        if not os.path.isfile(lib_dst) or not os.path.isfile(lib_src):
            return False
        if _file_hash(lib_dst) != _file_hash(lib_src):
            return False
        for name, _func in _DISPATCHERS:
            bin_path = os.path.join(dst_dir, name)
            if not os.path.isfile(bin_path) or not os.access(bin_path, os.X_OK):
                return False
            with open(bin_path, "r", encoding="utf-8") as f:
                body = f.read()
            if "from manus_tool_lib import " not in body or name not in body:
                return False
        return True
    except Exception:  # pragma: no cover
        return False


def ensure_manus_tools_deployed(bin_dir: Optional[str] = None) -> str:
    """Deploy (or refresh) the manus-* executables into ``bin_dir``.

    Idempotent: a content-hash check makes this a no-op after the first
    successful deployment. Failures are logged and returned as the target
    dir anyway — the shell executor reports a structured CAPABILITY error
    per call instead of crashing the backend.
    """
    target = bin_dir or resolve_manus_tools_bin_dir()
    src = _repo_canonical_dir()
    try:
        src_lib = os.path.join(src, "manus_tool_lib.py")
        if not os.path.isfile(src_lib):
            # Canonical copy missing (partial clone) — nothing to deploy;
            # shell tools will surface structured per-call errors.
            logger.warning(
                "manus_tools canonical copy missing at %s — shell tools "
                "will report CAPABILITY_UNAVAILABLE", src)
            return target
        if _deployment_current(src, target):
            return target
        os.makedirs(target, exist_ok=True)
        shutil.copy2(src_lib, os.path.join(target, "manus_tool_lib.py"))
        for name, func in _DISPATCHERS:
            bin_path = os.path.join(target, name)
            body = _DISPATCHER_TEMPLATE.format(name=name, func=func)
            needs_write = True
            if os.path.isfile(bin_path):
                with open(bin_path, "r", encoding="utf-8") as f:
                    needs_write = f.read() != body
            if needs_write:
                with open(bin_path, "w", encoding="utf-8") as f:
                    f.write(body)
                os.chmod(bin_path, os.stat(bin_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        logger.info("manus_tools deployed to %s (16 tools)", target)
    except Exception:  # noqa: BLE001 — deployment must never crash the backend
        logger.exception("manus_tools auto-deploy to %s failed", target)
    return target


_resolved_cache: Optional[str] = None


def get_manus_tools_bin_dir() -> str:
    """Resolved + ensured bin dir (cached for the process lifetime)."""
    global _resolved_cache
    if _resolved_cache is None:
        target = resolve_manus_tools_bin_dir()
        _resolved_cache = ensure_manus_tools_deployed(target)
    return _resolved_cache
