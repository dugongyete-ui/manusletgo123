"""Regression: raw Qwen-style tool_call wire residue must never reach the
user as message text.

Live incident (sessions e6690289 / b00448): the streaming summarize
emitted an EMPTY tool_call residue block as the whole answer; the
old stripper only knew <function=..>, so the TAGS counted as prose, the
empty-text guard passed, and the final bubble shipped with no summary.
"""
from app.domain.services.agents.base import _strip_function_syntax

OPEN = chr(60) + "tool_" + "call" + chr(62)
CLOSE = chr(60) + "/" + "tool_" + "call" + chr(62)


def test_empty_residue_block_strips_to_nothing():
    assert _strip_function_syntax(OPEN + "\n\n" + CLOSE) == ""


def test_prose_survives_residue():
    raw = "Ringkasan benar.\n" + OPEN + "\n\n" + CLOSE
    assert _strip_function_syntax(raw) == "Ringkasan benar."


def test_full_tool_call_json_block_stripped():
    raw = OPEN + '\n{"name": "message_notify_user", "arguments": {}}\n' + CLOSE
    assert _strip_function_syntax(raw) == ""


def test_unclosed_trailing_tag_stripped():
    assert _strip_function_syntax("teks " + OPEN + " terpotong") == "teks"


def test_plain_prose_untouched():
    assert _strip_function_syntax("Prose only") == "Prose only"


def test_legacy_function_block_still_stripped():
    assert _strip_function_syntax("<function=x>hi</function> selesai") == "selesai"


def test_guard_sees_wire_only_as_empty():
    """The summarize empty-prose guard relies on strip() + .strip() being
    empty for wire-only output — the exact condition that failed live."""
    wire_only = OPEN + "\n\n" + CLOSE
    assert _strip_function_syntax(wire_only).strip() == ""
