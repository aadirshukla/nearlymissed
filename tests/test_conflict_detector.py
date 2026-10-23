"""Synthetic vehicle trajectory tests for the provisional conflict heuristic.

These records are deliberately generated test fixtures. They are not real
traffic observations and are never surfaced by the application as events.
"""

from __future__ import annotations

from conflict_detector import detect_conflicts, diagnose_conflicts


FPS = 10.0
ZONE = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
CONFIG = {
    "prediction_horizon_seconds": 2.0,
    "high_time_gap_seconds": 0.30,
    "medium_time_gap_seconds": 0.80,
    "low_time_gap_seconds": 1.60,
    "path_intersection_tolerance_pixels": 4.0,
    "min_closing_speed_pixels_per_second": 0.10,
    "stationary_speed_pixels_per_second": 0.50,
    "closing_speed_reference_pixels_per_second": 40.0,
    "minimum_time_to_conflict_seconds": 0.02,
    "velocity_smoothing_frames": 4,
    "min_track_age_frames": 4,
    "max_observation_age_seconds": 0.15,
    "duplicate_cooldown_seconds": 2.0,
    "id_stitch_gap_seconds": 0.25,
    "id_stitch_distance_pixels": 8.0,
}


def observation(frame, track_id, object_type, x, y):
    """Create one synthetic bbox whose bottom-center is exactly ``(x, y)``."""

    return {
        "track_id": track_id,
        "class_id": 2,
        "class_name": "car",
        "object_type": object_type,
        "frame_index": frame,
        "timestamp_seconds": frame / FPS,
        "bbox": [x - 2.0, y - 8.0, x + 2.0, y],
        "center": [x, y - 4.0],
        "confidence": 0.95,
    }


def linear_track(
    track_id,
    object_type,
    start,
    velocity,
    frames=range(11),
    missing_frames=frozenset(),
    switched_id=None,
    switch_frame=None,
):
    records = []
    for frame in frames:
        if frame in missing_frames:
            continue
        timestamp = frame / FPS
        x = start[0] + velocity[0] * timestamp
        y = start[1] + velocity[1] * timestamp
        current_id = (
            switched_id
            if switched_id is not None and switch_frame is not None and frame >= switch_frame
            else track_id
        )
        records.append(observation(frame, current_id, object_type, x, y))
    return records


def crossing_tracks():
    vehicle = linear_track(1, "vehicle", (0.0, 50.0), (30.0, 0.0))
    second_vehicle = linear_track(2, "vehicle", (50.0, 0.0), (0.0, 30.0))
    return vehicle + second_vehicle


def test_empty_tracks_return_no_events():
    assert detect_conflicts([], ZONE, CONFIG) == []


def test_same_point_at_nearly_same_time_is_high():
    events = detect_conflicts(crossing_tracks(), ZONE, CONFIG)
    assert len(events) == 1
    event = events[0]
    assert event["severity"] == "HIGH"
    assert event["arrival_time_gap_seconds"] <= CONFIG["high_time_gap_seconds"]
    assert event["vehicle_a_track_id"] == 1
    assert event["vehicle_b_track_id"] == 2
    assert event["inside_conflict_zone"] is True


def test_same_point_at_very_different_times_is_low():
    vehicle = linear_track(1, "vehicle", (20.0, 50.0), (30.0, 0.0))
    second_vehicle = linear_track(2, "vehicle", (50.0, 0.0), (0.0, 20.0))
    events = detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG)
    assert len(events) == 1
    assert events[0]["severity"] == "LOW"
    assert events[0]["arrival_time_gap_seconds"] > CONFIG["medium_time_gap_seconds"]


def test_objects_moving_away_are_ignored():
    vehicle = linear_track(1, "vehicle", (50.0, 50.0), (-20.0, 0.0))
    second_vehicle = linear_track(2, "vehicle", (50.0, 50.0), (0.0, -20.0))
    assert detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG) == []


