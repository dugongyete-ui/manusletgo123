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

See skills/fullstack-web-app, python-api-service, and build-verification.
