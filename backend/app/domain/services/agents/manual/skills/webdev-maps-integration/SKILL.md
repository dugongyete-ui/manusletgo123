---
name: webdev-maps-integration
description: Fullstack web app builds — Google Maps integration for maps, geocoding, directions, places (user-provided key) with a zero-key Leaflet fallback.
---

## 🗺️ Maps Integration

**No proxy here — the key question comes first.** Google Maps JS API runs client-side with a standard API key: when maps are genuinely required, ASK the user for their key (or whether they have one). Load it via env-driven config, never hardcoded. A normal key unlocks the full standard feature set: Places, Geocoder, Directions, Drawing, Street View.

**Default: frontend SDK** - Build `client/src/components/Map.tsx` exposing a MapView with an onMapReady callback; initialize whatever Maps service the feature needs (geocoding, directions, places, drawing) inside it. 

**Use Backend API only when:**
- Persisting data (save routes/locations to database)
- Bulk operations (1000+ addresses)
- Server-side needs (caching, scheduled jobs, hiding business logic)

**Implementation:**
- Frontend: See `client/src/components/Map.tsx` for component usage - ALL Google Maps JavaScript API features work
- Backend: create tRPC procedures that call the Maps REST APIs server-side (key from env) when persisting routes or doing bulk geocoding

**Zero-key fallback:** if the user has no key, Leaflet + OpenStreetMap tiles covers display, markers, and basic geocoding with no account at all — offer it instead of blocking the build.
