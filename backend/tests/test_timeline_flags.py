"""Tests for the Manus-style unified timeline contract:

1. ask_user questions carry is_question=True (they must stay standalone in
   the chat — visible, pausing the task — and NEVER be swallowed by the
   step timeline).
2. Progress narrations carry is_progress=True (rendered INSIDE the timeline).
3. The final summary carries is_final=True (standalone, single file delivery).
4. SSE serialization round-trips all three flags so the frontend grouping
   receives them intact — for live streams AND session-history replays.
"""

import pytest

from app.domain.models.event import MessageEvent
from app.interfaces.schemas.event import MessageSSEEvent, EventMapper


def test_ask_user_question_flag():
    # Emission site: execution.py ask_user CALLING → is_question=True
    msg = MessageEvent(message="Data untuk kota mana yang Anda inginkan?", is_question=True)
    assert msg.is_question is True
    assert msg.is_progress is False
    assert msg.is_final is False


def test_progress_narration_flag():
    msg = MessageEvent(role="assistant", message="Menulis file laporan.md", is_progress=True)
    assert msg.is_progress is True
    assert msg.is_question is False


def test_final_summary_flag():
    msg = MessageEvent(role="assistant", message="# Ringkasan", is_final=True)
    assert msg.is_final is True
    assert msg.is_question is False


@pytest.mark.anyio
async def test_sse_roundtrip_preserves_flags():
    """The SSE payload must carry is_progress / is_final / is_question so the
    frontend timeline grouping works on both live and replay paths."""
    for kwargs in (
        {"is_progress": True},
        {"is_final": True},
        {"is_question": True},
        {},  # default plain message (ack)
    ):
        event = MessageEvent(role="assistant", message="teks", **kwargs)
        sse = await MessageSSEEvent.from_event_async(event)
        assert sse.data.is_progress == kwargs.get("is_progress", False)
        assert sse.data.is_final == kwargs.get("is_final", False)
        assert sse.data.is_question == kwargs.get("is_question", False)


@pytest.mark.anyio
async def test_event_mapper_roundtrip():
    """events_to_sse_events (session-history replay path) keeps the flags."""
    events = [
        MessageEvent(role="user", message="halo"),
        MessageEvent(role="assistant", message="Baik, saya mulai."),
        MessageEvent(role="assistant", message="Menjalankan perintah shell", is_progress=True),
        MessageEvent(role="assistant", message="Pilih kota mana?", is_question=True),
        MessageEvent(role="assistant", message="# Ringkasan akhir", is_final=True),
    ]
    mapped = await EventMapper.events_to_sse_events(events)
    assert len(mapped) == 5
    flags = [(m.data.is_progress, m.data.is_question, m.data.is_final) for m in mapped]
    assert flags == [
        (False, False, False),  # user
        (False, False, False),  # ack
        (True, False, False),   # progress narration
        (False, True, False),   # question
        (False, False, True),   # final summary
    ]
