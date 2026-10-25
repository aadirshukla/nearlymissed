"""Streamlit page for Explain & Share.

A thin view over :mod:`nearmiss.evidence_brief`: every sentence, fact and
checklist row comes from those pure functions, so the page and the downloaded
brief always say the same thing. The page reuses the app's ``nm-*`` CSS classes
when they are loaded and stays readable without them.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from nearmiss.evidence_brief import (
    INCIDENT,
    PREDICTION,
    brief_filename,
    build_evidence_brief,
    describe_source,
    evidence_options,
    explain_evidence,
    processing_quality,
)


_STATUS_ICON = {"ok": "✅", "caution": "⚠️", "info": "ℹ️"}
_KIND_LABEL = {INCIDENT: "Suspected incidents", PREDICTION: "Prediction warnings"}


def _section(title: str, copy: str | None = None) -> None:
    st.markdown(f'<div class="nm-section-title">{escape(title)}</div>', unsafe_allow_html=True)
    if copy:
        st.markdown(f'<p class="nm-section-copy">{escape(copy)}</p>', unsafe_allow_html=True)


def _empty(title: str, message: str) -> None:
    st.markdown(
        f'<div class="nm-empty"><strong>{escape(title)}</strong>'
        f'<div style="margin-top:.45rem">{escape(message)}</div></div>',
        unsafe_allow_html=True,
    )


def render_evidence_page(
    *,
    source_name: str,
    video_id: str,
    source_kind: str,
    metadata: Any,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    reviews: Any,
    notifications: list[dict],
) -> None:
    """Render the Explain & Share page for one analysed source."""

    source = describe_source(source_kind, video_id, tracks, (incidents or []) + (events or []))
    if source["is_synthetic"]:
        st.warning(source["statement"], icon="🧪")
    if source.get("note"):
        st.caption(source["note"])

    _section(
        "Explain & share evidence",
        "Pick one flagged moment to see why NearMiss marked it, what the detector actually "
        "measured, and what limits apply. The brief you download says exactly what this page says.",
    )

    options = evidence_options(events, incidents)
    if not options:
        _empty(
            "Nothing to explain yet",
            "No prediction warnings or suspected incidents were produced for this source with the "
            "current settings. NearMiss does not create evidence that the detectors did not report.",
        )
        return

    counts = {kind: sum(1 for item in options if item["kind"] == kind) for kind in (INCIDENT, PREDICTION)}
    kinds = [kind for kind in (INCIDENT, PREDICTION) if counts[kind]]
    kind = st.radio(
        "Evidence type",
        kinds,
        format_func=lambda value: f"{_KIND_LABEL[value]} ({counts[value]})",
        horizontal=True,
        key=f"evidence_kind_{video_id}",
    )
    choices = [item for item in options if item["kind"] == kind]
    selected = st.selectbox(
        "Flagged moment",
        choices,
        format_func=lambda item: item["label"],
        key=f"evidence_item_{video_id}_{kind}",
    )
    record = selected["record"]
    explanation = explain_evidence(kind, record, reviews, notifications)
    checks = processing_quality(kind=kind, record=record, metadata=metadata, tracks=tracks, source=source)

    _section(explanation["title"], f"Evidence ID {explanation['id']}")
    st.markdown(" ".join(explanation["explanation"]))
    if explanation["evidence_status"] != "established":
        st.warning(
            "The supplied record is incomplete, so this explanation only reports what was supplied "
            "and does not establish the flagged result."
        )
    if kind == INCIDENT:
        review, dispatch = explanation["review"], explanation["dispatch"]
        status_cols = st.columns(2)
        status_cols[0].metric("Operator review", review["status"])
        status_cols[1].metric("Simulated dispatch", dispatch["status"])
        st.caption(dispatch["statement"])
        for note in (review["inconsistency"], dispatch["inconsistency"]):
            if note:
                st.warning(note)
    else:
        st.caption("Prediction warnings are forecasts. They are not reviewed as incidents and never create a dispatch notice.")

    _section("Evidence facts", "Values come straight from detector output. Pixel values are uncalibrated image measurements.")
    st.dataframe(
        [{"Measure": fact["label"], "Value": fact["value"], "Notes": fact["note"]} for fact in explanation["facts"]],
        hide_index=True,
        width="stretch",
    )
    if explanation["motion_rows"]:
        st.dataframe(
            [
                {
                    "Track": "—" if row["track_id"] is None else f"#{row['track_id']}",
                    "Speed before": row["speed_before"],
                    "Speed after": row["speed_after"],
                    "Direction change": row["direction_change"],
                    "Signals": row["signals"],
                }
                for row in explanation["motion_rows"]
            ],
            hide_index=True,
            width="stretch",
        )
    if explanation["missing_fields"]:
        st.info("Missing or unusable fields: " + ", ".join(explanation["missing_fields"]) + ".")

    _section("Processing-quality checklist", "Limits to keep in mind before sharing. These are disclosures, not accuracy scores.")
    for check in checks:
        st.markdown(f"{_STATUS_ICON.get(check['status'], 'ℹ️')} **{escape(check['check'])}**: {escape(check['detail'])}")

    brief = build_evidence_brief(
        source_name=source_name,
        video_id=video_id,
        source_kind=source_kind,
        metadata=metadata,
        tracks=tracks,
        kind=kind,
        record=record,
        reviews=reviews,
        notifications=notifications,
    )
    st.download_button(
        "Download evidence brief",
        brief.encode("utf-8"),
        brief_filename(kind, record, source["is_synthetic"]),
        "text/markdown",
        type="primary",
        key=f"evidence_download_{video_id}_{selected['key']}",
    )
    st.caption(
        "Markdown file for sharing with reviewers. It is separate from the PDF safety report, "
        "which summarises the whole clip."
    )
