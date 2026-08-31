# PROJECT.md

Conventions for THIS workspace's projects — the defaults you apply unless
the user or the task says otherwise.

## Naming
- Project folder & archive: kebab-case of what it is (`todo-app/`,
  `landing-kopi.zip`, `analisis-penjualan/`).
- Documents: the user's words for it (`laporan-keuangan-q1.md`).
- Scratch/temp files: keep them out of the project folder entirely; delete
  before delivery.

## Defaults by build type
- Static site → plain HTML/CSS/JS unless the user asked for a framework.
  Served and screenshot-verified before packaging.
- Web app → minimal dependency footprint; README with run steps; lockfile
  included; verified by actually starting it.
- API → README documents every endpoint with one curl example each.
- Data/analysis → `data/` (inputs), `charts/` (PNGs), report .md at root.

## Where things live
```
<home>/
  project/            ← this manual (read-only, never your output)
  upload/             ← files the user sent (read, don't modify)
  <app-name>/         ← YOUR build output for this task
  <name>.md           ← YOUR document output for this task
  <name>.zip          ← the archive you deliver
```

## Per-task adjustments
If the user's request implies different conventions (they name a folder,
ask for a specific structure, bring a repo in upload/), follow THEIR
convention — and note the deviation in the final summary so future tasks
in this workspace stay consistent.
