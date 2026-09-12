"""Task 49 — fixes for issues found by the user's full tool matrix test
(session 97c0d154cdfc4a4b, share page).

Three production failures were reported by the live AI run:
1. task_delegate ALWAYS failed: "Agent <id>-nested-<x> not found" — the
   nested ExecutionAgent was given the REAL MongoAgentRepository, but its
   id is never persisted, so the first save_memory raised ValueError and
   delegation died before doing any work.
   Fix: nested agents get _TransientAgentRepository (in-memory dict, same
   protocol shape) — sub-agents are ephemeral by design.
2. browser_console_exec with `return document.title;` → "Illegal return
   statement" SyntaxError (console habits: top-level return is illegal in
   eval / bare expressions).
   Fix: both browser backends retry ONCE with the code wrapped as an
   async-function body, where return is legal and its value is the result.
3. browser_navigate to file:// died with a dead-end message; the model had
   no way to know the one-step recovery.
   Fix: the rejection now teaches the model to serve the directory with
   `python3 -m http.server` and browse http://localhost:8000/<file>.
"""

import pytest

from app.domain.models.memory import Memory
from app.domain.models.tool_result import ToolResult


# ── 1. task_delegate uses a transient repository ────────────────────────────

class _StrictRepo:
    """Behaves like MongoAgentRepository confronted with an unknown agent id
    (exactly how the production failure surfaced)."""

    async def save(self, agent):
        raise ValueError("not expected in this test")

    async def find_by_id(self, agent_id):
        return None

    async def add_memory(self, agent_id, name, memory):
        raise ValueError(f"Agent {agent_id} not found")

    async def get_memory(self, agent_id, name):
        raise ValueError(f"Agent {agent_id} not found")

    async def save_memory(self, agent_id, name, memory):
        raise ValueError(f"Agent {agent_id} not found")


@pytest.mark.asyncio
async def test_task_delegate_survives_memory_persistence(monkeypatch):
    """The nested agent must NEVER touch the parent's real repository: with
    the transient repo, save_memory inside execute() succeeds even though
    the nested agent id was never persisted anywhere."""
    import app.domain.services.agents.execution as execution_module
    from app.domain.services.tools.delegate import DelegateToolkit

    saved_repos = []

    class _FakeNested:
        def __init__(self, agent_id, agent_repository, tools):
            self.agent_id = agent_id
            self._repo = agent_repository
            self.max_iterations = None
            self.system_prompt = ""
            self.memory = Memory(messages=[])
            saved_repos.append(agent_repository)

        async def execute(self, request):
            # Persist memory mid-run like the real BaseAgent does — this is
            # the exact call that used to explode with "Agent ... not found".
            await self._repo.save_memory(self.agent_id, "executor", self.memory)
            from langchain.messages import AIMessage as LCAIMessage
            self.memory.messages.append(
                LCAIMessage(content="Subtask done: delegated_output.txt created.")
            )
            yield None

    monkeypatch.setattr(execution_module, "ExecutionAgent", _FakeNested)

    from app.domain.services.tools.base import Tool

    toolkit = DelegateToolkit(
        sandbox=None,
        browser=None,
        mcp_tool=None,
        search_engine=None,
        agent_id="parent-agent-1",
        agent_repository=_StrictRepo(),
        base_prompt="BASE",
    )
    # Wrap exactly like production does (strips `self` from the schema and
    # binds the toolkit instance).
    wrapped = Tool(toolkit.task_delegate, toolkit=toolkit)

    tool_message = await wrapped.ainvoke(
        {
            "id": "call-1",
            "name": "task_delegate",
            "type": "tool_call",
            "args": {
                "goal": "Buat file delegated_output.txt",
                "expected_output": "Laporan pembuatan file",
            },
        }
    )
    result = tool_message.artifact  # raw ToolResult

    assert result.success is True
    assert "delegated_output.txt" in result.message
    # The nested agent was NOT handed the strict (real-style) repository.
    assert len(saved_repos) == 1
    assert not isinstance(saved_repos[0], _StrictRepo)
    # …and its repository absorbs save_memory without raising (already
    # proven by result.success, but assert the transient type explicitly).
    from app.domain.services.tools.delegate import _TransientAgentRepository
    assert isinstance(saved_repos[0], _TransientAgentRepository)


