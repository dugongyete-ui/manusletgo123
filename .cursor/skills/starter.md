# AI Dzeck – Runtime Starter Skill

> Use this skill when setting up, running, debugging, or testing any part of the AI Dzeck codebase. Updated 2026-08-30 to match the ACTUAL runtime (z-container, NOT Replit anymore).

---

## Architecture at a Glance

| Service | Language / Framework | Port | Entry Point |
|---|---|---|---|
| **Backend + Frontend** | Python 3.12 FastAPI, serves compiled Vue dist | **3000** | `backend/app/main.py` (mounts `frontend/dist` in production) |
| **Sandbox** | Python FastAPI | 8080 (API), 5901 (VNC WS), 8222 (Chrome CDP) | `sandbox/app/main.py` |
| **Mockserver** | Python, FastAPI | 8090 | `mockserver/main.py` (dev only) |

**Persistence:** MongoDB Atlas (db `manus`) + Redis Cloud — credentials in `backend/.env`.

**Agents:** two interchangeable orchestration engines — `PlanActGraphFlow` (LangGraph, **default**) and `PlanActFlow` (custom state machine), selected by `AGENT_FLOW_ENGINE` in `agent_task_runner.py`. Parity is machine-checked by `tests/test_flow_engine_parity.py`.

---

## 1 · Running & Controlling Services

All services are managed by ONE master supervisord (no Docker, no Replit workflows):

```bash
SUP=/home/z/.venv/bin/supervisorctl
CONF=/home/z/my-project/.infra/master_supervisord.conf

$SUP -c $CONF status                    # backend, chrome, sandbox-app, websockify, x11vnc, xvfb
$SUP -c $CONF restart services:backend  # after backend code changes
curl -s http://localhost:3000/health    # → 200 when healthy
```

**Logs** (grep here first when debugging incidents):

| File | What |
|---|---|
| `/home/z/my-project/.infra/logs/backend.log` | API + agent lifecycle INFO |
| `/home/z/my-project/.infra/logs/backend_err.log` | exceptions — tool failures (`Tool execution failed`), tracebacks |
| `/home/z/my-project/.infra/logs/sandbox_app.log` | sandbox file/shell ops |
| `/home/z/my-project/.infra/logs/chrome_err.log` | browser engine |

### Key `.env` knobs (`backend/.env` — values current)

| Variable | Value | Purpose |
|---|---|---|
| `API_BASE` | `https://integrate.api.nvidia.com/v1` | NVIDIA NIM gateway |
| `MODEL_NAME` | `nvidia/nemotron-3-super-120b-a12b` | Main chat model |
| `VISION_MODEL_NAME` | `meta/llama-3.2-11b-vision-instruct` | Screenshot analysis |
| `SSL_VERIFY` | `false` | REQUIRED — gateway cert fails Python CA check |
| `SEARCH_PROVIDER` | `tavily` | web search backend |
| `BROWSER_ENGINE` | `browser_use` | `browser_use` or `playwright` |
| `AGENT_FLOW_ENGINE` | *(default `langgraph`)* | `custom` = instant rollback to hand-rolled engine |
| `AGENT_CONTEXT_SOFT_LIMIT_CHARS` | *(default 280000)* | proactive compaction threshold (0 = off) |
| `AGENT_TOOL_RESULT_MAX_CHARS` | *(default 48000)* | per-tool-result LLM context cap (0 = off) |
| `SANDBOX_PROVIDER` | `replit` | hybrid: `replit` (current) / `e2b` / `auto` — E2B microVMs verified consistent 2026-08-30 |
| `AUTH_PROVIDER` | `password` | `none` skips login |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose agent traces |

### Sandbox isolation

Each user gets `/home/z/sandbox/users/<user_id>/`. `UserScopedSandbox` BLOCKS cross-user paths and anything outside the workspace (e.g. `/home/runner/...` → "Access denied (write)"). When writing test tasks, expect files to land under the user sandbox home.

---

## 2 · Running Services Individually (Manual)

### Backend

