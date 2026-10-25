"""Tests for the labeled synthetic demo, evidence explanations, and Street Lab.

The demo footage and tracks are generated illustrations; these tests verify
they flow through the real detectors and stay labeled, not that they measure
anything about real traffic.
"""

from __future__ import annotations

import base64
import re
import zlib

import numpy as np
import pytest

import nearmiss.video as video_module
from conflict_detector import detect_conflicts
from nearmiss import demo, streetlab
from nearmiss.config import DEFAULT_CONFLICT_CONFIG
from nearmiss.explain import explain_event, explain_incident
from nearmiss.incidents import detect_suspected_collisions
from nearmiss.report import generate_safety_report
from nearmiss.safety import deduplicate_events
from nearmiss.store import list_notifications, list_reviews, review_incident
from nearmiss.video import cached_analysis, frame_at_timestamp, inspect_video, load_artifacts


FULL_FRAME = [[0, 0], [demo.WIDTH, 0], [demo.WIDTH, demo.HEIGHT], [0, demo.HEIGHT]]


def pdf_text(pdf: bytes) -> str:
    """Inflate ReportLab content streams (ASCII85 + Flate) for text assertions."""

    chunks = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        data = stream.strip()
        try:
            if data.endswith(b"~>"):
                data = base64.a85decode(data, adobe=True)
            chunks.append(zlib.decompress(data).decode("latin-1"))
        except (ValueError, zlib.error):
            continue
    return "\n".join(chunks)


def demo_results():
    tracks = demo.synthetic_tracks()
    events = deduplicate_events(detect_conflicts(tracks, FULL_FRAME, DEFAULT_CONFLICT_CONFIG))
    incidents = detect_suspected_collisions(tracks, events, demo.DEMO_VIDEO_ID)
    return tracks, events, incidents


def test_demo_tracks_are_deterministic_and_labeled():
    first, second = demo.synthetic_tracks(), demo.synthetic_tracks()
    assert first == second
    assert first and all(row["data_source"] == "synthetic_demo" for row in first)
    assert demo.is_demo_video_id(demo.DEMO_VIDEO_ID)
    assert not demo.is_demo_video_id("a" * 64)


def test_demo_runs_through_real_detectors_with_an_inspectable_incident():
    _tracks, events, incidents = demo_results()
    geometries = sorted(event["conflict_geometry"] for event in events)
    assert geometries == ["crossing_paths", "crossing_paths", "same_direction_following"]
    assert len(incidents) == 1
    incident = incidents[0]
    assert {incident["vehicle_a_track_id"], incident["vehicle_b_track_id"]} == {3, 4}
    assert incident["associated_prediction_event_id"] is not None
    assert incident["prediction_lead_seconds"] > 0
    assert "sudden_deceleration" in incident["detection_signals"]


def test_demo_assets_follow_cache_layout_and_are_stamped(tmp_path, monkeypatch):
    monkeypatch.setattr(video_module, "CACHE_ROOT", tmp_path)
    source_path, artifacts = demo.ensure_demo_assets()
    assert source_path == tmp_path / demo.DEMO_VIDEO_ID / "source.mp4"
    metadata, _first = inspect_video(source_path)
    assert (metadata.width, metadata.height) == (demo.WIDTH, demo.HEIGHT)
    found = cached_analysis(demo.DEMO_VIDEO_ID, source_path, demo.DEMO_TRACKING_CONFIG, metadata)
    assert found is not None and found.tracks_path == artifacts.tracks_path
    tracks, saved_metadata = load_artifacts(found)
    assert tracks == demo.synthetic_tracks()
    assert saved_metadata.frame_count == demo.frame_count()
    # The SYNTHETIC DEMO pill (amber, bottom right) is burned into decoded frames.
    frame = frame_at_timestamp(source_path, 6.0)
    patch = frame[demo.HEIGHT - 44 : demo.HEIGHT - 16, demo.WIDTH - 236 : demo.WIDTH - 16]
    amber = (np.abs(patch.astype(int) - np.array(demo.AMBER)) < 40).all(axis=2).mean()
    assert amber > 0.5
    assert (tmp_path / demo.DEMO_VIDEO_ID / "provenance.json").exists()
    # A second call reuses the files rather than regenerating them.
    before = source_path.stat().st_mtime_ns
    demo.ensure_demo_assets()
    assert source_path.stat().st_mtime_ns == before


