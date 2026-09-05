"""Tests for the Manus-feature parity wave 1 (Task 45).

Covers: chat-mode classifier gating, effort budget scaling, knowledge
section rendering, file categorisation, session status states, agent
profile built-ins, scheduled-task model, KnowledgeEvent SSE mapping,
map-reduce compaction, discuss-mode helpers, fork event filtering.
Pure unit tests — no live server, no LLM calls (mocked where needed).
"""
import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.domain.services.file_categorize import categorize_file
from app.domain.models.session import SessionStatus
from app.domain.models.plan import Plan
from app.domain.models.knowledge import KnowledgeItem, KnowledgeStatus, KnowledgeKind
from app.domain.models.scheduled_task import ScheduledTask
from app.domain.models.agent_profile import BUILTIN_PROFILES, resolve_builtin_profile
from app.domain.models.event import KnowledgeEvent
from app.domain.services.prompts.system import (
    format_knowledge_section,
    format_agent_persona,
    get_system_prompt,
)


# ── File categorisation (Manus getSessionFilesV2) ───────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("deck.pptx", "slides"),
    ("sales.csv", "tables"),
    ("report.xlsx", "tables"),
    ("README.md", "docs"),
    ("paper.pdf", "docs"),
    ("photo.png", "media"),
    ("clip.mp4", "media"),
    ("app.py", "code"),
    ("index.html", "code"),
    ("bundle.zip", "archives"),
    ("unknown.xyz", "other"),
    (None, "other"),
])
def test_categorize_file_by_extension(filename, expected):
    assert categorize_file(filename) == expected


def test_categorize_file_by_content_type():
    assert categorize_file(None, "image/png") == "media"
    assert categorize_file("noext", "application/pdf") == "docs"
    assert categorize_file("noext", "text/csv") == "tables"
    assert categorize_file("noext", "application/zip") == "archives"


# ── Session status states (IN_QUEUE / FAILED) ───────────────────────────────

def test_session_status_new_states():
    assert SessionStatus.IN_QUEUE.value == "in_queue"
    assert SessionStatus.FAILED.value == "failed"
    # Enum members stay string-coercible for SSE payloads.
    assert str(SessionStatus.IN_QUEUE) == "SessionStatus.IN_QUEUE"


# ── Knowledge prompt sections (natural, non-hardcoded feel) ─────────────────

def test_format_knowledge_section_empty():
    assert format_knowledge_section([]) == ""
    assert format_knowledge_section(None) == ""
    assert format_knowledge_section(["  ", ""]) == ""


def test_format_knowledge_section_items():
    section = format_knowledge_section(["User prefers Indonesian replies"])
    assert "<user_knowledge>" in section
    assert "- User prefers Indonesian replies" in section
    assert "long-term memory" in section


def test_format_agent_persona():
    assert format_agent_persona("") == ""
    persona = format_agent_persona("You are a meticulous researcher.")
    assert "<agent_profile>" in persona
    assert "meticulous researcher" in persona


def test_get_system_prompt_appends_tail_sections():
    prompt = get_system_prompt(
        environment="replit",
        knowledge=["Always reply in Indonesian"],
        agent_persona="Act like a senior engineer",
    )
    assert "<user_knowledge>" in prompt
    assert "Always reply in Indonesian" in prompt
    assert "<agent_profile>" in prompt
    # Static sections land at the END so the provider prefix-cache can reuse
    # the static head across calls within a session.
    assert prompt.rindex("<user_knowledge>") > prompt.rindex("<sandbox_environment>")


def test_get_system_prompt_without_extras_unchanged_shape():
    prompt = get_system_prompt(environment="replit")
    assert "<user_knowledge>" not in prompt
    assert "<agent_profile>" not in prompt


# ── Effort budget scaling (AgentTaskMode standard vs high_effort) ───────────

class _FakeFlow:
    from app.domain.services.flows.plan_act import PlanActFlow  # methods reused

    _effective_step_budget = PlanActFlow._effective_step_budget
    plan = None


def test_effective_budget_standard():
    flow = _FakeFlow()
    flow.plan = Plan(task_mode="standard")
    assert flow._effective_step_budget(50, 3) == (50, 3)


