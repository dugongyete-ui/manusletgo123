from typing import AsyncGenerator, Optional, List
from app.domain.models.plan import Plan, Step, ExecutionStatus
from app.domain.models.file import FileInfo
from app.domain.models.message import Message, VisionImage
from app.domain.services.agents.base import BaseAgent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.services.prompts.system import SYSTEM_PROMPT
from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT, EXECUTION_PROMPT, SUMMARIZE_PROMPT
from app.domain.models.event import (
    BaseEvent,
    StepEvent,
    StepStatus,
    ErrorEvent,
    MessageEvent,
    MessageChunkEvent,
    DoneEvent,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.services.tools.base import BaseToolkit
from langchain.messages import HumanMessage as LCHumanMessage
import json
import logging

logger = logging.getLogger(__name__)


class ExecutionAgent(BaseAgent):
    """
    Execution agent class, defining the basic behavior of execution
    """

    name: str = "execution"
    system_prompt: str = SYSTEM_PROMPT + EXECUTION_SYSTEM_PROMPT
    format: str = "json_object"

    def __init__(
        self,
        agent_id: str,
        agent_repository: AgentRepository,
        tools: List[BaseToolkit],
    ):
        super().__init__(
            agent_id=agent_id,
            agent_repository=agent_repository,
            tools=tools
        )

    def _build_vision_content(self, text: str, images: List[VisionImage]) -> list:
        content = [{"type": "text", "text": text}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.content_type};base64,{img.data}"}
            })
        return content

    async def _handle_execution_events(self, step: Step, content) -> AsyncGenerator[BaseEvent, None]:
        async for event in self.execute(content):
            if isinstance(event, ErrorEvent):
                step.status = ExecutionStatus.FAILED
                step.error = event.error
                yield StepEvent(status=StepStatus.FAILED, step=step)
            elif isinstance(event, MessageEvent):
                step.status = ExecutionStatus.COMPLETED
                parsed_response = await self._parse_json(event.message)
                new_step = Step.model_validate(parsed_response)
                step.success = new_step.success
                step.result = new_step.result
                step.attachments = new_step.attachments
                yield StepEvent(status=StepStatus.COMPLETED, step=step)
                return
            elif isinstance(event, ToolEvent):
                if event.function_name == "message_ask_user":
                    if event.status == ToolStatus.CALLING:
                        yield MessageEvent(message=event.function_args.get("text", ""))
                    elif event.status == ToolStatus.CALLED:
                        yield WaitEvent()
                        return
                    continue
                elif event.function_name == "message_notify_user" and event.status == ToolStatus.CALLING:
                    raw_att = event.function_args.get("attachments")
                    if raw_att:
                        att_list = [raw_att] if isinstance(raw_att, str) else list(raw_att)
                        att_list = [p for p in att_list if p]
                        if att_list:
                            yield MessageEvent(
                                message=event.function_args.get("text", ""),
                                attachments=[FileInfo(file_path=p) for p in att_list],
                            )
                            continue
            yield event

    async def execute_step(self, plan: Plan, step: Step, message: Message) -> AsyncGenerator[BaseEvent, None]:
        prompt = EXECUTION_PROMPT.format(
            step=step.description,
            message=message.message,
            attachments="\n".join(message.attachments),
            language=plan.language
        )

        vision_content = None
        if message.vision_images:
            vision_content = self._build_vision_content(prompt, message.vision_images)

        step.status = ExecutionStatus.RUNNING
        yield StepEvent(status=StepStatus.STARTED, step=step)

        content = vision_content if vision_content else prompt
        retry_text_only = False

        try:
            async for event in self._handle_execution_events(step, content):
                yield event
        except Exception as e:
            error_str = str(e).lower()
            if vision_content and (
                "image" in error_str or "vision" in error_str
                or "multimodal" in error_str or "unsupported" in error_str
                or "invalid request" in error_str or "not supported" in error_str
                or "400" in error_str
            ):
                logger.warning(f"Model rejected image content in execute_step, retrying text-only: {e}")
                retry_text_only = True
            else:
                raise

        if retry_text_only:
            logger.info("Retrying execute_step without vision images")
            async for event in self._handle_execution_events(step, prompt):
                yield event

        step.status = ExecutionStatus.COMPLETED

    async def _decide_and_create_summary_file(
        self,
        summary_text: str,
        context: list,
    ) -> List[FileInfo]:
        """
        Ask the LLM (without modifying memory) whether this task involved
        internet research.  If yes, write the summary as a .md file directly
        via the sandbox and return its FileInfo.  The LLM decides — nothing
        is hardcoded.
        """
        from app.domain.services.tools.file import FileToolkit

        file_toolkit = next(
            (tk for tk in self.toolkits if isinstance(tk, FileToolkit)), None
        )
        if not file_toolkit:
            return []

        DECIDE_PROMPT = (
            "Answer ONLY in compact JSON, no extra text.\n"
            "Was the task you just completed an internet research or information-gathering task "
            "(web browsing, search results, Wikipedia, news articles, any data fetched from online URLs)?\n"
            'If YES: {"research":true,"filename":"summary_<topic>.md"} '
            "— use a short descriptive topic name, ASCII-safe, no spaces, same language root as the task.\n"
            'If NO:  {"research":false,"filename":""}'
        )
        decide_context = context + [LCHumanMessage(content=DECIDE_PROMPT)]

        try:
            response = await self._model.ainvoke(decide_context)
            raw = response.content if isinstance(response.content, str) else ""
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()

            data = json.loads(raw)
            if not data.get("research") or not data.get("filename"):
                logger.debug("Summary file skipped: not a research task")
                return []

            filename = str(data["filename"]).strip().lstrip("/")
            filename = filename.replace("..", "").replace("/", "_")
            if not filename.endswith(".md"):
                filename += ".md"

            sandbox_home = getattr(file_toolkit.sandbox, "_sandbox_home", "/home/runner")
            sandbox_path = f"{sandbox_home}/{filename}"

            await file_toolkit.sandbox.file_write(
                file=sandbox_path,
                content=summary_text,
                append=False,
                leading_newline=False,
                trailing_newline=True,
                sudo=False,
            )
            logger.info("Research summary .md saved: %s", sandbox_path)
            return [FileInfo(file_path=sandbox_path)]

        except Exception as exc:
            logger.warning("Could not create summary .md file: %s", exc)
            return []

    async def summarize(self) -> AsyncGenerator[BaseEvent, None]:
        await self._ensure_memory()
        context = list(self.memory.get_messages())

        # Prompt that asks for a direct plain-text response (no JSON wrapper)
        # so we can stream tokens cleanly to the user.
        STREAM_PROMPT = (
            "Deliver the final result to the user. "
            "Write a comprehensive, detailed response in the same language as the user used. "
            "Use Markdown formatting where helpful. "
            "Do NOT wrap your response in JSON."
        )
        stream_context = context + [LCHumanMessage(content=STREAM_PROMPT)]

        full_text = ""
        try:
            async for chunk in self._model.astream(stream_context):
                token = chunk.content if isinstance(chunk.content, str) else ""
                if token:
                    full_text += token
                    yield MessageChunkEvent(content=token, done=False)
            yield MessageChunkEvent(content="", done=True)
            if full_text:
                # Let the LLM decide (without modifying memory) whether a .md
                # summary file is appropriate for this task.
                attachments = await self._decide_and_create_summary_file(
                    full_text, context
                )
                yield MessageEvent(
                    message=full_text,
                    attachments=attachments if attachments else None,
                )
            return
        except Exception as e:
            logger.warning(f"Streaming summarize failed, falling back to JSON mode: {e}")

        # Fallback: original JSON-based summarize
        message = SUMMARIZE_PROMPT
        async for event in self.execute(message):
            if isinstance(event, MessageEvent):
                logger.debug(f"Execution agent summary: {event.message}")
                parsed_response = await self._parse_json(event.message)
                msg_obj = Message.model_validate(parsed_response)
                attachments = [FileInfo(file_path=file_path) for file_path in msg_obj.attachments]
                yield MessageEvent(message=msg_obj.message, attachments=attachments)
                continue
            yield event
