---
name: build-verification
description: "Prove what you built actually works: start it, curl it, open it in the browser, click the main flow, check console — before you claim done."
---

# Build Verification

The discipline for the gap between "I wrote the files" and "it works".
Apply at the end of EVERY build task, at the depth the task deserves.

## Ladder
1. **Static** — `file_list_dir` the project (structure sane, no junk);
   `node --check app.js` / `python3 -m py_compile app.py`.
2. **Boots** — start it; `shell_wait` → returncode / `shell_view` →
   startup log ("listening on :8000"). A server without a listen log
   didn't start.
3. **Serves** — `shell_exec curl -s http://localhost:PORT/` and READ the
   response body. Status + payload, not just "connected".
4. **Renders** — `browser_navigate http://localhost:PORT` → check title
   and the expected headline/element actually present.
5. **Behaves** — click the ONE flow the app exists for (add-to-cart,
   submit, search). Confirm the DOM/count/URL changed. Check
   `browser_console_view` for red errors.
6. **Edges** (when warranted) — empty input, invalid input: the app shows
   a sane error, not a crash.

Depth rule: user-facing product → rungs 1-5 minimum. Internal tool →
1-3. Data pipeline → run the script on real input, check row counts.

## Reporting
- Each rung you climb gets one progress line with the EVIDENCE, not the
  intention: "curl /items → JSON 12 item; klik 'Tambah' → counter 0→1".
- A failure at ANY rung is reported as a failure, even if the next rung
  passes. "Form renders, tapi submit tidak mengubah data" — both halves
  said.

## Cleanup (part of "done")
`shell_kill_process` every session you started. Verify via `shell_view`
that nothing of yours is still running before the final message.

## Gotchas
- curl success ≠ app success: read the body (a 200 serving an error page
  is a failure).
- Dev watchers restart on file change — re-verify after your LAST edit,
  not before it.
- `localhost` in browser tools = the sandbox's own localhost. If a port
  differs between what you started and what you curl — check the actual
  listen line.