def test_close_parallel_nonintersecting_paths_are_ignored():
    vehicle = linear_track(1, "vehicle", (10.0, 45.0), (20.0, 0.0))
    second_vehicle = linear_track(2, "vehicle", (10.0, 52.0), (20.0, 0.0))
    assert detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG) == []


def test_stationary_vehicle_and_approaching_vehicle_are_handled():
    vehicle = linear_track(1, "vehicle", (0.0, 50.0), (30.0, 0.0))
    stopped_vehicle = linear_track(2, "vehicle", (50.0, 50.0), (0.0, 0.0))
    events = detect_conflicts(vehicle + stopped_vehicle, ZONE, CONFIG)
    assert len(events) == 1
    assert events[0]["vehicle_b_eta_seconds"] == 0.0
    assert events[0]["closing_speed_pixels_per_second"] > 0


def test_missing_tracking_frames_do_not_break_velocity_prediction():
    vehicle = linear_track(
        1,
        "vehicle",
        (0.0, 50.0),
        (30.0, 0.0),
        missing_frames={4, 6},
    )
    second_vehicle = linear_track(
        2,
        "vehicle",
        (50.0, 0.0),
        (0.0, 30.0),
        missing_frames={5, 7},
    )
    events = detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG)
    assert len(events) == 1
    assert events[0]["severity"] == "HIGH"


def test_brief_id_switch_is_stitched_without_duplicate_event():
    vehicle = linear_track(
        1,
        "vehicle",
        (0.0, 50.0),
        (30.0, 0.0),
        switched_id=99,
        switch_frame=5,
    )
    second_vehicle = linear_track(2, "vehicle", (50.0, 0.0), (0.0, 30.0))
    events = detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG)
    assert len(events) == 1
    assert events[0]["vehicle_a_track_ids"] == [1, 99]


def test_repeated_candidate_frames_collapse_to_one_event():
    frames = range(16)
    vehicle = linear_track(1, "vehicle", (0.0, 50.0), (30.0, 0.0), frames=frames)
    second_vehicle = linear_track(2, "vehicle", (50.0, 0.0), (0.0, 30.0), frames=frames)
    events = detect_conflicts(vehicle + second_vehicle, ZONE, CONFIG)
    assert len(events) == 1
    assert events[0]["start_frame_index"] <= events[0]["end_frame_index"]
    assert events[0]["first_alert_timestamp_seconds"] == events[0]["start_timestamp_seconds"]


def test_multiple_vehicles_produce_only_the_relevant_pairs():
    horizontal = linear_track(1, "vehicle", (0.0, 50.0), (30.0, 0.0))
    vertical = linear_track(2, "vehicle", (50.0, 0.0), (0.0, 30.0))
    parallel = linear_track(3, "vehicle", (0.0, 95.0), (30.0, 0.0))
    events = detect_conflicts(horizontal + vertical + parallel, ZONE, CONFIG)
    assert len(events) == 1
    assert {events[0]["vehicle_a_track_id"], events[0]["vehicle_b_track_id"]} == {1, 2}


def test_vehicle_pedestrian_mode_remains_available():
    vehicle = linear_track(1, "vehicle", (0.0, 50.0), (30.0, 0.0))
    pedestrian = linear_track(2, "pedestrian", (50.0, 0.0), (0.0, 30.0))
    events = detect_conflicts(vehicle + pedestrian, ZONE, {**CONFIG, "analysis_mode": "vehicle_pedestrian"})
    assert len(events) == 1
    assert events[0]["vehicle_track_id"] == 1
    assert events[0]["pedestrian_track_id"] == 2


def test_diagnostics_explain_parallel_pair_rejection():
    first = linear_track(1, "vehicle", (10.0, 45.0), (20.0, 0.0))
    second = linear_track(2, "vehicle", (10.0, 52.0), (20.0, 0.0))
    rows = diagnose_conflicts(first + second, ZONE, CONFIG)
    assert rows
    evaluated = [row for row in rows if "projected_paths_overlap" in row]
    assert evaluated
    assert all(row["rejection_reason"] == "not_closing" for row in evaluated)
    assert all(row["projected_paths_overlap"] is False for row in evaluated)
