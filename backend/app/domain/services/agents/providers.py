"""Agent provider abstraction — model-provider adapters for the agent runtime.

Adapted (original implementation) from the workflow patterns studied in the
official Claude Code repository audit: the agent loop stays tool-use driven,
permission-gated and provider-agnostic; only the MODEL LAYER is swapped.

Design constraints (see worklog + claude-code-reference-audit.md):
- ``existing`` (OpenAI-compatible gateway) MUST remain the default and behave
  byte-for-byte like the pre-abstraction code path.
- ``anthropic`` uses the Anthropic Messages API SERVER-SIDE via
  ``langchain-anthropic`` (ChatAnthropic). The Claude Code CLI and the
  ``claude-agent-sdk`` wrapper are NEVER spawned — web backend multi-user
  requires a programmatically controlled API, not a CLI subprocess.
- No API key may ever reach logs, SSE events, the browser, or the database.
- Error translation is provider-neutral: both adapters classify exceptions
  into the SAME kinds the existing retry ladder already handles, so the
  fallback rotation / patient rate-limit loop / context-overflow compaction
  keep working no matter which provider is selected.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable

import httpx
from langchain.chat_models import init_chat_model

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ProviderErrorKind(str, Enum):
    """Provider-neutral classification for LLM API failures.

    The retry ladder in ``BaseAgent.ask_with_messages`` branches on these
    kinds (auth → swap to fallback; transient → short back-off; rate limit →
    patient rotation; context overflow → emergency compaction).
    """

    AUTH = "auth"                        # invalid / unauthorized key — do not retry same provider
    RATE_LIMIT = "rate_limit"            # 429 / quota / billing — patient rotation
    TRANSIENT = "transient"              # 5xx / network / timeout — short back-off
    CONTEXT_OVERFLOW = "context_overflow"  # prompt too large — compact & retry
    FATAL = "fatal"                      # anything else — surface immediately


@runtime_checkable
class AgentProvider(Protocol):
    """Contract every agent provider adapter must satisfy.

    The conceptual ``run_turn`` of the reference design maps onto the
    EXISTING turn pipeline (chat route → AgentTaskRunner → PlanActFlow →
    BaseAgent.execute). A provider therefore swaps the model layer plus its
    error/binding semantics instead of duplicating the loop.
    """

    name: str

    @property
    def supports_response_format(self) -> bool:
        """Whether ``bind(response_format=...)`` is supported (OpenAI-style
        JSON mode). Anthropic rejects it — the guard must drop the key."""
        ...

    def build_chat_model(self, prefer_fallback: bool = False) -> Optional[Any]:
        """Build the LangChain chat model.

        ``prefer_fallback=True`` returns the secondary provider (or None when
        none is configured). Returns None when this provider is not usable
        (e.g. missing credentials) so the factory can fall back safely.
        """
        ...

    def transient_error_types(self) -> Tuple[type, ...]:
        """Exception types retried with short back-off (5xx/network/429)."""
        ...

    def auth_error_types(self) -> Tuple[type, ...]:
        """Exception types meaning the credentials are unusable."""
        ...

    def status_error_types(self) -> Tuple[type, ...]:
        """HTTP-status exception types handled by the status-error branch
        (checked LAST — includes rate-limit subclasses in both SDKs)."""
        ...

    def classify_exception(self, exc: BaseException) -> ProviderErrorKind:
        """Map any exception to a ProviderErrorKind."""
        ...

    def describe(self) -> dict:
        """Safe metadata for logs/diagnostics — MUST NOT contain secrets."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible adapter (the pre-existing behaviour, unchanged)
