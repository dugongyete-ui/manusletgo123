from typing import Optional
from app.domain.external.browser import Browser
from app.domain.services.tools.base import BaseToolkit
from app.domain.models.tool_result import ToolResult
from langchain.tools import tool

class BrowserToolkit(BaseToolkit):
    """Browser tool class, providing browser interaction functions"""

    name: str = "browser"
    
    def __init__(self, browser: Browser):
        """Initialize browser tool class
        
        Args:
            browser: Browser service
        """
        super().__init__()
        self.browser = browser
    
    @tool(parse_docstring=True)
    async def browser_view(self) -> ToolResult:
        """View content of the current browser page. Use for checking the latest state of previously opened pages.
        """
        return await self.browser.view_page()
    
    @tool(parse_docstring=True)
    async def browser_navigate(self, url: str) -> ToolResult:
        """Navigate browser to specified URL. Use when accessing new pages is needed.
        The result includes the OBSERVED page right after load: url, title, all interactive elements, and the page text content — READ it before acting so you react to what the page actually shows.
        
        Args:
            url: Complete URL to visit. Must include protocol prefix.
        """
        return await self.browser.navigate(url)
    
    @tool(parse_docstring=True)
    async def browser_restart(self, url: str) -> ToolResult:
        """Restart browser and navigate to specified URL. Use when browser state needs to be reset.
        
        Args:
            url: Complete URL to visit after restart. Must include protocol prefix.
        """
        return await self.browser.restart(url)
    
    @tool(parse_docstring=True)
    async def browser_click(
        self,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None,
        text: Optional[str] = None
    ) -> ToolResult:
        """Click on elements in the current browser page — by index, by coordinates, or by text locator.

        The text locator (text="...") finds a VISIBLE element by aria-label, placeholder or visible
        text and clicks it with the full pointer-event sequence. USE IT when the element you need is
        NOT in the interactive_elements list — many modern React widgets (combobox dropdown
        triggers, custom menus) never appear there. Check the aria_widgets list in browser_view
        results for elements that require this form of clicking.

        On success the result carries the observed page state afterwards: url, title, page_changed
        flag, fresh interactive elements (and page text when the click navigated). Read it to see
        what your click actually did before the next action.

        Args:
            index: (Optional) Index number of the element to click (from interactive_elements)
            coordinate_x: (Optional) X coordinate of click position
            coordinate_y: (Optional) Y coordinate of click position
            text: (Optional) Locator: aria-label, placeholder or visible text of the element to click (e.g. text="Select day")
        """
        return await self.browser.click(index, coordinate_x, coordinate_y, text)
    
    @tool(parse_docstring=True)
    async def browser_find_element(
        self,
        query: str,
        role: Optional[str] = None
    ) -> ToolResult:
        """Locate elements on the current page by text, aria-label or placeholder — even when they are NOT in the interactive_elements list.

        Use this BEFORE giving up on finding an element. It searches both the interactive-elements
        list (returns clickable indexes) AND the live DOM (returns coordinates + text-locator hints
        for elements the list does not expose — e.g. role=combobox dropdown triggers on React sites,
        or elements beyond the 300-element cap).

        Args:
            query: Text to search for — substring of the visible text, aria-label or placeholder (e.g. "Select day", "gender", "Sign up")
            role: (Optional) Filter by ARIA role (e.g. combobox, button, tab, option, checkbox, radio, switch, menuitem)
        """
        return await self.browser.find_element(query, role)
    
    @tool(parse_docstring=True)
    async def browser_input(
        self,
        text: str,
        press_enter: bool,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None
    ) -> ToolResult:
        """Overwrite text in editable elements on the current browser page. Use when filling content in input fields.
        With press_enter=true the result includes the observed page state after the submit (url, title, fresh elements, page text when the page changed) — read it to see how the site responded.
        
        Args:
            index: (Optional) Index number of the element to overwrite text
            coordinate_x: (Optional) X coordinate of the element to overwrite text
            coordinate_y: (Optional) Y coordinate of the element to overwrite text
            text: Complete text content to overwrite
            press_enter: Whether to press Enter key after input
        """
        return await self.browser.input(text, press_enter, index, coordinate_x, coordinate_y)
    
    @tool(parse_docstring=True)
    async def browser_move_mouse(
        self,
        coordinate_x: float,
        coordinate_y: float
    ) -> ToolResult:
        """Move cursor to specified position on the current browser page. Use when simulating user mouse movement.
        
        Args:
            coordinate_x: X coordinate of target cursor position
            coordinate_y: Y coordinate of target cursor position
        """
        return await self.browser.move_mouse(coordinate_x, coordinate_y)
    
    @tool(parse_docstring=True)
    async def browser_press_key(
        self,
        key: str
    ) -> ToolResult:
        """Simulate key press in the current browser page. Use when specific keyboard operations are needed.
        
        Args:
            key: Key name to simulate (e.g., Enter, Tab, ArrowUp), supports key combinations (e.g., Control+Enter).
        """
        return await self.browser.press_key(key)
    
    @tool(parse_docstring=True)
    async def browser_select_option(
        self,
        index: int,
        option: int
    ) -> ToolResult:
        """Select specified option from dropdown list element in the current browser page. Use when selecting dropdown menu options.
        
        Args:
            index: Index number of the dropdown list element
            option: Option number to select, starting from 0.
        """
        return await self.browser.select_option(index, option)
    
    @tool(parse_docstring=True)
    async def browser_back(self) -> ToolResult:
        """Navigate back to the previous page in browser history. Use when you need to return to the page visited before the current one (equivalent to clicking the browser Back button).
        """
        return await self.browser.go_back()

    @tool(parse_docstring=True)
    async def browser_forward(self) -> ToolResult:
        """Navigate forward to the next page in browser history. Use after browser_back when you want to return to the page you came from.
        """
        return await self.browser.go_forward()

    @tool(parse_docstring=True)
    async def browser_scroll_up(
        self,
        to_top: Optional[bool] = None
    ) -> ToolResult:
        """Scroll up the current browser page. Use when viewing content above or returning to page top.
        
        Args:
            to_top: (Optional) Whether to scroll directly to page top instead of one viewport up.
        """
        return await self.browser.scroll_up(to_top)
    
    @tool(parse_docstring=True)
    async def browser_scroll_down(
        self,
        to_bottom: Optional[bool] = None
    ) -> ToolResult:
        """Scroll down the current browser page. Use when viewing content below or jumping to page bottom.
        
        Args:
            to_bottom: (Optional) Whether to scroll directly to page bottom instead of one viewport down.
        """
        return await self.browser.scroll_down(to_bottom)
    
    @tool(parse_docstring=True)
    async def browser_console_exec(
        self,
        javascript: str
    ) -> ToolResult:
        """Execute JavaScript code in browser console. Use when custom scripts need to be executed.
        
        Args:
            javascript: JavaScript code to execute. Note that the runtime environment is browser console.
        """
        return await self.browser.console_exec(javascript)
    
    @tool(parse_docstring=True)
    async def browser_list_tabs(self) -> ToolResult:
        """List all currently open browser tabs with their tab number and URL. Call this before switching tabs so you know which index to use with browser_switch_tab.
        """
        return await self.browser.list_tabs()

    @tool(parse_docstring=True)
    async def browser_open_tab(self, url: str) -> ToolResult:
        """Open a URL in a new browser tab without replacing the current page. Use this whenever a task requires two sites open simultaneously — for example, opening a sign-up form while keeping a temp-mail inbox visible in tab 1.

        Args:
            url: Complete URL to open in the new tab. Must include protocol prefix (e.g. https://).
        """
        return await self.browser.open_tab(url)

    @tool(parse_docstring=True)
    async def browser_switch_tab(self, tab_index: int) -> ToolResult:
        """Switch to a specific browser tab by its 1-based position. Use this whenever you need to move between open tabs — for example, switching back to a temp-mail tab after submitting a form in another tab.

        Args:
            tab_index: The 1-based index of the tab to switch to (1 = first/leftmost tab, 2 = second tab, etc.).
        """
        return await self.browser.switch_tab(tab_index)

    @tool(parse_docstring=True)
    async def browser_select_by_text(self, index: int, text: str) -> ToolResult:
        """Select a dropdown option by its visible text in one call — no need to open the dropdown first.

        Works directly on native <select> elements by setting the value via JavaScript and firing
        React-compatible events. Handles Day/Month/Year birthday pickers, country selects, etc.

        - If it succeeds → the value is set. Done.
        - If it returns an error saying "not a native <select>" → the element is a custom dropdown, use browser_click to open it then click the option.
        - If it returns "not found" → check the available options listed in the message and retry with the correct text.

        Args:
            index: DOM index of the dropdown element (from browser_view interactive elements list).
            text: The visible option text to select (e.g. "5", "June", "1992", "Indonesia").
        """
        return await self.browser.select_by_text(index, text)

    @tool(parse_docstring=True)
    async def browser_get_select_options(self, index: int) -> ToolResult:
        """Probe any dropdown element to check if it is a native <select> and retrieve its options.

        Call this on EVERY dropdown-looking element BEFORE deciding how to interact with it.
        - If it returns a list of options → it IS a native <select>. Use browser_select_option(index, option_index) to pick the value — do NOT click it.
        - If it returns an error → it is a custom dropdown. Click to open, then browser_view, then click the target option.

        Returns [{option_index, value, text}] — option_index is the 0-based number to pass to browser_select_option.

        Args:
            index: DOM index of the element to probe (from browser_view interactive elements list).
        """
        return await self.browser.get_select_options(index)

    @tool(parse_docstring=True)
    async def browser_smart_select(
        self,
        index: Optional[int] = None,
        option: Optional[str] = None,
        dropdown: Optional[str] = None
    ) -> ToolResult:
        """Select a dropdown option — the PRIMARY tool for ALL dropdowns and comboboxes.

        Three locator styles, use whichever fits:
        1. dropdown="Select day", option="15"  — BY NAME (recommended for custom React comboboxes:
           Facebook/Instagram-style DOB & gender pickers, Material-UI/Ant selects). The dropdown
           locator is the trigger's aria-label or visible text; works even when the trigger is NOT
           in the interactive_elements list.
        2. index=123, option="June"             — by element index from browser_view.
        3. For native <select> you may also use browser_select_by_text(index, text).

        One call handles everything automatically: finds the trigger, opens it with the pointer-event
        sequence (required by React widgets that ignore plain clicks), waits for the option list,
        clicks the matching option, and VERIFIES the trigger now shows the chosen value.

        If the option text is not found, the visible options are returned so you can retry with the
        exact text immediately.

        Args:
            index: (Optional) DOM index of the dropdown element (from browser_view interactive elements list).
            option: The visible option text to select (e.g. "15", "June", "1992", "Male", "Indonesia").
            dropdown: (Optional but recommended) Locator for the dropdown trigger: its aria-label or visible text (e.g. "Select day", "Month", "Country").
        """
        return await self.browser.smart_select(index, option, dropdown)

    @tool(parse_docstring=True)
    async def browser_verify_value(self, index: int, expected_text: str) -> ToolResult:
        """Verify that an interactive element has the expected value after setting it.

        Call this after browser_smart_select or browser_input to confirm the value was
        actually accepted by the page (especially important for React-controlled forms).

        Works for: native <select> (selected text), <input>/<textarea> (value),
        custom elements (innerText / aria-label / data-value).

        Returns success=True if current value matches expected_text (case-insensitive).

        Args:
            index: DOM index of the element to check (from browser_view interactive elements list).
            expected_text: The value you expect the element to have (e.g. "June", "15", "1992").
        """
        return await self.browser.verify_value(index, expected_text)

    @tool(parse_docstring=True)
    async def browser_console_view(
        self,
        max_lines: Optional[int] = None
    ) -> ToolResult:
        """View browser console output. Use when checking JavaScript logs or debugging page errors.
        
        Args:
            max_lines: (Optional) Maximum number of log lines to return.
        """
        return await self.browser.console_view(max_lines)

    @tool(parse_docstring=True)
    async def browser_wait_for_network_idle(
        self,
        timeout: Optional[float] = 5.0,
    ) -> ToolResult:
        """Wait for all in-flight network requests (fetch/XHR) to complete before continuing.

        Use this after actions that trigger background API calls:
        - After clicking a "Login" / "Submit" / "Search" button
        - After a form submission that loads new data
        - After any navigation where content streams in asynchronously

        Do NOT use for simple DOM changes — browser_click and browser_input already
        include DOM settle. Only add browser_wait_for_network_idle when you expect
        the page to make API calls after your action.

        Args:
            timeout: Maximum seconds to wait (default 5). Use 10 for slow pages.
        """
        return await self.browser.wait_for_network_idle(timeout or 5.0)

    @tool(parse_docstring=True)
    async def browser_wait_for_element(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        timeout: Optional[float] = 10.0,
    ) -> ToolResult:
        """Wait until a specific DOM element appears and becomes visible on the page.

        Use this after actions that cause new content to load:
        - After clicking a button that opens a modal or dialog
        - After a navigation before the next interaction
        - After submitting a form — wait for confirmation message
        - After clicking "Load more" — wait for new items to appear

        Provide at least one of selector or text (can provide both as extra confirmation).

        Args:
            selector: CSS selector (e.g. '.modal', '#success-msg', '[role="dialog"]', 'button.confirm').
            text:     Visible text to wait for (e.g. "Welcome", "Order confirmed", "successfully created").
            timeout:  Max wait in seconds (default 10). Use 20 for slow pages or file processing.
        """
        return await self.browser.wait_for_element(
            selector=selector,
            text=text,
            timeout=timeout or 10.0,
        )

    @tool(parse_docstring=True)
    async def browser_upload_file(
        self,
        index: int,
        file_path: str,
    ) -> ToolResult:
        """Upload a local file to an <input type='file'> form field.

        Use this when a web form requires a file attachment (profile photo, document, CSV, etc.).
        The file must already exist in the sandbox filesystem.

        Steps to use:
        1. Call browser_view() to find the <input type="file"> element and note its index.
        2. Call browser_upload_file(index, file_path) with the absolute sandbox path.
        3. Call browser_verify_value(index, filename) to confirm upload was registered.

        Args:
            index:     DOM index of the <input type='file'> element from browser_view.
            file_path: Absolute path to the file in the sandbox, under the home directory described in your sandbox environment (e.g. ~/photo.jpg — the shell expands it; or its absolute form).
        """
        return await self.browser.upload_file(index=index, file_path=file_path)
