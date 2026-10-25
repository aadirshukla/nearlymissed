"""Tests for the frame-by-frame Investigation workspace.

All tracks, events, incidents and videos here are generated fixtures. They are
never presented by the application as real detections.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from nearmiss.investigation import (
    evidence_focus,
    evidence_timeline,
    build_investigation_export,
    clean_observations,
    draw_investigation_frame,
    evidence_track_ids,
    filter_observations,
    filter_participants,
    frame_index_for_timestamp,
    investigation_json,
    is_synthetic_source,
    movement_summary,
    nearby_evidence,
    nearest_observed_frame,
    observations_at_frame,
    participant_catalog,
    timestamp_for_frame_index,
    track_trail,
)
from nearmiss.video import VideoMetadata, frame_at_timestamp


FPS = 10.0


def row(track_id, frame, x, y, object_type="vehicle", class_name="car", **extra):
    return {
        "track_id": track_id,
        "class_name": class_name,
        "object_type": object_type,
        "frame_index": frame,
        "timestamp_seconds": frame / FPS,
        "bbox": [x - 5.0, y - 10.0, x + 5.0, y],
        "center": [x, y - 5.0],
        "confidence": 0.9,
        **extra,
    }


def fixture_tracks() -> list[dict]:
    car = [row(1, frame, 10.0 + 2 * frame, 50.0, data_source="synthetic_demo") for frame in range(0, 11)]
    # Pedestrian observed on frames 0-3 and 8-10 only (tracking gap 4-7).
    walker = [
        row(2, frame, 80.0, 20.0 + frame, "pedestrian", "person", data_source="synthetic_demo")
        for frame in (0, 1, 2, 3, 8, 9, 10)
    ]
    truck = [row(3, frame, 40.0, 70.0, class_name="truck", data_source="synthetic_demo") for frame in (5,)]
    return car + walker + truck


EVENTS = [
    {"event_id": 7, "timestamp_seconds": 0.5, "participant_a_track_id": 1,
     "participant_b_track_id": 2, "severity": "HIGH"},
    {"event_id": 8, "timestamp_seconds": 3.0, "vehicle_a_track_id": 1, "vehicle_b_track_id": 3},
    {"event_id": 9, "timestamp_seconds": None, "vehicle_a_track_id": 1},
]
INCIDENTS = [
    {"incident_id": "inc-1", "timestamp_seconds": 0.9,
     "first_suspected_impact_timestamp_seconds": 0.8, "frame_index": 8,
     "vehicle_a_track_id": 1, "vehicle_b_track_id": 3, "review_status": "Uncertain"},
]
METADATA = VideoMetadata(fps=FPS, frame_count=11, width=120, height=90, duration_seconds=1.1)


# -- frame/time selection -------------------------------------------------


def test_frame_and_timestamp_conversion_round_trips_and_clamps():
    assert frame_index_for_timestamp(0.0, FPS) == 0
    assert frame_index_for_timestamp(0.3, FPS) == 3
    assert frame_index_for_timestamp(0.349, FPS) == 3
    assert frame_index_for_timestamp(-4.0, FPS) == 0
    assert frame_index_for_timestamp(99.0, FPS, frame_count=11) == 10
    assert frame_index_for_timestamp(1.0, 0.0) == 0
    for frame in range(11):
        assert frame_index_for_timestamp(timestamp_for_frame_index(frame, 29.97), 29.97) == frame


def test_observations_at_frame_returns_only_stored_rows():
    tracks = fixture_tracks()
    at_five = observations_at_frame(tracks, 5)
    assert [item["track_id"] for item in at_five] == [1, 3]  # pedestrian has no row at 5
    assert all(item["frame_index"] == 5 and item["match"] == "exact" for item in at_five)
    assert observations_at_frame(tracks, 500) == []
    assert observations_at_frame([], 0) == []
    assert observations_at_frame(None, 0) == []


def test_tolerance_rows_are_labeled_and_keep_their_own_frame():
    near = {item["track_id"]: item for item in observations_at_frame(fixture_tracks(), 5, tolerance_frames=2)}
    assert near[1]["match"] == "exact"
    assert near[2]["match"] == "nearest_within_tolerance"
    assert near[2]["frame_index"] == 3 and near[2]["frame_offset"] == -2
    assert near[2]["bbox"] == row(2, 3, 80.0, 23.0)["bbox"]  # not moved toward frame 5


def test_malformed_rows_are_dropped_not_repaired():
    bad = [
        {"track_id": 1, "frame_index": 0, "bbox": [0, 0, 1]},
        {"track_id": 1, "frame_index": 0, "bbox": [0, 0, float("nan"), 3]},
        {"track_id": None, "frame_index": 0, "bbox": [0, 0, 1, 1]},
        {"track_id": 1, "frame_index": 1.5, "bbox": [0, 0, 1, 1]},
        {"track_id": 1, "frame_index": 0, "bbox": [5, 5, 1, 1]},
        "not a row",
    ]
    assert clean_observations(bad) == []
    assert nearest_observed_frame(bad, 1, 0) is None


# -- filtering and ranking -----------------------------------------------


def test_filters_distinguish_none_from_empty():
    tracks = fixture_tracks()
    assert len(filter_observations(tracks)) == len(tracks)
    assert filter_observations(tracks, track_ids=[]) == []
    assert {item["track_id"] for item in filter_observations(tracks, object_types=["pedestrian"])} == {2}
    assert {item["track_id"] for item in filter_observations(tracks, class_names=["truck"])} == {3}
    assert observations_at_frame(tracks, 5, track_ids=["3"]) == observations_at_frame(tracks, 5, class_names=["truck"])


def test_participant_ranking_prefers_visible_then_evidence():
    catalog = participant_catalog(fixture_tracks(), frame_index=5, events=EVENTS, incidents=INCIDENTS)
    assert [item["track_id"] for item in catalog] == [1, 3, 2]
    by_id = {item["track_id"]: item for item in catalog}
    assert by_id[1]["evidence_count"] == 3  # untimed event 9 is ignored
    assert by_id[2]["visible_at_frame"] is False
    assert by_id[2]["observation_count"] == 7
    assert [item["rank"] for item in catalog] == [1, 2, 3]
    assert [item["track_id"] for item in filter_participants(catalog, object_types=["vehicle"])] == [1, 3]
    assert participant_catalog([], frame_index=0) == []


# -- trails and movement ---------------------------------------------------


def test_trail_window_is_inclusive_and_never_looks_ahead():
    trail = track_trail(fixture_tracks(), 1, 6, trail_frames=3)
    assert [point["frame_index"] for point in trail] == [3, 4, 5, 6]
    assert trail[-1]["x"] == 22.0 and trail[-1]["y"] == 50.0  # bbox bottom-centre
    assert [p["frame_index"] for p in track_trail(fixture_tracks(), 1, 6, trail_frames=0)] == [6]
    gap_trail = track_trail(fixture_tracks(), 2, 9, trail_frames=9)
    assert [point["frame_index"] for point in gap_trail] == [0, 1, 2, 3, 8, 9]
    assert track_trail(fixture_tracks(), 99, 5) == []


def test_movement_summary_uses_image_units_and_reports_gaps():
    summary = movement_summary(fixture_tracks(), 1, 10, fps=FPS, window_frames=10)
    assert summary["observations_in_window"] == 11
    assert summary["displacement_pixels"] == pytest.approx(20.0)
    assert summary["path_length_pixels"] == pytest.approx(20.0)
    assert summary["mean_speed_pixels_per_second"] == pytest.approx(20.0)
    assert summary["heading_image_degrees"] == pytest.approx(0.0)
    assert summary["direction"] == "toward image right"
    assert summary["units"].startswith("image pixels")

    walker = movement_summary(fixture_tracks(), 2, 6, fps=FPS, window_frames=6)
    assert walker["observed_at_requested_frame"] is False
    assert walker["nearest_observed_frame_index"] == 8  # 2 frames away vs 3 for frame 3
    assert walker["missing_frames_in_observed_span"] == 0  # frames 0-3 contiguous
    assert walker["direction"] == "toward image bottom"

    gappy = movement_summary(fixture_tracks(), 2, 10, fps=FPS, window_frames=10)
    assert gappy["missing_frames_in_observed_span"] == 4

    single = movement_summary(fixture_tracks(), 3, 5, fps=FPS)
    assert single["observations_in_window"] == 1 and single["mean_speed_pixels_per_second"] is None
    none = movement_summary(fixture_tracks(), 3, 2, fps=FPS)
    assert none["observations_in_window"] == 0 and none["displacement_pixels"] is None


# -- evidence ---------------------------------------------------------------


def test_nearby_evidence_has_explicit_times_offsets_and_review_status():
    rows = nearby_evidence(EVENTS, INCIDENTS, 0.6, window_seconds=0.5)
    assert [(item["evidence_kind"], item["evidence_id"]) for item in rows] == [
        ("prediction_event", "7"),
        ("suspected_incident", "inc-1"),
    ]
    incident = rows[1]
    assert incident["event_time_field"] == "first_suspected_impact_timestamp_seconds"
    assert incident["event_time_seconds"] == pytest.approx(0.8)
    assert incident["offset_seconds"] == pytest.approx(0.2)
    assert incident["review_status"] == "Uncertain"
    assert rows[0]["offset_seconds"] == pytest.approx(-0.1)
    assert [item["evidence_id"] for item in nearby_evidence(EVENTS, INCIDENTS, 0.6, window_seconds=0.5, track_ids=[2])] == ["7"]
    assert nearby_evidence(EVENTS, INCIDENTS, 0.6, window_seconds=0.5, track_ids=[]) == []
    assert nearby_evidence(None, None, 0.0) == []


def test_prediction_navigation_uses_first_alert_and_keeps_measurement_time():
    event = {
        "event_id": "conflict-001", "timestamp_seconds": 2.7, "frame_index": 27,
        "first_alert_timestamp_seconds": 2.8, "start_frame_index": 28,
        "participant_a_track_id": 1, "participant_b_track_id": 2,
    }
    [row] = evidence_timeline([event], [])
    assert row["event_time_field"] == "first_alert_timestamp_seconds"
    assert row["event_time_seconds"] == pytest.approx(2.8)
    assert row["event_frame_index"] == 28
    assert row["measurement_timestamp_seconds"] == pytest.approx(2.7)
    assert row["measurement_frame_index"] == 27
    # Missing or non-finite first alert falls back to the measurement timestamp.
    for bad in (None, float("nan"), "x"):
        [fallback] = evidence_timeline([{**event, "first_alert_timestamp_seconds": bad}], [])
        assert fallback["event_time_field"] == "timestamp_seconds"
        assert fallback["event_time_seconds"] == pytest.approx(2.7)
        assert fallback["event_frame_index"] == 27


STITCHED_EVENT = {
    "event_id": "s1", "timestamp_seconds": 1.0,
    "participant_a_track_id": 1, "participant_a_track_ids": [1, 7],
    "participant_b_track_id": 2, "participant_b_track_ids": [2],
}


def test_evidence_focus_selects_stitched_participants_and_widens_filters():
    catalog = [
        {"track_id": 1, "object_type": "vehicle", "class_name": "car"},
        {"track_id": 7, "object_type": "vehicle", "class_name": "truck"},
        {"track_id": 2, "object_type": "pedestrian", "class_name": "person"},
        {"track_id": 9, "object_type": "vehicle", "class_name": "bus"},
    ]
    [row] = evidence_timeline([{**STITCHED_EVENT, "participant_b_track_ids": [2, 44]}], [])
    focus = evidence_focus(catalog, row, object_types=["vehicle"], class_names=["bus"])
    # 44 has no stored observations, so it is not offered as a selection.
    assert focus["track_ids"] == [1, 7, 2]
    assert focus["object_types"] == ["vehicle", "pedestrian"]
    assert focus["class_names"] == ["bus", "car", "truck", "person"]
    unfiltered = evidence_focus(catalog, row)
    assert unfiltered["object_types"] is None and unfiltered["class_names"] is None
    assert evidence_focus(catalog, {"participant_track_ids": [99]})["track_ids"] == []


def test_evidence_track_ids_include_stitched_raw_ids_in_order():
    assert evidence_track_ids(STITCHED_EVENT) == [1, 7, 2]
    assert evidence_track_ids({
        "participant_a_track_id": 4,
        "participant_a_track_ids": (np.int64(9), 4.0, "11"),
        "participant_b_track_ids": np.array([5, 9]),
        "vehicle_track_ids": {13, 12},
        "pedestrian_track_ids": 14,  # scalar in an array key
    }) == [4, 9, 11, 5, 12, 13, 14]


def test_evidence_track_ids_skip_malformed_and_nonfinite_values():
    record = {
        "participant_a_track_id": float("nan"),
        "participant_a_track_ids": [None, "x", 1.5, float("inf"), True, [3], {"id": 4}, 6],
        "participant_b_track_id": "",
        "participant_b_track_ids": "12",  # a string is one value, not characters
        "vehicle_track_ids": None,
    }
    assert evidence_track_ids(record) == [6, 12]
    assert evidence_track_ids({}) == []


def test_stitched_raw_id_finds_evidence_ranking_and_export():
    tracks = fixture_tracks() + [row(7, frame, 30.0, 50.0) for frame in range(8, 11)]
    assert [item["evidence_id"] for item in nearby_evidence([STITCHED_EVENT], None, 1.0, track_ids=[7])] == ["s1"]
    assert nearby_evidence([STITCHED_EVENT], None, 1.0, track_ids=[3]) == []

    catalog = participant_catalog(tracks, frame_index=0, events=[STITCHED_EVENT], incidents=None)
    by_id = {item["track_id"]: item for item in catalog}
    assert by_id[7]["evidence_count"] == 1 and by_id[3]["evidence_count"] == 0
    # Neither 7 nor 3 is visible at frame 0; the evidence-named raw ID ranks first.
    assert [item["track_id"] for item in catalog if item["track_id"] in (3, 7)] == [7, 3]

    export = build_investigation_export(
        video_id="v", source_kind="upload", metadata=METADATA, tracks=tracks,
        events=[STITCHED_EVENT], incidents=None, frame_index=9, selected_track_ids=[7],
        evidence_window_seconds=0.5,
    )
    assert [item["track_id"] for item in export["observed_rows"]] == [7]
    assert [item["evidence_id"] for item in export["nearby_evidence"]] == ["s1"]
    assert export["nearby_evidence"][0]["participant_track_ids"] == [1, 7, 2]


# -- drawing ----------------------------------------------------------------


def test_drawing_works_on_a_copy_and_skips_unsafe_rows():
    frame = np.zeros((90, 120, 3), dtype=np.uint8)
    rows = observations_at_frame(fixture_tracks(), 5) + [
        {"track_id": 9, "bbox": [500, 500, 600, 600]},  # entirely outside
        {"track_id": 10, "bbox": [-50, -50, 5, 5]},  # partially outside, clipped
        {"track_id": 11, "bbox": [1, 2]},  # malformed
    ]
    output = draw_investigation_frame(frame, rows, selected_track_ids=[1, 10])
    assert frame.sum() == 0
    assert output.shape == frame.shape and output.dtype == np.uint8
    assert output[50, 17].any()  # selected car box edge (x1 = 17)
    assert output[0, 0].any()  # clipped box touches the corner
    assert not draw_investigation_frame(frame, []).any()
    gray = draw_investigation_frame(np.zeros((20, 20), dtype=np.uint8), [])
    assert gray.shape == (20, 20, 3)
    with pytest.raises(ValueError):
        draw_investigation_frame(np.zeros((0, 0, 3), dtype=np.uint8), [])


def test_trail_gaps_are_not_drawn_as_motion():
    frame = np.zeros((90, 120, 3), dtype=np.uint8)
    trail = {2: [{"frame_index": 0, "x": 10, "y": 10}, {"frame_index": 20, "x": 110, "y": 10}]}
    output = draw_investigation_frame(frame, [], trail, selected_track_ids=[2], track_types={2: "pedestrian"})
    assert output[10, 10].any() and output[10, 110].any()
    assert not output[10, 60].any()
    joined = draw_investigation_frame(frame, [], {2: [{"frame_index": 0, "x": 10, "y": 10}, {"frame_index": 1, "x": 110, "y": 10}]}, selected_track_ids=[2])
    assert joined[10, 60].any()


# -- provenance and export ------------------------------------------------


def test_export_carries_request_selection_observed_rows_and_provenance():
    export = build_investigation_export(
        video_id="demo-video",
        source_kind="synthetic",
        metadata=METADATA,
        tracks=fixture_tracks(),
        events=EVENTS,
        incidents=INCIDENTS,
        frame_index=5,
        selected_track_ids=[2, 1, 3],
        object_types=["vehicle", "pedestrian"],
        class_names=["car", "person"],
        trail_frames=3,
        evidence_window_seconds=0.5,
        frame_decoded=True,
    )
    assert export["request"] == {
        "frame_index": 5, "timestamp_seconds": 0.5, "fps": 10.0,
        "frame_count": 11, "frame_width": 120, "frame_height": 90,
    }
    assert export["selection"]["track_ids"] == [1, 2, 3]
    assert [item["track_id"] for item in export["observed_rows"]] == [1]
    assert all(item["frame_index"] == 5 for item in export["observed_rows"])
    assert "match" not in export["observed_rows"][0]
    missing = {item["track_id"]: item for item in export["selected_tracks_without_observation"]}
    assert missing[2]["reason"] == "no_stored_row_at_frame"
    assert missing[2]["nearest_observed_frame_index"] == 3
    assert missing[3]["reason"] == "excluded_by_type_or_class_filter"
    provenance = export["provenance"]
    assert provenance["synthetic"] is True and "SYNTHETIC" in provenance["synthetic_notice"]
    assert provenance["track_data_sources"] == ["synthetic_demo"]
    assert provenance["interpolated_rows_included"] is False
    assert provenance["units"]["speed"] == "pixels_per_second"
    assert {item["evidence_id"] for item in export["nearby_evidence"]} == {"7", "inc-1"}
    decoded = json.loads(investigation_json(export))
    assert decoded["observed_rows"] == export["observed_rows"]


def test_export_is_json_safe_and_handles_empty_input():
    export = build_investigation_export(
        video_id=None, source_kind="upload", metadata=None, tracks=[], events=None,
        incidents=None, frame_index=0, selected_track_ids=[],
    )
    assert export["observed_rows"] == [] and export["nearby_evidence"] == []
    assert export["provenance"]["synthetic"] is False
    payload = {**export, "extra": [np.float32(1.5), np.int64(3), float("nan")]}
    assert json.loads(investigation_json(payload))["extra"] == [1.5, 3, None]


def test_synthetic_detection_from_kind_or_rows():
    assert is_synthetic_source("synthetic_demo")
    assert is_synthetic_source("upload", [{"data_source": "Synthetic demonstration"}])
    assert not is_synthetic_source("upload", [{"data_source": "yolo"}])
    assert not is_synthetic_source(None)


# -- real frame decode and Streamlit page --------------------------------


def write_marker_video(path: Path, frames: int = 12, fps: float = FPS) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (120, 90))
    for index in range(frames):
        image = np.zeros((90, 120, 3), dtype=np.uint8)
        cv2.rectangle(image, (index * 9, 0), (index * 9 + 8, 89), (255, 255, 255), -1)
        writer.write(image)
    writer.release()
    return path


def test_frame_index_timestamp_decodes_that_exact_source_frame(tmp_path):
    path = write_marker_video(tmp_path / "markers.mp4")
    for frame in (0, 3, 7, 11):
        image = frame_at_timestamp(path, timestamp_for_frame_index(frame, FPS))
        column = int(np.argmax(image[45, :, 0].astype(int)))
        assert column // 9 == frame


def _page(source_path, tracks, events, incidents, source_kind, video_id, metadata):
    from nearmiss.investigation_ui import render_investigation_page

    render_investigation_page(
        source_path=source_path, metadata=metadata, tracks=tracks, events=events,
        incidents=incidents, source_kind=source_kind, video_id=video_id,
    )


def test_page_renders_clean_empty_state():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(_page, kwargs={
        "source_path": None, "tracks": [], "events": [], "incidents": [],
        "source_kind": "upload", "video_id": "empty", "metadata": None,
    }).run()
    assert not app.exception
    assert any("No frame timing" in item.value for item in app.info)


def test_page_shows_synthetic_banner_frame_and_tables(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = write_marker_video(tmp_path / "demo.mp4", frames=11)
    app = AppTest.from_function(_page, default_timeout=20, kwargs={
        "source_path": str(path), "tracks": fixture_tracks(), "events": EVENTS,
        "incidents": INCIDENTS, "source_kind": "synthetic", "video_id": "demo",
        "metadata": {"fps": FPS, "frame_count": 11, "width": 120, "height": 90},
    }).run()
    assert not app.exception
    assert any("SYNTHETIC" in item.value for item in app.warning)
    assert app.slider(key="investigation_demo_frame").value == 0
    # Visible at frame 0 (1, 2) plus evidence-named truck 3, in rank order.
    assert app.multiselect(key="investigation_demo_tracks").value == [1, 2, 3]
    assert len(app.dataframe) == 2
    app.button(key="investigation_demo_next").click().run()
    assert app.slider(key="investigation_demo_frame").value == 1
    app.button(key="investigation_demo_jump").click().run()
    assert app.slider(key="investigation_demo_frame").value == 5  # first evidence: event 7 at 0.5 s
    assert not app.exception


def test_page_without_tracks_still_shows_frame(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = write_marker_video(tmp_path / "plain.mp4", frames=5)
    app = AppTest.from_function(_page, default_timeout=20, kwargs={
        "source_path": path, "tracks": [], "events": [], "incidents": [],
        "source_kind": "upload", "video_id": "plain",
        "metadata": VideoMetadata(fps=FPS, frame_count=5, width=120, height=90, duration_seconds=0.5),
    }).run()
    assert not app.exception
    assert any("No track observations" in item.value for item in app.info)
    assert not app.warning
