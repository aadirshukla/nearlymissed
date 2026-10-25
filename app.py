"""NearMiss Streamlit application."""

from __future__ import annotations

import json
from dataclasses import asdict

import cv2
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image, ImageDraw

from conflict_detector import detect_conflicts, diagnose_conflicts
from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.events import events_to_csv, format_timestamp, normalize_events
from nearmiss.geometry import enrich_tracks_with_zone, normalized_polygon
from nearmiss.report import generate_safety_report
from nearmiss.safety import (
    build_conflict_heatmap,
    deduplicate_events,
    diagnostics_to_csv,
    event_pair_key,
    events_with_review_labels,
    pipeline_stage_counts,
    safety_statistics,
    timeline_rows,
)
from nearmiss.video import (
    VideoError,
    analyze_video,
    cache_summary,
    cached_analysis,
    clear_analysis_cache,
    extract_event_clip,
    frame_at_timestamp,
    inspect_video,
    load_artifacts,
    render_annotated_video,
    save_upload,
    tracks_to_csv,
)

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
except ImportError:  # pragma: no cover - requirements include the component
    streamlit_image_coordinates = None


st.set_page_config(
    page_title="NearMiss · Safer streets through vision",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.session_state.setdefault("upload_generation", 0)

st.markdown(
    """
    <style>
    :root { --ink:#e8eefc; --muted:#94a3b8; --cyan:#38bdf8; --orange:#fb923c; }
    .stApp { background: radial-gradient(circle at 72% -10%, #172554 0, #090f1f 38%, #070b14 75%); }
    [data-testid="stSidebar"] { background: #0b1220; border-right: 1px solid #1e293b; }
    .nm-eyebrow { color:var(--cyan); letter-spacing:.16em; text-transform:uppercase;
      font-weight:700; font-size:.75rem; margin-bottom:.5rem; }
    .nm-title { font-size:clamp(2.4rem,6vw,5rem); line-height:.9; font-weight:800;
      letter-spacing:-.06em; margin:0 0 1rem; color:#f8fafc; }
    .nm-title span { color:var(--cyan); }
    .nm-subtitle { color:#a8b3c7; font-size:1.08rem; max-width:720px; line-height:1.65; }
    .nm-notice { border:1px solid #334155; border-left:3px solid var(--orange); border-radius:10px;
      padding:.8rem 1rem; background:#111827aa; color:#cbd5e1; font-size:.9rem; margin:1.2rem 0; }
    .nm-step { display:inline-flex; align-items:center; justify-content:center; width:1.7rem; height:1.7rem;
      background:#0c4a6e; color:#7dd3fc; border-radius:99px; font-weight:800; margin-right:.5rem; }
    [data-testid="stMetric"] { background:#101827cc; border:1px solid #243044; padding:1rem;
      border-radius:14px; }
    [data-testid="stFileUploaderDropzone"] { border-color:#334155; background:#0f172a; }
    .stButton>button, .stDownloadButton>button { border-radius:9px; font-weight:650; }
    div[data-testid="stStatusWidget"] { background:#0f172a; }
    </style>
    """,
    unsafe_allow_html=True,
)


def section_title(number: int, title: str) -> None:
    st.markdown(f'<h3><span class="nm-step">{number}</span>{title}</h3>', unsafe_allow_html=True)


def draw_zone_preview(frame_bgr, zone: list[list[float]], max_width: int = 900):
    """Return a resized PIL preview and its original/display scale factors."""

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    original = Image.fromarray(rgb)
    ratio = min(1.0, max_width / original.width)
    display_size = (max(1, int(original.width * ratio)), max(1, int(original.height * ratio)))
    preview = original.resize(display_size, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(preview, "RGBA")
    display_points = [(int(x * ratio), int(y * ratio)) for x, y in zone]
    if len(display_points) >= 3:
        draw.polygon(display_points, fill=(56, 189, 248, 35), outline=(56, 189, 248, 255), width=3)
    elif len(display_points) >= 2:
        draw.line(display_points, fill=(56, 189, 248, 255), width=3)
    for index, point in enumerate(display_points, start=1):
        x, y = point
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(251, 146, 60, 255), outline="white", width=2)
        draw.text((x + 10, y - 11), str(index), fill="white", stroke_width=2, stroke_fill=(0, 0, 0))
    return preview, ratio


def zone_picker(video_hash: str, first_frame) -> tuple[list[list[float]], list[list[float]]]:
    """Interactive polygon editor; returns (draft, applied) pixel-space zones."""

    draft_key = f"zone_draft_{video_hash}"
    applied_key = f"zone_applied_{video_hash}"
    last_click_key = f"zone_last_click_{video_hash}"
    st.session_state.setdefault(draft_key, [])
    st.session_state.setdefault(applied_key, [])
    st.session_state.setdefault(last_click_key, None)

    controls = st.columns([1, 1, 2.2])
    if controls[0].button("Undo point", key=f"undo_{video_hash}", use_container_width=True):
        if st.session_state[draft_key]:
            st.session_state[draft_key].pop()
    if controls[1].button("Clear", key=f"clear_{video_hash}", use_container_width=True):
        st.session_state[draft_key] = []
    can_apply = len(st.session_state[draft_key]) >= 3
    if controls[2].button(
        "Use this conflict zone",
        key=f"apply_{video_hash}",
        type="primary",
        disabled=not can_apply,
        use_container_width=True,
    ):
        st.session_state[applied_key] = [point[:] for point in st.session_state[draft_key]]
        st.toast("Conflict zone applied")

    preview, ratio = draw_zone_preview(first_frame, st.session_state[draft_key])
    if streamlit_image_coordinates is not None:
        click = streamlit_image_coordinates(preview, key=f"zone_image_{video_hash}")
        if click:
            signature = (int(click["x"]), int(click["y"]))
            if signature != st.session_state[last_click_key]:
                st.session_state[last_click_key] = signature
                st.session_state[draft_key].append(
                    [round(signature[0] / ratio, 2), round(signature[1] / ratio, 2)]
                )
                st.rerun()
    else:
        st.image(preview, caption="Preview (coordinate component unavailable)")
        st.warning("Install streamlit-image-coordinates to select the zone by clicking.")

    point_count = len(st.session_state[draft_key])
    if point_count < 3:
        st.caption(f"Click at least 3 corners in order · {point_count} selected")
    else:
        st.caption(f"{point_count} corners selected · apply the zone when its shape looks right")
    return st.session_state[draft_key], st.session_state[applied_key]


def progress_callback(progress_bar):
    def update(fraction: float, message: str) -> None:
        progress_bar.progress(max(0.0, min(float(fraction), 1.0)), text=message)

    return update


def json_default(value):
    """Make NumPy-like values from custom detectors safe for JSON export."""

    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def conflict_timeline_figure(events: list[dict]):
    """Build an event-linked timeline without inventing missing scores."""

    rows = timeline_rows(events)
    if not rows:
        return None
    timeline_df = pd.DataFrame(rows)
    y_column = "risk_score" if timeline_df["risk_score"].notna().all() else "severity"
    figure = px.scatter(
        timeline_df,
        x="timestamp_seconds",
        y=y_column,
        color="severity",
        hover_data=[
            column
            for column in [
                "event_id",
                "participant_a_track_id",
                "participant_b_track_id",
                "arrival_time_gap_seconds",
                "time_to_conflict_seconds",
                "risk_score",
            ]
            if column in timeline_df
        ],
        labels={
            "timestamp_seconds": "First alert (seconds)",
            "risk_score": "Heuristic conflict score",
            "severity": "Risk category",
        },
        color_discrete_map={"LOW": "#facc15", "MEDIUM": "#fb923c", "HIGH": "#f43f5e"},
    )
    figure.update_traces(marker={"size": 14, "line": {"width": 1, "color": "white"}})
    figure.update_layout(
        height=280,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend_title_text="Provisional risk",
    )
    return figure


st.markdown('<div class="nm-eyebrow">Computer vision for safer streets</div>', unsafe_allow_html=True)
st.markdown('<h1 class="nm-title">Near<span>Miss</span></h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="nm-subtitle">Upload an intersection video, track road users, '
    "and inspect potential vehicle conflict flags with frame-level evidence.</p>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="nm-notice"><b>Decision-support prototype.</b> Any detector output is a '
    "heuristic flag—not a verified crash or near miss. Review the source video before "
    "drawing conclusions.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Analysis settings")
    model_label = st.selectbox(
        "CPU model",
        ["YOLO11 nano", "YOLOv8 nano"],
        help="Nano models prioritize speed and are suitable for this CPU-first prototype.",
    )
    model_name = "yolo11n.pt" if model_label == "YOLO11 nano" else "yolov8n.pt"
    confidence = st.slider("Detection confidence", 0.10, 0.90, 0.30, 0.05)
    iou_threshold = st.slider("Detection IoU threshold", 0.10, 0.90, 0.50, 0.05)
    trail_length = st.slider("Trajectory length (frames)", 5, 90, 30, 5)
    st.caption("The first use downloads public pretrained weights. Later runs are local.")

    with st.expander("Local cache", expanded=False):
        cached_video_count, cached_bytes = cache_summary()
        st.caption(
            f"{cached_video_count} cached video(s) · {cached_bytes / (1024 * 1024):.1f} MB"
        )
        if st.button("Clear all cached videos", use_container_width=True):
            removed_count, removed_bytes = clear_analysis_cache()
            for key in list(st.session_state):
                if str(key).startswith(
                    (
                        "zone_draft_",
                        "zone_applied_",
                        "zone_last_click_",
                        "event_reviews_",
                        "review_status_",
                        "safety_report_",
                    )
                ):
                    del st.session_state[key]
            # Rotate the uploader key so Streamlit releases the selected file;
            # otherwise the next rerun immediately recreates its cache folder.
            st.session_state["upload_generation"] += 1
            st.toast(
                f"Removed {removed_count} cached video(s) "
                f"({removed_bytes / (1024 * 1024):.1f} MB)"
            )
            st.rerun()

    with st.expander("Conflict detector configuration", expanded=False):
        interaction_label = st.selectbox(
            "Interaction mode",
            ["Vehicle to vehicle", "Vehicle to pedestrian", "Both"],
            index=0,
        )
        prediction_horizon = st.slider(
            "Prediction horizon (seconds)", 1.0, 3.0,
            float(DEFAULT_CONFLICT_CONFIG["prediction_horizon_seconds"]), 0.1,
        )
        high_time_gap = st.slider(
            "HIGH arrival gap (seconds)", 0.1, 1.5,
            float(DEFAULT_CONFLICT_CONFIG["high_time_gap_seconds"]), 0.05,
        )
        low_time_gap = st.slider(
            "Maximum qualifying arrival gap (seconds)", 0.5, 3.0,
            float(DEFAULT_CONFLICT_CONFIG["low_time_gap_seconds"]), 0.05,
        )
        minimum_history = st.slider(
            "Minimum trajectory observations", 3, 15,
            int(DEFAULT_CONFLICT_CONFIG["min_track_age_frames"]), 1,
        )
        high_confirmation = st.slider(
            "Frames required for HIGH", 2, 10,
            int(DEFAULT_CONFLICT_CONFIG["high_persistence_frames"]), 1,
        )
        debug_mode = st.checkbox("Debug rejected vehicle pairs", value=False)
        st.caption(
            "All distances and velocities are image-space approximations. "
            "These controls change heuristic screening, not accident probability."
        )

tracking_config = TrackingConfig(
    model_name=model_name,
    confidence=confidence,
    iou_threshold=iou_threshold,
    device="cpu",
    trail_length=trail_length,
)
conflict_config = {
    **DEFAULT_CONFLICT_CONFIG,
    "analysis_mode": {
        "Vehicle to vehicle": "vehicle_vehicle",
        "Vehicle to pedestrian": "vehicle_pedestrian",
        "Both": "both",
    }[interaction_label],
    "prediction_horizon_seconds": float(prediction_horizon),
    "high_time_gap_seconds": float(high_time_gap),
    "medium_time_gap_seconds": max(float(high_time_gap), 1.0),
    "low_time_gap_seconds": max(float(low_time_gap), float(high_time_gap)),
    "min_track_age_frames": int(minimum_history),
    "high_persistence_frames": int(high_confirmation),
}

section_title(1, "Upload Traffic Footage")
uploaded = st.file_uploader(
    "MP4 video",
    type=["mp4"],
    key=f'video_upload_{st.session_state["upload_generation"]}',
    label_visibility="collapsed",
    help="Short, fixed-camera clips process fastest on CPU. Maximum size: 500 MB.",
)

if uploaded is None:
    st.info("Choose an MP4 to begin. Your video stays on this machine.", icon="↗")
    st.stop()

try:
    upload_bytes = uploaded.getvalue()
    video_hash, source_path = save_upload(upload_bytes, uploaded.name)
    initial_metadata, first_frame = inspect_video(source_path)
except VideoError as exc:
    st.error(str(exc))
    st.stop()

meta_cols = st.columns(4)
meta_cols[0].metric("Duration", format_timestamp(initial_metadata.duration_seconds))
meta_cols[1].metric("Frames", f"{initial_metadata.frame_count:,}")
meta_cols[2].metric("Frame rate", f"{initial_metadata.fps:.1f} fps")
meta_cols[3].metric("Resolution", f"{initial_metadata.width} × {initial_metadata.height}")

section_title(2, "Define the Analysis Zone")
st.write("Click the boundary corners in order. The final edge closes automatically.")
draft_zone, applied_zone = zone_picker(video_hash, first_frame)
if applied_zone:
    st.success(f"Conflict zone active · {len(applied_zone)} vertices", icon="✅")
    if draft_zone != applied_zone:
        st.warning("The draft has unapplied changes; the active zone is still shown in exports and video.")
elif len(draft_zone) >= 3:
    st.warning("The draft polygon is not active yet. Select **Use this conflict zone**.")

section_title(3, "Analyze Video")
existing = cached_analysis(video_hash, source_path, tracking_config, initial_metadata)
run_clicked = st.button(
    "Analyze video" if existing is None else "Use cached analysis",
    type="primary",
    use_container_width=True,
)

artifacts = existing
if run_clicked:
    progress_bar = st.progress(0, text="Preparing analysis")
    try:
        artifacts = analyze_video(
            video_hash,
            source_path,
            tracking_config,
            progress=progress_callback(progress_bar),
        )
    except VideoError as exc:
        progress_bar.empty()
        st.error(str(exc))
        st.stop()
    progress_bar.empty()

if artifacts is None:
    st.caption("Tracking has not run with the current model settings.")
    st.stop()

try:
    tracks, metadata = load_artifacts(artifacts)
except (OSError, ValueError, TypeError) as exc:
    st.error(f"Cached analysis could not be loaded: {exc}")
    st.stop()

has_user_zone = len(applied_zone) >= 3
analysis_zone = (
    applied_zone
    if has_user_zone
    else [
        [0.0, 0.0],
        [float(metadata.width), 0.0],
        [float(metadata.width), float(metadata.height)],
        [0.0, float(metadata.height)],
    ]
)
tracks_for_detector = enrich_tracks_with_zone(tracks, analysis_zone)
conflict_config["zone_is_user_defined"] = has_user_zone
raw_events = []
detector_error = None
try:
    raw_events = detect_conflicts(tracks_for_detector, analysis_zone, conflict_config)
except Exception as exc:  # user-owned extension point should not crash the dashboard
    detector_error = str(exc)

events, event_warnings = normalize_events(raw_events, metadata.fps)
events = deduplicate_events(events)
if detector_error:
    st.error(f"Conflict detector failed: {detector_error}")
for warning in event_warnings:
    st.warning(warning)

diagnostics: list[dict] = []
if debug_mode:
    try:
        diagnostics = diagnose_conflicts(tracks_for_detector, analysis_zone, conflict_config)
    except Exception as exc:
        st.warning(f"Conflict diagnostics could not be generated: {exc}")

annotation_progress = st.progress(0, text="Preparing annotated video")
try:
    annotated_path = render_annotated_video(
        artifacts,
        tracks,
        applied_zone,
        trail_length=tracking_config.trail_length,
        progress=progress_callback(annotation_progress),
        events=events,
    )
except VideoError as exc:
    annotation_progress.empty()
    st.error(str(exc))
    st.stop()
annotation_progress.empty()

unique_vehicles = {
    record["track_id"] for record in tracks if record["object_type"] == "vehicle"
}
unique_pedestrians = {
    record["track_id"] for record in tracks if record["object_type"] == "pedestrian"
}
in_zone_ids = {record["track_id"] for record in tracks_for_detector if record["in_conflict_zone"]}

st.divider()
section_title(4, "Intersection Safety Analysis")
statistics = safety_statistics(tracks, events, metadata.duration_seconds)
summary_cols = st.columns(4)
summary_cols[0].metric("Vehicles tracked", statistics["vehicles_tracked"])
summary_cols[1].metric("Unique potential conflicts", statistics["total_conflicts"])
summary_cols[2].metric(
    "Conflicts per minute", f'{statistics["conflicts_per_minute"]:.2f}'
)
summary_cols[3].metric("Distinct vehicle pairs", statistics["distinct_vehicle_pairs"])

risk_cols = st.columns(4)
risk_cols[0].metric("HIGH experimental", statistics["high_conflicts"])
risk_cols[1].metric("MEDIUM experimental", statistics["medium_conflicts"])
risk_cols[2].metric("LOW experimental", statistics["low_conflicts"])
average_gap = statistics["average_arrival_gap_seconds"]
risk_cols[3].metric(
    "Average predicted time gap",
    "—" if average_gap is None else f"{average_gap:.3f} s",
)
st.caption(
    "Experimental image-coordinate conflict indicators derived from this processed clip; "
    "they are not validated crash probabilities or roadway safety ratings."
)

if not has_user_zone:
    st.warning(
        "Whole-frame analysis is active because no conflict zone was selected. "
        "This is less reliable; draw the intersection or road area to reduce unrelated flags."
    )

if not tracks:
    st.warning(
        "No trackable vehicles or pedestrians met the current confidence threshold. "
        "Try a lower threshold or a clearer clip."
    )

video_tab, events_tab, data_tab = st.tabs(["Annotated video", "Event details", "Track data"])

with video_tab:
    st.video(str(annotated_path))
    st.caption(
        "Boxes show detected classes and persistent IDs; lines show recent movement trajectories. "
        "Detector-provided participants and evidence are highlighted when those fields are present."
    )
    timeline_figure = conflict_timeline_figure(events)
    if timeline_figure is not None:
        st.markdown("#### Conflict timeline")
        st.plotly_chart(timeline_figure, use_container_width=True)
        st.caption("Markers show timestamps supplied by your conflict detector.")

with events_tab:
    if detector_error:
        st.error("No timeline is available until the detector error is fixed.")
    elif not events:
        st.info(
            "No qualifying potential conflicts were returned for this footage, zone, "
            "and detector configuration. This measured zero is not proof of safety."
        )
    else:
        display_events = []
        for event in events:
            row = dict(event)
            row["video_time"] = format_timestamp(event.get("timestamp_seconds"))
            row["first_alert_time"] = format_timestamp(event.get("first_alert_timestamp_seconds"))
            display_events.append(row)
        preferred = [
            column
            for column in [
                "event_id",
                "first_alert_time",
                "video_time",
                "severity",
                "participant_a_track_id",
                "participant_a_type",
                "participant_b_track_id",
                "participant_b_type",
                "risk_score",
                "arrival_time_gap_seconds",
                "time_to_conflict_seconds",
                "persistence_frames",
                "path_separation_pixels",
                "closing_speed_pixels_per_second",
                "description",
            ]
            if any(column in item for item in display_events)
        ]
        remaining = [column for column in pd.DataFrame(display_events).columns if column not in preferred]
        st.dataframe(pd.DataFrame(display_events)[preferred + remaining], use_container_width=True)
        st.warning(
            "Every row is a provisional detector flag requiring human review, not a "
            "verified accident or near miss."
        )

with data_tab:
    counts = (
        pd.DataFrame(tracks)[["track_id", "class_name", "object_type"]]
        .drop_duplicates("track_id")
        .groupby(["object_type", "class_name"], as_index=False)
        .size()
        if tracks
        else pd.DataFrame(columns=["object_type", "class_name", "size"])
    )
    if not counts.empty:
        count_chart = px.bar(
            counts,
            x="class_name",
            y="size",
            color="object_type",
            labels={"class_name": "Object class", "size": "Unique tracks"},
            color_discrete_map={"vehicle": "#fb923c", "pedestrian": "#2dd4bf"},
        )
        count_chart.update_layout(
            height=320,
            margin={"l": 8, "r": 8, "t": 24, "b": 8},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(count_chart, use_container_width=True)

    if tracks:
        table = pd.DataFrame(tracks_for_detector)
        table["bbox"] = table["bbox"].apply(json.dumps)
        table["center"] = table["center"].apply(json.dumps)
        st.dataframe(table, use_container_width=True, height=380)

if debug_mode:
    st.markdown("### Debug conflict pipeline")
    window_diagnostics = [
        row
        for row in diagnostics
        if 0.5 <= float(row.get("timestamp_seconds", -1.0)) <= 3.0
    ]
    stages = pipeline_stage_counts(window_diagnostics, events)
    stage_columns = st.columns(4)
    stage_columns[0].metric("Pair evaluations", stages["pair_evaluations"])
    stage_columns[1].metric("Sufficient history", stages["sufficient_history"])
    stage_columns[2].metric("Projected path candidates", stages["path_candidates"])
    stage_columns[3].metric("Deduplicated events", stages["deduplicated_events"])
    st.caption(
        f'Valid motion: {stages["valid_motion"]} · closing: {stages["closing_pairs"]} · '
        f'future path conflicts: {stages["future_conflicts"]} · '
        f'zone eligible: {stages["zone_eligible"]} · timing eligible: {stages["timing_eligible"]} · '
        f'temporally confirmed rows: {stages["temporally_confirmed"]}'
    )
    if window_diagnostics:
        debug_frame = pd.DataFrame(window_diagnostics)
        preferred_debug = [
            "timestamp_seconds",
            "participant_a_track_id",
            "participant_a_class",
            "participant_a_observations",
            "participant_a_velocity_pixels_per_second",
            "participant_a_predicted_position",
            "participant_b_track_id",
            "participant_b_class",
            "participant_b_observations",
            "participant_b_velocity_pixels_per_second",
            "participant_b_predicted_position",
            "projected_paths_overlap",
            "time_to_conflict_seconds",
            "arrival_time_gap_seconds",
            "inside_conflict_zone",
            "temporal_confirmation_frames_required",
            "temporal_confirmation_frames_observed",
            "temporal_confirmation_met",
            "rejection_reason",
        ]
        visible_debug = [column for column in preferred_debug if column in debug_frame]
        st.dataframe(debug_frame[visible_debug], use_container_width=True, height=340)
        st.download_button(
            "Download debug_conflicts.csv",
            data=diagnostics_to_csv(window_diagnostics),
            file_name="debug_conflicts.csv",
            mime="text/csv",
            use_container_width=True,
        )

        ranked_diagnostics = sorted(
            [row for row in window_diagnostics if row.get("participant_a_position")],
            key=lambda row: (
                row.get("rejection_reason") not in {"accepted", "accepted_low_uncertainty_margin_only"},
                float(row.get("path_separation_pixels", 1e9)),
            ),
        )[:20]
        if ranked_diagnostics:
            diagnostic_labels = [
                f'{row["timestamp_seconds"]:.3f}s · #{row["participant_a_track_id"]} / '
                f'#{row["participant_b_track_id"]} · {row["rejection_reason"]}'
                for row in ranked_diagnostics
            ]
            selected_debug_label = st.selectbox(
                "Visualize a considered vehicle pair", diagnostic_labels
            )
            selected_diagnostic = ranked_diagnostics[
                diagnostic_labels.index(selected_debug_label)
            ]
            rejected_frame = frame_at_timestamp(
                source_path, float(selected_diagnostic["timestamp_seconds"])
            )
            for start_key, end_key, color in (
                ("participant_a_position", "participant_a_predicted_position", (255, 210, 80)),
                ("participant_b_position", "participant_b_predicted_position", (210, 90, 255)),
            ):
                start, end = selected_diagnostic.get(start_key), selected_diagnostic.get(end_key)
                if start and end:
                    cv2.arrowedLine(
                        rejected_frame,
                        tuple(int(value) for value in start),
                        tuple(int(value) for value in end),
                        color,
                        3,
                        cv2.LINE_AA,
                    )
            point = selected_diagnostic.get("conflict_point")
            if point:
                cv2.drawMarker(
                    rejected_frame,
                    tuple(int(value) for value in point),
                    (0, 0, 255),
                    cv2.MARKER_TILTED_CROSS,
                    22,
                    3,
                )
            st.image(
                cv2.cvtColor(rejected_frame, cv2.COLOR_BGR2RGB),
                caption=f'Reason: {selected_diagnostic["rejection_reason"]}',
                use_container_width=True,
            )
    else:
        st.info("No simultaneous vehicle-pair evaluations occurred between 0.5 and 3.0 seconds.")

st.divider()
section_title(5, "Explore Safety Heatmap")
heatmap_opacity = st.slider("Heatmap opacity", 0.10, 0.90, 0.55, 0.05)
heatmap_rgb, heatmap_points = build_conflict_heatmap(first_frame, events, heatmap_opacity)
st.image(
    heatmap_rgb,
    caption="Detected potential-conflict concentration on the uploaded intersection frame",
    use_container_width=True,
)
if not heatmap_points:
    st.info(
        "No valid event locations are available, so the actual intersection frame is shown "
        "without fabricated heat coloration."
    )
else:
    hotspot_ids = [str(point["event_id"]) for point in heatmap_points]
    selected_hotspot = st.selectbox("Inspect hotspot event", hotspot_ids)
    hotspot_event = next(
        event for event in events if str(event.get("event_id")) == selected_hotspot
    )
    st.caption(
        f'{selected_hotspot} · {format_timestamp(hotspot_event.get("first_alert_timestamp_seconds"))} · '
        f'{hotspot_event.get("severity", "—")} · pair {event_pair_key(hotspot_event) or "unavailable"}'
    )

timeline_figure = conflict_timeline_figure(events)
if timeline_figure is not None:
    st.markdown("#### Conflict timeline")
    st.plotly_chart(timeline_figure, use_container_width=True)
else:
    st.info("No detector events are available for the conflict timeline.")

st.divider()
section_title(6, "Review Flagged Events")
review_key = f"event_reviews_{video_hash}"
st.session_state.setdefault(review_key, {})
review_labels: dict[str, str] = st.session_state[review_key]
for event in events:
    review_labels.setdefault(str(event.get("event_id")), "Uncertain")

if not events:
    st.info("No flagged events are available for human review.")
else:
    review_rows = []
    for event in events:
        event_id = str(event.get("event_id"))
        review_rows.append(
            {
                "event_id": event_id,
                "first_alert": format_timestamp(event.get("first_alert_timestamp_seconds")),
                "vehicle_ids": event_pair_key(event),
                "classes": f'{event.get("participant_a_class", "—")} / {event.get("participant_b_class", "—")}',
                "risk": event.get("severity"),
                "conflict_location": event.get("conflict_point"),
                "arrival_gap_seconds": event.get("arrival_time_gap_seconds"),
                "review_status": review_labels[event_id],
                "explanation": event.get("description"),
            }
        )
    st.dataframe(pd.DataFrame(review_rows), use_container_width=True, height=260)
    selected_event_id = st.selectbox(
        "Select an event for evidence review", [row["event_id"] for row in review_rows]
    )
    selected_event = next(
        event for event in events if str(event.get("event_id")) == selected_event_id
    )
    evidence_columns = st.columns([1.1, 1.9])
    with evidence_columns[0]:
        st.markdown(f"#### {selected_event_id}")
        st.write(
            f"First alert: {format_timestamp(selected_event.get('first_alert_timestamp_seconds'))}  \n"
            f"Vehicles: {event_pair_key(selected_event) or 'unavailable'}  \n"
            f"Classes: {selected_event.get('participant_a_class', '—')} / "
            f"{selected_event.get('participant_b_class', '—')}  \n"
            f"Risk: {selected_event.get('severity', '—')}  \n"
            f"Arrival gap: {selected_event.get('arrival_time_gap_seconds', '—')} s  \n"
            f"Conflict location: {selected_event.get('conflict_point', '—')}"
        )
        st.caption(str(selected_event.get("description", "No explanation supplied.")))
        options = ["Confirmed potential conflict", "False positive", "Uncertain"]
        current_status = review_labels.get(selected_event_id, "Uncertain")
        selected_status = st.radio(
            "Human review label",
            options,
            index=options.index(current_status) if current_status in options else 2,
            key=f"review_status_{video_hash}_{selected_event_id}",
        )
        review_labels[selected_event_id] = selected_status
    with evidence_columns[1]:
        alert_time = float(
            selected_event.get(
                "first_alert_timestamp_seconds", selected_event.get("timestamp_seconds", 0.0)
            )
        )
        evidence_frame = frame_at_timestamp(source_path, alert_time)
        st.image(
            cv2.cvtColor(evidence_frame, cv2.COLOR_BGR2RGB),
            caption=f"Actual source frame at {format_timestamp(alert_time)}",
            use_container_width=True,
        )
        evidence_clip = extract_event_clip(
            artifacts, selected_event_id, alert_time, before_seconds=2.0, after_seconds=2.0
        )
        st.video(str(evidence_clip))
        st.caption("Actual source footage: approximately 2 seconds before and after the first alert.")

st.divider()
section_title(7, "Generate Safety Report")
report_state_key = f"safety_report_{video_hash}"
if st.button("Generate Safety Report", type="primary", use_container_width=True):
    try:
        report_frames = {}
        for event in events:
            event_id = str(event.get("event_id"))
            alert_time = float(
                event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds", 0.0))
            )
            report_frames[event_id] = cv2.cvtColor(
                frame_at_timestamp(source_path, alert_time), cv2.COLOR_BGR2RGB
            )
        st.session_state[report_state_key] = generate_safety_report(
            source_filename=uploaded.name,
            duration_seconds=metadata.duration_seconds,
            tracks=tracks,
            events=events,
            heatmap_rgb=heatmap_rgb,
            review_labels=review_labels,
            event_frames=report_frames,
        )
        st.success("Safety report generated from the current processed results.")
    except (RuntimeError, VideoError, ValueError) as exc:
        st.error(f"Safety report could not be generated: {exc}")
if report_state_key in st.session_state:
    st.download_button(
        "Download Intersection Safety Report PDF",
        data=st.session_state[report_state_key],
        file_name="nearmiss_intersection_safety_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

st.markdown("### Export results")
reviewed_events = events_with_review_labels(events, review_labels)
export_payload = {
    "schema_version": "1.0",
    "source_filename": uploaded.name,
    "video_sha256": video_hash,
    "video": asdict(metadata),
    "tracking_config": tracking_config.as_dict(),
    "conflict_config": conflict_config,
    "zone_pixels": applied_zone,
    "analysis_zone_pixels": analysis_zone,
    "zone_normalized": normalized_polygon(applied_zone, metadata.width, metadata.height),
    "tracks": tracks_for_detector,
    "events": reviewed_events,
    "disclaimer": "Potential conflict flags are heuristic and are not verified accidents or near misses.",
}
download_cols = st.columns(4)
download_cols[0].download_button(
    "Download tracks CSV",
    data=tracks_to_csv(tracks_for_detector),
    file_name="nearmiss_tracks.csv",
    mime="text/csv",
    use_container_width=True,
)
download_cols[1].download_button(
    "Download events CSV",
    data=events_to_csv(reviewed_events),
    file_name="nearmiss_events.csv",
    mime="text/csv",
    use_container_width=True,
)
download_cols[2].download_button(
    "Download analysis JSON",
    data=json.dumps(export_payload, indent=2, default=json_default),
    file_name="nearmiss_analysis.json",
    mime="application/json",
    use_container_width=True,
)
download_cols[3].download_button(
    "Download annotated MP4",
    data=annotated_path.read_bytes(),
    file_name="nearmiss_annotated.mp4",
    mime="video/mp4",
    use_container_width=True,
)

st.caption(
    "NearMiss MVP · YOLO detections + ByteTrack identities · All analysis runs locally after model download"
)

