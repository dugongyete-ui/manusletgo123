import logging
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, ClassVar
from app.domain.models.tool_result import ToolResult
from langchain.messages import AnyMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# All tool names whose large result payloads should be stripped after a
# step / mid-step compaction. Only the most recent call of each is kept
# intact. Browser tools carry DOM snapshots; file tools echo file bodies;
# shell tools echo command output; search/image tools echo result lists
# (and image_download historically embedded a base64 preview) — none of
# the stale copies matter once the agent has moved on (it can always
# re-read / re-run / re-search if needed).
TOOLS_TO_COMPACT = {
    "browser_view",
    "browser_navigate",
    "browser_click",
    "browser_input",
    "browser_scroll_up",
    "browser_scroll_down",
    "browser_move_mouse",
    "browser_press_key",
    "browser_select_option",
    "browser_open_tab",
    "browser_switch_tab",
    "browser_restart",
    "file_write",
    "file_read",
    "shell_exec",
    "shell_wait",
    "shell_kill_process",
    "browser_console_exec",
    # Search / image results accumulate on research-heavy tasks
    # (search → download → search → download …): each search keeps ~10
    # results and each download used to embed a base64 preview. Without
    # compaction these pile up for the WHOLE task and blow the provider's
    # prompt-length limit (error 1261) — the exact failure mode reported
    # on image-heavy autonomous runs.
    "info_search_web",
    "image_search_web",
    "image_download",
    "image_generate",
}

# Tool-call ARGUMENTS that embed bulk user-generated payloads. The full
# file body written via file_write / the whole script passed to shell_exec
# live inside AIMessage.tool_calls and inflate every later request — the
# dominant cause of "Prompt exceeds max length" (provider error 1261)
# on build-heavy tasks that write dozens of files in one step.
# Only the most recent KEEP_RECENT_ARG_CALLS calls per tool keep their
# full argument; older ones get the bulky field replaced by a stub.
BULKY_TOOL_ARGS = {
    "file_write": "content",
    "shell_exec": "command",
}
KEEP_RECENT_ARG_CALLS = 2

# Aggressive-mode knobs (used when the prompt has ALREADY blown the
# provider limit — see BaseAgent._emergency_context_reduction):
AGGRESSIVE_KEEP_TAIL = 12        # messages whose tool results stay (truncated)
AGGRESSIVE_TOOL_CHAR_CAP = 12_000  # max chars per surviving tool result
AGGRESSIVE_TEXT_CHAR_CAP = 20_000  # max chars per old human/ai text blob
AGGRESSIVE_TEXT_KEPT = 8_000      # chars kept when truncating such a blob
AGGRESSIVE_ARG_CHAR_CAP = 2_000   # max chars per surviving tool_call argument
AGGRESSIVE_ARG_KEPT = 1_500       # chars kept when truncating such an argument

# Head+tail truncation helper (keeps both the beginning and the end of a
# payload — for DOM lists the end usually holds the interactive index
# space the model is currently working in).
def _truncate_middle(text: str, limit: int, kept: Optional[int] = None) -> str:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    total_kept = kept if kept is not None else limit
    head = int(total_kept * 0.7)
    tail = max(0, total_kept - head)
    marker = (
        f"\n…[TRUNCATED {len(text) - total_kept} characters — full content "
        "is preserved in the task artifact; re-run the tool or use "
        "file_read to view it again]…\n"
    )
    return text[:head] + marker + (text[-tail:] if tail else "")


