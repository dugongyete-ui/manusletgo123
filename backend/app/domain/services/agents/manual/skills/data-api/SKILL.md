---
name: data-api
description: Consume data from public or authenticated web APIs robustly. Use when the user asks to pull data from an API (weather, finance, sports, government open data), merge it, transform it, or keep a local copy in sync.
---

# Data API

## When to Use

- The deliverable needs live data from a public or keyed API
- The user asks to build a dataset from an API source
- A dashboard or report must refresh from an upstream endpoint

## Robust Consumption Checklist

1. **Read the docs for auth and limits first.** Note: auth scheme (key, Bearer,
   OAuth), rate limit (per second/day), pagination style (page, cursor, link
   header), and licensing of the data.
2. **One module per source.** Isolate fetching in a single module exposing
   `fetch_x() -> list[dict]`; never let raw HTTP calls scatter across the app.
3. **Timeouts and retries are mandatory.**
   `httpx.get(url, timeout=15)` + retry with exponential backoff on 429/5xx
   (max 3, honor `Retry-After`). A missing timeout is a hung deliverable.
4. **Cache locally.** Write raw responses to disk (JSON) keyed by query+date;
   serve reads from cache on failure (stale-but-useful beats down).
5. **Validate the shape.** Check required fields and types after parsing;
   log-and-skip bad rows instead of crashing the whole pull.
6. **Persist incrementally.** For large pulls, write to SQLite or JSONL as
   pages arrive; a crash must not lose what already came down.

## Presentation

- Small datasets: JSON/CSV file the user can download.
- Recurring needs: combine with the automation-and-scheduling skill.
- Numeric analysis: hand the data to pandas/openpyxl deliverables.

## Honesty Rules

- Cite the API and the retrieval date in the deliverable ("source: …, pulled 2026-09-20").
- If an endpoint needs a key the user hasn't provided, deliver the full pipeline
  plus a mock sample response, and mark clearly what runs once the key is set.
- Never fabricate data to fill a failed API call — report the failure.
