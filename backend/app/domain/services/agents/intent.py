"""Chat-mode intent classification (Manus CHAT_MODE_AGENT vs CHAT_MODE_DISCUSS).

A tiny, fast model call decides whether an incoming message is
  · DISCUSS — pure conversation the assistant can answer directly (greeting,
    small talk, opinions, questions answerable from knowledge or session
    history, clarifications about finished work), or
  · AGENT   — a request that needs the sandbox/tools (research, browsing,
    building, files, data processing, multi-step work).

The classification is semantic (the model judges intent), never a hardcoded
keyword list, so it generalises across languages. Safe default on ANY
failure is AGENT — the planner then produces a zero-step conversational
answer anyway, so a mis-gate degrades to today's behaviour, never worse.
"""

from typing import Optional, Tuple
import asyncio
import json
import logging
import re

from langchain.messages import SystemMessage as LCSystemMessage
from langchain.messages import HumanMessage as LCHumanMessage

logger = logging.getLogger(__name__)

CHAT_MODE_AGENT = "agent"
CHAT_MODE_DISCUSS = "discuss"

# Discuss requires this minimum confidence — anything lower runs as a task.
DISCUSS_MIN_CONFIDENCE = 0.6

_CLASSIFY_TIMEOUT_S = 12.0

# ── Deterministic trivial-chat fast path ────────────────────────────────────
# A message that is ENTIRELY a greeting / acknowledgement / farewell (any mix
# of English, Indonesian, and chat slang) is pure conversation — it never
# needs tools. Sending it to the model wastes latency, and a low-confidence
# model answer used to drop it into agent mode, where the executor's "read
# AGENTS.md first" instruction made a bare "hai" open the workspace manual —
# the exact mismatch users saw. The gate fires ONLY when every token is a
# known trivial token and the message is short; "hai, buatkan website" keeps
# the normal semantic path because "buatkan"/"website" are not trivial.
_TRIVIAL_TOKENS = frozenset({
    # greetings — EN / ID / misc
    "hi", "hii", "hiii", "hai", "haii", "hy", "hello", "helloo", "halo",
    "haloo", "hey", "heyy", "heyo", "yo", "yoo", "sup", "oi", "oy",
    "pagi", "pagii", "siang", "siangg", "sore", "soree", "malam",
    "malamm", "selamat", "assalamualaikum", "wr", "wb", "hola", "bonjour",
    "ciao", "nihao", "annyeong",
    # acknowledgements
    "ok", "oke", "okeh", "okey", "okee", "okok", "k", "kk", "siap",
    "sip", "sipp", "sippp", "yes", "ya", "yaa", "yup", "yups", "yoi",
    "no", "noo", "enggak", "nggak", "gak", "gk", "ndak", "hm", "hmm",
    "hmmm", "mm", "mmm", "eh", "ehm", "umm", "wow", "wee", "waw",
    # reactions
    "good", "nice", "great", "cool", "mantap", "mantul", "keren",
    "sepp", "joss", "cakep", "mantab",
    # thanks
    "thanks", "thank", "thankss", "thx", "tks", "ty", "tq", "makasih",
    "makasihh", "makasi", "mksih", "tengkyu", "thankyou",
    # farewells
    "bye", "byee", "bai", "dadah", "daah", "gtg", "cya", "cu",
    # pings
    "bot", "bro", "gan", "kak", "min", "tes", "test", "testing",
})

_TRIVIAL_TOKEN_MAX = 5
_TOKEN_SPLIT = re.compile(r"[\s,.!?;:\u2026\u2014\u2013()\[\]{}\"']+")


def _is_trivial_chat(text: str) -> bool:
    """True when the whole message is pure small talk — greeting, ack, thanks,
    farewell, or an emoji/punctuation-only message. Never true for anything
    containing a request, question word, or task vocabulary."""
    tokens = [t for t in _TOKEN_SPLIT.split(text.lower()) if t]
    # Keep only tokens with real alphanumeric content; an emoji-only or
    # punctuation-only message ("👋", "!!!", "…") leaves nothing.
    word_tokens = [t for t in tokens if any(c.isalnum() for c in t)]
    if not word_tokens:
        return bool(text.strip())
    if len(word_tokens) > _TRIVIAL_TOKEN_MAX:
        return False
    return all(t in _TRIVIAL_TOKENS for t in word_tokens)

