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
                kwargs = dict(
                    model=settings.vision_model_name,
                    model_provider=settings.vision_model_provider or settings.model_provider,
                    temperature=settings.temperature,
                    base_url=settings.vision_api_base or settings.api_base,
                )
                if settings.extra_headers:
                    kwargs["default_headers"] = settings.extra_headers
                self._vision_model = init_chat_model(**kwargs)
                logger.info(f"Vision model initialised: {settings.vision_model_name}")
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

    async def _analyze_images(self, images: List[VisionImage], context: str) -> str:
        """Use the dedicated vision model to describe images as text."""
        prompt = (
            f"The user sent you these images as part of this request: {context}\n\n"
            "Describe each image in detail. Focus on what is visually present, "
            "any text visible, the overall content, and anything relevant to the user's request."
        )
        content = self._build_vision_content(prompt, images)
        try:
            response = await self._vision_model.ainvoke([LCHumanMessage(content=content)])
            return response.content if isinstance(response.content, str) else ""
        except Exception as e:
            logger.warning(f"Vision model image analysis failed: {e}")
            return ""

    async def acknowledge(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        """Stream an acknowledgment in < 1 s before full JSON planning begins.

        Uses LangChain astream() so the very first token reaches the client as
        soon as the model starts responding — typically well under one second.
        """
        prompt = (
            f"The user sent you this request: {message.message}\n\n"
            "Respond naturally to acknowledge their request before you start working on it. "
            "Use the same language the user used."
        )
        try:
            full_text = ""
            async for chunk in self._model.astream([LCHumanMessage(content=prompt)]):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    full_text += text
                    yield MessageChunkEvent(content=text, done=False)
            if full_text:
                yield MessageChunkEvent(content="", done=True)
        except Exception as e:
            logger.warning(f"Acknowledge streaming failed, skipping: {e}")

    async def create_plan(self, message: Message) -> AsyncGenerator[BaseEvent, None]:
        base_prompt = CREATE_PLAN_PROMPT.format(
            message=message.message,
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
                    plan = Plan.model_validate(parsed_response)
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
                    plan = Plan.model_validate(parsed_response)
                    yield PlanEvent(status=PlanStatus.CREATED, plan=plan)
                else:
                    yield event

    async def update_plan(self, plan: Plan, step: Step) -> AsyncGenerator[BaseEvent, None]:
        message = UPDATE_PLAN_PROMPT.format(plan=plan.dump_json(), step=step.model_dump_json())
        async for event in self.execute(message):
            if isinstance(event, MessageEvent):
                logger.debug(f"Planner agent update plan: {event.message}")
                parsed_response = await self._parse_json(event.message)
                updated_plan = Plan.model_validate(parsed_response)
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
