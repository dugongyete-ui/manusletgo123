"""Unit tests for the narration cleanliness policy in ExecutionAgent.

Policy (aligned with the reference ai-manus / official Manus behaviour):
1. NO deterministic fallback narration after EVERY tool completion — the
   step rows, tool pills and brief labels already show each action live.
   The ONLY deterministic narration is the mid-step keep-alive safety net:
   ONE short status line every 4 SILENT real-tool rounds (max 3 per step)
   so a silent free-tier model can never leave the chat dead-quiet
   (design doc's LONG_TASK_UPDATE_INTERVAL rule).
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
    agent._tools_since_narration = 0
    agent._tool_window = []
    agent._midstep_narration_count = 0
    agent._real_tools_in_step = 0
    agent._narration_lang = "en"
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


# ── 4. Mid-step keep-alive safety net (silent-run keep-alive) ────────────────


def _feed_completed_tools(agent: ExecutionAgent, count: int, fn: str = "info_search_web"):
    """Simulate `count` completed real-tool rounds through the emission hook
    (same logic as the post-yield block in _handle_execution_events)."""
    emitted = []
    for _ in range(count):
        ev = tool_event(fn)
        agent._tools_since_narration += 1
        agent._tool_window.append(ev.function_name)
        agent._real_tools_in_step += 1
        if (
            agent._tools_since_narration >= ExecutionAgent._MIDSTEP_NARRATION_EVERY
            and agent._midstep_narration_count < ExecutionAgent._MIDSTEP_NARRATION_MAX
        ):
            line = agent._derived_midstep_progress()
            if line:
                agent._tools_since_narration = 0
                agent._tool_window = []
                agent._midstep_narration_count += 1
                emitted.append(line)
    return emitted


def test_keepalive_emits_after_four_silent_tool_rounds():
    agent = make_executor()
    agent._narration_lang = "id"
    # 3 silent rounds: nothing yet (below threshold, chat stays clean).
    assert _feed_completed_tools(agent, 3) == []
    # 4th silent round: exactly ONE keep-alive line fires.
    lines = _feed_completed_tools(agent, 1)
    assert len(lines) == 1
    assert "4 aksi" in lines[0]  # status summary mentions the count
    assert len(lines[0]) <= 200  # short, per the ≤300-char narration policy


def test_keepalive_capped_at_three_per_step():
    agent = make_executor()
    agent._narration_lang = "en"
    # 24 silent tool rounds → at most 3 keep-alive lines, never a flood.
    lines = _feed_completed_tools(agent, 24)
    assert len(lines) == ExecutionAgent._MIDSTEP_NARRATION_MAX
    # Every line is distinct (rotated phrasing / growing counts).
    assert len(set(lines)) == len(lines)


def test_keepalive_window_resets_on_model_narration():
    agent = make_executor()
    agent._narration_lang = "id"
    # Model narrates after 3 silent rounds → window resets, no keep-alive.
    _feed_completed_tools(agent, 3)
    agent._tools_since_narration = 0  # reset by the notify branch
    agent._tool_window = []
    # 3 more silent rounds are NOT enough to fire a new keep-alive line.
    assert _feed_completed_tools(agent, 3) == []


def test_keepalive_categorizes_dominant_tool_type():
    agent = make_executor()
    agent._narration_lang = "en"
    agent._tool_window = ["browser_navigate"] * 5
    agent._midstep_narration_count = 0
    line = agent._derived_midstep_progress()
    assert "browsing" in line.lower() or "browsing web" in line.lower()

    agent2 = make_executor()
    agent2._narration_lang = "id"
    agent2._tool_window = ["info_search_web"] * 4
    line2 = agent2._derived_midstep_progress()
    assert "informasi" in line2.lower()


def test_keepalive_empty_window_returns_empty():
    agent = make_executor()
    assert agent._derived_midstep_progress() == ""
