# AGENTS.md — Operating Manual

manual-version: 1

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

Build task outputs NEVER go inside this folder. Create a sibling directory
under your home, e.g. `<home>/my-app-name/`. This manual stays clean so it can
be reused by every future task.

## The delivery contract

- One document (report, summary, single file) → deliver the file itself.
- A build with multiple files (site, app, script project) → ONE .zip archive
  containing the whole project. The user receives the archive, not the loose
  files. Never attach build artifacts (.map, .d.ts, lockfiles) individually —
  they travel inside the archive.
- Verify what you deliver: if you say a file exists, you saw it exist.
