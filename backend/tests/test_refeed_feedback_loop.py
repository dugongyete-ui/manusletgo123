"""Regression tests for the re-feed feedback loop (fixed 2026-09-05).

THE BUG (live incident, session 7cc82e8f44a341a9 "Latest Persib News from
Kompas Bola"): after a backend restart the in-memory task registry is empty,
a stuck RUNNING status makes every SSE reconnect enter the recovery path, and
recovery re-queued ``session.latest_message`` as a USER message — but the
runner also updates that field for AGENT output. The agent's own narration
("We've reached Persib's official site…") was re-injected as user input, the
agent answered itself in discuss mode, the reply became the new
latest_message, and the loop repeated on every reload (4 re-feeds observed).

These tests pin the fix:
- recovery resolves input from the persisted EVENT LOG (provenance-safe),
  never from latest_message;
- a stale RUNNING/IN_QUEUE status resolves honestly (COMPLETED when a final
  summary exists, FAILED + explanation otherwise) instead of re-feeding;
- concurrent reconnects share ONE recovery via the in-flight registry;
- WAITING answers are no longer flipped to IN_QUEUE (ask_user resume path);
- reconnect dedup compares against the last USER message timestamp, not the
  narration-updated preview timestamp.
"""
import asyncio
import json
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock

import pytest

from app.domain.models.event import (
    MessageEvent,
    ToolEvent,
    ToolStatus,
    TitleEvent,
    DoneEvent,
    ErrorEvent,
)
from app.domain.models.session import Session, SessionStatus
from app.domain.services.agent_domain_service import AgentDomainService


# ── helpers ──────────────────────────────────────────────────────────────────

def _tool(name="browser_navigate") -> ToolEvent:
    return ToolEvent(
        tool_call_id="call-1",
        tool_name="browser",
        function_name=name,
        function_args={},
        status=ToolStatus.CALLED,
    )


def _tool(name: str = "browser_navigate") -> ToolEvent:
    return ToolEvent(
        tool_call_id="call-1",
        tool_name="browser",
        function_name=name,
        function_args={},
        status=ToolStatus.CALLED,
    )


def _session(events, status=SessionStatus.RUNNING, **kw) -> Session:
    s = Session(agent_id="agent-1", user_id="u1", **kw)
    s.events = events
    s.status = status
    s.task_id = None
    return s


class _FakeQueue:
    def __init__(self):
        self.put_calls: list[str] = []

    async def put(self, payload: str) -> str:
        self.put_calls.append(payload)
        return f"{len(self.put_calls)}-0"

    async def get(self, start_id=None, block_ms=None):
        return (None, None)


class _FakeTask:
    def __init__(self):
        self.id = "task-1"
        self.input_stream = _FakeQueue()
        self.output_stream = _FakeQueue()
        self.done = False

    async def run(self) -> None:
        self.done = True

    def cancel(self) -> bool:
        return True


def _make_repo(session) -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_id_and_user_id = AsyncMock(return_value=session)
    repo.find_by_id = AsyncMock(return_value=session)
    return repo


def _make_service(repo) -> AgentDomainService:
    svc = AgentDomainService(
        agent_repository=AsyncMock(),
        session_repository=repo,
        sandbox_cls=AsyncMock(),
        task_cls=AsyncMock(),
        file_storage=AsyncMock(),
        mcp_repository=AsyncMock(),
    )
    svc._get_task = AsyncMock(return_value=None)
    svc._create_task = AsyncMock(return_value=None)
    return svc


@pytest.fixture(autouse=True)
def _clean_registries():
    AgentDomainService._inflight_setups.clear()
    AgentDomainService._session_locks.clear()
    yield
    AgentDomainService._inflight_setups.clear()
    AgentDomainService._session_locks.clear()


# ── 1. Provenance scan: the exact incident scenario ─────────────────────────

def test_narration_after_user_message_is_not_recoverable():
    """THE incident: user task → tools → agent narration. Nothing to recover."""
    session = _session([
        MessageEvent(role="user", message="Latest Persib News from Kompas Bola"),
        _tool(),
        MessageEvent(role="assistant", message="We've reached Persib's official site…", is_progress=True),
    ])
    session.latest_message = "We've reached Persib's official site…"
    assert AgentDomainService._last_unprocessed_user_message(session) is None


def test_agent_final_reply_after_user_message_is_not_recoverable():
    session = _session([
        MessageEvent(role="user", message="buat laporan"),
        MessageEvent(role="assistant", message="laporan selesai", is_final=True),
        DoneEvent(),
    ])
    assert AgentDomainService._last_unprocessed_user_message(session) is None


