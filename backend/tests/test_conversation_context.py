"""Regression tests for the AI conversation-context fix (Task 23).

Bug (live session 8b84dc9efe5946d5, screenshot 2026-08-30):
    User asked a follow-up "Sebelumnya kita bahas apa?" in a session whose
    first turn had produced a full Persib Bandung report. The assistant
    answered "Saya tidak memiliki riwayat percakapan sebelumnya" — while the
    planner, running in parallel WITH agent memory, produced the correct
    contextual answer that was then thrown away.

Root cause:
    The streamed first reply (PlannerAgent._acknowledgement_chunks) is the
    model call that actually answers conversational follow-ups (0-step plans),
    but it was deliberately memory-free — it saw ONLY the current message.

Fix:
    1. PlanActFlow._build_conversation_digest(session, message) — compact
       transcript from the session's persisted events (user/assistant turns,
       progress narration excluded, current message excluded, capped sizes).
    2. Both engines pass the digest to acknowledge_stream(message, history).
    3. The reply prompt injects the transcript and instructs the model to
       treat it as its own memory — never claim amnesia when history exists.
"""

import pytest
from langchain_core.messages import AIMessage

from app.domain.models.event import MessageEvent
from app.domain.models.message import Message
from app.domain.services.agents.planner import PlannerAgent
from app.domain.services.flows.plan_act import PlanActFlow
from app.domain.services.flows.plan_act_graph import PlanActGraphFlow


# ─────────────────────────────────────────────────────────────────────────────
# Digest builder
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self, events):
        self.events = events


def _msg_events(*pairs, progress=()):
    evs = [MessageEvent(role=r, message=m) for r, m in pairs]
    evs += [MessageEvent(role="assistant", message=m, is_progress=True) for m in progress]
    return evs


def test_digest_contains_prior_turns_and_excludes_current_and_progress():
    events = _msg_events(
        ("user", "Carikan informasi tentang Persib Bandung 2026"),
        ("assistant", "Sedang mencari, satu saat ya."),
        ("assistant", "# Laporan Persib 2026\n\nIsi laporan lengkap..."),
        ("user", "Sebelumnya kita bahas apa?"),  # early-persisted CURRENT msg
        progress=("mengunduh halaman…", "menulis file…"),
    )
    digest = PlanActFlow._build_conversation_digest(
        _FakeSession(events), Message(message="Sebelumnya kita bahas apa?")
    )
    assert "User: Carikan informasi tentang Persib Bandung 2026" in digest
    assert "Assistant: Sedang mencari, satu saat ya." in digest
    assert "Assistant: # Laporan Persib 2026" in digest
    assert "mengunduh halaman" not in digest           # progress narration
    assert "menulis file" not in digest
    assert "Sebelumnya kita bahas apa?" not in digest  # current message
    # Ordering: oldest → newest
    assert digest.index("Carikan") < digest.index("Sedang mencari") < digest.index("Laporan")


def test_digest_empty_for_first_message():
    assert PlanActFlow._build_conversation_digest(
        _FakeSession([]), Message(message="Halo")
    ) == ""


def test_digest_session_without_events_attribute():
    """Flow mocks (and any repository variant) may lack .events — no crash."""
    session = type("S", (), {})()
    assert PlanActFlow._build_conversation_digest(session, Message(message="Hai")) == ""


def test_digest_accepts_raw_dict_events():
    """Defensive path: dict-shaped events still produce a transcript."""
    events = [
        {"type": "message", "role": "user", "message": "Buat laporan", "is_progress": False},
        {"type": "plan", "steps": []},  # non-message events ignored
        {"type": "message", "role": "assistant", "message": "Laporan siap.", "is_progress": False},
    ]
    digest = PlanActFlow._build_conversation_digest(
        _FakeSession(events), Message(message="Lanjut")
    )
    assert "User: Buat laporan" in digest
    assert "Assistant: Laporan siap." in digest


def test_digest_truncates_each_message():
    long_text = "x" * 2000
    events = _msg_events(("assistant", long_text))
    digest = PlanActFlow._build_conversation_digest(
        _FakeSession(events), Message(message="next")
    )
    assert len(digest) < 700
    assert digest.endswith("…")


