# GridLock Handoff

## Project snapshot
- Project: `GridLock_Round2`
- Stack: `FastAPI` backend + static frontend (`HTML/CSS/JS`) + Leaflet map UI
- Current default mode: historical dashboard
- Live mode is now implemented as a second dashboard mode entered via `Go Live`
- The old cinema/live scraper mode is still intentionally not being reintroduced

## What is currently implemented

### 1) Dual dashboard modes
- Dashboard opens in historical mode by default
- A topbar `Go Live` control switches between:
  - `historical` mode
  - `live` mode
- Historical mode keeps the original date-window workflow
- Live mode keeps the same layout and cards, but swaps the data behavior to today-only live monitoring

### 2) Historical dashboard flow
- Weekly timeline / date navigation remains active
- Weekly review flow remains available after the usual unlock conditions
- Manual events still attach to the selected historical date
- Weekly correction UI still exists in historical mode

### 3) Live dashboard flow
- Live mode uses a backend-managed in-process hourly refresh
- Refresh starts when the backend starts
- Refresh stops when the backend stops
- Live data is session-scoped in memory
- Live timeline area is reused for today-only snapshots rather than historical weekly playback
- Live review tab is placeholder-only for now

### 4) Live hotspot selection behavior
- Live mode does **not** scrape arbitrary citywide traffic
- It monitors a shortlist of historically strong hotspot nodes derived from the dataset
- That shortlist is now broader than the original live implementation:
  - `LIVE_PROBE_LIMIT = 12`
  - `LIVE_EVENT_LIMIT = 12`
- For each live probe:
  - Google Routes traffic-aware routing is requested on refresh
  - Google traffic signals are converted into a live congestion severity score
- Missing event metadata is backfilled from historical context

### 5) Historical-context fallback logic for live mode
- Historical fallback is now **hour-band aware**
- It does **not** use one specific historical date
- It prefers nearby historical events that occurred around the same local hour across all dates
- This historical context is used to infer:
  - corridor
  - junction
  - zone
  - police station
  - likely cause / priority / closure tendency / event type

### 6) Live hotspot naming cleanup
- Live hotspots no longer inherit raw historical operator descriptions/comments as titles
- Instead, live labels are derived from corridor / junction / zone context
- This avoids old Kannada/operator notes showing up in live detail cards

### 7) Route planner behavior
- Route planner is still hotspot-first
- Operator selects a hotspot, then the system suggests routes from the assigned police station to the congestion source
- Google Routes + GridLock reranking is still present
- Fallback routing remains available when Google routing is unavailable

### 8) On-demand hotspot impact drilldown
- Each hotspot in the left feed now has a `More Info` button
- This was added specifically to avoid making Google calls for every hotspot by default
- The backend only fetches extra impact detail when that button is clicked
- The modal currently shows:
  - road-level affected stretches
  - spillover / diversion corridors
  - nearest police station
  - impact score and recommended field metrics
- Lane-level exactness is **not** available in the current Google-backed setup; the UI explicitly says this

### 9) Manual event feature
- `Add Event` remains in the map top-right controls
- Operators can still add a manual event using:
  - date
  - time
  - title
  - Bengaluru location / landmark
  - cause
  - priority
  - optional attendance
  - road closure flag
- Backend still resolves coordinates using local historical matching, not external geocoding
- Manual events are still persisted in:
  - `backend/manual_events.json`
- Manual events are still merged into:
  - day dashboard
  - calendar counts
  - review window
  - route planner selection flow
- In live mode, manual events effectively attach to today

### 10) Weekly correction and learning behavior
- Weekly correction learning is now session-scoped
- On backend restart:
  - feedback log starts fresh in memory
  - retraining state is effectively session-only
  - previous feedback is not reused for the new session
- Frontend correction history is invalidated by backend session ID
- Weekly correction summaries still use local storage, but only for the active backend session

### 11) Station alert email flow
- `Raise Station Alert` is now wired end-to-end
- It no longer uses Resend
- It now sends through Gmail SMTP using env-configured credentials
- The alert email contains a structured operational summary including:
  - hotspot title
  - source
  - location / corridor / zone
  - nearest police station
  - impact score
  - risk level
  - officers / marshals / barricades / sign boards
  - diversion requirement / suggestions
  - alert message

## Current UI state

