# AI Dzeck – Replit Starter Skill

> Use this skill when setting up, running, or testing any part of the AI Dzeck codebase on Replit.

---

## Architecture at a Glance

| Service | Language / Framework | Port | Entry Point |
|---|---|---|---|
| **Frontend** | Vue 3 + TypeScript, Vite | 5000 (dev) | `frontend/src/main.ts` |
| **Backend** | Python 3.12, FastAPI | 8000 | `backend/app/main.py` |
| **Sandbox** | Python 3.10, FastAPI + Supervisord | 8080 (API), 5901 (VNC WS) | `sandbox/app/main.py` |
| **Mockserver** | Python, FastAPI | 8090 | `mockserver/main.py` (dev only) |

**Persistence:** MongoDB Atlas (cloud) + Redis Cloud — credentials already in Replit env vars.

---

## 1 · Running on Replit

All services are managed by Replit Workflows. They start automatically when the project opens.

| Workflow | Purpose |
|---|---|
| **Start application** | Vite dev server on port 5000, proxies `/api` → backend |
| **Backend API** | FastAPI on port 8000 |
| **Sandbox Services** | Supervisord: Xvfb + Chrome + x11vnc + websockify + sandbox API |

To restart a service: use the Replit workflow panel or the agent `restart_workflow` tool.

### Key `.env` knobs (already configured in Replit shared env vars)

| Variable | Current Value | Purpose |
|---|---|---|
| `AUTH_PROVIDER` | `password` | JWT-based auth; set to `none` to skip login entirely |
| `API_BASE` | `https://chat-gateway--tmi84kzh.replit.app/v1` | LLM provider gateway |
| `API_KEY` | set | LLM API key |
| `MODEL_NAME` | `kimi-k2` | Main chat model |
| `VISION_MODEL_NAME` | `kimi-k2` | Browser screenshot analysis |
| `SEARCH_PROVIDER` | `tavily` | Web search engine |
| `BROWSER_ENGINE` | `browser_use` | `playwright` or `browser_use` |
| `SANDBOX_BASE_URL` | `http://localhost:8080` | Sandbox API |
| `SANDBOX_VNC_URL` | `ws://localhost:5901` | VNC WebSocket |
| `LOG_LEVEL` | `INFO` | Set `DEBUG` for verbose logs |

### Bypassing Auth Entirely

Set `AUTH_PROVIDER=none`. The frontend treats the user as anonymous, backend skips token checks.

### Using Local Auth

Set `AUTH_PROVIDER=local`. Login with `LOCAL_AUTH_EMAIL` / `LOCAL_AUTH_PASSWORD` (defaults: `admin@example.com` / `admin`).

---

## 2 · Running Services Individually (Manual)

### Backend

```bash
cd backend
# Install deps
pip install uv && uv sync
# Start server (MongoDB + Redis already available via cloud)
python3 -m uvicorn app.main:app --host localhost --port 8000 --reload
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev   # Opens on port 5000; Vite proxies /api → localhost:8000
```

### Sandbox

Sandbox runs via supervisord — already managed by the **Sandbox Services** workflow. To run manually:

```bash
cd sandbox
/home/runner/workspace/.pythonlibs/bin/supervisord -n -c replit_supervisord.conf
```

### Mockserver (dev/testing without a real LLM)

```bash
cd mockserver
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090 --reload
```

Then set `API_BASE=http://localhost:8090/v1` and `API_KEY=any-string`.

Controls: `MOCK_DATA_FILE` (default: `default.yaml`), `MOCK_DELAY` (seconds, default: `1`).
Mock data files: `mockserver/mock_datas/` — options: `default.yaml`, `shell_tools.yaml`, `file_tools.yaml`, `browser_tools.yaml`, `search_tools.yaml`, `message_tools.yaml`.

---

## 3 · Testing Workflows by Codebase Area

### 3.1 Backend (pytest, against running server)

Tests in `backend/tests/` hit `http://localhost:8000` via `requests`. Requires **Backend API** workflow running.

```bash
cd backend
python3 -m pytest                            # all tests
python3 -m pytest tests/test_auth_routes.py  # specific file
python3 -m pytest -m file_api                # by marker
```

Key test files:
- `tests/test_auth_routes.py` – registration, login, token refresh, logout
- `tests/test_api_file.py` – file upload / download API
- `tests/test_sandbox_file.py` – sandbox file operations

### 3.2 Sandbox (pytest)

```bash
# Ensure Sandbox Services workflow is running
cd sandbox
python3 -m pytest
```

### 3.3 Frontend

No automated test runner. Validate with:

```bash
cd frontend
pnpm type-check    # vue-tsc type checking
pnpm build         # production build (catches template + TS errors)
```

### 3.4 Mockserver

No tests. Verify it responds:

```bash
curl -X POST http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mock","messages":[{"role":"user","content":"hi"}]}'
```

