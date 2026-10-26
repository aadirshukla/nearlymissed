"""The bundled real-traffic sample: integrity, cache restore, provenance and app entry.

Two kinds of bundle are used. ``fixture_bundle`` is a tiny throwaway bundle
built in a temporary directory (hand-written rows, labeled as a fixture) to
exercise every validation failure without touching the shipped files. The
remaining tests use the shipped ``static/real-demo`` bundle read-only, so a
missing or altered asset fails here rather than in front of an audience.
Cache and SQLite paths are always redirected to a temporary directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

import nearmiss.store as store_module
import nearmiss.video as video_module
from conflict_detector import detect_conflicts
from nearmiss import demo, real_demo
from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.events import normalize_events
from nearmiss.geometry import enrich_tracks_with_zone
from nearmiss.incidents import detect_suspected_collisions
from nearmiss.safety import deduplicate_events
from nearmiss.store import list_notifications, list_reviews, review_incident
from nearmiss.video import _artifact_paths, cached_analysis, load_artifacts


ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
SHIPPED = ROOT / "static" / "real-demo"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(video_module, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(store_module, "DEFAULT_DATABASE_PATH", tmp_path / "data" / "nearmiss.db")
    return tmp_path


# ------------------------------------------------------------ fixture bundle

FPS, FRAMES, WIDTH, HEIGHT = 10.0, 12, 64, 48


def fixture_rows() -> list[dict]:
    rows = []
    for frame in range(FRAMES):
        x1, y1 = 4.0 + 2 * frame, 10.0
        x2, y2 = x1 + 12.0, y1 + 8.0
        rows.append({
            "track_id": 1, "class_id": 2, "class_name": "car", "object_type": "vehicle",
            "frame_index": frame, "timestamp_seconds": round(frame / FPS, 6),
            "bbox": [x1, y1, x2, y2], "center": [round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2)],
            "confidence": 0.8,
        })
    return rows


def write_bundle(directory: Path, rows: list[dict] | None = None, **manifest_overrides) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(directory / "source.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    for frame in range(FRAMES):
        writer.write(np.full((HEIGHT, WIDTH, 3), 30 + frame, dtype=np.uint8))
    writer.release()
    rows = fixture_rows() if rows is None else rows
    (directory / "tracks.json").write_text(json.dumps(rows), encoding="utf-8")
    (directory / "metadata.json").write_text(json.dumps(
        {"fps": FPS, "frame_count": FRAMES, "width": WIDTH, "height": HEIGHT, "duration_seconds": FRAMES / FPS}
    ), encoding="utf-8")
    (directory / "annotated.mp4").write_bytes((directory / "source.mp4").read_bytes())
    video_id = sha(directory / "source.mp4")
    manifest = {
        "schema_version": 1,
        "video_id": video_id,
        "source_sha256": video_id,
        "tracks_sha256": sha(directory / "tracks.json"),
        "metadata_sha256": sha(directory / "metadata.json"),
        "tracking_config": TrackingConfig().as_dict(),
        "provenance": {
            "creator": "Fixture Author", "title": "Fixture clip",
            "source_url": "https://example.invalid/clip", "license": "Test License",
            "license_url": "https://example.invalid/license",
        },
        "counts": {"frames": FRAMES, "track_rows": len(rows), "track_ids": len({r["track_id"] for r in rows})},
    }
    manifest.update(manifest_overrides)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.fixture()
def fixture_bundle(isolated, monkeypatch):
    directory = isolated / "bundle"
    manifest = write_bundle(directory)
    monkeypatch.setattr(real_demo, "REAL_DEMO_DIR", directory)
    return directory, manifest


def test_fixture_bundle_restores_to_the_normal_cache_layout(fixture_bundle, isolated):
    directory, manifest = fixture_bundle
    source_path, artifacts = real_demo.ensure_real_demo_assets(verify=True)
    video_id = manifest["video_id"]
    assert source_path == isolated / "cache" / video_id / "source.mp4"
    metadata = real_demo.load_bundle().metadata
    expected = _artifact_paths(video_id, source_path, TrackingConfig(), metadata)
    assert artifacts.tracks_path == expected.tracks_path
    assert sha(source_path) == manifest["source_sha256"]
    assert artifacts.tracks_path.read_bytes() == (directory / "tracks.json").read_bytes()
    assert artifacts.metadata_path.read_bytes() == (directory / "metadata.json").read_bytes()

    # Only the manifest's tracking config hits the bundled rows.
    assert cached_analysis(video_id, source_path, TrackingConfig(), metadata) is not None
    assert cached_analysis(video_id, source_path, TrackingConfig(confidence=0.5), metadata) is None
    assert cached_analysis(video_id, source_path, TrackingConfig(model_name="yolov8n.pt"), metadata) is None

    # A damaged cached copy is replaced from the bundle, never trusted.
    artifacts.tracks_path.write_text("[]", encoding="utf-8")
    real_demo.ensure_real_demo_assets()
    assert artifacts.tracks_path.read_bytes() == (directory / "tracks.json").read_bytes()

    # Clearing the cache and starting again recovers from the bundle.
    video_module.clear_analysis_cache()
    assert not source_path.exists()
    record = real_demo.real_demo_active_video()
    assert record["video_hash"] == video_id and Path(record["source_path"]).exists()
    assert not demo.is_demo_video_id(record["video_hash"])


@pytest.mark.parametrize("name", ["source.mp4", "tracks.json", "metadata.json"])
def test_altered_file_is_rejected_by_digest(fixture_bundle, name):
    directory, _ = fixture_bundle
    with (directory / name).open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(real_demo.RealDemoError, match=f"{name} does not match the SHA-256"):
        real_demo.load_bundle()


@pytest.mark.parametrize("name", ["source.mp4", "tracks.json", "metadata.json", "manifest.json"])
def test_missing_file_is_named_in_an_actionable_error(fixture_bundle, name):
    directory, _ = fixture_bundle
    (directory / name).unlink()
    with pytest.raises(real_demo.RealDemoError) as caught:
        real_demo.ensure_real_demo_assets()
    message = str(caught.value)
    assert name in message and "Restore the original files" in message and "Nothing was substituted" in message


def mutated(row_change=None, rows=None):
    rows = rows if rows is not None else fixture_rows()
    if row_change:
        rows[3] = {**rows[3], **row_change}
    return rows


@pytest.mark.parametrize(
    ("rows", "overrides", "problem"),
    [
        (mutated({"bbox": [60.0, 10.0, 80.0, 18.0], "center": [70.0, 14.0]}), {}, "outside"),
        (mutated({"timestamp_seconds": 9.0}), {}, "timestamp"),
        (mutated({"data_source": "synthetic_demo"}), {}, "data_source"),
        (mutated({"confidence": 0.1}), {}, "below the manifest threshold"),
        (mutated({"frame_index": FRAMES + 5}), {}, "outside the source video"),
        (mutated({"class_id": 2, "class_name": "truck"}), {}, "unexpected class"),
        (mutated({"frame_index": 2, "timestamp_seconds": 0.2}), {}, "repeats track"),
        (None, {"counts": {"frames": FRAMES, "track_rows": 99, "track_ids": 1}}, "track_rows=99"),
        (None, {"video_id": "f" * 64}, "video_id is not the source"),
        (None, {"tracking_config": {**TrackingConfig().as_dict(), "extra": 1}}, "tracking_config"),
        (None, {"provenance": {"title": "No credit"}}, "provenance is missing"),
    ],
)
def test_bundle_validation_rejects_rows_that_do_not_match_source(isolated, monkeypatch, rows, overrides, problem):
    directory = isolated / "bad"
    write_bundle(directory, rows, **overrides)
    monkeypatch.setattr(real_demo, "REAL_DEMO_DIR", directory)
    with pytest.raises(real_demo.RealDemoError, match=problem):
        real_demo.load_bundle()
    assert not (isolated / "cache").exists()


def test_metadata_must_describe_the_source_video(isolated, monkeypatch):
    directory = isolated / "bad"
    write_bundle(directory)
    (directory / "metadata.json").write_text(json.dumps(
        {"fps": FPS, "frame_count": FRAMES, "width": 128, "height": HEIGHT, "duration_seconds": FRAMES / FPS}
    ), encoding="utf-8")
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["metadata_sha256"] = sha(directory / "metadata.json")
    (directory / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(real_demo, "REAL_DEMO_DIR", directory)
    with pytest.raises(real_demo.RealDemoError, match="does not describe source.mp4"):
        real_demo.load_bundle()


def test_provenance_identifies_the_real_sample_distinctly(fixture_bundle):
    _, manifest = fixture_bundle
    provenance = demo.provenance_for(manifest["video_id"])
    assert provenance["data_source"] == "real_traffic_demo"
    assert provenance["label"] == "Real traffic sample"
    text = provenance["summary"] + " " + provenance["pipeline_boundary"]
    for expected in ("Fixture Author", "Fixture clip", "https://example.invalid/clip",
                     "https://example.invalid/license", "actual YOLO", "ByteTrack", "precomputed",
                     "provisional", "has not been measured", "not your upload"):
        assert expected in text
    assert "synthetic" not in text.lower()
    assert provenance["tracking_config"] == TrackingConfig().as_dict()
    assert provenance["evaluation_note"] is None
    # The other sources are unchanged.
    assert demo.provenance_for(demo.DEMO_VIDEO_ID)["data_source"] == "synthetic_demo"
    assert demo.provenance_for("a" * 64)["data_source"] == "uploaded_video"


def test_reset_only_touches_the_real_sample(fixture_bundle, isolated):
    _, manifest = fixture_bundle
    database = isolated / "data" / "nearmiss.db"
    for video_id in (manifest["video_id"], "c" * 64):
        review_incident({"incident_id": f"i-{video_id[:4]}", "source_video_id": video_id, "timestamp_seconds": 1.0},
                        "Confirmed Incident", "CAM", database)
    assert real_demo.reset_real_demo_reviews(manifest["video_id"], database) == (1, 1)
    assert len(list_reviews("c" * 64, database)) == 1
    with pytest.raises(ValueError):
        real_demo.reset_real_demo_reviews("c" * 64, database)


# ----------------------------------------------------------- shipped bundle


def test_shipped_bundle_is_actual_tracking_for_the_shipped_source():
    bundle = real_demo.load_bundle(SHIPPED)
    manifest = bundle.manifest
    assert bundle.video_id == sha(SHIPPED / "source.mp4") == manifest["source_sha256"]
    assert not demo.is_demo_video_id(bundle.video_id)
    assert manifest["tracking_config"] == TrackingConfig().as_dict()
    assert manifest["provenance"]["source_url"].startswith("https://www.pexels.com/video/")
    assert manifest["provenance"]["license_url"] == "https://www.pexels.com/license/"
    assert bundle.row_count == manifest["counts"]["track_rows"] > 0
    assert (SHIPPED / "annotated.mp4").stat().st_size > 0
    rows = json.loads((SHIPPED / "tracks.json").read_text())
    assert all(row.get("data_source", "real_traffic_demo") == "real_traffic_demo" for row in rows)
    assert all(row["confidence"] < 1.0 for row in rows), "scripted rows carry confidence 1.0"
    # The producer's caveat about unverified candidates reaches every surface.
    note = manifest.get("evaluation_note")
    if note:
        assert note in real_demo.real_provenance(bundle)["pipeline_boundary"]


def test_shipped_rows_reproduce_the_recorded_counts_at_default_thresholds():
    bundle = real_demo.load_bundle(SHIPPED)
    tracks = json.loads((SHIPPED / "tracks.json").read_text())
    metadata = bundle.metadata
    zone = [[0.0, 0.0], [float(metadata.width), 0.0],
            [float(metadata.width), float(metadata.height)], [0.0, float(metadata.height)]]
    raw = detect_conflicts(
        enrich_tracks_with_zone(tracks, zone), zone, {**DEFAULT_CONFLICT_CONFIG, "zone_is_user_defined": False}
    )
    events = deduplicate_events(normalize_events(raw, metadata.fps)[0])
    incidents = detect_suspected_collisions(tracks, events, source_video_id=bundle.video_id)
    assert len(events) == bundle.manifest["counts"]["warnings"]
    assert len(incidents) == bundle.manifest["counts"]["suspected_incidents"]


# --------------------------------------------------------------------- app


def text_of(at: AppTest) -> str:
    return "\n".join(str(item.value) for item in [*at.markdown, *at.caption, *at.info, *at.warning, *at.error])


def metric(at: AppTest, label: str) -> str:
    return next(item.value for item in at.metric if item.label == label)


def go(at: AppTest, page: str) -> None:
    at.radio(key="navigation").set_value(page).run()
    assert not at.exception, at.exception


@pytest.fixture()
def offline(isolated, monkeypatch):
    """Any model load or inference fails loudly."""

    monkeypatch.setitem(sys.modules, "ultralytics", None)

    def no_inference(*_args, **_kwargs):
        raise AssertionError("analyze_video must not run for the bundled sample")

    monkeypatch.setattr(video_module, "analyze_video", no_inference)
    return isolated


def test_default_guided_demo_opens_real_footage_offline(offline):
    bundle = real_demo.load_bundle(SHIPPED)
    counts = bundle.manifest["counts"]
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    assert not at.exception, at.exception
    assert at.button(key="start_demo").proto.type == "primary"
    at.button(key="start_demo").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Analysis"
    active = at.session_state["active_video"]
    assert active["video_hash"] == bundle.video_id
    assert not demo.is_demo_video_id(active["video_hash"])

    text = text_of(at)
    assert "REAL TRAFFIC SAMPLE" in text and "SYNTHETIC DEMO" not in text
    assert "UPLOADED FOOTAGE" not in text
    assert bundle.credit["credit"] in text and "precomputed" in text
    banner = next(str(m.value) for m in at.markdown if 'aria-label="Data source"' in str(m.value))
    assert "REAL TRAFFIC SAMPLE" in banner and bundle.credit["title"] in banner
    assert f'href="{bundle.credit["source_url"]}"' in banner and ">Pexels</a>" in banner
    assert "human review" in banner and "false alarms are possible" in banner
    prose = banner.replace(f'href="{bundle.credit["source_url"]}"', "")
    assert "https://" not in prose and "yolo11n" not in prose and len(prose) < 900
    details = next(e for e in at.expander if e.label == "Source and technical details")
    detail_text = "\n".join(str(m.value) for m in details.markdown)
    assert bundle.credit["license_url"] in detail_text and "yolo11n.pt" in detail_text
    assert bundle.video_id in detail_text
    if bundle.manifest.get("evaluation_note"):
        assert bundle.manifest["evaluation_note"] in detail_text
    # Tracker IDs, not physical vehicles.
    labels = [m.label for m in at.metric]
    assert "Vehicle track IDs" in labels and "Vehicles" not in labels
    assert next(m for m in at.metric if m.label == "Vehicle track IDs").proto.help
    assert metric(at, "Potential conflicts") == str(counts["warnings"])
    assert metric(at, "Suspected incidents") == str(counts["suspected_incidents"])

    # The bundled rows were restored byte-for-byte at the manifest config's cache path.
    source_path = Path(active["source_path"])
    artifacts = cached_analysis(bundle.video_id, source_path, TrackingConfig(), bundle.metadata)
    assert artifacts is not None
    assert artifacts.tracks_path.read_bytes() == (SHIPPED / "tracks.json").read_bytes()
    rows, _ = load_artifacts(artifacts)
    assert len(rows) == counts["track_rows"]

    snapshot = at.session_state["history_current_snapshot"]
    assert snapshot["source_kind"] == "real_traffic_demo"
    # Exports keep the full provenance, URLs and settings included.
    full = real_demo.real_provenance(bundle)
    assert bundle.credit["source_url"] in full["summary"] and "yolo11n.pt" in full["pipeline_boundary"]
    assert snapshot["provenance"]["record_data_sources"] == ["real_traffic_demo"]
    assert snapshot["provenance"]["warnings"] == []
    assert "YOLO (yolo11n.pt)" in snapshot["provenance"]["detector"]

    for page in ("Incidents", "Dispatch", "Investigation", "Explain & Share", "Street Lab", "Overview"):
        go(at, page)
        assert "REAL TRAFFIC SAMPLE" in text_of(at), page
        assert "SYNTHETIC DEMO" not in text_of(at), page
        if page == "Street Lab":
            assert "one short bundled stock clip of real traffic" in text_of(at)
    go(at, "Library")
    assert "Real sample" in text_of(at)

    # Return-to-upload behavior matches the synthetic demo.
    go(at, "Analysis")
    next(b for b in at.button if str(b.key or "").startswith("leave_demo_")).click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Overview"
    assert "active_video" not in at.session_state


def test_changed_model_settings_need_a_normal_reanalysis(offline):
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    at.button(key="start_demo").click().run()
    next(item for item in at.slider if item.label == "Object confidence").set_value(0.50).run()
    assert not at.exception, at.exception
    assert "not been processed with the current settings" in text_of(at)
    assert not [m for m in at.metric if m.label == "Potential conflicts"]


def test_cache_clear_then_start_recovers_from_the_bundle(offline):
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    at.button(key="start_demo").click().run()
    source_path = Path(at.session_state["active_video"]["source_path"])
    assert source_path.exists()
    next(b for b in at.button if b.label == "Clear processed videos").click().run()
    assert not at.exception, at.exception
    assert not source_path.exists()
    at.button(key="start_demo").click().run()
    assert not at.exception, at.exception
    assert source_path.exists() and at.session_state["navigation"] == "Analysis"
    assert metric(at, "Suspected incidents") is not None


def test_corrupt_bundle_shows_an_error_and_never_falls_back(offline, monkeypatch):
    broken = offline / "broken"
    shutil.copytree(SHIPPED, broken)
    (broken / "tracks.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(real_demo, "REAL_DEMO_DIR", broken)
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    assert not at.exception, at.exception
    assert "tracks.json does not match" in text_of(at)  # Overview preview warns too
    at.button(key="start_demo").click().run()
    assert not at.exception, at.exception
    errors = "\n".join(str(item.value) for item in at.error)
    assert "could not be opened" in errors and "Restore the original files" in errors
    assert "active_video" not in at.session_state
    assert not (offline / "cache").exists()


def test_controlled_synthetic_example_stays_separately_reachable(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    html = text_of(at)
    assert "Controlled schematic example" in html and "not the real footage above" in html
    assert "Real traffic, through the NearMiss pipeline" in html
    assert len(at.get("video")) == 1  # the real annotated preview
    at.button(key="start_synthetic_demo").click().run()
    assert not at.exception, at.exception
    assert demo.is_demo_video_id(at.session_state["active_video"]["video_hash"])
    assert "SYNTHETIC DEMO" in text_of(at)
    assert "REAL TRAFFIC SAMPLE" not in text_of(at)


def test_presenter_without_footage_presents_the_real_sample_read_only(offline):
    bundle = real_demo.load_bundle(SHIPPED)
    real = {"incident_id": "incident-real", "source_video_id": "c" * 64, "timestamp_seconds": 2.0}
    review_incident(real, "Confirmed Incident", "CAM-REAL")
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    at.button(key="presenter_open_sidebar").click().run()
    assert not at.exception, at.exception
    assert at.session_state["active_video"]["video_hash"] == bundle.video_id
    text = text_of(at)
    assert "REAL TRAFFIC SAMPLE" in text and "SYNTHETIC DEMO" not in text
    assert "Synthetic regression" not in text and "accuracy on real footage" in text
    for _ in range(4):
        at.button(key="presenter_next").click().run()
        assert not at.exception, at.exception
    if bundle.manifest["counts"]["warnings"] == 0:
        assert "No flagged moment" in text_of(at)
    assert list_reviews(bundle.video_id) == [] and list_notifications(bundle.video_id) == []
    assert len(list_reviews("c" * 64)) == 1
    at.button(key="presenter_return").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Analysis"


# ------------------------------------------------- runtime tracking provenance


def keyed_reanalysis(video_id: str, source_path: Path, config: TrackingConfig, metadata, rows) -> Path:
    """Write rows at the cache key a normal analysis with ``config`` would use.

    Stands in for a re-analysis without running inference in the test suite.
    """

    artifacts = _artifact_paths(video_id, source_path, config, metadata)
    artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
    artifacts.tracks_path.write_text(json.dumps(rows), encoding="utf-8")
    artifacts.metadata_path.write_text(json.dumps(asdict(metadata)), encoding="utf-8")
    return artifacts.tracks_path


def test_reanalysis_provenance_states_fresh_inference_with_actual_settings(fixture_bundle):
    _, manifest = fixture_bundle
    source_path, bundled = real_demo.ensure_real_demo_assets(verify=True)
    bundle = real_demo.load_bundle()
    default = demo.provenance_for(manifest["video_id"], TrackingConfig(), bundled.tracks_path)
    assert default["tracking_origin"] == "bundled_precomputed" and default["tracks_precomputed"] is True
    assert "precomputed locally and bundled" in default["pipeline_boundary"]

    pending = real_demo.runtime_provenance(TrackingConfig(model_name="yolov8n.pt"))
    assert pending["tracking_origin"] == "not_analyzed" and "precomputed" not in pending["pipeline_boundary"]

    for config in (TrackingConfig(confidence=0.5), TrackingConfig(model_name="yolov8n.pt", iou_threshold=0.6)):
        rows = [row for row in fixture_rows() if row["frame_index"] % 2 == 0]
        tracks_path = keyed_reanalysis(manifest["video_id"], source_path, config, bundle.metadata, rows)
        runtime = demo.provenance_for(manifest["video_id"], config, tracks_path)
        assert runtime == real_demo.runtime_provenance(config)
        assert runtime["data_source"] == "real_traffic_demo"
        assert runtime["tracking_origin"] == "local_inference" and runtime["tracks_precomputed"] is False
        assert runtime["tracking_config"] == config.as_dict()
        boundary = runtime["pipeline_boundary"]
        assert "fresh local" in boundary and config.model_name in boundary
        assert f"confidence {config.confidence:.2f}" in boundary and f"overlap {config.iou_threshold:.2f}" in boundary
        assert "precomputed" not in boundary and runtime["evaluation_note"] is None
        if config.model_name != "yolo11n.pt":
            assert "yolo11n" not in json.dumps(runtime)
        # The stock-footage credit is unchanged.
        assert runtime["summary"] == default["summary"] and runtime["credit"] == "Fixture Author"

    # Default settings but rows that are not the bundled bytes are not called precomputed.
    bundled.tracks_path.write_text(json.dumps(fixture_rows()[:3]), encoding="utf-8")
    assert demo.provenance_for(manifest["video_id"], TrackingConfig(), bundled.tracks_path)[
        "tracking_origin"
    ] == "local_inference"


def test_generated_briefs_and_report_follow_the_runtime_provenance(fixture_bundle, monkeypatch):
    from reportlab import rl_config

    from nearmiss import streetlab
    from nearmiss.evidence_brief import PREDICTION, build_evidence_brief
    from nearmiss.motion import EXAMPLE_CROSSING
    from nearmiss.report import generate_safety_report

    _, manifest = fixture_bundle
    source_path, _ = real_demo.ensure_real_demo_assets(verify=True)
    config = TrackingConfig(confidence=0.5)
    bundle = real_demo.load_bundle()
    rows = [{**row, "data_source": "real_traffic_demo"} for row in fixture_rows()]
    tracks_path = keyed_reanalysis(manifest["video_id"], source_path, config, bundle.metadata, rows)
    runtime = demo.provenance_for(manifest["video_id"], config, tracks_path)
    record = {
        "event_id": "conflict-001", "severity": "LOW", "first_alert_timestamp_seconds": 0.5,
        "participant_a_track_id": 1, "participant_b_track_id": 2, "arrival_time_gap_seconds": 1.2,
    }
    common = dict(
        source_name="real_traffic_sample.mp4", video_id=manifest["video_id"], source_kind="real_traffic_demo",
        metadata=asdict(bundle.metadata), tracks=rows, kind=PREDICTION, record=record,
    )
    brief = build_evidence_brief(**common, provenance=runtime)
    assert "fresh local" in brief and "confidence 0.50" in brief and "Fixture Author" in brief
    assert "precomputed" not in brief and "SYNTHETIC" not in brief
    # Without runtime provenance the brief makes no tracking-origin claim at all.
    bare = build_evidence_brief(**common)
    assert "precomputed" not in bare and "tracking origin was not supplied" in bare

    summary = streetlab.evidence_summary(
        provenance=runtime, tracks=rows, events=[record], incidents=[], duration_seconds=1.2,
        width=bundle.metadata.width, height=bundle.metadata.height,
    )
    community = streetlab.brief_markdown(streetlab.build_brief(
        summary=summary, crossing=streetlab.crossing_comparison(EXAMPLE_CROSSING),
        checklist=streetlab.checklist_items(summary), checked_ids=[], notes="",
        source_filename="real_traffic_sample.mp4",
    ))
    assert "real_traffic_demo" in community and "Fixture Author" in community
    assert "precomputed" not in community and "SYNTHETIC" not in community

    monkeypatch.setattr(rl_config, "pageCompression", 0)
    pdf = generate_safety_report(
        source_filename="real_traffic_sample.mp4", duration_seconds=1.2, tracks=rows, events=[],
        heatmap_rgb=np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), provenance=runtime,
    )
    assert b"fresh local" in pdf and b"precomputed" not in pdf


def test_app_after_reanalysis_reports_fresh_inference_everywhere(offline):
    bundle = real_demo.load_bundle(SHIPPED)
    record = real_demo.real_demo_active_video()
    config = TrackingConfig(confidence=0.5)
    shipped_rows = json.loads((SHIPPED / "tracks.json").read_text())
    # A correctly keyed stand-in for a confidence-0.50 re-analysis (no inference is run).
    rows = [row for row in shipped_rows if row["confidence"] >= 0.5]
    keyed_reanalysis(bundle.video_id, Path(record["source_path"]), config, bundle.metadata, rows)

    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["active_video"] = record
    at.session_state["navigation"] = "Analysis"
    at.run()
    assert not at.exception, at.exception
    assert "precomputed locally" in text_of(at)
    next(item for item in at.slider if item.label == "Object confidence").set_value(0.50).run()
    assert not at.exception, at.exception

    banner = next(str(m.value) for m in at.markdown if 'aria-label="Data source"' in str(m.value))
    assert "REAL TRAFFIC SAMPLE" in banner and bundle.credit["credit"] in banner
    assert "fresh local YOLO + ByteTrack analysis" in banner and "precomputed" not in banner
    details = "\n".join(
        str(m.value) for m in next(e for e in at.expander if e.label == "Source and technical details").markdown
    )
    assert "confidence 0.50" in details and "precomputed" not in details
    note = bundle.manifest.get("evaluation_note")
    if note:  # the producer note describes the bundled rows only
        assert note not in details

    snapshot = at.session_state["history_current_snapshot"]
    assert snapshot["source_kind"] == "real_traffic_demo"
    assert snapshot["config"]["tracking_config"]["confidence"] == pytest.approx(0.5)
    assert snapshot["provenance"]["tracking_origin"] == "local_inference"
    assert "fresh local inference" in snapshot["provenance"]["detector"]

    go(at, "Explain & Share")
    page = text_of(at)
    assert "fresh local YOLO" in page and "precomputed" not in page
    go(at, "Library")
    assert "precomputed" not in text_of(at)
