"""NearMiss premium Streamlit interface.

The UI is intentionally thin: detection, tracking, prediction, incident
evidence, persistence, and reporting remain in their existing backend modules.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from html import escape
from pathlib import Path

import cv2
import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image, ImageDraw

from conflict_detector import detect_conflicts, diagnose_conflicts
import nearmiss.store as store_module
from nearmiss import motion, presenter, streetlab
from nearmiss.config import DEFAULT_CONFLICT_CONFIG, TrackingConfig
from nearmiss.demo import (
    DEMO_CAMERA_ID,
    DEMO_SCENES,
    DEMO_TRACKING_CONFIG,
    demo_active_video,
    ensure_demo_assets,
    is_demo_video_id,
    provenance_for,
    reset_demo_reviews,
)
from nearmiss.events import events_to_csv, format_timestamp, normalize_events
from nearmiss.evidence_ui import render_evidence_page
from nearmiss.explain import explain_event, explain_incident, interaction_pattern, PATTERN_LABELS
from nearmiss.geometry import enrich_tracks_with_zone, normalized_polygon
from nearmiss.history import build_analysis_snapshot, save_analysis_snapshot
from nearmiss.history_ui import render_history_page
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG, detect_suspected_collisions
from nearmiss.investigation import evidence_track_ids
from nearmiss.investigation_ui import render_investigation_page
from nearmiss.report import generate_safety_report, report_cache_key
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
    "background": "#0B0B0C",
    "card": "#131315",
    "accent": "#F2A93B",
    "text": "#F5F5F4",
    "muted": "#A8A29E",
    "warning": "#F2A93B",
    "critical": "#E5676F",
    "success": "#6BBE9F",
    "border": "#27272A",
}

PAGES = [
    "Overview",
    "Analysis",
    "Investigation",
    "Incidents",
    "Explain & Share",
    "Dispatch",
    "Street Lab",
    "Library",
]
DEMO_STEPS = [
    ("Overview", "Start"),
    ("Analysis", "See the warnings"),
    ("Incidents", "Review evidence"),
    ("Dispatch", "Acknowledge"),
    ("Street Lab", "Plan follow-up"),
]
DEMO_STEP_HINTS = {
    "Analysis": "Play the annotated clip. Then open each warning below to see the measurements behind it.",
    "Incidents": "Open the suspected collision, replay the clip, and choose Confirm, Dismiss, or Uncertain.",
    "Dispatch": "A confirmed incident creates one local, simulated notification. Acknowledge it. Nothing leaves this computer.",
    "Street Lab": "Turn the reviewed patterns into a community review brief with clearly stated assumptions.",
}


st.set_page_config(
    page_title="NearMiss · Intersection safety evidence",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="auto",
)


def apply_styles() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
          --nm-bg:{COLORS['background']}; --nm-card:{COLORS['card']};
          --nm-signal:{COLORS['accent']}; --nm-text:{COLORS['text']};
          --nm-muted:{COLORS['muted']}; --nm-warning:{COLORS['warning']};
          --nm-critical:{COLORS['critical']}; --nm-success:{COLORS['success']};
          --nm-border:{COLORS['border']}; --nm-ease:cubic-bezier(.2,0,0,1);
        }}
        html {{ color-scheme:dark; }}
        html, body, [class*="css"] {{ font-family:Inter, "SF Pro Text", ui-sans-serif, -apple-system,
          BlinkMacSystemFont, "Segoe UI", sans-serif; -webkit-font-smoothing:antialiased;
          font-feature-settings:"tnum" 1, "cv11" 1; }}
        .stApp {{ background:var(--nm-bg); color:var(--nm-text); }}
        [data-testid="stHeader"] {{ background:rgba(11,11,12,.92); }}
        [data-testid="stAppDeployButton"], #MainMenu {{ display:none !important; }}
        [data-testid="stMainBlockContainer"] {{ max-width:1180px; padding:4.5rem 3rem 6rem; }}
        [data-testid="stSidebar"] {{ background:#0E0E10; border-right:1px solid var(--nm-border); }}
        /* Fixed width only on wide screens and only while expanded, so the
           collapsed/overlay sidebar on narrow screens never covers content. */
        @media (min-width: 901px) {{
          [data-testid="stSidebar"][aria-expanded="true"] {{ min-width:236px !important;
            max-width:236px !important; }}
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ padding:1.35rem .8rem; }}
        .nm-brand {{ display:flex; align-items:center; gap:.6rem; padding:.2rem .55rem 2rem; }}
        .nm-brand-mark {{ width:22px; height:22px; flex:none; }}
        .nm-brand-name {{ color:var(--nm-text); font-size:1rem; font-weight:650; letter-spacing:-.015em; }}
        .nm-brand-sub {{ color:#78716C; font-size:.64rem; font-weight:600; letter-spacing:.13em;
          text-transform:uppercase; margin-top:.2rem; }}
        [data-testid="stSidebar"] [role="radiogroup"] {{ gap:.12rem; }}
        [data-testid="stSidebar"] [role="radiogroup"] label {{
          min-height:2.35rem; padding:.48rem .62rem; border-radius:6px; border:1px solid transparent;
          border-left:2px solid transparent; color:#8D8D96;
          transition:background-color 180ms var(--nm-ease), color 180ms var(--nm-ease);
        }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background:#17171A; color:#D6D3D1; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
          background:#1A1A1D; border-left-color:var(--nm-signal); }}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
          color:var(--nm-text); font-weight:570; }}
        [data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child {{ display:none; }}
        .nm-page-kicker {{ color:var(--nm-signal); font-size:.72rem; line-height:1.4; letter-spacing:.12em;
          text-transform:uppercase; font-weight:620; margin-bottom:1rem; }}
        .nm-page-title {{ color:var(--nm-text); font-size:2.7rem; line-height:1.06; letter-spacing:-.045em;
          font-weight:640; margin:0; max-width:780px; }}
        .nm-page-subtitle {{ color:#B5B0AA; font-size:1.02rem; line-height:1.65; max-width:680px;
          margin:.9rem 0 2.4rem; }}
        .nm-section-title {{ color:var(--nm-text); font-size:1.02rem; font-weight:600;
          letter-spacing:-.012em; margin:2.6rem 0 .32rem; }}
        .nm-section-copy {{ color:#8A847E; font-size:.84rem; line-height:1.55; margin:0 0 1.1rem; max-width:720px; }}
        .nm-status {{ display:inline-flex; align-items:center; border-radius:999px; padding:.2rem .52rem;
          font-size:.7rem; line-height:1.25; font-weight:580; border:1px solid var(--nm-border);
          color:#A8A29E; }}
        .nm-status.success {{ color:#8ED0B6; border-color:#2B4A3F; }}
        .nm-status.warning {{ color:#F5C373; border-color:#5A4321; }}
        .nm-status.critical {{ color:#EE9197; border-color:#5C3034; }}
        .nm-empty {{ border-top:1px solid var(--nm-border); border-bottom:1px solid var(--nm-border);
          padding:3rem 1rem; text-align:center; color:#8A847E; }}
        .nm-source {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.35rem .75rem;
          border-left:3px solid #52525B; padding:.55rem .9rem; margin:0 0 1.4rem;
          color:#B5B0AA; font-size:.82rem; line-height:1.5; background:#111113; border-radius:0 6px 6px 0; }}
        .nm-source.synthetic {{ border-left-color:var(--nm-signal); background:#17130C; color:#E7D8BF; }}
        .nm-source-tag {{ font-weight:700; letter-spacing:.1em; font-size:.7rem; color:#A8A29E; }}
        .nm-source.synthetic .nm-source-tag {{ color:#0B0B0C; background:var(--nm-signal);
          padding:.12rem .42rem; border-radius:3px; }}
        .nm-steps {{ display:flex; flex-wrap:wrap; gap:.3rem 1.4rem; list-style:none; margin:0 0 .5rem;
          padding:.75rem 0; border-top:1px solid var(--nm-border); border-bottom:1px solid var(--nm-border); }}
        .nm-steps li {{ color:#6B6661; font-size:.76rem; }}
        .nm-steps li strong {{ color:#8A847E; margin-right:.35rem; font-weight:600; }}
        .nm-steps li.done {{ color:#A8A29E; }}
        .nm-steps li.current {{ color:var(--nm-text); }}
        .nm-steps li.current strong {{ color:var(--nm-signal); }}
        .nm-hint {{ color:#B5B0AA; font-size:.86rem; margin:.65rem 0 .35rem; }}
        .nm-pipeline {{ list-style:none; padding:0; margin:0; border-top:1px solid var(--nm-border); }}
        .nm-pipeline li {{ display:grid; grid-template-columns:7.5rem 1fr; gap:1rem; padding:.9rem 0;
          border-bottom:1px solid var(--nm-border); font-size:.86rem; color:#B5B0AA; line-height:1.55; }}
        .nm-pipeline li strong {{ color:var(--nm-text); font-weight:600; }}
        .nm-pipeline .nm-tag {{ display:inline-block; font-size:.64rem; letter-spacing:.08em;
          text-transform:uppercase; margin-left:.4rem; color:var(--nm-signal); }}
        .nm-pipeline .nm-tag.sim {{ color:#A8A29E; }}
        .nm-explain {{ border-left:2px solid var(--nm-signal); padding:.2rem 0 .2rem 1rem; margin:.4rem 0 1rem; }}
        .nm-explain h4 {{ color:var(--nm-text); font-size:.95rem; font-weight:600; margin:0 0 .45rem; }}
        .nm-explain ul {{ margin:0; padding-left:1.1rem; color:#C9C4BE; font-size:.86rem; line-height:1.6; }}
        .nm-explain p {{ color:#8A847E; font-size:.78rem; margin:.5rem 0 0; }}
        .nm-file-meta {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1.2rem 1rem; margin-top:1.25rem; }}
        .st-key-nearmiss_hero {{ position:relative; isolation:isolate; overflow:hidden;
          min-height:760px; margin:-5rem -3rem 4.5rem; padding:7rem clamp(2rem,6vw,6rem) 4rem;
          background-image:url('/app/static/nearmiss-hero.jpg'); background-size:cover;
          background-position:center 58%; border-bottom:1px solid #27272A;
          display:flex !important; flex-direction:column; justify-content:center; align-items:center; }}
        .st-key-nearmiss_hero::before {{ content:""; position:absolute; inset:0; z-index:-1;
          background:rgba(5,7,10,.68); }}
        .st-key-nearmiss_hero > div {{ width:100%; }}
        .nm-hero-mark {{ color:rgba(255,255,255,.68); font-size:.68rem; font-weight:550;
          letter-spacing:.16em; text-transform:uppercase; text-align:center; margin-bottom:2rem; }}
        .nm-hero-title {{ color:#FFFFFF; font-size:clamp(3.6rem,6.4vw,6.1rem); line-height:.98;
          letter-spacing:-.065em; font-weight:320; text-align:center; max-width:1050px;
          margin:0 auto !important; font-size:clamp(3.6rem,6.4vw,6.1rem) !important;
          line-height:.98 !important; font-weight:320 !important; }}
        .nm-hero-title em {{ font-family:Georgia,"Times New Roman",serif; font-weight:400;
          letter-spacing:-.045em; }}
        .nm-hero-copy {{ color:rgba(255,255,255,.78); font-size:1.02rem; line-height:1.65;
          text-align:center; max-width:650px; margin:1.65rem auto 2rem !important; }}
        .nm-hero-proof {{ color:rgba(255,255,255,.58); font-size:.7rem; text-align:center;
          letter-spacing:.02em; margin-top:1rem; }}
        .st-key-nearmiss_hero [data-testid="stFileUploader"] {{ width:min(620px,100%);
          margin-left:auto !important; margin-right:auto !important; }}
        .st-key-nearmiss_hero [data-testid="stFileUploader"] > label {{ display:none; }}
        .st-key-nearmiss_hero [data-testid="stFileUploaderDropzone"] {{
          background:rgba(5,5,7,.42); border-color:rgba(255,255,255,.30);
          backdrop-filter:blur(5px); -webkit-backdrop-filter:blur(5px); }}
        .st-key-nearmiss_hero [data-testid="stFileUploaderDropzone"]:hover {{
          background:rgba(5,5,7,.56); border-color:rgba(255,255,255,.58); }}
        .st-key-nearmiss_hero [data-testid="stFileUploaderDropzone"] button {{
          background:#C7C9CC !important; border-color:#C7C9CC !important; color:#111214 !important;
          box-shadow:none !important; }}
        .st-key-nearmiss_hero [data-testid="stFileUploaderDropzone"] button:hover {{
          background:#E1E2E4 !important; border-color:#E1E2E4 !important; }}
        .st-key-nearmiss_hero .stButton {{ display:flex; justify-content:center; }}
        .st-key-nearmiss_hero .stButton > button {{ width:min(620px,100%); min-height:3rem;
          font-size:1rem; }}
        .nm-hero-demo-note {{ color:rgba(255,255,255,.78); font-size:.8rem; text-align:center;
          margin:.55rem auto 1.6rem; max-width:620px; line-height:1.5; }}
        .nm-hero-or {{ color:rgba(255,255,255,.68); font-size:.72rem; letter-spacing:.12em;
          text-transform:uppercase; text-align:center; margin:0 auto .7rem; }}
        .nm-hero-credit {{ color:rgba(255,255,255,.62); font-size:.68rem; text-align:center;
          margin-top:.45rem; }}
        /* Text below the photograph sits on an opaque panel for legibility. */
        .st-key-overview_explainer {{ background:var(--nm-bg); max-width:1180px; margin:0 auto;
          padding:1rem 3rem 5rem; border-radius:10px 10px 0 0; }}
        /* The story's diagram is position:sticky inside its component; keep every
           wrapper between it and the page scroller from clipping. */
        .st-key-overview_explainer, .st-key-overview_explainer [data-testid="stVerticalBlock"],
        .st-key-overview_explainer [data-testid="stElementContainer"] {{ overflow:visible !important; }}
        .nm-file-meta-item {{ border-top:1px solid var(--nm-border); padding-top:.75rem; min-width:0; }}
        .nm-file-meta-label {{ color:#8A847E; font-size:.7rem; margin-bottom:.28rem; }}
        .nm-file-meta-value {{ color:#E7E5E4; font-size:.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .nm-row-separator {{ height:1px; background:var(--nm-border); margin:.65rem 0; }}
        .nm-meta {{ color:#8A847E; font-size:.78rem; line-height:1.6; }}
        [data-testid="stMetric"] {{ background:transparent; border:0; border-top:1px solid var(--nm-border);
          padding:1rem 0 .65rem; border-radius:0; box-shadow:none; min-height:90px; }}
        [data-testid="stMetricLabel"] {{ color:#8A847E; font-size:.72rem; }}
        [data-testid="stMetricValue"] {{ color:var(--nm-text); font-size:1.8rem; font-weight:580; letter-spacing:-.04em; }}
        [data-testid="stVerticalBlockBorderWrapper"] {{ background:transparent;
          border-color:var(--nm-border) !important; border-radius:6px !important; }}
        [data-testid="stFileUploaderDropzone"] {{ background:#0F0F11; border:1px dashed #44403C; border-radius:7px;
          padding:1.15rem; transition:border-color 180ms var(--nm-ease), background-color 180ms var(--nm-ease); }}
        [data-testid="stFileUploaderDropzone"]:hover {{ border-color:#78716C; background:#131315; }}
        .stButton > button, .stDownloadButton > button {{ border-radius:6px; min-height:2.45rem; font-weight:560;
          border:1px solid #33302D; background:#161618; color:#E7E5E4;
          transition:background-color 180ms var(--nm-ease), border-color 180ms var(--nm-ease), color 180ms var(--nm-ease); }}
        .stButton > button:hover, .stDownloadButton > button:hover {{ background:#1E1E21; border-color:#57534E; color:#FAFAF9; }}
        .stButton > button:active, .stDownloadButton > button:active {{ transform:translateY(1px); }}
        .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{ background:var(--nm-signal);
          color:#0B0B0C; border-color:var(--nm-signal); }}
        .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{
          color:#0B0B0C; background:#F6BD62; border-color:#F6BD62; }}
        .stButton > button[kind="primary"] p {{ color:#0B0B0C; }}
        /* Keyboard focus is always visible, in the signal color. */
        :where(button, a, summary, [role="tab"], [role="option"], [tabindex]):focus-visible,
        .stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
        [data-testid="stExpander"] summary:focus-visible {{
          outline:2px solid var(--nm-signal) !important; outline-offset:2px; box-shadow:none !important; }}
        [data-testid="stSidebar"] label:has(input:focus-visible),
        [data-testid="stCheckbox"] label:has(input:focus-visible),
        [data-testid="stRadio"] label:has(input:focus-visible) {{
          outline:2px solid var(--nm-signal); outline-offset:2px; border-radius:6px; }}
        [data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within,
        [data-baseweb="textarea"]:focus-within {{ box-shadow:0 0 0 2px var(--nm-signal) !important; }}
        [role="slider"]:focus-visible {{ box-shadow:0 0 0 3px var(--nm-signal) !important; }}
        /* Selected multiselect chips: the light theme primary would render white
           text on a white chip, so pin a dark chip with light text and icon. */
        [data-baseweb="tag"], span[data-tag] {{ background:#24211D !important;
          border:1px solid #57534E !important; color:#F5F5F4 !important; }}
        [data-baseweb="tag"] span, span[data-tag] span,
        [data-baseweb="tag"] [title], span[data-tag] [title] {{ color:#F5F5F4 !important; }}
        [data-baseweb="tag"] svg, span[data-tag] svg {{ color:#D6D3D1 !important;
          fill:currentColor !important; }}
        [data-baseweb="tag"]:hover, span[data-tag]:hover {{ background:#2E2A25 !important;
          border-color:#78716C !important; }}
        [data-baseweb="tag"] [role="presentation"]:hover svg,
        span[data-tag] [role="presentation"]:hover svg {{ color:var(--nm-signal) !important; }}
        [data-baseweb="tag"]:focus-within, span[data-tag]:focus-within,
        [data-baseweb="tag"]:focus-visible, span[data-tag]:focus-visible {{
          outline:2px solid var(--nm-signal) !important; outline-offset:1px; }}
        [data-testid="stTabs"] [role="tablist"] {{ gap:1.35rem; border-bottom:1px solid var(--nm-border); }}
        [data-testid="stTabs"] button {{ color:#8A847E; padding:.65rem 0; font-size:.82rem; }}
        [data-testid="stTabs"] button[aria-selected="true"] {{ color:var(--nm-text); }}
        [data-testid="stDataFrame"] {{ border:1px solid var(--nm-border); border-radius:6px; overflow:hidden; }}
        [data-testid="stAlert"] {{ border-radius:6px; border-width:1px; background:#131315; }}
        [data-testid="stExpander"] details {{ border-color:var(--nm-border); border-radius:6px; background:transparent; }}
        [data-testid="stCheckbox"] label:has(input[role="switch"]:checked) > div:nth-of-type(1) {{
          background-color:var(--nm-signal) !important; }}
        [data-testid="stProgress"] > div > div {{ background:var(--nm-signal); }}
        hr {{ border-color:var(--nm-border) !important; opacity:1; }}
        .nm-footer {{ color:#57534E; font-size:.68rem; margin-top:3rem; line-height:1.6; }}
        @media (max-width: 900px) {{
          [data-testid="stMainBlockContainer"] {{ padding:4.2rem 1.4rem 4rem; }}
          .nm-page-title {{ font-size:2.15rem; }}
          .st-key-overview_media [data-testid="stHorizontalBlock"] {{ flex-direction:column; }}
          .st-key-overview_media [data-testid="stColumn"] {{ width:100% !important;
            flex:1 1 100% !important; }}
          .st-key-nearmiss_hero {{ margin:-4.5rem -1.5rem 3.5rem; padding:6rem 2rem 3rem;
            min-height:720px; }}
          .st-key-overview_explainer {{ padding:1rem 1.4rem 4rem; }}
        }}
        @media (max-width: 640px) {{
          [data-testid="stMainBlockContainer"] {{ padding:4rem 1rem 4rem; }}
          .nm-page-title {{ font-size:1.85rem; }}
          .nm-page-subtitle {{ margin-bottom:1.8rem; }}
          .nm-pipeline li {{ grid-template-columns:1fr; gap:.2rem; }}
          .st-key-nearmiss_hero {{ margin:-4.2rem -1rem 3rem; padding:5.5rem 1.1rem 2.5rem;
            min-height:680px; }}
          .nm-hero-title {{ font-size:3rem !important; }}
          .nm-hero-copy {{ font-size:.92rem; }}
          .st-key-overview_explainer {{ padding:1rem 1rem 4rem; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
          *, *::before, *::after {{ transition-duration:.01ms !important;
            animation-duration:.01ms !important; animation-iteration-count:1 !important;
            scroll-behavior:auto !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


BRAND_MARK = (
    '<svg class="nm-brand-mark" viewBox="0 0 22 22" aria-hidden="true">'
    '<rect x="8" y="0" width="6" height="22" fill="#2A2A2E"/><rect x="0" y="8" width="22" height="6" fill="#2A2A2E"/>'
    '<circle cx="11" cy="11" r="4.2" fill="none" stroke="#F2A93B" stroke-width="2"/></svg>'
)


def apply_overview_shell() -> None:
    """Let the Overview image span the viewport while keeping the sidebar optional."""
    st.markdown(
        """
        <style>
        .stApp {
          background-image:url('/app/static/nearmiss-hero.jpg') !important;
          background-size:cover !important;
          background-position:center center !important;
          background-attachment:fixed !important;
        }
        [data-testid="stAppViewContainer"], [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] { background:transparent !important; }
        [data-testid="stMainBlockContainer"] {
          max-width:none !important; padding:0 !important; margin:0 !important;
        }
        [data-testid="stHeader"] { background:transparent !important; }
        [data-testid="stSidebar"] {
          background:rgba(9,10,12,.82) !important;
          border-right:1px solid rgba(199,201,204,.18) !important;
          backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px);
        }
        [data-testid="stSidebar"][data-collapsed="true"] {
          width:0 !important; min-width:0 !important; max-width:0 !important;
          flex:0 0 0 !important; border:0 !important; backdrop-filter:none !important;
        }
        [data-testid="stSidebarCollapsedControl"] button,
        [data-testid="stSidebarCollapseButton"] button {
          color:#D6D7D9 !important; background:rgba(16,17,20,.58) !important;
          border:1px solid rgba(199,201,204,.24) !important; border-radius:4px !important;
        }
        .st-key-nearmiss_hero {
          width:100% !important; min-height:100vh !important; margin:0 !important;
          padding:clamp(5rem,9vh,8rem) clamp(1.25rem,7vw,8rem) 4rem !important;
          background-image:none !important; border:0 !important;
        }
        .st-key-nearmiss_hero::before { background:rgba(6,8,11,.55) !important; }
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
    st.markdown(f'<h2 class="nm-section-title">{title}</h2>', unsafe_allow_html=True)
    if copy:
        st.markdown(f'<p class="nm-section-copy">{copy}</p>', unsafe_allow_html=True)


