# AGENTS.md — Operating Manual

manual-version: 2

This folder is your operating manual. It was scaffolded automatically into your
workspace — it is NOT user content, and it must never be edited, moved, zipped,
or delivered as a task output.

## Start here

When you begin your FIRST task in a fresh workspace, read this file top to
bottom. It takes one tool call and it tells you where everything else lives.
On later tasks, come back only when you need a specific reference.

## What lives where

One topic per file — open only what the current task needs:

| Question you have | File to open |
|---|---|
| Who am I, how do I think? | SOUL.md, IDENTITY.md, MISSION.md |
| What must I never do? | RULES.md, SECURITY.md |
| How does a task flow start to end? | WORKFLOW.md, INSTRUCTIONS.md |
| What tools do I have and how do they behave? | TOOLS.md, CAPABILITIES.md |
| What task type is this? | TASKS.md, SKILLS.md |
| How good must the output be? | STANDARDS.md, CODING.md, TESTING.md |
| How should the result look and sound? | STYLE.md, DESIGN.md, BRAND.md, CONTENT.md |
| How do I research properly? | RESEARCH.md |
| How do I package and deliver? | DEPLOYMENT.md |
| What was already decided? | CONTEXT.md, MEMORY.md, PROJECT.md |

## Skills

`skills/` contains focused playbooks (one folder per skill, each with a
SKILL.md). The index is in SKILLS.md. When a task clearly matches a skill,
read that SKILL.md BEFORE writing any code or file — it encodes the lessons
that make the difference between "it ran once" and "it actually works".

## Where your output goes

Your builds live INSIDE this folder, in their own named subdirectory:
`<home>/project/<your-app-name>/` (e.g. `project/kopi-senja/`). One build =
one subfolder, named after the project in kebab-case. Keep the manual's own
files at the root of `project/` and `project/skills/` untouched — they are
scaffolding, not task output, and never get delivered.

A standalone document (a report, a slide deck, a summary) may sit directly
in `<home>/` or in `<home>/project/` as a single file — it does not need a
subfolder.

## The delivery contract

- One document (report, summary, single file) → deliver the file itself.
- A build with multiple files (site, app, script project) → ONE .zip archive
  containing the whole project. The user receives the archive, not the loose
  files. Never attach build artifacts (.map, .d.ts, lockfiles) individually —
  they travel inside the archive.
- Verify what you deliver: if you say a file exists, you saw it exist.