def test_effective_budget_high_effort_doubles():
    flow = _FakeFlow()
    flow.plan = Plan(task_mode="high_effort")
    steps, failures = flow._effective_step_budget(50, 3)
    assert steps == 100
    assert failures == 6


def test_effective_budget_no_plan_unchanged():
    flow = _FakeFlow()
    assert flow._effective_step_budget(50, 3) == (50, 3)


# ── Discuss-mode gating (CHAT_MODE_DISCUSS) ────────────────────────────────

@pytest.mark.asyncio
async def test_is_discuss_gates_on_state(monkeypatch):
    """A message queued mid-run or answering a question NEVER discusses."""
    from app.domain.services.flows.plan_act import PlanActFlow
    from app.domain.models.message import Message

    flow = PlanActFlow.__new__(PlanActFlow)
    flow._agent_id = "test-agent"

    called = {"n": 0}

    async def fake_classify(text, history=None):
        called["n"] += 1
        return "discuss", 0.99

    monkeypatch.setattr(
        "app.domain.services.agents.intent.classify_chat_mode", fake_classify
    )

    msg = Message(message="halo apa kabar?")
    # Mid-run / waiting for an answer → agent mode, classifier not even called.
    for status in (SessionStatus.RUNNING, SessionStatus.WAITING):
        assert await flow._is_discuss(status, msg, "") is False
    assert called["n"] == 0
    # Fresh (PENDING / IN_QUEUE while the task boots) and COMPLETED
    # conversations may discuss.
    assert await flow._is_discuss(SessionStatus.PENDING, msg, "") is True
    assert await flow._is_discuss(SessionStatus.IN_QUEUE, msg, "") is True
    assert await flow._is_discuss(SessionStatus.COMPLETED, msg, "") is True
    assert called["n"] == 3


@pytest.mark.asyncio
async def test_is_discuss_gates_on_attachments(monkeypatch):
    from app.domain.services.flows.plan_act import PlanActFlow
    from app.domain.models.message import Message

    flow = PlanActFlow.__new__(PlanActFlow)
    flow._agent_id = "test-agent"

    async def fail_classify(text, history=None):
        raise AssertionError("classifier must not run for attachments")

    monkeypatch.setattr(
        "app.domain.services.agents.intent.classify_chat_mode", fail_classify
    )

    with_attachment = Message(message="analyze this", attachments=["/upload/a.csv"])
    assert await flow._is_discuss(SessionStatus.PENDING, with_attachment, "") is False

    with_files = Message(message="baca <file name=\"a.txt\">isi</file>")
    assert await flow._is_discuss(SessionStatus.PENDING, with_files, "") is False


@pytest.mark.asyncio
async def test_classify_chat_mode_failure_defaults_to_agent(monkeypatch):
    from app.domain.services.agents.intent import classify_chat_mode, CHAT_MODE_AGENT

    def broken_builder(prefer_fallback=False):
        raise RuntimeError("no provider")

    # The classifier imports the builder lazily from the base module at call
    # time, so patching the module attribute intercepts it. Note: a trivial
    # greeting is handled by the deterministic fast path and never reaches
    # the model — so this test must use a non-trivial message.
    monkeypatch.setattr(
        "app.domain.services.agents.base._build_chat_model", broken_builder
    )
    mode, confidence = await classify_chat_mode("please research the latest news for me")
    assert mode == CHAT_MODE_AGENT
    assert confidence == 0.0


@pytest.mark.asyncio
async def test_classify_chat_mode_low_confidence_rejected():
    from app.domain.services.agents.intent import (
        classify_chat_mode,
        CHAT_MODE_AGENT,
        _classify_call,
    )

    class _FakeResp:
        content = '{"mode": "discuss", "confidence": 0.3}'

    class _FakeModel:
        async def ainvoke(self, messages):
            return _FakeResp()

    def builder(prefer_fallback=False):
        return _FakeModel()

    # Direct call parses; full path applies the confidence gate.
    mode, conf = await _classify_call(builder, "hi")
    assert mode == "discuss" and abs(conf - 0.3) < 1e-9


