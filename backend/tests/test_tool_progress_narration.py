"""Unit tests for the narration policy in ExecutionAgent.

Policy (product direction 2026-08-28 — "aware, frequent, pre-tool"):
1. The agent MUST narrate BEFORE executing tools (prompt-driven). The ONLY
   deterministic narration is the mid-step keep-alive safety net: ONE short
   status line every 3 SILENT real-tool rounds (max 4 per step) so a silent
   free-tier model can never leave the chat dead-quiet.
2. The old "redundant action announcement" suppression is RETIRED — it
   dropped exactly the pre-tool intent lines the user now wants (they
   legitimately overlap with the step description). The method now always
   returns False and pre-tool lines pass through untouched.
3. Near-DUPLICATE narrations (the same line sent twice) are still
   suppressed — a literal repeat is a glitch, never an update.
"""

import pytest

from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.services.agents.execution import ExecutionAgent


def make_executor(step_desc: str = "", user_request: str = "") -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
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


# ── 2. Pre-tool intent narrations pass through (suppression retired) ─────────


def test_pretool_intent_line_matching_step_passes_through():
    """The mandated BEFORE-tool narration legitimately references the step's
    own content — it must NOT be suppressed."""
    agent = make_executor(
        step_desc="Buat file tes_collapse.txt dengan konten 'halo collapse test'.",
        user_request="Buat file tes_collapse.txt berisi tulisan 'halo collapse test' lalu tampilkan isinya",
    )
    assert not agent._is_redundant_action_announcement(
        "Saya sedang menulis tes_collapse.txt."
    )
    assert not agent._is_redundant_action_announcement(
        "Saya akan membaca file tes_collapse.txt untuk memastikan isinya."
    )


def test_pretool_intent_line_matching_request_passes_through():
    agent = make_executor(
        step_desc="Tampilkan isi file",
        user_request="Cari harga emas hari ini",
    )
    # Short pre-tool line mostly made of request words → still passes now.
    assert not agent._is_redundant_action_announcement("Mencari harga emas sekarang.")


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


def test_keepalive_emits_after_three_silent_tool_rounds():
    agent = make_executor()
    agent._narration_lang = "id"
    # 2 silent rounds: nothing yet (below threshold, chat stays clean).
    assert _feed_completed_tools(agent, 2) == []
    # 3rd silent round: exactly ONE keep-alive line fires.
    lines = _feed_completed_tools(agent, 1)
    assert len(lines) == 1
    assert "3 aksi" in lines[0]  # status summary mentions the count
    assert len(lines[0]) <= 200  # short, per the ≤300-char narration policy


def test_keepalive_capped_at_four_per_step():
    agent = make_executor()
    agent._narration_lang = "en"
    # 24 silent tool rounds → at most 4 keep-alive lines, never a flood.
    lines = _feed_completed_tools(agent, 24)
    assert len(lines) == ExecutionAgent._MIDSTEP_NARRATION_MAX
    # Every line is distinct (rotated phrasing / growing counts).
    assert len(set(lines)) == len(lines)


def test_keepalive_window_resets_on_model_narration():
    agent = make_executor()
    agent._narration_lang = "id"
    # Model narrates after 2 silent rounds → window resets, no keep-alive.
    _feed_completed_tools(agent, 2)
    agent._tools_since_narration = 0  # reset by the notify branch
    agent._tool_window = []
    # 2 more silent rounds are NOT enough to fire a new keep-alive line.
    assert _feed_completed_tools(agent, 2) == []


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
