"""Agent provider abstraction — model-provider adapters for the agent runtime.

Adapted (original implementation) from the workflow patterns studied in the
official Claude Code repository audit: the agent loop stays tool-use driven,
permission-gated and provider-agnostic; only the MODEL LAYER is swapped.

Design constraints (see worklog + claude-code-reference-audit.md):
- ``existing`` (the configured OpenAI-compatible gateway — in this deployment
  the NVIDIA NIM endpoint set via API_BASE/MODEL_NAME) MUST remain the default
  and behave byte-for-byte like the pre-abstraction code path.
- The Claude Code CLI and the ``claude-agent-sdk`` wrapper are NEVER spawned —
  a web backend with multiple users requires a programmatically controlled
  server-side API, not a CLI subprocess.
- No API key may ever reach logs, SSE events, the browser, or the database.
- Error translation is provider-neutral: adapters classify exceptions into
  the SAME kinds the existing retry ladder already handles, so the fallback
  rotation / patient rate-limit loop / context-overflow compaction keep
  working no matter which provider is selected.

The ``AgentProvider`` protocol is the single extension point for adding a
future model adapter; per project decision the Anthropic adapter was removed
(the deployment standardizes on the NVIDIA gateway already configured in
``config.py`` / ``.env``).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable

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
        JSON mode). Strict providers without it must never receive the key —
        the guard drops it (the default NVIDIA gateway supports it)."""
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
# OpenAI-compatible adapter (the pre-existing behaviour, unchanged).
# In this deployment the gateway is NVIDIA NIM (integrate.api.nvidia.com) —
# configured through the standard API_BASE / MODEL_NAME / API_KEY settings.
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


class OpenCodeAdapterProvider(OpenAICompatProvider):
    """OpenCode-inspired adapter over the existing server-side model seam.

    OpenCode itself is not embedded here.  Selecting this adapter keeps the
    current LangChain model construction and error ladder, while enabling the
    native plan-mode policy and event normalization without duplicating the
    agent loop or bypassing the existing tool boundary.
    """

    name = "opencode_adapter"

    def describe(self) -> dict:
        from app.domain.services.agents.opencode_adapter import configured_agent_mode

        metadata = super().describe()
        metadata.update(
            {
                "adapter": "opencode-inspired-native",
                "mode": configured_agent_mode(),
            }
        )
        return metadata