def compact_messages(
    messages: List[AnyMessage],
    aggressive: bool = False,
    keep_recent_arg_calls: int = KEEP_RECENT_ARG_CALLS,
) -> None:
    """Three-pass (four in aggressive mode) in-place context cleanup.

    Pass 1 — bulky ToolMessage payloads:
        Strip large tool results (browser DOM snapshots, file bodies,
        shell output, search/image result lists) from all but the most
        recent call of each tool. The agent only needs the latest state.

    Pass 2 — Vision image_url base64 in HumanMessages:
        Vision images (user attachments, step-start screenshots) are
        embedded as data-URI base64 strings (~150-300 KB each) inside
        multimodal HumanMessage content lists. Once the LLM has processed
        them they are never needed again, but they accumulate across steps
        and inflate every subsequent API request. This pass strips all
        image_url entries from every HumanMessage, preserving only the
        text parts. This is the primary cause of 500 "payload too large"
        errors on long browser automation tasks.

    Pass 3 — bulky tool-call ARGUMENTS in old AIMessages:
        file_write carries the entire file body and shell_exec the whole
        script inside the AIMessage tool_calls themselves. On build-heavy
        tasks (e.g. scaffolding a whole project in one step) dozens of
        these accumulate and blow the provider's prompt-length limit on
        the NEXT step. Keep the most recent calls intact and stub the
        bulky argument of older ones (the content still exists in the
        sandbox — the agent can re-read it via file_read if needed).

    Aggressive mode (error-1261 emergency) additionally:
        Pass 1b — stub tool results for ALL tools in TOOLS_TO_COMPACT
            except those inside the trailing AGGRESSIVE_KEEP_TAIL messages,
            and hard-truncate the surviving ones to
            AGGRESSIVE_TOOL_CHAR_CAP chars each.
        Pass 4 — truncate very long plain-text blobs in old human/ai
            messages outside the tail window.
    """
    n = len(messages)
    tail_start = n - AGGRESSIVE_KEEP_TAIL if aggressive else n

    # --- Pass 1 (+1b): strip old bulky ToolMessage payloads ---
    last_index: dict[str, int] = {}
    for i, message in enumerate(messages):
        if message.type == "tool" and message.name in TOOLS_TO_COMPACT:
            last_index[message.name] = i

    for i, message in enumerate(messages):
        if message.type != "tool" or message.name not in TOOLS_TO_COMPACT:
            continue
        if not aggressive and last_index.get(message.name) == i:
            continue
        if aggressive:
            # Keep (truncated) results only inside the tail window; the
            # "latest call per tool" may be hundreds of messages back on
            # long tasks — when the prompt already blew the limit every
            # char counts, so stub it too.
            if i >= tail_start:
                message.content = _truncate_middle(
                    str(message.content), AGGRESSIVE_TOOL_CHAR_CAP
                )
                continue
            message.content = ToolResult(success=True, data="(removed)").model_dump_json()
            logger.debug(f"Compacted tool result from memory: {message.name} at index {i}")
        else:
            message.content = ToolResult(success=True, data="(removed)").model_dump_json()
            logger.debug(f"Compacted tool result from memory: {message.name} at index {i}")

    # --- Pass 2: strip base64 image_url data from HumanMessages ---
    for i, message in enumerate(messages):
        if message.type != "human":
            continue
        if not isinstance(message.content, list):
            continue
        has_image = any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in message.content
        )
        if not has_image:
            continue
        # Keep only text parts — drop all image_url (base64) entries.
        text_parts = [
            part for part in message.content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if text_parts:
            message.content = (
                text_parts[0]["text"] if len(text_parts) == 1 else text_parts
            )
        else:
            message.content = "(image removed)"
        logger.debug(f"Stripped vision image(s) from HumanMessage at index {i}")

    # --- Pass 3: stub bulky tool-call arguments in old AIMessages ---
    # Walk from the END so the most recent keep_recent_arg_calls calls
    # per bulky tool keep their full arguments; older ones get the bulky
    # field replaced by a length marker.  In-place mutation is safe: the
    # OpenAI serializer builds the payload from AIMessage.tool_calls.
    recent_kept: dict[str, int] = {}
    for message in reversed(messages):
        if message.type != "ai":
            continue
        for call in message.tool_calls or []:
            field = BULKY_TOOL_ARGS.get(call.get("name", ""))
            if field is None:
                # Aggressive mode: ANY tool can carry a giant argument
                # (e.g. a model pasting a 60K DOM fragment into
                # browser_input). Clip oversized string args everywhere.
                if aggressive:
                    args = call.get("args") or {}
                    for key, value in list(args.items()):
                        if isinstance(value, str) and len(value) > AGGRESSIVE_ARG_CHAR_CAP:
                            args[key] = _truncate_middle(
                                value, AGGRESSIVE_ARG_CHAR_CAP,
                                kept=AGGRESSIVE_ARG_KEPT,
                            )
                continue
            kept = recent_kept.setdefault(call["name"], 0)
            if kept < keep_recent_arg_calls:
                recent_kept[call["name"]] = kept + 1
                # Aggressive mode clips even the KEPT recent bulky args —
                # when the prompt already blew the limit, a 60K file body
                # in the newest call is part of the problem.
                if aggressive:
                    args = call.get("args") or {}
                    value = args.get(field)
                    if isinstance(value, str) and len(value) > AGGRESSIVE_ARG_CHAR_CAP:
                        args[field] = _truncate_middle(
                            value, AGGRESSIVE_ARG_CHAR_CAP,
                            kept=AGGRESSIVE_ARG_KEPT,
                        )
                continue
            args = call.get("args") or {}
            value = args.get(field)
            if isinstance(value, str) and len(value) > 400:
                args[field] = f"(compacted: {len(value)} chars)"
                logger.debug(
                    "Compacted tool_call argument %s.%s (%d chars)",
                    call["name"], field, len(value),
                )

    # --- Pass 4 (aggressive only): truncate old long text blobs ---
    if aggressive:
        for i, message in enumerate(messages):
            if i >= tail_start:
                continue
            if message.type not in ("human", "ai"):
                continue
            if not isinstance(message.content, str):
                continue
            if len(message.content) > AGGRESSIVE_TEXT_CHAR_CAP:
                message.content = _truncate_middle(
                    message.content, AGGRESSIVE_TEXT_CHAR_CAP,
                    kept=AGGRESSIVE_TEXT_KEPT,
                )
                logger.debug(
                    "Aggressive compaction truncated %s message at index %d",
                    message.type, i,
                )


def drop_older_rounds(
    messages: List[AnyMessage],
    keep_last_messages: int = 10,
) -> List[AnyMessage]:
    """Protocol-safe removal of the OLDEST conversation rounds (in place).

    This is the last-resort rung of the context-overflow ladder: after
    compaction the accumulated history can still exceed the provider's
    prompt limit (e.g. one giant browser_view per round), so whole old
    rounds must go.  OpenAI-compatible providers reject a conversation
    whose AIMessage.tool_calls are not followed by their matching
    ToolMessages, so the cut point MUST fall on a HumanMessage boundary
    — in this architecture every round starts with a HumanMessage and
    all tool results of a round precede the next HumanMessage.

    Kept after the cut:
      * the leading SystemMessage (agent persona),
      * a truncated stub of the FIRST HumanMessage (the session's
        original task, so the goal is never lost),
      * a system-note HumanMessage documenting the removal,
      * the trailing `keep_last_messages` messages starting at a
        HumanMessage boundary (recent, complete rounds).
    """
    n = len(messages)
    if n <= keep_last_messages + 2:
        return messages

    cut = n - keep_last_messages
    # Advance the cut to the first HumanMessage at/after the target so no
    # AIMessage(tool_calls) is separated from its ToolMessages.
    j = cut
    while j < n and messages[j].type != "human":
        j += 1
    if j >= n:
        # No safe boundary found — refuse to cut rather than corrupt the
        # tool-call pairing.
        return messages

    head: List[AnyMessage] = []
    start = 0
    if messages[0].type == "system":
        head.append(messages[0])
        start = 1

    # Stub of the session's first user task (only if it is being dropped).
    first_human_idx: Optional[int] = None
    for k in range(start, j):
        if messages[k].type == "human":
            first_human_idx = k
            break
    if first_human_idx is not None:
        stub = messages[first_human_idx].content
        if not isinstance(stub, str):
            stub = "(multimodal content removed)"
        head.append(HumanMessage(content=_truncate_middle(stub, 800)))

    dropped = j - start - (1 if first_human_idx is not None else 0)
    head.append(HumanMessage(content=(
        f"[SYSTEM NOTE: {dropped} older conversation messages were removed "
        "to fit the model's context window. Earlier work is reflected in "
        "the plan and in the recent messages kept below.]"
    )))

    messages[:] = head + messages[j:]
    logger.info(
        "Dropped %d older conversation rounds to fit the context window "
        "(%d → %d messages)", dropped, n, len(messages),
    )
    return messages


class Memory(BaseModel):
    """
    Memory class, defining the basic behavior of memory
    """
    messages: List[AnyMessage] = []

    def add_message(self, message: AnyMessage) -> None:
        """Add message to memory"""
        self.messages.append(message)
    
    def add_messages(self, messages: List[AnyMessage]) -> None:
        """Add messages to memory"""
        self.messages.extend(messages)

    def get_messages(self) -> List[AnyMessage]:
        """Get all message history"""
        return self.messages
    
    def get_last_message(self) -> Optional[AnyMessage]:
        """Get the last message"""
        if len(self.messages) > 0:  
            return self.messages[-1]
        return None
    
    def roll_back(self) -> None:
        """Roll back memory"""
        self.messages = self.messages[:-1]

    # Kept for backwards compatibility with existing call sites/tests.
    _TOOLS_TO_COMPACT = TOOLS_TO_COMPACT
    _BULKY_TOOL_ARGS = BULKY_TOOL_ARGS
    _KEEP_RECENT_ARG_CALLS = KEEP_RECENT_ARG_CALLS

    # ── Map-reduce context summary (Manus-style compaction) ────────────────
    # Marker prefix of the rolling SystemMessage that carries the distilled
    # summary of older, already-compacted work. Kept right after the leading
    # system prompt so the model always starts with the distilled context.
    SUMMARY_MARKER: ClassVar[str] = "[Earlier work summary]"

    def compact(self, aggressive: bool = False) -> None:
        """Compact memory — see :func:`compact_messages` for the passes."""
        compact_messages(self.messages, aggressive=aggressive)

    def find_summary_message(self) -> Optional[int]:
        """Index of the rolling summary SystemMessage, if present."""
        for idx, message in enumerate(self.messages[:4]):
            if (
                message.type == "system"
                and isinstance(message.content, str)
                and message.content.startswith(self.SUMMARY_MARKER)
            ):
                return idx
        return None

    def get_context_summary(self) -> str:
        """Current rolling summary text ('' when none exists yet)."""
        idx = self.find_summary_message()
        if idx is None:
            return ""
        content = self.messages[idx].content
        return content[len(self.SUMMARY_MARKER):].strip() if isinstance(content, str) else ""

    def set_context_summary(self, text: str) -> None:
        """Insert or refresh the rolling summary SystemMessage.

        Placed immediately after the leading system prompt (or at the head
        when there is none) so it behaves as stable distilled context.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return
        payload = f"{self.SUMMARY_MARKER} {cleaned}"
        idx = self.find_summary_message()
        if idx is not None:
            self.messages[idx].content = payload
            return
        insert_at = 1 if (self.messages and self.messages[0].type == "system") else 0
        self.messages.insert(insert_at, SystemMessage(content=payload))

    def collect_compaction_digest(self, max_chars: int = 24_000) -> str:
        """Snapshot of the context a normal compaction is ABOUT to lose.

        Mirrors the pass logic of :func:`compact_messages`: old bulky tool
        results (all but the most recent per tool) and old bulky tool-call
        arguments (all but the most recent calls). The result feeds the
        map step of the map-reduce summary; the physical compaction then
        runs as usual.
        """
        lines: List[str] = []
        budget = max_chars

        def _emit(label: str, text: Any) -> None:
            nonlocal budget
            if budget <= 0:
                return
            clean = text if isinstance(text, str) else ""
            if not clean.strip():
                return
            snippet = clean[:1500]
            lines.append(f"{label}: {snippet}")
            budget -= len(snippet)

        last_tool_index: Dict[str, int] = {}
        for i, message in enumerate(self.messages):
            if message.type == "tool" and getattr(message, "name", None) in TOOLS_TO_COMPACT:
                last_tool_index[message.name] = i
        for i, message in enumerate(self.messages):
            if (
                message.type == "tool"
                and getattr(message, "name", None) in TOOLS_TO_COMPACT
                and last_tool_index.get(message.name) != i
            ):
                _emit(f"[older {message.name} result]", message.content)

        recent_calls: Dict[str, List[int]] = {}
        for i, message in enumerate(self.messages):
            if message.type != "ai":
                continue
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name")
                if name in BULKY_TOOL_ARGS:
                    recent_calls.setdefault(name, []).append(i)
        for i, message in enumerate(self.messages):
            if message.type != "ai":
                continue
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name")
                if name not in BULKY_TOOL_ARGS:
                    continue
                call_rows = recent_calls.get(name) or []
                if i in call_rows[-KEEP_RECENT_ARG_CALLS:]:
                    continue
                args = call.get("args") or {}
                bulky = args.get(BULKY_TOOL_ARGS[name])
                if bulky:
                    _emit(f"[older {name} argument]", bulky)

        return "\n".join(lines)

    async def compact_with_summary(self, summarize) -> bool:
        """Map-reduce compaction: distil the about-to-be-lost context with
        an LLM (map step), run the physical compaction, then store the
        rolling summary (reduce step) as a SystemMessage.

        ``summarize`` is an async callable digest→summary-text. Returns
        True when a summary was stored. On ANY summarizer failure the
        physical compaction still ran — plain truncation remains the
        fallback, exactly like before.
        """
        digest = self.collect_compaction_digest()
        previous_summary = self.get_context_summary()
        compact_messages(self.messages, aggressive=False)
        if not digest or summarize is None:
            return False
        try:
            merged = digest
            if previous_summary:
                merged = (
                    f"[Previous distilled summary]\n{previous_summary}\n\n"
                    f"[Newly compacted material]\n{digest}"
                )
            summary = await summarize(merged)
        except Exception:
            logger.debug("map-reduce summary failed — plain compaction kept", exc_info=True)
            return False
        if not (summary or "").strip():
            return False
        self.set_context_summary(summary)
        logger.info(
            "Map-reduce compaction: %d chars of digest distilled into a "
            "%d-char rolling summary",
            len(digest), len(summary),
        )
        return True

    def drop_older_rounds(self, keep_last_messages: int = 10) -> None:
        """Drop the oldest conversation rounds — see :func:`drop_older_rounds`."""
        drop_older_rounds(self.messages, keep_last_messages=keep_last_messages)

    @property
    def empty(self) -> bool:
        """Check if memory is empty"""
        return len(self.messages) == 0
