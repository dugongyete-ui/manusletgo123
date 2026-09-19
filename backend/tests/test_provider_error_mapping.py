"""Tests — provider-neutral exception classification (error adapter).

Adapters must map SDK errors into the SAME ProviderErrorKind values the
existing retry ladder understands, so the fallback rotation, patient 429
loop and context-overflow compaction behave identically no matter which
adapter is active.
"""

import pytest

from app.domain.services.agents.providers import (
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


# ── OpenAI-compatible adapter (NVIDIA NIM gateway in this deployment) ──────
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


def test_error_type_tuples_nonempty():
    q = OpenAICompatProvider()
    assert q.transient_error_types()
    assert q.auth_error_types()
    assert q.status_error_types()
