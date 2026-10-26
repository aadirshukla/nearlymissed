"""Threshold sensitivity comparison: real detector re-runs on stored track rows."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from conflict_detector import detect_conflicts
from nearmiss import demo
from nearmiss.comparison import (
    PARAMETER,
    ComparisonError,
    build_changed_config,
    compare_threshold,
    comparison_json,
    match_episodes,
    resolve_zone,
    run_detector,
    same_participants,
    validate_threshold_config,
)
from nearmiss.config import DEFAULT_CONFLICT_CONFIG


FPS = 20.0
FRAME = (800, 600)
ZONE = [[0.0, 0.0], [800.0, 0.0], [800.0, 600.0], [0.0, 600.0]]


def row(track_id, frame, cx, cy):
    return {
        "track_id": track_id,
        "class_id": 2,
        "class_name": "car",
        "object_type": "vehicle",
        "frame_index": frame,
        "timestamp_seconds": round(frame / FPS, 4),
        "bbox": [cx - 20, cy - 20, cx + 20, cy],
        "center": [cx, cy - 10],
        "confidence": 0.9,
    }


def crossing(gap, a_id, b_id, start_frame=0, x=300.0, switch_at=None, b_new_id=None):
    """Two cars at 100 px/s; B reaches the crossing ``gap`` seconds after A."""

    rows = []
    for i in range(int(4.0 * FPS)):
        t = i / FPS
        frame = start_frame + i
        rows.append(row(a_id, frame, x - 200 + 100 * t, 200))
        b = b_id if switch_at is None or t < switch_at else b_new_id
        rows.append(row(b, frame, x, 200 - 100 * (2 + gap) + 100 * t))
    return rows


def fixture_tracks():
    # Pair 1/2: 0.3 s gap (HIGH under any setting). Pair 3/4 starts at 5 s with a
    # 1.6 s gap, qualifying at 1.75 s but not at 1.25 s. Track 4 switches to 9.
    return crossing(0.3, 1, 2) + crossing(1.6, 3, 4, start_frame=100, x=600, switch_at=1.0, b_new_id=9)


def baseline_cfg():
    return {**DEFAULT_CONFLICT_CONFIG, "zone_is_user_defined": False}


def compare(value, tracks=None, events=None, cfg=None, data_source="uploaded_video", **kwargs):
    tracks = fixture_tracks() if tracks is None else tracks
    cfg = baseline_cfg() if cfg is None else cfg
    if events is None:
        events = run_detector(tracks, ZONE, cfg)
    return compare_threshold(
        tracks=tracks,
        events=events,
        cfg=cfg,
        zone_polygon=[],
        frame_size=FRAME,
        data_source=data_source,
        video_id="a" * 64,
        changed_value=value,
        **kwargs,
    )


def test_fixture_is_sensitive_and_stitched():
    events = run_detector(fixture_tracks(), ZONE, baseline_cfg())
    assert [e["severity"] for e in events] == ["HIGH", "LOW"]
    assert events[1]["participant_b_track_ids"] == [4, 9]


def test_identical_setting_gives_identical_result_and_all_retained():
    first, second = compare(1.75), compare(1.75)
    assert comparison_json(first) == comparison_json(second)
    assert first["parameter"]["identical_setting"] is True
    assert first["settings"]["differing_keys"] == []
    assert first["counts"] == {
        **first["counts"],
        "baseline_episodes": 2, "changed_episodes": 2, "retained": 2, "removed": 0, "added": 0,
    }
    assert first["provenance"]["supplied_events_match_baseline_rerun"] is True


def test_stricter_value_removes_only_the_long_gap_episode():
    result = compare(1.25)
    assert result["parameter"]["baseline_value"] == 1.75
    assert result["parameter"]["changed_value"] == 1.25
    assert result["settings"]["differing_keys"] == [PARAMETER]
    assert (result["counts"]["retained"], result["counts"]["removed"], result["counts"]["added"]) == (1, 1, 0)
    removed = result["episodes"]["removed"][0]["baseline"]
    assert removed["participant_a_track_ids"] == [3]
    assert removed["participant_b_track_ids"] == [4, 9]
    assert removed["start_timestamp_seconds"] == pytest.approx(6.5)
    assert removed["investigation_frame_index"] == 130  # start_frame_index of the episode
    assert removed["investigation_track_ids"] == [3, 9, 4]  # current ID, then stitched IDs
    kept = result["episodes"]["retained"][0]
    assert kept["baseline"]["participant_a_track_ids"] == [1]
    assert kept["severity_changed"] is False


def test_looser_value_from_strict_baseline_reports_added_episode():
    cfg = {**baseline_cfg(), PARAMETER: 1.25}
    result = compare(1.75, cfg=cfg)
    assert (result["counts"]["retained"], result["counts"]["removed"], result["counts"]["added"]) == (1, 0, 1)
    assert result["episodes"]["added"][0]["changed"]["participant_b_track_ids"] == [4, 9]


def test_other_settings_stay_fixed_and_inputs_are_not_mutated():
    tracks, cfg = fixture_tracks(), baseline_cfg()
    events = run_detector(tracks, ZONE, cfg)
    snapshot = copy.deepcopy((tracks, events, cfg))
    result = compare(1.25, tracks=tracks, events=events, cfg=cfg)
    assert (tracks, events, cfg) == snapshot
    base, changed = result["settings"]["baseline"], result["settings"]["changed"]
    assert {k: v for k, v in base.items() if k != PARAMETER} == {
        k: v for k, v in changed.items() if k != PARAMETER
    }
    assert base == json.loads(json.dumps(cfg))


def test_detector_receives_copies_with_only_the_parameter_changed():
    seen = []

    def spy(tracks, zone, config):
        seen.append(config)
        config["high_time_gap_seconds"] = 99  # mutation must not leak back
        tracks.clear()
        return []

    cfg = baseline_cfg()
    result = compare(2.0, cfg=cfg, events=[], detector=spy)
    assert cfg == baseline_cfg()
    assert seen[0][PARAMETER] == 1.75 and seen[1][PARAMETER] == 2.0
    assert result["counts"]["baseline_episodes"] == result["counts"]["changed_episodes"] == 0


def test_episode_matching_ignores_sequential_ids_and_uses_stitched_participants():
    base = [
        {"event_id": "conflict-001", "participant_a_track_id": 3, "participant_b_track_id": 4,
         "participant_b_track_ids": [4, 9], "first_alert_timestamp_seconds": 6.0,
         "end_timestamp_seconds": 7.0, "severity": "LOW"},
    ]
    # Renumbered, reversed sides, and participant B observed under stitched ID 9.
    changed = [
        {"event_id": "conflict-007", "participant_a_track_id": 9, "participant_a_track_ids": [9],
         "participant_b_track_id": 3, "first_alert_timestamp_seconds": 6.5,
         "end_timestamp_seconds": 6.8, "severity": "LOW"},
        {"event_id": "conflict-001", "participant_a_track_id": 1, "participant_b_track_id": 2,
         "first_alert_timestamp_seconds": 6.0, "end_timestamp_seconds": 7.0, "severity": "LOW"},
    ]
    result = match_episodes(base, changed)
    assert len(result["retained"]) == 1
    assert result["retained"][0]["changed"]["event_id"] == "conflict-007"
    assert [row["changed"]["event_id"] for row in result["added"]] == ["conflict-001"]


def test_same_pair_without_temporal_overlap_is_removed_plus_added():
    base = [{"event_id": "x", "participant_a_track_id": 1, "participant_b_track_id": 2,
             "first_alert_timestamp_seconds": 1.0, "end_timestamp_seconds": 2.0}]
    changed = [{"event_id": "x", "participant_a_track_id": 1, "participant_b_track_id": 2,
                "first_alert_timestamp_seconds": 5.0, "end_timestamp_seconds": 6.0}]
    result = match_episodes(base, changed)
    assert (len(result["retained"]), len(result["removed"]), len(result["added"])) == (0, 1, 1)


def test_merged_episode_matches_one_and_flags_overlap_for_the_other():
    pair = {"participant_a_track_id": 1, "participant_b_track_id": 2}
    base = [
        {**pair, "event_id": "conflict-001", "first_alert_timestamp_seconds": 1.0, "end_timestamp_seconds": 2.0},
        {**pair, "event_id": "conflict-002", "first_alert_timestamp_seconds": 2.5, "end_timestamp_seconds": 4.0},
    ]
    changed = [{**pair, "event_id": "conflict-001", "first_alert_timestamp_seconds": 1.0, "end_timestamp_seconds": 4.0}]
    result = match_episodes(base, changed)
    assert result["retained"][0]["baseline"]["event_id"] == "conflict-002"  # larger overlap
    assert result["removed"][0]["overlaps_changed_event_ids"] == ["conflict-001"]
    assert same_participants(base[0], changed[0])


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"high_time_gap_seconds": 1.2, "medium_time_gap_seconds": 1.0}, "HIGH ≤ MEDIUM ≤ LOW"),
        ({PARAMETER: float("nan")}, "finite"),
        ({PARAMETER: "fast"}, "finite"),
        ({"high_time_gap_seconds": 0}, "greater than 0"),
        ({PARAMETER: 5.0}, "between"),
    ],
)
def test_invalid_baseline_config_is_rejected(overrides, fragment):
    cfg = {**baseline_cfg(), **overrides}
    assert any(fragment in problem for problem in validate_threshold_config(cfg))
    with pytest.raises(ComparisonError):
        compare(1.75, cfg=cfg, events=[])


def test_missing_threshold_and_non_dict_config_are_rejected():
    cfg = baseline_cfg()
    del cfg["medium_time_gap_seconds"]
    assert validate_threshold_config(cfg)
    assert validate_threshold_config(None) == ["Detector settings must be a dictionary."]


@pytest.mark.parametrize("value", [0.9, 3.5, float("inf"), None, "1.5"])
def test_invalid_changed_values_are_rejected(value):
    # 0.9 < MEDIUM (1.0) would break ordering; "1.5" is accepted as a number.
    if value == "1.5":
        assert build_changed_config(baseline_cfg(), value)[PARAMETER] == 1.5
        return
    with pytest.raises(ComparisonError):
        build_changed_config(baseline_cfg(), value)


def test_zone_resolution_and_errors():
    assert resolve_zone([], FRAME) == (ZONE, False)
    assert resolve_zone([[1, 2], [3, 4], [5, 7]], None)[1] is True
    with pytest.raises(ComparisonError):
        resolve_zone([], None)
    with pytest.raises(ComparisonError):
        resolve_zone([[0, 0], [1, float("nan")], [2, 2]], FRAME)


def test_detector_exception_propagates():
    def broken(*_args):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        compare(1.25, events=[], detector=broken)


def test_supplied_events_mismatch_is_reported():
    result = compare(1.25, events=[])
    assert result["provenance"]["supplied_events_match_baseline_rerun"] is False


def test_export_is_deterministic_numeric_safe_and_records_provenance():
    tracks = fixture_tracks()
    tracks[0]["confidence"] = np.float32(0.9)
    result = compare(1.25, tracks=tracks)
    payload = comparison_json(result)
    assert payload == comparison_json(compare(1.25, tracks=tracks))
    text = payload.decode()
    assert "NaN" not in text and "Infinity" not in text
    parsed = json.loads(payload)
    assert parsed["provenance"]["re_inference"] is False
    assert parsed["provenance"]["track_rows"] == len(tracks)
    assert parsed["provenance"]["synthetic"] is False
    assert parsed["settings"]["baseline_sha256"] != parsed["settings"]["changed_sha256"]


def test_synthetic_demo_export_is_labeled_and_honestly_unchanged():
    tracks = demo.synthetic_tracks()
    zone = [[0, 0], [demo.WIDTH, 0], [demo.WIDTH, demo.HEIGHT], [0, demo.HEIGHT]]
    cfg = {**DEFAULT_CONFLICT_CONFIG, "zone_is_user_defined": False}
    result = compare_threshold(
        tracks=tracks, events=run_detector(tracks, zone, cfg), cfg=cfg, zone_polygon=[],
        frame_size=(demo.WIDTH, demo.HEIGHT), data_source=demo.DEMO_DATA_SOURCE,
        video_id=demo.DEMO_VIDEO_ID, changed_value=1.25,
    )
    parsed = json.loads(comparison_json(result))
    assert parsed["provenance"]["synthetic"] is True
    assert "SYNTHETIC" in parsed["provenance"]["label"]
    assert "not a safety rating" in parsed["disclaimer"]
    # The scripted demo gaps are all far below 1.25 s, so nothing is removed.
    assert (parsed["counts"]["retained"], parsed["counts"]["removed"], parsed["counts"]["added"]) == (3, 0, 0)
    assert parsed["provenance"]["supplied_events_match_baseline_rerun"] is True


def test_rerun_matches_direct_detector_call():
    tracks = fixture_tracks()
    direct = detect_conflicts(tracks, ZONE, baseline_cfg())
    rerun = run_detector(tracks, ZONE, baseline_cfg())
    assert [e["event_id"] for e in direct] == [e["event_id"] for e in rerun]
    assert [e["start_timestamp_seconds"] for e in direct] == [e["start_timestamp_seconds"] for e in rerun]
