"""Force-fit the sandbox Chrome window to the virtual display.

Why this exists
---------------
The sandbox desktop is a bare Xvfb screen (no window manager). Chrome is
launched with ``--window-size=1280,1029 --start-maximized``, but:

* ``--start-maximized`` requires a window manager to honour the maximize
  request — without one it is silently ignored;
* the initial ``--window-size`` only applies to the very first window; any
  later window (new tab promoted to a window, session restore, popup) gets
  an arbitrary size/position — usually floating in the middle of the
  desktop with empty space around it.

The result: the live VNC takeover view shows a small off-centre browser
window that does NOT match the agent's viewport screenshots (which are
captured from the page, not the desktop).

Fix: every time the backend connects to the browser over CDP we query the
window bounds and force them to exactly cover the Xvfb screen
(``left=0, top=0, width=W, height=H``). CDP ``Browser.setWindowBounds``
works without a window manager because it drives the X11 geometry from the
client side.

The display size is configurable via the ``SANDBOX_DISPLAY_SIZE`` setting
(default ``1280x1029`` — matching every supervisord config in the repo).
"""

import logging
import re
from typing import Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Display size cache — parsed once from settings, overridable for tests.
_cached_display_size: Optional[Tuple[int, int]] = None


def get_display_size() -> Tuple[int, int]:
    """Return the (width, height) of the sandbox virtual display."""
    global _cached_display_size
    if _cached_display_size is not None:
        return _cached_display_size
    try:
        from app.core.config import get_settings
        raw = getattr(get_settings(), "sandbox_display_size", None) or "1280x1029"
        match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(raw))
        if not match:
            raise ValueError(f"invalid display size {raw!r} (expected WxH, e.g. 1280x1029)")
        _cached_display_size = (int(match.group(1)), int(match.group(2)))
    except Exception as exc:  # config not ready / bad value — fall back to default
        logger.warning("get_display_size failed (%s) — defaulting to 1280x1029", exc)
        _cached_display_size = (1280, 1029)
    return _cached_display_size


# Type of the async CDP `send` callable both wrappers adapt to.
CdpSend = Callable[[str, Dict], Awaitable[Dict]]


async def fit_window(send: CdpSend, context_name: str = "browser", target_id: Optional[str] = None) -> bool:
    """Force the Chrome window to cover the whole display via CDP.

    ``send`` must accept ``("Domain.method", params_dict)`` and return the
    parsed result dict. ``target_id`` — when known — is passed to
    ``Browser.getWindowForTarget`` because that command resolves "the current
    target" from the caller's session, which fails with "No web contents in
    the target" on browser-level connections. Returns True when a correction
    was applied, False when the window already fit. Never raises — a failure
    to fit the window must not break the browser session it belongs to.
    """
    try:
        width, height = get_display_size()
        params = {"targetId": target_id} if target_id else {}
        target_info = await send("Browser.getWindowForTarget", params)
        window_id = target_info.get("windowId")
        current = (await send("Browser.getWindowBounds", {"windowId": window_id})).get(
            "bounds", {}
        )
        desired = {"left": 0, "top": 0, "width": width, "height": height}
        needs_fix = (
            current.get("windowState") not in ("normal", None)
            or any(current.get(key) != value for key, value in desired.items())
        )

        if not needs_fix:
            return False

        # windowState must be sent separately from a bounds change per CDP.
        if current.get("windowState") not in ("normal", None):
            await send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "normal"}},
            )
        await send("Browser.setWindowBounds", {"windowId": window_id, "bounds": desired})
        logger.info(
            "[%s] window fitted to display %dx%d (was left=%s top=%s %sx%s state=%s)",
            context_name, width, height,
            current.get("left"), current.get("top"),
            current.get("width"), current.get("height"),
            current.get("windowState"),
        )
        return True
    except Exception as exc:
        logger.warning("[%s] fit_window failed (non-fatal): %s", context_name, exc)
        return False


async def fit_window_to_display(page, context_name: str = "playwright") -> bool:
    """Playwright adapter: fit the window containing ``page`` (a Playwright Page)."""
    try:
        cdp = await page.context.newCDPSession(page)

        async def send(method: str, params: Dict) -> Dict:
            return await cdp.send(method, params)

        try:
            return await fit_window(send, context_name)
        finally:
            try:
                await cdp.detach()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[%s] fit_window_to_display failed (non-fatal): %s", context_name, exc)
        return False


async def fit_window_browser_use(session, context_name: str = "browser_use") -> bool:
    """browser-use adapter: fit the window of the session's focused target.

    ``session`` is a browser_use BrowserSession. Uses its CDP client; the
    Browser.* window commands are browser-level so any attached session works.
    """
    try:
        cdp_sess = await session.get_or_create_cdp_session()

        async def send(method: str, params: Dict) -> Dict:
            domain, _, method_name = method.partition(".")
            fn = getattr(getattr(cdp_sess.cdp_client.send, domain), method_name)
            return await fn(params=params)

        # target_id is required: browser-level connections cannot resolve
        # "the current target" on their own ("No web contents in the target").
        return await fit_window(send, context_name, target_id=cdp_sess.target_id)
    except Exception as exc:
        logger.warning("[%s] fit_window_browser_use failed (non-fatal): %s", context_name, exc)
        return False


async def clear_viewport_overrides_browser_use(session, context_name: str = "browser_use") -> int:
    """Clear stale Emulation.setDeviceMetricsOverride overrides on every page target.

    Earlier sessions (running with browser_use's default 1920x1080 viewport)
    leave a virtual-viewport override on every tab they touched. The override
    persists per-target until explicitly cleared, so switching to no-viewport
    mode alone is not enough for tabs that are already open. Returns the
    number of targets cleared; never raises.
    """
    cleared = 0
    try:
        cdp_sess = await session.get_or_create_cdp_session()
        targets = await cdp_sess.cdp_client.send.Target.getTargets(params={})
        page_targets = [
            t.get("targetId")
            for t in targets.get("targetInfos", [])
            if t.get("type") == "page" and t.get("targetId")
        ]
        for tid in page_targets:
            try:
                target_sess = await session.get_or_create_cdp_session(tid, focus=False)
                await target_sess.cdp_client.send.Emulation.clearDeviceMetricsOverride(
                    params={}, session_id=target_sess.session_id,
                )
                cleared += 1
            except Exception:
                continue
        if cleared:
            logger.info("[%s] cleared stale viewport overrides on %d page(s)", context_name, cleared)
    except Exception as exc:
        logger.warning(
            "[%s] clear_viewport_overrides failed (non-fatal): %s", context_name, exc
        )
    return cleared
