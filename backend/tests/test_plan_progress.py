"""Task 22 — Real-time plan progress + prompt-length compaction.

Live incident (session e4931d85ae304ede, "clone ChatGPT" task):
1. The executor ran ~9 minutes INSIDE step 1 and finished the work of all
   four phases (scaffold, backend, frontend, browser test, zip) — but the
   plan panel stayed frozen at "step 1 of 4" the whole time because
   PlanEvents were only emitted at step boundaries.
2. update_plan then marked ONLY step 1 completed (steps 2-4 stayed pending
   even though their goals were already met).
3. Step 2 crashed instantly with provider error 1261 "Prompt exceeds max
   length" — 30 file_write calls had left the FULL file bodies inside
   AIMessage.tool_calls arguments, which memory compaction never touched.

These tests pin the three mechanisms (all format/contract-level, no
task-domain hardcodes anywhere):

A. Live plan progress  — throttled mid-step judge marks fully-met pending
   steps and emits PlanEvent(UPDATED); never the current step; failures
   are silently ignored.
B. Boundary accuracy   — UPDATE_PLAN_PROMPT instructs deleting already
   achieved later steps.
C. Memory compaction   — stale bulky ToolMessages stubbed; old bulky
   tool_call ARGUMENTS (file_write content / shell_exec command) stubbed
   while the most recent calls stay intact.
"""

import json
import time

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from app.domain.models.event import PlanEvent, PlanStatus
from app.domain.models.memory import Memory
from app.domain.models.plan import ExecutionStatus, Plan, Step
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.services.prompts.planner import UPDATE_PLAN_PROMPT


# ── helpers ────────────────────────────────────────────────────────────────


def make_plan() -> Plan:
    return Plan(
        title="t",
        goal="g",
        language="en",
        steps=[
            Step(id="1", description="Scaffold the project structure"),
            Step(id="2", description="Implement the backend API"),
            Step(id="3", description="Build the frontend UI"),
            Step(id="4", description="Run the app and verify"),
        ],
    )


def make_executor(plan: Plan, judge_reply: str = "{}") -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)

    class _Mem:
        def __init__(self):
            self.messages = [
                ToolMessage(name="file_write", content="wrote server.js", tool_call_id="a"),
                ToolMessage(name="shell_exec", content="npm install ok", tool_call_id="b"),
            ]

        def get_messages(self):
            return self.messages

    agent.memory = _Mem()
    agent.calls = {"judge": 0}

    async def astream_text_with_fallback(messages):
        agent.calls["judge"] += 1
        return judge_reply

    agent.astream_text_with_fallback = astream_text_with_fallback
    return agent


def ctx_for(agent: ExecutionAgent, plan: Plan, current_id="1", **overrides):
    current = next(s for s in plan.steps if s.id == current_id)
    ctx = {
        "plan": plan,
        "step": current,
        "started": time.monotonic() - 1000.0,  # step is "old" by default
        "last_check": None,
        "rounds_since_check": 10,
        "checks": 0,
    }
    ctx.update(overrides)
    agent._step_progress = ctx
    return ctx


# ── A. live plan progress ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_judge_marks_fully_met_steps_and_emits_plan_event():
    plan = make_plan()
    plan.steps[0].status = ExecutionStatus.COMPLETED
    agent = make_executor(plan, judge_reply='{"completed_ids": ["2", "3"]}')
    ctx_for(agent, plan, current_id="4")

    events = [e async for e in agent._on_tool_round_end(5)]

    assert plan.steps[1].status == ExecutionStatus.COMPLETED
    assert plan.steps[2].status == ExecutionStatus.COMPLETED
    assert plan.steps[3].status == ExecutionStatus.PENDING  # current untouched
    assert agent.calls["judge"] == 1
    assert any(isinstance(e, PlanEvent) and e.status == PlanStatus.UPDATED for e in events)


