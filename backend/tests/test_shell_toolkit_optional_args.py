"""Regression tests: shell_exec frictionless arguments.

Live incident (session cadb430f545a482e, 2026-08-30, Replit): the model
omitted ``id`` or ``exec_dir`` on 5 of 59 action rounds — each call died with
``TypeError: missing 1 required positional argument`` and forced a repair
round. Both arguments are bookkeeping the tool can derive itself:

* ``id``  — an opaque session handle; a fresh uuid works whenever the model
  does not intend to reuse/wait on a specific session.
* ``exec_dir`` — the sandbox service already defaults to the home directory
  when it receives None (sandbox/app/services/shell.py) and E2B does the
  same ("/home/user").

Under test: the toolkit signature now makes both optional, auto-generates
``id`` when absent, and passes ``exec_dir`` through as-is (None allowed).
"""

import pytest

from app.domain.models.tool_result import ToolResult
from app.domain.services.tools.shell import ShellToolkit


class _RecordingSandbox:
    """Sandbox double that records every exec_command call."""

    def __init__(self):
        self.calls = []

    async def exec_command(self, session_id, exec_dir, command):
        self.calls.append((session_id, exec_dir, command))
        return ToolResult(success=True, message="Command executed")


def _toolkit():
    tk = ShellToolkit(_RecordingSandbox())
    # Resolve the langchain tool wrapper bound to this toolkit instance.
    return tk, next(t for t in tk.tools if t.name == "shell_exec")


@pytest.mark.asyncio
async def test_command_only_generates_session_and_passes_none_dir():
    """The exact failing shape from the incident: model sends ONLY command."""
    tk, tool = _toolkit()
    result = await tool.ainvoke({"args": {"command": "ls -la"}, "id": "call-1"})
    assert '"success":true' in result.content
    session_id, exec_dir, command = tk.sandbox.calls[0]
    assert command == "ls -la"
    assert session_id  # auto-generated, non-empty
    assert len(session_id) == 36  # uuid4 string
    assert exec_dir is None  # server side defaults to home


@pytest.mark.asyncio
async def test_command_and_dir_without_id():
    """Model supplies command + exec_dir but forgets id (event 113 shape)."""
    tk, tool = _toolkit()
    await tool.ainvoke({
        "args": {"command": "pwd", "exec_dir": "/home/runner/users/u1"},
        "id": "call-2",
    })
    session_id, exec_dir, command = tk.sandbox.calls[0]
    assert command == "pwd"
    assert exec_dir == "/home/runner/users/u1"
    assert len(session_id) == 36


@pytest.mark.asyncio
async def test_command_and_id_without_dir():
    """Model supplies command + id but forgets exec_dir (event 97 shape)."""
    tk, tool = _toolkit()
    await tool.ainvoke({
        "args": {"command": "node -v", "id": "42"},
        "id": "call-3",
    })
    session_id, exec_dir, command = tk.sandbox.calls[0]
    assert session_id == "42"  # explicit id honoured
    assert command == "node -v"
    assert exec_dir is None


@pytest.mark.asyncio
async def test_all_args_unchanged():
    """Full explicit call keeps working exactly as before."""
    tk, tool = _toolkit()
    await tool.ainvoke({
        "args": {
            "command": "npm install",
            "id": "36",
            "exec_dir": "/home/runner/users/u1/astra-ai",
        },
        "id": "call-4",
    })
    assert tk.sandbox.calls[0] == (
        "36", "/home/runner/users/u1/astra-ai", "npm install",
    )


def test_signature_hint_marks_only_command_required():
    """The actionable error hint must now show id/exec_dir as optional —
    the model reads this when repairing a call."""
    tk, tool = _toolkit()
    hint = tool._signature_hint()
    assert "command (required)" in hint
    assert "id (optional)" in hint
    assert "exec_dir (optional)" in hint
