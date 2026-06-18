import unittest
from unittest.mock import patch

try:
    from .engine import GridlockRecommendationEngine
except ImportError:
    from engine import GridlockRecommendationEngine


class RouteRerankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = GridlockRecommendationEngine()
        cls.sample_event = cls.engine.events[0]
        cls.route_context = cls.engine.get_route_context(cls.sample_event["id"])

    def test_route_context_uses_event_assigned_station(self) -> None:
        self.assertIsNotNone(self.route_context)
        expected_station = self.engine._station_payload(self.sample_event["police_station"])
        self.assertEqual(
            self.route_context["origin_station"]["station_name"],
            expected_station["station_name"],
        )

    def test_fallback_activates_when_google_unavailable(self) -> None:
        with patch.object(
            self.engine.google_routes_client,
            "compute_routes",
            return_value={"ok": False, "error": "google_api_key_missing", "routes": []},
        ):
            result = self.engine.recommend_route(
                origin_latitude=self.route_context["origin_station"]["latitude"],
                origin_longitude=self.route_context["origin_station"]["longitude"],
                destination_latitude=self.route_context["destination_event"]["latitude"],
                destination_longitude=self.route_context["destination_event"]["longitude"],
                event_context={
                    "latitude": self.route_context["destination_event"]["latitude"],
                    "longitude": self.route_context["destination_event"]["longitude"],
                    "impact_score": self.route_context["destination_event"]["impact_score"],
                },
                alternatives=2,
                origin_station=self.route_context["origin_station"],
                destination_event=self.route_context["destination_event"],
            )
        self.assertEqual(result["route_source"], "gridlock_fallback")
        self.assertEqual(result["google_error"], "google_api_key_missing")
        self.assertTrue(result["routes"])

    def test_google_reranking_prefers_lower_exposure_candidate(self) -> None:
        destination = self.route_context["destination_event"]
        origin_station = self.route_context["origin_station"]
        with patch.object(
            self.engine.google_routes_client,
            "compute_routes",
            return_value={
                "ok": True,
                "routes": [
                    {
                        "encoded_polyline": "route-a",
                        "duration_seconds": 540.0,
                        "distance_meters": 3400.0,
                        "travel_advisory": {},
                        "path_points": [
                            {"latitude": destination["latitude"], "longitude": destination["longitude"]},
                            {"latitude": destination["latitude"], "longitude": destination["longitude"]},
                            {"latitude": destination["latitude"], "longitude": destination["longitude"]},
                        ],
                    },
                    {
                        "encoded_polyline": "route-b",
                        "duration_seconds": 610.0,
                        "distance_meters": 3900.0,
                        "travel_advisory": {},
                        "path_points": [
                            {"latitude": origin_station["latitude"], "longitude": origin_station["longitude"]},
                            {
                                "latitude": round((origin_station["latitude"] + destination["latitude"]) / 2, 5),
                                "longitude": round((origin_station["longitude"] + destination["longitude"]) / 2, 5),
                            },
                            {"latitude": destination["latitude"], "longitude": destination["longitude"]},
                        ],
                    },
                ],
            },
        ):
            result = self.engine.recommend_route(
                origin_latitude=origin_station["latitude"],
                origin_longitude=origin_station["longitude"],
                destination_latitude=destination["latitude"],
                destination_longitude=destination["longitude"],
                event_context={
                    "latitude": destination["latitude"],
                    "longitude": destination["longitude"],
                    "impact_score": destination["impact_score"],
                },
                alternatives=2,
                origin_station=origin_station,
                destination_event=destination,
            )
        self.assertEqual(result["route_source"], "google_gridlock_reranked")
        self.assertEqual(result["routes"][0]["route_source"], "google_gridlock_reranked")
        self.assertTrue(result["routes"][0]["recommended"])
        self.assertEqual(result["routes"][0]["encoded_polyline"], "route-b")


if __name__ == "__main__":
    unittest.main()