def status_pill(label: str, tone: str = "") -> None:
    css_class = f"nm-status {tone}".strip()
    st.markdown(f'<span class="{css_class}">{escape(label)}</span>', unsafe_allow_html=True)


def empty_state(title: str, message: str) -> None:
    st.markdown(
        f'<div class="nm-empty"><strong style="color:{COLORS["text"]}">{title}</strong>'
        f'<div style="margin-top:.45rem">{message}</div></div>',
        unsafe_allow_html=True,
    )


def source_banner(provenance: dict, source_name: str) -> None:
    synthetic = provenance.get("data_source") == "synthetic_demo"
    st.markdown(
        f'<div class="nm-source{" synthetic" if synthetic else ""}" role="note" aria-label="Data source">'
        f'<span class="nm-source-tag">{escape(provenance["label"].upper())}</span>'
        f'<span>{escape(provenance["summary"])}'
        + (f" {escape(provenance['pipeline_boundary'])}" if synthetic else f" · {escape(source_name)}")
        + "</span></div>",
        unsafe_allow_html=True,
    )


def demo_steps(current: str) -> None:
    names = [name for name, _ in DEMO_STEPS]
    position = names.index(current) if current in names else -1
    items = []
    for index, (name, label) in enumerate(DEMO_STEPS):
        state = "current" if index == position else "done" if index < position else ""
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="{state}"{aria}><strong>{index + 1}</strong>{escape(label)}</li>')
    st.markdown(
        '<ol class="nm-steps" aria-label="Guided demo steps">' + "".join(items) + "</ol>",
        unsafe_allow_html=True,
    )
    hint = DEMO_STEP_HINTS.get(current)
    if hint:
        st.markdown(f'<p class="nm-hint">{escape(hint)}</p>', unsafe_allow_html=True)
    if 0 <= position < len(DEMO_STEPS) - 1:
        next_page, next_label = DEMO_STEPS[position + 1]
        st.button(
            f"Next: {next_label} →",
            key=f"demo_next_{current}",
            on_click=queue_page,
            args=(next_page,),
        )