@pytest.mark.asyncio
async def test_transient_repository_roundtrip():
    from app.domain.services.tools.delegate import _TransientAgentRepository

    repo = _TransientAgentRepository()
    # get_memory on an unknown name → fresh empty memory, never a raise.
    memory = await repo.get_memory("nested-1", "executor")
    assert memory.messages == []
    # save/add round-trip locally.
    m = Memory(messages=[])
    await repo.save_memory("nested-1", "executor", m)
    assert (await repo.get_memory("nested-1", "executor")) is m
    await repo.add_memory("nested-1", "planner", m)
    # No-ops stay no-ops.
    await repo.save(object())
    assert await repo.find_by_id("nested-1") is None


# ── 2. console_exec retries top-level `return` as a function body ──────────

@pytest.mark.asyncio
async def test_browser_use_console_exec_wraps_illegal_return():
    from app.infrastructure.external.browser.browser_use_browser import (
        BrowserUseBrowser,
    )

    browser = object.__new__(BrowserUseBrowser)

    class _Page:
        def __init__(self):
            self.eval_calls = []

        async def evaluate(self, js):
            self.eval_calls.append(js)
            if "__consoleLogs" in js:
                return "[]" if "JSON.stringify" in js else 0
            if self.eval_calls.count(js) == 1 and "return" in js and "async function" not in js:
                # First attempt with the raw code → the production error.
                raise Exception(
                    "JavaScript evaluation failed: {'text': 'Uncaught (in "
                    "promise) SyntaxError: Illegal return statement'}"
                )
            return "Example Domain"

    page = _Page()

    async def _get_page():
        return page

    async def _noop():
        return None

    async def _call_with_deadline(coro, timeout=None):
        return await coro

    browser._get_current_page = _get_page
    browser._ensure_console_capture = _noop
    browser._call_with_deadline = _call_with_deadline

    result = await browser.console_exec("return document.title;")
    assert result.success is True, result.message
    assert result.data["result"] == "Example Domain"
    # The retry actually wrapped the code in a function body.
    assert any("async function" in js for js in page.eval_calls)


@pytest.mark.asyncio
async def test_browser_use_console_exec_other_errors_not_retried():
    from app.infrastructure.external.browser.browser_use_browser import (
        BrowserUseBrowser,
    )

    browser = object.__new__(BrowserUseBrowser)

    class _Page:
        async def evaluate(self, js):
            if "__consoleLogs" in js:
                return "[]" if "JSON.stringify" in js else 0
            raise Exception("ReferenceError: undefinedVariable is not defined")

    async def _get_page():
        return page

    async def _noop():
        return None

    async def _call_with_deadline(coro, timeout=None):
        return await coro

    page = _Page()
    browser._get_current_page = _get_page
    browser._ensure_console_capture = _noop
    browser._call_with_deadline = _call_with_deadline

    result = await browser.console_exec("undefinedVariable;")
    assert result.success is False
    assert "ReferenceError" in result.message


@pytest.mark.asyncio
async def test_playwright_console_exec_wraps_illegal_return():
    from app.infrastructure.external.browser.playwright_browser import (
        PlaywrightBrowser,
    )

    browser = object.__new__(PlaywrightBrowser)
    attempts = []

    class _Page:
        async def evaluate(self, js):
            attempts.append(js)
            if len(attempts) == 1:
                raise Exception(
                    "SyntaxError: Illegal return statement"
                )
            return "Example Domain"

    browser.page = _Page()

    async def _noop():
        return None

    browser._ensure_page = _noop
    browser._ensure_console_capture = _noop

    result = await browser.console_exec("return document.title;")
    assert result.success is True, result.message
    assert result.data["result"] == "Example Domain"
    assert any("async" in js and "document.title" in js for js in attempts)


# ── 3. file:// rejection teaches the local-server recovery ─────────────────

def test_scheme_rejection_file_url_has_http_server_hint():
    from app.infrastructure.external.browser.browser_use_browser import (
        _scheme_rejection,
    )

    result = _scheme_rejection("file:///home/z/sandbox/users/x/test.html")
    assert result is not None
    assert result.success is False
    assert "python3 -m http.server" in result.message
    assert "http://localhost:8000/" in result.message


def test_scheme_rejection_other_schemes_unchanged():
    from app.infrastructure.external.browser.browser_use_browser import (
        _scheme_rejection,
    )

    for url in ("data:text/html,<h1>hi</h1>", "javascript:alert(1)"):
        result = _scheme_rejection(url)
        assert result is not None
        assert result.success is False
        assert "http.server" not in result.message

    assert _scheme_rejection("https://example.com") is None
