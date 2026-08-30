"""Regression tests: every tool result must be RICH and VISIBLE (Task 27).

Covers the 2026-08-30 full-tool-verification fixes:
1. ``AgentTaskRunner._handle_tool_event`` shell branch — a FAILED
   shell_exec (missing the required ``id`` arg) must display the actual
   error message, not "(No Console)".
2. ``_handle_tool_event`` search branch — a FAILED search (data=None)
   must produce SearchToolContent(results=[]) instead of raising and
   leaving the tool pill blank.
3. ``BrowserUseBrowser`` action tools (input / press_key / move_mouse /
   scroll_up / scroll_down) must return a descriptive message + data —
   a bare ``ToolResult(success=True)`` left the LLM blind and the tool
   panel empty whenever the screenshot circuit breaker was open.
4. ``BrowserUseBrowser.upload_file`` — provider-agnostic path resolution
   (Chrome validates the path on ITS filesystem, works on E2B microVMs
   where the backend host cannot see the file) + post-verify guard:
   Chrome silently accepts dangling paths as 0-byte entries, so a
   non-zero attached size is required for success.
"""

import pytest

from app.domain.models.event import ToolEvent, ToolStatus
from app.domain.models.tool_result import ToolResult
from app.domain.services.agent_task_runner import AgentTaskRunner
from app.infrastructure.external.browser.browser_use_browser import (
    BrowserUseBrowser,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSandbox:
    def __init__(self, console=None):
        self.console = console or []

    async def view_shell(self, session_id, console=False):
        return ToolResult(success=True, data={"console": self.console})


def _runner_skeleton(sandbox=None):
    if sandbox is None:
        sandbox = _FakeSandbox()
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._agent_id = "test-agent"
    runner._session_id = "sess-test"
    runner._file_old_by_call = {}
    runner._synced_paths = []
    runner._sandbox = sandbox
    return runner


def _tool_event(tool_name, function_name, args, result, status=ToolStatus.CALLED):
    return ToolEvent(
        tool_call_id="call-1",
        tool_name=tool_name,
        function_name=function_name,
        function_args=args,
        status=status,
        function_result=result,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Shell display: failed call shows the real error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shell_missing_id_shows_error_message():
    """shell_exec without id → the panel shows the actionable error, never
    the opaque '(No Console)' placeholder."""
    runner = _runner_skeleton()
    error = ToolResult(
        success=False,
        message=(
            "Invalid arguments for shell_exec: ShellToolkit.shell_exec() "
            "missing 1 required positional argument: 'id'. Arguments you "
            "provided: [command, exec_dir]."
        ),
    )
    event = _tool_event("shell", "shell_exec",
                       {"command": "ls", "exec_dir": "/tmp"}, error)
    await runner._handle_tool_event(event)
    assert event.tool_content is not None
    console = event.tool_content.console
    assert "Invalid arguments for shell_exec" in console
    assert "(No Console)" not in console


@pytest.mark.asyncio
async def test_shell_success_shows_console():
    runner = _runner_skeleton(
        _FakeSandbox(console=[{"ps1": "$", "command": "ls", "output": "file.txt"}])
    )
    event = _tool_event("shell", "shell_exec",
                       {"id": "s1", "command": "ls", "exec_dir": "/tmp"},
                       ToolResult(success=True, message="Command executed"))
    await runner._handle_tool_event(event)
    assert event.tool_content.console == [
        {"ps1": "$", "command": "ls", "output": "file.txt"}
    ]


@pytest.mark.asyncio
async def test_shell_success_without_id_and_without_error_falls_back():
    """A success with no id and no error message (should not happen) keeps
    the placeholder instead of crashing."""
    runner = _runner_skeleton()
    event = _tool_event("shell", "shell_exec",
                       {"command": "ls"}, ToolResult(success=True))
    await runner._handle_tool_event(event)
    assert event.tool_content.console == "(No Console)"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Search display: failed search must not blank the panel
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_failed_returns_empty_results_not_crash():
    runner = _runner_skeleton()
    event = _tool_event("search", "info_search_web",
                       {"query": "x"},
                       ToolResult(success=False, message="Search engine unreachable"))
    await runner._handle_tool_event(event)  # must not raise
    assert event.tool_content is not None
    assert event.tool_content.results == []


@pytest.mark.asyncio
async def test_search_success_returns_results():
    from app.domain.models.search import SearchResults, SearchResultItem

    runner = _runner_skeleton()
    data = SearchResults(
        query="persib",
        results=[SearchResultItem(
            title="Persib", link="https://persib.example", snippet="snippet")],
    )
    event = _tool_event("search", "info_search_web",
                       {"query": "persib"},
                       ToolResult(success=True, data=data))
    await runner._handle_tool_event(event)
    assert len(event.tool_content.results) == 1
    assert event.tool_content.results[0].title == "Persib"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Browser action tools return rich results
# ─────────────────────────────────────────────────────────────────────────────

class _FakePage:
    """CDP page double: canned url / evaluate / press."""

    def __init__(self, evaluate_results=None, url="http://test/index.html"):
        self.url = url
        self.evaluate_results = evaluate_results or {}
        self.pressed = []

    async def get_url(self):
        return self.url

    async def press(self, key):
        self.pressed.append(key)

    async def evaluate(self, script, *args):
        if isinstance(script, str) and script in self.evaluate_results:
            return self.evaluate_results[script]
        # default: scroll probe
        return (
            '{"scroll_y": 1080, "page_height": 4200, "viewport": 1080, '
            '"max_scroll": 3120}'
        )


def _browser_skeleton(page):
    b = BrowserUseBrowser.__new__(BrowserUseBrowser)
    b._page = page

    async def _get_current_page():
        return page

    async def _wait_for_dom_settle(timeout=0.6):
        return None

    async def _dispatch_mouse_event(*a, **k):
        return None

    b._get_current_page = _get_current_page
    b._wait_for_dom_settle = _wait_for_dom_settle
    b._dispatch_mouse_event = _dispatch_mouse_event
    return b


@pytest.mark.asyncio
async def test_scroll_down_reports_position():
    b = _browser_skeleton(_FakePage())
    result = await b.scroll_down()
    assert result.success
    assert result.message is not None
    assert "y=1080" in result.message
    assert "more content below" in result.message
    assert result.data["scroll_y"] == 1080
    assert result.data["direction"] == "down"


@pytest.mark.asyncio
async def test_scroll_to_top_reports_top():
    b = _browser_skeleton(_FakePage())
    result = await b.scroll_up(to_top=True)
    assert result.success
    assert result.data["direction"] == "top"
    assert "Scrolled top" in result.message


@pytest.mark.asyncio
async def test_press_key_returns_message_and_data():
    page = _FakePage()
    b = _browser_skeleton(page)
    result = await b.press_key("Tab")
    assert result.success
    assert "Key 'Tab' pressed" in result.message
    assert result.data["key"] == "Tab"
    assert result.data["page_changed"] is False
    assert page.pressed == ["Tab"]


@pytest.mark.asyncio
async def test_press_key_navigation_observed():
    class _NavPage(_FakePage):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def get_url(self):
            self.calls += 1
            return "http://test/index.html" if self.calls == 1 else "http://test/next.html"

    b = _browser_skeleton(_NavPage())

    async def _observe_page_state(session, include_content):
        return {"url": "http://test/next.html", "title": "Next"}

    async def _ensure_session():
        return object()

    b._observe_page_state = _observe_page_state
    b._ensure_session = _ensure_session
    result = await b.press_key("Enter")
    assert result.success
    assert "page navigated to http://test/next.html" in result.message
    assert result.data["page_changed"] is True


@pytest.mark.asyncio
async def test_move_mouse_returns_message():
    b = _browser_skeleton(_FakePage())
    result = await b.move_mouse(100, 150)
    assert result.success
    assert "(100, 150)" in result.message
    assert result.data == {"x": 100, "y": 150}


@pytest.mark.asyncio
async def test_input_without_enter_reports_typed_text():
    page = _FakePage()

    class _Element:
        async def evaluate(self, script, *args):
            if isinstance(script, str) and script.startswith("(text)"):
                return args[0] if args else ""
            return None

    class _Session:
        async def get_dom_element_by_index(self, index):
            return type("Node", (), {"backend_node_id": 42})()

    async def _get_element(backend_node_id):
        return _Element()

    page.get_element = _get_element
    b = _browser_skeleton(page)

    async def _ensure_session():
        return _Session()

    async def _ensure_dom_document():
        return None

    b._ensure_session = _ensure_session
    b._ensure_dom_document = _ensure_dom_document
    b._last_elements_signature = None

    result = await b.input("hello world", press_enter=False, index=7)
    assert result.success
    assert "hello world" in result.message
    assert "element 7" in result.message
    assert result.data == {"index": 7, "value": "hello world", "press_enter": False}


# ─────────────────────────────────────────────────────────────────────────────
# 4. upload_file: provider-agnostic + 0-byte guard
# ─────────────────────────────────────────────────────────────────────────────

def _upload_browser(attached):
    """Build a BrowserUseBrowser skeleton whose page hosts a file input that
    reports `attached` ({n, name, size}) after DOM.setFileInputFiles."""

    class _Element:
        async def evaluate(self, script, *args):
            if "tagName" in script:
                return '{"tag":"INPUT","type":"file"}'
            if "files.length" in script:
                import json as _json
                return _json.dumps(attached)
            return None

    class _Node:
        backend_node_id = 42

    class _Session:
        async def get_dom_element_by_index(self, index):
            return _Node()

    class _Page:
        async def get_element(self, backend_node_id):
            return _Element()

    class _Cdp:
        class send:
            class DOM:
                @staticmethod
                async def setFileInputFiles(params=None, session_id=None):
                    return None

    class _CdpSession:
        cdp_client = _Cdp
        session_id = "sess"

    page = _Page()
    b = _browser_skeleton(page)

    async def _ensure_session():
        return _Session()

    async def _ensure_dom_document():
        return None

    async def _get_cdp_session():
        return _CdpSession()

    b._ensure_session = _ensure_session
    b._ensure_dom_document = _ensure_dom_document
    b._get_cdp_session = _get_cdp_session
    return b


@pytest.mark.asyncio
async def test_upload_file_success_reports_size():
    b = _upload_browser({"n": 1, "name": "upload_ok.txt", "size": 25})
    result = await b.upload_file(3, "/home/user/upload_ok.txt")
    assert result.success
    assert "25 bytes" in result.message
    assert result.data["file_name"] == "upload_ok.txt"
    assert result.data["size"] == 25


@pytest.mark.asyncio
async def test_upload_file_dangling_path_rejected():
    """Chrome silently accepts a missing path as a 0-byte entry on BOTH
    providers (verified live) — the guard must reject it visibly."""
    b = _upload_browser({"n": 1, "name": "missing.bin", "size": 0})
    result = await b.upload_file(3, "/home/user/missing.bin")
    assert not result.success
    assert "did not attach" in result.message
    assert "ls -la" in result.message


@pytest.mark.asyncio
async def test_upload_file_empty_files_rejected():
    b = _upload_browser({"n": 0, "name": None, "size": 0})
    result = await b.upload_file(3, "/home/user/whatever.txt")
    assert not result.success
    assert "did not attach" in result.message


@pytest.mark.asyncio
async def test_upload_file_cdp_error_friendly():
    class _Cdp:
        class send:
            class DOM:
                @staticmethod
                async def setFileInputFiles(params=None, session_id=None):
                    raise RuntimeError("boom: could not read file")

    b = _upload_browser({"n": 0, "name": None, "size": 0})
    b._get_cdp_session = _make_cdp_session(_Cdp)
    result = await b.upload_file(3, "/home/user/gone.txt")
    assert not result.success
    assert "File not found or unreadable" in result.message
    assert "ls ~" in result.message


def _make_cdp_session(cdp_cls):
    class _CdpSession:
        cdp_client = cdp_cls
        session_id = "sess"

    async def _get():
        return _CdpSession()

    return _get
