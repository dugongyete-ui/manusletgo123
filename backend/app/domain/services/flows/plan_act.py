import logging
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
        user_home = getattr(sandbox, 'user_home', '/home/runner')
        upload_dir = getattr(sandbox, 'upload_dir', '/home/runner/upload')
        base_prompt = get_system_prompt(user_home=user_home, upload_dir=upload_dir)

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
            logger.warning(f"Vision pre-processing failed, passing raw images to agents: {e}")
            return message

        if not description:
            return message

        from copy import deepcopy
        enriched = deepcopy(message)
        enriched.message = message.message + f"\n\n[Image Analysis]\n{description}"
        enriched.vision_images = []
        logger.info("Vision pre-processing complete — image descriptions injected into message")
        return enriched

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
                # ── Step 1: collect the plan first so we know whether steps exist ─────
                logger.info(f"Agent {self._agent_id} started creating plan")
                plan_events_buffer = []
                async for event in self.planner.create_plan(message):
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

                logger.info(f"Agent {self._agent_id} created plan with {len(self.plan.steps)} steps")

                # ── Step 2: now stream acknowledge OR direct answer based on step count ─
                if len(self.plan.steps) == 0:
                    # Simple / conversational query — plan.message IS the full answer.
                    # Skip acknowledge entirely to avoid a double-response bubble.
                    yield TitleEvent(title=self.plan.title)
                    if self.plan.message:
                        yield MessageEvent(role="assistant", message=self.plan.message)
                else:
                    # Complex query: send acknowledgment streaming NOW (gives quick feedback
                    # while the user watches the plan appear below it).
                    logger.info(f"Agent {self._agent_id} streaming acknowledgment")
                    async for ack_event in self.planner.acknowledge(message):
                        yield ack_event

                    # Emit buffered plan events so the UI can render the steps list
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
                            f"⚠️ Reached the maximum step limit ({_max_steps}). "
                            "Summarising with the data collected so far."
                        ),
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
                            f"⚠️ {_consecutive_failures} steps failed consecutively. "
                            "Summarising with the data collected so far."
                        ),
                    )
                    self.status = AgentStatus.SUMMARIZING
                    continue

                # Execute step
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
                async for event in self.executor.summarize():
                    yield event
                logger.info(f"Agent {self._agent_id} summarizing completed, state changed from {AgentStatus.SUMMARIZING} to {AgentStatus.COMPLETED}")
                self.status = AgentStatus.COMPLETED
            elif self.status == AgentStatus.COMPLETED:
                self.plan.status = ExecutionStatus.COMPLETED
                logger.info(f"Agent {self._agent_id} plan has been completed")
                yield PlanEvent(status=PlanStatus.COMPLETED, plan=self.plan)
                self.status = AgentStatus.IDLE
                break
        yield DoneEvent()
        
        logger.info(f"Agent {self._agent_id} message processing completed")
    
    def is_done(self) -> bool:
        return self.status == AgentStatus.IDLE