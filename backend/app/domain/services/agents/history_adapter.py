"""Session-history → provider-format conversion.

The agent runtime stores conversation memory as LangChain messages
(``AnyMessage``). The configured gateway — the OpenAI-compatible NVIDIA NIM
endpoint in this deployment — consumes that history as-is, so the default
conversion is a validated passthrough: identical objects, identical order,
byte-for-byte the same behaviour as before the provider seam existed.

``convert_history_for_provider`` stays the single seam where a future strict
provider (one that rejects dangling tool results / empty messages, like the
former Anthropic adapter did) would project the history — per project
decision the Anthropic adapter was removed and the deployment standardizes
on the NVIDIA gateway, so every current provider name maps to passthrough.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def convert_history_for_provider(provider_name: str, messages: List) -> List:
    """Convert stored LangChain history into the provider's protocol shape.

    The OpenAI-compatible path (NVIDIA NIM) consumes the history as-is —
    behaviour preserved byte-for-byte from before the provider seam.
    """
    if not messages:
        return []
    return list(messages)
