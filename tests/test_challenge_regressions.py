"""Regression tests for the challenge-build correctness fixes.

All tracks, incidents and events here are generated fixtures, not measured
traffic or accuracy ground truth.
"""

from __future__ import annotations

import numpy as np
import pytest

from conflict_detector import MotionState, _following_conflict, detect_conflicts, diagnose_conflicts
from nearmiss.config import DEFAULT_CONFLICT_CONFIG
from nearmiss.incidents import detect_suspected_collisions
from nearmiss.report import report_cache_key
from nearmiss.store import (
    acknowledge_notification,
    list_notifications,
    list_reviews,
    review_incident,
)
from nearmiss.video import tracks_to_csv

from test_conflict_detector import ZONE, horizontal, trajectory, vertical
from test_incident_workflow import collision_tracks, incident_fixture


FOLLOW_TIMES = [index / 10 for index in range(16)]


def following(lead_speed: float = 10.0, lead_start: float = 30.0, lead_y: float = 50.0):
    trailing = [(t, 10.0 + 20.0 * t, 50.0) for t in FOLLOW_TIMES]
    leading = [(t, lead_start + lead_speed * t, lead_y) for t in FOLLOW_TIMES]
    return trajectory(1, trailing) + trajectory(2, leading)


# --------------------------------------------------- same-direction geometry


def test_trailing_vehicle_closing_on_slower_leader_raises_following_warning():
    # Trailing x=10+20t and leading x=30+10t meet at t=2, inside the horizon.
    events = detect_conflicts(following(), ZONE, DEFAULT_CONFLICT_CONFIG)
    assert len(events) == 1
    event = events[0]
    assert event["conflict_geometry"] == "same_direction_following"
    assert event["first_alert_timestamp_seconds"] < 1.5
    assert event["follower_track_id"] == 1 and event["leader_track_id"] == 2
    assert 0 < event["time_to_conflict_seconds"] <= DEFAULT_CONFLICT_CONFIG["prediction_horizon_seconds"]
    assert "trailing vehicle" in event["description"]


def test_following_branch_is_what_finds_the_same_lane_case():
    config = {**DEFAULT_CONFLICT_CONFIG, "same_direction_following_enabled": False}
    assert detect_conflicts(following(), ZONE, config) == []
    reasons = {row["rejection_reason"] for row in diagnose_conflicts(following(), ZONE, DEFAULT_CONFLICT_CONFIG)}
    assert "accepted" in reasons


def test_same_direction_without_closing_or_in_another_lane_is_not_flagged():
    # Equal speeds never close.
    assert detect_conflicts(following(lead_speed=20.0), ZONE, DEFAULT_CONFLICT_CONFIG) == []
    # A faster vehicle in an adjacent lane (30px lateral offset) is not a rear-end conflict.
    assert detect_conflicts(following(lead_y=80.0), ZONE, DEFAULT_CONFLICT_CONFIG) == []


def test_following_contact_beyond_look_ahead_is_not_flagged():
    # Gap of 70px closing at 10px/s needs ~6s, far past the 2s horizon.
    assert detect_conflicts(following(lead_start=80.0), ZONE, DEFAULT_CONFLICT_CONFIG) == []


def _state(track_id: int, position, velocity, width: float = 10.0):
    x, y = position
    return MotionState(
        logical_id=track_id, object_type="vehicle", class_name="car",
        current_track_id=track_id, source_track_ids=(track_id,), frame_index=0,
        timestamp=0.0, position=np.array(position, dtype=float),
        velocity=np.array(velocity, dtype=float),
        bbox=[x - width / 2, y - 10.0, x + width / 2, y],
        observation_count=5, mean_confidence=0.9, velocity_samples=4,
    )


def _follow(follower, leader):
    # Width 10px with the default 0.20 footprint fraction gives radius 2 each.
    return _following_conflict(
        follower, leader, conflict_region_radius=4.0, effective_margin=1.0,
        horizon=2.0, min_future_time=0.05, config=DEFAULT_CONFLICT_CONFIG,
    )


def test_following_contact_time_accounts_for_lateral_offset():
    follower = _state(1, (10.0, 50.0), (20.0, 0.0))
    leader = _state(2, (28.0, 53.5), (10.0, 0.0))
    result = _follow(follower, leader)
    assert result is not None
    # Longitudinal-only shortcut would say (18-4)/10 = 1.4s with 5.3px separation.
    assert result["first_eta"] == pytest.approx(1.6063, abs=1e-3)
    separation = np.linalg.norm(result["second_point"] - result["first_point"])
    assert separation == pytest.approx(4.0, abs=1e-6)


def test_following_offset_wider_than_footprints_never_reports_contact():
    follower = _state(1, (10.0, 50.0), (20.0, 0.0))
    leader = _state(2, (28.0, 54.5), (10.0, 0.0))  # 4.5px lateral > 4px radius
    assert _follow(follower, leader) is None


def test_following_contact_includes_relative_lateral_drift():
    follower = _state(1, (10.0, 50.0), (24.0, 0.0))
    parallel = _follow(follower, _state(2, (28.0, 53.5), (14.0, 0.0)))
    toward = _follow(follower, _state(2, (28.0, 53.5), (14.0, -1.0)))
    assert parallel is not None and toward is not None
    separation = np.linalg.norm(toward["second_point"] - toward["first_point"])
    assert separation == pytest.approx(4.0, abs=1e-6)
    assert toward["first_eta"] < parallel["first_eta"]
    # Drifting away keeps the circles apart for the whole horizon.
    assert _follow(follower, _state(2, (28.0, 53.5), (14.0, 1.0))) is None


