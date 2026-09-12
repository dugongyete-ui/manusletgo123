"""Regression tests for the context-overflow defense (Task 25).

Bug (user report, 2026-08-30):
    Autonomous research task (web search → document → image search →
    download → search → download …) died with:
        Task error: Error code: 400 - {'error': {'code': '1261',
        'message': 'Prompt exceeds max length'}}
    The agent's accumulated conversation (search result lists, image
    search results, base64 image previews inside image_download results,
    browser DOM snapshots, file bodies) is re-sent to the provider on
    every round; nothing ever removed it, and the provider's rejection
    of the oversized prompt killed the whole task — usually at the FINAL
    SUMMARY, after all the work was already done.

Fix (four layers):
    L1  Tool results are capped as they enter the context
        (cap_tool_content + Tool.ainvoke); image_download no longer
        embeds a base64 data_url (~30-50K tokens per image).
    L2  Memory compaction covers the search/image tools and gained an
        AGGRESSIVE mode plus drop_older_rounds (protocol-safe surgery).
    L3  Proactive budget gate before every LLM call
        (_enforce_context_budget) — browser-use-style prevention.
    L4  In-flight emergency recovery: when the provider STILL returns a
        1261-family error, compact → re-snapshot → retry (max 2), in
        both ask_with_messages and astream_chunks_with_fallback.
"""

import httpx
import openai
import pytest
from langchain.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.domain.models.memory import (
    AGGRESSIVE_TOOL_CHAR_CAP,
    Memory,
    compact_messages,
    drop_older_rounds,
)
from app.domain.models.tool_result import ToolResult
from app.domain.services.agents.base import BaseAgent
from app.domain.services.tools.base import BaseToolkit, cap_tool_content


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _overflow_error() -> openai.BadRequestError:
    """The exact provider failure from the user's report."""
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"code": "1261", "message": "Prompt exceeds max length"}},
    )
    return openai.BadRequestError(
        "Error code: 400 - {'error': {'code': '1261', "
        "'message': 'Prompt exceeds max length'}}",
        response=response,
        body=None,
    )


def _ai_tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _round(i: int, tool: str = "file_write", size: int = 5_000) -> list:
    """One conversation round: Human → AI(tool_call) → Tool(result)."""
    return [
        HumanMessage(content=f"round {i}: do something"),
        _ai_tool_call(tool, {"file": f"f{i}.txt", "content": "x" * size}, f"c{i}"),
        ToolMessage(name=tool, content="y" * size, tool_call_id=f"c{i}"),
    ]


class _FakeRepo:
    def __init__(self):
        self.saved = []

    async def get_memory(self, agent_id, name):
        return Memory()

    async def save_memory(self, agent_id, name, memory):
        self.saved.append(memory)


class _FakeChain:
    def __init__(self, model):
        self._model = model

    async def ainvoke(self, context, config=None, **kwargs):
        return await self._model.ainvoke(context)


class _FakeModel:
    """Chain-compatible fake model.

    bind()/bind_tools() return self; `model | parser` yields a _FakeChain
    so ask_with_messages' chain construction works without langchain
    runnables. `outcomes` is consumed left→right: exceptions are raised,
    strings become AIMessage contents. Context sizes are recorded AT CALL
    TIME (the message objects are shared with memory and compaction
    mutates them in place — a stored list reference would shrink too).
    """

    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.astream_outcomes = []
        self.seen_contexts = []
        self.seen_sizes = []

    def bind(self, **kwargs):
        return self

    def bind_tools(self, tools):
        return self

    def __or__(self, other):
        return _FakeChain(self)

    async def ainvoke(self, context):
        # Map-reduce compaction summaries (base._summarize_digest) are
        # internal housekeeping calls, not task asks — answer them with a
        # canned summary WITHOUT consuming a scripted outcome, so the call
        # counts below still assert exactly the ask/recovery sequence.
        first = context[0] if context else None
        if (
            getattr(first, "type", None) == "system"
            and "precise summariser" in str(getattr(first, "content", ""))
        ):
            return AIMessage(content="summary of earlier work")
        self.seen_contexts.append(list(context))
        self.seen_sizes.append(BaseAgent._estimate_context_chars(context))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return AIMessage(content=outcome)

    async def astream(self, messages):
        outcome = (
            self.astream_outcomes.pop(0) if self.astream_outcomes
            else AIMessage(content="ok")
        )
        if isinstance(outcome, Exception):
            raise outcome
        yield AIMessage(content="chunk-text")


class _StubParser:
    """Stands in for RobustJsonParser.from_llm — the real one builds a
    langchain chain (prompt | llm | ...) which requires a real model."""

    @classmethod
    def from_llm(cls, llm):
        return object()


class _TestAgent(BaseAgent):
    """BaseAgent without the real __init__ (no provider config needed)."""

    name = "tester"

    def __init__(self, model, memory=None, repo=None):
        self._agent_id = "agent-1"
        self._repository = repo or _FakeRepo()
        self._model = model
        self._primary_model = model
        self._using_fallback = False
        self._primary_auth_failed = False
        self.memory = memory or Memory()
        self.max_retries = 3
        self.retry_interval = 0.0
        self.toolkits = []
        self.tool_choice = None
        self.rate_limit_notice = None
        self._last_rate_limit_notice_ts = 0.0
        self._json_output_parser = None
        self.system_prompt = "system"
        self.format = None


# ─────────────────────────────────────────────────────────────────────────────
# L1 — entry cap (Tool Result Processor)
# ─────────────────────────────────────────────────────────────────────────────

def test_cap_tool_content_passthrough_and_truncation():
    assert cap_tool_content("short", 1000) == "short"
    big = "a" * 10_000
    capped = cap_tool_content(big, 1_000)
    assert len(capped) < 1_400  # head + tail + marker
    assert "TRUNCATED" in capped
    # head+tail preserved
    assert capped.startswith("a" * 50)
    assert capped.endswith("a" * 50)


def test_cap_tool_content_zero_limit_disables():
    assert cap_tool_content("x" * 100, 0) == "x" * 100


@pytest.mark.asyncio
async def test_tool_ainvoke_caps_llm_content_but_keeps_artifact():
    from langchain.tools import tool as lc_tool

    class _BigToolkit(BaseToolkit):
        name: str = "big"

        @lc_tool(parse_docstring=True)
        async def big_tool(self, payload: str) -> ToolResult:
            """Returns a huge result for testing.

            Args:
                payload: input payload
            """
            return ToolResult(success=True, data=payload)

    tk = _BigToolkit()
    t = tk.get_tool("big_tool")
    huge = "z" * 200_000
    msg = await t.ainvoke({"id": "c1", "args": {"payload": huge}})
    # LLM-facing content capped…
    assert len(msg.content) < 60_000
    assert "TRUNCATED" in msg.content
    # …but the UI-facing artifact keeps the full payload.
    assert msg.artifact.data == huge


@pytest.mark.asyncio
async def test_image_download_result_has_no_base64_data_url(monkeypatch):
    """The single biggest 1261 driver: ≤100KB images were embedded as
    ~130K-char base64 previews straight into the LLM context."""
    from app.domain.services.tools.image import ImageToolkit

    class _FakeResp:
        status_code = 200
        content = b"i" * 150_000

        def raise_for_status(self):
            pass

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _FakeResp()

    monkeypatch.setattr(
        "app.domain.services.tools.image.httpx.AsyncClient", _FakeAsyncClient
    )

    class _FakeSandbox:
        async def file_upload(self, data, path):
            return ToolResult(success=True)

    tk = ImageToolkit(_FakeSandbox())
    t = tk.get_tool("image_download")
    msg = await t.ainvoke({
        "id": "c1",
        "args": {"url": "https://x/img.png", "file_path": "img.png"},
    })
    assert msg.artifact.success is True
    data = msg.artifact.data
    assert "data_url" not in data
    assert data["file_path"] == "img.png"
    assert data["size"] == 150_000
    # The serialized content that enters the LLM context must be tiny.
    assert len(msg.content) < 500


# ─────────────────────────────────────────────────────────────────────────────
# L2 — compaction coverage + aggressive mode + surgery
# ─────────────────────────────────────────────────────────────────────────────

