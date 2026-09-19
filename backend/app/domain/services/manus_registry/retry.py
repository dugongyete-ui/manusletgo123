"""Retry Error Handler (agent architecture contract v1.0).

Contract: agent_architecture_json/retry-error-handler/contract.json

Role: mengklasifikasi error dan mengontrol retry di level executor —
SEBELUM kegagalan transient dikembalikan ke model.

  retryable      : timeout, temporary_network_error, server_busy,
                   transient_connection_failure
  non_retryable  : validation_error, tool_not_found, permission_denied,
                   authentication_required, captcha, missing_file,
                   unsupported_operation  (+ semua kode gate lain)

Config (contract): max_attempts=2, backoff=exponential, jitter=true.
Retries hanya menyentuh kode RETRYABLE_CODES — error deterministik
(validasi, izin, tool tidak ada) TIDAK pernah di-retry otomatis.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, Dict

from app.core.config import get_settings
from app.domain.services.manus_registry.errors import RETRYABLE_CODES

logger = logging.getLogger(__name__)

DEFAULT_BASE_DELAY = 0.5  # seconds — first retry waits ~0.5s


def is_retryable_payload(payload: Dict[str, Any]) -> bool:
    """Contract rule: only the payload's retryable flag (→ RETRYABLE_CODES)."""
    return bool(payload.get("retryable")) and (
        (payload.get("error") or {}).get("code") in RETRYABLE_CODES
    )


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with ±20% jitter: 0.5s, 1.0s, 2.0s, ..."""
    base = DEFAULT_BASE_DELAY * (2 ** max(0, attempt - 1))
    return base * (0.8 + 0.4 * random.random())


async def run_with_retry(
    exec_fn: Callable[[], Awaitable[Dict[str, Any]]],
    *,
    tool_name: str,
) -> Dict[str, Any]:
    """Execute a transport call with contract retry semantics.

    exec_fn must return a NORMALIZED payload ({success, error, retryable}).
    A retryable failure (timeout / transient network) is re-executed after
    an exponential backoff, up to manus_max_retries_per_call attempts
    (contract default 2). Any success, non-retryable failure, or exhausted
    budget returns the LAST payload to the caller (the gate / the model).
    """
    settings = get_settings()
    max_attempts = max(1, int(getattr(settings, "manus_max_retries_per_call", 2) or 1))

    payload: Dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        payload = await exec_fn()
        if payload.get("success") or not is_retryable_payload(payload):
            return payload
        if attempt >= max_attempts:
            logger.warning(
                "retry budget exhausted for %s after %d attempt(s): %s",
                tool_name, attempt,
                (payload.get("error") or {}).get("code"),
            )
            return payload
        delay = backoff_delay(attempt)
        logger.info(
            "retrying %s (attempt %d/%d) after %.2fs — %s",
            tool_name, attempt, max_attempts, delay,
            (payload.get("error") or {}).get("code"),
        )
        # Annotate the final payload with the retry accounting (trace).
        payload.setdefault("retry_state", {})
        payload["retry_state"] = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "next_backoff_ms": int(delay * 1000),
        }
        await asyncio.sleep(delay)
    return payload