def test_crossing_events_keep_their_original_geometry_and_label():
    events = detect_conflicts(
        trajectory(1, horizontal()) + trajectory(2, vertical(), "truck"), ZONE, DEFAULT_CONFLICT_CONFIG
    )
    assert len(events) == 1
    assert events[0]["severity"] == "HIGH"
    assert events[0]["conflict_geometry"] == "crossing_paths"


# ------------------------------------------------------ incident association


def prediction(event_id: str, warning_time: float) -> dict:
    return {
        "event_id": event_id,
        "first_alert_timestamp_seconds": warning_time,
        "participant_a_track_ids": [1],
        "participant_b_track_ids": [2],
    }


def test_warning_after_first_contact_is_not_called_a_prediction():
    impact = detect_suspected_collisions(collision_tracks(), [], "synthetic")[0]["timestamp_seconds"]
    late = detect_suspected_collisions(
        collision_tracks(), [prediction("late", impact + 0.2)], "synthetic"
    )[0]
    assert late["associated_prediction_event_id"] is None
    assert late["prediction_lead_seconds"] is None
    simultaneous = detect_suspected_collisions(
        collision_tracks(), [prediction("same", impact)], "synthetic"
    )[0]
    assert simultaneous["associated_prediction_event_id"] is None


def test_warning_before_contact_is_associated_with_positive_lead():
    impact = detect_suspected_collisions(collision_tracks(), [], "synthetic")[0]["timestamp_seconds"]
    incident = detect_suspected_collisions(
        collision_tracks(),
        [prediction("late", impact + 0.1), prediction("early", impact - 0.5)],
        "synthetic",
    )[0]
    assert incident["associated_prediction_event_id"] == "early"
    assert incident["prediction_lead_seconds"] == 0.5


def inside(point, bbox) -> bool:
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def test_contact_point_comes_from_the_same_frame_as_timestamp_and_boxes():
    # Boxes close at different speeds so first-contact and peak overlap differ.
    first, second = [], []
    for index in range(16):
        t = index / 10
        if t <= 0.8:
            first.append((t, 10.0 + 50.0 * t, 50.0))
            second.append((t, 50.0, 10.0 + 50.0 * t))
        else:
            first.append((t, 52.0, 50.0))
            second.append((t, 50.0, 52.0))
    from test_incident_workflow import track

    incident = detect_suspected_collisions(track(1, first) + track(2, second), [], "synthetic")[0]
    assert inside(incident["contact_point"], incident["vehicle_a_bbox"])
    assert inside(incident["contact_point"], incident["vehicle_b_bbox"])
    assert incident["frame_index"] <= incident["measurements"]["peak_overlap_frame_index"]
    assert "peak_contact_point" in incident["measurements"]


# --------------------------------------------------------- dispatch reversal


def test_reversed_confirmation_withdraws_notification_and_reconfirm_restores(tmp_path):
    database = tmp_path / "review.db"
    incident = incident_fixture()
    _review, notification = review_incident(incident, "Confirmed Incident", "CAM", database)
    acknowledge_notification(notification["notification_id"], database)

    review_incident(incident, "False Alarm", "CAM", database)
    withdrawn = list_notifications("synthetic-video", database)
    assert len(withdrawn) == 1
    assert withdrawn[0]["status"] == "Withdrawn"
    assert withdrawn[0]["summary"]["operator_confirmation"] == "False Alarm"
    assert list_reviews("synthetic-video", database)[0]["review_status"] == "False Alarm"
    # A withdrawn notification cannot be acknowledged again.
    assert acknowledge_notification(notification["notification_id"], database)["status"] == "Withdrawn"

    review_incident(incident, "Uncertain", "CAM", database)
    assert list_notifications("synthetic-video", database)[0]["summary"]["operator_confirmation"] == "Uncertain"

    review_incident(incident, "Confirmed Incident", "CAM", database)
    restored = list_notifications("synthetic-video", database)
    assert len(restored) == 1
    assert restored[0]["status"] == "New"
    assert restored[0]["acknowledged_at"] is None
    assert restored[0]["summary"]["operator_confirmation"] == "Confirmed Incident"


def test_unconfirmed_review_without_notification_creates_none(tmp_path):
    database = tmp_path / "review.db"
    review_incident(incident_fixture(), "Uncertain", "CAM", database)
    assert list_notifications("synthetic-video", database) == []


# ------------------------------------------------------- report cache key


def test_report_cache_key_changes_with_thresholds_zone_and_reviews():
    base = {
        "video": "abc",
        "conflict_config": dict(DEFAULT_CONFLICT_CONFIG),
        "zone": [],
        "events": [{"event_id": "conflict-001"}],
        "reviews": {},
    }
    key = report_cache_key(base)
    assert key == report_cache_key(dict(base))
    changed_threshold = {**base, "conflict_config": {**base["conflict_config"], "high_time_gap_seconds": 0.3}}
    changed_zone = {**base, "zone": [[0, 0], [10, 0], [10, 10]]}
    changed_review = {**base, "reviews": {"conflict-001": "False positive"}}
    assert len({key, report_cache_key(changed_threshold), report_cache_key(changed_zone),
                report_cache_key(changed_review)}) == 4


def test_track_csv_adds_provenance_column_only_when_rows_carry_it():
    row = trajectory(1, horizontal())[0]
    assert "data_source" not in tracks_to_csv([row]).decode().splitlines()[0]
    tagged = tracks_to_csv([{**row, "data_source": "synthetic_demo"}]).decode()
    assert tagged.splitlines()[0].endswith("data_source")
    assert tagged.splitlines()[1].endswith("synthetic_demo")
