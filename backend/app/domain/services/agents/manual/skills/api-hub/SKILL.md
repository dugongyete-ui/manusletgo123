---
name: api-hub
description: Curated hub for choosing and integrating third-party APIs. Use when the user asks "is there an API for X", wants to compare API options for a feature, or needs an integration checklist for a paid/free API in a deliverable.
---

# API Hub

## When to Use

- The user asks whether an API exists for a capability (maps, payments, weather, mail…)
- A build needs an external service and the options must be compared honestly
- An integration must be wired into a deliverable the right way

## Choosing an API (decision order)

1. **Capability fit** — does it actually do the thing the user asked for?
2. **Auth model** — plain API key (simplest), OAuth (user-authorized data), or none.
3. **Free tier reality** — monthly quota, watermark/branding requirements,
   required credit card. State the limit in the deliverable README.
4. **Stability** — official provider beats a scraped/internal endpoint; check
   the docs URL resolves and note the version you integrated against.
5. **Exit cost** — wrap the client in one module so swapping providers later
   touches one file, not the whole app.

## Integration Checklist (per integration)

- [ ] Key from environment variable (`.env` + `.env.example` shipped; never committed)
- [ ] Timeout + retry-with-backoff on 429/5xx (max 3, honor `Retry-After`)
- [ ] Response validated (required fields present) before use
- [ ] Failure mode defined: cached data, degraded UI, or explicit error — never a crash
- [ ] Quota note in README ("free tier: 100 calls/day — plan accordingly")

## Common Categories (starting points, verify current docs before wiring)

- **Maps/geocoding**: Nominatim (free, attribution required), Mapbox, Google Maps
- **Weather**: Open-Meteo (keyless), OpenWeatherMap
- **Email sending**: Resend, Postmark, SES (needs AWS creds)
- **Payments**: Stripe (test mode keys for development)
- **Search/web data**: Tavily, Brave Search API

## Honesty Rules

- Never fabricate an endpoint or response shape — check the docs or say it is
  unverified. An invented API is worse than no API.
- If every option needs a key the user hasn't given, ship the integration with
  a mock provider and a clear "set KEY to go live" note.
