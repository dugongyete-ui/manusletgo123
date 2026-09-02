---
name: webdev-periodic-updates
description: Fullstack web app builds — scheduled work reference for recurring jobs, daily/hourly tasks, end-user-scheduled cron, periodic notifications. Read FIRST before planning or coding anything that runs on a schedule.
---

# Periodic Updates — Reference

Scope: any recurring or scheduled work for this site (digests, refreshes, cleanups, end-user-defined schedules, periodic notifications).

Default here: the app runs its own scheduler — a `scheduled_jobs` table plus ONE in-process driver (node-cron) started from the server entry. That is correct for self-hosted/long-running deployments. If the user will host on a platform that sleeps idle instances (free tiers, autoscaling containers), pair the same `/api/scheduled/*` handlers with an external HTTP pinger (cron-job.org, Replit Deployments + uptime pinger, GitHub Actions schedule) instead of relying on the in-process driver.

---

## 1. Pick the right cron type

Two flavors. The difference is what runs at trigger time:

- **HTTP cron (external scheduler).** An external pinger POSTs directly to `/api/scheduled/*` on this site. Your handler runs and returns. Nothing else lives in the app — the handler may call the site's own LLM helper inline if needed.
- **In-app scheduler (self-host default).** The server process itself drives the jobs: a `scheduled_jobs` table (cron expression, task_uid, enabled) + a node-cron driver that reads the table and fires handlers inside the process. Survives restarts because the schedule is data, not code.

Decision: keep every trigger a single HTTP handler when an external pinger will drive it; use the in-app driver when the user runs the app themselves (node dist/index.js on a VPS / Repl that stays alive). End-user-defined schedules (UI on this site lets a user pick when X runs) always go through the SAME `/api/scheduled/*` endpoint with the same auth shape — see §3.

---

## 2. Facts (apply to BOTH flavors)

1. Callback path **MUST** start with `/api/scheduled/`. Keep that prefix consistent — external schedulers and the in-app driver both target it.
2. Add a `schedule_cron_task_uid varchar(65)` column (indexed, nullable) to whatever business row owns the job. **Update / delete / look up the business row by `task_uid`, never by `name` or by anything from `req.body`.**
3. The callback only fires once the app is actually RUNNING — the user must start it (`npm start`) or deploy it. In dev, trigger it manually once with `curl -X POST` (with the cron token) to verify the handler before shipping.
4. Wrap handler logic in try/catch and JSON-encode the error on 500 — the operator should see the failure verbatim in logs and in the pinger's response.
5. Cron is **6-field** (with seconds): `sec min hour dom mon dow`, UTC, min interval 60s. Use `0` for the seconds field — e.g. `0 0 9 * * *` is daily 09:00 UTC.
6. Handlers must be **idempotent**. Schedulers retry `5xx` and `429` (up to 3 times, 3s → 1m backoff). Other `4xx` are treated as business failures and not retried.
7. Handler timeout is 2 minutes per call — anything longer must be split into resumable steps that record their own progress.

---

## 3. End-user-driven scheduling (tRPC create + `/api/scheduled/*` callback)

