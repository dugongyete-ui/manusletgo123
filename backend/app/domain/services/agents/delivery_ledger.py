"""Cross-session delivery ledger.

Problem it fixes (live incident, 2026-08-31 evening): sessions of the SAME
user share one sandbox home. When two tasks overlap in time (or a later
task's home-sweep runs while an earlier task's files are still settling),
the artifact sweep of session B "discovers" files created by session A
AFTER B's baseline was taken — and re-delivers them to the user.
Observed: a `hello.txt` written by a debug session was delivered again by
two later landing-page sessions; an older `kopi-senja-landing.zip` rode
along with an unrelated task's summary.

Semantics:
  * mark(user, path, size)  — called when a FINAL summary delivers a file.
  * seen(user, path, size)  — checked only for AUTOMATIC sweep candidates
    (never for files the model explicitly listed — a user asking "kirim
    lagi" in a new session must get the file again).
  * Entries expire after TTL (default 48h) so long-lived processes don't
    grow unbounded and genuinely re-created files always deliver.

In-process state is intentional: the backend runs as a single uvicorn
worker, contamination is a same-process temporal phenomenon, and a restart
resets the ledger harmlessly (the baseline diff still protects sequential
tasks).
"""

import time
from typing import Dict, Set, Tuple

_TTL_SECONDS = 48 * 3600

# {(user_id, path, size_bytes): marked_at_epoch}
_ledger: Dict[Tuple[str, str, int], float] = {}


def mark(user_id: str, path: str, size: int | None) -> None:
    """Record that (user, path, size) was delivered with a final summary."""
    if not user_id or not path:
        return
    _ledger[(user_id, path, int(size or 0))] = time.time()


def seen(user_id: str, path: str, size: int | None) -> bool:
    """True when this exact (path, size) was already delivered to the user
    recently (within TTL). Sweep candidates matching this are skipped."""
    key = (user_id, path, int(size or 0))
    at = _ledger.get(key)
    if at is None:
        return False
    if time.time() - at > _TTL_SECONDS:
        _ledger.pop(key, None)
        return False
    return True


def _purge() -> None:
    """Drop expired entries (called from tests to keep the map tiny)."""
    now = time.time()
    for key in [k for k, at in _ledger.items() if now - at > _TTL_SECONDS]:
        _ledger.pop(key, None)


def reset() -> None:
    """Test helper: clear the ledger."""
    _ledger.clear()


def snapshot() -> Set[Tuple[str, str, int]]:
    """Test helper: immutable view of current keys."""
    return set(_ledger.keys())
