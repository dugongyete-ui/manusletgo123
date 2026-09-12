"""Task 20 — Summarize delivery-quality gate.

Live incident (session 8a54aca598f4450a): the final task message — the one
the user reads as the task's summary — was a raw legacy tool-call wire block:

    "\n<function=file_read>\n<parameter=file>\n.../Persib_Bandung_2026_Artikel.md\n</parameter>\n</function>\n"

The model came out of a tool-heavy execution context and, asked for a plain
text summary WITHOUT tools bound, streamed its next tool call as raw text.

These tests pin the recovery MECHANISM (format-level detection, no
task-specific strings anywhere):

1. wire-format-only stream        -> NOT delivered; JSON tool-loop fallback
                                     runs and its answer becomes the summary
2. empty stream                   -> NOT a silent return; fallback runs
3. prose + wire-format residue    -> prose delivered, residue stripped
4. clean prose                    -> delivered unchanged (regression guard)
5. fallback progress narration    -> passes through as progress, never
                                     re-delivered as the final answer
6. fallback non-JSON final        -> wire-format stripped before delivery
7. planner acknowledgement        -> wire-format residue stripped
8. narration assist line          -> wire-format-only line suppressed
"""

import json
from types import SimpleNamespace

import pytest

from app.domain.models.event import MessageEvent
from app.domain.services.agents.execution import ExecutionAgent
from app.domain.services.agents.planner import PlannerAgent
from app.domain.services.agents.base import _strip_function_syntax

WIRE_ONLY = (
    "\n<function=file_read>\n<parameter=file>\n"
    "/home/z/sandbox/users/u1/Persib_Bandung_2026_Artikel.md\n"
    "</parameter>\n</function>\n\n"
)
PROSE = (
    "Artikel lengkap tentang Persib Bandung 2026 sudah selesai dibuat. "
    "Skuad berisi 32 pemain dengan pelatih kepala Igor Tolic."
)
PROSE_PLUS_RESIDUE = "Ringkasan selesai.\n" + WIRE_ONLY


def make_executor(stream_text: str, fallback_events=None) -> ExecutionAgent:
    """ExecutionAgent skeleton with the summarize collaborators mocked.

    `stream_text` is what astream_text_with_fallback "streams";
    `fallback_events` (when given) is what the JSON tool-loop fallback
    (self.execute) yields. Recording flags verify which path ran.
    """
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent.calls = SimpleNamespace(stream=0, execute=0, decide=0)

    class _Mem:
        def get_messages(self):
            return []

    agent.memory = _Mem()

    async def _ensure_memory():
        return None

    async def astream_text_with_fallback(messages):
        agent.calls.stream += 1
        return stream_text

    async def _decide_and_create_summary_file(text, context, existing_attachments=None):
        agent.calls.decide += 1
        return []

    async def _drop_zip_member_attachments(attachments):
        return attachments

    def _resolve_user_home():
        return "/home/z/sandbox/users/u1"

    async def _parse_json(text):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    async def execute(request, format=None):
        agent.calls.execute += 1
        for e in fallback_events or []:
            yield e

    agent._ensure_memory = _ensure_memory
    agent.astream_text_with_fallback = astream_text_with_fallback
    agent._decide_and_create_summary_file = _decide_and_create_summary_file
    agent._drop_zip_member_attachments = _drop_zip_member_attachments
    agent._resolve_user_home = _resolve_user_home
    agent._parse_json = _parse_json
    agent.execute = execute
    return agent


async def collect(agent, **kwargs):
    return [e async for e in agent.summarize(**kwargs)]


# ── 1. wire-format-only stream → fallback ─────────────────────────────────


@pytest.mark.asyncio
async def test_wire_format_only_stream_never_reaches_user():
    """The incident case: raw <function=file_read> instead of a summary."""
    final_json = json.dumps({"message": PROSE, "attachments": []})
    agent = make_executor(
        stream_text=WIRE_ONLY,
        fallback_events=[MessageEvent(message=final_json)],
    )

    events = await collect(agent)

    assert agent.calls.stream == 1
    assert agent.calls.execute == 1, "must recover via the JSON tool-loop"
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1
    assert PROSE in finals[0].message
    assert "<function=" not in finals[0].message


