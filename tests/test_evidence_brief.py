"""Tests for Explain & Share evidence explanations and Markdown briefs.

All tracks, events and incidents here are synthetic fixtures. Incidents are
produced by running the real incident detector on scripted tracks so the
explained metrics are actual detector output, not hand-typed values.
"""

from __future__ import annotations

import re

import pytest

from nearmiss.evidence_brief import (
    INCIDENT,
    PREDICTION,
    brief_filename,
    build_evidence_brief,
    describe_source,
    dispatch_state,
    evidence_options,
    explain_incident,
    explain_prediction,
    md,
    missing_fields,
    processing_quality,
    review_state,
)
from nearmiss.incidents import detect_suspected_collisions
from nearmiss.store import list_notifications, list_reviews, review_incident
from nearmiss.video import VideoMetadata


VIDEO_ID = "synthetic-video"
TIMES = [index / 10 for index in range(16)]


def _rows(track_id: int, positions: list[tuple[float, float, float]], data_source=None) -> list[dict]:
    rows = []
    for timestamp, x, y in positions:
        row = {
            "track_id": track_id,
            "object_type": "vehicle",
            "class_name": "car",
            "frame_index": round(timestamp * 10),
            "timestamp_seconds": timestamp,
            "bbox": [x - 5.0, y - 10.0, x + 5.0, y],
            "confidence": 0.9,
        }
        if data_source:
            row["data_source"] = data_source
        rows.append(row)
    return rows


def collision_tracks(data_source=None) -> list[dict]:
    first, second = [], []
    for timestamp in TIMES:
        if timestamp <= 0.8:
            first.append((timestamp, 10.0 + 50.0 * timestamp, 50.0))
            second.append((timestamp, 50.0, 10.0 + 50.0 * timestamp))
        else:
            first.append((timestamp, 50.0, 50.0))
            second.append((timestamp, 50.0, 50.0))
    return _rows(1, first, data_source) + _rows(2, second, data_source)


def prediction_event(**overrides) -> dict:
    event = {
        "event_id": "conflict-001",
        "timestamp_seconds": 0.3,
        "first_alert_timestamp_seconds": 0.3,
        "end_timestamp_seconds": 0.6,
        "severity": "High",
        "risk_score": 81.2,
        "conflict_geometry": "crossing_paths",
        "participant_a_track_id": 1,
        "participant_b_track_id": 2,
        "participant_a_track_ids": [1],
        "participant_b_track_ids": [2],
        "participant_a_class": "car",
        "participant_b_class": "truck",
        "arrival_time_gap_seconds": 0.42,
        "time_to_conflict_seconds": 1.37,
        "path_separation_pixels": 18.46,
        "persistence_frames": 4,
        "closing_speed_pixels_per_second": 61.3,
        "zone_is_user_defined": False,
    }
    event.update(overrides)
    return event


@pytest.fixture
def incident() -> dict:
    incidents = detect_suspected_collisions(collision_tracks(), [prediction_event()], VIDEO_ID)
    assert len(incidents) == 1
    return incidents[0]


LONG_META = VideoMetadata(fps=10.0, frame_count=600, width=100, height=100, duration_seconds=60.0)


# ----------------------------------------------------------------- options


def test_options_skip_malformed_records_and_order_by_time(incident):
    options = evidence_options([prediction_event(), "junk", None], [incident, 7])
    assert [item["kind"] for item in options] == [PREDICTION, INCIDENT]
    assert options[1]["id"] == incident["incident_id"]
    assert "Suspected incident" in options[1]["label"]
    assert evidence_options(None, "not-a-list") == []


def test_option_without_id_is_labeled_not_invented():
    options = evidence_options([{"participant_a_track_id": 3}], [])
    assert options[0]["id"] == "prediction-1 (no ID supplied)"
    assert "track ID missing" in options[0]["label"]


# -------------------------------------------------------------- predictions


