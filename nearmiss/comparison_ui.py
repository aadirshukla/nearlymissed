"""Streamlit page for the one-setting threshold sensitivity comparison."""

from __future__ import annotations

from typing import Any

import streamlit as st

from nearmiss.comparison import (
    DISCLAIMER,
    PARAMETER,
    PARAMETER_LABEL,
    STEP,
    ComparisonError,
    allowed_range,
    compare_threshold,
    comparison_json,
    inputs_fingerprint,
    validate_threshold_config,
)
from nearmiss.events import format_timestamp
from nearmiss.investigation import is_synthetic_source


def open_in_investigation(video_id: str, frame_index: int, track_ids: list[int]) -> None:
    """Same session-state contract as app.py ``open_investigation``."""

    prefix = f"investigation_{video_id}"
    st.session_state[f"{prefix}_frame"] = int(frame_index)
    if track_ids:
        st.session_state.pop(f"{prefix}_types", None)
        st.session_state.pop(f"{prefix}_classes", None)
        st.session_state[f"{prefix}_tracks"] = list(track_ids)
    st.session_state["_next_page"] = "Investigation"


def _participants(summary: dict) -> str:
    a = ", ".join(str(value) for value in summary.get("participant_a_track_ids") or []) or "?"
    b = ", ".join(str(value) for value in summary.get("participant_b_track_ids") or []) or "?"
    return f"#{a} ↔ #{b}"


def _gap(summary: dict) -> str:
    value = summary.get("arrival_time_gap_seconds")
    return f"{value:.2f} s" if isinstance(value, (int, float)) else "—"


def _row(summary: dict, prefix: str = "") -> dict[str, Any]:
    return {
        f"{prefix}Event": summary.get("event_id"),
        f"{prefix}Level": summary.get("severity"),
        f"{prefix}Start": format_timestamp(summary.get("start_timestamp_seconds")),
        f"{prefix}End": format_timestamp(summary.get("end_timestamp_seconds")),
        f"{prefix}Arrival gap": _gap(summary),
    }


def _jump_button(video_id: str, summary: dict, key: str, label: str) -> None:
    frame = summary.get("investigation_frame_index")
    if frame is None:
        st.caption(f"{label}: no frame index recorded, so no Investigation link.")
        return
    st.button(
        f"{label} · {format_timestamp(summary.get('start_timestamp_seconds'))} · "
        f"{_participants(summary)}",
        key=key,
        on_click=open_in_investigation,
        args=(video_id, int(frame), list(summary.get("investigation_track_ids") or [])),
    )


def _section(title: str, rows: list[dict], kind: str, video_id: str, prefix: str) -> None:
    st.markdown(f"**{title} ({len(rows)})**")
    if not rows:
        st.caption("None.")
        return
    table = []
    for row in rows:
        if kind == "retained":
            table.append(
                {
                    "Participants": _participants(row["baseline"]),
                    **_row(row["baseline"], "Baseline "),
                    **_row(row["changed"], "Changed "),
                }
            )
        else:
            summary = row["baseline" if kind == "removed" else "changed"]
            overlaps = row.get("overlaps_changed_event_ids") or row.get("overlaps_baseline_event_ids")
            table.append(
                {
                    "Participants": _participants(summary),
                    **_row(summary),
                    "Overlaps (merge/split)": ", ".join(str(item) for item in overlaps or []) or "—",
                }
            )
    st.dataframe(table, hide_index=True, width="stretch")
    for index, row in enumerate(rows):
        summary = row["changed"] if kind != "removed" else row["baseline"]
        _jump_button(video_id, summary, f"{prefix}_{kind}_{index}", f"Investigate {kind}")


