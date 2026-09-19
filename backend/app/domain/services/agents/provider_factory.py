"""Agent provider factory — selects the model-provider adapter.

``AGENT_PROVIDER`` (env / Settings):
- ``existing``  → :class:`OpenAICompatProvider` (DEFAULT, unchanged behaviour)
- ``anthropic`` → :class:`AnthropicProvider`   (server-side Messages API)

Any unknown/unconfigured value safely degrades to ``existing`` — the chat
pipeline can never break because of a typo in the environment. Rollback to
the previous behaviour is a single environment-variable flip.
"""

from __future__ import annotations

import logging
import threading

from app.core.config import get_settings
from app.domain.services.agents.providers import (
    AgentProvider,
    AnthropicProvider,
    OpenAICompatProvider,
)

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = ("existing", "anthropic")

_cache_lock = threading.Lock()
_cached_name: str | None = None
_cached_provider: AgentProvider | None = None


def _resolve_provider_name() -> str:
    raw = (get_settings().agent_provider or "existing").strip().lower()
    if raw not in _VALID_PROVIDERS:
        logger.warning(
            "Unknown AGENT_PROVIDER %r — falling back to 'existing'. "
            "Valid values: %s",
            raw,
            ", ".join(_VALID_PROVIDERS),
        )
        return "existing"
    return raw


def get_agent_provider() -> AgentProvider:
    """Return the configured provider adapter (process-lifetime cached)."""
    global _cached_name, _cached_provider

    name = _resolve_provider_name()
    with _cache_lock:
        if _cached_provider is not None and _cached_name == name:
            return _cached_provider

        provider: AgentProvider
        if name == "anthropic":
            anthropic = AnthropicProvider()
            if not get_settings().anthropic_api_key:
                logger.warning(
                    "AGENT_PROVIDER=anthropic but ANTHROPIC_API_KEY is not "
                    "configured — falling back to the 'existing' provider. "
                    "Set ANTHROPIC_API_KEY to enable the Anthropic adapter."
                )
                provider = OpenAICompatProvider()
            else:
                provider = anthropic
        else:
            provider = OpenAICompatProvider()

        # Log safe metadata only — never credentials.
        logger.info("Agent provider selected: %s", provider.describe())
        _cached_name = name
        _cached_provider = provider
        return provider


def reset_agent_provider_cache() -> None:
    """Test hook — force re-selection after Settings/env changes."""
    global _cached_name, _cached_provider
    with _cache_lock:
        _cached_name = None
        _cached_provider = None