Required pieces (assumes the `schedule_cron_task_uid` column from Facts #2 is already on the business row):

1. tRPC mutation that persists a job row (`task_uid`, cron, name) and registers it with the scheduler; persists the returned `taskUid` to that column.
2. Express handler at `/api/scheduled/<name>` that authenticates (cron token or session), looks up the business row by `taskUid`, runs the work.
3. Explicit `app.post("/api/scheduled/<name>", handler)` in the server entry BEFORE the Vite/static fallthrough — `/api/scheduled/*` is not auto-registered.

A one-time setup walkthrough — do all three steps in one pass; they're a single workflow, not independent options.

**Step 1 — tRPC mutation creates the job and persists `task_uid` on the business row.** For update / delete / pause / resume, look up `scheduleCronTaskUid` first then patch the job row — `enabled=false` pauses, `true` resumes, omit to leave unchanged.

```ts
// server/routers.ts
import { randomUUID } from "crypto";
import { db } from "../db";
import { scheduledJobs } from "../drizzle/schema";

scheduledJobCreate: protectedProcedure
  .input(z.object({ name: z.string(), cron: z.string().regex(/^\S\s+\S\s+\S\s+\S\s+\S\s+\S$/) }))
  .mutation(async ({ input, ctx }) => {
    const taskUid = randomUUID();
    await db.insert(scheduledJobs).values({
      taskUid, name: input.name, cron: input.cron, enabled: true,
    });
    // persist taskUid onto the owning business row here (Facts #2)
    return { taskUid };
  }),
```

**Step 2 — the callback handler.** Same auth shape for both flavors: verify the `x-cron-token` header against `CRON_SECRET` (env) when the call comes from outside; the in-app driver calls handlers directly.

```ts
// server/scheduled/digest.ts
import type { Request, Response } from "express";

export async function digestHandler(req: Request, res: Response) {
  if (req.get("x-cron-token") !== process.env.CRON_SECRET) {
    return res.status(403).json({ error: "bad cron token" });
  }
  try {
    const row = await lookupByTaskUid(String(req.query.taskUid)); // Facts #2: by uid, never by name
    await runDigest(row);
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ error: String(error) }); // Facts #4: verbatim
  }
}
```

**Step 3 — register routes + start the in-app driver.**

```ts
// server/index.ts (before the Vite/static fallthrough)
app.post("/api/scheduled/digest", digestHandler);
app.post("/api/scheduled/cleanup", cleanupHandler);

// In-app driver (self-host flavor): read the table, register with node-cron
import { CronJob } from "cron";
import { listEnabledJobs } from "./db";

for (const job of await listEnabledJobs()) {
  CronJob.from({ cronTime: job.cron, onTick: () => fireHandler(job), start: true });
}
```

Idempotency guard for jobs that mutate data: stamp the business row with `last_run_at` inside the handler and skip when now - last_run_at < 0.9 × the schedule interval — retried calls then become no-ops (Facts #6).

---

## 4. Variants — when the trigger isn't an end-user

### 4a. Project-level jobs (no end-user)

Seed the `scheduled_jobs` table via a migration (INSERT with a fixed `task_uid`) and rely on the in-app driver, or configure the external pinger with the same fixed uid. Everything else — handler, auth, idempotency — is identical.

### 4b. When the trigger needs agentic capabilities

An HTTP handler is a fixed function — it cannot browse, plan, or adapt. If a scheduled task genuinely needs multi-step reasoning at run time, the honest architecture is: the handler enqueues the job into a queue the app exposes, and the user runs an agent worker (or you document a manual trigger for them). Do not fake agentic behavior inside a cron handler with a single LLM call.

---

## 5. Reference — `server/scheduler.ts` (the whole driver, ~40 lines)

```ts
import { CronJob } from "cron";
import { listEnabledJobs } from "./db";

const HANDLERS: Record<string, (taskUid: string) => Promise<void>> = {
  digest: runDigest,
  cleanup: runCleanup,
};

export async function startScheduler() {
  for (const job of await listEnabledJobs()) {
    const handler = HANDLERS[job.name];
    if (!handler) { console.warn(`[scheduler] no handler for ${job.name}`); continue; }
    CronJob.from({
      cronTime: job.cron,                     // 6-field, UTC (Facts #5)
      onTick: () => handler(job.taskUid).catch(e => console.error(`[scheduler] ${job.name} failed:`, e)),
      start: true,
    });
    console.log(`[scheduler] ${job.name} @ ${job.cron}`);
  }
}
```

`cron` (node-cron v3+) accepts 6-field expressions directly. Handler bodies must respect Facts #6 (idempotent) and #7 (2-minute budget) — the driver does not retry, external pingers do.
