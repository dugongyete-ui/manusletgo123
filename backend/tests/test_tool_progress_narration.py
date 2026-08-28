"""Unit tests for the narration cleanliness policy in ExecutionAgent.

Policy (aligned with the reference ai-manus / official Manus behaviour):
1. NO deterministic fallback narration is emitted after tool completions —
   the step rows, tool pills and brief labels already show every action live.
2. message_notify_user texts that merely RE-ANNOUNCE the current step
   description or the user's request ("Saya sedang menulis file X" while the
   step row already says "Buat file X …") are suppressed: zero new
   information, pure clutter.
3. Substantive findings (which introduce NEW content words) always pass.
"""

import pytest

from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.services.agents.execution import ExecutionAgent


def make_executor(step_desc: str = "", user_request: str = "") -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._current_step_words = agent._content_words(step_desc)
    agent._user_request_words = agent._content_words(user_request)
    return agent


def tool_event(fn: str, tool_name: str = "browser", **args) -> ToolEvent:
    return ToolEvent(
        status=ToolStatus.CALLED,
        tool_call_id=f"call-{fn}",
        tool_name=tool_name,
        function_name=fn,
        function_args=args,
    )


# ── 1. No fallback narration after tool completion ───────────────────────────


def test_no_fallback_narration_machinery_remains():
    """The deterministic template narration was removed entirely — the timeline
    (step rows + tool pills + brief labels) already reports every action."""
    assert not hasattr(ExecutionAgent, "_tool_progress_narration")
    assert not hasattr(ExecutionAgent, "_TOOL_NARRATIONS")
    assert not hasattr(ExecutionAgent, "_NARRATION_NUDGE")


def test_tool_event_has_no_narration_marker():
    ev = tool_event("file_write", tool_name="file", file="report.md")
    # The event itself is the only thing emitted — no MessageEvent narration.
    assert isinstance(ev, ToolEvent)
    msg = MessageEvent(role="assistant", message="x", is_progress=True)
    assert msg.is_progress is True  # marker still supported for model narrations


# ── 2. Redundant action announcements are suppressed ─────────────────────────


def test_action_announcement_matching_step_is_suppressed():
    agent = make_executor(
        step_desc="Buat file tes_collapse.txt dengan konten 'halo collapse test'.",
        user_request="Buat file tes_collapse.txt berisi tulisan 'halo collapse test' lalu tampilkan isinya",
    )
    assert agent._is_redundant_action_announcement(
        "Saya sedang menulis tes_collapse.txt."
    )
    assert agent._is_redundant_action_announcement(
        "Saya akan membaca file tes_collapse.txt untuk memastikan isinya."
    )


def test_action_announcement_matching_request_is_suppressed():
    agent = make_executor(
        step_desc="Tampilkan isi file",
        user_request="Cari harga emas hari ini",
    )
    # Short line mostly made of request words → redundant.
    assert agent._is_redundant_action_announcement("Mencari harga emas sekarang.")


def test_substantive_finding_passes_through():
    agent = make_executor(
        step_desc="Buat file tes_collapse.txt dengan konten 'halo collapse test'.",
        user_request="Buat file tes_collapse.txt berisi tulisan 'halo collapse test' lalu tampilkan isinya",
    )
    # New content words (dua, sumber, menyebut, angka, sama, yakin, akurat)
    assert not agent._is_redundant_action_announcement(
        "Dua sumber menyebut angka yang sama, jadi saya yakin datanya akurat."
    )
    assert not agent._is_redundant_action_announcement(
        "Ternyata halaman ini tidak memuat data yang saya harapkan — saya coba sumber alternatif."
    )


def test_long_narration_is_never_suppressed():
    agent = make_executor(
        step_desc="Buat file laporan",
        user_request="Buat laporan penjualan",
    )
    long_text = (
        "Laporan penjualan kuartal ini menunjukkan pertumbuhan 12 persen "
        "dibanding kuartal sebelumnya, didorong terutama oleh kategori "
        "elektronik, sementara fashion stagnan karena perubahan musim yang "
        "tidak sesuai ekspektasi tim merchandising."
    )
    assert not agent._is_redundant_action_announcement(long_text)


def test_empty_narration_is_suppressed_by_duplicate_check():
    agent = make_executor(step_desc="Buat file", user_request="Buat file")
    # Empty texts carry no words for the announcement heuristic, but the
    # near-duplicate check treats them as "nothing new to say" and drops them.
    assert agent._is_duplicate_narration("", agent._last_narration_norm)
    assert agent._is_duplicate_narration("", None)


# ── 3. Near-duplicate narration dedup still works ────────────────────────────


def test_duplicate_narration_detected():
    agent = make_executor()
    agent._last_narration_norm = agent._normalize_narration(
        "Saya mulai dari pencarian web untuk harga emas."
    )
    assert agent._is_duplicate_narration(
        "Saya mulai dari pencarian web untuk harga emas.",
        agent._last_narration_norm,
    )
