"""Tests — session history → provider format conversion."""

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
    """The existing provider (NVIDIA gateway) consumes history as-is
    (behaviour preserved)."""
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="halo"),
        AIMessage(content=""),
        HumanMessage(content="lanjut"),
        ToolMessage(content="hasil", tool_call_id="abc"),
    ]
    out = convert_history_for_provider("existing", messages)
    assert out == messages  # same objects, same order — passthrough


def test_empty_history_passthrough():
    assert convert_history_for_provider("existing", []) == []


def test_unknown_provider_name_also_passthrough():
    """Every provider name maps to passthrough — the strict-projection
    adapters (e.g. the removed Anthropic one) were deleted by decision."""
    messages = [HumanMessage(content=""), HumanMessage(content="halo")]
    out = convert_history_for_provider("something-else", messages)
    assert out == messages


def test_returned_list_is_a_copy():
    """Mutating the returned list must not affect the stored history."""
    messages = [HumanMessage(content="halo")]
    out = convert_history_for_provider("existing", messages)
    out.append(AIMessage(content="x"))
    assert len(messages) == 1
