"""Tests for the Replit-host environment-consistency guarantee.

Requirement: "kalau di lingkungan Replit ya 100% di lingkungan Replit,
tidak loncat ke E2B" — when the process runs on a real Replit host
(home/runner layout), E2B must never be touched, and every path the agent
sees must resolve to the Replit layout (/home/runner/...), never the E2B
layout (/home/user/...).
"""

import asyncio
import os

import pytest

import app.infrastructure.external.sandbox.sandbox_factory as factory_mod
from app.infrastructure.external.sandbox.sandbox_factory import (
    HybridSandboxFactory,
    reset_failure_state_for_tests,
    _e2b_available,
    _running_on_replit,
)


_REPLIT_ENV = {
    "REPLIT_ENVIRONMENT": "production",
    "REPL_ID": "dzeck-abc123",
    "REPL_OWNER": "manusletgo123",
}


class FakeReplitSandbox:
    shared = True
    provider = "replit"
    _instance = None

    @classmethod
    async def create(cls):
        cls._instance = cls._instance or cls()
        return cls._instance

    @classmethod
    async def get(cls, id):
        cls._instance = cls._instance or cls()
        return cls._instance


@pytest.fixture(autouse=True)
def isolated_factory(monkeypatch):
    """Reset cached failure state and isolate env between tests."""
    reset_failure_state_for_tests()
    monkeypatch.setattr(factory_mod, "ReplitSandbox", FakeReplitSandbox)
    yield
    reset_failure_state_for_tests()


def _settings(provider="auto", key="e2b_valid_key"):
    return type("S", (), {
        "sandbox_provider": provider,
        "e2b_api_key": key,
        "e2b_sandbox_timeout": 3600,
    })()


# ── Host detection ────────────────────────────────────────────────────────────


def test_detects_replit_host_markers(monkeypatch):
    for marker, value in _REPLIT_ENV.items():
        monkeypatch.setenv(marker, value)
    assert _running_on_replit() is True


def test_no_replit_markers_off_host(monkeypatch):
    for marker in list(_REPLIT_ENV) + ["REPLIT_DEVBOX_ID", "REPLIT_DEPLOYMENT"]:
        monkeypatch.delenv(marker, raising=False)
    assert _running_on_replit() is False


# ── E2B availability on a Replit host ────────────────────────────────────────


def test_on_replit_auto_never_touches_e2b(monkeypatch):
    """THE core guarantee: Replit host + auto + a perfectly valid E2B key
    still never consults E2B — 100% Replit sandbox."""
    for marker, value in _REPLIT_ENV.items():
        monkeypatch.setenv(marker, value)
    monkeypatch.setattr(factory_mod, "get_settings", lambda: _settings("auto"))
    assert _e2b_available() is False
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)


def test_on_replit_stale_e2b_session_id_not_reconnected(monkeypatch):
    """Reconnect requests for stale e2b:* sessions on a Replit host land on
    the Replit sandbox WITHOUT touching the E2B SDK (graceful continuation —
    the task keeps running on home/runner instead of erroring out)."""
    for marker, value in _REPLIT_ENV.items():
        monkeypatch.setenv(marker, value)
    monkeypatch.setattr(factory_mod, "get_settings", lambda: _settings("auto"))

    class Sentinel:
        @classmethod
        async def get(cls, sandbox_id):
            raise AssertionError("E2B SDK must not be touched on a Replit host")

    import sys, types
    fake_module = types.ModuleType("app.infrastructure.external.sandbox.e2b_sandbox")
    fake_module.E2BSandbox = Sentinel
    monkeypatch.setitem(sys.modules, "app.infrastructure.external.sandbox.e2b_sandbox", fake_module)

    sandbox = asyncio.run(HybridSandboxFactory.get("e2b:stale123"))
    assert isinstance(sandbox, FakeReplitSandbox)


def test_on_replit_explicit_e2b_override_honoured(monkeypatch):
    """Documented escape hatch: SANDBOX_PROVIDER=e2b explicitly set by the
    operator overrides the host guard (deliberate choice, not a silent jump)."""
    for marker, value in _REPLIT_ENV.items():
        monkeypatch.setenv(marker, value)
    monkeypatch.setattr(factory_mod, "get_settings", lambda: _settings("e2b"))
    assert _e2b_available() is True


def test_off_replit_auto_still_prefers_e2b(monkeypatch):
    """Off-host behaviour unchanged: auto + valid key → E2B available."""
    for marker in list(_REPLIT_ENV) + ["REPLIT_DEVBOX_ID", "REPLIT_DEPLOYMENT"]:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setattr(factory_mod, "get_settings", lambda: _settings("auto"))
    assert _e2b_available() is True


def test_off_replit_local_still_skips_e2b(monkeypatch):
    for marker in list(_REPLIT_ENV) + ["REPLIT_DEVBOX_ID", "REPLIT_DEPLOYMENT"]:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setattr(factory_mod, "get_settings", lambda: _settings("local"))
    assert _e2b_available() is False


# ── Replit home/runner path chain ─────────────────────────────────────────────


def test_replit_home_chain_defaults_to_runner(monkeypatch):
    """With NO env overrides (as on a fresh Replit deployment — .env is
    gitignored), the whole chain resolves to the /home/runner layout."""
    monkeypatch.delenv("USER_HOME_ROOT", raising=False)

    # Fresh Settings instance ignoring any local .env file — simulates a
    # clean Replit checkout where only [userenv] shell env exists
    from app.core.config import Settings
    settings = Settings(_env_file=None, sandbox_provider="replit")
    assert settings.user_home_root == "/home/runner/users"
    assert settings.sandbox_protected_paths == "/home/runner/workspace"

    # UserScopedSandbox reads get_settings() at init — point it at the
    # clean-Replit settings instance for the duration of this test
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)

    class _Inner:
        shared = True
        provider = "replit"

    from app.infrastructure.external.sandbox.user_sandbox import UserScopedSandbox

    scoped = UserScopedSandbox(_Inner(), "uid42")
    assert scoped.user_home == "/home/runner/users/uid42"
    assert scoped.upload_dir == "/home/runner/users/uid42/upload"
    # Zero E2B-layout paths anywhere in the resolved chain
    assert "/home/user" not in scoped.user_home
    assert "/home/user" not in scoped.upload_dir


def test_replit_prompt_has_no_e2b_paths():
    """The 'replit' prompt variant must never leak the E2B home layout."""
    from app.domain.services.prompts.system import get_system_prompt

    prompt = get_system_prompt(
        user_home="/home/runner/users/uid42",
        upload_dir="/home/runner/users/uid42/upload",
        environment="replit",
    )
    assert "/home/user" not in prompt
    assert "/home/runner/users/uid42" in prompt