```bash
cd backend
uv sync                                   # deps (uv, from pyproject.toml)
python -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

### Frontend (build + served BY backend)

```bash
cd frontend
pnpm install
pnpm type-check                           # vue-tsc
pnpm build                                # → frontend/dist (backend serves it)
```

### Sandbox services (already under master supervisord)

```bash
# manual, if ever needed:
cd sandbox && supervisord -n -c replit_supervisord.conf
```

### Mockserver (testing without a real LLM)

```bash
cd mockserver && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090
# then API_BASE=http://localhost:8090/v1, API_KEY=any-string
```

---

## 3 · Testing Workflows by Codebase Area

### 3.1 Backend unit/integration (pytest — NO server needed)

```bash
cd backend
python -m pytest tests/ -q               # 280 passed expected
python -m pytest tests/test_context_overflow.py -q   # single file
```

**Known pre-existing failures (do NOT chase):** `test_api_file.py` + `test_auth_routes.py` (14 failed + 19 errors) — they require the live auth service / seeded DB and fail identically on a clean tree (verified via `git stash`).

Key test files (agent behavior):
- `tests/test_flow_engine_parity.py` – LangGraph vs custom engine event parity
- `tests/test_context_overflow.py` – error-1261 defense (caps, compaction, recovery)
- `tests/test_conversation_context.py` – planner conversation digest
- `tests/test_tool_error_visibility.py` – tool failure UX (no "(No Content)")
- `tests/test_tool_result_richness.py` – every tool result rich+visible (scroll/press/move/input state, upload guard, shell/search display)
- `tests/test_artifact_sync_nonblocking.py` – real-time plan progress
- `tests/test_ghost_success.py`, `test_loop_awareness.py` – execution guards

### 3.2 E2E smoke (real LLM + real sandbox)

```bash
python /home/z/my-project/scripts/langgraph_e2e_smoke.py          # create+read file task → SMOKE PASSED
python /home/z/my-project/scripts/langgraph_e2e_smoke.py "custom task text"
python /home/z/my-project/scripts/context_e2e_smoke.py            # 2-turn conversation memory
python /home/z/my-project/scripts/verify_all_tools.py --provider both   # EVERY tool, Replit + E2B (57 checks each)
python /home/z/my-project/scripts/verify_tool_events_e2e.py       # real tasks → ToolEvent function_result/tool_content audit
```

Session forensics helpers (MongoDB Atlas):
```bash
python /home/z/my-project/scripts/find_session_by_url.py <16-char-chat-id>
python /home/z/my-project/scripts/dump_tool_calls.py <mongo-object-id>
python /home/z/my-project/scripts/dump_tool_event_full.py <oid> <function_name>
```

### 3.3 Frontend

No automated runner. `pnpm type-check` + `pnpm build` catch template + TS errors.

---

## 4 · Agent Architecture Notes (what recent work shipped)

| Area | Where | Notes |
|---|---|---|
| **LangGraph engine** | `flows/plan_act_graph.py` | default; `recursion_limit = max_steps*2+20`; thread_id = session_id (checkpointer-ready) |
| **Context defense** | `agents/base.py`, `memory.py`, `tools/base.py` | 4 layers vs error 1261: entry cap 48K → compaction → budget gate 280K → in-flight emergency retry (max 2). image_download returns NO base64. |
| **Conversation memory** | `flows/plan_act.py` `_build_conversation_digest` | 0-step follow-ups answered from session transcript (anti-amnesia) |
| **Real-time plan** | `agent_task_runner.py` | step artifact sync is a background chained task; junk dirs (node_modules…) never sync |
| **Tool error UX** | `tools/base.py` + `agent_task_runner.py` | arg mismatches → actionable failed ToolResult (lists provided vs accepted args); UI shows real errors, never "(No Content)" |
| **Rich tool results** | `browser_use_browser.py` | input/press_key/move_mouse/scroll return observed state (position %, typed text, navigation); upload_file validates the path via Chrome (provider-agnostic) + rejects 0-byte dangling entries |
| **Hybrid sandbox** | `sandbox_factory.py`, `e2b_sandbox.py` | `SANDBOX_PROVIDER` = replit (current) / e2b / auto; E2B per-user microVM + automatic fallback; tool behavior verified IDENTICAL on both providers |

---

## 5 · API Quick Reference

### Auth endpoints (`/api/v1/auth/`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/register` | No | `{fullname, email, password}` |
| POST | `/auth/login` | No | `{email, password}` → tokens |
| POST | `/auth/refresh` | No | `{refresh_token}` → new access token |
| POST | `/auth/logout` | Bearer | Invalidates session |
| GET | `/auth/status` | No | `{authenticated, auth_provider}` |

### Session endpoints (`/api/v1/sessions/`)

| Method | Path | Notes |
|---|---|---|
| PUT | `/sessions` | Create new session |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | Get session + event history |
| DELETE | `/sessions/{id}` | Delete session |
| POST | `/sessions/{id}/stop` | Stop running session |
| POST | `/sessions/{id}/chat` | Send message (SSE stream) |
| POST | `/sessions/{id}/file` | Read sandbox file |
| WS | `/sessions/{id}/vnc` | VNC WebSocket proxy |

### Sandbox endpoints (port 8080, `/api/v1/`)

- `/shell/*` – exec, view, wait, write, kill
- `/file/*` – read, write, replace, search, find, upload
- `/supervisor/*` – status, restart, stop, timeout

---

## 6 · Dropdown / Form Interaction Reference

### Primary tool: `browser_smart_select(index, text)`

Use for **every** dropdown field — handles native `<select>` AND custom React/div dropdowns in one call.

```
browser_smart_select(5, "15")     # Day (native select)
browser_smart_select(8, "Male")   # Custom React dropdown
```

Failure ladder: retry with exact option text → `browser_view()` once → `browser_console_exec` React-safe setter. Then verify with `browser_verify_value(8, "Male")` before submit.

**Never** click a `<select>` repeatedly — the loop detector flags it and `max_consecutive_failures=3` force-summarizes the step.

`browser_extract_text` was REMOVED — use `browser_navigate` + `browser_view` or search tools.

---

## 7 · Updating This Skill

When you discover a new operational fact, workaround, or runbook step:

1. **Open** `.cursor/skills/starter.md`.
2. **Add** the knowledge to the appropriate section — keep it concrete (exact commands, env values, paths).
3. **Date the change**: `<!-- Updated YYYY-MM-DD: reason -->`.
4. Keep `.agents/memory/MEMORY.md` index in sync — deep-dive notes live there.

<!-- Updated 2026-08-30 (Task 27): full tool verification on BOTH providers (57/57 Replit + 57/57 E2B) via scripts/verify_all_tools.py; browser action tools return rich state; upload_file provider-agnostic with 0-byte guard; shell/search display guards; test suite 280 passed; E2B is an optional hybrid provider (not removed) -->
<!-- Updated 2026-08-30: full rewrite for z-container runtime — master supervisord (backend :3000 serving Vue dist, sandbox :8080), NVIDIA NIM provider (nemotron-3-super-120b), LangGraph default engine, 4-layer context-overflow defense, tool error visibility fix, current test suite state (265 passed), session forensics scripts -->
<!-- Updated 2026-06-13: browser_smart_select + browser_verify_value; Manus.im-style adaptive dropdown handling -->