def test_plan_or_tool_activity_marks_message_processed():
    """A run that merely STARTED (title/plan/step/tool) is not recoverable —
    re-queueing it would restart finished work from scratch."""
    session = _session([
        MessageEvent(role="user", message="riset persib"),
        TitleEvent(title="Riset"),
    ])
    assert AgentDomainService._last_unprocessed_user_message(session) is None


def test_trailing_user_message_is_recoverable():
    session = _session([MessageEvent(role="user", message="halo, tolong buat")])
    assert AgentDomainService._last_unprocessed_user_message(session) == "halo, tolong buat"


def test_empty_log_falls_back_to_user_pointer_only():
    session = _session([])
    session.latest_user_message = "pesan asli"
    session.latest_message = "narasi agent"  # must be ignored
    assert AgentDomainService._last_unprocessed_user_message(session) == "pesan asli"


def test_empty_log_ignores_agent_preview_text():
    session = _session([])
    session.latest_message = "narasi agent"
    session.latest_user_message = None
    assert AgentDomainService._last_unprocessed_user_message(session) is None


def test_blank_user_message_not_recoverable():
    session = _session([MessageEvent(role="user", message="   ")])
    assert AgentDomainService._last_unprocessed_user_message(session) is None


# ── 2. Honest stale-status resolution ────────────────────────────────────────

def test_last_assistant_was_final_true():
    session = _session([
        MessageEvent(role="user", message="tugas"),
        MessageEvent(role="assistant", message="ringkasan akhir", is_final=True),
    ])
    assert AgentDomainService._last_assistant_was_final(session) is True


def test_last_assistant_was_final_false_for_progress():
    session = _session([
        MessageEvent(role="user", message="tugas"),
        MessageEvent(role="assistant", message="sedang berjalan", is_progress=True),
    ])
    assert AgentDomainService._last_assistant_was_final(session) is False


# ── 3. chat() recovery: no re-feed of agent narration (stuck RUNNING) ────────

async def test_chat_recovery_does_not_refeed_agent_narration():
    """Stuck RUNNING + agent narration last → FAILED + ErrorEvent, no re-queue."""
    events = [
        MessageEvent(role="user", message="Latest Persib News"),
        _tool("browser_console_exec"),
        MessageEvent(role="assistant", message="We've reached Persib's official site…", is_progress=True),
    ]
    session = _session(events, status=SessionStatus.RUNNING)
    session.latest_message = "We've reached Persib's official site…"
    repo = _make_repo(session)
    svc = _make_service(repo)

    out = [e async for e in svc.chat("s1", "u1", message=None)]

    # No task was created, nothing was queued — the narration was NOT re-fed.
    svc._create_task.assert_not_called()
    assert session.task_id is None
    # Status resolved honestly to FAILED with a persisted explanation.
    statuses = [c.args[1] for c in repo.update_status.call_args_list]
    assert SessionStatus.FAILED in statuses
    assert any(isinstance(e, ErrorEvent) for e in out)
    assert repo.add_event.called  # the explanation event is persisted


async def test_chat_recovery_completes_when_final_summary_exists():
    events = [
        MessageEvent(role="user", message="tugas"),
        MessageEvent(role="assistant", message="selesai — ringkasan", is_final=True),
    ]
    session = _session(events, status=SessionStatus.RUNNING)
    repo = _make_repo(session)
    svc = _make_service(repo)

    out = [e async for e in svc.chat("s1", "u1", message=None)]

    svc._create_task.assert_not_called()
    statuses = [c.args[1] for c in repo.update_status.call_args_list]
    assert SessionStatus.COMPLETED in statuses
    assert any(isinstance(e, DoneEvent) for e in out)
    assert not repo.add_event.called


# ── 4. chat() recovery: genuine orphaned user message IS re-fed once ─────────

async def test_chat_recovery_refeeds_genuine_user_message_once():
    """Message persisted but never processed (restart during boot) → exactly
    one re-queue, sourced from the event log, no duplicate bubble persist."""
    events = [MessageEvent(role="user", message="halo, buat ringkasan")]
    session = _session(events, status=SessionStatus.IN_QUEUE)
    session.latest_message = "halo, buat ringkasan"
    repo = _make_repo(session)
    svc = _make_service(repo)
    fake_task = _FakeTask()
    svc._create_task = AsyncMock(return_value=fake_task)

    _ = [e async for e in svc.chat("s1", "u1", message=None)]

    svc._create_task.assert_awaited_once()
    assert len(fake_task.input_stream.put_calls) == 1
    payload = json.loads(fake_task.input_stream.put_calls[0])
    assert payload["role"] == "user"
    assert payload["message"] == "halo, buat ringkasan"
    # The user message is already persisted — recovery must NOT persist again
    # (that used to duplicate the bubble on reload).
    assert not repo.add_event.called


