---
name: Replit environment setup
description: Key facts about how AI Dzeck × Claw runs on Replit — ports, sandbox, DB, no Docker
---

## Runtime

- **Frontend**: Vite dev server on port **5000** (not 5173). `allowedHosts: true`, proxies `/api` → `localhost:8000`.
- **Backend**: FastAPI on port **8000**, bound to `localhost`.
- **Sandbox**: Runs via `supervisord` with `replit_supervisord.conf` — no Docker. Manages: xvfb, chrome, x11vnc, websockify (port 5901), sandbox API (port 8080).

## Persistence

- **MongoDB**: Atlas cloud (`MONGODB_URI` in shared env vars). Database name: `manus`.
- **Redis**: Redis Cloud, Asia Southeast (`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` in shared env vars).

## No Docker

Docker is not available / not used. Sandbox runs directly in the Replit container via supervisord.

**Why:** Replit environment doesn't support Docker containers. The project was adapted to run natively using supervisord for the sandbox process group.

**How to apply:** Never suggest `docker build`, `docker run`, or `docker compose` commands. Use Replit workflows to manage services.

## E2B removed

E2B (`E2B_API_KEY`, `E2B_TEMPLATE_ID`) was removed from env vars on 2026-06-10. The sandbox is now exclusively the local Replit-hosted sandbox service.
