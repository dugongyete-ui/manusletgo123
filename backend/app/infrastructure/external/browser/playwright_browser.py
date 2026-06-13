from typing import Dict, Any, Optional, List
from playwright.async_api import async_playwright, Browser, Page
import asyncio
from markdownify import markdownify
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import get_settings
from app.domain.models.tool_result import ToolResult
import logging

# Set up logger for this module
logger = logging.getLogger(__name__)

class PlaywrightBrowser:
    """Playwright client that provides specific implementation of browser operations"""
    
    def __init__(self, cdp_url: str):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.settings = get_settings()
        kwargs = dict(
            model=self.settings.model_name,
            model_provider=self.settings.model_provider,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            base_url=self.settings.api_base,
        )
        if self.settings.extra_headers:
            kwargs["default_headers"] = self.settings.extra_headers
        self._model = init_chat_model(**kwargs)
        self.cdp_url = cdp_url
        
    async def initialize(self):
        """Initialize and ensure resources are available"""
        # Add retry logic
        max_retries = 5
        retry_delay = 1  # Initial wait 1 second
        for attempt in range(max_retries):
            try:
                self.playwright = await async_playwright().start()
                # Connect to existing Chrome instance
                self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
                # Get all contexts
                contexts = self.browser.contexts
                if contexts and len(contexts[0].pages) == 1:
                    # Check if it's the initial page (by URL)
                    page = contexts[0].pages[0]
                    page_url = await page.evaluate("window.location.href")
                    if (
                        page_url == "about:blank" or 
                        page_url == "chrome://newtab/" or 
                        page_url == "chrome://new-tab-page/" or 
                        not page_url
                    ):
                        # Only use it when it's the initial page and only one tab
                        self.page = page
                    else:
                        # Not the initial page, create a new page
                        self.page = await contexts[0].new_page()
                else:
                    # Create a new page in other cases
                    context = contexts[0] if contexts else await self.browser.new_context()
                    self.page = await context.new_page()
                return True
            except Exception as e:
                # Clean up failed resources
                await self.cleanup()
                
                # Return error if maximum retry count is reached
                if attempt == max_retries - 1:
                    logger.error(f"Initialization failed (retried {max_retries} times): {e}")
                    return False
                
                # Otherwise increase waiting time (exponential backoff strategy)
                retry_delay = min(retry_delay * 2, 10)  # Maximum wait 10 seconds
                logger.warning(f"Initialization failed, will retry in {retry_delay} seconds: {e}")
                await asyncio.sleep(retry_delay)

    async def cleanup(self):
        """Clean up Playwright resources, first close all tabs, then close the browser"""
        try:
            # If browser exists, first close all tabs
            if self.browser:
                # Get all contexts
                contexts = self.browser.contexts
                if contexts:
                    for context in contexts:
                        # Get all pages in the context
                        pages = context.pages
                        # Close all pages
                        for page in pages:
                            # Avoid closing self.page multiple times
                            if page != self.page or (self.page and not self.page.is_closed()):
                                await page.close()
            
            # Ensure the current page is closed (if it exists and is not closed)
            if self.page and not self.page.is_closed():
                await self.page.close()
                
            # Close the browser
            if self.browser:
                await self.browser.close()
                
            # Stop playwright
            if self.playwright:
                await self.playwright.stop()
                
        except Exception as e:
            logger.error(f"Error occurred when cleaning up resources: {e}")
        finally:
            # Reset references
            self.page = None
            self.browser = None
            self.playwright = None
    
    async def _ensure_browser(self):
        """Ensure the browser is started"""
        if not self.browser or not self.page:
            if not await self.initialize():
                raise Exception("Unable to initialize browser resources")
    
    async def _ensure_page(self):
        """Ensure the page is created and update to the current active tab (rightmost tab)"""
        await self._ensure_browser()
        if not self.page:
            self.page = await self.browser.new_page()
        else:
            # Get all contexts
            contexts = self.browser.contexts
            if contexts:
                # Get all pages in the current context
                current_context = contexts[0]
                pages = current_context.pages
                
                if pages:
                    # Get the rightmost tab (usually the most recently opened page)
                    rightmost_page = pages[-1]
                    
                    # Update if the current page is not the rightmost tab
                    if self.page != rightmost_page:
                        # Update to the rightmost tab
                        self.page = rightmost_page
    
    async def wait_for_page_load(self, timeout: int = 15) -> bool:
        """Wait for the page to finish loading, waiting up to the specified timeout
        
        Args:
            timeout: Maximum wait time (seconds), default is 15 seconds
            
        Returns:
            bool: Whether successfully waited for the page to load completely
        """
        await self._ensure_page()
        
        start_time = asyncio.get_event_loop().time()
        check_interval = 5  # Check every 5 seconds
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            # Check if the page has completely loaded
            is_loaded = await self.page.evaluate("""() => {
                return document.readyState === 'complete';
            }""")
            
            if is_loaded:
                return True
                
            # Wait for a while before checking again
            await asyncio.sleep(check_interval)
        
        # Timeout, page loading not completed
        return False
    
    async def _extract_content(self) -> Dict[str, Any]:
        """Extract content from the current page"""

        # Execute JavaScript to get elements in the viewport    
        visible_content = await self.page.evaluate("""() => {
            const visibleElements = [];
            const viewportHeight = window.innerHeight;
            const viewportWidth = window.innerWidth;
            
            // Get all potentially relevant elements
            const elements = document.querySelectorAll('body *');
            
            for (const element of elements) {
                // Check if the element is in the viewport and visible
                const rect = element.getBoundingClientRect();
                
                // Element must have some dimensions
                if (rect.width === 0 || rect.height === 0) continue;
                
                // Element must be within the viewport
                if (
                    rect.bottom < 0 || 
                    rect.top > viewportHeight ||
                    rect.right < 0 || 
                    rect.left > viewportWidth
                ) continue;
                
                // Check if the element is visible (not hidden by CSS)
                const style = window.getComputedStyle(element);
                if (
                    style.display === 'none' || 
                    style.visibility === 'hidden' || 
                    style.opacity === '0'
                ) continue;
                
                // If it's a text node or meaningful element, add it to the results
                if (
                    element.innerText || 
                    element.tagName === 'IMG' || 
                    element.tagName === 'INPUT' || 
                    element.tagName === 'BUTTON'
                ) {
                    visibleElements.push(element.outerHTML);
                }
            }
            
            // Build HTML containing these visible elements
            return '<div>' + visibleElements.join('') + '</div>';
        }""")

        
        # Convert to Markdown
        markdown_content = markdownify(visible_content)

        max_content_length = min(50000, len(markdown_content))
        response = await self._model.ainvoke([
            SystemMessage(content="You are a professional web page information extraction assistant. Please extract all information from the current page content and convert it to Markdown format."),
            HumanMessage(content=markdown_content[:max_content_length]),
        ])
        return response.content
    
    async def view_page(self) -> ToolResult:
        """View visible elements within the current page's viewport and convert to Markdown format"""
        await self._ensure_page()
        
        # Wait for the page to load completely, maximum wait 15 seconds
        await self.wait_for_page_load()
        
        # First update the interactive elements cache
        interactive_elements = await self._extract_interactive_elements()

        # Build tab summary so the agent always knows which tabs are open
        # and can use browser_switch_tab instead of browser_navigate
        tabs_info = []
        try:
            if self.browser and self.browser.contexts:
                pages = self.browser.contexts[0].pages
                for i, p in enumerate(pages):
                    tabs_info.append({
                        "tab": i + 1,
                        "url": p.url,
                        "active": p == self.page,
                    })
        except Exception:
            pass

        return ToolResult(
            success=True,
            data={
                "open_tabs": tabs_info,
                "interactive_elements": interactive_elements,
                "content": await self._extract_content(),
            }
        )
    
    async def _extract_interactive_elements(self) -> List[str]:
        """Return a list of visible interactive elements on the page, formatted as index:<tag>text</tag>"""
        await self._ensure_page()
        
        # Clear the current page's cache to ensure we always get the latest list of elements
        self.page.interactive_elements_cache = []
        
        # Execute JavaScript to get interactive elements in the viewport
        interactive_elements = await self.page.evaluate("""() => {
            const interactiveElements = [];
            const viewportHeight = window.innerHeight;
            const viewportWidth = window.innerWidth;
            
            // Get all potentially relevant interactive elements
            const elements = document.querySelectorAll('button, a, input, textarea, select, [role="button"], [tabindex]:not([tabindex="-1"])');
            
            let validElementIndex = 0; // For generating consecutive indices
            
            for (let i = 0; i < elements.length; i++) {
                const element = elements[i];
                // Check if the element is in the viewport and visible
                const rect = element.getBoundingClientRect();
                
                // Element must have some dimensions
                if (rect.width === 0 || rect.height === 0) continue;
                
                // Element must be within the viewport
                if (
                    rect.bottom < 0 || 
                    rect.top > viewportHeight ||
                    rect.right < 0 || 
                    rect.left > viewportWidth
                ) continue;
                
                // Check if the element is visible (not hidden by CSS)
                const style = window.getComputedStyle(element);
                if (
                    style.display === 'none' || 
                    style.visibility === 'hidden' || 
                    style.opacity === '0'
                ) continue;
                
                
                // Get element type and text
                let tagName = element.tagName.toLowerCase();
                let text = '';
                
                if (element.value && ['input', 'textarea', 'select'].includes(tagName)) {
                    text = element.value;
                    
                    // Add label and placeholder information for input elements
                    if (tagName === 'input') {
                        // Get associated label text
                        let labelText = '';
                        if (element.id) {
                            const label = document.querySelector(`label[for="${element.id}"]`);
                            if (label) {
                                labelText = label.innerText.trim();
                            }
                        }
                        
                        // Look for parent or sibling label
                        if (!labelText) {
                            const parentLabel = element.closest('label');
                            if (parentLabel) {
                                labelText = parentLabel.innerText.trim().replace(element.value, '').trim();
                            }
                        }
                        
                        // Add label information
                        if (labelText) {
                            text = `[Label: ${labelText}] ${text}`;
                        }
                        
                        // Add placeholder information
                        if (element.placeholder) {
                            text = `${text} [Placeholder: ${element.placeholder}]`;
                        }
                    }
                } else if (element.innerText) {
                    text = element.innerText.trim().replace(/\\s+/g, ' ');
                } else if (element.alt) { // For image buttons
                    text = element.alt;
                } else if (element.title) { // For elements with title
                    text = element.title;
                } else if (element.placeholder) { // For placeholder text
                    text = `[Placeholder: ${element.placeholder}]`;
                } else if (element.type) { // For input type
                    text = `[${element.type}]`;
                    
                    // Add label and placeholder information for text-less input elements
                    if (tagName === 'input') {
                        // Get associated label text
                        let labelText = '';
                        if (element.id) {
                            const label = document.querySelector(`label[for="${element.id}"]`);
                            if (label) {
                                labelText = label.innerText.trim();
                            }
                        }
                        
                        // Look for parent or sibling label
                        if (!labelText) {
                            const parentLabel = element.closest('label');
                            if (parentLabel) {
                                labelText = parentLabel.innerText.trim();
                            }
                        }
                        
                        // Add label information
                        if (labelText) {
                            text = `[Label: ${labelText}] ${text}`;
                        }
                        
                        // Add placeholder information
                        if (element.placeholder) {
                            text = `${text} [Placeholder: ${element.placeholder}]`;
                        }
                    }
                } else {
                    text = '[No text]';
                }
                
                // Maximum limit on text length to keep it clear
                if (text.length > 100) {
                    text = text.substring(0, 97) + '...';
                }
                
                // Only add data-dzeck-id attribute to elements that meet the conditions
                element.setAttribute('data-dzeck-id', `dzeck-element-${validElementIndex}`);
                                                        
                // Build selector - using only data-dzeck-id
                const selector = `[data-dzeck-id="dzeck-element-${validElementIndex}"]`;
                
                // Add element information to the array
                interactiveElements.push({
                    index: validElementIndex,  // Use consecutive index
                    tag: tagName,
                    text: text,
                    selector: selector
                });
                
                validElementIndex++; // Increment valid element counter
            }
            
            return interactiveElements;
        }""")
        
        # Update cache
        self.page.interactive_elements_cache = interactive_elements
        
        # Format element information in specified format
        formatted_elements = []
        for el in interactive_elements:
            formatted_elements.append(f"{el['index']}:<{el['tag']}>{el['text']}</{el['tag']}>")
        
        return formatted_elements
    
    async def navigate(self, url: str, timeout: Optional[int] = 15000) -> ToolResult:
        """Navigate to the specified URL
        
        Args:
            url: URL to navigate to
            timeout: Navigation timeout (milliseconds), default is 60 seconds
        """
        await self._ensure_page()
        try:
            # Clear cache as the page is about to change
            self.page.interactive_elements_cache = []
            try:
                await self.page.goto(url, timeout=timeout)
            except Exception as e:
                logger.warning(f"Failed to navigate to {url}: {str(e)}")
            return ToolResult(
                success=True,
                data={
                    "interactive_elements": await self._extract_interactive_elements(),
                }
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to navigate to {url}: {str(e)}")
    
    async def restart(self, url: str) -> ToolResult:
        """Restart the browser and navigate to the specified URL"""
        await self.cleanup()
        return await self.navigate(url)

    async def go_back(self) -> ToolResult:
        """Navigate back in the browser history."""
        try:
            await self._ensure_page()
            await self.page.go_back()
            return ToolResult(
                success=True,
                message="Navigated back",
                data={"interactive_elements": await self._extract_interactive_elements()},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to go back: {exc}")

    async def go_forward(self) -> ToolResult:
        """Navigate forward in the browser history."""
        try:
            await self._ensure_page()
            await self.page.go_forward()
            return ToolResult(
                success=True,
                message="Navigated forward",
                data={"interactive_elements": await self._extract_interactive_elements()},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to go forward: {exc}")

    
    async def _get_element_by_index(self, index: int) -> Optional[Any]:
        """Get element by index using data-dzeck-id selector
        
        Args:
            index: Element index
            
        Returns:
            The found element, or None if not found
        """
        # Check if there are cached elements
        if not hasattr(self.page, 'interactive_elements_cache') or not self.page.interactive_elements_cache or index >= len(self.page.interactive_elements_cache):
            return None
        
        # Use data-dzeck-id selector
        selector = f'[data-dzeck-id="dzeck-element-{index}"]'
        return await self.page.query_selector(selector)
    
    async def click(
        self,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None
    ) -> ToolResult:
        """Click an element"""
        await self._ensure_page()
        if coordinate_x is not None and coordinate_y is not None:
            await self.page.mouse.click(coordinate_x, coordinate_y)
        elif index is not None:
            try:
                element = await self._get_element_by_index(index)
                if not element:
                    return ToolResult(success=False, message=f"Cannot find interactive element with index {index}")
                
                # Check if the element is visible
                is_visible = await self.page.evaluate("""(element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return !(
                        rect.width === 0 || 
                        rect.height === 0 || 
                        style.display === 'none' || 
                        style.visibility === 'hidden' || 
                        style.opacity === '0'
                    );
                }""", element)
                
                if not is_visible:
                    # Try to scroll to the element position
                    await self.page.evaluate("""(element) => {
                        if (element) {
                            element.scrollIntoView({behavior: 'smooth', block: 'center'});
                        }
                    }""", element)
                    # Wait for the element to become visible
                    await asyncio.sleep(1)
                
                # Try to click the element
                await element.click(timeout=5000)
            except Exception as e:
                return ToolResult(success=False, message=f"Failed to click element: {str(e)}")
        return ToolResult(success=True)
    
    async def input(
        self,
        text: str,
        press_enter: bool,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None
    ) -> ToolResult:
        """Input text"""
        await self._ensure_page()
        if coordinate_x is not None and coordinate_y is not None:
            await self.page.mouse.click(coordinate_x, coordinate_y)
            await self.page.keyboard.type(text)
        elif index is not None:
            try:
                element = await self._get_element_by_index(index)
                if not element:
                    return ToolResult(success=False, message=f"Cannot find interactive element with index {index}")
                
                # Try to use fill() method, but catch possible errors
                try:
                    await element.fill("")
                    await element.type(text)
                except Exception as e:
                    # If fill() fails, use type() method directly
                    await element.click()
                    await self.page.keyboard.type(text)
            except Exception as e:
                return ToolResult(success=False, message=f"Failed to input text: {str(e)}")
        
        if press_enter:
            await self.page.keyboard.press("Enter")
        return ToolResult(success=True)
    
    async def move_mouse(
        self,
        coordinate_x: float,
        coordinate_y: float
    ) -> ToolResult:
        """Move the mouse"""
        await self._ensure_page()
        await self.page.mouse.move(coordinate_x, coordinate_y)
        return ToolResult(success=True)
    
    async def list_tabs(self) -> ToolResult:
        """Return a list of all currently open browser tabs with their index and URL."""
        try:
            await self._ensure_browser()
            contexts = self.browser.contexts
            if not contexts:
                return ToolResult(success=True, message="0 tab(s) open.", data={"tabs": [], "total_tabs": 0})
            pages = contexts[0].pages
            tabs = [{"tab": i + 1, "url": p.url} for i, p in enumerate(pages)]
            return ToolResult(
                success=True,
                message=f"{len(tabs)} tab(s) open.",
                data={"tabs": tabs, "total_tabs": len(tabs)},
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list tabs: {e}")

    async def open_tab(self, url: str) -> ToolResult:
        """Open a URL in a new browser tab."""
        try:
            await self._ensure_browser()
            contexts = self.browser.contexts
            context = contexts[0] if contexts else await self.browser.new_context()
            new_page = await context.new_page()
            await new_page.goto(url, timeout=30000)
            await new_page.bring_to_front()
            self.page = new_page
            pages = context.pages
            return ToolResult(
                success=True,
                message=f"Opened new tab with {url}. Total tabs: {len(pages)}.",
                data={"url": url, "tab": len(pages), "total_tabs": len(pages)},
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to open new tab: {e}")

    async def switch_tab(self, tab_index: int) -> ToolResult:
        """Switch the active browser tab by 1-based index."""
        try:
            await self._ensure_browser()
            contexts = self.browser.contexts
            if not contexts:
                return ToolResult(success=False, message="No browser context available")
            pages = contexts[0].pages
            if not pages:
                return ToolResult(success=False, message="No tabs are open")
            if tab_index < 1 or tab_index > len(pages):
                return ToolResult(
                    success=False,
                    message=f"Tab {tab_index} does not exist. {len(pages)} tab(s) are currently open.",
                )
            target = pages[tab_index - 1]
            await target.bring_to_front()
            self.page = target
            await asyncio.sleep(0.3)
            return ToolResult(
                success=True,
                message=f"Switched to tab {tab_index}: {target.url}",
                data={"tab": tab_index, "url": target.url, "total_tabs": len(pages)},
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to switch tab: {e}")

    async def press_key(self, key: str) -> ToolResult:
        """Simulate key press.

        Tab-related browser shortcuts (Control+t, Control+1…9, Control+Tab,
        Control+Shift+Tab) are handled natively via the Playwright context API
        because page.keyboard.press() cannot dispatch browser-chrome shortcuts.
        """
        import re
        key_norm = key.lower().replace(" ", "")

        # Control+t → open a new tab
        if key_norm in ("control+t", "ctrl+t"):
            try:
                await self._ensure_browser()
                contexts = self.browser.contexts
                context = contexts[0] if contexts else await self.browser.new_context()
                new_page = await context.new_page()
                await new_page.bring_to_front()
                self.page = new_page
                await asyncio.sleep(0.2)
                pages = context.pages
                return ToolResult(
                    success=True,
                    message=f"Opened new tab (tab {len(pages)}). Total tabs: {len(pages)}.",
                    data={"tab": len(pages), "total_tabs": len(pages)},
                )
            except Exception as e:
                return ToolResult(success=False, message=f"Failed to open new tab: {e}")

        # Control+1 … Control+9 → switch to tab N
        tab_match = re.match(r"^(?:control|ctrl)\+([1-9])$", key_norm)
        if tab_match:
            return await self.switch_tab(int(tab_match.group(1)))

        # Control+Tab → next tab
        if key_norm in ("control+tab", "ctrl+tab"):
            try:
                contexts = self.browser.contexts
                pages = contexts[0].pages if contexts else []
                if pages and self.page in pages:
                    idx = pages.index(self.page)
                    return await self.switch_tab((idx + 1) % len(pages) + 1)
            except Exception as e:
                return ToolResult(success=False, message=f"Failed to switch tab: {e}")

        # Control+Shift+Tab → previous tab
        if key_norm in ("control+shift+tab", "ctrl+shift+tab"):
            try:
                contexts = self.browser.contexts
                pages = contexts[0].pages if contexts else []
                if pages and self.page in pages:
                    idx = pages.index(self.page)
                    return await self.switch_tab((idx - 1) % len(pages) + 1)
            except Exception as e:
                return ToolResult(success=False, message=f"Failed to switch tab: {e}")

        # Default: dispatch to page
        await self._ensure_page()
        await self.page.keyboard.press(key)
        return ToolResult(success=True)
    
    async def select_option(
        self,
        index: int,
        option: int
    ) -> ToolResult:
        """Select dropdown option — fires React-compatible input+change events."""
        await self._ensure_page()
        try:
            element = await self._get_element_by_index(index)
            if not element:
                return ToolResult(success=False, message=f"Cannot find selector element with index {index}")

            # Use JS native setter so React/Vue synthetic event systems detect the
            # change, then fire both 'input' and 'change' events.
            js_code = """(el, optionIndex) => {
                if (optionIndex < 0 || optionIndex >= el.options.length) {
                    return JSON.stringify({success:false, error:'index '+optionIndex+' out of range ('+el.options.length+' options)'});
                }
                const opt = el.options[optionIndex];
                const text = opt.text;
                const value = opt.value;
                try {
                    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;
                    setter.call(el, value);
                } catch(e) {
                    el.selectedIndex = optionIndex;
                }
                el.dispatchEvent(new Event('input',  {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                return JSON.stringify({success:true, text:text, value:value});
            }"""
            import json as _json
            raw = await self.page.evaluate(js_code, element, option)
            result = _json.loads(raw) if isinstance(raw, str) else raw
            if result and result.get("success"):
                selected_text = result.get("text", "")
                msg = f"Selected option {option}" + (f" ('{selected_text}')" if selected_text else "")
                return ToolResult(success=True, message=msg)
            else:
                err = result.get("error", str(result)) if result else "unknown"
                return ToolResult(success=False, message=f"select_option JS failed: {err}")
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to select option: {str(e)}")
    
    async def scroll_up(
        self,
        to_top: Optional[bool] = None
    ) -> ToolResult:
        """Scroll up"""
        await self._ensure_page()
        if to_top:
            await self.page.evaluate("window.scrollTo(0, 0)")
        else:
            await self.page.evaluate("window.scrollBy(0, -window.innerHeight)")
        return ToolResult(success=True)
    
    async def scroll_down(
        self,
        to_bottom: Optional[bool] = None
    ) -> ToolResult:
        """Scroll down"""
        await self._ensure_page()
        if to_bottom:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        else:
            await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
        return ToolResult(success=True)
    
    async def screenshot(
        self,
        full_page: Optional[bool] = False
    ) -> bytes:
        """Take a screenshot of the current page
        
        Args:
            full_page: Whether to capture the full page or just the viewport
            
        Returns:
            bytes: PNG screenshot data
        """
        await self._ensure_page()
        
        # Configure screenshot options
        screenshot_options = {
            "full_page": full_page,
            "type": "png"
        }
        
        # Return bytes data directly
        return await self.page.screenshot(**screenshot_options)
    
    async def get_select_options(self, index: int) -> ToolResult:
        """Return all options of a <select> element by DOM index.

        Returns a list of {option_index, value, text} objects so the caller
        knows exactly which option_index to pass to select_option().
        """
        await self._ensure_page()
        try:
            element = await self._get_element_by_index(index)
            if not element:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")
            import json as _json
            raw = await self.page.evaluate(
                "(el) => JSON.stringify(Array.from(el.options).map((o,i) => ({option_index:i, value:o.value, text:o.text.trim()})))",
                element,
            )
            options = _json.loads(raw) if isinstance(raw, str) else raw
            return ToolResult(
                success=True,
                message=f"Found {len(options)} options",
                data={"options": options},
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to get select options: {str(e)}")

    async def select_by_text(self, index: int, text: str) -> ToolResult:
        """Select a native <select> option by visible text in one call."""
        await self._ensure_page()
        try:
            element = await self._get_element_by_index(index)
            if not element:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")
            import json as _json
            js = (
                "(el, searchText) => {"
                "  if (el.tagName !== 'SELECT') {"
                "    return JSON.stringify({success:false, reason:'not_select', tag:el.tagName});"
                "  }"
                "  const lower = searchText.trim().toLowerCase();"
                "  let found = null;"
                "  for (let i = 0; i < el.options.length; i++) {"
                "    if (el.options[i].text.trim().toLowerCase() === lower) { found = i; break; }"
                "  }"
                "  if (found === null) {"
                "    const opts = Array.from(el.options).map(o => o.text.trim()).join(', ');"
                "    return JSON.stringify({success:false, reason:'not_found', available:opts});"
                "  }"
                "  const opt = el.options[found];"
                "  try {"
                "    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set;"
                "    setter.call(el, opt.value);"
                "  } catch(e) { el.selectedIndex = found; }"
                "  el.dispatchEvent(new Event('input',  {bubbles:true}));"
                "  el.dispatchEvent(new Event('change', {bubbles:true}));"
                "  return JSON.stringify({success:true, selected_text:opt.text.trim(), option_index:found});"
                "}"
            )
            raw = await self.page.evaluate(js, element, text)
            result = _json.loads(raw) if isinstance(raw, str) else raw
            if result.get("success"):
                return ToolResult(success=True, message=f"Selected '{result.get('selected_text', text)}'")
            reason = result.get("reason", "")
            if reason == "not_select":
                return ToolResult(success=False, message=f"Element {index} is <{result.get('tag','?')}>, not a native <select>. Use click approach.")
            return ToolResult(success=False, message=f"Option '{text}' not found. Available: {result.get('available','')[:200]}")
        except Exception as e:
            return ToolResult(success=False, message=f"select_by_text failed: {e}")

    async def smart_select(self, index: int, text: str) -> ToolResult:
        """Adaptive dropdown selector — 3-strategy chain (Manus.im style).

        Strategy 1 (native <select>): React-safe text match + synthetic events.
        Strategy 2 (custom dropdown):  click trigger → scan visible options → click option.
        Strategy 3 (last resort):      partial text match across all visible list items.
        """
        import json as _json

        # Strategy 1: native <select>
        s1 = await self.select_by_text(index, text)
        if s1.success:
            verified = (await self.verify_value(index, text)).success
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

        # Strategy 2: custom dropdown
        if is_custom:
            await self._ensure_page()
            element = await self._get_element_by_index(index)
            if element:
                try:
                    await element.click(timeout=3000)
                except Exception:
                    pass
            await asyncio.sleep(0.35)

            js_find_click = """(searchText) => {
                const lower = searchText.trim().toLowerCase();
                const SELECTORS = [
                    '[role="option"]', '[role="listitem"]', '[role="menuitem"]',
                    '[aria-selected]', '[data-value]', '[data-option]',
                    'li', 'ul > li', 'ol > li', '.option', '.dropdown-item'
                ];
                const seen = new Set();
                for (const sel of SELECTORS) {
                    let nodes;
                    try { nodes = Array.from(document.querySelectorAll(sel)); } catch(e) { continue; }
                    for (const n of nodes) {
                        if (seen.has(n)) continue;
                        seen.add(n);
                        const s = window.getComputedStyle(n);
                        if (s.display === 'none' || s.visibility === 'hidden') continue;
                        const t = (n.innerText || n.textContent || '').trim();
                        if (t.toLowerCase() === lower) {
                            n.click();
                            return JSON.stringify({success:true, clicked:t, match:'exact'});
                        }
                    }
                }
                const seen2 = new Set();
                const visible = [];
                for (const sel of SELECTORS) {
                    let nodes;
                    try { nodes = Array.from(document.querySelectorAll(sel)); } catch(e) { continue; }
                    for (const n of nodes) {
                        if (seen2.has(n)) continue;
                        seen2.add(n);
                        const s = window.getComputedStyle(n);
                        if (s.display === 'none' || s.visibility === 'hidden') continue;
                        const t = (n.innerText || n.textContent || '').trim();
                        if (!t) continue;
                        if (t.toLowerCase().includes(lower)) {
                            n.click();
                            return JSON.stringify({success:true, clicked:t, match:'partial'});
                        }
                        if (visible.length < 20) visible.push(t.substring(0, 40));
                    }
                }
                return JSON.stringify({success:false, visible_options:[...new Set(visible)]});
            }"""

            try:
                raw = await self.page.evaluate(js_find_click, text)
                res = _json.loads(raw) if isinstance(raw, str) else raw
                if res.get("success"):
                    clicked = res.get("clicked", text)
                    note = " (partial match)" if res.get("match") == "partial" else ""
                    await asyncio.sleep(0.2)
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
                return ToolResult(
                    success=False,
                    message=(
                        f"smart_select: dropdown opened but option '{text}' not found. "
                        f"Visible options: [{visible_str}]. "
                        f"Call browser_view() to inspect, then retry with exact text."
                    ),
                )
            except Exception as exc:
                return ToolResult(success=False, message=f"smart_select custom strategy failed: {exc}")

        return ToolResult(success=False, message=f"smart_select: {reason}")

    async def verify_value(self, index: int, expected_text: str) -> ToolResult:
        """Verify that an interactive element has the expected value after interaction.

        Works for native <select> (selected text), <input>/<textarea> (value),
        and custom elements (innerText / aria-label / data-value).
        """
        await self._ensure_page()
        try:
            element = await self._get_element_by_index(index)
            if not element:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")
            import json as _json
            js = """(el, expected) => {
                const lower = expected.trim().toLowerCase();
                const tag = el.tagName;
                let actual = '';
                if (tag === 'SELECT') {
                    const sel = el.selectedOptions[0];
                    actual = sel ? sel.text.trim() : '';
                } else if (tag === 'INPUT' || tag === 'TEXTAREA') {
                    actual = (el.value || '').trim();
                } else {
                    actual = (
                        el.innerText ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('data-value') ||
                        el.textContent || ''
                    ).trim();
                }
                const aLower = actual.toLowerCase();
                const match = aLower === lower || aLower.includes(lower) || lower.includes(aLower);
                return JSON.stringify({match, actual, expected, tag});
            }"""
            raw = await self.page.evaluate(js, element, expected_text)
            res = _json.loads(raw) if isinstance(raw, str) else raw
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

    async def wait_for_network_idle(self, timeout: float = 5.0) -> ToolResult:
        """Manus.im Network Idle Detection — wait for in-flight requests to stop."""
        await self._ensure_page()
        try:
            await self.page.evaluate(f"""() => new Promise(resolve => {{
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
            }})""")
            return ToolResult(success=True, message=f"Network idle confirmed (waited up to {timeout}s)")
        except Exception as exc:
            return ToolResult(success=False, message=f"wait_for_network_idle failed: {exc}")

    async def wait_for_element(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        timeout: float = 10.0,
    ) -> ToolResult:
        """Manus.im Element-Based Waiting — wait until a specific element appears or text is visible."""
        await self._ensure_page()
        import json as _json
        try:
            raw = await self.page.evaluate(f"""(args) => new Promise(resolve => {{
                const [selector, text, timeout] = args;
                const deadline = Date.now() + timeout * 1000;
                const check = () => {{
                    if (selector) {{
                        try {{
                            const el = document.querySelector(selector);
                            if (el) {{
                                const r = el.getBoundingClientRect();
                                const s = window.getComputedStyle(el);
                                if (r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden') {{
                                    resolve(JSON.stringify({{found:true, method:'selector',
                                        tag:el.tagName.toLowerCase(),
                                        text:(el.innerText||el.textContent||'').trim().substring(0,80)}}));
                                    return;
                                }}
                            }}
                        }} catch(e) {{}}
                    }}
                    if (text) {{
                        const lower = text.toLowerCase();
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
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
                                    tag:parent.tagName.toLowerCase(), text:t.substring(0,80)}}));
                                return;
                            }}
                        }}
                    }}
                    if (Date.now() >= deadline) {{
                        resolve(JSON.stringify({{found:false}})); return;
                    }}
                    setTimeout(check, 200);
                }};
                check();
            }})""", [selector, text, timeout])
            res = _json.loads(raw) if isinstance(raw, str) else raw
            if res.get("found"):
                return ToolResult(
                    success=True,
                    message=f"Found [{res.get('method')}]: <{res.get('tag')}>{res.get('text','')[:60]}</{res.get('tag')}>",
                    data=res,
                )
            target = selector or f'text="{text}"'
            return ToolResult(success=False, message=f"Element '{target}' not found within {timeout}s.")
        except Exception as exc:
            return ToolResult(success=False, message=f"wait_for_element failed: {exc}")

    async def upload_file(self, index: int, file_path: str) -> ToolResult:
        """Upload a local file to an <input type='file'> element — Manus.im Integrated File Upload."""
        import os
        await self._ensure_page()
        try:
            if not os.path.isfile(file_path):
                return ToolResult(success=False, message=f"File not found: {file_path}")
            element = await self._get_element_by_index(index)
            if not element:
                return ToolResult(success=False, message=f"Cannot find element with index {index}")
            import json as _json
            tag_check = await self.page.evaluate(
                "(el) => JSON.stringify({tag:el.tagName, type:(el.type||'').toLowerCase()})", element
            )
            info = _json.loads(tag_check) if isinstance(tag_check, str) else tag_check
            if info.get("tag", "").upper() != "INPUT" or info.get("type") != "file":
                return ToolResult(
                    success=False,
                    message=f"Element {index} is not <input type='file'>. Tag={info.get('tag')}, type={info.get('type')}.",
                )
            await element.set_input_files(file_path)
            await asyncio.sleep(0.3)
            return ToolResult(
                success=True,
                message=f"File '{os.path.basename(file_path)}' uploaded to element {index}.",
                data={"file_path": file_path, "file_name": os.path.basename(file_path)},
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"upload_file failed: {exc}")

    async def console_exec(self, javascript: str) -> ToolResult:
        """Execute JavaScript code"""
        await self._ensure_page()
        result = await self.page.evaluate(javascript)
        return ToolResult(success=True, data={"result": result})
    
    async def console_view(self, max_lines: Optional[int] = None) -> ToolResult:
        """View console output"""
        await self._ensure_page()
        logs = await self.page.evaluate("""() => {
            return window.console.logs || [];
        }""")
        if max_lines is not None:
            logs = logs[-max_lines:]
        return ToolResult(success=True, data={"logs": logs})
