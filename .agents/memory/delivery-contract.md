# Delivery contract (final-summary single point)

Live-verified 2026-08-31 (sessions 76a44fcc… web, fdb33c88… slide).

## Workspace layout (manual v2)
- `~/project/` root = the 25 scaffolded manual .md files + `skills/` — platform files, NEVER delivered.
- Builds live in `~/project/<app-name>/` subfolders (e.g. `project/kopi-senja/`), the archive lands next to it (`project/<name>.zip`). Standalone documents may sit at home root or project/ root.
- `manual_root_filenames()` in workspace_scaffold.py is the source of truth separating manual root files from task output — guards match by EXACT scaffold set, not by ".md heuristic".

## Delivery semantics (agent_task_runner.py)
- `add_to_session` flag on `_sync_file_to_storage`: mid-task syncs (tool read-backs, artifact sweeps, step attachments) upload CANDIDATES only; the session's visible file list gets files ONLY at the final summary merge (`_sync_message_attachments_to_storage` links + replaces stale same-path entries). This is why the file panel shows ONE zip for a build, not every intermediate version.
- `file_read` NEVER syncs (read-back upload is gated on `_FILE_WRITE_FUNCTIONS`) — fixes the AGENTS.md leak where reading the manual delivered it as a chat file.
- `delivery_ledger.py` (in-process, 48h TTL): automatic sweep candidates already delivered to the same user with identical (path, size) are skipped — fixes cross-session re-delivery when concurrent tasks share one home (hello.txt incident). Explicit model attachments are never ledger-blocked.
- Nets at final merge (unchanged): sanitize oversize zips → drop zip-member loose files → auto-bundle (only when NO zip and ≥2 non-document members).

## Documents vs builds
- .md/.txt/.html/.pptx/.pdf are documents → delivered as loose files, never zipped (user rule: "MD/TXT lightweight tidak perlu zip").
- Build artifacts (html/css/js code folders) → exactly ONE zip.

## Gotchas
- `_handle_tool_event` reads back file content AFTER every file tool call for the viewer (FileToolContent Diff tabs) — display-only, never drives sync on failure.
- Frontend file panel = GET /sessions/{id}/files = session_repository files = final deliverables only.
- Manual re-scaffold triggers on manual-version bump (v2 introduced project-subfolder builds).
