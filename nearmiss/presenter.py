"""Presenter Mode: a five-step, keyboard-driven walk through one flagged moment.

warning -> source frame -> incident review -> Street Lab -> exported brief.

Every visual, number and download comes from the existing modules (stored
track rows, conflict/incident records, review store, Street Lab, evidence
brief). Presenting is read-only: no step records a review decision or touches
the simulated dispatch inbox, and moving between steps only changes the
``presenter_*`` session keys. Keyboard Next/Back are native Streamlit button
shortcuts, so Streamlit scopes and clears them on every rerun; the elapsed
timer is a small ``st.components.v2`` element whose interval is cleaned up when
it unmounts.
"""

from __future__ import annotations

import time
from html import escape
from pathlib import Path
from typing import Any, MutableMapping

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v2 as components_v2

from nearmiss import streetlab
from nearmiss.events import format_timestamp
from nearmiss.evidence_brief import (
    INCIDENT,
    PREDICTION,
    brief_filename,
    build_evidence_brief,
    describe_source,
    explain_evidence,
)
from nearmiss.explain import explain_event, explain_incident
from nearmiss.investigation import (
    draw_investigation_frame,
    evidence_track_ids,
    observations_at_frame,
    timestamp_for_frame_index,
    track_trail,
)
from nearmiss.motion import EXAMPLE_CROSSING, focus_evidence


STEPS = (
    ("warning", "The warning", "Analysis"),
    ("source", "Source frame", "Investigation"),
    ("review", "Incident review", "Incidents"),
    ("streetlab", "Street Lab", "Street Lab"),
    ("brief", "Exported brief", "Explain & Share"),
)
ACTIVE, STEP, STARTED, RETURN = (
    "presenter_active",
    "presenter_step",
    "presenter_started_at",
    "presenter_return_page",
)
SUGGESTED_MINUTES = 2


# ------------------------------------------------------------- session state


def is_active(state: MutableMapping) -> bool:
    return bool(state.get(ACTIVE))


def enter(state: MutableMapping, *, return_page: str = "Overview", now: float | None = None) -> None:
    state[ACTIVE] = True
    state[STEP] = 0
    state[STARTED] = time.time() if now is None else float(now)
    state[RETURN] = return_page


def leave(state: MutableMapping, page: str | None = None) -> None:
    """Exit presenting. ``page`` (or the page presenting started from) opens next."""

    was_active = state.pop(ACTIVE, False)
    target = page or (state.get(RETURN) if was_active else None)
    if target:
        state["_next_page"] = target


def stop(state: MutableMapping) -> None:
    """Exit presenting without redirecting (the sidebar page choice wins)."""

    state.pop(ACTIVE, None)


def current_step(state: MutableMapping) -> int:
    try:
        return min(max(int(state.get(STEP, 0)), 0), len(STEPS) - 1)
    except (TypeError, ValueError):
        return 0


def step_by(state: MutableMapping, delta: int) -> None:
    state[STEP] = min(max(current_step(state) + int(delta), 0), len(STEPS) - 1)


def go_to(state: MutableMapping, index: int) -> None:
    state[STEP] = min(max(int(index), 0), len(STEPS) - 1)


def restart_timer(state: MutableMapping) -> None:
    state[STARTED] = time.time()


def open_in_workspace(
    state: MutableMapping,
    page: str,
    *,
    video_id: str,
    frame_index: int | None = None,
    track_ids: list[int] | None = None,
    incident_id: str | None = None,
) -> None:
    """Leave presenting and open a workspace page focused on the same evidence.

    Uses the same session keys as app.py ``open_investigation`` and the
    Incidents queue; it never writes a review or notification.
    """

    if page == "Investigation" and frame_index is not None:
        prefix = f"investigation_{video_id}"
        state[f"{prefix}_frame"] = int(frame_index)
        if track_ids:
            state.pop(f"{prefix}_types", None)
            state.pop(f"{prefix}_classes", None)
            state[f"{prefix}_tracks"] = list(track_ids)
    if page == "Incidents" and incident_id:
        state[f"selected_incident_{video_id}"] = incident_id
    leave(state, page)


# ------------------------------------------------------------- pure content