def test_demo_reset_only_touches_the_synthetic_video(tmp_path):
    database = tmp_path / "review.db"
    real_incident = {"incident_id": "incident-real", "source_video_id": "b" * 64, "timestamp_seconds": 1.0}
    demo_incident = {"incident_id": "incident-demo", "source_video_id": demo.DEMO_VIDEO_ID, "timestamp_seconds": 7.7}
    review_incident(real_incident, "Confirmed Incident", "CAM-REAL", database)
    review_incident(demo_incident, "Confirmed Incident", "CAM-DEMO", database)
    with pytest.raises(ValueError):
        demo.reset_demo_reviews("b" * 64, database)
    assert demo.reset_demo_reviews(demo.DEMO_VIDEO_ID, database) == (1, 1)
    assert list_reviews(demo.DEMO_VIDEO_ID, database) == []
    assert list_notifications(demo.DEMO_VIDEO_ID, database) == []
    assert len(list_reviews("b" * 64, database)) == 1
    assert len(list_notifications("b" * 64, database)) == 1


def test_explanations_cite_measured_values():
    _tracks, events, incidents = demo_results()
    following = next(e for e in events if e["conflict_geometry"] == "same_direction_following")
    crossing = next(e for e in events if e["conflict_geometry"] == "crossing_paths")
    following_text = explain_event(following)
    crossing_text = explain_event(crossing)
    assert following_text["pattern"] == "following"
    assert any("headway" in bullet for bullet in following_text["bullets"])
    assert crossing_text["pattern"] == "crossing"
    assert any(f"{crossing['arrival_time_gap_seconds']:.2f}s" in bullet for bullet in crossing_text["bullets"])
    incident_text = explain_incident(incidents[0])
    assert len(incident_text["bullets"]) == len(incidents[0]["detection_signals"])
    # Signals span contact, peak, and post-contact frames and are correlated.
    assert "across the contact episode" in incident_text["headline"]
    assert "independent" not in incident_text["headline"]
    assert "at first contact" not in incident_text["headline"]
    assert "before first contact" in incident_text["prediction"]
    no_lead = explain_incident({**incidents[0], "associated_prediction_event_id": None})
    assert "No prediction warning preceded" in no_lead["prediction"]


def test_persistence_bullet_describes_episode_run_not_pre_warning_frames():
    _tracks, events, _incidents = demo_results()
    event = next(e for e in events if e.get("high_persistence_frames"))
    text = " ".join(explain_event(event)["bullets"])
    assert f"longest consecutive run at HIGH lasted {int(event['high_persistence_frames'])} frames" in text
    assert "Across the observed episode" in text
    assert "before the warning" not in text


def test_crossing_comparison_is_plain_arithmetic_on_assumptions():
    result = streetlab.crossing_comparison(streetlab.CrossingAssumptions())
    typical, slower = result["rows"]
    assert typical["current_seconds"] == round(2.0 + 60 / 3.5, 1)
    assert typical["proposed_seconds"] == round(2.0 + 40 / 3.5, 1)
    assert slower["difference_seconds"] == 8.0
    assert typical["in_roadway_change_percent"] == 33.3
    assert "not a measured crash reduction" in result["boundary"]
    assert "review hypothesis" in result["hypothesis"]
    with pytest.raises(ValueError):
        streetlab.crossing_comparison(streetlab.CrossingAssumptions(walking_speed=0))
    with pytest.raises(ValueError):
        streetlab.crossing_comparison(streetlab.CrossingAssumptions(start_up_seconds=-1))


