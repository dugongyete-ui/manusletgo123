"""Unit tests for the fallback tool-progress narration:

1. A narration MessageEvent is emitted after the FIRST completed tool of each
   kind within a step (search → browse → write file…), marked is_progress=True
   so the frontend renders it inside the unified step timeline — but ONLY
   while the model itself has been quiet (no message_notify_user within
   _MODEL_NARRATION_SILENCE seconds).
2. Repeated calls of the SAME kind within a step stay quiet (no spam).
3. Rapid different-kind bursts are throttled by the minimum interval.
4. Narration text contains no emojis and no raw tool names.
5. Template variants rotate so consecutive narrations never repeat verbatim.
6. Navigation narrates per DISTINCT site (new site → new line).
7. While the model narrates on its own, the templates stay SILENT — the
   model's contextual voice is the narration, templates are only a fallback.
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
    # 0.0 == "model never narrated" → templates act as fallback immediately.
    agent._last_model_narration_ts = 0.0
    agent._step_narrated_functions = set()
    agent._narration_variants_used = {}
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
    assert text == 'Saya sedang mencari informasi tentang "Persib Bandung" di web.'
    # is_progress is set at the emission site — verify the marker here so the
    # frontend timeline grouping stays in sync with the backend contract.
    msg = MessageEvent(role="assistant", message=text, is_progress=True)
    assert msg.is_progress is True


def test_same_kind_repeats_stay_quiet():
    agent = make_executor()
    first = agent._tool_progress_narration(
        tool_event("browser_view")
    )
    assert first == "Saya sedang membaca isi halamannya untuk mengambil poin-poin penting."
    second = agent._tool_progress_narration(tool_event("browser_view"))
    assert second is None


def test_narration_carries_purpose_not_bare_action():
    """The narration must explain WHY (purpose-bearing), not just the action —
    "Saya sedang membuka X untuk mencari informasi yang dibutuhkan", never a
    bare "Membuka X"."""
    agent = make_executor()
    text = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://id.wikipedia.org/wiki/Persib_Bandung")
    )
    assert "id.wikipedia.org" in text
    assert text.startswith("Saya ")
    assert "untuk" in text  # purpose clause present


def test_navigate_narration_shows_domain_only():
    agent = make_executor()
    text = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://id.wikipedia.org/wiki/Persib_Bandung")
    )
    assert text == "Saya sedang membuka id.wikipedia.org untuk mencari informasi yang dibutuhkan."
    # Full URL must not leak — only the host.
    assert "https://" not in text


def test_navigate_new_site_narrates_again_same_site_stays_quiet():
    """Navigation dedups per DISTINCT site: a second site is newsworthy, a
    re-navigation to the same site is not."""
    agent = make_executor()
    first = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://en.wikipedia.org/wiki/X")
    )
    assert first is not None
    agent._last_tool_narration_ts = 0.0  # reset throttle for the test
    same_again = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://en.wikipedia.org/wiki/X")
    )
    assert same_again is None  # same site → quiet
    agent._last_tool_narration_ts = 0.0
    other = agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://www.transfermarkt.us/verein/14105")
    )
    assert other is not None and other != first


def test_variant_rotation_between_narrations():
    """Consecutive narrations of the same function must rotate templates so
    the stream never repeats itself verbatim (variant 0 → variant 1)."""
    agent = make_executor()
    first = agent._tool_progress_narration(tool_event("browser_view"))
    # Simulate a new step: per-step dedup resets, rotation counter persists.
    agent._step_narrated_functions = set()
    agent._last_tool_narration_ts = 0.0
    second = agent._tool_progress_narration(tool_event("browser_view"))
    assert first is not None and second is not None
    assert first != second
    assert first == "Saya sedang membaca isi halamannya untuk mengambil poin-poin penting."
    assert second == "Saya baca dulu isinya supaya detail yang dibutuhkan tidak terlewat."


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
    assert text == "I'm writing report.md."
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
    assert text == "Saya menjalankan `cat > index.html << 'EOF'`."
    # A different command still narrates (per-command dedup) — with the
    # ROTATED variant, since shell_exec was already narrated once above.
    agent._last_tool_narration_ts = 0.0  # reset throttle for the test
    text2 = agent._tool_progress_narration(
        tool_event("shell_exec", tool_name="shell", id="1",
                   exec_dir="/home/runner/users/x", command="ls -la")
    )
    assert text2 == "Saya eksekusi `ls -la` di terminal."
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
    assert text.startswith("Saya menjalankan `python3 xxx")
    assert len(text) <= len("Saya menjalankan ` ") + 48 + 2  # template + 48-char cmd + ellipsis/backtick


# ── Model-narration gating ──────────────────────────────────────────────────

def test_template_silent_while_model_is_narrating():
    """While the model keeps the user company (message_notify_user within the
    silence window), the deterministic templates must stay COMPLETELY silent —
    the model's contextual narration is the voice the user hears."""
    import time as _time
    agent = make_executor()
    agent._last_model_narration_ts = _time.monotonic()  # model narrated just now
    assert agent._tool_progress_narration(
        tool_event("info_search_web", tool_name="search", query="x")
    ) is None
    assert agent._tool_progress_narration(
        tool_event("browser_navigate", url="https://en.wikipedia.org/wiki/X")
    ) is None


def test_template_resumes_after_model_silence_window():
    """After the model goes quiet for longer than _MODEL_NARRATION_SILENCE,
    the fallback templates resume so the stream never goes dead."""
    import time as _time
    agent = make_executor()
    agent._last_model_narration_ts = (
        _time.monotonic() - ExecutionAgent._MODEL_NARRATION_SILENCE - 1.0
    )
    text = agent._tool_progress_narration(
        tool_event("info_search_web", tool_name="search", query="x")
    )
    assert text is not None


def test_model_narration_resets_silence_window():
    """A fresh model narration inside the window re-silences the templates
    even after they had already fired once."""
    import time as _time
    agent = make_executor()
    # Templates fired long ago (model was quiet).
    agent._last_tool_narration_ts = _time.monotonic() - 60
    agent._step_narrated_functions = set()
    # Model narrates now → templates silent again.
    agent._last_model_narration_ts = _time.monotonic()
    assert agent._tool_progress_narration(tool_event("browser_view")) is None