def test_prediction_explanation_uses_supplied_metrics():
    explanation = explain_prediction(prediction_event())
    text = " ".join(explanation["explanation"])
    assert "car #1" in text and "truck #2" in text
    assert "0.42 s" in text and "1.37 s" in text and "18.5 px" in text
    assert "4 analysed frames" in text and "61.3 px/s" in text
    assert "not an observed contact" in text
    facts = {fact["label"]: fact["value"] for fact in explanation["facts"]}
    assert facts["Arrival gap"] == "0.42 s"
    assert facts["Warning time"].endswith("(0.30 s)")
    assert "not a probability" in next(
        fact["note"] for fact in explanation["facts"] if fact["label"].startswith("Heuristic")
    )
    assert explanation["missing_fields"] == []


@pytest.mark.parametrize("bad", ["abc", float("nan"), float("inf"), True, None, [1], {"x": 1}])
def test_malformed_prediction_fields_are_reported_missing(bad):
    event = prediction_event(arrival_time_gap_seconds=bad, path_separation_pixels=bad)
    explanation = explain_prediction(event)
    assert "arrival gap" in explanation["missing_fields"]
    assert "projected separation" in explanation["missing_fields"]
    facts = {fact["label"]: fact["value"] for fact in explanation["facts"]}
    assert facts["Arrival gap"] == "—"
    assert "arrival times differed" not in " ".join(explanation["explanation"])


def test_non_dict_records_do_not_crash():
    assert len(missing_fields(PREDICTION, None)) == 8
    assert explain_prediction(None)["id"] == "—"
    explanation = explain_incident("garbage")
    assert explanation["review"]["confirmed"] is False
    assert "could not be checked" in " ".join(explanation["explanation"])


# ---------------------------------------------------------------- incidents


def test_incident_explanation_matches_detector_measurements(incident):
    measurements = incident["measurements"]
    explanation = explain_incident(incident)
    text = " ".join(explanation["explanation"])
    assert f"{incident['contact_persistence_frames']} consecutive frames" in text
    assert f"{measurements['distance_reduction_pixels']:.1f} px" in text
    assert f"{measurements['peak_overlap_fraction_smaller_box'] * 100:.0f}%" in text
    assert "conflict-001" in text and f"{incident['prediction_lead_seconds']:.2f} s" in text
    assert "not proof of a collision" in text
    assert explanation["missing_fields"] == []
    assert {row["track_id"] for row in explanation["motion_rows"]} == {1, 2}


def test_incident_without_prediction_says_so(incident):
    incident = {**incident, "associated_prediction_event_id": None, "prediction_lead_seconds": None}
    text = " ".join(explain_incident(incident)["explanation"])
    assert "No earlier prediction warning" in text


def test_incident_with_broken_measurements(incident):
    broken = {**incident, "measurements": "oops", "detection_signals": None}
    explanation = explain_incident(broken)
    assert "convergence result" in explanation["missing_fields"]
    assert "detection signals" in explanation["missing_fields"]
    assert "No motion-response signal" in " ".join(explanation["explanation"])


# ------------------------------------------------- evidence-gated claims


def _text_of(explanation: dict) -> str:
    return " ".join(explanation["explanation"])


@pytest.mark.parametrize("record", [{}, None, "garbage", {"event_type": "suspected_collision"}])
def test_empty_or_malformed_incident_makes_no_contact_claim(record):
    explanation = explain_incident(record)
    text = _text_of(explanation)
    assert explanation["evidence_status"] == "insufficient"
    assert "touching" not in text
    assert "cannot establish that their boxes touched" in text
    assert "cannot establish a suspected incident" in text
    assert "track IDs were not supplied" in text
    assert "unknown from the supplied fields" in text
    assert "No earlier prediction warning was linked" not in text


@pytest.mark.parametrize("record", [{}, None, [1, 2], {"severity": "High", "conflict_geometry": "crossing_paths"}])
def test_empty_or_malformed_prediction_makes_no_path_claim(record):
    explanation = explain_prediction(record)
    text = _text_of(explanation)
    assert explanation["evidence_status"] == "insufficient"
    assert "shared point" not in text and "trailing vehicle closing" not in text
    assert "cannot establish why it was flagged" in text


