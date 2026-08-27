"""Unit tests for the multi-round ghost-success fix in ExecutionAgent.

Session c397e25f ground truth: steps "Install ffmpeg" and "Buat script" were
marked completed+success with ZERO tool calls (fabricated results) — the UI
showed checkmarks for work that never happened, and every real tool landed in
a later step's correction round.

The fix: _handle_execution_events WITHHOLDS StepEvent(COMPLETED) for rounds
that end in a fabricated completion ("ghost") or plain text ("plain"), and
execute_step reruns them with an escalating mandatory tool-usage correction.
A round that still ghosts after all corrections marks the step FAILED — an
honest failure chip beats a false checkmark.
"""

import json

import pytest

from app.domain.models.event import (
    MessageEvent,
    StepEvent,
    StepStatus,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import Plan, Step
from app.domain.services.agents.execution import ExecutionAgent


def make_executor() -> ExecutionAgent:
    """ExecutionAgent skeleton without touching settings/model providers."""
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._round_needs_correction = None
    agent._narration_lang = "id"
    agent._last_narrated_function = None
    agent._last_model_narration_ts = 0.0
    agent._step_narrated_functions = set()
    agent._narration_variants_used = {}
    return agent


def shell_tool_events(call_id="t1") -> list:
    """A real (non-message) tool call + completion pair."""
    return [
        ToolEvent(
            status=ToolStatus.CALLING,
            tool_call_id=call_id,
            tool_name="shell",
            function_name="shell_exec",
            function_args={"command": "echo hi"},
        ),
        ToolEvent(
            status=ToolStatus.CALLED,
            tool_call_id=call_id,
            tool_name="shell",
            function_name="shell_exec",
            function_args={"command": "echo hi"},
            function_result="hi",
        ),
    ]


def final_message(payload) -> MessageEvent:
    """The executor's final step-result message (JSON payload as string)."""
    return MessageEvent(
        role="assistant",
        message=payload if isinstance(payload, str) else json.dumps(payload),
    )


def ghost_json(result="fabriki dari konteks"):
    return {"success": True, "result": result, "error": None, "attachments": []}


def ok_json(result="real work done"):
    return {"success": True, "result": result, "error": None, "attachments": []}


def wire_parse_json(agent, parsed):
    """Replace _parse_json with a canned result (dict or None)."""
    async def _fake(text):
        return parsed
    agent._parse_json = _fake


# ── _handle_execution_events: the ghost gate ────────────────────────────────

@pytest.mark.asyncio
async def test_ghost_round_withholds_completed_event():
    """success=True JSON with zero real tools must NOT emit StepEvent."""
    agent = make_executor()
    step = Step(id="1", description="Install ffmpeg")
    agent.execute = _Stream([final_message(ghost_json())]).execute
    wire_parse_json(agent, ghost_json())

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    assert events == []                          # nothing earned a checkmark
    assert agent._round_needs_correction == "ghost"


@pytest.mark.asyncio
async def test_legit_round_with_tools_emits_completed_event():
    agent = make_executor()
    step = Step(id="1", description="Install ffmpeg")
    agent.execute = _Stream(shell_tool_events() + [final_message(ok_json())]).execute
    wire_parse_json(agent, ok_json())

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    completed = [e for e in events if isinstance(e, StepEvent)]
    assert len(completed) == 1
    assert completed[0].status == StepStatus.COMPLETED
    assert step.success is True
    assert agent._round_needs_correction is None


@pytest.mark.asyncio
async def test_honest_failure_json_emits_completed_event():
    """success=False is an honest failure — the completed event flows (failed
    chip), no correction round is scheduled."""
    agent = make_executor()
    step = Step(id="1", description="Uji script")
    agent.execute = _Stream(shell_tool_events() + [final_message({"success": False, "result": None, "error": "command failed"})]).execute
    wire_parse_json(agent, {"success": False, "result": None, "error": "command failed"})

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    completed = [e for e in events if isinstance(e, StepEvent)]
    assert len(completed) == 1
    assert step.success is False
    assert agent._round_needs_correction is None


@pytest.mark.asyncio
async def test_plain_text_round_withholds_completed_event():
    agent = make_executor()
    step = Step(id="1", description="Uji script")
    agent.execute = _Stream([final_message("Saya sudah selesai semua.")]).execute
    wire_parse_json(agent, None)                  # non-JSON plain text

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    assert events == []
    assert agent._round_needs_correction == "plain"
    assert step.success is False
    assert step.error == "LLM returned a non-JSON response."


@pytest.mark.asyncio
async def test_message_only_step_with_attachments_is_legit():
    """A step whose purpose is delivering files completes with only a notify
    call carrying attachments — that is a real action, not a ghost."""
    agent = make_executor()
    step = Step(id="1", description="Kirim file")
    agent.execute = _Stream([
        ToolEvent(
            status=ToolStatus.CALLING,
            tool_call_id="n1",
            tool_name="message",
            function_name="message_notify_user",
            function_args={"text": "File siap.", "attachments": ["/home/z/runner/laporan.zip"]},
        ),
        final_message(ok_json()),
    ]).execute
    wire_parse_json(agent, ok_json())

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    completed = [e for e in events if isinstance(e, StepEvent)]
    assert len(completed) == 1
    assert agent._round_needs_correction is None
    assert agent._deferred_attachments == ["/home/z/runner/laporan.zip"]


@pytest.mark.asyncio
async def test_ask_user_round_has_no_correction_flag():
    agent = make_executor()
    step = Step(id="1", description="Tanya user")
    agent.execute = _Stream([
        ToolEvent(
            status=ToolStatus.CALLING,
            tool_call_id="q1",
            tool_name="message",
            function_name="message_ask_user",
            function_args={"text": "Format apa?"},
        ),
    ]).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    assert any(isinstance(e, MessageEvent) and e.is_question for e in events)
    assert agent._round_needs_correction is None


class _Stream:
    """Feeds a fixed list of events through execute()."""

    def __init__(self, events):
        self._events = events

    async def execute(self, content):
        for e in self._events:
            yield e


class _RoundScript:
    """execute() mock with a different event list per round."""

    def __init__(self, rounds: list):
        self.rounds = rounds
        self.calls = 0
        self.contents: list = []

    async def execute(self, content):
        self.contents.append(content)
        idx = min(self.calls, len(self.rounds) - 1)
        self.calls += 1
        for e in self.rounds[idx]:
            yield e


# ── execute_step: the correction loop ───────────────────────────────────────

@pytest.mark.asyncio
async def test_persistent_ghost_fails_the_step_honestly():
    """Ghost in every round (initial + 2 corrections): the step ends FAILED —
    never a false checkmark — and the user gets an explanation."""
    agent = make_executor()
    ghost_round = [final_message(ghost_json())]
    script = _RoundScript([ghost_round, ghost_round, ghost_round])
    agent.execute = script.execute
    wire_parse_json(agent, ghost_json())

    events = await _collect_step(agent)

    step_events = [e for e in events if isinstance(e, StepEvent)]
    completed = [e for e in step_events if e.status == StepStatus.COMPLETED]
    started = [e for e in step_events if e.status == StepStatus.STARTED]

    assert len(started) == 1
    assert len(completed) == 1                    # withheld until the verdict
    assert completed[0].step.success is False     # honest failure, not fake ✓
    assert "without executing any tools" in (completed[0].step.error or "")

    # 3 model rounds: initial + 2 escalating corrections.
    assert script.calls == 3
    assert "FINAL attempt" in script.contents[2]  # escalation on last round

    # The user-visible fallback narration explains the failure.
    narrations = [
        e for e in events
        if isinstance(e, MessageEvent) and e.is_progress
    ]
    assert any("fabrikasi" in (n.message or "") for n in narrations)


@pytest.mark.asyncio
async def test_ghost_then_real_work_recovers_with_single_checkmark():
    """Round 1 ghosts, the correction round does the real work: exactly ONE
    completed event, and the step ends success=True with the REAL result."""
    agent = make_executor()
    ok_round = shell_tool_events() + [final_message(ok_json("ffmpeg terinstall"))]
    script = _RoundScript([[final_message(ghost_json())], ok_round])
    agent.execute = script.execute

    async def parse(text):
        try:
            return json.loads(text)
        except Exception:
            return None
    agent._parse_json = parse

    events = await _collect_step(agent)

    step_events = [e for e in events if isinstance(e, StepEvent)]
    completed = [e for e in step_events if e.status == StepStatus.COMPLETED]
    assert len(completed) == 1
    assert completed[0].step.success is True
    assert completed[0].step.result == "ffmpeg terinstall"
    # The fabricated first-round result must not survive.
    assert "fabriki" not in (completed[0].step.result or "")
    # The correction prompt told the model its fabrication was discarded.
    assert "DISCARDED" in script.contents[1]
    # Tools of the correction round streamed into the step's timeline.
    assert any(
        isinstance(e, ToolEvent) and e.tool_name == "shell" for e in events
    )


@pytest.mark.asyncio
async def test_plain_text_then_ghost_then_recovery():
    """Mixed correction reasons also converge: plain -> ghost -> real work."""
    agent = make_executor()
    ok_round = shell_tool_events() + [final_message(ok_json("done"))]
    script = _RoundScript([
        [final_message("plain jawaban tanpa tools")],   # round 1: plain
        [final_message(ghost_json())],                  # round 2: ghost
        ok_round,                                       # round 3: real work
    ])
    agent.execute = script.execute

    async def parse(text):
        try:
            return json.loads(text)
        except Exception:
            return None
    agent._parse_json = parse

    events = await _collect_step(agent)

    completed = [
        e for e in events
        if isinstance(e, StepEvent) and e.status == StepStatus.COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0].step.success is True
    assert script.calls == 3


@pytest.mark.asyncio
async def test_legit_first_round_runs_no_correction():
    """A normal successful round is never rerun — no wasted model calls."""
    agent = make_executor()
    script = _RoundScript([shell_tool_events() + [final_message(ok_json())]])
    agent.execute = script.execute

    async def parse(text):
        return json.loads(text)
    agent._parse_json = parse

    events = await _collect_step(agent)

    assert script.calls == 1
    completed = [
        e for e in events
        if isinstance(e, StepEvent) and e.status == StepStatus.COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0].step.success is True


async def _collect_step(agent) -> list:
    plan = Plan(title="t", goal="g", language="id", steps=[])
    step = Step(id="1", description="Install ffmpeg dan yt-dlp")
    message = Message(message="buat script")
    return [e async for e in agent.execute_step(plan, step, message)]
