"""Source-backed metrics and visuals for intersection safety analysis."""

from __future__ import annotations

import csv
import json
from collections import Counter
from io import StringIO
from typing import Any

import cv2
import numpy as np


SEVERITIES = ("LOW", "MEDIUM", "HIGH")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def event_pair_key(event: dict) -> tuple[int, ...] | None:
    """Return a stable unordered participant key when IDs are usable."""

    values = [
        event.get("participant_a_track_id", event.get("vehicle_a_track_id")),
        event.get("participant_b_track_id", event.get("vehicle_b_track_id")),
    ]
    try:
        identifiers = tuple(sorted(int(value) for value in values if value is not None))
    except (TypeError, ValueError):
        return None
    return identifiers if len(identifiers) == 2 else None


def deduplicate_events(events: list[dict], cooldown_seconds: float = 2.0) -> list[dict]:
    """Merge only repeated/overlapping episodes for the same vehicle pair."""

    valid = [dict(event) for event in events if isinstance(event, dict)]
    valid.sort(
        key=lambda event: _number(
            event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
        )
        or 0.0
    )
    deduplicated: list[dict] = []
    for event in valid:
        pair = event_pair_key(event)
        start = _number(
            event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
        )
        end = _number(event.get("end_timestamp_seconds", event.get("timestamp_seconds")))
        if pair is None or start is None:
            deduplicated.append(event)
            continue
        match_index = None
        for index in range(len(deduplicated) - 1, -1, -1):
            previous = deduplicated[index]
            if event_pair_key(previous) != pair:
                continue
            previous_end = _number(
                previous.get("end_timestamp_seconds", previous.get("timestamp_seconds"))
            )
            if previous_end is not None and start - previous_end <= cooldown_seconds:
                match_index = index
            break
        if match_index is None:
            deduplicated.append(event)
            continue
        previous = deduplicated[match_index]
        severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        strongest = max(
            (previous, event),
            key=lambda item: (
                severity_rank.get(str(item.get("severity", "")).upper(), 0),
                _number(item.get("risk_score")) or 0.0,
            ),
        )
        merged = dict(strongest)
        merged["first_alert_timestamp_seconds"] = min(
            start,
            _number(
                previous.get(
                    "first_alert_timestamp_seconds", previous.get("timestamp_seconds")
                )
            )
            or start,
        )
        if end is not None:
            merged["end_timestamp_seconds"] = max(
                end,
                _number(previous.get("end_timestamp_seconds")) or end,
            )
        merged["merged_event_count"] = int(previous.get("merged_event_count", 1)) + int(
            event.get("merged_event_count", 1)
        )
        deduplicated[match_index] = merged
    return deduplicated


def safety_statistics(
    tracks: list[dict], events: list[dict], duration_seconds: float
) -> dict[str, Any]:
    """Calculate dashboard/report metrics from processed records only."""

    unique_events = deduplicate_events(events)
    vehicle_ids = {
        int(record["track_id"])
        for record in tracks
        if isinstance(record, dict)
        and record.get("object_type") == "vehicle"
        and record.get("track_id") is not None
    }
    counts = Counter(str(event.get("severity", "")).upper() for event in unique_events)
    gaps = [
        value
        for value in (_number(event.get("arrival_time_gap_seconds")) for event in unique_events)
        if value is not None
    ]
    distinct_pairs = {
        pair for pair in (event_pair_key(event) for event in unique_events) if pair is not None
    }
    minutes = max(0.0, float(duration_seconds)) / 60.0
    return {
        "vehicles_tracked": len(vehicle_ids),
        "total_conflicts": len(unique_events),
        "high_conflicts": counts["HIGH"],
        "medium_conflicts": counts["MEDIUM"],
        "low_conflicts": counts["LOW"],
        "conflicts_per_minute": len(unique_events) / minutes if minutes > 0 else 0.0,
        "distinct_vehicle_pairs": len(distinct_pairs),
        "average_arrival_gap_seconds": float(np.mean(gaps)) if gaps else None,
    }


def event_conflict_point(event: dict, width: int, height: int) -> tuple[float, float] | None:
    point = event.get("conflict_point")
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    x, y = _number(point[0]), _number(point[1])
    if x is None or y is None or width <= 0 or height <= 0:
        return None
    if not (0.0 <= x < width and 0.0 <= y < height):
        return None
    return x, y


