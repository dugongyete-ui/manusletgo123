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
        # ── Fallback tool-progress narration state ──────────────────────────
        # Safety net for quiet models: when the model has NOT narrated via
        # message_notify_user for a while, a compact status line keeps the
        # stream alive. When the model narrates on its own, these templates
        # stay completely silent (see _MODEL_NARRATION_SILENCE).
        self._narration_lang: str = "en"
        self._last_narrated_function: Optional[str] = None
        self._last_tool_narration_ts: float = 0.0
        # Monotonic timestamp of the last message_notify_user the MODEL sent
        # (any narration attempt, including duplicates). While the model keeps
        # the user company on its own, the deterministic template narration
        # stays completely silent — templates are a FALLBACK for models that
        # go quiet, never a replacement for the model's own voice.
        self._last_model_narration_ts: float = 0.0
        # Consecutive tool-response rounds without a message_notify_user —
        # drives the narration nudge (see ask_with_messages).
        self._silent_rounds: int = 0
        self._step_narrated_functions: set = set()
        # How many times each function has been narrated so far — drives the
        # template rotation so consecutive steps never repeat the same
        # phrasing (persists ACROSS steps on purpose; per-step dedup is
        # handled separately by _step_narrated_functions).
        self._narration_variants_used: dict = {}

    # ── Deterministic tool-progress narration ──────────────────────────────────
    # Plain, professional status lines derived from the tool itself — no
    # emojis, no raw tool names, no internal jargon (Manus-style narration).
    # Each line tells the user WHAT the agent is doing AND WHY (the purpose
    # behind the action), in natural first-person language, with the concrete
    # detail (command, filename, site). Variants rotate per narration so the
    # stream never sounds like a looped recording.
    _TOOL_NARRATIONS = {
        "en": {
            "info_search_web": [
                "I'm searching the web for information on \"{q}\".",
                "Let me look up \"{q}\" online first.",
                "Starting with a web search for \"{q}\".",
            ],
            "browser_navigate": [
                "I'm opening {q} to gather the information needed.",
                "Let me open {q} to check the source directly.",
                "Moving on to {q} for more complete data.",
            ],
            "browser_view": [
                "I'm reading through the page to pull out the key points.",
                "Let me go over the content so nothing important gets missed.",
                "Checking the page for the details that matter.",
            ],
            "browser_click": [
                "I'm clicking through this section to keep the search going.",
                "Let me open this part for more specific details.",
                "Clicking this element to dig a little deeper.",
            ],
            "file_write": [
                "I'm writing {q}.",
                "Putting the work together into {q}.",
                "Preparing {q} now.",
            ],
            "file_str_replace": [
                "I'm editing {q}.",
                "Updating part of {q}.",
                "Making a small revision to {q}.",
            ],
            "file_read": [
                "I'm reading {q}.",
                "Let me check the contents of {q}.",
                "Opening {q} to see what's inside.",
            ],
            "shell_exec": [
                "I'm running `{q}`.",
                "Executing `{q}` in the terminal.",
                "Running `{q}` now.",
            ],
            "image_search_web": [
                "I'm searching for images related to \"{q}\".",
                "Let me find supporting visuals for \"{q}\".",
                "Looking up pictures for \"{q}\".",
            ],
            "image_download": [
                "I'm downloading that image first.",
                "Saving the selected image.",
                "Downloading the image now.",
            ],
        },
        "id": {
            "info_search_web": [
                "Saya sedang mencari informasi tentang \"{q}\" di web.",
                "Saya cari dulu referensi tentang \"{q}\" lewat pencarian web.",
                "Saya mulai dari pencarian web untuk \"{q}\".",
            ],
            "browser_navigate": [
                "Saya sedang membuka {q} untuk mencari informasi yang dibutuhkan.",
                "Saya buka {q} untuk melihat sumbernya secara langsung.",
                "Saya lanjut ke {q} supaya datanya lebih lengkap.",
            ],
            "browser_view": [
                "Saya sedang membaca isi halamannya untuk mengambil poin-poin penting.",
                "Saya baca dulu isinya supaya detail yang dibutuhkan tidak terlewat.",
                "Saya periksa isi halaman untuk informasi yang relevan.",
            ],
            "browser_click": [
                "Saya mengeklik bagian halaman ini untuk melanjutkan pencarian.",
                "Saya buka bagian ini untuk melihat detail yang lebih spesifik.",
                "Saya klik elemen di halaman untuk mendapatkan data lebih lanjut.",
            ],
            "file_write": [
                "Saya sedang menulis {q}.",
                "Saya susun hasil kerjanya ke {q}.",
                "Saya siapkan {q} sekarang.",
            ],
            "file_str_replace": [
                "Saya sedang menyunting {q}.",
                "Saya perbarui sebagian isi {q}.",
                "Saya revisi sedikit bagian dari {q}.",
            ],
            "file_read": [
                "Saya sedang membaca {q}.",
                "Saya periksa dulu isi {q}.",
                "Saya buka {q} untuk melihat isinya.",
            ],
            "shell_exec": [
                "Saya menjalankan `{q}`.",
                "Saya eksekusi `{q}` di terminal.",
                "Menjalankan `{q}` sekarang.",
            ],
            "image_search_web": [
                "Saya mencari gambar terkait \"{q}\".",
                "Saya cari dulu gambar pendukung untuk \"{q}\".",
                "Mencari visual untuk \"{q}\".",
            ],
            "image_download": [
                "Saya mengunduh gambarnya terlebih dahulu.",
                "Saya simpan dulu gambar yang dipilih.",
                "Mengunduh gambarnya sekarang.",
            ],
        },
    }

    # Minimum seconds between two tool narrations — keeps the stream
    # informative without becoming spammy on tool-heavy steps.
    _TOOL_NARRATION_MIN_INTERVAL = 3.0

    # The deterministic templates only speak when the model has been silent
    # (no message_notify_user) for at least this many seconds. The model's own
    # narration (question before a tool, meaning after the result) is always
    # richer than any template — templates exist so a quiet model never leaves
    # a dead stream, nothing more.
    _MODEL_NARRATION_SILENCE = 45.0

    @staticmethod
    def _narration_arg(event: "ToolEvent") -> str:
        """Extract a short human-readable argument from a tool call."""
        args = event.function_args or {}
        if event.function_name == "browser_navigate":
            url = str(args.get("url", "")).strip()
            try:
                from urllib.parse import urlparse
                host = urlparse(url).hostname or url
                return host
            except Exception:
                return url
        for key in ("query", "file", "cmd", "command"):
            val = str(args.get(key, "")).strip()
            if val:
                if key == "file":
                    val = val.rstrip("/").split("/")[-1]
                if key in ("cmd", "command"):
                    # First line of the command only — heredocs and long
                    # pipelines get truncated, the user just needs the gist.
                    val = val.splitlines()[0] if val else val
                return val[:48] + ("…" if len(val) > 48 else "")
        return ""

    def _tool_progress_narration(self, event: "ToolEvent") -> Optional[str]:
        """Fallback one-line status for a completed tool call.

        ONLY speaks when the model itself has not narrated
        (message_notify_user) for _MODEL_NARRATION_SILENCE seconds. The model's
        own narration is contextual (what it wants to know, what a result
        means) — whenever it is present, templates add nothing but noise, so
        they stay silent.

        When the fallback IS active (quiet model), it narrates the CURRENT
        kind of work (search → browse → read → write → shell…), throttled to
        at most one line per _TOOL_NARRATION_MIN_INTERVAL seconds so rapid
        tool bursts stay quiet. Exceptions: each DISTINCT shell command gets
        its own line (that is what the user actually watches), and each
        DISTINCT site navigated to gets its own line, still throttled.
        Template variants rotate per function so consecutive steps never
        repeat the same phrasing.
        """
        import time as _time

        fn = event.function_name
        table = self._TOOL_NARRATIONS.get(
            self._narration_lang, self._TOOL_NARRATIONS["en"]
        )
        if fn not in table:
            return None
        now = _time.monotonic()
        # Model is actively keeping the user company — templates stay quiet.
        if now - self._last_model_narration_ts < self._MODEL_NARRATION_SILENCE:
            return None
        # Dedup key: shell commands dedupe per-command, navigation dedupes
        # per-site (a new site is a newsworthy action), everything else per
        # kind of work — one "membuka wikipedia.org" is enough per step.
        arg = self._narration_arg(event) or ""
        if fn in ("shell_exec", "browser_navigate"):
            dedup_key = f"{fn}:{arg}"
        else:
            dedup_key = fn
        # Already narrated this exact line of work in this step — stay quiet.
        if dedup_key in self._step_narrated_functions:
            return None
        # First narration of the step always goes out; later ones need a gap.
        if (
            self._step_narrated_functions
            and (now - self._last_tool_narration_ts) < self._TOOL_NARRATION_MIN_INTERVAL
        ):
            return None
        self._step_narrated_functions.add(dedup_key)
        self._last_narrated_function = fn
        self._last_tool_narration_ts = now
        # Rotate variants so the stream never repeats itself verbatim.
        variants = table[fn]
        count = self._narration_variants_used.get(fn, 0)
        self._narration_variants_used[fn] = count + 1
        template = variants[count % len(variants)]
        return template.format(q=arg)

    @staticmethod
    def _normalize_narration(text: str) -> str:
        """Lowercase, strip punctuation and collapse whitespace for comparison."""
        import re as _re
        return _re.sub(r"\s+", " ", _re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()

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

    # ── Narration nudge for silent models ────────────────────────────────────
    # Free-tier models often go straight from tool call to tool call without
    # ever calling message_notify_user — the user then sees a dead chat stream
    # while the tool panel fills up. A short reminder prepended to the tool
    # result (high salience, exactly where the model's attention sits) reliably
    # triggers narration, without the cost of a full correction retry.
    _NUDGE_AFTER_SILENT_ROUNDS = 2
    _NARRATION_NUDGE = (
        "\n\n[SYSTEM REQUIREMENT — NARRATION] Your last responses contained tool "
        "calls but NO message_notify_user call. The user is watching a silent "
        "screen and does not know what you are finding. Your NEXT response MUST "
        "include a message_notify_user call (before or alongside your next tool "
        "call): in the user's language, say what you just found — the actual "
        "finding, not the action — and what you are doing next. Example shape: "
        "\"Dari [sumber], saya menemukan bahwa [temuan konkret]. Selanjutnya "
        "saya [tindakan berikutnya] karena [alasan].\" This is mandatory."
    )

    async def ask_with_messages(self, messages, format=None):
        """Intercept tool-response rounds to nudge silent models into narrating.

        Counts consecutive rounds whose tool responses contain NO
        message_notify_user. After _NUDGE_AFTER_SILENT_ROUNDS silent rounds the
        narration reminder is PREPENDED to the first tool result of the batch
        (primacy — browser results are often tens of KB of page text, so a
        suffix at the end of the last message is invisible to the model). A
        narrated round resets the counter (the nudge never fires while the
        model talks on its own).
        """
        narrated_this_round = False
        for m in messages:
            name = m.get("name") if isinstance(m, dict) else getattr(m, "name", "")
            if name == "message_notify_user":
                narrated_this_round = True
                break
        if narrated_this_round:
            self._silent_rounds = 0
        else:
            self._silent_rounds = getattr(self, "_silent_rounds", 0) + 1
            if self._silent_rounds >= self._NUDGE_AFTER_SILENT_ROUNDS and messages:
                first = messages[0]
                original = (
                    first.get("content") if isinstance(first, dict) else first.content
                ) or ""
                combined = self._NARRATION_NUDGE + "\n\n" + original
                try:
                    if isinstance(first, dict):
                        first["content"] = combined
                    else:
                        first.content = combined
                    self._silent_rounds = 0  # nudge at most once per threshold
                    logger.info(
                        "Model silent for %s rounds — prepended narration nudge "
                        "to tool result", self._NUDGE_AFTER_SILENT_ROUNDS,
                    )
                except Exception:
                    # Message object immutable on this langchain version — skip
                    # the nudge rather than break the tool loop.
                    logger.debug("Could not prepend narration nudge", exc_info=True)
        return await super().ask_with_messages(messages, format)

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
                # Normalize: models occasionally emit the attachments array as
                # a JSON-encoded string or mix junk into the list.
                from app.domain.services.agents.attachment_paths import (
                    normalize_attachment_paths,
                )

                step.attachments = normalize_attachment_paths(new_step.attachments)
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
                        # The model is narrating on its own — from this moment
                        # the deterministic template narration stays silent
                        # for _MODEL_NARRATION_SILENCE seconds. Recorded BEFORE
                        # the duplicate check: even a suppressed duplicate
                        # proves the model is in narration mode.
                        import time as _time
                        self._last_model_narration_ts = _time.monotonic()
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
                        ):
                            logger.info(
                                "Suppressed duplicate progress narration: %s",
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
            # Fallback progress narration: after a non-message tool COMPLETES,
            # emit a short status line ONLY when the model has gone quiet for
            # a while (see _MODEL_NARRATION_SILENCE). When the model narrates
            # on its own, these templates never speak.
            if (
                isinstance(event, ToolEvent)
                and event.status == ToolStatus.CALLED
                and event.tool_name != "message"
            ):
                narration = self._tool_progress_narration(event)
                if narration:
                    yield MessageEvent(
                        role="assistant", message=narration, is_progress=True
                    )

    async def execute_step(
        self, plan: Plan, step: Step, message: Message
    ) -> AsyncGenerator[BaseEvent, None]:
        # Reset per-step deterministic-narration state and pick up the plan
        # language so tool-progress lines are spoken in the user's language.
        self._step_narrated_functions = set()
        self._last_narrated_function = None
        self._silent_rounds = 0
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
        self, step_attachments: Optional[List[str]] = None
    ) -> AsyncGenerator[BaseEvent, None]:
        """Deliver the final result to the user.

        Args:
            step_attachments: final deliverable file paths collected from every
                step's result JSON — delivered ONCE here, with this final
                summary message (never mid-task).
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

        stream_context = context + [LCHumanMessage(content=SUMMARIZE_STREAM_PROMPT)]

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
