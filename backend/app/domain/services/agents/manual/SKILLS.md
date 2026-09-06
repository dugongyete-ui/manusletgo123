# SKILLS.md

Index of the 50 playbooks in `project/skills/`. This file lives at
`project/SKILLS.md` (top level of project/, next to AGENTS.md) with an
identical copy at `project/skills/SKILLS.md` — both are the same index.
Each skill is a folder with a SKILL.md (read that first). Open one BEFORE
building when the task clearly matches — they encode the difference
between "ran once" and "actually works".

## Document skills — read before ANY matching document task

| Skill | Use when |
|---|---|
| pptx | creating, editing, or analyzing .pptx presentations — html2pptx workflow for new decks, OOXML editing for existing files, template-based creation via rearrange/inventory/replace scripts |
| docx | creating, editing, or analyzing .docx documents — OOXML workflows, tracked changes, comments, mail merge (docx-js guide included) |
| pdf | working with .pdf files — form filling, text extraction, layout analysis, annotation workflows |
| xlsx | .xlsx spreadsheet operations — formulas, recalculation via the recalc.py script, structured data editing |

## Build skills — read before any matching build

| Skill | Use when |
|---|---|
| web-design-engineer | ANY visual front-end deliverable (landing page, dashboard, prototype, HTML slide deck, animation, UI mockup, data viz) — the design-quality playbook: design system declaration, style recipes, anti-cliché rules, variant exploration |
| artifacts-builder | multi-component React/Tailwind/shadcn artifacts with state management, routing, or bundled single-file output |
| canvas-design | posters, art pieces, static visual designs in .png/.pdf — design-philosophy driven |
| theme-factory | applying one of 10 pre-set themes (colors/fonts) to slides, docs, HTML pages — or generating a new theme on the fly |
| webapp-testing | browser-testing local web apps via Playwright — screenshots, console logs, UI verification |
| video-downloader | downloading YouTube videos (quality/format options, audio-only MP3) |
| webdev-readme-fullstack | fullstack web app (web-db-user): the complete template guide — auth, database, file storage, backend API, integrations |
| webdev-readme-static | static site (web-static): the complete guide for static builds — conventions, file layout |
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
| webdev-periodic-updates | ANY scheduled work — recurring jobs, end-user-scheduled cron, periodic notifications. Read FIRST before planning or coding anything that runs on a schedule |

## Research & analysis skills — on demand

| Skill | Use when |
|---|---|
| web-research | multi-source research, fact-checking, reports |
| content-research-writer | long-form content with research, citations, outlines, section feedback |
| developer-growth-analysis | analyzing coding chat history to surface patterns, gaps, learning resources |
| lead-research-assistant | researching companies/contacts and building lead lists |
| competitive-ads-extractor | extracting and analyzing competitor ad campaigns |
| meeting-insights-analyzer | transcripts → structured meeting insights and action items |
| twitter-algorithm-optimizer | optimizing tweet/thread performance for reach |
| changelog-generator | git commits → user-facing release notes |
| langsmith-fetch | pulling LLM run data from LangSmith |

## Productivity & utility skills — on demand

| Skill | Use when |
|---|---|
| file-organizer | organizing files/folders, deduplication, cleanup |
| invoice-organizer | parsing and organizing invoices/receipts |
| image-enhancer | upscaling/restoring images |
| domain-name-brainstormer | brainstorming and checking domain names |
| raffle-winner-picker | random draws from participant lists |
| slack-gif-creator | generating animated GIFs (easing, palettes, effects) |
| tailored-resume-generator | tailoring resumes to specific job descriptions |
| internal-comms | status reports, leadership updates, newsletters, FAQs, incident reports |
| brand-guidelines | applying Anthropic's brand colors/typography to artifacts |
| document-writing | long-form documents, structured reports |

## Platform & meta skills — on demand

| Skill | Use when |
|---|---|
| skill-creator | creating or updating skills (structure, packaging, validation) |
| template-skill | the minimal skill template to copy from |
| skill-share | creating a skill and sharing it with the team |
| mcp-builder | building MCP servers (Python FastMCP / Node SDK) |
| typst-pdf-maker | polished PDF documents that Markdown-to-PDF cannot produce (typography, math, precise layouts) |
| tts-prompter | crafting TTS prompts before entering generate mode for speech tasks |
| build-verification | proving what you built actually runs |
| environment-troubleshooting | sandbox/network/tool failures |
| persistent-computing | needs beyond this sandbox: always-on services, Docker, fixed IP — build-vs-deploy guidance |
| packaging-delivery | zipping and delivering the final archive (structure rules, exclusions) |

## How to use a skill
1. Read its `project/skills/<name>/SKILL.md` top to bottom (one file_read).
2. Follow its workflow where it fits; deviate with reason, not habit.
3. If a skill's assumption is wrong for this environment, say so in the
   final result — the report flows back to the platform team.

## When NOT to use a skill
A task too small for a playbook (single file, single question) doesn't need
one. Skills are leverage, not ceremony.
