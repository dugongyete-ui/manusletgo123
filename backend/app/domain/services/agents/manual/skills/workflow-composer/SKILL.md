---
name: workflow-composer
description: Compose multi-step workflows that chain tools and skills into one repeatable run. Use when a task is long or recurring and benefits from a written pipeline (research → build → verify → package), or when the user asks to turn their process into a repeatable workflow.
---

# Workflow Composer

## When to Use

- A task spans several skills (research → data → build → package → deliver)
- The user describes a repeatable process and wants it codified
- Long multi-phase work needs checkpoints so a failure does not lose progress

## Composing a Workflow

1. **Name the phases and their exit criteria.** A phase is done only when its
   artifact exists and verifies (file opens, page renders, tests pass).
2. **Bind each phase to its skill.** Skills own their domain's quality bar —
   research phases follow deep-research, document phases follow the matching
   document skill, delivery follows packaging-delivery. A workflow replaces
   nothing; it orders and verifies the skills.
3. **Bind tools honestly.** Use registry tools that actually exist in this
   sandbox (`manus-config` for settings, `manus-md-to-pdf` for PDF handouts,
   `manus-render-diagram` for diagrams, the project's own database CLI for
   data steps). A workflow step naming a nonexistent tool is a defect.
4. **Write the workflow file.** `workflow.md` in the project folder:
   phases, commands/tools per phase, exit criteria, rollback note.
5. **Checkpoint between phases.** Persist intermediate artifacts to files
   (JSON/MD) so a rerun starts from the last good phase, not from zero.

## Verification Rules

- Each phase ends with a one-line status: `phase N ok — <artifact> (<how verified>)`.
- A failed phase stops the run: report what failed, what is preserved, and the
  resume point — never continue on a broken foundation.
- The final phase is always delivery: list every artifact path produced.

## Anti-Patterns

- A workflow that only exists in your head — if it isn't written to a file,
  the user can't rerun or audit it.
- Hiding tool failures inside a "successful" run; failed steps must surface.
- Over-composing: three steps done directly beat ten steps of ceremony.