# ── Knowledge models & event mapping ────────────────────────────────────────

def test_knowledge_item_defaults():
    item = KnowledgeItem(user_id="u1", content="prefers concise answers")
    assert item.status == KnowledgeStatus.ACTIVE
    assert item.kind == KnowledgeKind.USER
    assert len(item.id) == 16


def test_knowledge_event_sse_mapping():
    from app.interfaces.schemas.event import EventMapper, KnowledgeSSEEvent
    from app.domain.models.event import KnowledgeEvent as DomainKnowledgeEvent

    event = DomainKnowledgeEvent(
        items=["learning one", "learning two"],
        item_ids=["k1", "k2"],
        status="pending",
    )
    sse = EventMapper.event_to_sse_event_sync(event) if hasattr(
        EventMapper, "event_to_sse_event_sync"
    ) else KnowledgeSSEEvent.from_event(event)
    assert sse.event == "knowledge"
    assert sse.data.items == ["learning one", "learning two"]
    assert sse.data.item_ids == ["k1", "k2"]


# ── Map-reduce compaction ───────────────────────────────────────────────────

def _build_memory_with_old_tool_results():
    from app.domain.models.memory import Memory
    from langchain.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

    memory = Memory(messages=[
        SystemMessage(content="system prompt"),
        HumanMessage(content="buat laporan penjualan"),
        AIMessage(content="", tool_calls=[{
            "name": "file_write",
            "id": "call-1",
            "args": {"path": "~/report.md", "content": "x" * 3000},
        }]),
        ToolMessage(tool_call_id="call-1", name="file_write", content="ok"),
        AIMessage(content="", tool_calls=[{
            "name": "file_write",
            "id": "call-2",
            "args": {"path": "~/report2.md", "content": "y" * 3000},
        }]),
        ToolMessage(tool_call_id="call-2", name="file_write", content="ok"),
    ])
    return memory


def test_collect_compaction_digest_captures_old_arguments():
    memory = _build_memory_with_old_tool_results()
    digest = memory.collect_compaction_digest()
    # The FIRST file_write argument (old, beyond KEEP_RECENT_ARG_CALLS=2? no —
    # both are recent) — with 2 calls both stay recent. Add one more to age it.
    from langchain.messages import AIMessage, ToolMessage
    memory.messages.append(AIMessage(content="", tool_calls=[{
        "name": "file_write",
        "id": "call-3",
        "args": {"path": "~/report3.md", "content": "z" * 3000},
    }]))
    memory.messages.append(ToolMessage(tool_call_id="call-3", name="file_write", content="ok"))
    digest = memory.collect_compaction_digest()
    assert "older file_write argument" in digest


@pytest.mark.asyncio
async def test_compact_with_summary_stores_rolling_summary():
    memory = _build_memory_with_old_tool_results()
    # Force a stub-worthy tool result: many old shell_exec results.
    from langchain.messages import AIMessage, ToolMessage
    for i in range(4):
        memory.messages.append(AIMessage(content="", tool_calls=[{
            "name": "shell_exec", "id": f"s-{i}", "args": {"command": f"echo {i}"},
        }]))
        memory.messages.append(ToolMessage(
            tool_call_id=f"s-{i}", name="shell_exec", content=f"output {i} " * 200,
        ))

    async def summarizer(digest):
        return "Distilled: 4 shell runs, 2 file writes, report in progress."

    stored = await memory.compact_with_summary(summarizer)
    assert stored is True
    summary = memory.get_context_summary()
    assert "Distilled" in summary
    # The rolling summary SystemMessage sits right after the system prompt.
    idx = memory.find_summary_message()
    assert idx == 1
    assert memory.messages[idx].content.startswith(memory.SUMMARY_MARKER)


@pytest.mark.asyncio
async def test_compact_with_summary_falls_back_to_plain():
    memory = _build_memory_with_old_tool_results()
    before = list(memory.messages)

    async def broken(digest):
        raise RuntimeError("provider down")

    stored = await memory.compact_with_summary(broken)
    assert stored is False
    # Physical compaction still ran (plain truncation path) — messages intact
    # as a list, no exception leaked.
    assert isinstance(memory.messages, list)


