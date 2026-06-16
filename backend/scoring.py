from datetime import datetime
from typing import Optional

from engine import GridlockRecommendationEngine


ENGINE = GridlockRecommendationEngine()


def recommend_resources(
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
):
    return ENGINE.predict(
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
    )
