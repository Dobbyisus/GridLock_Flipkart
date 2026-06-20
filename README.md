# SANCHARA

SANCHARA is a traffic monitoring and operations platform built for proactive congestion management. It helps operators identify high-impact hotspots, understand likely disruption severity, plan field response, recommend routes, and continuously improve decisions through weekly feedback-driven correction.

The project combines a FastAPI backend, a lightweight frontend dashboard, historical traffic intelligence, live Google Routes probing, and an adaptive scoring workflow designed for demo-ready operational visibility.

## Overview

SANCHARA is centered around three connected backend engines:

- `Impact Scoring Engine`  
  Estimates congestion severity and operational risk using event cause, priority, hotspot relevance, timing, spread, and contextual traffic signals.
- `Live Scoring Engine`  
  Calls Google Routes to measure current traffic conditions and merges those signals with historical context to rescore live hotspots.
- `Weekly Retraining Engine`  
  Compares predicted impact with reviewed field outcomes and adjusts model behavior for future scoring accuracy.

## Key Features

- Historical dashboard for hotspot exploration across calendar windows
- Live hotspot monitoring with real-time rescoring
- Event impact estimation and risk classification
- Resource recommendation for officers, marshals, barricades, and diversions
- Route guidance using Google Routes API
- Station alert email workflow with runtime recipient input
- Weekly review and correction workflow for adaptive learning
- Manual event creation for demos and operator simulation

## Tech Stack

- `Backend:` Python, FastAPI, Uvicorn
- `Frontend:` HTML, CSS, JavaScript
- `Mapping:` Leaflet
- `Traffic Intelligence:` Google Routes API
- `Email Alerts:` SMTP / Gmail app password flow

## Repository Structure

```text
GridLock_Round2/
|-- backend/
|   |-- app.py
|   |-- engine.py
|   |-- google_routes.py
|   |-- scoring.py
|   |-- requirements.txt
|   `-- data/
|-- frontend/
|   |-- index.html
|   |-- app.js
|   `-- styles.css
|-- requirements.txt
`-- handoff.md
```

## Prerequisites

Before running SANCHARA locally, make sure you have:

- Python `3.10+`
- `pip`
- A valid `Google Maps / Routes API` key
- SMTP credentials if you want the station alert email feature to work

## Environment Setup

This repository does **not** include an `.env` file. You must create your own and supply your own credentials before running the project.

You can place your environment file in either of these locations:

- `backend/.env`
- project-root `.env`

### Required variable

```env
GOOGLE_MAPS_API_KEY=your_google_maps_api_key
```

### Optional variables for station alerts

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
ALERT_EMAIL_FROM=Operator Alert <your_email@gmail.com>
```

### Optional tuning variables

```env
GOOGLE_ROUTES_TIMEOUT_SECONDS=6.0
GOOGLE_ROUTES_MAX_ALTERNATIVES=3
```

### Notes

- `ALERT_EMAIL_TO` is **not required**.
- The station alert recipient is entered by the viewer at runtime in the dashboard.
- If SMTP credentials are missing, the rest of the platform still works, but station alert emails will not send.

## Installation

From the repository root:

```bash
pip install -r backend/requirements.txt
```

If you prefer using a virtual environment:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Running Locally

Start the application from the repository root:

```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open the dashboard in your browser:

```text
http://127.0.0.1:8000/dashboard
```

## Suggested Demo Flow

1. Open the historical dashboard and inspect the mapped hotspots.
2. Select a hotspot to review impact score, risk level, and recommended field response.
3. Use route guidance to inspect operational routing suggestions.
4. Switch to live mode to see live rescoring with Google traffic signals.
5. Add a session email and trigger `Raise Station Alert`.
6. Open `Weekly Review` to log reviewed outcomes and run correction.

## Useful Endpoints

- `GET /dashboard` - main SANCHARA dashboard
- `GET /health` - service health and runtime summary
- `GET /dashboard/live/status` - live engine status and refresh metadata
- `GET /learning/state` - current weekly learning state

## Demo Behavior Notes

- Manual demo events are session-scoped and reset on backend restart.
- Weekly correction state is designed for demo usage and can be reset with a fresh backend session.
- Live mode depends on a valid backend-side Google Maps API key.
- Station alerts use backend-side SMTP credentials and do not expose them in the frontend.

## Deployment

SANCHARA can be deployed as a single web service because the FastAPI backend also serves the frontend assets.

### Recommended demo deployment commands

Build:

```bash
pip install -r backend/requirements.txt
```

Start:

```bash
uvicorn backend.app:app --host 0.0.0.0 --port $PORT
```

### Environment variables for deployment

At minimum, configure:

- `GOOGLE_MAPS_API_KEY`

For station alert emails, also configure:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL_FROM`

## Problem SANCHARA Solves

Traffic operators often struggle with:

- uncertain event impact before congestion escalates
- delayed resource deployment after hotspots form
- disconnected historical, live, and field feedback signals

SANCHARA addresses this by unifying monitoring, prediction, response planning, and learning into one operational workflow.

## Status

This project is currently structured as a polished demo platform and operational prototype rather than a production-hardened deployment.

## License

This repository currently does not include an explicit license file. Add one before public redistribution if needed.
