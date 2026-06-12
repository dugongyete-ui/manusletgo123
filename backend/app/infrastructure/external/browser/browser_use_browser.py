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

    def __init__(self, cdp_url: str):
        self.cdp_url = cdp_url
        self._session: Optional[BrowserSession] = None

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_current_page(self):
        """Return the actor Page for the currently focused tab."""
        session = await self._ensure_session()
        page = await session.get_current_page()
        if page is None:
            page = await session.new_page()
        return page

    async def _get_cdp_session(self) -> CDPSession:
        """Return the CDPSession for the currently focused tab."""
        session = await self._ensure_session()
        return await session.get_or_create_cdp_session()

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

    # ------------------------------------------------------------------
    # Browser Protocol implementation
    # ------------------------------------------------------------------

    # Maximum interactive elements returned per browser_view / navigate call.
    # Keeps LLM context payload manageable for complex pages (e.g. Facebook).
    _MAX_INTERACTIVE_ELEMENTS = 300

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
                if len(interactive_elements) > self._MAX_INTERACTIVE_ELEMENTS:
                    interactive_elements = interactive_elements[:self._MAX_INTERACTIVE_ELEMENTS]
                    interactive_elements.append(
                        f"... (truncated, showing first {self._MAX_INTERACTIVE_ELEMENTS} of {len(selector_map)} elements — use coordinates or scroll to reach others)"
                    )

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
            session = await self._ensure_session()
            await session.navigate_to(url)
            # navigate_to() completes before the DOM watchdog has serialised the new page,
            # so _cached_selector_map is empty at this point.  Calling
            # get_browser_state_summary() triggers DOM serialisation and populates the
            # selector map so the caller immediately receives the correct element list.
            state = await session.get_browser_state_summary(include_screenshot=False)
            interactive_elements: List[str] = []
            if state.dom_state is not None:
                selector_map = state.dom_state.selector_map or {}
                interactive_elements = self._format_selector_map(selector_map)
                if len(interactive_elements) > self._MAX_INTERACTIVE_ELEMENTS:
                    interactive_elements = interactive_elements[:self._MAX_INTERACTIVE_ELEMENTS]
                    interactive_elements.append(
                        f"... (truncated, showing first {self._MAX_INTERACTIVE_ELEMENTS} of {len(selector_map)} elements)"
                    )
            return ToolResult(
                success=True,
                data={"interactive_elements": interactive_elements},
            )
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
        """Click an element by DOM index or by screen coordinates."""
        try:
            if coordinate_x is not None and coordinate_y is not None:
                # Move mouse to target before pressing to trigger hover/focus events
                await self._dispatch_mouse_event("mouseMoved", coordinate_x, coordinate_y)
                await asyncio.sleep(0.05)
                await self._dispatch_mouse_event(
                    "mousePressed", coordinate_x, coordinate_y, "left", 1
                )
                await asyncio.sleep(0.08)
                await self._dispatch_mouse_event(
                    "mouseReleased", coordinate_x, coordinate_y, "left", 1
                )
            elif index is not None:
                session = await self._ensure_session()
                node = await session.get_dom_element_by_index(index)
                if node is None:
                    return ToolResult(
                        success=False,
                        message=f"Cannot find interactive element with index {index}",
                    )
                page = await self._get_current_page()
                element = await page.get_element(node.backend_node_id)
                await element.click()
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
        """Type text into an element identified by DOM index or screen coordinates."""
        try:
            page = await self._get_current_page()

            if coordinate_x is not None and coordinate_y is not None:
                # Click first to focus, then insert text via CDP
                await self._dispatch_mouse_event(
                    "mousePressed", coordinate_x, coordinate_y, "left", 1
                )
                await self._dispatch_mouse_event(
                    "mouseReleased", coordinate_x, coordinate_y, "left", 1
                )
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
                await element.fill(text)

            if press_enter:
                await page.press("Enter")

            return ToolResult(success=True)
        except Exception as exc:
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
            return ToolResult(success=True, message=msg)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to select option: {exc}")

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
        """
        try:
            session = await self._ensure_session()
            node = await session.get_dom_element_by_index(index)
            if node is None:
                return ToolResult(
                    success=False,
                    message=f"Cannot find element with index {index}",
                )
            page = await self._get_current_page()
            element = await page.get_element(node.backend_node_id)

            import json as _json
            raw = await element.evaluate(
                "() => JSON.stringify(Array.from(this.options).map((o,i) => ({option_index:i, value:o.value, text:o.text.trim()})))"
            )
            options = _json.loads(raw) if isinstance(raw, str) else raw
            return ToolResult(
                success=True,
                message=f"Found {len(options)} options",
                data={"options": options},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to get select options: {exc}")

    async def console_exec(self, javascript: str) -> ToolResult:
        """Execute arbitrary JavaScript in the current page context."""
        try:
            page = await self._get_current_page()
            # page.evaluate() requires a function; wrap bare expressions/statements
            js = javascript.strip()
            if not (js.startswith("(") and "=>" in js):
                # Use async IIFE so await works inside, and wrap in parens so
                # it evaluates as an expression (not a statement).
                # If the code contains explicit return statements leave it as a
                # block body; otherwise treat the whole thing as a return value.
                if "return " in js:
                    js = f"async () => {{ {js} }}"
                else:
                    js = f"async () => ({js})"
            result = await page.evaluate(js)
            return ToolResult(success=True, data={"result": result})
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to execute JavaScript: {exc}")

    async def console_view(self, max_lines: Optional[int] = None) -> ToolResult:
        """Return captured console log lines from the current page."""
        try:
            page = await self._get_current_page()
            logs_raw = await page.evaluate("() => window.console.logs || []")

            import json

            try:
                logs = json.loads(logs_raw) if isinstance(logs_raw, str) else logs_raw
            except (TypeError, ValueError):
                logs = logs_raw

            if max_lines is not None and isinstance(logs, list):
                logs = logs[-max_lines:]

            return ToolResult(success=True, data={"logs": logs})
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to view console: {exc}")