_SYSTEM = (
    "You classify user messages sent to an AI assistant that has real "
    "working tools (browser, shell, file operations, web search, image "
    "tools). Decide how the assistant should handle the message:\n"
    "DISCUSS — pure conversation: greetings, small talk, thanks, opinions, "
    "brainstorming, quick factual or conceptual questions answerable from "
    "your own knowledge or from the conversation history, questions ABOUT "
    "work already delivered (asking what was done, why, or what something "
    "means), requests to simply continue chatting.\n"
    "AGENT — needs tools or real work: research or facts requiring web "
    "search, visiting websites, creating/modifying/downloading files or "
    "deliverables, running code, data analysis, building apps or sites, "
    "processing attachments/images, or any request whose answer must be "
    "produced rather than known.\n"
    "Quick calibration — a bare greeting in ANY language (hi, hai, halo, "
    "hello, hey, pagi, assalamualaikum…) is always DISCUSS with confidence "
    "0.95 or higher; a greeting that ALSO carries a request (\"hai, buatkan "
    "website\", \"hi, research X for me\") is AGENT — the attached work "
    "decides, not the greeting word.\n"
    'Reply with compact JSON only: {"mode": "discuss"|"agent", '
    '"confidence": 0.0-1.0}. When genuinely unsure whether real work is being '
    'requested, prefer "agent" — but a bare greeting is never a doubt.'
)


async def classify_chat_mode(
    message_text: str,
    conversation_history: Optional[str] = None,
) -> Tuple[str, float]:
    """Return (mode, confidence). Never raises; failure → ("agent", 0.0)."""
    text = (message_text or "").strip()
    if not text:
        return CHAT_MODE_AGENT, 0.0

    # Deterministic fast path: pure small talk is discuss without a model call
    # — zero latency, zero cost, and immune to provider hiccups.
    if _is_trivial_chat(text):
        return CHAT_MODE_DISCUSS, 0.99

    prompt = ""
    if conversation_history and conversation_history.strip():
        prompt += (
            "[Conversation so far in this session]\n"
            f"{conversation_history.strip()}\n\n"
        )
    prompt += f"[Message to classify]\n{text}"

    # Import here so tests can monkeypatch lazily without model init cost.
    from app.domain.services.agents.base import _build_chat_model

    try:
        answer = await asyncio.wait_for(_classify_call(_build_chat_model, prompt), _CLASSIFY_TIMEOUT_S)
    except Exception as exc:
        logger.debug("chat-mode classification failed (%s) — defaulting to agent", exc)
        return CHAT_MODE_AGENT, 0.0

    mode, confidence = answer
    if mode == CHAT_MODE_DISCUSS and confidence < DISCUSS_MIN_CONFIDENCE:
        return CHAT_MODE_AGENT, confidence
    return mode, confidence


async def _classify_call(_build, prompt: str) -> Tuple[str, float]:
    model = _build(prefer_fallback=False)
    try:
        response = await model.ainvoke(
            [LCSystemMessage(content=_SYSTEM), LCHumanMessage(content=prompt)]
        )
    except Exception:
        # Primary provider unavailable — try the fallback provider once.
        model = _build(prefer_fallback=True)
        response = await model.ainvoke(
            [LCSystemMessage(content=_SYSTEM), LCHumanMessage(content=prompt)]
        )

    raw = (response.content or "") if hasattr(response, "content") else ""
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    raw = raw.strip()

    # Tolerate fenced/prefixed JSON.
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Free-form fallback: scan for the keyword.
        lowered = raw.lower()
        if "discuss" in lowered and "agent" not in lowered:
            return CHAT_MODE_DISCUSS, DISCUSS_MIN_CONFIDENCE
        return CHAT_MODE_AGENT, 0.0

    mode = str(data.get("mode", CHAT_MODE_AGENT)).lower()
    if mode not in (CHAT_MODE_AGENT, CHAT_MODE_DISCUSS):
        mode = CHAT_MODE_AGENT
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return mode, max(0.0, min(1.0, confidence))
