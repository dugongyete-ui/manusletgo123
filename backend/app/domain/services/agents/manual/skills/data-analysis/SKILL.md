---
name: data-analysis
description: "CSV/Excel data work: load, clean, compute, chart (matplotlib), and write a report that explains the numbers — delivered as one project .zip."
---

# Data Analysis

For tasks over tabular data: sales summaries, survey results, log analysis,
"which X is best given this data".

## Workflow
1. **Look at the raw data first** — `shell_exec head -5 <file>.csv` +
   `wc -l`. Column names, separator, encoding, obvious junk. Say what you
   see in one progress line.
2. **Note the input's provenance**: file from `upload/` (user's data) or
   downloaded (say the source URL). Never present generated numbers as
   observed ones.
3. **Clean in Python, keep the recipe**:
```
<home>/<analysis-name>/
  README.md          what this is, how to re-run
  data/              raw input copies (never modify in place)
  analysis.py        load → clean → compute → charts (re-runnable)
  charts/*.png       one chart per question
  <report>.md        the written findings
```
4. **Compute with checks**: totals in == totals out; row counts stable
   through filters; sanity-check one number by hand.
5. **Charts (matplotlib)**: title, axis labels WITH units, source note,
   one question per chart. Save to charts/ (PNG, ~120dpi is enough).
   Chinese/Indonesian text: ensure a font that renders it (Noto) or keep
   chart text English — say which you did.
6. **Write the report**: findings in SENTENCES with the numbers inline
   ("Penjualan Q1 Rp 2,1M — naik 34% dari Q4"), tables for detail,
   charts referenced by filename, methodology + limits at the end.
7. Zip the project folder, verify, deliver the archive (+ nothing loose).

## Gotchas
- pandas needs installing (`pip install pandas matplotlib`) — do it
  before writing the script.
- Excel: `pip install openpyxl` for .xlsx.
- Locale numbers: keep raw digits in tables, formatted ones in prose.
- Empty cells / duplicate rows: your cleaning step handles them — say HOW.
