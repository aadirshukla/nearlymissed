"""Presenter Mode: state navigation, read-only evidence and honest status."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

import nearmiss.store as store_module
import nearmiss.video as video_module
from nearmiss import demo, motion, presenter
from nearmiss.config import DEFAULT_CONFLICT_CONFIG
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG
from nearmiss.store import list_notifications, list_reviews, review_incident


ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(video_module, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(store_module, "DEFAULT_DATABASE_PATH", tmp_path / "data" / "nearmiss.db")
    return tmp_path


def title(at: AppTest) -> str:
    return next(str(m.value) for m in at.markdown if "<h1 class=\"nm-page-title\">" in str(m.value))


def page_text(at: AppTest) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def downloads(at: AppTest) -> dict[str, object]:
    return {element.proto.label: element for element in at.get("download_button")}


# ------------------------------------------------------------------ state


def test_state_helpers_clamp_and_return_to_the_starting_page():
    state: dict = {}
    presenter.enter(state, return_page="Incidents", now=100.0)
    assert presenter.is_active(state) and presenter.current_step(state) == 0
    presenter.step_by(state, -1)
    assert presenter.current_step(state) == 0
    for _ in range(10):
        presenter.step_by(state, 1)
    assert presenter.current_step(state) == len(presenter.STEPS) - 1
    presenter.go_to(state, 2)
    assert presenter.current_step(state) == 2
    state[presenter.STEP] = "garbage"
    assert presenter.current_step(state) == 0
    presenter.leave(state)
    assert not presenter.is_active(state) and state["_next_page"] == "Incidents"


def test_stop_exits_without_overriding_the_sidebar_choice():
    state: dict = {}
    presenter.enter(state, return_page="Analysis")
    presenter.stop(state)
    assert not presenter.is_active(state) and "_next_page" not in state
    # Leaving when not presenting is a no-op rather than a redirect.
    presenter.leave(state)
    assert "_next_page" not in state


def test_open_in_workspace_uses_the_existing_state_contracts():
    state = {"investigation_v_types": ["x"], "investigation_v_classes": ["y"]}
    presenter.enter(state)
    presenter.open_in_workspace(state, "Investigation", video_id="v", frame_index=142, track_ids=[3, 4])
    assert state["investigation_v_frame"] == 142 and state["investigation_v_tracks"] == [3, 4]
    assert "investigation_v_types" not in state and "investigation_v_classes" not in state
    assert state["_next_page"] == "Investigation" and not presenter.is_active(state)
    presenter.enter(state)
    presenter.open_in_workspace(state, "Incidents", video_id="v", incident_id="incident-1")
    assert state["selected_incident_v"] == "incident-1" and state["_next_page"] == "Incidents"


# ------------------------------------------------------------------ content


def test_deck_presents_the_same_evidence_as_the_story():
    result = motion.recompute_demo(DEFAULT_CONFLICT_CONFIG, DEFAULT_COLLISION_CONFIG)
    deck = presenter.build_deck(
        events=result["events"], incidents=result["incidents"], conflict_config=result["config"], fps=demo.FPS
    )
    story = motion.demo_story(DEFAULT_CONFLICT_CONFIG, DEFAULT_COLLISION_CONFIG)
    assert deck["event"]["event_id"] == story["event"]["event_id"]
    assert deck["incident"]["incident_id"] == story["incident"]["incident_id"]
    assert deck["alert_frame"] == deck["event"]["start_frame_index"] == 142
    assert deck["contact_frame"] == deck["incident"]["frame_index"]
    assert set(deck["participants"]) == {3, 4}
    # The warning image draws stored rows at the measurement frame, where the
    # projected paths start, so the dashed lines begin at the boxes.
    assert deck["measure_frame"] == deck["event"]["frame_index"] == 140
    rows = {r["track_id"]: r["bbox"] for r in result["tracks"] if r["frame_index"] == deck["measure_frame"]}
    for side in ("a", "b"):
        x1, _y1, x2, y2 = rows[deck["event"][f"participant_{side}_track_id"]]
        assert ((x1 + x2) / 2, y2) == pytest.approx(tuple(deck["event"][f"participant_{side}_position"]), abs=0.05)
    empty = presenter.build_deck(events=[], incidents=[], conflict_config={}, fps=20.0)
    assert empty["event"] is None and empty["incident"] is None


def test_evidence_status_separates_verified_behavior_from_unmeasured_accuracy():
    status = presenter.evidence_status(
        provenance={"data_source": "synthetic_demo"}, events=[{}] * 3, incidents=[{}]
    )
    verified, unmeasured = " ".join(status["verified"]), " ".join(status["not_measured"])
    assert "recomputed 3 warning(s) and 1 suspected incident(s)" in verified
    assert "Synthetic regression" in verified and "not real-world accuracy" in verified
    assert "accuracy on real footage" in unmeasured and "no emergency-service connection" in unmeasured
    # A fixed test count is not a live metric.
    assert "170" not in verified + unmeasured and "passed" not in verified + unmeasured
    uploaded = presenter.evidence_status(provenance={"data_source": "uploaded_video"}, events=[], incidents=[])
    assert not any("Synthetic" in line for line in uploaded["verified"])


def test_projection_overlay_draws_on_a_copy():
    frame = np.zeros((60, 100, 3), dtype=np.uint8)
    event = {
        "participant_a_position": [5, 30], "participant_a_predicted_end": [95, 30],
        "participant_b_position": [50, 55], "participant_b_predicted_end": [50, 5],
        "conflict_point": [50, 30], "conflict_region_radius_pixels": 8,
    }
    drawn = presenter.draw_projection(frame, event)
    assert frame.sum() == 0 and drawn.sum() > 0
    assert presenter.draw_projection(frame, {}).sum() == 0  # missing geometry draws nothing


def test_presenter_module_cannot_record_reviews_or_dispatch():
    tree = ast.parse((ROOT / "nearmiss" / "presenter.py").read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    for forbidden in ("review_incident", "acknowledge_notification", "reset_demo_reviews", "delete_video_records"):
        assert forbidden not in names | imported
    assert not any(isinstance(n, ast.ImportFrom) and n.module == "nearmiss.store" for n in ast.walk(tree))


# ------------------------------------------------------------------ app


def test_presenter_walkthrough_is_read_only_and_keyboard_driven(isolated):
    real = {"incident_id": "incident-real", "source_video_id": "c" * 64, "timestamp_seconds": 2.0}
    review_incident(real, "Confirmed Incident", "CAM-REAL")

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="presenter_open_sidebar").click().run()
    assert not at.exception, at.exception
    assert at.session_state[presenter.ACTIVE] is True
    assert demo.is_demo_video_id(at.session_state["active_video"]["video_hash"])
    assert "SYNTHETIC DEMO" in "\n".join(str(m.value) for m in at.markdown)

    back, nxt = at.button(key="presenter_back"), at.button(key="presenter_next")
    assert back.proto.shortcut.lower() == "left" and nxt.proto.shortcut.lower() == "right"
    assert back.disabled and not nxt.disabled
    clocks = [e for e in at.get("bidi_component") if e.proto.component_name == "nearmiss_presenter_clock"]
    assert len(clocks) == 1 and "Back and Next still work" in clocks[0].proto.html_content

    expected = ["The warning", "Source frame", "Incident review", "Street Lab", "Exported brief"]
    for index, label in enumerate(expected):
        assert f"{index + 1}. {label}" in title(at)
        if label == "The warning":
            text = page_text(at)
            assert "Paths measured: 00:07.0 (frame 140)" in text
            assert "First warning: 00:07.1 (frame 142)" in text
        if label == "Incident review":
            assert "**Operator review:** Not reviewed" in page_text(at)
            assert not [m for m in at.metric if m.label == "Operator review"]
        if index < len(expected) - 1:
            at.button(key="presenter_next").click().run()
            assert not at.exception, at.exception
    assert at.button(key="presenter_next").disabled

    files = downloads(at)
    assert "Download evidence brief (Markdown)" in files
    assert "Download community review brief (Markdown)" in files

    at.button(key="presenter_back").click().run()
    assert "4. Street Lab" in title(at)

    # Presenting recorded nothing anywhere.
    assert list_reviews(demo.DEMO_VIDEO_ID) == []
    assert list_notifications(demo.DEMO_VIDEO_ID) == []
    assert len(list_reviews("c" * 64)) == 1

    at.button(key="presenter_return").click().run()
    assert not at.exception, at.exception
    assert presenter.ACTIVE not in at.session_state
    assert at.session_state["navigation"] == "Analysis"


def test_presenter_shows_saved_review_without_changing_it(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    at.radio(key="navigation").set_value("Incidents").run()
    next(b for b in at.button if str(b.key or "").startswith("confirm_")).click().run()
    before_reviews = list_reviews(demo.DEMO_VIDEO_ID)
    before_notes = list_notifications(demo.DEMO_VIDEO_ID)
    assert before_notes and before_notes[0]["status"] == "New"

    at.button(key="presenter_open_sidebar").click().run()
    for _ in range(2):
        at.button(key="presenter_next").click().run()
    # Full status words, in wrapping text rather than truncating metric columns.
    assert "**Operator review:** Confirmed Incident" in page_text(at)
    assert "**Simulated dispatch:** New" in page_text(at)
    for _ in range(2):
        at.button(key="presenter_next").click().run()
    assert list_reviews(demo.DEMO_VIDEO_ID) == before_reviews
    assert list_notifications(demo.DEMO_VIDEO_ID) == before_notes

    # Picking a page in the sidebar leaves presenting and opens that page.
    at.radio(key="navigation").set_value("Dispatch").run()
    assert not at.exception, at.exception
    assert presenter.ACTIVE not in at.session_state
    assert at.session_state["navigation"] == "Dispatch"
    assert next(m.value for m in at.metric if m.label == "New") == "1"


def test_presenter_step_opens_the_matching_workspace_page(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="presenter_open_story").click().run()
    at.button(key="presenter_next").click().run()
    at.button(key="presenter_open_source").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Investigation"
    assert at.session_state[f"investigation_{demo.DEMO_VIDEO_ID}_frame"] == 142
    assert presenter.ACTIVE not in at.session_state


def test_library_threshold_box_is_collapsed_until_opened(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    at.radio(key="navigation").set_value("Library").run()
    assert not at.exception, at.exception
    assert any(e.label == "Explore one threshold" for e in at.expander)
    run_key = f"comparison_{demo.DEMO_VIDEO_ID}_run"
    assert not any(b.key == run_key for b in at.button)

    at.session_state["library_threshold"] = True
    at.run()
    assert not at.exception, at.exception
    assert any(b.key == run_key for b in at.button)
    assert "SYNTHETIC DEMO" in "\n".join(str(w.value) for w in at.warning)


def test_library_without_footage_has_no_threshold_box(isolated):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.radio(key="navigation").set_value("Library").run()
    assert not at.exception, at.exception
    assert not any(e.label == "Explore one threshold" for e in at.expander)


def _upload(isolated, *, analyzed: bool) -> dict:
    import json
    from dataclasses import asdict

    import cv2

    from nearmiss.config import TrackingConfig
    from nearmiss.video import _artifact_paths, inspect_video, save_upload

    raw = isolated / "upload.mp4"
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (100, 100))
    for _ in range(16):
        writer.write(np.full((100, 100, 3), 40, dtype=np.uint8))
    writer.release()
    video_hash, source_path = save_upload(raw.read_bytes(), "intersection.mp4")
    if analyzed:
        from test_incident_workflow import collision_tracks

        metadata, _ = inspect_video(source_path)
        artifacts = _artifact_paths(video_hash, source_path, TrackingConfig(), metadata)
        artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
        artifacts.tracks_path.write_text(json.dumps(collision_tracks()), encoding="utf-8")
        artifacts.metadata_path.write_text(json.dumps(asdict(metadata)), encoding="utf-8")
    return {"name": "intersection.mp4", "video_hash": video_hash, "source_path": str(source_path)}


def test_presenter_on_uploaded_footage_is_labeled_uploaded(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["active_video"] = _upload(isolated, analyzed=True)
    at.session_state["navigation"] = "Analysis"
    at.run()
    at.button(key="presenter_open_sidebar").click().run()
    assert not at.exception, at.exception
    text = "\n".join(str(m.value) for m in at.markdown)
    assert "UPLOADED FOOTAGE" in text and "SYNTHETIC DEMO" not in text
    assert "Synthetic regression" not in text
    assert "accuracy on real footage" in text
    assert not demo.is_demo_video_id(at.session_state["active_video"]["video_hash"])


def test_presenter_on_unanalyzed_upload_explains_and_returns(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["active_video"] = _upload(isolated, analyzed=False)
    at.session_state["navigation"] = "Incidents"
    at.run()
    at.button(key="presenter_open_sidebar").click().run()
    assert not at.exception, at.exception
    assert "has not been analyzed" in "\n".join(str(item.value) for item in at.info)
    at.button(key="presenter_return_unavailable").click().run()
    assert presenter.ACTIVE not in at.session_state
    assert at.session_state["navigation"] == "Incidents"