# ─────────────────────────────────────────────────────────────────────────────
class OpenAICompatProvider:
    """The original model construction path, moved verbatim behind the
    provider seam. Selected when ``AGENT_PROVIDER=existing`` (default)."""

    name = "existing"
    supports_response_format = True

    def build_chat_model(self, prefer_fallback: bool = False) -> Optional[Any]:
        from app.domain.services.agents.base import _build_existing_chat_model

        return _build_existing_chat_model(prefer_fallback=prefer_fallback)

    def transient_error_types(self) -> Tuple[type, ...]:
        import openai

        return (
            openai.InternalServerError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
        )

    def auth_error_types(self) -> Tuple[type, ...]:
        import openai

        return (openai.AuthenticationError, openai.PermissionDeniedError)

    def status_error_types(self) -> Tuple[type, ...]:
        import openai

        return (openai.APIStatusError, openai.NotFoundError)

    def classify_exception(self, exc: BaseException) -> ProviderErrorKind:
        import openai

        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ProviderErrorKind.AUTH
        if isinstance(exc, openai.RateLimitError):
            return ProviderErrorKind.RATE_LIMIT
        if isinstance(
            exc,
            (openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError),
        ):
            return ProviderErrorKind.TRANSIENT
        if self._is_context_overflow(exc):
            return ProviderErrorKind.CONTEXT_OVERFLOW
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status == 402 or self._is_limit_message(exc):
                return ProviderErrorKind.RATE_LIMIT
            return ProviderErrorKind.FATAL
        if isinstance(exc, ValueError) and self._is_limit_message(exc):
            return ProviderErrorKind.RATE_LIMIT
        if isinstance(exc, ValueError) and self._is_transient_body(exc):
            return ProviderErrorKind.TRANSIENT
        if self._is_limit_message(exc):
            return ProviderErrorKind.RATE_LIMIT
        return ProviderErrorKind.FATAL

    def describe(self) -> dict:
        settings = get_settings()
        return {
            "provider": self.name,
            "model": settings.model_name,
            "gateway": "openai-compatible",
            "base_url_configured": bool(settings.api_base),
        }

    # ── shared string heuristics (mirror BaseAgent helpers) ────────────────
    @staticmethod
    def _is_limit_message(exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in (
                "rate limit", "quota", "credit", "insufficient",
                "exceeded your current quota", "billing", "limit reached",
            )
        )

    @staticmethod
    def _is_context_overflow(exc: BaseException) -> bool:
        from app.domain.services.agents.base import BaseAgent

        return BaseAgent._is_context_overflow_error(exc)

    @staticmethod
    def _is_transient_body(exc: BaseException) -> bool:
        """HTTP-200-with-error-body payloads surfaced as ValueError."""
        if not isinstance(exc, ValueError) or not exc.args:
            return False
        payload = exc.args[0]
        if not isinstance(payload, dict):
            return False
        code = payload.get("code")
        if code == 429 or code == 402 or (isinstance(code, int) and 500 <= code < 600):
            return True
        OpenAICompatProvider._is_limit_message(payload.get("message", ""))
        message = str(payload.get("message", "")).lower()
        return any(
            kw in message
            for kw in (
                "rate limit", "overloaded", "temporarily unavailable",
                "try again", "provider returned error", "no endpoints found",
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic adapter — server-side Messages API (NO CLI, NO subprocess)
# ─────────────────────────────────────────────────────────────────────────────
class AnthropicProvider:
    """Anthropic Messages API adapter built on ``langchain-anthropic``.

    The provider keeps every runtime guarantee of the existing system: tools
    still flow through ManusGate / the registry / the sandbox, events still
    follow the SSE contract, cancellation stays asyncio-native. Only the
    model client and its exception vocabulary change.
    """

    name = "anthropic"
    supports_response_format = False  # Anthropic has no OpenAI json_mode key

    def __init__(self) -> None:
        self._openai_compat = OpenAICompatProvider()

    # ── model construction ──────────────────────────────────────────────────
    def build_chat_model(self, prefer_fallback: bool = False) -> Optional[Any]:
        settings = get_settings()
        if prefer_fallback:
            # The secondary provider is the OpenAI-compatible fallback
            # (FALLBACK_* / z.ai internal API) regardless of the primary —
            # documented behaviour, keeps the rotation pool intact.
            return self._openai_compat.build_chat_model(prefer_fallback=True)
        if not settings.anthropic_api_key:
            return None  # factory falls back to "existing" — chat never breaks
        kwargs: dict = {
            "model": settings.anthropic_model,
            "model_provider": "anthropic",
            "api_key": settings.anthropic_api_key,
            "max_tokens": settings.anthropic_max_tokens,
            "temperature": (
                settings.anthropic_temperature
                if settings.anthropic_temperature is not None
                else settings.temperature
            ),
        }
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
            kwargs["http_client"] = httpx.Client(verify=settings.ssl_verify)
            kwargs["http_async_client"] = httpx.AsyncClient(verify=settings.ssl_verify)
        return init_chat_model(**kwargs)

    # ── exception vocabulary ────────────────────────────────────────────────
    @staticmethod
    def _anthropic():
        try:
            import anthropic

            return anthropic
        except ImportError:  # pragma: no cover — dependency is declared
            logger.warning("anthropic package unavailable — treating as FATAL")
            return None

    def transient_error_types(self) -> Tuple[type, ...]:
        sdk = self._anthropic()
        if sdk is None:
            return ()
        return (
            sdk.InternalServerError,
            sdk.APIConnectionError,
            sdk.APITimeoutError,
            sdk.RateLimitError,
        )

    def auth_error_types(self) -> Tuple[type, ...]:
        sdk = self._anthropic()
        if sdk is None:
            return ()
        return (sdk.AuthenticationError, sdk.PermissionDeniedError)

    def status_error_types(self) -> Tuple[type, ...]:
        sdk = self._anthropic()
        if sdk is None:
            return ()
        return (sdk.APIStatusError, sdk.NotFoundError)

    def classify_exception(self, exc: BaseException) -> ProviderErrorKind:
        sdk = self._anthropic()
        if sdk is not None:
            if isinstance(exc, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
                return ProviderErrorKind.AUTH
            if isinstance(exc, sdk.RateLimitError):
                return ProviderErrorKind.RATE_LIMIT
            if isinstance(
                exc,
                (sdk.InternalServerError, sdk.APIConnectionError, sdk.APITimeoutError),
            ):
                return ProviderErrorKind.TRANSIENT
        if self._openai_compat._is_context_overflow(exc):
            return ProviderErrorKind.CONTEXT_OVERFLOW
        if sdk is not None and isinstance(exc, sdk.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status == 402 or self._openai_compat._is_limit_message(exc):
                return ProviderErrorKind.RATE_LIMIT
            return ProviderErrorKind.FATAL
        if self._openai_compat._is_limit_message(exc):
            return ProviderErrorKind.RATE_LIMIT
        return ProviderErrorKind.FATAL

    def describe(self) -> dict:
        settings = get_settings()
        return {
            "provider": self.name,
            "model": settings.anthropic_model,
            "transport": "anthropic-messages-api (server-side, no CLI)",
            "base_url_configured": bool(settings.anthropic_base_url),
            "fallback_pool": "openai-compatible",
        }
