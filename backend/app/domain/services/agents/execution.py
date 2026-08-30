from typing import AsyncGenerator, Optional, List
from app.domain.models.plan import Plan, Step, ExecutionStatus
from app.domain.models.file import FileInfo
from app.domain.models.message import Message, VisionImage
from app.domain.services.agents.base import BaseAgent, _strip_function_syntax
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
    PlanEvent,
    PlanStatus,
)
from app.domain.services.tools.base import BaseToolkit
from langchain.messages import HumanMessage as LCHumanMessage
import json
import logging
import time

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
        # Content-word sets of the ORIGINAL user request — kept for context;
        # narration suppression is intentionally minimal now (see below).
        self._user_request_words: Optional[set] = None
        # ── LLM-written mid-step narration assist ────────────────────────────
        # Some models (NVIDIA nemotron) never narrate: no message_notify_user,
        # no content alongside tool calls — the chat goes dead-silent mid-task
        # (QA #5). The old template keep-alive ("Pengumpulan informasi berjalan
        # — 5 aksi selesai") was removed after user feedback that counting
        # lines read mechanical ("kaku", "ai selalu berkata begitu").
        # Replacement: when the model has stayed silent for
        # _NARRATION_ASSIST_EVERY completed real tools, ask the LLM to write ONE
        # short aware progress line FROM THE ACTUAL RECENT ACTIVITY (tool briefs
        # + result snippets) — context-aware, never a fixed template, never a
        # count. Model-driven narrations reset the window and always win; the
        # assist is capped per step so it can never flood the chat.
        self._silent_activities: List[str] = []
        self._silent_tool_count: int = 0
        self._narration_assist_count: int = 0
        self._narration_lang: str = "en"
    def _resolve_user_home(self) -> str:
        """Resolve the home directory of the sandbox actually serving this
        session (E2B → /home/user, shared Replit → /home/runner/users/<id>).

        Prompts must never carry a hard-coded provider path — the sandbox
        serving the session is chosen at runtime (and can switch, e.g. when
        the E2B quota runs out and the hybrid factory falls back to Replit).
        Defensive getattr because skeleton agents (tests using __new__) have
        no toolkits attribute at all.
        """
        from app.domain.services.tools.file import FileToolkit

        toolkits = getattr(self, "toolkits", None) or ()
        file_toolkit = next(
            (tk for tk in toolkits if isinstance(tk, FileToolkit)), None
        )
        return getattr(getattr(file_toolkit, "sandbox", None), "user_home", "/home/runner")

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
        """RETIRED filter — always False (kept for API compat with old tests).

        The 2026-08 product direction mandates a notify BEFORE every tool
        execution. Those intent lines legitimately reference the step's own
        content, so the old overlap-based suppression would delete exactly
        the lines the user asked for. Only the near-duplicate check remains
        active in the notify branch.
        """
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
    # PRODUCT DIRECTION (user request, 2026-08-28): the agent MUST narrate
    # BEFORE executing tools — a short aware line stating intent and why,
    # every time — and again after notable findings. The system/execution
    # prompts drive this model-side; base.execute() surfaces the model's own
    # content think-aloud. For models that stay silent anyway (nemotron), the
    # LLM-written narration assist below keeps the chat alive WITHOUT the
    # mechanical counting templates the user rejected. Only the near-DUPLICATE
    # check (same line twice) remains active — a literal repeat is a glitch,
    # never an update.
    _NARRATION_ASSIST_EVERY = 5   # silent completed real tools before an assist line
    _NARRATION_ASSIST_MAX = 3     # max assist lines per step
    # Ghost-success / plain-text correction rounds: after the initial model
    # round, rerun the step up to this many times with an escalating mandatory
    # tool-usage prompt. A round that STILL returns a fabricated completion
    # after all corrections is marked FAILED — never a false checkmark.
    _GHOST_MAX_CORRECTIONS = 2

    def _describe_tool_activity(self, event: ToolEvent) -> str:
        """One compact human-readable line describing a completed tool call.

        Used to give the narration-assist LLM real context: what the agent
        actually did and what came back — not just function names.
        """
        fn = event.function_name or ""
        args = event.function_args or {}
        label = getattr(event, "brief", None) or ""
        if not label:
            if fn in ("info_search_web", "info_search_image", "info_search"):
                label = f"search: {args.get('query', '')}"
            elif fn.startswith("browser_"):
                label = f"browser {fn.replace('browser_', '')} {args.get('url') or ''}"[:90]
            elif fn.startswith("file_"):
                label = f"file {fn.replace('file_', '')}: {args.get('path') or args.get('file_path') or ''}"
            elif fn.startswith("shell_"):
                label = f"shell: {str(args.get('command', ''))[:70]}"
            else:
                label = fn
        result = event.function_result
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False)
            except Exception:
                result = str(result)
        snippet = " ".join((result or "").split())[:140]
        line = f"- {label}".strip()
        if snippet:
            line += f" → {snippet}"
        return line[:240]

    async def _generate_activity_narration(self) -> str:
        """Ask the LLM to write ONE aware progress line from recent activity.

        Never raises: any failure returns "" (silence beats a broken task).
        Memory-free — uses astream_text_with_fallback, not self.ask, so the
        agent's conversation memory stays untouched.
        """
        if not self._silent_activities:
            return ""
        lang = getattr(self, "_narration_lang", "en")
        lang_name = (
            "Indonesian (Bahasa Indonesia)" if lang == "id" else "English"
        )
        activity = "\n".join(self._silent_activities[-8:])
        system = (
            "You write one-line progress updates for an AI agent's chat, in the "
            "same natural voice the agent itself uses. Given the agent's recent "
            "tool activity, write ONE short line that shows AWARENESS of what is "
            "happening — what is being found, read, built, or why the approach "
            "is shifting. Read like a thoughtful colleague, never like a log.\n"
            "HARD RULES: max 180 characters; one or two sentences; do NOT count "
            "actions (never write patterns like 'N aksi' / 'N actions'); do NOT "
            "mention tool or function names; do NOT use quotes or JSON; output "
            f"ONLY the line itself in {lang_name}."
        )
        try:
            text = await self.astream_text_with_fallback(
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Recent activity of the agent:\n{activity}\n\n"
                            "Write the one progress line now."
                        ),
                    },
                ]
            )
        except Exception as exc:
            logger.debug("Narration assist LLM call failed: %s", exc)
            return ""
        if not text:
            return ""
        line = " ".join(str(text).strip().split())
        line = line.strip("\"'`“”‘’ ")
        # Wire-format residue guard (same legacy blocks the execution loop
        # salvages): a progress line that is only a raw tool-call skeleton
        # is not a progress line at all.
        line = _strip_function_syntax(line).strip()
        if not line or line.startswith("{"):
            return ""
        # Refuse lines that violate the spirit (counting actions).
        import re as _re
        if _re.search(r"\b\d+\s*(aksi|actions?|tools?|langkah)\b", line.lower()):
            return ""
        return line[:220]

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
            elif isinstance(event, MessageEvent) and event.is_progress:
                # Content narration emitted by base.execute() BEFORE this
                # round's tool calls — the model "thinking out loud" in the
                # AIMessage content (MiniMax M3 style). Show it as a progress
                # line inside the timeline, with the same near-duplicate
                # suppression as notify-tool narrations.
                _narr = (event.message or "").strip()
                if _narr and not self._is_duplicate_narration(
                    _narr, self._last_narration_norm
                ):
                    self._last_narration_norm = self._normalize_narration(_narr)
                    # The model narrated on its own — reset the narration-assist
                    # window so assisted lines never stack on model updates.
                    self._silent_activities = []
                    self._silent_tool_count = 0
                    yield event
                else:
                    logger.info(
                        "Suppressed duplicate content narration: %s", _narr[:80]
                    )
                continue
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
                        # Suppress only near-DUPLICATE progress narrations
                        # (the same line sent twice). Pre-tool intent lines
                        # pass through untouched — see the narration policy
                        # note above.
                        notify_text = (event.function_args.get("text") or "").strip()
                        if self._is_duplicate_narration(
                            notify_text, self._last_narration_norm
                        ):
                            logger.info(
                                "Suppressed redundant progress narration: %s",
                                notify_text[:80],
                            )
                            self._suppressed_notify_ids.add(event.tool_call_id)
                            continue
                        self._last_narration_norm = self._normalize_narration(
                            notify_text
                        )
                        # The model narrated on its own — reset the narration-
                        # assist window so assisted lines never stack on it.
                        self._silent_activities = []
                        self._silent_tool_count = 0
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
            # ── LLM-written narration assist ─────────────────────────────
            # Fires only for real work tools when the model has stayed SILENT
            # (no notify call, no content narration) for
            # _NARRATION_ASSIST_EVERY completed tools. The line is written by
            # the LLM from the actual recent activity — aware, never a fixed
            # counting template — and capped per step.
            if (
                isinstance(event, ToolEvent)
                and event.status == ToolStatus.CALLED
                and event.tool_name != "message"
                and self._counts_as_real_action(event)
            ):
                self._silent_activities.append(self._describe_tool_activity(event))
                self._silent_tool_count += 1
                if (
                    self._silent_tool_count >= self._NARRATION_ASSIST_EVERY
                    and self._narration_assist_count < self._NARRATION_ASSIST_MAX
                ):
                    _assist = await self._generate_activity_narration()
                    if _assist:
                        self._silent_activities = []
                        self._silent_tool_count = 0
                        self._narration_assist_count += 1
                        logger.info(
                            "Narration assist (%d/%d for this step): %s",
                            self._narration_assist_count,
                            self._NARRATION_ASSIST_MAX,
                            _assist[:80],
                        )
                        yield MessageEvent(
                            role="assistant",
                            message=_assist,
                            is_progress=True,
                        )

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
        # Context kept for potential future heuristics (suppression is
        # intentionally minimal now — pre-tool narrations must pass).
        self._user_request_words = self._content_words(message.message or "")
        _lang = (getattr(plan, "language", None) or "").lower()
        self._narration_lang = (
            "id"
            if _lang.startswith("id") or "indonesia" in _lang or "bahasa" in _lang
            else "en"
        )
        # Fresh narration-assist window for every step: each step earns its
        # own budget of assisted progress lines.
        self._silent_activities = []
        self._silent_tool_count = 0
        self._narration_assist_count = 0

        # Live plan-progress context: while this step runs, a throttled check
        # (see _on_tool_round_end) may mark OTHER steps whose goals were
        # already achieved by the ongoing activity as completed, emitting
        # PlanEvents so the user's plan panel updates in real time instead
        # of freezing until the step boundary.  The executor model often
        # runs ahead of the current step's scope (it sees the user's whole
        # goal in memory); without this the plan lags an entire step behind
        # what the timeline visibly shows (observed live: a 9-minute step
        # covering four phases while the panel stayed at "step 1 of 4").
        self._step_progress = {
            "plan": plan,
            "step": step,
            "started": time.monotonic(),
            "last_check": None,
            "rounds_since_check": 0,
            "checks": 0,
        }

        prompt = EXECUTION_PROMPT.format(
            step=step.description,
            message=message.message,
            attachments="\n".join(message.attachments),
            language=plan.language,
            user_home=self._resolve_user_home(),
        )

        vision_content = None
        if message.vision_images:
            vision_content = self._build_vision_content(prompt, message.vision_images)

        step.status = ExecutionStatus.RUNNING
        yield StepEvent(status=StepStatus.STARTED, step=step)

        try:
            async for event in self._run_step_rounds(plan, step, message, prompt, vision_content):
                yield event
        finally:
            # Always clear the progress context — a stale plan reference
            # must never leak into the next step or the summarize phase.
            self._step_progress = None

    # ── Live plan progress ─────────────────────────────────────────────────
    # Throttling for the mid-step progress check (see _on_tool_round_end):
    # a phase-granular step can legitimately run for many minutes with dozens
    # of tool rounds, and the plan panel must not stay frozen while the
    # timeline visibly advances.  The check is a single cheap memory-free LLM
    # call, so it is capped in both directions: never for young steps, never
    # more often than the interval, and never past the total budget.
    _PROGRESS_MIN_STEP_AGE = 60.0     # seconds before the first check
    _PROGRESS_MIN_INTERVAL = 45.0     # seconds between checks
    _PROGRESS_MIN_ROUNDS = 4          # tool rounds between checks
    _PROGRESS_MAX_CHECKS = 12         # total checks per step (LLM budget)
    _PROGRESS_ACTIVITY_WINDOW = 14    # recent tool results shown to the judge

    async def _on_tool_round_end(self, iteration: int):
        """End-of-round hook (invoked by BaseAgent.execute between rounds).

        Runs the throttled plan-progress check while a step is executing and
        yields a PlanEvent(UPDATED) whenever another step's goal was already
        fully achieved by the ongoing activity.  Never raises — the check is
        strictly best-effort; a failing judge call just means no update.
        """
        ctx = getattr(self, "_step_progress", None)
        if not ctx:
            return
        ctx["rounds_since_check"] += 1
        now = time.monotonic()
        if now - ctx["started"] < self._PROGRESS_MIN_STEP_AGE:
            return
        if ctx["last_check"] is not None and (
            now - ctx["last_check"] < self._PROGRESS_MIN_INTERVAL
        ):
            return
        if ctx["rounds_since_check"] < self._PROGRESS_MIN_ROUNDS:
            return
        if ctx["checks"] >= self._PROGRESS_MAX_CHECKS:
            return
        ctx["last_check"] = now
        ctx["rounds_since_check"] = 0
        ctx["checks"] += 1
        try:
            async for event in self._check_plan_progress(ctx):
                yield event
        except Exception as exc:
            # Best-effort by contract: a judge failure must never disturb
            # the running step.
            logger.debug("Plan progress check failed (ignored): %s", exc)

    async def _check_plan_progress(self, ctx: dict):
        """Ask a cheap judge whether pending steps' goals are already met.

        Mechanism (format-contract only — no task-domain assumptions): the
        judge sees the plan's own step descriptions plus the recent tool
        activity recorded in agent memory, and may mark PENDING steps other
        than the current one as completed.  Mutating the shared Plan instance
        is safe: the orchestrator's get_next_step() skips completed steps and
        update_plan preserves them.
        """
        plan: Plan = ctx["plan"]
        current: Step = ctx["step"]
        pending = [
            s for s in (plan.steps or [])
            if s.id != current.id and not s.is_done()
        ]
        if not pending:
            return

        # Recent tool activity digest from memory (name + result head),
        # newest last — enough signal for the judge without dumping payloads.
        mem = getattr(self, "memory", None)
        activity: List[str] = []
        for msg in reversed(mem.get_messages() if mem else []):
            if msg.type != "tool" or not getattr(msg, "name", None):
                continue
            head = " ".join(str(msg.content).split())[:110]
            activity.append(f"{msg.name}: {head}")
            if len(activity) >= self._PROGRESS_ACTIVITY_WINDOW:
                break
        activity.reverse()
        if not activity:
            return

        steps_desc = "\n".join(
            f"- [{s.id}] ({s.status.value}) {s.description}"
            for s in (plan.steps or [])
        )
        prompt = (
            "You are judging the live progress of a multi-step plan.\n"
            f"Plan steps (id | status | description):\n{steps_desc}\n\n"
            f"Step currently being executed by the agent: [{current.id}].\n\n"
            "Recent tool activity of the agent (oldest first):\n"
            + "\n".join(activity)
            + "\n\nQuestion: which PENDING steps OTHER than the current one "
            "have had their goal FULLY achieved by this activity?\n"
            "Rules: include a step ONLY if the evidence clearly shows its "
            "whole goal is already met; partial progress is NOT completion; "
            "when unsure, exclude the step.\n"
            'Return ONLY compact JSON: {"completed_ids": ["<id>", ...]} '
            '(empty array when none).'
        )
        text = await self.astream_text_with_fallback(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a strict progress judge for an AI agent's "
                        "task plan. Answer only in the requested compact JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Plan progress judge returned non-JSON — ignored")
            return
        ids = data.get("completed_ids") if isinstance(data, dict) else None
        if not isinstance(ids, list):
            return

        changed = False
        for sid in ids:
            for s in pending:
                if str(s.id) == str(sid):
                    s.status = ExecutionStatus.COMPLETED
                    changed = True
                    logger.info(
                        "Live plan progress: step %s goal already met "
                        "during step %s — marking completed",
                        s.id, current.id,
                    )
        if changed:
            yield PlanEvent(status=PlanStatus.UPDATED, plan=plan)

    async def _run_step_rounds(
        self, plan: Plan, step: Step, message: Message, prompt: str, vision_content
    ) -> AsyncGenerator[BaseEvent, None]:
        """Body of execute_step after the StepEvent(STARTED) — separated so the
        progress context is cleared in a finally block around it."""

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
                    isinstance(event, MessageEvent) and event.is_progress
                ) or (
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
        # message_notify_user, emit ONE short clean line so the user is not
        # left wondering. Keep it minimal and friendly — no bold headers, no
        # internal model diagnostics, no step-description echo (the timeline
        # already shows which step it was).
        if not step.success and not narration_sent:
            _lang = getattr(plan, "language", "en") or "en"
            _error = (step.error or "").strip()
            logger.warning(
                f"Step {step.id!r} failed silently (success=False, no narration). "
                f"error={_error!r}"
            )
            if _lang == "en":
                _msg = (
                    "This step could not be fully completed — "
                    "continuing with the data already collected."
                )
            else:
                _msg = (
                    "Langkah ini belum bisa diselesaikan sepenuhnya — "
                    "saya lanjutkan dengan data yang sudah terkumpul."
                )
            yield MessageEvent(role="assistant", message=_msg, is_progress=True)

        # ── Silent-success fallback: keep the user informed mid-task ──────────
        # Free-tier models often finish a whole step without a single
        # message_notify_user, so the chat shows no activity between the
        # opening ack and the final summary (user complaint: "notifikasi
        # user tidak ada"). When the model stayed silent during a SUCCESSFUL
        # multi-step-plan step that produced a result, emit ONE short
        # progress line derived from the step's own result (first 1-2
        # sentences, clamped). Model-driven narrations always win; single-step
        # plans skip this (ack + final summary are enough there).
        if (
            step.success
            and not narration_sent
            and len(getattr(plan, "steps", []) or []) > 1
            and (step.result or "").strip()
        ):
            _progress_line = self._first_sentences(step.result, max_chars=200)
            if _progress_line:
                yield MessageEvent(
                    role="assistant", message=_progress_line, is_progress=True
                )

        step.status = ExecutionStatus.COMPLETED

    @staticmethod
    def _first_sentences(text: str, max_chars: int = 200) -> str:
        """First 1-2 sentences of a step result, clamped for a progress line.

        Used by the silent-success fallback: the derived line must read like
        a natural progress note (what was found/accomplished), never a wall.
        """
        import re as _re

        clean = _re.sub(r"\s+", " ", (text or "").strip())
        if not clean:
            return ""
        sentences = _re.split(r"(?<=[.!?])\s+", clean)
        out = ""
        for sentence in sentences[:2]:
            candidate = f"{out} {sentence}".strip()
            if len(candidate) > max_chars and out:
                break
            out = candidate
            if len(out) >= max_chars:
                break
        if len(out) > max_chars:
            out = out[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        return out

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
            sandbox_home = self._resolve_user_home()
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

            # ── Delivery-quality gate (format-level, not task-level) ──────
            # Two failure modes must NOT reach the chat as the final message:
            #   1. Wire-format leak: the model, coming out of a tool-heavy
            #      context, streams its next tool call as raw text (e.g.
            #      "<function=file_read>...</function>") instead of a summary
            #      — observed live in session 8a54aca5: the final message was
            #      a raw file_read call and the user got NO summary at all.
            #   2. Empty delivery: the stream returned nothing (returns before
            #      any tool_loop fallback, leaving the task without a final
            #      message).
            # Both are detected by FORMAT only: strip the known legacy
            # wire-format blocks (same contract the execution loop salvages,
            # see base._salvage_function_calls) and check whether any
            # user-facing prose survives. Prose + residue -> deliver the
            # prose. No prose -> fall through to the JSON tool-loop fallback,
            # which re-asks the model WITH tools bound: the intended action
            # (e.g. reading the deliverable file) executes properly and the
            # real final answer is produced afterwards.
            clean_text = self._extract_text_from_json(full_text or "")
            user_text = _strip_function_syntax(clean_text).strip()

            if user_text:
                clean_text = user_text
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

            # Wire-format-only or empty stream: do NOT yield garbage and do
            # NOT return silently — drop into the JSON tool-loop fallback
            # below so the model can still deliver a real summary.
            if (full_text or "").strip():
                logger.warning(
                    "Summarize stream leaked raw tool-call wire format "
                    "(%d chars, no user-facing prose) — recovering via "
                    "JSON tool-loop fallback",
                    len(full_text),
                )
            else:
                logger.warning(
                    "Summarize stream delivered no content — recovering "
                    "via JSON tool-loop fallback"
                )

        except Exception as e:
            logger.warning(
                f"Streaming summarize failed, falling back to JSON mode: {e}"
            )

        # Fallback: JSON-based summarize
        # user_home is injected so the prompt names paths in the sandbox that
        # is ACTUALLY serving this session (E2B /home/user vs Replit
        # /home/runner/...) — never a hard-coded provider path.
        async for event in self.execute(
            SUMMARIZE_PROMPT.format(user_home=self._resolve_user_home())
        ):
            if isinstance(event, MessageEvent):
                # Progress narration emitted by the tool loop is NOT a final
                # answer — pass it through as progress only, otherwise a
                # mid-loop line like "reading the deliverable…" would be
                # re-delivered as is_final and the real summary that follows
                # would become a duplicate final bubble.
                if event.is_progress:
                    yield event
                    continue
                logger.debug(f"Execution agent summary: {event.message}")
                parsed_response = await self._parse_json(event.message)
                if parsed_response is None:
                    logger.warning(
                        "Summarize fallback returned non-JSON, using raw message"
                    )
                    raw_msg = _strip_function_syntax(event.message or "").strip()
                    if raw_msg:
                        yield MessageEvent(message=raw_msg, is_final=True)
                    continue
                msg_obj = Message.model_validate(parsed_response)
                # Same wire-format residue guard on the parsed message body.
                msg_obj.message = _strip_function_syntax(
                    msg_obj.message or ""
                ).strip() or msg_obj.message
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
