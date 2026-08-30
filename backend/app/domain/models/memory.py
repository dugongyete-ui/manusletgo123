import logging
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.domain.models.tool_result import ToolResult
from langchain.messages import AnyMessage

logger = logging.getLogger(__name__)

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
    
    # All tool names whose large result payloads should be stripped after a
    # step / mid-step compaction. Only the most recent call of each is kept
    # intact. Browser tools carry DOM snapshots; file tools echo file bodies;
    # shell tools echo command output — none of the stale copies matter once
    # the agent has moved on (it can always re-read / re-run if needed).
    _TOOLS_TO_COMPACT = {
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
    }

    # Legacy alias kept for readability at call sites.
    _BROWSER_TOOLS_TO_COMPACT = _TOOLS_TO_COMPACT

    # Tool-call ARGUMENTS that embed bulk user-generated payloads. The full
    # file body written via file_write / the whole script passed to shell_exec
    # live inside AIMessage.tool_calls and inflate every later request — the
    # dominant cause of "Prompt exceeds max length" (provider error 1261)
    # on build-heavy tasks that write dozens of files in one step.
    # Only the most recent _KEEP_RECENT_ARG_CALLS calls per tool keep their
    # full argument; older ones get the bulky field replaced by a stub.
    _BULKY_TOOL_ARGS = {
        "file_write": "content",
        "shell_exec": "command",
    }
    _KEEP_RECENT_ARG_CALLS = 2

    def compact(self) -> None:
        """Compact memory — three-pass cleanup to keep context size small:

        Pass 1 — bulky ToolMessage payloads:
            Strip large tool results (browser DOM snapshots, file bodies,
            shell output) from all but the most recent call of each tool.
            The agent only needs the latest state of each.

        Pass 2 — Vision image_url base64 in HumanMessages:
            Vision images (user attachments, step-start screenshots) are
            embedded as data-URI base64 strings (~150-300 KB each) inside
            multimodal HumanMessage content lists.  Once the LLM has processed
            them they are never needed again, but they accumulate across steps
            and inflate every subsequent API request.  This pass strips all
            image_url entries from every HumanMessage, preserving only the
            text parts.  This is the primary cause of 500 "payload too large"
            errors on long browser automation tasks.

        Pass 3 — bulky tool-call ARGUMENTS in old AIMessages:
            file_write carries the entire file body and shell_exec the whole
            script inside the AIMessage tool_calls themselves.  On build-heavy
            tasks (e.g. scaffolding a whole project in one step) dozens of
            these accumulate and blow the provider's prompt-length limit on
            the NEXT step.  Keep the most recent calls intact and stub the
            bulky argument of older ones (the content still exists in the
            sandbox — the agent can re-read it via file_read if needed).
        """
        # --- Pass 1: strip old bulky ToolMessage payloads (existing logic) ---
        last_index: dict[str, int] = {}
        for i, message in enumerate(self.messages):
            if message.type == "tool" and message.name in self._TOOLS_TO_COMPACT:
                last_index[message.name] = i

        for i, message in enumerate(self.messages):
            if message.type == "tool" and message.name in self._TOOLS_TO_COMPACT:
                if last_index.get(message.name) == i:
                    continue
                message.content = ToolResult(success=True, data="(removed)").model_dump_json()
                logger.debug(f"Compacted tool result from memory: {message.name} at index {i}")

        # --- Pass 2: strip base64 image_url data from HumanMessages ---
        for i, message in enumerate(self.messages):
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
        # Walk from the END so the most recent _KEEP_RECENT_ARG_CALLS calls
        # per bulky tool keep their full arguments; older ones get the bulky
        # field replaced by a length marker.  In-place mutation is safe: the
        # OpenAI serializer builds the payload from AIMessage.tool_calls.
        recent_kept: dict[str, int] = {}
        for message in reversed(self.messages):
            if message.type != "ai":
                continue
            for call in message.tool_calls or []:
                field = self._BULKY_TOOL_ARGS.get(call.get("name", ""))
                if field is None:
                    continue
                kept = recent_kept.setdefault(call["name"], 0)
                if kept < self._KEEP_RECENT_ARG_CALLS:
                    recent_kept[call["name"]] = kept + 1
                    continue
                args = call.get("args") or {}
                value = args.get(field)
                if isinstance(value, str) and len(value) > 400:
                    args[field] = f"(compacted: {len(value)} chars)"
                    logger.debug(
                        "Compacted tool_call argument %s.%s (%d chars)",
                        call["name"], field, len(value),
                    )

    @property
    def empty(self) -> bool:
        """Check if memory is empty"""
        return len(self.messages) == 0
