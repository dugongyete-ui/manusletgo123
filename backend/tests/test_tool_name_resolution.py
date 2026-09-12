"""Unit tests for polluted tool-name resolution in BaseAgent.

Production incident (session 6a901cc0, task "Persib Bandung presentation"):
the LLM emitted a tool call whose NAME field carried junk from the model's
own serialization syntax — ``"browser_view\\n</parameter"`` — which made
``get_tool`` return None and surfaced "Unknown tool: browser_view
</parameter" in the user's chat.

These tests pin the three-stage resolution:
1. exact name,
2. normalized name (first line, junk stripped),
3. boundary-aware containment (registered name as a whole token).
"""

from app.domain.services.agents.base import BaseAgent
from app.domain.services.tools.message import MessageToolkit


def make_agent() -> BaseAgent:
    agent = BaseAgent.__new__(BaseAgent)
    agent.toolkits = [MessageToolkit()]
    return agent


def test_normalize_strips_xml_junk_after_newline():
    assert BaseAgent._normalize_tool_name("browser_view\n</parameter") == "browser_view"


def test_normalize_strips_surrounding_whitespace_and_quotes():
    assert BaseAgent._normalize_tool_name("  message_notify_user ") == "message_notify_user"
    assert BaseAgent._normalize_tool_name("'message_notify_user'") == "message_notify_user"


def test_normalize_cuts_inline_xml_fragment():
    assert BaseAgent._normalize_tool_name("message_notify_user</parameter>") == "message_notify_user"
    assert BaseAgent._normalize_tool_name("shell_exec`extra") == "shell_exec"


def test_normalize_exact_name_unchanged():
    assert BaseAgent._normalize_tool_name("browser_view") == "browser_view"


def test_get_tool_exact_match():
    agent = make_agent()
    tool = agent.get_tool("message_notify_user")
    assert tool is not None
    assert tool.name == "message_notify_user"


def test_get_tool_resolves_newline_junk():
    agent = make_agent()
    tool = agent.get_tool("message_notify_user\n</parameter")
    assert tool is not None
    assert tool.name == "message_notify_user"


def test_get_tool_resolves_inline_junk_via_containment():
    agent = make_agent()
    tool = agent.get_tool("message_notify_user (extra text)")
    assert tool is not None
    assert tool.name == "message_notify_user"


def test_get_tool_no_false_suffix_match():
    """A name that merely EXTENDS a registered name must not resolve to it —
    boundary check must reject "message_notify_user_v2"."""
    agent = make_agent()
    assert agent.get_tool("message_notify_user_v2") is None


def test_get_tool_no_false_prefix_match():
    """A name that merely CONTAINS a registered name as a fragment glued with
    an underscore must not resolve ("notify_user" inside
    "message_notify_user")."""
    agent = make_agent()
    assert agent.get_tool("notify_user") is None


def test_get_tool_unknown_returns_none():
    agent = make_agent()
    assert agent.get_tool("web_search") is None
    assert agent.get_tool("") is None
