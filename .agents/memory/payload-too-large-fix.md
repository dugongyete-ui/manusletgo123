---
name: Payload Too Large fix (historical)
description: Early browser-overflow fix — cap interactive elements + mid-step compaction. Superseded largely by context-management.md (Task 25).
---

## What happened (predecessor of the context-management work)

Complex pages (Facebook: 1500+ DOM elements) blew up LLM requests with "Payload Too Large": every `browser_view` re-sent the entire interactive-element list into the prompt on every round.

## What was done

1. Capped the interactive-elements payload exposed per browser state (element lists trimmed, compact rendering).
2. `compact_memory()` runs mid-step every 10 tool-call iterations (`_COMPACT_EVERY_N_ITERATIONS = 10` in `agents/base.py` — still active).

## Status today

The per-result entry cap (`AGENT_TOOL_RESULT_MAX_CHARS`, 48K) and the full 4-layer context defense (see [context-management.md](context-management.md)) now cover this class of overflow generically — for browser DOM, search results, file bodies, and images alike. The mid-step compaction cadence remains as an extra safety net inside long single steps.
