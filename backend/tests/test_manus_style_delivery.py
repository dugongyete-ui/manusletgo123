"""Unit tests for the Manus-style delivery & narration behaviour:

1. Files created mid-task are NEVER attached to mid-task messages — they are
   deferred and delivered once, with the final (is_final) summary message.
2. Near-duplicate progress narrations are suppressed (both CALLING and the
   matching CALLED event) so the chat stream stays clean.
"""

import pytest

from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.models.plan import Plan, Step
from app.domain.services.agents.execution import ExecutionAgent


def make_executor() -> ExecutionAgent:
    """ExecutionAgent skeleton without touching settings/model providers."""
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    return agent


def notify_call_event(text: str, attachments=None, call_id="c1") -> ToolEvent:
    return ToolEvent(
        status=ToolStatus.CALLING,
        tool_call_id=call_id,
        tool_name="message",
        function_name="message_notify_user",
        function_args={"text": text, **({"attachments": attachments} if attachments else {})},
    )


def notify_done_event(text: str, attachments=None, call_id="c1") -> ToolEvent:
    return ToolEvent(
        status=ToolStatus.CALLED,
        tool_call_id=call_id,
        tool_name="message",
        function_name="message_notify_user",
        function_args={"text": text, **({"attachments": attachments} if attachments else {})},
        function_result="OK",
    )


class _ExecStream:
    """Feeds a fixed list of events through _handle_execution_events."""

    def __init__(self, events):
        self._events = events

    async def execute(self, content):
        for e in self._events:
            yield e


@pytest.mark.asyncio
async def test_notify_attachments_deferred_not_delivered_midtask():
    """A notify call carrying file paths must NOT produce a message with
    attachments — the paths are deferred for the final summary."""
    agent = make_executor()
    step = Step(id="1", description="Buat file laporan")
    agent.execute = _ExecStream(
        [notify_call_event("File laporan siap.", ["/home/runner/laporan.md"])]
    ).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    # Only the ToolEvent passes through — pure text, no attachment delivery.
    assert len(events) == 1
    assert isinstance(events[0], ToolEvent)
    # The file was recorded for the final summary instead.
    assert agent._deferred_attachments == ["/home/runner/laporan.md"]


@pytest.mark.asyncio
async def test_duplicate_narration_suppressed_with_its_called_event():
    """Identical notify text sent twice: the second CALLING *and* its CALLED
    event are both suppressed so no duplicate bubble can render."""
    agent = make_executor()
    step = Step(id="1", description="Uji")
    agent.execute = _ExecStream(
        [
            notify_call_event("Memulai pengujian browser.", call_id="c1"),
            notify_done_event("Memulai pengujian browser.", call_id="c1"),
            notify_call_event("Memulai pengujian browser.", call_id="c2"),
            notify_done_event("Memulai pengujian browser.", call_id="c2"),
        ]
    ).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]

    # Only the first CALLING + its CALLED survive.
    ids = [(e.tool_call_id, e.status) for e in events]
    assert ids == [("c1", ToolStatus.CALLING), ("c1", ToolStatus.CALLED)]


@pytest.mark.asyncio
async def test_near_duplicate_narration_suppressed():
    """Reworded near-duplicates (Jaccard >= 0.7) count as duplicates too —
    exactly the glitch seen in the user's screenshot."""
    agent = make_executor()
    step = Step(id="1", description="Uji")
    agent.execute = _ExecStream(
        [
            notify_call_event(
                "Memulai pengujian tools browser: membuka halaman Wikipedia "
                "untuk menguji navigasi, klik, input, dropdown, scroll.",
                call_id="a",
            ),
            notify_done_event(
                "Memulai pengujian tools browser: membuka halaman Wikipedia "
                "untuk menguji navigasi, klik, input, dropdown, scroll.",
                call_id="a",
            ),
            notify_call_event(
                "Memulai pengujian tools browser: membuka halaman contoh "
                "untuk menguji navigasi, klik, input, dropdown, scroll.",
                call_id="b",
            ),
            notify_done_event(
                "Memulai pengujian tools browser: membuka halaman contoh "
                "untuk menguji navigasi, klik, input, dropdown, scroll.",
                call_id="b",
            ),
        ]
    ).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]
    ids = {(e.tool_call_id, e.status) for e in events}
    assert ("b", ToolStatus.CALLING) not in ids
    assert ("b", ToolStatus.CALLED) not in ids


@pytest.mark.asyncio
async def test_distinct_narrations_pass_through():
    """Genuinely different narrations all reach the user."""
    agent = make_executor()
    step = Step(id="1", description="Uji")
    agent.execute = _ExecStream(
        [
            notify_call_event("Konfigurasi server sudah diverifikasi.", call_id="c1"),
            notify_done_event("Konfigurasi server sudah diverifikasi.", call_id="c1"),
            notify_call_event("Instalasi dependensi selesai tanpa error.", call_id="c2"),
            notify_done_event("Instalasi dependensi selesai tanpa error.", call_id="c2"),
        ]
    ).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]
    assert len(events) == 4


@pytest.mark.asyncio
async def test_empty_narration_suppressed():
    agent = make_executor()
    step = Step(id="1", description="Uji")
    agent.execute = _ExecStream(
        [notify_call_event("   ", call_id="c1"), notify_done_event("", call_id="c1")]
    ).execute

    events = [e async for e in agent._handle_execution_events(step, "prompt")]
    assert events == []


def test_is_duplicate_narration_basics():
    f = ExecutionAgent._is_duplicate_narration
    assert f("Sama persis", "sama persis") is True
    assert f("Halo dunia", "Selamat pagi semua") is False
    assert f("", "apa pun") is True  # empty says nothing new
    assert f("Pesan baru", None) is False