@pytest.mark.asyncio
async def test_judge_never_marks_current_step():
    plan = make_plan()
    agent = make_executor(plan, judge_reply='{"completed_ids": ["1"]}')
    ctx_for(agent, plan, current_id="1")

    events = [e async for e in agent._on_tool_round_end(5)]

    assert plan.steps[0].status == ExecutionStatus.PENDING
    assert events == []


@pytest.mark.asyncio
async def test_judge_bad_json_ignored():
    plan = make_plan()
    agent = make_executor(plan, judge_reply="not json at all")
    ctx_for(agent, plan, current_id="1")

    events = [e async for e in agent._on_tool_round_end(5)]
    assert events == []
    assert all(s.status == ExecutionStatus.PENDING for s in plan.steps)


@pytest.mark.asyncio
async def test_judge_exception_swallowed():
    plan = make_plan()
    agent = make_executor(plan)

    async def boom(messages):
        raise RuntimeError("provider down")

    agent.astream_text_with_fallback = boom
    ctx_for(agent, plan, current_id="1")
    events = [e async for e in agent._on_tool_round_end(5)]
    assert events == []  # and no raise


@pytest.mark.asyncio
async def test_throttle_young_step_no_llm_call():
    plan = make_plan()
    agent = make_executor(plan)
    ctx_for(agent, plan, current_id="1", started=time.monotonic())
    events = [e async for e in agent._on_tool_round_end(5)]
    assert events == []
    assert agent.calls["judge"] == 0


@pytest.mark.asyncio
async def test_throttle_interval_and_rounds():
    plan = make_plan()
    agent = make_executor(plan)
    # Last check moments ago -> suppressed even with enough rounds.
    ctx_for(
        agent, plan, current_id="1",
        last_check=time.monotonic() - 1.0, rounds_since_check=10,
    )
    assert [e async for e in agent._on_tool_round_end(5)] == []
    assert agent.calls["judge"] == 0
    # Interval OK but too few rounds -> suppressed.
    ctx_for(agent, plan, current_id="1", last_check=None, rounds_since_check=1)
    assert [e async for e in agent._on_tool_round_end(5)] == []
    assert agent.calls["judge"] == 0


@pytest.mark.asyncio
async def test_check_budget_capped():
    plan = make_plan()
    agent = make_executor(plan)
    ctx_for(agent, plan, current_id="1", checks=12)
    assert [e async for e in agent._on_tool_round_end(5)] == []
    assert agent.calls["judge"] == 0


@pytest.mark.asyncio
async def test_no_pending_steps_skips_llm():
    plan = make_plan()
    for s in plan.steps:
        s.status = ExecutionStatus.COMPLETED
    agent = make_executor(plan)
    ctx_for(agent, plan, current_id="1", step=plan.steps[0])
    agent._step_progress["step"] = plan.steps[0]
    assert [e async for e in agent._on_tool_round_end(5)] == []
    assert agent.calls["judge"] == 0


# ── B. boundary accuracy ───────────────────────────────────────────────────


def test_update_plan_prompt_requires_deleting_achieved_steps():
    """The planner must delete later steps whose goals were already met,
    so the plan reflects reality at each boundary (second safety net)."""
    assert "already fully achieved" in UPDATE_PLAN_PROMPT
    assert "DELETE that step" in UPDATE_PLAN_PROMPT
    # Brace-safety: .format() with plan/step kwargs must not raise.
    _ = UPDATE_PLAN_PROMPT.format(plan="{}", step="{}")


# ── C. memory compaction ───────────────────────────────────────────────────


