---
name: Adaptive dropdown & browser interaction protocol
description: browser_smart_select + browser_verify_value for every form field; browser_use engine via CDP. Updated 2026-08-30 (browser_extract_text removed from codebase).
---

## Primary tools (still active in tools/browser.py)

### `browser_smart_select(index, text)` — every dropdown field
One call handles both native `<select>` and custom React/div dropdowns automatically.

```
# Birthday form (native <select>):
browser_smart_select(5, "15")      # Day
browser_smart_select(6, "June")    # Month
browser_smart_select(7, "1992")    # Year

# Custom React dropdown (e.g. Gender):
browser_smart_select(8, "Male")    # clicks trigger → scans options → clicks match
```

**Decision tree on failure:**
| Result | Action |
|---|---|
| ✅ success | Move to next field |
| ❌ "option not found" + options listed | Retry with exact text from list |
| ❌ "dropdown opened but not found" | `browser_view()` once, retry with visible text |
| ❌ 2nd failure | `browser_console_exec` with React-safe setter |

### `browser_verify_value(index, expected_text)` — verify before submit
```
browser_verify_value(5, "15")     # ✅ Verified '15' matches '15'
browser_verify_value(8, "Male")   # ❌ Mismatch: expected='Male', actual=''
```

### NEVER do this (causes 20+ step loops):
```
# BAD — clicking a <select> repeatedly:
browser_click(index=5) → browser_view() → browser_click(index=5) → …
```
The loop-awareness layer (`loop_detector`) also appends nudges after repeated identical actions, and the failure budget (`max_consecutive_failures=3`) force-summarizes instead of looping forever.

## Current browser toolset (2026-08-30)

view · navigate · restart · click · find_element · input · move_mouse · press_key · select_option · back · forward · scroll_up/down · console_exec · console_view · list_tabs · open_tab · switch_tab · select_by_text · get_select_options · **smart_select** · **verify_value** · wait_for_network_idle · wait_for_element · upload_file

**REMOVED:** `browser_extract_text` (standalone httpx text extractor) no longer exists — do not reference it in prompts or docs; use `browser_navigate` + `browser_view` or search tools instead.

## Engine notes

`BROWSER_ENGINE=browser_use` (default): browser_use library `BrowserSession` via CDP (port 8222) with AI-friendly selector map; `playwright` engine also maintained. Click fallback chain and React-safe synthetic events live in `app/infrastructure/external/browser/*.py`. DOM settle wait + network idle detection apply after every interaction.
