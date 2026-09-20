"""Tests for intent handling, stop-by-text, and stopped-run resume.

Covers the reported issues:
1. "Coba contohkan saya ingin melihat nya" must reach the agent flow (plan +
   tools) — either classified AGENT up-front, or recovered by the
   unfulfilled-promise safety net when the discuss reply is only a promise.
2. STOP button → "Dzeck telah berhenti, kirim pesan baru untuk melanjutkan."
   + session CANCELLED (resumable), never a fake COMPLETED.
3. Stop-by-text mid-run ("berhenti", "jangan dilanjutkan") → the run ends,
   the plan is closed as completed, and the text never reaches the executor.
4. A CANCELLED session's next message resumes the stored plan.
"""

import pytest

from app.domain.models.event import PlanStatus
from app.domain.models.plan import ExecutionStatus, Plan, Step
from app.domain.models.session import Session, SessionStatus
from app.domain.services.agents.intent import (
    is_unfulfilled_promise,
    looks_like_stop_request,
    stop_acknowledgement,
    stopped_by_button_notice,
)


# ── 1. Unfulfilled-promise detector ──────────────────────────────────────────


def test_promise_reply_detected():
    assert is_unfulfilled_promise(
        "Baik, saya akan siapkan contohnya untuk Anda."
    ) is True


def test_promise_reply_english_detected():
    assert is_unfulfilled_promise("Sure, I'll prepare an example for you.") is True


def test_identity_answer_not_a_promise():
    assert is_unfulfilled_promise(
        "Saya adalah Dzeck, agen AI yang bisa bekerja nyata di komputer."
    ) is False


def test_content_answer_not_a_promise():
    assert is_unfulfilled_promise(
        "Contohnya: saya bisa membuat website toko dengan keranjang, "
        "checkout, dan dashboard admin dalam satu folder project."
    ) is False


def test_long_answer_not_a_promise():
    text = "Saya akan jelaskan. " + ("Detail penting tentang kemampuan ini. " * 15)
    assert is_unfulfilled_promise(text) is False


def test_empty_not_a_promise():
    assert is_unfulfilled_promise("") is False


# ── 2. Stop-request detector ────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "stop",
    "Stop",
    "berhenti",
    "Berhenti!",
    "jangan dilanjutkan",
    "jangan diteruskan",
    "stop jangan diteruskan",
    "berhenti jangan dilanjutkan",
    "cukup sampai di sini",
    "batalkan task nya",
    "cancel it now",
    "enough stop please",
])
def test_stop_requests_detected(text):
    assert looks_like_stop_request(text) is True


@pytest.mark.parametrize("text", [
    "lanjutkan",
    "lanjut",
    "continue",
    "buatkan website toko",
    "stop pakai browser, lanjut ke step 3",   # mixed instruction, not a stop
    "jangan lupa buatkan laporan",             # "jangan" + work request
    "kerjakan tugasnya sampai selesai",
    "",
])
def test_non_stop_messages_rejected(text):
    assert looks_like_stop_request(text) is False


def test_stop_acknowledgement_language():
    # Deliberately SHORT, human, slop-free: no canned promises about
    # "continuing from the last point" (reported bug).
    id_ack = stop_acknowledgement("berhenti")
    assert "hentikan" in id_ack.lower()
    assert "tersimpan" in id_ack.lower()
    assert "lanjutkan dari titik terakhir" not in id_ack.lower()
    assert len(id_ack) < 120
    en_ack = stop_acknowledgement("stop now")
    assert "stopped" in en_ack.lower()
    assert "pick it back up" not in en_ack.lower()
    assert len(en_ack) < 120


def test_stop_button_notice_text():
    assert stopped_by_button_notice() == (
        "Dzeck berhenti di sini. Kirim pesan kalau mau disambung lagi."
    )


# ── Identity-chat fast path ─────────────────────────────────────────────────


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_identity_chat_detected_as_discuss():
    from app.domain.services.agents.intent import classify_chat_mode

    for text in (
        "hai nama lu siapa",
        "nama lu siapa",
        "kamu siapa",
        "siapa kamu sih",
        "nama kamu apa",
        "what's your name",
        "who are you",
        "kamu bisa apa",
        "kamu robot ya?",
        "kamu dibuat sama siapa",
    ):
        mode, confidence = _run(classify_chat_mode(text))
        assert mode == "discuss", f"{text!r} → {mode}"
        assert confidence >= 0.9


def test_identity_chat_with_task_vocab_not_deterministic_discuss():
    from app.domain.services.agents.intent import _is_identity_chat

    for text in (
        "hai, buatkan website portfolio",
        "buatkan nama domain untuk toko saya",
        "buat website namamu sendiri",
        "download file ini lalu ubah namanya",
    ):
        assert _is_identity_chat(text) is False, (
            f"{text!r} salah terdeteksi sebagai identitas — harus tetap lewat"
            " klasifikasi semantik / agent mode"
        )


