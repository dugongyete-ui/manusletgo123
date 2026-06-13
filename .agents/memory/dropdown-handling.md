---
name: Manus.im full parity — browser interaction protocol
description: All Manus.im browser capabilities implemented in BrowserUseBrowser + PlaywrightBrowser as of 2026-06-13
---

## Implemented: Manus.im Full Protocol

### 1. 3-Strategy Click Fallback Chain (`_click_with_fallback`)
S1: Playwright `element.click()` → S2: JS synthetic React-safe events → S3: Raw CDP at element center.
`click()` auto-uses this. Coordinate-based click uses CDP directly.

### 2. DOM Settle Wait (`_wait_for_dom_settle`)
MutationObserver race: 150ms idle or 600ms max. Applied after every click/input/select.

### 3. Network Idle Detection (`_wait_for_network_idle` + `browser_wait_for_network_idle` tool)
Resource Timing API polls: waits until `performance.getEntriesByType('resource').length` stops growing for 300ms. Public tool exposed to agent. Use AFTER login/submit/search buttons.

### 4. Element-Based Waiting (`wait_for_element` + `browser_wait_for_element` tool)
Polls DOM every 200ms until CSS selector match OR visible text found. Both BrowserUseBrowser and PlaywrightBrowser. Use AFTER modal triggers, form submissions, navigations.

### 5. File Upload (`upload_file` + `browser_upload_file` tool)
Uses `element.set_input_files(file_path)` (Playwright) or CDP for `<input type="file">`. Validates file exists and element is correct type.

### 6. Fast Text Extraction (`browser_extract_text` tool — standalone)
httpx async GET + HTMLParser (skips script/style/head). Returns ≤8000 chars. Does NOT use browser engine. For articles, docs, static pages. Falls back to `browser_navigate` for JS-heavy/login pages.

### 7. Input React-safe events
After `element.fill(text)`: fires `new Event('input', {bubbles:true})` + `new Event('change', {bubbles:true})`.

### 8. Dropdown 3-strategy chain (`smart_select`)
S1: native `<select>` React-safe setter + synthetic events → S2: custom div/ul dropdown (click trigger + DOM scan + coordinate backup click) → S3: partial text match. Includes 800ms visibility polling.

### Prompts updated
- `execution.py`: CLICK HIERARCHY + DROPDOWN RULES + SMART WAITING section + FILE UPLOAD / FAST EXTRACTION section
- `system.py`: browser_rules reflect full chain

**Why:** Matches Manus.im full protocol verbatim — 3-strategy click, network idle, element wait, file upload, fast extract.

**How to apply:**
- `click()` → fully automatic 3-strategy
- After login/submit: add `browser_wait_for_network_idle()`
- After modal/dialog triggers: add `browser_wait_for_element(selector='.modal')`
- File upload forms: `browser_upload_file(index, '/home/runner/file.jpg')`
- Read-only page content: `browser_extract_text(url)` (faster than navigate)
