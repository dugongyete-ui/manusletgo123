"""Regression tests for the MANDATORY first response (streamed first reply).

Bug report (screenshot, session "Coba js console Website Replit"): the first
assistant reply before the plan appears is intermittent — sometimes present,
sometimes the chat goes straight to the step list.

The original fix broadened a hardcoded verb list ("coba", "cek", "bantu",
"test", "lihat", ...) that gated the streamed acknowledgement. That list was
itself a template heuristic: it could never cover every phrasing in every
language, so the reply kept disappearing for uncovered messages.

The architecture is now GATE-FREE:
- The streamed first reply starts for EVERY message, concurrently with
  planning — no keyword/verb list decides anything (SKILL.md: awareness over
  instruction; the model judges the message, not a word list).
- The reply model itself distinguishes message kinds: tasks get a one-line
  acknowledgement, purely conversational messages get a direct answer (see
  PlannerAgent._acknowledgement_chunks).
- ``ack_message_delivered`` tracking in the concurrent plan/reply loop:
  steps>0 and no delivered reply → the planner's ``plan.message`` becomes
  the first response; plan.message empty too → deterministic fallback line.
- 0-step conversational plans: when the streamed reply already answered, it
  IS the single response — plan.message is suppressed so no duplicate bubble
  appears; when the reply failed, plan.message (or the fallback) is the
  final answer.
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
# Flow-level: the first reply always streams — no gate, any phrasing
# ─────────────────────────────────────────────────────────────────────────────

def _make_flow(plan: Plan, ack_llm_delivers: bool = True):
    """Build a PlanActFlow skeleton with mocked agents/repositories.

    planner.create_plan always returns ``plan``; acknowledge_stream optionally
    delivers a first-reply MessageEvent (set False to simulate the reply LLM
    failing or being suppressed as malformed JSON).
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

    async def acknowledge_stream(msg, conversation_history=None):
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


@pytest.mark.parametrize(
    "text",
    [
        "Coba js console Website Replit",   # the exact message from the bug report
        "Coba buat akun facebook",
        "Cek harga bitcoin hari ini",
        "bantu fix bug ini",
        "test website nya",
        "lihat halaman itu",
        "js console website replit",        # no recognizable verb at all
        "Hai",                              # conversational — also gets the reply
        "terima kasih banyak",
        "analyze this dataset",
    ],
)
@pytest.mark.asyncio
async def test_first_reply_streams_for_every_message(text):
    """GATE-FREE: every message — task-like OR conversational, with or without
    any recognizable verb — starts the streamed first reply, which appears
    before the plan. The old hardcoded verb list could never guarantee this."""
    plan = _one_step_plan(message="Pesan planner cadangan.")
    flow = _make_flow(plan, ack_llm_delivers=True)
    events = await _collect(flow, text)

    first = _first_response_before_plan(events)
    assert first is not None, f"No streamed first response for: {text!r}"
    assert first.message == "Baik, saya mulai kerjakan."


@pytest.mark.asyncio
async def test_first_reply_llm_failure_still_emits_first_response():
    """Reply LLM delivers nothing (failure / suppressed JSON) → plan.message
    MUST still become the first response."""
    plan = _one_step_plan(message="Siap, saya cek console-nya sekarang.")
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "Buat website company profile")

    first = _first_response_before_plan(events)
    assert first is not None, "Reply LLM failure left the user without any first response"
    assert first.message == plan.message


@pytest.mark.asyncio
async def test_deterministic_fallback_when_plan_message_also_empty():
    """steps>0 + no delivered reply + plan.message empty → deterministic
    fallback line (language-aware) instead of silence."""
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
async def test_no_double_response_when_reply_delivered():
    """When the streamed reply DID deliver text, the fallback must NOT fire —
    exactly one first response, no duplicate bubbles."""
    plan = _one_step_plan(message="Pesan planner yang tidak boleh dobel.")
    flow = _make_flow(plan, ack_llm_delivers=True)
    events = await _collect(flow, "Buat website company profile")

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
    assert firsts == ["Baik, saya mulai kerjakan."], f"Expected single reply, got: {firsts}"


# ─────────────────────────────────────────────────────────────────────────────
# Conversational (0-step) plans: single answer, no duplicate bubble
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conversational_reply_is_the_single_answer():
    """0-step conversational plan + delivered streamed reply → the reply IS
    the one and only assistant message; plan.message must NOT create a second
    bubble."""
    plan = Plan(
        title="Sapaan",
        goal="",
        language="id",
        message="Hai juga! Ada yang bisa saya bantu?",
        steps=[],
    )
    flow = _make_flow(plan, ack_llm_delivers=True)
    events = await _collect(flow, "Hai")

    assistant_msgs = [
        e for e in events
        if isinstance(e, MessageEvent) and (e.message or "").strip()
    ]
    assert len(assistant_msgs) == 1, (
        f"Expected exactly one assistant message (the streamed reply), "
        f"got: {[m.message for m in assistant_msgs]}"
    )
    assert assistant_msgs[0].message == "Baik, saya mulai kerjakan."
    assert not assistant_msgs[0].is_final


@pytest.mark.asyncio
async def test_conversational_reply_failure_answers_via_plan_message():
    """0-step conversational plan + reply LLM failure → plan.message is the
    final answer (safety net intact)."""
    plan = Plan(
        title="Sapaan",
        goal="",
        language="id",
        message="Hai juga! Ada yang bisa saya bantu?",
        steps=[],
    )
    flow = _make_flow(plan, ack_llm_delivers=False)
    events = await _collect(flow, "Hai")

    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1
    assert finals[0].message == "Hai juga! Ada yang bisa saya bantu?"


@pytest.mark.asyncio
async def test_conversational_empty_message_and_reply_failure_hits_fallback():
    """0-step + empty plan.message + reply failure → deterministic fallback
    line instead of silence."""
    plan = Plan(title="Sapaan", goal="", language="id", message=None, steps=[])
    flow = _make_flow(plan, ack_llm_delivers=False)
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
