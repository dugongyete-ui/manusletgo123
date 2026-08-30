# AI Dzeck

Intelligent AI Agent platform built with FastAPI + Vue 3. Users can chat with an AI agent that autonomously browses the web, executes shell commands, reads/writes files, searches the web, and downloads images — all streamed in real-time (Manus.im-style plan → execute → summarize loop).

## Architecture

| Service | Stack | Port | Entry Point |
|---|---|---|---|
| **Backend + Frontend** | Python 3.12, FastAPI, LangChain, Beanie — serves the compiled Vue dist | **3000** | `backend/app/main.py` |
| **Sandbox** | Python, FastAPI, Chrome/VNC, Supervisord | 8080 (API), 8222 (CDP), 5901 (VNC WS) | `sandbox/app/main.py` |

**Persistence:** MongoDB Atlas (db `manus`, GridFS artifacts) + Redis Cloud — credentials in `backend/.env`.

**Agent engine:** LangGraph `PlanActGraphFlow` (default) with a hand-rolled `PlanActFlow` fallback — parity machine-checked by `tests/test_flow_engine_parity.py`.

**Sandbox provider (hybrid):** `SANDBOX_PROVIDER` = `replit` (shared local sandbox + per-user path isolation) / `e2b` (per-user microVM) / `auto` (E2B first, transparent fallback). All agent tools verified to behave identically on both providers (`scripts/verify_all_tools.py --provider both` → 57/57 each).

## Running

All services are managed by one master supervisord (no Docker):

```bash
/home/z/.venv/bin/supervisorctl -c /home/z/my-project/.infra/master_supervisord.conf status
/home/z/.venv/bin/supervisorctl -c /home/z/my-project/.infra/master_supervisord.conf restart services:backend
curl -s http://localhost:3000/health   # → 200
```

See `AGENTS.md` (full agent guide) and `.cursor/skills/starter.md` (runbook) for details.

## Key Environment Variables

All configured in `backend/.env`:
- `API_KEY` / `API_BASE` — LLM provider credentials (NVIDIA NIM)
- `MODEL_NAME` — `nvidia/nemotron-3-super-120b-a12b`
- `VISION_MODEL_NAME` — `meta/llama-3.2-11b-vision-instruct`
- `MONGODB_URI` — MongoDB Atlas connection string
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` — Redis Cloud
- `TAVILY_API_KEY` — web search
- `E2B_API_KEY` — E2B microVM provider (optional)
- `AUTH_PROVIDER` — `password` (JWT-based)
- `SANDBOX_PROVIDER` — `replit` / `e2b` / `auto`
- `AGENT_FLOW_ENGINE` — `langgraph` (default) / `custom`
- `AGENT_CONTEXT_SOFT_LIMIT_CHARS` / `AGENT_TOOL_RESULT_MAX_CHARS` — context-overflow defense knobs

## User Preferences

- API keys stay in env vars (personal project)
- No Docker — sandbox runs directly via supervisord in the container
- MongoDB Atlas + Redis Cloud for persistence (no local DB)
- All documentation must reflect the ACTUAL runtime — update `.agents/memory/MEMORY.md` + `.cursor/skills/starter.md` when shipping changes
