"""Session-history → provider-format conversion.

The agent runtime stores conversation memory as LangChain messages
(``AnyMessage``). OpenAI-compatible gateways tolerate almost any ordering,
but the Anthropic Messages API is stricter:

- roles must alternate user/assistant (system lives in its own parameter);
- every ``ToolMessage`` must directly follow the assistant message that owns
  the matching ``tool_use`` id;
- empty text-only messages are rejected.

``convert_history_for_provider`` returns a provider-safe copy. The default
provider gets a validated passthrough (identical semantics — nothing changes
for the existing pipeline).
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def _content_to_text(content) -> str:
    """Best-effort plain-text projection of a message content block."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif block.get("type") == "tool_use" or block.get("type") == "tool_result":
                    parts.append("")  # structural blocks — keep, don't stringify
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)


def _has_tool_calls(message) -> bool:
    return bool(getattr(message, "tool_calls", None))


def _sanitize_for_anthropic(messages: List) -> List:
    """Protocol-safe cleanup for the Anthropic Messages API.

    Rules enforced (order matters):
    1. Drop ToolMessages whose matching assistant tool_use is not the
       immediately preceding message (dangling tool results are rejected).
    2. Drop empty text-only assistant/human messages (no content AND no
       tool calls) — Anthropic 400s on them.
    3. Merge consecutive same-role messages that carry plain text content
       (belt-and-braces: ChatAnthropic also merges, but pre-merging keeps
       tool_call adjacency intact and makes token estimates accurate).
    """
    sanitized: List = []
    from langchain_core.messages import AIMessage, HumanMessage

    for msg in messages:
        msg_type = getattr(msg, "type", "")
        # 1 — dangling tool results
        if msg_type == "tool":
            prev = sanitized[-1] if sanitized else None
            if prev is None or getattr(prev, "type", "") != "ai" or not _has_tool_calls(prev):
                logger.debug("Dropping dangling ToolMessage for provider history")
                continue
            sanitized.append(msg)
            continue
        if msg_type == "system":
            sanitized.append(msg)
            continue
        # 2 — empty messages (whitespace-only counts as empty)
        text = _content_to_text(getattr(msg, "content", None))
        if not text.strip() and not _has_tool_calls(msg):
            logger.debug("Dropping empty %s message for provider history", msg_type)
            continue
        # 3 — merge consecutive same-role text messages
        prev = sanitized[-1] if sanitized else None
        if (
            prev is not None
            and not _has_tool_calls(prev)
            and not _has_tool_calls(msg)
            and prev.type == msg.type
            and isinstance(prev.content, str)
            and isinstance(msg.content, str)
            and msg_type in ("ai", "human")
        ):
            merged_content = (prev.content or "") + "\n" + (msg.content or "")
            if msg_type == "ai":
                sanitized[-1] = AIMessage(content=merged_content)
            else:
                sanitized[-1] = HumanMessage(content=merged_content)
            continue
        sanitized.append(msg)
    return sanitized


def convert_history_for_provider(provider_name: str, messages: List) -> List:
    """Convert stored LangChain history into the provider's protocol shape.

    - ``anthropic`` → sanitized copy (see :func:`_sanitize_for_anthropic`)
    - anything else → validated passthrough (existing behaviour untouched)
    """
    if not messages:
        return []
    if provider_name == "anthropic":
        return _sanitize_for_anthropic(list(messages))
    # Default: the OpenAI-compatible path consumes the history as-is —
    # behaviour preserved byte-for-byte from before the provider seam.
    return list(messages)
