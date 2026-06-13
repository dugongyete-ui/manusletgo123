---
name: Adaptive dropdown + click handling
description: Full Manus.im-style browser interaction chain — 3-strategy click fallback + DOM settle wait + dropdown visibility check
---

## The Problem
Agent was looping 20+ times on form interactions because:
1. `browser_click` on native `<select>` → React ignores programmatic `.value` without synthetic events
2. No strategy switching on click failure — same approach repeated
3. No verification after set, no DOM settle wait for lazy-loaded content

## Full Manus.im Parity Fix

### 3-strategy click fallback chain (`_click_with_fallback`)
`browser_use_browser.py` — `click()` now automatically tries:
1. **Playwright element.click()** — standard scroll-into-view click
2. **JS synthetic click** — `scrollIntoView` + `mouseover/mouseenter/mousedown/mouseup/click` dispatched via `element.evaluate()`, React/Vue-safe
3. **Raw CDP at element center** — `_get_element_center()` reads `getBoundingClientRect`, then `_cdp_click_at(cx, cy)` fires full `mouseMoved → mousePressed → mouseReleased`

Coordinate-based `click(x, y)` uses `_cdp_click_at` directly.

### DOM settle wait (`_wait_for_dom_settle`)
MutationObserver race: resolves when DOM stops mutating for 150ms, or after 600ms timeout.
Applied after every: click, input, select_option, smart_select. Handles React lazy-loading.

### Input — React-safe events
After `element.fill(text)`, fires `new Event('input', {bubbles:true})` + `new Event('change', {bubbles:true})` via evaluate so framework state detects the change.

### smart_select — visibility check (Manus.im key step)
After opening a custom dropdown, polls up to 800ms (8×100ms) for any option-like element to become visible BEFORE scanning DOM — prevents clicking stale/hidden nodes.
JS scan returns `cx`/`cy` coordinates; after JS `.click()` also fires a CDP coordinate click (belt-and-suspenders for intercepted clicks).

### Dropdown tool chain (registered in BrowserToolkit + Protocol)
- `browser_smart_select(index, text)` — primary, 3-strategy: native select → custom dropdown → text mismatch
- `browser_verify_value(index, expected_text)` — confirms value after interaction
- `browser_select_by_text(index, text)` — native-only select by text
- `browser_get_select_options(index)` — probe element + return option list

### Prompts updated
- `execution.py`: CLICK HIERARCHY section + DROPDOWN rules with hard limits
- `system.py`: browser_rules reflect click hierarchy + smart_select as primary tool

**Why:** Manus.im parity requires click→JS→CDP fallback so elements blocked by overlays, React synthetic event systems, or CSS interceptors are still reliably interacted with.

**How to apply:** `click()` is automatic — just call once. For dropdowns: `smart_select`. For verification: `verify_value`. Last resort: `browser_console_exec` with React-safe setter from execution prompt.
