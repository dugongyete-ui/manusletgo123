# SKILLS.md

Index of playbooks in `skills/`. Each is a folder with a SKILL.md (read that
first). Open one BEFORE building when the task clearly matches — they encode
the difference between "ran once" and "actually works".

## Build skills — read before any matching build

| Skill | Use when |
|---|---|
| webdev-fullstack | full web app: frontend + backend + database + auth (tRPC/React/Express/Drizzle stack guide) |
| webdev-static | static site (web-static): pure frontend, no server |
| python-api-service | REST API in Python (FastAPI/Flask) |
| browser-automation | form filling, scraping, logged-in flows via CDP |
| data-analysis | CSV/data → cleaning → charts → written report |

## Feature skills — read only when that feature is actually requested

| Skill | Use when |
|---|---|
| webdev-llm-integration | AI features: chat completions, structured JSON, streaming |
| webdev-image-generation | AI image creation or editing in the built app |
| webdev-file-storage | uploading/serving user files, images, documents |
| webdev-maps-integration | maps, geocoding, directions, places |
| webdev-owner-notifications | pushing operational alerts to the app owner |
| webdev-periodic-updates | ANY scheduled work — recurring jobs, cron, periodic notifications. MUST read before any scheduled-work code |

## Specialist skills — on demand, not at session start

| Skill | Use when |
|---|---|
| slides-pptx | writing slide decks in the PPTX XML syntax (read it when you are ready to start editing, not during research) |
| typst-pdf-maker | polished PDF documents that Markdown-to-PDF cannot produce (typography, math, precise layouts) |
| tts-prompter | crafting TTS prompts before entering generate mode for speech tasks |
| document-writing | long-form documents, structured reports |
| web-research | multi-source research, fact-checking, reports |
| build-verification | proving what you built actually runs |
| environment-troubleshooting | sandbox/network/tool failures |
| persistent-computing | needs beyond this sandbox: always-on services, Docker, fixed IP — build-vs-deploy guidance |
| skill-creator | creating or updating skills for this workspace |
| packaging-delivery | zipping and delivering the final archive (structure rules, exclusions) |

## How to use a skill
1. Read its SKILL.md top to bottom (one file_read).
2. Follow its workflow where it fits; deviate with reason, not habit.
3. If a skill's assumption is wrong for this environment, say so in the
   final result — the report flows back to the platform team.

## When NOT to use a skill
A task too small for a playbook (single file, single question) doesn't need
one. Skills are leverage, not ceremony.