async def test_concurrent_reconnects_share_one_recovery():
    """Two simultaneous chat() reconnects → one _create_task, one put."""
    events = [MessageEvent(role="user", message="tugas orphan")]
    session = _session(events, status=SessionStatus.IN_QUEUE)
    repo = _make_repo(session)
    svc = _make_service(repo)
    fake_task = _FakeTask()

    async def _slow_create(session_arg):
        await asyncio.sleep(0.05)
        return fake_task

    svc._create_task = _slow_create

    async def _drive():
        return [e async for e in svc.chat("s1", "u1", message=None)]

    await asyncio.gather(_drive(), _drive())

    assert len(fake_task.input_stream.put_calls) == 1


# ── 5. WAITING answer: no IN_QUEUE flip (ask_user resume regression) ─────────

async def test_waiting_answer_is_not_flipped_to_in_queue():
    """An ask_user answer must keep WAITING so the flow resumes EXECUTING and
    the discuss gate stays in agent mode (T45 regression: the flip made the
    WAITING→EXECUTING branch dead code)."""
    events = [
        MessageEvent(role="user", message="buat laporan"),
        MessageEvent(role="assistant", message="berapa halaman?", is_question=True),
    ]
    session = _session(events, status=SessionStatus.WAITING)
    repo = _make_repo(session)
    svc = _make_service(repo)
    fake_task = _FakeTask()
    svc._create_task = AsyncMock(return_value=fake_task)

    _ = [e async for e in svc.chat("s1", "u1", message="5 halaman saja", timestamp=datetime.now(UTC))]

    statuses = [c.args[1] for c in repo.update_status.call_args_list]
    assert SessionStatus.IN_QUEUE not in statuses
    # Provenance pointer written for the genuine user input.
    assert repo.update_latest_user_message.await_count == 1
    assert repo.update_latest_user_message.await_args.args[1] == "5 halaman saja"
    assert len(fake_task.input_stream.put_calls) == 1


# ── 6. Reconnect dedup: user-message timestamp, not narration timestamp ──────

async def test_dedup_uses_user_timestamp_not_narration_timestamp():
    """User follow-up sent 3 s after an AGENT narration (5 s after their own
    last message is > 10 s… actually: narration at t-2s, user's previous
    message at t-5min). The OLD code compared against latest_message_at
    (the narration) and wrongly dropped the follow-up as a reconnect."""
    now = datetime.now(UTC)
    session = _session([
        MessageEvent(role="user", message="tugas awal"),
        MessageEvent(role="assistant", message="sedang mencari…", is_progress=True),
    ], status=SessionStatus.RUNNING)
    session.latest_message_at = now - timedelta(seconds=2)      # narration time
    session.latest_user_message_at = now - timedelta(minutes=5)
    repo = _make_repo(session)
    svc = _make_service(repo)
    fake_task = _FakeTask()
    svc._get_task = AsyncMock(return_value=fake_task)
    fake_task.done = True  # drain loop breaks immediately

    _ = [e async for e in svc.chat("s1", "u1", message="tambahkan juga harga sahamnya", timestamp=now)]

    # NOT treated as a reconnect duplicate — the message must be queued.
    assert len(fake_task.input_stream.put_calls) == 1
    assert repo.update_latest_user_message.await_count == 1


async def test_true_reconnect_is_still_deduped():
    """fetchEventSource retry of the SAME message within 10 s while RUNNING
    is still skipped (the original purpose of the dedup)."""
    now = datetime.now(UTC)
    session = _session([], status=SessionStatus.RUNNING)
    session.latest_message_at = now - timedelta(seconds=2)
    session.latest_user_message_at = now - timedelta(seconds=2)
    repo = _make_repo(session)
    svc = _make_service(repo)
    fake_task = _FakeTask()
    svc._get_task = AsyncMock(return_value=fake_task)
    fake_task.done = True  # drain loop breaks immediately

    _ = [e async for e in svc.chat("s1", "u1", message="pesan yang sama", timestamp=now)]

    assert len(fake_task.input_stream.put_calls) == 0
    assert not repo.add_event.called
