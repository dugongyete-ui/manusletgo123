---
name: Tool error visibility
description: Tool failures must be visible and actionable — never "(No Content)" in the UI, never a blind retry loop in the model. Task 26, 2026-08-30.
---

## The incident

Session 66bb17b346fc4776 ("Presentasi Sejarah Persib Bandung"): the model called `file_write` WITHOUT the required `file` argument (content-only). Chain of failure:

1. Raw `TypeError: FileToolkit.file_write() missing 1 required positional argument: 'file'` → the model retried the SAME broken call **4 times** (opaque Python message gave it nothing to repair with), then worked around via `shell_exec` inline python.
2. `invoke_tool`'s error path returned a ToolMessage with **no artifact** → `ToolEvent.function_result = null` in the DB.
3. `_handle_tool_event` fell into the no-`file`-arg branch → `FileToolContent(content="(No Content)")` → the user clicked the tool pill and saw "Tidak Ada Konten" with zero explanation.

## The fix (3 layers)

1. **`Tool.ainvoke` (tools/base.py)** — `TypeError` / pydantic `ValidationError` from argument mismatch are converted to a failed `ToolResult` whose message is ACTIONABLE: names the error, echoes `Arguments you provided: [content]`, lists `Arguments accepted by file_write: file (required), content (required), append (optional), …` (derived from `args_schema` via `_signature_hint()`), and states the call was NOT executed. Deterministic errors never enter the retry loop.
2. **`invoke_tool` (agents/base.py)** — the exhausted-retries path now attaches `artifact=ToolResult(success=False, message=last_error)` and content is the same JSON the model sees for other failures. Every failure lands in the event.
3. **`_handle_tool_event` (agent_task_runner.py)** — file-tool events show `result.message` when the operation failed (both the no-`file`-arg branch and the read-back-empty branch). The error text is **display-only**: `display_content` is kept separate from `file_content` so a failed write is never synced to GridFS as an artifact nor auto-attached as a deliverable.

## Why display-only matters

If the error message had been assigned into `file_content`, the `if file_content:` gate would (a) upload the error text as if it were the file body and (b) register the FAILED write in `_FILE_WRITE_FUNCTIONS` → deliverable attachment. A stale-file case (file exists, write failed) still syncs the REAL file from disk and returns `synced_file=None`.

## Tests

`tests/test_tool_error_visibility.py` (9): actionable missing-arg message, unexpected-kwarg message, success path untouched, no-retry on TypeError, artifact after retries, UI error text for both incident shapes, success sync regression, display-only error never synced.

## Task 27 refinements (2026-08-30, same-day follow-up)

Full-tool verification (see [tool-verification.md](tool-verification.md)) extended the same principle to two more branches, plus live confirmation:

- **Shell without `id`**: `_handle_tool_event` now shows `result.message` of the failed ToolResult instead of "(No Console)" — same display-only pattern (the error never pollutes console data).
- **Failed search**: `SearchToolContent(results=[])` instead of an AttributeError on `data=None` that left the pill blank.
- **Live E2E proof**: a real agent task called shell_exec without `id`, received the actionable error, and self-corrected in ONE round — exactly the designed loop. Regression tests: `tests/test_tool_result_richness.py`.
