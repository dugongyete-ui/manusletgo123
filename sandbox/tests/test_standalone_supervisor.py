"""Standalone-mode tests for the sandbox supervisor service (no supervisord).

Termux (Android) has no init system — the sandbox app runs WITHOUT
supervisord. These tests pin the fail-open contract:

1. importing the supervisor service must never crash when the RPC socket
   is absent (it used to raise at import time and take the whole app down);
2. with SANDBOX_STANDALONE=1 the status endpoint contract reports a single
   synthetic RUNNING ``app`` process — exactly what the backend's
   ``ensure_sandbox()`` handshake needs to consider the sandbox ready.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest

SANDBOX_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SANDBOX_ROOT))


@pytest.fixture()
def standalone_service(monkeypatch):
    """Fresh SupervisorService in standalone mode (no supervisord socket)."""
    monkeypatch.setenv("SANDBOX_STANDALONE", "1")
    import app.services.supervisor as supervisor_module

    mod = importlib.reload(supervisor_module)
    service = mod.SupervisorService()
    yield service
    monkeypatch.delenv("SANDBOX_STANDALONE", raising=False)
    importlib.reload(supervisor_module)


def test_import_survives_missing_supervisord(monkeypatch):
    """No supervisord socket → import + singleton init must NOT raise.

    On hosts where a live supervisord socket exists (Replit/z.ai) the RPC
    connects normally (server is a ServerProxy); on hosts without one the
    fail-open path keeps ``server = None``. Either way the import and the
    global singleton must succeed — that is the contract that used to be
    broken (ResourceNotFoundError raised at import time).
    """
    monkeypatch.delenv("SANDBOX_STANDALONE", raising=False)
    import app.services.supervisor as supervisor_module

    mod = importlib.reload(supervisor_module)
    assert mod.supervisor_service is not None
    # With a live supervisord the server object exists; without one it is
    # None. Both are legal — the assertion is "did not raise".
    assert mod.supervisor_service.server is None or hasattr(
        mod.supervisor_service.server, "supervisor"
    )


def test_standalone_reports_synthetic_running_app(standalone_service):
    """Standalone mode → one synthetic RUNNING 'app' process."""
    processes = asyncio.get_event_loop().run_until_complete(
        standalone_service.get_all_processes()
    )
    assert len(processes) == 1
    app = processes[0]
    assert app.name == "app"
    assert app.statename == "RUNNING"
    assert app.pid == os.getpid()


def test_standalone_flag_skips_rpc_connect(monkeypatch):
    """SANDBOX_STANDALONE=1 → _connect_rpc short-circuits (server None)."""
    monkeypatch.setenv("SANDBOX_STANDALONE", "1")
    import app.services.supervisor as supervisor_module

    mod = importlib.reload(supervisor_module)
    service = mod.SupervisorService()
    assert service.standalone is True
    assert service.server is None
