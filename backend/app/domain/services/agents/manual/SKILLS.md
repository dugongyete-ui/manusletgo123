# SKILLS.md

Index of playbooks in `skills/`. Each is a folder with a SKILL.md (read that
first). Open one BEFORE building when the task clearly matches — they encode
the difference between "ran once" and "actually works".

| Skill | Use when |
|---|---|
| fullstack-web-app | site/app with multiple files, possibly frontend + backend |
| static-landing-page | single- or few-page static site, no server |
| python-api-service | REST API in Python (FastAPI/Flask) |
| web-research | multi-source research, fact-checking, reports |
| data-analysis | CSV/data → cleaning → charts → written report |
| document-writing | long-form documents, structured reports |
| browser-automation | form filling, scraping, logged-in flows via CDP |
| build-verification | proving what you built actually runs |
| packaging-delivery | zipping and delivering the final archive |
| environment-troubleshooting | sandbox/network/tool failures |

## How to use a skill
1. Read its SKILL.md top to bottom (one file_read).
2. Follow its workflow where it fits; deviate with reason, not habit.
3. If a skill's assumption is wrong for this environment, say so in the
   final result — the report flows back to the platform team.

## When NOT to use a skill
A task too small for a playbook (single file, single question) doesn't need
one. Skills are leverage, not ceremony.
