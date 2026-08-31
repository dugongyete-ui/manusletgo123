---
name: python-api-service
description: "REST APIs in Python (FastAPI or Flask): build, run, test every endpoint with real curl calls, document, and deliver as one .zip."
---

# Python API Service

When the deliverable is an HTTP API: data service, webhook handler,
small backend for a frontend.

## Choose the frame
- FastAPI: modern, pydantic validation, auto /docs. Install:
  `pip install fastapi uvicorn` (in the sandbox this is quick).
- Flask: simpler for tiny endpoints, fewer concepts.
- Plain http.server: only for the most trivial static JSON.

## Workflow
1. Design the surface FIRST: write the endpoint table into README.md —
   method, path, body, response, example. This becomes your test plan.
2. Project shape:
```
<home>/<service-name>/
  README.md          endpoints + how to run + curl examples
  requirements.txt   pinned versions
  app/main.py        (FastAPI app or Flask app)
  app/models.py      pydantic models / data classes
  data/              seed JSON / SQLite if persistence is asked
  .env.example
```
3. Build with `file_write`, run with `uvicorn app.main:app --port 8000`
   from the project root. Confirm the startup log via `shell_view`.
4. **Test like a user**: `shell_exec curl -s http://localhost:8000/items`
   for EVERY endpoint — read the JSON, say the key field out loud in your
   progress message ("GET /items → 12 item, sesuai seed"). Test the error
   path too: wrong ID → 404 shape, bad body → 422.
5. Persistence check: POST something → restart the server → GET it back.
   Only claim persistence if you watched it survive a restart.
6. Kill the server. Zip (python zipfile, excludes in DEPLOYMENT.md).
   Verify listing + integrity. Deliver the archive only.

## Gotchas
- CORS: if a browser page will call this API, enable CORS explicitly or
  say the limitation in the README.
- `uvicorn --reload` spawns watchers — use plain mode and
  `shell_kill_process` after.
- Don't hardcode the DB path relative to CWD — resolve from `__file__`.
