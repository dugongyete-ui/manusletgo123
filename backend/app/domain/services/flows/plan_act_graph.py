"""LangGraph-backed driver for the plan→execute→update agent loop.

``PlanActGraphFlow`` is a drop-in engine swap for ``PlanActFlow``: it inherits
the SAME constructor (same agents, tools, prompts, repositories) and re-runs
the SAME state machine — PLANNING → EXECUTING → UPDATING → (cycle) →
SUMMARIZING → COMPLETED — but the loop is driven by a LangGraph
``StateGraph`` instead of a hand-rolled ``while True``.

Design contract (parity over novelty):
- Every agent call is unchanged: ``planner.create_plan``,
  ``planner.acknowledge_stream``, ``planner.update_plan``,
  ``executor.execute_step``, ``executor.compact_memory``,
  ``executor.summarize`` — identical order, identical arguments.
- Every guard is unchanged: max_steps, max_consecutive_failures,
  the 0-step safety nets, the mandatory first response, the
  previous-plan completion fallback.
- Every event is unchanged and streams to the consumer in real time via
  LangGraph custom streaming (``stream_mode="custom"``), preserving the SSE
  behaviour (ack chunks arrive while the planner is still thinking).
- Exceptions propagate out of ``run()`` exactly like the original generator.

What LangGraph adds here:
- The loop is an explicit graph (visualisable, auditable) instead of
  implicit control flow buried in a while-loop.
- Graph state (status / steps_executed / consecutive_failures) is managed
  by LangGraph channels — ready for a checkpointer (crash resume) and
  ``interrupt()`` (human approval gates) without touching the nodes.
- ``thread_id`` is wired to the session id so a future MongoDB checkpointer
  can drop in per-session.

Engine selection is data-driven via ``AGENT_FLOW_ENGINE`` (default
``langgraph``; ``custom`` restores the original loop) — see config.py.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.domain.models.event import (
    BaseEvent,
    DoneEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    TitleEvent,
)
from app.domain.models.message import Message
from app.domain.models.plan import ExecutionStatus
from app.domain.models.session import SessionStatus
from app.core.config import get_settings
from app.domain.services.flows.plan_act import AgentStatus, PlanActFlow

logger = logging.getLogger(__name__)

# AgentStatus → graph entry node (mirrors the original while-loop dispatch:
# a WAITING session resumes straight into EXECUTING, RUNNING re-plans).
_ENTRY_NODES: dict = {
    AgentStatus.IDLE: "plan",
    AgentStatus.PLANNING: "plan",
    AgentStatus.EXECUTING: "execute",
    AgentStatus.UPDATING: "update",
    AgentStatus.SUMMARIZING: "summarize",
    AgentStatus.COMPLETED: "complete",
}


class _GraphState(TypedDict):
    """Loop state owned by LangGraph channels.

    The Plan/Step domain objects stay on the flow instance (they are shared
    mutable models the agents write into); only the routing key and the two
    loop counters live in graph state so every transition is checkpointable.
    """

    status: str
    steps_executed: int
    consecutive_failures: int


class PlanActGraphFlow(PlanActFlow):
    """PlanActFlow with the while-loop replaced by a LangGraph StateGraph.

    The node bodies below are verbatim ports of the original branches —
    every ``yield event`` became ``writer(event)``; nothing else changed.
    """

    async def run(self, message: Message) -> AsyncGenerator[BaseEvent, None]:

        # ── Preamble: identical to PlanActFlow.run() ──────────────────────
        message = await self._preprocess_images(message)

        session = await self._session_repository.find_by_id(self._session_id)
        if not session:
            raise ValueError(f"Session {self._session_id} not found")

        if session.status != SessionStatus.PENDING:
            logger.debug(f"Session {self._session_id} is not in PENDING status, rolling back")
            await self.executor.roll_back(message)
            await self.planner.roll_back(message)

        if session.status == SessionStatus.RUNNING:
            logger.debug(f"Session {self._session_id} is in RUNNING status")
            self.status = AgentStatus.PLANNING

        if session.status == SessionStatus.WAITING:
            logger.debug(f"Session {self._session_id} is in WAITING status")
            self.status = AgentStatus.EXECUTING

        await self._session_repository.update_status(self._session_id, SessionStatus.RUNNING)
        self.plan = session.get_last_plan()
        previous_plan = self.plan

        settings = get_settings()
        _max_steps = settings.max_steps
        _max_consecutive_failures = settings.max_consecutive_failures

        logger.info(f"Agent {self._agent_id} started processing message: {message.message[:50]}...")
        # The step being executed / last executed (mirrors the original
        # ``step`` local reused by the UPDATING branch).
        self._last_step = None

        # ── Node bodies: verbatim ports of the while-loop branches ────────

        async def plan_node(state: _GraphState):
            writer = get_stream_writer()
            if self.status == AgentStatus.IDLE:
                logger.info(
                    f"Agent {self._agent_id} state changed from {AgentStatus.IDLE} "
                    f"to {AgentStatus.PLANNING}"
                )
                self.status = AgentStatus.PLANNING

            # Start planning and the user-facing first reply at the same
            # time — ALWAYS, for every message.  The first reply must not
            # wait for the planner's JSON response; that wait was the main
            # source of the "silent first response" feeling in the chat.
            # There is deliberately NO keyword/verb gate here (see
            # PlanActFlow for the full rationale).
            logger.info(
                f"Agent {self._agent_id} started plan and first reply concurrently"
            )
            plan_events_buffer = []
            event_queue: asyncio.Queue = asyncio.Queue()

            async def _produce_plan() -> None:
                try:
                    async for plan_event in self.planner.create_plan(message):
                        await event_queue.put(("plan", plan_event))
                except Exception as exc:
                    await event_queue.put(("plan_error", exc))
                finally:
                    await event_queue.put(("plan_done", None))

            async def _produce_first_reply() -> None:
                try:
                    async for ack_event in self.planner.acknowledge_stream(message):
                        await event_queue.put(("ack", ack_event))
                except Exception as exc:
                    # First reply is best-effort; the plan must still
                    # run when this optional fast path fails.
                    logger.warning(
                        f"Agent {self._agent_id} first reply failed: {exc}"
                    )
                finally:
                    await event_queue.put(("ack_done", None))

            plan_task = asyncio.create_task(_produce_plan())
            ack_task = asyncio.create_task(_produce_first_reply())
            plan_finished = False
            acknowledgement_finished = False
            # Whether the first reply actually DELIVERED a user-visible
            # assistant message (see PlanActFlow for the rationale).
            ack_message_delivered = False

            while not (plan_finished and acknowledgement_finished):
                kind, event = await event_queue.get()
                if kind == "plan":
                    plan_events_buffer.append(event)
                    if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                        self.plan = event.plan

                        has_pre_extracted = "<file name=" in message.message

                        # Safety net A: 0 steps + raw sandbox attachments (no <file> tags)
                        if len(self.plan.steps) == 0 and message.attachments and not has_pre_extracted:
                            from app.domain.models.plan import Step as PlanStep
                            file_list = "\n".join(message.attachments)
                            self.plan.steps = [PlanStep(
                                id="1",
                                description=(
                                    f"Extract and analyze the content of the uploaded file(s):\n"
                                    f"{file_list}\n"
                                    f"Save extracted text to /tmp/extracted_content.txt, "
                                    f"then read it and respond to the user's request."
                                )
                            )]
                            logger.warning(
                                f"Agent {self._agent_id}: planner returned 0 steps with "
                                f"{len(message.attachments)} raw attachment(s) — injected default step"
                            )

                        # Safety net B: 0 steps + pre-extracted <file> tags
                        if len(self.plan.steps) == 0 and has_pre_extracted:
                            from app.domain.models.plan import Step as PlanStep
                            import re as _re
                            fname_match = _re.search(r'<file name="([^"]+)"', message.message)
                            fname = fname_match.group(1) if fname_match else "the uploaded file"
                            self.plan.steps = [PlanStep(
                                id="1",
                                description=(
                                    f"The file \"{fname}\" content is already in the user message "
                                    f"inside <file> tags. Read it and respond to the user's request fully."
                                )
                            )]
                            logger.info(
                                f"Agent {self._agent_id}: routed pre-extracted file request "
                                f"through executor for a complete response"
                            )
                elif kind == "ack":
                    # Message chunks go straight to the SSE stream and are
                    # intentionally not persisted by the task runner.
                    writer(event)
                    if (
                        isinstance(event, MessageEvent)
                        and (event.message or "").strip()
                    ):
                        ack_message_delivered = True
                elif kind == "plan_error":
                    if ack_task:
                        ack_task.cancel()
                    raise event
                elif kind == "plan_done":
                    plan_finished = True
                elif kind == "ack_done":
                    acknowledgement_finished = True

            await asyncio.gather(plan_task, ack_task, return_exceptions=True)
            logger.info(
                f"Agent {self._agent_id} created plan with {len(self.plan.steps)} steps"
            )

            # Emit the plan only after its JSON is complete (see PlanActFlow).
            if len(self.plan.steps) == 0:
                # Simple / conversational query — the streamed first reply
                # IS the answer; plan.message only fires when it failed.
                writer(TitleEvent(title=self.plan.title))
                if not ack_message_delivered:
                    if self.plan.message:
                        writer(MessageEvent(
                            role="assistant", message=self.plan.message, is_final=True
                        ))
                    else:
                        # Edge: 0 steps AND empty message — still answer something.
                        writer(MessageEvent(
                            role="assistant",
                            message=self._fallback_ack_text(
                                self.plan.language, message.message
                            ),
                            is_final=True,
                        ))
            else:
                # ── MANDATORY FIRST RESPONSE ────────────────────────────
                # The user must ALWAYS see an assistant reply before the
                # plan/step list appears (see PlanActFlow for the rationale).
                if not ack_message_delivered:
                    first_response = (self.plan.message or "").strip()
                    if not first_response:
                        first_response = self._fallback_ack_text(
                            self.plan.language, message.message
                        )
                    writer(MessageEvent(role="assistant", message=first_response))
                    logger.info(
                        f"Agent {self._agent_id} acknowledgement was not "
                        f"streamed — emitted plan.message as mandatory "
                        f"first response ({len(first_response)} chars)"
                    )
                writer(TitleEvent(title=self.plan.title))
                for event in plan_events_buffer:
                    if isinstance(event, PlanEvent):
                        writer(event)

            logger.info(
                f"Agent {self._agent_id} state changed from "
                f"{AgentStatus.PLANNING} to {AgentStatus.EXECUTING}"
            )
            self.status = AgentStatus.EXECUTING
            if len(self.plan.steps) == 0:
                logger.info(f"Agent {self._agent_id} no steps — moving directly to COMPLETED")
                self.status = AgentStatus.COMPLETED
                return {"status": "complete"}
            return {"status": "execute"}

        async def execute_node(state: _GraphState):
            writer = get_stream_writer()
            # Execute plan
            self.plan.status = ExecutionStatus.RUNNING
            step = self.plan.get_next_step()
            if not step:
                logger.info(f"Agent {self._agent_id} has no more steps, moving to SUMMARIZING")
                self.status = AgentStatus.SUMMARIZING
                return {"status": "summarize"}

            # Guard: max total steps executed
            if state["steps_executed"] >= _max_steps:
                logger.warning(
                    f"Agent {self._agent_id} reached max_steps={_max_steps}, "
                    "force-moving to SUMMARIZING"
                )
                writer(MessageEvent(
                    role="assistant",
                    message=(
                        f"Reached the maximum step limit ({_max_steps}). "
                        "Summarising with the data collected so far."
                    ),
                    is_progress=True,
                ))
                self.status = AgentStatus.SUMMARIZING
                return {"status": "summarize"}

            # Guard: consecutive failures
            if state["consecutive_failures"] >= _max_consecutive_failures:
                logger.warning(
                    f"Agent {self._agent_id} reached {state['consecutive_failures']} consecutive "
                    f"failures (limit={_max_consecutive_failures}), force-moving to SUMMARIZING"
                )
                writer(MessageEvent(
                    role="assistant",
                    message=(
                        f"{state['consecutive_failures']} steps failed consecutively. "
                        "Summarising with the data collected so far."
                    ),
                    is_progress=True,
                ))
                self.status = AgentStatus.SUMMARIZING
                return {"status": "summarize"}

            # Execute step. No deterministic transition narration here:
            # the step rows themselves show progress live (see PlanActFlow).
            logger.info(f"Agent {self._agent_id} started executing step {step.id}: {step.description[:50]}...")
            async for event in self.executor.execute_step(self.plan, step, message):
                writer(event)

            steps_executed = state["steps_executed"] + 1
            consecutive_failures = state["consecutive_failures"]
            if step.success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(
                    f"Agent {self._agent_id} step {step.id} failed "
                    f"(consecutive_failures={consecutive_failures}/{_max_consecutive_failures})"
                )

            logger.info(f"Agent {self._agent_id} completed step {step.id}, moving to UPDATING")
            await self.executor.compact_memory()
            logger.debug(f"Agent {self._agent_id} compacted memory")
            self._last_step = step
            self.status = AgentStatus.UPDATING
            return {
                "status": "update",
                "steps_executed": steps_executed,
                "consecutive_failures": consecutive_failures,
            }

        async def update_node(state: _GraphState):
            writer = get_stream_writer()
            # Update plan
            logger.info(f"Agent {self._agent_id} started updating plan")
            async for event in self.planner.update_plan(self.plan, self._last_step):
                writer(event)
            logger.info(
                f"Agent {self._agent_id} plan update completed, state changed from "
                f"{AgentStatus.UPDATING} to {AgentStatus.EXECUTING}"
            )
            self.status = AgentStatus.EXECUTING
            return {"status": "execute"}

        async def summarize_node(state: _GraphState):
            writer = get_stream_writer()
            # Conclusion
            logger.info(f"Agent {self._agent_id} started summarizing")
            # Collect the final deliverable file paths recorded by every
            # step's result JSON — delivered once, here, in the summary.
            from app.domain.services.agents.attachment_paths import (
                normalize_attachment_paths,
            )

            step_attachments: list = []
            seen_paths: set = set()
            if self.plan is not None:
                for s in self.plan.steps or []:
                    for fp in normalize_attachment_paths(
                        getattr(s, "attachments", None)
                    ):
                        if fp and fp not in seen_paths:
                            seen_paths.add(fp)
                            step_attachments.append(fp)
            if step_attachments:
                logger.info(
                    f"Agent {self._agent_id} summary will deliver {len(step_attachments)} "
                    f"step deliverable(s): {step_attachments}"
                )
            async for event in self.executor.summarize(
                step_attachments, current_request=message.message
            ):
                writer(event)
            logger.info(
                f"Agent {self._agent_id} summarizing completed, state changed from "
                f"{AgentStatus.SUMMARIZING} to {AgentStatus.COMPLETED}"
            )
            self.status = AgentStatus.COMPLETED
            return {"status": "complete"}

        async def complete_node(state: _GraphState):
            writer = get_stream_writer()
            # Prefer the previous non-empty plan when the current one is empty
            # (conversational follow-up): completing with a 0-step plan would
            # make the user's visible plan disappear from the UI.
            completion_plan = self.plan
            if (
                (not completion_plan or not completion_plan.steps)
                and previous_plan and previous_plan.steps
            ):
                completion_plan = previous_plan
            completion_plan.status = ExecutionStatus.COMPLETED
            logger.info(f"Agent {self._agent_id} plan has been completed")
            writer(PlanEvent(status=PlanStatus.COMPLETED, plan=completion_plan))
            self.status = AgentStatus.IDLE
            return {"status": "idle"}

        # ── Routing (mirrors the while-loop transitions 1:1) ──────────────

        def _route_entry(state: _GraphState) -> str:
            return state["status"]

        def _route_after_plan(state: _GraphState) -> str:
            return state["status"]  # "execute" | "complete"

        def _route_after_execute(state: _GraphState) -> str:
            return state["status"]  # "update" | "summarize"

        graph = (
            StateGraph(_GraphState)
            .add_node("plan", plan_node)
            .add_node("execute", execute_node)
            .add_node("update", update_node)
            .add_node("summarize", summarize_node)
            .add_node("complete", complete_node)
            .add_conditional_edges(
                START, _route_entry,
                {name: name for name in set(_ENTRY_NODES.values())},
            )
            .add_conditional_edges(
                "plan", _route_after_plan,
                {"execute": "execute", "complete": "complete"},
            )
            .add_conditional_edges(
                "execute", _route_after_execute,
                {"update": "update", "summarize": "summarize"},
            )
            # update → execute → … cycle, exactly like the original loop
            .add_edge("update", "execute")
            .add_edge("summarize", "complete")
            .add_edge("complete", END)
            .compile()
        )

        entry_node = _ENTRY_NODES.get(self.status, "plan")
        # recursion_limit: each super-step counts one node execution. The
        # original loop allows max_steps executions (each = execute + update
        # nodes) plus the fixed phases — the default limit of 25 would kill
        # long plans well before max_steps.
        config = {
            "configurable": {"thread_id": str(self._session_id)},
            "recursion_limit": _max_steps * 2 + 20,
        }

        async for event in graph.astream(
            {"status": entry_node, "steps_executed": 0, "consecutive_failures": 0},
            config,
            stream_mode="custom",
        ):
            yield event

        yield DoneEvent()
        logger.info(f"Agent {self._agent_id} message processing completed")
