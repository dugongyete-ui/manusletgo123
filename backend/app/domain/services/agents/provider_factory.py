"""Agent provider factory — selects the model-provider adapter.

``AGENT_PROVIDER`` (env / Settings):
- ``existing`` → :class:`OpenAICompatProvider` (DEFAULT, unchanged behaviour)

In this deployment the ``existing`` adapter talks to the configured
OpenAI-compatible gateway — the NVIDIA NIM endpoint set via
``API_BASE`` / ``MODEL_NAME`` / ``API_KEY`` in config.py / .env.

Any unknown/unconfigured value safely degrades to ``existing`` — the chat
pipeline can never break because of a typo in the environment. The
``AgentProvider`` protocol stays the single extension point for a future
model adapter; per project decision the Anthropic adapter was removed
(rollback to any future alternative remains a single env-var flip).
"""

from __future__ import annotations

import logging
import threading

from app.core.config import get_settings
from app.domain.services.agents.providers import (
    AgentProvider,
    OpenAICompatProvider,
    OpenCodeAdapterProvider,
)

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = ("existing", "opencode_adapter")

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

        provider = (
            OpenCodeAdapterProvider()
            if name == "opencode_adapter"
            else OpenAICompatProvider()
        )

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