def explanation_block(explanation: dict, extra: str | None = None) -> None:
    bullets = "".join(f"<li>{escape(text)}</li>" for text in explanation["bullets"])
    note = f"<p>{escape(extra)}</p>" if extra else ""
    st.markdown(
        f'<div class="nm-explain"><h4>{escape(explanation["headline"])}</h4><ul>{bullets}</ul>'
        f'{note}<p>{escape(explanation["caveat"])}</p></div>',
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
        color_discrete_map={"LOW": "#D9C27A", "MEDIUM": COLORS["warning"], "HIGH": COLORS["critical"]},
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
        xaxis={"gridcolor": "#29272A"},
        yaxis={"gridcolor": "#29272A"},
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
                "streetlab_",
            )
        ):
            del st.session_state[key]
    st.session_state.pop("active_video", None)
    st.session_state.pop("previous_real_video", None)
    st.session_state.pop("history_current_snapshot", None)
    st.session_state.pop("history_current_fingerprint", None)


def analysis_settings_fingerprint(
    video_hash: str, tracking: TrackingConfig, conflict: dict, collision: dict, zone: list
) -> str:
    """Identity of every setting that changes analysis output for one video."""

    return json.dumps(
        {
            "video": video_hash,
            "tracking": asdict(tracking),
            # zone_is_user_defined is derived from the zone, which is included.
            "conflict": {k: v for k, v in conflict.items() if k != "zone_is_user_defined"},
            "collision": collision,
            "zone": zone,
        },
        sort_keys=True,
        default=str,
    )


