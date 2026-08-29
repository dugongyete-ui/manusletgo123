from typing import Any, Optional, List
import asyncio
import logging

from browser_use.browser.session import BrowserSession, CDPSession
from browser_use.dom.views import EnhancedDOMTreeNode

from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)


class BrowserUseBrowser:
    """Browser implementation using the browser_use library (BrowserSession + CDP).

    Connects to an existing Chrome instance via CDP URL and exposes the same
    interface as PlaywrightBrowser so it can be used as a drop-in replacement.
    """

    def __init__(self, cdp_url: str, heal_hook=None):
        self.cdp_url = cdp_url
        # Optional async callable invoked when the CDP endpoint refuses
        # connections (e.g. HTTP 502 from the in-VM proxy) — the signature of a
        # DEAD browser process. The hook (provided by the sandbox layer) relaunches
        # the browser inside its environment, so mid-task crashes self-heal
        # instead of exhausting all retries. No-op when not provided.
        self._heal_hook = heal_hook
        self._session: Optional[BrowserSession] = None
        # Cached actor Page for the currently focused tab.
        # browser_use's session.get_current_page() constructs a NEW Page object
        # (with _session_id=None) on EVERY call, so each operation would attach a
        # fresh CDP session — leaking sessions and, critically, making any
        # DOM.getDocument setup useless for the next Page object (root cause of
        # the -32000 "Document needs to be requested first" failures).
        self._cached_page = None
        # Targets that already have the console-capture init script registered
        # via Page.addScriptToEvaluateOnNewDocument (avoids duplicate scripts).
        self._console_capture_targets: set = set()
        # Signature (frozen tuple) of the interactive-element list from the
        # most recent observation — used to tell the model whether a click
        # VISIBLY changed the page (menu opened/closed, modal, new items),
        # not just whether the URL changed. browser-use exposes the same
        # signal implicitly via its DOM snapshot diffing.
        self._last_elements_signature: Optional[tuple] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> BrowserSession:
        """Return a started BrowserSession, initialising it if necessary.

        Uses generous retries because the first browser tool call may arrive
        while Chrome is still warming up in the Replit sandbox.
        """
        if self._session is not None:
            return self._session

        # Generous retry budget: up to ~3 minutes total (15 attempts × up to 30 s each)
        max_retries = 15
        retry_delay = 2.0
        last_error: Exception = RuntimeError("Unknown error")

        for attempt in range(max_retries):
            try:
                session = BrowserSession(
                    cdp_url=self.cdp_url,
                    minimum_wait_page_load_time=0.5,
                    wait_for_network_idle_page_load_time=2.0,
                    highlight_elements=False,
                )
                await session.start()
                self._session = session
                logger.info("BrowserSession connected to CDP: %s", self.cdp_url)
                return session
            except Exception as exc:
                last_error = exc
                await self.cleanup()
                if attempt == max_retries - 1:
                    logger.error(
                        "Failed to initialise BrowserSession after %d attempts: %s",
                        max_retries,
                        exc,
                    )
                    raise
                # webSocketDebuggerUrl missing → Chrome not yet ready; back off longer
                exc_str = str(exc)
                if "webSocketDebuggerUrl" in exc_str:
                    retry_delay = min(retry_delay * 2, 30.0)
                    logger.warning(
                        "Chrome CDP not ready (attempt %d/%d) — webSocketDebuggerUrl missing, "
                        "Chrome may still be starting. Retrying in %.0fs…",
                        attempt + 1, max_retries, retry_delay,
                    )
                elif ("502" in exc_str or "rejected" in exc_str.lower()) and self._heal_hook is not None:
                    # HTTP 502 / WS rejected = the proxy is alive but the browser
                    # process behind it is DEAD (crashed mid-task, OOM, etc.).
                    # Plain retries can never fix that — ask the sandbox layer to
                    # relaunch the browser, then reconnect.
                    retry_delay = min(retry_delay * 1.5, 15.0)
                    logger.warning(
                        "CDP endpoint refuses connections (attempt %d/%d) — "
                        "invoking browser heal hook to relaunch it: %s",
                        attempt + 1, max_retries, exc_str[:120],
                    )
                    try:
                        await asyncio.wait_for(self._heal_hook(), timeout=150.0)
                    except Exception as heal_exc:
                        logger.warning("Browser heal hook failed: %s", heal_exc)
                else:
                    retry_delay = min(retry_delay * 1.5, 15.0)
                    logger.warning(
                        "BrowserSession init failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, max_retries, retry_delay, exc,
                    )
                await asyncio.sleep(retry_delay)

        raise last_error

    async def cleanup(self) -> None:
        """Stop the browser session and release resources."""
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception as exc:
                logger.error("Error stopping BrowserSession: %s", exc)
            finally:
                self._session = None
        self._cached_page = None
        self._console_capture_targets.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_current_page(self):
        """Return the actor Page for the currently focused tab (CACHED per target).

        browser_use's session.get_current_page() builds a new Page object on
        every call — each starting with _session_id=None — so every caller
        attached a brand-new CDP session (Target.attachToTarget). That leaked
        sessions AND meant DOM.getDocument called on one Page never applied to
        the next Page's session, reproducing CDP -32000 "Document needs to be
        requested first" on every element.evaluate() based tool. Caching the
        Page per target_id keeps ONE stable session per tab.

        The cache is validated with a cheap liveness probe so a CDP websocket
        reconnect (which clears all sessions) transparently re-attaches a
        fresh session instead of hanging forever on a dead one.
        """
        session = await self._ensure_session()
        current_target = getattr(session, "agent_focus_target_id", None)
        if (
            self._cached_page is not None
            and current_target is not None
            and getattr(self._cached_page, "_target_id", None) == current_target
        ):
            if await self._page_session_alive(self._cached_page):
                return self._cached_page
            logger.info("Cached page session is stale — re-attaching a fresh CDP session")
            self._cached_page = None
        # get_current_page()/new_page() go through the CDP websocket (possibly
        # via a remote proxy). When the browser VM stalls, the underlying CDP
        # send can hang for minutes with no internal timeout — bound them so
        # the tool call fails fast and the agent's retry budget kicks in.
        page = await self._call_with_deadline(session.get_current_page(), timeout=30.0)
        if page is None:
            page = await self._call_with_deadline(session.new_page(), timeout=30.0)
        self._cached_page = page
        return page

    async def _page_session_alive(self, page) -> bool:
        """Cheap liveness probe for a cached page's CDP session."""
        try:
            session_id = getattr(page, "_session_id", None)
            if not session_id:
                return False
            await self._call_with_deadline(
                page._client.send.Runtime.evaluate(
                    params={"expression": "1", "returnByValue": True},
                    session_id=session_id,
                ),
                timeout=3.0,
            )
            return True
        except Exception:
            return False

    async def _get_cdp_session(self) -> CDPSession:
        """Return the CDPSession for the currently focused tab."""
        session = await self._ensure_session()
        # Bounded: get_or_create_cdp_session can stall indefinitely on a hung
        # CDP websocket (same class of hang as get_current_page).
        return await self._call_with_deadline(
            session.get_or_create_cdp_session(), timeout=30.0
        )

    async def _call_with_deadline(self, coro, timeout: float):
        """Await `coro` with a hard deadline, ABANDONING it on timeout.

        Unlike asyncio.wait_for(), this never waits for the cancelled task to
        actually finish: cdp_use send futures do not react to cancellation
        while the CDP websocket is reconnecting, so wait_for would hang
        forever in its cancellation wait. asyncio.wait() leaves the timed-out
        task running (it is garbage once the session is re-established).
        """
        task = asyncio.ensure_future(coro)
        done, _pending = await asyncio.wait({task}, timeout=timeout)
        if done:
            return task.result()
        task.cancel()  # best-effort cancel; do NOT await it
        raise asyncio.TimeoutError()

    async def _ensure_dom_document(self) -> None:
        """Ensure the page's CDP session has an active DOM document.

        Element.evaluate() resolves elements through
        DOM.pushNodesByBackendIdsToFrontend, which fails with CDP error -32000
        "Document needs to be requested first" unless DOM.getDocument has been
        called on that session. Page._ensure_session() only enables the DOM
        domain — it never requests the document — so every element.evaluate()
        based tool (get_select_options / smart_select / verify_value / click
        strategies 2–3) failed. Calling DOM.getDocument here is cheap and
        idempotent, so we do it before each element interaction.
        """
        try:
            page = await self._get_current_page()
            session_id = await page._ensure_session()
            await page._client.send.DOM.getDocument(
                params={"depth": 1},
                session_id=session_id,
            )
        except Exception as exc:
            logger.debug("DOM.getDocument failed (non-fatal): %s", exc)

    # Map from CSS icon-font class keywords → human-readable symbol.
    # Covers Layui icons used by the leaftools.net calculator (and similar sites).
    _ICON_CLASS_SYMBOLS: dict = {
        "layui-icon-addition": "+",
        "layui-icon-subtraction": "-",
        "layui-icon-close": "×",
        "layui-icon-search": "🔍",
        "layui-icon-refresh": "↻",
        "layui-icon-left": "←",
        "layui-icon-right": "→",
        "layui-icon-up": "↑",
        "layui-icon-down": "↓",
        "bi-backspace": "⌫",
        "bi-plus-slash-minus": "±",
        # generic fallbacks
        "addition": "+",
        "subtraction": "-",
        "multiply": "×",
        "divide": "÷",
        "equals": "=",
        "backspace": "⌫",
        "clear": "C",
    }

    @staticmethod
    def _get_node_hint(node) -> str:
        """Return a human-readable hint for a node whose visible text is empty.

        Priority order:
        1. ``data-key`` / ``data-val`` attribute on the node itself (e.g. calculator buttons)
        2. AX accessibility tree ``name`` field
        3. CSS icon-font class keywords on the node's child <i> / <span> / <svg>
        """
        attrs: dict = getattr(node, "attributes", None) or {}

        # 1. data-key / data-val (most reliable for widget buttons)
        for attr in ("data-key", "data-val", "data-value"):
            val = attrs.get(attr, "").strip()
            if val:
                return val

        # 2. AX name
        ax_node = getattr(node, "ax_node", None)
        if ax_node:
            ax_name = getattr(ax_node, "name", None) or ""
            if ax_name.strip():
                return ax_name.strip()

        # 3. Icon-font class on child elements
        children = getattr(node, "children_nodes", None) or []
        for child in children:
            child_tag = (getattr(child, "tag_name", "") or "").lower()
            if child_tag not in ("i", "span", "em", "svg", "use"):
                continue
            child_attrs: dict = getattr(child, "attributes", None) or {}
            class_str = child_attrs.get("class", "").lower()
            for keyword, symbol in BrowserUseBrowser._ICON_CLASS_SYMBOLS.items():
                if keyword in class_str:
                    return symbol

        return ""

    @staticmethod
    def _format_selector_map(selector_map: dict) -> List[str]:
        """Format a selector map dict into the standard index:<tag>text</tag> list."""
        formatted: List[str] = []
        for idx, node in sorted(selector_map.items()):
            tag = node.tag_name or "element"
            text = node.get_meaningful_text_for_llm() if hasattr(node, "get_meaningful_text_for_llm") else ""

            # Fallback: explicit HTML attributes (placeholder / aria-label / title)
            if not text and node.attributes:
                text = (
                    node.attributes.get("placeholder", "")
                    or node.attributes.get("aria-label", "")
                    or node.attributes.get("title", "")
                    or ""
                )

            # Fallback: data-key / AX name / icon-font class
            if not text:
                text = BrowserUseBrowser._get_node_hint(node)

            if len(text) > 100:
                text = text[:97] + "..."
            formatted.append(f"{idx}:<{tag}>{text}</{tag}>")
        return formatted

    async def _get_interactive_elements(self) -> List[str]:
        """Return a formatted list of interactive elements from the DOM selector map.

        browser_use's get_selector_map() only returns populated data after
        get_browser_state_summary() has been called (which triggers the DOM
        serialisation event).  If the cached map is empty we trigger a fresh
        state summary to ensure the selector map is populated.
        """
        try:
            session = await self._ensure_session()
            selector_map: dict[int, EnhancedDOMTreeNode] = await session.get_selector_map()

            if not selector_map:
                logger.debug(
                    "Selector map is empty – triggering get_browser_state_summary to populate DOM cache"
                )
                state = await session.get_browser_state_summary(include_screenshot=False)
                if state.dom_state is not None:
                    selector_map = state.dom_state.selector_map or {}

            return self._format_selector_map(selector_map)
        except Exception as exc:
            logger.warning("Failed to get interactive elements: %s", exc)
            return []

    async def _dispatch_mouse_event(
        self,
        event_type: str,
        x: float,
        y: float,
        button: str = "none",
        click_count: int = 0,
    ) -> None:
        """Send a raw CDP mouse event to the currently focused tab."""
        cdp_sess = await self._get_cdp_session()
        params: dict[str, Any] = {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "clickCount": click_count,
        }
        await cdp_sess.cdp_client.send.Input.dispatchMouseEvent(
            params=params,
            session_id=str(cdp_sess.session_id),
        )

    async def _get_element_center(self, element) -> Optional[tuple]:
        """Get the center (x, y) of an element via JS getBoundingClientRect.

        Returns (cx, cy) or None if the element is not in the viewport.
        Used as a fallback for CDP-direct click when Playwright click fails.
        """
        try:
            raw = await element.evaluate("""() => {
                const r = this.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return null;
                return JSON.stringify({x: r.left + r.width/2, y: r.top + r.height/2});
            }""")
            if raw is None:
                return None
            import json as _json
            coords = _json.loads(raw) if isinstance(raw, str) else raw
            return (coords["x"], coords["y"])
        except Exception:
            return None

    async def _cdp_click_at(self, x: float, y: float) -> None:
        """Fire a full mousemove → mousedown → mouseup CDP sequence at (x, y)."""
        await self._dispatch_mouse_event("mouseMoved", x, y)
        await asyncio.sleep(0.04)
        await self._dispatch_mouse_event("mousePressed", x, y, "left", 1)
        await asyncio.sleep(0.06)
        await self._dispatch_mouse_event("mouseReleased", x, y, "left", 1)

    async def _click_with_fallback(self, element, index: int) -> tuple[bool, str]:
        """Manus-style 3-strategy click chain.

        Strategy 1 — Playwright element.click() (standard, handles scroll-into-view)
        Strategy 2 — JS synthetic click + React-safe mouse events dispatched via evaluate()
        Strategy 3 — raw CDP Input.dispatchMouseEvent at element's bounding-box center

        Returns (success, strategy_used_or_error_message).
        """
        # ── Strategy 1: JS synthetic click with React-safe events ─────────────
        # PRIMARY since the browser_use actor click (Element.click(), CDP mouse
        # events) was observed to silently no-op on some targets — it returned
        # success while the page's onclick handler never fired. Direct JS event
        # dispatch always reaches the right document: the same proven mechanism
        # the select_* tools use.
        try:
            result = await element.evaluate("""() => {
                try {
                    // Scroll into view first
                    this.scrollIntoView({block: 'center', inline: 'nearest'});
                    // Dispatch React-compatible mouse events
                    const opts = {bubbles: true, cancelable: true, view: window};
                    this.dispatchEvent(new MouseEvent('mouseover', opts));
                    this.dispatchEvent(new MouseEvent('mouseenter', opts));
                    this.dispatchEvent(new MouseEvent('mousedown', opts));
                    this.dispatchEvent(new MouseEvent('mouseup',   opts));
                    // Native HTMLElement.click() fires onclick AND performs
                    // default actions (form submit, anchor navigation).
                    if (typeof this.click === 'function') this.click();
                    else this.dispatchEvent(new MouseEvent('click', opts));
                    // Also trigger focus for inputs/buttons
                    if (typeof this.focus === 'function') this.focus();
                    return 'ok';
                } catch(e) { return 'err:' + e.message; }
            }""")
            if result == "ok":
                await asyncio.sleep(0.15)
                return True, "js-synthetic"
            logger.info("CLICK[%d] S1-js-synthetic returned '%s' → trying S2-actor-click", index, result)
        except Exception as e1:
            logger.info("CLICK[%d] S1-js-synthetic failed → trying S2-actor-click (%s)", index, type(e1).__name__)

        # ── Strategy 2: browser_use actor click (CDP mouse events) ────────────
        try:
            # NOTE: browser_use's Element.click() signature is
            # click(button, click_count, modifiers) — it takes NO timeout kwarg.
            # Passing timeout= raised TypeError instantly, so this strategy
            # always "failed" before it even attempted the click.
            await element.click()
            return True, "actor-click"
        except Exception as e2:
            logger.info("CLICK[%d] S2-actor-click failed → trying S3-cdp-coords (%s)", index, type(e2).__name__)

        # ── Strategy 3: raw CDP at element center coordinates ─────────────────
        try:
            coords = await self._get_element_center(element)
            if coords:
                cx, cy = coords
                await self._cdp_click_at(cx, cy)
                await asyncio.sleep(0.15)
                return True, f"cdp-coords({cx:.0f},{cy:.0f})"
        except Exception as e3:
            logger.info("CLICK[%d] S3-cdp-coords failed (%s)", index, type(e3).__name__)

        logger.warning("CLICK[%d] ALL 3 strategies failed — element may be hidden/off-screen", index)
        return False, "all 3 click strategies failed (js-synthetic, actor-click, cdp-coords)"

    async def _wait_for_dom_settle(self, timeout: float = 0.6) -> None:
        """Short wait for React/Vue state updates and lazy-loaded DOM changes to settle.

        Mimics Manus.im behaviour of waiting after interactions before continuing.
        Uses a MutationObserver race: resolves as soon as DOM stops mutating for
        150 ms, or after `timeout` seconds whichever comes first.
        """
        try:
            page = await self._get_current_page()
            # Timeout-guarded: a dead CDP session makes the raw evaluate hang forever
            # (Chrome silently drops messages addressed to unknown sessions).
            try:
                await self._call_with_deadline(
                    page.evaluate(f"""() => new Promise(resolve => {{
                let timer = null;
                const reset = () => {{ clearTimeout(timer); timer = setTimeout(resolve, 150); }};
                const obs = new MutationObserver(reset);
                obs.observe(document.body, {{childList:true, subtree:true, attributes:true}});
                reset();  // start immediately
                setTimeout(() => {{ obs.disconnect(); resolve(); }}, {int(timeout*1000)});
            }})"""),
                    timeout=timeout + 5.0,
                )
            except asyncio.TimeoutError:
                logger.debug("_wait_for_dom_settle timed out (session may be reconnecting)")
        except Exception:
            await asyncio.sleep(0.3)

    async def _wait_for_network_idle(self, timeout: float = 2.0) -> None:
        """Manus.im 'Network Idle Detection' — polls until no new resources for 300 ms.

        Uses the browser's Resource Timing API to detect in-flight fetch/XHR requests.
        Resolves when `performance.getEntriesByType('resource').length` stops growing
        for a full 300 ms interval, or when `timeout` seconds elapses.
        """
        try:
            page = await self._get_current_page()
            try:
                await self._call_with_deadline(
                    page.evaluate(f"""() => new Promise(resolve => {{
                const deadline = Date.now() + {int(timeout * 1000)};
                let lastCount = performance.getEntriesByType('resource').length;
                const check = () => {{
                    const count = performance.getEntriesByType('resource').length;
                    if (count === lastCount || Date.now() >= deadline) {{
                        resolve(); return;
                    }}
                    lastCount = count;
                    setTimeout(check, 300);
                }};
                setTimeout(check, 300);
            }})"""),
                    timeout=timeout + 5.0,
                )
            except asyncio.TimeoutError:
                logger.debug("_wait_for_network_idle timed out (session may be reconnecting)")
        except Exception:
            await asyncio.sleep(0.5)

    async def wait_for_network_idle(self, timeout: float = 5.0) -> ToolResult:
        """Public wrapper around _wait_for_network_idle for use as a browser tool."""
        try:
            await self._wait_for_network_idle(timeout=timeout)
            return ToolResult(success=True, message=f"Network idle confirmed (waited up to {timeout}s)")
        except Exception as exc:
            return ToolResult(success=False, message=f"wait_for_network_idle failed: {exc}")

    async def _wait_for_page_ready(self, timeout: float = 10.0) -> None:
        """Poll document.readyState until 'complete' on the current tab.

        Survives mid-navigation execution-context swaps (each failed evaluate is
        simply retried). Fixes the "Empty DOM tree" race where browser_view()
        right after browser_back()/browser_forward() serialised the DOM while
        the navigation was still in flight.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                page = await self._get_current_page()
                state = await self._call_with_deadline(
                    page.evaluate("() => document.readyState"), timeout=3.0,
                )
                if state and "complete" in str(state):
                    return
            except Exception:
                pass  # context destroyed mid-navigation — keep polling
            await asyncio.sleep(0.15)

    # ------------------------------------------------------------------
    # Console capture (browser_console_view support)
    # ------------------------------------------------------------------

    # Plain script source for Page.addScriptToEvaluateOnNewDocument — runs
    # BEFORE page scripts on every future navigation of the tab, so console
    # output is captured from the very first line after a page load.
    _CONSOLE_CAPTURE_NEW_DOC_SOURCE = """