def build_deck(
    *,
    events: list[dict],
    incidents: list[dict],
    conflict_config: dict,
    fps: float,
) -> dict[str, Any]:
    """The evidence each step shows, chosen the same way as the Overview story."""

    event, incident = focus_evidence(events, incidents)
    deck: dict[str, Any] = {"event": event, "incident": incident, "fps": float(fps)}
    if event is not None:
        alert_frame = int(event.get("start_frame_index", event.get("frame_index", 0)))
        deck.update(
            alert_frame=alert_frame,
            alert_seconds=float(event.get("first_alert_timestamp_seconds", alert_frame / fps)),
            measure_frame=int(event.get("frame_index", alert_frame)),
            participants=evidence_track_ids(event),
            warning=explain_event(event, conflict_config),
        )
    if incident is not None:
        deck.update(
            contact_frame=int(incident.get("frame_index", 0)),
            contact_seconds=float(
                incident.get("first_suspected_impact_timestamp_seconds", incident.get("timestamp_seconds", 0.0))
            ),
            incident_participants=evidence_track_ids(incident),
            incident_explanation=explain_incident(incident),
        )
    return deck


def evidence_status(*, provenance: dict, events: list[dict], incidents: list[dict]) -> dict[str, list[str]]:
    """What this run verifies locally versus what nobody has measured."""

    synthetic = provenance.get("data_source") == "synthetic_demo"
    verified = [
        f"This run recomputed {len(events)} warning(s) and {len(incidents)} suspected incident(s) "
        "from stored track rows with the current thresholds.",
        "Every figure on these steps is decoded from the source video or plotted from stored rows; "
        "nothing is interpolated or typed in.",
        "Reviews and the simulated dispatch inbox are stored locally in SQLite; presenting does not "
        "change them.",
    ]
    if synthetic:
        verified.append(
            "Synthetic regression: automated tests pin the expected warnings and suspected incident "
            "for this scripted clip at default thresholds. That checks the pipeline, not real-world accuracy."
        )
    not_measured = [
        "Detector accuracy on real footage: false-alarm and miss rates have not been measured.",
        "Any safety outcome or crash reduction.",
        "Real-world distances or speeds: measurements are uncalibrated image pixels.",
        "Real dispatch: there is no emergency-service connection; notifications are local simulations.",
    ]
    return {"verified": verified, "not_measured": not_measured}


