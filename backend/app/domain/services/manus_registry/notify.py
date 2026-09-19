"""Notification Event Bus + Run Registry (agent architecture contract v1.0
+ agent_runtime_json v1.0 notification.events.json).

Contract: agent_architecture_json/notification-event-bus/contract.json
          contracts/agent_runtime_json/notification.events.json

Role: menerbitkan status agent kepada frontend/user — BUKAN MCP tool.

Events (contract enum — terminal / pauses_task flags from the runtime
notification.events.json):
    agent_started          terminal=False
    tool_call_started      terminal=False
    tool_call_finished     terminal=False
    confirmation_required  terminal=False, pauses_task=True
    agent_error            terminal=True
    agent_finished         terminal=True

Event shape (contract event_schema):
    {type, task_id, step?, message, data?}   (+ timestamp, session_id)

Adapters implemented here:
    - database_event_log → in-process bounded RunRegistry (polling source)
    - polling            → GET /sessions/{id}/agent-events (session_routes)

Redaction: every event passes redact_secrets() — api_key / access_token /
cookie / password / secret / raw stack traces never leave the process.
Run lifecycle changes are validated against task.state-machine.json
(pending → running ⇄ waiting_confirmation → completed | failed | cancelled).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.domain.services.manus_registry.errors import redact_secrets
from app.domain.services.manus_registry.runtime_config import load_contract
from app.domain.services.manus_registry import state_machine as tsm

logger = logging.getLogger(__name__)

# ── Contract event types ─────────────────────────────────────────────────────
AGENT_STARTED = "agent_started"
TOOL_CALL_STARTED = "tool_call_started"
TOOL_CALL_FINISHED = "tool_call_finished"
CONFIRMATION_REQUIRED = "confirmation_required"
AGENT_ERROR = "agent_error"
AGENT_FINISHED = "agent_finished"

EVENT_TYPES = {
    AGENT_STARTED, TOOL_CALL_STARTED, TOOL_CALL_FINISHED,
    CONFIRMATION_REQUIRED, AGENT_ERROR, AGENT_FINISHED,
}

# ── notification.events.json contract metadata ──────────────────────────
def _load_event_metadata() -> Dict[str, Dict[str, Any]]:
    try:
        contract = load_contract("notification.events.json")
        return contract.get("events") or {}
    except Exception:  # noqa: BLE001 — missing contract → safe defaults
        return {}

_EVENT_META = _load_event_metadata()

TERMINAL_EVENTS = frozenset(
    name for name, meta in _EVENT_META.items() if meta.get("terminal")
) or frozenset({AGENT_ERROR, AGENT_FINISHED})

PAUSES_TASK_EVENTS = frozenset(
    name for name, meta in _EVENT_META.items() if meta.get("pauses_task")
) or frozenset({CONFIRMATION_REQUIRED})

DELIVERY_ADAPTERS = ("sse", "websocket", "polling", "database_event_log")


def event_metadata(event_type: str) -> Dict[str, Any]:
    """Contract metadata (terminal / pauses_task) for one event type."""
    return dict(_EVENT_META.get(event_type, {}))

# Bounded retention (single-process uvicorn deployment).
MAX_EVENTS_PER_RUN = 400
MAX_RUNS_PER_SESSION = 8
MAX_SESSIONS = 500


def make_event(
    type: str,
    task_id: str,
    message: str,
    step: Optional[int] = None,
    data: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one contract-shaped event (redacted, JSON-safe)."""
    if type not in EVENT_TYPES:
        logger.warning("unknown event type %r (contract enum mismatch)", type)
    event: Dict[str, Any] = {
        "type": type,
        "task_id": task_id,
        "message": str(message)[:600],
        "timestamp": time.time(),
    }
    if step is not None:
        event["step"] = int(step)
    if data:
        event["data"] = redact_secrets(data)
    if session_id:
        event["session_id"] = session_id
    return event


class _RunRecord(dict):
    """One agent run: contract events + trace entries + final status."""