### Branding
- Main Kannada title is `ಸಂಚಾರ`
- English `Sanchara` appears beside it in smaller font
- Eyebrow/subscript remains in English

### Left panel
- Main operations panel remains horizontally resizable
- Hotspot feed itself is now independently vertically resizable
- Hotspot feed size persists in local storage

### Live mode UI notes
- `Go Live` now matches the header pill/button system more closely
- The mode pill is `Historical Mode` in historical view and `Live Mode` / `Live Mode (Stale Cache)` in live view

## Backend/API changes currently present

### Historical endpoints retained
- `GET /dashboard/calendar`
- `GET /dashboard/calendar/windows`
- `GET /dashboard/day/{date_key}`
- `GET /dashboard/review`
- `POST /dashboard/events/manual`

### Live endpoints added
- `GET /dashboard/live/status`
- `GET /dashboard/live/calendar`
- `GET /dashboard/live/calendar/windows`
- `GET /dashboard/live/day/{snapshot_key}`
- `GET /dashboard/live/review`

### On-demand hotspot detail endpoint
- `GET /hotspots/{event_id}/impact-details`

### Station alert endpoint
- `POST /alerts/station-email`

## Config/env currently expected

### Google Routes
- Existing Google Maps / Google Routes config is still used for routing and live probing

### Gmail SMTP for station alerts
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=<gmail address>`
- `SMTP_PASSWORD=<gmail app password>`
- `ALERT_EMAIL_FROM=Operator Alert <same gmail address>`
- `ALERT_EMAIL_TO=shashwattiwari884@gmail.com`

## Known limitations
- Live mode is hotspot-network-based, not full-map congestion extraction
- Lane-level exact impact is not available from the current Google-backed approach
- Live hotspot metadata is still inferred from historical context where Google cannot provide structure
- Manual-event location matching is still local and heuristic-based
- If a typed location does not match the known dataset context well enough, manual event creation still fails with a helpful error
- Gmail SMTP is good for demo/manual alerting but should not be treated as unlimited production email capacity

## Files changed most recently

### Backend
- `backend/app.py`
  - Added live endpoints
  - Added station alert email endpoint
  - Added Gmail SMTP transport for alert sending

- `backend/engine.py`
  - Added live monitor / cache / session handling
  - Added live hotspot selection and scoring logic
  - Added hour-band-aware historical fallback for live mode
  - Added on-demand hotspot impact-detail builder
  - Added session-scoped learning behavior

- `backend/google_routes.py`
  - Extended route calls to support configurable routing preference

### Frontend
- `frontend/index.html`
  - Added `Go Live`
  - Added hotspot impact modal
  - Added hotspot feed resize handle
  - Updated branding to `ಸಂಚಾರ` + `Sanchara`

- `frontend/app.js`
  - Added dashboard mode switching
  - Added live polling/status handling
  - Added hotspot `More Info` behavior
  - Added station alert send behavior
  - Added hotspot feed resize persistence
  - Added session-aware correction-history invalidation

- `frontend/styles.css`
  - Added live-mode header/button tweaks
  - Added hotspot impact modal styling
  - Added hotspot feed resizer styling
  - Added branding layout styling

## Suggested next steps

### High-value UX / product improvements
1. Add edit / delete support for manual events
2. Add a stronger live hotspot diversity strategy, for example per-corridor coverage instead of globally strongest nodes only
3. Add richer road-impact visuals directly on the map when `More Info` is opened
4. Improve station-alert send feedback with a clearer success/error panel instead of toast-only messaging
5. Add a small live-mode freshness indicator near the timeline or banner

### Higher-fidelity traffic improvements
1. Add same-weekday + same-hour fallback weighting instead of hour-only weighting
2. Expand live probe generation to use more corridor approach pairs, not only station-to-hotspot probes
3. Add operator-supplied lane notes if lane-level field intelligence is needed

## Recommended next-chat starting prompt
Use this if continuing in a new chat:

> Read `C:\Users\Shashwat Tiwari\Desktop\GridLock_Round2\handoff.md` first. We now have both historical and live dashboard modes. Live mode uses hourly Google-backed hotspot probing over historically strong nodes, with hour-band-aware historical fallback for missing metadata. Weekly correction is session-scoped, station alerts send via Gmail SMTP, each hotspot has on-demand `More Info`, and the hotspot feed is resizable. Please inspect the current implementation and continue from the suggested next steps without reintroducing the old scraper mode.
