"""Regression tests for the MANDATORY first response (planner acknowledgement).

Bug report (screenshot, session "Coba js console Website Replit"): the first
assistant reply before the plan appears is intermittent — sometimes present,
sometimes the chat goes straight to the step list.

Root cause had two layers:
1. ``_should_stream_acknowledgement`` verb-gate missed common Indonesian
   phrasings ("coba", "cek", "bantu", "test", "lihat", URLs) so the streamed
   acknowledgement never even started.
2. No safety net: when the gate missed (or the ack LLM call failed / its text
   was suppressed as malformed JSON), the planner's ``plan.message`` — which
   the planner ALWAYS generates — was silently discarded on the steps>0 path,
   leaving the user with NO first response at all.

The fix guarantees a first response in every path:
- gate broadened (verbs + URL detection),
- ``ack_message_delivered`` tracking in the concurrent plan/ack loop,
- steps>0 and no delivered ack → plan.message becomes the first response,
- plan.message empty too → deterministic language-aware fallback line.
"""

import pytest

from app.domain.models.event import (
    DoneEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    TitleEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import ExecutionStatus, Plan, Step
from app.domain.models.session import SessionStatus
from app.domain.services.flows.plan_act import AgentStatus, PlanActFlow


# ─────────────────────────────────────────────────────────────────────────────
# Unit: the verb gate
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "Coba js console Website Replit",   # the exact message from the bug report
        "Coba buat akun facebook",
        "Cek harga bitcoin hari ini",
        "bantu fix bug ini",
        "test website nya",
        "lihat halaman itu",
        "Tolong uji dulu sistemnya",
        "kunjungi https://example.com dan ambil screenshot",
        "visit www.replit.com",
        "Buatkan laporan penjualan",
        "analyze this dataset",
    ],
)
def test_acknowledgement_gate_covers_task_like_messages(text):
    """Task-like phrasings must start the streamed acknowledgement."""
    assert PlanActFlow._should_stream_acknowledgement(Message(message=text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hai",
        "halo, apa kabar?",
        "terima kasih banyak",
        "ok",
        "siapa presiden indonesia sekarang?",
    ],
)
def test_acknowledgement_gate_skips_conversational_messages(text):
    """Pure conversation must NOT pre-ack (plan.message is the single answer)."""
    assert PlanActFlow._should_stream_acknowledgement(Message(message=text)) is False


# ─────────────────────────────────────────────────────────────────────────────
# Flow-level: the mandatory first response
# ─────────────────────────────────────────────────────────────────────────────

def _make_flow(plan: Plan, ack_llm_delivers: bool = True):
    """Build a PlanActFlow skeleton with mocked agents/repositories.

    planner.create_plan always returns ``plan``; acknowledge_stream optionally
    delivers an ack MessageEvent (set False to simulate the LLM ack failing or
    being suppressed as malformed JSON).
    """
    flow = PlanActFlow.__new__(PlanActFlow)
    flow._agent_id = "test-agent"
    flow._session_id = "sess-test"
    flow.status = AgentStatus.IDLE
    flow.plan = None

    # ── planner mock ──────────────────────────────────────────────────────
    planner = type("P", (), {})()
    planner._vision_model = None
    planner.roll_back = _async_noop()

    async def create_plan(msg):
        yield PlanEvent(status=PlanStatus.CREATED, plan=plan)

    planner.create_plan = create_plan

    async def acknowledge_stream(msg):
        if ack_llm_delivers:
            yield MessageEvent(role="assistant", message="Baik, saya mulai kerjakan.")

    planner.acknowledge_stream = acknowledge_stream

    async def update_plan(plan_, step_):
        yield PlanEvent(status=PlanStatus.UPDATED, plan=plan_)

    planner.update_plan = update_plan

    # ── executor mock ─────────────────────────────────────────────────────
    executor = type("E", (), {})()
    executor.roll_back = _async_noop()
    executor.compact_memory = _async_noop()

    async def execute_step(plan_, step_, msg):
        step_.status = ExecutionStatus.COMPLETED
        step_.success = True
        yield MessageEvent(role="assistant", message="langkah selesai", is_progress=True)

    executor.execute_step = execute_step

    async def summarize(attachments, current_request=None):
        yield MessageEvent(role="assistant", message="hasil akhir", is_final=True)

    executor.summarize = summarize

    flow.planner = planner
    flow.executor = executor

    # ── session repository mock ───────────────────────────────────────────
    session = type("S", (), {})()
    session.status = SessionStatus.PENDING
    session.get_last_plan = lambda: None

    repo = type("R", (), {})()
    repo.find_by_id = _async_return(session)
    repo.update_status = _async_noop()
    repo.update_title = _async_noop()
    repo.update_latest_message = _async_noop()
    repo.increment_unread_message_count = _async_noop()
    flow._session_repository = repo
    return flow


