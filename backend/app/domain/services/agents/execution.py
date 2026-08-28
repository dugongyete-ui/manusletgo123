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
        # Sandbox file paths the user still needs to receive. Deferred from
        # mid-task message_notify_user calls (files are ONLY delivered with the
        # final summary — never mid-task, Manus-style) and consumed by
        # summarize() so nothing is lost and nothing is sent twice.
        self._deferred_attachments: List[str] = []
        # Last narration text sent via message_notify_user — used to suppress
        # near-duplicate progress messages (the model sometimes re-announces
        # the same intent with slightly different wording).
        self._last_narration_norm: Optional[str] = None
        # tool_call_ids of notify calls suppressed as duplicates — their
        # completion (CALLED) events are dropped too so the duplicate text
        # can never reach the chat UI through the back door.
        self._suppressed_notify_ids: set = set()
        # Content-word sets of the CURRENT step description and the ORIGINAL
        # user request — narrations that merely re-announce them ("Saya sedang
        # menulis file X" while the step row says "Buat file X") duplicate
        # what the timeline already shows and are suppressed.
        self._current_step_words: Optional[set] = None
        self._user_request_words: Optional[set] = None
    @staticmethod
    def _normalize_narration(text: str) -> str:
        """Lowercase, strip punctuation and collapse whitespace for comparison."""
        import re as _re
        return _re.sub(r"\s+", " ", _re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()

    _STOPWORDS = {
        # Indonesian
        "saya", "aku", "anda", "kita", "akan", "sedang", "telah", "sudah", "sedang",
        "dengan", "untuk", "yang", "ini", "itu", "dari", "ke", "di", "dan", "atau",
        "buat", "membuat", "buatlah", "tolong", "silakan", "lalu", "kemudian", "juga",
        "pada", "adalah", "bisa", "dapat", "agar", "sebuah", "secara", "saat", "sekarang",
        # English
        "i", "me", "my", "the", "a", "an", "to", "of", "for", "and", "or", "in",
        "on", "at", "is", "are", "am", "will", "be", "been", "was", "were", "now",
        "this", "that", "it", "with", "as", "by", "from", "please", "make", "create",
        "then", "also", "so", "can", "could", "just", "about", "into", "up", "out",
    }

    @classmethod
    def _content_words(cls, text: str) -> set:
        """Meaningful lowercase tokens (stopwords + punctuation removed)."""
        norm = cls._normalize_narration(text)
        return {w for w in norm.split() if len(w) > 2 and w not in cls._STOPWORDS}

    def _is_redundant_action_announcement(self, text: str) -> bool:
        """True when a narration ONLY re-announces the current step/request.

        Pattern seen in the wild (and complained about by users): while the
        timeline already shows a step row "Buat file tes_collapse.txt …" and a
        live tool pill, the model sends "Saya sedang menulis tes_collapse.txt"
        — zero new information. Detection: the narration is SHORT (few content
        words) and most of its content words already appear in the current
        step description or the user's request. Substantive findings always
        introduce NEW content words and pass through untouched.
        """
        words = self._content_words(text)
        if not words or len(words) > 8:
            # Long texts carry context of their own — never auto-suppress.
            return False
        step_words = getattr(self, "_current_step_words", None)
        request_words = getattr(self, "_user_request_words", None)
        for reference in (step_words, request_words):
            if not reference:
                continue
            overlap = len(words & reference)
            if overlap and overlap / len(words) >= 0.6:
                return True
        return False

    @classmethod
    def _is_duplicate_narration(cls, text: str, last_norm: Optional[str], threshold: float = 0.7) -> bool:
        """True when `text` is (near-)identical to the previous narration.

        Uses word-token Jaccard similarity: free-tier models occasionally send
        the same progress line twice with small rewording ("Memulai pengujian
        browser: membuka halaman Wikipedia…" followed immediately by "…
        halaman contoh…"). Those read as glitches in the chat stream.
        """
        norm = cls._normalize_narration(text)
        if not norm:
            return True  # empty narration → nothing new to say
        if not last_norm:
            return False
        if norm == last_norm:
            return True
        a = set(norm.split())
        b = set(last_norm.split())
        if not a or not b:
            return False
        jaccard = len(a & b) / len(a | b)
        return jaccard >= threshold

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

    # ── Narration policy ─────────────────────────────────────────────────────
    # The aggressive "narration nudge" (forced message_notify_user after N
    # silent tool rounds) was REMOVED: it forced the model to announce every
    # mechanical action ("Saya sedang menulis X") that the step rows and tool
    # pills ALREADY show in the timeline — producing the redundant, cluttered
    # chat stream users complained about. Official Manus keeps narration
    # model-driven and sparse ("sparingly for meaningful progress"); activity
    # visibility comes from the step list + tool pills + shimmer, not from
    # narrating every action.
    # Ghost-success / plain-text correction rounds: after the initial model
    # round, rerun the step up to this many times with an escalating mandatory
    # tool-usage prompt. A round that STILL returns a fabricated completion
    # after all corrections is marked FAILED — never a false checkmark.
    _GHOST_MAX_CORRECTIONS = 2

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
        # ── Ghost-success gate ─────────────────────────────────────────────
        # Count REAL actions (tools that actually do work) this round. When the
        # model returns a completion JSON with success=True but never called a
        # real tool, the result is FABRICATED ("ghost success"): do NOT emit
        # StepEvent(COMPLETED) — the step must not get a checkmark it did not
        # earn. Instead flag the round so execute_step runs a correction round
        # while the UI honestly keeps the step spinner.
        self._round_needs_correction = None
        real_actions = 0
        async for event in self.execute(content):
            if (
                isinstance(event, ToolEvent)
                and event.status == ToolStatus.CALLING
                and self._counts_as_real_action(event)
            ):
                real_actions += 1
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
                    # Plain-text round: suppress the completed event so
                    # execute_step can retry with a correction prompt — the
                    # user should not see a failed chip that may still recover.
                    self._round_needs_correction = "plain"
                    return

                if isinstance(parsed_response, list):
                    logger.warning(
                        "Execution agent returned a list instead of a Step dict — "
                        "salvaging as raw result"
                    )
                    step.success = True
                    step.result = json.dumps(parsed_response, ensure_ascii=False)
                    if real_actions == 0:
                        self._round_needs_correction = "ghost"
                        return
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
                    if real_actions == 0:
                        self._round_needs_correction = "ghost"
                        return
                    yield StepEvent(status=StepStatus.COMPLETED, step=step)
                    return

                step.success = new_step.success
                step.result = new_step.result
                # Normalize: models occasionally emit the attachments array as
                # a JSON-encoded string or mix junk into the list.
                from app.domain.services.agents.attachment_paths import (
                    normalize_attachment_paths,
                )

                step.attachments = normalize_attachment_paths(new_step.attachments)
                if step.success and real_actions == 0:
                    # success=True with zero real tools = fabricated result.
                    logger.warning(
                        "Ghost success: model reported success with no real tool "
                        "calls (result=%.80s)", str(step.result)[:80],
                    )
                    self._round_needs_correction = "ghost"
                    return
                yield StepEvent(status=StepStatus.COMPLETED, step=step)
                return

            elif isinstance(event, ToolEvent):
                if event.function_name == "message_ask_user":
                    if event.status == ToolStatus.CALLING:
                        # Question → standalone chat message (pauses the task,
                        # waits for the user's answer). It must break out of
                        # the step timeline, hence is_question (NOT progress).
                        yield MessageEvent(
                            message=event.function_args.get("text", ""),
                            is_question=True,
                        )
                    elif event.status == ToolStatus.CALLED:
                        yield WaitEvent()
                        return
                    continue
                elif event.function_name == "message_notify_user":
                    if event.status == ToolStatus.CALLING:
                        raw_att = event.function_args.get("attachments")
                        if raw_att:
                            # Models sometimes emit attachments as a JSON-
                            # encoded string ('["/home/.../x.zip"]') instead of
                            # a real array — normalize so the zip path cannot
                            # turn into one broken blob path.
                            from app.domain.services.agents.attachment_paths import (
                                normalize_attachment_paths,
                            )

                            att_list = normalize_attachment_paths(raw_att)
                            # Files are NEVER delivered mid-task anymore — every
                            # path is deferred and delivered exactly ONCE with
                            # the final summary (user requirement: files created
                            # during the task are sent at the end, in the summary).
                            for p in att_list:
                                if p not in self._deferred_attachments:
                                    self._deferred_attachments.append(p)
                                    logger.info(
                                        "Deferred mid-task attachment to final "
                                        "summary: %s", p,
                                    )
                        # Suppress near-duplicate progress narrations so the
                        # chat stream stays clean and professional.
                        notify_text = (event.function_args.get("text") or "").strip()
                        if self._is_duplicate_narration(
                            notify_text, self._last_narration_norm
                        ) or self._is_redundant_action_announcement(notify_text):
                            logger.info(
                                "Suppressed redundant progress narration: %s",
                                notify_text[:80],
                            )
                            self._suppressed_notify_ids.add(event.tool_call_id)
                            continue
                        self._last_narration_norm = self._normalize_narration(
                            notify_text
                        )
                    elif (
                        event.status == ToolStatus.CALLED
                        and event.tool_call_id in self._suppressed_notify_ids
                    ):
                        # The matching CALLING event was suppressed as a
                        # duplicate — drop its completion event too, otherwise
                        # the frontend would still render the duplicate text.
                        self._suppressed_notify_ids.discard(event.tool_call_id)
                        continue
                    # The notify ToolEvent itself streams to the frontend and is
                    # rendered as a plain chat bubble (ToolUse.vue renders
                    # tool.args.text for the message toolkit) — no MessageEvent
                    # needed, so files can never leak into a mid-task bubble.
                    yield event
                    continue
            # ErrorEvents (logged above) and all non-message ToolEvents
            # (file/shell/browser/…) pass through unchanged.
            yield event

    def _correction_prompt(self, reason: str, round_no: int) -> str:
        """Escalating correction appended to the step prompt on retry rounds.

        ``reason`` is either ``"ghost"`` (model fabricated success without
        calling tools) or ``"plain"`` (model answered in plain text instead
        of calling tools). The final round adds an explicit warning that a
        repeat offense fails the step.
        """
        if reason == "ghost":
            base = (
                "\n\n[CORRECTION — MANDATORY]: Your previous response reported "
                "this step as complete WITHOUT calling any tools. That result "
                "was fabricated and has been DISCARDED. You MUST actually call "
                "the required tools now (file, shell, browser, or search tools "
                "as the step requires) to do the real work. Call the tools one "
                "by one. Only after the tools have produced real results may "
                "you return the final JSON result."
            )
        else:
            base = (
                "\n\n[CORRECTION — MANDATORY]: Your previous response was plain "
                "text instead of tool calls. You MUST call the required tools "
                "one by one to do the real work. Do NOT write a text response — "
                "call tools first. Only return the final JSON result after "
                "completing all tool calls."
            )
        if round_no >= self._GHOST_MAX_CORRECTIONS:
            base += (
                " This is your FINAL attempt: if you return a result without "
                "calling the tools, the step will be marked as FAILED."
            )
        return base

    async def execute_step(
        self, plan: Plan, step: Step, message: Message
    ) -> AsyncGenerator[BaseEvent, None]:
        # Context for redundant-narration suppression: a short line that only
        # re-announces the step description or the user's request carries zero
        # new information (the timeline already shows both) — it is dropped.
        self._current_step_words = self._content_words(step.description or "")
        self._user_request_words = self._content_words(message.message or "")
        _lang = (getattr(plan, "language", None) or "").lower()
        self._narration_lang = "id" if _lang.startswith("id") or "indonesia" in _lang or "bahasa" in _lang else "en"

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

        # Track whether the LLM sent at least one user-visible narration.
        # If the step fails with no narration the user sees a silent failure.
        narration_sent = False

        async def _run_round(round_content):
            """Consume one model round, tracking narration along the way."""
            nonlocal narration_sent
            async for event in self._handle_execution_events(step, round_content):
                if (
                    isinstance(event, ToolEvent)
                    and event.status == ToolStatus.CALLING
                    and event.function_name == "message_notify_user"
                ):
                    narration_sent = True
                yield event

        try:
            async for event in _run_round(content):
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
            narration_sent = False
            async for event in _run_round(prompt):
                yield event

        # ── Correction loop: ghost success / plain-text rounds ──────────────
        # _handle_execution_events suppresses the completed event for rounds
        # that ended in a fabricated completion ("ghost") or plain text
        # ("plain") and flags them here. Rerun such rounds with an escalating
        # mandatory tool-usage correction — the step keeps its RUNNING spinner
        # in the UI the whole time (no false checkmark), and the tools of the
        # correction round stream into the step's timeline where they belong.
        for _round_no in range(1, self._GHOST_MAX_CORRECTIONS + 1):
            _reason = getattr(self, "_round_needs_correction", None)
            if _reason is None:
                break
            logger.warning(
                f"Step {step.id} round {_round_no}/{self._GHOST_MAX_CORRECTIONS} "
                f"ended in a {_reason} response — rerunning with mandatory "
                "tool usage."
            )
            # The previous round never really finished: rewind the step so a
            # later completion event reflects the REAL outcome only.
            step.status = ExecutionStatus.RUNNING
            step.result = None
            step.error = None
            step.success = False
            narration_sent = False
            self._round_needs_correction = None

            try:
                async for event in _run_round(
                    prompt + self._correction_prompt(_reason, _round_no)
                ):
                    yield event
            except Exception as retry_err:
                logger.error(
                    f"Correction round {_round_no} of step {step.id} raised: "
                    f"{retry_err}"
                )
                break

        # ── Persistent ghost/plain after all correction rounds ──────────────
        # The model refused to do real work even after the escalating
        # corrections. Mark the step FAILED — an honest failure chip beats a
        # false checkmark — and emit the completed event that was withheld.
        if getattr(self, "_round_needs_correction", None) is not None:
            _reason = self._round_needs_correction
            self._round_needs_correction = None
            step.status = ExecutionStatus.COMPLETED
            step.success = False
            if _reason == "ghost":
                step.error = "Model reported success without executing any tools."
            else:
                step.error = step.error or "LLM returned a non-JSON response."
            logger.error(
                f"Step {step.id} still {_reason} after "
                f"{self._GHOST_MAX_CORRECTIONS} correction rounds — marking the "
                "step FAILED (no false completion)."
            )
            yield StepEvent(status=StepStatus.COMPLETED, step=step)

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
            elif "without executing any tools" in _error:
                _reason_en = (
                    "The AI model claimed the step was complete without actually "
                    "running any tools (fabricated result). The step is marked "
                    "failed so the plan continues with real data only."
                )
                _reason_id = (
                    "Model AI mengklaim langkah selesai tanpa benar-benar menjalankan "
                    "tools (hasil fabrikasi). Langkah ditandai gagal supaya rencana "
                    "hanya melanjutkan dengan data nyata."
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
                    f"**Step could not be completed:** {_step_desc}\n\n"
                    f"**Reason:** {_reason_en}\n\n"
                    "Analysis will continue with the data already collected from other steps."
                )
            else:
                _msg = (
                    f"**Langkah tidak dapat diselesaikan:** {_step_desc}\n\n"
                    f"**Alasan:** {_reason_id}\n\n"
                    "Analisis akan dilanjutkan dengan data yang sudah terkumpul dari langkah lain."
                )
            yield MessageEvent(role="assistant", message=_msg, is_progress=True)

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

            # Write into the USER's isolated home (user_home on
            # UserScopedSandbox), NOT a hard-coded /home/runner — files
            # outside the user home cannot be synced back to storage, so the
            # summary .md would silently never reach the user (observed:
            # file_write "succeeded" per log, file_download 404 afterwards).
            sandbox_home = getattr(
                file_toolkit.sandbox, "user_home", "/home/runner"
            )
            sandbox_path = f"{sandbox_home}/{filename}"

            write_result = await file_toolkit.sandbox.file_write(
                file=sandbox_path,
                content=summary_text,
                append=False,
                leading_newline=False,
                trailing_newline=True,
                sudo=False,
            )
            if not (write_result and getattr(write_result, "success", False)):
                logger.warning(
                    "Summary .md write FAILED at %s: %s",
                    sandbox_path,
                    getattr(write_result, "message", None) or "unknown error",
                )
                return []
            logger.info("Research summary .md saved: %s", sandbox_path)
            return [FileInfo(file_path=sandbox_path)]

        except Exception as exc:
            logger.warning("Could not create summary .md file: %s", exc)
            return []

    async def _drop_zip_member_attachments(
        self, attachments: List[FileInfo]
    ) -> List[FileInfo]:
        """ZIP-only delivery safety net for the model's own attachment list.

        When a .zip deliverable is present, drop the sibling attachments that
        are already bundled inside the archive — the user receives only the
        zip. See agents.zip_delivery for the matching rules; the AgentTaskRunner
        applies the same filter to its artifact-sweep merge, so both delivery
        paths stay ZIP-only.
        """
        zip_paths = [
            a.file_path
            for a in attachments
            if a.file_path and a.file_path.lower().endswith(".zip")
        ]
        if not zip_paths:
            return attachments

        from app.domain.services.agents.zip_delivery import (
            drop_zip_member_attachments,
        )
        from app.domain.services.tools.file import FileToolkit

        file_toolkit = next(
            (tk for tk in self.toolkits if isinstance(tk, FileToolkit)), None
        )
        if not file_toolkit:
            return attachments
        return await drop_zip_member_attachments(
            file_toolkit.sandbox, attachments
        )

    async def summarize(
        self, step_attachments: Optional[List[str]] = None,
        current_request: Optional[str] = None,
    ) -> AsyncGenerator[BaseEvent, None]:
        """Deliver the final result to the user.

        Args:
            step_attachments: final deliverable file paths collected from every
                step's result JSON — delivered ONCE here, with this final
                summary message (never mid-task).
            current_request: the user's request for THIS run. Session memory
                accumulates across tasks; without explicit scoping the model
                sometimes summarizes an EARLIER task from the same session.
        """
        from app.domain.services.agents.attachment_paths import (
            normalize_attachment_paths,
        )

        # Normalize both model-facing inputs: step JSON attachments and
        # deferred notify attachments can carry JSON-string junk.
        step_attachments = normalize_attachment_paths(step_attachments)
        self._deferred_attachments = normalize_attachment_paths(
            self._deferred_attachments
        )
        await self._ensure_memory()
        context = list(self.memory.get_messages())

        # Scope the summary to the CURRENT request: execution memory keeps
        # every task of the session, and without this instruction the model
        # can drift into summarizing an earlier exchange instead.
        if current_request:
            scope_note = (
                f"\n\n[IMPORTANT] The user's CURRENT request (the one you must "
                f"answer now) is:\n{current_request}\nSummarize ONLY the work "
                "and findings from THIS request — the most recent exchanges in "
                "the conversation. Ignore earlier tasks from this session "
                "except where they directly affect the current result."
            )
            stream_prompt = SUMMARIZE_STREAM_PROMPT + scope_note
        else:
            stream_prompt = SUMMARIZE_STREAM_PROMPT
        stream_context = context + [LCHumanMessage(content=stream_prompt)]

        full_text = ""
        try:
            # Streams with automatic fallback-provider switch when the primary
            # key is exhausted (auth/limit errors fail before any chunk).
            full_text = await self.astream_text_with_fallback(stream_context)

            if full_text:
                clean_text = self._extract_text_from_json(full_text)
                # NOTE: the summary is delivered as ONE atomic MessageEvent —
                # no MessageChunkEvent "fake typing" replay.  Chunk events are
                # transient (never persisted to session history), so a client
                # that refreshes mid-summary would replay every chunk already
                # emitted and the whole summary re-typed from scratch.  A single
                # authoritative MessageEvent is idempotent under replay: the
                # refreshed page shows the summary exactly once.

                # Let the LLM decide whether a .md summary file is appropriate
                # (skipped automatically when a report .md already exists).
                attachments = await self._decide_and_create_summary_file(
                    clean_text, context, existing_attachments=step_attachments
                )
                # Deliver every deliverable from this task exactly once, here,
                # with the final summary: the step JSON attachments plus any
                # files deferred from mid-task notifications.
                already_listed = {
                    a.file_path for a in attachments if a.file_path
                }
                for p in list(step_attachments or []) + list(
                    self._deferred_attachments
                ):
                    if p and p not in already_listed:
                        already_listed.add(p)
                        attachments.append(FileInfo(file_path=p))
                # ZIP-only delivery: when an archive is among the deliverables,
                # drop the individual files already bundled inside it.
                attachments = await self._drop_zip_member_attachments(attachments)
                yield MessageEvent(
                    message=clean_text,
                    attachments=attachments if attachments else None,
                    is_final=True,
                )
            return

        except Exception as e:
            logger.warning(
                f"Streaming summarize failed, falling back to JSON mode: {e}"
            )

        # Fallback: JSON-based summarize
        async for event in self.execute(SUMMARIZE_PROMPT):
            if isinstance(event, MessageEvent):
                logger.debug(f"Execution agent summary: {event.message}")
                parsed_response = await self._parse_json(event.message)
                if parsed_response is None:
                    logger.warning(
                        "Summarize fallback returned non-JSON, using raw message"
                    )
                    yield MessageEvent(message=event.message, is_final=True)
                    continue
                msg_obj = Message.model_validate(parsed_response)
                # Collect every deliverable exactly once, deduplicated:
                # the model's own attachments + step deliverables + files
                # deferred from mid-task notifications.
                paths: List[str] = []
                for fp in list(
                    normalize_attachment_paths(msg_obj.attachments)
                ) + list(step_attachments or []) + list(
                    self._deferred_attachments
                ):
                    if fp and fp not in paths:
                        paths.append(fp)
                attachments = [FileInfo(file_path=fp) for fp in paths]
                # ZIP-only delivery: when an archive is among the deliverables,
                # drop the individual files already bundled inside it.
                attachments = await self._drop_zip_member_attachments(attachments)
                yield MessageEvent(
                    message=msg_obj.message,
                    attachments=attachments if attachments else None,
                    is_final=True,
                )
                continue
            yield event
