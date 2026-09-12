---
name: Human-like task awareness
description: Patterns adopted from DzeckmanusTrader to make the execution agent genuinely aware of what it's doing rather than guessing.
---

## The core pattern

DzeckmanusTrader's key insight: the execution agent works through **questions**, not checklists.
"What don't I know yet, and what's the most important thing to find out?" → call tool → read honestly → next question.

## What was adopted into AI Dzeck

### 1. EXECUTION_SYSTEM_PROMPT rewrite
- **HOW YOU THINK** section: question-driven loop, honest reading of tool results, contradictions must be resolved not skipped, stop when genuinely done (not at an arbitrary minimum).
- **HOW YOU TALK** section: `message_notify_user` BEFORE every tool call (intent + why) AND AFTER (what it means). No silence mid-step.
- **Error handling rule**: single tool failure ≠ step failure. Adapt, try alternatives, summarise what you couldn't get.
- **Ask-user rule**: only when you genuinely cannot proceed without user-held information.

### 2. EXECUTION_PROMPT additions
- **MANDATORY FINAL OUTPUT** section: strict JSON-only block as the last thing emitted, no prose before/after, no markdown fences.
- **Cross-step referencing**: "Connect findings across earlier steps… reference it explicitly… do not treat each step as if it exists in isolation."
- **"Use actual data"** rule: do not invent or estimate values.

### 3. Ghost success detection (execution.py)
When LLM returns `{"success": true}` without calling any real tools (fabricated result due to long context), the step is flagged and retried once with a `[CORRECTION — MANDATORY]` prompt.

### 4. No-tool-call correction retry (execution.py)
When LLM returns plain text instead of tool calls (detected by `step.error == "LLM returned a non-JSON response."`), retried once with a correction prompt.

### 5. Silent failure fallback (execution.py)
If a step fails AND the LLM never called `message_notify_user`, a diagnostic `MessageEvent` is emitted so the user always sees what happened and why.

### 6. `_extract_text_from_json()` (execution.py)
Unwraps `{"result": "..."}` or `{"message": "..."}` JSON wrappers from streaming responses so the frontend receives clean Markdown.

### 7. `SUMMARIZE_STREAM_PROMPT` (execution.py)
Dedicated streaming summarise prompt: direct, Markdown, honest about gaps, no JSON wrapper, no echo of tool errors.

### 8. Config additions (config.py)
- `max_steps: int = 50` — hard cap on plan steps executed before force-summarising.
- `max_consecutive_failures: int = 3` — force-summarise after N consecutive failed steps.
- `extend_system_message: str | None = None` — extra instructions appended to all agent system prompts at runtime.

### 9. Loop guards (plan_act.py)
`_steps_executed` and `_consecutive_failures` counters. When limits are hit, emit a warning `MessageEvent` and transition to SUMMARIZING instead of looping forever.

### 10. `extend_system_message` applied (base.py)
In `_add_to_memory`, if `settings.extend_system_message` is set it is appended to the system prompt when the memory is first initialised. Applied to ALL agents (planner + executor).

## Why

The original agent was "task executor" mode: pick a tool, run it, iterate. No explicit thinking narration, no awareness of prior steps, no ghost-success guard. This caused:
- Silent failures (user sees failed chip, no explanation)
- Ghost successes (fabricated results with no tool calls)
- Loop repetition (same tool called 3x because no dedup guard)
- Disconnected steps (step 3 ignores what step 1 found)

**How to apply:** any future changes to execution prompts or the agent loop should preserve: (a) the pre/post-tool narration contract, (b) the MANDATORY FINAL OUTPUT format, (c) the ghost-success and no-tool-call retry guards.
