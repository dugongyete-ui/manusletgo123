"""Unit tests for the content-narration emission in BaseAgent.execute().

Product direction (2026-08-28): models like MiniMax M3 "think out loud" in
the AIMessage content alongside tool calls. That narration used to be
discarded (chat went silent); it must now be emitted as an is_progress
MessageEvent BEFORE the round's tool events, so the user hears the intent
before the action executes.
"""

import pytest
from unittest.mock import AsyncMock

from langchain.messages import AIMessage

from app.domain.services.agents.execution import ExecutionAgent
from app.domain.models.event import MessageEvent, ErrorEvent, ToolEvent


def _make_agent() -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._user_request_words = None
    agent._silent_activities = []
    agent._silent_tool_count = 0
    agent._narration_assist_count = 0
    agent._narration_lang = "en"
    agent.toolkits = []
    return agent


def _narrated_round() -> AIMessage:
    return AIMessage(
        content="Saya akan memeriksa dulu konfigurasinya sebelum menulis skrip.",
        tool_calls=[
            {
                "name": "file_read",
                "args": {"path": "/tmp/x.conf"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )


@pytest.mark.asyncio
async def test_content_narration_emitted_before_tool_events():
    """AIMessage content + tool_calls → the narration is the FIRST event,
    flagged is_progress, BEFORE any tool event of that round."""
    agent = _make_agent()
    agent.ask = AsyncMock(return_value=_narrated_round())
    agent.ask_with_messages = AsyncMock(
        return_value=AIMessage(content='{"success": true, "result": "done"}')
    )

    events = [e async for e in agent.execute("do the thing")]

    assert len(events) >= 1
    first = events[0]
    assert isinstance(first, MessageEvent)
    assert first.is_progress is True
    assert "konfigurasi" in first.message
    # The tool round DID run (unknown tool → ErrorEvent, no crash) and the
    # final JSON arrives last as the step result.
    kinds = [type(e).__name__ for e in events]
    assert "ErrorEvent" in kinds  # file_read is unknown with empty toolkits
    last = events[-1]
    assert isinstance(last, MessageEvent)
    assert last.is_progress is False
    assert "success" in last.message


@pytest.mark.asyncio
async def test_no_narration_when_content_empty():
    """Tool-carrying rounds without content emit no progress event."""
    agent = _make_agent()
    agent.ask = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "file_read",
                    "args": {"path": "/tmp/x.conf"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )
    )
    agent.ask_with_messages = AsyncMock(
        return_value=AIMessage(content='{"success": true, "result": "done"}')
    )

    events = [e async for e in agent.execute("do the thing")]
    assert not any(
        isinstance(e, MessageEvent) and e.is_progress for e in events
    )


@pytest.mark.asyncio
async def test_json_content_not_emitted_as_narration():
    """Content that is the result JSON (models sometimes emit it alongside
    trailing tool calls) must not leak into the chat as a progress line."""
    agent = _make_agent()
    agent.ask = AsyncMock(
        return_value=AIMessage(
            content='{"success": true, "result": "premature"}',
            tool_calls=[
                {
                    "name": "file_read",
                    "args": {"path": "/tmp/x.conf"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )
    )
    agent.ask_with_messages = AsyncMock(
        return_value=AIMessage(content='{"success": true, "result": "done"}')
    )

    events = [e async for e in agent.execute("do the thing")]
    assert not any(
        isinstance(e, MessageEvent) and e.is_progress for e in events
    )


@pytest.mark.asyncio
async def test_progress_narration_passes_execution_handler_with_dedup():
    """_handle_execution_events: an is_progress narration flows through to
    the frontend, resets the keep-alive window, and a near-duplicate is
    suppressed."""
    from app.domain.models.plan import Step
    from app.domain.models.event import ToolStatus

    agent = _make_agent()
    step = Step(id="1", description="Uji")

    class _Stream:
        async def execute(self, content):
            yield MessageEvent(message="Mulai memeriksa sumber data utama.", is_progress=True)
            yield MessageEvent(message="Mulai memeriksa sumber data utama.", is_progress=True)
            yield MessageEvent(message="Sumber kedua mengonfirmasi angka pertama.", is_progress=True)

    agent.execute = _Stream().execute
    events = [e async for e in agent._handle_execution_events(step, "p")]

    narrations = [
        e.message for e in events if isinstance(e, MessageEvent) and e.is_progress
    ]
    # Near-duplicate suppressed; the two distinct lines survive.
    assert len(narrations) == 2
