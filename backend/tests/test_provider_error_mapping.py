"""Tests — provider-neutral exception classification (error adapter).

Both adapters must map SDK errors into the SAME ProviderErrorKind values the
existing retry ladder understands, so the fallback rotation, patient 429
loop and context-overflow compaction behave identically for every provider.
"""

import pytest

from app.domain.services.agents.providers import (
    AnthropicProvider,
    OpenAICompatProvider,
    ProviderErrorKind,
)
from app.core.config import get_settings

import openai
import httpx


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _anthropic_sdk():
    import anthropic

    return anthropic


# ── OpenAI-compatible adapter ────────────────────────────────────────────────
def test_openai_auth_errors():
    p = OpenAICompatProvider()
    req = httpx.Request("POST", "https://gw.test/v1/chat")
    assert p.classify_exception(
        openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    ) is ProviderErrorKind.AUTH


def test_openai_rate_limit():
    p = OpenAICompatProvider()
    req = httpx.Request("POST", "https://gw.test/v1/chat")
    assert p.classify_exception(
        openai.RateLimitError("429", response=httpx.Response(429, request=req), body=None)
    ) is ProviderErrorKind.RATE_LIMIT


def test_openai_transient():
    p = OpenAICompatProvider()
    assert p.classify_exception(openai.APIConnectionError(request=None)) is ProviderErrorKind.TRANSIENT
    assert p.classify_exception(ValueError({"code": 500, "message": "boom"})) is ProviderErrorKind.TRANSIENT


def test_openai_context_overflow():
    p = OpenAICompatProvider()
    req = httpx.Request("POST", "https://gw.test/v1/chat")
    err = openai.APIStatusError(
        "Prompt exceeds max length (1261)",
        response=httpx.Response(400, request=req),
        body=None,
    )
    assert p.classify_exception(err) is ProviderErrorKind.CONTEXT_OVERFLOW


def test_openai_fatal():
    p = OpenAICompatProvider()
    req = httpx.Request("POST", "https://gw.test/v1/chat")
    assert p.classify_exception(
        openai.APIStatusError("weird", response=httpx.Response(418, request=req), body=None)
    ) is ProviderErrorKind.FATAL
    assert p.classify_exception(RuntimeError("anything")) is ProviderErrorKind.FATAL


def test_openai_quota_wording():
    p = OpenAICompatProvider()
    assert p.classify_exception(ValueError({"code": 402, "message": "Insufficient balance"})) is ProviderErrorKind.RATE_LIMIT


# ── Anthropic adapter ────────────────────────────────────────────────────────
def test_anthropic_auth_errors():
    sdk = _anthropic_sdk()
    p = AnthropicProvider()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = sdk.AuthenticationError(
        "invalid x-api-key",
        response=httpx.Response(401, request=req),
        body=None,
    )
    assert p.classify_exception(err) is ProviderErrorKind.AUTH


def test_anthropic_rate_limit():
    sdk = _anthropic_sdk()
    p = AnthropicProvider()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = sdk.RateLimitError(
        "Number of requests too high",
        response=httpx.Response(429, request=req),
        body=None,
    )
    assert p.classify_exception(err) is ProviderErrorKind.RATE_LIMIT


def test_anthropic_transient():
    p = AnthropicProvider()
    assert p.classify_exception(
        _anthropic_sdk().APIConnectionError(request=None)
    ) is ProviderErrorKind.TRANSIENT


def test_anthropic_context_overflow():
    """Anthropic's 'prompt is too long' wording must hit the compaction path."""
    sdk = _anthropic_sdk()
    p = AnthropicProvider()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = sdk.BadRequestError(
        "Your prompt is too long for this model",
        response=httpx.Response(400, request=req),
        body=None,
    )
    assert p.classify_exception(err) is ProviderErrorKind.CONTEXT_OVERFLOW


def test_anthropic_fatal_404():
    """Model-not-found 404 is fatal (no OpenRouter pool recycling here)."""
    sdk = _anthropic_sdk()
    p = AnthropicProvider()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = sdk.NotFoundError(
        "model not found",
        response=httpx.Response(404, request=req),
        body=None,
    )
    assert p.classify_exception(err) is ProviderErrorKind.FATAL


def test_error_type_tuples_nonempty():
    p = AnthropicProvider()
    assert p.transient_error_types()
    assert p.auth_error_types()
    assert p.status_error_types()
    q = OpenAICompatProvider()
    assert q.transient_error_types()
    assert q.auth_error_types()
    assert q.status_error_types()
