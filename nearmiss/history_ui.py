"""Streamlit page for the local Analysis Library (saved runs and comparisons)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from nearmiss.history import (
    BASE_CAVEATS,
    DEFAULT_DATABASE_PATH,
    SOURCE_KINDS,
    compare_analysis_snapshots,
    comparison_to_csv,
    comparison_to_json,
    list_analysis_snapshots,
    load_analysis_snapshot,
    save_analysis_snapshot,
    snapshot_table_rows,
    snapshots_to_csv,
    snapshots_to_json,
)


def _section(title: str, copy: str | None = None) -> None:
    # Reuses app.py's section classes so the page matches the existing theme.
    st.markdown(f'<div class="nm-section-title">{title}</div>', unsafe_allow_html=True)
    if copy:
        st.markdown(f'<p class="nm-section-copy">{copy}</p>', unsafe_allow_html=True)


def _duration(seconds: Any) -> str:
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "—"
    minutes, remainder = divmod(total, 60.0)
    return f"{int(minutes)}:{remainder:04.1f}"


def _run_label(snapshot: dict) -> str:
    kind = {"synthetic_demo": "Synthetic", "real_traffic_demo": "Real sample"}.get(
        snapshot.get("source_kind"), "Uploaded"
    )
    return (
        f"{snapshot.get('source_name')} · {snapshot.get('camera_label')} · {kind} · "
        f"{_duration(snapshot.get('duration_seconds'))} · {snapshot.get('snapshot_id')}"
    )


def _source_notice(snapshot: dict) -> None:
    label = SOURCE_KINDS.get(snapshot.get("source_kind"), "Unknown source")
    if snapshot.get("source_kind") == "synthetic_demo":
        st.warning(f"{label}. Counts are scripted for demonstration, not observed traffic.")
    else:
        st.info(f"{label}. Counts are unverified candidates for human review.")


def _render_current(current_snapshot: dict | None, database_path: Path | str, key_prefix: str) -> None:
    if not current_snapshot:
        return
    _section("Current analysis", "Save this processed run to compare it later. Footage itself is not stored.")
    saved = load_analysis_snapshot(
        snapshot_id=current_snapshot["snapshot_id"], database_path=database_path
    )
    cols = st.columns([3, 1])
    cols[0].markdown(f"**{_run_label(current_snapshot)}**")
    if saved:
        cols[0].caption(f"Already in library · last saved {saved.get('updated_at')}")
    if cols[1].button(
        "Update saved run" if saved else "Save to library",
        key=f"{key_prefix}_save_current",
        type="primary",
        width="stretch",
    ):
        _, created = save_analysis_snapshot(snapshot=current_snapshot, database_path=database_path)
        st.toast("Saved to Analysis Library" if created else "Saved run updated (no duplicate created)")
        st.rerun()


def _render_details(snapshot: dict) -> None:
    summary = snapshot.get("summary", {})
    _source_notice(snapshot)
    metrics = st.columns(4)
    metrics[0].metric("Footage analysed", _duration(snapshot.get("duration_seconds")))
    metrics[1].metric("Candidate warnings", snapshot.get("event_count", 0))
    metrics[2].metric("Suspected incidents", snapshot.get("incident_count", 0))
    metrics[3].metric("Vehicle tracker IDs", summary.get("distinct_vehicle_track_ids", 0))
    st.caption(summary.get("unique_physical_vehicles_note", ""))
    left, right = st.columns(2)
    with left:
        st.markdown("**Summary metrics**")
        st.json({key: value for key, value in summary.items() if key != "unique_physical_vehicles_note"}, expanded=False)
        st.markdown("**Provenance**")
        st.json(snapshot.get("provenance", {}), expanded=False)
    with right:
        st.markdown("**Settings**")
        st.json(snapshot.get("config", {}), expanded=False)
        st.markdown("**Analysis zone**")
        st.json(snapshot.get("zone", {}), expanded=False)
    st.caption(
        f"Video SHA-256 {snapshot.get('video_sha256')} · created {snapshot.get('created_at')} · "
        f"updated {snapshot.get('updated_at')}"
    )
    st.download_button(
        "Download run JSON",
        snapshots_to_json([snapshot]),
        f"nearmiss_{snapshot.get('snapshot_id')}.json",
        "application/json",
        key=f"download_run_{snapshot.get('snapshot_id')}",
    )


def _format_value(metric: str, value: Any) -> str:
    if value is None:
        return "—"
    if metric == "duration_seconds":
        return _duration(value)
    return f"{value:g}" if isinstance(value, float) else str(value)


def _render_comparison(comparison: dict, key_prefix: str) -> None:
    if comparison["provenance_mismatch"]:
        st.error(comparison["caveats"][0])
    elif comparison.get("source_difference"):
        st.warning(comparison["caveats"][0])
    if comparison["comparison_kind"] == "identical_snapshot":
        st.info("Both selections are the same saved run.")
    rows = [
        {
            "Metric": row["label"],
            "Baseline": _format_value(row["metric"], row["baseline"]),
            "Comparison": _format_value(row["metric"], row["candidate"]),
            "Difference": "—" if row["delta"] is None else f"{row['delta']:+g}",
        }
        for row in comparison["metrics"]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    if comparison["setting_changes"]:
        with st.expander(f"Setting differences ({len(comparison['setting_changes'])})", expanded=False):
            st.dataframe(
                pd.DataFrame(comparison["setting_changes"]).astype(str), width="stretch", hide_index=True
            )
    st.markdown("**Read before interpreting**")
    for caveat in comparison["caveats"]:
        if (comparison["provenance_mismatch"] or comparison.get("source_difference")) and (
            caveat == comparison["caveats"][0]
        ):
            continue
        st.markdown(f"- {caveat}")
    st.caption(comparison["ranking_note"])
    downloads = st.columns(2)
    downloads[0].download_button(
        "Comparison CSV",
        comparison_to_csv(comparison),
        "nearmiss_comparison.csv",
        "text/csv",
        key=f"{key_prefix}_comparison_csv",
    )
    downloads[1].download_button(
        "Comparison JSON",
        comparison_to_json(comparison),
        "nearmiss_comparison.json",
        "application/json",
        key=f"{key_prefix}_comparison_json",
    )


def render_history_page(
    *,
    current_snapshot: dict[str, Any] | None = None,
    database_path: Path | str = DEFAULT_DATABASE_PATH,
    key_prefix: str = "history",
) -> None:
    """Render the Analysis Library: saved runs, details, comparison, exports.

    ``current_snapshot`` is an unsaved dict from ``build_analysis_snapshot``;
    when given, a save/update button is shown. The caller renders the page
    header; this function only renders page body sections.
    """

    _render_current(current_snapshot, database_path, key_prefix)
    snapshots = list_analysis_snapshots(database_path=database_path)

    _section("Saved runs", "Each row is one footage + settings + zone combination. Re-saving updates it in place.")
    if not snapshots:
        st.markdown(
            '<div class="nm-empty"><strong>No saved runs yet</strong>'
            '<div style="margin-top:.45rem">Analyze footage or open the synthetic demonstration, '
            "then choose Save to library. Saved runs keep summary counts, settings and provenance "
            "only; no video is stored.</div></div>",
            unsafe_allow_html=True,
        )
        for caveat in BASE_CAVEATS:
            st.caption(caveat)
        return

    table = pd.DataFrame(snapshot_table_rows(snapshots))
    table["duration"] = table["duration_seconds"].map(_duration)
    st.dataframe(
        table[
            [
                "source_name",
                "camera_label",
                "source_kind",
                "duration",
                "candidate_warnings",
                "suspected_incidents",
                "distinct_vehicle_track_ids",
                "updated_at",
                "snapshot_id",
            ]
        ].rename(
            columns={
                "source_name": "Source",
                "camera_label": "Camera",
                "source_kind": "Kind",
                "duration": "Footage",
                "candidate_warnings": "Candidate warnings",
                "suspected_incidents": "Suspected incidents",
                "distinct_vehicle_track_ids": "Vehicle tracker IDs",
                "updated_at": "Last saved",
                "snapshot_id": "Run ID",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    library_downloads = st.columns(2)
    library_downloads[0].download_button(
        "Library CSV", snapshots_to_csv(snapshots), "nearmiss_library.csv", "text/csv",
        key=f"{key_prefix}_library_csv",
    )
    library_downloads[1].download_button(
        "Library JSON", snapshots_to_json(snapshots), "nearmiss_library.json", "application/json",
        key=f"{key_prefix}_library_json",
    )

    by_id = {snapshot["snapshot_id"]: snapshot for snapshot in snapshots}
    ids = list(by_id)
    default_index = (
        ids.index(current_snapshot["snapshot_id"])
        if current_snapshot and current_snapshot.get("snapshot_id") in by_id
        else 0
    )

    _section("Run details")
    selected = st.selectbox(
        "Saved run",
        ids,
        index=default_index,
        format_func=lambda snapshot_id: _run_label(by_id[snapshot_id]),
        key=f"{key_prefix}_selected",
    )
    _render_details(by_id[selected])

    _section(
        "Compare two runs",
        "Shows count and exposure differences with caveats. It does not rank locations by safety.",
    )
    if len(ids) < 2:
        st.info("Save a second run (for example, the same footage with different settings) to compare.")
        return
    pick = st.columns(2)
    baseline_id = pick[0].selectbox(
        "Baseline", ids, index=0, format_func=lambda i: _run_label(by_id[i]), key=f"{key_prefix}_baseline"
    )
    candidate_id = pick[1].selectbox(
        "Comparison", ids, index=1, format_func=lambda i: _run_label(by_id[i]), key=f"{key_prefix}_candidate"
    )
    _render_comparison(
        compare_analysis_snapshots(baseline=by_id[baseline_id], candidate=by_id[candidate_id]), key_prefix
    )
