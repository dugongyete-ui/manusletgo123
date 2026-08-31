# MEMORY.md

What carries across tasks. This workspace persists per user account —
files and decisions from previous tasks may already exist.

## At task start
- Check `<home>` for prior output folders before assuming a clean slate.
  A "new" task may really be "continue/redo the old one".
- If a previous task's output exists and the user's new request conflicts
  with it, ask once or pick the safer interpretation and say which you chose.
- Uploads in `upload/` persist too — old attachments may still be relevant.

## During the task
- Keep your own working notes in your head/messages, not as junk files in
  the user's home. Scratch files you create get cleaned up (`rm`) before
  delivery.
- Facts worth carrying to the end: decisions made, blockers hit, anything
  the final summary must mention.

## Never
- Do not edit this manual to "remember" things. Your memory channel is the
  conversation and the artifacts you leave.
- Do not leave credentials, tokens, or .env files in the workspace between
  tasks. If a task needs secrets, they arrive with the task.
