---
name: Runtime environment (Replit hybrid)
description: Current workflow topology, active sandbox provider, and verification caveats for this Replit workspace.
---

## Runtime topology (verified 2026-08-30)

The active workspace is `/home/runner/workspace` and services are managed by Replit workflows:

| Service | Port | Notes |
|---|---:|---|
| Frontend (Vite) | 5000 | Preview/webview target |
| Backend (FastAPI) | 8000 | API and health endpoint |
| Sandbox API | 8080 | Local file/shell/browser API |
| Chrome CDP | 8222 | Headless Chrome used by `browser_use` |
| VNC websocket | 5901 | websockify → x11vnc → Xvfb |

The active workflow configuration is `.replit`; there is no active z-container master supervisor in this workspace. MongoDB Atlas and Redis Cloud are the persistence services.

## Sandbox provider status

The configured value is `SANDBOX_PROVIDER=auto`, which asks `HybridSandboxFactory` to try E2B and then fall back to the local Replit sandbox. The current runtime has E2B configuration present, but the `e2b` Python package is not installed. A live factory smoke therefore selected `ReplitSandbox` (`replit-local`) after `ModuleNotFoundError`.

The E2B implementation remains in the codebase, but the historical both-provider verification belongs to another environment and must not be treated as current proof until the dependency is installed and the live E2B smoke is rerun.

## LLM and safety caveats

- NVIDIA NIM is the configured primary LLM gateway; `SSL_VERIFY=false` is currently required by that gateway.
- Local sandbox source protection defaults to `/home/runner/workspace`; tests that create relative files below the repository can be rejected by design.
- The local VNC service currently runs without a password and Chrome uses relaxed flags intended for the isolated sandbox; do not expose these ports publicly without an access boundary.

## Verification state (2026-08-30)

- Backend suite: **313 passed** after the backend service was already ready. The initial parallel Project workflow run failed only because its API test connected before port 8000 was ready.
- Backend imports/syntax: passed.
- Frontend type-check and production build: passed, with a CSS nesting warning and a large main chunk warning.
- Sandbox suite: **9 passed, 1 failed** because `test_upload_file_success` writes below the protected repository path and then attempts to read it; this is a test-harness/configuration mismatch, not proof that the sandbox API is unavailable.
