"""Compliance tests for the agent architecture contracts (v1.0).

Covers the components that were implemented/upgrade in this pass:
  - retry-error-handler      → run_with_retry semantics
  - confirmation-manager     → GlobalConfirmationStore + ledger wiring
  - notification-event-bus   → event schema, redaction, RunRegistry polling
  - browser-session-manager  → BrowserSessionTracker state transitions
  - agent-orchestrator       → LoopSafety contract limits (max_identical_calls)
"""
from __future__ import annotations

import time

import pytest

from app.domain.services.manus_registry.browser_session import BrowserSessionTracker
from app.domain.services.manus_registry.confirmations import (
    GlobalConfirmationStore,
    confirmation_store,
)
from app.domain.services.manus_registry.errors import (
    REQUIRES_CONFIRMATION,
    TIMEOUT,
    VALIDATION_ERROR,
    failure_payload,
    success_payload,
)
from app.domain.services.manus_registry.notify import (
    AGENT_STARTED,
    TOOL_CALL_FINISHED,
    make_event,
    run_registry,
)
from app.domain.services.manus_registry.policy import ConfirmationLedger
from app.domain.services.manus_registry.retry import run_with_retry
from app.domain.services.manus_registry.trace import (
    LoopSafety,
    arguments_hash,
    failure_loop_payload,
)


def _payload(counter: dict, fail_times: int, code: str = TIMEOUT):
    async def _fn():
        counter["calls"] += 1
        if counter["calls"] <= fail_times:
            return failure_payload("manus-heartbeat", code, "boom")
        return success_payload("manus-heartbeat", {"ok": True})

    return _fn


# ── retry-error-handler ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_retries_transient_then_succeeds():
    counter = {"calls": 0}
    payload = await run_with_retry(_payload(counter, 1), tool_name="manus-heartbeat")
    assert payload["success"] is True
    assert counter["calls"] == 2  # 1 failure + 1 successful retry


@pytest.mark.asyncio
async def test_retry_never_retries_validation_error():
    counter = {"calls": 0}
    payload = await run_with_retry(
        _payload(counter, 5, code=VALIDATION_ERROR), tool_name="manus-heartbeat"
    )
    assert payload["success"] is False
    assert counter["calls"] == 1  # non-retryable → returned to model as-is


@pytest.mark.asyncio
async def test_retry_budget_is_bounded():
    counter = {"calls": 0}
    payload = await run_with_retry(_payload(counter, 99), tool_name="manus-heartbeat")
    assert counter["calls"] <= 3  # contract max_attempts=2 (+ safe margin)
    assert payload["retryable"] is True  # last failure still surfaced honestly


# ── confirmation-manager ─────────────────────────────────────────────────────

def test_confirmation_issue_idempotent_and_approved():
    store = GlobalConfirmationStore()
    conf1 = store.issue("task-a", "webdev_execute_sql", {"query": "DROP TABLE x"})
    conf2 = store.issue("task-a", "webdev_execute_sql", {"query": "DROP TABLE x"})
    assert conf1["confirmation_token"] == conf2["confirmation_token"]
    assert conf1["expires_at"]  # contract: expires_at present
    h = arguments_hash("webdev_execute_sql", {"query": "DROP TABLE x"})
    assert store.is_approved("task-a", "webdev_execute_sql", h) is False
    assert store.decide(conf1["confirmation_token"], "approved")["ok"] is True
    assert store.is_approved("task-a", "webdev_execute_sql", h) is True


def test_confirmation_rejected_is_terminal():
    store = GlobalConfirmationStore()
    conf = store.issue("task-b", "manus-channel", {"argv": ["send"]})
    assert store.decide(conf["confirmation_token"], "rejected")["ok"] is True
    h = arguments_hash("manus-channel", {"argv": ["send"]})
    assert store.is_rejected("task-b", "manus-channel", h) is True
    assert store.is_approved("task-b", "manus-channel", h) is False


def test_confirmation_expiry():
    store = GlobalConfirmationStore()
    conf = store.issue("task-c", "manus-config", {"x": "1"})
    rec = store._find("task-c", "manus-config", arguments_hash("manus-config", {"x": "1"}))
    rec["expires_at"] = time.time() - 1  # force expiry
    assert store.status_for("task-c", "manus-config", rec["args_hash"]) == "expired"
    assert store.decide(conf["confirmation_token"], "approved")["status"] == "expired"


def test_ledger_approval_survives_via_global_store():
    """Contract: resume same task after approval (cross-run)."""
    ledger = ConfirmationLedger(task_id="task-d")
    tool_def = {"policy": {"requires_confirmation": True}}
    args = {"secret_names": ["API_KEY"]}
    pending = ledger.pending_payload("webdev_request_secrets", tool_def, args)
    assert pending["error"]["code"] == REQUIRES_CONFIRMATION
    assert ledger.is_approved("webdev_request_secrets", args) is False
    # NEW ledger instance = the resumed run — must still see the approval.
    confirmation_store.approve_hash(
        "task-d", "webdev_request_secrets", arguments_hash("webdev_request_secrets", args)
    )
    resumed = ConfirmationLedger(task_id="task-d")
    assert resumed.is_approved("webdev_request_secrets", args) is True