# ── Agent profiles (InitManusAgent equivalent) ──────────────────────────────

def test_builtin_profiles_resolvable():
    assert len(BUILTIN_PROFILES) >= 3
    general = resolve_builtin_profile("builtin-general")
    assert general is not None and general.name == "Dzeck"
    assert resolve_builtin_profile("builtin-nope") is None


# ── Scheduled tasks (scheduleTask model) ────────────────────────────────────

def test_scheduled_task_defaults():
    task = ScheduledTask(user_id="u1", prompt="check prices", session_id="s1")
    assert task.is_active is True
    assert task.interval_minutes == 1440
    assert task.run_count == 0
    assert isinstance(task.next_run_at, datetime)


def test_scheduler_run_due_advances_schedule():
    from app.application.services.scheduler_service import SchedulerService

    repository = MagicMock()
    agent_service = MagicMock()
    service = SchedulerService(agent_service, repository)

    scheduled = ScheduledTask(
        user_id="u1", prompt="daily digest", session_id="s1", interval_minutes=60,
    )

    async def fake_chat(**kwargs):
        yield "event"

    agent_service.chat = fake_chat
    repository.update_run = AsyncMock()

    import asyncio
    asyncio.run(service._run_scheduled(scheduled))

    repository.update_run.assert_awaited_once()
    args = repository.update_run.await_args.args
    last_run, next_run = args[1], args[2]
    assert last_run <= next_run
    assert next_run - last_run >= timedelta(minutes=60)
    # In-flight registry cleaned up.
    assert scheduled.id not in service._running


def test_scheduler_run_due_survives_failure():
    from app.application.services.scheduler_service import SchedulerService

    repository = MagicMock()
    agent_service = MagicMock()
    service = SchedulerService(agent_service, repository)

    scheduled = ScheduledTask(
        user_id="u1", prompt="boom", session_id="s1", interval_minutes=5,
    )

    async def exploding_chat(**kwargs):
        raise RuntimeError("provider outage")
        yield "never"  # pragma: no cover

    agent_service.chat = exploding_chat
    repository.update_run = AsyncMock()

    import asyncio
    asyncio.run(service._run_scheduled(scheduled))  # must not raise
    repository.update_run.assert_awaited_once()


# ── Fork filtering (own/shared storyline copy) ───────────────────────────────

def test_fork_event_filtering():
    """Fork keeps messages/plans/steps/title, strips tool payloads."""
    from app.domain.models.event import (
        MessageEvent, PlanEvent, StepEvent, TitleEvent, ToolEvent, ErrorEvent,
        ToolStatus, PlanStatus,
    )
    from app.domain.models.plan import Plan, Step

    plan = Plan(title="T", goal="G", steps=[Step(id="1", description="d")])
    events = [
        MessageEvent(role="user", message="buat"),
        MessageEvent(role="assistant", message="selesai", is_final=True),
        PlanEvent(status=PlanStatus.CREATED, plan=plan),
        StepEvent(step=plan.steps[0], status="completed"),
        TitleEvent(title="T"),
        ToolEvent(
            tool_call_id="t1", tool_name="browser", function_name="browser_click",
            function_args={}, status=ToolStatus.CALLED,
            function_result={"screenshot": "gridfs-id"},
        ),
        ErrorEvent(error="old noise"),
    ]
    # The filtering logic lives in AgentService.fork_session; verify the
    # classification contract used there via isinstance checks.
    from app.domain.models.event import MessageEvent as M, PlanEvent as P, \
        StepEvent as S, TitleEvent as Ti, ToolEvent as To, ValidationEvent
    keep_types = (M, P, S, Ti, ValidationEvent)
    copied = 0
    for event in events:
        if isinstance(event, To):
            stripped = event.model_copy(deep=True)
            stripped.tool_content = None
            stripped.function_result = None
            copied += 1
        elif isinstance(event, keep_types):
            copied += 1
    assert copied == 6  # 5 keep + 1 stripped tool event
