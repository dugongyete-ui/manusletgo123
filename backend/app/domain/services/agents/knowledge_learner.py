"""Post-task learning proposals (Manus KnowledgeEvent PENDING loop).

After a real task finishes, a small best-effort model call distils durable
learnings — stable user preferences, correction patterns, environment facts,
reusable conventions — that would genuinely help FUTURE tasks. The proposals
are stored as PENDING knowledge items; the user accepts or rejects them, and
only accepted items ride along in later sessions' context.

Deliberately conservative: anything task-specific (this session's file names,
one-off request details) is NOT knowledge and is filtered out by the prompt.
The call never raises and never blocks the task — a failure simply means no
learning proposal for this run.
"""

from typing import List, Optional
import asyncio
import json
import logging

from langchain.messages import SystemMessage as LCSystemMessage
from langchain.messages import HumanMessage as LCHumanMessage

logger = logging.getLogger(__name__)

_LEARN_TIMEOUT_S = 20.0
MAX_LEARNINGS = 3
MAX_ITEM_CHARS = 240
MAX_DIGEST_CHARS = 12_000

_SYSTEM = (
    "You distil durable, reusable knowledge from a completed AI-assistant "
    "task session. Only propose a learning when it would clearly help a "
    "FUTURE, DIFFERENT task with the same user. Good learnings:\n"
    "- stable user preferences (language, output style, tone, format)\n"
    "- corrections the user made that will recur (\"never zip files\", "
    "\"always keep the original folder structure\", \"prefer PNG\")\n"
    "- environment/tool facts that were discovered the hard way and will "
    "apply again (which package works, which site blocks bots)\n"
    "Bad learnings (never propose): anything about THIS task's specific "
    "content, one-off file names, the task's own results, or generic "
    "assistant behaviour. Prefer zero learnings over noise.\n"
    'Reply with compact JSON only: {"learnings": ["...", "..."]} — at most '
    f"{MAX_LEARNINGS} items, each one sentence, same language as the user."
)


def _clean_item(item: str) -> Optional[str]:
    text = str(item or "").strip().strip('"').strip()
    if not text:
        return None
    if len(text) > MAX_ITEM_CHARS:
        text = text[: MAX_ITEM_CHARS - 1].rstrip() + "…"
    return text


async def propose_learnings(
    transcript_digest: str,
    user_message: str,
) -> List[str]:
    """Return up to MAX_LEARNINGS proposed knowledge strings.

    ``transcript_digest`` is a compact rendering of the finished run
    (user request, steps, final summary). Never raises.
    """
    digest = (transcript_digest or "").strip()[:MAX_DIGEST_CHARS]
    if not digest:
        return []

    prompt = (
        f"[User request]\n{(user_message or '').strip()[:2000]}\n\n"
        f"[Run digest]\n{digest}"
    )

    from app.domain.services.agents.base import _build_chat_model

    try:
        return await asyncio.wait_for(
            _learn_call(_build_chat_model, prompt), _LEARN_TIMEOUT_S
        )
    except Exception as exc:
        logger.debug("learning proposal failed (%s) — skipping", exc)
        return []


async def _learn_call(_build, prompt: str) -> List[str]:
    model = _build(prefer_fallback=False)
    try:
        response = await model.ainvoke(
            [LCSystemMessage(content=_SYSTEM), LCHumanMessage(content=prompt)]
        )
    except Exception:
        model = _build(prefer_fallback=True)
        response = await model.ainvoke(
            [LCSystemMessage(content=_SYSTEM), LCHumanMessage(content=prompt)]
        )

    raw = (response.content or "") if hasattr(response, "content") else ""
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    raw = raw.strip()

    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []

    items = data.get("learnings")
    if not isinstance(items, list):
        return []

    cleaned: List[str] = []
    seen = set()
    for item in items[:MAX_LEARNINGS]:
        text = _clean_item(item)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
    return cleaned
