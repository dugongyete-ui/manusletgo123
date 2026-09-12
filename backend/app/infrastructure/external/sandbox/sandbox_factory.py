"""Hybrid sandbox provider: E2B first (per-user isolation), Replit fallback.

Selection rules (sandbox_provider setting):
  - "auto" / "e2b" → try E2B when an API key is configured; on ANY failure
    (quota exhausted, invalid key, network, bootstrap timeout) transparently
    fall back to the shared Replit-local sandbox so user tasks never die.
  - "replit" → skip E2B entirely.

Additional safety:
  - An AuthenticationException (bad key) disables E2B for the process
    lifetime — no per-session retry storm.
  - RateLimitException (quota) disables E2B for 10 minutes (quota may reset
    or the billing window may roll over) — sessions meanwhile run on Replit.
  - Sandboxes are addressed as "e2b:<sandbox_id>" vs "replit-local" so
    reconnects route to the right provider from session.sandbox_id.
"""

import asyncio
import logging
import time
from typing import Optional

from app.core.config import get_settings
from app.domain.external.sandbox import Sandbox
from app.infrastructure.external.sandbox.replit_sandbox import ReplitSandbox

logger = logging.getLogger(__name__)

_AUTH_DISABLED = {"disabled": False}
_RATE_LIMIT_COOLDOWN: dict[str, float] = {"until": 0.0}
_COOLDOWN_SECONDS = 600  # 10 minutes


def _e2b_available() -> bool:
    """Check config + cached failure states without touching the network."""
    settings = get_settings()
    if _AUTH_DISABLED["disabled"]:
        return False
    if time.time() < _RATE_LIMIT_COOLDOWN["until"]:
        return False
    if settings.sandbox_provider == "replit":
        return False
    if not settings.e2b_api_key:
        return False
    return True


def _classify_failure(exc: Exception) -> str:
    """Map an E2B failure to a cooldown policy. Returns 'auth' | 'rate' | 'transient'."""
    name = type(exc).__name__
    try:
        import e2b  # noqa: F401

        if isinstance(exc, e2b.AuthenticationException):
            return "auth"
        if isinstance(exc, e2b.RateLimitException):
            return "rate"
    except Exception:
        pass
    # Quota-exhausted messages sometimes surface as generic SandboxException
    msg = str(exc).lower()
    if "quota" in msg or "rate limit" in msg or "payment" in msg or "credits" in msg:
        return "rate"
    if "unauthorized" in msg or "invalid api key" in msg or "authentication" in msg:
        return "auth"
    return "transient"


class HybridSandboxFactory:
    """Drop-in replacement for the ReplitSandbox class used as `sandbox_cls`.

    Exposes the same create()/get() async classmethods the domain service
    calls, but routes to E2B when possible and never lets an E2B failure
    crash session creation.
    """

    @classmethod
    async def create(cls) -> Sandbox:
        if _e2b_available():
            try:
                from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

                sandbox = await E2BSandbox.create()
                logger.info(
                    "HybridSandboxFactory: using E2B sandbox %s (per-user isolation)",
                    sandbox.id,
                )
                return sandbox
            except Exception as exc:
                kind = _classify_failure(exc)
                if kind == "auth":
                    _AUTH_DISABLED["disabled"] = True
                    logger.error(
                        "E2B authentication failed (%s) — E2B disabled for this "
                        "process; falling back to Replit sandbox permanently. "
                        "Check E2B_API_KEY.",
                        exc,
                    )
                elif kind == "rate":
                    _RATE_LIMIT_COOLDOWN["until"] = time.time() + _COOLDOWN_SECONDS
                    logger.warning(
                        "E2B quota/rate limit hit (%s) — E2B paused for %ds; "
                        "falling back to Replit sandbox meanwhile.",
                        exc,
                        _COOLDOWN_SECONDS,
                    )
                else:
                    logger.warning(
                        "E2B sandbox unavailable (%s: %s) — falling back to "
                        "Replit sandbox for this session.",
                        type(exc).__name__,
                        exc,
                    )
        return await ReplitSandbox.create()

    @classmethod
    async def get(cls, id: str) -> Sandbox:
        """Reconnect to the sandbox referenced by session.sandbox_id.

        E2B ids carry the "e2b:" prefix. If reconnecting fails (sandbox
        expired/removed, quota), the domain service's own fallback creates a
        fresh sandbox via create().
        """
        if id and id.startswith("e2b:") and _e2b_available():
            try:
                from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

                sandbox = await E2BSandbox.get(id)
                return sandbox
            except Exception as exc:
                kind = _classify_failure(exc)
                if kind == "auth":
                    _AUTH_DISABLED["disabled"] = True
                elif kind == "rate":
                    _RATE_LIMIT_COOLDOWN["until"] = time.time() + _COOLDOWN_SECONDS
                logger.warning(
                    "Failed to reconnect E2B sandbox %s (%s: %s)",
                    id,
                    type(exc).__name__,
                    exc,
                )
                # Raise a CLEAN, human-readable error instead of the raw e2b
                # SDK exception: aux endpoints (file view / shell view / VNC)
                # surface this directly to the UI, while the chat flow
                # (_create_task) catches it and transparently creates a fresh
                # sandbox — which the factory itself routes to Replit while
                # E2B is cooling down, so tasks keep running (home/runner).
                raise RuntimeError(
                    f"Sandbox {id} is no longer available "
                    f"({type(exc).__name__}). "
                    "The next task in this session will automatically continue "
                    "in the shared local sandbox."
                ) from exc
        return await ReplitSandbox.get(id)


def reset_failure_state_for_tests() -> None:
    """Test hook: clear cached auth/rate-limit decisions."""
    _AUTH_DISABLED["disabled"] = False
    _RATE_LIMIT_COOLDOWN["until"] = 0.0