def test_digest_keeps_newest_within_global_budget():
    """Over-budget transcripts keep the NEWEST turns."""
    events = _msg_events(*[
        ("user", f"Pertanyaan nomor {i} yang panjang " + "y" * 400) for i in range(20)
    ])
    digest = PlanActFlow._build_conversation_digest(
        _FakeSession(events), Message(message="next")
    )
    assert len(digest) <= PlanActFlow._DIGEST_MAX_TOTAL_CHARS
    assert "Pertanyaan nomor 19" in digest   # newest kept
    assert "Pertanyaan nomor 0" not in digest  # oldest dropped


def test_digest_caps_turn_count():
    """At most _DIGEST_MAX_MESSAGES conversational turns are kept (newest)."""
    events = _msg_events(*[
        ("user", f"pesan {i}") for i in range(30)
    ])
    digest = PlanActFlow._build_conversation_digest(
        _FakeSession(events), Message(message="next")
    )
    assert "pesan 29" in digest
    assert "pesan 13" not in digest   # beyond the 16-newest window
    assert "pesan 0" not in digest


def test_graph_engine_inherits_identical_digest():
    """LangGraph engine uses the SAME builder (parity requirement)."""
    events = _msg_events(
        ("user", "Halo"), ("assistant", "Hai, ada yang bisa dibantu?")
    )
    msg = Message(message="Sebelumnya apa?")
    a = PlanActFlow._build_conversation_digest(_FakeSession(events), msg)
    b = PlanActGraphFlow._build_conversation_digest(_FakeSession(events), msg)
    assert a == b
    assert "Halo" in a


# ─────────────────────────────────────────────────────────────────────────────
# Prompt injection (PlannerAgent._acknowledgement_chunks)
# ─────────────────────────────────────────────────────────────────────────────

class _CapturingModel:
    def __init__(self, response="Baik."):
        self.response = response
        self.calls: list = []

    async def astream(self, messages):
        self.calls.append(messages)
        yield AIMessage(content=self.response)


def _planner_with_capture(response="Baik."):
    agent = PlannerAgent.__new__(PlannerAgent)
    agent._model = _CapturingModel(response)
    return agent


@pytest.mark.asyncio
async def test_ack_prompt_includes_history_block():
    agent = _planner_with_capture()
    history = (
        "User: Carikan informasi tentang Persib Bandung 2026\n"
        "Assistant: # Laporan Persib 2026 ..."
    )
    async for _ in agent._acknowledgement_chunks(
        Message(message="Sebelumnya kita bahas apa?"), history
    ):
        pass

    assert len(agent._model.calls) == 1
    system_msg, user_msg = agent._model.calls[0]
    # System prompt: history must be treated as the assistant's own memory
    assert "treat them as your own memory" in system_msg.content
    # User prompt: transcript block present, current message labelled
    prompt = user_msg.content
    assert "[Conversation so far in this session" in prompt
    assert "User: Carikan informasi tentang Persib Bandung 2026" in prompt
    assert "[Current user message]" in prompt
    assert "Sebelumnya kita bahas apa?" in prompt
    # Anti-amnesia instruction
    assert "NEVER claim you have no memory" in prompt


@pytest.mark.asyncio
async def test_ack_prompt_without_history_has_no_history_block():
    agent = _planner_with_capture()
    async for _ in agent._acknowledgement_chunks(
        Message(message="Buat website"), None
    ):
        pass

    prompt = agent._model.calls[0][1].content
    assert "[Conversation so far" not in prompt
    assert "[Current user message]" in prompt
    # First message: no anti-amnesia instruction leak is fine, but the
    # current message must still be the reply target.
    assert "Buat website" in prompt


@pytest.mark.asyncio
async def test_acknowledge_stream_forwards_history():
    agent = _planner_with_capture("Sebelumnya kita membahas laporan Persib.")
    events = [
        e async for e in agent.acknowledge_stream(
            Message(message="Sebelumnya kita bahas apa?"),
            "User: tanya Persib\nAssistant: laporan siap",
        )
    ]
    # The final atomic MessageEvent is the persisted, user-visible answer
    assert events[-1].message == "Sebelumnya kita membahas laporan Persib."
    prompt = agent._model.calls[0][1].content
    assert "User: tanya Persib" in prompt


@pytest.mark.asyncio
async def test_acknowledge_non_streaming_forwards_history():
    agent = _planner_with_capture("Kita membahas Persib Bandung.")
    events = [
        e async for e in agent.acknowledge(
            Message(message="Sebelumnya kita bahas apa?"), "User: tanya Persib"
        )
    ]
    assert len(events) == 1
    assert events[0].message == "Kita membahas Persib Bandung."
    assert "User: tanya Persib" in agent._model.calls[0][1].content
