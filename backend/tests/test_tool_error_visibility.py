"""Regression tests: tool failures must be VISIBLE, not "(No Content)".

Live incident (session 66bb17b346fc4776, 2026-08-30): the model called
file_write WITHOUT the required ``file`` argument (content-only). The raw
``TypeError: FileToolkit.file_write() missing 1 required positional
argument: 'file'`` surfaced to the model as an opaque Python traceback, so
it retried the SAME broken call 4 times; the ToolEvent carried
function_result=null, and the UI rendered the tool pill as "(No Content)"
when the user clicked it.

Three-layer fix under test:
1. ``Tool.ainvoke`` converts TypeError/ValidationError argument mismatches
   into a failed ToolResult whose message lists provided vs. accepted
   arguments (actionable for the model, visible to the UI) — no retries.
2. ``BaseAgent.invoke_tool`` attaches a failed ToolResult artifact on the
   exhausted-retries path too, so EVERY tool error lands in the event.
3. ``AgentTaskRunner._handle_tool_event`` displays the real error message
   in the file tool_content instead of "(No Content)" — as display-only
   text that never masquerades as file content for artifact syncing.
"""

import json

import pytest

from app.domain.models.event import ToolEvent, ToolStatus
from app.domain.models.tool_result import ToolResult
from app.domain.services.agent_task_runner import AgentTaskRunner
from app.domain.services.agents.base import BaseAgent
from app.domain.services.tools.base import BaseToolkit
from app.domain.services.tools.file import FileToolkit


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSandbox:
    """Sandbox double with canned file_read results."""

    def __init__(self, files=None):
        self.files = files or {}

    async def file_read(self, path, **kwargs):
        if path in self.files:
            return ToolResult(success=True, data={"content": self.files[path]})
        return ToolResult(success=False, message=f"File not found: {path}")


def _runner_skeleton():
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._agent_id = "test-agent"
    runner._session_id = "sess-test"
    runner._file_old_by_call = {}
    runner._synced_paths = []
    return runner


def _file_tool_event(function_args, function_result, tool_call_id="call-1"):
    return ToolEvent(
        tool_call_id=tool_call_id,
        tool_name="file",
        function_name="file_write",
        function_args=function_args,
        status=ToolStatus.CALLED,
        function_result=function_result,
    )


class _CountingAgent(BaseAgent):
    """Minimal concrete agent exposing invoke_tool without __init__ deps."""

    def __init__(self, tool, max_retries=2, retry_interval=0):
        self._tool = tool
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    async def invoke_tool(self, tool, tool_call):
        return await super().invoke_tool(tool, tool_call)


class _ExplodingToolkit(BaseToolkit):
    """Toolkit whose tool raises on every invocation."""

    name: str = "boom"

    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    from langchain.tools import tool as _tool_dec

    @_tool_dec(parse_docstring=True)
    async def boom_explode(self, target: str) -> ToolResult:
        """Explode on purpose.

        Args:
            target: Something to explode at
        """
        raise self._exc
        # pragma: no cover