### 3.5 Integration / End-to-End

1. Ensure all 3 workflows are running (Start application, Backend API, Sandbox Services)
2. Open app preview (port 5000)
3. Login or set `AUTH_PROVIDER=none`
4. Create a new session, send a message
5. Watch backend logs in Backend API workflow console

---

## 4 · Common Environment Notes

### Sandbox Architecture on Replit

The sandbox runs **in-process** within the Replit container (no Docker). Supervisord manages:
- `xvfb` — virtual display
- `chrome` — headless Chrome via CDP
- `x11vnc` — VNC server on the virtual display
- `websockify` — WebSocket bridge for noVNC (port 5901)
- `app` — FastAPI sandbox API (port 8080)

The backend connects to sandbox via `SANDBOX_BASE_URL=http://localhost:8080`. VNC is proxied through the backend WebSocket endpoint `/api/v1/sessions/{id}/vnc`.

### Debugging Backend Logs

Check the **Backend API** workflow console in Replit, or:
```bash
cat /tmp/logs/Backend_API_*.log
```

### Resetting MongoDB / Redis State

- **MongoDB**: Data is in Atlas cloud. Wipe via Atlas console or run a delete script.
- **Redis**: Data is in Redis Cloud. Flush via Redis Cloud console.

---

## 5 · API Quick Reference

### Auth endpoints (`/api/v1/auth/`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/register` | No | `{fullname, email, password}` |
| POST | `/auth/login` | No | `{email, password}` → tokens |
| POST | `/auth/refresh` | No | `{refresh_token}` → new access token |
| POST | `/auth/logout` | Bearer | Invalidates session |
| GET | `/auth/status` | No | Returns `{authenticated, auth_provider}` |
| GET | `/auth/me` | Bearer | Current user info |
| POST | `/auth/change-password` | Bearer | `{old_password, new_password}` |

### Session endpoints (`/api/v1/sessions/`)

| Method | Path | Notes |
|---|---|---|
| PUT | `/sessions` | Create new session |
| GET | `/sessions` | List all sessions |
| GET | `/sessions/{id}` | Get session + history |
| DELETE | `/sessions/{id}` | Delete session |
| POST | `/sessions/{id}/stop` | Stop running session |
| POST | `/sessions/{id}/chat` | Send message (SSE stream response) |
| POST | `/sessions/{id}/shell` | View sandbox shell output |
| POST | `/sessions/{id}/file` | Read sandbox file |
| WS | `/sessions/{id}/vnc` | VNC WebSocket proxy |

### Sandbox endpoints (port 8080, `/api/v1/`)

- `/shell/*` – exec, view, wait, write, kill
- `/file/*` – read, write, replace, search, find, upload
- `/supervisor/*` – status, restart, stop, timeout

---

## 6 · Updating This Skill

When you discover a new testing trick, environment workaround, or operational runbook step:

1. **Open** `.cursor/skills/starter.md`.
2. **Add** the new knowledge to the appropriate section.
3. **Keep it concrete** — exact commands, env var values, and file paths.
4. **Date your addition**: `<!-- Added YYYY-MM-DD: brief reason -->`.

---

## 7 · Dropdown / Form Interaction Reference

### Primary tool: `browser_smart_select(index, text)`

Use this for **every** dropdown field. One call handles both native `<select>` and custom React/div dropdowns automatically.

```
# Birthday form (native <select>):
browser_smart_select(5, "15")      # Day
browser_smart_select(6, "June")    # Month
browser_smart_select(7, "1992")    # Year

# Custom React dropdown (e.g. Gender):
browser_smart_select(8, "Male")    # clicks trigger → scans options → clicks match
```

**Decision tree on failure:**
| Result | Action |
|---|---|
| ✅ success | Move to next field |
| ❌ "option not found" + options listed | Retry with exact text from list |
| ❌ "dropdown opened but not found" | `browser_view()` once, retry with visible text |
| ❌ 2nd failure | `browser_console_exec` with React-safe setter (see prompt) |

### Verification: `browser_verify_value(index, expected_text)`

After filling critical fields, verify before submit:
```
browser_verify_value(5, "15")     # ✅ Verified '15' matches '15'
browser_verify_value(8, "Male")   # ❌ Mismatch: expected='Male', actual=''
```

### NEVER do this (causes 20+ step loops):
```
# BAD — do not do this:
browser_click(index=5)         # clicking a <select>
browser_view()                 # just to check
browser_click(index=5)         # same click again
... (repeats 15 more times)
```

<!-- Updated 2026-06-10: migrated from Docker Compose to Replit; updated ports (5173→5000), removed docker-compose references, updated MongoDB/Redis to cloud-hosted, updated sandbox to supervisord-based Replit workflow -->
<!-- Updated 2026-06-13: added browser_smart_select + browser_verify_value tools; Manus.im-style adaptive dropdown handling; strengthened execution prompt with hard limits -->
