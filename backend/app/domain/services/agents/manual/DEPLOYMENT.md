# DEPLOYMENT.md

Packaging and delivery — the last mile, where most "failed successes" happen.

## What the user receives
- **Document task** → the document file itself (e.g. `laporan.md`).
- **Build task** → ONE `.zip` archive containing the complete project.
  The archive is the deliverable. Loose member files are NEVER attached
  next to it (the platform also enforces this — don't fight it, use it).

## Building the archive (python zipfile — the zip binary is not guaranteed)
```sh
cd <home>/project
python3 - <<'PY'
import zipfile, os
EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist-cache"}
EXCLUDE_FILES = {".env", ".DS_Store"}
root = "my-app-name"            # the build subfolder inside project/
out = "my-app-name.zip"          # the archive lands next to it, in project/
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in filenames:
            if f in EXCLUDE_FILES or f.endswith((".pyc", ".log")):
                continue
            p = os.path.join(dirpath, f)
            z.write(p, p)
print("wrote", out, os.path.getsize(out), "bytes")
PY
```

## Verify BEFORE finishing (mandatory)
```sh
python3 -m zipfile -l <home>/project/<name>.zip     # every expected file listed?
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("<home>/project/<name>.zip")
bad = z.testzip()   # None means every member is intact
flat = [n for n in z.namelist() if "/" not in n and not n.endswith("/")]
print("corrupt member:", bad)
print("flat members (MUST be empty):", flat)
PY
```
If the listing misses files you intended, rebuild the archive — don't
hand-wave it in the summary. If `flat members` is NOT empty the archive
is a flat dump — rebuild it properly (walk the project FOLDER as in the
recipe above, `z.write(p, p)` with the folder as the arcname prefix).

## Archive hygiene
- The zip contains the project FOLDER (`my-app-name/...`), not a flat dump —
  unzipping creates one clean directory. NEVER `z.write(p, os.path.basename(p))`
  — that flattens everything and the user extracts a pile of loose files
  with no folders.
- Every member path inside the archive must contain `/` (a directory
  component): `my-app-name/index.html`, `my-app-name/src/App.tsx`.
- Secrets never enter archives (.env excluded, .env.example included).
- Name it after the project, kebab-case: `kopi-shop.zip`, not `final2.zip`.

## In the final message
List ONLY the archive path in attachments (plus a standalone summary
document if one exists). State what was verified: "archive berisi 14 file,
integritas OK, aplikasi sudah dijalankan sebelum dikemas".