class _CallCountingTool:
    """Wraps a real Tool and counts _arun invocations."""

    def __init__(self, tool):
        self._tool = tool
        self.calls = 0
        self.name = tool.name
        self.args_schema = tool.args_schema

    async def ainvoke(self, input, config=None, **kwargs):
        self.calls += 1
        return await self._tool.ainvoke(input, config, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tool.ainvoke — argument mismatches become actionable failures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ainvoke_missing_required_arg_returns_actionable_failure():
    """file_write without `file` — the exact live incident call."""
    toolkit = FileToolkit(_FakeSandbox())
    tool = toolkit.get_tool("file_write")
    msg = await tool.ainvoke({
        "id": "call-1",
        "args": {"content": "print('halo')"},
    })

    assert msg.artifact is not None
    assert msg.artifact.success is False
    # The message names the missing parameter and lists accepted ones.
    assert "'file'" in msg.artifact.message
    assert "file (required)" in msg.artifact.message
    assert "content (required)" in msg.artifact.message
    assert "append (optional)" in msg.artifact.message
    # What the model actually sent is echoed back.
    assert "content" in msg.artifact.message
    # Wire content is the same JSON the model sees for other failures.
    payload = json.loads(msg.content)
    assert payload["success"] is False
    assert "file (required)" in payload["message"]


@pytest.mark.asyncio
async def test_ainvoke_unexpected_kwarg_returns_actionable_failure():
    """Extra bogus argument → same actionable treatment."""
    toolkit = FileToolkit(_FakeSandbox())
    tool = toolkit.get_tool("file_write")
    msg = await tool.ainvoke({
        "id": "call-2",
        "args": {"file": "/tmp/x.py", "content": "x", "command": "ls"},
    })

    assert msg.artifact.success is False
    assert "'command'" in msg.artifact.message
    assert "file (required)" in msg.artifact.message


@pytest.mark.asyncio
async def test_ainvoke_success_path_unaffected():
    """A good call still returns the real result as artifact."""
    sandbox = _FakeSandbox()
    toolkit = FileToolkit(sandbox)
    tool = toolkit.get_tool("file_write")

    async def fake_write(**kwargs):
        return ToolResult(
            success=True,
            message="File written successfully",
            data={"file": kwargs.get("file"), "bytes_written": 4},
        )

    sandbox.file_write = fake_write
    msg = await tool.ainvoke({
        "id": "call-3",
        "args": {"file": "/tmp/x.py", "content": "halo"},
    })

    assert msg.artifact.success is True
    assert msg.artifact.data["bytes_written"] == 4
    assert json.loads(msg.content)["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. invoke_tool — every failure path carries a ToolResult artifact
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_tool_arg_mismatch_is_not_retried():
    """TypeError (deterministic) must NOT burn the retry loop — one call."""
    toolkit = _ExplodingToolkit(TypeError("boom() missing 1 required positional argument: 'target'"))
    real_tool = toolkit.get_tool("boom_explode")
    counting = _CallCountingTool(real_tool)
    agent = _CountingAgent(counting)

    msg = await agent.invoke_tool(
        counting, {"id": "call-4", "name": "boom_explode", "args": {}}
    )

    assert counting.calls == 1
    assert msg.artifact is not None
    assert msg.artifact.success is False
    assert "target (required)" in msg.artifact.message


@pytest.mark.asyncio
async def test_invoke_tool_transient_error_artifact_after_retries():
    """Non-arg errors still retry, then return a ToolMessage WITH a failed
    ToolResult artifact — the event must never carry function_result=null."""
    toolkit = _ExplodingToolkit(RuntimeError("sandbox connection reset"))
    real_tool = toolkit.get_tool("boom_explode")
    counting = _CallCountingTool(real_tool)
    agent = _CountingAgent(counting, max_retries=2)

    msg = await agent.invoke_tool(
        counting,
        {"id": "call-5", "name": "boom_explode", "args": {"target": "/tmp"}},
    )

    # initial attempt + 2 retries
    assert counting.calls == 3
    assert msg.artifact is not None
    assert msg.artifact.success is False
    assert "sandbox connection reset" in msg.artifact.message
    payload = json.loads(msg.content)
    assert payload["success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. _handle_tool_event — the UI shows the real error, never "(No Content)"
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_tool_event_missing_file_arg_shows_error():
    """The exact live incident event: file_write without `file`, failed
    result → tool_content carries the error message, not "(No Content)"."""
    runner = _runner_skeleton()
    runner._sandbox = _FakeSandbox()

    async def _no_sync(path):
        raise AssertionError("must not sync a failed write")

    runner._sync_file_to_storage = _no_sync

    failure = ToolResult(
        success=False,
        message=(
            "Invalid arguments for file_write: missing 1 required positional "
            "argument: 'file'. Arguments you provided: [content]."
        ),
    )
    event = _file_tool_event({"content": "print('halo')"}, failure)

    await runner._handle_tool_event(event)

    assert event.tool_content is not None
    assert "missing 1 required positional argument" in event.tool_content.content
    assert event.tool_content.content != "(No Content)"


@pytest.mark.asyncio
async def test_handle_tool_event_failed_write_shows_error_not_blank():
    """file_write WITH `file` but failed (e.g. permission denied, file
    absent) → viewer shows the failure message instead of a blank pane."""
    runner = _runner_skeleton()
    runner._sandbox = _FakeSandbox()  # file does not exist → read fails

    synced = []
    runner._sync_file_to_storage = lambda path: (_ for _ in ()).throw(
        AssertionError("must not sync a failed write")
    )

    failure = ToolResult(success=False, message="Access denied (write): /etc/shadow")
    event = _file_tool_event({"file": "/etc/shadow", "content": "x"}, failure)

    await runner._handle_tool_event(event)

    assert "Access denied" in event.tool_content.content
    assert event.tool_content.content != "(No Content)"


@pytest.mark.asyncio
async def test_handle_tool_event_successful_write_still_syncs():
    """Success path regression: real content read-back → sync + attachment."""
    runner = _runner_skeleton()
    runner._sandbox = _FakeSandbox(files={"/tmp/halo.py": "print('halo')"})
    synced = []

    async def _sync(path, *, add_to_session=True):
        synced.append(path)
        return type("F", (), {"file_id": "f1", "filename": "halo.py"})()

    runner._sync_file_to_storage = _sync

    ok = ToolResult(success=True, message="File written successfully", data={"bytes_written": 13})
    event = _file_tool_event({"file": "/tmp/halo.py", "content": "print('halo')"}, ok)

    file_info = await runner._handle_tool_event(event)

    assert event.tool_content.content == "print('halo')"
    assert synced == ["/tmp/halo.py"]
    assert file_info is not None and file_info.filename == "halo.py"


@pytest.mark.asyncio
async def test_handle_tool_event_error_text_never_synced_as_content():
    """A failed write to an EXISTING file: the viewer shows the error, but
    artifact sync must still be driven by the real file on disk — never by
    the display-only error text."""
    runner = _runner_skeleton()
    # File exists with old content — write itself failed though.
    runner._sandbox = _FakeSandbox(files={"/tmp/old.txt": "OLD"})

    sync_calls = []

    async def _sync(path, *, add_to_session=True):
        sync_calls.append(path)
        return None

    runner._sync_file_to_storage = _sync

    failure = ToolResult(success=False, message="disk quota exceeded")
    event = _file_tool_event(
        {"file": "/tmp/old.txt", "content": "NEW"}, failure, tool_call_id="call-9"
    )

    file_info = await runner._handle_tool_event(event)

    # Real (stale) content was read back → sync happens for the real file,
    # and the failed write is NOT auto-attached as a deliverable.
    assert sync_calls == ["/tmp/old.txt"]
    assert file_info is None
    assert event.tool_content.content == "OLD"
