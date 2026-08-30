"""PARITY PROOF: PlanActGraphFlow (LangGraph) vs PlanActFlow (while-loop).

The user's core question when adopting LangGraph was "apakah logika AI bekerja
 akan berubah?" — these tests are the machine-checked answer: for every
 scenario, both engines drive the SAME mocked agents and MUST emit the exact
 same event sequence (type + payload, ids normalised).

Scenarios covered:
- multi-step plan with plan updates (full execute→update cycle)
- 0-step conversational plan (streamed ack is the answer)
- 0-step plan with reply-LLM failure (plan.message fallback)
- 0-step plan with empty plan.message (deterministic fallback line)
- WAITING session resume (entry straight into EXECUTING)
- max_steps guard (force-summarise progress message)
- consecutive-failures guard
- planner exception propagation
- real-time ordering: streamed ack chunks arrive BEFORE the buffered plan

Also verifies the engine flag plumbing (AGENT_FLOW_ENGINE).
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
from app.domain.services.flows.plan_act_graph import PlanActGraphFlow


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures — identical mocks for BOTH engines
# ─────────────────────────────────────────────────────────────────────────────

class _Settings:
    def __init__(self, max_steps=50, max_consecutive_failures=3):
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures


def _noop():
    async def _f(*args, **kwargs):
        return None
    return _f


def _ret(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def _make_plan(n_steps=1, message=None, language="id"):
    return Plan(
        title="Rencana Uji",
        goal="Menguji paritas engine",
        language=language,
        message=message,
        steps=[
            Step(id=str(i + 1), description=f"Langkah {i + 1}")
            for i in range(n_steps)
        ],
    )


def _build_flow(flow_cls, *, plan, ack_delivers=True, ack_chunks=None,
                session_status=SessionStatus.PENDING, last_plan=None,
                step_success=True, settings=None):
    """Build a flow skeleton of EITHER engine class with identical mocks."""
    flow = flow_cls.__new__(flow_cls)
    flow._agent_id = "test-agent"
    flow._session_id = "sess-parity"
    flow.status = AgentStatus.IDLE
    flow.plan = None
    flow._last_step = None

    # ── planner mock ──────────────────────────────────────────────────────
    planner = type("P", (), {})()
    planner._vision_model = None
    planner.roll_back = _noop()

    async def create_plan(msg):
        yield PlanEvent(status=PlanStatus.CREATED, plan=plan)

    planner.create_plan = create_plan

    async def acknowledge_stream(msg):
        if ack_delivers:
            for chunk in (ack_chunks or ["Baik, saya mulai kerjakan."]):
                yield MessageEvent(role="assistant", message=chunk)

    planner.acknowledge_stream = acknowledge_stream

    async def update_plan(plan_, step_):
        yield PlanEvent(status=PlanStatus.UPDATED, plan=plan_)

    planner.update_plan = update_plan

    # ── executor mock ─────────────────────────────────────────────────────
    executor = type("E", (), {})()
    executor.roll_back = _noop()
    executor.compact_memory = _noop()

    async def execute_step(plan_, step_, msg):
        step_.status = ExecutionStatus.COMPLETED if step_success else ExecutionStatus.FAILED
        step_.success = step_success
        yield MessageEvent(role="assistant", message=f"langkah {step_.id} selesai",
                           is_progress=True)

    executor.execute_step = execute_step

    async def summarize(attachments, current_request=None):
        yield MessageEvent(role="assistant", message="hasil akhir", is_final=True)

    executor.summarize = summarize

    flow.planner = planner
    flow.executor = executor

    # ── session repository mock ───────────────────────────────────────────
    session = type("S", (), {})()
    session.status = session_status
    session.get_last_plan = (lambda: last_plan) if last_plan else (lambda: None)

    repo = type("R", (), {})()
    repo.find_by_id = _ret(session)
    repo.update_status = _noop()
    flow._session_repository = repo
    return flow


def _sig(event):
    """Comparable signature of an event.

    Normalises per-instance fields (event uuid, timestamp, plan uuid) — those
    are generated fresh for every event on every run and carry no behavioural
    meaning. Everything else (type, payload, plan step states) must match
    EXACTLY between engines.
    """
    d = event.model_dump()
    d.pop("id", None)
    d.pop("timestamp", None)
    if isinstance(event, PlanEvent) and d.get("plan"):
        d["plan"]["id"] = "<plan>"
    return (type(event).__name__, d)


def _collect(flow, text="Buat sesuatu"):
    return [_sig(e) for e in flow.run(Message(message=text))]


def _collect_async(flow, text="Buat sesuatu"):
    async def _run():
        return [_sig(e) async for e in flow.run(Message(message=text))]
    return _run()


ENGINES = [
    ("custom", PlanActFlow),
    ("langgraph", PlanActGraphFlow),
]


# ─────────────────────────────────────────────────────────────────────────────
# Parity: full happy path (multi-step, cycle execute→update)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parity_multi_step_plan():
    """3-step plan, all succeed — both engines emit identical sequences."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(cls, plan=_make_plan(3))
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"], (
        "Event sequences diverged between engines:\n"
        f"custom:    {[s[0] for s in sigs['custom']]}\n"
        f"langgraph: {[s[0] for s in sigs['langgraph']]}"
    )
    # Sanity: sequence really exercises the cycle + final state
    kinds = [s[0] for s in sigs["custom"]]
    assert kinds.count("PlanEvent") >= 4          # 1 CREATED + 3 UPDATED
    assert kinds.count("TitleEvent") == 1
    assert kinds[-2] == "PlanEvent"               # COMPLETED plan
    assert kinds[-1] == "DoneEvent"
    assert sigs["custom"][-1][1] == {"type": "done"}


