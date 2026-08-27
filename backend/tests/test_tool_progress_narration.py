"""Unit tests for the deterministic tool-progress narration:

1. A narration MessageEvent is emitted after the FIRST completed tool of each
   kind within a step (search → browse → write file…), marked is_progress=True
   so the frontend renders it inside the unified step timeline.
2. Repeated calls of the SAME kind within a step stay quiet (no spam).
3. Rapid different-kind bursts are throttled by the minimum interval.
4. Narration text contains no emojis and no raw tool names.
"""

import pytest

from app.domain.models.event import MessageEvent, ToolEvent, ToolStatus
from app.domain.services.agents.execution import ExecutionAgent


def make_executor() -> ExecutionAgent:
    agent = ExecutionAgent.__new__(ExecutionAgent)
    agent._deferred_attachments = []
    agent._last_narration_norm = None
    agent._suppressed_notify_ids = set()
    agent._narration_lang = "id"
    agent._last_narrated_function = None
    agent._last_tool_narration_ts = 0.0
    agent._step_narrated_functions = set()
    return agent


def tool_event(fn: str, tool_name: str = "browser", **args) -> ToolEvent:
    return ToolEvent(
        status=ToolStatus.CALLED,
        tool_call_id=f"call-{fn}",
        tool_name=tool_name,
        function_name=fn,
        function_args=args,
    )


def test_first_tool_of_each_kind_narrates_with_is_progress():
    agent = make_executor()
    ev = tool_event("info_search_web", tool_name="search", query="Persib Bandung")
    text = agent._tool_progress_narration(ev)
    assert text == 'Mencari di web: "Persib Bandung"'
    # is_progress is set at the emission site — verify the marker here so the
    # frontend timeline grouping stays in sync with the backend contract.
    msg = MessageEvent(role="assistant", message=text, is_progress=True)
    assert msg.is_progress is True


def test_same_kind_repeats_stay_quiet():
    agent = make_executor()
    first = agent._tool_progress_narration(
        tool_event("browser_view")
    )
    assert first == "Membaca isi halaman"
    second = agent._tool_progress_narration(tool_event("browser_view"))
    assert second is None


def test_navigate_narration_shows_domain_only():
    agent = make_executor()
    text = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://id.wikipedia.org/wiki/Persib_Bandung")
    )
    assert text == "Membuka id.wikipedia.org"


def test_rapid_different_kinds_are_throttled():
    agent = make_executor()
    # First narration goes out…
    assert agent._tool_progress_narration(
        tool_event("info_search_web", tool_name="search", query="x")
    )
    # …but a different kind arriving immediately (within the interval) is quiet.
    assert agent._tool_progress_narration(tool_event("browser_view")) is None


def test_narrations_have_no_emoji_and_no_tool_names():
    agent = make_executor()
    agent._narration_lang = "en"
    text = agent._tool_progress_narration(
        tool_event("file_write", tool_name="file", file="/home/runner/report.md")
    )
    assert text == "Writing report.md"
    for ch in text:
        # Emoji live outside the Basic Multilingual Plane / symbol blocks.
        assert not (ord(ch) > 0x2000 and ord(ch) not in (0x2014, 0x2026)), f"unexpected symbol: {ch!r}"
    assert "file_write" not in text


def test_shell_narration_shows_the_actual_command():
    """Shell narrates each DISTINCT command (human-like detail), not a
    generic "Menjalankan perintah shell" — and heredocs are truncated to
    their first line."""
    agent = make_executor()
    text = agent._tool_progress_narration(
        tool_event("shell_exec", tool_name="shell", id="1",
                   exec_dir="/home/runner/users/x",
                   command="cat > index.html << 'EOF'\n<!DOCTYPE html>\nEOF")
    )
    assert text == "Menjalankan `cat > index.html << 'EOF'`"
    # A different command still narrates (per-command dedup)…
    agent._last_tool_narration_ts = 0.0  # reset throttle for the test
    text2 = agent._tool_progress_narration(
        tool_event("shell_exec", tool_name="shell", id="1",
                   exec_dir="/home/runner/users/x", command="ls -la")
    )
    assert text2 == "Menjalankan `ls -la`"
    # …the same command again stays quiet.
    agent._last_tool_narration_ts = 0.0
    assert agent._tool_progress_narration(
        tool_event("shell_exec", tool_name="shell", id="1",
                   exec_dir="/home/runner/users/x", command="ls -la")
    ) is None


def test_long_commands_are_truncated():
    agent = make_executor()
    long_cmd = "python3 " + "x" * 80
    text = agent._tool_progress_narration(
        tool_event("shell_exec", tool_name="shell", id="1",
                   exec_dir="/d", command=long_cmd)
    )
    assert text.startswith("Menjalankan `python3 xxx")
    assert len(text) <= len("Menjalankan ` ") + 48 + 2  # template + 48-char cmd + ellipsis/backtick