def test_type_strings_do_not_count_as_evidence():
    garbage = prediction_event(
        arrival_time_gap_seconds="soon", time_to_conflict_seconds=None,
        path_separation_pixels=float("nan"), persistence_frames="many",
        closing_speed_pixels_per_second=True,
    )
    assert explain_prediction(garbage)["evidence_status"] == "insufficient"
    incident = {"vehicle_a_track_id": 1, "vehicle_b_track_id": 2, "contact_persistence_frames": "x",
                "detection_signals": [None, 3], "measurements": {"converging": "yes"}}
    explanation = explain_incident(incident)
    assert explanation["evidence_status"] == "insufficient"
    assert "could not be checked" in _text_of(explanation)


def test_partial_prediction_reports_values_without_headline():
    explanation = explain_prediction({"event_id": "e1", "participant_a_track_id": 4,
                                      "participant_b_track_id": 9, "arrival_time_gap_seconds": 0.5})
    text = _text_of(explanation)
    assert explanation["evidence_status"] == "partial"
    assert "lacks a projected-path measure" in text
    assert "0.50 s" in text and "shared point" not in text
    facts = {fact["label"]: fact["value"] for fact in explanation["facts"]}
    assert facts["Evidence completeness"].startswith("Partial")


def test_partial_incident_states_only_supplied_parts(incident):
    contact_only = {key: incident[key] for key in (
        "incident_id", "source_video_id", "vehicle_a_track_id", "vehicle_b_track_id",
        "first_suspected_impact_timestamp_seconds", "contact_persistence_frames",
    )}
    explanation = explain_incident(contact_only)
    text = _text_of(explanation)
    assert explanation["evidence_status"] == "partial"
    assert "detector reported the boxes around car" not in text  # classes were not supplied
    assert "road user #1 and road user #2 touching" in text
    assert "it lacks prior convergence, a motion response" in text

    motion_only = {"measurements": {"motion_response": {"sudden_deceleration": True}}}
    text = _text_of(explain_incident(motion_only))
    assert "no usable box-contact evidence" in text
    assert "After the flagged time the tracker recorded: sudden slowdown" in text
    assert "it lacks box contact, prior convergence" in text


def test_valid_detector_output_keeps_clear_explanations(incident):
    explanation = explain_incident(incident)
    text = _text_of(explanation)
    assert explanation["evidence_status"] == "established"
    assert "detector reported the boxes around car #1 and car #2 touching" in text
    assert "includes all three parts" in text
    assert "cannot establish" not in text
    prediction = explain_prediction(prediction_event())
    assert prediction["evidence_status"] == "established"
    assert "would reach a shared point" in _text_of(prediction)
    following = explain_prediction(prediction_event(
        conflict_geometry="same_direction_following", time_headway_seconds=0.8,
        arrival_time_gap_seconds=None,
    ))
    assert following["evidence_status"] == "established"
    assert "trailing vehicle closing" in _text_of(following)


def test_insufficient_brief_does_not_assert_result():
    brief = build_evidence_brief(
        source_name="clip.mp4", video_id="v", source_kind="uploaded_video", metadata=LONG_META,
        tracks=[], kind=INCIDENT, record={},
    )
    assert "| Evidence completeness | Insufficient" in brief
    assert "cannot establish a suspected incident" in brief
    assert "touching" not in brief


def test_ui_flags_incomplete_record():
    app = _app(incidents=[{"incident_id": "x"}])
    assert not app.exception
    assert any("record is incomplete" in block.value for block in app.warning)


# --------------------------------------------------- review and dispatch


def test_unreviewed_incident_is_never_called_confirmed(incident):
    claimed = {**incident, "review_status": "Confirmed Incident"}
    review = review_state(claimed, [])
    assert review["status"] == "Not reviewed" and review["confirmed"] is False
    assert "no matching saved review" in review["inconsistency"]
    brief = build_evidence_brief(
        source_name="clip.mp4", video_id=VIDEO_ID, source_kind="uploaded_video",
        metadata=LONG_META, tracks=collision_tracks(), kind=INCIDENT, record=claimed,
    )
    assert "No saved operator review" in brief
    assert "marked this as a Confirmed Incident" not in brief


def test_review_from_other_video_is_ignored(incident):
    row = {"incident_id": incident["incident_id"], "video_id": "other", "review_status": "Confirmed Incident"}
    assert review_state(incident, [row])["confirmed"] is False


