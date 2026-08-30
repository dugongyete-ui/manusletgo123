---
name: Tool verification (all tools, both providers)
description: Task 27, 2026-08-30 — every agent tool tested live on Replit AND E2B (57 checks each, 100% pass); browser action tools now return rich state; upload_file is provider-agnostic; verification scripts are reusable.
---

## Historical verification (not current-runtime proof)

User ask: "test semua tools, result-nya ada terlihat atau no content; lingkungan Replit dan E2B harus konsisten".

**Script:** `/home/z/my-project/scripts/verify_all_tools.py --provider replit|e2b|both` in the former z-container environment. This script is not present in the current workspace.
- Drives EVERY tool through the REAL production path: `Toolkit.get_tool(name).ainvoke({...})` → `ToolMessage(content=ToolResult JSON, artifact=ToolResult)`.
- After each call it simulates `_handle_tool_event` display logic and asserts the UI text is non-empty and never "(No Content)".
- Coverage: shell ×5 (exec/wait/view/write_to_process/kill + SLEEP_DONE + stdin-echo markers), file ×10 (+ cross-user denial negative), search ×1 (live Tavily), image ×3 (search/download live; generate = graceful-failure only, no API key), message ×2, browser ×22 (navigate/view/click-by-index/input/verify_value/find_element/wait_for_element/native select ×4/press_key/move_mouse/scroll ×2/console_exec/console_view/tabs ×3/back/forward/network_idle/upload_file ±negative/restart/view-after-restart).
- Browser tests self-host a test page (`python3 -m http.server 8899` INSIDE the sandbox) so chrome resolves `http://localhost:8899` identically on both providers.
- Historical result: **57/57 PASS on Replit, 57/57 PASS on E2B**. It should be rerun in the current workspace after installing the declared E2B dependency.

**Event-pipeline check:** `/home/z/my-project/scripts/verify_tool_events_e2e.py` runs 3 real agent tasks (file+shell / browser / image) through the API and verifies every persisted ToolEvent has `function_result != null` and non-empty `tool_content`. Live proof of the Task-26 self-correct loop: model omitted `id` from shell_exec → got the actionable error → ONE round later called it correctly.

## Fixes that came out of the verification

1. **Browser action tools returned bare success** (`message=None, data=None`) — browser_input (no-enter), browser_press_key, browser_move_mouse, browser_scroll_up/down left the LLM blind and the tool panel empty whenever the screenshot circuit breaker was open. Now: input reports what was typed where; press_key reports key + navigation (observed state when the page changed); move_mouse reports coordinates; scrolls report post-scroll position (`y=1080, 35% down the page, more content below`) via a `_scroll_report` probe.
2. **upload_file was host-filesystem-coupled** — `os.path.isfile()` on the BACKEND host works on Replit (same container) but rejected EVERY E2B upload (file lives inside the microVM). Fix: drop the gate, let Chrome (which shares the sandbox FS on every provider) validate via CDP `DOM.setFileInputFiles`, then post-verify `element.files` — Chrome SILENTLY accepts dangling paths as 0-byte entries, so success requires `files[0].size > 0`. Playwright engine keeps the host check but the error now explains the E2B/browser_use constraint.
3. **Failed shell_exec without `id` displayed "(No Console)"** — `_handle_tool_event` now shows the actual error message from the failed ToolResult (same pattern as the Task-26 file-tool fix).
4. **Failed search crashed the display branch** — `search_results.data.results` with `data=None` raised → swallowed → BLANK tool pill. Guarded: failed search → `SearchToolContent(results=[])`.

## Tests

`tests/test_tool_result_richness.py` (15): shell error/success display ×3, search guard ×2, scroll report ×2, press_key message + navigation ×2, move_mouse, input no-enter, upload success/dangling/empty/CDP-error ×4. Suite: **280 passed** (265 + 15).

## Provider consistency notes

- The current setting is `SANDBOX_PROVIDER=auto`. The hybrid code still supports `auto`/`e2b`/`replit`, but the active runtime lacks the `e2b` Python package, so the live factory smoke fell back to `ReplitSandbox`.
- Both providers expose identical Sandbox/shell/file semantics (E2B mirrors the Replit console history per session); browser engine is `browser_use` via CDP on both (E2B through an nginx Host-rewrite proxy).
- The one engine-level provider difference: PlaywrightBrowser uploads read the file on the backend host — on E2B use the default browser_use engine.
