# WORKFLOW.md

Request → result, the whole arc.

```
user message
   │
   ▼
[1] READ     AGENTS.md (fresh workspace) · index project/SKILLS.md · matched project/skills/<name>/SKILL.md · upload/ files
   │
   ▼
[2] OPEN     one specific opening line (what & why first)
   │
   ▼
[3] LOOP     one-sentence goal → phases: INSPECT → PLAN → IMPLEMENT →
   │         VERIFY → REPORT, each with a checkable done-condition →
   │         narrate intent → tool call(s) → read result honestly →
   │         verify side effects → interpret → next real question
   │         (repeat until the goal is genuinely met, not until it looks met)
   │         discipline: never re-run an identical exploratory command;
   │         after two failures on the same problem → STOP and ask
   │         (circuit breaker — ORCHESTRATION.md)
   ▼
[4] VERIFY   goal requirements × actual observations, side by side
   │         every gap named · every blocker surfaced
   ▼
[5] PACKAGE  document → one file        build → project dir → ONE .zip
   │
   ▼
[6] CLOSE    final summary: what · where · how to use · what's limited
             attachments = the archive / the file. Nothing else.
```

## The three failure modes this flow exists to prevent
1. **The phantom deliverable** — the message says the file exists, the disk
   disagrees. Prevented by [4]: list before you list.
2. **The zip-and-spill** — the user gets the archive AND every loose file
   inside it. Prevented by [5]: attachments contain the archive only.
3. **The silent partial** — 60% done, reported as done. Prevented by [4]:
   unmet requirements get named, not implied away.

## Timing checkpoints
- Halfway through your action budget? Consolidate: lock in what's verified,
   stop exploring, produce the deliverable.
- New user message mid-task? It supersedes — adapt the plan, keep the arc.
