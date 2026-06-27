# AGENTS.md

> Canonical guide for AI coding agents working on the **AI Dzeck** codebase.

---

## Project Overview

AI Dzeck is a general-purpose AI Agent platform running on **Replit**. It comprises three active services:

| Service | Stack | Port (dev) | Entry Point |
|---|---|---|---|
| **Frontend** | Vue 3 + TypeScript, Vite 4, Tailwind CSS | 5000 | `frontend/src/main.ts` |
| **Backend** | Python 3.12, FastAPI, LangChain, Beanie/Motor | 8000 | `backend/app/main.py` |
| **Sandbox** | Python 3.10, FastAPI, Xvfb/Chrome/VNC | 8080 (API), 5901 (VNC WS) | `sandbox/app/main.py` |

Infrastructure: **MongoDB Atlas** (cloud), **Redis Cloud** (Asia Southeast). No local Docker required.

Additional (dev-only):
| Service | Stack | Port (dev) | Entry Point |
|---|---|---|---|
| **Mockserver** | Python, FastAPI | 8090 | `mockserver/main.py` |

---

## Directory Structure

```
dzeck/
├── frontend/          # Vue 3 SPA (Vite, TypeScript, Tailwind)
├── backend/           # FastAPI backend (DDD layout)
│   └── app/
│       ├── domain/           # Models, services, tools, agents, repositories
│       ├── application/      # Application services (auth, agent, file, token, email)
│       ├── infrastructure/   # External integrations (search, browser, sandbox, DB, cache)
│       ├── interfaces/       # API routes, schemas, error handlers, dependencies
│       ├── core/             # Config (config.py)
│       └── main.py
├── sandbox/           # Sandbox service (shell, file, supervisor APIs)
├── mockserver/        # Mock LLM server for dev/testing
├── .cursor/skills/    # Cursor agent skills
├── .env.example       # Environment variable template
└── replit.md          # Replit project overview and user preferences
```

---

## Development Environment (Replit)

### Running Services

All services are managed by **Replit Workflows**. They start automatically:

| Workflow | Command | Port |
|---|---|---|
| **Start application** | `cd frontend && pnpm dev` | 5000 |
| **Backend API** | `cd backend && python3 -m uvicorn app.main:app --host localhost --port 8000` | 8000 |
| **Sandbox Services** | `cd sandbox && supervisord -n -c replit_supervisord.conf` | 8080/5901 |

To restart a workflow, use the Replit workflow UI or the `restart_workflow` agent tool.

### Key Environment Variables (already configured in Replit)

| Variable | Value / Purpose |
|---|---|
| `API_KEY` | LLM API key |
| `API_BASE` | LLM API base URL |
| `MODEL_NAME` | `kimi-k2` |
| `VISION_MODEL_NAME` | `kimi-k2` |
| `MONGODB_URI` | MongoDB Atlas connection string |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis Cloud credentials |
| `TAVILY_API_KEY` | Web search |
| `AUTH_PROVIDER` | `password` (JWT-based auth) |
| `SANDBOX_BASE_URL` | `http://localhost:8080` |
| `SANDBOX_VNC_URL` | `ws://localhost:5901` |
| `SANDBOX_CDP_URL` | `http://localhost:8222` |
| `SEARCH_PROVIDER` | `tavily` |
| `BROWSER_ENGINE` | `browser_use` |

For development without a real LLM, set `API_BASE=http://localhost:8090/v1` and start the mockserver manually.

---

## Testing

### Backend Tests (pytest — integration-style)

Tests live in `backend/tests/` and hit a **running** backend at `http://localhost:8000`.

```bash
# Ensure backend is running first (Backend API workflow)
cd backend
python3 -m pytest                               # all tests
python3 -m pytest tests/test_auth_routes.py     # specific file
python3 -m pytest -m file_api                   # by marker
```

Key test files:
- `tests/test_auth_routes.py` — auth endpoints
- `tests/test_api_file.py` — file upload/download
- `tests/test_sandbox_file.py` — sandbox file operations

Config: `backend/pytest.ini` (`asyncio_mode = auto`, markers: `file_api`).

### Sandbox Tests (pytest)

```bash
# Ensure Sandbox Services workflow is running
cd sandbox
python3 -m pytest
```

### Frontend (No Automated Test Runner)

```bash
cd frontend
pnpm type-check    # vue-tsc type checking
pnpm build         # production build (catches TS + template errors)
```

### Full-Stack Integration Test

1. Ensure all 3 workflows are running
2. Open the app preview (port 5000)
3. Register/login (or set `AUTH_PROVIDER=none`)
4. Create session, send message
5. Check backend logs in the **Backend API** workflow console

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
- **vue-i18n** for internationalization (Chinese + English)
- Dependency management: **pnpm** + `package.json`
- No ESLint or Prettier configured

### Sandbox (Python)

- **FastAPI** service exposing shell, file, and supervisor APIs
- Runs via **supervisord** managing Chrome, Xvfb, VNC, and the API
- Dependency management: **uv** + `pyproject.toml`

---

## Debugging

### Backend Logs
Check the **Backend API** workflow console in Replit, or read `/tmp/logs/Backend_API_*.log`.

### Sandbox Logs
Check the **Sandbox Services** workflow console, or read `/tmp/logs/Sandbox_Services_*.log`.

### Resetting State

- MongoDB data is in Atlas cloud — wipe via Atlas console if needed.
- Redis data is in Redis Cloud — flush via Redis Cloud console if needed.

---

## Skills

| Skill File | When to Use |
|---|---|
| `.cursor/skills/starter.md` | Setting up, running, or testing any part of the codebase. Contains detailed API reference, env var tables, and testing workflows. |