def _async_noop():
    async def _noop(*args, **kwargs):
        return None
    return _noop


def _async_return(value):
    async def _ret(*args, **kwargs):
        return value
    return _ret


async def _collect(flow, text):
    return [e async for e in flow.run(Message(message=text))]


def _first_response_before_plan(events):
    """Return the first standalone assistant MessageEvent emitted BEFORE the
    PlanEvent (excluding progress lines), or None."""
    for e in events:
        if isinstance(e, PlanEvent) and e.status == PlanStatus.CREATED:
            return None  # plan arrived without a preceding first response
        if isinstance(e, TitleEvent):
            return None
        if (
            isinstance(e, MessageEvent)
            and not e.is_progress
            and not e.is_final
            and (e.message or "").strip()
        ):
            return e
    return None


def _one_step_plan(message=None, language="id"):
    return Plan(
        title="Uji Console Replit",
        goal="Uji JS console di website Replit",
        language=language,
        message=message,
        steps=[Step(id="1", description="Buka website Replit dan uji console")],
    )


@pytest.mark.asyncio
async def test_gate_miss_still_emits_first_response_from_plan_message():
    """steps>0 + gate miss (no streamed ack) → plan.message MUST be emitted as
    the first response before the plan events.  This is the exact scenario of
    the bug report."""
    plan = _one_step_plan(message="Baik, saya akan membuka website Replit dan menguji console JS-nya.")
    flow = _make_flow(plan, ack_llm_delivers=True)  # gate False → never started
    events = await _collect(flow, "js console website replit")  # no verb → gate miss

    first = _first_response_before_plan(events)
    assert first is not None, "No first response before the plan — regression of the reported bug"
    assert first.message == plan.message


@pytest.mark.asyncio
async def test_ack_llm_failure_still_emits_first_response():
    """Gate OK (ack started) but the ack LLM delivers nothing (failure /
    suppressed JSON) → plan.message MUST still become the first response."""
    plan = _one_step_plan(message="Siap, saya cek console-nya sekarang.")
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "Buat website company profile")  # gate True

    first = _first_response_before_plan(events)
    assert first is not None, "Ack LLM failure left the user without any first response"
    assert first.message == plan.message


@pytest.mark.asyncio
async def test_deterministic_fallback_when_plan_message_also_empty():
    """steps>0 + gate miss + plan.message empty → deterministic fallback line
    (language-aware) instead of silence."""
    plan = _one_step_plan(message=None, language="id")
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "js console website replit")

    first = _first_response_before_plan(events)
    assert first is not None
    assert first.message == "Baik, saya mulai pengerjaannya."


@pytest.mark.asyncio
async def test_deterministic_fallback_english():
    plan = _one_step_plan(message=None, language="en")
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "js console website replit")

    first = _first_response_before_plan(events)
    assert first is not None
    assert first.message == "On it — starting now."


@pytest.mark.asyncio
async def test_no_double_response_when_ack_delivered():
    """When the streamed ack DID deliver text, the fallback must NOT fire —
    exactly one first response, no duplicate bubbles."""
    plan = _one_step_plan(message="Pesan planner yang tidak boleh dobel.")
    flow = _make_flow(plan, ack_llm_delivers=True)
    events = await _collect(flow, "Buat website company profile")  # gate True

    firsts = []
    for e in events:
        if isinstance(e, (PlanEvent,)) and e.status == PlanStatus.CREATED:
            break
        if (
            isinstance(e, MessageEvent)
            and not e.is_progress
            and not e.is_final
            and (e.message or "").strip()
        ):
            firsts.append(e.message)
    assert firsts == ["Baik, saya mulai kerjakan."], f"Expected single ack, got: {firsts}"


@pytest.mark.asyncio
async def test_conversational_zero_step_plan_answered_directly():
    """0-step conversational plan → plan.message is the final answer; the
    deterministic fallback covers the empty-message edge case."""
    plan = Plan(title="Sapaan", goal="", language="id", message=None, steps=[])
    flow = _make_flow(plan, ack_llm_delivers=True)
    events = await _collect(flow, "Hai")

    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1
    assert finals[0].message == "Baik, saya mulai pengerjaannya."


@pytest.mark.asyncio
async def test_flow_completes_end_to_end():
    """Sanity: the mocked flow still runs to completion and emits DoneEvent."""
    plan = _one_step_plan(message="Baik, saya mulai.")
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "js console website replit")

    assert any(isinstance(e, DoneEvent) for e in events)
    assert any(
        isinstance(e, PlanEvent) and e.status == PlanStatus.COMPLETED for e in events
    )
