---
name: Orchestration engines (LangGraph default) + real-time plan updates
description: PlanActGraphFlow is the default engine (machine-checked parity with PlanActFlow); real-time step progress via non-blocking artifact sync. Tasks 22-23, 2026-08.
---

## Two engines, one behavior

- **`flows/plan_act.py`** — `PlanActFlow`: hand-rolled state machine IDLE→PLANNING→EXECUTING→UPDATING→SUMMARIZING→COMPLETED.
- **`flows/plan_act_graph.py`** — `PlanActGraphFlow(PlanActFlow)`: full subclass (constructor/tools/prompts identical), overrides `run()` only; node bodies are verbatim ports of the while-loop branches (yield → `get_stream_writer()`), routing 1:1 with original transitions. State TypedDict `{status, steps_executed, consecutive_failures}`; `recursion_limit = max_steps*2+20` (LangGraph's default 25 kills long plans otherwise); `thread_id = session_id` (ready for a MongoDB checkpointer / crash-resume later).

**AI logic does NOT change between engines** — proven by `tests/test_flow_engine_parity.py` (14 tests run both engines with identical mocks and assert byte-identical event sequences).

Switch: `AGENT_FLOW_ENGINE=custom|langgraph` (default **langgraph**), then restart backend. Selection lives in `agent_task_runner.py`.

## Real-time plan progress (Task 23 incident fix)

Symptom: user watched the agent work but the plan panel sat at 0/5 pending for minutes, then jumped.

Root cause (engine-independent): `_scan_user_home_files` didn't filter dependency dirs, and the artifact sync inside `StepEvent(COMPLETED)` blocked the whole event pump — `npm install` uploaded ~400 node_modules files one-by-one (~0.4s each) BEFORE the completed-step event escaped.

Fix (3 layers in `agent_task_runner.py`, applies to both engines):
1. `_SCAN_JUNK_DIRS` filter — node_modules / bower_components / __pycache__ / venv / target / coverage never sync.
2. Step artifact sync runs as a chained BACKGROUND task (max one in flight, serialized, exceptions swallowed with log); `StepEvent` is yielded immediately.
3. `files_written` mutated in-place (`[:] =`) so background references never break; final summary awaits the background sync before its own sweep; post-loop await prevents orphan uploads.

Note: steps can still "condense" (5→2) when the planner runs `update_plan` after a mega-step — that's by design, not a bug.

## Known behavioral notes (not bugs)

- SSE stream breaks at WaitEvent by protocol (frontend reconnects/polls).
- `ShellToolkit.shell_exec` needs `id` — the model sometimes omits it; arg-mismatch errors are now actionable (see tool-error-visibility.md).
