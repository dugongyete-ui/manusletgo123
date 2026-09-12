# TOOLS.md

The toolset and its sharp edges. Full argument schemas live in your execution
prompt — this file is about BEHAVIOUR you must know to use them well.

## Shell (`shell_exec` / `shell_view` / `shell_wait` / `shell_write_to_process` / `shell_kill_process`)
- Long-running commands (servers, watchers) return "still running" after ~5s
  — that's normal. Use `shell_wait` to wait, `shell_view` to read output,
  `shell_kill_process` to stop. ALWAYS kill your dev servers before finishing.
- One session id per logical process. Don't interleave unrelated commands
  into a session you're streaming.
- `cd` doesn't persist between calls — use absolute paths or `cd x && cmd`
  in a single command.

## Browser (`browser_navigate`, `browser_view`, `browser_click`, `browser_input`, ...)
- This is a real Chrome via CDP, not a fetch tool. `browser_navigate` returns
  the interactive element list — READ it before clicking; indices are only
  valid for the observation they came from.
- data:/javascript:/file: URLs are rejected by design — don't retry them.
- After every click/submit, verify the page actually changed (URL, new
  elements, confirmation text). See the build-verification skill.
- Find elements by their visible text via `browser_find_element` when the
  index route fails.

## Files (`file_write` / `file_read` / `file_str_replace` / `file_find_*` / `file_list_dir` / `file_copy` / `file_move` / `file_delete`)
- `file_write` is the ONLY tracked way to create deliverables. Heredocs are
  invisible to delivery. Use `file_str_replace` for surgical edits instead
  of rewriting whole files.
- Paths are absolute, inside your home only.

## Search (`info_search_web`) and images (`image_search_web` / `image_download` / `image_generate`)
- Search results are evidence — record source URLs for any claim you make.
  Research tasks: see RESEARCH.md.
- `image_generate` may be unavailable (no provider key); when it fails, it
  fails cleanly — fall back to `image_search_web` and say so.

## Messages (`message_notify_user` / `message_ask_user`)
- Progress: notify (text, <300 chars, intent/interpretation).
- Decisions the user must make: ask — with options and a sensible default.

## Packaging
- Zip creation: `python3 -m zipfile` one-liners (see DEPLOYMENT.md) — the
  `zip` binary is not guaranteed on every host.
