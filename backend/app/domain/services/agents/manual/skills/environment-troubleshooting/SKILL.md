---
name: environment-troubleshooting
description: "Diagnose sandbox, network, and tool failures like an engineer: read the real error, isolate, work around, and report what actually happened."
---

# Environment Troubleshooting

When the environment fights you: command fails, network unreachable,
browser misbehaves, package won't install.

## Method
1. **Read the actual error** — full output via `shell_view`, not the first
   line. "Permission denied" ≠ "command not found" ≠ timeout; each has a
   different fix.
2. **Isolate with a minimal probe**:
   - Network: `curl -sI https://example.com | head -3`
   - DNS: `getent hosts pypi.org`
   - Disk: `df -h . | tail -1`;  Memory: `free -m | head -2`
   - Tool presence: `which python3 node npm; python3 --version`
3. **Fix the specific thing**: wrong path → absolute paths; missing bin →
   pip/npm install or a python stdlib alternative; full disk → clean YOUR
   files (never others'); port busy → another port.
4. **One retry after a fix** — then adapt. Loops of identical retries burn
   the task for nothing.
5. **Report honestly**: what failed, what you tried, what you did instead.
   "image_generate unavailable → substituted image_search_web" is a good
   line. Silent substitution is not.

## Known failure modes in this environment
- **Network flake** (timeouts on search/browser): retry once; then
  continue with what you have and mark the gap.
- **Provider 404/5xx from AI-side calls** (transient): retry once; the
  platform has its own fallbacks.
- **npm install OOM in shared container**: `npm install --no-audit
  --no-fund --loglevel=error`; or pick a lighter dependency; or avoid the
  dependency.
- **Browser tab state odd** (empty tabs, stale indices): `browser_list_tabs`
  → switch to a real tab → re-observe. Never navigate data: URLs.
- **File "exists" but read fails**: check the path is inside your home and
  absolute; check with `file_list_dir` on the parent.

## When to stop and escalate
A real blocker (auth wall, quota, missing capability the task depends on):
one clear `message_ask_user` with options + a default, or finish the
deliverable without that part and say so in the final summary. Never
fabricate the missing part.
