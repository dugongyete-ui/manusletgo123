---
name: Runtime environment (z-container)
description: How the platform actually runs NOW — ports, services, supervisord, provider, persistence. Supersedes the old Replit setup (2026-06).
---

## Runtime topology (as of 2026-08-30)

The project no longer runs on Replit. It runs in the `z` user container (`/home/z/my-project/`), all services managed by ONE master supervisord:

| Service | Port | Command / Notes |
|---|---|---|
| **Backend** (FastAPI) | **3000** | `uvicorn app.main:app` — ALSO serves the compiled Vue frontend from `frontend/dist` (production mode). The public preview URL (`preview-*.space-z.ai`) proxies here. |
| **Sandbox API** (FastAPI) | **8080** | File/shell/browser API. User-scoped: each user gets `/home/z/sandbox/users/<user_id>/` — cross-user access is BLOCKED by UserScopedSandbox. |
| Chrome CDP | 8222 | Headless Chrome via `--remote-debugging-port=8222` |
| websockify (VNC WS) | 5901 | → x11vnc :5900 → Xvfb :1 (1280x1029x24) |

**Master supervisord config:** `/home/z/my-project/.infra/master_supervisord.conf`

```bash
# Status / restart (NOT Replit workflows — those are gone)
/home/z/.venv/bin/supervisorctl -c /home/z/my-project/.infra/master_supervisord.conf status
/home/z/.venv/bin/supervisorctl -c /home/z/my-project/.infra/master_supervisord.conf restart services:backend
curl -s http://localhost:3000/health   # → 200
```

**Logs:** `/home/z/my-project/.infra/logs/` — `backend.log` / `backend_err.log` (grep tool failures here), `sandbox_app.log`, `chrome_err.log`.

## LLM provider

- **API_BASE:** `https://integrate.api.nvidia.com/v1` (NVIDIA NIM)
- **MODEL_NAME:** `nvidia/nemotron-3-super-120b-a12b`
- **VISION_MODEL_NAME:** `meta/llama-3.2-11b-vision-instruct` (provider `openai`)
- **SSL_VERIFY=false** is REQUIRED (gateway cert fails Python CA verification — the hook lives in `agents/base.py`)
- NVIDIA's overflow error is `400 {'error': {'code': '1261', 'message': 'Prompt exceeds max length'}}` → see [context-management.md](context-management.md)

## Persistence

- **MongoDB Atlas** (db `manus`) — sessions, events, GridFS artifacts (fs.files/fs.chunks). Junk uploads (node_modules etc.) are filtered before sync; quota 512MB.
- **Redis Cloud** — queue/cache.

## No Docker; E2B optional (hybrid provider)

`SANDBOX_PROVIDER=replit` is the CURRENT setting (in-process supervisord sandbox, user-scoped). E2B is NOT removed — `HybridSandboxFactory` supports `auto`/`e2b`/`replit` with per-user microVMs and automatic fallback; the E2B key is configured and quota verified 2026-08-30 (57/57 tool checks pass identically on both providers — see [tool-verification.md](tool-verification.md)). Never suggest `docker ...`. Agent files are written under the user's sandbox home, not `/tmp`.

## Key agent env knobs (backend/.env — defaults shown)

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_FLOW_ENGINE` | `langgraph` | `langgraph` (PlanActGraphFlow) or `custom` (PlanActFlow) — instant rollback switch |
| `AGENT_CONTEXT_SOFT_LIMIT_CHARS` | `280000` | proactive compaction threshold (0 = off) |
| `AGENT_TOOL_RESULT_MAX_CHARS` | `48000` | per-tool-result entry cap into LLM context (0 = off) |
| `SEARCH_PROVIDER` | `tavily` | baidu / baidu_web / google / bing / bing_web / tavily |
| `BROWSER_ENGINE` | `browser_use` | browser_use (CDP + selector map) or playwright |
| `LOG_LEVEL` | `INFO` | DEBUG for verbose agent traces |

## Test suite state (2026-08-30, after Task 27)

`cd backend && python -m pytest tests/ -q` → **280 passed**; the 14 failed + 19 errors are ALL pre-existing in `test_api_file.py` / `test_auth_routes.py` (they need the live auth service + seeded DB — unrelated to agent code; verified identical via `git stash` on a clean tree).

E2E smoke (real LLM + sandbox): `python /home/z/my-project/scripts/langgraph_e2e_smoke.py` — expects `SMOKE PASSED`, checks full plan lifecycle → done event.

Full tool verification (every tool × both providers): `python /home/z/my-project/scripts/verify_all_tools.py --provider both` — 57 checks per provider incl. UI-visible assertions; and `python /home/z/my-project/scripts/verify_tool_events_e2e.py` — real agent tasks, verifies every persisted ToolEvent has non-null function_result + visible tool_content.
