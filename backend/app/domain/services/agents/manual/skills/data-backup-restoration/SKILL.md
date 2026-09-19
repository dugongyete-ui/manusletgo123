---
name: data-backup-restoration
description: Back up project data and restore it reliably. Use when the user asks to back up a database, website, or project folder, to migrate data between environments, or to recover from a broken state.
---

# Data Backup and Restoration

## When to Use

- Before risky changes: schema migrations, bulk edits, refactors of a data layer
- The user explicitly asks for a backup, snapshot, export, or migration
- A deliverable holds user data (SQLite, uploads, generated files) worth protecting

## Backup Patterns

1. **SQLite**
   - Consistent copy: `sqlite3 app.db ".backup 'backups/app-YYYYMMDD-HHMM.db'"`
     (a plain `cp` of a live DB can capture a half-written state — use `.backup`).
2. **File trees**
   - `tar -czf backups/project-YYYYMMDD-HHMM.tar.gz --exclude='node_modules'
     --exclude='.venv' -C <parent> <folder>` — exclude dependencies, include data.
3. **Uploads / media**
   - Separate archive from code; large media gets its own tarball with a manifest
     (`find uploads -type f | sort > uploads.manifest.txt`).
4. **Databases of a running web app**
   - Stop the app or use the DB's snapshot facility first; verify by restoring.

## Restoration Contract

- A backup without a tested restore is a rumor. For every backup, run the
  restore into a temp directory and diff/check row counts before declaring done.
- Document the exact restore commands in `backups/RESTORE.md`:
  where files live, what each archive contains, restore order (schema → data → media).
- Name archives with source + timestamp; never overwrite a previous backup.

## Delivery

- Default location: `<project>/backups/` with the RESTORE.md beside it.
- Off-site copy: upload the tarball via the deliverable/download flow so the
  user can stash it outside the sandbox.
- Keep a manifest (path, size, sha256) so integrity is verifiable later.
