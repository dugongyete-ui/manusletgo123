"""Notification Event Bus + Run Registry (agent architecture contract v1.0).

Contract: agent_architecture_json/notification-event-bus/contract.json

Role: menerbitkan status agent kepada frontend/user — BUKAN MCP tool.

Events (contract enum):
    agent_started, tool_call_started, tool_call_finished,
    confirmation_required, agent_error, agent_finished

Event shape (contract event_schema):
    {type, task_id, step?, message, data?}   (+ timestamp, session_id)

Adapters implemented here:
    - database_event_log → in-process bounded RunRegistry (polling source)
    - polling            → GET /sessions/{id}/agent-events (session_routes)

Redaction: every event passes redact_secrets() — api_key / access_token /
cookie / password / secret / raw stack traces never leave the process.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.domain.services.manus_registry.errors import redact_secrets

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
            status="running",
            events=[],
            trace=[],
        )
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
        rec = self._by_task.get(task_id)
        if rec is None:
            return
        rec["status"] = status
        rec["finished_at"] = time.time()

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
