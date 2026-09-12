"""Final validation gate — runs once, right before the task's summary is
generated, so "Completed" can never be a lie.

What this gate does (and does NOT do):

VERIFIED MECHANICALLY (from the executor's real memory + sandbox files):
1. required_stages  — every planned step reached a terminal status
                      (completed / completed_with_warnings / failed).
2. required_files   — every deliverable path the steps declared actually
                      exists and is readable in the sandbox right now.
3. file_integrity   — Markdown: non-empty and decodable. CSV: valid header,
                      consistent column count, not accidentally empty.
4. unresolved_errors— count of tool calls that returned success=false.
5. execution summary— counts (tool calls ok/fail, files created/updated,
                      steps completed/failed) derived from the ordered
                      tool-call log in memory.
6. evidence register- URLs/titles/snippets actually returned by search tools
                      and browser navigations, including redirect detection
                      (requested domain != final domain).

NOT VERIFIED MECHANICALLY (reported as SKIPPED, never as PASS):
- data_completeness, source_coverage, calculation_consistency — semantic
  judgements (e.g. "at least 10 risks", "every number has a unit"). The gate
  reports them as skipped with a note so the UI asks for review instead of
  pretending they passed.

The gate NEVER fabricates data: unknown fields stay empty, unverifiable
claims stay unverified. Its failures degrade into warnings, not exceptions —
a broken gate must never kill the task's summary delivery.
"""

import csv
import io
import json
import logging
from datetime import datetime
from typing import Awaitable, Callable, List, Optional, Tuple
from urllib.parse import urlparse