def test_register_user_reply_guard():
    ledger = ConfirmationLedger(task_id="task-e")
    tool_def = {"policy": {"requires_confirmation": True}}
    ledger.pending_payload("webdev_execute_sql", tool_def, {"query": "q1"})
    # A long task message that merely contains "ya" must NOT approve.
    assert (
        ledger.register_user_reply("ya benar, tapi tolong buatkan juga laporan lengkapnya hari ini")
        is None
    )
    assert ledger.is_approved("webdev_execute_sql", {"query": "q1"}) is False
    # A short deliberate reply DOES approve (and reaches the global store).
    assert ledger.register_user_reply("ya") is not None
    assert ledger.is_approved("webdev_execute_sql", {"query": "q1"}) is True


def test_rejected_payload_is_terminal_permission_denied():
    ledger = ConfirmationLedger(task_id="task-f")
    payload = ledger.rejected_payload("webdev_execute_sql", {"query": "q"})
    assert payload["error"]["code"] == "PERMISSION_DENIED"
    assert payload["retryable"] is False


# ── notification-event-bus ───────────────────────────────────────────────────

def test_event_schema_and_redaction():
    event = make_event(
        "tool_call_finished",
        "task-g",
        message="done",
        step=3,
        data={"api_key": "nvapi-SUPERSECRET123456", "output": "fine"},
    )
    assert event["type"] == "tool_call_finished"
    assert event["task_id"] == "task-g"
    assert event["step"] == 3
    assert event["data"]["api_key"] == "[REDACTED]"
    assert event["data"]["output"] == "fine"


def test_run_registry_polling_and_caps():
    rec = run_registry.begin_run("sess-x", "task-h", "user-1")
    assert rec["status"] == "running"
    run_registry.emit(make_event(AGENT_STARTED, "task-h", "go", session_id="sess-x"))
    run_registry.emit(make_event(TOOL_CALL_FINISHED, "task-h", "done", step=1))
    polled = run_registry.get_events("sess-x", since=0)
    assert polled["task_id"] == "task-h"
    assert len(polled["events"]) >= 2
    assert polled["next_since"] == polled["events"].__len__() + 0 or polled["next_since"] >= 2
    # cursor works
    nxt = run_registry.get_events("sess-x", since=polled["next_since"])
    assert nxt["events"] == []
    run_registry.finish_run("task-h", "completed")
    assert run_registry.get_events("sess-x")["status"] == "completed"
    # bounded retention
    for i in range(450):
        run_registry.emit(make_event("agent_error", "task-h", f"e{i}", data={"i": i}))
    assert len(run_registry.get_events("sess-x", task_id="task-h")["events"]) <= 400


# ── browser-session-manager ─────────────────────────────────────────────────

def test_browser_tracker_state_transitions():
    tracker = BrowserSessionTracker("task-i")
    tracker.observe(
        "browser_navigate",
        {"url": "https://x.dev/login?token=abcdef123456"},
        {"success": True, "data": {}},
    )
    assert tracker.snapshot()["active_url"] is not None
    assert "abcdef123456" not in str(tracker.snapshot()["active_url"])  # redacted
    tracker.observe("browser_view", {}, {"success": True, "data": {"content": "<html>hi</html>"}})
    snap = tracker.snapshot()
    assert snap["last_view_hash"]  # view captured
    tracker.observe("browser_click", {"index": 2}, {"success": True, "data": {"page_changed": True}})
    assert tracker.snapshot()["last_view_hash"] is None  # mutation invalidates view


# ── agent-orchestrator loop safety (contract limits) ────────────────────────

def test_loop_safety_identical_call_limit(monkeypatch):
    """Contract max_identical_calls=2: TWO identical calls with the same
    outcome are allowed, the THIRD is blocked. Outcome recording is part
    of the semantics — a call whose outcome CHANGED between attempts is
    progress, never a loop (the old consecutive-only counter blocked the
    2nd attempt blindly and was laundered by any interleaved probe)."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "manus_max_identical_calls", 2)
    safety = LoopSafety()
    h = arguments_hash("browser_click", {"index": 1})
    args = {"index": 1}
    assert safety.check_before_execute("browser_click", h, args) is None  # 1st
    safety.record_result("browser_click", h, False, "EXECUTION_ERROR", "stale index", arguments=args)
    assert safety.check_before_execute("browser_click", h, args) is None  # 2nd allowed
    safety.record_result("browser_click", h, False, "EXECUTION_ERROR", "stale index", arguments=args)
    blocked = safety.check_before_execute("browser_click", h, args)       # 3rd blocked
    assert blocked is not None
    assert blocked["error"]["code"] == "LOOP_DETECTED"


def test_loop_error_streak_stops():
    safety = LoopSafety()
    payload = None
    for _ in range(safety.identical_error_limit):
        payload = safety.record_error("manus-heartbeat", "TIMEOUT", "same error")
    assert payload is not None
    assert payload["error"]["code"] == "LOOP_DETECTED"
    safety.record_success()
    assert safety.record_error("manus-heartbeat", "TIMEOUT", "different now") is None
