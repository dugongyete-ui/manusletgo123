"""Tests for the native OpenCode-inspired policy and event adapter."""

import json

import pytest

from app.core.config import get_settings
from app.domain.models.event import (
    DoneEvent,
    ErrorEvent,
    MessageChunkEvent,
    PlanEvent,
    ToolEvent,
    ToolStatus,
    WaitEvent,
)
from app.domain.services.agents.opencode_adapter import (
    OpenCodeEventNormalizer,
    is_read_only_tool,
    normalize_opencode_event,
    readonly_tool_message,
)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_plan_mode_allowlist_is_conservative(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "plan")
    get_settings.cache_clear()
    assert is_read_only_tool("file_read")
    assert is_read_only_tool("browser_view")
    assert not is_read_only_tool("file_write")
    assert not is_read_only_tool("shell_exec")
    assert not is_read_only_tool("browser_click")


def test_denied_mutation_is_an_actionable_tool_result(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "plan")
    get_settings.cache_clear()
    message = readonly_tool_message("file_write", "call-1")
    payload = json.loads(message.content)
    assert payload["success"] is False
    assert payload["error"]["code"] == "PERMISSION_DENIED"
    assert "plan mode" in payload["error"]["message"]
    assert message.artifact.success is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"type": "session.idle"}, DoneEvent),
        ({"type": "permission.asked"}, WaitEvent),
        ({"type": "session.error", "properties": {"message": "failed"}}, ErrorEvent),
        (
            {
                "type": "message.part.updated",
                "properties": {"part": {"type": "text", "text": "hello", "done": True}},
            },
            MessageChunkEvent,
        ),
        (
            {
                "type": "tool.execute.before",
                "properties": {
                    "tool": "manus-shell",
                    "callID": "c1",
                    "args": {"command": "pwd"},
                },
            },
            ToolEvent,
        ),
        (
            {
                "type": "plan.updated",
                "properties": {"plan": {"title": "Inspect", "goal": "Inspect safely"}},
            },
            PlanEvent,
        ),
    ],
)
def test_opencode_events_normalize_to_existing_contract(raw, expected):
    event = normalize_opencode_event(raw)
    assert isinstance(event, expected)


def test_tool_event_preserves_call_and_redacts_sensitive_args():
    event = OpenCodeEventNormalizer.normalize(
        {
            "type": "tool.execute.after",
            "properties": {
                "tool": "manus-shell",
                "callID": "c2",
                "args": {"token": "do-not-store"},
                "result": {"ok": True},
            },
        }
    )
    assert isinstance(event, ToolEvent)
    assert event.status == ToolStatus.CALLED
    assert event.tool_call_id == "c2"
    assert event.function_args["token"] == "[REDACTED]"
    assert event.function_result == {"ok": True}


def test_unknown_opencode_event_is_ignored():
    assert normalize_opencode_event({"type": "server.heartbeat"}) is None