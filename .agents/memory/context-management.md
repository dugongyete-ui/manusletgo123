---
name: Context management (error 1261 defense + conversation memory)
description: Four-layer defense against provider "Prompt exceeds max length" errors, plus planner conversation digest. Tasks 24-25, 2026-08-30.
---

## The incident

Image-heavy research tasks (search → doc → image-search → download ×N) died at the FINAL summary with:
`400 {'error': {'code': '1261', 'message': 'Prompt exceeds max length'}}` (NVIDIA NIM).
Root causes: base64 previews inside image_download results (~30-50K tokens/image), search/image tool results never compacted, and the summarize path had NO overflow recovery — all work lost at the last step.

## The four layers (all in BaseAgent/Memory level — both engines inherit)

1. **ENTRY CAP** — `cap_tool_content()` in `tools/base.py`: every `ToolMessage.content` capped at 48K chars (head 60% + tail 40% + truncation marker). RAW result stays complete on `ToolMessage.artifact` (UI unaffected). `image_download` no longer returns base64 `data_url` at all — only file_path/size/source_url.
2. **COMPACTION** — `memory.py`: `compact_messages(messages, aggressive)`; `info_search_web` / `image_search_web` / `image_download` / `image_generate` are all in `_TOOLS_TO_COMPACT`. Aggressive mode: stub all tool results outside the 12-message tail window, hard-truncate tail items to 12K, clip >2K tool args. `drop_older_rounds()` performs protocol-safe surgery (cuts only at HumanMessage boundaries, preserves AI.tool_calls ↔ ToolMessages pairing, keeps system + original stub task + SYSTEM NOTE).
3. **PROACTIVE BUDGET** — `_estimate_context_chars()` + `_enforce_context_budget()` run before EVERY LLM call (`ask_with_messages` + `summarize`): ladder compact → aggressive → drop_older_rounds when above `context_soft_limit_chars` (280K default).
4. **IN-FLIGHT RECOVERY** — `_is_context_overflow_error()` distinguishes 1261-family prompt-length errors from 429/quota (`_is_limit_error`); on hit → `_emergency_context_reduction()` (recovery 1: aggressive; recovery 2: + drop rounds + keep_last=4) → re-snapshot → retry, max 2. Wired into BOTH `ask_with_messages` AND `astream_chunks_with_fallback` (the summary path that used to die).

Parity with browser-use: they only do proactive compaction (`maybe_compact_messages`, step-interval + 40K char floor, keep first + last 6); we additionally survive the in-flight 1261.

## Planner conversation digest (Task 24 — "AI amnesia" fix)

`PlanActFlow._build_conversation_digest(session, message)` (mirrored in `PlanActGraphFlow`): compact transcript from persisted session events (only user/assistant MessageEvents; skips progress narration; excludes the current early-persisted message; caps: 16 newest turns, 600 chars/message, 4000 chars total keeping-newest). Passed into `planner.acknowledge_stream(message, conversation_history=...)` — the ack prompt gets a `[Conversation so far in this session]` block + anti-amnesia instruction, so 0-step conversational follow-ups answer from memory instead of "Saya tidak memiliki riwayat".

## Knobs (no deploy needed)

- `AGENT_CONTEXT_SOFT_LIMIT_CHARS` (default 280000, 0 = disable budget gate)
- `AGENT_TOOL_RESULT_MAX_CHARS` (default 48000, 0 = disable entry cap)

## Tests

`tests/test_context_overflow.py` (22) + `tests/test_conversation_context.py` (14) + parity digest tests in `test_flow_engine_parity.py`.