from app.domain.models.plan import ExecutionStatus, Plan
from app.domain.models.validation import (
    CheckState,
    EvidenceConfidence,
    EvidenceEntry,
    EvidenceType,
    ExecutionSummaryData,
    ValidationCheck,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Readable-file size cap for integrity checks: 8 MB is far beyond any sane
# deliverable report/CSV, and protects the gate from huge binaries.
_MAX_INTEGRITY_BYTES = 8 * 1024 * 1024

FileReader = Callable[[str], Awaitable[Optional[str]]]

SEARCH_TOOL_NAMES = {"info_search_web", "web_search", "search_web"}
BROWSER_NAV_TOOLS = {"browser_navigate", "browser_restart"}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _parse_tool_content(message) -> Optional[dict]:
    """Parse a ToolMessage's JSON content into {success, message, data}."""
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _as_dict(value) -> dict:
    """Coerce a tool-result `data` / tool-call `args` value into a dict.

    Context compaction replaces old tool results with
    ToolResult(success=True, data="(removed)") — a STRING data field
    (regression, session 345eb263b2cd4cd7: the gate crashed on
    `"(removed)".get("results")` → 'str' object has no attribute 'get').
    Some providers also serialize tool-call args as a JSON string. This
    helper accepts dicts as-is, tries one JSON parse for strings, and
    returns {} for anything else — the caller then simply finds no
    data, which is the honest outcome for a stubbed/compacted result.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _as_args(value) -> dict:
    """Normalize tool_call args (dict | JSON string | garbage) to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _collect_tool_rounds(memory_messages) -> List[Tuple[str, dict, Optional[dict]]]:
    """Pair each AIMessage tool_call (name, args) with its ToolMessage result.

    Returns an ordered list of (tool_name, args, parsed_result) — the actual
    chronological sequence of tool activity for this run.
    """
    rounds: List[Tuple[str, dict, Optional[dict]]] = []
    pending: dict = {}  # tool_call_id -> (name, args)
    for msg in memory_messages:
        # AIMessage.tool_calls: [{name, args, id}] — args is normally a
        # dict, but robustness first: a string (or anything else) must
        # never crash the gate downstream.
        for call in (getattr(msg, "tool_calls", None) or []):
            try:
                pending[call.get("id", "")] = (
                    call.get("name", ""), _as_args(call.get("args"))
                )
            except Exception:
                continue
        if type(msg).__name__ == "ToolMessage":
            parsed = _parse_tool_content(msg)
            name, args = pending.pop(getattr(msg, "tool_call_id", ""), (getattr(msg, "name", ""), {}))
            rounds.append((name, args, parsed))
    return rounds


def _check_csv(path: str, content: str) -> Tuple[bool, str]:
    """Validate CSV structure. Returns (ok, detail).

    The sandbox caps reads at ~10k chars and appends a "(truncated)" marker;
    when present, the marker is removed and the (possibly cut) final row is
    excluded from the consistency check to avoid false positives.
    """
    truncated = content.endswith("(truncated)")
    if truncated:
        content = content[: -len("(truncated)")]
    if not content.strip():
        return False, f"{path}: file is empty"
    try:
        rows = list(csv.reader(io.StringIO(content)))
    except csv.Error as e:
        return False, f"{path}: cannot parse CSV ({e})"
    if not rows:
        return False, f"{path}: no rows found"
    header = rows[0]
    if not any(cell.strip() for cell in header):
        return False, f"{path}: header row is empty"
    expected = len(header)
    data_rows = rows[1:]
    if truncated and data_rows:
        data_rows = data_rows[:-1]  # final row may be cut mid-field
    inconsistent = [
        i + 1 for i, row in enumerate(data_rows)
        if len(row) != expected
    ]
    if inconsistent:
        preview = ", ".join(str(i) for i in inconsistent[:5])
        more = "" if len(inconsistent) <= 5 else f" (+{len(inconsistent) - 5} more)"
        return False, (
            f"{path}: {len(inconsistent)} row(s) have a different column count "
            f"than the header ({expected}); rows {preview}{more}"
        )
    note = f"{path}: OK — {len(data_rows)} data rows, {expected} columns"
    if truncated:
        note += " (validated from the first ~10k characters)"
    empty_cells = sum(1 for row in data_rows for cell in row if not cell.strip())
    if empty_cells:
        note += f", {empty_cells} empty cell(s)"
    return True, note


def _check_markdown(path: str, content: str) -> Tuple[bool, str]:
    body = content[:-len("(truncated)")] if content.endswith("(truncated)") else content
    if not body.strip():
        return False, f"{path}: file is empty"
    return True, f"{path}: readable ({len(body)} chars)"


def _extract_evidence(rounds) -> List[EvidenceEntry]:
    """Build the evidence register from REAL search results + browser visits.

    - search: every result item the engine actually returned becomes one entry
      (verified=True only for the link/title/snippet as returned).
    - browser: every navigation becomes one entry; when the final host differs
      from the requested host the entry is flagged redirected=True.
    """
    evidence: List[EvidenceEntry] = []
    now = datetime.now()
    for name, args, result in rounds:
        ok = bool(result and result.get("success"))
        if name in SEARCH_TOOL_NAMES and ok:
            data = _as_dict(result.get("data"))
            items = data.get("results") or []
            if not isinstance(items, list):
                continue
            for item in items[:20]:
                if not isinstance(item, dict):
                    continue
                link = str(item.get("link") or item.get("url") or "").strip()
                if not link:
                    continue
                evidence.append(EvidenceEntry(
                    summary=str(item.get("title") or "")[:200],
                    url=link,
                    title=str(item.get("title") or ""),
                    site_name=_host(link),
                    quote=str(item.get("snippet") or "")[:500],
                    type=EvidenceType.FACT,
                    confidence=EvidenceConfidence.MEDIUM,
                    verified=True,
                    source="search",
                    accessed_date=now,
                ))
        elif name in BROWSER_NAV_TOOLS:
            requested = str(args.get("url") or "").strip()
            data = _as_dict((result or {}).get("data"))
            final_url = str(data.get("final_url") or requested)
            redirected = bool(
                requested and final_url and _host(requested) and _host(final_url)
                and _host(requested) != _host(final_url)
            )
            evidence.append(EvidenceEntry(
                summary=str(data.get("title") or "")[:200] or final_url,
                url=final_url,
                requested_url=requested,
                title=str(data.get("title") or ""),
                site_name=_host(final_url),
                type=EvidenceType.FACT,
                # A browser visit proves the page was opened, nothing more.
                confidence=EvidenceConfidence.LOW,
                verified=True,
                source="browser",
                redirected=redirected,
                accessed_date=now,
            ))
    return evidence


def _summarize_file_activity(rounds) -> Tuple[int, int]:
    """Count files created vs updated from ordered file_write activity.

    First successful write to a path = created; later successful writes to the
    same path = updated. append=True writes always count as updates.
    """
    created: set = set()
    updated: set = set()
    for name, args, result in rounds:
        if name != "file_write":
            continue
        if not (result and result.get("success")):
            continue
        path = str(args.get("file") or "") if isinstance(args, dict) else ""
        if not path:
            continue
        append = isinstance(args, dict) and bool(args.get("append"))
        if append or path in created:
            updated.add(path)
        else:
            created.add(path)
    return len(created), len(updated)


async def run_final_validation(
    plan: Optional[Plan],
    memory_messages,
    read_file: FileReader,
    started_at: Optional[datetime] = None,
) -> ValidationResult:
    """Build the validation result. Pure w.r.t. inputs; async only for the
    sandbox file reads. NEVER raises — a gate crash must not kill the task.
    """
    checks: List[ValidationCheck] = []
    try:
        rounds = _collect_tool_rounds(memory_messages)

        # ── 1. required_stages ─────────────────────────────────────
        steps = list(plan.steps) if plan else []
        pending_steps = [s for s in steps if not s.is_done()]
        failed_steps = [s for s in steps if s.status == ExecutionStatus.FAILED]
        if not steps:
            checks.append(ValidationCheck(
                key="required_stages", state=CheckState.SKIPPED,
                detail="No plan steps were recorded for this run.",
            ))
        elif pending_steps:
            names = "; ".join(
                f"step {s.id} ({s.status.value})" for s in pending_steps[:5]
            )
            checks.append(ValidationCheck(
                key="required_stages", state=CheckState.FAIL,
                detail=f"{len(pending_steps)} step(s) never finished: {names}",
            ))
        elif failed_steps:
            checks.append(ValidationCheck(
                key="required_stages", state=CheckState.WARN,
                detail=f"All steps ran, but {len(failed_steps)} finished with status failed.",
            ))
        else:
            checks.append(ValidationCheck(
                key="required_stages", state=CheckState.PASS,
                detail=f"All {len(steps)} planned steps completed.",
            ))

        # ── 2. required_files ──────────────────────────────────────
        declared: List[str] = []
        seen = set()
        for s in steps:
            for p in (getattr(s, "attachments", None) or []):
                if p and p not in seen:
                    seen.add(p)
                    declared.append(p)
        file_details: List[str] = []
        files_state = CheckState.PASS
        if not declared:
            checks.append(ValidationCheck(
                key="required_files", state=CheckState.SKIPPED,
                detail="No deliverable files were declared by the steps.",
            ))
        else:
            missing = []
            for path in declared:
                content = None
                try:
                    content = await read_file(path)
                except Exception as exc:  # sandbox hiccup — record, don't crash
                    logger.warning("validation read failed for %s: %s", path, exc)
                if content is None:
                    missing.append(path)
                else:
                    file_details.append((path, content))
            if missing:
                files_state = CheckState.FAIL
                preview = "; ".join(missing[:5])
                more = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
                checks.append(ValidationCheck(
                    key="required_files", state=files_state,
                    detail=f"{len(missing)} declared deliverable(s) not readable in storage: {preview}{more}",
                ))
            else:
                checks.append(ValidationCheck(
                    key="required_files", state=files_state,
                    detail=f"All {len(declared)} declared deliverable(s) are readable in storage.",
                ))

        # ── 3. file_integrity ──────────────────────────────────────
        integrity_details: List[str] = []
        integrity_state = CheckState.PASS
        if not file_details:
            checks.append(ValidationCheck(
                key="file_integrity", state=CheckState.SKIPPED,
                detail="No text deliverables to validate.",
            ))
        else:
            for path, content in file_details:
                lowered = path.lower()
                if lowered.endswith(".csv"):
                    ok, detail = _check_csv(path, content if len(content) <= _MAX_INTEGRITY_BYTES else "")
                    if not ok and len(content) > _MAX_INTEGRITY_BYTES:
                        detail = f"{path}: too large for inline validation"
                        ok = True  # not a failure — just unverifiable here
                elif lowered.endswith((".md", ".markdown", ".txt")):
                    ok, detail = _check_markdown(path, content)
                else:
                    continue
                integrity_details.append(detail)
                if not ok:
                    integrity_state = CheckState.FAIL
            if integrity_details:
                checks.append(ValidationCheck(
                    key="file_integrity", state=integrity_state,
                    detail=" | ".join(integrity_details[:6]),
                ))

        # ── 4. unresolved errors / tool failures ───────────────────
        failures = [
            (name, result) for name, _args, result in rounds
            if result is not None and result.get("success") is False
        ]
        # Tool rounds whose result we could not parse count as unknown, not failed.
        if failures:
            names = "; ".join(sorted({n for n, _ in failures}))[:300]
            checks.append(ValidationCheck(
                key="unresolved_errors", state=CheckState.WARN,
                detail=f"{len(failures)} tool call(s) failed during the run ({names}).",
            ))
        else:
            checks.append(ValidationCheck(
                key="unresolved_errors", state=CheckState.PASS,
                detail="No failed tool calls were recorded for this run.",
            ))

        # ── 5. semantic checks — honestly skipped, never faked ─────
        for key, label in (
            ("data_completeness", "data completeness (e.g. minimum item counts)"),
            ("source_coverage", "source coverage per claim"),
            ("calculation_consistency", "calculation consistency (units & assumptions)"),
        ):
            checks.append(ValidationCheck(
                key=key, state=CheckState.SKIPPED,
                detail=f"{label.capitalize()} requires human or model review — not mechanically verifiable.",
            ))

        # ── 6. evidence register ───────────────────────────────────
        evidence = _extract_evidence(rounds)
        redirects = [e for e in evidence if e.redirected]
        if evidence and redirects:
            hosts = "; ".join(f"{e.requested_url} → {e.url}" for e in redirects[:3])
            checks.append(ValidationCheck(
                key="redirect_warnings", state=CheckState.WARN,
                detail=f"{len(redirects)} browser visit(s) landed on a different domain than requested ({hosts}).",
            ))
        elif evidence:
            checks.append(ValidationCheck(
                key="redirect_warnings", state=CheckState.PASS,
                detail=f"{len(evidence)} source(s) collected; no cross-domain redirects detected.",
            ))
        else:
            checks.append(ValidationCheck(
                key="redirect_warnings", state=CheckState.SKIPPED,
                detail="No web sources were collected during this run.",
            ))

        # ── 7. execution summary ───────────────────────────────────
        files_created, files_updated = _summarize_file_activity(rounds)
        finished_at = datetime.now()
        succeeded = sum(1 for _n, _a, r in rounds if r and r.get("success"))
        summary = ExecutionSummaryData(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(
                (finished_at - started_at).total_seconds() if started_at else None
            ),
            total_steps=len(steps),
            steps_completed=sum(
                1 for s in steps if s.status == ExecutionStatus.COMPLETED
            ),
            steps_failed=len(failed_steps),
            tool_calls_total=len(rounds),
            tool_calls_succeeded=succeeded,
            tool_calls_failed=len(failures),
            files_created=files_created,
            files_updated=files_updated,
            evidence_count=len(evidence),
            errors=len(failures),
            warnings=sum(1 for c in checks if c.state == CheckState.WARN),
        )

        has_fail = any(c.state == CheckState.FAIL for c in checks)
        has_warn = any(c.state == CheckState.WARN for c in checks)
        overall = "needs_review" if (has_fail or has_warn) else "pass"
        return ValidationResult(
            overall=overall,
            checks=checks,
            unresolved_errors=len(failures),
            warnings=summary.warnings,
            summary=summary,
            evidence=evidence,
        )
    except Exception as exc:
        # The gate must never take the task down with it. The full
        # traceback goes to the server log only — the user-facing check
        # detail stays a clean, human sentence (never a raw Python
        # exception like "'str' object has no attribute 'get'").
        logger.exception("validation gate crashed: %s", exc)
        return ValidationResult(
            overall="needs_review",
            checks=[ValidationCheck(
                key="gate", state=CheckState.WARN,
                detail=(
                    "The automated final check could not finish because of"
                    " an internal error, so this result was not fully"
                    " verified. Please review the deliverables manually."
                ),
            )],
            warnings=1,
            summary=ExecutionSummaryData(
                started_at=started_at, finished_at=datetime.now()
            ),
        )


def build_gate_file_reader(executor) -> FileReader:
    """File reader backed by the executor's FileToolkit sandbox.

    Handles both sandbox ToolResult data shapes ({content: str} | str) and
    returns None for anything unreadable — the gate treats that as a missing
    file, which is exactly what we want to detect.
    """
    from app.domain.services.tools.file import FileToolkit

    toolkits = getattr(executor, "toolkits", None) or ()
    file_toolkit = next(
        (tk for tk in toolkits if isinstance(tk, FileToolkit)), None
    )

    async def reader(path: str) -> Optional[str]:
        if file_toolkit is None:
            return None
        try:
            result = await file_toolkit.sandbox.file_read(file=path)
        except Exception:
            return None
        if not result or not getattr(result, "success", False):
            return None
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            content = data.get("content")
            return content if isinstance(content, str) else None
        if isinstance(data, str):
            return data
        return None

    return reader


def validation_note_for_prompt(result: Optional[ValidationResult]) -> str:
    """Render the gate FACTS as context for the summary model.

    This is context, not a script: the model writes its own natural summary.
    Only mechanical facts are included — no template phrasing.
    """
    if not result:
        return ""
    lines = [
        "\n\n[VALIDATION GATE — mechanical facts about this run, verified from"
        "\n execution data. Weave them into your summary naturally where"
        "\n relevant; do not read them out verbatim:]",
        f"overall: {result.overall}",
    ]
    for c in result.checks:
        lines.append(f"- {c.key}: {c.state.value} — {c.detail}")
    s = result.summary
    lines.append(
        f"counts: steps {s.total_steps} (completed {s.steps_completed},"
        f" failed {s.steps_failed}); tool calls {s.tool_calls_total}"
        f" (ok {s.tool_calls_succeeded}, failed {s.tool_calls_failed});"
        f" files created {s.files_created}, updated {s.files_updated};"
        f" evidence collected {s.evidence_count}"
    )
    if result.overall == "needs_review" or result.unresolved_errors:
        lines.append(
            "Some checks did not fully pass. Be honest about what is missing,"
            " unverified, or incomplete in the final result — do not claim"
            " work was done that the data does not show."
        )
    return "\n".join(lines)
