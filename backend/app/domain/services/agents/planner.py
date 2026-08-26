from typing import Dict, Any, List, AsyncGenerator, Optional
import json
import logging
from app.domain.models.plan import Plan, Step
from app.domain.models.message import Message, VisionImage
from app.domain.services.agents.base import BaseAgent
from app.domain.models.memory import Memory
from app.domain.services.prompts.system import SYSTEM_PROMPT
from app.domain.services.prompts.planner import (
    CREATE_PLAN_PROMPT, 
    UPDATE_PLAN_PROMPT,
    PLANNER_SYSTEM_PROMPT
)
from app.domain.models.event import (
    BaseEvent,
    PlanEvent,
    PlanStatus,
    ErrorEvent,
    MessageEvent,
    MessageChunkEvent,
    DoneEvent,
)
from langchain.messages import HumanMessage as LCHumanMessage
from langchain.messages import SystemMessage as LCSystemMessage
import httpx
from langchain.chat_models import init_chat_model
from app.core.config import get_settings
from app.domain.external.sandbox import Sandbox
from app.domain.services.tools.base import BaseToolkit
from app.domain.services.tools.file import FileToolkit
from app.domain.services.tools.shell import ShellToolkit
from app.domain.repositories.agent_repository import AgentRepository

logger = logging.getLogger(__name__)

