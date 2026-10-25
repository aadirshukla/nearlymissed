"""Synthetic tests for collision evidence, review, and simulated dispatch.

The tracks and incidents in this file are generated fixtures. They are never
presented by the application as real detections.
"""

from __future__ import annotations

from nearmiss.incidents import detect_suspected_collisions
from nearmiss.store import (
    acknowledge_notification,
    list_notifications,
    list_reviews,
    review_incident,
)


TIMES = [index / 10 for index in range(16)]


def track(track_id: int, positions: list[tuple[float, float, float]]) -> list[dict]:
    return [
        {
            "track_id": track_id,
            "object_type": "vehicle",
            "class_name": "car",
            "class_id": 2,
            "frame_index": round(timestamp * 10),
            "timestamp_seconds": timestamp,
            "bbox": [x - 5.0, y - 10.0, x + 5.0, y],
            "center": [x, y - 5.0],
            "confidence": 0.95,
        }
        for timestamp, x, y in positions
    ]


def collision_tracks() -> list[dict]:
    first = []
    second = []
    for timestamp in TIMES:
        if timestamp <= 0.8:
            first.append((timestamp, 10.0 + 50.0 * timestamp, 50.0))
            second.append((timestamp, 50.0, 10.0 + 50.0 * timestamp))
        else:
            first.append((timestamp, 50.0, 50.0))
            second.append((timestamp, 50.0, 50.0))
    return track(1, first) + track(2, second)


def incident_fixture() -> dict:
    return {
        "incident_id": "incident-synthetic-001",
        "source_video_id": "synthetic-video",
        "timestamp_seconds": 0.7,
        "vehicle_a_track_id": 1,
        "vehicle_b_track_id": 2,
        "detection_signals": [
            "persistent_bounding_box_contact",
            "previously_converging_trajectories",
            "sudden_deceleration",
        ],
    }


def test_sudden_deceleration_without_contact_is_not_an_incident():
    first = []
    second = []
    for timestamp in TIMES:
        x = 10.0 + 40.0 * min(timestamp, 0.8)
        first.append((timestamp, x, 30.0))
        second.append((timestamp, 10.0 + 40.0 * timestamp, 75.0))
    tracks = track(1, first) + track(2, second)
    assert detect_suspected_collisions(tracks, [], "synthetic") == []


def test_perspective_overlap_without_motion_response_is_rejected():
    crossing = track(
        1, [(timestamp, 10.0 + 50.0 * timestamp, 50.0) for timestamp in TIMES]
    ) + track(
        2, [(timestamp, 50.0, 10.0 + 50.0 * timestamp) for timestamp in TIMES]
    )
    assert detect_suspected_collisions(crossing, [], "synthetic") == []


def test_suspected_collision_does_not_require_previous_prediction():
    incidents = detect_suspected_collisions(collision_tracks(), [], "synthetic")
    assert len(incidents) == 1
    assert incidents[0]["associated_prediction_event_id"] is None
    assert "sudden_deceleration" in incidents[0]["detection_signals"]


def test_duplicate_track_rows_do_not_create_duplicate_incidents():
    tracks = collision_tracks()
    duplicated = tracks + [dict(row) for row in tracks]
    incidents = detect_suspected_collisions(duplicated, [], "synthetic")
    assert len(incidents) == 1


def test_confirmed_incident_creates_exactly_one_notification(tmp_path):
    database = tmp_path / "review.db"
    incident = incident_fixture()
    review_incident(incident, "Confirmed Incident", "CAM-TEST", database)
    review_incident(incident, "Confirmed Incident", "CAM-TEST", database)
    notifications = list_notifications("synthetic-video", database)
    assert len(notifications) == 1
    assert notifications[0]["status"] == "New"
    assert notifications[0]["summary"]["operator_confirmation"] == "Confirmed Incident"


def test_false_alarm_creates_no_notification(tmp_path):
    database = tmp_path / "review.db"
    review_incident(incident_fixture(), "False Alarm", "CAM-TEST", database)
    assert list_notifications("synthetic-video", database) == []


def test_review_and_notification_persist_across_new_connections(tmp_path):
    database = tmp_path / "review.db"
    incident = incident_fixture()
    _review, notification = review_incident(
        incident, "Confirmed Incident", "CAM-TEST", database
    )
    acknowledge_notification(notification["notification_id"], database)

    reviews_after_restart = list_reviews("synthetic-video", database)
    notifications_after_restart = list_notifications("synthetic-video", database)
    assert reviews_after_restart[0]["review_status"] == "Confirmed Incident"
    assert notifications_after_restart[0]["status"] == "Acknowledged"
    assert notifications_after_restart[0]["acknowledged_at"] is not None
