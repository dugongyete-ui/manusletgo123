---
name: Adaptive dropdown handling
description: Manus.im-style 3-strategy dropdown interaction — prevents the 20+ step click loops seen on React form pages like Facebook registration.
---

# Adaptive Dropdown Handling

## The Problem
Agent was looping 20+ times on dropdown fields (Facebook birthday Day/Year, Gender) because:
1. It called `browser_click` on native `<select>` elements (React ignores programmatic `.value` set without synthetic events)
2. No strategy switching — repeated same failing approach
3. No verification — couldn't confirm if value was actually accepted

## The Fix (2026-06-13)

### New tools added
- `browser_smart_select(index, text)` — primary tool, 3-strategy chain:
  1. Native `<select>`: React-safe text match via `Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set` + `dispatchEvent('change')`
  2. Custom dropdown (div/ul/role="option"): click trigger → scan DOM → click matching option (exact then partial)
  3. Returns visible options list on failure so agent can immediately retry with correct text
- `browser_verify_value(index, expected_text)` — confirms element value after interaction

### Hard limits added to execution prompt
- NEVER `browser_click` on a `<select>` element
- NEVER loop `browser_click → browser_view` more than 3 times on same dropdown
- `browser_console_exec` last-resort pattern with React-safe setter included in prompt

### Files changed
- `backend/app/domain/external/browser.py` — protocol: `smart_select`, `verify_value`
- `backend/app/infrastructure/external/browser/browser_use_browser.py` — full implementation
- `backend/app/infrastructure/external/browser/playwright_browser.py` — full implementation
- `backend/app/domain/services/tools/browser.py` — exposed as LangChain tools
- `backend/app/domain/services/prompts/execution.py` — dropdown rules section with hard limits
- `.cursor/skills/starter.md` — Section 7 documents usage

**Why:** React/Vue synthetic event system ignores `.value = x` direct assignment. Must use native prototype setter + dispatch `input` + `change` events with `bubbles:true` for framework to detect change.

**How to apply:** Any time form interaction fails on a modern SPA (React/Vue/Angular), use `browser_smart_select` and `browser_verify_value`. If both fail twice, use `browser_console_exec` with the React-safe setter pattern from the execution prompt.