def open_investigation(video_hash: str, frame_index: int, track_ids: list[int] | None = None) -> None:
    prefix = f"investigation_{video_hash}"
    st.session_state[f"{prefix}_frame"] = frame_index
    if track_ids:
        # Focus the incident participants; clearing the filters restores their
        # "everything" defaults so the participants cannot be filtered out.
        st.session_state.pop(f"{prefix}_types", None)
        st.session_state.pop(f"{prefix}_classes", None)
        st.session_state[f"{prefix}_tracks"] = list(track_ids)
    st.session_state["_next_page"] = "Investigation"


def start_demo() -> None:
    """Generate (or reuse) the labeled synthetic demo and open its results."""

    current = st.session_state.get("active_video")
    if current and not is_demo_video_id(current.get("video_hash")):
        st.session_state["previous_real_video"] = current
    try:
        demo_video = demo_active_video()
    except VideoError as exc:
        st.session_state["_demo_error"] = str(exc)
        return
    st.session_state["active_video"] = demo_video
    st.session_state.setdefault(f"camera_id_{demo_video['video_hash']}", DEMO_CAMERA_ID)
    st.session_state["_next_page"] = "Analysis"


def open_presenter() -> None:
    """Enter Presenter mode on the active footage, or on the guided demo."""

    current = st.session_state.get("active_video")
    return_page = st.session_state.get("navigation", "Overview")
    if not current or not Path(current["source_path"]).exists():
        start_demo()
        if "_demo_error" in st.session_state:
            return
        return_page = st.session_state.get("_next_page", "Analysis")
    presenter.enter(st.session_state, return_page=return_page)


def leave_demo() -> None:
    """Return to uploaded footage (the previous upload when there was one)."""

    previous = st.session_state.pop("previous_real_video", None)
    if previous and Path(previous["source_path"]).exists():
        st.session_state["active_video"] = previous
    else:
        st.session_state.pop("active_video", None)
    st.session_state["upload_generation"] = st.session_state.get("upload_generation", 0) + 1
    st.session_state["_next_page"] = "Overview"


def reset_demo(video_hash: str) -> None:
    reviews, notifications = reset_demo_reviews(video_hash)
    st.session_state["_toast"] = (
        f"Demo reset · cleared {reviews} review(s) and {notifications} simulated notification(s)"
    )


def demo_controls(video_hash: str, key: str) -> None:
    cols = st.columns([1, 1, 2])
    cols[0].button("Return to real footage", key=f"leave_demo_{key}", on_click=leave_demo, width="stretch")
    cols[1].button(
        "Reset demo reviews",
        key=f"reset_demo_{key}",
        on_click=reset_demo,
        args=(video_hash,),
        width="stretch",
        help="Clears decisions and simulated notifications for the synthetic demo only. "
        "Reviews of uploaded footage are never touched.",
    )


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
if st.session_state["navigation"] not in PAGES:
    st.session_state["navigation"] = "Overview"
if "_next_page" in st.session_state:
    requested_page = st.session_state.pop("_next_page")
    st.session_state["navigation"] = legacy_navigation.get(requested_page, requested_page)
if "_toast" in st.session_state:
    st.toast(st.session_state.pop("_toast"))
presenting = presenter.is_active(st.session_state)

active_video = st.session_state.get("active_video")
active_is_demo = bool(active_video) and is_demo_video_id(active_video.get("video_hash"))
if active_is_demo and not Path(active_video["source_path"]).exists():
    # The processed-video cache was cleared; regenerate the deterministic demo.
    active_video = st.session_state["active_video"] = demo_active_video()
if st.session_state["navigation"] == "Overview" and not presenting and not (
    active_video and Path(active_video["source_path"]).exists()
):
    # Full-photo landing only; pages with evidence keep the dark interface.
    apply_overview_shell()


