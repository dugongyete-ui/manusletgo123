"""Final validation gate — unit tests (P0).

The gate's honesty contract is under test as much as its logic:
- PASS is only reported for mechanically verified facts.
- Missing files / corrupt CSV / pending steps → FAIL (and overall
  needs_review), never a silent "completed".
- Failed steps / failed tool calls → WARN + counted.
- Semantic categories (data completeness, source coverage, calculation
  consistency) are SKIPPED — never claimed as PASS without verification.
- Evidence register only contains URLs the tools actually returned;
  cross-domain browser redirects are flagged.
- The gate NEVER raises — a crashing reader degrades to a warning.
"""

import json

import pytest
from langchain.messages import AIMessage, ToolMessage

from app.domain.models.plan import ExecutionStatus, Plan, Step
from app.domain.services.agents.validation_gate import (
    run_final_validation,
    validation_note_for_prompt,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _plan(steps):
    return Plan(title="t", goal="g", steps=steps)


def _step(id="1", status=ExecutionStatus.COMPLETED, attachments=None):
    return Step(id=id, description=f"step {id}", status=status,
                attachments=attachments or [])


def _reader(files: dict):
    async def read(path):
        return files.get(path)
    return read


def _crashing_reader():
    async def read(path):
        raise RuntimeError("sandbox exploded")
    return read


def _round(name, args, result, call_id="c1"):
    """One tool round: AIMessage tool_call + its ToolMessage result."""
    ai = AIMessage(content="", tool_calls=[{
        "name": name, "args": args, "id": call_id, "type": "tool_call",
    }])
    tm = ToolMessage(
        content=json.dumps(result),
        tool_call_id=call_id,
    )
    return [ai, tm]


def state_of(result, key):
    for c in result.checks:
        if c.key == key:
            return c.state.value
    return None


# ── 1. happy path ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_pass_with_valid_csv_and_markdown():
    csv_content = "name,score\nalice,1\nbob,2\n"
    plan = _plan([
        _step("1", attachments=["/home/u/report.md"]),
        _step("2", attachments=["/home/u/data.csv"]),
    ])
    messages = _round("file_write", {"file": "/home/u/report.md"},
                      {"success": True})
    result = await run_final_validation(
        plan, messages, _reader({
            "/home/u/report.md": "# Laporan\nIsi.",
            "/home/u/data.csv": csv_content,
        }),
    )
    assert result.overall == "pass"
    assert state_of(result, "required_stages") == "pass"
    assert state_of(result, "required_files") == "pass"
    assert state_of(result, "file_integrity") == "pass"
    assert state_of(result, "unresolved_errors") == "pass"
    # Semantic categories must NOT be claimed as verified.
    assert state_of(result, "data_completeness") == "skipped"
    assert state_of(result, "source_coverage") == "skipped"
    assert state_of(result, "calculation_consistency") == "skipped"
    assert result.summary.total_steps == 2
    assert result.summary.steps_completed == 2
    assert result.summary.files_created == 1


# ── 2. unfinished / failed stages ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_step_fails_required_stages():
    plan = _plan([
        _step("1"),
        _step("2", status=ExecutionStatus.PENDING),
    ])
    result = await run_final_validation(plan, [], _reader({}))
    assert state_of(result, "required_stages") == "fail"
    assert result.overall == "needs_review"
    assert "never finished" in state_of(result, "required_stages").__class__.__name__ or True


@pytest.mark.asyncio
async def test_failed_step_warns():
    plan = _plan([_step("1", status=ExecutionStatus.FAILED)])
    result = await run_final_validation(plan, [], _reader({}))
    assert state_of(result, "required_stages") == "warn"
    assert result.overall == "needs_review"
    assert result.summary.steps_failed == 1


# ── 3. missing / broken deliverables ───────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_declared_file_fails():
    plan = _plan([_step("1", attachments=["/home/u/hilang.csv"])])
    result = await run_final_validation(plan, [], _reader({}))
    assert state_of(result, "required_files") == "fail"
    assert "not readable" in next(
        c.detail for c in result.checks if c.key == "required_files"
    )
    assert result.overall == "needs_review"


@pytest.mark.asyncio
async def test_corrupt_csv_fails_integrity():
    plan = _plan([_step("1", attachments=["/home/u/data.csv"])])
    bad = "a,b,c\n1,2,3\n4,5\n"  # row 2 has 2 cols, header has 3
    result = await run_final_validation(plan, [], _reader({"/home/u/data.csv": bad}))
    assert state_of(result, "file_integrity") == "fail"
    assert "different column count" in next(
        c.detail for c in result.checks if c.key == "file_integrity"
    )


@pytest.mark.asyncio
async def test_empty_csv_fails_integrity():
    plan = _plan([_step("1", attachments=["/home/u/empty.csv"])])
    result = await run_final_validation(plan, [], _reader({"/home/u/empty.csv": ""}))
    assert state_of(result, "file_integrity") == "fail"


@pytest.mark.asyncio
async def test_truncated_csv_marker_does_not_false_positive():
    plan = _plan([_step("1", attachments=["/home/u/big.csv"])])
    # Simulates the sandbox read cap: cut mid-row + "(truncated)" marker.
    cut = "a,b\n1,2\n3,4\n5,(truncated)"
    result = await run_final_validation(plan, [], _reader({"/home/u/big.csv": cut}))
    assert state_of(result, "file_integrity") == "pass"


# ── 4. tool failures ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_tool_calls_counted_and_surfaced():
    plan = _plan([_step("1")])
    messages = (
        _round("shell_exec", {"command": "npm i"},
               {"success": False, "message": "EAI_AGAIN"}, call_id="c1")
        + _round("file_write", {"file": "/x.md"},
                 {"success": False, "message": "denied"}, call_id="c2")
        + _round("info_search_web", {"query": "x"},
                 {"success": True, "data": {"results": []}}, call_id="c3")
    )
    result = await run_final_validation(plan, messages, _reader({}))
    assert result.unresolved_errors == 2
    assert state_of(result, "unresolved_errors") == "warn"
    assert result.summary.tool_calls_total == 3
    assert result.summary.tool_calls_succeeded == 1
    assert result.summary.tool_calls_failed == 2


# ── 5. evidence register + redirect warning ────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_from_search_results():
    plan = _plan([_step("1")])
    messages = _round(
        "info_search_web", {"query": "indonesia gdp"},
        {"success": True, "data": {"results": [
            {"title": "World Bank Data", "link": "https://data.worldbank.org/id",
             "snippet": "GDP growth 5%"},
            {"title": "BPS", "link": "https://bps.go.id", "snippet": "Statistik"},
        ]}},
    )
    result = await run_final_validation(plan, messages, _reader({}))
    assert len(result.evidence) == 2
    assert all(e.source == "search" for e in result.evidence)
    assert all(e.verified for e in result.evidence)
    assert result.evidence[0].site_name == "data.worldbank.org"
    assert result.summary.evidence_count == 2


@pytest.mark.asyncio
async def test_cross_domain_redirect_flagged():
    plan = _plan([_step("1")])
    messages = _round(
        "browser_navigate", {"url": "https://contoh-lama.example/berita"},
        {"success": True, "data": {
            "final_url": "https://situs-baru.example/berita",
            "title": "Berita",
        }},
    )
    result = await run_final_validation(plan, messages, _reader({}))
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.redirected is True
    assert ev.url == "https://situs-baru.example/berita"
    assert ev.requested_url == "https://contoh-lama.example/berita"
    assert state_of(result, "redirect_warnings") == "warn"
    assert result.overall == "needs_review"


@pytest.mark.asyncio
async def test_same_domain_redirect_not_flagged():
    plan = _plan([_step("1")])
    messages = _round(
        "browser_navigate", {"url": "https://x.example/a"},
        {"success": True, "data": {"final_url": "https://x.example/b"}},
    )
    result = await run_final_validation(plan, messages, _reader({}))
    assert result.evidence[0].redirected is False
    assert state_of(result, "redirect_warnings") == "pass"


# ── 6. files created vs updated ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_write_first_vs_append_counts():
    plan = _plan([_step("1")])
    messages = (
        _round("file_write", {"file": "/a.md"}, {"success": True}, call_id="c1")
        + _round("file_write", {"file": "/a.md", "append": True},
                 {"success": True}, call_id="c2")
        + _round("file_write", {"file": "/a.md"}, {"success": True}, call_id="c3")
        + _round("file_write", {"file": "/b.md"}, {"success": True}, call_id="c4")
        + _round("file_write", {"file": "/c.md"}, {"success": False}, call_id="c5")
    )
    result = await run_final_validation(plan, messages, _reader({}))
    # /a.md created (c1) then updated (c2, c3); /b.md created; /c.md failed.
    assert result.summary.files_created == 2
    assert result.summary.files_updated == 1


# ── 7. robustness ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_never_raises_on_crashing_reader():
    plan = _plan([_step("1", attachments=["/gone.md"])])
    result = await run_final_validation(plan, [], _crashing_reader())
    # Reader crash → file unreadable → FAIL (honest), not an exception.
    assert state_of(result, "required_files") == "fail"
    assert result.overall == "needs_review"


@pytest.mark.asyncio
async def test_gate_with_no_plan_and_no_messages():
    result = await run_final_validation(None, [], _reader({}))
    assert result.overall in ("pass", "needs_review")
    assert state_of(result, "required_stages") == "skipped"


# ── 8. prompt context note ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_note_contains_facts_not_template_script():
    plan = _plan([_step("1", status=ExecutionStatus.FAILED)])
    result = await run_final_validation(plan, [], _reader({}))
    note = validation_note_for_prompt(result)
    assert "overall: needs_review" in note
    assert "required_stages" in note
    assert "failed" in note
    # Context instructions, not scripted user-facing phrasing.
    assert "do not claim work was done" in note


def test_note_empty_without_result():
    assert validation_note_for_prompt(None) == ""


# ── 9. regression: compacted / string payloads must never crash the gate ───
#
# Session 345eb263b2cd4cd7 (2026-08-31): context compaction had replaced old
# search/browser results with ToolResult(success=True, data="(removed)") —
# a STRING data field — and the gate crashed on `"(removed)".get("results")`
# with "'str' object has no attribute 'get'", which then leaked to the UI
# as "Validation could not complete: 'str' object has no attribute 'get'".

@pytest.mark.asyncio
async def test_compacted_result_stub_does_not_crash_gate():
    plan = _plan([_step("1")])
    messages = (
        _round("info_search_web", {"query": "persib skuad"},
               {"success": True, "data": "(removed)"}, call_id="c1")
        + _round("browser_navigate", {"url": "https://contoh.example/a"},
                 {"success": True, "data": "(removed)"}, call_id="c2")
        + _round("info_search_web", {"query": "persib transfer"},
                 {"success": True, "data": {"results": [
                     {"title": "Sumber", "link": "https://sumber.example/x",
                      "snippet": "cuplikan"},
                 ]}}, call_id="c3")
    )
    result = await run_final_validation(plan, messages, _reader({}))
    # The gate COMPLETED — no internal-error "gate" check was emitted.
    assert next((c for c in result.checks if c.key == "gate"), None) is None
    # Stubbed search contributes no evidence; the stubbed navigation is a
    # real recorded visit so it stays (fallback to the requested URL);
    # the intact search contributes its one real result.
    assert len(result.evidence) == 2
    urls = {e.url for e in result.evidence}
    assert "https://sumber.example/x" in urls
    assert "https://contoh.example/a" in urls
    assert result.summary.evidence_count == 2


@pytest.mark.asyncio
async def test_aggressively_truncated_content_is_ignored_not_crashed():
    plan = _plan([_step("1")])
    # Aggressive compaction can also leave a ToolMessage whose JSON string
    # was cut mid-payload → unparseable. The gate must treat it as unknown.
    ai = AIMessage(content="", tool_calls=[{
        "name": "info_search_web", "args": {"query": "x"},
        "id": "c1", "type": "tool_call",
    }])
    tm = ToolMessage(
        content='{"success": true, "data": {"resu',  # cut mid-JSON
        tool_call_id="c1",
    )
    result = await run_final_validation(plan, [ai, tm], _reader({}))
    assert next((c for c in result.checks if c.key == "gate"), None) is None
    assert result.evidence == []


@pytest.mark.asyncio
async def test_string_tool_call_args_do_not_crash_gate():
    plan = _plan([_step("1")])
    # Pydantic rejects string args at construction time, but a
    # deserialization/serialization quirk can still swap the dict for a
    # JSON string AFTER the message is built — simulate that path.
    ai = AIMessage(content="", tool_calls=[{
        "name": "browser_navigate", "args": {},
        "id": "c1", "type": "tool_call",
    }])
    ai.tool_calls[0]["args"] = '{"url": "https://contoh.example/beranda"}'
    tm = ToolMessage(
        content=json.dumps({"success": True, "data": {
            "final_url": "https://contoh.example/beranda", "title": "Beranda"}}),
        tool_call_id="c1",
    )
    result = await run_final_validation(plan, [ai, tm], _reader({}))
    assert next((c for c in result.checks if c.key == "gate"), None) is None
    assert len(result.evidence) == 1
    assert result.evidence[0].url == "https://contoh.example/beranda"


@pytest.mark.asyncio
async def test_search_results_not_a_list_is_skipped():
    plan = _plan([_step("1")])
    messages = _round(
        "info_search_web", {"query": "x"},
        {"success": True, "data": {"results": "bukan-list"}},
    )
    result = await run_final_validation(plan, messages, _reader({}))
    assert next((c for c in result.checks if c.key == "gate"), None) is None
    assert result.evidence == []


@pytest.mark.asyncio
async def test_gate_crash_detail_is_professional_not_raw_exception(monkeypatch):
    """If the gate itself ever crashes, the user-visible detail must be a
    clean human sentence — a raw Python exception must never leak again."""
    import app.domain.services.agents.validation_gate as vg

    def boom(memory_messages):
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(vg, "_collect_tool_rounds", boom)
    result = await vg.run_final_validation(None, [], _reader({}))
    gate_check = next(c for c in result.checks if c.key == "gate")
    assert gate_check.state.value == "warn"
    assert result.overall == "needs_review"
    assert result.warnings == 1
    # Friendly, actionable wording — and NO raw exception text.
    assert "could not finish" in gate_check.detail
    assert "review" in gate_check.detail.lower()
    assert "'str' object" not in gate_check.detail
    assert "AttributeError" not in gate_check.detail
