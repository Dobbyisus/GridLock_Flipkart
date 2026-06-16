import csv
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "ProblemStatement2_Data_Gridlock.csv"
STATE_PATH = BASE_DIR / "learning_state.json"
FEEDBACK_PATH = BASE_DIR / "event_feedback_log.json"

BENGALURU_CENTER = (12.9716, 77.5946)

ALERT_THRESHOLDS = {
    "critical": 82.0,
    "high": 66.0,
    "medium": 48.0,
}

RISK_TO_RESPONSE = {
    "Low": {
        "officers": 4,
        "barricades": 6,
        "message_sign_boards": 1,
        "diversion_depth": "micro diversion at the nearest junction",
    },
    "Medium": {
        "officers": 8,
        "barricades": 12,
        "message_sign_boards": 2,
        "diversion_depth": "one corridor-level diversion",
    },
    "High": {
        "officers": 14,
        "barricades": 20,
        "message_sign_boards": 3,
        "diversion_depth": "multi-junction diversion with field supervision",
    },
    "Critical": {
        "officers": 22,
        "barricades": 30,
        "message_sign_boards": 4,
        "diversion_depth": "full corridor diversion and command post",
    },
}

CROWD_CAUSES = {"public_event", "procession", "protest", "vip_movement"}

DEFAULT_WEIGHTS = {
    "cause": 0.24,
    "priority": 0.10,
    "road_closure": 0.16,
    "hotspot": 0.20,
    "corridor": 0.12,
    "temporal": 0.08,
    "spread": 0.10,
}

