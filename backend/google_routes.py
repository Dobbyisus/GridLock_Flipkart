import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request


GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _parse_dotenv_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_config_value(name: str, project_root: Path, default: Optional[str] = None) -> Optional[str]:
    direct = os.getenv(name)
    if direct:
        return direct
    for dotenv_path in (project_root / ".env", project_root / "backend" / ".env"):
        dotenv_values = _parse_dotenv_file(dotenv_path)
        if dotenv_values.get(name):
            return dotenv_values[name]
    return default


def _decode_polyline(encoded: str) -> List[Tuple[float, float]]:
    index = 0
    latitude = 0
    longitude = 0
    points: List[Tuple[float, float]] = []
    while index < len(encoded):
        result = 0
        shift = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_latitude = ~(result >> 1) if result & 1 else result >> 1
        latitude += delta_latitude

        result = 0
        shift = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        delta_longitude = ~(result >> 1) if result & 1 else result >> 1
        longitude += delta_longitude
        points.append((latitude / 1e5, longitude / 1e5))
    return points


def _parse_duration_seconds(duration_text: str) -> float:
    if not duration_text:
        return 0.0
    return float(str(duration_text).rstrip("s") or 0.0)


class GoogleRoutesClient:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.api_key = _load_config_value("GOOGLE_MAPS_API_KEY", project_root)
        self.timeout_seconds = float(
            _load_config_value("GOOGLE_ROUTES_TIMEOUT_SECONDS", project_root, "6.0") or "6.0"
        )
        self.max_alternatives = int(
            _load_config_value("GOOGLE_ROUTES_MAX_ALTERNATIVES", project_root, "3") or "3"
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def compute_routes(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        alternatives: int = 3,
        routing_preference: str = "TRAFFIC_AWARE",
    ) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "ok": False,
                "error": "google_api_key_missing",
                "routes": [],
            }

        candidate_limit = max(1, min(int(alternatives), self.max_alternatives))
        payload = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": origin[0],
                        "longitude": origin[1],
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": destination[0],
                        "longitude": destination[1],
                    }
                }
            },
            "travelMode": "DRIVE",
            "routingPreference": routing_preference,
            "computeAlternativeRoutes": candidate_limit > 1,
            "polylineEncoding": "ENCODED_POLYLINE",
            "polylineQuality": "OVERVIEW",
            "languageCode": "en-US",
            "units": "METRIC",
        }
        field_mask = ",".join(
            [
                "routes.duration",
                "routes.distanceMeters",
                "routes.polyline.encodedPolyline",
                "routes.legs.duration",
                "routes.legs.distanceMeters",
                "routes.travelAdvisory.speedReadingIntervals",
            ]
        )
        req = request.Request(
            GOOGLE_ROUTES_URL,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": field_mask,
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            response_text = exc.read().decode("utf-8", errors="ignore")
            return {
                "ok": False,
                "error": f"google_http_{exc.code}",
                "details": response_text,
                "routes": [],
            }
        except error.URLError as exc:
            return {
                "ok": False,
                "error": "google_network_error",
                "details": str(exc.reason),
                "routes": [],
            }

        raw_routes = body.get("routes", [])[:candidate_limit]
        routes: List[Dict[str, Any]] = []
        for index, route in enumerate(raw_routes):
            encoded_polyline = (
                route.get("polyline", {}) or {}
            ).get("encodedPolyline")
            path_points = _decode_polyline(encoded_polyline) if encoded_polyline else []
            duration_seconds = _parse_duration_seconds(route.get("duration", "0s"))
            distance_meters = float(route.get("distanceMeters") or 0.0)
            routes.append(
                {
                    "google_route_index": index,
                    "encoded_polyline": encoded_polyline,
                    "path_points": [
                        {"latitude": round(latitude, 5), "longitude": round(longitude, 5)}
                        for latitude, longitude in path_points
                    ],
                    "duration_seconds": duration_seconds,
                    "distance_meters": distance_meters,
                    "travel_advisory": route.get("travelAdvisory", {}),
                }
            )
        return {
            "ok": bool(routes),
            "error": None if routes else "google_no_routes",
            "routes": routes,
        }