class RunRegistry:
    """Bounded in-process event/trace log per session (polling adapter).

    Single-process deployments (z.ai / Replit / typical VPS) read events
    and traces from here. A multi-worker deployment would swap this for a
    Mongo/Redis collection behind the same 5 methods — the contract's
    ``database_event_log`` adapter.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, List[_RunRecord]] = {}
        self._by_task: Dict[str, _RunRecord] = {}

    # ── lifecycle ────────────────────────────────────────────────────────
    def begin_run(
        self, session_id: str, task_id: str, user_id: Optional[str] = None
    ) -> _RunRecord:
        existing = self._by_task.get(task_id)
        if existing is not None:
            return existing
        rec = _RunRecord(
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            started_at=time.time(),
            finished_at=None,
            # Contract task.state-machine.json: a run is born pending and
            # immediately transitions pending → running (bootstrap below).
            status=tsm.PENDING,
            events=[],
            trace=[],
        )
        tsm.assert_transition(rec["status"], tsm.RUNNING)
        rec["status"] = tsm.RUNNING
        bucket = self._sessions.setdefault(session_id, [])
        bucket.append(rec)
        while len(bucket) > MAX_RUNS_PER_SESSION:
            old = bucket.pop(0)
            self._by_task.pop(old["task_id"], None)
        self._sessions[session_id] = bucket
        while len(self._sessions) > MAX_SESSIONS:
            oldest_session = next(iter(self._sessions))
            for old in self._sessions.pop(oldest_session):
                self._by_task.pop(old["task_id"], None)
        self._by_task[task_id] = rec
        return rec

    def finish_run(self, task_id: str, status: str) -> None:
        """Move a run to its terminal status (state-machine validated).

        Valid targets: completed | failed | cancelled. A terminal run never
        resurrects (illegal transition → logged, record left untouched).
        """
        rec = self._by_task.get(task_id)
        if rec is None:
            return
        target = tsm.normalize_status(status)
        try:
            tsm.assert_transition(rec.get("status", tsm.RUNNING), target)
        except tsm.IllegalTransition as exc:
            logger.warning(
                "finish_run(%s → %s) rejected: %s", rec.get("status"), status, exc
            )
            return
        rec["status"] = target
        rec["finished_at"] = time.time()

    def pause_run(self, task_id: str) -> None:
        """running → waiting_confirmation (contract: confirmation_required
        pauses the task; the run resumes when the tool is approved)."""
        rec = self._by_task.get(task_id)
        if rec is None:
            return
        try:
            tsm.assert_transition(rec.get("status", tsm.RUNNING), tsm.WAITING_CONFIRMATION)
        except tsm.IllegalTransition:
            return  # already waiting / terminal — nothing to pause
        rec["status"] = tsm.WAITING_CONFIRMATION

    def resume_run(self, task_id: str) -> None:
        """waiting_confirmation → running (approval granted, tool executing)."""
        rec = self._by_task.get(task_id)
        if rec is None:
            return
        try:
            tsm.assert_transition(rec.get("status", tsm.RUNNING), tsm.RUNNING)
        except tsm.IllegalTransition:
            return  # not paused / terminal — nothing to resume
        rec["status"] = tsm.RUNNING

    # ── events ───────────────────────────────────────────────────────────
    def emit(self, event: Dict[str, Any]) -> None:
        rec = self._by_task.get(event.get("task_id", ""))
        if rec is None:
            # Event before begin_run (gate built lazily) — best-effort drop.
            logger.debug(
                "event dropped (no run for task %s): %s",
                event.get("task_id"), event.get("type"),
            )
            return
        rec["events"].append(event)
        if len(rec["events"]) > MAX_EVENTS_PER_RUN:
            del rec["events"][: len(rec["events"]) - MAX_EVENTS_PER_RUN]

    def get_events(
        self, session_id: str, since: int = 0, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Polling adapter: events of the latest (or given) run, from index."""
        rec = (
            self._by_task.get(task_id)
            if task_id
            else self._latest(session_id)
        )
        if rec is None:
            return {"task_id": None, "status": None, "events": [], "next_since": 0}
        events = rec["events"][max(0, int(since)):]
        return {
            "task_id": rec["task_id"],
            "status": rec["status"],
            "events": events,
            "next_since": int(since) + len(events),
        }

    # ── trace ────────────────────────────────────────────────────────────
    def record_trace(self, task_id: str, entry: Dict[str, Any]) -> None:
        rec = self._by_task.get(task_id)
        if rec is not None:
            rec["trace"].append(entry)
            if len(rec["trace"]) > MAX_EVENTS_PER_RUN:
                del rec["trace"][: len(rec["trace"]) - MAX_EVENTS_PER_RUN]

    def get_trace(
        self, session_id: str, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        rec = (
            self._by_task.get(task_id)
            if task_id
            else self._latest(session_id)
        )
        if rec is None:
            return {"task_id": None, "trace": []}
        return {"task_id": rec["task_id"], "trace": rec["trace"]}

    # ── helpers ──────────────────────────────────────────────────────────
    def _latest(self, session_id: str) -> Optional[_RunRecord]:
        bucket = self._sessions.get(session_id)
        return bucket[-1] if bucket else None


# Module-level singleton (contract: one bus per process).
run_registry = RunRegistry()


def ensure_run_started(
    session_id: str,
    task_id: str,
    user_id: Optional[str] = None,
    user_message: str = "",
) -> _RunRecord:
    """Idempotent run bootstrap: begin the run + emit agent_started ONCE.

    Called from BaseAgent.execute() (the orchestrator entry point per the
    contract execution flow) and safe to call again from the gate/runner.
    """
    rec = run_registry.begin_run(session_id, task_id, user_id)
    if not rec.get("started_emitted"):
        rec["started_emitted"] = True
        run_registry.emit(
            make_event(
                AGENT_STARTED,
                task_id,
                message=user_message[:300] or "Agent run started",
                session_id=session_id,
            )
        )
    return rec
