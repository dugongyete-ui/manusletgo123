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
    ValidationEvent,
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
    def _fallback_ack_text(language: Optional[str], message_text: str) -> str:
        """Last-resort deterministic first response.

        Used only when BOTH the streamed first reply failed to deliver a
        message AND the planner's plan.message is empty — normally the
        streamed reply serves as the guaranteed first response, so this
        line almost never fires.  Language follows the planner's language
        field with a structural keyword fallback from the user's message.
        """
        lang = (language or "").lower()
        text = (message_text or "").lower()
        indonesian = (
            lang.startswith("id")
            or "indonesia" in lang
            or "bahasa" in lang
            or any(w in text for w in ("apa", "yang", "saya", "tolong", "bisa", "dengan", "buat"))
        )
        if indonesian:
            return "Baik, saya mulai pengerjaannya."
        return "On it — starting now."

    # ── Conversation context for the streamed first reply ─────────────
    # Caps keep the digest small: it is injected into EVERY first-reply
    # prompt (a fast, user-facing path), so it must never balloon into a
    # second copy of the whole transcript.
    _DIGEST_MAX_MESSAGES = 16        # newest N conversational turns
    _DIGEST_PER_MESSAGE_CHARS = 600  # head-truncate individual messages
    _DIGEST_MAX_TOTAL_CHARS = 4000   # global budget, newest side kept

    @classmethod
    def _build_conversation_digest(cls, session, message: Message) -> str:
        """Build a compact transcript of the session's EARLIER turns.

        Source: persisted session events (user + assistant messages only —
        progress narrations, plans, steps and tool events are skipped).

        Why this exists: the streamed first reply (the "ack" path) is the
        model call that answers conversational follow-ups, but it is
        deliberately memory-free (no ``self.memory`` — that state belongs to
        the parallel planner/executor agents).  Without a transcript a
        follow-up like "what did we discuss before?" was answered with "I
        have no previous conversation history" — even though the previous
        turns were fully persisted in the session events.

        The CURRENT message is excluded (it is already in the prompt as the
        message being replied to): chat() early-persists the user message
        BEFORE the flow runs, so it is normally the LAST user event here.
        """
        from app.domain.models.event import MessageEvent as _MessageEvent

        turns: list[tuple[str, str]] = []
        for ev in list(getattr(session, "events", None) or []):
            role = text = None
            is_progress = False
            if isinstance(ev, _MessageEvent):
                role, text, is_progress = ev.role, ev.message, ev.is_progress
            elif isinstance(ev, dict) and ev.get("type") == "message":
                # Defensive: a repository that returns raw dicts still works.
                role = ev.get("role")
                text = ev.get("message")
                is_progress = bool(ev.get("is_progress"))
            else:
                continue  # plan / step / tool / title / done / error events
            if is_progress:
                continue  # step & tool narration — not a conversational turn
            text = (text or "").strip()
            if not text:
                continue
            if role == "user":
                turns.append(("User", text))
            elif role == "assistant":
                turns.append(("Assistant", text))

        # Drop the current message (early-persisted by chat() before run()).
        current_text = (message.message or "").strip()
        while turns and turns[-1][0] == "User" and turns[-1][1] == current_text:
            turns.pop()

        if not turns:
            return ""

        # Keep only the NEWEST turns, then render oldest → newest.
        turns = turns[-cls._DIGEST_MAX_MESSAGES:]

        lines: list[str] = []
        for role, text in turns:
            if len(text) > cls._DIGEST_PER_MESSAGE_CHARS:
                text = text[: cls._DIGEST_PER_MESSAGE_CHARS - 1].rstrip() + "…"
            lines.append(f"{role}: {text}")

        # Enforce the global budget from the NEWEST side (recent context
        # matters most for follow-ups).  The +1 per line accounts for the
        # "\n" separator added by the final join, so the RESULT string
        # (separators included) stays within the budget.
        total = sum(len(line) for line in lines)
        if total > cls._DIGEST_MAX_TOTAL_CHARS:
            kept: list[str] = []
            budget = cls._DIGEST_MAX_TOTAL_CHARS
            for line in reversed(lines):
                if budget < 2:  # room for content + separator only
                    break
                if len(line) + 1 > budget:
                    line = line[: budget - 2].rstrip() + "…"
                kept.append(line)
                budget -= len(line) + 1
            lines = list(reversed(kept))

        return "\n".join(lines)

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
        knowledge: Optional[list] = None,
        agent_persona: Optional[str] = None,
    ):
        self._agent_id = agent_id
        self._repository = agent_repository
        self._session_id = session_id
        self._session_repository = session_repository
        self.status = AgentStatus.IDLE
        self.plan = None

        # Late-binding digest of the executor's recent memory — feeds the
        # sub-agent delegation tool so nested work starts informed.
        def _parent_context_digest() -> str:
            try:
                memory = getattr(self.executor, "memory", None)
                if memory is None:
                    return ""
                lines: list[str] = []
                for msg in memory.get_messages()[-24:]:
                    content = msg.content
                    if isinstance(content, list):
                        content = "".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    text = (content or "").strip()
                    if text:
                        lines.append(f"{msg.type}: {text[:400]}")
                return "\n".join(lines)
            except Exception:
                return ""

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
        # Protected app-source dir: default = Replit layout; overridable per
        # deployment via SANDBOX_PROTECTED_PATHS so the prompt never lies.
        from app.core.config import get_settings as _get_settings
        _protected = (_get_settings().sandbox_protected_paths or "").split(":")[0].strip() or None
        base_prompt = get_system_prompt(
            user_home=user_home, upload_dir=upload_dir, environment=environment,
            project_instruction=project_instruction,
            protected_workspace=_protected,
            knowledge=knowledge,
            agent_persona=agent_persona,
        )

        # Sub-agent delegation (Manus NestedExecutor): registered AFTER
        # base_prompt exists so the nested executor inherits the exact same
        # sandbox/security contract. One level deep by construction.
        from app.domain.services.tools.delegate import DelegateToolkit
        tools.append(DelegateToolkit(
            sandbox=sandbox,
            browser=browser,
            mcp_tool=mcp_tool,
            search_engine=search_engine,
            agent_id=agent_id,
            agent_repository=agent_repository,
            base_prompt=base_prompt,
            parent_context_provider=_parent_context_digest,
        ))

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

    # ── CHAT_MODE_DISCUSS (Manus discuss mode) ───────────────────
    # Semantic classifier decides whether this message is pure conversation
    # (answer directly, no plan, no tools, no sandbox wait) or agent work.
    # Shared by BOTH engines so parity holds.

    async def _is_discuss(self, entry_status, message: Message, conversation_history: Optional[str]) -> bool:
        """Decide whether this turn runs in discuss mode.

        Only fresh or finished conversations qualify — a message queued while
        a task runs, or an answer to the agent's question, ALWAYS continues
        the agent flow. (IN_QUEUE counts as fresh: it is the pre-run state of
        a first/follow-up message while the task boots.) Attachments/images/
        pre-extracted files force agent mode (they need the executor).
        Failure of the classifier itself degrades to agent mode — never
        crashes, never traps a real task.
        """
        if entry_status not in (SessionStatus.PENDING, SessionStatus.IN_QUEUE, SessionStatus.COMPLETED):
            return False
        if message.attachments or message.vision_images:
            return False
        if "<file name=" in (message.message or ""):
            return False
        from app.domain.services.agents.intent import (
            CHAT_MODE_DISCUSS,
            classify_chat_mode,
        )
        mode, confidence = await classify_chat_mode(message.message, conversation_history)
        logger.info(
            "Agent %s chat-mode: %s (confidence %.2f)",
            self._agent_id, mode, confidence,
        )
        return mode == CHAT_MODE_DISCUSS

    async def _run_discuss(
        self,
        message: Message,
        conversation_history: Optional[str],
        session_title: Optional[str],
    ) -> AsyncGenerator[BaseEvent, None]:
        """Answer directly, streamed — no plan, no executor, no tools.

        The acknowledgement model already answers conversational messages
        completely (warm, direct, grounded in the session transcript), so
        discuss mode simply makes that reply the FINAL answer of the turn
        instead of a preamble to a plan.
        """
        delivered = False
        async for event in self.planner.acknowledge_stream(message, conversation_history):
            if isinstance(event, MessageEvent) and (event.message or "").strip():
                # The authoritative final message of this discuss turn —
                # persisted, replayable, and final (files never attach here).
                yield MessageEvent(
                    role="assistant", message=event.message, is_final=True
                )
                delivered = True
            else:
                yield event
        if not delivered:
            yield MessageEvent(
                role="assistant",
                message=self._fallback_ack_text(None, message.message),
                is_final=True,
            )

        # Sessions still without a title get one (discuss turns can be the
        # first turn of a session — the UI needs a title immediately).
        if not (session_title or "").strip():
            try:
                title = await self.planner.generate_title(message.message)
                if title:
                    yield TitleEvent(title=title)
            except Exception:
                logger.debug("discuss-mode title generation failed", exc_info=True)

    # ── Effort budget scaling (AgentTaskMode standard vs HIGH_EFFORT) ──

    def _effective_step_budget(self, base_steps: int, base_failures: int):
        """Scale the execution budget when the planner judged high effort.

        High-effort tasks (substantial builds, deep research) legitimately
        need more phases and tolerate more failed experiments before
        giving up — the limits stay calibrated for standard tasks.
        """
        if self.plan is not None and getattr(self.plan, "task_mode", None) == "high_effort":
            return base_steps * 2, max(base_failures * 2, base_failures)
        return base_steps, base_failures

    async def run(self, message: Message) -> AsyncGenerator[BaseEvent, None]:

        # Real wall-clock start of THIS run — feeds the execution summary in
        # the final validation gate (never fabricated).
        from datetime import datetime as _dt
        self._run_started_at = _dt.now()

        # Analyze vision images once up-front so every downstream agent
        # receives a consistent, text-enriched message without raw image data.
        message = await self._preprocess_images(message)

        # TODO: move to task runner
        session = await self._session_repository.find_by_id(self._session_id)
        if not session:
            raise ValueError(f"Session {self._session_id} not found")

        # Entry status BEFORE any transition — the discuss-mode classifier
        # must know whether this turn starts fresh / after completion (can
        # discuss) or interrupts ongoing work (always agent mode).
        entry_status = session.status

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

        # Compact transcript of the session's earlier turns — injected into the
        # streamed first reply so conversational follow-ups ("what did we discuss
        # before?") are answered WITH context instead of "I have no history".
        conversation_history = self._build_conversation_digest(session, message)

        # ── CHAT_MODE_DISCUSS fast path (Manus discuss mode) ───────────
        # Pure conversation gets a direct streamed answer and the turn ends
        # here: no plan, no executor, no sandbox dependency. Awaiting the
        # sandbox would otherwise add 1-7 min of latency to a greeting.
        try:
            if await self._is_discuss(entry_status, message, conversation_history):
                logger.info(
                    "Agent %s discuss mode — answering directly without tools",
                    self._agent_id,
                )
                async for event in self._run_discuss(
                    message, conversation_history, session.title
                ):
                    yield event
                yield DoneEvent()
                logger.info(f"Agent {self._agent_id} discuss turn completed")
                return
        except Exception:
            # Classifier problems must never trap a real task — fall through
            # to the normal agent flow.
            logger.warning(
                "Agent %s discuss-mode classification failed — continuing "
                "as agent mode",
                self._agent_id,
                exc_info=True,
            )

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
                # Start planning and the user-facing first reply at the same
                # time — ALWAYS, for every message.  The first reply must not
                # wait for the planner's JSON response; that wait was the main
                # source of the "silent first response" feeling in the chat.
                # There is deliberately NO keyword/verb gate here: a hardcoded
                # word list ("coba", "cek", "bantu", ...) deciding whether the
                # reply starts is a template heuristic that misses phrasings
                # in any language it does not cover.  The reply model itself
                # judges the message: tasks get a one-line acknowledgement,
                # conversational messages get a direct answer (see
                # PlannerAgent._acknowledgement_chunks).
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
                        async for ack_event in self.planner.acknowledge_stream(
                            message, conversation_history
                        ):
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
                # assistant message.  The reply LLM call can fail, stream
                # nothing, or have its text suppressed as malformed JSON — in
                # all those cases the user would otherwise see NO first
                # response before the plan appears.
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
                        yield event
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

                # Emit the plan only after its JSON is complete.  At this point
                # the acknowledgement stream has also ended, so the next event
                # is the plan followed immediately by execution.
                if len(self.plan.steps) == 0:
                    # Simple / conversational query.  When the streamed first
                    # reply already answered (the reply model answers
                    # conversational messages directly), it IS the single
                    # response — emitting plan.message too would duplicate
                    # the bubble.  Only when no reply was delivered does the
                    # planner's message (or the deterministic fallback)
                    # become the answer.
                    yield TitleEvent(title=self.plan.title)
                    if not ack_message_delivered:
                        if self.plan.message:
                            yield MessageEvent(
                                role="assistant", message=self.plan.message, is_final=True
                            )
                        else:
                            # Edge: 0 steps AND empty message — still answer something.
                            yield MessageEvent(
                                role="assistant",
                                message=self._fallback_ack_text(
                                    self.plan.language, message.message
                                ),
                                is_final=True,
                            )
                else:
                    # ── MANDATORY FIRST RESPONSE ────────────────────────────
                    # The user must ALWAYS see an assistant reply before the
                    # plan/step list appears.  The streamed reply now starts
                    # for EVERY message, but it can still fail or deliver
                    # nothing — then reuse the planner's own plan.message —
                    # which was previously wasted in this path — as the first
                    # response.  Only when that is empty too, fall back to a
                    # deterministic line.
                    if not ack_message_delivered:
                        first_response = (self.plan.message or "").strip()
                        if not first_response:
                            first_response = self._fallback_ack_text(
                                self.plan.language, message.message
                            )
                        yield MessageEvent(role="assistant", message=first_response)
                        logger.info(
                            f"Agent {self._agent_id} acknowledgement was not "
                            f"streamed — emitted plan.message as mandatory "
                            f"first response ({len(first_response)} chars)"
                        )
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

                # Guard: max total steps executed — budget scales up when the
                # planner judged this a high-effort task (AgentTaskMode).
                _eff_steps, _eff_failures = self._effective_step_budget(
                    _max_steps, _max_consecutive_failures
                )
                if _steps_executed >= _eff_steps:
                    logger.warning(
                        f"Agent {self._agent_id} reached max_steps={_eff_steps} "
                        f"(mode={getattr(self.plan, 'task_mode', 'standard')}), "
                        "force-moving to SUMMARIZING"
                    )
                    yield MessageEvent(
                        role="assistant",
                        message=(
                            f"Reached the maximum step limit ({_eff_steps}). "
                            "Summarising with the data collected so far."
                        ),
                        is_progress=True,
                    )
                    self.status = AgentStatus.SUMMARIZING
                    continue

                # Guard: consecutive failures (scaled with effort budget)
                if _consecutive_failures >= _eff_failures:
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

                # ── Final validation gate (P0) — same contract as the graph
                # engine (engine parity): runs before the summary, emits one
                # ValidationEvent, never raises, and feeds the facts to the
                # model as context.
                from app.domain.services.agents.validation_gate import (
                    build_gate_file_reader,
                    run_final_validation,
                )

                self._validation_result = None
                try:
                    self._validation_result = await run_final_validation(
                        plan=self.plan,
                        memory_messages=self.executor.memory.get_messages(),
                        read_file=build_gate_file_reader(self.executor),
                        started_at=getattr(self, "_run_started_at", None),
                    )
                    yield ValidationEvent(result=self._validation_result)
                    logger.info(
                        f"Agent {self._agent_id} validation gate overall="
                        f"{self._validation_result.overall} warnings="
                        f"{self._validation_result.warnings}"
                    )
                except Exception as exc:
                    logger.warning(f"Agent {self._agent_id} validation gate skipped: {exc}")

                async for event in self.executor.summarize(
                    step_attachments, current_request=message.message,
                    validation=self._validation_result,
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
                # Validation gate outcome decides the final plan status
                # (engine parity with the graph flow).
                _validation = getattr(self, "_validation_result", None)
                if _validation is not None and _validation.overall == "needs_review":
                    completion_plan.status = ExecutionStatus.COMPLETED_WITH_WARNINGS
                else:
                    completion_plan.status = ExecutionStatus.COMPLETED
                logger.info(
                    f"Agent {self._agent_id} plan completed with status "
                    f"{completion_plan.status}"
                )
                yield PlanEvent(status=PlanStatus.COMPLETED, plan=completion_plan)
                self.status = AgentStatus.IDLE
                break
        yield DoneEvent()
        
        logger.info(f"Agent {self._agent_id} message processing completed")
    
    def is_done(self) -> bool:
        return self.status == AgentStatus.IDLE