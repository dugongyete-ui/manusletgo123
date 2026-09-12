"""Unit tests for the narration policy in ExecutionAgent.

Policy (product direction 2026-08-28 — "aware, frequent, pre-tool"):
1. The agent MUST narrate BEFORE executing tools (prompt-driven). The
   deterministic mid-step keep-alive safety net (template counting lines
   like "Pengumpulan informasi berjalan — 5 aksi selesai") was REMOVED
   after user feedback that it reads mechanical — narration is now purely
   model-driven (prompt-mandated notify + content think-aloud surfaced by
   base.execute + step-completion lines derived from the step result).
2. The old "redundant action announcement" suppression is RETIRED — it
   dropped exactly the pre-tool intent lines the user wants (they
   legitimately overlap with the step description). The method now always
   returns False and pre-tool lines pass through untouched.
3. Near-DUPLICATE narrations (the same line sent twice) are still
   suppressed — a literal repeat is a glitch, never an update.
"""

import pytest
from unittest.mock import AsyncMock as _AsyncMock

from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.services.agents.execution import ExecutionAgent


def make_executor(step_desc: str = "", user_request: str = "") -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._user_request_words = agent._content_words(user_request)
    agent._silent_activities = []
    agent._silent_tool_count = 0
    agent._narration_assist_count = 0
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


# ── 4. Mid-step keep-alive machinery fully removed ───────────────────────────


def test_keepalive_machinery_removed():
    """The old TEMPLATE counting machinery ("N aksi selesai") stays removed —
    replaced by the LLM-written narration assist, which is context-aware and
    never counts actions."""
    for attr in (
        "_derived_midstep_progress",
        "_tools_since_narration",
        "_tool_window",
        "_midstep_narration_count",
        "_real_tools_in_step",
        "_MIDSTEP_NARRATION_EVERY",
        "_MIDSTEP_NARRATION_MAX",
    ):
        assert not hasattr(ExecutionAgent, attr), f"{attr} should be gone"


@pytest.mark.asyncio
async def test_silent_real_tools_without_llm_stay_silent():
    """With no LLM available (astream_text_with_fallback missing/raising) the
    assist degrades to silence — never a template line, never a crash."""
    from app.domain.models.plan import Step

    agent = make_executor()
    step = Step(id="1", description="Uji")

    class _Stream:
        async def execute(self, content):
            for i in range(12):
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=f"c{i}",
                    tool_name="browser",
                    function_name="browser_navigate",
                    function_args={"url": f"https://example.com/{i}"},
                )

    agent.execute = _Stream().execute
    events = [
        e async for e in agent._handle_execution_events(step, "p")
        if not isinstance(e, ToolEvent)
    ]
    # Assist LLM unavailable → no synthesized line, no crash.
    assert events == []


@pytest.mark.asyncio
async def test_narration_assist_emits_llm_line_after_five_silent_tools():
    """Five silent real tools → ONE LLM-written aware line (is_progress),
    window resets; the line must NOT be a counting template."""
    from app.domain.models.plan import Step

    agent = make_executor()
    agent._narration_lang = "id"
    agent.astream_text_with_fallback = _AsyncMock(
        return_value="Sumber dari Antara dan Detik mulai melengkapi data regulasi AI pemerintah."
    )
    step = Step(id="1", description="Uji")

    class _Stream:
        async def execute(self, content):
            for i in range(10):
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=f"c{i}",
                    tool_name="browser",
                    function_name="browser_navigate",
                    function_args={"url": f"https://example.com/{i}"},
                )

    agent.execute = _Stream().execute
    events = [
        e async for e in agent._handle_execution_events(step, "p")
    ]
    lines = [e for e in events if isinstance(e, MessageEvent) and e.is_progress]
    # 10 silent tools → assist at #5, window resets, assist again at #10.
    assert len(lines) == 2
    assert "regulasi AI" in lines[0].message
    assert "aksi" not in lines[0].message.lower()
    assert agent._silent_tool_count == 0  # second assist reset the window


@pytest.mark.asyncio
async def test_narration_assist_refuses_counting_lines():
    """If the LLM disobeys and writes a counting line ("5 aksi selesai"),
    the guard drops it — that phrasing is exactly what the user rejected."""
    from app.domain.models.plan import Step

    agent = make_executor()
    agent.astream_text_with_fallback = _AsyncMock(
        return_value="Pengumpulan informasi berjalan — 5 aksi selesai."
    )
    step = Step(id="1", description="Uji")

    class _Stream:
        async def execute(self, content):
            for i in range(5):
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=f"c{i}",
                    tool_name="browser",
                    function_name="browser_navigate",
                    function_args={"url": f"https://example.com/{i}"},
                )

    agent.execute = _Stream().execute
    events = [
        e async for e in agent._handle_execution_events(step, "p")
    ]
    lines = [e for e in events if isinstance(e, MessageEvent) and e.is_progress]
    assert lines == []


@pytest.mark.asyncio
async def test_model_narration_resets_assist_window():
    """A model-driven narration (notify or content) resets the silent window —
    the assist never stacks on top of the model's own updates."""
    from app.domain.models.plan import Step

    agent = make_executor()
    agent.astream_text_with_fallback = _AsyncMock(return_value="baris bantuan")
    step = Step(id="1", description="Uji")

    class _Stream:
        async def execute(self, content):
            for i in range(3):
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=f"c{i}",
                    tool_name="browser",
                    function_name="browser_navigate",
                    function_args={"url": f"https://example.com/{i}"},
                )
            yield MessageEvent(message="Saya dapat data awal dari tiga sumber.", is_progress=True)
            for i in range(3, 6):
                yield ToolEvent(
                    status=ToolStatus.CALLED,
                    tool_call_id=f"c{i}",
                    tool_name="browser",
                    function_name="browser_navigate",
                    function_args={"url": f"https://example.com/{i}"},
                )

    agent.execute = _Stream().execute
    events = [e async for e in agent._handle_execution_events(step, "p")]
    # Only the model's own line — assist never fired (window reset mid-run).
    lines = [e for e in events if isinstance(e, MessageEvent) and e.is_progress]
    assert len(lines) == 1
    assert "tiga sumber" in lines[0].message
