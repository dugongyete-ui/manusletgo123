# RULES.md

Hard rules. They override convenience and never bend to task pressure.

## Workspace
1. Stay inside YOUR user home. The application's own source tree is
   off-limits — never read, list, archive, or transmit it. See SECURITY.md.
2. Build outputs go in their own folder (`<home>/<app-name>/`), never inside
   `project/` (this manual) or `upload/` (user's incoming files).
3. This manual is read-only for you. Do not edit, rename, zip, or "clean" it.

## Doing the work
4. Use `file_write` to create files; shell heredocs bypass delivery tracking
   and the user may never see the result. Shell is for running, not making.
5. Never claim a file, page, or command succeeded without having seen the
   evidence (listing, observation, output) in the same step.
6. If a blocker is real (login wall, paywall, access denied, quota), say so
   plainly. Do not simulate success around it.

## Communicating
7. Progress messages are text only — no attachments mid-task. Files are
   delivered once, at the end, with the final summary.
8. Keep each progress message under 300 characters, with intent or
   interpretation — never bare tool announcements.
9. One language: the user's language. Filenames too, when reasonable.

## Delivering
10. Multi-file build → ONE .zip archive, verified before finishing.
    Single document → the file itself. Never both at once for the same files.
11. Never deliver secrets (.env, keys, tokens) inside any archive or file.
12. Never leave the task in "probably done" — done means verified, or the
    final result explains exactly what remains and why.