def render_comparison(
    *,
    tracks: list[dict] | None,
    events: list[dict] | None,
    cfg: dict | None,
    zone_polygon: list | None,
    frame_size: tuple[int, int] | list[int] | None,
    data_source: str | None,
    video_id: str | None,
) -> None:
    """Compare baseline warnings with one changed arrival-gap threshold."""

    video_key = str(video_id or "video")
    prefix = f"comparison_{video_key}"
    synthetic = is_synthetic_source(data_source, tracks or ())
    st.info(DISCLAIMER)
    if synthetic:
        st.warning(
            "SYNTHETIC DEMO: scripted track rows, not a real location, real traffic or a "
            "real incident. Comparison results describe the detector on generated data only."
        )

    problems = validate_threshold_config(cfg)
    if problems:
        st.error("Baseline detector settings are invalid, so no comparison was run. " + " ".join(problems))
        return
    if not tracks:
        st.warning("No stored track rows are available for this footage, so there is nothing to re-run.")
        return

    baseline_value = float(cfg[PARAMETER])
    minimum, maximum = allowed_range(cfg)
    value_key = f"{prefix}_value"
    stored = st.session_state.get(value_key)
    if not isinstance(stored, (int, float)) or not minimum <= stored <= maximum:
        st.session_state[value_key] = baseline_value
    st.caption(
        f"Only **{PARAMETER_LABEL}** (`{PARAMETER}`) changes. Every other setting, the stored "
        "tracks, source and zone stay fixed. The baseline settings are never modified. "
        f"Allowed range {minimum:.2f}–{maximum:.2f} s keeps HIGH ≤ MEDIUM ≤ LOW."
    )
    cols = st.columns(2)
    cols[0].metric(f"Baseline {PARAMETER_LABEL.lower()}", f"{baseline_value:.2f} s")
    changed_value = cols[1].number_input(
        f"Changed {PARAMETER_LABEL.lower()} (s)",
        min_value=float(minimum),
        max_value=float(maximum),
        step=float(STEP),
        format="%.2f",
        key=value_key,
    )

    current = inputs_fingerprint(
        tracks=tracks,
        events=events,
        cfg=cfg,
        zone_polygon=zone_polygon,
        frame_size=list(frame_size) if frame_size else None,
        data_source=data_source,
        video_id=video_id,
        changed_value=round(float(changed_value), 6),
    )
    result_key, error_key, input_key = f"{prefix}_result", f"{prefix}_error", f"{prefix}_inputs"
    if st.button("Re-run detector on stored tracks", type="primary", key=f"{prefix}_run"):
        st.session_state.pop(result_key, None)
        st.session_state.pop(error_key, None)
        st.session_state[input_key] = current
        try:
            with st.spinner("Re-running the conflict detector twice on stored tracks…"):
                st.session_state[result_key] = compare_threshold(
                    tracks=tracks,
                    events=events,
                    cfg=cfg,
                    zone_polygon=zone_polygon,
                    frame_size=frame_size,
                    data_source=data_source,
                    video_id=video_id,
                    changed_value=changed_value,
                )
        except ComparisonError as exc:
            st.session_state[error_key] = str(exc)
        except Exception as exc:  # detector failures stay visible without taking down the page
            st.session_state[error_key] = f"The conflict detector failed: {type(exc).__name__}: {exc}"

    if st.session_state.get(input_key) != current:
        st.caption("Select **Re-run detector on stored tracks** to compare with the current values.")
        return
    if st.session_state.get(error_key):
        st.error(st.session_state[error_key])
        return
    result = st.session_state.get(result_key)
    if not result:
        return

    counts = result["counts"]
    parameter = result["parameter"]
    metric_cols = st.columns(5)
    metric_cols[0].metric("Baseline episodes", counts["baseline_episodes"])
    metric_cols[1].metric("Changed episodes", counts["changed_episodes"])
    metric_cols[2].metric("Retained", counts["retained"])
    metric_cols[3].metric("Removed", counts["removed"])
    metric_cols[4].metric("Added", counts["added"])
    st.caption(
        f"{PARAMETER_LABEL}: {parameter['baseline_value']:.2f} s → {parameter['changed_value']:.2f} s. "
        f"{counts['retained_with_severity_change']} retained episode(s) changed level. "
        "Episodes are matched by logical participants (stitched track IDs) and overlapping "
        "time intervals, not by event number."
    )
    if parameter["identical_setting"]:
        st.caption("The changed value equals the baseline, so both runs used identical settings.")
    if result["provenance"].get("supplied_events_match_baseline_rerun") is False:
        st.warning(
            "The baseline re-run does not match the warnings currently shown elsewhere in the "
            "app. They may come from different settings; this comparison uses the re-run."
        )
    if counts["baseline_episodes"] == 0 and counts["changed_episodes"] == 0:
        st.info(
            "The detector produced no warning episodes under either setting. That is not "
            "evidence that the scene is safe."
        )
    else:
        episodes = result["episodes"]
        _section("Retained", episodes["retained"], "retained", video_key, prefix)
        _section("Removed by the changed setting", episodes["removed"], "removed", video_key, prefix)
        _section("Added by the changed setting", episodes["added"], "added", video_key, prefix)
        st.caption(
            "Investigation opens the source frame and participants. Added episodes are not "
            "in the Investigation evidence list, which shows baseline warnings only."
        )

    st.download_button(
        "Download comparison JSON",
        data=comparison_json(result),
        file_name=f"{'synthetic_' if synthetic else ''}threshold_comparison_{video_key[:16]}.json",
        mime="application/json",
        key=f"{prefix}_download",
    )
