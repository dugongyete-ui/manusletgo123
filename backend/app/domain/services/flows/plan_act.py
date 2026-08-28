import asyncio
import logging
import re
from app.domain.services.flows.base import BaseFlow
from app.domain.models.message import Message
from typing import AsyncGenerator, Optional
from enum import Enum
from app.domain.models.event import (
    BaseEvent,
    PlanEvent,
    PlanStatus,
    MessageEvent,
    DoneEvent,
    TitleEvent,
)
from app.domain.models.plan import ExecutionStatus
from app.core.config import get_settings
from app.domain.services.agents.planner import PlannerAgent
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.external.sandbox import Sandbox
from app.domain.external.browser import Browser
from app.domain.external.search import SearchEngine
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.session_repository import SessionRepository
from app.domain.models.session import SessionStatus
from app.domain.services.tools.mcp import MCPToolkit
from app.domain.services.tools.shell import ShellToolkit
from app.domain.services.tools.browser import BrowserToolkit
from app.domain.services.tools.file import FileToolkit
from app.domain.services.tools.message import MessageToolkit
from app.domain.services.tools.search import SearchToolkit
from app.domain.services.tools.image import ImageToolkit
from app.domain.services.prompts.system import get_system_prompt
from app.domain.services.prompts.planner import PLANNER_SYSTEM_PROMPT
from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class AgentStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    UPDATING = "updating"



