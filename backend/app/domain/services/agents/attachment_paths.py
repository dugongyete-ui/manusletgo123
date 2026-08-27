"""Attachment path normalization.

LLM models emit file attachment lists in inconsistent shapes. Observed in
production (session 5e7888777d4b4c03): ``message_notify_user`` called with
``attachments: '["/home/z/.../kopi_senja.zip"]'`` — a JSON-encoded LIST as a
plain string. Naive handling stores the whole JSON blob as one "path",
which then fails every sandbox sync and silently disappears from delivery.

This module turns any model-emitted attachment value into a clean list of
sandbox paths:
  • JSON-encoded string  '["/a.zip", "/b.md"]'  → ["/a.zip", "/b.md"]
  • single path string   "/home/runner/a.md"    → ["/home/runner/a.md"]
  • list (mixed strings) ["/a.zip", '["/b"]']   → ["/a.zip", "/b.md"]
  • junk (empty, non-path text)                 → dropped (logged)
"""

import json
import logging
from typing import Any, List

logger = logging.getLogger(__name__)


def _looks_like_path(p: str) -> bool:
    return p.startswith("/") or p.startswith("~/") or p == "~"


def _expand(value: Any, out: List[str]) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _expand(item, out)
        return
    if not isinstance(value, str):
        # numbers, dicts, etc. — not a path
        return
    v = value.strip()
    if not v:
        return
    if v.startswith("[") and v.endswith("]"):
        try:
            parsed = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                _expand(item, out)
            return
        # fall through: treat as plain (weird) string
    # strip stray quotes from copy-pasted paths
    p = v.strip().strip('"').strip("'").strip()
    if not p:
        return
    if _looks_like_path(p):
        out.append(p)
    else:
        logger.warning(
            "Dropping non-path attachment value (not an absolute sandbox path): %r",
            p[:120],
        )


def normalize_attachment_paths(raw: Any) -> List[str]:
    """Normalize a model-emitted attachments value into clean absolute
    sandbox paths, de-duplicated, order-preserving."""
    out: List[str] = []
    _expand(raw, out)
    seen: set = set()
    deduped: List[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped
