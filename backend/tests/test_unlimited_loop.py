"""Unlimited iteration contract (Task 60).

The agent loop must run UNTIL THE WORK IS DONE, not until a counter runs
out — mirroring the reference agent's behaviour: a fullstack setup from
zero to a running server is never truncated by an arbitrary limit.

Locks in:
  * max_iterations=0 (default) → UNLIMITED tool rounds; the loop only
    ends when the model stops calling tools. Regression guard: the old
    `range(self.max_iterations)` silently ran ZERO rounds for 0.
  * No BUDGET WARNING / LAST ROUNDS advisories on the unlimited path
    (there is no budget to warn about).
  * Finite values keep the classic cap + error event (cost caps, tests).
  * Settings defaults: max_steps=0 (unlimited plan steps),
    nested_max_iterations=0 (sub-agents finish their subtask).
  * Effort scaling can never turn unlimited into limited.
"""

import inspect
from unittest.mock import AsyncMock

import pytest
from langchain.messages import AIMessage

from app.domain.models.tool_result import ToolResult
from app.domain.models.event import ErrorEvent, MessageEvent
from app.core.config import get_settings
from app.domain.services.flows.plan_act import PlanActFlow


class _FakeToolkit:
    name = "fake"


class _FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.toolkit = _FakeToolkit()

    async def ainvoke(self, tool_call):
        artifact = ToolResult(success=True, message="ok")
        return ToolMessage(
            tool_call_id=tool_call["id"],
            name=self.name,
            content=artifact.model_dump_json(),
            artifact=artifact,
        )


from langchain.messages import ToolMessage  # noqa: E402


def _click_msg(round_id: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "browser_click",
            "args": {"index": 3},
            "id": f"call-{round_id}",
            "type": "tool_call",
        }],
    )


def _make_agent(max_iterations: int) -> "ExecutionAgent":
    from app.domain.services.agents.execution import ExecutionAgent

    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._user_request_words = None
    agent._silent_activities = []
    agent._silent_tool_count = 0
    agent._narration_assist_count = 0
    agent._narration_lang = "en"
    agent.toolkits = []
    agent.max_iterations = max_iterations
    # Mid-step compaction fires every N rounds; with 40-round unlimited
    # runs the real compact_memory would need repository-backed memory.
    agent.compact_memory = AsyncMock()
    return agent


@pytest.mark.asyncio
async def test_unlimited_loop_runs_until_model_stops():
    """max_iterations=0 must mean UNLIMITED rounds — 40 tool rounds happen,
    the model then stops, and no 'Maximum iteration' error is ever raised."""
    agent = _make_agent(max_iterations=0)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    rounds = {"n": 0}

    async def _fake_ask(messages, format=None):
        rounds["n"] += 1
        if rounds["n"] <= 40:
            return _click_msg(rounds["n"])
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click")

    events = [e async for e in agent.execute("build the thing")]

    assert rounds["n"] == 41  # 40 tool rounds + 1 final answer
    assert not any(
        isinstance(e, ErrorEvent) and "Maximum iteration" in e.error
        for e in events
    )
    finals = [
        e for e in events
        if isinstance(e, MessageEvent) and not e.is_progress
    ]
    assert finals, "final result message must still be emitted"


@pytest.mark.asyncio
async def test_unlimited_loop_has_no_budget_advisories():
    """On the unlimited path the model must NEVER receive BUDGET WARNING or
    LAST ROUNDS — those advisories exist only for explicitly finite caps."""
    agent = _make_agent(max_iterations=0)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 30:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click")

    [e async for e in agent.execute("do the thing")]

    all_text = " ".join(
        str(getattr(m, "content", "")) for batch in captured for m in batch
    )
    assert "BUDGET WARNING" not in all_text
    assert "LAST ROUNDS" not in all_text


@pytest.mark.asyncio
async def test_finite_loop_still_capped():
    """Explicit finite caps keep the classic behaviour: exhaustion raises
    the 'Maximum iteration count reached' error event."""
    agent = _make_agent(max_iterations=2)
    agent.ask = AsyncMock(return_value=_click_msg(0))
    agent.ask_with_messages = AsyncMock(return_value=_click_msg(1))
    agent.get_tool = lambda name: _FakeTool("browser_click")

    events = [e async for e in agent.execute("do the thing")]

    assert any(
        isinstance(e, ErrorEvent) and "Maximum iteration" in e.error
        for e in events
    )


def test_settings_defaults_unlimited():
    """Deployment defaults (updated 2026-09-19): MAX_STEPS=0 → UNLIMITED.
    The loop runs until the goal is genuinely complete — long-running tasks
    are never cut short by a counter. MAX_CONSECUTIVE_FAILURES stays the
    only health guard; sub-agent delegation stays unlimited."""
    settings = get_settings()
    assert settings.max_steps == 0
    assert settings.nested_max_iterations == 0
    # Health guard (failed STEPS, not iterations) stays generous but finite.
    assert settings.max_consecutive_failures == 10
    # The CODE default is unlimited so deployments share the same contract.
    import inspect
    from app.core.config import Settings
    src = inspect.getsource(Settings)
    assert "max_steps: int = 0" in src


def test_effort_scaling_never_limits_unlimited():
    """_effective_step_budget: high_effort doubles finite budgets but keeps
    0 (unlimited) unlimited — an infinite budget cannot be scaled down."""

    class _Flow(PlanActFlow):
        def __init__(self, task_mode):
            self.plan = type("P", (), {"task_mode": task_mode})()

    assert _Flow("high_effort")._effective_step_budget(0, 10) == (0, 20)
    assert _Flow("standard")._effective_step_budget(0, 10) == (0, 10)
    assert _Flow("high_effort")._effective_step_budget(50, 3) == (100, 6)


def test_flow_guards_skip_when_unlimited():
    """Both flow engines guard with `_eff_steps > 0 and ...` so an unlimited
    budget can never force-summarise healthy work mid-build."""
    import app.domain.services.flows.plan_act as plan_act_mod
    import app.domain.services.flows.plan_act_graph as graph_mod

    for module in (plan_act_mod, graph_mod):
        source = inspect.getsource(module)
        assert "_eff_steps > 0 and" in source, (
            f"{module.__name__} must skip the max_steps guard when "
            "the effective step budget is 0 (unlimited)"
        )


def test_graph_recursion_limit_unlimited_fallback():
    """With max_steps=0 the LangGraph recursion_limit must fall back to a
    huge cap (1,000,000) instead of collapsing to 20 node executions."""
    import app.domain.services.flows.plan_act_graph as graph_mod

    source = inspect.getsource(graph_mod)
    assert "else 1_000_000" in source


def test_delegate_nested_budget_from_settings():
    """task_delegate reads the sub-agent round budget from settings
    (nested_max_iterations), never from a hardcoded constant."""
    import app.domain.services.tools.delegate as delegate_mod

    source = inspect.getsource(delegate_mod)
    assert "get_settings().nested_max_iterations" in source
    assert "_NESTED_MAX_ITERATIONS" not in source