with st.sidebar:
    st.markdown(
        f'<div class="nm-brand">{BRAND_MARK}<div><div class="nm-brand-name">NearMiss</div>'
        '<div class="nm-brand-sub">Intersection safety evidence</div></div></div>',
        unsafe_allow_html=True,
    )
    navigation = st.radio(
        "Workspace",
        PAGES,
        key="navigation",
        label_visibility="collapsed",
        # Choosing any page is also the way out of Presenter mode.
        on_change=presenter.stop,
        args=(st.session_state,),
    )
    st.markdown("<div style='height:.75rem'></div>", unsafe_allow_html=True)
    if presenting:
        st.button(
            "Exit presenter mode", key="presenter_exit_sidebar", on_click=presenter.leave,
            args=(st.session_state,), width="stretch",
        )
    else:
        st.button(
            "Presenter mode", key="presenter_open_sidebar", on_click=open_presenter, width="stretch",
            help="Five keyboard-driven steps: warning, source frame, incident review, Street Lab "
            "and exported brief. Uses the guided demo when no footage is open. Read-only.",
        )

    with st.expander("Advanced settings", expanded=False):
        if active_is_demo:
            st.caption(
                "Synthetic demo: tracks are scripted, so model settings do not apply. "
                "Prediction and incident thresholds below still do."
            )
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


def render_pipeline_explainer() -> None:
    section_header(
        "How a warning is earned",
        "Each stage has an explicit, adjustable threshold. Nothing is a probability or a safety rating.",
    )
    st.markdown(
        '<ol class="nm-pipeline">'
        "<li><strong>Track</strong><span>Pretrained YOLO detects road users and ByteTrack keeps their IDs. "
        "The bottom-center of each box approximates where it touches the road."
        '<span class="nm-tag">implemented</span></span></li>'
        f"<li><strong>Predict</strong><span>Recent motion is projected ahead "
        f"{conflict_config['prediction_horizon_seconds']:.1f}s. A warning needs projected paths that meet, "
        f"an arrival gap of at most {conflict_config['low_time_gap_seconds']:.2f}s "
        f"(HIGH at ≤ {conflict_config['high_time_gap_seconds']:.2f}s), and "
        f"{conflict_config['high_persistence_frames']} consecutive confirming frames for HIGH."
        '<span class="nm-tag">implemented</span></span></li>'
        "<li><strong>Detect</strong><span>A separate check looks for suspected collisions: persistent box "
        "contact, converging motion beforehand, and a motion response such as sudden braking. "
        "It does not depend on the prediction."
        '<span class="nm-tag">implemented</span></span></li>'
        "<li><strong>Review</strong><span>A person confirms, dismisses, or leaves each suspected incident "
        "uncertain. Decisions are saved locally in SQLite."
        '<span class="nm-tag">implemented</span></span></li>'
        "<li><strong>Notify</strong><span>Confirmed incidents appear in a local inbox for acknowledgment. "
        "Nothing is sent to emergency services or anyone else."
        '<span class="nm-tag sim">simulated</span></span></li>'
        "</ol>",
        unsafe_allow_html=True,
    )


