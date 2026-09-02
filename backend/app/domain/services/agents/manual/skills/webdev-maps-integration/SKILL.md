---
name: webdev-maps-integration
description: Dzeck webdev fullstack (web-db-user) projects — Google Maps integration for maps, geocoding, directions, places.
---

## 🗺️ Maps Integration

**CRITICAL: decide the maps stack WITH the user.** Google Maps JS API runs client-side with a standard API key — ALL features work (advanced drawing, heatmaps, Street View, all layers, Places API) with a normal key. Ask the user for their key when maps are required; if they have none, Leaflet + OpenStreetMap tiles is the zero-key fallback. Authentication is NOT automatic here — no proxy injects a key.

**Default: Use Frontend SDK** - Import MapView from `client/src/components/Map.tsx` and initialize ANY Google Maps service (geocoding, directions, places, drawing, visualization, geometry, etc.) in the onMapReady callback. 

**Use Backend API only when:**
- Persisting data (save routes/locations to database)
- Bulk operations (1000+ addresses)
- Server-side needs (caching, scheduled jobs, hiding business logic)

**Implementation:**
- Frontend: See `client/src/components/Map.tsx` for component usage - ALL Google Maps JavaScript API features work
- Backend: Create tRPC procedures using `makeRequest` from `server/_core/map.ts`

NEVER hardcode keys into source or commit them — load from env config. Do not silently pick a stack the user didn't choose; decide with them.
