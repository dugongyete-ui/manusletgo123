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
    "More calibration (the common misfires):\n"
    "- Requests to SEE or BE SHOWN something real (\"contohkan dong\", "
    "\"coba contohkan\", \"kasih contoh yang bisa saya lihat\", \"saya ingin "
    "melihat nya\", \"tunjukkan\", \"show me an example\", \"demokan\") are "
    "AGENT — the assistant must actually produce or demonstrate something "
    "with its tools, not just promise.\n"
    "- If the previous assistant message PROMISED work (\"saya akan "
    "siapkan…\", \"saya akan buatkan…\", \"I'll prepare…\") and the user now "
    "says proceed / show it / okay / go ahead, that is AGENT — the work "
    "must now actually run.\n"
    "- Polite softeners (\"coba\", \"dong\", \"deh\", \"ya\", \"please\") never "
    "downgrade a request to DISCUSS.\n"
    "- A request to DO or CHANGE something on a device/file/account "
    "(\"hapus\", \"buat\", \"ubah\", \"kirim\", \"cari\" + object) is AGENT.\n"
    "- Only label DISCUSS when the ENTIRE answer already exists in the "
    "model's knowledge or the transcript — nothing to produce, fetch, or "
    "demonstrate.\n"
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


# ── Unfulfilled-promise detector (discuss-mode safety net) ─────────────────
# Reported bug: "Coba contohkan saya ingin melihat nya" was classified as
# DISCUSS, so the reply model answered "Baik, saya akan siapkan contohnya
# untuk Anda." and the turn ENDED — a promise with no work behind it. This
# detector catches that exact shape: a SHORT reply that ONLY commits to
# future work and contains no actual answer.
_PROMISE_RE = re.compile(
    r"^\s*(baik|oke|ok|siap|baiklah|tentu|sure|okay|alright|got it)?[\s,!.]*"
    r"(saya|aku|i|i'll|i will|let me|allow me)\s*"
    r"(akan|akan saya|will|'ll|mau|ingin|usahakan|coba|coba untuk|"
    r"siapkan|menyiapkan|buatkan|membuatkan|bikinkan|menunjukkan|"
    r"tunjukkan|menunjukan|menyiapkan contoh|buatkan contoh|"
    r"prepare|prepared|get|getting|show|demonstrate|start|begin|"
    r"work on|handle|cek|check|mencari|cari|carikan|search)",
    re.IGNORECASE,
)
# Content markers that mean the reply actually ANSWERED something (even if
# it also contains "saya akan …").
_ANSWER_MARKERS_RE = re.compile(
    r"\?|karena|yaitu|adalah|contohnya:|contoh:|misalnya|sebagai contoh|"
    r"here (is|are)|this is|berikut|\d\s*(mb|gb|cm|kg|km|%)",
    re.IGNORECASE,
)
_PROMISE_MAX_CHARS = 220


def is_unfulfilled_promise(reply_text: str) -> bool:
    """True when a discuss-mode reply is ONLY a promise of future work.

    Narrow by design: short, starts with a commitment phrase, and carries
    no answer content (no question, no example, no explanation marker).
    A false positive merely sends a short conversational answer through the
    normal agent flow — degraded, never wrong.
    """
    text = (reply_text or "").strip()
    if not text or len(text) > _PROMISE_MAX_CHARS:
        return False
    if _ANSWER_MARKERS_RE.search(text):
        return False
    return bool(_PROMISE_RE.match(text))


# ── Stop-request detector (stop-by-text mid-run) ──────────────────────────
# When the agent is working and the user sends a short explicit stop command
# ("stop", "berhenti", "jangan dilanjutkan", …), the run must end gracefully:
# acknowledge, mark the plan finished, and stop — NOT feed the text to the
# executor as a new instruction. Deliberately conservative: short messages
# whose content words are ALL stop vocabulary or fillers, so work instructions
# that merely CONTAIN the word "stop" ("stop pakai browser, lanjut step 3")
# are never hijacked.
_STOP_WORDS = frozenset({
    # explicit stop commands
    "stop", "stopped", "stopp", "stoppp", "berhenti", "berhentikan",
    "hentikan", "henti", "halt", "abort",
    "batalkan", "batal", "cancel", "canceled", "cancelled",
    # "don't continue" family
    "jangan", "janganlah", "usahakan", "jgn",
    "dilanjutkan", "diteruskan", "diterusin", "dilanjut",
    "lanjutkan", "teruskan",  # only safe inside "jangan X" combos
    # "enough" family
    "cukup", "udahan", "udah", "dahan", "gustu", "sampai",
    "sini", "disini", "di", "situ",
    # english support
    "enough", "thats", "that's", "it", "now", "please", "pls",
    "task", "the", "a", "an", "it's", "its",
    # indonesian fillers
    "ya", "yah", "aja", "saja", "dulu", "dah", "deh", "dong",
    "nya", "nih", "tuh", "gitu", "gitu", "intent", "ini",
})
# A "jangan/stop … lanjutkan/teruskan" combo is a stop; a bare "lanjutkan"
# (continue!) is the OPPOSITE and must never count.
_CONTINUE_ONLY_RE = re.compile(r"^(lanjut(kan)?|terus(kan)?|continue|go on|resume)\b", re.IGNORECASE)
_STOP_MAX_TOKENS = 8