@pytest.mark.asyncio
async def test_parity_zero_step_conversational():
    """0-step plan + streamed ack delivered — ack IS the answer, no plan steps."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(cls, plan=_make_plan(0), ack_delivers=True)
        sigs[name] = await _collect_async(flow, text="Hai")

    assert sigs["custom"] == sigs["langgraph"]
    kinds = [s[0] for s in sigs["custom"]]
    assert kinds.count("MessageEvent") == 1        # only the streamed ack
    assert kinds.count("PlanEvent") == 1           # only COMPLETED (empty plan)
    assert kinds[-1] == "DoneEvent"


@pytest.mark.asyncio
async def test_parity_zero_step_reply_failure():
    """0-step plan + reply LLM failed → plan.message becomes the final answer."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(0, message="Pesan planner cadangan."),
            ack_delivers=False,
        )
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    finals = [s for s in sigs["custom"] if s[0] == "MessageEvent"]
    assert len(finals) == 1 and finals[0][1]["message"] == "Pesan planner cadangan."


@pytest.mark.asyncio
async def test_parity_multi_step_reply_failure_uses_plan_message():
    """Steps>0 + reply LLM failed → plan.message is emitted as the first response."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(2, message="Siap, saya kerjakan."),
            ack_delivers=False,
        )
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    msgs = [s for s in sigs["custom"] if s[0] == "MessageEvent"]
    assert msgs[0][1]["message"] == "Siap, saya kerjakan."
    assert msgs[0][1].get("is_final") is not True   # first response, not final


@pytest.mark.asyncio
async def test_parity_zero_step_empty_message_fallback():
    """0-step + empty plan.message + failed reply → deterministic fallback line."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(0, message=""), ack_delivers=False,
        )
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    msgs = [s for s in sigs["custom"] if s[0] == "MessageEvent"]
    assert len(msgs) == 1
    assert msgs[0][1]["message"] == "Baik, saya mulai pengerjaannya."  # id fallback