def draw_projection(frame_bgr: np.ndarray, event: dict) -> np.ndarray:
    """Overlay the detector's projected paths and meeting point on a frame copy."""

    frame = frame_bgr.copy()
    colors = {"a": (59, 169, 242), "b": (228, 229, 231)}  # BGR amber, light
    for side in ("a", "b"):
        start, end = event.get(f"participant_{side}_position"), event.get(f"participant_{side}_predicted_end")
        try:
            x0, y0, x1, y1 = float(start[0]), float(start[1]), float(end[0]), float(end[1])
        except (TypeError, ValueError, IndexError):
            continue
        length = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1e-9)
        dash = 14.0
        steps = int(length // dash)
        for index in range(0, steps, 2):
            a, b = index * dash / length, min((index + 1) * dash / length, 1.0)
            cv2.line(
                frame,
                (int(x0 + (x1 - x0) * a), int(y0 + (y1 - y0) * a)),
                (int(x0 + (x1 - x0) * b), int(y0 + (y1 - y0) * b)),
                colors[side], 3, cv2.LINE_AA,
            )
    point = event.get("conflict_point")
    try:
        center = (int(float(point[0])), int(float(point[1])))
        radius = max(6, int(float(event.get("conflict_region_radius_pixels") or 16)))
        cv2.circle(frame, center, radius, colors["a"], 3, cv2.LINE_AA)
    except (TypeError, ValueError, IndexError):
        pass
    return frame


# ------------------------------------------------------------- rendering

CLOCK_HTML = (
    '<div class="clock" data-presenter-clock role="timer" aria-label="Elapsed presenting time">'
    '<span class="label">Elapsed</span> <strong data-elapsed>--:--</strong>'
    f'<span class="hint"> · suggested {SUGGESTED_MINUTES} min</span>'
    '<span class="nojs"> · timer needs JavaScript; Back and Next still work</span></div>'
)
CLOCK_CSS = """
.clock { color:#D6D3D1; font:inherit; font-size:.85rem; padding:.2rem 0; }
.clock strong { color:#F5F5F4; font-variant-numeric:tabular-nums; font-weight:620; }
.clock .label, .clock .hint, .clock .nojs { color:#A8A29E; }
.clock.is-live .nojs { display:none; }
"""
CLOCK_JS = """
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector('[data-presenter-clock]');
  if (!root || !data) return;
  if (typeof root.__nmCleanup === 'function') root.__nmCleanup();
  const out = root.querySelector('[data-elapsed]');
  const pad = (n) => String(n).padStart(2, '0');
  const render = () => {
    const s = Math.max(0, Math.floor((Date.now() - data.started_at_ms) / 1000));
    out.textContent = `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
  };
  render();
  const timer = setInterval(render, 1000);
  root.classList.add('is-live');
  const cleanup = () => { clearInterval(timer); root.__nmCleanup = null; };
  root.__nmCleanup = cleanup;
  return cleanup;
}
"""
_CLOCK: list[Any] = []


def _clock(started_at: float) -> None:
    if not _CLOCK:
        _CLOCK.append(
            components_v2.component(
                "nearmiss_presenter_clock", html=CLOCK_HTML, css=CLOCK_CSS, js=CLOCK_JS
            )
        )
    _CLOCK[0](key="presenter_clock", data={"started_at_ms": int(started_at * 1000)}, height="content")


def _source_ribbon(provenance: dict, source_name: str) -> None:
    synthetic = provenance.get("data_source") == "synthetic_demo"
    detail = provenance.get("pipeline_boundary") if synthetic else source_name
    st.markdown(
        f'<div class="nm-source{" synthetic" if synthetic else ""}" role="note" aria-label="Data source">'
        f'<span class="nm-source-tag">{escape(str(provenance.get("label", "")).upper())}</span>'
        f'<span>{escape(str(provenance.get("summary", "")))} {escape(str(detail or ""))}</span></div>',
        unsafe_allow_html=True,
    )


def _steps_bar(position: int) -> None:
    items = []
    for index, (_key, label, _page) in enumerate(STEPS):
        state = "current" if index == position else "done" if index < position else ""
        aria = ' aria-current="step"' if state == "current" else ""
        items.append(f'<li class="{state}"{aria}><strong>{index + 1}</strong>{escape(label)}</li>')
    st.markdown(
        '<ol class="nm-steps" aria-label="Presenter steps">' + "".join(items) + "</ol>",
        unsafe_allow_html=True,
    )


def _frame(source_path: Path, frame_index: int, fps: float):
    from nearmiss.video import VideoError, frame_at_timestamp

    try:
        return frame_at_timestamp(Path(source_path), timestamp_for_frame_index(frame_index, fps)), None
    except VideoError as exc:
        return None, str(exc)


def _rgb(frame_bgr):
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


def _bullets(explanation: dict, extra: str | None = None) -> None:
    bullets = "".join(f"<li>{escape(text)}</li>" for text in explanation.get("bullets", []))
    note = f"<p>{escape(extra)}</p>" if extra else ""
    st.markdown(
        f'<div class="nm-explain"><h4>{escape(explanation.get("headline", ""))}</h4><ul>{bullets}</ul>'
        f'{note}<p>{escape(explanation.get("caveat", ""))}</p></div>',
        unsafe_allow_html=True,
    )


def render_unavailable(message: str) -> None:
    st.markdown('<div class="nm-page-kicker">Presenter mode</div>', unsafe_allow_html=True)
    st.info(message)
    st.button("Return to workspace", key="presenter_return_unavailable", on_click=leave, args=(st.session_state,))


def render_presenter(
    *,
    source_path: Path,
    metadata: Any,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    reviews: dict,
    notifications: list[dict],
    provenance: dict,
    source_name: str,
    video_id: str,
    source_kind: str,
    conflict_config: dict,
) -> None:
    """Render the current step. Read-only with respect to reviews and dispatch."""

    state = st.session_state
    position = current_step(state)
    step_key, step_label, workspace_page = STEPS[position]
    fps = float(metadata.fps) or 1.0
    deck = build_deck(events=events, incidents=incidents, conflict_config=conflict_config, fps=fps)
    event, incident = deck["event"], deck["incident"]
    synthetic = provenance.get("data_source") == "synthetic_demo"
    tag = "SYNTHETIC — " if synthetic else ""

    top = st.columns([3, 1.2])
    with top[0]:
        st.markdown(
            '<div class="nm-page-kicker">Presenter mode</div>'
            f'<h1 class="nm-page-title">{position + 1}. {escape(step_label)}</h1>',
            unsafe_allow_html=True,
        )
    with top[1]:
        st.button(
            "Return to workspace", key="presenter_return", on_click=leave, args=(state,), width="stretch"
        )
        _clock(float(state.get(STARTED) or time.time()))
        st.button("Restart timer", key="presenter_restart", on_click=restart_timer, args=(state,), type="tertiary")
    _source_ribbon(provenance, source_name)
    _steps_bar(position)
    nav = st.columns([1, 1, 3])
    nav[0].button(
        "← Back", key="presenter_back", on_click=step_by, args=(state, -1),
        disabled=position == 0, shortcut="Left", width="stretch",
    )
    nav[1].button(
        "Next →", key="presenter_next", on_click=step_by, args=(state, 1), type="primary",
        disabled=position == len(STEPS) - 1, shortcut="Right", width="stretch",
    )
    nav[2].caption("Keyboard: ← and → move between steps. Presenting never changes a review or the inbox.")

    open_kwargs: dict[str, Any] = {"video_id": video_id}

    if step_key == "warning":
        if event is None:
            st.info("No warning was raised with the current thresholds, so there is nothing to present here.")
        else:
            # Boxes, trails and projected paths all come from the measurement
            # frame, so the dashed paths start where the boxes are drawn.
            shown = deck["measure_frame"]
            frame, error = _frame(source_path, shown, fps)
            visual, words = st.columns([1.6, 1], gap="large")
            with visual:
                if frame is None:
                    st.warning(f"Frame {shown} could not be decoded: {error}")
                else:
                    ids = deck["participants"]
                    rows = observations_at_frame(tracks, shown, track_ids=ids)
                    trails = {
                        track_id: track_trail(tracks, track_id, shown, trail_frames=int(2 * fps))
                        for track_id in ids
                    }
                    types = {int(r["track_id"]): r.get("object_type", "vehicle") for r in rows}
                    drawn = draw_investigation_frame(
                        frame, rows, trails, selected_track_ids=ids, track_types=types
                    )
                    st.image(
                        _rgb(draw_projection(drawn, event)),
                        width="stretch",
                        caption=(
                            f"{tag}Frame {shown} ({format_timestamp(shown / fps)}), where the projected paths "
                            "were measured. Boxes and trails are stored rows from the same frame. The first "
                            f"warning was confirmed later, at frame {deck['alert_frame']} "
                            f"({format_timestamp(deck['alert_seconds'])})."
                        ),
                    )
            with words:
                st.markdown(
                    f"**{escape(str(event.get('severity')))} warning** · {escape(str(event.get('event_id')))}  \n"
                    f"Paths measured: {format_timestamp(deck['measure_frame'] / fps)} (frame {deck['measure_frame']})  \n"
                    f"First warning: {format_timestamp(deck['alert_seconds'])} (frame {deck['alert_frame']})"
                )
                _bullets(deck["warning"])
            open_kwargs.update(frame_index=deck["alert_frame"], track_ids=deck["participants"])

    elif step_key == "source":
        if event is None:
            st.info("No warning frame to show with the current thresholds.")
        else:
            frame, error = _frame(source_path, deck["alert_frame"], fps)
            if frame is None:
                st.warning(f"Frame {deck['alert_frame']} could not be decoded: {error}")
            else:
                st.image(
                    _rgb(frame),
                    width="stretch",
                    caption=f"{tag}Original frame {deck['alert_frame']} "
                    f"({format_timestamp(deck['alert_seconds'])}) exactly as decoded, with no overlays.",
                )
            rows = observations_at_frame(tracks, deck["alert_frame"], track_ids=deck["participants"])
            st.caption("Stored track rows for the warning participants at this frame:")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Track": f"#{row['track_id']}",
                            "Class": row.get("class_name"),
                            "Frame": row["frame_index"],
                            "Box (x1, y1, x2, y2 px)": ", ".join(f"{float(v):.1f}" for v in row["bbox"]),
                        }
                        for row in rows
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            open_kwargs.update(frame_index=deck["alert_frame"], track_ids=deck["participants"])

    elif step_key == "review":
        if incident is None:
            st.info(
                "No suspected incident followed this warning with the current thresholds. "
                "Nothing is fabricated for review."
            )
        else:
            frame, error = _frame(source_path, deck["contact_frame"], fps)
            visual, words = st.columns([1.6, 1], gap="large")
            with visual:
                if frame is None:
                    st.warning(f"Frame {deck['contact_frame']} could not be decoded: {error}")
                else:
                    from nearmiss.video import annotate_incident_frame

                    st.image(
                        _rgb(annotate_incident_frame(frame, incident)),
                        width="stretch",
                        caption=f"{tag}Source frame {deck['contact_frame']} at first suspected contact "
                        f"({format_timestamp(deck['contact_seconds'])}).",
                    )
            with words:
                explanation = explain_evidence(INCIDENT, incident, reviews, notifications)
                # Plain wrapping text: long statuses must never be truncated.
                st.markdown(
                    f"**Operator review:** {escape(str(explanation['review']['status']))}  \n"
                    f"**Simulated dispatch:** {escape(str(explanation['dispatch']['status']))}"
                )
                st.caption(explanation["review"]["statement"])
                st.caption(explanation["dispatch"]["statement"])
                _bullets(deck["incident_explanation"], deck["incident_explanation"]["prediction"])
                st.caption("Decisions are recorded only on the Incidents page, by a person.")
            open_kwargs.update(incident_id=incident.get("incident_id"))

    elif step_key == "streetlab":
        summary = streetlab.evidence_summary(
            provenance=provenance, tracks=tracks, events=events, incidents=incidents,
            duration_seconds=metadata.duration_seconds, width=metadata.width, height=metadata.height,
        )
        cols = st.columns(4)
        cols[0].metric("Warnings", summary["warnings_total"])
        cols[1].metric("HIGH priority", summary["warnings_by_priority"]["HIGH"])
        cols[2].metric("Suspected incidents", summary["incidents_total"])
        cols[3].metric("Operator-confirmed", summary["incident_reviews"]["Confirmed"])
        crossing = streetlab.crossing_comparison(EXAMPLE_CROSSING)
        unit = crossing["assumptions"]["unit"]
        st.markdown(
            f"**Crossing-time illustration** with Street Lab's example assumptions: "
            f"{crossing['assumptions']['current_distance']:.0f} {unit} now versus "
            f"{crossing['assumptions']['proposed_distance']:.0f} {unit} hypothetical. "
            "These are placeholders, not measurements of this footage."
        )
        st.dataframe(
            pd.DataFrame(crossing["rows"])[
                ["walker", "speed", "current_seconds", "proposed_seconds", "difference_text"]
            ].rename(
                columns={
                    "walker": "Walker", "speed": f"Speed ({unit}/s)", "current_seconds": "Current (s)",
                    "proposed_seconds": "Hypothetical (s)", "difference_text": "Hypothetical vs current",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(crossing["boundary"])
        st.caption(crossing["hypothesis"])

    elif step_key == "brief":
        source = describe_source(source_kind, video_id, tracks, (incidents or []) + (events or []), provenance)
        kind, record = (INCIDENT, incident) if incident is not None else (PREDICTION, event)
        if record is None:
            st.info("No flagged moment to brief with the current thresholds.")
        else:
            brief = build_evidence_brief(
                source_name=source_name, video_id=video_id, source_kind=source_kind, metadata=metadata,
                tracks=tracks, kind=kind, record=record, reviews=reviews, notifications=notifications,
                provenance=provenance,
            )
            summary = streetlab.evidence_summary(
                provenance=provenance, tracks=tracks, events=events, incidents=incidents,
                duration_seconds=metadata.duration_seconds, width=metadata.width, height=metadata.height,
            )
            community = streetlab.build_brief(
                summary=summary,
                crossing=streetlab.crossing_comparison(EXAMPLE_CROSSING),
                checklist=streetlab.checklist_items(summary),
                checked_ids=[],
                notes="",
                source_filename=source_name,
            )
            prefix = "synthetic_demo_" if source["is_synthetic"] else ""
            st.markdown(
                "Two local files, built by the same functions as Explain & Share and Street Lab. "
                "Each states its source and limits."
            )
            cols = st.columns(2)
            cols[0].download_button(
                "Download evidence brief (Markdown)",
                brief.encode("utf-8"),
                brief_filename(kind, record, source["is_synthetic"]),
                "text/markdown",
                type="primary",
                key="presenter_evidence_brief",
                width="stretch",
            )
            cols[1].download_button(
                "Download community review brief (Markdown)",
                streetlab.brief_markdown(community).encode("utf-8"),
                f"{prefix}nearmiss_community_review_brief.md",
                "text/markdown",
                key="presenter_community_brief",
                width="stretch",
            )
            with st.expander("Read the evidence brief", expanded=False):
                st.markdown(brief)

    st.button(
        f"Open {workspace_page} in the workspace",
        key=f"presenter_open_{step_key}",
        on_click=open_in_workspace,
        args=(state, workspace_page),
        kwargs=open_kwargs,
    )

    status = evidence_status(provenance=provenance, events=events, incidents=incidents)
    with st.container(border=True, key="presenter_evidence_status"):
        st.markdown("**Evidence status**")
        cols = st.columns(2)
        with cols[0]:
            st.markdown("Verified locally\n\n" + "\n".join(f"- {line}" for line in status["verified"]))
        with cols[1]:
            st.markdown("Not measured\n\n" + "\n".join(f"- {line}" for line in status["not_measured"]))
