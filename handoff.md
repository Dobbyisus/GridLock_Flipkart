# GridLock Handoff

## Project snapshot
- Project: `GridLock_Round2`
- Stack: `FastAPI` backend + static frontend (`HTML/CSS/JS`) + Leaflet map UI
- Current default mode: historical dashboard only
- Live / cinema-congestion scraper mode was intentionally rolled back

## What is currently implemented

### 1) Historical dashboard flow
- Dashboard opens in historical mode.
- Weekly timeline / date navigation remains active.
- Weekly review flow remains available after the usual unlock conditions.

### 2) Route planner improvements
- Route planner is hotspot-first.
- Operator selects a hotspot, then the system suggests routes from the assigned police station to the congestion source.
- Google Routes + GridLock reranking logic is still present.
- Fallback routing remains available when Google routing is unavailable.

### 3) Weekly correction UI
- Weekly correction uses a styled panel with a short loading state.
- After completion, the summary can collapse into an info icon for later reopening.
- Weekly correction summaries are stored in frontend local storage.

### 4) Manual event feature
- Added a top-right map control: `Add Event`
- This avoids cluttering the left operations panel.
- Operators can add a manual event for the currently selected historical date.
- Manual events are persisted locally in:
  - `backend/manual_events.json`
- Manual events are merged into:
  - day dashboard
  - calendar counts
  - review window
  - route planner selection flow

## Important manual-event behavior

### Engine-computed scoring
- Operators do **not** enter impact score.
- Operators do **not** enter lat/lon anymore.
- The backend computes:
  - matched coordinates
  - impact score
  - risk level
  - resource plan
  - diversions

### Address-first location matching
- Manual event form now asks for:
  - date
  - time
  - event title
  - Bengaluru location / landmark
  - cause
  - priority
  - optional attendance
  - road closure flag
- Backend derives lat/lon from Bengaluru location text using a local matcher built from the existing historical dataset.
- This is **not external geocoding**.
- Best results happen when the operator enters known Bengaluru-style labels like:
  - roads
  - junctions
  - corridors
  - metro-adjacent landmarks
  - police stations
  - common areas / zones

## Files changed recently

### Backend
- `backend/app.py`
  - Added manual event request model
  - Added `POST /dashboard/events/manual`
  - Returns `422` with readable error if location cannot be matched

- `backend/engine.py`
  - Added manual event persistence
  - Added local Bengaluru location reference index
  - Added address-to-coordinate matching
  - Added manual events into day dashboard / calendar / review flow

### Frontend
- `frontend/index.html`
  - Added `Add Event` button in the map top-right controls
  - Added floating manual-event modal
  - Replaced lat/lon inputs with a single Bengaluru location input + datalist hints

- `frontend/app.js`
  - Added manual event modal logic
  - Loads backend catalog for cause options + location hints
  - Submits address-first manual events
  - Reloads selected date after save
  - Surfaces backend location-match errors in toast

- `frontend/styles.css`
  - Added manual event modal styling
  - Added manual event badge styling in event feed

## Known limitations
- Manual-event location matching is local and heuristic-based.
- If a typed location does not resemble known dataset locations closely enough, event creation will fail with a helpful message.
- Runtime browser validation was blocked in the last chat because the local dashboard server was not running at `127.0.0.1:8000`.
- Python compile/test validation was also blocked in this environment due local interpreter launch restrictions.

## Suggested next steps

### High-value UX improvements
1. Add a matched-location preview before final event save
2. Add edit / delete support for manual events
3. Add a “manual” filter/tag in the dashboard feed
4. Improve location matching confidence and synonym coverage

### If external APIs are allowed later
1. Replace local location matching with Google Geocoding
2. Show exact resolved point before save
3. Use Places autocomplete for operator-friendly location entry

## Recommended next-chat starting prompt
Use this if continuing in a new chat:

> Read `C:\Users\Shashwat Tiwari\Desktop\GridLock_Round2\handoff.md` first. We currently have a historical-only GridLock dashboard with hotspot-first routing and a new manual event feature. The manual event form is address-first and the backend computes coordinates and impact score. Please inspect the current implementation and continue from the “Suggested next steps” section without reintroducing the rolled-back live scraper mode.

