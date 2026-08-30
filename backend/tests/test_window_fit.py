"""Unit tests for the per-sandbox window fit (window_fit.py).

The regression under test: fit_window used the GLOBAL SANDBOX_DISPLAY_SIZE
(1280x1029 — the replit/local Xvfb screen) for EVERY sandbox, including E2B
whose microVM display is 1024x768. Chrome silently honours oversized bounds,
so the E2B browser window overflowed its display and the live VNC takeover
showed a shifted/cropped view while Replit looked fine.

The fix: callers pass the sandbox's real display size; the global setting is
only a fallback. These tests pin that contract with a fake CDP ``send``.
"""

import asyncio
from typing import Dict

import pytest

import app.infrastructure.external.browser.window_fit as wf


class FakeCDP:
    """Records Browser.* calls; window starts in a floating state."""

    def __init__(self, left=20, top=20, width=900, height=600, state="normal"):
        self.calls: list = []
        self.bounds = {"left": left, "top": top, "width": width, "height": height,
                       "windowState": state}
        self.window_id = 42

    async def __call__(self, method: str, params: Dict) -> Dict:
        self.calls.append((method, dict(params)))
        if method == "Browser.getWindowForTarget":
            return {"windowId": self.window_id}
        if method == "Browser.getWindowBounds":
            return {"bounds": dict(self.bounds)}
        if method == "Browser.setWindowBounds":
            bounds = params.get("bounds", {})
            if "windowState" in bounds:
                self.bounds["windowState"] = bounds["windowState"]
            else:
                self.bounds.update(bounds)
            return {}
        raise AssertionError(f"unexpected CDP method {method}")

    def last_set_bounds(self):
        for method, params in reversed(self.calls):
            if method == "Browser.setWindowBounds" and "left" in params.get("bounds", {}):
                return params["bounds"]
        return None


@pytest.fixture(autouse=True)
def clean_cache():
    wf._cached_display_size = None
    yield
    wf._cached_display_size = None


class TestFitWindowDisplaySize:
    def test_explicit_display_size_is_used(self):
        """E2B path: (1024, 768) must be sent, NOT the global 1280x1029."""
        cdp = FakeCDP()

        async def run():
            return await wf.fit_window(cdp, "e2b", target_id="T1", display_size=(1024, 768))

        assert asyncio.run(run()) is True
        sent = cdp.last_set_bounds()
        assert sent == {"left": 0, "top": 0, "width": 1024, "height": 768}

    def test_fallback_uses_settings_when_no_display_size(self, monkeypatch):
        """Replit path: no explicit size → global SANDBOX_DISPLAY_SIZE."""
        monkeypatch.setattr(
            wf, "get_display_size", lambda: (1280, 1029)
        )
        cdp = FakeCDP()

        async def run():
            return await wf.fit_window(cdp, "replit")

        asyncio.run(run())
        sent = cdp.last_set_bounds()
        assert sent == {"left": 0, "top": 0, "width": 1280, "height": 1029}

    def test_no_fix_needed_when_window_already_fits(self):
        cdp = FakeCDP(left=0, top=0, width=1024, height=768)

        async def run():
            return await wf.fit_window(cdp, "e2b", display_size=(1024, 768))

        assert asyncio.run(run()) is False
        assert cdp.last_set_bounds() is None

    def test_never_raises_on_cdp_error(self):
        async def boom(method, params):
            raise RuntimeError("Browser window not found")

        async def run():
            return await wf.fit_window(boom, "broken", display_size=(1024, 768))

        assert asyncio.run(run()) is False


class TestAdaptersAcceptDisplaySize:
    def test_browser_use_browser_stores_display_size(self):
        """BrowserUseBrowser must carry the sandbox display size to its fit call."""
        from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser

        b = BrowserUseBrowser("ws://x", display_size=(1024, 768))
        assert b._display_size == (1024, 768)
        assert BrowserUseBrowser("ws://x")._display_size is None

    def test_playwright_browser_stores_display_size(self):
        from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser

        b = PlaywrightBrowser("http://x", display_size=(1024, 768))
        assert b._display_size == (1024, 768)
        assert PlaywrightBrowser("http://x")._display_size is None


class TestE2BDisplayConstants:
    def test_e2b_constants_match_bootstrap(self):
        """The Xvfb screen, --window-size and window fit must stay in sync."""
        import importlib
        import re

        spec = importlib.util.find_spec(
            "app.infrastructure.external.sandbox.e2b_sandbox"
        )
        assert spec and spec.origin
        src = open(spec.origin).read()
        assert "_DISPLAY_W = 1024" in src and "_DISPLAY_H = 768" in src
        # Xvfb screen uses the constants
        assert "screen 0 {_DISPLAY_W}x{_DISPLAY_H}x24" in src
        # chrome --window-size uses the constants
        assert "--window-size={_DISPLAY_W},{_DISPLAY_H}" in src
        # get_browser passes the constants to both browser adapters
        assert "display_size=(_DISPLAY_W, _DISPLAY_H)" in src
        # the raw numbers must NOT appear hardcoded anymore (single source)
        assert "screen 0 1024x768x24" not in src
        assert "--window-size=1024,768" not in src


class TestFitWindowRawWsUrlHandling:
    def test_http_url_fails_gracefully_when_offline(self):
        """Unreachable endpoint → 0 windows fitted, no exception."""
        async def run():
            return await wf.fit_window_raw_ws(
                "http://127.0.0.1:1", display_size=(1024, 768), attempts=1
            )

        assert asyncio.run(run()) == 0