def test_compact_now_covers_search_and_image_tools():
    mem = Memory()
    mem.add_message(HumanMessage(content="find logos"))

    def _search_round(tool: str, query: str, call_id: str, size: int):
        return [
            _ai_tool_call(tool, {"query": query}, call_id),
            ToolMessage(name=tool, content="r" * size, tool_call_id=call_id),
        ]

    # Two calls per tool: the older one must be stubbed, the newest kept.
    mem.add_messages(_search_round("image_search_web", "persib logo", "s1", 8_000))
    mem.add_messages(_search_round("image_search_web", "persib jersey", "s2", 6_000))
    mem.add_messages(_search_round("image_download", "https://x/1.png", "d1", 8_000))
    mem.add_messages(_search_round("image_download", "https://x/2.png", "d2", 6_000))
    mem.add_messages(_search_round("info_search_web", "persib history", "w1", 8_000))
    mem.add_messages(_search_round("info_search_web", "persib 2026", "w2", 6_000))

    mem.compact()

    tools = {m.tool_call_id: m for m in mem.messages if m.type == "tool"}
    # Old calls stubbed…
    assert "(removed)" in tools["s1"].content
    assert "(removed)" in tools["d1"].content
    assert "(removed)" in tools["w1"].content
    # …newest call per tool kept intact.
    assert len(tools["s2"].content) == 6_000
    assert len(tools["d2"].content) == 6_000
    assert len(tools["w2"].content) == 6_000


def test_aggressive_compact_stubs_even_latest_old_tool_results():
    mem = Memory()
    # 20 rounds → the "latest" tool result is far outside the tail window.
    for i in range(20):
        mem.add_messages(_round(i, tool="browser_view", size=4_000))
    mem.compact(aggressive=True)
    tool_msgs = [m for m in mem.messages if m.type == "tool"]
    assert tool_msgs, "tool messages should exist"
    # Everything outside the tail window is stubbed…
    stubbed = [m for m in tool_msgs if "(removed)" in str(m.content)]
    assert len(stubbed) >= len(tool_msgs) - 12


def test_aggressive_compact_truncates_tail_tool_results():
    mem = Memory()
    mem.add_messages(_round(0, tool="browser_view", size=100_000))
    mem.compact(aggressive=True)
    tool_msgs = [m for m in mem.messages if m.type == "tool"]
    # Even the newest (kept) result is hard-truncated in aggressive mode.
    assert all(
        len(str(m.content)) <= AGGRESSIVE_TOOL_CHAR_CAP + 400
        for m in tool_msgs
    )


def test_drop_older_rounds_keeps_protocol_pairing():
    mem = Memory()
    mem.add_message(SystemMessage(content="system prompt"))
    mem.add_message(HumanMessage(content="original user task"))
    for i in range(20):
        mem.add_messages(_round(i))
    before = len(mem.messages)
    mem.drop_older_rounds(keep_last_messages=6)
    msgs = mem.messages

    assert len(msgs) < before
    # System prompt survives at the front.
    assert msgs[0].type == "system"
    # The original task survives as a stub + a system note documents the cut.
    assert any("original user task" in str(m.content) for m in msgs[:4])
    assert any("SYSTEM NOTE" in str(m.content) for m in msgs[:4])
    # The trailing window starts at a HumanMessage boundary.
    note_idx = next(i for i, m in enumerate(msgs) if "SYSTEM NOTE" in str(m.content))
    assert msgs[note_idx + 1].type == "human"
    # Protocol safety: every ToolMessage in the kept window has its
    # matching AIMessage tool_call ALSO in the kept window.
    kept_call_ids = {
        tc["id"]
        for m in msgs
        if m.type == "ai"
        for tc in (m.tool_calls or [])
    }
    for m in msgs:
        if m.type == "tool":
            assert m.tool_call_id in kept_call_ids, (
                "orphan ToolMessage after surgery — provider would 400"
            )


def test_drop_older_rounds_noop_for_short_lists():
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="hi"))
    mem.drop_older_rounds()
    assert len(mem.messages) == 2


def test_drop_older_rounds_refuses_unsafe_cut():
    """If no HumanMessage boundary exists in the drop zone, refuse."""
    msgs = [SystemMessage(content="s"), AIMessage(content="a")] + [
        ToolMessage(name="t", content="x", tool_call_id=f"c{i}") for i in range(30)
    ]
    out = drop_older_rounds(msgs, keep_last_messages=5)
    assert out is msgs
    assert len(msgs) == 32  # unchanged