# ── Demonstration-request detector (deterministic agent-mode lock) ────
# The semantic classifier is unstable on short Indonesian demo requests
# ("Coba contohkan saya ingin melihat nya" flipped discuss↔agent across
# runs) and the planner answered them with 0 steps + words. These phrases
# are unambiguous: the user wants to SEE something produced. A precise
# pattern list beats a wobbling model call here — worst case the agent
# produces a real example instead of chatting.
_DEMO_REQUEST_RE = re.compile(
    r"(\bcontoh(kan|in|nya)?\b|\bkasih\s+contoh\b|\bberi(kan)?\s+contoh\b"
    r"|\bcoba\s+contoh\b|\bcontoh\s+dong\b|\bperlihatkan\b|\btunjuk(kan|in)?\b"
    r"|\bdemokan\b|\bdemo\s+(dong|dulu)\b|\bsaya\s+(ingin|mau|pengen)\s+(melihat|lihat)\b"
    r"|\bpengen\s+lihat\b|\bmau\s+lihat\b|\bbiar\s+saya\s+lihat\b"
    r"|\bshow\s+(me|us)\b|\bgive\s+(me\s+)?an?\s+example\b|\bdemonstrate\b"
    r"|\blet\s+me\s+see\b)",
    re.IGNORECASE,
)


def looks_like_demonstration_request(text: str) -> bool:
    """True when the message asks to be SHOWN something real.

    Used as a deterministic lock: such messages always run as agent work
    (plan + tools), never as pure chat, and a 0-step plan for them is
    rescued with a demonstration step.
    """
    return bool(_DEMO_REQUEST_RE.search(text or ""))


def looks_like_stop_request(text: str) -> bool:
    """True when the message is a short, explicit request to STOP working.

    Requires EVERY content word to be stop vocabulary or a known filler, so
    mixed instructions ("stop, lanjut ke step 3") stay out. A bare
    "lanjutkan"/"continue" is never a stop.
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 80:
        return False
    if _CONTINUE_ONLY_RE.match(raw):
        return False
    tokens = [t for t in _TOKEN_SPLIT.split(raw.lower()) if t]
    tokens = [t for t in tokens if any(c.isalnum() for c in t)]
    if not tokens or len(tokens) > _STOP_MAX_TOKENS:
        return False
    if not all(t in _STOP_WORDS for t in tokens):
        return False
    # Must contain at least one REAL stop command word — pure filler
    # ("ya dah" alone is ambiguous) still requires an explicit verb.
    explicit = {"stop", "stopped", "stopp", "stoppp", "berhenti",
                "berhentikan", "hentikan", "halt", "abort", "batalkan",
                "batal", "cancel", "canceled", "cancelled", "enough",
                "cukup", "udahan", "jangan", "janganlah", "jgn",
                "dilanjutkan", "diteruskan", "diterusin", "dilanjut",
                "udah"}
    return any(t in explicit for t in tokens)


def stop_acknowledgement(message_text: str) -> str:
    """The assistant's reply when the user stops the task by text.

    Language follows the stop message itself (Indonesian stop words →
    Indonesian reply). States that the task is closed and progress kept.
    """
    lowered = (message_text or "").lower()
    indonesian = any(w in lowered for w in (
        "berhenti", "hentikan", "jangan", "cukup", "udahan", "batalkan",
        "batal", "dilanjutkan", "diteruskan", "udah", "sini",
    ))
    if indonesian:
        return (
            "Baik, task saya hentikan di sini — tidak dilanjutkan. "
            "Semua progres yang sudah dibuat sudah disimpan dan plan saya "
            "tandai selesai.\n\n"
            "Kalau nanti mau menyambung lagi, kirim pesan apa saja dan saya "
            "lanjutkan dari titik terakhir."
        )
    return (
        "Okay — I've stopped here as requested; this task will not continue. "
        "All progress made so far is saved and the plan is marked complete.\n\n"
        "Send any message whenever you want me to pick it back up from the "
        "last stopping point."
    )


def stopped_by_button_notice() -> str:
    """The fixed user-facing line emitted when the STOP button is pressed."""
    return "Dzeck telah berhenti, kirim pesan baru untuk melanjutkan."
