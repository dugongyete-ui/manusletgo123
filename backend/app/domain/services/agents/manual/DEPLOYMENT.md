# DEPLOYMENT.md

Packaging and delivery — the last mile, where most "failed successes" happen.

## What the user receives
- **Document task** → the document file itself (e.g. `laporan.md`).
- **Build task** → ONE `.zip` archive containing the complete project.
  The archive is the deliverable. Loose member files are NEVER attached
  next to it (the platform also enforces this — don't fight it, use it).

## Building the archive (python zipfile — the zip binary is not guaranteed)
```sh
cd <home>
python3 - <<'PY'
import zipfile, os
EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist-cache"}
EXCLUDE_FILES = {".env", ".DS_Store"}
root = "my-app-name"
out = "my-app-name.zip"
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
python3 -m zipfile -l <home>/<name>.zip     # every expected file listed?
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("<home>/<name>.zip")
bad = z.testzip()   # None means every member is intact
print("corrupt member:", bad)
PY
```
If the listing misses files you intended, rebuild the archive — don't
hand-wave it in the summary.

## Archive hygiene
- The zip contains the project FOLDER (`my-app-name/...`), not a flat dump —
  unzipping creates one clean directory.
- Secrets never enter archives (.env excluded, .env.example included).
- Name it after the project, kebab-case: `kopi-shop.zip`, not `final2.zip`.

## In the final message
List ONLY the archive path in attachments (plus a standalone summary
document if one exists). State what was verified: "archive berisi 14 file,
integritas OK, aplikasi sudah dijalankan sebelum dikemas".