(function () {
    if (window.__consoleLogs) { return; }
    try {
        window.__consoleLogs = [];
        var __fmt = function (args) {
            var out = [];
            for (var i = 0; i < args.length; i++) {
                var a = args[i];
                try {
                    if (typeof a === 'string') { out.push(a); }
                    else if (a instanceof Error) { out.push(a.message); }
                    else { out.push(JSON.stringify(a)); }
                } catch (e) { out.push(String(a)); }
            }
            return out.join(' ');
        };
        ['log', 'info', 'warn', 'error', 'debug'].forEach(function (level) {
            var orig = console[level] ? console[level].bind(console) : null;
            console[level] = function () {
                try {
                    window.__consoleLogs.push('[' + level.toUpperCase() + '] ' + __fmt(arguments));
                    if (window.__consoleLogs.length > 1000) { window.__consoleLogs.shift(); }
                } catch (e) {}
                if (orig) { orig.apply(null, arguments); }
            };
        });
        window.addEventListener('error', function (e) {
            try {
                window.__consoleLogs.push('[ERROR] ' + e.message + ' @ ' + (e.filename || '') + ':' + (e.lineno || 0));
                if (window.__consoleLogs.length > 1000) { window.__consoleLogs.shift(); }
            } catch (err) {}
        });
    } catch (e) {}
})();
"""

    # Arrow-function installer for the CURRENT document (idempotent).
    _CONSOLE_CAPTURE_INSTALL_JS = """() => {
    if (window.__consoleLogs) { return 'already-installed'; }
    try {
        window.__consoleLogs = [];
        const __fmt = (args) => Array.from(args).map(a => {
            try {
                if (typeof a === 'string') { return a; }
                if (a instanceof Error) { return a.message; }
                return JSON.stringify(a);
            } catch (e) { return String(a); }
        }).join(' ');
        ['log', 'info', 'warn', 'error', 'debug'].forEach(level => {
            const orig = console[level] ? console[level].bind(console) : null;
            console[level] = function () {
                try {
                    window.__consoleLogs.push('[' + level.toUpperCase() + '] ' + __fmt(arguments));
                    if (window.__consoleLogs.length > 1000) { window.__consoleLogs.shift(); }
                } catch (e) {}
                if (orig) { orig.apply(null, arguments); }
            };
        });
        window.addEventListener('error', e => {
            try {
                window.__consoleLogs.push('[ERROR] ' + e.message + ' @ ' + (e.filename || '') + ':' + (e.lineno || 0));
                if (window.__consoleLogs.length > 1000) { window.__consoleLogs.shift(); }
            } catch (err) {}
        });
        return 'installed';
    } catch (e) { return 'err:' + e.message; }
}"""

    async def _ensure_console_capture(self) -> None:
        """Install the console-capture shim into the current tab.

        Two layers:
        1. Page.addScriptToEvaluateOnNewDocument — captures console output on
           every FUTURE navigation of this tab (registered once per target).
        2. page.evaluate installer — captures output in the CURRENT document.

        Idempotent: the shim itself no-ops when already installed.
        """
        try:
            page = await self._get_current_page()
            session_id = await page._ensure_session()
            target_id = getattr(page, "_target_id", None)
            if target_id and target_id not in self._console_capture_targets:
                try:
                    await self._call_with_deadline(
                        page._client.send.Page.addScriptToEvaluateOnNewDocument(
                            params={"source": self._CONSOLE_CAPTURE_NEW_DOC_SOURCE},
                            session_id=session_id,
                        ),
                        timeout=5.0,
                    )
                    self._console_capture_targets.add(target_id)
                except Exception as exc:
                    logger.debug("addScriptToEvaluateOnNewDocument failed: %s", exc)
            try:
                await self._call_with_deadline(
                    page.evaluate(self._CONSOLE_CAPTURE_INSTALL_JS), timeout=5.0
                )
            except Exception as exc:
                logger.debug("Console capture install evaluate failed: %s", exc)
        except Exception as exc:
            logger.debug("_ensure_console_capture failed: %s", exc)

    async def wait_for_element(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        timeout: float = 10.0,
    ) -> ToolResult:
        """Wait until a DOM element matching a CSS selector or containing specific text
        becomes visible on the page.  Returns the first matching element's tag + text
        so the agent knows what appeared.

        Manus.im 'Element-Based Waiting' — ensures the agent doesn't act on stale DOM.
        Use after: navigating, clicking a button that opens a modal, submitting a form,
        or any action where you expect new content to appear before proceeding.

        Args:
            selector: CSS selector to wait for (e.g. '.modal', '#success-msg', '[role="dialog"]').
            text:     Visible text to wait for (e.g. "Welcome", "Order confirmed").
            timeout:  Maximum wait time in seconds (default 10).
        """
        try:
            page = await self._get_current_page()
            import json as _json
            raw = await page.evaluate(f"""(args) => new Promise(resolve => {{
                const [selector, text, timeout] = args;
                const deadline = Date.now() + timeout * 1000;
                const check = () => {{
                    // CSS selector match
                    if (selector) {{
                        try {{
                            const el = document.querySelector(selector);
                            if (el) {{
                                const r = el.getBoundingClientRect();
                                const s = window.getComputedStyle(el);
                                const visible = r.width > 0 && r.height > 0
                                    && s.display !== 'none' && s.visibility !== 'hidden';
                                if (visible) {{
                                    resolve(JSON.stringify({{found:true, method:'selector',
                                        tag:el.tagName.toLowerCase(),
                                        text:(el.innerText||el.textContent||'').trim().substring(0,80)
                                    }}));
                                    return;
                                }}
                            }}
                        }} catch(e) {{}}
                    }}
                    // Text content match (visible text nodes only)
                    if (text) {{
                        const lower = text.toLowerCase();
                        const walker = document.createTreeWalker(
                            document.body, NodeFilter.SHOW_TEXT, null, false
                        );
                        let node;
                        while (node = walker.nextNode()) {{
                            const t = (node.textContent || '').trim();
                            if (!t) continue;
                            const parent = node.parentElement;
                            if (!parent) continue;
                            const s = window.getComputedStyle(parent);
                            if (s.display === 'none' || s.visibility === 'hidden') continue;
                            if (t.toLowerCase().includes(lower)) {{
                                resolve(JSON.stringify({{found:true, method:'text',
                                    tag:parent.tagName.toLowerCase(),
                                    text:t.substring(0,80)
                                }}));
                                return;
                            }}
                        }}
                    }}
                    if (Date.now() >= deadline) {{
                        resolve(JSON.stringify({{found:false}}));
                        return;
                    }}
                    setTimeout(check, 200);
                }};
                check();
            }})""", [selector, text, timeout])
            res = _json.loads(raw) if isinstance(raw, str) else raw
            if res.get("found"):
                tag = res.get("tag", "element")
                found_text = res.get("text", "")
                method = res.get("method", "")
                return ToolResult(
                    success=True,
                    message=f"Element found [{method}]: <{tag}>{found_text[:60]}</{tag}>",
                    data=res,
                )
            target = selector or f'text="{text}"'
            return ToolResult(
                success=False,
                message=f"Element '{target}' did not appear within {timeout}s. Page may still be loading — try browser_view() to inspect current state.",
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"wait_for_element failed: {exc}")

    async def upload_file(self, index: int, file_path: str) -> ToolResult:
        """Upload a file to an <input type='file'> element via CDP setFileInputFiles.

        Manus.im 'Integrated File Upload' — attaches a local sandbox file to any
        file upload form field without opening a system file picker.

        Args:
            index:     DOM index of the <input type='file'> element.
            file_path: Absolute path to the file inside the sandbox, under the
                home directory described in your sandbox environment
                (e.g. /home/user/photo.jpg on an E2B sandbox,
                /home/runner/photo.jpg on a shared Replit sandbox).
        """
        import os
        import json as _json
        try:
            if not os.path.isfile(file_path):
                # NOTE: '~' is expanded by the SANDBOX's own shell, so the hint
                # stays correct for every provider (E2B /home/user vs shared
                # Replit /home/runner/...) — never hard-code a host path here.
                return ToolResult(
                    success=False,
                    message=(
                        f"File not found: {file_path}. List your home directory "
                        "with shell_exec('ls ~') to find the correct absolute "
                        "path, then retry."
                    ),
                )
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")

            await self._ensure_dom_document()
            page = await self._get_current_page()
            element = await page.get_element(node.backend_node_id)

            # Verify it is an <input type="file">
            tag_check = await element.evaluate(
                "() => JSON.stringify({tag:this.tagName, type:(this.type||'').toLowerCase()})"
            )
            info = _json.loads(tag_check) if isinstance(tag_check, str) else tag_check
            if info.get("tag", "").upper() != "INPUT" or info.get("type") != "file":
                return ToolResult(
                    success=False,
                    message=(
                        f"Element {index} is <{info.get('tag','?')} type='{info.get('type','?')}'>, "
                        f"not an <input type='file'>."
                    ),
                )

            # Use CDP DOM.setFileInputFiles directly — cdp_use's Element has no
            # Playwright-style set_input_files(); the raw CDP command is the
            # reliable way to attach a local file to the input (works on every
            # cdp_use version, unlike element.set_input_files which raised
            # "'Element' object has no attribute 'set_input_files'").
            cdp_sess = await self._get_cdp_session()
            await cdp_sess.cdp_client.send.DOM.setFileInputFiles(
                params={"files": [file_path], "backendNodeId": node.backend_node_id},
                session_id=str(cdp_sess.session_id),
            )
            await self._wait_for_dom_settle()
            file_name = os.path.basename(file_path)
            return ToolResult(
                success=True,
                message=f"File '{file_name}' uploaded to element {index}.",
                data={"file_path": file_path, "file_name": file_name},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"upload_file failed: {exc}")

    # ------------------------------------------------------------------
    # Browser Protocol implementation
    # ------------------------------------------------------------------

    # Maximum interactive elements returned per browser_view / navigate call.
    # Keeps LLM context payload manageable for complex pages (e.g. Facebook).
    _MAX_INTERACTIVE_ELEMENTS = 300

    async def _observe_page_state(self, session, include_content: bool) -> dict:
        """Serialise the page exactly the way the LLM "sees" it after an action.

        This is the post-action awareness payload: current URL, page title and
        the fresh interactive elements (indices may have shifted after a click
        or navigation). When ``include_content`` is True the DOM text
        representation is included too — used when the action changed the page
        (navigation / submit), so the agent reads what a human would read.
        Retries once on an empty snapshot (navigation race), same as view_page.
        """
        state = await session.get_browser_state_summary(include_screenshot=False)
        if include_content:
            repr_ = (state.dom_state.llm_representation() if state.dom_state is not None else "") or ""
            if not repr_.strip():
                await self._wait_for_page_ready(timeout=8.0)
                await self._wait_for_dom_settle(timeout=1.0)
                state = await session.get_browser_state_summary(include_screenshot=False)
        selector_map = (state.dom_state.selector_map if state.dom_state is not None else None) or {}
        elements = self._format_selector_map(selector_map)
        if len(elements) > self._MAX_INTERACTIVE_ELEMENTS:
            elements = elements[: self._MAX_INTERACTIVE_ELEMENTS]
            elements.append(
                f"... (truncated, showing first {self._MAX_INTERACTIVE_ELEMENTS} of {len(selector_map)} elements)"
            )
        content = ""
        if include_content and state.dom_state is not None:
            content = state.dom_state.llm_representation() or ""
        return {
            "url": state.url or "",
            "title": state.title or "",
            "interactive_elements": elements,
            "content": content,
        }

    async def view_page(self) -> ToolResult:
        """Return the current page content and interactive elements."""
        try:
            session = await self._ensure_session()
            state = await session.get_browser_state_summary(include_screenshot=False)

            content = ""
            interactive_elements: List[str] = []
            if state.dom_state is not None:
                content = state.dom_state.llm_representation()
                selector_map = state.dom_state.selector_map or {}
                interactive_elements = self._format_selector_map(selector_map)

            # Retry once when the DOM serialisation came back empty — this
            # happens when the snapshot races an in-flight navigation (e.g.
            # right after browser_back/forward). Wait for the page to settle,
            # then re-serialise instead of reporting "Empty DOM tree".
            if (not content or not content.strip()) and not interactive_elements:
                logger.info("view_page: empty DOM snapshot — waiting for page ready and retrying once")
                await self._wait_for_page_ready(timeout=8.0)
                await self._wait_for_dom_settle(timeout=1.0)
                state = await session.get_browser_state_summary(include_screenshot=False)
                if state.dom_state is not None:
                    content = state.dom_state.llm_representation()
                    selector_map = state.dom_state.selector_map or {}
                    interactive_elements = self._format_selector_map(selector_map)

            if len(interactive_elements) > self._MAX_INTERACTIVE_ELEMENTS:
                interactive_elements = interactive_elements[:self._MAX_INTERACTIVE_ELEMENTS]
                interactive_elements.append(
                    f"... (truncated, showing first {self._MAX_INTERACTIVE_ELEMENTS} of {len(selector_map)} elements — use coordinates or scroll to reach others)"
                )

            # Element-diff baseline: browser_view is the agent's canonical
            # observation, so the next click compares against THIS state
            # (set AFTER the empty-snapshot retry so the baseline is final).
            self._last_elements_signature = tuple(interactive_elements)

            # Build tab summary so the agent always knows which tabs are open
            # and can use browser_switch_tab instead of browser_navigate
            tabs_info = []
            try:
                pages = await session.get_pages()
                current_page = await session.get_current_page()
                current_target_id = current_page._target_id if current_page else None
                for i, page in enumerate(pages):
                    try:
                        url = await page.get_url()
                    except Exception:
                        url = "unknown"
                    tabs_info.append({
                        "tab": i + 1,
                        "url": url,
                        "active": page._target_id == current_target_id,
                    })
            except Exception:
                pass

            return ToolResult(
                success=True,
                data={
                    "open_tabs": tabs_info,
                    "interactive_elements": interactive_elements,
                    "content": content,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to view page: {exc}")

    async def navigate(self, url: str) -> ToolResult:
        """Navigate to the given URL."""
        try:
            logger.info("NAVIGATE → %s", url)
            session = await self._ensure_session()
            # Register the console-capture init script on this tab BEFORE
            # navigating so browser_console_view() has data from page load.
            await self._ensure_console_capture()
            await session.navigate_to(url)
            await self._wait_for_page_ready()
            # Return the full observed state (url/title/elements/content) so the
            # agent immediately reads the page it landed on — no extra
            # browser_view round-trip, no acting blind on an unfamiliar site.
            observed = await self._observe_page_state(session, include_content=True)
            # New page → reset the element-diff baseline to THIS state so the
            # next click's change-detection compares against the right page.
            self._last_elements_signature = tuple(
                observed.get("interactive_elements") or []
            )
            return ToolResult(success=True, data=observed)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to navigate to {url}: {exc}")

    async def restart(self, url: str) -> ToolResult:
        """Restart the browser session and navigate to the given URL."""
        await self.cleanup()
        return await self.navigate(url)

    async def click(
        self,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None,
    ) -> ToolResult:
        """Click an element by DOM index or by screen coordinates.

        For index-based clicks uses Manus-style 3-strategy fallback chain:
          1. Playwright element.click()  — standard, handles scroll-into-view
          2. JS synthetic click          — React/Vue-safe mouse events via evaluate()
          3. Raw CDP coordinates         — dispatchMouseEvent at bounding-box center

        For coordinate clicks uses raw CDP directly (same as before).
        DOM-settle wait is applied after every successful click so React state
        and lazy-loaded DOM changes are stable before the next action.
        """
        try:
            if coordinate_x is not None and coordinate_y is not None:
                await self._cdp_click_at(coordinate_x, coordinate_y)
                await self._wait_for_dom_settle()
                return ToolResult(success=True)

            elif index is not None:
                session = await self._ensure_session()
                node = await session.get_dom_element_by_index(index)
                if node is None:
                    return ToolResult(
                        success=False,
                        message=f"Cannot find interactive element with index {index}",
                    )
                # Ensure the page session has requested the DOM document —
                # otherwise element.evaluate() fails with CDP -32000
                # "Document needs to be requested first".
                await self._ensure_dom_document()
                page = await self._get_current_page()
                element = await page.get_element(node.backend_node_id)

                # Smart redirect: if clicking a native <select>, block the click and
                # return options so the AI uses browser_select_by_text directly.
                # This avoids the open-dropdown → view → click-option loop entirely.
                try:
                    import json as _json_click
                    probe_js = (
                        "() => {"
                        "  if (this.tagName !== 'SELECT') return null;"
                        "  return JSON.stringify(Array.from(this.options).map((o,i)=>({i,t:o.text.trim()})));"
                        "}"
                    )
                    probe_raw = await element.evaluate(probe_js)
                    if probe_raw is not None:
                        opts = _json_click.loads(probe_raw) if isinstance(probe_raw, str) else probe_raw
                        preview = ", ".join(f"{o['i']}:{o['t']}" for o in opts[:8])
                        more = f" … +{len(opts)-8} more" if len(opts) > 8 else ""
                        return ToolResult(
                            success=False,
                            message=(
                                f"Element {index} is a native <select> — do NOT click it. "
                                f"Use browser_select_by_text({index}, 'your value') to select directly. "
                                f"Available options: [{preview}{more}]"
                            ),
                        )
                except Exception:
                    pass  # Not a select or probe failed — fall through to click chain

                # ── Manus-style 3-strategy fallback chain ────────────────────
                try:
                    pre_url = await page.get_url()
                except Exception:
                    pre_url = ""
                ok, strategy = await self._click_with_fallback(element, index)
                if ok:
                    logger.info("CLICK[%d] ✓ via [%s]", index, strategy)
                    await self._wait_for_dom_settle()
                    # Post-action awareness: show the agent what the click led
                    # to (URL/title/fresh elements; full text when it navigated).
                    try:
                        session2 = await self._ensure_session()
                        now_url = ""
                        try:
                            now_url = await (await self._get_current_page()).get_url()
                        except Exception:
                            pass
                        navigated = bool(now_url) and now_url != pre_url
                        observed = await self._observe_page_state(
                            session2, include_content=navigated
                        )
                        # Element-diff awareness: menus/modals change the
                        # element list WITHOUT changing the URL. Telling the
                        # model "no visible change" stops blind re-clicks on
                        # toggle widgets (observed live: 10 identical clicks
                        # on a dropdown trigger that toggled itself shut).
                        els = observed.get("interactive_elements") or []
                        els_sig = tuple(els)
                        elements_changed = (
                            self._last_elements_signature is not None
                            and els_sig != self._last_elements_signature
                        )
                        self._last_elements_signature = els_sig
                        observed["page_changed"] = navigated or elements_changed
                        if not navigated and not elements_changed:
                            observed["note"] = (
                                "No visible change after this click. The element "
                                "may have toggled something back shut, or it "
                                "needs a different interaction. Do NOT repeat "
                                "the same click — re-observe or change strategy "
                                "(e.g. browser_smart_select for dropdowns)."
                            )
                        return ToolResult(
                            success=True,
                            message=f"Clicked element {index} via [{strategy}]",
                            data=observed,
                        )
                    except Exception as obs_exc:
                        logger.debug("post-click observe failed: %s", obs_exc)
                        return ToolResult(
                            success=True,
                            message=f"Clicked element {index} via [{strategy}]",
                        )
                logger.warning("CLICK[%d] ✗ all strategies exhausted", index)
                return ToolResult(success=False, message=f"Click failed for element {index}: {strategy}")

            return ToolResult(success=True)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to click element: {exc}")

    async def input(
        self,
        text: str,
        press_enter: bool,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None,
    ) -> ToolResult:
        """Type text into an element identified by DOM index or screen coordinates.

        After filling, dispatches React-safe input+change events so the framework's
        state management detects the change — same pattern used by Manus.im.
        DOM-settle wait is applied so lazy-loaded suggestions/validation can render.
        """
        try:
            page = await self._get_current_page()
            try:
                pre_url = await page.get_url()
            except Exception:
                pre_url = ""

            if coordinate_x is not None and coordinate_y is not None:
                # CDP click-to-focus then insertText
                await self._cdp_click_at(coordinate_x, coordinate_y)
                await asyncio.sleep(0.05)
                cdp_sess = await self._get_cdp_session()
                await cdp_sess.cdp_client.send.Input.insertText(
                    params={"text": text},
                    session_id=str(cdp_sess.session_id),
                )
            elif index is not None:
                session = await self._ensure_session()
                node = await session.get_dom_element_by_index(index)
                if node is None:
                    return ToolResult(
                        success=False,
                        message=f"Cannot find interactive element with index {index}",
                    )
                element = await page.get_element(node.backend_node_id)
                # Mirroring verify_value/upload_file: Element.evaluate() raises
                # 'Document needs to be requested first' unless the DOM document
                # was requested on this session — ensure it before the JS fill.
                await self._ensure_dom_document()
                # JS-first fill with VERIFICATION: the browser_use actor
                # Element.fill() was observed to silently no-op on some targets
                # (returned success but the value stayed empty). Setting the
                # value via the prototype setter is React-safe by construction
                # and lets us VERIFY the result instead of trusting a no-op.
                set_value_js = """(text) => {
                    const proto = this.tagName === 'TEXTAREA'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    setter.call(this, text);
                    this.dispatchEvent(new Event('input',  {bubbles:true}));
                    this.dispatchEvent(new Event('change', {bubbles:true}));
                    return this.value;
                }"""
                actual = await element.evaluate(set_value_js, text)
                if actual != text:
                    # Fallback 1: actor fill (legacy path)
                    try:
                        await element.fill(text)
                        actual = await element.evaluate("() => this.value")
                    except Exception:
                        pass
                if actual != text:
                    # Fallback 2: CDP click-to-focus + insertText
                    try:
                        coords = await self._get_element_center(element)
                        if coords:
                            await self._cdp_click_at(coords[0], coords[1])
                            await asyncio.sleep(0.05)
                            cdp_sess = await self._get_cdp_session()
                            await cdp_sess.cdp_client.send.Input.insertText(
                                params={"text": text},
                                session_id=str(cdp_sess.session_id),
                            )
                            actual = await element.evaluate("() => this.value")
                    except Exception:
                        pass
                if actual != text:
                    return ToolResult(
                        success=False,
                        message=(
                            f"Input failed: element value is {actual!r}, "
                            f"expected {text!r}. Try browser_verify_value or "
                            "click the element first."
                        ),
                        data={"expected": text, "actual": actual},
                    )
                logger.info("INPUT[%d] ✓ text=%r%s", index, text[:40], "…" if len(text) > 40 else "")

            if press_enter:
                await page.press("Enter")
                logger.info("INPUT press_enter=True")

            await self._wait_for_dom_settle()
            # press_enter usually submits a form / triggers a search — show the
            # agent the resulting page state (full text when it navigated).
            if press_enter and index is not None:
                try:
                    session2 = await self._ensure_session()
                    now_url = ""
                    try:
                        now_url = await (await self._get_current_page()).get_url()
                    except Exception:
                        pass
                    navigated = bool(now_url) and now_url != pre_url
                    observed = await self._observe_page_state(
                        session2, include_content=navigated
                    )
                    observed["page_changed"] = navigated
                    return ToolResult(success=True, data=observed)
                except Exception as obs_exc:
                    logger.debug("post-input observe failed: %s", obs_exc)
            return ToolResult(success=True)
        except Exception as exc:
            logger.warning("INPUT[%s] ✗ %s", index, exc)
            return ToolResult(success=False, message=f"Failed to input text: {exc}")

    async def move_mouse(
        self,
        coordinate_x: float,
        coordinate_y: float,
    ) -> ToolResult:
        """Move the mouse cursor to the given coordinates."""
        try:
            await self._dispatch_mouse_event("mouseMoved", coordinate_x, coordinate_y)
            return ToolResult(success=True)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to move mouse: {exc}")

    async def list_tabs(self) -> ToolResult:
        """Return a list of all currently open browser tabs with their index and URL."""
        try:
            session = await self._ensure_session()
            pages = await session.get_pages()
            tabs = []
            for i, page in enumerate(pages):
                try:
                    url = await page.get_url()
                except Exception:
                    url = "unknown"
                tabs.append({"tab": i + 1, "url": url})
            return ToolResult(
                success=True,
                message=f"{len(tabs)} tab(s) open.",
                data={"tabs": tabs, "total_tabs": len(tabs)},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to list tabs: {exc}")

    async def open_tab(self, url: str) -> ToolResult:
        """Open a URL in a new browser tab using native browser_use API."""
        try:
            session = await self._ensure_session()
            await session.navigate_to(url, new_tab=True)
            await asyncio.sleep(0.5)
            pages = await session.get_pages()
            return ToolResult(
                success=True,
                message=f"Opened new tab with {url}. Total tabs: {len(pages)}.",
                data={"url": url, "tab": len(pages), "total_tabs": len(pages)},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to open new tab: {exc}")

    async def switch_tab(self, tab_index: int) -> ToolResult:
        """Switch the active browser tab by 1-based index."""
        try:
            from browser_use.browser.events import SwitchTabEvent
            session = await self._ensure_session()
            pages = await session.get_pages()
            if not pages:
                return ToolResult(success=False, message="No tabs are open")
            if tab_index < 1 or tab_index > len(pages):
                return ToolResult(
                    success=False,
                    message=f"Tab {tab_index} does not exist. {len(pages)} tab(s) are currently open.",
                )
            target = pages[tab_index - 1]
            target_id = target._target_id
            await session.on_SwitchTabEvent(SwitchTabEvent(target_id=target_id))
            await asyncio.sleep(0.3)
            # Different tab → the element-diff baseline from the old tab is
            # stale; clear it so the next click's change detection starts
            # fresh (no false "no visible change" notes across tabs).
            self._cached_page = None  # force re-resolve against the new focus
            self._last_elements_signature = None
            try:
                url = await target.get_url()
            except Exception:
                url = "unknown"
            return ToolResult(
                success=True,
                message=f"Switched to tab {tab_index}: {url}",
                data={"tab": tab_index, "url": url, "total_tabs": len(pages)},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to switch tab: {exc}")

    async def press_key(self, key: str) -> ToolResult:
        """Simulate a key press.

        Tab-related browser shortcuts are intercepted and handled via native
        browser_use session API because page.press() cannot dispatch browser-chrome
        shortcuts (Control+t, Control+1..9, Control+Tab).
        """
        try:
            import re
            key_norm = key.lower().replace(" ", "")

            # Control+t → open a blank new tab
            if key_norm in ("control+t", "ctrl+t"):
                session = await self._ensure_session()
                await session.navigate_to("about:blank", new_tab=True)
                await asyncio.sleep(0.3)
                pages = await session.get_pages()
                return ToolResult(
                    success=True,
                    message=f"Opened new blank tab (tab {len(pages)}). Total tabs: {len(pages)}.",
                    data={"tab": len(pages), "total_tabs": len(pages)},
                )

            # Control+1 … Control+9 → switch to tab N
            tab_match = re.match(r"^(?:control|ctrl)\+([1-9])$", key_norm)
            if tab_match:
                return await self.switch_tab(int(tab_match.group(1)))

            # Control+Tab → next tab
            if key_norm in ("control+tab", "ctrl+tab"):
                session = await self._ensure_session()
                pages = await session.get_pages()
                current = await session.get_current_page()
                if pages and current:
                    idx = next((i for i, p in enumerate(pages) if p.target_id == current.target_id), 0)
                    return await self.switch_tab((idx + 1) % len(pages) + 1)

            # Control+Shift+Tab → previous tab
            if key_norm in ("control+shift+tab", "ctrl+shift+tab"):
                session = await self._ensure_session()
                pages = await session.get_pages()
                current = await session.get_current_page()
                if pages and current:
                    idx = next((i for i, p in enumerate(pages) if p.target_id == current.target_id), 0)
                    return await self.switch_tab((idx - 1) % len(pages) + 1)

            # Default: dispatch to page
            page = await self._get_current_page()
            await page.press(key)
            return ToolResult(success=True)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to press key: {exc}")

    async def select_option(self, index: int, option: int) -> ToolResult:
        """Select an option in a <select> element by DOM index and option index (0-based).
        
        Correctly targets the specific <select> element identified by `index` —
        critical when multiple selects exist on the same page (e.g. Day/Month/Year).
        """
        try:
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(
                    success=False,
                    message=f"Cannot find selector element with index {index}",
                )
            await self._ensure_dom_document()
            page = await self._get_current_page()

            # Resolve to the exact Element handle for this specific backend_node_id.
            # This is critical — page.get_element() guarantees we act on the right <select>
            # rather than scanning document.querySelectorAll('select')[0] (which caused
            # Day/Month/Year selects to all modify the same first select element).
            element = await page.get_element(node.backend_node_id)

            # Use element.evaluate() where `this` is bound to the exact element.
            # We use the native HTMLSelectElement setter so React/Vue synthetic event
            # systems detect the change, then fire both 'input' and 'change' events.
            js_code = (
                "(optionIndex) => {"
                "  if (optionIndex < 0 || optionIndex >= this.options.length) {"
                "    return JSON.stringify({success:false, error:'index '+optionIndex+' out of range ('+this.options.length+' options)'});"
                "  }"
                "  const opt = this.options[optionIndex];"
                "  const text = opt.text;"
                "  const value = opt.value;"
                "  try {"
                "    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;"
                "    setter.call(this, value);"
                "  } catch(e) {"
                "    this.selectedIndex = optionIndex;"
                "  }"
                "  this.dispatchEvent(new Event('input',  {bubbles:true}));"
                "  this.dispatchEvent(new Event('change', {bubbles:true}));"
                "  return JSON.stringify({success:true, text:text, value:value});"
                "}"
            )

            import json as _json
            selected_text = ""
            try:
                raw = await element.evaluate(js_code, option)
                result = _json.loads(raw) if isinstance(raw, str) else raw
                if result and result.get("success"):
                    selected_text = result.get("text", "")
                else:
                    err = result.get("error", str(result)) if result else "unknown"
                    return ToolResult(success=False, message=f"select_option JS failed: {err}")
            except Exception as js_exc:
                # Fallback: select by value string via element.select_option(values=[...])
                try:
                    # Get option value by iterating children via CDP
                    await element.select_option(values=[str(option)])
                    selected_text = str(option)
                except Exception as fallback_exc:
                    return ToolResult(
                        success=False,
                        message=f"select_option failed (JS: {js_exc}, fallback: {fallback_exc})",
                    )

            msg = f"Selected option {option}" + (f" ('{selected_text}')" if selected_text else "")
            await self._wait_for_dom_settle()
            return ToolResult(success=True, message=msg)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to select option: {exc}")

    async def go_back(self) -> ToolResult:
        """Navigate back in the browser history."""
        try:
            page = await self._get_current_page()
            await page.go_back()
            # Wait for the new document to actually load before returning —
            # Page.navigateToHistoryEntry returns immediately, and an immediate
            # browser_view() used to race the navigation and see an empty DOM.
            await self._wait_for_page_ready()
            await self._wait_for_dom_settle()
            # Refresh the DOM snapshot so the next view/interaction sees the
            # restored page instead of stale state.
            try:
                session = await self._ensure_session()
                await session.get_browser_state_summary(include_screenshot=False)
            except Exception:
                pass
            logger.info("NAVIGATE ← back")
            return ToolResult(success=True, message="Navigated back")
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to go back: {exc}")

    async def go_forward(self) -> ToolResult:
        """Navigate forward in the browser history."""
        try:
            page = await self._get_current_page()
            await page.go_forward()
            # Same ready-wait as go_back — fixes the "Empty DOM tree" race.
            await self._wait_for_page_ready()
            await self._wait_for_dom_settle()
            try:
                session = await self._ensure_session()
                await session.get_browser_state_summary(include_screenshot=False)
            except Exception:
                pass
            logger.info("NAVIGATE → forward")
            return ToolResult(success=True, message="Navigated forward")
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to go forward: {exc}")

    async def scroll_up(self, to_top: Optional[bool] = None) -> ToolResult:
        """Scroll the page upward (or to the very top when to_top is True)."""
        try:
            page = await self._get_current_page()
            if to_top:
                await page.evaluate("() => window.scrollTo(0, 0)")
            else:
                await page.evaluate("() => window.scrollBy(0, -window.innerHeight)")
            return ToolResult(success=True)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to scroll up: {exc}")

    async def scroll_down(self, to_bottom: Optional[bool] = None) -> ToolResult:
        """Scroll the page downward (or to the very bottom when to_bottom is True)."""
        try:
            page = await self._get_current_page()
            if to_bottom:
                await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            else:
                await page.evaluate("() => window.scrollBy(0, window.innerHeight)")
            return ToolResult(success=True)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to scroll down: {exc}")

    async def screenshot(self, full_page: Optional[bool] = False) -> bytes:
        """Return a PNG screenshot of the current page."""
        session = await self._ensure_session()
        return await session.take_screenshot(full_page=bool(full_page))

    async def get_select_options(self, index: int) -> ToolResult:
        """Return all options of a <select> element by DOM index.

        Returns a list of {option_index, value, text} objects so the caller
        knows exactly which option_index to pass to select_option().
        Returns success=False with a clear message when the element is not a native <select>.
        """
        try:
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(
                    success=False,
                    message=f"Cannot find element with index {index}",
                )
            await self._ensure_dom_document()
            page = await self._get_current_page()
            element = await page.get_element(node.backend_node_id)

            import json as _json
            js = (
                "() => {"
                "  if (this.tagName !== 'SELECT') {"
                "    return JSON.stringify({is_select: false, tag: this.tagName});"
                "  }"
                "  const opts = Array.from(this.options).map((o,i) => ({option_index:i, value:o.value, text:o.text.trim()}));"
                "  return JSON.stringify({is_select: true, options: opts});"
                "}"
            )
            raw = await element.evaluate(js)
            result = _json.loads(raw) if isinstance(raw, str) else raw
            if not result.get("is_select"):
                tag = result.get("tag", "unknown")
                return ToolResult(
                    success=False,
                    message=f"Element at index {index} is a <{tag}>, not a native <select>. Use click approach instead.",
                )
            options = result["options"]
            return ToolResult(
                success=True,
                message=f"Native <select> found with {len(options)} options",
                data={"options": options},
            )
        except Exception as exc:
            # Report the raw error — do NOT claim "not a native <select>" when
            # the actual failure is a CDP/session problem (misleading diagnosis).
            return ToolResult(
                success=False,
                message=(
                    f"get_select_options failed for element {index}: {exc}. "
                    "Call browser_view() to refresh the DOM snapshot, then retry "
                    "with a fresh index."
                ),
            )

    async def select_by_text(self, index: int, text: str) -> ToolResult:
        """Select a native <select> option whose visible text matches `text` (case-insensitive).

        Works WITHOUT opening the dropdown first — sets the value directly via JS and fires
        React-compatible input+change events. Returns success=False if element is not a native
        <select> so caller knows to fall back to the click approach.
        """
        try:
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")
            await self._ensure_dom_document()
            page = await self._get_current_page()
            element = await page.get_element(node.backend_node_id)

            import json as _json
            js = (
                "(searchText) => {"
                "  if (this.tagName !== 'SELECT') {"
                "    return JSON.stringify({success:false, reason:'not_select', tag:this.tagName});"
                "  }"
                "  const lower = searchText.trim().toLowerCase();"
                "  let found = null;"
                "  for (let i = 0; i < this.options.length; i++) {"
                "    if (this.options[i].text.trim().toLowerCase() === lower) { found = i; break; }"
                "  }"
                "  if (found === null) {"
                "    const opts = Array.from(this.options).map(o => o.text.trim()).join(', ');"
                "    return JSON.stringify({success:false, reason:'not_found', available:opts});"
                "  }"
                "  const opt = this.options[found];"
                "  try {"
                "    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;"
                "    setter.call(this, opt.value);"
                "  } catch(e) { this.selectedIndex = found; }"
                "  this.dispatchEvent(new Event('input',  {bubbles:true}));"
                "  this.dispatchEvent(new Event('change', {bubbles:true}));"
                "  return JSON.stringify({success:true, selected_text:opt.text.trim(), option_index:found});"
                "}"
            )
            raw = await element.evaluate(js, text)
            result = _json.loads(raw) if isinstance(raw, str) else raw
            if result.get("success"):
                sel = result.get("selected_text", text)
                return ToolResult(success=True, message=f"Selected '{sel}' in native <select>")
            reason = result.get("reason", "")
            if reason == "not_select":
                tag = result.get("tag", "unknown")
                return ToolResult(success=False, message=f"Element {index} is <{tag}>, not a native <select>. Use click approach.")
            available = result.get("available", "")
            return ToolResult(success=False, message=f"Option '{text}' not found. Available: {available[:200]}")
        except Exception as exc:
            return ToolResult(success=False, message=f"select_by_text failed: {exc}")

    async def _verify_element_value(self, index: int, expected_text: str) -> bool:
        """Internal helper: returns True if element value matches expected text."""
        try:
            result = await self.verify_value(index, expected_text)
            return result.success
        except Exception:
            return False

    async def smart_select(self, index: int, text: str) -> ToolResult:
        """Adaptive dropdown selector — 3-strategy chain (Manus.im style).

        Strategy 1 (native <select>): React-safe text match + prototype setter + synthetic events.
        Strategy 2 (custom dropdown):  click trigger → verify list visible → scan DOM → click option.
        Strategy 3 (text mismatch):    return available options list so agent retries with correct text.

        Key Manus.im behaviours implemented here:
        - Visibility check: after opening custom dropdown we wait and CONFIRM the list appeared
          before scanning for options (avoids clicking stale/hidden nodes).
        - DOM-settle wait after every successful pick so React/Vue state settles.
        - Coordinate-based CDP fallback for option clicks when JS .click() is intercepted.

        Returns success + which strategy worked so the agent can log/debug easily.
        No looping needed — one call handles everything.
        """
        import json as _json

        logger.info("SMART_SELECT[%d] text=%r — trying S1-native-select", index, text)
        # ── Strategy 1: native <select> via React-safe JS ──────────────────────
        s1 = await self.select_by_text(index, text)
        if s1.success:
            await self._wait_for_dom_settle()
            verified = await self._verify_element_value(index, text)
            logger.info("SMART_SELECT[%d] ✓ S1-native-select verified=%s", index, verified)
            return ToolResult(
                success=True,
                message=f"[native-select] Selected '{text}'. Verified={verified}",
                data={"strategy": "native_select", "verified": verified},
            )

        reason = s1.message or ""
        is_custom = (
            "not a native" in reason.lower()
            or "not_select" in reason.lower()
            or "use click" in reason.lower()
        )
        if is_custom:
            logger.info("SMART_SELECT[%d] S1 found custom dropdown → trying S2-custom-dropdown", index)
        else:
            logger.info("SMART_SELECT[%d] S1 failed (%s)", index, reason[:80])

        # ── Strategy 2: custom dropdown (click → visibility check → scan DOM → click option) ──
        if is_custom:
            # Open the dropdown using the full 3-strategy click chain
            click_r = await self.click(index=index)
            if not click_r.success:
                return ToolResult(
                    success=False,
                    message=(
                        f"smart_select: cannot open custom dropdown at index {index}: "
                        f"{click_r.message}"
                    ),
                )

            # ── Visibility check (Manus.im key step) ──────────────────────────
            # Wait up to 800 ms for at least one option-like element to become visible.
            # This prevents scanning the DOM before the dropdown animation completes.
            page = await self._get_current_page()
            OPTION_SELECTORS = (
                '[role="option"],[role="listitem"],[role="menuitem"],'
                '[aria-selected],[data-value],[data-option],'
                'li,ul>li,ol>li,.option,.dropdown-item'
            )
            visible_count = 0
            for _ in range(8):  # 8 × 100 ms = 800 ms max
                await asyncio.sleep(0.1)
                try:
                    visible_count = await page.evaluate(f"""() => {{
                        const nodes = document.querySelectorAll('{OPTION_SELECTORS}');
                        let n = 0;
                        for (const el of nodes) {{
                            const s = window.getComputedStyle(el);
                            if (s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) >= 0.1) n++;
                        }}
                        return n;
                    }}""")
                    if visible_count > 0:
                        break
                except Exception:
                    break

            js_find_click = """(searchText) => {
                const lower = searchText.trim().toLowerCase();
                const SELECTORS = [
                    '[role="option"]', '[role="listitem"]', '[role="menuitem"]',
                    '[aria-selected]', '[data-value]', '[data-option]',
                    'li', 'ul > li', 'ol > li', '.option', '.dropdown-item'
                ];
                const seen = new Set();
                // Exact match first
                for (const sel of SELECTORS) {
                    let nodes;
                    try { nodes = Array.from(document.querySelectorAll(sel)); } catch(e) { continue; }
                    for (const n of nodes) {
                        if (seen.has(n)) continue;
                        seen.add(n);
                        const s = window.getComputedStyle(n);
                        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.1) continue;
                        const t = (n.innerText || n.textContent || '').trim();
                        if (t.toLowerCase() === lower) {
                            const r = n.getBoundingClientRect();
                            n.click();
                            return JSON.stringify({success:true, clicked:t, match:'exact', cx: r.left+r.width/2, cy: r.top+r.height/2});
                        }
                    }
                }
                // Partial match fallback
                const seen2 = new Set();
                const visible = [];
                for (const sel of SELECTORS) {
                    let nodes;
                    try { nodes = Array.from(document.querySelectorAll(sel)); } catch(e) { continue; }
                    for (const n of nodes) {
                        if (seen2.has(n)) continue;
                        seen2.add(n);
                        const s = window.getComputedStyle(n);
                        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.1) continue;
                        const t = (n.innerText || n.textContent || '').trim();
                        if (!t) continue;
                        if (t.toLowerCase().includes(lower)) {
                            const r = n.getBoundingClientRect();
                            n.click();
                            return JSON.stringify({success:true, clicked:t, match:'partial', cx: r.left+r.width/2, cy: r.top+r.height/2});
                        }
                        if (visible.length < 20) visible.push(t.substring(0, 40));
                    }
                }
                return JSON.stringify({success:false, visible_options:[...new Set(visible)]});
            }"""

            try:
                raw = await page.evaluate(js_find_click, text)
                res = _json.loads(raw) if isinstance(raw, str) else raw
                if res.get("success"):
                    clicked = res.get("clicked", text)
                    match_type = res.get("match", "")
                    note = " (partial match)" if match_type == "partial" else ""
                    # CDP coordinate fallback: if JS .click() was intercepted, fire raw CDP event
                    cx = res.get("cx")
                    cy = res.get("cy")
                    if cx is not None and cy is not None:
                        try:
                            await self._cdp_click_at(cx, cy)
                        except Exception:
                            pass
                    await self._wait_for_dom_settle()
                    logger.info("SMART_SELECT[%d] ✓ S2-custom-dropdown clicked=%r match=%s", index, clicked, match_type)
                    return ToolResult(
                        success=True,
                        message=f"[custom-dropdown] Clicked option '{clicked}'{note}",
                        data={"strategy": "custom_dropdown", "clicked": clicked},
                    )
                visible = res.get("visible_options", [])
                visible_str = (
                    ", ".join(f'"{v}"' for v in visible[:12])
                    if visible
                    else "none visible — dropdown may not have opened"
                )
                logger.warning("SMART_SELECT[%d] ✗ S2 option %r not found. visible=[%s]", index, text, visible_str[:120])
                return ToolResult(
                    success=False,
                    message=(
                        f"smart_select: dropdown opened but option '{text}' not found. "
                        f"Visible options: [{visible_str}]. "
                        f"Call browser_view() to inspect, then retry with exact text from visible list."
                    ),
                )
            except Exception as exc:
                logger.warning("SMART_SELECT[%d] ✗ S2 exception: %s", index, exc)
                return ToolResult(
                    success=False,
                    message=f"smart_select custom-dropdown strategy failed: {exc}",
                )

        # Not custom — option text mismatch, pass back original message with available options
        logger.warning("SMART_SELECT[%d] ✗ no matching strategy for text=%r", index, text)
        return ToolResult(success=False, message=f"smart_select: {reason}")

    async def verify_value(self, index: int, expected_text: str) -> ToolResult:
        """Verify that an interactive element has the expected value after interaction.

        Works for:
        - native <select>  → checks selectedOptions[0].text
        - <input>/<textarea> → checks .value
        - custom elements  → checks innerText / aria-label / data-value

        Returns success=True if the element's current value matches expected_text
        (case-insensitive, partial containment accepted).
        """
        try:
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(
                    success=False,
                    message=f"Cannot find element with index {index}",
                )
            await self._ensure_dom_document()
            page = await self._get_current_page()
            element = await page.get_element(node.backend_node_id)

            import json as _json
            js = """(expected) => {
                const lower = expected.trim().toLowerCase();
                const tag = this.tagName;
                let actual = '';
                if (tag === 'SELECT') {
                    const sel = this.selectedOptions[0];
                    actual = sel ? sel.text.trim() : '';
                } else if (tag === 'INPUT' || tag === 'TEXTAREA') {
                    actual = (this.value || '').trim();
                } else {
                    actual = (
                        this.innerText ||
                        this.getAttribute('aria-label') ||
                        this.getAttribute('data-value') ||
                        this.textContent || ''
                    ).trim();
                }
                const aLower = actual.toLowerCase();
                // Empty actual must only match empty expected — previously
                // lower.includes('') was always true, so verify_value claimed
                // success even when the element had NO value at all.
                const match = aLower === ''
                    ? lower === ''
                    : (aLower === lower || aLower.includes(lower) || lower.includes(aLower));
                return JSON.stringify({match, actual, expected, tag});
            }"""
            raw = await element.evaluate(js, expected_text)
            import json as _json2
            res = _json2.loads(raw) if isinstance(raw, str) else raw
            match = res.get("match", False)
            actual = res.get("actual", "")
            return ToolResult(
                success=match,
                message=(
                    f"✅ Verified '{actual}' matches '{expected_text}'"
                    if match
                    else f"❌ Mismatch: expected='{expected_text}', actual='{actual}'"
                ),
                data=res,
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"verify_value failed: {exc}")

    async def console_exec(self, javascript: str) -> ToolResult:
        """Execute arbitrary JavaScript in the current page context."""
        try:
            page = await self._get_current_page()
            # Install the console capture shim FIRST so any console.* calls
            # inside the user's code are recorded for browser_console_view().
            await self._ensure_console_capture()
            js = javascript.strip()
            if not (js.startswith("(") and "=>" in js):
                # Bare JavaScript (not an arrow function). page.evaluate()
                # requires an expression starting with "(" containing "=>",
                # so wrap the code in an async arrow that runs it through
                # GLOBAL INDIRECT EVAL — this gives console-like semantics:
                # multiple statements are allowed AND the completion value
                # (last expression) is returned.
                import json as _json
                js = f"(async () => (0, eval)({_json.dumps(js)}))"
            result = await self._call_with_deadline(page.evaluate(js), timeout=60.0)
            return ToolResult(success=True, data={"result": result})
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to execute JavaScript: {exc}")

    async def console_view(self, max_lines: Optional[int] = None) -> ToolResult:
        """Return captured console log lines from the current page.

        Reads the buffer maintained by the console-capture shim installed via
        _ensure_console_capture() (registered with
        Page.addScriptToEvaluateOnNewDocument + an in-document installer, so
        capture also survives navigations).
        """
        try:
            # Make sure capture is active on the current document before reading.
            await self._ensure_console_capture()
            page = await self._get_current_page()
            logs_raw = await self._call_with_deadline(
                page.evaluate("() => JSON.stringify(window.__consoleLogs || [])"),
                timeout=30.0,
            )

            import json

            try:
                logs = json.loads(logs_raw) if isinstance(logs_raw, str) else logs_raw
            except (TypeError, ValueError):
                logs = logs_raw

            if logs is None:
                logs = []
            if max_lines is not None and isinstance(logs, list) and max_lines > 0:
                logs = logs[-max_lines:]

            return ToolResult(success=True, data={"logs": logs})
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to view console: {exc}")
