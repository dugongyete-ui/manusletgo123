---
name: packaging-delivery
description: "The last mile: build ONE clean .zip with python zipfile, exclude junk and secrets, verify integrity, and attach only the archive."
---

# Packaging & Delivery

Everything about the archive the user receives. This skill is the
enforcement detail behind DEPLOYMENT.md's contract.

## What goes in
- The whole project folder: source, README, lockfile, assets, seed data,
  `.env.example`.
- Nothing else. Scratch scripts, logs, caches, downloaded installers stay
  OUT.

## What stays out (hard excludes)
node_modules/ · .git/ · __pycache__/ · venv/ .venv/ · *.pyc · *.log ·
.env (REAL secrets — never) · .DS_Store

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
            z.write(os.path.join(dp, f))
print("wrote", out, os.path.getsize(out))
PY
```

## Verify (before you attach anything)
```sh
python3 -m zipfile -l <home>/my-app.zip        # listing: every file you expect?
python3 -c "import zipfile; print('corrupt:', zipfile.ZipFile('<home>/my-app.zip').testzip())"
```
- Listing missing a file you intended? Rebuild. Never "fix" it in prose.
- testzip() must print `corrupt: None`.

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
