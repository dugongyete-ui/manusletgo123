# AGENTS.md

> Canonical guide for AI coding agents working on the **AI Dzeck** codebase.
> Updated 2026-08-30 to match the ACTUAL runtime (z-container, NOT Replit workflows anymore).

---

## Project Overview

AI Dzeck is a general-purpose AI Agent platform (Manus.im-style). It runs in a single Linux container (`z` user, `/home/z/my-project/`) with all services managed by **one master supervisord**:

| Service | Stack | Port | Entry Point |
|---|---|---|---|
| **Backend + Frontend** | Python 3.12, FastAPI, LangChain, Beanie/Motor — serves the compiled Vue dist | **3000** | `backend/app/main.py` |
| **Sandbox** | Python, FastAPI, Xvfb/Chrome/VNC (supervisord-managed) | 8080 (API), 8222 (Chrome CDP), 5901 (VNC WS) | `sandbox/app/main.py` |

Infrastructure: **MongoDB Atlas** (db `manus`, GridFS artifacts), **Redis Cloud**. No Docker, no Replit workflows.

Additional (dev-only): **Mockserver** (FastAPI, port 8090, `mockserver/main.py`) for LLM-free development.

Agent execution: two interchangeable orchestration engines — `PlanActGraphFlow` (**LangGraph**, default) and `PlanActFlow` (custom state machine), switched by `AGENT_FLOW_ENGINE`; parity machine-checked by `tests/test_flow_engine_parity.py`.

Sandbox provider is hybrid: `SANDBOX_PROVIDER` = `replit` (current: shared local sandbox with per-user path isolation via `UserScopedSandbox`) / `e2b` (per-user microVM) / `auto` (E2B first, transparent fallback). Tool behavior is verified IDENTICAL on both providers (`scripts/verify_all_tools.py --provider both` → 57/57 each).

---

## Directory Structure

```
manusletgo123/
├── frontend/          # Vue 3 SPA (Vite, TypeScript, Tailwind) — built to frontend/dist, served BY the backend
├── backend/           # FastAPI backend (DDD layout)
│   └── app/
│       ├── domain/           # Models, services, tools, agents, flows, repositories
│       ├── application/      # Application services (auth, agent, file, token, email)
│       ├── infrastructure/   # External integrations (search, browser, sandbox, DB, cache)
│       ├── interfaces/       # API routes, schemas, error handlers, dependencies
│       ├── core/             # Config (config.py)
│       └── main.py
├── sandbox/           # Sandbox service (shell, file, supervisor APIs)
├── mockserver/        # Mock LLM server for dev/testing
├── .agents/memory/    # Deep-dive engineering memory (indexed by MEMORY.md)
├── .cursor/skills/    # Cursor agent skills
├── scripts/e2e/       # Browser E2E harness
└── SKILL.md           # Development contract for prompts/tools (READ BEFORE touching prompts)
```

---

## Development Environment (z-container)

### Running Services

All services live under the master supervisord:

```bash
SUP=/home/z/.venv/bin/supervisorctl
CONF=/home/z/my-project/.infra/master_supervisord.conf

$SUP -c $CONF status                    # backend, chrome, sandbox-app, websockify, x11vnc, xvfb
$SUP -c $CONF restart services:backend  # after backend code changes
curl -s http://localhost:3000/health    # → 200 when healthy
```

Frontend changes: `cd frontend && pnpm build` (backend serves `dist/`; restart not required for static assets).

### Key Environment Variables (backend/.env)

| Variable | Value / Purpose |
|---|---|
| `API_KEY` / `API_BASE` | NVIDIA NIM gateway (`https://integrate.api.nvidia.com/v1`) |
| `MODEL_NAME` | `nvidia/nemotron-3-super-120b-a12b` |
| `VISION_MODEL_NAME` | `meta/llama-3.2-11b-vision-instruct` |
| `SSL_VERIFY` | `false` — REQUIRED (gateway cert fails Python CA check) |
| `MONGODB_URI` | MongoDB Atlas connection string |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis Cloud credentials |
| `TAVILY_API_KEY` | Web search |
| `E2B_API_KEY` | E2B microVM provider (optional; quota verified 2026-08-30) |
| `AUTH_PROVIDER` | `password` (JWT-based auth) |
| `SANDBOX_PROVIDER` | `replit` (current) / `e2b` / `auto` |
| `SANDBOX_BASE_URL` | `http://localhost:8080` |
| `SANDBOX_VNC_URL` | `ws://localhost:5901` |
| `SANDBOX_CDP_URL` | `http://localhost:8222` |
| `SEARCH_PROVIDER` | `tavily` |
| `BROWSER_ENGINE` | `browser_use` (CDP + selector map) or `playwright` |
| `AGENT_FLOW_ENGINE` | `langgraph` (default) / `custom` |
| `AGENT_CONTEXT_SOFT_LIMIT_CHARS` | 280000 — proactive compaction threshold (0 = off) |
| `AGENT_TOOL_RESULT_MAX_CHARS` | 48000 — per-tool-result LLM context cap (0 = off) |

