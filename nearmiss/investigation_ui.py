"""Streamlit Investigation workspace: step through original frames and stored tracks.

The page decodes real source frames with nearmiss.video.frame_at_timestamp and
overlays only stored track rows. It runs no detector and never edits reviews.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import pandas as pd
import streamlit as st

from nearmiss.events import format_timestamp
from nearmiss.investigation import (
    REVIEW_NOTE,
    SYNTHETIC_NOTE,
    build_investigation_export,
    clean_observations,
    draw_investigation_frame,
    evidence_focus,
    evidence_timeline,
    filter_participants,
    frame_index_for_timestamp,
    investigation_json,
    is_synthetic_source,
    metadata_fields,
    movement_summary,
    nearby_evidence,
    observations_at_frame,
    participant_catalog,
    timestamp_for_frame_index,
    track_trail,
)
from nearmiss.video import VideoError, frame_at_timestamp


DEFAULT_SELECTED_TRACKS = 4


@st.cache_data(show_spinner=False, max_entries=48)
def _decoded_frame(path: str, timestamp_seconds: float, modified_ns: int):
    # modified_ns keys the cache to the file version on disk.
    del modified_ns
    return frame_at_timestamp(Path(path), timestamp_seconds)


def _step(key: str, delta: int, last_frame: int) -> None:
    st.session_state[key] = min(max(0, int(st.session_state.get(key, 0)) + delta), last_frame)


def _jump(
    frame_key: str,
    choice_key: str,
    timeline: list[dict],
    fps: float,
    last_frame: int,
    catalog: list[dict],
    filter_keys: tuple[str, str, str],
):
    index = st.session_state.get(choice_key)
    if index is None or not 0 <= index < len(timeline):
        return
    target = frame_index_for_timestamp(timeline[index]["event_time_seconds"], fps, last_frame + 1)
    st.session_state[frame_key] = target
    # Select the evidence participants and widen filters so the nearby-evidence
    # panel cannot hide the record that was just jumped to.
    type_key, class_key, track_key = filter_keys
    focus = evidence_focus(
        catalog,
        timeline[index],
        object_types=st.session_state.get(type_key),
        class_names=st.session_state.get(class_key),
    )
    if not focus["track_ids"]:
        return
    if focus["object_types"] is not None:
        st.session_state[type_key] = focus["object_types"]
    if focus["class_names"] is not None:
        st.session_state[class_key] = focus["class_names"]
    st.session_state[track_key] = focus["track_ids"]


def _evidence_label(row: dict) -> str:
    kind = "Suspected incident" if row["evidence_kind"] == "suspected_incident" else "Prediction"
    ids = ", ".join(f"#{track_id}" for track_id in row["participant_track_ids"]) or "no IDs"
    return f"{format_timestamp(row['event_time_seconds'])} · {kind} {row['evidence_id']} · {ids}"


def _sanitize_choice(key: str, options: list) -> None:
    """Drop stale multiselect values that a changed filter no longer offers."""

    if key in st.session_state:
        st.session_state[key] = [value for value in st.session_state[key] if value in options]


def render_investigation_page(
    *,
    source_path: Path | str | None,
    metadata: Any,
    tracks: list[dict] | None,
    events: list[dict] | None,
    incidents: list[dict] | None,
    source_kind: str | None,
    video_id: str | None,
) -> None:
    """Render the frame-by-frame investigation workspace for one analyzed video."""

    rows = clean_observations(tracks)
    synthetic = is_synthetic_source(source_kind, rows)
    meta = metadata_fields(metadata)
    fps = float(meta["fps"])
    prefix = f"investigation_{video_id or 'video'}"

    st.subheader("Investigation")
    if synthetic:
        st.warning(SYNTHETIC_NOTE, icon="🧪")
    else:
        st.caption(
            "Source footage with tracker observations. Boxes are model output, not ground truth."
        )
    st.caption(REVIEW_NOTE)

    path = Path(source_path) if source_path else None
    has_source = path is not None and path.exists()
    frame_count = int(meta["frame_count"])
    if frame_count <= 0 and rows:
        frame_count = max(row["frame_index"] for row in rows) + 1
    if fps <= 0 or frame_count <= 0:
        st.info(
            "No frame timing is available for this source yet. Analyze a video or open "
            "the synthetic demonstration to investigate frames."
        )
        return
    last_frame = frame_count - 1

    frame_key = f"{prefix}_frame"
    st.session_state.setdefault(frame_key, 0)
    st.session_state[frame_key] = min(int(st.session_state[frame_key]), last_frame)

    type_key = f"{prefix}_types"
    class_key = f"{prefix}_classes"
    track_key = f"{prefix}_tracks"

    # Frame navigation --------------------------------------------------------
    timeline = evidence_timeline(events, incidents)
    if timeline:
        choice_key = f"{prefix}_jump_choice"
        jump_col, button_col = st.columns([5, 1], vertical_alignment="bottom")
        with jump_col:
            st.selectbox(
                "Jump to evidence",
                options=list(range(len(timeline))),
                format_func=lambda index: _evidence_label(timeline[index]),
                key=choice_key,
            )
        with button_col:
            st.button(
                "Go",
                key=f"{prefix}_jump",
                on_click=_jump,
                args=(
                    frame_key, choice_key, timeline, fps, last_frame,
                    participant_catalog(rows), (type_key, class_key, track_key),
                ),
                width="stretch",
            )

    back_col, slider_col, next_col = st.columns([1, 8, 1], vertical_alignment="bottom")
    with back_col:
        st.button("◀", key=f"{prefix}_back", on_click=_step, args=(frame_key, -1, last_frame),
                  help="Previous frame", width="stretch")
    with slider_col:
        st.slider(
            "Frame",
            min_value=0,
            max_value=max(last_frame, 1),
            key=frame_key,
            help="Frames are stepped at the source frame rate; time is frame ÷ fps.",
        )
    with next_col:
        st.button("▶", key=f"{prefix}_next", on_click=_step, args=(frame_key, 1, last_frame),
                  help="Next frame", width="stretch")
    frame_index = min(int(st.session_state[frame_key]), last_frame)
    timestamp = timestamp_for_frame_index(frame_index, fps)
    st.markdown(
        f"**Frame {frame_index:,} of {last_frame:,}** · t = {format_timestamp(timestamp)} "
        f"({timestamp:.3f} s at {fps:g} fps)"
    )

    # Participant filters -----------------------------------------------------
    catalog = participant_catalog(rows, frame_index=frame_index, events=events, incidents=incidents)
    if not catalog:
        st.info(
            "No track observations are stored for this source, so there is nothing to "
            "overlay. The original frame is shown unannotated."
        )
    type_options = sorted({item["object_type"] for item in catalog})
    _sanitize_choice(type_key, type_options)
    filter_cols = st.columns(2)
    with filter_cols[0]:
        types = st.multiselect(
            "Participant types",
            type_options,
            default=type_options if type_key not in st.session_state else None,
            key=type_key,
        )
    class_options = sorted(
        {item["class_name"] for item in filter_participants(catalog, object_types=types)}
    )
    _sanitize_choice(class_key, class_options)
    with filter_cols[1]:
        classes = st.multiselect(
            "Detector classes",
            class_options,
            default=class_options if class_key not in st.session_state else None,
            key=class_key,
        )
    candidates = filter_participants(catalog, object_types=types, class_names=classes)
    track_options = [item["track_id"] for item in candidates]
    by_id = {item["track_id"]: item for item in catalog}
    _sanitize_choice(track_key, track_options)
    default_ids = [
        item["track_id"]
        for item in candidates
        if item["visible_at_frame"] or item["evidence_count"]
    ][:DEFAULT_SELECTED_TRACKS]
    selected_ids = st.multiselect(
        "Tracks to inspect (ranked: visible now, named in evidence, most observed)",
        track_options,
        default=default_ids if track_key not in st.session_state else None,
        format_func=lambda track_id: (
            f"#{track_id} · {by_id[track_id]['class_name']} · "
            f"{by_id[track_id]['observation_count']} obs"
            + (" · in view" if by_id[track_id]["visible_at_frame"] else "")
        ),
        key=track_key,
    )

    option_cols = st.columns(3)
    with option_cols[0]:
        trail_seconds = st.slider(
            "Trail (s)", 0.0, 5.0, 1.0, 0.5, key=f"{prefix}_trail",
            help="Past observed positions only; gaps in tracking stay as gaps.",
        )
    with option_cols[1]:
        evidence_window = st.slider(
            "Evidence window (± s)", 0.5, 10.0, 2.0, 0.5, key=f"{prefix}_evidence_window"
        )
    with option_cols[2]:
        show_context = st.checkbox(
            "Outline other participants", value=True, key=f"{prefix}_context",
            help="Thin grey boxes for unselected tracks in the current filters.",
        )
    trail_frames = int(round(trail_seconds * fps))

    # Frame display -----------------------------------------------------------
    drawn_rows = observations_at_frame(
        rows,
        frame_index,
        track_ids=None if show_context else selected_ids,
        object_types=types,
        class_names=classes,
    )
    frame_decoded = False
    if not has_source:
        st.warning("The source video file is not available, so no frame can be shown.")
    else:
        try:
            frame = _decoded_frame(str(path), timestamp, path.stat().st_mtime_ns)
            frame_decoded = True
        except VideoError as exc:
            st.warning(f"Frame {frame_index} could not be decoded: {exc}")
        if frame_decoded:
            trails = {
                track_id: track_trail(rows, track_id, frame_index, trail_frames=trail_frames)
                for track_id in selected_ids
            }
            annotated = draw_investigation_frame(
                frame,
                drawn_rows,
                trails,
                selected_track_ids=selected_ids,
                track_types={track_id: by_id[track_id]["object_type"] for track_id in selected_ids},
            )
            st.image(
                cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB),
                width="stretch",
                caption=(
                    f"{'SYNTHETIC — ' if synthetic else ''}Original frame {frame_index} "
                    f"with stored observations only"
                ),
            )

    # Selected-track and evidence tables -------------------------------------
    if selected_ids:
        summaries = [
            movement_summary(rows, track_id, frame_index, fps=fps, window_frames=trail_frames)
            for track_id in selected_ids
        ]
        st.markdown("**Selected tracks** (image-space pixels; uncalibrated)")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Track": f"#{item['track_id']}",
                        "Class": item["class_name"],
                        "At this frame": (
                            "observed"
                            if item["observed_at_requested_frame"]
                            else f"not observed (nearest frame {item['nearest_observed_frame_index']})"
                        ),
                        "Rows in trail window": item["observations_in_window"],
                        "Missing frames": item["missing_frames_in_observed_span"],
                        "Path (px)": item["path_length_pixels"],
                        "Mean speed (px/s)": item["mean_speed_pixels_per_second"],
                        "Direction": item["direction"],
                    }
                    for item in summaries
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    elif catalog:
        st.caption("Select one or more tracks to see their movement and evidence.")

    evidence = nearby_evidence(
        events, incidents, timestamp, window_seconds=evidence_window,
        track_ids=selected_ids or None,
    )
    st.markdown(f"**Evidence within ±{evidence_window:g} s**")
    if evidence:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Kind": (
                            "Suspected incident"
                            if row["evidence_kind"] == "suspected_incident"
                            else "Prediction event"
                        ),
                        "ID": row["evidence_id"],
                        "Event time": format_timestamp(row["event_time_seconds"]),
                        "Offset (s)": row["offset_seconds"],
                        "Tracks": ", ".join(f"#{value}" for value in row["participant_track_ids"]),
                        "Severity": row.get("severity"),
                        "Human review": row.get("review_status", "—"),
                    }
                    for row in evidence
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No prediction events or suspected incidents in this window.")

    export = build_investigation_export(
        video_id=video_id,
        source_kind=source_kind,
        metadata=metadata,
        tracks=rows,
        events=events,
        incidents=incidents,
        frame_index=frame_index,
        selected_track_ids=selected_ids,
        object_types=types,
        class_names=classes,
        trail_frames=trail_frames,
        evidence_window_seconds=evidence_window,
        frame_decoded=frame_decoded,
    )
    st.download_button(
        "Download investigation JSON",
        data=investigation_json(export),
        file_name=(
            f"{'synthetic_' if synthetic else ''}investigation_{video_id or 'video'}"
            f"_frame{frame_index}.json"
        ),
        mime="application/json",
        key=f"{prefix}_download",
    )
