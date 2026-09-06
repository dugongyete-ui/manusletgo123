# CODING.md

Engineering standards for every build.

## Project shape
```
<home>/<app-name>/
  README.md          what it is, how to run, requirements
  package.json / requirements.txt / pyproject.toml
  src/ or app/       source, not a flat dump of 30 files in root
  assets/ or static/ images, styles, data
  .env.example       keys NEEDED, values empty — never real secrets
```
- README answers: what is this, prerequisites, install, run, verify.
  A user who can't start it in 5 minutes will delete it.
- Lockfiles (package-lock.json, etc.) belong in the project — reproducible
  installs are part of the deliverable.

## Code
- Readable names, small functions, no dead code or commented-out blocks.
- Errors handled where they occur: a caught-and-ignored exception is a bug
  wearing a disguise.
- Config via env/flags, not edited constants. No secrets in source (see
  SECURITY.md).
- Comments explain WHY; the code already says what.

## Dependencies
- Minimum viable set. Every dependency is future maintenance debt.
- Pin versions. Install before claiming it runs.

## Before "done"
- It runs from a clean state (fresh install, no magic env).
- No leftover console.log/debug prints in delivered files.
- `ls -R` the project: everything there is either used or removed.

See skills/webdev-readme-fullstack, webdev-readme-static, python-api-service, and build-verification.

## Build bar for web apps
Scale the architecture to what the request actually needs; never fake
the parts that are in scope:
- App-like requests (accounts, persistent data, chat, dashboards,
  ordering) use the webdev-readme-fullstack template (React+Vite+
  Tailwind / Express+tRPC / drizzle+SQLite / JWT auth) — never a
  plain-Express 2-file shortcut.
- Content-style sites (company profile, landing, portfolio) use the
  webdev-readme-static guide — do not bolt a database or auth onto a
  site that never asked for them.
- This sandbox has NO database server (no PostgreSQL/MySQL daemon
  runs here; server-DB migrations like `prisma migrate` fail forever) —
  the skill's file-based SQLite (drizzle) is the database. Never
  scaffold Prisma + PostgreSQL in this workspace.
- Real persistence in the database for app data — never localStorage
  or in-memory arrays, never placeholder data posing as features.
- Real auth (bcrypt, HTTP-only cookies) when the app has users — never
  mock auth or a hardcoded user.
- Real integrations (actual LLM API call for AI chat, key via env var,
  honest degradation without it) — never canned responses. AI features
  load their skill only when the request actually includes them.
- The named feature works end-to-end in the browser before delivery;
  verified by actually exercising it, not by assuming it.
- Whatever skill guided the build, the deliverable follows it — the
  skill's workflow and acceptance criteria define done.
