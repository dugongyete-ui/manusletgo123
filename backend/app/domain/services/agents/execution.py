from typing import AsyncGenerator, Optional, List
from app.domain.models.plan import Plan, Step, ExecutionStatus
from app.domain.models.file import FileInfo
from app.domain.models.message import Message, VisionImage
from app.domain.services.agents.base import BaseAgent
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.services.prompts.system import SYSTEM_PROMPT
from app.domain.services.prompts.execution import (
    EXECUTION_SYSTEM_PROMPT,
    EXECUTION_PROMPT,
    SUMMARIZE_PROMPT,
    SUMMARIZE_STREAM_PROMPT,
)
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
    Execution agent — responsible for executing a single plan step using tools,
    then summarising the full task result for the user.
    """

    name: str = "execution"
    system_prompt: str = SYSTEM_PROMPT + EXECUTION_SYSTEM_PROMPT
    format: Optional[str] = None

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
        # Sandbox file paths already delivered to the user during execution
        # (via message_notify_user with attachments). Used by summarize() to
        # avoid sending the same file twice — the "double send" bug.
        self._delivered_attachments: List[str] = []

    @staticmethod
    def _counts_as_real_action(event: "ToolEvent") -> bool:
        """Whether a tool CALL counts as a real action for ghost-success detection.

        Any non-message toolkit tool counts. Within the message toolkit,
        ``message_notify_user`` **with attachments** and ``message_ask_user``
        also count: a step whose whole purpose is delivering files or asking
        the user a question legitimately completes with only message-tool
        calls — treating those as "ghost success" re-ran the step and
        re-delivered the same files (double-send bug).
        """
        if event.tool_name != "message":
            return True
        if event.function_name == "message_ask_user":
            return True
        if (
            event.function_name == "message_notify_user"
            and event.function_args.get("attachments")
        ):
            return True
        return False

    def _build_vision_content(self, text: str, images: List[VisionImage]) -> list:
        content = [{"type": "text", "text": text}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.content_type};base64,{img.data}"},
            })
        return content

    async def _handle_execution_events(
        self, step: Step, content
    ) -> AsyncGenerator[BaseEvent, None]:
        async for event in self.execute(content):
            if isinstance(event, ErrorEvent):
                # Tool lookup errors are handled by LLM retry (base.py appends a
                # ToolMessage so the LLM can adapt). Do not fail the step here.
                logger.debug(
                    f"Step {step.id} tool error (LLM will retry): {event.error}"
                )
            elif isinstance(event, MessageEvent):
                step.status = ExecutionStatus.COMPLETED
                parsed_response = await self._parse_json(event.message)

                if parsed_response is None:
                    logger.warning(
                        "Execution agent returned non-JSON response for step result"
                    )
                    step.success = False
                    step.result = event.message or "No result returned."
                    step.error = "LLM returned a non-JSON response."
                    yield StepEvent(status=StepStatus.COMPLETED, step=step)
                    return

                if isinstance(parsed_response, list):
                    logger.warning(
                        "Execution agent returned a list instead of a Step dict — "
                        "salvaging as raw result"
                    )
                    step.success = True
                    step.result = json.dumps(parsed_response, ensure_ascii=False)
                    yield StepEvent(status=StepStatus.COMPLETED, step=step)
                    return

                try:
                    new_step = Step.model_validate(parsed_response)
                except Exception as val_err:
                    logger.warning(
                        f"Step validation failed, salvaging as raw result: {val_err}"
                    )
                    step.success = True
                    step.result = (
                        json.dumps(parsed_response, ensure_ascii=False)
                        if not isinstance(parsed_response, str)
                        else parsed_response
                    )
                    yield StepEvent(status=StepStatus.COMPLETED, step=step)
                    return

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
                elif (
                    event.function_name == "message_notify_user"
                    and event.status == ToolStatus.CALLING
                ):
                    raw_att = event.function_args.get("attachments")
                    if raw_att:
                        att_list = (
                            [raw_att] if isinstance(raw_att, str) else list(raw_att)
                        )
                        att_list = [p for p in att_list if p]
                        # Only deliver files that were NOT already delivered in an
                        # earlier message of this run — re-attaching them here made
                        # the same file appear on multiple chat bubbles (the
                        # "double send" bug).
                        new_paths = [
                            p for p in att_list
                            if p not in self._delivered_attachments
                        ]
                        if new_paths:
                            # Record mid-task deliveries so the final summary
                            # never re-sends the same file (double-send bug).
                            for p in new_paths:
                                if p not in self._delivered_attachments:
                                    self._delivered_attachments.append(p)
                            yield MessageEvent(
                                message=event.function_args.get("text", ""),
                                attachments=[FileInfo(file_path=p) for p in new_paths],
                            )
                            continue
            yield event

    async def execute_step(
        self, plan: Plan, step: Step, message: Message
    ) -> AsyncGenerator[BaseEvent, None]:
        prompt = EXECUTION_PROMPT.format(
            step=step.description,
            message=message.message,
            attachments="\n".join(message.attachments),
            language=plan.language,
        )

        vision_content = None
        if message.vision_images:
            vision_content = self._build_vision_content(prompt, message.vision_images)

        step.status = ExecutionStatus.RUNNING
        yield StepEvent(status=StepStatus.STARTED, step=step)

        content = vision_content if vision_content else prompt
        retry_text_only = False

        # Track whether any real (non-message) tool was called.
        # When the LLM skips all tool calls and fabricates a success JSON
        # ("ghost success"), this stays False so we can retry.
        real_tools_called = False
        # Track whether the LLM sent at least one user-visible narration.
        # If the step fails with no narration the user sees a silent failure.
        narration_sent = False

        try:
            async for event in self._handle_execution_events(step, content):
                if isinstance(event, ToolEvent) and event.status == ToolStatus.CALLING:
                    if self._counts_as_real_action(event):
                        real_tools_called = True
                    if event.function_name == "message_notify_user":
                        narration_sent = True
                yield event
        except Exception as e:
            error_str = str(e).lower()
            if vision_content and (
                "image" in error_str
                or "vision" in error_str
                or "multimodal" in error_str
                or "unsupported" in error_str
                or "invalid request" in error_str
                or "not supported" in error_str
                or "400" in error_str
            ):
                logger.warning(
                    f"Model rejected image content in execute_step, "
                    f"retrying text-only: {e}"
                )
                retry_text_only = True
            else:
                raise

        if retry_text_only:
            logger.info("Retrying execute_step without vision images")
            real_tools_called = False
            narration_sent = False
            async for event in self._handle_execution_events(step, prompt):
                if isinstance(event, ToolEvent) and event.status == ToolStatus.CALLING:
                    if event.tool_name != "message":
                        real_tools_called = True
                    if event.function_name == "message_notify_user":
                        narration_sent = True
                yield event

        # ── Case 1: LLM returned plain text with no tool calls at all ─────────
        # Detected when _parse_json returned None (non-JSON plain text).
        _is_skipped_tools = (
            not retry_text_only
            and not step.success
            and step.status == ExecutionStatus.COMPLETED
            and step.error == "LLM returned a non-JSON response."
        )
        if _is_skipped_tools:
            logger.warning(
                f"Step {step.id} completed with no tool calls (LLM returned plain "
                "text). Retrying once with a correction prompt."
            )
            step.status = ExecutionStatus.RUNNING
            step.result = None
            step.error = None
            step.success = False
            real_tools_called = False
            narration_sent = False

            correction_content = (
                prompt
                + "\n\n[CORRECTION — MANDATORY]: Your previous response was plain text "
                "instead of tool calls. You MUST begin by calling message_notify_user "
                "with your opening narration, then call the required tools one by one. "
                "Do NOT write a text response — call tools first. "
                "Only return the final JSON result after completing all tool calls."
            )
            try:
                async for event in self._handle_execution_events(
                    step, correction_content
                ):
                    if isinstance(event, ToolEvent) and event.status == ToolStatus.CALLING:
                        if self._counts_as_real_action(event):
                            real_tools_called = True
                        if event.function_name == "message_notify_user":
                            narration_sent = True
                    yield event
            except Exception as retry_err:
                logger.error(
                    f"Retry of step {step.id} also raised: {retry_err}"
                )

        # ── Case 2: Ghost success ─────────────────────────────────────────────
        # LLM returned valid JSON {"success": true} but never called any real
        # tool. This happens when accumulated context causes the model to
        # fabricate a completion instead of actually using tools.
        _is_ghost_success = (
            not retry_text_only
            and not _is_skipped_tools
            and step.success
            and step.status == ExecutionStatus.COMPLETED
            and not real_tools_called
        )
        if _is_ghost_success:
            logger.warning(
                f"Step {step.id} reported success but called no real tools "
                "(ghost success — LLM fabricated result). Retrying once."
            )
            step.status = ExecutionStatus.RUNNING
            step.result = None
            step.error = None
            step.success = False
            narration_sent = False

            correction_content = (
                prompt
                + "\n\n[CORRECTION — MANDATORY]: You reported this step as complete "
                "without calling any tools. You MUST actually call the required tools "
                "to complete the task — do NOT fabricate or assume results. "
                "Start by calling message_notify_user to narrate your approach, then "
                "call the tools one by one. "
                "Only return the final JSON result after completing all tool calls."
            )
            try:
                async for event in self._handle_execution_events(
                    step, correction_content
                ):
                    if isinstance(event, ToolEvent) and event.status == ToolStatus.CALLING:
                        if self._counts_as_real_action(event):
                            real_tools_called = True
                        if event.function_name == "message_notify_user":
                            narration_sent = True
                    yield event
            except Exception as retry_err:
                logger.error(
                    f"Ghost-success retry of step {step.id} also raised: {retry_err}"
                )

        # ── Fallback: step failed with no user-visible narration ──────────────
        # If the step ended in failure and the LLM never called
        # message_notify_user, the user sees a failed chip with no explanation.
        # Emit a diagnostic message so there is always actionable context.
        if not step.success and not narration_sent:
            _lang = getattr(plan, "language", "en") or "en"
            _error = (step.error or "").strip()
            _step_desc = (step.description or "").strip()

            if "non-JSON response" in _error:
                _reason_en = (
                    "The AI model produced a plain-text response instead of calling "
                    "the required tools — this usually happens when the conversation "
                    "context becomes very long."
                )
                _reason_id = (
                    "Model AI menghasilkan teks biasa alih-alih memanggil tools — "
                    "ini biasanya terjadi saat konteks percakapan sudah terlalu panjang."
                )
            elif _error:
                _reason_en = f"Recorded error: {_error}"
                _reason_id = f"Error yang tercatat: {_error}"
            else:
                _reason_en = (
                    "The AI model completed the step without calling any tools "
                    "and without providing an explanation."
                )
                _reason_id = (
                    "Model AI menyelesaikan langkah tanpa memanggil tools apapun "
                    "dan tanpa memberikan penjelasan."
                )

            logger.warning(
                f"Step {step.id!r} failed silently (success=False, no narration). "
                f"desc={_step_desc!r} error={_error!r}"
            )

            if _lang == "en":
                _msg = (
                    f"⚠️ **Step could not be completed:** {_step_desc}\n\n"
                    f"**Reason:** {_reason_en}\n\n"
                    "Analysis will continue with the data already collected from other steps."
                )
            else:
                _msg = (
                    f"⚠️ **Langkah tidak dapat diselesaikan:** {_step_desc}\n\n"
                    f"**Alasan:** {_reason_id}\n\n"
                    "Analisis akan dilanjutkan dengan data yang sudah terkumpul dari langkah lain."
                )
            yield MessageEvent(role="assistant", message=_msg)

        step.status = ExecutionStatus.COMPLETED

    def _extract_text_from_json(self, text: str) -> str:
        """
        If the LLM wrapped its streaming response in a JSON object
        (e.g. {"result": "..."} or {"message": "..."}), unwrap and return the
        inner text so the frontend receives clean Markdown, not raw JSON.
        """
        clean = text.strip()
        if clean.startswith("```"):
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", clean)
            if m:
                clean = m.group(1).strip()
        if not clean.startswith("{"):
            return text
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                extracted = parsed.get("result") or parsed.get("message")
                if extracted and isinstance(extracted, str):
                    return extracted
        except (json.JSONDecodeError, ValueError):
            pass
        return text

    async def _decide_and_create_summary_file(
        self,
        summary_text: str,
        context: list,
        existing_attachments: Optional[List[str]] = None,
    ) -> List[FileInfo]:
        """
        Ask the LLM (without modifying memory) whether this task involved
        internet research. If yes, write the summary as a .md file directly
        via the sandbox and return its FileInfo.

        Skipped when the executor already produced a Markdown deliverable
        (e.g. laporan_pengujian.md) — creating a second summary_<topic>.md
        with the same content caused the duplicated-MD complaint.
        """
        from app.domain.services.tools.file import FileToolkit

        file_toolkit = next(
            (tk for tk in self.toolkits if isinstance(tk, FileToolkit)), None
        )
        if not file_toolkit:
            return []

        # If any step already delivered a .md report file, do NOT create
        # another summary .md — the existing report IS the deliverable.
        existing_md = [
            p for p in (existing_attachments or [])
            if isinstance(p, str) and p.strip().lower().endswith(".md")
        ]
        if existing_md:
            logger.info(
                "Summary .md skipped — task already produced a Markdown deliverable: %s",
                existing_md,
            )
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

            sandbox_home = getattr(
                file_toolkit.sandbox, "_sandbox_home", "/home/runner"
            )
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

    async def summarize(
        self, step_attachments: Optional[List[str]] = None
    ) -> AsyncGenerator[BaseEvent, None]:
        """Deliver the final result to the user.

        Args:
            step_attachments: final deliverable file paths collected from every
                step's result JSON. Used (a) to skip creating a duplicate
                summary .md when a report already exists, and (b) to filter out
                files that were already delivered mid-task via
                message_notify_user so nothing is sent twice.
        """
        await self._ensure_memory()
        context = list(self.memory.get_messages())

        stream_context = context + [LCHumanMessage(content=SUMMARIZE_STREAM_PROMPT)]

        full_text = ""
        try:
            async for chunk in self._model.astream(stream_context):
                token = chunk.content if isinstance(chunk.content, str) else ""
                if token:
                    full_text += token

            if full_text:
                clean_text = self._extract_text_from_json(full_text)
                # Emit in small chunks for a smooth progressive typing effect
                _CHUNK = 5
                for _i in range(0, len(clean_text), _CHUNK):
                    yield MessageChunkEvent(
                        content=clean_text[_i : _i + _CHUNK], done=False
                    )
                yield MessageChunkEvent(content="", done=True)

                # Let the LLM decide whether a .md summary file is appropriate
                # (skipped automatically when a report .md already exists).
                attachments = await self._decide_and_create_summary_file(
                    clean_text, context, existing_attachments=step_attachments
                )
                # Deliver step deliverables that were NOT already sent mid-task.
                already_delivered = set(self._delivered_attachments)
                for p in step_attachments or []:
                    if p and p not in already_delivered:
                        already_delivered.add(p)
                        attachments.append(FileInfo(file_path=p))
                yield MessageEvent(
                    message=clean_text,
                    attachments=attachments if attachments else None,
                )
            return

        except Exception as e:
            logger.warning(
                f"Streaming summarize failed, falling back to JSON mode: {e}"
            )

        # Fallback: JSON-based summarize
        already_delivered = list(self._delivered_attachments)
        async for event in self.execute(SUMMARIZE_PROMPT):
            if isinstance(event, MessageEvent):
                logger.debug(f"Execution agent summary: {event.message}")
                parsed_response = await self._parse_json(event.message)
                if parsed_response is None:
                    logger.warning(
                        "Summarize fallback returned non-JSON, using raw message"
                    )
                    yield MessageEvent(message=event.message)
                    continue
                msg_obj = Message.model_validate(parsed_response)
                # Filter out anything already delivered mid-task so the user
                # never receives the same file twice.
                attachment_paths = [
                    fp for fp in msg_obj.attachments
                    if fp and fp not in already_delivered
                ]
                attachments = [FileInfo(file_path=fp) for fp in attachment_paths]
                yield MessageEvent(message=msg_obj.message, attachments=attachments)
                continue
            yield event