@pytest.mark.asyncio
async def test_wire_format_only_stream_without_fallback_events_yields_nothing():
    """If the fallback also fails, never emit the wire-format garbage."""
    agent = make_executor(stream_text=WIRE_ONLY, fallback_events=[])
    events = await collect(agent)
    assert agent.calls.execute == 1
    assert not [e for e in events if isinstance(e, MessageEvent) and e.is_final]


# ── 2. empty stream → fallback (was: silent return) ───────────────────────


@pytest.mark.asyncio
async def test_empty_stream_falls_back_instead_of_silence():
    final_json = json.dumps({"message": PROSE, "attachments": []})
    agent = make_executor(
        stream_text="", fallback_events=[MessageEvent(message=final_json)]
    )
    events = await collect(agent)
    assert agent.calls.execute == 1
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1 and PROSE in finals[0].message


# ── 3. prose + residue → prose delivered, residue stripped ────────────────


@pytest.mark.asyncio
async def test_prose_with_residue_delivers_clean_prose():
    agent = make_executor(stream_text=PROSE_PLUS_RESIDUE)
    events = await collect(agent)
    assert agent.calls.execute == 0, "prose survives — no fallback needed"
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1
    assert finals[0].message.strip() == "Ringkasan selesai."
    assert "<function=" not in finals[0].message


# ── 4. clean prose → unchanged (regression) ───────────────────────────────


@pytest.mark.asyncio
async def test_clean_prose_unchanged():
    agent = make_executor(stream_text=PROSE)
    events = await collect(agent)
    assert agent.calls.execute == 0
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1 and finals[0].message == PROSE


# ── 5. fallback narration passthrough ─────────────────────────────────────


@pytest.mark.asyncio
async def test_fallback_progress_narration_not_promoted_to_final():
    narration = MessageEvent(message="Membaca file artikel…", is_progress=True)
    final_json = json.dumps({"message": PROSE, "attachments": []})
    agent = make_executor(
        stream_text=WIRE_ONLY,
        fallback_events=[narration, MessageEvent(message=final_json)],
    )
    events = await collect(agent)

    progress = [e for e in events if isinstance(e, MessageEvent) and e.is_progress]
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(progress) == 1 and "Membaca" in progress[0].message
    assert len(finals) == 1 and PROSE in finals[0].message


# ── 6. fallback non-JSON final → strip residue before delivery ────────────


@pytest.mark.asyncio
async def test_fallback_non_json_final_strips_wire_format():
    agent = make_executor(
        stream_text=WIRE_ONLY,
        fallback_events=[
            MessageEvent(message="Jawaban akhir.\n" + WIRE_ONLY)
        ],
    )
    events = await collect(agent)
    finals = [e for e in events if isinstance(e, MessageEvent) and e.is_final]
    assert len(finals) == 1
    assert finals[0].message.strip() == "Jawaban akhir."


@pytest.mark.asyncio
async def test_fallback_non_json_wire_only_final_suppressed():
    agent = make_executor(
        stream_text=WIRE_ONLY,
        fallback_events=[MessageEvent(message=WIRE_ONLY)],
    )
    events = await collect(agent)
    assert not [e for e in events if isinstance(e, MessageEvent) and e.is_final]


# ── 7. planner acknowledgement guard ──────────────────────────────────────


def test_planner_ack_strips_residue():
    cleaned = PlannerAgent._clean_acknowledgement("Oke, saya mulai.\n" + WIRE_ONLY)
    assert cleaned.strip() == "Oke, saya mulai."


def test_planner_ack_wire_only_suppressed():
    assert PlannerAgent._clean_acknowledgement(WIRE_ONLY) == ""


# ── 8. narration assist guard ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_narration_wire_format_only_suppressed():
    agent = make_executor(stream_text="")
    agent._silent_activities = ["file_read artikel.md"]
    agent._narration_lang = "id"

    async def fake_stream(messages):
        return WIRE_ONLY

    agent.astream_text_with_fallback = fake_stream
    assert await agent._generate_activity_narration() == ""


# ── helper unit: _strip_function_syntax contract ──────────────────────────


def test_strip_function_syntax_contract():
    assert _strip_function_syntax(WIRE_ONLY).strip() == ""
    # Surrounding blank lines may remain after block removal — compare
    # line-content only (renderers collapse blank lines anyway).
    mixed = _strip_function_syntax("a\n" + WIRE_ONLY + "b")
    assert [ln for ln in mixed.splitlines() if ln.strip()] == ["a", "b"]
    assert _strip_function_syntax("plain text") == "plain text"
    assert _strip_function_syntax("") == ""
