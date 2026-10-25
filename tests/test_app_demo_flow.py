"""Streamlit AppTest walk-through of the guided synthetic demonstration.

Cache and SQLite paths are redirected to a temporary directory, so this never
touches the operator's real reviews or processed footage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import nearmiss.store as store_module
import nearmiss.video as video_module
from nearmiss import demo
from nearmiss.store import list_notifications, list_reviews, review_incident


APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(video_module, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(store_module, "DEFAULT_DATABASE_PATH", tmp_path / "data" / "nearmiss.db")
    return tmp_path


def text_of(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.markdown) + "\n".join(
        str(element.value) for element in at.caption
    )


def button(at: AppTest, prefix: str):
    matches = [item for item in at.button if str(item.key or "").startswith(prefix)]
    assert matches, f"no button with key prefix {prefix!r}"
    return matches[0]


def metric(at: AppTest, label: str) -> str:
    return next(item.value for item in at.metric if item.label == label)


def go(at: AppTest, page: str) -> None:
    at.radio(key="navigation").set_value(page).run()
    assert not at.exception, at.exception


def test_guided_demo_end_to_end(isolated):
    # A real-footage review that must survive a demo reset.
    real = {"incident_id": "incident-real", "source_video_id": "c" * 64, "timestamp_seconds": 2.0}
    review_incident(real, "Confirmed Incident", "CAM-REAL")

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert any(item.key == "start_demo" for item in at.button)

    at.button(key="start_demo").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Analysis"
    assert demo.is_demo_video_id(at.session_state["active_video"]["video_hash"])
    assert "SYNTHETIC DEMO" in text_of(at)
    assert metric(at, "Potential conflicts") == "3"
    assert metric(at, "Suspected incidents") == "1"
    assert "Arrival gap" in text_of(at) or "headway" in text_of(at)

    go(at, "Incidents")
    assert metric(at, "Needs review") == "1"
    assert "before first contact" in text_of(at)
    button(at, "confirm_").click().run()
    assert not at.exception, at.exception
    assert metric(at, "Confirmed") == "1"

    go(at, "Dispatch")
    assert metric(at, "New") == "1"
    button(at, "ack_").click().run()
    assert metric(at, "Acknowledged") == "1"

    # Reversing the decision withdraws the simulated notification everywhere.
    go(at, "Incidents")
    button(at, "dismiss_").click().run()
    go(at, "Dispatch")
    assert metric(at, "Withdrawn") == "1"
    assert metric(at, "Acknowledged") == "0"
    assert not [item for item in at.button if str(item.key or "").startswith("ack_")]
    stored = list_notifications(demo.DEMO_VIDEO_ID)
    assert stored[0]["status"] == "Withdrawn"
    assert stored[0]["summary"]["data_source"] == "synthetic_demo"

    go(at, "Street Lab")
    assert metric(at, "Warnings") == "3"
    assert "review hypothesis" in "\n".join(str(item.value) for item in at.warning)
    current = next(item for item in at.number_input if item.label.startswith("Current crossing"))
    current.set_value(80.0).run()
    assert not at.exception, at.exception

    button(at, "reset_demo_").click().run()
    assert list_reviews(demo.DEMO_VIDEO_ID) == []
    assert list_notifications(demo.DEMO_VIDEO_ID) == []
    assert len(list_reviews("c" * 64)) == 1
    assert len(list_notifications("c" * 64)) == 1

    button(at, "leave_demo_").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Overview"
    assert "active_video" not in at.session_state


def test_pages_without_footage_offer_the_demo(isolated):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    go(at, "Street Lab")
    assert any(item.key == "gate_demo" for item in at.button)


def test_uploaded_footage_path_is_unchanged_and_not_labeled_synthetic(isolated):
    import json
    from dataclasses import asdict

    import cv2
    import numpy as np

    from nearmiss.config import TrackingConfig
    from nearmiss.video import _artifact_paths, inspect_video, save_upload

    raw = isolated / "upload.mp4"
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (100, 100))
    for _ in range(16):
        writer.write(np.full((100, 100, 3), 40, dtype=np.uint8))
    writer.release()
    video_hash, source_path = save_upload(raw.read_bytes(), "intersection.mp4")
    assert not demo.is_demo_video_id(video_hash)
    metadata, _ = inspect_video(source_path)
    artifacts = _artifact_paths(video_hash, source_path, TrackingConfig(), metadata)
    artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
    from test_incident_workflow import collision_tracks

    artifacts.tracks_path.write_text(json.dumps(collision_tracks()), encoding="utf-8")
    artifacts.metadata_path.write_text(json.dumps(asdict(metadata)), encoding="utf-8")

    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["active_video"] = {
        "name": "intersection.mp4", "video_hash": video_hash, "source_path": str(source_path),
    }
    at.session_state["navigation"] = "Analysis"
    at.run()
    assert not at.exception, at.exception
    assert metric(at, "Suspected incidents") == "1"
    assert "SYNTHETIC DEMO" not in text_of(at)
    assert "UPLOADED FOOTAGE" in text_of(at)
    assert not [item for item in at.button if str(item.key or "").startswith("reset_demo_")]
    go(at, "Street Lab")
    assert "one uploaded clip" in text_of(at)


def test_integrated_tool_pages_render_for_the_demo(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    for page in ("Investigation", "Explain & Share", "Library", "Overview"):
        go(at, page)
        assert "SYNTHETIC DEMO" in text_of(at) or page == "Library"
    go(at, "Incidents")
    button(at, "investigate_").click().run()
    assert not at.exception, at.exception
    assert at.session_state["navigation"] == "Investigation"
    frame_key = f"investigation_{demo.DEMO_VIDEO_ID}_frame"
    assert at.session_state[frame_key] > 0


def test_safety_report_download_is_withheld_after_threshold_change(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    at.button(key=f"report_{demo.DEMO_VIDEO_ID}").click().run()
    assert not at.exception, at.exception
    labels = [element.proto.label for element in at.get("download_button")]
    assert "Download safety report" in labels
    gap = next(item for item in at.slider if item.label == "High-priority arrival gap")
    gap.set_value(0.30).run()
    assert not at.exception, at.exception
    labels = [element.proto.label for element in at.get("download_button")]
    assert "Download safety report" not in labels
    assert "Generate it again" in text_of(at)


def save_buttons(at: AppTest) -> list:
    return [item for item in at.button if str(item.key or "").endswith("_save_current")]


def test_library_never_offers_a_snapshot_built_with_older_settings(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    built = at.session_state["history_current_snapshot"]
    assert built["config"]["conflict_config"]["high_time_gap_seconds"] == pytest.approx(0.50)

    go(at, "Library")
    assert save_buttons(at), "current demo run should be offered for saving"

    gap = next(item for item in at.slider if item.label == "High-priority arrival gap")
    gap.set_value(0.25).run()
    assert not at.exception, at.exception
    assert save_buttons(at) == []
    assert "recompute before saving" in "\n".join(str(item.value) for item in at.info)

    # Visiting Analysis recomputes with the new value; the Library offers it again.
    go(at, "Analysis")
    snapshot = at.session_state["history_current_snapshot"]
    assert snapshot["config"]["conflict_config"]["high_time_gap_seconds"] == pytest.approx(0.25)
    go(at, "Library")
    assert save_buttons(at)

    # Reset clears the current snapshot entirely.
    at.session_state["history_current_fingerprint"] = "stale"
    at.run()
    assert save_buttons(at) == []


def test_jump_to_evidence_selects_its_participants_over_unrelated_tracks(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.button(key="start_demo").click().run()
    go(at, "Investigation")
    prefix = f"investigation_{demo.DEMO_VIDEO_ID}"
    tracks = at.multiselect(key=f"{prefix}_tracks")
    types = at.multiselect(key=f"{prefix}_types")
    choice = at.selectbox(key=f"{prefix}_jump_choice")
    # Pick the first prediction event and narrow selection away from it.
    target_index = next(
        index for index, label in enumerate(choice.options) if "Prediction" in str(label)
    )
    choice.set_value(target_index).run()
    label = str(choice.options[target_index])
    participants = {
        int(part.strip().lstrip("#")) for part in label.split("·")[-1].split(",")
    }
    unrelated = [value for value in tracks.options if int(str(value).split()[0].lstrip("#")) not in participants]
    assert unrelated
    tracks.set_value([int(str(unrelated[0]).split()[0].lstrip("#"))]).run()
    other_types = [value for value in types.options if value != "vehicle"]
    if other_types:
        at.multiselect(key=f"{prefix}_types").set_value(other_types).run()
    assert not at.exception, at.exception

    button(at, f"{prefix}_jump").click().run()
    assert not at.exception, at.exception
    selected = set(at.session_state[f"{prefix}_tracks"])
    assert selected and selected <= participants
    assert "vehicle" in at.session_state[f"{prefix}_types"]
    shown = at.dataframe[-1].value
    assert "ID" in shown.columns
    assert label.split("·")[1].split()[-1] in set(shown["ID"])


def page_html(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.markdown)


def test_photo_landing_keeps_demo_upload_and_explainer_then_drops_photo(isolated):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    html = page_html(at)
    assert "See the moments" in html and "before impact." in html
    assert "background-attachment:fixed" in html  # collaborator's full-photo shell
    assert "illustrative context only" in html
    assert "How a warning is earned" in html
    assert at.button(key="start_demo").proto.type == "primary"
    assert len(at.get("file_uploader")) == 1

    at.button(key="start_demo").click().run()
    go(at, "Overview")
    # With footage active the evidence tables stay on the dark interface.
    assert "background-attachment:fixed" not in page_html(at)
    assert "SYNTHETIC DEMO" in text_of(at)
