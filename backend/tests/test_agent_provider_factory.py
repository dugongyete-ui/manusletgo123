"""Tests — Agent provider factory & selection (AGENT_PROVIDER env)."""

import pytest

from app.core.config import get_settings
from app.domain.services.agents.provider_factory import (
    get_agent_provider,
    reset_agent_provider_cache,
)
from app.domain.services.agents.providers import (
    AgentProvider,
    AnthropicProvider,
    OpenAICompatProvider,
)


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    """Isolate env + provider cache per test."""
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    reset_agent_provider_cache()
    get_settings.cache_clear()
    yield
    reset_agent_provider_cache()
    get_settings.cache_clear()


def test_default_provider_is_existing():
    """AGENT_PROVIDER unset → the existing OpenAI-compatible provider."""
    provider = get_agent_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "existing"


def test_provider_satisfies_protocol():
    """Both adapters honour the AgentProvider runtime protocol."""
    assert isinstance(OpenAICompatProvider(), AgentProvider)
    assert isinstance(AnthropicProvider(), AgentProvider)


def test_anthropic_selected_with_key(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    provider = get_agent_provider()
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"
    assert provider.supports_response_format is False


def test_anthropic_without_key_falls_back_to_existing(monkeypatch):
    """Missing ANTHROPIC_API_KEY must never break chat — fall back."""
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
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret-value")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    provider = get_agent_provider()
    rendered = repr(provider.describe()) + str(provider.describe())
    assert "sk-ant-super-secret-value" not in rendered
    assert "api_key" not in provider.describe()


def test_anthropic_build_model_uses_server_side_api(monkeypatch):
    """The anthropic adapter builds a server-side model — never a CLI."""
    import app.domain.services.agents.providers as providers_mod

    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    reset_agent_provider_cache()

    captured = {}

    def _fake_init_chat_model(**kwargs):
        captured.update(kwargs)
        return "MODEL-SENTINEL"

    monkeypatch.setattr(providers_mod, "init_chat_model", _fake_init_chat_model)
    provider = AnthropicProvider()
    model = provider.build_chat_model(prefer_fallback=False)
    assert model == "MODEL-SENTINEL"
    assert captured["model_provider"] == "anthropic"
    assert captured["model"] == "claude-sonnet-4-5"
    # Credentials pass through the SDK config only — never logged anywhere.
    assert captured["api_key"] == "sk-ant-test-123"


def test_anthropic_fallback_uses_openai_compat_pool(monkeypatch):
    """The fallback pool stays the OpenAI-compatible one (rotation intact)."""
    import app.domain.services.agents.base as base_mod

    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    reset_agent_provider_cache()

    def _fake_existing(prefer_fallback=False):
        assert prefer_fallback is True
        return "FALLBACK-SENTINEL"

    monkeypatch.setattr(base_mod, "_build_existing_chat_model", _fake_existing)
    provider = AnthropicProvider()
    assert provider.build_chat_model(prefer_fallback=True) == "FALLBACK-SENTINEL"


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