DEFAULT_STATE = {
    "weights": DEFAULT_WEIGHTS,
    "bias": 0.0,
    "learning_rate": 0.10,
    "retrain_window_days": 7,
    "last_retrained_at": "2026-01-01T00:00:00+00:00",
    "cause_adjustments": {},
    "last_training_summary": {},
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "NULL", "null"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def clean_text(value: Any, default: str = "Unknown") -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "null":
        return default
    return text


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value or str(value).strip().lower() == "null":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def haversine_km(start: Tuple[float, float], end: Tuple[float, float]) -> float:
    lat1, lon1 = start
    lat2, lon2 = end
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    arc = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius_km * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def percentile(sorted_values: List[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(clamp(fraction, 0.0, 1.0) * (len(sorted_values) - 1))
    return sorted_values[index]


class GridlockRecommendationEngine:
    def __init__(
        self,
        data_path: Path = DATA_PATH,
        state_path: Path = STATE_PATH,
        feedback_path: Path = FEEDBACK_PATH,
    ) -> None:
        self.data_path = data_path
        self.state_path = state_path
        self.feedback_path = feedback_path
        self.events = self._load_events()
        self.analytics = self._build_analytics(self.events)
        self.state = self._load_state()
        self.feedback_log = self._load_feedback_log()

    def _load_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        with self.data_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            for row in reader:
                latitude = safe_float(row.get("latitude"))
                longitude = safe_float(row.get("longitude"))
                if latitude is None or longitude is None:
                    continue
                if not (12.70 <= latitude <= 13.25 and 77.35 <= longitude <= 77.80):
                    continue
                end_latitude = safe_float(row.get("endlatitude"))
                end_longitude = safe_float(row.get("endlongitude"))
                if end_latitude == 0:
                    end_latitude = None
                if end_longitude == 0:
                    end_longitude = None
                start_dt = parse_datetime(row.get("start_datetime"))
                end_dt = (
                    parse_datetime(row.get("resolved_datetime"))
                    or parse_datetime(row.get("closed_datetime"))
                    or parse_datetime(row.get("end_datetime"))
                )
                duration_hours = None
                if start_dt and end_dt and end_dt >= start_dt:
                    duration_hours = (end_dt - start_dt).total_seconds() / 3600
                grid_id = f"{round(latitude, 2):.2f}_{round(longitude, 2):.2f}"
                corridor = clean_text(row.get("corridor"))
                junction = clean_text(row.get("junction"))
                zone = clean_text(row.get("zone"))
                cause = clean_text(row.get("event_cause"), "others").lower()
                priority = clean_text(row.get("priority"), "Low").title()
                event_type = clean_text(row.get("event_type"), "unplanned").lower()
                status = clean_text(row.get("status"), "closed").lower()
                path_distance_km = 0.0
                if end_latitude and end_longitude:
                    path_distance_km = haversine_km(
                        (latitude, longitude), (end_latitude, end_longitude)
                    )
                events.append(
                    {
                        "id": row.get("id") or str(uuid.uuid4()),
                        "latitude": latitude,
                        "longitude": longitude,
                        "end_latitude": end_latitude,
                        "end_longitude": end_longitude,
                        "event_cause": cause,
                        "priority": priority,
                        "requires_road_closure": safe_bool(
                            row.get("requires_road_closure")
                        ),
                        "event_type": event_type,
                        "status": status,
                        "corridor": corridor,
                        "junction": junction,
                        "zone": zone,
                        "grid_id": grid_id,
                        "start_datetime": start_dt,
                        "duration_hours": duration_hours,
                        "path_distance_km": path_distance_km,
                    }
                )
        return events

    def _build_analytics(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        hotspot_counts: Dict[str, int] = {}
        corridor_counts: Dict[str, int] = {}
        cause_counts: Dict[str, int] = {}
        graph_points: Dict[str, Dict[str, Any]] = {}
        durations: List[float] = []
        path_lengths: List[float] = []

        for event in events:
            hotspot_counts[event["grid_id"]] = hotspot_counts.get(event["grid_id"], 0) + 1
            corridor_counts[event["corridor"]] = corridor_counts.get(event["corridor"], 0) + 1
            cause_counts[event["event_cause"]] = cause_counts.get(event["event_cause"], 0) + 1
            if event["duration_hours"] is not None:
                durations.append(min(event["duration_hours"], 24.0))
            if event["path_distance_km"] > 0:
                path_lengths.append(min(event["path_distance_km"], 8.0))
            if event["grid_id"] not in graph_points:
                graph_points[event["grid_id"]] = {
                    "grid_id": event["grid_id"],
                    "latitude": round(event["latitude"], 2),
                    "longitude": round(event["longitude"], 2),
                    "corridor": event["corridor"],
                    "junction": event["junction"],
                    "zone": event["zone"],
                    "count": 0,
                }
            graph_points[event["grid_id"]]["count"] += 1

        durations.sort()
        path_lengths.sort()
        max_hotspot = max(hotspot_counts.values()) if hotspot_counts else 1

        cause_totals: Dict[str, List[float]] = {}
        priority_totals: Dict[str, List[float]] = {}
        closure_totals: Dict[bool, List[float]] = {True: [], False: []}
        corridor_totals: Dict[str, List[float]] = {}
        hour_totals: Dict[int, List[float]] = {}
        weekday_totals: Dict[int, List[float]] = {}
        grid_totals: Dict[str, List[float]] = {}
        event_type_totals: Dict[str, List[float]] = {}

        for event in events:
            duration_component = 0.0
            if event["duration_hours"] is not None:
                duration_component = (
                    math.log1p(min(event["duration_hours"], 24.0)) / math.log1p(24.0)
                ) * 100.0
            closure_component = 100.0 if event["requires_road_closure"] else 22.0
            priority_component = 90.0 if event["priority"].lower() == "high" else 38.0
            status_component = {
                "active": 95.0,
                "resolved": 70.0,
                "closed": 54.0,
            }.get(event["status"], 50.0)
            spread_component = 0.0
            if path_lengths and event["path_distance_km"] > 0:
                spread_component = min(event["path_distance_km"], 8.0) / 8.0 * 100.0
            hotspot_component = hotspot_counts[event["grid_id"]] / max_hotspot * 100.0
            proxy_score = (
                (0.30 * duration_component)
                + (0.22 * closure_component)
                + (0.16 * priority_component)
                + (0.10 * status_component)
                + (0.08 * spread_component)
                + (0.14 * hotspot_component)
            )
            event["historical_proxy_score"] = round(clamp(proxy_score, 0.0, 100.0), 2)

            cause_totals.setdefault(event["event_cause"], []).append(proxy_score)
            priority_totals.setdefault(event["priority"].title(), []).append(proxy_score)
            closure_totals[event["requires_road_closure"]].append(proxy_score)
            corridor_totals.setdefault(event["corridor"], []).append(proxy_score)
            grid_totals.setdefault(event["grid_id"], []).append(proxy_score)
            event_type_totals.setdefault(event["event_type"], []).append(proxy_score)
            if event["start_datetime"]:
                hour_totals.setdefault(event["start_datetime"].hour, []).append(proxy_score)
                weekday_totals.setdefault(event["start_datetime"].weekday(), []).append(proxy_score)

        graph_nodes = list(graph_points.values())
        graph_edges = self._build_graph_edges(graph_nodes)

        return {
            "event_count": len(events),
            "top_causes": sorted(cause_counts.items(), key=lambda item: item[1], reverse=True),
            "top_corridors": sorted(
                corridor_counts.items(), key=lambda item: item[1], reverse=True
            ),
            "hotspot_scores": {
                grid_id: round(count / max_hotspot * 100.0, 2)
                for grid_id, count in hotspot_counts.items()
            },
            "cause_scores": self._average_map(cause_totals),
            "priority_scores": self._average_map(priority_totals),
            "closure_scores": {
                str(key).lower(): round(sum(values) / len(values), 2)
                for key, values in closure_totals.items()
                if values
            },
            "corridor_scores": self._average_map(corridor_totals),
            "grid_scores": self._average_map(grid_totals),
            "event_type_scores": self._average_map(event_type_totals),
            "hour_scores": {key: round(sum(values) / len(values), 2) for key, values in hour_totals.items()},
            "weekday_scores": {
                key: round(sum(values) / len(values), 2) for key, values in weekday_totals.items()
            },
            "duration_p95": round(percentile(durations, 0.95), 2),
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
        }

    def _average_map(self, mapping: Dict[str, List[float]]) -> Dict[str, float]:
        return {
            key: round(sum(values) / len(values), 2)
            for key, values in mapping.items()
            if values
        }

    def _build_graph_edges(self, nodes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        edges: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            distances: List[Tuple[float, str, Dict[str, Any]]] = []
            for candidate in nodes:
                if candidate["grid_id"] == node["grid_id"]:
                    continue
                distance_km = haversine_km(
                    (node["latitude"], node["longitude"]),
                    (candidate["latitude"], candidate["longitude"]),
                )
                if distance_km <= 7.5:
                    distances.append((distance_km, candidate["grid_id"], candidate))
            distances.sort(key=lambda item: item[0])
            edges[node["grid_id"]] = []
            for distance_km, grid_id, candidate in distances[:6]:
                edges[node["grid_id"]].append(
                    {
                        "to": grid_id,
                        "distance_km": round(distance_km, 3),
                        "corridor": candidate["corridor"],
                    }
                )
        return edges

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            with self.state_path.open("r", encoding="utf-8") as file_obj:
                state = json.load(file_obj)
        else:
            state = dict(DEFAULT_STATE)
            self._save_json(self.state_path, state)
        merged = dict(DEFAULT_STATE)
        merged.update(state)
        merged["weights"] = dict(DEFAULT_WEIGHTS) | dict(state.get("weights", {}))
        merged["cause_adjustments"] = dict(state.get("cause_adjustments", {}))
        return merged

    def _load_feedback_log(self) -> List[Dict[str, Any]]:
        if self.feedback_path.exists():
            with self.feedback_path.open("r", encoding="utf-8") as file_obj:
                return json.load(file_obj)
        self._save_json(self.feedback_path, [])
        return []

    def _save_json(self, path: Path, payload: Any) -> None:
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, indent=2)

    def get_catalog(self) -> Dict[str, Any]:
        return {
            "known_event_causes": [name for name, _ in self.analytics["top_causes"]],
            "known_corridors": [name for name, _ in self.analytics["top_corridors"][:20]],
            "alert_thresholds": ALERT_THRESHOLDS,
            "weights": self.state["weights"],
            "retrain_window_days": self.state["retrain_window_days"],
        }

    def get_health_summary(self) -> Dict[str, Any]:
        return {
            "dataset_path": str(self.data_path),
            "historical_events_loaded": self.analytics["event_count"],
            "feedback_records": len(self.feedback_log),
            "last_retrained_at": self.state["last_retrained_at"],
            "top_hotspots": self.get_top_hotspots(limit=5),
        }

    def get_top_hotspots(self, limit: int = 10) -> List[Dict[str, Any]]:
        ranked = sorted(
            self.analytics["hotspot_scores"].items(),
            key=lambda item: item[1],
            reverse=True,
        )
        hotspots: List[Dict[str, Any]] = []
        for grid_id, score in ranked[:limit]:
            lat_text, lon_text = grid_id.split("_")
            hotspots.append(
                {
                    "grid_id": grid_id,
                    "latitude": float(lat_text),
                    "longitude": float(lon_text),
                    "hotspot_risk": score,
                }
            )
        return hotspots

    def _temporal_score(self, when: Optional[datetime]) -> float:
        if not when:
            when = datetime.now(timezone.utc)
        hour_score = self.analytics["hour_scores"].get(when.hour, 50.0)
        weekday_score = self.analytics["weekday_scores"].get(when.weekday(), 50.0)
        return round((hour_score * 0.55) + (weekday_score * 0.45), 2)

    def _nearest_grid_score(self, latitude: float, longitude: float) -> float:
        grid_id = f"{round(latitude, 2):.2f}_{round(longitude, 2):.2f}"
        if grid_id in self.analytics["grid_scores"]:
            return self.analytics["grid_scores"][grid_id]
        nearest_score = 35.0
        nearest_distance = float("inf")
        for known_grid, score in self.analytics["grid_scores"].items():
            grid_lat, grid_lon = known_grid.split("_")
            distance_km = haversine_km(
                (latitude, longitude), (float(grid_lat), float(grid_lon))
            )
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_score = score
        distance_penalty = clamp(nearest_distance / 8.0, 0.0, 0.4)
        return round(clamp(nearest_score * (1 - distance_penalty), 15.0, 95.0), 2)

    def _corridor_score(self, latitude: float, longitude: float) -> Tuple[float, str]:
        nearest_score = 35.0
        nearest_corridor = "Unknown"
        nearest_distance = float("inf")
        for node in self.analytics["graph_nodes"]:
            distance_km = haversine_km(
                (latitude, longitude), (node["latitude"], node["longitude"])
            )
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_corridor = node["corridor"]
                nearest_score = self.analytics["corridor_scores"].get(
                    nearest_corridor, self.analytics["grid_scores"].get(node["grid_id"], 40.0)
                )
        return round(nearest_score, 2), nearest_corridor

    def _spread_score(
        self,
        latitude: float,
        longitude: float,
        end_latitude: Optional[float],
        end_longitude: Optional[float],
    ) -> float:
        if end_latitude is None or end_longitude is None:
            return 28.0
        path_distance_km = haversine_km((latitude, longitude), (end_latitude, end_longitude))
        return round(clamp((path_distance_km / 6.0) * 100.0, 12.0, 100.0), 2)

    def _infer_attendance(
        self, event_cause: str, risk_level: str, impact_score: float, expected_attendance: Optional[int]
    ) -> int:
        if expected_attendance:
            return max(0, expected_attendance)
        if event_cause in CROWD_CAUSES:
            base = {
                "Low": 500,
                "Medium": 1500,
                "High": 4000,
                "Critical": 9000,
            }[risk_level]
            multiplier = {
                "public_event": 1.3,
                "procession": 1.1,
                "protest": 0.9,
                "vip_movement": 0.6,
            }.get(event_cause, 1.0)
            return int(base * multiplier)
        return int(120 + (impact_score * 18))

    def _resource_plan(
        self,
        event_cause: str,
        risk_level: str,
        impact_score: float,
        requires_road_closure: bool,
        spread_score: float,
        expected_attendance: Optional[int],
        corridor_name: str,
    ) -> Dict[str, Any]:
        attendance = self._infer_attendance(
            event_cause, risk_level, impact_score, expected_attendance
        )
        response_base = RISK_TO_RESPONSE[risk_level]
        approach_arms = 2
        if spread_score >= 60:
            approach_arms += 2
        elif spread_score >= 35:
            approach_arms += 1
        if requires_road_closure:
            approach_arms += 1
        if event_cause in CROWD_CAUSES:
            crowd_ratio = {
                "Low": 250,
                "Medium": 180,
                "High": 130,
                "Critical": 90,
            }[risk_level]
            officers_from_crowd = math.ceil(attendance / crowd_ratio)
        else:
            officers_from_crowd = math.ceil(impact_score / 8.5)
        officers_required = max(
            response_base["officers"], officers_from_crowd + (approach_arms * 2)
        )
        barricades_required = response_base["barricades"] + (approach_arms * 3)
        if requires_road_closure:
            barricades_required += 4
        traffic_marshals = max(2, math.ceil(officers_required * 0.35))
        return {
            "estimated_crowd_or_vehicle_load": attendance,
            "traffic_officers_required": officers_required,
            "traffic_marshals_required": traffic_marshals,
            "barricades_required": barricades_required,
            "portable_message_boards": response_base["message_sign_boards"],
            "affected_approach_roads": approach_arms,
            "deployment_note": (
                f"Primary deployment should anchor around {corridor_name} with "
                f"{response_base['diversion_depth']}."
            ),
        }

    def _alert_payload(
        self, impact_score: float, risk_level: str, requires_road_closure: bool
    ) -> Dict[str, Any]:
        if impact_score >= ALERT_THRESHOLDS["critical"] or (
            requires_road_closure and impact_score >= 74.0
        ):
            return {
                "triggered": True,
                "severity": "Critical",
                "code": "GRIDLOCK_CRITICAL",
                "message": "Immediate corridor management, diversion, and field escalation required.",
            }
        if impact_score >= ALERT_THRESHOLDS["high"]:
            return {
                "triggered": True,
                "severity": "High",
                "code": "GRIDLOCK_HIGH",
                "message": "Pre-position officers and activate diversion advisory messaging.",
            }
        if impact_score >= ALERT_THRESHOLDS["medium"]:
            return {
                "triggered": True,
                "severity": "Medium",
                "code": "GRIDLOCK_WATCH",
                "message": "Monitor junction build-up and prepare soft barricading.",
            }
        return {
            "triggered": False,
            "severity": risk_level,
            "code": "GRIDLOCK_NORMAL",
            "message": "Standard traffic monitoring is sufficient.",
        }

    def _suggest_diversions(
        self, latitude: float, longitude: float, impacted_corridor: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        for node in self.analytics["graph_nodes"]:
            if node["corridor"] == impacted_corridor:
                continue
            distance_km = haversine_km((latitude, longitude), (node["latitude"], node["longitude"]))
            if distance_km > 8.5:
                continue
            grid_score = self.analytics["grid_scores"].get(node["grid_id"], 45.0)
            corridor_score = self.analytics["corridor_scores"].get(node["corridor"], 45.0)
            composite = (grid_score * 0.6) + (corridor_score * 0.4) + (distance_km * 2.2)
            candidates.append(
                (
                    composite,
                    {
                        "corridor": node["corridor"],
                        "via_junction": node["junction"],
                        "latitude": node["latitude"],
                        "longitude": node["longitude"],
                        "estimated_exposure_score": round((grid_score * 0.7) + (corridor_score * 0.3), 2),
                        "distance_from_event_km": round(distance_km, 2),
                    },
                )
            )
        candidates.sort(key=lambda item: item[0])
        unique: List[Dict[str, Any]] = []
        seen = set()
        for _, candidate in candidates:
            key = (candidate["corridor"], candidate["via_junction"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
            if len(unique) >= limit:
                break
        return unique

    def classify_risk(self, score: float) -> str:
        if score >= 82.0:
            return "Critical"
        if score >= 64.0:
            return "High"
        if score >= 42.0:
            return "Medium"
        return "Low"

    def predict(
        self,
        event_cause: str,
        priority: str,
        requires_road_closure: bool,
        latitude: float,
        longitude: float,
        event_type: str = "unplanned",
        start_datetime: Optional[datetime] = None,
        end_latitude: Optional[float] = None,
        end_longitude: Optional[float] = None,
        expected_attendance: Optional[int] = None,
    ) -> Dict[str, Any]:
        cause_key = clean_text(event_cause, "others").lower()
        priority_key = clean_text(priority, "Low").title()
        event_type_key = clean_text(event_type, "unplanned").lower()
        cause_score = self.analytics["cause_scores"].get(cause_key, 42.0)
        cause_score += self.state["cause_adjustments"].get(cause_key, 0.0)
        priority_score = self.analytics["priority_scores"].get(priority_key, 45.0)
        closure_score = self.analytics["closure_scores"].get(
            str(requires_road_closure).lower(), 45.0
        )
        hotspot_score = self._nearest_grid_score(latitude, longitude)
        corridor_score, nearest_corridor = self._corridor_score(latitude, longitude)
        temporal_score = self._temporal_score(start_datetime)
        spread_score = self._spread_score(latitude, longitude, end_latitude, end_longitude)
        type_score = self.analytics["event_type_scores"].get(event_type_key, 46.0)

        weights = self.state["weights"]
        impact_score = (
            (weights["cause"] * cause_score)
            + (weights["priority"] * priority_score)
            + (weights["road_closure"] * closure_score)
            + (weights["hotspot"] * hotspot_score)
            + (weights["corridor"] * corridor_score)
            + (weights["temporal"] * temporal_score)
            + (weights["spread"] * spread_score)
            + (0.08 * type_score)
            + self.state["bias"]
        )
        impact_score = round(clamp(impact_score, 0.0, 100.0), 2)
        risk_level = self.classify_risk(impact_score)
        resource_plan = self._resource_plan(
            cause_key,
            risk_level,
            impact_score,
            requires_road_closure,
            spread_score,
            expected_attendance,
            nearest_corridor,
        )
        diversion_suggestions = self._suggest_diversions(
            latitude, longitude, nearest_corridor
        )
        alert = self._alert_payload(impact_score, risk_level, requires_road_closure)
        return {
            "impact_score": impact_score,
            "risk_level": risk_level,
            "recommended_corridor_context": nearest_corridor,
            "resource_plan": resource_plan,
            "diversion_required": bool(diversion_suggestions and impact_score >= 58.0),
            "diversion_suggestions": diversion_suggestions,
            "alert": alert,
            "learning_state": {
                "last_retrained_at": self.state["last_retrained_at"],
                "feedback_records": len(self.feedback_log),
            },
            "breakdown": {
                "cause_score": round(cause_score, 2),
                "priority_score": round(priority_score, 2),
                "road_closure_score": round(closure_score, 2),
                "hotspot_score": round(hotspot_score, 2),
                "corridor_score": round(corridor_score, 2),
                "temporal_score": round(temporal_score, 2),
                "spread_score": round(spread_score, 2),
                "event_type_score": round(type_score, 2),
                "weights": weights,
                "bias": self.state["bias"],
            },
        }

    def _node_lookup(self) -> Dict[str, Dict[str, Any]]:
        return {node["grid_id"]: node for node in self.analytics["graph_nodes"]}

    def _nearest_node_ids(
        self, latitude: float, longitude: float, limit: int = 4
    ) -> List[Tuple[str, float]]:
        ranked: List[Tuple[float, str]] = []
        for node in self.analytics["graph_nodes"]:
            distance_km = haversine_km((latitude, longitude), (node["latitude"], node["longitude"]))
            ranked.append((distance_km, node["grid_id"]))
        ranked.sort(key=lambda item: item[0])
        return [(node_id, distance_km) for distance_km, node_id in ranked[:limit]]

    def _build_route_graph(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        hazard: Optional[Dict[str, Any]],
        extra_penalty_nodes: Optional[Dict[str, float]] = None,
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
        graph = {
            node_id: list(edges)
            for node_id, edges in self.analytics["graph_edges"].items()
        }
        nodes = self._node_lookup()
        nodes["origin"] = {
            "grid_id": "origin",
            "latitude": origin[0],
            "longitude": origin[1],
            "corridor": "Origin",
            "junction": "Origin",
        }
        nodes["destination"] = {
            "grid_id": "destination",
            "latitude": destination[0],
            "longitude": destination[1],
            "corridor": "Destination",
            "junction": "Destination",
        }
        graph["origin"] = []
        graph["destination"] = []
        for label, point in [("origin", origin), ("destination", destination)]:
            for node_id, distance_km in self._nearest_node_ids(point[0], point[1], limit=5):
                graph[label].append({"to": node_id, "distance_km": distance_km, "corridor": nodes[node_id]["corridor"]})
                graph.setdefault(node_id, []).append({"to": label, "distance_km": distance_km, "corridor": nodes[node_id]["corridor"]})
        return graph, nodes

    def _edge_penalty(
        self,
        from_node: Dict[str, Any],
        to_node: Dict[str, Any],
        hazard: Optional[Dict[str, Any]],
        extra_penalty_nodes: Optional[Dict[str, float]],
    ) -> float:
        midpoint = (
            (from_node["latitude"] + to_node["latitude"]) / 2,
            (from_node["longitude"] + to_node["longitude"]) / 2,
        )
        grid_score = self._nearest_grid_score(midpoint[0], midpoint[1])
        penalty = 1.0 + (grid_score / 100.0 * 1.65)
        if extra_penalty_nodes and to_node["grid_id"] in extra_penalty_nodes:
            penalty += extra_penalty_nodes[to_node["grid_id"]]
        if hazard:
            hazard_distance = haversine_km(
                midpoint, (hazard["latitude"], hazard["longitude"])
            )
            if hazard_distance < hazard["avoidance_radius_km"]:
                penalty += (hazard["impact_score"] / 100.0) * (
                    (hazard["avoidance_radius_km"] - hazard_distance) + 1.0
                )
        return penalty

    def _dijkstra_route(
        self,
        graph: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
        hazard: Optional[Dict[str, Any]],
        extra_penalty_nodes: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        queue: List[Tuple[float, str]] = [(0.0, "origin")]
        costs = {"origin": 0.0}
        previous: Dict[str, str] = {}
        while queue:
            current_cost, current = heappop(queue)
            if current == "destination":
                break
            if current_cost > costs.get(current, float("inf")):
                continue
            for edge in graph.get(current, []):
                next_node = edge["to"]
                from_node = nodes[current]
                to_node = nodes[next_node]
                penalty = self._edge_penalty(
                    from_node, to_node, hazard, extra_penalty_nodes
                )
                new_cost = current_cost + (edge["distance_km"] * penalty)
                if new_cost < costs.get(next_node, float("inf")):
                    costs[next_node] = new_cost
                    previous[next_node] = current
                    heappush(queue, (new_cost, next_node))
        if "destination" not in previous:
            return None
        path = ["destination"]
        while path[-1] != "origin":
            path.append(previous[path[-1]])
        path.reverse()
        total_distance = 0.0
        exposures: List[float] = []
        waypoints: List[Dict[str, Any]] = []
        for index, node_id in enumerate(path):
            node = nodes[node_id]
            waypoints.append(
                {
                    "latitude": round(node["latitude"], 5),
                    "longitude": round(node["longitude"], 5),
                    "corridor": node.get("corridor", "Unknown"),
                    "junction": node.get("junction", "Unknown"),
                }
            )
            if index == 0:
                continue
            previous_node = nodes[path[index - 1]]
            segment_distance = haversine_km(
                (previous_node["latitude"], previous_node["longitude"]),
                (node["latitude"], node["longitude"]),
            )
            total_distance += segment_distance
            midpoint = (
                (previous_node["latitude"] + node["latitude"]) / 2,
                (previous_node["longitude"] + node["longitude"]) / 2,
            )
            exposures.append(self._nearest_grid_score(midpoint[0], midpoint[1]))
        average_exposure = round(sum(exposures) / len(exposures), 2) if exposures else 0.0
        return {
            "path": path,
            "waypoints": waypoints,
            "estimated_distance_km": round(total_distance, 2),
            "average_exposure_score": average_exposure,
            "estimated_travel_multiplier": round(1 + (average_exposure / 100.0), 2),
        }

    def recommend_route(
        self,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        event_context: Optional[Dict[str, Any]] = None,
        alternatives: int = 3,
    ) -> Dict[str, Any]:
        hazard = None
        if event_context:
            impact_score = float(event_context.get("impact_score") or 0.0)
            hazard = {
                "latitude": float(event_context["latitude"]),
                "longitude": float(event_context["longitude"]),
                "impact_score": impact_score,
                "avoidance_radius_km": round(1.2 + (impact_score / 100.0 * 4.8), 2),
            }
        origin = (origin_latitude, origin_longitude)
        destination = (destination_latitude, destination_longitude)
        graph, nodes = self._build_route_graph(origin, destination, hazard, None)
        ranked_routes: List[Dict[str, Any]] = []
        used_penalties: Dict[str, float] = {}
        for _ in range(max(1, alternatives)):
            route = self._dijkstra_route(graph, nodes, hazard, used_penalties)
            if not route:
                break
            route["route_label"] = f"Option {len(ranked_routes) + 1}"
            route["recommended"] = len(ranked_routes) == 0
            ranked_routes.append(route)
            for node_id in route["path"][1:-1]:
                used_penalties[node_id] = used_penalties.get(node_id, 0.0) + 1.0
        return {
            "origin": {"latitude": origin_latitude, "longitude": origin_longitude},
            "destination": {
                "latitude": destination_latitude,
                "longitude": destination_longitude,
            },
            "hazard_context": hazard,
            "routes": ranked_routes,
        }

    def log_feedback(
        self,
        event_payload: Dict[str, Any],
        actual_impact_score: float,
        notes: Optional[str] = None,
        source: str = "manual_dashboard",
    ) -> Dict[str, Any]:
        prediction = self.predict(
            event_cause=event_payload["event_cause"],
            priority=event_payload["priority"],
            requires_road_closure=event_payload["requires_road_closure"],
            latitude=event_payload["latitude"],
            longitude=event_payload["longitude"],
            event_type=event_payload.get("event_type", "unplanned"),
            start_datetime=parse_datetime(event_payload.get("start_datetime")),
            end_latitude=event_payload.get("end_latitude"),
            end_longitude=event_payload.get("end_longitude"),
            expected_attendance=event_payload.get("expected_attendance"),
        )
        entry = {
            "feedback_id": str(uuid.uuid4()),
            "event_reference_id": event_payload.get("event_reference_id") or str(uuid.uuid4()),
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "notes": notes or "",
            "event_payload": event_payload,
            "predicted_impact_score": prediction["impact_score"],
            "actual_impact_score": round(clamp(actual_impact_score, 0.0, 100.0), 2),
            "error": round(actual_impact_score - prediction["impact_score"], 2),
            "breakdown": prediction["breakdown"],
        }
        self.feedback_log.append(entry)
        self._save_json(self.feedback_path, self.feedback_log)
        learning_update = self.retrain_if_due()
        return {
            "feedback_logged": True,
            "feedback_entry": entry,
            "learning_update": learning_update,
        }

    def get_learning_state(self) -> Dict[str, Any]:
        return {
            "weights": self.state["weights"],
            "bias": self.state["bias"],
            "cause_adjustments": self.state["cause_adjustments"],
            "last_retrained_at": self.state["last_retrained_at"],
            "retrain_window_days": self.state["retrain_window_days"],
            "feedback_records": len(self.feedback_log),
            "last_training_summary": self.state.get("last_training_summary", {}),
        }

    def retrain_if_due(self) -> Dict[str, Any]:
        last_retrained_at = parse_datetime(self.state["last_retrained_at"]) or datetime(
            2026, 1, 1, tzinfo=timezone.utc
        )
        due_at = last_retrained_at + timedelta(days=self.state["retrain_window_days"])
        now = datetime.now(timezone.utc)
        if now < due_at:
            return {
                "retrained": False,
                "next_due_at": due_at.isoformat(),
                "message": "Weekly correction window has not opened yet.",
            }
        return self.retrain_model(force=True)

    def retrain_model(self, force: bool = False) -> Dict[str, Any]:
        if not self.feedback_log:
            return {
                "retrained": False,
                "message": "No post-event feedback is available yet.",
            }
        gradients = {key: 0.0 for key in DEFAULT_WEIGHTS}
        cause_errors: Dict[str, List[float]] = {}
        errors: List[float] = []
        for entry in self.feedback_log:
            error = float(entry["error"])
            errors.append(error)
            breakdown = entry["breakdown"]
            for key in gradients:
                feature_key = f"{key}_score"
                feature_value = float(breakdown.get(feature_key, 50.0)) / 100.0
                gradients[key] += (error / 100.0) * (feature_value - 0.5)
            event_cause = entry["event_payload"]["event_cause"].strip().lower()
            cause_errors.setdefault(event_cause, []).append(error)
        learning_rate = float(self.state["learning_rate"])
        updated_weights = dict(self.state["weights"])
        total_weight = 0.0
        for key, gradient in gradients.items():
            updated_weights[key] = clamp(
                updated_weights[key] + (learning_rate * (gradient / max(len(errors), 1))),
                0.04,
                0.34,
            )
            total_weight += updated_weights[key]
        for key in updated_weights:
            updated_weights[key] = round(updated_weights[key] / total_weight, 4)
        bias_shift = learning_rate * (sum(errors) / max(len(errors), 1)) * 0.2
        self.state["bias"] = round(clamp(self.state["bias"] + bias_shift, -12.0, 12.0), 4)
        self.state["weights"] = updated_weights
        for cause, cause_error_list in cause_errors.items():
            current_adjustment = self.state["cause_adjustments"].get(cause, 0.0)
            updated_adjustment = clamp(
                current_adjustment + (learning_rate * (sum(cause_error_list) / len(cause_error_list)) * 0.15),
                -10.0,
                10.0,
            )
            self.state["cause_adjustments"][cause] = round(updated_adjustment, 3)
        self.state["last_retrained_at"] = datetime.now(timezone.utc).isoformat()
        self.state["last_training_summary"] = {
            "samples_used": len(errors),
            "mean_error": round(sum(errors) / len(errors), 2),
            "mean_absolute_error": round(sum(abs(error) for error in errors) / len(errors), 2),
            "bias_shift": round(bias_shift, 4),
        }
        self._save_json(self.state_path, self.state)
        return {
            "retrained": True,
            "state": self.get_learning_state(),
        }