def test_persisted_confirmation_and_withdrawal(tmp_path, incident):
    database = tmp_path / "nearmiss.db"
    review_incident(incident, "Confirmed Incident", "CAM-1", database)
    reviews, notifications = list_reviews(VIDEO_ID, database), list_notifications(VIDEO_ID, database)
    explanation = explain_incident(incident, reviews, notifications)
    assert explanation["review"]["confirmed"] is True
    assert explanation["dispatch"]["status"] == "New"
    assert explanation["dispatch"]["external_alert_sent"] is False
    assert "nothing outside this computer" in explanation["dispatch"]["statement"]

    # Dict keyed by incident ID (as app.py holds it) works too.
    keyed = {row["incident_id"]: row for row in reviews}
    assert review_state(incident, keyed)["confirmed"] is True

    review_incident(incident, "False Alarm", "CAM-1", database)
    reviews, notifications = list_reviews(VIDEO_ID, database), list_notifications(VIDEO_ID, database)
    explanation = explain_incident(incident, reviews, notifications)
    assert explanation["review"]["status"] == "False Alarm"
    assert explanation["dispatch"]["status"] == "Withdrawn"
    assert explanation["dispatch"]["inconsistency"] is None


def test_no_dispatch_record_means_no_external_alert(incident):
    state = dispatch_state(incident, None)
    assert state["status"] == "None" and state["external_alert_sent"] is False
    assert "no external alert was sent" in state["statement"]


def test_active_notice_without_confirmation_is_flagged(incident):
    notice = {"incident_id": incident["incident_id"], "status": "New"}
    state = dispatch_state(incident, [notice], review_state(incident, []))
    assert "still treated as unconfirmed" in state["inconsistency"]


# --------------------------------------------------------------- provenance


def test_synthetic_marker_wins_over_label():
    assert describe_source("synthetic_demo")["is_synthetic"] is True
    relabeled = describe_source("uploaded_video", "abc", collision_tracks("synthetic_demo"))
    assert relabeled["is_synthetic"] is True and relabeled["note"]
    assert describe_source("uploaded_video", "abc", collision_tracks())["is_synthetic"] is False
    assert describe_source(None)["label"] == "Unspecified source"


def test_synthetic_brief_is_labeled_throughout(incident):
    brief = build_evidence_brief(
        source_name="demo.mp4", video_id="synthetic-demo-1", source_kind="synthetic_demo",
        metadata={"fps": 20.0, "duration_seconds": 12.0}, tracks=collision_tracks("synthetic_demo"),
        kind=INCIDENT, record=incident, generated_at="2026-10-25T00:00:00+00:00",
    )
    assert brief.startswith("# [SYNTHETIC] NearMiss evidence brief")
    assert "SYNTHETIC DEMONSTRATION" in brief.splitlines()[2]
    assert brief.rstrip().endswith("SYNTHETIC DEMONSTRATION.")
    assert "Scripted tracks report confidence" in brief
    assert brief_filename(INCIDENT, incident, True).startswith("SYNTHETIC_nearmiss_evidence_incident_")


def test_real_source_brief_has_no_synthetic_label(incident):
    brief = build_evidence_brief(
        source_name="clip.mp4", video_id="abc123", source_kind="uploaded_video",
        metadata=LONG_META, tracks=collision_tracks(), kind=INCIDENT,
        record={**incident, "source_video_id": "abc123"},
    )
    assert "SYNTHETIC" not in brief


# ---------------------------------------------------------------- quality


def _quality(kind, record, metadata, tracks, source_kind="uploaded_video"):
    checks = processing_quality(
        kind=kind, record=record, metadata=metadata, tracks=tracks,
        source=describe_source(source_kind, "abc", tracks),
    )
    return {check["check"]: check for check in checks}


def test_quality_flags_short_clip_sparse_tracks_and_calibration():
    sparse = [row for row in collision_tracks() if row["frame_index"] % 7 == 0]
    checks = _quality(PREDICTION, prediction_event(), {"fps": 10, "duration_seconds": 1.5}, sparse)
    assert checks["Clip length"]["status"] == "caution" and "Short clip" in checks["Clip length"]["detail"]
    assert checks["Track coverage"]["status"] == "caution" and "Sparse" in checks["Track coverage"]["detail"]
    assert checks["Field calibration"]["status"] == "caution"
    assert checks["Analysis area"]["status"] == "info"
    assert "not an accuracy rate" in checks["Detector confidence"]["detail"]


