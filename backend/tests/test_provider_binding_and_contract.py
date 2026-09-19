"""Tests — provider binding guard + event-contract & no-CLI guarantees.

Acceptance criteria covered here:
- ``response_format`` never reaches the Anthropic adapter (SDK would 400);
- the OpenAI-compatible path keeps receiving it (regression guard);
- no provider spawns an interactive CLI (e.g. ``claude``) per request;
- the SSE event contract is untouched by the provider seam (the provider
  only swaps the model layer — events keep flowing through the same
  AgentEvent union the frontend consumes).
"""

import inspect

import pytest

from app.core.config import get_settings
from app.domain.services.agents.base import (
    _provider_bind_kwargs,
    _provider_history,
)
from app.domain.services.agents.provider_factory import (
    get_agent_provider,
    reset_agent_provider_cache,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_agent_provider_cache()
    get_settings.cache_clear()
    yield
    reset_agent_provider_cache()
    get_settings.cache_clear()


def test_bind_kwargs_openai_keeps_response_format(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "existing")
    reset_agent_provider_cache()
    kwargs = _provider_bind_kwargs({"type": "json"}, "auto")
    assert kwargs == {"response_format": {"type": "json"}, "tool_choice": "auto"}


def test_bind_kwargs_anthropic_drops_response_format(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    reset_agent_provider_cache()
    kwargs = _provider_bind_kwargs({"type": "json"}, "auto")
    assert "response_format" not in kwargs
    assert kwargs["tool_choice"] == "auto"


def test_bind_kwargs_none_values_dropped(monkeypatch):
    reset_agent_provider_cache()
    assert _provider_bind_kwargs(None, None) == {}


def test_history_projection_anthropic(monkeypatch):
    from langchain_core.messages import HumanMessage

    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    reset_agent_provider_cache()
    out = _provider_history([
        HumanMessage(content=""),
        HumanMessage(content="halo"),
    ])
    assert len(out) == 1  # empty message dropped for anthropic


def test_history_projection_default_passthrough(monkeypatch):
    from langchain_core.messages import HumanMessage

    reset_agent_provider_cache()
    messages = [HumanMessage(content="x")]
    out = _provider_history(messages)
    assert out == messages


def test_no_cli_subprocess_in_providers():
    """No adapter may launch the interactive Claude Code CLI (or any CLI) as
    a per-request runtime — server-side APIs only. Checked via AST imports,
    so documentation mentions do not false-positive."""
    import ast

    import app.domain.services.agents.providers as providers_mod

    tree = ast.parse(inspect.getsource(providers_mod))
    imported_names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    for forbidden in ("claude_agent_sdk", "subprocess", "asyncio.subprocess"):
        assert not any(
            forbidden == name or name.startswith(forbidden + ".")
            for name in imported_names
        ), f"forbidden import in providers.py: {forbidden}"


def test_event_contract_untouched_by_provider_seam():
    """The provider seam must not alter the AgentEvent union the frontend
    consumes — import the union and assert the full expected set."""
    from app.domain.models.event import AgentEvent
    import typing

    names = {
        t.__name__ if hasattr(t, "__name__") else str(t)
        for t in typing.get_args(AgentEvent)
    }
    assert names == {
        "ErrorEvent", "PlanEvent", "ToolEvent", "StepEvent",
        "MessageEvent", "MessageChunkEvent", "ValidationEvent",
        "KnowledgeEvent", "DoneEvent", "TitleEvent", "WaitEvent",
    }


def test_no_api_key_in_provider_module_logs(monkeypatch, caplog):
    """Selecting the anthropic provider must never log the API key."""
    import logging

    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-never-log")
    with caplog.at_level(logging.DEBUG, logger="app.domain.services.agents.provider_factory"):
        reset_agent_provider_cache()
        get_agent_provider()
    assert "sk-ant-secret-never-log" not in caplog.text
