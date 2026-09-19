"""Tests — Agent provider factory & selection (AGENT_PROVIDER env)."""

import pytest

from app.core.config import get_settings
from app.domain.services.agents.provider_factory import (
    get_agent_provider,
    reset_agent_provider_cache,
)
from app.domain.services.agents.providers import (
    AgentProvider,
    OpenAICompatProvider,
)


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    """Isolate env + provider cache per test."""
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    reset_agent_provider_cache()
    get_settings.cache_clear()
    yield
    reset_agent_provider_cache()
    get_settings.cache_clear()


def test_default_provider_is_existing():
    """AGENT_PROVIDER unset → the existing OpenAI-compatible provider
    (in this deployment: the NVIDIA NIM gateway)."""
    provider = get_agent_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "existing"


def test_provider_satisfies_protocol():
    """The adapter honours the AgentProvider runtime protocol."""
    assert isinstance(OpenAICompatProvider(), AgentProvider)


def test_removed_anthropic_value_degrades_to_existing(monkeypatch):
    """Per project decision the Anthropic adapter was removed — selecting it
    (or any unknown value) must safely degrade to the default provider."""
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    provider = get_agent_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "existing"


def test_unknown_provider_falls_back_to_existing(monkeypatch):
    """A typo in AGENT_PROVIDER degrades safely to the default."""
    monkeypatch.setenv("AGENT_PROVIDER", "codex-fake")
    provider = get_agent_provider()
    assert isinstance(provider, OpenAICompatProvider)


def test_describe_never_contains_secrets(monkeypatch):
    """Provider metadata must not leak credentials."""
    monkeypatch.setenv("API_KEY", "sk-super-secret-value-123")
    provider = get_agent_provider()
    rendered = repr(provider.describe()) + str(provider.describe())
    assert "sk-super-secret-value-123" not in rendered
    assert "api_key" not in provider.describe()


def test_existing_build_model_delegates_verbatim(monkeypatch):
    """``existing`` keeps calling the original construction path."""
    import app.domain.services.agents.base as base_mod

    reset_agent_provider_cache()
    calls = []

    def _fake_existing(prefer_fallback=False):
        calls.append(prefer_fallback)
        return "EXISTING-SENTINEL"

    monkeypatch.setattr(base_mod, "_build_existing_chat_model", _fake_existing)
    provider = OpenAICompatProvider()
    assert provider.build_chat_model(prefer_fallback=True) == "EXISTING-SENTINEL"
    assert provider.build_chat_model(prefer_fallback=False) == "EXISTING-SENTINEL"
    assert calls == [True, False]