if navigation == "Overview" and not presenting:
    if "_demo_error" in st.session_state:
        st.error(f"The synthetic demo could not be generated: {st.session_state.pop('_demo_error')}")

    if active_is_demo:
        page_header(
            "Guided demo",
            "A staged intersection, run through the real pipeline.",
            "The footage and track rows are generated locally. Everything after tracking (prediction, "
            "incident evidence, review, and the simulated inbox) is the same code used for uploaded footage.",
        )
        source_banner(provenance_for(active_video["video_hash"]), active_video["name"])
        demo_steps("Overview")
        section_header("What was staged", "Compare this script with what the detectors actually return on the next page.")
        st.dataframe(
            pd.DataFrame(DEMO_SCENES).rename(columns={"window": "Time", "scene": "Scene", "staged": "Scripted motion"}),
            hide_index=True,
            width="stretch",
        )
        demo_controls(active_video["video_hash"], "overview")
        render_pipeline_explainer()
        st.stop()

    if not active_video or not Path(active_video["source_path"]).exists():
        with st.container(key="nearmiss_hero"):
            st.markdown(
                '<div class="nm-hero-mark">NearMiss / Intersection safety</div>'
                '<h1 class="nm-hero-title">See the moments<br><em>before impact.</em></h1>'
                '<p class="nm-hero-copy">Turn fixed-camera traffic footage into reviewable '
                'vehicle trajectories, potential conflict warnings, and operator-ready evidence.</p>',
                unsafe_allow_html=True,
            )
            st.button("Start guided demo", type="primary", on_click=start_demo, key="start_demo")
            st.markdown(
                '<p class="nm-hero-demo-note">About 2 minutes. Uses a generated, clearly labeled '
                "intersection: no upload, network, or model download needed.</p>"
                '<div class="nm-hero-or">Or analyze your own footage</div>',
                unsafe_allow_html=True,
            )
            uploaded = st.file_uploader(
                "Traffic camera video",
                type=["mp4"],
                key=f'video_upload_{st.session_state["upload_generation"]}',
                help="Use original footage rather than a previously annotated export.",
            )
            st.markdown(
                '<div class="nm-hero-proof">Local processing &nbsp;·&nbsp; Human verification required '
                "&nbsp;·&nbsp; No emergency-service connection</div>"
                '<div class="nm-hero-credit">Background photograph is illustrative context only, '
                "not analyzed footage.</div>",
                unsafe_allow_html=True,
            )
    else:
        page_header(
            "Overview",
            "Turn traffic footage into reviewable evidence.",
            "NearMiss follows vehicle movement, surfaces possible conflicts, and keeps every operator "
            "decision connected to the original video.",
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
        with st.container(key="overview_explainer"):
            story = motion.demo_story(conflict_config, collision_config)
            if story is not None:
                motion.render_story(story)
                st.button(
                    "Present this walkthrough", key="presenter_open_story", on_click=open_presenter,
                    help="Opens Presenter mode on the guided demo. Use ← and → to move between steps.",
                )
            render_pipeline_explainer()
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
    st.button("Try the guided demo instead", on_click=start_demo, key="start_demo_secondary")
    render_pipeline_explainer()
    st.stop()


threshold_box = None
if navigation == "Library" and not presenting:
    page_header(
        "Library",
        "Saved analyses",
        "Compare saved runs by candidate counts and footage length. No footage is stored.",
    )
    snapshot = st.session_state.get("history_current_snapshot")
    if snapshot:
        # Only offer the snapshot if it was built from this video with exactly the
        # current tracking, prediction, incident and zone settings.
        current_hash = str(active_video.get("video_hash")) if active_video else ""
        expected = analysis_settings_fingerprint(
            current_hash,
            DEMO_TRACKING_CONFIG if active_is_demo else tracking_config,
            conflict_config,
            collision_config,
            st.session_state.get(f"zone_applied_{current_hash}", []),
        )
        if (
            not active_video
            or snapshot.get("video_sha256") != current_hash
            or st.session_state.get("history_current_fingerprint") != expected
        ):
            snapshot = None
            if active_video:
                st.info(
                    "Settings changed since the last analysis view. Open Analysis to "
                    "recompute before saving this run to the Library."
                )
    render_history_page(
        current_snapshot=snapshot,
        database_path=store_module.DEFAULT_DATABASE_PATH,
    )
    if active_video and Path(active_video["source_path"]).exists():
        # Contained and collapsed; only an open box runs the analysis below.
        threshold_box = st.expander(
            "Explore one threshold", key="library_threshold", on_change="rerun"
        )
    if threshold_box is None or not threshold_box.open:
        st.stop()


if not active_video or not Path(active_video["source_path"]).exists():
    if presenting:
        presenter.render_unavailable("The footage for Presenter mode is no longer available.")
        st.stop()
    page_header(navigation, "No footage selected", "Choose a source video, or start the guided demo.")
    empty_state("Footage required", "Upload an MP4 on Overview, or open the labeled synthetic demo.")
    cols = st.columns([1, 1, 3])
    cols[0].button("Start guided demo", type="primary", on_click=start_demo, key="gate_demo")
    cols[1].button("Open Overview", on_click=queue_page, args=("Overview",))
    st.stop()

source_path = Path(active_video["source_path"])
video_hash = str(active_video["video_hash"])
source_filename = str(active_video["name"])
provenance = provenance_for(video_hash)
source_kind = provenance["data_source"]
export_prefix = "synthetic_demo_" if active_is_demo else ""
try:
    initial_metadata, first_frame = inspect_video(source_path)
except VideoError as exc:
    st.error(str(exc))
    st.stop()

camera_id = st.session_state.get(
    f"camera_id_{video_hash}", DEMO_CAMERA_ID if active_is_demo else f"CAM-{video_hash[:8].upper()}"
)
applied_zone = st.session_state.get(f"zone_applied_{video_hash}", [])
if active_is_demo:
    # Scripted rows replace model inference; regenerate if the cache was cleared.
    ensure_demo_assets()
artifacts = cached_analysis(
    video_hash,
    source_path,
    DEMO_TRACKING_CONFIG if active_is_demo else tracking_config,
    initial_metadata,
)
if artifacts is None:
    if presenting:
        presenter.render_unavailable(
            "This footage has not been analyzed with the current settings. Return to the "
            "workspace and select Analyze footage on Overview, then present again."
        )
        st.stop()
    if threshold_box is not None:
        threshold_box.info("Analyze this footage with the current settings before comparing thresholds.")
        st.stop()
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
    incident["data_source"] = source_kind
dispatch_notifications = list_notifications(video_hash)
statistics = safety_statistics(tracks, events, metadata.duration_seconds)
# The Library compares against the snapshot it already validated; rebuilding it
# there would silently clear its "open Analysis to recompute" notice.
if threshold_box is None:
    try:
        st.session_state["history_current_snapshot"] = build_analysis_snapshot(
            video_sha256=video_hash,
            source_name=source_filename,
            camera_label=camera_id,
            source_kind=source_kind,
            duration_seconds=metadata.duration_seconds,
            tracks=tracks_for_detector,
            events=events,
            incidents=incidents,
            tracking_config=DEMO_TRACKING_CONFIG if active_is_demo else tracking_config,
            conflict_config=conflict_config,
            collision_config=collision_config,
            zone_pixels=applied_zone,
            video_metadata=asdict(metadata),
        )
        st.session_state["history_current_fingerprint"] = analysis_settings_fingerprint(
            video_hash,
            DEMO_TRACKING_CONFIG if active_is_demo else tracking_config,
            conflict_config,
            collision_config,
            applied_zone,
        )
    except ValueError:
        st.session_state.pop("history_current_snapshot", None)
        st.session_state.pop("history_current_fingerprint", None)

if detector_error:
    st.error(f"Prediction analysis failed: {detector_error}")
if incident_detector_error:
    st.error(f"Incident evidence analysis failed: {incident_detector_error}")
for warning in event_warnings:
    st.warning(warning)


def incident_for_event(event_id) -> dict | None:
    return next(
        (item for item in incidents if item.get("associated_prediction_event_id") == event_id), None
    )


def event_option_label(event: dict) -> str:
    pair = event_pair_key(event)
    return (
        f"{format_timestamp(event.get('first_alert_timestamp_seconds'))} · {event.get('severity')} · "
        f"{PATTERN_LABELS[interaction_pattern(event)]} · "
        + ("—" if pair is None else f"#{pair[0]} / #{pair[1]}")
    )


if presenting:
    presenter.render_presenter(
        source_path=source_path,
        metadata=metadata,
        tracks=tracks,
        events=events,
        incidents=incidents,
        reviews=persisted_reviews,
        notifications=dispatch_notifications,
        provenance=provenance,
        source_name=source_filename,
        video_id=video_hash,
        source_kind=source_kind,
        conflict_config=conflict_config,
    )


elif navigation == "Analysis":
    page_header(
        "Analysis",
        "Playback with context",
        "Follow tracked movement and inspect the moments NearMiss marked for attention.",
    )
    source_banner(provenance, source_filename)
    if active_is_demo:
        demo_steps("Analysis")
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

    section_header(
        "Why each warning was raised",
        "A plain reading of the measurements behind one warning. Change thresholds in Advanced settings to see how they move.",
    )
    if not events:
        st.info("No warning to explain with the current settings.")
    else:
        ranked = sorted(
            events,
            key=lambda item: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(item.get("severity")), 3),
                              float(item.get("first_alert_timestamp_seconds") or 0.0)),
        )
        selected_index = st.selectbox(
            "Warning",
            list(range(len(ranked))),
            format_func=lambda index: event_option_label(ranked[index]),
            key=f"explain_event_{video_hash}",
        )
        selected_event = ranked[min(int(selected_index or 0), len(ranked) - 1)]
        linked = incident_for_event(selected_event.get("event_id"))
        extra = None
        if linked is not None and (linked.get("prediction_lead_seconds") or 0) > 0:
            extra = (
                f"This warning came {float(linked['prediction_lead_seconds']):.2f}s before the first contact "
                f"of a suspected incident at {format_timestamp(linked['timestamp_seconds'])}."
            )
        explanation_block(explain_event(selected_event, conflict_config), extra)

    if active_is_demo:
        with st.expander("Demo script versus detector output", expanded=False):
            st.caption("What was staged in the generated clip. The warnings above were computed, not scripted.")
            st.dataframe(
                pd.DataFrame(DEMO_SCENES).rename(
                    columns={"window": "Time", "scene": "Scene", "staged": "Scripted motion"}
                ),
                hide_index=True,
                width="stretch",
            )

    event_tab, map_tab, details_tab = st.tabs(["Events", "Safety map", "Details"])
    with event_tab:
        if not events:
            st.info("No potential conflict events are available.")
        else:
            rows = [
                {
                    "Time": format_timestamp(event.get("first_alert_timestamp_seconds")),
                    "Priority": event.get("severity"),
                    "Pattern": PATTERN_LABELS[interaction_pattern(event)],
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
                        f"{export_prefix}debug_conflicts.csv",
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
        # The cached PDF is valid only for the exact inputs it was built from.
        current_report_key = report_cache_key(
            {
                "video": video_hash,
                "source_filename": source_filename,
                "provenance": provenance,
                "tracking": (DEMO_TRACKING_CONFIG if active_is_demo else tracking_config).as_dict(),
                "conflict_config": conflict_config,
                "collision_config": collision_config,
                "zone": applied_zone,
                "events": events,
                "reviews": prediction_reviews,
            }
        )
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
            st.session_state[report_key] = {
                "key": current_report_key,
                "pdf": generate_safety_report(
                    source_filename=source_filename,
                    duration_seconds=metadata.duration_seconds,
                    tracks=tracks,
                    events=events,
                    heatmap_rgb=heatmap_rgb,
                    review_labels=prediction_reviews,
                    event_frames=report_frames,
                    provenance=provenance,
                ),
            }
            st.success("Safety report is ready.")
        saved_report = st.session_state.get(report_key)
        if isinstance(saved_report, dict) and saved_report.get("key") == current_report_key:
            st.download_button(
                "Download safety report",
                saved_report["pdf"],
                f"{export_prefix}nearmiss_safety_report.pdf",
                "application/pdf",
            )
        elif saved_report is not None:
            st.caption(
                "Thresholds, analysis area, or reviews changed since the last report. "
                "Generate it again to download a matching PDF."
            )
        reviewed_events = [
            {**event, "data_source": source_kind}
            for event in events_with_review_labels(events, prediction_reviews)
        ]
        export_payload = {
            "schema_version": "1.2",
            "provenance": provenance,
            "source_filename": source_filename,
            "video_sha256": None if active_is_demo else video_hash,
            "video_id": video_hash,
            "camera_id": camera_id,
            "video": asdict(metadata),
            "tracking_config": (DEMO_TRACKING_CONFIG if active_is_demo else tracking_config).as_dict(),
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
        if st.session_state.get("history_current_snapshot") and st.button(
            "Save to library", key=f"library_save_{video_hash}"
        ):
            _, created = save_analysis_snapshot(
                snapshot=st.session_state["history_current_snapshot"],
                database_path=store_module.DEFAULT_DATABASE_PATH,
            )
            st.toast("Saved to library" if created else "Library entry updated")
        downloads = st.columns(5)
        downloads[0].download_button(
            "Tracks CSV", tracks_to_csv(tracks_for_detector), f"{export_prefix}tracks.csv", "text/csv"
        )
        downloads[1].download_button(
            "Warnings CSV", events_to_csv(reviewed_events), f"{export_prefix}warnings.csv", "text/csv"
        )
        downloads[2].download_button(
            "Incidents CSV", events_to_csv(incidents), f"{export_prefix}incidents.csv", "text/csv"
        )
        downloads[3].download_button(
            "Analysis JSON",
            json.dumps(export_payload, indent=2, default=json_default),
            f"{export_prefix}analysis.json",
            "application/json",
        )
        downloads[4].download_button(
            "Annotated video",
            annotated_path.read_bytes(),
            f"{export_prefix}nearmiss_annotated.mp4",
            "video/mp4",
        )
    if active_is_demo:
        demo_controls(video_hash, "analysis")


elif navigation == "Investigation":
    page_header(
        "Investigation",
        "Step through the evidence",
        "Original frames with stored track rows only. Nothing is re-detected or interpolated.",
    )
    source_banner(provenance, source_filename)
    render_investigation_page(
        source_path=source_path,
        metadata=metadata,
        tracks=tracks,
        events=events,
        incidents=incidents,
        source_kind=source_kind,
        video_id=video_hash,
    )


elif navigation == "Explain & Share":
    page_header(
        "Explain & Share",
        "Why was this flagged?",
        "Plain-language evidence for one flagged moment, with a downloadable brief.",
    )
    source_banner(provenance, source_filename)
    render_evidence_page(
        source_name=source_filename,
        video_id=video_hash,
        source_kind=source_kind,
        metadata=metadata,
        tracks=tracks,
        events=events,
        incidents=incidents,
        reviews=persisted_reviews,
        notifications=dispatch_notifications,
    )


elif navigation == "Incidents":
    page_header(
        "Incidents",
        "Review the evidence",
        "Open a suspected incident, replay the moment, and record an operator decision.",
    )
    source_banner(provenance, source_filename)
    if active_is_demo:
        demo_steps("Incidents")
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
        selected_id = selected_incident["incident_id"]
        section_header("Evidence review")
        evidence_col, decision_col = st.columns([1.8, 1], gap="large")
        with evidence_col:
            impact_time = float(selected_incident["timestamp_seconds"])
            source_frame = frame_at_timestamp(source_path, impact_time)
            marked_frame = annotate_incident_frame(source_frame, selected_incident)
            st.image(
                cv2.cvtColor(marked_frame, cv2.COLOR_BGR2RGB),
                caption=f"Source frame at first contact · {format_timestamp(impact_time)}",
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
            lead = selected_incident.get("prediction_lead_seconds")
            if prediction_id and lead is not None and float(lead) > 0:
                status_pill(f"Warned {float(lead):.2f}s earlier · {prediction_id}", "warning")
            else:
                status_pill("No earlier warning")
            explanation = explain_incident(selected_incident)
            explanation_block(explanation, explanation["prediction"])
            notification = next(
                (item for item in dispatch_notifications if item["incident_id"] == selected_id), None
            )
            if notification is not None:
                st.caption(f"Simulated inbox: {notification['notification_id']} · {notification['status']}")
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
            link_cols = st.columns(2)
            link_cols[0].button(
                "Step through frames",
                key=f"investigate_{selected_id}",
                on_click=open_investigation,
                args=(
                    video_hash,
                    int(selected_incident.get("frame_index", 0)),
                    evidence_track_ids(selected_incident),
                ),
                width="stretch",
            )
            link_cols[1].button(
                "Explain & share",
                key=f"explain_{selected_id}",
                on_click=queue_page,
                args=("Explain & Share",),
                width="stretch",
            )
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
    if active_is_demo:
        demo_controls(video_hash, "incidents")


elif navigation == "Dispatch":
    page_header(
        "Dispatch",
        "Verified incident inbox",
        "Confirmed incidents appear here for acknowledgment. This is a local simulation; nothing is sent externally.",
    )
    source_banner(provenance, source_filename)
    if active_is_demo:
        demo_steps("Dispatch")
    new_count = sum(notification["status"] == "New" for notification in dispatch_notifications)
    acknowledged_count = sum(
        notification["status"] == "Acknowledged" for notification in dispatch_notifications
    )
    withdrawn_count = sum(
        notification["status"] == "Withdrawn" for notification in dispatch_notifications
    )
    notify_cols = st.columns(3)
    notify_cols[0].metric("New", new_count)
    notify_cols[1].metric("Acknowledged", acknowledged_count)
    notify_cols[2].metric("Withdrawn", withdrawn_count)

    section_header("Inbox", "Local simulation only. No external message was sent.")
    decision_labels = {
        "Confirmed Incident": "Confirmed",
        "False Alarm": "Dismissed",
        "Uncertain": "Uncertain",
    }
    if not dispatch_notifications:
        empty_state(
            "Inbox is clear",
            "Confirm a suspected incident in Incidents to create a simulated dispatch notification.",
        )
        st.button("Open Incidents", type="primary", on_click=queue_page, args=("Incidents",))
    else:
        for notification in dispatch_notifications:
            summary = notification.get("summary", {})
            withdrawn = notification["status"] == "Withdrawn"
            with st.container(border=False):
                header_cols = st.columns([3.4, 1.2])
                with header_cols[0]:
                    st.markdown(f"### {notification['notification_id']}")
                    st.caption(
                        f"{notification['camera_id']} · Generated {notification['generated_at']}"
                        + (" · SYNTHETIC DEMO" if summary.get("data_source") == "synthetic_demo" else "")
                    )
                with header_cols[1]:
                    status_pill(
                        notification["status"],
                        "success" if notification["status"] == "Acknowledged" else "" if withdrawn else "warning",
                    )
                detail_cols = st.columns(3)
                detail_cols[0].metric("Video time", format_timestamp(summary.get("timestamp_seconds")))
                vehicles = summary.get("vehicle_track_ids", [])
                detail_cols[1].metric(
                    "Vehicles",
                    " / ".join(f"#{value}" for value in vehicles if value is not None) or "—",
                )
                detail_cols[2].metric(
                    "Operator decision",
                    decision_labels.get(summary.get("operator_confirmation"), "—"),
                )
                st.write(
                    "Evidence: "
                    + ", ".join(
                        str(signal).replace("_", " ")
                        for signal in summary.get("detection_signals", [])
                    )
                )
                if withdrawn:
                    st.caption(
                        f"Withdrawn {summary.get('withdrawn_at', '')} after the operator changed the decision. "
                        "Kept as an audit record; it cannot be acknowledged."
                    )
                else:
                    st.caption("This record exists only inside NearMiss on this computer.")
                if notification["status"] == "New" and st.button(
                    "Acknowledge",
                    key=f"ack_{notification['notification_id']}",
                    type="primary",
                ):
                    acknowledge_notification(notification["notification_id"])
                    st.toast("Notification acknowledged")
                    st.rerun()
            st.markdown('<div class="nm-row-separator"></div>', unsafe_allow_html=True)
    if active_is_demo:
        demo_controls(video_hash, "dispatch")


elif navigation == "Street Lab":
    page_header(
        "Street Lab",
        "From flagged moments to a community review",
        "Summarize what this footage shows, explore a crossing-distance question under your own "
        "assumptions, and take a practical observation plan to a neighborhood or school meeting.",
    )
    source_banner(provenance, source_filename)
    if active_is_demo:
        demo_steps("Street Lab")
    st.markdown(
        f'<p class="nm-section-copy">{escape(streetlab.DATA_BOUNDARY)} '
        + (
            "Here that is the scripted synthetic demo, which describes no real place."
            if active_is_demo
            else "Here that is one uploaded clip; a single clip is not a representative sample of an intersection."
        )
        + "</p>",
        unsafe_allow_html=True,
    )
    summary = streetlab.evidence_summary(
        provenance=provenance,
        tracks=tracks,
        events=events,
        incidents=incidents,
        duration_seconds=metadata.duration_seconds,
        width=metadata.width,
        height=metadata.height,
    )
    section_header("Evidence summary")
    lab_cols = st.columns(4)
    lab_cols[0].metric("Warnings", summary["warnings_total"])
    lab_cols[1].metric("HIGH priority", summary["warnings_by_priority"]["HIGH"])
    lab_cols[2].metric("Suspected incidents", summary["incidents_total"])
    lab_cols[3].metric("Operator-confirmed", summary["incident_reviews"]["Confirmed"])
    if summary["patterns"]:
        st.caption(
            "Patterns: "
            + ", ".join(f"{name} ({count})" for name, count in summary["patterns"].items())
            + (f" · most warnings in the {summary['busiest_region']}" if summary["busiest_region"] else "")
        )

    section_header(
        "Interactions that warrant human review",
        "Why each item deserves a closer look before anyone draws a conclusion.",
    )
    if summary["review_items"]:
        st.dataframe(
            pd.DataFrame(summary["review_items"]).rename(
                columns={
                    "kind": "Type", "id": "ID", "time": "Time", "pattern": "Pattern",
                    "priority": "Priority", "location": "Frame location", "why_review": "Why review",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        empty_state("Nothing flagged", "A zero count is not proof that the intersection is safe.")

    section_header(
        "Crossing-distance illustration",
        "Every number here is an assumption you control. Example values are placeholders; "
        "replace them with field measurements.",
    )
    unit_label = st.radio("Units", ["Feet", "Meters"], horizontal=True, key=f"streetlab_unit_{video_hash}")
    unit = "ft" if unit_label == "Feet" else "m"
    defaults = (60.0, 40.0, 3.5, 2.5) if unit == "ft" else (18.0, 12.0, 1.1, 0.8)
    input_cols = st.columns(5)
    current_distance = input_cols[0].number_input(
        f"Current crossing ({unit})", 1.0, 400.0, defaults[0], 1.0, key=f"streetlab_current_{unit}_{video_hash}"
    )
    proposed_distance = input_cols[1].number_input(
        f"Hypothetical crossing ({unit})", 1.0, 400.0, defaults[1], 1.0,
        key=f"streetlab_proposed_{unit}_{video_hash}",
        help="For example, after curb extensions or a refuge island. A hypothesis, not a design.",
    )
    walking_speed = input_cols[2].number_input(
        f"Walking speed ({unit}/s)", 0.1, 10.0, defaults[2], 0.1, key=f"streetlab_walk_{unit}_{video_hash}"
    )
    slower_speed = input_cols[3].number_input(
        f"Slower walker ({unit}/s)", 0.1, 10.0, defaults[3], 0.1,
        key=f"streetlab_slow_{unit}_{video_hash}",
        help="For example, a child, an older adult, or someone using a mobility aid.",
    )
    start_up = input_cols[4].number_input(
        "Start-up time (s)", 0.0, 15.0, 2.0, 0.5, key=f"streetlab_startup_{video_hash}"
    )
    try:
        crossing = streetlab.crossing_comparison(
            streetlab.CrossingAssumptions(
                unit=unit,
                current_distance=float(current_distance),
                proposed_distance=float(proposed_distance),
                walking_speed=float(walking_speed),
                slower_walking_speed=float(slower_speed),
                start_up_seconds=float(start_up),
            )
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    crossing_frame = pd.DataFrame(crossing["rows"])
    chart_frame = crossing_frame.melt(
        id_vars="walker", value_vars=["current_seconds", "proposed_seconds"],
        var_name="layout", value_name="seconds",
    )
    chart_frame["layout"] = chart_frame["layout"].map(
        {"current_seconds": "Current", "proposed_seconds": "Hypothetical"}
    )
    figure = px.bar(
        chart_frame, x="seconds", y="walker", color="layout", barmode="group", orientation="h",
        color_discrete_map={"Current": "#78716C", "Hypothetical": COLORS["accent"]},
        labels={"seconds": "Crossing time (s)", "walker": "", "layout": ""},
        text="seconds",
    )
    figure.update_layout(
        height=230, margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": COLORS["muted"]}, xaxis={"gridcolor": "#29272A"},
    )
    st.plotly_chart(figure, width="stretch", key=f"streetlab_chart_{video_hash}")
    st.dataframe(
        crossing_frame[
            ["walker", "speed", "current_seconds", "proposed_seconds", "difference_text",
             "in_roadway_change_text"]
        ].rename(
            columns={
                "walker": "Walker", "speed": f"Speed ({unit}/s)", "current_seconds": "Current (s)",
                "proposed_seconds": "Hypothetical (s)", "difference_text": "Hypothetical vs current",
                "in_roadway_change_text": "Time in roadway",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(crossing["boundary"])
    st.warning(crossing["hypothesis"])

    section_header("Follow-up observations", "Evidence-driven items come first. Check what you plan to do.")
    checklist = streetlab.checklist_items(summary)
    checked_ids = []
    for item in checklist:
        if st.checkbox(item["text"], key=f"streetlab_check_{video_hash}_{item['id']}", help=item["why"]):
            checked_ids.append(item["id"])
    notes = st.text_area(
        "Reviewer notes",
        key=f"streetlab_notes_{video_hash}",
        placeholder="Who you will contact, when you will observe, what you want to measure…",
    )

    section_header("Community review brief", "The downloads contain exactly the content shown on this page.")
    brief = streetlab.build_brief(
        summary=summary,
        crossing=crossing,
        checklist=checklist,
        checked_ids=checked_ids,
        notes=notes,
        source_filename=source_filename,
    )
    brief_cols = st.columns([1, 1, 2])
    brief_cols[0].download_button(
        "Download brief (PDF)",
        streetlab.brief_pdf(brief),
        f"{export_prefix}nearmiss_community_review_brief.pdf",
        "application/pdf",
        type="primary",
        width="stretch",
    )
    brief_cols[1].download_button(
        "Download brief (Markdown)",
        streetlab.brief_markdown(brief),
        f"{export_prefix}nearmiss_community_review_brief.md",
        "text/markdown",
        width="stretch",
    )
    if active_is_demo:
        demo_controls(video_hash, "streetlab")


elif threshold_box is not None:
    # Owned by nearmiss.comparison_ui (see docs/comparison-integration.md).
    # Imported only when the box is open; failures surface rather than hide.
    from nearmiss.comparison_ui import render_comparison

    with threshold_box:
        render_comparison(
            tracks=tracks_for_detector,
            events=events,
            cfg=conflict_config,
            zone_polygon=analysis_zone,
            frame_size=(metadata.width, metadata.height),
            data_source=source_kind,
            video_id=video_hash,
        )


st.markdown(
    '<div class="nm-footer">NearMiss · Experimental decision support · '
    'Not a validated crash detector or emergency-service system'
    + (" · SYNTHETIC DEMO data in use" if active_is_demo else "")
    + "</div>",
    unsafe_allow_html=True,
)