class PlannerAgent(BaseAgent):
    """
    Planner agent class, defining the basic behavior of planning
    """

    name: str = "planner"
    system_prompt: str = SYSTEM_PROMPT + PLANNER_SYSTEM_PROMPT
    format: Optional[str] = "json_object"
    tool_choice: Optional[str] = "none"

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        tools: List[BaseToolkit],
    ):
        super().__init__(
            agent_id=agent_id,
            agent_repository=agent_repository,
            tools=tools,
        )

        # Initialize a dedicated vision model if configured, otherwise None.
        # When None we try the main model directly (works for GPT-4o etc.).
        settings = get_settings()
        self._vision_model = None
        if settings.vision_model_name:
            try:
                provider = settings.vision_model_provider or settings.model_provider
                kwargs = dict(
                    model=settings.vision_model_name,
                    model_provider=provider,
                    temperature=settings.temperature,
                    base_url=settings.vision_api_base or settings.api_base,
                )
                # Pass the vision-specific API key explicitly so it is not
                # confused with the main model's key.
                if settings.vision_api_key:
                    # LangChain's init_chat_model forwards kwargs to the
                    # underlying ChatModel constructor.  For the "openai"
                    # provider (incl. OpenAI-compat endpoints like Cohere)
                    # the accepted parameter is openai_api_key.
                    if provider in ("openai",):
                        kwargs["openai_api_key"] = settings.vision_api_key
                    else:
                        # Generic fallback — works for some providers
                        kwargs["api_key"] = settings.vision_api_key
                if settings.extra_headers:
                    kwargs["default_headers"] = settings.extra_headers
                vision_base = settings.vision_api_base or settings.api_base
                if vision_base:
                    verify = settings.ssl_verify
                    kwargs["http_client"] = httpx.Client(verify=verify)
                    kwargs["http_async_client"] = httpx.AsyncClient(verify=verify)
                self._vision_model = init_chat_model(**kwargs)
                logger.info(
                    f"Vision model initialised: {settings.vision_model_name} "
                    f"(provider={provider}, base_url={kwargs.get('base_url')})"
                )
            except Exception as e:
                logger.warning(f"Failed to initialise vision model, falling back to main model: {e}")

    def _build_vision_content(self, text: str, images: List[VisionImage]) -> list:
        """Build a multimodal message content list with text + images."""
        content = [{"type": "text", "text": text}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.content_type};base64,{img.data}"}
            })
        return content

    @staticmethod
    def _clean_acknowledgement(text: str) -> str:
        """Return only natural-language acknowledgement text.

        Planning responses are structured JSON, but acknowledgements are user-facing
        prose.  Some providers follow the planner's cached system instructions even
        when asked for a short acknowledgement, so never pass a JSON-shaped response
        through to the chat renderer.
        """
        cleaned = text.strip()
        if not cleaned:
            return ""

        candidate = cleaned
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if len(lines) >= 3 and lines[-1].strip().startswith("```"):
                candidate = "\n".join(lines[1:-1]).strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            # A truncated JSON object is especially harmful here: it looks like a
            # broken assistant answer and can be persisted in session history.
            if candidate.startswith(("{", "[")):
                logger.warning("Suppressing malformed JSON acknowledgement from planner")
                return ""
            return cleaned

        if isinstance(parsed, dict):
            for key in ("message", "response", "text"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        logger.warning("Suppressing structured acknowledgement from planner")
        return ""

    async def _analyze_images(self, images: List[VisionImage], context: str) -> str:
        """Use the dedicated vision model to describe images as text.

        Images are sent ONE PER REQUEST: many vision endpoints (NVIDIA NIM
        llama-3.2-vision, some OpenRouter models) accept at most one image per
        call — batching them fails the whole analysis with
        'At most 1 image(s) may be provided in one prompt'.
        """
        descriptions = []
        for idx, image in enumerate(images, 1):
            prompt = (
                f"The user sent {len(images)} image(s) as part of this request: {context}\n"
                f"This is image {idx} of {len(images)}. "
                "Describe it in detail. Focus on what is visually present, "
                "any text visible, the overall content, and anything relevant "
                "to the user's request."
            )
            content = self._build_vision_content(prompt, [image])
            try:
                response = await self._vision_model.ainvoke([LCHumanMessage(content=content)])
                text = response.content if isinstance(response.content, str) else ""
                if text.strip():
                    descriptions.append(f"[Image {idx}]\n{text.strip()}")
            except Exception as e:
                logger.warning(f"Vision model analysis failed for image {idx}: {e}")
        if not descriptions:
            return ""
        return "\n\n".join(descriptions)

    async def _get_previous_file_names(self) -> list:
        """Scan conversation memory for file names analyzed in previous turns.

        Looks for <file name="..."> patterns in stored HumanMessages so that
        follow-up questions about previously uploaded files can reference them.
        Returns a deduplicated list of file names in order of first appearance.
        """
        import re
        await self._ensure_memory()
        names = []
        seen = set()
        for msg in self.memory.get_messages():
            content = ""
            if hasattr(msg, "content"):
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    content = " ".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in msg.content
                    )
            for n in re.findall(r'<file name="([^"]+)">', content):
                if n not in seen:
                    seen.add(n)
                    names.append(n)
        return names

    async def acknowledge(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        """Stream an acknowledgment in < 1 s before full JSON planning begins.

        Uses an isolated plain-text prompt.  This must not reuse planner memory:
        planner memory contains the JSON planning contract, which can make a model
        stream the plan itself as the acknowledgement.
        """
        import re

        # Collect context clues (files, images) so the AI is aware of what's present.
        # We do NOT prescribe the exact wording — let the model respond naturally.
        context_note = ""

        # Pre-extracted files (<file name="..."> tags in the message text)
        pre_extracted = re.findall(r'<file name="([^"]+)">', message.message)
        if pre_extracted:
            context_note = f"\n[Files available: {', '.join(pre_extracted)}]"
        # Raw sandbox attachments
        elif message.attachments:
            file_names = [a.split("/")[-1] for a in message.attachments if a]
            if file_names:
                context_note = f"\n[Files available: {', '.join(file_names)}]"
        # Vision images only
        elif message.vision_images:
            context_note = "\n[Image(s) attached]"
        # No current file — check prior conversation turns
        else:
            prev_files = await self._get_previous_file_names()
            if prev_files:
                context_note = f"\n[Previously shared files: {', '.join(prev_files)}]"

        prompt = (
            f"{message.message}{context_note}\n\n"
            "Give a short, natural opening reply in the same language as the user. "
            "Just react to what they asked — no rigid format, no lists, no bullet points. "
            "Return plain text only. Do not return JSON, markdown code fences, or a plan."
        )
        try:
            # Do not use self.memory here.  The planner's memory includes
            # PLANNER_SYSTEM_PROMPT, which explicitly requires JSON output.
            context = [
                LCSystemMessage(
                    content=(
                        "You are writing a brief acknowledgement on behalf of an AI "
                        "assistant agent. The agent HAS working tools (browser, shell, "
                        "file operations, web search, image tools, messaging) and will "
                        "use them right after this acknowledgement — the full task is "
                        "already being handled. Never speculate about tools being "
                        "missing, unavailable, or not connected, and never describe "
                        "limitations of the environment. Reply in plain natural "
                        "language only. Never output JSON, code fences, a schema, or "
                        "a step list."
                    )
                ),
                LCHumanMessage(content=prompt),
            ]
            raw_text = ""
            # Streams with automatic fallback-provider switch when the primary
            # key is exhausted (auth/limit errors fail before any chunk).
            raw_text = await self.astream_text_with_fallback(context)

            # Validate before emitting anything so malformed/truncated JSON can
            # never flash in the UI or be saved as a persisted assistant message.
            full_text = self._clean_acknowledgement(raw_text)
            if full_text:
                yield MessageChunkEvent(content=full_text, done=False)
                yield MessageChunkEvent(content="", done=True)
                # Persist the acknowledgment so it survives page refresh.
                # MessageChunkEvent is transient (not saved to DB), so we follow up
                # with a MessageEvent that IS saved.  The frontend replaces the
                # streaming bubble with this rather than creating a duplicate.
                yield MessageEvent(role="assistant", message=full_text)
        except Exception as e:
            logger.warning(f"Acknowledge streaming failed, skipping: {e}")

    def _fallback_plan(self, message: Message) -> Plan:
        """Single-step fallback plan when the planner LLM returns unparseable JSON.

        Routing the task through the executor (instead of crashing with a raw
        pydantic validation error) keeps the task alive — the executor is
        tool-driven and completes the user's request directly.
        """
        snippet = (message.message or "").strip().replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:299].rstrip() + "…"
        return Plan(
            title="Task",
            goal=snippet or "Complete the user's request",
            language=None,
            steps=[Step(
                id="1",
                description=f"Complete the user's request: {snippet}",
            )],
            message=None,
        )

    def _safe_plan(self, parsed_response, message: Message) -> Plan:
        """Validate the parsed planner JSON into a Plan, never raising.

        _parse_json returns None when the LLM output cannot be repaired into
        JSON at all — Plan.model_validate(None) used to crash the whole task
        with 'Input should be a valid dictionary or instance of Plan'.
        """
        if isinstance(parsed_response, dict):
            try:
                plan = Plan.model_validate(parsed_response)
                # Salvage plans whose steps are unusable — an empty steps list
                # with a non-conversational request would answer nothing.
                if not plan.steps and plan.message:
                    return plan  # conversational answer path (0 steps is valid)
                if plan.steps:
                    return plan
                # No steps and no message — fall through to executor routing
            except Exception as val_err:
                logger.warning(f"Plan validation failed, salvaging: {val_err}")
                # Try a permissive rebuild: keep any usable fields
                try:
                    salvage = dict(parsed_response)
                    salvage.setdefault("steps", [])
                    plan = Plan.model_validate(salvage)
                    if plan.steps or plan.message:
                        return plan
                except Exception:
                    pass
        elif parsed_response is not None:
            logger.warning(
                f"Planner JSON parse returned {type(parsed_response).__name__} "
                "instead of dict — using fallback single-step plan"
            )
        else:
            logger.warning(
                "Planner returned unparseable JSON — using fallback single-step plan "
                "so the executor can still complete the task"
            )
        return self._fallback_plan(message)

    async def create_plan(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        # If the current message has no pre-extracted files, check conversation
        # history for files from earlier turns.  Injecting their names helps the
        # planner understand that follow-up questions ("tell me more", "kirim isi
        # nya") refer to those previously analyzed documents.
        prev_files_note = ""
        if "<file name=" not in message.message:
            prev_file_names = await self._get_previous_file_names()
            if prev_file_names:
                prev_files_note = (
                    f"\n\nConversation context — files analyzed earlier in this session "
                    f"(their full content is in your conversation history): "
                    f"{', '.join(prev_file_names)}. "
                    "If the user's request is about any of these files, answer using the "
                    "content already in your memory. Do NOT say there is no file available."
                )
                logger.info(
                    f"Injecting previous file context into create_plan: {prev_file_names}"
                )

        base_prompt = CREATE_PLAN_PROMPT.format(
            message=message.message + prev_files_note,
            attachments="\n".join(message.attachments)
        )

        content = base_prompt

        if message.vision_images:
            if self._vision_model:
                # Dedicated vision model: analyse images separately, inject description as text.
                logger.info("Using dedicated vision model to analyse images")
                description = await self._analyze_images(message.vision_images, message.message)
                if description:
                    content = base_prompt + f"\n\n[Image Analysis]\n{description}"
                # content stays text-only — main model never sees raw images
            else:
                # No dedicated vision model — try passing images directly to the main model.
                # This works for multimodal models like GPT-4o. If it fails we retry text-only.
                content = self._build_vision_content(base_prompt, message.vision_images)

        async def _run(c):
            async for event in self.execute(c):
                yield event

        # First attempt
        failed_with_vision = False
        events_buffer = []
        try:
            async for event in _run(content):
                if isinstance(event, MessageEvent):
                    logger.info(event.message)
                    parsed_response = await self._parse_json(event.message)
                    plan = self._safe_plan(parsed_response, message)
                    yield PlanEvent(status=PlanStatus.CREATED, plan=plan)
                    return
                else:
                    events_buffer.append(event)
                    yield event
        except Exception as e:
            error_str = str(e).lower()
            if message.vision_images and not self._vision_model and (
                "image" in error_str or "vision" in error_str or "multimodal" in error_str
                or "unsupported" in error_str or "invalid request" in error_str
            ):
                logger.warning(f"Main model rejected image content, retrying text-only: {e}")
                failed_with_vision = True
            else:
                raise

        # Fallback: retry without images (text-only)
        if failed_with_vision:
            logger.info("Retrying create_plan without vision images")
            note = (
                "\n\n[Note: The user attached image(s) but the current model does not support "
                "image analysis. Please proceed based on the text request only, "
                "or set VISION_MODEL_NAME to enable image understanding.]"
            )
            fallback_content = base_prompt + note
            async for event in self.execute(fallback_content):
                if isinstance(event, MessageEvent):
                    logger.info(event.message)
                    parsed_response = await self._parse_json(event.message)
                    plan = self._safe_plan(parsed_response, message)
                    yield PlanEvent(status=PlanStatus.CREATED, plan=plan)
                else:
                    yield event

    async def update_plan(self, plan: Plan, step: Step) -> AsyncGenerator[BaseEvent, None]:
        message = UPDATE_PLAN_PROMPT.format(plan=plan.dump_json(), step=step.model_dump_json())
        async for event in self.execute(message):
            if isinstance(event, MessageEvent):
                logger.debug(f"Planner agent update plan: {event.message}")
                parsed_response = await self._parse_json(event.message)
                if not isinstance(parsed_response, dict):
                    # Unparseable update response — keep the current plan as-is
                    # instead of crashing the whole task with a validation error.
                    logger.warning(
                        "update_plan could not parse planner JSON — keeping existing plan"
                    )
                    yield PlanEvent(status=PlanStatus.UPDATED, plan=plan)
                    continue
                try:
                    updated_plan = Plan.model_validate(parsed_response)
                except Exception as val_err:
                    logger.warning(f"update_plan validation failed, keeping existing plan: {val_err}")
                    yield PlanEvent(status=PlanStatus.UPDATED, plan=plan)
                    continue
                new_steps = [Step.model_validate(step) for step in updated_plan.steps]
                
                # Find the index of the first pending step
                first_pending_index = None
                for i, step in enumerate(plan.steps):
                    if not step.is_done():
                        first_pending_index = i
                        break
                
                # If there are pending steps, replace all pending steps
                if first_pending_index is not None:
                    # Keep completed steps
                    updated_steps = plan.steps[:first_pending_index]
                    # Add new steps
                    updated_steps.extend(new_steps)
                    # Update steps in plan
                    plan.steps = updated_steps
                
                yield PlanEvent(status=PlanStatus.UPDATED, plan=plan)
            else:
                yield event