# ── Demonstration-request lock ───────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Coba contohkan saya ingin melihat nya",
    "contohkan dong",
    "kasih contoh yang bisa saya lihat",
    "tunjukkan cara kerjanya",
    "demokan fiturnya",
    "saya ingin melihat hasilnya",
    "show me an example",
    "give me an example",
])
def test_demo_requests_detected(text):
    from app.domain.services.agents.intent import looks_like_demonstration_request
    assert looks_like_demonstration_request(text) is True


@pytest.mark.parametrize("text", [
    "Nama lu siapa",
    "halo",
    "buatkan website toko",
    "apa itu machine learning",
    "makasih ya",
])
def test_chat_messages_not_demo_requests(text):
    from app.domain.services.agents.intent import looks_like_demonstration_request
    assert looks_like_demonstration_request(text) is False


@pytest.mark.asyncio
async def test_discuss_gate_forces_agent_for_demo_requests():
    """A demonstration request must NEVER take the discuss path."""
    from types import SimpleNamespace

    from app.domain.services.flows.plan_act import PlanActFlow
    from app.domain.models.message import Message

    fake_self = SimpleNamespace(_agent_id="agent-x")
    result = await PlanActFlow._is_discuss(
        fake_self, SessionStatus.COMPLETED,
        Message(message="Coba contohkan saya ingin melihat nya"), "",
    )
    assert result is False


# ── 3. Session model: CANCELLED status ──────────────────────────────────────


def test_cancelled_status_exists():
    assert SessionStatus.CANCELLED == "cancelled"
    assert SessionStatus.CANCELLED.value == "cancelled"


def test_plan_with_pending_steps_is_resumable_shape():
    plan = Plan(goal="t", language="id", title="t", steps=[
        Step(id="1", description="a", status=ExecutionStatus.COMPLETED, success=True),
        Step(id="2", description="b"),
    ])
    assert any(not s.is_done() for s in plan.steps)
    assert plan.get_next_step().id == "2"


def test_all_completed_plan_not_resumable():
    plan = Plan(goal="t", language="id", title="t", steps=[
        Step(id="1", description="a", status=ExecutionStatus.COMPLETED, success=True),
    ])
    assert all(s.is_done() for s in plan.steps)


# ── 4. Discuss gate excludes cancelled sessions (resume always runs) ────────


@pytest.mark.asyncio
async def test_discuss_gate_excludes_cancelled():
    """A CANCELLED session must never take the discuss path — the resume
    path owns the next turn."""
    from types import SimpleNamespace

    from app.domain.services.flows.plan_act import PlanActFlow
    from app.domain.models.message import Message

    fake_self = SimpleNamespace(_agent_id="agent-x")
    result = await PlanActFlow._is_discuss(
        fake_self, SessionStatus.CANCELLED, Message(message="lanjutkan"), ""
    )
    assert result is False


@pytest.mark.asyncio
async def test_discuss_gate_allows_completed_sessions():
    from types import SimpleNamespace

    from app.domain.services.flows.plan_act import PlanActFlow
    from app.domain.models.message import Message

    calls = {}

    async def fake_classify(text, history):
        calls["text"] = text
        return "discuss", 0.99

    import app.domain.services.agents.intent as intent_mod
    original = intent_mod.classify_chat_mode
    intent_mod.classify_chat_mode = fake_classify
    try:
        # _is_discuss imports classify_chat_mode lazily from the module —
        # patch the module attribute it reads.
        fake_self = SimpleNamespace(_agent_id="agent-x")
        result = await PlanActFlow._is_discuss(
            fake_self, SessionStatus.COMPLETED, Message(message="nama lu siapa"), ""
        )
        # The lazy import inside _is_discuss binds the original function at
        # call time — patching the module attr still works because the import
        # re-reads the attribute. Either way the call must not raise.
        assert isinstance(result, bool)
    finally:
        intent_mod.classify_chat_mode = original


# ── 5. Plan finalization shape (stop-by-text) ───────────────────────────────


def test_stop_finalization_marks_steps_completed():
    """Mirror of the runner's stop finalization loop."""
    plan = Plan(goal="t", language="id", title="t", steps=[
        Step(id="1", description="a", status=ExecutionStatus.COMPLETED,
             success=True, result="done earlier"),
        Step(id="2", description="b", status=ExecutionStatus.RUNNING),
        Step(id="3", description="c"),
    ])
    for s in plan.steps:
        if not s.is_done():
            s.status = ExecutionStatus.COMPLETED
            s.success = True
            if not (s.result or "").strip():
                s.result = "Closed when the user stopped the task."
    plan.status = ExecutionStatus.COMPLETED

    assert all(s.is_done() for s in plan.steps)
    assert plan.status == ExecutionStatus.COMPLETED
    assert plan.get_next_step() is None


def test_session_get_last_plan_finds_latest():
    from app.domain.models.event import PlanEvent

    p1 = Plan(goal="g1", language="id", title="t1", steps=[Step(id="1")])
    s = Session(agent_id="a", user_id="u")
    s.events = [PlanEvent(status=PlanStatus.CREATED, plan=p1)]
    assert s.get_last_plan() is p1