# ─────────────────────────────────────────────────────────────────────────────
# Parity: entry routing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parity_waiting_session_resumes_into_executing():
    """WAITING session → both engines skip planning and resume the last plan."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(1),
            session_status=SessionStatus.WAITING,
            last_plan=_make_plan(1),
        )
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    kinds = [s[0] for s in sigs["custom"]]
    # No plan CREATED / no first-response ack — straight into execution
    assert "TitleEvent" not in kinds
    first_msg = next(s for s in sigs["custom"] if s[0] == "MessageEvent")
    assert first_msg[1]["message"].startswith("langkah")


@pytest.mark.asyncio
async def test_parity_running_session_replans():
    """RUNNING session → both engines re-plan (PLANNING entry)."""
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(1),
            session_status=SessionStatus.RUNNING,
            last_plan=_make_plan(1),
        )
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    kinds = [s[0] for s in sigs["custom"]]
    assert kinds.count("TitleEvent") == 1          # plan phase ran


# ─────────────────────────────────────────────────────────────────────────────
# Parity: guards
# ─────────────────────────────────────────────────────────────────────────────

def _patch_settings(monkeypatch, settings):
    import app.domain.services.flows.plan_act as pa
    import app.domain.services.flows.plan_act_graph as pag
    monkeypatch.setattr(pa, "get_settings", lambda: settings)
    monkeypatch.setattr(pag, "get_settings", lambda: settings)


@pytest.mark.asyncio
async def test_parity_max_steps_guard(monkeypatch):
    """4-step plan, max_steps=2 → force-summarise with the same progress message."""
    _patch_settings(monkeypatch, _Settings(max_steps=2))
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(cls, plan=_make_plan(4))
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    msgs = [s for s in sigs["custom"] if s[0] == "MessageEvent"]
    guard_msgs = [m for m in msgs if "maximum step limit" in m[1]["message"]]
    assert len(guard_msgs) == 1
    # 2 steps executed + guard message + final summary
    step_msgs = [m for m in msgs if m[1]["message"].startswith("langkah")]
    assert len(step_msgs) == 2


@pytest.mark.asyncio
async def test_parity_consecutive_failures_guard(monkeypatch):
    """4 failing steps, max_consecutive_failures=3 → same guard message + summary."""
    _patch_settings(monkeypatch, _Settings(max_consecutive_failures=3))
    sigs = {}
    for name, cls in ENGINES:
        flow = _build_flow(cls, plan=_make_plan(4), step_success=False)
        sigs[name] = await _collect_async(flow)

    assert sigs["custom"] == sigs["langgraph"]
    msgs = [s for s in sigs["custom"] if s[0] == "MessageEvent"]
    guard_msgs = [m for m in msgs if "failed consecutively" in m[1]["message"]]
    assert len(guard_msgs) == 1
    assert guard_msgs[0][1]["message"].startswith("3 steps failed")


@pytest.mark.asyncio
async def test_parity_planner_exception_propagates():
    """Planner crash → the SAME exception escapes run() on both engines."""

    class _PlannerBoom(RuntimeError):
        pass

    for name, cls in ENGINES:
        flow = _build_flow(cls, plan=_make_plan(1))

        async def boom(msg, _f=flow):
            raise _PlannerBoom("provider down")
            yield  # pragma: no cover — make it an async generator

        flow.planner.create_plan = boom
        with pytest.raises(_PlannerBoom, match="provider down"):
            async for _ in flow.run(Message(message="Buat sesuatu")):
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Parity: real-time ordering (streamed ack BEFORE buffered plan events)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parity_streamed_ack_precedes_plan():
    """Ack chunks stream out while the planner thinks → they precede the plan.

    This is the SSE real-time contract: in the LangGraph engine the ack
    chunks flow through the custom stream writer immediately, they are NOT
    buffered until the node returns.
    """
    for name, cls in ENGINES:
        flow = _build_flow(
            cls, plan=_make_plan(2, message="pesan planner"),
            ack_chunks=["Baik, ", "saya mulai."],
        )
        events = [e async for e in flow.run(Message(message="Buat website"))]
        first_ack_idx = next(
            i for i, e in enumerate(events)
            if isinstance(e, MessageEvent) and e.message == "Baik, "
        )
        first_plan_idx = next(
            i for i, e in enumerate(events)
            if isinstance(e, PlanEvent) and e.status == PlanStatus.CREATED
        )
        assert first_ack_idx < first_plan_idx, (
            f"{name}: streamed ack must arrive before the plan event"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Engine flag plumbing
# ─────────────────────────────────────────────────────────────────────────────

def test_engine_flag_default_is_langgraph():
    from app.core.config import get_settings
    assert get_settings().agent_flow_engine == "langgraph"


def test_engine_flag_env_override(monkeypatch):
    """AGENT_FLOW_ENGINE=custom must be readable from settings (rollback path)."""
    import importlib
    import app.core.config as cfg

    monkeypatch.setenv("AGENT_FLOW_ENGINE", "custom")
    # Fresh Settings instance honouring the env var
    fresh = cfg.Settings()
    assert fresh.agent_flow_engine == "custom"


def test_task_runner_selects_engine_by_flag(monkeypatch):
    """agent_task_runner picks the flow class from the flag — verified at the
    source level (constructing the full runner needs live infra)."""
    import inspect
    from app.domain.services import agent_task_runner as atr

    src = inspect.getsource(atr)
    assert "agent_flow_engine" in src
    assert "PlanActGraphFlow" in src and "PlanActFlow" in src