def _ai_with_file_write(content: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "file_write",
                "args": {"file": "f.py", "content": content},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def test_compact_stubs_old_file_write_tool_messages():
    mem = Memory()
    big = "x" * 5000
    mem.add_message(HumanMessage(content="go"))
    mem.add_message(_ai_with_file_write(big, "c1"))
    mem.add_message(ToolMessage(name="file_write", content=big, tool_call_id="c1"))
    mem.add_message(_ai_with_file_write(big, "c2"))
    mem.add_message(ToolMessage(name="file_write", content=big, tool_call_id="c2"))
    mem.add_message(_ai_with_file_write(big, "c3"))
    mem.add_message(ToolMessage(name="file_write", content=big, tool_call_id="c3"))

    mem.compact()

    tool_msgs = [m for m in mem.messages if m.type == "tool"]
    # Only the LAST file_write result stays intact; older ones stubbed.
    assert len(tool_msgs[0].content) < 200
    assert len(tool_msgs[1].content) < 200
    assert len(tool_msgs[2].content) == len(big)


def test_compact_stubs_old_bulky_tool_call_args():
    mem = Memory()
    big = "y" * 8000
    # Three file_write rounds: the two NEWEST keep full args, the oldest is stubbed.
    mem.add_message(_ai_with_file_write(big, "c1"))
    mem.add_message(_ai_with_file_write(big, "c2"))
    mem.add_message(_ai_with_file_write(big, "c3"))

    mem.compact()

    ai_calls = [m for m in mem.messages if m.type == "ai"]
    oldest = ai_calls[0].tool_calls[0]["args"]["content"]
    newest = ai_calls[-1].tool_calls[0]["args"]["content"]
    assert oldest.startswith("(compacted:")
    assert len(oldest) < 100
    assert ai_calls[1].tool_calls[0]["args"]["content"] == big
    assert newest == big


def test_compact_small_tool_call_args_untouched():
    mem = Memory()
    small = "print('hi')"
    mem.add_message(_ai_with_file_write(small, "c1"))
    mem.add_message(_ai_with_file_write(small, "c2"))
    mem.add_message(_ai_with_file_write(small, "c3"))
    mem.compact()
    ai_calls = [m for m in mem.messages if m.type == "ai"]
    assert all(m.tool_calls[0]["args"]["content"] == small for m in ai_calls)


def test_compact_shell_exec_command_args_stubbed():
    mem = Memory()
    script = "echo " + "z" * 3000
    for i in range(3):
        mem.add_message(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "shell_exec",
                        "args": {"command": script},
                        "id": f"c{i}",
                        "type": "tool_call",
                    }
                ],
            )
        )
    mem.compact()
    ai_calls = [m for m in mem.messages if m.type == "ai"]
    assert ai_calls[0].tool_calls[0]["args"]["command"].startswith("(compacted:")
    assert ai_calls[-1].tool_calls[0]["args"]["command"] == script


def test_compact_preserves_non_bulky_messages():
    mem = Memory()
    mem.add_message(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "browser_click",
                    "args": {"index": 5},
                    "id": "c1",
                    "type": "tool_call",
                }
            ],
        )
    )
    mem.add_message(ToolMessage(name="browser_click", content="ok", tool_call_id="c1"))
    mem.compact()
    assert mem.messages[0].tool_calls[0]["args"] == {"index": 5}
    assert mem.messages[1].content == "ok"


def test_compact_shrinks_serialized_payload():
    """End-to-end guard: after compaction the OpenAI-serialized argument
    payload must actually shrink (the provider prompt-length fix)."""
    from langchain_openai.chat_models.base import _convert_message_to_dict

    mem = Memory()
    body = "a" * 20000
    for i in range(4):
        mem.add_message(_ai_with_file_write(body, f"c{i}"))

    def payload_len():
        return sum(
            len(m.tool_calls[0]["args"]["content"])
            for m in mem.messages
            if m.type == "ai"
            and isinstance(m.tool_calls, list)
            and m.tool_calls
        )

    before = payload_len()
    mem.compact()
    after = payload_len()
    assert before == 4 * 20000
    assert after < 2 * 20000 + 200  # only the two newest remain full
    # Serializer really sees the stub (mutation is effective, not just local).
    d = _convert_message_to_dict(mem.messages[0])
    assert "(compacted:" in d["tool_calls"][0]["function"]["arguments"]
