# AI Dzeck

Intelligent AI Agent platform built with FastAPI + Vue 3. Users can chat with an AI agent that autonomously browses the web, executes shell commands, reads/writes files, and performs web searches — all streamed in real-time.

## Architecture

| Service | Stack | Port | Entry Point |
|---|---|---|---|
| **Frontend** | Vue 3 + TypeScript + Vite + Tailwind | 5000 | `frontend/src/main.ts` |
| **Backend** | Python 3.12, FastAPI, LangChain, Beanie | 8000 | `backend/app/main.py` |
| **Sandbox** | Python 3.10, FastAPI, Chrome/VNC, Supervisord | 8080 / 5901 | `sandbox/app/main.py` |

**Database:** MongoDB Atlas (cloud) + Redis Cloud (Asia Southeast)

## Running on Replit

Three workflows run in parallel:
- **Start application** — Vite dev server on port 5000, proxies `/api` → backend
- **Backend API** — FastAPI on port 8000
- **Sandbox Services** — Supervisord managing Xvfb, Chrome, x11vnc, websockify, sandbox API

## Key Environment Variables

All configured in Replit env vars (shared):
- `API_KEY` / `API_BASE` — LLM provider credentials
- `MODEL_NAME` — currently `kimi-k2`
- `VISION_MODEL_NAME` — currently `kimi-k2`
- `MONGODB_URI` — MongoDB Atlas connection string
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` — Redis Cloud
- `TAVILY_API_KEY` — web search
- `AUTH_PROVIDER` — `password` (JWT-based)
- `SANDBOX_BASE_URL` — `http://localhost:8080`
- `SANDBOX_VNC_URL` — `ws://localhost:5901`

## User Preferences

- API keys stay in env vars (personal project)
- No Docker — sandbox runs directly via Supervisord in Replit
- MongoDB Atlas + Redis Cloud for persistence (no local DB)
- Both English and Chinese documentation must be kept in sync when updating docs