def test_compact_messages_strips_base64_from_human_messages():
    mem = Memory()
    mem.add_message(HumanMessage(content=[
        {"type": "text", "text": "what is in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 100_000}},
    ]))
    compact_messages(mem.messages)
    assert "base64" not in str(mem.messages[0].content)
    assert "what is in this image?" in str(mem.messages[0].content)


# ─────────────────────────────────────────────────────────────────────────────
# L4 — overflow detection
# ─────────────────────────────────────────────────────────────────────────────

def test_is_context_overflow_error_matrix():
    detect = BaseAgent._is_context_overflow_error
    # The user's exact failure.
    assert detect(_overflow_error()) is True
    # Common phrasings across providers.
    assert detect(ValueError(
        "Error code: 400 - {'error': {'code': '1261', "
        "'message': 'Prompt exceeds max length'}}")) is True
    assert detect(RuntimeError(
        "This model's maximum context length is 8192 tokens")) is True
    assert detect(RuntimeError("prompt is too long")) is True
    assert detect(RuntimeError("too many input tokens")) is True
    # Negative: provider limit/quota errors must NOT trigger compaction.
    assert detect(RuntimeError("Error code: 429 - rate limit exceeded")) is False
    assert detect(RuntimeError("insufficient credits")) is False
    _req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    _resp = httpx.Response(401, request=_req, json={"error": {"message": "bad key"}})
    assert detect(openai.AuthenticationError(
        "invalid api key", response=_resp, body=None)) is False


def test_estimate_context_chars_counts_content_and_tool_args():
    msgs = [
        SystemMessage(content="s" * 100),
        _ai_tool_call("file_write", {"content": "x" * 500}, "c1"),
        ToolMessage(name="file_write", content="y" * 1_000, tool_call_id="c1"),
    ]
    total = BaseAgent._estimate_context_chars(msgs)
    assert total >= 1_600
    # Multimodal base64 parts count (they used to hide from estimates).
    vision = HumanMessage(content=[
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 50_000}},
    ])
    assert BaseAgent._estimate_context_chars([vision]) > 50_000


# ─────────────────────────────────────────────────────────────────────────────
# L3 — proactive budget gate
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enforce_context_budget_ladder():
    """Normal compaction alone leaves the newest browser_view result
    intact (60K) — the aggressive rung must hard-truncate it so the
    estimate drops under the budget."""
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="browse the site"))
    for i in range(3):
        mem.add_messages(_round(i, tool="browser_view", size=3_000))
    # Last round carries a giant DOM snapshot as its tool result.
    mem.add_messages(_round(3, tool="browser_view", size=60_000))

    agent = _TestAgent(_FakeModel(), memory=mem)
    agent._context_soft_limit = lambda: 20_000  # tiny budget for the test

    before = BaseAgent._estimate_context_chars(mem.get_messages())
    await agent._enforce_context_budget()
    after = BaseAgent._estimate_context_chars(mem.get_messages())

    assert after <= 20_000
    assert after < before / 2
    # The 60K DOM snapshot got hard-truncated (aggressive rung ran).
    biggest = max(
        len(str(m.content)) for m in mem.messages if m.type == "tool"
    )
    assert biggest <= AGGRESSIVE_TOOL_CHAR_CAP + 400
    # Compacted memory was persisted.
    assert agent._repository.saved


@pytest.mark.asyncio
async def test_enforce_context_budget_drops_rounds_when_still_over():
    """When even aggressive compaction stays over budget, whole old
    rounds are dropped (protocol-safe surgery) — documented by the
    SYSTEM NOTE marker."""
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="task"))
    for i in range(20):
        mem.add_message(HumanMessage(content=f"research dump {i}: " + "d" * 40_000))

    agent = _TestAgent(_FakeModel(), memory=mem)
    agent._context_soft_limit = lambda: 20_000

    before = BaseAgent._estimate_context_chars(mem.get_messages())
    await agent._enforce_context_budget()
    after = BaseAgent._estimate_context_chars(mem.get_messages())

    assert after < before
    assert any("SYSTEM NOTE" in str(m.content) for m in mem.messages)


@pytest.mark.asyncio
async def test_enforce_context_budget_noop_below_limit():
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="hi"))
    agent = _TestAgent(_FakeModel(), memory=mem)
    await agent._enforce_context_budget()  # default 280K limit — far away
    assert not agent._repository.saved


