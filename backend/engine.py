import csv
import json
import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .google_routes import GoogleRoutesClient
except ImportError:
    from google_routes import GoogleRoutesClient


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "ProblemStatement2_Data_Gridlock.csv"
STATE_PATH = BASE_DIR / "learning_state.json"
FEEDBACK_PATH = BASE_DIR / "event_feedback_log.json"
MANUAL_EVENTS_PATH = BASE_DIR / "manual_events.json"

BENGALURU_CENTER = (12.9716, 77.5946)
INDIA_TZ = timezone(timedelta(hours=5, minutes=30))
LIVE_REFRESH_INTERVAL_SECONDS = 3600
LIVE_SNAPSHOT_LIMIT = 7
LIVE_PROBE_LIMIT = 12
LIVE_EVENT_LIMIT = 12

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
        self.manual_events_path = MANUAL_EVENTS_PATH
        self.session_started_at = datetime.now(timezone.utc)
        self.session_id = f"session-{uuid.uuid4().hex[:12]}"
        self.events = self._load_events()
        self.manual_events = self._load_manual_events()
        self.analytics = self._build_analytics(self.events)
        self.state = self._load_state()
        self.feedback_log = self._load_feedback_log()
        self.prediction_cache: Dict[str, Dict[str, Any]] = {}
        self.station_index = self._build_station_index()
        self.date_index = self._build_date_index()
        self.event_lookup = self._build_event_lookup()
        self.location_reference_points = self._build_location_reference_points()
        self.google_routes_client = GoogleRoutesClient(BASE_DIR.parent)
        self.live_probe_nodes = self._build_live_probe_nodes(limit=LIVE_PROBE_LIMIT)
        self.live_refresh_lock = threading.Lock()
        self.live_refresh_stop = threading.Event()
        self.live_refresh_thread: Optional[threading.Thread] = None
        self.live_cache = self._empty_live_cache()

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
                        "address": clean_text(row.get("address")),
                        "description": clean_text(row.get("description"), ""),
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
                        "police_station": clean_text(row.get("police_station")),
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
        merged["last_retrained_at"] = self.session_started_at.isoformat()
        merged["last_training_summary"] = {}
        return merged

    def _load_feedback_log(self) -> List[Dict[str, Any]]:
        return []

    def _parse_manual_event_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).strip())
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=INDIA_TZ)
        return dt

    def _load_manual_events(self) -> List[Dict[str, Any]]:
        # Demo manual events stay in memory only and reset on backend restart.
        return []

    def _serialize_manual_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": event["id"],
            "address": event["address"],
            "description": event["description"],
            "latitude": event["latitude"],
            "longitude": event["longitude"],
            "end_latitude": event["end_latitude"],
            "end_longitude": event["end_longitude"],
            "event_cause": event["event_cause"],
            "priority": event["priority"],
            "requires_road_closure": event["requires_road_closure"],
            "event_type": event["event_type"],
            "status": event["status"],
            "corridor": event["corridor"],
            "junction": event["junction"],
            "zone": event["zone"],
            "police_station": event["police_station"],
            "grid_id": event["grid_id"],
            "start_datetime": event["start_datetime"].isoformat() if event["start_datetime"] else None,
            "duration_hours": event["duration_hours"],
            "path_distance_km": event["path_distance_km"],
            "expected_attendance": event.get("expected_attendance"),
        }

    def _save_manual_events(self) -> None:
        # Demo manual events are intentionally not persisted to disk.
        return None

    def _build_event_lookup(self) -> Dict[str, Dict[str, Any]]:
        lookup = {event["id"]: event for event in self.events}
        lookup.update({event["id"]: event for event in self.manual_events})
        return lookup

    def _location_tokens(self, value: str) -> List[str]:
        stopwords = {
            "bengaluru",
            "bangalore",
            "india",
            "karnataka",
            "road",
            "main",
            "near",
            "opp",
            "opposite",
            "beside",
            "street",
            "layout",
            "area",
            "gate",
            "station",
        }
        return [
            token
            for token in re.findall(r"[a-z0-9]+", clean_text(value, "").lower())
            if len(token) >= 3 and token not in stopwords
        ]

    def _build_location_reference_points(self) -> List[Dict[str, Any]]:
        references: Dict[str, Dict[str, Any]] = {}
        for event in self.events:
            labels = {
                clean_text(event.get("address"), ""): 1.0,
                clean_text(event.get("junction"), ""): 0.92,
                clean_text(event.get("corridor"), ""): 0.84,
                clean_text(event.get("zone"), ""): 0.8,
                clean_text(event.get("police_station"), ""): 0.76,
            }
            for label, weight in labels.items():
                if not label or label == "Unknown":
                    continue
                key = label.lower()
                bucket = references.setdefault(
                    key,
                    {
                        "label": label,
                        "tokens": set(self._location_tokens(label)),
                        "latitudes": [],
                        "longitudes": [],
                        "weight": weight,
                        "count": 0,
                    },
                )
                bucket["latitudes"].append(event["latitude"])
                bucket["longitudes"].append(event["longitude"])
                bucket["weight"] = max(bucket["weight"], weight)
                bucket["count"] += 1
        points: List[Dict[str, Any]] = []
        for reference in references.values():
            if not reference["tokens"]:
                continue
            points.append(
                {
                    "label": reference["label"],
                    "label_lower": reference["label"].lower(),
                    "tokens": reference["tokens"],
                    "latitude": round(sum(reference["latitudes"]) / len(reference["latitudes"]), 6),
                    "longitude": round(sum(reference["longitudes"]) / len(reference["longitudes"]), 6),
                    "weight": reference["weight"],
                    "count": reference["count"],
                }
            )
        points.sort(key=lambda item: (item["weight"], item["count"], len(item["tokens"])), reverse=True)
        return points

    def _build_station_index(self) -> Dict[str, Dict[str, Any]]:
        station_groups: Dict[str, Dict[str, Any]] = {}
        for event in self.events:
            station_name = clean_text(event.get("police_station"), "Control")
            bucket = station_groups.setdefault(
                station_name,
                {
                    "name": station_name,
                    "latitudes": [],
                    "longitudes": [],
                    "event_count": 0,
                },
            )
            bucket["latitudes"].append(event["latitude"])
            bucket["longitudes"].append(event["longitude"])
            bucket["event_count"] += 1
        station_index: Dict[str, Dict[str, Any]] = {}
        for station_name, bucket in station_groups.items():
            station_index[station_name] = {
                "station_name": station_name,
                "latitude": round(sum(bucket["latitudes"]) / len(bucket["latitudes"]), 5),
                "longitude": round(sum(bucket["longitudes"]) / len(bucket["longitudes"]), 5),
                "historical_event_count": bucket["event_count"],
            }
        return station_index

    def _build_date_index(self) -> Dict[str, Any]:
        events_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for event in self.events:
            if not event["start_datetime"]:
                continue
            date_key = event["start_datetime"].date().isoformat()
            events_by_date.setdefault(date_key, []).append(event)
        sorted_dates = sorted(events_by_date.keys())
        windows: List[Dict[str, Any]] = []
        for start in range(0, len(sorted_dates), 7):
            chunk = sorted_dates[start : start + 7]
            windows.append(
                {
                    "window_index": len(windows),
                    "start_date": chunk[0],
                    "end_date": chunk[-1],
                    "dates": chunk,
                }
            )
        return {"events_by_date": events_by_date, "sorted_dates": sorted_dates, "windows": windows}

    def _build_live_probe_nodes(self, limit: int = LIVE_PROBE_LIMIT) -> List[Dict[str, Any]]:
        ranked_nodes = sorted(
            self.analytics["graph_nodes"],
            key=lambda node: (
                self.analytics["hotspot_scores"].get(node["grid_id"], 0.0),
                node.get("count", 0),
            ),
            reverse=True,
        )
        return ranked_nodes[: max(1, limit)]

    def _empty_live_cache(self) -> Dict[str, Any]:
        return {
            "last_refresh_at": None,
            "next_refresh_at": None,
            "cache_warm": False,
            "stale": False,
            "last_error": None,
            "route_source": "historical_fallback",
            "events": [],
            "events_by_id": {},
            "snapshots": [],
        }

    def start_live_monitor(self) -> None:
        with self.live_refresh_lock:
            if self.live_refresh_thread and self.live_refresh_thread.is_alive():
                return
            self.live_refresh_stop.clear()
            self.refresh_live_cache()
            self.live_refresh_thread = threading.Thread(
                target=self._live_refresh_loop,
                name="gridlock-live-refresh",
                daemon=True,
            )
            self.live_refresh_thread.start()

    def stop_live_monitor(self) -> None:
        self.live_refresh_stop.set()
        thread = self.live_refresh_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self.live_refresh_thread = None

    def _live_refresh_loop(self) -> None:
        while not self.live_refresh_stop.wait(LIVE_REFRESH_INTERVAL_SECONDS):
            self.refresh_live_cache()

    def _historical_profile_for_coordinates(
        self, latitude: float, longitude: float, reference_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        reference_hour = None
        if reference_time is not None:
            localized_reference = reference_time.astimezone(INDIA_TZ)
            reference_hour = localized_reference.hour

        ranked_candidates: List[Tuple[float, float, Dict[str, Any]]] = []
        for event in self.events:
            distance_km = haversine_km((latitude, longitude), (event["latitude"], event["longitude"]))
            hour_penalty = 0.0
            if reference_hour is not None and event.get("start_datetime"):
                event_hour = event["start_datetime"].astimezone(INDIA_TZ).hour
                circular_gap = min(abs(event_hour - reference_hour), 24 - abs(event_hour - reference_hour))
                hour_penalty = circular_gap * 0.55
            ranked_candidates.append((distance_km + hour_penalty, distance_km, event))

        ranked_candidates.sort(key=lambda item: (item[0], item[1]))
        ranked_events = [event for _, _, event in ranked_candidates[:18]]
        if not ranked_events:
            return {
                "title": "Live congestion hotspot",
                "address": "Bengaluru traffic corridor",
                "event_cause": "others",
                "priority": "High",
                "event_type": "unplanned",
                "requires_road_closure": False,
                "corridor": "Unknown",
                "junction": "Unknown",
                "zone": "Zone unavailable",
                "police_station": "Control",
                "end_latitude": None,
                "end_longitude": None,
                "expected_attendance": None,
            }

        def pick_weighted_value(field: str, default: Any) -> Any:
            weights: Dict[Any, float] = {}
            for event in ranked_events:
                distance = haversine_km((latitude, longitude), (event["latitude"], event["longitude"]))
                hour_multiplier = 1.0
                if reference_hour is not None and event.get("start_datetime"):
                    event_hour = event["start_datetime"].astimezone(INDIA_TZ).hour
                    circular_gap = min(abs(event_hour - reference_hour), 24 - abs(event_hour - reference_hour))
                    hour_multiplier = max(0.25, 1.0 - (circular_gap * 0.12))
                weight = hour_multiplier / max(distance + 0.2, 0.2)
                value = event.get(field, default)
                weights[value] = weights.get(value, 0.0) + weight
            return max(weights.items(), key=lambda item: item[1])[0] if weights else default

        closure_votes = sum(1 for event in ranked_events if event["requires_road_closure"])
        corridor_name = clean_text(pick_weighted_value("corridor", "Unknown"), "Unknown")
        junction_name = clean_text(pick_weighted_value("junction", "Unknown"), "Unknown")
        zone_name = clean_text(pick_weighted_value("zone", "Zone unavailable"), "Zone unavailable")
        live_title = corridor_name if corridor_name != "Unknown" else junction_name
        if live_title in {"Unknown", ""}:
            live_title = f"Live hotspot - {zone_name}" if zone_name != "Zone unavailable" else "Live congestion hotspot"
        return {
            "title": live_title,
            "address": clean_text(junction_name if junction_name != "Unknown" else corridor_name, "Bengaluru traffic corridor"),
            "event_cause": pick_weighted_value("event_cause", "others"),
            "priority": pick_weighted_value("priority", "High"),
            "event_type": pick_weighted_value("event_type", "unplanned"),
            "requires_road_closure": closure_votes >= max(1, math.ceil(len(ranked_events) * 0.45)),
            "corridor": corridor_name,
            "junction": junction_name,
            "zone": zone_name,
            "police_station": pick_weighted_value("police_station", "Control"),
            "end_latitude": None,
            "end_longitude": None,
            "expected_attendance": None,
        }

    def _traffic_interval_distribution(self, speed_reading_intervals: List[Dict[str, Any]]) -> Dict[str, float]:
        totals = {"NORMAL": 0.0, "SLOW": 0.0, "TRAFFIC_JAM": 0.0}
        covered = 0.0
        for interval in speed_reading_intervals:
            start_index = int(interval.get("startPolylinePointIndex", 0) or 0)
            end_index = int(interval.get("endPolylinePointIndex", start_index + 1) or (start_index + 1))
            span = max(1, end_index - start_index)
            speed = clean_text(interval.get("speed"), "NORMAL").upper()
            if speed not in totals:
                speed = "NORMAL"
            totals[speed] += span
            covered += span
        if covered <= 0:
            return {"normal_share": 1.0, "slow_share": 0.0, "jam_share": 0.0}
        return {
            "normal_share": round(totals["NORMAL"] / covered, 4),
            "slow_share": round(totals["SLOW"] / covered, 4),
            "jam_share": round(totals["TRAFFIC_JAM"] / covered, 4),
        }

    def _live_scores_from_probe(
        self,
        *,
        aware_duration_seconds: float,
        baseline_duration_seconds: float,
        interval_distribution: Dict[str, float],
        historical_hotspot_score: float,
        historical_corridor_score: float,
        alternative_duration_seconds: List[float],
    ) -> Dict[str, float]:
        slowdown_ratio = (
            aware_duration_seconds / baseline_duration_seconds
            if baseline_duration_seconds > 0
            else 1.0
        )
        jam_share = interval_distribution["jam_share"]
        slow_share = interval_distribution["slow_share"]
        volatility_ratio = 0.0
        if alternative_duration_seconds:
            min_duration = min(alternative_duration_seconds)
            max_duration = max(alternative_duration_seconds)
            if min_duration > 0:
                volatility_ratio = (max_duration - min_duration) / min_duration

        slowdown_score = clamp((slowdown_ratio - 1.0) * 90.0, 0.0, 100.0)
        interval_score = clamp((jam_share * 100.0 * 0.7) + (slow_share * 100.0 * 0.3), 0.0, 100.0)
        detour_score = clamp(volatility_ratio * 140.0, 0.0, 100.0)
        live_traffic_score = clamp(
            (interval_score * 0.48) + (slowdown_score * 0.34) + (detour_score * 0.18),
            8.0,
            100.0,
        )
        hotspot_score = clamp((live_traffic_score * 0.68) + (historical_hotspot_score * 0.32), 15.0, 100.0)
        corridor_score = clamp((live_traffic_score * 0.58) + (historical_corridor_score * 0.42), 15.0, 100.0)
        spread_score = clamp(
            (jam_share * 100.0 * 0.48) + (slow_share * 100.0 * 0.24) + (detour_score * 0.28),
            12.0,
            100.0,
        )
        return {
            "hotspot_score": round(hotspot_score, 2),
            "corridor_score": round(corridor_score, 2),
            "spread_score": round(spread_score, 2),
            "live_traffic_score": round(live_traffic_score, 2),
            "slowdown_ratio": round(slowdown_ratio, 3),
            "jam_share": round(jam_share, 4),
            "slow_share": round(slow_share, 4),
            "detour_penalty_score": round(detour_score, 2),
        }

    def _build_live_event_from_probe(
        self, probe: Dict[str, Any], refreshed_at: datetime
    ) -> Optional[Dict[str, Any]]:
        latitude = float(probe["latitude"])
        longitude = float(probe["longitude"])
        profile = self._historical_profile_for_coordinates(latitude, longitude, refreshed_at)
        station = self._station_payload(profile["police_station"])
        aware_result = self.google_routes_client.compute_routes(
            origin=(station["latitude"], station["longitude"]),
            destination=(latitude, longitude),
            alternatives=3,
            routing_preference="TRAFFIC_AWARE",
        )
        if not aware_result.get("ok") or not aware_result.get("routes"):
            return None

        baseline_result = self.google_routes_client.compute_routes(
            origin=(station["latitude"], station["longitude"]),
            destination=(latitude, longitude),
            alternatives=1,
            routing_preference="TRAFFIC_UNAWARE",
        )
        baseline_duration_seconds = 0.0
        if baseline_result.get("ok") and baseline_result.get("routes"):
            baseline_duration_seconds = float(
                baseline_result["routes"][0].get("duration_seconds") or 0.0
            )
        primary_route = aware_result["routes"][0]
        interval_distribution = self._traffic_interval_distribution(
            ((primary_route.get("travel_advisory") or {}).get("speedReadingIntervals") or [])
        )
        scores = self._live_scores_from_probe(
            aware_duration_seconds=float(primary_route.get("duration_seconds") or 0.0),
            baseline_duration_seconds=baseline_duration_seconds,
            interval_distribution=interval_distribution,
            historical_hotspot_score=self._nearest_grid_score(latitude, longitude),
            historical_corridor_score=self._corridor_score(latitude, longitude)[0],
            alternative_duration_seconds=[
                float(route.get("duration_seconds") or 0.0)
                for route in aware_result["routes"]
                if route.get("duration_seconds")
            ],
        )
        event_id = f"LIVE_{probe['grid_id'].replace('.', '').replace('_', '')}"
        return {
            "id": event_id,
            "address": profile["address"],
            "description": profile["title"],
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "end_latitude": profile["end_latitude"],
            "end_longitude": profile["end_longitude"],
            "event_cause": clean_text(profile["event_cause"], "others").lower(),
            "priority": clean_text(profile["priority"], "High").title(),
            "requires_road_closure": bool(profile["requires_road_closure"]),
            "event_type": clean_text(profile["event_type"], "unplanned").lower(),
            "status": "active",
            "corridor": clean_text(profile["corridor"]),
            "junction": clean_text(profile["junction"]),
            "zone": clean_text(profile["zone"]),
            "police_station": clean_text(profile["police_station"], "Control"),
            "grid_id": probe["grid_id"],
            "start_datetime": refreshed_at,
            "duration_hours": None,
            "path_distance_km": 0.0,
            "expected_attendance": profile["expected_attendance"],
            "event_source": "live",
            "live_scoring_inputs": scores,
            "live_probe_summary": {
                "route_source": "google_live_probe",
                "aware_duration_seconds": round(float(primary_route.get("duration_seconds") or 0.0), 2),
                "baseline_duration_seconds": round(float(baseline_duration_seconds or 0.0), 2),
                "google_distance_km": round(float(primary_route.get("distance_meters") or 0.0) / 1000.0, 2),
                "interval_distribution": interval_distribution,
            },
        }

    def _build_fallback_live_events(self, refreshed_at: datetime) -> List[Dict[str, Any]]:
        fallback_events: List[Dict[str, Any]] = []
        for probe in self.live_probe_nodes[:LIVE_EVENT_LIMIT]:
            profile = self._historical_profile_for_coordinates(
                probe["latitude"], probe["longitude"], refreshed_at
            )
            fallback_events.append(
                {
                    "id": f"LIVE_FALLBACK_{probe['grid_id'].replace('.', '').replace('_', '')}",
                    "address": profile["address"],
                    "description": profile["title"],
                    "latitude": round(float(probe["latitude"]), 6),
                    "longitude": round(float(probe["longitude"]), 6),
                    "end_latitude": None,
                    "end_longitude": None,
                    "event_cause": clean_text(profile["event_cause"], "others").lower(),
                    "priority": clean_text(profile["priority"], "High").title(),
                    "requires_road_closure": bool(profile["requires_road_closure"]),
                    "event_type": clean_text(profile["event_type"], "unplanned").lower(),
                    "status": "active",
                    "corridor": clean_text(profile["corridor"]),
                    "junction": clean_text(profile["junction"]),
                    "zone": clean_text(profile["zone"]),
                    "police_station": clean_text(profile["police_station"], "Control"),
                    "grid_id": probe["grid_id"],
                    "start_datetime": refreshed_at,
                    "duration_hours": None,
                    "path_distance_km": 0.0,
                    "expected_attendance": None,
                    "event_source": "live",
                    "live_scoring_inputs": {
                        "hotspot_score": round(self._nearest_grid_score(probe["latitude"], probe["longitude"]), 2),
                        "corridor_score": round(self._corridor_score(probe["latitude"], probe["longitude"])[0], 2),
                        "spread_score": 34.0,
                        "live_traffic_score": round(self.analytics["hotspot_scores"].get(probe["grid_id"], 42.0), 2),
                        "slowdown_ratio": 1.0,
                        "jam_share": 0.0,
                        "slow_share": 0.0,
                        "detour_penalty_score": 0.0,
                    },
                    "live_probe_summary": {
                        "route_source": "historical_fallback",
                        "aware_duration_seconds": 0.0,
                        "baseline_duration_seconds": 0.0,
                        "google_distance_km": 0.0,
                        "interval_distribution": {
                            "normal_share": 1.0,
                            "slow_share": 0.0,
                            "jam_share": 0.0,
                        },
                    },
                }
            )
        return fallback_events

    def refresh_live_cache(self) -> Dict[str, Any]:
        refreshed_at = datetime.now(timezone.utc)
        live_events: List[Dict[str, Any]] = []
        errors: List[str] = []
        for probe in self.live_probe_nodes:
            try:
                live_event = self._build_live_event_from_probe(probe, refreshed_at)
            except Exception as error:
                live_event = None
                errors.append(str(error))
            if live_event:
                live_events.append(live_event)

        route_source = "google_live_probe"
        cache_warm = bool(live_events)
        stale = False
        last_error = None
        if not live_events:
            if self.live_cache["cache_warm"] and self.live_cache["events"]:
                live_events = list(self.live_cache["events"])
                stale = True
                route_source = self.live_cache.get("route_source", "google_live_probe")
                last_error = errors[0] if errors else "Live refresh failed; serving the last warm cache."
                cache_warm = True
            else:
                live_events = self._build_fallback_live_events(refreshed_at)
                route_source = "historical_fallback"
                last_error = errors[0] if errors else "Google live traffic is unavailable; serving historical fallback hotspots."
                cache_warm = bool(live_events)

        live_events.sort(
            key=lambda event: (
                event.get("live_scoring_inputs", {}).get("live_traffic_score", 0.0),
                self.analytics["hotspot_scores"].get(event["grid_id"], 0.0),
            ),
            reverse=True,
        )
        top_events = live_events[:LIVE_EVENT_LIMIT]
        events_by_id = {event["id"]: event for event in top_events}

        existing_snapshots = list(self.live_cache.get("snapshots", []))
        snapshot_key = refreshed_at.strftime("%Y-%m-%dT%H:00:00Z")
        snapshot_summary = self._build_live_snapshot_summary(snapshot_key, refreshed_at, top_events)
        snapshots = [item for item in existing_snapshots if item["date"] != snapshot_key]
        snapshots.append(snapshot_summary)
        snapshots.sort(key=lambda item: item["captured_at"])
        snapshots = snapshots[-LIVE_SNAPSHOT_LIMIT:]

        self.prediction_cache = {
            event_id: prediction
            for event_id, prediction in self.prediction_cache.items()
            if not str(event_id).startswith("LIVE_")
        }
        self.live_cache = {
            "last_refresh_at": refreshed_at.isoformat(),
            "next_refresh_at": (refreshed_at + timedelta(seconds=LIVE_REFRESH_INTERVAL_SECONDS)).isoformat(),
            "cache_warm": cache_warm,
            "stale": stale,
            "last_error": last_error,
            "route_source": route_source,
            "events": top_events,
            "events_by_id": events_by_id,
            "snapshots": snapshots,
        }
        return self.live_cache

    def _build_live_snapshot_summary(
        self, snapshot_key: str, refreshed_at: datetime, events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        predicted_events = [self._event_dashboard_payload(event) for event in events]
        max_score = max((event["impact_score"] for event in predicted_events), default=0.0)
        critical_count = sum(1 for event in predicted_events if event["risk_level"] == "Critical")
        return {
            "date": snapshot_key,
            "captured_at": refreshed_at.isoformat(),
            "slot_label": refreshed_at.astimezone(INDIA_TZ).strftime("%H:%M"),
            "slot_hour": refreshed_at.astimezone(INDIA_TZ).strftime("%H"),
            "event_count": len(predicted_events),
            "critical_count": critical_count,
            "max_impact_score": round(max_score, 2),
            "color": self._score_color(max_score),
        }

    def get_live_status(self) -> Dict[str, Any]:
        return {
            "mode": "live",
            "available": True,
            "google_routes_configured": self.google_routes_client.is_configured(),
            "last_refresh_at": self.live_cache["last_refresh_at"],
            "next_refresh_at": self.live_cache["next_refresh_at"],
            "cache_warm": self.live_cache["cache_warm"],
            "stale": self.live_cache["stale"],
            "last_error": self.live_cache["last_error"],
            "route_source": self.live_cache["route_source"],
            "session_started_at": self.session_started_at.isoformat(),
            "session_id": self.session_id,
        }

    def _live_snapshot_dates(self) -> List[Dict[str, Any]]:
        snapshots = list(self.live_cache.get("snapshots", []))
        snapshots.sort(key=lambda item: item["captured_at"])
        return snapshots

    def get_live_calendar_window(self, window_index: int = 0) -> Dict[str, Any]:
        snapshots = self._live_snapshot_dates()
        today_text = datetime.now(INDIA_TZ).date().isoformat()
        label = f"Live today - {datetime.now(INDIA_TZ).strftime('%d %b %Y')}"
        return {
            "window_index": 0,
            "total_windows": 1,
            "start_date": today_text,
            "end_date": today_text,
            "label": label,
            "dates": snapshots,
        }

    def list_live_calendar_windows(self) -> Dict[str, Any]:
        today_text = datetime.now(INDIA_TZ).date().isoformat()
        label = f"Live today - {datetime.now(INDIA_TZ).strftime('%d %b %Y')}"
        return {
            "total_windows": 1,
            "windows": [
                {
                    "window_index": 0,
                    "start_date": today_text,
                    "end_date": today_text,
                    "label": label,
                }
            ],
        }

    def _live_events_for_snapshot(self, snapshot_key: Optional[str] = None) -> List[Dict[str, Any]]:
        live_events = list(self.live_cache.get("events", []))
        if not snapshot_key:
            return live_events
        snapshot_date = snapshot_key.split("T", 1)[0]
        manual_today = [
            event
            for event in self.manual_events
            if event["start_datetime"] and event["start_datetime"].date().isoformat() == snapshot_date
        ]
        return live_events + manual_today

    def get_live_day_dashboard(self, snapshot_key: str) -> Dict[str, Any]:
        events = self._live_events_for_snapshot(snapshot_key)
        dashboard_events = [self._event_dashboard_payload(event) for event in events]
        dashboard_events.sort(key=lambda item: item["impact_score"], reverse=True)
        police_markers = []
        seen_stations = set()
        for event in dashboard_events:
            station_name = event["police_station"]["station_name"]
            if station_name in seen_stations:
                continue
            seen_stations.add(station_name)
            police_markers.append(event["police_station"])
        snapshot_meta = next(
            (item for item in self._live_snapshot_dates() if item["date"] == snapshot_key),
            None,
        )
        summary_date = snapshot_meta["captured_at"] if snapshot_meta else datetime.now(timezone.utc).isoformat()
        summary = {
            "date": summary_date,
            "event_count": len(dashboard_events),
            "critical_count": sum(1 for event in dashboard_events if event["risk_level"] == "Critical"),
            "high_or_above": sum(1 for event in dashboard_events if event["impact_score"] >= 64.0),
            "average_impact_score": round(
                sum(event["impact_score"] for event in dashboard_events) / len(dashboard_events),
                2,
            )
            if dashboard_events
            else 0.0,
            "slot_label": snapshot_meta["slot_label"] if snapshot_meta else datetime.now(INDIA_TZ).strftime("%H:%M"),
            "mode": "live",
        }
        return {
            "summary": summary,
            "events": dashboard_events,
            "police_markers": police_markers,
        }

    def get_live_review_window(self, window_index: int = 0) -> Dict[str, Any]:
        calendar = self.get_live_calendar_window(window_index)
        return {
            "window_index": calendar["window_index"],
            "start_date": calendar["start_date"],
            "end_date": calendar["end_date"],
            "placeholder": True,
            "events": [],
            "message": "Weekly review remains available in historical mode only for this phase.",
        }

    def _save_json(self, path: Path, payload: Any) -> None:
        with path.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, indent=2)

    def _score_color(self, score: float) -> str:
        if score >= 82.0:
            return "#ff5a36"
        if score >= 64.0:
            return "#ff8c1a"
        if score >= 42.0:
            return "#f5c04a"
        return "#40c4aa"

    def _format_calendar_window_label(self, start_date_text: str, end_date_text: str) -> str:
        start_date = datetime.fromisoformat(start_date_text)
        end_date = datetime.fromisoformat(end_date_text)
        if (
            start_date.month == end_date.month
            and start_date.year == end_date.year
        ):
            return f"{start_date.strftime('%B')} {start_date.day}-{end_date.day}, {start_date.year}"
        return f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b %Y')}"

    def _predict_event_record(self, event: Dict[str, Any]) -> Dict[str, Any]:
        cached = self.prediction_cache.get(event["id"])
        if cached:
            return cached
        live_scoring_inputs = event.get("live_scoring_inputs")
        if live_scoring_inputs:
            prediction = self._predict_with_component_scores(
                event_cause=event["event_cause"],
                priority=event["priority"],
                requires_road_closure=event["requires_road_closure"],
                latitude=event["latitude"],
                longitude=event["longitude"],
                event_type=event["event_type"],
                start_datetime=event["start_datetime"],
                end_latitude=event["end_latitude"],
                end_longitude=event["end_longitude"],
                expected_attendance=event.get("expected_attendance"),
                score_overrides=live_scoring_inputs,
            )
        else:
            prediction = self.predict(
                event_cause=event["event_cause"],
                priority=event["priority"],
                requires_road_closure=event["requires_road_closure"],
                latitude=event["latitude"],
                longitude=event["longitude"],
                event_type=event["event_type"],
                start_datetime=event["start_datetime"],
                end_latitude=event["end_latitude"],
                end_longitude=event["end_longitude"],
                expected_attendance=event.get("expected_attendance"),
            )
        self.prediction_cache[event["id"]] = prediction
        return prediction

    def _station_payload(self, station_name: str) -> Dict[str, Any]:
        return self.station_index.get(
            clean_text(station_name, "Control"),
            {
                "station_name": "Control",
                "latitude": BENGALURU_CENTER[0],
                "longitude": BENGALURU_CENTER[1],
                "historical_event_count": 0,
            },
        )

    def _event_record(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self.live_cache.get("events_by_id", {}).get(event_id) or self.event_lookup.get(event_id)

    def _event_dashboard_payload(self, event: Dict[str, Any]) -> Dict[str, Any]:
        prediction = self._predict_event_record(event)
        station = self._station_payload(event.get("police_station", "Control"))
        impact_score = prediction["impact_score"]
        return {
            "event_id": event["id"],
            "title": clean_text(event["description"], event["event_cause"].replace("_", " ").title()),
            "date": event["start_datetime"].date().isoformat() if event["start_datetime"] else None,
            "time": event["start_datetime"].strftime("%H:%M") if event["start_datetime"] else "--:--",
            "address": event["address"],
            "event_cause": event["event_cause"],
            "priority": event["priority"],
            "event_type": event["event_type"],
            "status": event["status"],
            "latitude": event["latitude"],
            "longitude": event["longitude"],
            "end_latitude": event["end_latitude"],
            "end_longitude": event["end_longitude"],
            "corridor": event["corridor"],
            "junction": event["junction"],
            "zone": event["zone"],
            "requires_road_closure": event["requires_road_closure"],
            "police_station": station,
            "impact_score": impact_score,
            "impact_color": self._score_color(impact_score),
            "risk_level": prediction["risk_level"],
            "resource_plan": prediction["resource_plan"],
            "diversion_required": prediction["diversion_required"],
            "diversion_suggestions": prediction["diversion_suggestions"],
            "alert": prediction["alert"],
            "breakdown": prediction["breakdown"],
            "event_source": event.get("event_source", "historical"),
            "live_probe_summary": event.get("live_probe_summary"),
        }

    def get_catalog(self) -> Dict[str, Any]:
        return {
            "known_event_causes": [name for name, _ in self.analytics["top_causes"]],
            "known_corridors": [name for name, _ in self.analytics["top_corridors"][:20]],
            "known_locations": self._location_suggestions(),
            "alert_thresholds": ALERT_THRESHOLDS,
            "weights": self.state["weights"],
            "retrain_window_days": self.state["retrain_window_days"],
            "available_day_count": len(self.date_index["sorted_dates"]),
            "available_windows": len(self.date_index["windows"]),
        }

    def get_health_summary(self) -> Dict[str, Any]:
        return {
            "dataset_path": str(self.data_path),
            "historical_events_loaded": self.analytics["event_count"],
            "feedback_records": len(self.feedback_log),
            "last_retrained_at": self.state["last_retrained_at"],
            "session_id": self.session_id,
            "session_started_at": self.session_started_at.isoformat(),
            "live_status": self.get_live_status(),
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

    def _geocode_location_text(self, location_text: str) -> Tuple[float, float]:
        query = clean_text(location_text, "")
        query_tokens = set(self._location_tokens(query))
        if not query_tokens:
            raise ValueError("Please enter a recognizable Bengaluru location or landmark.")
        query_lower = query.lower()
        best_match = None
        best_score = 0.0
        for candidate in self.location_reference_points:
            overlap = query_tokens & candidate["tokens"]
            if not overlap:
                continue
            token_precision = len(overlap) / len(query_tokens)
            token_recall = len(overlap) / len(candidate["tokens"])
            score = (token_precision * 0.62) + (token_recall * 0.28) + (candidate["weight"] * 0.10)
            if candidate["label_lower"] in query_lower or query_lower in candidate["label_lower"]:
                score += 0.24
            if score > best_score:
                best_score = score
                best_match = candidate
        if not best_match or best_score < 0.48:
            raise ValueError(
                "Location could not be matched confidently. Try a known Bengaluru landmark, corridor, junction, or police station."
            )
        return best_match["latitude"], best_match["longitude"]

    def _location_suggestions(self, limit: int = 120) -> List[str]:
        suggestions = []
        seen = set()
        for candidate in self.location_reference_points:
            label = candidate["label"]
            if label.lower() in seen:
                continue
            seen.add(label.lower())
            suggestions.append(label)
            if len(suggestions) >= limit:
                break
        return suggestions

    def _events_for_date(self, date_key: str) -> List[Dict[str, Any]]:
        historical_events = list(self.date_index["events_by_date"].get(date_key, []))
        manual_events = [
            event
            for event in self.manual_events
            if event["start_datetime"] and event["start_datetime"].date().isoformat() == date_key
        ]
        return historical_events + manual_events

    def _nearest_station_name_for_coordinates(self, latitude: float, longitude: float) -> str:
        nearest_station_name = "Control"
        nearest_distance = float("inf")
        for station_name, station in self.station_index.items():
            distance_km = haversine_km(
                (latitude, longitude),
                (station["latitude"], station["longitude"]),
            )
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_station_name = station_name
        return nearest_station_name

    def _nearest_zone_for_coordinates(self, latitude: float, longitude: float) -> str:
        nearest_zone = "Zone unavailable"
        nearest_distance = float("inf")
        for event in self.events:
            distance_km = haversine_km((latitude, longitude), (event["latitude"], event["longitude"]))
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_zone = clean_text(event.get("zone"), "Zone unavailable")
        return nearest_zone

    def create_manual_event(
        self,
        *,
        date: str,
        time_text: str,
        title: str,
        address: str,
        event_cause: str,
        priority: str,
        requires_road_closure: bool,
        event_type: str = "planned",
        expected_attendance: Optional[int] = None,
    ) -> Dict[str, Any]:
        scheduled_local = datetime.fromisoformat(f"{date}T{time_text}:00").replace(tzinfo=INDIA_TZ)
        latitude, longitude = self._geocode_location_text(address)
        corridor_score, corridor_name = self._corridor_score(latitude, longitude)
        station_name = self._nearest_station_name_for_coordinates(latitude, longitude)
        event_id = f"MANUAL_{uuid.uuid4().hex[:10].upper()}"
        event = {
            "id": event_id,
            "address": clean_text(address),
            "description": clean_text(title, "Manual Event"),
            "latitude": round(float(latitude), 6),
            "longitude": round(float(longitude), 6),
            "end_latitude": None,
            "end_longitude": None,
            "event_cause": clean_text(event_cause, "others").lower(),
            "priority": clean_text(priority, "Low").title(),
            "requires_road_closure": bool(requires_road_closure),
            "event_type": clean_text(event_type, "planned").lower(),
            "status": "scheduled",
            "corridor": corridor_name,
            "junction": corridor_name,
            "zone": self._nearest_zone_for_coordinates(latitude, longitude),
            "police_station": station_name,
            "grid_id": f"{round(latitude, 2):.2f}_{round(longitude, 2):.2f}",
            "start_datetime": scheduled_local,
            "duration_hours": None,
            "path_distance_km": 0.0,
            "expected_attendance": expected_attendance,
            "event_source": "manual",
            "corridor_score_hint": corridor_score,
        }
        self.manual_events.append(event)
        self.event_lookup[event_id] = event
        self.prediction_cache.pop(event_id, None)
        self._save_manual_events()
        return self._event_dashboard_payload(event)

    def get_calendar_window(self, window_index: int = 0) -> Dict[str, Any]:
        windows = self.date_index["windows"]
        if not windows:
            return {"window_index": 0, "total_windows": 0, "dates": []}
        safe_index = max(0, min(window_index, len(windows) - 1))
        window = windows[safe_index]
        date_cards: List[Dict[str, Any]] = []
        for date_key in window["dates"]:
            day_events = self._events_for_date(date_key)
            dashboard_events = [self._event_dashboard_payload(event) for event in day_events]
            if dashboard_events:
                max_score = max(item["impact_score"] for item in dashboard_events)
                critical_count = sum(
                    1 for item in dashboard_events if item["risk_level"] == "Critical"
                )
            else:
                max_score = 0.0
                critical_count = 0
            date_cards.append(
                {
                    "date": date_key,
                    "event_count": len(dashboard_events),
                    "critical_count": critical_count,
                    "max_impact_score": round(max_score, 2),
                    "color": self._score_color(max_score),
                }
            )
        return {
            "window_index": safe_index,
            "total_windows": len(windows),
            "start_date": window["start_date"],
            "end_date": window["end_date"],
            "label": self._format_calendar_window_label(window["start_date"], window["end_date"]),
            "dates": date_cards,
        }

    def list_calendar_windows(self) -> Dict[str, Any]:
        return {
            "total_windows": len(self.date_index["windows"]),
            "windows": [
                {
                    "window_index": window["window_index"],
                    "start_date": window["start_date"],
                    "end_date": window["end_date"],
                    "label": self._format_calendar_window_label(window["start_date"], window["end_date"]),
                }
                for window in self.date_index["windows"]
            ],
        }

    def get_day_dashboard(self, date_key: str) -> Dict[str, Any]:
        day_events = self._events_for_date(date_key)
        dashboard_events = [self._event_dashboard_payload(event) for event in day_events]
        dashboard_events.sort(
            key=lambda item: (item["impact_score"], item["priority"] == "High"),
            reverse=True,
        )
        police_markers = []
        seen_stations = set()
        for event in dashboard_events:
            station_name = event["police_station"]["station_name"]
            if station_name in seen_stations:
                continue
            seen_stations.add(station_name)
            police_markers.append(event["police_station"])
        summary = {
            "date": date_key,
            "event_count": len(dashboard_events),
            "critical_count": sum(
                1 for event in dashboard_events if event["risk_level"] == "Critical"
            ),
            "high_or_above": sum(
                1 for event in dashboard_events if event["impact_score"] >= 64.0
            ),
            "average_impact_score": round(
                sum(event["impact_score"] for event in dashboard_events) / len(dashboard_events),
                2,
            )
            if dashboard_events
            else 0.0,
        }
        return {
            "summary": summary,
            "events": dashboard_events,
            "police_markers": police_markers,
        }

    def get_review_window(self, window_index: int = 0) -> Dict[str, Any]:
        calendar = self.get_calendar_window(window_index)
        review_events: List[Dict[str, Any]] = []
        for date_card in calendar["dates"]:
            for event in self.get_day_dashboard(date_card["date"])["events"]:
                review_events.append(
                    {
                        "event_id": event["event_id"],
                        "title": event["title"],
                        "date": event["date"],
                        "time": event["time"],
                        "event_cause": event["event_cause"],
                        "priority": event["priority"],
                        "requires_road_closure": event["requires_road_closure"],
                        "latitude": event["latitude"],
                        "longitude": event["longitude"],
                        "event_type": event["event_type"],
                        "end_latitude": event["end_latitude"],
                        "end_longitude": event["end_longitude"],
                        "corridor": event["corridor"],
                        "zone": event["zone"],
                        "predicted_impact_score": event["impact_score"],
                        "predicted_risk_level": event["risk_level"],
                        "impact_color": event["impact_color"],
                        "resource_plan": event["resource_plan"],
                        "dropdown_options": {
                            "actual_impact_scores": list(range(10, 101, 5)),
                            "observed_severity": ["Low", "Medium", "High", "Critical"],
                            "crowd_levels": ["Very Low", "Low", "Medium", "High", "Very High"],
                        },
                    }
                )
        return {
            "window_index": calendar["window_index"],
            "start_date": calendar["start_date"],
            "end_date": calendar["end_date"],
            "events": review_events,
        }

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
        score_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        return self._predict_with_component_scores(
            event_cause=event_cause,
            priority=priority,
            requires_road_closure=requires_road_closure,
            latitude=latitude,
            longitude=longitude,
            event_type=event_type,
            start_datetime=start_datetime,
            end_latitude=end_latitude,
            end_longitude=end_longitude,
            expected_attendance=expected_attendance,
            score_overrides=score_overrides,
        )

    def _predict_with_component_scores(
        self,
        *,
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
        score_overrides: Optional[Dict[str, float]] = None,
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
        if score_overrides:
            hotspot_score = float(score_overrides.get("hotspot_score", hotspot_score))
            corridor_score = float(score_overrides.get("corridor_score", corridor_score))
            spread_score = float(score_overrides.get("spread_score", spread_score))
            temporal_score = float(score_overrides.get("temporal_score", temporal_score))

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
                "live_traffic_score": round(float((score_overrides or {}).get("live_traffic_score", 0.0)), 2),
                "slowdown_ratio": round(float((score_overrides or {}).get("slowdown_ratio", 0.0)), 3),
                "jam_share": round(float((score_overrides or {}).get("jam_share", 0.0)), 4),
                "slow_share": round(float((score_overrides or {}).get("slow_share", 0.0)), 4),
                "weights": weights,
                "bias": self.state["bias"],
            },
        }

    def _node_lookup(self) -> Dict[str, Dict[str, Any]]:
        return {node["grid_id"]: node for node in self.analytics["graph_nodes"]}

    def _sample_route_points(
        self, path_points: List[Dict[str, float]], max_points: int = 24
    ) -> List[Tuple[float, float]]:
        if not path_points:
            return []
        if len(path_points) <= max_points:
            return [
                (float(point["latitude"]), float(point["longitude"]))
                for point in path_points
            ]
        sampled: List[Tuple[float, float]] = []
        last_index = len(path_points) - 1
        for index in range(max_points):
            point_index = round(index * last_index / max(max_points - 1, 1))
            point = path_points[point_index]
            sampled.append((float(point["latitude"]), float(point["longitude"])))
        return sampled

    def _route_exposure_score(
        self,
        path_points: List[Dict[str, float]],
        hazard: Optional[Dict[str, Any]] = None,
    ) -> float:
        sampled_points = self._sample_route_points(path_points)
        if not sampled_points:
            return 100.0
        exposures = [
            self._nearest_grid_score(latitude, longitude)
            for latitude, longitude in sampled_points
        ]
        average_exposure = sum(exposures) / len(exposures)
        hazard_penalty = 0.0
        if hazard:
            for latitude, longitude in sampled_points:
                hazard_distance = haversine_km(
                    (latitude, longitude),
                    (hazard["latitude"], hazard["longitude"]),
                )
                if hazard_distance < hazard["avoidance_radius_km"]:
                    hazard_penalty += (
                        (hazard["impact_score"] / 100.0)
                        * (hazard["avoidance_radius_km"] - hazard_distance)
                        * 8.0
                    )
        return round(average_exposure + hazard_penalty, 2)

    def _normalize_exposure_score(self, raw_exposure_score: float) -> int:
        floor_score = 75.0
        ceiling_score = 350.0
        clamped_score = clamp(raw_exposure_score, floor_score, ceiling_score)
        normalized_score = 1 + (
            ((clamped_score - floor_score) / (ceiling_score - floor_score)) * 99.0
        )
        return int(round(clamp(normalized_score, 1.0, 100.0)))

    def _route_rank_score(
        self,
        exposure_score: float,
        duration_seconds: float,
        baseline_duration_seconds: float,
    ) -> float:
        duration_penalty = 0.0
        if baseline_duration_seconds > 0:
            duration_penalty = (
                max(duration_seconds - baseline_duration_seconds, 0.0)
                / baseline_duration_seconds
            ) * 18.0
        return round(exposure_score + duration_penalty, 2)

    def _google_rerank_reason(
        self,
        normalized_exposure_score: int,
        duration_seconds: float,
        baseline_duration_seconds: float,
    ) -> str:
        minutes = round(duration_seconds / 60.0, 1)
        if baseline_duration_seconds <= 0:
            return f"Chosen for the lowest GridLock exposure score at roughly {minutes} min."
        baseline_minutes = baseline_duration_seconds / 60.0
        if normalized_exposure_score <= 35:
            return (
                f"Chosen for the safest corridor profile with low exposure ({normalized_exposure_score}/100) "
                f"at about {minutes} min."
            )
        if duration_seconds <= baseline_duration_seconds * 1.08:
            return (
                f"Chosen for balanced live travel time ({minutes} min vs {baseline_minutes:.1f} min best) "
                f"and lower congestion exposure."
            )
        return (
            f"Chosen despite a slightly longer ETA ({minutes} min) because the risk path "
            f"score is lower than faster alternatives."
        )

    def _format_google_reranked_routes(
        self,
        origin_station: Dict[str, Any],
        destination_event: Dict[str, Any],
        google_routes: List[Dict[str, Any]],
        hazard: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not google_routes:
            return []
        baseline_duration_seconds = min(
            (route["duration_seconds"] for route in google_routes),
            default=0.0,
        )
        ranked_routes: List[Dict[str, Any]] = []
        for route in google_routes:
            raw_exposure_score = self._route_exposure_score(route["path_points"], hazard)
            normalized_exposure_score = self._normalize_exposure_score(raw_exposure_score)
            rank_score = self._route_rank_score(
                exposure_score=raw_exposure_score,
                duration_seconds=route["duration_seconds"],
                baseline_duration_seconds=baseline_duration_seconds,
            )
            ranked_routes.append(
                {
                    "route_label": f"Option {len(ranked_routes) + 1}",
                    "recommended": False,
                    "route_source": "google_gridlock_reranked",
                    "origin_station": origin_station,
                    "destination_event": destination_event,
                    "encoded_polyline": route["encoded_polyline"],
                    "path_points": route["path_points"],
                    "waypoints": route["path_points"],
                    "google_duration_seconds": round(route["duration_seconds"], 2),
                    "google_duration_minutes": round(route["duration_seconds"] / 60.0, 1),
                    "google_distance_km": round(route["distance_meters"] / 1000.0, 2),
                    "average_exposure_score": raw_exposure_score,
                    "gridlock_exposure_score": normalized_exposure_score,
                    "estimated_distance_km": round(route["distance_meters"] / 1000.0, 2),
                    "estimated_travel_multiplier": round(
                        1 + (normalized_exposure_score / 100.0),
                        2,
                    ),
                    "rerank_score": rank_score,
                    "rerank_reason": self._google_rerank_reason(
                        normalized_exposure_score,
                        route["duration_seconds"],
                        baseline_duration_seconds,
                    ),
                    "travel_advisory": route.get("travel_advisory", {}),
                }
            )
        ranked_routes.sort(key=lambda item: item["rerank_score"])
        for index, route in enumerate(ranked_routes):
            route["route_label"] = f"Option {index + 1}"
            route["recommended"] = index == 0
        return ranked_routes

    def get_route_context(self, event_id: str) -> Optional[Dict[str, Any]]:
        event = self._event_record(event_id)
        if not event:
            return None
        destination_event = self._event_dashboard_payload(event)
        return {
            "origin_station": destination_event["police_station"],
            "destination_event": destination_event,
        }

    def get_hotspot_impact_details(self, event_id: str) -> Dict[str, Any]:
        route_context = self.get_route_context(event_id)
        if not route_context:
            raise ValueError("Selected hotspot was not found.")
        destination_event = route_context["destination_event"]
        origin_station = route_context["origin_station"]
        google_result = self.google_routes_client.compute_routes(
            origin=(origin_station["latitude"], origin_station["longitude"]),
            destination=(destination_event["latitude"], destination_event["longitude"]),
            alternatives=2,
            routing_preference="TRAFFIC_AWARE",
        )

        primary_affected_roads: List[Dict[str, Any]] = []
        source = "historical_fallback"
        unavailable_reason = None
        if google_result.get("ok") and google_result.get("routes"):
            source = "google_on_demand"
            primary_affected_roads = self._route_interval_segments(google_result["routes"][0])
            if not primary_affected_roads:
                primary_affected_roads = [
                    {
                        "label": destination_event["corridor"],
                        "severity": "Slow Movement",
                        "corridor": destination_event["corridor"],
                        "start_junction": destination_event["junction"],
                        "end_junction": destination_event["junction"],
                        "approx_length_km": None,
                    }
                ]
        else:
            unavailable_reason = google_result.get("error") or "google_unavailable"
            primary_affected_roads = [
                {
                    "label": destination_event["corridor"],
                    "severity": destination_event["risk_level"],
                    "corridor": destination_event["corridor"],
                    "start_junction": destination_event["junction"],
                    "end_junction": destination_event["junction"],
                    "approx_length_km": None,
                }
            ]

        return {
            "event_id": destination_event["event_id"],
            "title": destination_event["title"],
            "source": source,
            "lane_level_available": False,
            "lane_note": "Exact lane-level impact is not directly available from the current Google-backed setup; road-level impact is shown.",
            "location": {
                "address": destination_event["address"],
                "corridor": destination_event["corridor"],
                "junction": destination_event["junction"],
                "zone": destination_event["zone"],
            },
            "nearest_police_station": origin_station,
            "impact_score": destination_event["impact_score"],
            "risk_level": destination_event["risk_level"],
            "resource_plan": destination_event["resource_plan"],
            "diversion_required": destination_event["diversion_required"],
            "diversion_suggestions": destination_event["diversion_suggestions"],
            "primary_affected_roads": primary_affected_roads,
            "advisory": destination_event["alert"]["message"],
            "google_unavailable_reason": unavailable_reason,
        }

    def _nearest_node_ids(
        self, latitude: float, longitude: float, limit: int = 4
    ) -> List[Tuple[str, float]]:
        ranked: List[Tuple[float, str]] = []
        for node in self.analytics["graph_nodes"]:
            distance_km = haversine_km((latitude, longitude), (node["latitude"], node["longitude"]))
            ranked.append((distance_km, node["grid_id"]))
        ranked.sort(key=lambda item: item[0])
        return [(node_id, distance_km) for distance_km, node_id in ranked[:limit]]

    def _nearest_graph_context(self, latitude: float, longitude: float) -> Dict[str, Any]:
        nearest_node = None
        nearest_distance = float("inf")
        for node in self.analytics["graph_nodes"]:
            distance_km = haversine_km((latitude, longitude), (node["latitude"], node["longitude"]))
            if distance_km < nearest_distance:
                nearest_distance = distance_km
                nearest_node = node
        if not nearest_node:
            return {
                "corridor": "Unknown",
                "junction": "Unknown",
                "zone": "Zone unavailable",
                "distance_km": None,
            }
        return {
            "corridor": nearest_node.get("corridor", "Unknown"),
            "junction": nearest_node.get("junction", "Unknown"),
            "zone": nearest_node.get("zone", "Zone unavailable"),
            "distance_km": round(nearest_distance, 2),
        }

    def _route_interval_segments(self, route: Dict[str, Any]) -> List[Dict[str, Any]]:
        path_points = route.get("path_points") or []
        travel_advisory = route.get("travel_advisory") or {}
        intervals = travel_advisory.get("speedReadingIntervals") or []
        segments: List[Dict[str, Any]] = []
        seen = set()
        for interval in intervals:
            severity = clean_text(interval.get("speed"), "NORMAL").upper()
            if severity == "NORMAL":
                continue
            start_index = int(interval.get("startPolylinePointIndex", 0) or 0)
            end_index = int(interval.get("endPolylinePointIndex", start_index + 1) or (start_index + 1))
            if not path_points:
                continue
            start_index = max(0, min(start_index, len(path_points) - 1))
            end_index = max(start_index, min(end_index, len(path_points) - 1))
            start_point = path_points[start_index]
            end_point = path_points[end_index]
            start_context = self._nearest_graph_context(start_point["latitude"], start_point["longitude"])
            end_context = self._nearest_graph_context(end_point["latitude"], end_point["longitude"])
            start_junction = start_context["junction"]
            end_junction = end_context["junction"]
            corridor = start_context["corridor"]
            if corridor != end_context["corridor"] and end_context["corridor"] != "Unknown":
                corridor = f"{corridor} -> {end_context['corridor']}"
            label = corridor
            if start_junction != "Unknown" or end_junction != "Unknown":
                label = f"{corridor} via {start_junction} -> {end_junction}"
            key = (severity, label)
            if key in seen:
                continue
            seen.add(key)
            approx_length_km = haversine_km(
                (start_point["latitude"], start_point["longitude"]),
                (end_point["latitude"], end_point["longitude"]),
            )
            segments.append(
                {
                    "label": label,
                    "severity": "Traffic Jam" if severity == "TRAFFIC_JAM" else "Slow Movement",
                    "corridor": corridor,
                    "start_junction": start_junction,
                    "end_junction": end_junction,
                    "approx_length_km": round(approx_length_km, 2),
                }
            )
        return segments

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

    def _recommend_route_fallback(
        self,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        event_context: Optional[Dict[str, Any]] = None,
        alternatives: int = 3,
        origin_station: Optional[Dict[str, Any]] = None,
        destination_event: Optional[Dict[str, Any]] = None,
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
            route["route_source"] = "gridlock_fallback"
            route["origin_station"] = origin_station
            route["destination_event"] = destination_event
            route["encoded_polyline"] = None
            route["path_points"] = route["waypoints"]
            route["google_duration_seconds"] = None
            route["google_duration_minutes"] = None
            route["google_distance_km"] = None
            route["gridlock_exposure_score"] = self._normalize_exposure_score(
                route["average_exposure_score"]
            )
            route["rerank_reason"] = "Fallback GridLock route used because live Google routing was unavailable."
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
            "route_source": "gridlock_fallback",
            "origin_station": origin_station,
            "destination_event": destination_event,
            "routes": ranked_routes,
        }

    def recommend_route(
        self,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        event_context: Optional[Dict[str, Any]] = None,
        alternatives: int = 3,
        origin_station: Optional[Dict[str, Any]] = None,
        destination_event: Optional[Dict[str, Any]] = None,
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
        google_result = self.google_routes_client.compute_routes(
            origin=(origin_latitude, origin_longitude),
            destination=(destination_latitude, destination_longitude),
            alternatives=alternatives,
        )
        if google_result.get("ok"):
            ranked_routes = self._format_google_reranked_routes(
                origin_station=origin_station or self._station_payload("Control"),
                destination_event=destination_event or {
                    "event_id": None,
                    "title": "Manual destination",
                    "latitude": destination_latitude,
                    "longitude": destination_longitude,
                },
                google_routes=google_result["routes"],
                hazard=hazard,
            )
            if ranked_routes:
                return {
                    "origin": {"latitude": origin_latitude, "longitude": origin_longitude},
                    "destination": {
                        "latitude": destination_latitude,
                        "longitude": destination_longitude,
                    },
                    "hazard_context": hazard,
                    "route_source": "google_gridlock_reranked",
                    "origin_station": origin_station,
                    "destination_event": destination_event,
                    "routes": ranked_routes,
                }
        fallback_result = self._recommend_route_fallback(
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
            destination_latitude=destination_latitude,
            destination_longitude=destination_longitude,
            event_context=event_context,
            alternatives=alternatives,
            origin_station=origin_station,
            destination_event=destination_event,
        )
        fallback_result["google_error"] = google_result.get("error")
        return fallback_result

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
            "session_id": self.session_id,
            "source": source,
            "notes": notes or "",
            "event_payload": event_payload,
            "predicted_impact_score": prediction["impact_score"],
            "actual_impact_score": round(clamp(actual_impact_score, 0.0, 100.0), 2),
            "error": round(actual_impact_score - prediction["impact_score"], 2),
            "breakdown": prediction["breakdown"],
        }
        self.feedback_log.append(entry)
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
            "session_id": self.session_id,
            "session_started_at": self.session_started_at.isoformat(),
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
        return {
            "retrained": True,
            "state": self.get_learning_state(),
        }
