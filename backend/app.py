from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
import smtplib
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .google_routes import _load_config_value
    from .scoring import ENGINE, recommend_resources
except ImportError:
    from google_routes import _load_config_value
    from scoring import ENGINE, recommend_resources


app = FastAPI(
    title="Gridlock Recommendation Engine",
    version="2.0.0",
    description="Event impact scoring, manpower recommendation, diversion planning, routing, alerting, and weekly learning.",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_ALERT_EMAIL_FROM = "Operator Alert <shashwattiwari884@gmail.com>"


class PredictionRequest(BaseModel):
    event_cause: str
    priority: str
    requires_road_closure: bool
    latitude: float
    longitude: float
    event_type: str = "unplanned"
    start_datetime: Optional[datetime] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None
    expected_attendance: Optional[int] = Field(default=None, ge=0)


class RouteRequest(BaseModel):
    event_id: Optional[str] = None
    origin_latitude: Optional[float] = None
    origin_longitude: Optional[float] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    origin_station_name: Optional[str] = None
    event_context: Optional[PredictionRequest] = None
    alternatives: int = Field(default=3, ge=1, le=4)


class FeedbackRequest(BaseModel):
    event_reference_id: Optional[str] = None
    event_cause: str
    priority: str
    requires_road_closure: bool
    latitude: float
    longitude: float
    event_type: str = "unplanned"
    start_datetime: Optional[datetime] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None
    expected_attendance: Optional[int] = Field(default=None, ge=0)
    actual_impact_score: float = Field(ge=0, le=100)
    observed_severity: Optional[str] = None
    observed_crowd_level: Optional[str] = None
    actual_clearance_minutes: Optional[int] = Field(default=None, ge=0)
    field_officers_deployed: Optional[int] = Field(default=None, ge=0)
    field_barricades_used: Optional[int] = Field(default=None, ge=0)
    diversion_effectiveness: Optional[str] = None
    source: str = "manual_dashboard"
    notes: Optional[str] = None


class ManualEventRequest(BaseModel):
    date: str
    time: str
    title: str
    address: str
    event_cause: str
    priority: str
    requires_road_closure: bool = False
    event_type: str = "planned"
    expected_attendance: Optional[int] = Field(default=None, ge=0)


class StationAlertRequest(BaseModel):
    event_id: str
    recipient_email: str


def _smtp_host() -> Optional[str]:
    return _load_config_value("SMTP_HOST", PROJECT_ROOT)


def _smtp_port() -> int:
    raw_value = _load_config_value("SMTP_PORT", PROJECT_ROOT, "587") or "587"
    try:
        return int(raw_value)
    except ValueError:
        return 587


def _smtp_username() -> Optional[str]:
    return _load_config_value("SMTP_USERNAME", PROJECT_ROOT)


def _smtp_password() -> Optional[str]:
    return _load_config_value("SMTP_PASSWORD", PROJECT_ROOT)


def _alert_email_from() -> str:
    return _load_config_value("ALERT_EMAIL_FROM", PROJECT_ROOT, DEFAULT_ALERT_EMAIL_FROM) or DEFAULT_ALERT_EMAIL_FROM


def _is_valid_recipient_email(value: str) -> bool:
    _, parsed = parseaddr((value or "").strip())
    return bool(parsed and "@" in parsed and " " not in parsed)


def _station_alert_subject(event: dict) -> str:
    risk_level = event.get("risk_level", "Alert")
    title = event.get("title", "Hotspot")
    return f"GridLock Station Alert | {risk_level} | {title}"


def _station_alert_text(event: dict, origin_station: dict) -> str:
    resource_plan = event.get("resource_plan", {})
    diversion_suggestions = event.get("diversion_suggestions", [])
    diversion_text = ", ".join(
        f"{item.get('corridor', 'Unknown')} via {item.get('via_junction', 'Unknown')}"
        for item in diversion_suggestions
    ) or "Direct corridor management preferred"
    alert_message = (event.get("alert") or {}).get("message", "Field review required.")
    return "\n".join(
        [
            "GridLock Station Alert",
            "",
            f"Alert Time: {datetime.utcnow().isoformat()}Z",
            f"Hotspot: {event.get('title', '--')}",
            f"Source: {event.get('event_source', 'historical').title()}",
            f"Location: {event.get('address', '--')}",
            f"Corridor: {event.get('corridor', '--')}",
            f"Zone: {event.get('zone', '--')}",
            f"Nearest Police Station: {origin_station.get('station_name', '--')}",
            f"Impact Score: {event.get('impact_score', '--')}",
            f"Risk Level: {event.get('risk_level', '--')}",
            f"Traffic Officers Required: {resource_plan.get('traffic_officers_required', '--')}",
            f"Traffic Marshals Required: {resource_plan.get('traffic_marshals_required', '--')}",
            f"Barricades Required: {resource_plan.get('barricades_required', '--')}",
            f"Message Sign Boards: {resource_plan.get('message_sign_boards_required', '--')}",
            f"Diversion Required: {'Yes' if event.get('diversion_required') else 'No'}",
            f"Diversion Suggestions: {diversion_text}",
            f"Alert Message: {alert_message}",
        ]
    )


def _station_alert_html(event: dict, origin_station: dict) -> str:
    resource_plan = event.get("resource_plan", {})
    diversion_suggestions = event.get("diversion_suggestions", [])
    diversion_items = "".join(
        f"<li>{item.get('corridor', 'Unknown')} via {item.get('via_junction', 'Unknown')}</li>"
        for item in diversion_suggestions
    ) or "<li>Direct corridor management preferred</li>"
    alert_message = (event.get("alert") or {}).get("message", "Field review required.")
    return f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:720px;margin:0 auto;color:#10224f">
      <h2 style="margin-bottom:8px;">GridLock Station Alert</h2>
      <p style="margin-top:0;color:#64748b;">Operator alert generated for the selected hotspot.</p>
      <table style="width:100%;border-collapse:collapse;border:1px solid #dde3ee;">
        <tbody>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Alert Time</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{datetime.utcnow().isoformat()}Z</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Hotspot</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('title', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Source</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{str(event.get('event_source', 'historical')).title()}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Location</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('address', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Corridor</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('corridor', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Zone</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('zone', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Nearest Police Station</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{origin_station.get('station_name', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Impact Score</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('impact_score', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Risk Level</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{event.get('risk_level', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Traffic Officers</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{resource_plan.get('traffic_officers_required', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Traffic Marshals</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{resource_plan.get('traffic_marshals_required', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Barricades</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{resource_plan.get('barricades_required', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Message Sign Boards</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{resource_plan.get('message_sign_boards_required', '--')}</td></tr>
          <tr><td style="padding:10px;border:1px solid #dde3ee;"><strong>Diversion Required</strong></td><td style="padding:10px;border:1px solid #dde3ee;">{'Yes' if event.get('diversion_required') else 'No'}</td></tr>
        </tbody>
      </table>
      <div style="margin-top:18px;">
        <strong>Diversion Suggestions</strong>
        <ul>{diversion_items}</ul>
      </div>
      <div style="margin-top:18px;padding:12px 14px;border-radius:12px;background:#f7f8fb;border:1px solid #dde3ee;">
        <strong>Alert Message</strong>
        <p style="margin:8px 0 0;">{alert_message}</p>
      </div>
    </div>
    """.strip()


def _send_station_alert_email(event: dict, origin_station: dict, recipient_email: str) -> dict:
    smtp_host = _smtp_host()
    smtp_username = _smtp_username()
    smtp_password = _smtp_password()
    if not smtp_host or not smtp_username or not smtp_password:
        raise HTTPException(status_code=503, detail="SMTP credentials are not fully configured.")

    message = EmailMessage()
    message["Subject"] = _station_alert_subject(event)
    message["From"] = _alert_email_from()
    message["To"] = recipient_email
    message.set_content(_station_alert_text(event, origin_station))
    message.add_alternative(_station_alert_html(event, origin_station), subtype="html")
    try:
        with smtplib.SMTP(smtp_host, _smtp_port(), timeout=15) as smtp_client:
            smtp_client.ehlo()
            smtp_client.starttls()
            smtp_client.ehlo()
            smtp_client.login(smtp_username, smtp_password)
            smtp_client.send_message(message)
        return {
            "transport": "smtp",
            "host": smtp_host,
            "recipient": recipient_email,
        }
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(status_code=502, detail="SMTP authentication failed. Check the Gmail app password.") from exc
    except smtplib.SMTPException as exc:
        raise HTTPException(status_code=502, detail=f"SMTP rejected the alert email: {exc}") from exc


@app.get("/")
def root():
    return {
        "message": "Gridlock Recommendation Engine Running",
        "version": app.version,
        "capabilities": [
            "impact_prediction",
            "resource_recommendation",
            "diversion_suggestions",
            "route_recommendation",
            "threshold_alerting",
            "weekly_learning",
            "hotspot_catalog",
        ],
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.on_event("startup")
def startup_live_monitor():
    ENGINE.start_live_monitor()


@app.on_event("shutdown")
def shutdown_live_monitor():
    ENGINE.stop_live_monitor()


@app.get("/health")
def health():
    return ENGINE.get_health_summary()


@app.get("/engine/catalog")
def engine_catalog():
    return ENGINE.get_catalog()


@app.get("/hotspots")
def hotspots(limit: int = 10):
    return {"hotspots": ENGINE.get_top_hotspots(limit=limit)}


@app.get("/hotspots/{event_id}/impact-details")
def hotspot_impact_details(event_id: str):
    try:
        return ENGINE.get_hotspot_impact_details(event_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/dashboard/calendar")
def dashboard_calendar(window: int = Query(default=0, ge=0)):
    return ENGINE.get_calendar_window(window_index=window)


@app.get("/dashboard/calendar/windows")
def dashboard_calendar_windows():
    return ENGINE.list_calendar_windows()


@app.get("/dashboard/day/{date_key}")
def dashboard_day(date_key: str):
    return ENGINE.get_day_dashboard(date_key)


@app.post("/dashboard/events/manual")
def create_manual_event(data: ManualEventRequest):
    try:
        event = ENGINE.create_manual_event(
            date=data.date,
            time_text=data.time,
            title=data.title,
            address=data.address,
            event_cause=data.event_cause,
            priority=data.priority,
            requires_road_closure=data.requires_road_closure,
            event_type=data.event_type,
            expected_attendance=data.expected_attendance,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"event": event}


@app.post("/alerts/station-email")
def send_station_alert(data: StationAlertRequest):
    recipient_email = data.recipient_email.strip()
    if not _is_valid_recipient_email(recipient_email):
        raise HTTPException(status_code=422, detail="Recipient email is required to send a station alert.")
    route_context = ENGINE.get_route_context(data.event_id)
    if not route_context:
        raise HTTPException(status_code=404, detail="Selected hotspot was not found.")
    provider_response = _send_station_alert_email(
        route_context["destination_event"],
        route_context["origin_station"],
        recipient_email,
    )
    return {
        "sent": True,
        "recipient": recipient_email,
        "provider": "smtp",
        "provider_response": provider_response,
    }


@app.get("/dashboard/review")
def dashboard_review(window: int = Query(default=0, ge=0)):
    return ENGINE.get_review_window(window_index=window)


@app.get("/dashboard/live/status")
def dashboard_live_status():
    return ENGINE.get_live_status()


@app.get("/dashboard/live/calendar")
def dashboard_live_calendar(window: int = Query(default=0, ge=0)):
    return ENGINE.get_live_calendar_window(window_index=window)


@app.get("/dashboard/live/calendar/windows")
def dashboard_live_calendar_windows():
    return ENGINE.list_live_calendar_windows()


@app.get("/dashboard/live/day/{snapshot_key}")
def dashboard_live_day(snapshot_key: str):
    return ENGINE.get_live_day_dashboard(snapshot_key)


@app.get("/dashboard/live/review")
def dashboard_live_review(window: int = Query(default=0, ge=0)):
    return ENGINE.get_live_review_window(window_index=window)


@app.post("/predict")
def predict(data: PredictionRequest):
    return recommend_resources(
        event_cause=data.event_cause,
        priority=data.priority,
        requires_road_closure=data.requires_road_closure,
        latitude=data.latitude,
        longitude=data.longitude,
        event_type=data.event_type,
        start_datetime=data.start_datetime,
        end_latitude=data.end_latitude,
        end_longitude=data.end_longitude,
        expected_attendance=data.expected_attendance,
    )


@app.post("/events/assess")
def assess_event(data: PredictionRequest):
    assessment = predict(data)
    return {
        "assessment": assessment,
        "threshold_alert": assessment["alert"],
    }


@app.post("/alerts/evaluate")
def evaluate_alert(data: PredictionRequest):
    assessment = predict(data)
    return {
        "impact_score": assessment["impact_score"],
        "risk_level": assessment["risk_level"],
        "alert": assessment["alert"],
    }


@app.post("/routes/recommend")
def recommend_route(data: RouteRequest):
    origin_station = None
    destination_event = None
    event_context = None
    origin_latitude = data.origin_latitude
    origin_longitude = data.origin_longitude
    destination_latitude = data.destination_latitude
    destination_longitude = data.destination_longitude

    if data.event_id:
        route_context = ENGINE.get_route_context(data.event_id)
        if not route_context:
            raise HTTPException(status_code=404, detail="Selected event was not found.")
        destination_event = route_context["destination_event"]
        origin_station = route_context["origin_station"]
        origin_latitude = origin_station["latitude"]
        origin_longitude = origin_station["longitude"]
        destination_latitude = destination_event["latitude"]
        destination_longitude = destination_event["longitude"]
        event_context = {
            "latitude": destination_event["latitude"],
            "longitude": destination_event["longitude"],
            "impact_score": destination_event["impact_score"],
        }
    elif data.event_context:
        predicted = predict(data.event_context)
        event_context = {
            "latitude": data.event_context.latitude,
            "longitude": data.event_context.longitude,
            "impact_score": predicted["impact_score"],
        }
        if data.origin_station_name:
            origin_station = ENGINE._station_payload(data.origin_station_name)
    if None in (origin_latitude, origin_longitude, destination_latitude, destination_longitude):
        raise HTTPException(
            status_code=422,
            detail="Route request requires either event_id or explicit origin/destination coordinates.",
        )
    return ENGINE.recommend_route(
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        destination_latitude=destination_latitude,
        destination_longitude=destination_longitude,
        event_context=event_context,
        alternatives=data.alternatives,
        origin_station=origin_station,
        destination_event=destination_event,
    )


@app.post("/feedback/log")
def log_feedback(data: FeedbackRequest):
    payload = data.model_dump()
    actual_impact_score = payload.pop("actual_impact_score")
    source = payload.pop("source")
    notes = payload.pop("notes")
    if payload.get("start_datetime") is not None:
        payload["start_datetime"] = payload["start_datetime"].isoformat()
    return ENGINE.log_feedback(
        event_payload=payload,
        actual_impact_score=actual_impact_score,
        notes=notes,
        source=source,
    )


@app.get("/learning/state")
def learning_state():
    return ENGINE.get_learning_state()


@app.post("/learning/retrain")
def retrain_learning():
    return ENGINE.retrain_model(force=True)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
