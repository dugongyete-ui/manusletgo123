---
name: packaging-delivery
description: "The last mile: build ONE clean .zip with python zipfile, exclude junk and secrets, verify integrity, and attach only the archive."
---

# Packaging & Delivery

Everything about the archive the user receives. This skill is the
enforcement detail behind DEPLOYMENT.md's contract.

## What goes in
- The whole project folder: source, README, assets, seed data,
  `.env.example`.
- Nothing else. Scratch scripts, logs, caches, lockfiles, downloaded
  installers stay OUT.

## What stays out (hard excludes)
node_modules/ · .git/ · __pycache__/ · venv/ .venv/ · *.pyc · *.log ·
.env (REAL secrets — never) · .DS_Store

## Structure (the #1 rule)
The archive mirrors the REAL project tree — every member path must carry
its folder(s): `my-app/index.html`, `my-app/src/App.tsx`,
`my-app/client/vite.config.ts`. NEVER `z.write(p, os.path.basename(p))`
or a per-file flat zip: extracting a flat dump scatters loose files with
no folders (users hate it, the platform rebuilds it anyway — don't fight
the net).

## Build (python zipfile — zip binary not guaranteed)
```sh
cd <home>
python3 - <<'PY'
import zipfile, os
EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv"}
SKIP_FILES = {".env", ".DS_Store"}
SKIP_EXT = (".pyc", ".log")
root, out = "my-app", "my-app.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS]
        for f in fn:
            if f in SKIP_FILES or f.endswith(SKIP_EXT):
                continue
            z.write(os.path.join(dp, f))   # arcname keeps the folder path
print("wrote", out, os.path.getsize(out))
PY
```
(os.walk starts INSIDE the project folder, so every member name keeps
`my-app/...` — that is exactly what you want.)

## Verify (before you attach anything)
```sh
python3 -m zipfile -l <home>/my-app.zip        # listing: every file you expect?
python3 -c "import zipfile; print('corrupt:', zipfile.ZipFile('<home>/my-app.zip').testzip())"
python3 -c "import zipfile; print('flat:', [n for n in zipfile.ZipFile('<home>/my-app.zip').namelist() if '/' not in n])"
```
- Listing missing a file you intended? Rebuild. Never "fix" it in prose.
- testzip() must print `corrupt: None`.
- `flat:` must print `[]` — any bare filename means the archive lost its
  folder structure. Rebuild it.

## Attach
- Final attachments: the .zip path ONLY (+ a standalone summary document
  if one exists as a separate deliverable).
- NEVER the members next to the archive — the platform also drops them,
  but your attachment list should already be correct.

## Naming
Kebab-case, what-it-is: `kopi-shop.zip`, `analisis-penjualan-2026.zip`.
Never `final.zip`, `project2.zip`, `output.zip`.

## Gotchas
- Zip the FOLDER so unzip creates one clean dir, not a file-spill.
- Size sanity: a 40MB "static site" zip means you packaged junk — check
  the listing for node_modules/venv leakage.
- Created the zip inside the project dir by accident? Move it out to
  <home> and rebuild (zip-inside-itself is invalid).