class PlanActFlow(BaseFlow):
    @staticmethod
    def _should_stream_acknowledgement(message: Message) -> bool:
        """Only pre-ack requests that are likely to execute tools.

        Conversational questions can produce a zero-step plan whose message is
        already the complete answer.  Starting an acknowledgement for those
        requests would create a second assistant bubble when that answer arrives.
        """
        if message.attachments or message.vision_images:
            return True

        task_verbs = (
            "buat", "buatkan", "bikin", "bangun", "tulis", "hasilkan",
            "ubah", "edit", "hapus", "kirim", "cari", "analisis", "unduh",
            "download", "upload", "implement", "build", "create", "write",
            "generate", "update", "delete", "send", "search", "analyze",
            "design", "run", "jalankan", "buka", "open",
        )
        words = set(re.findall(r"[a-z0-9]+", message.message.lower()))
        return any(verb in words for verb in task_verbs)

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        session_id: str,
        session_repository: SessionRepository,
        sandbox: Sandbox,
        browser: Browser,
        mcp_tool: MCPToolkit,
        search_engine: Optional[SearchEngine] = None,
        project_instruction: Optional[str] = None,
    ):
        self._agent_id = agent_id
        self._repository = agent_repository
        self._session_id = session_id
        self._session_repository = session_repository
        self.status = AgentStatus.IDLE
        self.plan = None

        tools = [
            ShellToolkit(sandbox),
            BrowserToolkit(browser),
            FileToolkit(sandbox),
            MessageToolkit(),
            ImageToolkit(sandbox),
            mcp_tool
        ]
        
        # Only add search tool when search_engine is not None
        if search_engine:
            tools.append(SearchToolkit(search_engine))

        # Build a user-specific system prompt so the agent works inside
        # the correct isolated home directory (UserScopedSandbox provides
        # user_home / upload_dir; fall back to shared defaults otherwise).
        # The environment description must match the sandbox provider that
        # actually serves this session (E2B Debian microVM vs shared Replit
        # Ubuntu container) — a mismatched prompt makes the agent emit
        # commands and paths that cannot work.
        user_home = getattr(sandbox, 'user_home', '/home/runner')
        upload_dir = getattr(sandbox, 'upload_dir', '/home/runner/upload')
        environment = getattr(sandbox, 'provider', 'replit')
        base_prompt = get_system_prompt(
            user_home=user_home, upload_dir=upload_dir, environment=environment,
            project_instruction=project_instruction,
        )

        # Create planner and execution agents
        self.planner = PlannerAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )
        self.planner.system_prompt = base_prompt + PLANNER_SYSTEM_PROMPT
        logger.debug(f"Created planner agent for Agent {self._agent_id} (home={user_home})")
            
        self.executor = ExecutionAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )
        self.executor.system_prompt = base_prompt + EXECUTION_SYSTEM_PROMPT
        logger.debug(f"Created execution agent for Agent {self._agent_id} (home={user_home})")

    async def _preprocess_images(self, message: Message) -> Message:
        """Analyze vision images once using the dedicated vision model (if configured).

        Injects a rich text description into the message and clears raw image data so
        that downstream agents (planner + executor) only ever receive plain text — even
        when the main model does not support multimodal input.
        """
        if not message.vision_images:
            return message
        if not self.planner._vision_model:
            return message  # agents will fall back individually

        logger.info("Pre-processing vision images with dedicated vision model")
        try:
            description = await self.planner._analyze_images(
                message.vision_images, message.message
            )
        except Exception as e:
            logger.warning(f"Vision pre-processing failed: {e}")
            description = ""

        if description:
            from copy import deepcopy
            enriched = deepcopy(message)
            enriched.message = message.message + f"\n\n[Image Analysis]\n{description}"
            enriched.vision_images = []
            logger.info("Vision pre-processing complete — image descriptions injected into message")
            return enriched

        # Vision analysis produced nothing (vision model down / rejected images).
        # Strip the raw images and tell the agents why: passing raw image data to
        # a text-only main model makes the provider fail the WHOLE request
        # (observed: nemotron-3 500 Internal Server Error), which kills the task.
        from copy import deepcopy
        stripped = deepcopy(message)
        stripped.message = message.message + (
            "\n\n[Note: The user attached image(s), but automatic image analysis is "
            "currently unavailable. Proceed with the text request only and tell the "
            "user you could not visually inspect the images.]"
        )
        stripped.vision_images = []
        logger.warning(
            "Vision analysis unavailable — raw images stripped from message to "
            "protect the text model request"
        )
        return stripped

    async def run(self, message: Message) -> AsyncGenerator[BaseEvent, None]:

        # Analyze vision images once up-front so every downstream agent
        # receives a consistent, text-enriched message without raw image data.
        message = await self._preprocess_images(message)

        # TODO: move to task runner
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
        # Remember the session's previous plan before re-planning overwrites it.
        # When the new plan is empty (conversational follow-up answered directly),
        # the COMPLETED PlanEvent must still reference the previous non-empty plan —
        # emitting a 0-step plan wipes the visible steps in the UI panel.
        previous_plan = self.plan

        settings = get_settings()
        _max_steps = settings.max_steps
        _max_consecutive_failures = settings.max_consecutive_failures
        _steps_executed = 0
        _consecutive_failures = 0

        logger.info(f"Agent {self._agent_id} started processing message: {message.message[:50]}...")
        step = None
        while True:
            if self.status == AgentStatus.IDLE:
                logger.info(f"Agent {self._agent_id} state changed from {AgentStatus.IDLE} to {AgentStatus.PLANNING}")
                self.status = AgentStatus.PLANNING
            elif self.status == AgentStatus.PLANNING:
                # Start planning and the short user-facing acknowledgement at
                # the same time.  The acknowledgement must not wait for the
                # planner's JSON response; that wait was the main source of the
                # "silent first response" feeling in the chat.
                logger.info(
                    f"Agent {self._agent_id} started plan and acknowledgement concurrently"
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

                async def _produce_acknowledgement() -> None:
                    try:
                        async for ack_event in self.planner.acknowledge_stream(message):
                            await event_queue.put(("ack", ack_event))
                    except Exception as exc:
                        # Acknowledgement is best-effort; the plan must still
                        # run when this optional fast path fails.
                        logger.warning(
                            f"Agent {self._agent_id} acknowledgement failed: {exc}"
                        )
                    finally:
                        await event_queue.put(("ack_done", None))

                plan_task = asyncio.create_task(_produce_plan())
                ack_task = None
                should_stream_ack = self._should_stream_acknowledgement(message)
                if should_stream_ack:
                    ack_task = asyncio.create_task(_produce_acknowledgement())
                plan_finished = False
                acknowledgement_finished = not should_stream_ack

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
                        yield event
                    elif kind == "plan_error":
                        if ack_task:
                            ack_task.cancel()
                        raise event
                    elif kind == "plan_done":
                        plan_finished = True
                    elif kind == "ack_done":
                        acknowledgement_finished = True

                if ack_task:
                    await asyncio.gather(plan_task, ack_task, return_exceptions=True)
                else:
                    await plan_task
                logger.info(
                    f"Agent {self._agent_id} created plan with {len(self.plan.steps)} steps"
                )

                # Emit the plan only after its JSON is complete.  At this point
                # the acknowledgement stream has also ended, so the next event
                # is the plan followed immediately by execution.
                if len(self.plan.steps) == 0:
                    # Simple / conversational query — plan.message IS the full answer.
                    # Skip acknowledge entirely to avoid a double-response bubble.
                    yield TitleEvent(title=self.plan.title)
                    if self.plan.message:
                        yield MessageEvent(
                            role="assistant", message=self.plan.message, is_final=True
                        )
                else:
                    yield TitleEvent(title=self.plan.title)
                    for event in plan_events_buffer:
                        if isinstance(event, PlanEvent):
                            yield event

                logger.info(f"Agent {self._agent_id} state changed from {AgentStatus.PLANNING} to {AgentStatus.EXECUTING}")
                self.status = AgentStatus.EXECUTING
                if len(self.plan.steps) == 0:
                    logger.info(f"Agent {self._agent_id} no steps — moving directly to COMPLETED")
                    self.status = AgentStatus.COMPLETED
                    
            elif self.status == AgentStatus.EXECUTING:
                # Execute plan
                self.plan.status = ExecutionStatus.RUNNING
                step = self.plan.get_next_step()
                if not step:
                    logger.info(f"Agent {self._agent_id} has no more steps, moving to SUMMARIZING")
                    self.status = AgentStatus.SUMMARIZING
                    continue

                # Guard: max total steps executed
                if _steps_executed >= _max_steps:
                    logger.warning(
                        f"Agent {self._agent_id} reached max_steps={_max_steps}, "
                        "force-moving to SUMMARIZING"
                    )
                    yield MessageEvent(
                        role="assistant",
                        message=(
                            f"Reached the maximum step limit ({_max_steps}). "
                            "Summarising with the data collected so far."
                        ),
                        is_progress=True,
                    )
                    self.status = AgentStatus.SUMMARIZING
                    continue

                # Guard: consecutive failures
                if _consecutive_failures >= _max_consecutive_failures:
                    logger.warning(
                        f"Agent {self._agent_id} reached {_consecutive_failures} consecutive "
                        f"failures (limit={_max_consecutive_failures}), force-moving to SUMMARIZING"
                    )
                    yield MessageEvent(
                        role="assistant",
                        message=(
                            f"{_consecutive_failures} steps failed consecutively. "
                            "Summarising with the data collected so far."
                        ),
                        is_progress=True,
                    )
                    self.status = AgentStatus.SUMMARIZING
                    continue

                # Execute step. No deterministic transition narration here:
                # the step rows themselves show progress live (spinner →
                # checkmark), and official Manus keeps the chat stream free of
                # "Done with X — moving on to Y" filler that would just
                # duplicate the step list the user can already see.
                logger.info(f"Agent {self._agent_id} started executing step {step.id}: {step.description[:50]}...")
                async for event in self.executor.execute_step(self.plan, step, message):
                    yield event

                _steps_executed += 1
                if step.success:
                    _consecutive_failures = 0
                else:
                    _consecutive_failures += 1
                    logger.warning(
                        f"Agent {self._agent_id} step {step.id} failed "
                        f"(consecutive_failures={_consecutive_failures}/{_max_consecutive_failures})"
                    )

                logger.info(f"Agent {self._agent_id} completed step {step.id}, moving to UPDATING")
                await self.executor.compact_memory()
                logger.debug(f"Agent {self._agent_id} compacted memory")
                self.status = AgentStatus.UPDATING
            elif self.status == AgentStatus.UPDATING:
                # Update plan
                logger.info(f"Agent {self._agent_id} started updating plan")
                async for event in self.planner.update_plan(self.plan, step):
                    yield event
                logger.info(f"Agent {self._agent_id} plan update completed, state changed from {AgentStatus.UPDATING} to {AgentStatus.EXECUTING}")
                self.status = AgentStatus.EXECUTING
            elif self.status == AgentStatus.SUMMARIZING:
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
                    yield event
                logger.info(f"Agent {self._agent_id} summarizing completed, state changed from {AgentStatus.SUMMARIZING} to {AgentStatus.COMPLETED}")
                self.status = AgentStatus.COMPLETED
            elif self.status == AgentStatus.COMPLETED:
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
                yield PlanEvent(status=PlanStatus.COMPLETED, plan=completion_plan)
                self.status = AgentStatus.IDLE
                break
        yield DoneEvent()
        
        logger.info(f"Agent {self._agent_id} message processing completed")
    
    def is_done(self) -> bool:
        return self.status == AgentStatus.IDLE