def test_quality_handles_missing_inputs():
    checks = _quality(PREDICTION, {}, None, [], source_kind=None)
    assert checks["Clip length"]["detail"] == "Clip duration is unknown."
    assert checks["Frame rate"]["status"] == "caution"
    assert "No track rows" in checks["Track coverage"]["detail"]
    assert checks["Detector fields"]["status"] == "caution"
    assert checks["Source provenance"]["status"] == "caution"


def test_quality_ok_for_long_dense_clip(incident):
    checks = _quality(INCIDENT, incident, LONG_META, collision_tracks())
    assert checks["Clip length"]["status"] == "ok"
    assert checks["Track coverage"]["status"] == "ok"
    assert checks["Detector fields"]["status"] == "ok"
    assert checks["Field calibration"]["status"] == "caution"


# ------------------------------------------------------------------ brief


def test_prediction_brief_content_and_no_invented_scores():
    brief = build_evidence_brief(
        source_name="clip.mp4", video_id="abc", source_kind="uploaded_video", metadata=LONG_META,
        tracks=collision_tracks(), kind=PREDICTION, record=prediction_event(),
        generated_at="2026-10-25T00:00:00+00:00",
    )
    for heading in ("## What NearMiss observed", "## Evidence facts", "## Processing-quality checklist",
                    "## What this brief does not claim"):
        assert heading in brief
    assert "| Arrival gap | 0.42 s |" in brief
    assert "never create a dispatch notice" in brief
    assert "2026-10-25T00:00:00+00:00" in brief
    assert not re.search(r"\d+(\.\d+)?\s*% (accura|probab|chance|risk)", brief, re.I)
    assert "Confirmed Incident" not in brief


def test_brief_escapes_supplied_text():
    brief = build_evidence_brief(
        source_name="evil|name<script>", video_id="v", source_kind="uploaded_video", metadata=None,
        tracks=[], kind=PREDICTION, record=prediction_event(participant_a_class="car|*x*"),
    )
    assert "<script>" not in brief
    assert r"evil\|name\<script\>" in brief
    assert r"car\|\*x\*" in brief
    assert md("a\nb") == "a b"


def test_brief_filename_is_safe():
    assert brief_filename(PREDICTION, {"event_id": "../../etc/passwd"}, False) == (
        "nearmiss_evidence_prediction_etc-passwd.md"
    )
    assert brief_filename(INCIDENT, None, False) == "nearmiss_evidence_incident_unidentified.md"


# --------------------------------------------------------------------- UI


def _page(**kwargs):
    from nearmiss.evidence_ui import render_evidence_page

    render_evidence_page(**kwargs)


def _app(**overrides):
    from streamlit.testing.v1 import AppTest

    kwargs = {
        "source_name": "demo.mp4", "video_id": "synthetic-demo-1", "source_kind": "synthetic_demo",
        "metadata": {"fps": 10.0, "duration_seconds": 1.6}, "tracks": collision_tracks("synthetic_demo"),
        "events": [], "incidents": [], "reviews": [], "notifications": [],
    }
    kwargs.update(overrides)
    return AppTest.from_function(_page, kwargs=kwargs, default_timeout=20).run()


def test_ui_empty_state():
    app = _app()
    assert not app.exception
    assert any("Nothing to explain yet" in block.value for block in app.markdown)
    assert any("SYNTHETIC DEMONSTRATION" in block.value for block in app.warning)


def test_ui_renders_incident_and_prediction(incident):
    app = _app(events=[prediction_event()], incidents=[incident])
    assert not app.exception
    assert [option for option in app.radio[0].options] == [
        "Suspected incidents (1)", "Prediction warnings (1)"
    ]
    assert any(metric.value == "Not reviewed" for metric in app.metric)
    app.radio[0].set_value(PREDICTION).run()
    assert not app.exception
    assert any("not an observed contact" in block.value for block in app.markdown)
