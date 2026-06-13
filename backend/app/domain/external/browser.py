from typing import Optional, Protocol
from app.domain.models.tool_result import ToolResult

class Browser(Protocol):
    """Browser service gateway interface"""
    
    async def view_page(self) -> ToolResult:
        """View current page content"""
        ...
    
    async def navigate(self, url: str) -> ToolResult:
        """Navigate to specified URL"""
        ...
    
    async def restart(self, url: str) -> ToolResult:
        """Restart browser and navigate to specified URL"""
        ...
    
    async def click(
        self,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None
    ) -> ToolResult:
        """Click element"""
        ...
    
    async def input(
        self,
        text: str,
        press_enter: bool,
        index: Optional[int] = None,
        coordinate_x: Optional[float] = None,
        coordinate_y: Optional[float] = None
    ) -> ToolResult:
        """Input text"""
        ...
    
    async def move_mouse(
        self,
        coordinate_x: float,
        coordinate_y: float
    ) -> ToolResult:
        """Move mouse"""
        ...
    
    async def press_key(self, key: str) -> ToolResult:
        """Simulate key press"""
        ...
    
    async def select_option(
        self,
        index: int,
        option: int
    ) -> ToolResult:
        """Select dropdown option"""
        ...
    
    async def go_back(self) -> ToolResult:
        """Navigate back in browser history"""
        ...

    async def go_forward(self) -> ToolResult:
        """Navigate forward in browser history"""
        ...

    async def scroll_up(
        self,
        to_top: Optional[bool] = None
    ) -> ToolResult:
        """Scroll up"""
        ...
    
    async def scroll_down(
        self,
        to_bottom: Optional[bool] = None
    ) -> ToolResult:
        """Scroll down"""
        ...
    
    async def screenshot(
        self,
        full_page: Optional[bool] = False
    ) -> bytes:
        """Take a screenshot of the current page"""
        ...
    
    async def console_exec(self, javascript: str) -> ToolResult:
        """Execute JavaScript code"""
        ...
    
    async def list_tabs(self) -> ToolResult:
        """List all currently open browser tabs with their index and URL"""
        ...

    async def open_tab(self, url: str) -> ToolResult:
        """Open a URL in a new browser tab"""
        ...

    async def switch_tab(self, tab_index: int) -> ToolResult:
        """Switch to a browser tab by 1-based index"""
        ...

    async def get_select_options(self, index: int) -> ToolResult:
        """Get all options from a <select> element by DOM index"""
        ...

    async def select_by_text(self, index: int, text: str) -> ToolResult:
        """Select a native <select> option by visible text in one call"""
        ...

    async def smart_select(self, index: int, text: str) -> ToolResult:
        """Adaptive dropdown selector: handles native <select> AND custom React/div dropdowns"""
        ...

    async def verify_value(self, index: int, expected_text: str) -> ToolResult:
        """Verify an element has the expected value after interaction"""
        ...

    async def wait_for_network_idle(self, timeout: float = 5.0) -> ToolResult:
        """Wait for all in-flight network requests to complete (Network Idle Detection)"""
        ...

    async def wait_for_element(
        self,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        timeout: float = 10.0,
    ) -> ToolResult:
        """Wait until a DOM element matching a CSS selector or visible text appears"""
        ...

    async def upload_file(self, index: int, file_path: str) -> ToolResult:
        """Upload a local file to an <input type='file'> element"""
        ...

    async def console_view(self, max_lines: Optional[int] = None) -> ToolResult:
        """View console output"""
        ...