def normalized_heatmap_points(
    events: list[dict], width: int, height: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in deduplicate_events(events):
        point = event_conflict_point(event, width, height)
        if point is None:
            continue
        x, y = point
        rows.append(
            {
                "event_id": event.get("event_id"),
                "x_pixels": x,
                "y_pixels": y,
                "x_normalized": x / width,
                "y_normalized": y / height,
                "severity": event.get("severity"),
            }
        )
    return rows


def build_conflict_heatmap(
    frame_bgr: np.ndarray,
    events: list[dict],
    opacity: float = 0.55,
    sigma_pixels: float | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Overlay event density on an actual fixed-camera frame.

    Returns an RGB image plus the exact normalized event points used. With no
    valid conflict locations, the source frame is returned unchanged.
    """

    height, width = frame_bgr.shape[:2]
    points = normalized_heatmap_points(events, width, height)
    if not points:
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), []
    density = np.zeros((height, width), dtype=np.float32)
    for row in points:
        x = int(round(row["x_pixels"]))
        y = int(round(row["y_pixels"]))
        if 0 <= x < width and 0 <= y < height:
            density[y, x] += 1.0
    sigma = sigma_pixels or max(12.0, min(width, height) * 0.055)
    kernel = max(3, int(round(sigma * 6)) | 1)
    density = cv2.GaussianBlur(density, (kernel, kernel), sigmaX=sigma, sigmaY=sigma)
    maximum = float(density.max())
    if maximum <= 0:
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB), points
    normalized = np.clip(density / maximum, 0.0, 1.0)
    colored = cv2.applyColorMap(np.uint8(normalized * 255), cv2.COLORMAP_JET)
    alpha = np.clip(normalized * float(np.clip(opacity, 0.0, 1.0)), 0.0, 1.0)[..., None]
    overlay = frame_bgr.astype(np.float32) * (1.0 - alpha) + colored.astype(np.float32) * alpha
    for row in points:
        point = (int(round(row["x_pixels"])), int(round(row["y_pixels"])))
        cv2.circle(overlay, point, 5, (255, 255, 255), 2, cv2.LINE_AA)
    return cv2.cvtColor(np.uint8(np.clip(overlay, 0, 255)), cv2.COLOR_BGR2RGB), points


def timeline_rows(events: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in deduplicate_events(events):
        timestamp = _number(
            event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
        )
        if timestamp is None:
            continue
        rows.append(
            {
                "event_id": event.get("event_id"),
                "timestamp_seconds": timestamp,
                "severity": str(event.get("severity", "")).upper(),
                "risk_score": _number(event.get("risk_score")),
                "participant_a_track_id": event.get("participant_a_track_id"),
                "participant_b_track_id": event.get("participant_b_track_id"),
                "time_to_conflict_seconds": _number(event.get("time_to_conflict_seconds")),
                "arrival_time_gap_seconds": _number(event.get("arrival_time_gap_seconds")),
            }
        )
    return rows


def events_with_review_labels(
    events: list[dict], review_labels: dict[str, str]
) -> list[dict[str, Any]]:
    """Attach session review decisions without mutating detector evidence."""

    allowed = {"Confirmed potential conflict", "False positive", "Uncertain"}
    output: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id"))
        label = review_labels.get(event_id, "Uncertain")
        output.append(
            {
                **event,
                "human_review_status": label if label in allowed else "Uncertain",
            }
        )
    return output


def diagnostics_to_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b"timestamp_seconds,rejection_reason\n"
    fields = sorted({key for row in rows for key in row})
    preferred = [
        "timestamp_seconds",
        "frame_index",
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
        "rejection_reason",
    ]
    fieldnames = [field for field in preferred if field in fields]
    fieldnames.extend(field for field in fields if field not in fieldnames)
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value) if isinstance(value, (list, tuple, dict)) else value
                for key, value in row.items()
            }
        )
    return stream.getvalue().encode("utf-8")


def pipeline_stage_counts(diagnostics: list[dict], events: list[dict]) -> dict[str, int]:
    total = len(diagnostics)
    stage_order = {
        "insufficient_trajectory_observations": 0,
        "stale_or_invalid_observation": 1,
        "not_closing": 2,
        "both_stationary": 2,
        "projected_paths_separated": 3,
        "conflict_is_not_in_future": 4,
        "conflict_point_outside_zone": 5,
        "arrival_gap_above_low_threshold": 6,
        "pending_temporal_confirmation": 7,
        "accepted": 8,
        "accepted_low_uncertainty_margin_only": 8,
    }
    reached = [stage_order.get(row.get("rejection_reason"), 0) for row in diagnostics]
    return {
        "pair_evaluations": total,
        "sufficient_history": sum(stage >= 1 for stage in reached),
        "valid_motion": sum(stage >= 2 for stage in reached),
        "closing_pairs": sum(stage >= 3 for stage in reached),
        "path_candidates": sum(stage >= 4 for stage in reached),
        "future_conflicts": sum(stage >= 5 for stage in reached),
        "zone_eligible": sum(stage >= 6 for stage in reached),
        "timing_eligible": sum(stage >= 7 for stage in reached),
        "temporally_confirmed": sum(stage >= 8 for stage in reached),
        "deduplicated_events": len(deduplicate_events(events)),
    }
