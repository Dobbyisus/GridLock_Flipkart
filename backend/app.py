from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scoring import ENGINE, recommend_resources


app = FastAPI(
    title="Gridlock Recommendation Engine",
    version="2.0.0",
    description="Event impact scoring, manpower recommendation, diversion planning, routing, alerting, and weekly learning.",
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float
    destination_longitude: float
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
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return ENGINE.get_health_summary()


@app.get("/engine/catalog")
def engine_catalog():
    return ENGINE.get_catalog()


@app.get("/hotspots")
def hotspots(limit: int = 10):
    return {"hotspots": ENGINE.get_top_hotspots(limit=limit)}


@app.get("/dashboard/calendar")
def dashboard_calendar(window: int = Query(default=0, ge=0)):
    return ENGINE.get_calendar_window(window_index=window)


@app.get("/dashboard/calendar/windows")
def dashboard_calendar_windows():
    return ENGINE.list_calendar_windows()


@app.get("/dashboard/day/{date_key}")
def dashboard_day(date_key: str):
    return ENGINE.get_day_dashboard(date_key)


@app.get("/dashboard/review")
def dashboard_review(window: int = Query(default=0, ge=0)):
    return ENGINE.get_review_window(window_index=window)


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
    event_context = None
    if data.event_context:
        predicted = predict(data.event_context)
        event_context = {
            "latitude": data.event_context.latitude,
            "longitude": data.event_context.longitude,
            "impact_score": predicted["impact_score"],
        }
    return ENGINE.recommend_route(
        origin_latitude=data.origin_latitude,
        origin_longitude=data.origin_longitude,
        destination_latitude=data.destination_latitude,
        destination_longitude=data.destination_longitude,
        event_context=event_context,
        alternatives=data.alternatives,
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

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
