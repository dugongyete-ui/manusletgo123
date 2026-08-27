"""Unit tests for HybridSandboxFactory fallback behaviour (E2B → Replit).

The promise under test: a session must NEVER crash because E2B is
unavailable (quota exhausted, invalid key, network error, bootstrap
failure). Every failure mode transparently falls back to the shared
Replit sandbox.
"""

import asyncio

import pytest

import app.infrastructure.external.sandbox.sandbox_factory as factory_mod
from app.infrastructure.external.sandbox.sandbox_factory import (
    HybridSandboxFactory,
    reset_failure_state_for_tests,
)


class FakeReplitSandbox:
    shared = True
    _instance = None

    @classmethod
    async def create(cls):
        cls._instance = cls._instance or cls()
        return cls._instance

    @classmethod
    async def get(cls, id):
        cls._instance = cls._instance or cls()
        return cls._instance


class FakeE2BError(Exception):
    pass


@pytest.fixture(autouse=True)
def isolated_factory(monkeypatch, tmp_path):
    """Point the factory at fakes and reset cached failure state per test."""
    reset_failure_state_for_tests()
    monkeypatch.setattr(
        factory_mod,
        "get_settings",
        lambda: type("S", (), {
            "sandbox_provider": "auto",
            "e2b_api_key": "e2b_test_key",
            "e2b_sandbox_timeout": 3600,
        })(),
    )
    # Patch ReplitSandbox inside the factory module
    monkeypatch.setattr(factory_mod, "ReplitSandbox", FakeReplitSandbox)
    yield
    reset_failure_state_for_tests()


def _patch_e2b(monkeypatch, factory_result):
    """Make E2BSandbox.create() return or raise factory_result."""
    class FakeE2BSandbox:
        shared = False

        def __init__(self):
            self.id = "e2b:fake123"

    async def fake_create():
        if isinstance(factory_result, Exception):
            raise factory_result
        return FakeE2BSandbox()

    async def fake_get(sandbox_id):
        if isinstance(factory_result, Exception):
            raise factory_result
        return FakeE2BSandbox()

    import types
    fake_module = types.ModuleType("app.infrastructure.external.sandbox.e2b_sandbox")
    fake_module.E2BSandbox = types.SimpleNamespace(create=fake_create, get=fake_get)
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.infrastructure.external.sandbox.e2b_sandbox",
        fake_module,
    )
    # Force the factory's lazy import to hit the fake
    import builtins
    real_import = builtins.__import__

    def stubbed_import(name, *args, **kwargs):
        if name == "app.infrastructure.external.sandbox.e2b_sandbox":
            return fake_module
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stubbed_import)


def test_create_prefers_e2b_when_healthy(monkeypatch):
    _patch_e2b(monkeypatch, None)
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert sandbox.id == "e2b:fake123"


def test_create_falls_back_on_transient_error(monkeypatch):
    _patch_e2b(monkeypatch, FakeE2BError("network unreachable"))
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)


def test_create_falls_back_on_quota_error(monkeypatch):
    _patch_e2b(monkeypatch, FakeE2BError("quota exceeded for this API key"))
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)


def test_rate_limit_introduces_cooldown(monkeypatch):
    _patch_e2b(monkeypatch, FakeE2BError("rate limit exceeded"))
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)
    # During cooldown E2B is skipped without even trying (still works)
    sandbox2 = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox2, FakeReplitSandbox)


def test_auth_error_disables_e2b_permanently(monkeypatch):
    _patch_e2b(monkeypatch, FakeE2BError("401 unauthorized invalid api key"))
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)
    assert factory_mod._AUTH_DISABLED["disabled"] is True
    # Second create does not attempt E2B again — still Replit
    sandbox2 = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox2, FakeReplitSandbox)


def test_replit_provider_skips_e2b(monkeypatch):
    import app.infrastructure.external.sandbox.sandbox_factory as fm
    original = fm._e2b_available

    def provider_replit():
        # simulate sandbox_provider == "replit"
        return False

    monkeypatch.setattr(fm, "_e2b_available", provider_replit)
    _patch_e2b(monkeypatch, None)
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)
    monkeypatch.setattr(fm, "_e2b_available", original)


def test_missing_api_key_skips_e2b(monkeypatch):
    monkeypatch.setattr(
        factory_mod,
        "get_settings",
        lambda: type("S", (), {
            "sandbox_provider": "auto",
            "e2b_api_key": None,
            "e2b_sandbox_timeout": 3600,
        })(),
    )
    _patch_e2b(monkeypatch, None)  # E2B would work if it were consulted
    sandbox = asyncio.run(HybridSandboxFactory.create())
    assert isinstance(sandbox, FakeReplitSandbox)


def test_get_routes_e2b_ids_to_e2b(monkeypatch):
    _patch_e2b(monkeypatch, None)
    sandbox = asyncio.run(HybridSandboxFactory.get("e2b:abc123"))
    assert sandbox.id == "e2b:fake123"


def test_get_routes_replit_ids_to_replit(monkeypatch):
    _patch_e2b(monkeypatch, None)
    sandbox = asyncio.run(HybridSandboxFactory.get("replit-local"))
    assert isinstance(sandbox, FakeReplitSandbox)


def test_get_e2b_reconnect_failure_raises_for_domain_fallback(monkeypatch):
    """get() on a dead E2B sandbox raises so the domain service creates a new one."""
    _patch_e2b(monkeypatch, FakeE2BError("sandbox not found"))
    with pytest.raises(FakeE2BError):
        asyncio.run(HybridSandboxFactory.get("e2b:gone"))


def test_classify_failure_kinds():
    classify = factory_mod._classify_failure
    assert classify(FakeE2BError("API quota exceeded")) == "rate"
    assert classify(FakeE2BError("401 unauthorized invalid api key")) == "auth"
    assert classify(FakeE2BError("connection reset")) == "transient"
    assert classify(FakeE2BError("not enough credits/payment required")) == "rate"
    assert classify(FakeE2BError("Authentication failed for key")) == "auth"
