---
name: web-research
description: "Multi-source web research with evidence: search, open pages in the real browser, triangulate, and produce one cited .md report."
---

# Web Research

For tasks whose deliverable is knowledge: market overviews, comparisons,
fact-checks, "find the latest X", person/company profiles.

## Workflow
1. **Frame the question set**: decompose the request into 3-6 concrete
   questions that, answered, complete the task. Say them in your first
   progress line.
2. **Search wide, then go primary**:
   `info_search_web` → 2-3 query variants (different phrasings, +English
   AND the user's language for local topics). From results pick PRIMARY
   sources: official pages, docs, filings, reputable outlets — not
   aggregators quoting aggregators.
3. **Open before citing**: `browser_navigate` the promising URL. Read what
   actually rendered (the browser observation IS your evidence). Snippets
   and search-result titles are hints, never citations.
4. **Record the register as you go**: for each usable source — URL, title,
   site, access date, and which fact it supports. This becomes the source
   list of the report.
5. **Triangulate key facts**: two independent origins = "confirmed".
   One source = labelled. Contradiction = report both + your weighing.
6. **Write the report** (see CONTENT.md + document-writing skill):
   inverted pyramid, conclusion first; tables for comparisons; source
   list at the end; honest "tidak ditemukan / belum terverifikasi" lines.
7. Deliver: ONE .md file in attachments. Nothing else.

## Environment notes
- The browser is a real Chrome — pages render JS. If a page needs login
  the user didn't provide, note it and move on.
- Heavy bot-protected sites: try the search cache or an alternative source
  rather than hammering.
- image_search_web can add a map/diagram if it genuinely helps.

## Gotchas
- Dates matter: prefer the newest source for time-sensitive claims and
  note when data is older than the question implies.
- Wikipedia is a fine STARTING point (follow its citations), rarely the
  final citation.
- Don't pad with background paragraphs — the user asked a question.
