"""Synthetic trajectory tests for the heuristic conflict detector.

These records are intentionally generated test data, not measured traffic or
accuracy ground truth.
"""

from __future__ import annotations

from conflict_detector import detect_conflicts, diagnose_conflicts
from nearmiss.config import DEFAULT_CONFLICT_CONFIG


ZONE = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
TIMES = [index / 10 for index in range(21)]


def trajectory(
    track_id: int,
    samples: list[tuple[float, float, float]],
    class_name: str = "car",
) -> list[dict]:
    class_ids = {"car": 2, "motorcycle": 3, "bus": 5, "truck": 7}
    return [
        {
            "track_id": track_id,
            "object_type": "vehicle",
            "class_name": class_name,
            "class_id": class_ids[class_name],
            "frame_index": round(timestamp * 10),
            "timestamp_seconds": timestamp,
            "bbox": [x - 8.0, y - 10.0, x + 8.0, y],
            "center": [x, y - 5.0],
            "confidence": 0.90,
        }
        for timestamp, x, y in samples
    ]


def horizontal(speed: float = 20.0, y: float = 50.0) -> list[tuple[float, float, float]]:
    return [(timestamp, 10.0 + speed * timestamp, y) for timestamp in TIMES]


def vertical(speed: float = 20.0, x: float = 50.0) -> list[tuple[float, float, float]]:
    return [(timestamp, x, 10.0 + speed * timestamp) for timestamp in TIMES]


def test_simultaneous_perpendicular_vehicles_raise_high_warning():
    events = detect_conflicts(
        trajectory(1, horizontal(), "car") + trajectory(2, vertical(), "truck"),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert len(events) == 1
    assert events[0]["severity"] == "HIGH"
    assert events[0]["interaction_type"] == "vehicle_to_vehicle"
    assert events[0]["first_alert_timestamp_seconds"] < 2.0
    assert events[0]["arrival_time_gap_seconds"] <= 0.5


def test_same_crossing_at_different_arrival_times_is_not_high():
    slower_vertical = [(timestamp, 50.0, 20.0 + 10.0 * timestamp) for timestamp in TIMES]
    events = detect_conflicts(
        trajectory(1, horizontal()) + trajectory(2, slower_vertical),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert events
    assert all(event["severity"] != "HIGH" for event in events)


def test_parallel_vehicles_are_rejected():
    tracks = trajectory(1, horizontal(y=40.0)) + trajectory(2, horizontal(y=70.0))
    assert detect_conflicts(tracks, ZONE, DEFAULT_CONFLICT_CONFIG) == []


def test_diverging_vehicles_are_rejected_as_not_closing():
    first = [(timestamp, 50.0 - 20.0 * timestamp, 50.0) for timestamp in TIMES]
    second = [(timestamp, 50.0, 50.0 - 20.0 * timestamp) for timestamp in TIMES]
    tracks = trajectory(1, first) + trajectory(2, second)
    assert detect_conflicts(tracks, ZONE, DEFAULT_CONFLICT_CONFIG) == []
    diagnostics = diagnose_conflicts(tracks, ZONE, DEFAULT_CONFLICT_CONFIG)
    assert "not_closing" in {row["rejection_reason"] for row in diagnostics}


def test_stationary_vehicle_and_approaching_vehicle_are_supported():
    stationary = [(timestamp, 50.0, 50.0) for timestamp in TIMES]
    events = detect_conflicts(
        trajectory(1, stationary, "truck") + trajectory(2, horizontal(), "car"),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert len(events) == 1
    assert events[0]["severity"] in {"MEDIUM", "HIGH"}


def test_missing_frames_do_not_create_duplicate_events():
    intermittent = [sample for index, sample in enumerate(horizontal()) if index not in {7, 8}]
    events = detect_conflicts(
        trajectory(1, intermittent) + trajectory(2, vertical()),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert len(events) == 1
    assert events[0]["persistence_frames"] >= 3


def test_short_tracking_id_change_is_stitched_without_duplicate_alert():
    tracks = (
        trajectory(1, horizontal()[:10])
        + trajectory(9, horizontal()[10:])
        + trajectory(2, vertical(), "truck")
    )
    events = detect_conflicts(tracks, ZONE, DEFAULT_CONFLICT_CONFIG)
    assert len(events) == 1
    stitched_ids = [
        set(events[0]["participant_a_track_ids"]),
        set(events[0]["participant_b_track_ids"]),
    ]
    assert {1, 9} in stitched_ids


def test_single_jitter_jump_does_not_destroy_smoothed_prediction():
    noisy = horizontal()
    timestamp, x, y = noisy[8]
    noisy[8] = (timestamp, x + 80.0, y - 50.0)
    events = detect_conflicts(
        trajectory(1, noisy) + trajectory(2, vertical()),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert len(events) == 1


def test_multiple_vehicles_only_emit_qualifying_pair():
    unrelated = [(timestamp, 90.0, 90.0) for timestamp in TIMES]
    events = detect_conflicts(
        trajectory(1, horizontal(), "bus")
        + trajectory(2, vertical(), "truck")
        + trajectory(3, unrelated, "car"),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    assert len(events) == 1
    assert {events[0]["participant_a_class"], events[0]["participant_b_class"]} == {
        "bus",
        "truck",
    }


def test_temporal_confirmation_reason_is_exposed():
    diagnostics = diagnose_conflicts(
        trajectory(1, horizontal()) + trajectory(2, vertical()),
        ZONE,
        DEFAULT_CONFLICT_CONFIG,
    )
    pending = [row for row in diagnostics if row["rejection_reason"] == "pending_temporal_confirmation"]
    accepted = [row for row in diagnostics if row["rejection_reason"] == "accepted"]
    assert pending
    assert accepted
    assert pending[0]["temporal_confirmation_met"] is False
    assert accepted[0]["temporal_confirmation_met"] is True


def test_selected_zone_can_exclude_otherwise_qualifying_conflict():
    remote_zone = [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]
    tracks = trajectory(1, horizontal()) + trajectory(2, vertical())
    assert detect_conflicts(tracks, remote_zone, DEFAULT_CONFLICT_CONFIG) == []
    diagnostics = diagnose_conflicts(tracks, remote_zone, DEFAULT_CONFLICT_CONFIG)
    assert "conflict_point_outside_zone" in {
        row["rejection_reason"] for row in diagnostics
    }
