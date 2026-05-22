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
            mcp_tool
        ]
        
        # Only add search tool when search_engine is not None
        if search_engine:
            tools.append(SearchToolkit(search_engine))

        # Create planner and execution agents
        self.planner = PlannerAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )
        logger.debug(f"Created planner agent for Agent {self._agent_id}")
            
        self.executor = ExecutionAgent(
            agent_id=self._agent_id,
            agent_repository=self._repository,
            tools=tools,
        )
        logger.debug(f"Created execution agent for Agent {self._agent_id}")

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

        logger.info(f"Agent {self._agent_id} started processing message: {message.message[:50]}...")
        step = None
        while True:
            if self.status == AgentStatus.IDLE:
                logger.info(f"Agent {self._agent_id} state changed from {AgentStatus.IDLE} to {AgentStatus.PLANNING}")
                self.status = AgentStatus.PLANNING
            elif self.status == AgentStatus.PLANNING:
                # Stream an immediate acknowledgment to the user (<1s) while the
                # full JSON plan is being generated in the second LLM call below.
                logger.info(f"Agent {self._agent_id} streaming acknowledgment")
                async for ack_event in self.planner.acknowledge(message):
                    yield ack_event

                # Create plan
                logger.info(f"Agent {self._agent_id} started creating plan")
                async for event in self.planner.create_plan(message):
                    if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                        self.plan = event.plan

                        has_pre_extracted = "<file name=" in message.message

                        # Safety net A: 0 steps + raw sandbox attachments (no <file> tags)
                        # → inject extraction + analysis step
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

                        # Safety net B: 0 steps + pre-extracted <file> tags + analysis intent
                        # The planner should have created steps but didn't — inject analysis step.
                        analysis_keywords = [
                            "jelaskan", "explain", "analisis", "analisa", "analyze", "analyse",
                            "summarize", "summarise", "ringkas", "rangkum", "describe", "deskripsikan",
                            "ceritakan", "tell me", "what", "apa", "bagaimana", "how", "why", "kenapa",
                            "translate", "terjemahkan", "review", "evaluate", "evaluasi",
                        ]
                        msg_lower = message.message.lower()
                        has_analysis_intent = any(kw in msg_lower for kw in analysis_keywords)
                        if len(self.plan.steps) == 0 and has_pre_extracted and has_analysis_intent:
                            from app.domain.models.plan import Step as PlanStep
                            import re as _re
                            fname_match = _re.search(r'<file name="([^"]+)"', message.message)
                            fname = fname_match.group(1) if fname_match else "the uploaded file"
                            self.plan.steps = [PlanStep(
                                id="1",
                                description=(
                                    f"Read the pre-extracted content from the <file name=\"{fname}\"> tag "
                                    f"in the user message and provide a thorough, comprehensive response "
                                    f"to the user's request. Use message_notify_user to show progress. "
                                    f"Do NOT run any extraction scripts — the full text is already in the message."
                                )
                            )]
                            logger.warning(
                                f"Agent {self._agent_id}: planner returned 0 steps despite pre-extracted "
                                f"file and analysis intent — injected analysis step"
                            )

                        logger.info(f"Agent {self._agent_id} created plan successfully with {len(self.plan.steps)} steps")
                        yield TitleEvent(title=event.plan.title)
                        if len(self.plan.steps) == 0:
                            # Direct chat: plan.message IS the full answer — show it
                            yield MessageEvent(role="assistant", message=event.plan.message)
                        # else: acknowledgment already served as the user-facing intro message
                    yield event
                logger.info(f"Agent {self._agent_id} state changed from {AgentStatus.PLANNING} to {AgentStatus.EXECUTING}")
                self.status = AgentStatus.EXECUTING
                if len(self.plan.steps) == 0:
                    logger.info(f"Agent {self._agent_id} created plan successfully with no steps")
                    self.status = AgentStatus.COMPLETED
                    
            elif self.status == AgentStatus.EXECUTING:
                # Execute plan
                self.plan.status = ExecutionStatus.RUNNING
                step = self.plan.get_next_step()
                if not step:
                    logger.info(f"Agent {self._agent_id} has no more steps, state changed from {AgentStatus.EXECUTING} to {AgentStatus.COMPLETED}")
                    self.status = AgentStatus.SUMMARIZING
                    continue
                # Execute step
                logger.info(f"Agent {self._agent_id} started executing step {step.id}: {step.description[:50]}...")
                async for event in self.executor.execute_step(self.plan, step, message):
                    yield event
                logger.info(f"Agent {self._agent_id} completed step {step.id}, state changed from {AgentStatus.EXECUTING} to {AgentStatus.UPDATING}")
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