---
name: gws-best-practices
description: Work with Google Workspace content (Docs, Sheets, Drive files) from the sandbox. Use when the user shares Google Docs/Sheets links, asks to export or import Google formats, or wants an app that reads/writes Google Workspace data.
---

# Google Workspace Best Practices

## When to Use

- The user pastes Google Docs / Sheets / Drive links into the task
- A deliverable must produce content Google formats can round-trip
- The user wants an app integration with Google Workspace

## Reading Google Content Without a Browser

- **Public Google Sheets**: append `/gviz/tq?tqx=out:csv` to the sheet URL to
  get CSV directly — parse with pandas or the csv module. This is the fastest
  reliable path and needs no key when the sheet is link-shared.
- **Public Google Docs**: use the `/export?format=txt` (or `md`) export URL on
  a link-shared doc to pull plain text.
- **Drive links** that are not public cannot be read — say so and ask the user
  for a link-shared URL or an exported file upload.

## Writing Content Google Can Ingest

- Sheets: deliver `.xlsx` or CSV (Sheets imports both cleanly; xlsx preserves types).
- Docs: deliver `.docx` (imports with formatting) or Markdown for copy-paste.
- Slides: follow the pptx skill pipeline — pptx imports into Google Slides.

## App Integrations (when the user's app must talk to Google)

- Use the official `google-api-python-client` + user-supplied OAuth credentials;
  the app reads client secrets from environment variables, never committed files.
- Scope requests minimally (read-only scopes unless writing is required).
- Handle token refresh and expired-token errors explicitly.

## Honesty Rules

- Never claim to have read a non-public Google link.
- Round-trip check: after generating a Google-ingestable file, re-open it and
  verify the first rows/paragraphs survived before delivering.
