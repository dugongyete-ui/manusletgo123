---
name: browser-automation
description: "Drive the real Chrome (CDP) for forms, logins-free flows, scraping, and uploads: find elements from the live list, act, verify the page changed."
---

# Browser Automation

For tasks that need a real browser: filling forms, scraping JS-rendered
pages, using the user's logged-in session, uploading files, clicking
through flows.

## Core loop (every single action)
1. **OBSERVE** — `browser_navigate` (returns elements) or `browser_view`
   (refresh). Element indices are valid ONLY for the observation they came
   from.
2. **ACT** — `browser_click(index)` / `browser_input(index, value)` /
   `browser_select_by_text(...)` / `browser_upload_file(...)`.
3. **VERIFY** — the observation AFTER: `page_changed`? URL moved? the
   confirmation text appeared (`browser_find_element`)? If not → treat as
   failed and recover (see below).

Never fire an action against a stale index — re-observe after every page
change.

## Finding elements
- Index from the last `browser_view` is the primary route.
- Text route when indices confuse: `browser_find_element("Pilih hari")`.
- Native <select> dropdowns: `browser_get_select_options` →
  `browser_select_by_text` (or `browser_smart_select`).

## Inputs & uploads
- Type with `browser_input`; verify with `browser_verify_value`.
- File upload: file must exist in the sandbox first (file_write /
  image_download), then `browser_upload_file` with the element index of
  the file input.

## Scraping JS pages
- Navigate, wait for content (`browser_wait_for_element` with a selector
  or text you EXPECT on the loaded page), then read elements or
  `browser_console_exec` to extract JSON from the DOM. Cite the URL.

## Safety (see SECURITY.md)
- Credentials/MFA/consent walls: STOP, ask the user via message_ask_user.
- Never submit payments or irreversible actions without explicit approval
  in this task.
- Leave tabs tidy: don't close tabs you didn't create; one working tab
  per site.

## Gotchas
- data:/javascript:/file: URLs are rejected — don't attempt them.
- Popups/omnibox aren't real tabs; re-observe if the tab list looks odd.
- Slow pages: wait_for_element beats sleep-loops.