def test_street_lab_summary_brief_and_checklist_match(tmp_path):
    tracks, events, incidents = demo_results()
    incidents[0]["review_status"] = "Confirmed Incident"
    summary = streetlab.evidence_summary(
        provenance=demo.DEMO_PROVENANCE, tracks=tracks, events=events, incidents=incidents,
        duration_seconds=12.0, width=demo.WIDTH, height=demo.HEIGHT,
    )
    assert summary["warnings_total"] == 3
    assert summary["pedestrians_tracked"] == 2
    assert summary["incident_reviews"]["Confirmed"] == 1
    linked = [item for item in summary["review_items"] if "preceded a suspected collision" in item["why_review"]]
    assert len(linked) == 1 and "operator confirmed" in linked[0]["why_review"]
    checklist = streetlab.checklist_items(summary)
    ids = [item["id"] for item in checklist]
    assert ids.index("crossing_rightofway") < ids.index("measure_crossing")
    assert {"following_braking", "incident_records", "pedestrian_counts"} <= set(ids)

    crossing = streetlab.crossing_comparison(streetlab.CrossingAssumptions(current_distance=72, proposed_distance=48))
    brief = streetlab.build_brief(
        summary=summary, crossing=crossing, checklist=checklist, checked_ids={"measure_crossing"},
        notes="Observe Tuesday 7:30", source_filename=demo.DEMO_FILENAME, generated_at="2026-01-01T00:00:00+00:00",
    )
    markdown = streetlab.brief_markdown(brief)
    text = pdf_text(streetlab.brief_pdf(brief))
    for expected in ("SYNTHETIC DEMO", "review hypothesis", f"{crossing['rows'][0]['current_seconds']:.1f}",
                     "Observe Tuesday 7:30", summary["review_items"][0]["time"]):
        assert expected in markdown
        assert expected in text
    assert "- [x] Measure curb-to-curb" in markdown
    assert "- [ ] " in markdown


@pytest.mark.parametrize(
    ("current", "proposed", "difference", "roadway"),
    [
        (60, 40, "5.7 s shorter", "33.3% less time"),
        (40, 60, "5.7 s longer", "50.0% more time"),
        (50, 50, "no change", "no change"),
    ],
)
def test_crossing_change_exports_use_direction_words(current, proposed, difference, roadway):
    summary = streetlab.evidence_summary(
        provenance=demo.UPLOAD_PROVENANCE, tracks=[], events=[], incidents=[],
        duration_seconds=10.0, width=100, height=100,
    )
    crossing = streetlab.crossing_comparison(
        streetlab.CrossingAssumptions(current_distance=current, proposed_distance=proposed)
    )
    assert crossing["rows"][0]["difference_text"] == difference
    assert crossing["rows"][0]["in_roadway_change_text"] == roadway
    brief = streetlab.build_brief(
        summary=summary, crossing=crossing, checklist=streetlab.checklist_items(summary),
        checked_ids=[], notes="", source_filename="clip.mp4",
    )
    markdown = streetlab.brief_markdown(brief)
    text = pdf_text(streetlab.brief_pdf(brief))
    for export in (markdown, text):
        assert difference in export and roadway in export
        assert "--" not in export.replace("|---", "")


def test_uploaded_source_brief_is_not_labeled_synthetic():
    summary = streetlab.evidence_summary(
        provenance=demo.UPLOAD_PROVENANCE, tracks=[], events=[], incidents=[],
        duration_seconds=10.0, width=100, height=100,
    )
    brief = streetlab.build_brief(
        summary=summary, crossing=streetlab.crossing_comparison(streetlab.CrossingAssumptions()),
        checklist=streetlab.checklist_items(summary), checked_ids=[], notes="", source_filename="clip.mp4",
    )
    markdown = streetlab.brief_markdown(brief)
    assert "SYNTHETIC" not in markdown
    assert "not proof of safety" in markdown


def test_safety_report_carries_synthetic_provenance():
    heatmap = np.zeros((60, 100, 3), dtype=np.uint8)
    pdf = generate_safety_report(
        source_filename=demo.DEMO_FILENAME, duration_seconds=12.0, tracks=[], events=[],
        heatmap_rgb=heatmap, provenance=demo.DEMO_PROVENANCE,
    )
    assert "SYNTHETIC DEMO" in pdf_text(pdf)
    assert b"SYNTHETIC DEMO" in pdf  # document title metadata
