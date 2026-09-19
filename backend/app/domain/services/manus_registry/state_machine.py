"""Task state machine (agent_runtime_json v1.0 — task.state-machine.json).

The contract governs the lifecycle of ONE agent run (task), not the session
(a session spans many runs):

    pending ──▶ running ──▶ completed | failed | cancelled
                 │  ▲
                 ▼  │
      waiting_confirmation

States map from the platform vocabulary:

    SessionStatus.IN_QUEUE / PENDING → pending   (queued, not yet executing)
    SessionStatus.RUNNING            → running
    SessionStatus.WAITING            → waiting_confirmation  (ask_user pause)
    SessionStatus.COMPLETED          → completed
    SessionStatus.FAILED             → failed
    task.cancel() / stop endpoint    → cancelled

RunRegistry uses ``assert_transition`` so an illegal lifecycle change fails
loudly instead of silently corrupting the run record.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.domain.services.manus_registry.runtime_config import load_contract

logger = logging.getLogger(__name__)

# ── Contract states ──────────────────────────────────────────────────────────
PENDING = "pending"
RUNNING = "running"
WAITING_CONFIRMATION = "waiting_confirmation"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED}

# Platform → contract state aliases.
SESSION_STATUS_ALIASES: Dict[str, str] = {
    "pending": PENDING,
    "in_queue": PENDING,
    "running": RUNNING,
    "waiting": WAITING_CONFIRMATION,
    "completed": COMPLETED,
    "failed": FAILED,
    "cancelled": CANCELLED,
}

# RunRegistry internal statuses are already contract-shaped.
RUN_STATUS_ALIASES: Dict[str, str] = {
    "running": RUNNING,
    "waiting_confirmation": WAITING_CONFIRMATION,
    "completed": COMPLETED,
    "failed": FAILED,
    "cancelled": CANCELLED,
    "pending": PENDING,
}


def _load_transitions() -> List[Dict[str, str]]:
    try:
        contract = load_contract("task.state-machine.json")
        return contract.get("transitions") or []
    except Exception:  # noqa: BLE001 — missing contract → fall back to defaults
        return []


# (from, to) pairs straight from the contract JSON.
_CONTRACT_TRANSITIONS = {(t["from"], t["to"]) for t in _load_transitions()}

# Contract-declared transitions; idempotent self-heal (state → same state) is
# always legal and needs no JSON entry.
DEFAULT_TRANSITIONS = _CONTRACT_TRANSITIONS or {
    (PENDING, RUNNING),
    (RUNNING, WAITING_CONFIRMATION),
    (WAITING_CONFIRMATION, RUNNING),
    (RUNNING, COMPLETED),
    (RUNNING, FAILED),
    (PENDING, CANCELLED),
    (RUNNING, CANCELLED),
}


def contract_state(status_name: Optional[str]) -> Optional[str]:
    """Map a platform/run status name to its contract state (None = unknown)."""
    if not status_name:
        return None
    return (
        RUN_STATUS_ALIASES.get(status_name)
        or SESSION_STATUS_ALIASES.get(status_name)
    )


def can_transition(current: str, target: str) -> bool:
    """Whether the contract allows current → target (idempotent re-set OK)."""
    if current == target:
        return True
    pair = (current, target)
    if pair in DEFAULT_TRANSITIONS:
        return True
    # Terminal states are absorbing — nothing leaves them (completed/failed/
    # cancelled runs never resurrect; a NEW run is a NEW task record).
    if current in TERMINAL_STATES:
        return False
    return False


class IllegalTransition(RuntimeError):
    """Raised when a run lifecycle change violates task.state-machine.json."""


def assert_transition(current: str, target: str) -> None:
    """Raise IllegalTransition when current → target is not contract-legal."""
    if can_transition(current, target):
        return
    raise IllegalTransition(
        f"Illegal task-state transition {current!r} → {target!r} "
        "(task.state-machine.json v1.0)"
    )


def normalize_status(status_name: str) -> str:
    """Normalize any platform/run status to the contract state name."""
    state = contract_state(status_name)
    if state is None:
        raise IllegalTransition(f"unknown run status {status_name!r}")
    return state
