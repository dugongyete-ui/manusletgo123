"""Unit tests for the adaptive-loop instrumentation ported from browser-use.

Covers (see agents/loop_detector.py + BaseAgent.execute()):
  1. ActionLoopDetector — hash stability, exempt tools, escalation 3/6/9,
     result-stagnation, window trimming.
  2. execute() injections — repetition nudges, GOAL CHECK re-anchoring,
     failure-budget annotations, BUDGET WARNING at >=75%, LAST ROUNDS
     wrap-up, user-visible loop event.
"""

import pytest
from unittest.mock import AsyncMock

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from app.domain.models.tool_result import ToolResult
from app.domain.models.event import MessageEvent, ErrorEvent
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.services.agents.loop_detector import (
    ActionLoopDetector,
    compute_action_hash,
    leading_binary,
)

# ───────────────────────── 1. ActionLoopDetector ─────────────────────────


def test_action_hash_is_stable_and_brief_insensitive():
    h1 = compute_action_hash("browser_click", {"index": 5})
    h2 = compute_action_hash("browser_click", {"index": 5, "brief": "klik tombol"})
    h3 = compute_action_hash("browser_click", {"index": 5})
    assert h1 == h2 == h3
    assert h1 != compute_action_hash("browser_click", {"index": 6})
    # whitespace noise collapsed
    assert compute_action_hash("x", {"t": "a  b"}) == compute_action_hash("x", {"t": "a b"})


def test_exempt_tools_are_not_tracked():
    d = ActionLoopDetector()
    for _ in range(10):
        d.record_action("browser_view", {})
    assert d.max_repetition_count == 0
    assert d.get_nudge_message() is None


def test_nudge_escalation_3_6_9():
    d = ActionLoopDetector()
    for _ in range(3):
        d.record_action("browser_click", {"index": 3})
    msg = d.get_nudge_message()
    assert msg and "similar action" in msg

    for _ in range(3):  # total 6
        d.record_action("browser_click", {"index": 3})
    assert "LOOP WARNING" in d.get_nudge_message()

    for _ in range(3):  # total 9
        d.record_action("browser_click", {"index": 3})
    assert "LOOP ALERT" in d.get_nudge_message()


def test_nudge_silent_below_threshold():
    d = ActionLoopDetector()
    d.record_action("browser_click", {"index": 3})
    d.record_action("browser_click", {"index": 3})
    assert d.get_nudge_message() is None


def test_result_stagnation_detection():
    d = ActionLoopDetector()
    for i in range(3):
        d.record_action("browser_click", {"index": i})
        d.record_result("browser_click", "identical-result")
    msg = d.get_nudge_message()
    assert msg and "no effect" in msg


def test_changing_results_are_not_stagnation():
    d = ActionLoopDetector()
    for i in range(6):
        d.record_action("browser_click", {"index": i})
        d.record_result("browser_click", f"result-{i}")
    assert d.get_nudge_message() is None


def test_window_trims_to_size():
    d = ActionLoopDetector(window_size=5)
    for i in range(20):
        d.record_action("shell_exec", {"cmd": f"x{i % 3}"})
    assert len(d.recent_action_hashes) == 5
    assert len(d.recent_command_keys) == 5


# ─────────── 1b. coarse command-family focus (prisma spiral) ───────────


def test_leading_binary_collapses_wrapper_and_path_variants():
    """Session 1303b902a2d54516: 30+ syntactic variants of the same
    failing prisma command, each string distinct — the leading binary
    must collapse them to one family."""
    assert leading_binary("npx prisma migrate dev --name init") == "prisma"
    assert leading_binary(
        "cd /home/x/project && npx prisma migrate dev --name init 2>&1"
    ) == "prisma"
    assert leading_binary("./node_modules/.bin/prisma migrate dev") == "prisma"
    assert leading_binary("node_modules/.bin/prisma migrate dev") == "prisma"
    assert leading_binary("npx prisma migration dev --name init 2>&1") == "prisma"
    assert leading_binary("sudo systemctl restart nginx") == "systemctl"
    assert leading_binary("ls -la prisma/") == "ls"
    assert leading_binary("") == ""


