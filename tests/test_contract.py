from __future__ import annotations

import json

import pandas as pd
import pyarrow as pa

from conflict_detector import detect_conflicts
from nearmiss.events import events_to_csv, format_timestamp, normalize_events
from nearmiss.geometry import enrich_tracks_with_zone, point_in_polygon
from nearmiss.video import tracks_to_csv, validate_upload, video_digest


SAMPLE_TRACK = {
    "track_id": 4,
    "class_id": 0,
    "class_name": "person",
    "object_type": "pedestrian",
    "frame_index": 15,
    "timestamp_seconds": 0.5,
    "bbox": [10.0, 20.0, 30.0, 50.0],
    "center": [20.0, 35.0],
    "confidence": 0.9,
}


def test_conflict_detector_requires_sufficient_track_history():
    zone = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert detect_conflicts([SAMPLE_TRACK], zone, {}) == []


def test_zone_membership_is_added_without_mutating_source():
    zone = [[0, 0], [100, 0], [100, 100], [0, 100]]
    output = enrich_tracks_with_zone([SAMPLE_TRACK], zone)
    assert output[0]["in_conflict_zone"] is True
    assert "in_conflict_zone" not in SAMPLE_TRACK
    assert point_in_polygon([150, 150], zone) is False


def test_event_frame_timestamp_is_normalized():
    events, warnings = normalize_events([{"frame_index": 75, "severity": "low"}], fps=30)
    assert not warnings
    assert events[0]["timestamp_seconds"] == 2.5
    assert format_timestamp(events[0]["timestamp_seconds"]) == "00:02.5"


def test_invalid_detector_return_is_rejected():
    events, warnings = normalize_events({"timestamp_seconds": 1.0}, fps=30)
    assert events == []
    assert warnings


def test_csv_contains_flat_coordinates_and_zone_flag():
    track = {**SAMPLE_TRACK, "in_conflict_zone": True}
    text = tracks_to_csv([track]).decode("utf-8")
    assert "bbox_x1" in text
    assert "10.0,20.0,30.0,50.0" in text
    assert ",True" in text


def test_mp4_header_and_digest_validation():
    payload = b"\x00\x00\x00\x18ftypmp42" + b"test-data"
    validate_upload(payload, "clip.mp4")
    assert len(video_digest(payload)) == 64


def test_tracking_table_serializes_through_pyarrow():
    """Guard the Pandas -> PyArrow path used by ``st.dataframe``."""

    table = pd.DataFrame([{**SAMPLE_TRACK, "in_conflict_zone": False}])
    table["bbox"] = table["bbox"].apply(json.dumps)
    table["center"] = table["center"].apply(json.dumps)
    arrow_table = pa.Table.from_pandas(table, preserve_index=False)
    assert arrow_table.num_rows == 1
    assert arrow_table.column("track_id")[0].as_py() == 4


def test_event_csv_preserves_measurements_and_nested_evidence():
    event = {
        "event_id": "conflict-001",
        "timestamp_seconds": 1.2,
        "severity": "HIGH",
        "arrival_time_gap_seconds": 0.2,
        "metrics": {"path_separation_pixels": 1.5},
    }
    text = events_to_csv([event]).decode("utf-8")
    assert "arrival_time_gap_seconds" in text
    assert "conflict-001" in text
    assert 'path_separation_pixels' in text

