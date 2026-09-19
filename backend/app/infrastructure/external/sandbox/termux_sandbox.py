"""Termux-local Sandbox — the shared local sandbox running ON Android/Termux.

The sandbox stack on Termux is the same FastAPI sandbox service used on
Replit/z.ai (port 8080), started by ``start_termux.sh`` — but WITHOUT
supervisord (Termux has no init system). The sandbox app runs with
``SANDBOX_STANDALONE=1`` so its supervisor status endpoint degrades to a
synthetic RUNNING list and the standard ``ensure_sandbox()`` handshake
succeeds unchanged.

This class is deliberately a thin subclass of :class:`ReplitSandbox`:
everything (shell exec, file ops, admin commands, browser lazy connect)
behaves identically. Only the identity changes:

- ``id``       — ``"termux-local"`` (reconnect routing + UI badge)
- ``provider`` — ``"termux"`` (drives the Termux-accurate system prompt:
                 Android aarch64, Termux $PREFIX layout, pkg packages,
                 localhost services, no supervisord)

Selection happens in :mod:`app.infrastructure.external.sandbox.sandbox_factory`
via the Termux host guard (same policy as the Replit host guard: on a real
Termux host the local sandbox is used unless the operator explicitly forces
``SANDBOX_PROVIDER="e2b"``).
"""

from __future__ import annotations

import logging

from app.infrastructure.external.sandbox.replit_sandbox import ReplitSandbox

logger = logging.getLogger(__name__)


class TermuxSandbox(ReplitSandbox):
    """Shared local sandbox for the Termux (Android) deployment."""

    shared = True

    # Provider id consumed by the prompt assembly (system.py) — must say
    # "termux" so the agent never emits Replit/Debian paths or `apt` commands
    # on a Bionic-Linux phone.
    provider = "termux"

    _instance: "TermuxSandbox | None" = None  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self._id = "termux-local"
        logger.info(
            "TermuxSandbox initialised: base_url=%s (SANDBOX_STANDALONE Termux layout)",
            self.base_url,
        )
