"""NearMiss premium Streamlit interface.

The UI is intentionally thin: detection, tracking, prediction, incident
evidence, persistence, and reporting remain in their existing backend modules.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import cv2
import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image, ImageDraw

from conflict_detector import detect_conflicts, diagnose_conflicts
from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.events import events_to_csv, format_timestamp, normalize_events
from nearmiss.geometry import enrich_tracks_with_zone, normalized_polygon
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG, detect_suspected_collisions
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
from nearmiss.store import (
    acknowledge_notification,
    list_notifications,
    list_reviews,
    review_incident,
)
from nearmiss.video import (
    VideoError,
    analyze_video,
    annotate_incident_frame,
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
except ImportError:  # pragma: no cover - dependency is included in requirements
    streamlit_image_coordinates = None


COLORS = {
    "background": "#09090B",
    "card": "#111113",
    "accent": "#FAFAFA",
    "text": "#FAFAFA",
    "muted": "#A1A1AA",
    "warning": "#D6A75C",
    "critical": "#E06B72",
    "success": "#65B89E",
    "border": "#27272A",
}


st.set_page_config(
    page_title="NearMiss Safety Operations",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_styles() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
          --nm-bg:{COLORS['background']}; --nm-card:{COLORS['card']};
          --nm-accent:{COLORS['accent']}; --nm-text:{COLORS['text']};
          --nm-muted:{COLORS['muted']}; --nm-warning:{COLORS['warning']};
          --nm-critical:{COLORS['critical']}; --nm-success:{COLORS['success']};
          --nm-border:{COLORS['border']};
        }}
        html {{ color-scheme:dark; }}
        html, body, [class*="css"] {{ font-family:Inter, Geist, ui-sans-serif, -apple-system,
          BlinkMacSystemFont, "Segoe UI", sans-serif; -webkit-font-smoothing:antialiased; }}
        .stApp {{ background:var(--nm-bg); color:var(--nm-text); }}
        [data-testid="stHeader"] {{ background:rgba(9,9,11,.92); border-bottom:1px solid transparent; }}
        [data-testid="stMainBlockContainer"] {{ max-width:1180px; padding:5rem 3rem 6rem; }}
        [data-testid="stSidebar"] {{ background:#0C0C0E; border-right:1px solid var(--nm-border);
          min-width:232px !important; max-width:232px !important; }}
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ padding:1.35rem .8rem; }}
        .nm-brand {{ padding:.2rem .55rem 2.15rem; }}
        .nm-brand-name {{ color:var(--nm-text); font-size:1rem; font-weight:650;
          letter-spacing:-.015em; }}
        .nm-brand-sub {{ color:#71717A; font-size:.66rem; font-weight:600;
          letter-spacing:.13em; text-transform:uppercase; margin-top:.42rem; }}
        [data-testid="stSidebar"] [role="radiogroup"] {{ gap:.12rem; }}
        [data-testid="stSidebar"] [role="radiogroup"] label {{
          min-height:2.35rem; padding:.48rem .62rem; border-radius:6px; border:1px solid transparent;
          color:#8D8D96; transition:background-color 180ms cubic-bezier(.2,0,0,1),
          color 180ms cubic-bezier(.2,0,0,1);
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
          background:#151517; color:#D4D4D8;
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
          background:#1A1A1D; color:var(--nm-text);
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
          color:var(--nm-text); font-weight:570;
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child {{ display:none; }}
        .nm-page-kicker {{ color:#71717A; font-size:.72rem; line-height:1.4;
          letter-spacing:.02em; font-weight:530; margin-bottom:1rem; padding-top:.1rem; }}
        .nm-page-title {{ color:var(--nm-text); font-size:2.7rem; line-height:1.06;
          letter-spacing:-.05em; font-weight:620; margin:0; max-width:780px; }}
        .nm-page-subtitle {{ color:#A1A1AA; font-size:1rem; line-height:1.65;
          max-width:690px; margin:.9rem 0 3rem; }}
        .nm-section-title {{ color:var(--nm-text); font-size:1rem; font-weight:570;
          letter-spacing:-.012em; margin:2.65rem 0 .32rem; }}
        .nm-section-copy {{ color:#71717A; font-size:.82rem; margin:0 0 1.15rem; }}
        .nm-status {{ display:inline-flex; align-items:center; border-radius:999px;
          padding:.2rem .48rem; font-size:.68rem; line-height:1.25; font-weight:560;
          border:1px solid var(--nm-border); background:transparent; color:#A1A1AA; }}
        .nm-status.success {{ color:#87C7B3; border-color:#29473E; }}
        .nm-status.warning {{ color:#D7B477; border-color:#52432A; }}
        .nm-status.critical {{ color:#E18A8E; border-color:#573236; }}
        .nm-empty {{ border-top:1px solid var(--nm-border); border-bottom:1px solid var(--nm-border);
          padding:3.2rem 1rem; text-align:center; background:transparent; color:#71717A; }}
        .nm-workflow {{ display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid var(--nm-border);
          border-bottom:1px solid var(--nm-border); margin:-.5rem 0 2.8rem; }}
        .nm-workflow-step {{ padding:.85rem 0; color:#71717A; font-size:.72rem; }}
        .nm-workflow-step strong {{ color:#D4D4D8; font-weight:540; margin-right:.35rem; }}
        .nm-file-meta {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
          gap:1.2rem 1rem; margin-top:1.25rem; }}
        .nm-file-meta-item {{ border-top:1px solid var(--nm-border); padding-top:.75rem; min-width:0; }}
        .nm-file-meta-label {{ color:#71717A; font-size:.7rem; margin-bottom:.28rem; }}
        .nm-file-meta-value {{ color:#E4E4E7; font-size:.9rem; white-space:nowrap;
          overflow:hidden; text-overflow:ellipsis; }}
        .nm-row-separator {{ height:1px; background:var(--nm-border); margin:.65rem 0; }}
        .nm-meta {{ color:#71717A; font-size:.78rem; line-height:1.6; }}
        .nm-hero-rule {{ height:1px; background:var(--nm-border); margin:0 0 2.2rem; }}
        [data-testid="stMetric"] {{ background:transparent; border:0; border-top:1px solid var(--nm-border);
          padding:1rem 0 .65rem; border-radius:0; box-shadow:none; min-height:90px; }}
        [data-testid="stMetricLabel"] {{ color:#71717A; font-size:.72rem; }}
        [data-testid="stMetricValue"] {{ color:var(--nm-text); font-size:1.8rem;
          font-weight:560; letter-spacing:-.04em; }}
        [data-testid="stVerticalBlockBorderWrapper"] {{ background:transparent;
          border-color:var(--nm-border) !important; border-radius:6px !important; }}
        [data-testid="stFileUploaderDropzone"] {{ background:#0D0D0F; border:1px dashed #3F3F46;
          border-radius:7px; padding:1.15rem; transition:border-color 180ms cubic-bezier(.2,0,0,1),
          background-color 180ms cubic-bezier(.2,0,0,1); }}
        [data-testid="stFileUploaderDropzone"]:hover {{ border-color:#71717A; background:#111113; }}
        .stButton > button, .stDownloadButton > button {{ border-radius:6px; min-height:2.45rem;
          font-weight:540; border:1px solid #303036; background:#151517; color:#E4E4E7;
          transition:background-color 180ms cubic-bezier(.2,0,0,1),
          border-color 180ms cubic-bezier(.2,0,0,1), color 180ms cubic-bezier(.2,0,0,1); }}
        .stButton > button:hover, .stDownloadButton > button:hover {{
          background:#1C1C1F; border-color:#52525B; color:#FAFAFA; }}
        .stButton > button:active, .stDownloadButton > button:active {{ transform:translateY(1px); }}
        .stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
        [data-testid="stSidebar"] label:has(input:focus-visible) {{ outline:2px solid #A1A1AA;
          outline-offset:2px; }}
        .stButton > button[kind="primary"] {{ background:#FAFAFA; color:#09090B;
          border-color:#FAFAFA; }}
        .stButton > button[kind="primary"]:hover {{ color:#09090B; background:#E4E4E7;
          border-color:#E4E4E7; }}
        [data-testid="stTabs"] [role="tablist"] {{ gap:1.35rem; border-bottom:1px solid var(--nm-border); }}
        [data-testid="stTabs"] button {{ color:#71717A; padding:.65rem 0; font-size:.82rem; }}
        [data-testid="stTabs"] button[aria-selected="true"] {{ color:#FAFAFA; }}
        [data-testid="stDataFrame"] {{ border:1px solid var(--nm-border); border-radius:6px; overflow:hidden; }}
        [data-testid="stAlert"] {{ border-radius:6px; border-width:1px; background:#111113; }}
        [data-testid="stExpander"] details {{ border-color:var(--nm-border); border-radius:6px; background:transparent; }}
        [data-testid="stCheckbox"] label:has(input[role="switch"]:checked) > div:nth-of-type(1) {{
          background-color:#E4E4E7 !important;
        }}
        [data-testid="stProgress"] > div > div {{ background:#E4E4E7; }}
        hr {{ border-color:var(--nm-border) !important; opacity:1; }}
        .nm-footer {{ color:#52525B; font-size:.68rem; margin-top:3rem; line-height:1.6; }}
        @media (max-width: 900px) {{
          [data-testid="stSidebar"] {{ min-width:205px !important; max-width:205px !important; }}
          [data-testid="stMainBlockContainer"] {{ padding:4.5rem 1.5rem 4rem; }}
          .nm-page-title {{ font-size:2.15rem; }}
          .st-key-overview_media [data-testid="stHorizontalBlock"] {{ flex-direction:column; }}
          .st-key-overview_media [data-testid="stColumn"] {{ width:100% !important;
            flex:1 1 100% !important; }}
        }}
        @media (max-width: 640px) {{
          [data-testid="stMainBlockContainer"] {{ padding:4.2rem 1rem 4rem; }}
          .nm-page-title {{ font-size:1.9rem; }}
          .nm-page-subtitle {{ margin-bottom:2.2rem; }}
          .nm-workflow {{ grid-template-columns:repeat(2,1fr); }}
        }}
        @media (prefers-reduced-motion: reduce) {{
          *, *::before, *::after {{ transition-duration:.01ms !important;
            animation-duration:.01ms !important; animation-iteration-count:1 !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="nm-page-kicker">{kicker}</div>'
        f'<h1 class="nm-page-title">{title}</h1>'
        f'<p class="nm-page-subtitle">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def section_header(title: str, copy: str | None = None) -> None:
    st.markdown(f'<div class="nm-section-title">{title}</div>', unsafe_allow_html=True)
    if copy:
        st.markdown(f'<p class="nm-section-copy">{copy}</p>', unsafe_allow_html=True)


def status_pill(label: str, tone: str = "") -> None:
    css_class = f"nm-status {tone}".strip()
    st.markdown(f'<span class="{css_class}">{label}</span>', unsafe_allow_html=True)


def empty_state(title: str, message: str) -> None:
    st.markdown(
        f'<div class="nm-empty"><strong style="color:{COLORS["text"]}">{title}</strong>'
        f'<div style="margin-top:.45rem">{message}</div></div>',
        unsafe_allow_html=True,
    )


def progress_callback(progress_bar):
    def update(fraction: float, message: str) -> None:
        progress_bar.progress(max(0.0, min(float(fraction), 1.0)), text=message)

    return update


def json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def draw_zone_preview(frame_bgr, zone: list[list[float]], max_width: int = 900):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    original = Image.fromarray(rgb)
    ratio = min(1.0, max_width / original.width)
    display_size = (max(1, int(original.width * ratio)), max(1, int(original.height * ratio)))
    preview = original.resize(display_size, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(preview, "RGBA")
    display_points = [(int(x * ratio), int(y * ratio)) for x, y in zone]
    if len(display_points) >= 3:
        draw.polygon(display_points, fill=(250, 250, 250, 24), outline=(212, 212, 216, 255), width=3)
    elif len(display_points) >= 2:
        draw.line(display_points, fill=(212, 212, 216, 255), width=3)
    for index, (x, y) in enumerate(display_points, start=1):
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(244, 184, 96, 255))
        draw.text((x + 9, y - 10), str(index), fill="white")
    return preview, ratio


def zone_picker(video_hash: str, first_frame) -> tuple[list[list[float]], list[list[float]]]:
    draft_key = f"zone_draft_{video_hash}"
    applied_key = f"zone_applied_{video_hash}"
    last_click_key = f"zone_last_click_{video_hash}"
    st.session_state.setdefault(draft_key, [])
    st.session_state.setdefault(applied_key, [])
    st.session_state.setdefault(last_click_key, None)
    controls = st.columns([1, 1, 2])
    if controls[0].button("Undo", key=f"undo_{video_hash}", width="stretch"):
        if st.session_state[draft_key]:
            st.session_state[draft_key].pop()
    if controls[1].button("Clear", key=f"clear_zone_{video_hash}", width="stretch"):
        st.session_state[draft_key] = []
    if controls[2].button(
        "Apply analysis area",
        key=f"apply_{video_hash}",
        type="primary",
        disabled=len(st.session_state[draft_key]) < 3,
        width="stretch",
    ):
        st.session_state[applied_key] = [point[:] for point in st.session_state[draft_key]]
        st.toast("Analysis area saved")
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
        st.image(preview, width="stretch")
        st.warning("Install streamlit-image-coordinates to draw an analysis area.")
    st.caption(
        "Click the boundary corners in order. Leave empty to analyze the full frame."
    )
    return st.session_state[draft_key], st.session_state[applied_key]


def conflict_timeline_figure(events: list[dict]):
    rows = timeline_rows(events)
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    frame["display_level"] = frame["severity"].map({"LOW": 1, "MEDIUM": 2, "HIGH": 3})
    figure = px.scatter(
        frame,
        x="timestamp_seconds",
        y="display_level",
        color="severity",
        hover_data=[
            "event_id",
            "participant_a_track_id",
            "participant_b_track_id",
            "arrival_time_gap_seconds",
            "time_to_conflict_seconds",
        ],
        color_discrete_map={"LOW": COLORS["warning"], "MEDIUM": "#E28B55", "HIGH": COLORS["critical"]},
        labels={"timestamp_seconds": "Video time", "display_level": "Priority"},
    )
    figure.update_traces(marker={"size": 13, "line": {"width": 1, "color": COLORS["text"]}})
    figure.update_yaxes(
        tickmode="array", tickvals=[1, 2, 3], ticktext=["Low", "Medium", "High"], range=[0.6, 3.4]
    )
    figure.update_layout(
        height=250,
        margin={"l": 8, "r": 8, "t": 12, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["muted"]},
        legend_title_text="Priority",
        xaxis={"gridcolor": "#26313E"},
        yaxis={"gridcolor": "#26313E"},
    )
    return figure


def queue_page(page: str) -> None:
    st.session_state["_next_page"] = page


def clear_interface_state() -> None:
    for key in list(st.session_state):
        if str(key).startswith(
            (
                "zone_draft_",
                "zone_applied_",
                "zone_last_click_",
                "event_reviews_",
                "review_status_",
                "safety_report_",
                "selected_incident_",
                "camera_id_",
            )
        ):
            del st.session_state[key]
    st.session_state.pop("active_video", None)


apply_styles()
st.session_state.setdefault("upload_generation", 0)
legacy_navigation = {
    "Upload": "Overview",
    "Analyze": "Analysis",
    "Review": "Incidents",
    "Notify": "Dispatch",
}
st.session_state.setdefault("navigation", "Overview")
st.session_state["navigation"] = legacy_navigation.get(
    st.session_state["navigation"], st.session_state["navigation"]
)
if "_next_page" in st.session_state:
    requested_page = st.session_state.pop("_next_page")
    st.session_state["navigation"] = legacy_navigation.get(requested_page, requested_page)


with st.sidebar:
    st.markdown(
        '<div class="nm-brand"><div class="nm-brand-name">NearMiss</div>'
        '<div class="nm-brand-sub">Safety operations</div></div>',
        unsafe_allow_html=True,
    )
    navigation = st.radio(
        "Workspace",
        ["Overview", "Analysis", "Incidents", "Dispatch"],
        key="navigation",
        label_visibility="collapsed",
    )
    st.markdown("<div style='height:.75rem'></div>", unsafe_allow_html=True)

    with st.expander("Advanced settings", expanded=False):
        model_label = st.selectbox("Detection model", ["YOLO11 nano", "YOLOv8 nano"])
        model_name = "yolo11n.pt" if model_label == "YOLO11 nano" else "yolov8n.pt"
        confidence = st.slider("Object confidence", 0.10, 0.90, 0.30, 0.05)
        iou_threshold = st.slider("Object overlap threshold", 0.10, 0.90, 0.50, 0.05)
        trail_length = st.slider("Trail length", 5, 90, 30, 5)
        interaction_label = st.selectbox(
            "Prediction mode", ["Vehicle to vehicle", "Vehicle to pedestrian", "Both"]
        )
        prediction_horizon = st.slider(
            "Look-ahead window", 1.0, 3.0,
            float(DEFAULT_CONFLICT_CONFIG["prediction_horizon_seconds"]), 0.1,
            format="%.1f sec",
        )
        high_time_gap = st.slider(
            "High-priority arrival gap", 0.10, 1.50,
            float(DEFAULT_CONFLICT_CONFIG["high_time_gap_seconds"]), 0.05,
            format="%.2f sec",
        )
        low_time_gap = st.slider(
            "Maximum arrival gap", 0.50, 3.00,
            float(DEFAULT_CONFLICT_CONFIG["low_time_gap_seconds"]), 0.05,
            format="%.2f sec",
        )
        minimum_history = st.slider(
            "Minimum track history", 3, 15,
            int(DEFAULT_CONFLICT_CONFIG["min_track_age_frames"]), 1,
        )
        high_confirmation = st.slider(
            "High-priority confirmation", 2, 10,
            int(DEFAULT_CONFLICT_CONFIG["high_persistence_frames"]), 1,
            format="%d frames",
        )
        collision_overlap = st.slider(
            "Incident overlap evidence", 0.20, 0.70,
            float(DEFAULT_COLLISION_CONFIG["minimum_strong_overlap_fraction"]), 0.01,
        )
        collision_persistence = st.slider(
            "Incident contact duration", 2, 8,
            int(DEFAULT_COLLISION_CONFIG["contact_persistence_frames"]), 1,
            format="%d frames",
        )
        collision_deceleration = st.slider(
            "Post-contact speed ratio", 0.20, 0.90,
            float(DEFAULT_COLLISION_CONFIG["deceleration_speed_ratio"]), 0.05,
        )
        debug_mode = st.toggle("Show technical diagnostics", value=False)

    with st.expander("Storage", expanded=False):
        cached_video_count, cached_bytes = cache_summary()
        st.caption(f"{cached_video_count} cached video(s) · {cached_bytes / 1048576:.1f} MB")
        if st.button("Clear processed videos", width="stretch"):
            removed_count, removed_bytes = clear_analysis_cache()
            clear_interface_state()
            st.session_state["upload_generation"] += 1
            st.session_state["_next_page"] = "Overview"
            st.toast(f"Removed {removed_count} video(s), {removed_bytes / 1048576:.1f} MB")
            st.rerun()

    st.markdown(
        '<div class="nm-footer">Runs locally<br>No emergency-service connection</div>',
        unsafe_allow_html=True,
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
collision_config = {
    **DEFAULT_COLLISION_CONFIG,
    "minimum_strong_overlap_fraction": float(collision_overlap),
    "contact_persistence_frames": int(collision_persistence),
    "deceleration_speed_ratio": float(collision_deceleration),
}


active_video = st.session_state.get("active_video")

if navigation == "Overview":
    page_header(
        "Overview",
        "Turn traffic footage into reviewable evidence.",
        "NearMiss follows vehicle movement, surfaces possible conflicts, and keeps every operator decision connected to the original video.",
    )
    st.markdown(
        '<div class="nm-workflow">'
        '<div class="nm-workflow-step"><strong>1</strong>Upload footage</div>'
        '<div class="nm-workflow-step"><strong>2</strong>Run analysis</div>'
        '<div class="nm-workflow-step"><strong>3</strong>Review evidence</div>'
        '<div class="nm-workflow-step"><strong>4</strong>Acknowledge</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "Traffic camera video",
        type=["mp4"],
        key=f'video_upload_{st.session_state["upload_generation"]}',
        help="Use original footage rather than a previously annotated export.",
    )
    if uploaded is not None:
        try:
            video_hash, source_path = save_upload(uploaded.getvalue(), uploaded.name)
            st.session_state["active_video"] = {
                "name": uploaded.name,
                "video_hash": video_hash,
                "source_path": str(source_path),
            }
            active_video = st.session_state["active_video"]
        except VideoError as exc:
            st.error(str(exc))

    if not active_video or not Path(active_video["source_path"]).exists():
        empty_state(
            "No footage selected",
            "Drop an MP4 above to preview it and begin analysis.",
        )
        st.stop()

    source_path = Path(active_video["source_path"])
    video_hash = str(active_video["video_hash"])
    try:
        initial_metadata, first_frame = inspect_video(source_path)
    except VideoError as exc:
        st.error(str(exc))
        st.stop()

    overview_media = st.container(key="overview_media")
    preview_col, details_col = overview_media.columns([1.65, 1], gap="large")
    with preview_col:
        st.video(str(source_path))
    with details_col:
        section_header("Footage ready")
        status_pill("Ready to analyze", "success")
        st.markdown(f"**{active_video['name']}**")
        st.markdown(
            '<div class="nm-file-meta">'
            f'<div class="nm-file-meta-item"><div class="nm-file-meta-label">Duration</div>'
            f'<div class="nm-file-meta-value">{format_timestamp(initial_metadata.duration_seconds)}</div></div>'
            f'<div class="nm-file-meta-item"><div class="nm-file-meta-label">Frame rate</div>'
            f'<div class="nm-file-meta-value">{initial_metadata.fps:.0f} fps</div></div>'
            f'<div class="nm-file-meta-item"><div class="nm-file-meta-label">Frames</div>'
            f'<div class="nm-file-meta-value">{initial_metadata.frame_count:,}</div></div>'
            f'<div class="nm-file-meta-item"><div class="nm-file-meta-label">Resolution</div>'
            f'<div class="nm-file-meta-value">{initial_metadata.width} × {initial_metadata.height}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        camera_id = st.text_input(
            "Camera name",
            value=f"CAM-{video_hash[:8].upper()}",
            key=f"camera_id_{video_hash}",
            help="Used in the simulated dispatch inbox. No street address is inferred.",
        )

    with st.expander("Optional analysis area", expanded=False):
        _draft_zone, applied_zone = zone_picker(video_hash, first_frame)
        if applied_zone:
            st.success("Custom analysis area is active.")

    existing = cached_analysis(video_hash, source_path, tracking_config, initial_metadata)
    if existing is not None:
        st.caption("Processed results already exist for these settings. Opening them will not rerun tracking.")
    if st.button("Analyze Footage", type="primary", width="stretch"):
        progress_bar = st.progress(0, text="Preparing footage")
        try:
            analyze_video(
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
        st.session_state["_next_page"] = "Analysis"
        st.toast("Analysis complete")
        st.rerun()
    st.stop()


if not active_video or not Path(active_video["source_path"]).exists():
    page_header(navigation, "No footage selected", "Choose a source video before continuing.")
    empty_state("Footage required", "Open Overview and upload an MP4 to begin.")
    st.button("Open Overview", type="primary", on_click=queue_page, args=("Overview",))
    st.stop()

source_path = Path(active_video["source_path"])
video_hash = str(active_video["video_hash"])
source_filename = str(active_video["name"])
try:
    initial_metadata, first_frame = inspect_video(source_path)
except VideoError as exc:
    st.error(str(exc))
    st.stop()

camera_id = st.session_state.get(f"camera_id_{video_hash}", f"CAM-{video_hash[:8].upper()}")
applied_zone = st.session_state.get(f"zone_applied_{video_hash}", [])
artifacts = cached_analysis(video_hash, source_path, tracking_config, initial_metadata)
if artifacts is None:
    page_header(navigation, "Analysis is not ready", "This footage has not been processed with the current settings.")
    empty_state(
        "Analysis required",
        "Return to Overview and select Analyze footage. Changing advanced model settings also requires a new analysis.",
    )
    st.button("Return to Overview", type="primary", on_click=queue_page, args=("Overview",))
    st.stop()

try:
    tracks, metadata = load_artifacts(artifacts)
except (OSError, ValueError, TypeError) as exc:
    st.error(f"Processed results could not be loaded: {exc}")
    st.stop()

analysis_zone = (
    applied_zone
    if len(applied_zone) >= 3
    else [
        [0.0, 0.0],
        [float(metadata.width), 0.0],
        [float(metadata.width), float(metadata.height)],
        [0.0, float(metadata.height)],
    ]
)
tracks_for_detector = enrich_tracks_with_zone(tracks, analysis_zone)
conflict_config["zone_is_user_defined"] = len(applied_zone) >= 3

detector_error = None
try:
    raw_events = detect_conflicts(tracks_for_detector, analysis_zone, conflict_config)
except Exception as exc:  # detector errors must remain visible without taking down the UI
    raw_events = []
    detector_error = str(exc)
events, event_warnings = normalize_events(raw_events, metadata.fps)
events = deduplicate_events(events)

incident_detector_error = None
try:
    incidents = detect_suspected_collisions(
        tracks, events, source_video_id=video_hash, config=collision_config
    )
except Exception as exc:
    incidents = []
    incident_detector_error = str(exc)

persisted_reviews = {row["incident_id"]: row for row in list_reviews(video_hash)}
for incident in incidents:
    saved = persisted_reviews.get(incident["incident_id"])
    incident["review_status"] = saved["review_status"] if saved else "Uncertain"
    incident["camera_id"] = saved["camera_id"] if saved else camera_id
dispatch_notifications = list_notifications(video_hash)
statistics = safety_statistics(tracks, events, metadata.duration_seconds)

if detector_error:
    st.error(f"Prediction analysis failed: {detector_error}")
if incident_detector_error:
    st.error(f"Incident evidence analysis failed: {incident_detector_error}")
for warning in event_warnings:
    st.warning(warning)


if navigation == "Analysis":
    page_header(
        "Analysis",
        "Playback with context",
        "Follow tracked movement and inspect the moments NearMiss marked for attention.",
    )
    section_header("Footage", "Choose which annotations stay visible during playback.")
    control_cols = st.columns([.8, 1.15, .9, 4])
    show_boxes = control_cols[0].toggle("Boxes", value=True)
    show_trajectories = control_cols[1].toggle("Trajectories", value=True)
    show_track_ids = control_cols[2].toggle("Track IDs", value=True)
    annotation_progress = st.progress(0, text="Preparing annotated playback")
    try:
        annotated_path = render_annotated_video(
            artifacts,
            tracks,
            applied_zone,
            trail_length=tracking_config.trail_length,
            progress=progress_callback(annotation_progress),
            events=events,
            incidents=incidents,
            show_boxes=show_boxes,
            show_trajectories=show_trajectories,
            show_track_ids=show_track_ids,
        )
    except VideoError as exc:
        annotation_progress.empty()
        st.error(str(exc))
        st.stop()
    annotation_progress.empty()
    st.video(str(annotated_path))
    st.caption("Amber/coral marks are provisional computer-vision evidence, not verified collisions.")

    section_header("Summary")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Vehicles", statistics["vehicles_tracked"])
    metric_cols[1].metric("Potential conflicts", statistics["total_conflicts"])
    metric_cols[2].metric("Suspected incidents", len(incidents))
    metric_cols[3].metric("Footage analyzed", format_timestamp(metadata.duration_seconds))

    section_header("Timeline", "One marker per continuous vehicle interaction.")
    timeline = conflict_timeline_figure(events)
    if timeline is None:
        empty_state("No potential conflicts", "No qualifying warning was found with the current settings.")
    else:
        st.plotly_chart(timeline, width="stretch", key=f"timeline_{video_hash}")

    event_tab, map_tab, details_tab = st.tabs(["Events", "Safety map", "Details"])
    with event_tab:
        if not events:
            st.info("No potential conflict events are available.")
        else:
            rows = [
                {
                    "Time": format_timestamp(event.get("first_alert_timestamp_seconds")),
                    "Priority": event.get("severity"),
                    "Vehicles": event_pair_key(event),
                    "Time gap": event.get("arrival_time_gap_seconds"),
                    "Why it was flagged": event.get("description"),
                }
                for event in events
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with map_tab:
        opacity = st.slider("Map intensity", 0.10, 0.90, 0.52, 0.05)
        heatmap_rgb, heatmap_points = build_conflict_heatmap(first_frame, events, opacity)
        st.image(
            heatmap_rgb,
            caption="Concentration of deduplicated potential-conflict locations",
            width="stretch",
        )
        if not heatmap_points:
            st.info("No event locations are available, so no heat coloration was added.")
    with details_tab:
        st.caption(
            "Image-space measurements are approximate. Perspective, occlusion, lighting, and tracking changes affect results."
        )
        risk_cols = st.columns(4)
        risk_cols[0].metric("High", statistics["high_conflicts"])
        risk_cols[1].metric("Medium", statistics["medium_conflicts"])
        risk_cols[2].metric("Low", statistics["low_conflicts"])
        average_gap = statistics["average_arrival_gap_seconds"]
        risk_cols[3].metric("Average time gap", "—" if average_gap is None else f"{average_gap:.2f}s")
        if debug_mode:
            with st.expander("Technical diagnostics", expanded=False):
                diagnostics = diagnose_conflicts(tracks_for_detector, analysis_zone, conflict_config)
                stage_counts = pipeline_stage_counts(diagnostics, events)
                st.json(stage_counts)
                if diagnostics:
                    diagnostic_frame = pd.DataFrame(diagnostics)
                    st.dataframe(diagnostic_frame, width="stretch", height=320)
                    st.download_button(
                        "Download diagnostics CSV",
                        diagnostics_to_csv(diagnostics),
                        "debug_conflicts.csv",
                        "text/csv",
                    )
        with st.expander("Tracked object records", expanded=False):
            if tracks_for_detector:
                table = pd.DataFrame(tracks_for_detector)
                table["bbox"] = table["bbox"].apply(json.dumps)
                table["center"] = table["center"].apply(json.dumps)
                st.dataframe(table, width="stretch", height=340)

    with st.expander("Report and exports", expanded=False):
        heatmap_rgb, _ = build_conflict_heatmap(first_frame, events, 0.52)
        review_key = f"event_reviews_{video_hash}"
        st.session_state.setdefault(review_key, {})
        prediction_reviews = st.session_state[review_key]
        report_key = f"safety_report_{video_hash}"
        if st.button("Generate safety report", key=f"report_{video_hash}"):
            report_frames = {
                str(event.get("event_id")): cv2.cvtColor(
                    frame_at_timestamp(
                        source_path,
                        float(event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds", 0.0))),
                    ),
                    cv2.COLOR_BGR2RGB,
                )
                for event in events
            }
            st.session_state[report_key] = generate_safety_report(
                source_filename=source_filename,
                duration_seconds=metadata.duration_seconds,
                tracks=tracks,
                events=events,
                heatmap_rgb=heatmap_rgb,
                review_labels=prediction_reviews,
                event_frames=report_frames,
            )
            st.success("Safety report is ready.")
        if report_key in st.session_state:
            st.download_button(
                "Download safety report",
                st.session_state[report_key],
                "nearmiss_safety_report.pdf",
                "application/pdf",
            )
        reviewed_events = events_with_review_labels(events, prediction_reviews)
        export_payload = {
            "schema_version": "1.1",
            "source_filename": source_filename,
            "video_sha256": video_hash,
            "camera_id": camera_id,
            "video": asdict(metadata),
            "tracking_config": tracking_config.as_dict(),
            "conflict_config": conflict_config,
            "collision_evidence_config": collision_config,
            "zone_pixels": applied_zone,
            "zone_normalized": normalized_polygon(applied_zone, metadata.width, metadata.height),
            "tracks": tracks_for_detector,
            "events": reviewed_events,
            "suspected_collisions": incidents,
            "persistent_incident_reviews": list(persisted_reviews.values()),
            "simulated_dispatch_notifications": dispatch_notifications,
        }
        downloads = st.columns(5)
        downloads[0].download_button("Tracks CSV", tracks_to_csv(tracks_for_detector), "tracks.csv", "text/csv")
        downloads[1].download_button("Warnings CSV", events_to_csv(reviewed_events), "warnings.csv", "text/csv")
        downloads[2].download_button("Incidents CSV", events_to_csv(incidents), "incidents.csv", "text/csv")
        downloads[3].download_button(
            "Analysis JSON",
            json.dumps(export_payload, indent=2, default=json_default),
            "analysis.json",
            "application/json",
        )
        downloads[4].download_button(
            "Annotated video",
            annotated_path.read_bytes(),
            "nearmiss_annotated.mp4",
            "video/mp4",
        )


elif navigation == "Incidents":
    page_header(
        "Incidents",
        "Review the evidence",
        "Open a suspected incident, replay the moment, and record an operator decision.",
    )
    review_counts = {
        "Uncertain": sum(incident.get("review_status") == "Uncertain" for incident in incidents),
        "Confirmed": sum(incident.get("review_status") == "Confirmed Incident" for incident in incidents),
        "Dismissed": sum(incident.get("review_status") == "False Alarm" for incident in incidents),
    }
    count_cols = st.columns(3)
    count_cols[0].metric("Needs review", review_counts["Uncertain"])
    count_cols[1].metric("Confirmed", review_counts["Confirmed"])
    count_cols[2].metric("Dismissed", review_counts["Dismissed"])

    section_header("Incident queue", "One row per deduplicated suspected interaction.")
    if not incidents:
        empty_state(
            "No suspected incidents",
            "The evidence detector did not find a qualifying incident. Nothing has been fabricated for review.",
        )
    else:
        selected_key = f"selected_incident_{video_hash}"
        st.session_state.setdefault(selected_key, incidents[0]["incident_id"])
        for incident in incidents:
            with st.container(border=False):
                card_cols = st.columns([1.1, 1.3, 3.6, 1.2])
                card_cols[0].markdown(f"**{format_timestamp(incident['timestamp_seconds'])}**")
                card_cols[1].markdown(
                    f"Vehicles **#{incident['vehicle_a_track_id']} / #{incident['vehicle_b_track_id']}**"
                )
                card_cols[2].caption(incident["description"])
                status = incident.get("review_status", "Uncertain")
                tone = "success" if status == "Confirmed Incident" else "critical" if status == "False Alarm" else "warning"
                with card_cols[3]:
                    status_pill("Confirmed" if status == "Confirmed Incident" else "Dismissed" if status == "False Alarm" else "Uncertain", tone)
                    if st.button("Review", key=f"open_{incident['incident_id']}", width="stretch"):
                        st.session_state[selected_key] = incident["incident_id"]
                        st.rerun()
            st.markdown('<div class="nm-row-separator"></div>', unsafe_allow_html=True)

        selected_id = st.session_state[selected_key]
        selected_incident = next(
            (incident for incident in incidents if incident["incident_id"] == selected_id),
            incidents[0],
        )
        section_header("Evidence review")
        evidence_col, decision_col = st.columns([1.8, 1], gap="large")
        with evidence_col:
            impact_time = float(selected_incident["timestamp_seconds"])
            source_frame = frame_at_timestamp(source_path, impact_time)
            marked_frame = annotate_incident_frame(source_frame, selected_incident)
            st.image(
                cv2.cvtColor(marked_frame, cv2.COLOR_BGR2RGB),
                caption=f"Source frame · {format_timestamp(impact_time)}",
                width="stretch",
            )
            clip = extract_event_clip(
                artifacts, selected_incident["incident_id"], impact_time, 2.0, 2.0
            )
            st.video(str(clip))
            st.caption("Replay includes approximately two seconds before and after the suspected impact.")
        with decision_col:
            st.markdown(f"### {format_timestamp(selected_incident['timestamp_seconds'])}")
            st.write(
                f"Vehicles **#{selected_incident['vehicle_a_track_id']}** and "
                f"**#{selected_incident['vehicle_b_track_id']}**"
            )
            prediction_id = selected_incident.get("associated_prediction_event_id")
            if prediction_id:
                status_pill(f"Predicted earlier · {prediction_id}", "warning")
            else:
                status_pill("No earlier warning")
            st.markdown("#### Why it was flagged")
            for signal in selected_incident["detection_signals"]:
                st.write(f"• {signal.replace('_', ' ').capitalize()}")
            st.caption("Choose one operator decision. Only Confirm creates a simulated notification.")
            if st.button(
                "Confirm incident",
                type="primary",
                key=f"confirm_{selected_id}",
                width="stretch",
            ):
                review_incident(selected_incident, "Confirmed Incident", camera_id)
                st.toast("Confirmed · simulated dispatch item created")
                st.rerun()
            action_cols = st.columns(2)
            if action_cols[0].button("Dismiss", key=f"dismiss_{selected_id}", width="stretch"):
                review_incident(selected_incident, "False Alarm", camera_id)
                st.toast("Incident dismissed")
                st.rerun()
            if action_cols[1].button("Uncertain", key=f"uncertain_{selected_id}", width="stretch"):
                review_incident(selected_incident, "Uncertain", camera_id)
                st.toast("Saved for further review")
                st.rerun()
            with st.expander("Technical evidence", expanded=False):
                st.json(selected_incident.get("measurements", {}))

    with st.expander("Potential conflict predictions", expanded=False):
        if not events:
            st.info("No prediction candidates are available.")
        else:
            prediction_rows = [
                {
                    "Event": event.get("event_id"),
                    "Time": format_timestamp(event.get("first_alert_timestamp_seconds")),
                    "Priority": event.get("severity"),
                    "Vehicles": event_pair_key(event),
                    "Arrival gap": event.get("arrival_time_gap_seconds"),
                }
                for event in events
            ]
            st.dataframe(pd.DataFrame(prediction_rows), width="stretch", hide_index=True)


elif navigation == "Dispatch":
    page_header(
        "Dispatch",
        "Verified incident inbox",
        "Confirmed incidents appear here for acknowledgment. This is a local simulation; nothing is sent externally.",
    )
    new_count = sum(notification["status"] == "New" for notification in dispatch_notifications)
    acknowledged_count = sum(
        notification["status"] == "Acknowledged" for notification in dispatch_notifications
    )
    notify_cols = st.columns(3)
    notify_cols[0].metric("New", new_count)
    notify_cols[1].metric("Acknowledged", acknowledged_count)
    notify_cols[2].metric("Total generated", len(dispatch_notifications))

    section_header("Inbox", "Local simulation only. No external message was sent.")
    if not dispatch_notifications:
        empty_state(
            "Inbox is clear",
            "Confirm a suspected incident in Review to create a simulated dispatch notification.",
        )
        st.button("Open Incidents", type="primary", on_click=queue_page, args=("Incidents",))
    else:
        for notification in dispatch_notifications:
            summary = notification.get("summary", {})
            with st.container(border=False):
                header_cols = st.columns([3.4, 1.2])
                with header_cols[0]:
                    st.markdown(f"### {notification['notification_id']}")
                    st.caption(
                        f"{notification['camera_id']} · Generated {notification['generated_at']}"
                    )
                with header_cols[1]:
                    status_pill(
                        notification["status"],
                        "success" if notification["status"] == "Acknowledged" else "warning",
                    )
                detail_cols = st.columns(3)
                detail_cols[0].metric("Video time", format_timestamp(summary.get("timestamp_seconds")))
                vehicles = summary.get("vehicle_track_ids", [])
                detail_cols[1].metric(
                    "Vehicles",
                    " / ".join(f"#{value}" for value in vehicles if value is not None) or "—",
                )
                detail_cols[2].metric("Operator decision", "Confirmed")
                st.write(
                    "Evidence: "
                    + ", ".join(
                        str(signal).replace("_", " ")
                        for signal in summary.get("detection_signals", [])
                    )
                )
                st.caption("This record exists only inside NearMiss on this computer.")
                if notification["status"] != "Acknowledged" and st.button(
                    "Acknowledge",
                    key=f"ack_{notification['notification_id']}",
                    type="primary",
                ):
                    acknowledge_notification(notification["notification_id"])
                    st.toast("Notification acknowledged")
                    st.rerun()
            st.markdown('<div class="nm-row-separator"></div>', unsafe_allow_html=True)


st.markdown(
    '<div class="nm-footer">NearMiss · Experimental decision support · '
    'Not a validated crash detector or emergency-service system</div>',
    unsafe_allow_html=True,
)