def test_command_variant_spiral_triggers_focus_warning():
    """Every command string is DIFFERENT (so exact-hash detection stays
    quiet) yet all revolve around the same failing binary — the coarse
    key must still escalate: WARNING at 6, ALERT at 10."""
    d = ActionLoopDetector()
    variants = [
        "npx prisma migrate dev --name init",
        "npx prisma migration dev --name init",
        "./node_modules/.bin/prisma migrate dev",
        "cd /x/orca-ai && npx prisma migrate dev --name init 2>&1",
        "npx prisma --help",
        "npx prisma migration new init",
    ]
    for v in variants:
        d.record_action("shell_exec", {"command": v})
    # exact hashes are all distinct → no LOOP nudge from the old detector
    assert d.max_repetition_count == 1
    msg = d.get_nudge_message()
    assert msg and "COMMAND-FOCUS WARNING" in msg
    assert "prisma" in msg

    for i, v in enumerate(
        ["npx prisma migrate dev --create-only", "npx prisma generate",
         "npx prisma -v", "npx prisma --version"]
    ):
        d.record_action("shell_exec", {"command": v})
    msg = d.get_nudge_message()
    assert "COMMAND-FOCUS ALERT" in msg
    assert "stop retrying" in msg


def test_distinct_binaries_do_not_trigger_focus_nudge():
    """A healthy build round runs many DIFFERENT commands (npm, ls, cat,
    node, curl) — no command-family nudge may fire."""
    d = ActionLoopDetector()
    for cmd in (
        "npm install react",
        "ls -la",
        "cat package.json",
        "node -v",
        "curl localhost:3000",
        "mkdir -p src",
    ):
        d.record_action("shell_exec", {"command": cmd})
    assert d.max_command_focus == 1
    assert d.get_nudge_message() is None


def test_non_shell_tools_do_not_record_command_keys():
    d = ActionLoopDetector()
    for i in range(12):
        d.record_action("browser_click", {"index": i})
    assert d.recent_command_keys == []
    assert d.max_command_focus == 0


def test_exempt_tools_never_hash_or_key():
    d = ActionLoopDetector()
    for _ in range(12):
        d.record_action("shell_exec", {"command": "ls"})
        d.record_action("message_notify_user", {"text": "update"})
    assert d.max_command_focus == 12  # shell side still tracked
    # notify side invisible to BOTH detectors
    assert "message_notify_user" not in str(d.recent_action_hashes)


# ───────────────────────── 2. execute() injections ───────────────────────


class _FakeToolkit:
    name = "fake"


class _FakeTool:
    """Fails or succeeds on demand so we can drive failure streaks."""

    def __init__(self, name: str, success: bool):
        self.name = name
        self.success = success
        self.toolkit = _FakeToolkit()

    async def ainvoke(self, tool_call):
        artifact = ToolResult(success=self.success, message="boom" if not self.success else "ok")
        content = artifact.model_dump_json()
        return ToolMessage(tool_call_id=tool_call["id"], name=self.name, content=content, artifact=artifact)


def _make_agent(max_iterations: int = 10) -> ExecutionAgent:
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
    return agent


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


@pytest.mark.asyncio
async def test_goal_check_injected_periodically():
    """Goal-directedness: while a step runs, the model is re-anchored on the
    step's goal every 3 rounds (from round 3) so the loop stays aimed at
    the objective instead of drifting in circles."""
    agent = _make_agent(max_iterations=10)
    agent._current_step_description = "Deploy the API service to production"
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 6:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=True)

    [e async for e in agent.execute("do the thing")]

    # Rounds 1-2: no GOAL CHECK yet (below the round-3 floor).
    for early in (captured[0], captured[1]):
        early_text = " ".join(str(getattr(m, "content", "")) for m in early)
        assert "GOAL CHECK" not in early_text

    # Round 3: the step goal is re-injected.
    round3 = " ".join(str(getattr(m, "content", "")) for m in captured[2])
    assert "GOAL CHECK" in round3
    assert "Deploy the API service" in round3
    assert "confirm it DIRECTLY advances this goal" in round3

    # Round 6: injected again (every 3 rounds), not on rounds 4-5.
    round6 = " ".join(str(getattr(m, "content", "")) for m in captured[5])
    assert "GOAL CHECK" in round6


@pytest.mark.asyncio
async def test_goal_check_absent_without_step_goal():
    """Outside execute_step (no current step description) the base agent's
    _goal_reminder returns None — no GOAL CHECK advisory is ever injected."""
    agent = _make_agent(max_iterations=10)
    # NOTE: no _current_step_description set — same state as a planner or
    # summarize round.
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 6:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=True)

    [e async for e in agent.execute("do the thing")]

    all_text = " ".join(
        str(getattr(m, "content", "")) for batch in captured for m in batch
    )
    assert "GOAL CHECK" not in all_text


