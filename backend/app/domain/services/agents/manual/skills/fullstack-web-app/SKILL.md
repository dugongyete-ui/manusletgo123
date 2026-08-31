---
name: fullstack-web-app
description: "Build a complete web application (frontend, optionally backend + data) in the sandbox, verify it actually runs, and deliver it as one .zip archive."
---

# Fullstack Web App

When the user asks for a website, web app, dashboard, shop, game, or any
build with more than a couple of files, this is the playbook.

## When NOT to use
- A single static page with no JS logic → static-landing-page instead.
- A Python HTTP API with no frontend → python-api-service.

## Workflow

### 1. Decide the shape BEFORE writing code
- Frontend only (HTML/CSS/JS, maybe a framework via CDN) or
  frontend + backend (Node/Express or Python/FastAPI)?
- In the sandbox, prefer the SIMPLEST stack that meets the request. Plain
  files run everywhere; heavy frameworks need installs that can fail or
  eat memory. If you do use npm, install FIRST (`npm install` succeeds
  before you write 20 files that depend on it).
- Data that must survive: JSON/SQLite in the project folder.

### 2. Build in a clean project folder
```
<home>/<app-name>/
  README.md           run instructions (prereqs, install, start, verify)
  package.json | requirements.txt
  src/ | app/ | public/ ...
  .env.example        empty values only
```
Create files with `file_write` (never heredocs — heredocs bypass delivery
tracking).

### 3. Run it — the step most skipped, most fatal
- Static: `python3 -m http.server 8000 --directory <home>/<app>` → it keeps
  running; use `shell_view` to confirm, then `browser_navigate
  http://localhost:8000` to SEE it.
- Node: `npm install && npm start` (or `node src/server.js`); wait for the
  listen log BEFORE navigating.
- Python API: `uvicorn app.main:app --port 8000` (or `python3 -m ...`).

### 4. Verify in the browser, not in hope
- `browser_navigate` the local URL → read the returned title/elements.
- Click the main flow once (add item, submit form) → confirm the page
  changed (`page_changed`, new text, new count).
- Screenshot if the user will care about looks.
- Check the browser console for red errors via `browser_console_view`.

### 5. Kill the server, then package
`shell_kill_process` for EVERY session you started. Then build the archive
with the python zipfile recipe in DEPLOYMENT.md (exclude node_modules,
.git, __pycache__, .env, *.pyc, *.log). Verify with `python3 -m zipfile -l`.

### 6. Deliver
Final attachments = [the .zip] (plus a standalone summary .md if you wrote
one). State what you verified: "server jalan, flow utama diklik,
integritas zip OK".

## Environment notes (shared container vs E2B)
- Same techniques on both hosts. Shared container: check `free -m` before
  heavy installs; avoid leaving processes running (you share the box).
- E2B: full VM, more headroom — same cleanup discipline applies.
- The `zip` binary may be absent → always use python zipfile.

## Gotchas
- `npm install` in a watched folder can loop with dev servers — install
  before starting the watcher.
- Port already in use → pick another (8100+), don't fight for 3000.
- localStorage keys collide between apps on the same origin — prefix them
  with the app name.
