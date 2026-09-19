---
name: automation-and-scheduling
description: Automate recurring tasks and schedule work to run without manual triggering. Use when the user asks to automate a repetitive process, run a job on a schedule, poll a source for changes, or keep something updated in the background.
---

# Automation and Scheduling

## When to Use

- The user asks to automate a repetitive process (reports, backups, syncs, checks)
- The user wants something to run on a schedule (hourly, daily, weekly)
- The user needs polling with alerting (watch a page, an API, an inbox export)

## Reality of This Sandbox

- The sandbox has **no cron daemon and no systemd timers**. Anything you build
  must keep itself alive as a process or be packaged for the user's own host.
- Long-running automation runs as a background process: `nohup python3 job.py
  >> logs/job.log 2>&1 &` — always log to a file, always write a PID file
  (`echo $! > job.pid`) so it can be stopped cleanly with `kill $(cat job.pid)`.
- A scheduled task that only matters while a session lives should say so.
  A task that must outlive the session ships as a **script + crontab line +
  README** the user can install on their own server.

## Delivery Patterns

1. **In-session automation (lives while this sandbox lives)**
   - Write `job.py` with an explicit loop: work → log → `time.sleep(interval)`.
   - Guard every iteration in try/except; one bad network call must never kill the loop.
   - Start with `nohup`, verify with `tail -f logs/job.log`, show the user the log path.
2. **Portable automation (outlives the session)**
   - Deliver a self-contained script plus a crontab line
     (`0 * * * * cd /path && /usr/bin/python3 job.py >> cron.log 2>&1`)
     or a GitHub Actions workflow file when the trigger is repo-related.
3. **Change detection**
   - Store last-seen state in a small JSON file; diff on each run; only act
     (notify, write, upload) when state actually changed.

## Quality Bar

- Every automation is idempotent: running twice must not duplicate output.
- Every automation logs enough to answer "did it run?" without guessing.
- Secrets (API keys) come from environment variables — never hardcode them.
- Test the job body once in the foreground before backgrounding it.
