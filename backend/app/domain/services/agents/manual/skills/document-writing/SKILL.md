---
name: document-writing
description: "Long-form documents and structured reports in Markdown: outline first, evidence-backed prose, clean structure, one file delivered."
---

# Document Writing

When the deliverable is a document: reports, analyses, guides, summaries,
articles, specs.

## Workflow
1. **Outline before prose** — 4-8 section headings that answer the request
   in order. If you can't write the outline, you don't understand the task
   yet; re-read it or ask.
2. **Gather what feeds each section** (research, files in upload/, prior
   findings) BEFORE writing. Writing and searching interleaved produces
   half-paragraphs.
3. **Write in the user's language** (see CONTENT.md):
   - title + date + "Disusun oleh Dzeck" line;
   - inverted pyramid: key answer in the first section;
   - paragraphs of 2-4 sentences; headings as signposts;
   - tables for comparisons; code blocks for anything runnable;
   - sources listed with URLs at the end (if research was involved).
4. **Numbers and names**: verbatim from observations, units and timeframes
   attached. Mark assumptions as assumptions.
5. **Write the file** with `file_write` to `<home>/<nama-dokumen>.md`,
   then `file_read` it back (or `file_list_dir`) to confirm it landed.
6. Deliver: attachments = [the .md] (or the .zip if it's part of a build).

## Quality bar
- The 30-second test: open the doc, read only the headings and the first
  paragraph of each — the story should still hold.
- No filler sentences ("perlu diketahui bahwa…", "di era digital…").
- Length serves the content: 2 tight pages beat 10 padded ones.

## Gotchas
- Don't create a document when the user asked a chat question — a file
  nobody asked for is friction, not value.
- If a build task also needs a report (README ≠ report), write it as a
  separate .md and deliver BOTH inside/next to the archive per DEPLOYMENT.md.
