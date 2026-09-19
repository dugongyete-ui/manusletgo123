"""Tests — session history → provider format conversion."""

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.domain.services.agents.history_adapter import (
    convert_history_for_provider,
)


def test_default_provider_passthrough():
    """The existing provider consumes history as-is (behaviour preserved)."""
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="halo"),
        AIMessage(content=""),
        HumanMessage(content="lanjut"),
    ]
    out = convert_history_for_provider("existing", messages)
    assert out == messages  # same objects, same order — passthrough


def test_empty_history_passthrough():
    assert convert_history_for_provider("anthropic", []) == []


def test_anthropic_dangling_tool_message_dropped():
    """A ToolMessage without a preceding assistant tool_use is refused by
    the Anthropic API — the adapter must drop it."""
    messages = [
        HumanMessage(content="jalankan"),
        ToolMessage(content="hasil", tool_call_id="abc"),
        AIMessage(content="selesai"),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert all(getattr(m, "type", "") != "tool" for m in out)
    assert len(out) == 2


def test_anthropic_tool_adjacency_preserved():
    """A valid assistant(tool_calls) → ToolMessage pair stays intact."""
    messages = [
        HumanMessage(content="jalankan shell"),
        AIMessage(
            content="",
            tool_calls=[{"name": "shell_exec", "args": {"command": "ls"}, "id": "t1"}],
        ),
        ToolMessage(content="file.txt", tool_call_id="t1"),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert len(out) == 3
    assert out[2].tool_call_id == "t1"


def test_anthropic_empty_messages_dropped():
    messages = [
        HumanMessage(content=""),
        AIMessage(content="   "),
        HumanMessage(content="pesan nyata"),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert len(out) == 1
    assert out[0].content == "pesan nyata"


def test_anthropic_consecutive_same_role_merged():
    messages = [
        HumanMessage(content="bagian satu"),
        HumanMessage(content="bagian dua"),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert len(out) == 1
    assert "bagian satu" in out[0].content and "bagian dua" in out[0].content


def test_anthropic_system_and_turns_kept():
    messages = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="halo"),
        AIMessage(content="hai!"),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert [getattr(m, "type", "") for m in out] == ["system", "human", "ai"]


def test_multimodal_content_projected_not_crashing():
    """List-style (multimodal) content must not break the sanitizer."""
    messages = [
        HumanMessage(content=[{"type": "text", "text": "lihat gambar"}]),
        AIMessage(content=""),
    ]
    out = convert_history_for_provider("anthropic", messages)
    assert len(out) == 1
