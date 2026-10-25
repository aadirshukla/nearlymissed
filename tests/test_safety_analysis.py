"""Synthetic event tests for dashboard metrics, visuals, review, and reports."""

from __future__ import annotations

import cv2
import numpy as np

from nearmiss.report import generate_safety_report
from nearmiss.safety import (
    build_conflict_heatmap,
    deduplicate_events,
    events_with_review_labels,
    normalized_heatmap_points,
    safety_statistics,
    timeline_rows,
)


TRACKS = [
    {"track_id": 1, "object_type": "vehicle"},
    {"track_id": 1, "object_type": "vehicle"},
    {"track_id": 2, "object_type": "vehicle"},
]


def event(
    event_id: str,
    timestamp: float,
    severity: str = "HIGH",
    point: list[float] | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "timestamp_seconds": timestamp,
        "first_alert_timestamp_seconds": timestamp,
        "end_timestamp_seconds": timestamp + 0.4,
        "severity": severity,
        "risk_score": 82.0,
        "participant_a_track_id": 1,
        "participant_b_track_id": 2,
        "participant_a_class": "car",
        "participant_b_class": "truck",
        "arrival_time_gap_seconds": 0.2,
        "time_to_conflict_seconds": 0.5,
        "conflict_point": point if point is not None else [40.0, 30.0],
        "description": "Synthetic test candidate.",
    }


def test_no_conflicts_produces_measured_zero_and_unmodified_frame():
    frame = np.full((60, 100, 3), 30, dtype=np.uint8)
    statistics = safety_statistics(TRACKS, [], 10.0)
    heatmap, points = build_conflict_heatmap(frame, [])
    assert statistics["total_conflicts"] == 0
    assert statistics["conflicts_per_minute"] == 0.0
    assert points == []
    assert np.array_equal(heatmap, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def test_continuous_pair_alerts_are_deduplicated():
    assert len(deduplicate_events([event("a", 1.0), event("b", 1.5, "MEDIUM")])) == 1


def test_heatmap_coordinates_align_with_source_frame():
    points = normalized_heatmap_points([event("a", 1.0, point=[25.0, 30.0])], 100, 60)
    assert points[0]["x_normalized"] == 0.25
    assert points[0]["y_normalized"] == 0.5


def test_timeline_uses_detector_first_alert_and_measurements():
    rows = timeline_rows([event("a", 1.25)])
    assert rows == [
        {
            "event_id": "a",
            "timestamp_seconds": 1.25,
            "severity": "HIGH",
            "risk_score": 82.0,
            "participant_a_track_id": 1,
            "participant_b_track_id": 2,
            "time_to_conflict_seconds": 0.5,
            "arrival_time_gap_seconds": 0.2,
        }
    ]


def test_human_review_labels_survive_export_enrichment():
    reviewed = events_with_review_labels([event("a", 1.0)], {"a": "False positive"})
    assert reviewed[0]["human_review_status"] == "False positive"
    assert "human_review_status" not in event("a", 1.0)


def test_report_statistics_match_underlying_records():
    statistics = safety_statistics(TRACKS, [event("a", 1.0)], 30.0)
    assert statistics["vehicles_tracked"] == 2
    assert statistics["total_conflicts"] == 1
    assert statistics["high_conflicts"] == 1
    assert statistics["conflicts_per_minute"] == 2.0
    assert statistics["average_arrival_gap_seconds"] == 0.2


def test_pdf_generation_supports_zero_and_multiple_events():
    heatmap = np.zeros((60, 100, 3), dtype=np.uint8)
    zero_pdf = generate_safety_report(
        source_filename="zero.mp4",
        duration_seconds=10.0,
        tracks=TRACKS,
        events=[],
        heatmap_rgb=heatmap,
    )
    multiple_pdf = generate_safety_report(
        source_filename="events.mp4",
        duration_seconds=10.0,
        tracks=TRACKS,
        events=[event("a", 1.0), {**event("b", 5.0, "LOW"), "participant_b_track_id": 3}],
        heatmap_rgb=heatmap,
        review_labels={"a": "Confirmed potential conflict"},
        event_frames={"a": heatmap},
    )
    assert zero_pdf.startswith(b"%PDF")
    assert multiple_pdf.startswith(b"%PDF")
    assert len(multiple_pdf) > len(zero_pdf)


def test_malformed_event_fields_are_ignored_or_rendered_safely():
    malformed = {
        "event_id": "bad<&>",
        "first_alert_timestamp_seconds": "not-a-time",
        "severity": "UNKNOWN",
        "arrival_time_gap_seconds": "not-a-number",
        "time_to_conflict_seconds": None,
        "conflict_point": [9999, None],
        "description": "bad <xml> & value",
    }
    heatmap = np.zeros((60, 100, 3), dtype=np.uint8)
    assert normalized_heatmap_points([malformed], 100, 60) == []
    assert timeline_rows([malformed]) == []
    pdf = generate_safety_report(
        source_filename="bad<&>.mp4",
        duration_seconds=10.0,
        tracks=[],
        events=[malformed],
        heatmap_rgb=heatmap,
    )
    assert pdf.startswith(b"%PDF")