# ─────────────────────────────────────────────────────────────────────────────
# L4 — in-flight 1261 recovery (ask path)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_with_messages_recovers_from_1261(monkeypatch):
    """First call → 1261; emergency compaction; retry succeeds."""
    monkeypatch.setattr(
        "app.domain.services.agents.base.RobustJsonParser", _StubParser
    )
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="task"))
    for i in range(6):
        mem.add_messages(_round(i, size=40_000))

    model = _FakeModel(outcomes=[_overflow_error(), "recovered answer"])
    agent = _TestAgent(model, memory=mem)
    # Disable the proactive gate for this test — here we exercise the
    # IN-FLIGHT recovery: the provider must reject the first (huge)
    # context, the agent must compact, and the retry must succeed.
    agent._context_soft_limit = lambda: 10_000_000

    result = await agent.ask_with_messages([HumanMessage(content="next step")])

    assert result.content == "recovered answer"
    assert len(model.seen_contexts) == 2
    # The retried context is materially smaller than the rejected one.
    size0, size1 = model.seen_sizes
    assert size1 < size0 / 2


@pytest.mark.asyncio
async def test_ask_with_messages_gives_up_after_two_recoveries(monkeypatch):
    monkeypatch.setattr(
        "app.domain.services.agents.base.RobustJsonParser", _StubParser
    )
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="task"))
    for i in range(6):
        mem.add_messages(_round(i, size=40_000))

    model = _FakeModel(outcomes=[
        _overflow_error(), _overflow_error(), _overflow_error(),
    ])
    agent = _TestAgent(model, memory=mem)

    with pytest.raises(openai.BadRequestError):
        await agent.ask_with_messages([HumanMessage(content="next step")])
    # provider called exactly 3 times (initial + 2 recovery retries)
    assert len(model.seen_contexts) == 3


@pytest.mark.asyncio
async def test_ask_with_messages_escalates_to_round_surgery(monkeypatch):
    """Recovery 2 must ALSO drop whole old rounds — the SYSTEM NOTE
    marker proves the surgery ran, and the task still completes."""
    monkeypatch.setattr(
        "app.domain.services.agents.base.RobustJsonParser", _StubParser
    )
    mem = Memory()
    mem.add_message(SystemMessage(content="s"))
    mem.add_message(HumanMessage(content="task"))
    for i in range(12):
        mem.add_messages(_round(i, size=30_000))

    model = _FakeModel(outcomes=[_overflow_error(), _overflow_error(), "ok"])
    agent = _TestAgent(model, memory=mem)
    before_msgs = len(mem.messages)

    result = await agent.ask_with_messages([HumanMessage(content="next step")])

    assert result.content == "ok"
    assert any("SYSTEM NOTE" in str(m.content) for m in mem.messages)
    assert len(mem.messages) < before_msgs


@pytest.mark.asyncio
async def test_astream_recovers_from_1261():
    """The final summary path (astream) — the exact place the user's task
    died. Compaction + round-dropping must let it retry successfully."""
    messages = [SystemMessage(content="s"), HumanMessage(content="task")]
    for i in range(12):
        messages.extend(_round(i, size=30_000))
    before = len(messages)

    model = _FakeModel()
    model.astream_outcomes = [_overflow_error(), AIMessage(content="ok")]
    agent = _TestAgent(model)

    chunks = []
    async for text in agent.astream_chunks_with_fallback(messages):
        chunks.append(text)

    assert chunks == ["chunk-text"]
    assert len(messages) < before  # old rounds dropped
    assert messages[0].type == "system"


@pytest.mark.asyncio
async def test_astream_gives_up_after_two_recoveries():
    messages = [SystemMessage(content="s"), HumanMessage(content="task")]
    for i in range(12):
        messages.extend(_round(i, size=30_000))

    model = _FakeModel()
    model.astream_outcomes = [
        _overflow_error(), _overflow_error(), _overflow_error(),
    ]
    agent = _TestAgent(model)

    with pytest.raises(openai.BadRequestError):
        async for _ in agent.astream_chunks_with_fallback(messages):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Task-runner friendly message
# ─────────────────────────────────────────────────────────────────────────────

def test_friendly_task_error_maps_1261():
    from app.domain.services.agent_task_runner import _friendly_task_error

    text = _friendly_task_error(_overflow_error())
    assert "1261" in text
    assert "sesi baru" in text
    # Non-overflow errors keep the generic prefix.
    assert _friendly_task_error(ValueError("boom")).startswith("Task error:")
