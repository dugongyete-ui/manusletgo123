"""Task 47 — trivial-chat gating & build-class AGENTS.md scoping.

Two regressions users hit:
1. A bare "hai" fell into agent mode (model classifier confidence < 0.6 or
   provider hiccup) → planner created a step → executor's old unconditional
   "first tool call: file_read project/AGENTS.md" fired. A greeting opened
   the workspace manual — pure mismatch.
2. The manual read was mandated for EVERY task that touches files, so even
   a one-off tiny script paid the orientation tax.

Fixes under test:
- intent.py: deterministic trivial-chat fast path (pure greeting/ack/thanks/
  farewell/emoji-only → discuss 0.99, no model call, immune to provider
  failures). A greeting WITH a request keeps the semantic path.
- prompts: AGENTS.md orientation is scoped to BUILD-CLASS steps (multi-file
  builds in their own project folder); small single-file outputs and
  conversational answers skip it.
"""

import pytest

from app.domain.services.agents.intent import (
    _is_trivial_chat,
    classify_chat_mode,
    CHAT_MODE_AGENT,
    CHAT_MODE_DISCUSS,
)


# ── Deterministic fast path ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        # bare greetings, EN / ID / misc, any casing & punctuation
        "hai", "Hai", "HAI!", "hai?", "hai...", "halo", "haloo!!",
        "hi", "hii", "hello", "hey", "yo", "sup",
        "pagi", "selamat pagi", "siang", "malam",
        "assalamualaikum", "assalamualaikum wr wb",
        # acknowledgements / reactions
        "ok", "oke", "sip", "siap", "yes", "ya", "mantap", "keren",
        # thanks & farewells
        "thanks", "makasih", "thx", "bye", "dadah", "gtg",
        # pings / smoke tests
        "tes", "test", "bot?", "min",
        # emoji-only / punctuation-only
        "👋", "!!!", "...",
    ],
)
def test_trivial_chat_detected(text):
    assert _is_trivial_chat(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # greeting + actual request → semantic path
        "hai, buatkan website", "halo tolong carikan berita persib",
        "hi, research X for me", "oke lanjutkan build nya",
        # task vocabulary alone
        "buatkan script python", "kode", "website",
        "cari berita", "baca file ini",
        # questions (not small talk)
        "apa kabar? ada yang bisa dibantu?",
        "kamu bisa apa saja?",
        # long greeting-ish message (over token limit → semantic path)
        "hai hai hai hai hai hai hai",
    ],
)
def test_trivial_chat_not_detected(text):
    assert _is_trivial_chat(text) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["hai", "halo"])
async def test_greeting_short_circuits_model(monkeypatch, text):
    """A trivial message returns discuss WITHOUT any model call — even when
    the provider is dead (the original 'hai reads AGENTS.md' incident)."""
    def _explode(*args, **kwargs):
        raise RuntimeError("provider dead")

    monkeypatch.setattr(
        "app.domain.services.agents.base._build_chat_model", _explode
    )
    mode, confidence = await classify_chat_mode(text)
    assert mode == CHAT_MODE_DISCUSS
    assert confidence >= 0.99


@pytest.mark.asyncio
async def test_greeting_with_request_still_classified_by_model(monkeypatch):
    """'hai, buatkan website' must NOT be fast-pathed — the model decides."""
    calls = {"n": 0}

    class _FakeResp:
        content = '{"mode": "agent", "confidence": 0.97}'

    class _FakeModel:
        async def ainvoke(self, messages):
            calls["n"] += 1
            return _FakeResp()

    monkeypatch.setattr(
        "app.domain.services.agents.base._build_chat_model",
        lambda *a, **k: _FakeModel(),
    )
    mode, confidence = await classify_chat_mode("hai, buatkan website")
    assert mode == CHAT_MODE_AGENT
    assert calls["n"] == 1  # semantic path actually consulted the model


# ── Prompt scoping — AGENTS.md is build-class orientation, not a tax ────────

def test_system_prompt_scopes_manual_to_build_class():
    from app.domain.services.prompts.system import SYSTEM_PROMPT

    # The unconditional mandate is gone…
    assert "EVERY conversation" not in SYSTEM_PROMPT
    # …replaced by build-class scoping with an explicit skip rule.
    assert "BUILD-CLASS" in SYSTEM_PROMPT
    assert "do NOT need this read" in SYSTEM_PROMPT


def test_execution_prompt_scopes_manual_to_build_class():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT

    assert "First tool call of a conversation" not in EXECUTION_SYSTEM_PROMPT
    assert "BUILD-CLASS" in EXECUTION_SYSTEM_PROMPT
    assert "not a tax on every step" in EXECUTION_SYSTEM_PROMPT


def test_planner_prompt_scopes_manual_to_build_class():
    from app.domain.services.prompts.planner import CREATE_PLAN_PROMPT

    assert "Any task that will create or modify files" not in CREATE_PLAN_PROMPT
    assert "Build-class tasks" in CREATE_PLAN_PROMPT
    assert "skip the manual read" in CREATE_PLAN_PROMPT


def test_classifier_prompt_calibrates_bare_greetings():
    from app.domain.services.agents.intent import _SYSTEM

    assert "bare greeting" in _SYSTEM
    assert "greeting that ALSO carries a request" in _SYSTEM
