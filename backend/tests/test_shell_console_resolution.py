"""Regression tests: id-less shell_exec console rendering (Task 34).

Covers the 2026-08-30 "undefined undefined" bug in the live session
bccb86b6fab34d52:

    Menjalankan perintah
    npx tsc --noEmit
    undefined undefined
    undefined
    ... (12x)

Root cause chain:
1. Since shell_exec's ``id`` became optional (commit 82b2619), the agent
   rightfully omits it — the toolkit auto-creates a session uuid.
2. ``AgentTaskRunner._handle_tool_event`` shell branch only looked at
   ``function_args["id"]``; without it, EVERY successful call was stored as
   the literal STRING "(No Console)" in tool_content.console.
3. The frontend ShellToolView iterates console entries as records
   (``e.ps1``, ``e.command``, ``e.output``) — iterating a 12-char string
   per-character produced 12 lines of "undefined undefined / undefined".

Fix under test:
- The runner now falls back to ``function_result.data.session_id`` (the
  auto-created session id echoed by the sandbox) and stores real console
  records plus the resolved ``session_id`` on ShellToolContent.
- The frontend renders string payloads as text (tested indirectly via the
  contract: console is either a list of records or a short string).
"""

import pytest

from app.domain.models.event import ToolEvent, ToolStatus
from app.domain.models.tool_result import ToolResult
from app.domain.services.agent_task_runner import AgentTaskRunner


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSandbox:
    """Records requested session ids; returns canned console records."""

    def __init__(self, console=None, sessions=None):
        self.console = console if console is not None else [
            {"ps1": "$", "command": "npx tsc --noEmit", "output": "ok"}
        ]
        # sessions that "exist" — others raise like the sandbox API does
        self.sessions = sessions if sessions is not None else {"*": True}
        self.requested_ids = []

    async def view_shell(self, session_id, console=False):
        self.requested_ids.append(session_id)
        if session_id not in self.sessions and "*" not in self.sessions:
            return ToolResult(success=False, message=f"Session {session_id} not found")
        return ToolResult(success=True, data={"console": self.console})


def _runner_skeleton(sandbox):
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._agent_id = "test-agent"
    runner._session_id = "sess-test"
    runner._file_old_by_call = {}
    runner._synced_paths = []
    runner._sandbox = sandbox
    return runner


def _tool_event(args, result, status=ToolStatus.CALLED):
    return ToolEvent(
        tool_call_id="call-1",
        tool_name="shell",
        function_name="shell_exec",
        function_args=args,
        status=status,
        function_result=result,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Session-id resolution
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_id_less_shell_exec_resolves_session_from_result():
    """shell_exec WITHOUT id but WITH result.data.session_id must fetch the
    real console records (the exact live-session bug: 20+ events stored the
    string "(No Console)" while the commands had run fine)."""
    sandbox = _FakeSandbox()
    runner = _runner_skeleton(sandbox)
    auto_id = "f28c5aae-b176-4afe-b089-55d3f691a554"
    event = _tool_event(
        {"command": "npx tsc --noEmit"},
        ToolResult(success=True, message="Command executed",
                   data={"session_id": auto_id, "command": "npx tsc --noEmit",
                         "status": "completed", "returncode": 0, "output": ""}),
    )
    await runner._handle_tool_event(event)

    # The auto-created session id was used to fetch the console
    assert sandbox.requested_ids == [auto_id]
    # Real console records — never the "(No Console)" string
    assert isinstance(event.tool_content.console, list)
    assert event.tool_content.console[0]["command"] == "npx tsc --noEmit"
    assert "(No Console)" not in str(event.tool_content.console)
    # The resolved id is echoed so the frontend can poll live output
    assert event.tool_content.session_id == auto_id


@pytest.mark.asyncio
async def test_explicit_id_argument_wins_over_result_session_id():
    """When the agent passed an explicit id (session reuse), that id is used
    for the console view — behaviour unchanged from before."""
    sandbox = _FakeSandbox()
    runner = _runner_skeleton(sandbox)
    event = _tool_event(
        {"id": "explicit-session", "command": "ls"},
        ToolResult(success=True, data={"session_id": "other-session",
                                       "command": "ls", "status": "completed"}),
    )
    await runner._handle_tool_event(event)
    assert sandbox.requested_ids == ["explicit-session"]
    assert event.tool_content.session_id == "explicit-session"


@pytest.mark.asyncio
async def test_view_shell_failure_yields_empty_console_not_crash():
    """A resolved session id whose view fails (e.g. evicted session) must
    produce an empty console list, not an exception / not a string."""
    sandbox = _FakeSandbox(sessions=set())  # no session exists
    runner = _runner_skeleton(sandbox)
    event = _tool_event(
        {"command": "ls"},
        ToolResult(success=True, data={"session_id": "gone-session",
                                       "command": "ls", "status": "completed"}),
    )
    await runner._handle_tool_event(event)  # must not raise
    assert event.tool_content.console == []
    assert event.tool_content.session_id == "gone-session"


@pytest.mark.asyncio
async def test_failed_call_without_id_still_shows_error_message():
    """A genuinely failed invocation (no id, no result session_id) keeps
    surfacing the actionable error message."""
    sandbox = _FakeSandbox()
    runner = _runner_skeleton(sandbox)
    event = _tool_event(
        {"command": "ls"},
        ToolResult(success=False, message="Invalid arguments: command required"),
    )
    await runner._handle_tool_event(event)
    assert sandbox.requested_ids == []  # nothing to view
    assert "Invalid arguments" in event.tool_content.console
    assert "(No Console)" not in event.tool_content.console


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prompt naturalness — no "Langkah [X]" templates / numbered narration
# ─────────────────────────────────────────────────────────────────────────────

def _system_prompt() -> str:
    from app.domain.services.prompts.system import get_system_prompt
    return get_system_prompt()


def test_system_prompt_has_no_langkah_template():
    """The rigid failure skeleton 'Langkah [X] belum berhasil…' made every
    failure message read identical — it must be gone."""
    prompt = _system_prompt()
    assert "Langkah [X]" not in prompt
    assert "Use this pattern" not in prompt


def test_system_prompt_forbids_numbered_step_labels():
    """Narration must not recite plan indices ('Langkah 1 selesai…') — the
    plan UI already numbers the steps."""
    prompt = _system_prompt()
    assert "numbered step labels" in prompt
    assert "Langkah 1 selesai" in prompt  # cited as a forbidden example


def test_execution_prompt_forbids_numbered_step_labels():
    from app.domain.services.prompts.execution import EXECUTION_SYSTEM_PROMPT
    assert "Langkah 1 selesai" in EXECUTION_SYSTEM_PROMPT
    assert "plan-step numbers" in EXECUTION_SYSTEM_PROMPT