For development without a real LLM, set `API_BASE=http://localhost:8090/v1` and start the mockserver manually.

---

## Testing

### Backend Tests (pytest — NO server needed)

```bash
cd backend
python -m pytest tests/ -q          # 280 passed expected
python -m pytest tests/test_context_overflow.py -q   # single file
```

**Known pre-existing failures (do NOT chase):** `test_api_file.py` + `test_auth_routes.py` (14 failed + 19 errors) — they require the live auth service / seeded DB and fail identically on a clean tree.

Key test files (agent behavior): `test_flow_engine_parity.py`, `test_context_overflow.py`, `test_conversation_context.py`, `test_tool_error_visibility.py`, `test_tool_result_richness.py`, `test_artifact_sync_nonblocking.py`, `test_plan_progress.py`.

### Sandbox Tests (pytest)

```bash
cd sandbox && python -m pytest
```

### Frontend (No Automated Test Runner)

```bash
cd frontend
pnpm type-check    # vue-tsc type checking
pnpm build         # production build (catches TS + template errors)
```

### E2E / Live Verification (real LLM + real sandbox)

```bash
python /home/z/my-project/scripts/langgraph_e2e_smoke.py        # create+read file task → SMOKE PASSED
python /home/z/my-project/scripts/context_e2e_smoke.py          # 2-turn conversation memory
python /home/z/my-project/scripts/verify_all_tools.py --provider both   # EVERY tool × Replit + E2B
python /home/z/my-project/scripts/verify_tool_events_e2e.py     # ToolEvent function_result/tool_content audit
```

### Full-Stack Integration Test

1. Ensure services are RUNNING (`$SUP -c $CONF status`)
2. Open the preview URL (proxied to port 3000) or `http://localhost:3000`
3. Register/login (or set `AUTH_PROVIDER=none`)
4. Create session, send message
5. Check `/home/z/my-project/.infra/logs/backend.log` + `backend_err.log`

---

## Code Conventions

### Backend (Python)

- **DDD architecture**: `domain/` → `application/` → `infrastructure/` → `interfaces/`
- **FastAPI** with **Pydantic v2** models and settings
- **Beanie** ODM for MongoDB documents (`infrastructure/models/documents.py`)
- **Redis** for caching and message queues
- Dependency management: **uv** + `pyproject.toml` (PEP 621)
- No enforced linter/formatter (no Ruff, Black, or Flake8 configured)
- Async-first: use `async def` for route handlers and service methods

### Frontend (TypeScript / Vue)

- **Vue 3 Composition API** with `<script setup lang="ts">`
- **TypeScript** throughout
- **Tailwind CSS** for styling, **reka-ui** component library
- Path alias: `@/` → `src/`
- **vue-i18n** for internationalization (Indonesian + English)
- Dependency management: **pnpm** + `package.json`
- No ESLint or Prettier configured

### Sandbox (Python)

- **FastAPI** service exposing shell, file, and supervisor APIs
- Runs via **supervisord** managing Chrome, Xvfb, VNC, and the API
- Dependency management: **uv** + `pyproject.toml`

### Agent / Prompt Contract

`SKILL.md` (repo root) is the binding contract for prompt and tool-docstring changes — read it BEFORE touching system prompts, tool docstrings, planner, or the agent loop. Deep-dive engineering memory lives in `.agents/memory/` (index: `MEMORY.md`).

---

## Debugging

### Logs

`/home/z/my-project/.infra/logs/` — `backend.log` / `backend_err.log` (tool failures, tracebacks), `sandbox_app.log`, `chrome_err.log`.

### Session forensics (MongoDB Atlas)

```bash
python /home/z/my-project/scripts/find_session_by_url.py <16-char-chat-id>
python /home/z/my-project/scripts/dump_tool_calls.py <mongo-object-id>
python /home/z/my-project/scripts/event_timeline.py <session-id-or-title-fragment>
```

### Resetting State

- MongoDB data is in Atlas cloud — wipe via Atlas console if needed.
- Redis data is in Redis Cloud — flush via Redis Cloud console if needed.

---

## Skills

| Skill File | When to Use |
|---|---|
| `.cursor/skills/starter.md` | Setting up, running, or testing any part of the codebase. Contains detailed API reference, env var tables, and testing workflows. |
| `SKILL.md` | Before changing prompts, tool docstrings, planner, or agent loop — the development contract. |