@pytest.mark.asyncio
async def test_repetition_nudge_and_failure_annotation_injected():
    """Model retries the same failing click forever → the conversation must
    receive the loop nudge + failure-budget annotation; the user must see the
    self-correction progress line once repetition hits 6."""
    agent = _make_agent(max_iterations=10)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        # Rounds 0..8 keep retrying; round 9 wraps up.
        if len(captured) < 9:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=False)

    events = [e async for e in agent.execute("do the thing")]

    # Failure annotation appears from the 2nd failed round onwards.
    annotated = [m for m in captured[1] if isinstance(m, ToolMessage) and "SYSTEM NOTE: this action failed" in str(m.content)]
    assert annotated, "failure-budget annotation missing on repeated failures"

    # Repetition nudge: 5 identical calls by round 4 → NOTE in round-4 ask.
    round4 = " ".join(str(getattr(m, "content", "")) for m in captured[4])
    assert "similar action" in round4

    # Escalation: 7 identical calls by round 7 → LOOP WARNING (fires at 6)
    # + user-visible event.
    round7 = " ".join(str(getattr(m, "content", "")) for m in captured[7])
    assert "LOOP WARNING" in round7
    assert any(
        isinstance(e, MessageEvent) and e.is_progress and "repeated-action loop" in e.message
        for e in events
    )

    # Task finished with the final JSON (not the hard iteration error).
    assert not any(isinstance(e, ErrorEvent) and "Maximum iteration" in e.error for e in events)


@pytest.mark.asyncio
async def test_budget_warning_and_last_rounds_injected():
    """4-round budget → BUDGET WARNING + LAST ROUNDS appear at rounds 3-4."""
    agent = _make_agent(max_iterations=4)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 3:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=True)

    events = [e async for e in agent.execute("do the thing")]

    # Round 3 = 3/4 = 75% budget.
    round3 = " ".join(str(getattr(m, "content", "")) for m in captured[2])
    assert "BUDGET WARNING" in round3
    assert "LAST ROUNDS" in round3

    # No loop nudge for healthy distinct actions (index changes each round
    # via call id; args identical though — that's fine, budget test only).
    assert not any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_success_resets_failure_streak():
    """Alternating success/failure rounds never accumulate a streak →
    no STRATEGY CHANGE advisory ever appears."""
    agent = _make_agent(max_iterations=10)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 6:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)

    calls = {"n": 0}

    class _Alternating:
        name = "browser_click"
        toolkit = _FakeToolkit()

        async def ainvoke(self, tool_call):
            calls["n"] += 1
            ok = calls["n"] % 2 == 0
            artifact = ToolResult(success=ok, message="ok" if ok else "boom")
            return ToolMessage(tool_call_id=tool_call["id"], name=self.name,
                               content=artifact.model_dump_json(), artifact=artifact)

    agent.get_tool = lambda name: _Alternating()

    [e async for e in agent.execute("do the thing")]

    all_messages = [str(getattr(m, "content", "")) for batch in captured for m in batch]
    assert not any("STRATEGY CHANGE REQUIRED" in m for m in all_messages)
    # With perfect alternation the streak never accumulates (each success
    # resets it), so NO failure annotation is ever attached either — the
    # annotation only fires when a call fails while already inside a streak.
    assert not any("SYSTEM NOTE: this action failed" in m for m in all_messages)


@pytest.mark.asyncio
async def test_strategy_change_after_consecutive_failures():
    """3 consecutive all-failed rounds (default budget) → STRATEGY CHANGE
    advisory injected so the model is told to switch approach."""
    agent = _make_agent(max_iterations=10)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 5:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=False)

    [e async for e in agent.execute("do the thing")]

    # Round 3's ask happens after 3 failed rounds (0,1,2) → advisory present.
    round3 = " ".join(str(getattr(m, "content", "")) for m in captured[3])
    assert "STRATEGY CHANGE REQUIRED" in round3


@pytest.mark.asyncio
async def test_advisory_arrives_as_human_message_after_tool_messages():
    """Message-ordering contract: nudges are appended AFTER the round's
    ToolMessages (OpenAI/Anthropic-compatible ordering)."""
    agent = _make_agent(max_iterations=10)
    agent.ask = AsyncMock(return_value=_click_msg(0))

    captured: list = []

    async def _fake_ask(messages, format=None):
        captured.append(list(messages))
        if len(captured) < 6:
            return _click_msg(len(captured))
        return AIMessage(content='{"success": true, "result": "done"}')

    agent.ask_with_messages = AsyncMock(side_effect=_fake_ask)
    agent.get_tool = lambda name: _FakeTool("browser_click", success=False)

    [e async for e in agent.execute("do the thing")]

    # Round 4 (5 identical failures) must end with the HumanMessage nudge.
    last_batch = captured[4]
    assert isinstance(last_batch[-1], HumanMessage)
    assert any(isinstance(m, ToolMessage) for m in last_batch[:-1])
