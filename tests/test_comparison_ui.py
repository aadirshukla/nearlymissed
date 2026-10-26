"""Streamlit AppTest coverage for the threshold comparison page."""

from __future__ import annotations

import copy
import json

from streamlit.testing.v1 import AppTest

from nearmiss import demo
from nearmiss.comparison import run_detector
from nearmiss.config import DEFAULT_CONFLICT_CONFIG


FPS = 20.0
VIDEO_ID = "b" * 64
ZONE = [[0.0, 0.0], [800.0, 0.0], [800.0, 600.0], [0.0, 600.0]]


def _row(track_id, frame, cx, cy):
    return {
        "track_id": track_id, "class_id": 2, "class_name": "car", "object_type": "vehicle",
        "frame_index": frame, "timestamp_seconds": round(frame / FPS, 4),
        "bbox": [cx - 20, cy - 20, cx + 20, cy], "center": [cx, cy - 10], "confidence": 0.9,
    }


def _crossing(gap, a_id, b_id, start_frame=0, x=300.0):
    rows = []
    for i in range(int(4.0 * FPS)):
        t = i / FPS
        rows.append(_row(a_id, start_frame + i, x - 200 + 100 * t, 200))
        rows.append(_row(b_id, start_frame + i, x, 200 - 100 * (2 + gap) + 100 * t))
    return rows


def tracks():
    return _crossing(0.3, 1, 2) + _crossing(1.6, 3, 4, start_frame=100, x=600)


def cfg():
    return {**DEFAULT_CONFLICT_CONFIG, "zone_is_user_defined": False}


def page(**kwargs):
    from nearmiss.comparison_ui import render_comparison

    render_comparison(**kwargs)


def app(**overrides) -> AppTest:
    kwargs = {
        "tracks": tracks(), "cfg": cfg(), "zone_polygon": [], "frame_size": (800, 600),
        "data_source": "uploaded_video", "video_id": VIDEO_ID,
    }
    kwargs.update(overrides)
    if "events" not in kwargs:
        kwargs["events"] = run_detector(tracks(), ZONE, cfg())
    return AppTest.from_function(page, kwargs=kwargs, default_timeout=30)


def run_button(at: AppTest):
    return next(b for b in at.button if b.key == f"comparison_{VIDEO_ID}_run")


def metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def test_changed_value_shows_counts_and_jump_opens_investigation():
    at = app().run()
    assert not at.exception
    assert "not a safety rating" in at.info[0].value
    at.number_input(key=f"comparison_{VIDEO_ID}_value").set_value(1.25).run()
    run_button(at).click().run()
    assert not at.exception and not at.error
    values = metrics(at)
    assert (values["Baseline episodes"], values["Changed episodes"]) == ("2", "1")
    assert (values["Retained"], values["Removed"], values["Added"]) == ("1", "1", "0")
    jump = next(b for b in at.button if b.key == f"comparison_{VIDEO_ID}_removed_0")
    jump.click().run()
    state = at.session_state
    assert state[f"investigation_{VIDEO_ID}_frame"] == 130  # start_frame_index of the removed episode
    assert state[f"investigation_{VIDEO_ID}_tracks"] == [3, 4]
    assert state["_next_page"] == "Investigation"


def test_stale_result_is_hidden_after_value_changes():
    at = app().run()
    run_button(at).click().run()
    assert metrics(at)["Retained"] == "2"
    at.number_input(key=f"comparison_{VIDEO_ID}_value").set_value(2.0).run()
    assert "Retained" not in metrics(at)


def test_inputs_are_not_mutated_by_the_page():
    kwargs = {
        "tracks": tracks(), "events": run_detector(tracks(), ZONE, cfg()), "cfg": cfg(),
        "zone_polygon": [], "frame_size": (800, 600), "data_source": "uploaded_video",
        "video_id": VIDEO_ID,
    }
    snapshot = copy.deepcopy(kwargs)
    at = AppTest.from_function(page, kwargs=kwargs, default_timeout=30).run()
    at.number_input(key=f"comparison_{VIDEO_ID}_value").set_value(1.25).run()
    run_button(at).click().run()
    assert kwargs == snapshot


def test_invalid_config_shows_error_and_no_run_button():
    bad = {**cfg(), "high_time_gap_seconds": 1.5, "medium_time_gap_seconds": 1.0}
    at = app(cfg=bad).run()
    assert at.error and "HIGH ≤ MEDIUM ≤ LOW" in at.error[0].value
    assert not any(b.key == f"comparison_{VIDEO_ID}_run" for b in at.button)


def test_detector_error_is_visible(monkeypatch):
    import nearmiss.comparison as comparison

    def broken(*_args):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(comparison, "detect_conflicts", broken)
    at = app(events=[]).run()
    run_button(at).click().run()
    assert at.error and "detector exploded" in at.error[0].value
    assert "Retained" not in metrics(at)


def test_malformed_rows_surface_a_visible_error():
    at = app(tracks=[{"track_id": 1}], events=[]).run()
    run_button(at).click().run()
    assert at.error and "KeyError" in at.error[0].value


def test_zero_episodes_is_honest():
    # B reaches the crossing 3 s after A, beyond the 2 s look-ahead: no warnings at all.
    at = app(tracks=_crossing(3.0, 1, 2), events=[]).run()
    run_button(at).click().run()
    assert not at.error
    assert metrics(at)["Baseline episodes"] == "0"
    assert "not evidence that the scene is safe" in " ".join(i.value for i in at.info)


def test_missing_tracks_warns():
    at = app(tracks=[]).run()
    assert at.warning and "No stored track rows" in at.warning[0].value


def test_synthetic_demo_is_labeled():
    rows = demo.synthetic_tracks()
    zone = [[0, 0], [demo.WIDTH, 0], [demo.WIDTH, demo.HEIGHT], [0, demo.HEIGHT]]
    at = app(
        tracks=rows, events=run_detector(rows, zone, cfg()), frame_size=(demo.WIDTH, demo.HEIGHT),
        data_source=demo.DEMO_DATA_SOURCE,
    ).run()
    assert at.warning and "SYNTHETIC DEMO" in at.warning[0].value
    run_button(at).click().run()
    assert not at.error
    assert metrics(at)["Retained"] == "3"
