"""NearMiss Streamlit application."""

from __future__ import annotations

import json
from dataclasses import asdict

import cv2
import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image, ImageDraw

from conflict_detector import detect_conflicts, diagnose_conflicts
from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.events import events_to_csv, format_timestamp, normalize_events
from nearmiss.geometry import enrich_tracks_with_zone, normalized_polygon
from nearmiss.video import (
    VideoError,
    analyze_video,
    cached_analysis,
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
    """Build the shared event timeline without creating placeholder points."""

    timeline_rows = [event for event in events if event.get("timestamp_seconds") is not None]
    if not timeline_rows:
        return None
    timeline_df = pd.DataFrame(timeline_rows)
    timeline_df["timeline"] = "Potential conflict flag"
    figure = px.scatter(
        timeline_df,
        x="timestamp_seconds",
        y="timeline",
        color="severity",
        hover_data=[
            column
            for column in [
                "event_id",
                "participant_a_track_id",
                "participant_b_track_id",
                "interaction_type",
                "first_alert_timestamp_seconds",
                "arrival_time_gap_seconds",
                "risk_score",
                "description",
            ]
            if column in timeline_df
        ],
        labels={"timestamp_seconds": "Seconds into video", "timeline": ""},
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
    "and inspect provisional vehicle collision-risk flags with frame-level evidence.</p>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="nm-notice"><b>Decision-support prototype.</b> Risk labels are provisional '
    "image-coordinate heuristics—not verified crashes, near misses, physical speeds, or "
    "collision probabilities. Review source video before drawing conclusions.</div>",
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

    with st.expander("Detector configuration", expanded=False):
        analysis_label = st.selectbox(
            "Interaction analysis",
            ["Vehicle to vehicle (default)", "Vehicle to pedestrian", "Both"],
            help="Pedestrians remain available, but vehicle-to-vehicle screening is the default.",
        )
        prediction_horizon = st.number_input(
            "Prediction horizon (seconds)",
            min_value=0.5,
            max_value=5.0,
            value=DEFAULT_CONFLICT_CONFIG["prediction_horizon_seconds"],
            step=0.1,
        )
        high_time_gap = st.number_input(
            "HIGH: maximum arrival gap (seconds)",
            min_value=0.05,
            max_value=3.0,
            value=DEFAULT_CONFLICT_CONFIG["high_time_gap_seconds"],
            step=0.05,
        )
        medium_time_gap = st.number_input(
            "MEDIUM: maximum arrival gap (seconds)",
            min_value=0.05,
            max_value=4.0,
            value=DEFAULT_CONFLICT_CONFIG["medium_time_gap_seconds"],
            step=0.05,
        )
        low_time_gap = st.number_input(
            "LOW: maximum arrival gap (seconds)",
            min_value=0.05,
            max_value=5.0,
            value=DEFAULT_CONFLICT_CONFIG["low_time_gap_seconds"],
            step=0.05,
        )
        path_tolerance = st.number_input(
            "Projected path tolerance (pixels)",
            min_value=1.0,
            max_value=250.0,
            value=DEFAULT_CONFLICT_CONFIG["path_intersection_tolerance_pixels"],
            step=1.0,
            help="Compensates for box jitter and object width in image coordinates.",
        )
        min_closing_speed = st.number_input(
            "Minimum closing motion (pixels/second)",
            min_value=0.0,
            max_value=200.0,
            value=DEFAULT_CONFLICT_CONFIG["min_closing_speed_pixels_per_second"],
            step=1.0,
        )
        smoothing_frames = st.number_input(
            "Velocity smoothing observations",
            min_value=2,
            max_value=30,
            value=DEFAULT_CONFLICT_CONFIG["velocity_smoothing_frames"],
            step=1,
        )
        min_track_age = st.number_input(
            "Minimum track age (observations)",
            min_value=2,
            max_value=120,
            value=DEFAULT_CONFLICT_CONFIG["min_track_age_frames"],
            step=1,
        )
        duplicate_cooldown = st.number_input(
            "Duplicate suppression window (seconds)",
            min_value=0.25,
            max_value=10.0,
            value=DEFAULT_CONFLICT_CONFIG["duplicate_cooldown_seconds"],
            step=0.25,
        )
        debug_mode = st.checkbox(
            "Debug rejected vehicle pairs",
            value=False,
            help="Shows real detector gate measurements and rejection reasons. Disable for normal review.",
        )
        st.caption(
            "All motion is measured in pixels. Thresholds are screening heuristics, "
            "not calibrated physical safety limits."
        )
        if not float(high_time_gap) <= float(medium_time_gap) <= float(low_time_gap):
            st.warning(
                "Arrival-gap thresholds must increase from HIGH to MEDIUM to LOW. "
                "The detector will expand later thresholds to preserve that order."
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
    "prediction_horizon_seconds": float(prediction_horizon),
    "high_time_gap_seconds": float(high_time_gap),
    "medium_time_gap_seconds": max(float(high_time_gap), float(medium_time_gap)),
    "low_time_gap_seconds": max(
        float(high_time_gap), float(medium_time_gap), float(low_time_gap)
    ),
    "path_intersection_tolerance_pixels": float(path_tolerance),
    "min_closing_speed_pixels_per_second": float(min_closing_speed),
    "velocity_smoothing_frames": int(smoothing_frames),
    "min_track_age_frames": int(min_track_age),
    "duplicate_cooldown_seconds": float(duplicate_cooldown),
    "analysis_mode": {
        "Vehicle to vehicle (default)": "vehicle_vehicle",
        "Vehicle to pedestrian": "vehicle_pedestrian",
        "Both": "both",
    }[analysis_label],
}

section_title(1, "Upload an intersection video")
uploaded = st.file_uploader(
    "MP4 video",
    type=["mp4"],
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

section_title(2, "Mark the conflict zone")
st.write("Click the boundary corners in order. The final edge closes automatically.")
draft_zone, applied_zone = zone_picker(video_hash, first_frame)
if applied_zone:
    st.success(f"Conflict zone active · {len(applied_zone)} vertices", icon="✅")
    if draft_zone != applied_zone:
        st.warning("The draft has unapplied changes; the active zone is still shown in exports and video.")
elif len(draft_zone) >= 3:
    st.warning("The draft polygon is not active yet. Select **Use this conflict zone**.")

section_title(3, "Run object tracking")
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

diagnostic_rows: list[dict] = []
if debug_mode:
    try:
        diagnostic_rows = diagnose_conflicts(tracks_for_detector, analysis_zone, conflict_config)
    except Exception as exc:
        st.warning(f"Pair diagnostics failed: {exc}")

events, event_warnings = normalize_events(raw_events, metadata.fps)
if detector_error:
    st.error(f"Conflict detector failed: {detector_error}")
for warning in event_warnings:
    st.warning(warning)

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
section_title(4, "Review the analysis")
summary_cols = st.columns(4)
summary_cols[0].metric("Vehicles tracked", len(unique_vehicles))
summary_cols[1].metric("Pedestrians tracked", len(unique_pedestrians))
summary_cols[2].metric("Tracks in analysis area", len(in_zone_ids))
summary_cols[3].metric("Vehicle conflict flags", len(events))

risk_counts = {
    severity: sum(str(event.get("severity", "")).upper() == severity for event in events)
    for severity in ("LOW", "MEDIUM", "HIGH")
}
risk_cols = st.columns(3)
risk_cols[0].metric("LOW provisional", risk_counts["LOW"])
risk_cols[1].metric("MEDIUM provisional", risk_counts["MEDIUM"])
risk_cols[2].metric("HIGH provisional", risk_counts["HIGH"])

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
        "Orange: vehicles · teal: pedestrians · blue: active zone · "
        "yellow/orange/red: provisional LOW/MEDIUM/HIGH conflict evidence"
    )
    timeline_figure = conflict_timeline_figure(events)
    if timeline_figure is not None:
        st.markdown("#### Conflict timeline")
        st.plotly_chart(timeline_figure, use_container_width=True)
        st.caption("Markers show the strongest image-coordinate heuristic frame for each event.")

with events_tab:
    if detector_error:
        st.error("No timeline is available until the detector error is fixed.")
    elif not events:
        st.info(
            "No qualifying projected vehicle interactions were found with the "
            "current zone and detector thresholds."
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
                "path_separation_pixels",
                "closing_speed_pixels_per_second",
                "description",
            ]
            if any(column in item for item in display_events)
        ]
        remaining = [column for column in pd.DataFrame(display_events).columns if column not in preferred]
        st.dataframe(pd.DataFrame(display_events)[preferred + remaining], use_container_width=True)
        st.warning(
            "Every row is a provisional pixel-space heuristic flag requiring human review. "
            "The risk index ranks evidence; it is not an accident probability."
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
    with st.expander("Debug: vehicle-pair rejection trace", expanded=True):
        st.caption(
            "One row is emitted for each active vehicle pair at each tracker update. "
            "This is diagnostic evidence only; it does not create alerts."
        )
        if not diagnostic_rows:
            st.warning("No simultaneous vehicle pairs reached the detector's timestamp loop.")
        else:
            debug_table = pd.DataFrame(diagnostic_rows)
            debug_table["video_time"] = debug_table["timestamp_seconds"].map(format_timestamp)
            preferred_debug_columns = [
                "video_time",
                "frame_index",
                "participant_a_track_id",
                "participant_a_class",
                "participant_a_observations",
                "participant_a_velocity_pixels_per_second",
                "participant_b_track_id",
                "participant_b_class",
                "participant_b_observations",
                "participant_b_velocity_pixels_per_second",
                "projected_paths_overlap",
                "participant_a_eta_seconds",
                "participant_b_eta_seconds",
                "arrival_time_gap_seconds",
                "inside_conflict_zone",
                "rejection_reason",
            ]
            visible_columns = [column for column in preferred_debug_columns if column in debug_table]
            st.dataframe(debug_table[visible_columns], use_container_width=True, height=360)

st.markdown("### Export results")
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
    "events": events,
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
    data=events_to_csv(events),
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

