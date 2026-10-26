"""Analysis Library tests.

All tracks, events and incidents here are generated fixtures, not real traffic.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3

import pytest

from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.history import (
    _csv,
    build_analysis_snapshot,
    compare_analysis_snapshots,
    compare_saved_snapshots,
    comparison_to_csv,
    comparison_to_json,
    list_analysis_snapshots,
    load_analysis_snapshot,
    save_analysis_snapshot,
    snapshots_to_csv,
    snapshots_to_json,
    summarize_analysis,
)
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG


DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
ZONE = [[0.0, 0.0], [100.0, 0.0], [100.0, 80.0]]


def fixture_tracks(data_source: str | None = None) -> list[dict]:
    records = []
    for frame in range(5):
        for track_id, object_type in ((1, "vehicle"), (2, "vehicle"), (3, "vehicle"), (9, "pedestrian")):
            record = {"track_id": track_id, "object_type": object_type, "frame_index": frame, "bbox": [0, 0, 1, 1]}
            if data_source:
                record["data_source"] = data_source
            records.append(record)
    return records


def fixture_events() -> list[dict]:
    return [
        {
            "event_id": "e1",
            "severity": "HIGH",
            "participant_a_track_id": 1,
            "participant_b_track_id": 2,
            "participant_a_track_ids": [1, 7],
            "participant_b_track_ids": [2],
            "arrival_time_gap_seconds": 0.4,
        },
        {"event_id": "e2", "severity": "LOW", "vehicle_a_track_id": 3, "vehicle_b_track_id": 2, "arrival_time_gap_seconds": 1.2},
    ]


def snapshot(**overrides) -> dict:
    arguments = {
        "video_sha256": DIGEST,
        "source_name": "corner.mp4",
        "camera_label": "CAM-NORTH",
        "source_kind": "uploaded_video",
        "duration_seconds": 30.0,
        "tracks": fixture_tracks(),
        "events": fixture_events(),
        "incidents": [{"incident_id": "i1", "review_status": "Uncertain"}],
        "tracking_config": TrackingConfig(),
        "conflict_config": dict(DEFAULT_CONFLICT_CONFIG),
        "collision_config": dict(DEFAULT_COLLISION_CONFIG),
        "zone_pixels": ZONE,
        "video_metadata": {"fps": 10.0, "width": 640, "height": 480},
    }
    arguments.update(overrides)
    return build_analysis_snapshot(**arguments)


def test_identical_snapshot_upserts_without_duplicates(tmp_path):
    database = tmp_path / "nm.db"
    first, created = save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    assert created is True
    # Reordered dict keys, int-vs-float and a renamed camera are the same analysis.
    reordered = dict(reversed(list(DEFAULT_CONFLICT_CONFIG.items())))
    second, created_again = save_analysis_snapshot(
        snapshot=snapshot(conflict_config=reordered, camera_label="CAM-N2", zone_pixels=[[0, 0], [100, 0], [100, 80]]),
        database_path=database,
    )
    assert created_again is False
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["created_at"] == first["created_at"]
    assert second["camera_label"] == "CAM-N2"
    assert len(list_analysis_snapshots(database_path=database)) == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"tracking_config": TrackingConfig(confidence=0.45)},
        {"conflict_config": {**DEFAULT_CONFLICT_CONFIG, "high_time_gap_seconds": 0.3}},
        {"collision_config": {**DEFAULT_COLLISION_CONFIG, "contact_persistence_frames": 5}},
        {"zone_pixels": [[0, 0], [120, 0], [120, 80]]},
        {"zone_pixels": []},
        {"video_sha256": OTHER_DIGEST},
    ],
)
def test_changed_footage_settings_or_zone_create_new_snapshot(tmp_path, overrides):
    database = tmp_path / "nm.db"
    base, _ = save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    changed, created = save_analysis_snapshot(snapshot=snapshot(**overrides), database_path=database)
    assert created is True
    assert changed["snapshot_id"] != base["snapshot_id"]
    assert len(list_analysis_snapshots(database_path=database)) == 2


def test_persisted_fields_summary_and_no_footage(tmp_path):
    database = tmp_path / "nm.db"
    saved, _ = save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    loaded = load_analysis_snapshot(snapshot_id=saved["snapshot_id"], database_path=database)
    assert loaded == saved
    assert loaded["source_name"] == "corner.mp4"
    assert loaded["camera_label"] == "CAM-NORTH"
    assert loaded["duration_seconds"] == 30.0
    assert loaded["track_record_count"] == 20
    assert loaded["event_count"] == 2 and loaded["incident_count"] == 1
    summary = loaded["summary"]
    assert summary["high_candidates"] == 1 and summary["low_candidates"] == 1
    assert summary["distinct_candidate_pairs"] == 2
    assert summary["candidate_warnings_per_footage_minute"] == 4.0
    assert summary["incident_review_status_at_save"] == {"Uncertain": 1}
    assert loaded["config"]["tracking_config"]["confidence"] == 0.3
    assert loaded["zone"] == {"zone_pixels": ZONE, "user_defined": True}
    assert loaded["created_at"] and loaded["updated_at"]
    assert load_analysis_snapshot(snapshot_id="run-missing", database_path=database) is None
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_runs)")}
        types = {row[0] for row in connection.execute("SELECT typeof(summary_json) FROM analysis_runs")}
    assert not any(word in column for column in columns for word in ("blob", "frame", "footage", "path"))
    assert types == {"text"}
    assert "bbox" not in json.dumps(loaded)


def test_tracker_ids_are_not_reported_as_physical_vehicles():
    summary = snapshot()["summary"]
    assert summary["distinct_vehicle_track_ids"] == 3
    assert summary["distinct_pedestrian_track_ids"] == 1
    assert summary["unique_physical_vehicles"] is None
    assert "not unique physical vehicles" in summary["unique_physical_vehicles_note"]
    assert summary["candidate_participants_with_stitched_ids"] == 1


def test_provenance_is_recorded_and_mismatch_flagged(tmp_path):
    demo = snapshot(source_kind="synthetic_demo", tracks=fixture_tracks("synthetic_demo"))
    assert demo["provenance"]["source_kind"] == "synthetic_demo"
    assert demo["provenance"]["record_data_sources"] == ["synthetic_demo"]
    assert "no YOLO" in demo["provenance"]["detector"]
    assert demo["provenance"]["footage_stored"] is False
    assert demo["provenance"]["warnings"] == []
    # Same digest + settings but different source kind is never merged.
    assert demo["snapshot_id"] != snapshot()["snapshot_id"]

    mislabeled = snapshot(tracks=fixture_tracks("synthetic_demo"))
    assert mislabeled["provenance"]["warnings"]
    saved, _ = save_analysis_snapshot(snapshot=demo, database_path=tmp_path / "nm.db")
    assert saved["provenance"] == demo["provenance"]
    assert list_analysis_snapshots(database_path=tmp_path / "nm.db", source_kind="uploaded_video") == []

    with pytest.raises(ValueError):
        snapshot(source_kind="real_traffic")
    with pytest.raises(ValueError):
        snapshot(video_sha256="")


def test_tampered_snapshot_identity_is_rejected(tmp_path):
    tampered = snapshot()
    tampered["config"]["tracking_config"]["confidence"] = 0.9
    with pytest.raises(ValueError):
        save_analysis_snapshot(snapshot=tampered, database_path=tmp_path / "nm.db")


def test_list_filters_and_order(tmp_path):
    database = tmp_path / "nm.db"
    save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    save_analysis_snapshot(snapshot=snapshot(video_sha256=OTHER_DIGEST), database_path=database)
    assert len(list_analysis_snapshots(database_path=database, video_sha256=DIGEST.upper())) == 1
    assert len(list_analysis_snapshots(database_path=database, limit=1)) == 1
    assert list_analysis_snapshots(database_path=tmp_path / "empty.db") == []


def test_same_footage_comparison_attributes_change_to_settings(tmp_path):
    database = tmp_path / "nm.db"
    base, _ = save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    stricter, _ = save_analysis_snapshot(
        snapshot=snapshot(
            conflict_config={**DEFAULT_CONFLICT_CONFIG, "high_time_gap_seconds": 0.3},
            events=fixture_events()[:1],
        ),
        database_path=database,
    )
    comparison = compare_saved_snapshots(
        baseline_id=base["snapshot_id"], candidate_id=stricter["snapshot_id"], database_path=database
    )
    assert comparison["comparison_kind"] == "same_footage_different_settings"
    assert comparison["provenance_mismatch"] is False
    assert comparison["ranking"] is None
    metrics = {row["metric"]: row for row in comparison["metrics"]}
    assert metrics["candidate_warnings"]["delta"] == -1
    assert metrics["duration_seconds"]["delta"] == 0
    assert comparison["setting_changes"] == [
        {"section": "conflict_config", "setting": "high_time_gap_seconds", "baseline": 0.5, "candidate": 0.3}
    ]
    text = " ".join(comparison["caveats"])
    assert "reflect detector settings" in text and "Short exposure" in text
    assert "safer" not in json.dumps(comparison["metrics"])
    with pytest.raises(KeyError):
        compare_saved_snapshots(baseline_id="run-x", candidate_id=base["snapshot_id"], database_path=database)


def test_synthetic_vs_uploaded_comparison_has_mismatch_notice():
    real = snapshot(duration_seconds=900.0)
    demo = snapshot(video_sha256=OTHER_DIGEST, source_kind="synthetic_demo", tracks=fixture_tracks("synthetic_demo"))
    comparison = compare_analysis_snapshots(baseline=real, candidate=demo)
    assert comparison["provenance_mismatch"] is True
    assert comparison["comparison_kind"] == "different_footage"
    assert comparison["caveats"][0].startswith("PROVENANCE MISMATCH")
    assert any("do not show which location is safer" in caveat for caveat in comparison["caveats"])
    # Only the 30 s demo is short; the 15 min clip is not called short.
    short = [caveat for caveat in comparison["caveats"] if caveat.startswith("Short exposure")]
    assert short and "900" not in short[0]

    same = compare_analysis_snapshots(baseline=real, candidate=real)
    assert same["comparison_kind"] == "identical_snapshot"
    assert all(row["delta"] in (0, None) for row in same["metrics"])


def test_real_sample_vs_upload_is_a_source_difference_not_synthetic():
    upload = snapshot(duration_seconds=900.0)
    sample = snapshot(
        video_sha256=OTHER_DIGEST, source_kind="real_traffic_demo",
        tracks=fixture_tracks("real_traffic_demo"), tracking_origin="bundled_precomputed",
    )
    assert sample["provenance"]["warnings"] == []
    assert "bundled rows, precomputed locally" in sample["provenance"]["detector"]
    for baseline, candidate in ((upload, sample), (sample, upload)):
        comparison = compare_analysis_snapshots(baseline=baseline, candidate=candidate)
        assert comparison["provenance_mismatch"] is False
        assert comparison["source_difference"] is True
        first = comparison["caveats"][0]
        assert first.startswith("SOURCE DIFFERENCE")
        assert "uploaded footage" in first and "bundled real-traffic stock sample" in first
        exported = comparison_to_csv(comparison) + comparison_to_json(comparison)
        assert "synthetic" not in exported.lower() and "PROVENANCE MISMATCH" not in exported

    # Synthetic versus the real sample is still a mismatch, naming the real source.
    demo = snapshot(video_sha256=OTHER_DIGEST, source_kind="synthetic_demo", tracks=fixture_tracks("synthetic_demo"))
    mixed = compare_analysis_snapshots(
        baseline=snapshot(source_kind="real_traffic_demo", tracks=fixture_tracks("real_traffic_demo")),
        candidate=demo,
    )
    assert mixed["provenance_mismatch"] is True and mixed["source_difference"] is False
    assert mixed["caveats"][0].startswith("PROVENANCE MISMATCH")
    assert "the bundled real-traffic stock sample" in mixed["caveats"][0]
    # Same-kind runs carry neither notice.
    plain = compare_analysis_snapshots(baseline=upload, candidate=snapshot(video_sha256=OTHER_DIGEST))
    assert not plain["provenance_mismatch"] and not plain["source_difference"]


def test_exports_round_trip(tmp_path):
    database = tmp_path / "nm.db"
    save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    snapshots = list_analysis_snapshots(database_path=database)
    rows = list(csv.DictReader(io.StringIO(snapshots_to_csv(snapshots))))
    assert rows[0]["source_kind"] == "uploaded_video" and rows[0]["candidate_warnings"] == "2"
    assert snapshots_to_csv([]).startswith("snapshot_id,")
    library = json.loads(snapshots_to_json(snapshots))
    assert library["snapshots"][0]["snapshot_id"] == snapshots[0]["snapshot_id"]
    assert library["caveats"]

    comparison = compare_analysis_snapshots(baseline=snapshots[0], candidate=snapshot(source_kind="synthetic_demo"))
    exported = comparison_to_csv(comparison)
    assert "metric,label,baseline,candidate,delta" in exported and "PROVENANCE MISMATCH" in exported
    assert json.loads(comparison_to_json(comparison))["provenance_mismatch"] is True


@pytest.mark.parametrize(
    "label", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "  =HYPERLINK(\"x\")", "\t=1", "\r=1", "\n-1", "\x01data"]
)
def test_csv_exports_neutralise_formula_labels(tmp_path, label):
    database = tmp_path / "nm.db"
    hostile = snapshot(camera_label=label, source_name=label, source_kind="synthetic_demo")
    save_analysis_snapshot(snapshot=hostile, database_path=database)
    saved = list_analysis_snapshots(database_path=database)
    # Stored and JSON values stay verbatim; only CSV cells are escaped.
    assert saved[0]["camera_label"] == label.strip() and saved[0]["source_name"] == label.strip()
    row = next(csv.DictReader(io.StringIO(snapshots_to_csv(saved))))
    for column in ("camera_label", "source_name"):
        assert row[column].startswith("'") and row[column][1:] == label.strip()
    assert row["duration_seconds"] == "30.0" and row["candidate_warnings"] == "2"

    raw_label = snapshot(camera_label="CAM-OK", source_name="ok.mp4")
    raw_label["source_name"] = label  # unstripped, e.g. leading control characters
    raw_label["provenance"]["warnings"] = ["test warning"]
    comparison = compare_analysis_snapshots(baseline=raw_label, candidate=hostile)
    exported = list(csv.reader(io.StringIO(comparison_to_csv(comparison))))
    caveats = [cells[0] for cells in exported[exported.index(["caveat"]) + 1:]]
    assert any(caveat == "'" + label + ": test warning" for caveat in caveats)
    assert not any(caveat[:1] in "=+-@" or ord(caveat[0]) < 32 for caveat in caveats)


def test_csv_keeps_numbers_numeric_and_json_structure():
    fewer = snapshot(events=[], duration_seconds=12.5)
    comparison = compare_analysis_snapshots(baseline=snapshot(), candidate=fewer)
    metric_section = comparison_to_csv(comparison).split("\r\n\r\n")[0]
    rows = {row["metric"]: row for row in csv.DictReader(io.StringIO(metric_section))}
    assert len(rows) == len(comparison["metrics"])
    # Negative numeric deltas are written as plain numbers, never quote-escaped.
    assert float(rows["candidate_warnings"]["delta"]) == -2.0
    assert rows["duration_seconds"]["delta"] == "-17.5"
    assert float(rows["candidate_warnings_per_footage_minute"]["delta"]) == -4.0
    assert not any(row["delta"].startswith("'") for row in rows.values())
    structured = next(csv.DictReader(io.StringIO(_csv([{"zone": [[-1.0, 2.0]], "meta": {"k": "=x"}}], ["zone", "meta"]))))
    assert json.loads(structured["zone"]) == [[-1.0, 2.0]]
    assert json.loads(structured["meta"]) == {"k": "=x"}
    assert rows["high_candidates"]["label"] == "High-priority candidates"
    library = list(csv.DictReader(io.StringIO(snapshots_to_csv([snapshot(camera_label="-north")]))))
    assert library[0]["camera_label"] == "'-north"
    assert library[0]["zone_user_defined"] == "True"


@pytest.mark.parametrize("bad_id", [float("inf"), float("-inf"), float("nan"), "abc", None, [1]])
def test_nonfinite_or_malformed_track_ids_are_missing(bad_id):
    tracks = fixture_tracks() + [{"track_id": bad_id, "object_type": "vehicle"}]
    events = fixture_events() + [
        {"severity": "LOW", "participant_a_track_id": bad_id, "participant_b_track_id": 1}
    ]
    summary = summarize_analysis(tracks=tracks, events=events, incidents=[], duration_seconds=30.0)
    assert summary["distinct_vehicle_track_ids"] == 3
    assert summary["distinct_track_ids"] == 4
    assert summary["distinct_candidate_pairs"] == 2
    assert summary["candidate_warnings"] == 3
    assert summary["track_record_count"] == 21
    # Valid integer-like IDs keep their existing semantics.
    valid = summarize_analysis(
        tracks=[{"track_id": "5", "object_type": "vehicle"}, {"track_id": 6.0, "object_type": "vehicle"}],
        events=[], incidents=[], duration_seconds=1.0,
    )
    assert valid["distinct_vehicle_track_ids"] == 2


def _history_app(database_path: str, with_current: bool) -> None:
    from nearmiss.history import build_analysis_snapshot as build
    from nearmiss.history_ui import render_history_page

    current = None
    if with_current:
        current = build(
            video_sha256="c" * 64, source_name="demo.mp4", camera_label="CAM-DEMO",
            source_kind="synthetic_demo", duration_seconds=12.0, tracks=[], events=[], incidents=[],
            tracking_config={}, conflict_config={}, collision_config={},
        )
    render_history_page(current_snapshot=current, database_path=database_path)


def test_history_page_renders_empty_and_populated(tmp_path):
    from streamlit.testing.v1 import AppTest

    database = str(tmp_path / "nm.db")
    empty = AppTest.from_function(_history_app, args=(database, False)).run()
    assert not empty.exception
    assert any("No saved runs yet" in block.value for block in empty.markdown)

    save_analysis_snapshot(snapshot=snapshot(), database_path=database)
    page = AppTest.from_function(_history_app, args=(database, True)).run()
    assert not page.exception
    page.button(key="history_save_current").click().run()
    assert not page.exception
    assert len(list_analysis_snapshots(database_path=database)) == 2
    assert any("PROVENANCE MISMATCH" in block.value for block in page.error)
    assert len(page.dataframe) >= 2
