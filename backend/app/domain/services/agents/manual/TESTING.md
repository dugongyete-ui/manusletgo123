# TESTING.md

Verification discipline — proving the thing works, cheaply and honestly.

## The ladder (climb as high as the task deserves)
1. **Static check** — files exist, structure sane (`file_list_dir`), syntax
   OK (`node --check`, `python3 -m py_compile`).
2. **Runs once** — the server starts / the script completes with exit code 0
   (`shell_wait` shows the returncode).
3. **Does the thing** — curl the endpoint and READ the response; open the
   page in the browser and look at the rendered state (screenshot); feed
   real input, check real output.
4. **Edge behaviour** — empty input, wrong input, the state after an error.
   At least one deliberate wrong case.

A task that builds anything user-facing stops at rung 1 or 2 = not done.

## Practical patterns
- Web page: `browser_navigate` to the served URL → `browser_view`/screenshot
  → check the expected element/text actually rendered.
- API: `shell_exec curl -s localhost:PORT/endpoint` → read the JSON → assert
  the key field in your message ("returns items: 12 — count matches seed").
- Data: totals and row counts cross-checked ("1.204 baris masuk, 1.204
  keluar — tidak ada yang hilang").

## Honesty rules
- One failing check outweighs ten passing ones in what you report.
- Flaky ≠ passing: if it worked once and you can't repeat it, say that.
- Never test with fake data and report it as real usage.

## Cleanup
Kill every server/process you started (`shell_kill_process`) BEFORE the
final message. A "finished" task with orphan processes is not finished.
