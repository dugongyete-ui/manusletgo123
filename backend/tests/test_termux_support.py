"""Termux (Android) deployment support — environment detection, sandbox
factory host guard, provider-accurate prompt, and graceful degradation.

Contract pinned here:
1. ``detect_environment()`` classifies a Termux host as ``"termux"``
   (TERMUX_VERSION marker or the com.termux $PREFIX layout).
2. The sandbox factory host guard: on a real Termux host, E2B is never
   consulted unless the operator EXPLICITLY sets SANDBOX_PROVIDER="e2b";
   the local sandbox class becomes TermuxSandbox (id "termux-local",
   provider "termux") so session ids and the agent prompt never lie.
3. ``get_system_prompt(environment="termux")`` describes Android/Termux
   reality (pkg, $PREFIX, no sudo, no FHS) and never mentions Replit-only
   paths or supervisord.
4. Search selector degradation: when curl_cffi is not installed (glibc-only
   wheels — common on Termux), scraping providers resolve to None instead
   of crashing search initialization.
"""

from __future__ import annotations

import pytest

from app.domain.services.mcp.environment import (
    _running_on_termux,
    detect_environment,
)
from app.domain.services.prompts.system import get_system_prompt
from app.infrastructure.external.sandbox import sandbox_factory
from app.infrastructure.external.sandbox.replit_sandbox import ReplitSandbox


# ── 1. environment detection ─────────────────────────────────────────────


def test_detect_environment_termux_marker(monkeypatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    assert detect_environment() == "termux"
    assert _running_on_termux() is True


def test_detect_environment_termux_prefix(monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setenv("PREFIX", "/data/data/com.termux.files/usr")
    assert detect_environment() == "termux"


def test_detect_environment_non_termux_unchanged(monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.delenv("TERMUX_MAIN_PACKAGE_FORMAT", raising=False)
    monkeypatch.setenv("PREFIX", "/usr")
    assert detect_environment() == "zai"


def test_replit_still_wins_over_termux(monkeypatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    monkeypatch.setenv("REPLIT_ENVIRONMENT", "production")
    assert detect_environment() == "replit"


# ── 2. sandbox factory host guard ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_factory_state():
    sandbox_factory.reset_failure_state_for_tests()
    yield
    sandbox_factory.reset_failure_state_for_tests()


def test_local_sandbox_class_is_termux_on_termux(monkeypatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    from app.infrastructure.external.sandbox.termux_sandbox import TermuxSandbox

    assert sandbox_factory._local_sandbox_cls() is TermuxSandbox


def test_local_sandbox_class_is_replit_elsewhere(monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setenv("PREFIX", "/usr")
    assert sandbox_factory._local_sandbox_cls() is ReplitSandbox


def test_termux_host_guard_skips_e2b(monkeypatch):
    """auto + E2B key present on a Termux host → E2B untouched (local)."""
    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    monkeypatch.setattr(
        sandbox_factory, "get_settings",
        lambda: type(
            "S", (),
            {
                "sandbox_provider": "auto",
                "e2b_api_key": "ek_live_test",
            },
        )(),
    )
    assert sandbox_factory._e2b_available() is False


def test_termux_explicit_e2b_overrides_guard(monkeypatch):
    """Operator forcing SANDBOX_PROVIDER=e2b on Termux is honoured."""
    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    monkeypatch.setattr(
        sandbox_factory, "get_settings",
        lambda: type(
            "S", (),
            {
                "sandbox_provider": "e2b",
                "e2b_api_key": "ek_live_test",
            },
        )(),
    )
    assert sandbox_factory._e2b_available() is True


def test_create_routes_to_termux_sandbox(monkeypatch):
    """On Termux, create() builds a TermuxSandbox singleton."""
    import asyncio

    monkeypatch.setenv("TERMUX_VERSION", "0.118.1")
    from app.infrastructure.external.sandbox.termux_sandbox import TermuxSandbox

    TermuxSandbox._instance = None

    async def _run():
        return await sandbox_factory.HybridSandboxFactory.create()

    sandbox = asyncio.run(_run())
    assert isinstance(sandbox, TermuxSandbox)
    assert sandbox.id == "termux-local"
    assert sandbox.provider == "termux"
    TermuxSandbox._instance = None


# ── 3. provider-accurate prompt ──────────────────────────────────────────


def test_termux_prompt_describes_android_reality():
    prompt = get_system_prompt(
        user_home="/data/data/com.termux/files/home/dzeck_users/abc",
        upload_dir="/data/data/com.termux/files/home/dzeck_users/abc/upload",
        environment="termux",
        protected_workspace="/data/data/com.termux/files/home/manusletgo123",
    )
    assert "Termux" in prompt
    assert "pkg install" in prompt
    assert "$PREFIX" in prompt
    assert "NO sudo" in prompt
    assert "/data/data/com.termux/files/home/dzeck_users/abc" in prompt


def test_termux_prompt_has_no_replit_claims():
    prompt = get_system_prompt(
        user_home="/home/dzeck/users/abc",
        upload_dir="/home/dzeck/users/abc/upload",
        environment="termux",
    )
    # The Replit block's LibreOffice claim must not leak into Termux.
    assert "LibreOffice" not in prompt or "NOT available" in prompt
    assert "supervisord" not in prompt


# ── 4. search degradation without curl_cffi ──────────────────────────────


@pytest.fixture()
def _no_curl_cffi(monkeypatch):
    from app.infrastructure.external.search import __init__ as search_init  # noqa: F401


def test_search_selector_degrades_without_curl_cffi(monkeypatch):
    """curl_cffi missing → scraping providers resolve to None (no crash)."""
    from app.infrastructure.external import search as search_pkg

    monkeypatch.setattr(search_pkg, "_curl_cffi_available", lambda: False)
    search_pkg.get_search_engine.cache_clear()
    monkeypatch.setattr(
        search_pkg, "get_settings",
        lambda: type(
            "S", (),
            {
                "search_provider": "bing_web",
                "bing_search_api_key": "",
            },
        )(),
    )
    assert search_pkg.get_search_engine() is None
    search_pkg.get_search_engine.cache_clear()


def test_search_selector_uses_scraping_with_curl_cffi(monkeypatch):
    """curl_cffi present → scraping provider still constructs (no regression)."""
    from app.infrastructure.external import search as search_pkg

    monkeypatch.setattr(search_pkg, "_curl_cffi_available", lambda: True)
    search_pkg.get_search_engine.cache_clear()
    monkeypatch.setattr(
        search_pkg, "get_settings",
        lambda: type(
            "S", (),
            {
                "search_provider": "bing_web",
                "bing_search_api_key": "",
            },
        )(),
    )
    engine = search_pkg.get_search_engine()
    assert engine is not None
    search_pkg.get_search_engine.cache_clear()
