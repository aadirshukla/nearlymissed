"""Pure helpers for frame-by-frame investigation of source footage.

Everything here works on rows already produced by the tracker (or by the
labeled synthetic demonstration). Nothing is inferred, interpolated or
re-detected: a participant with no row at the requested frame is reported as
missing rather than drawn at a guessed position. All positions, distances and
speeds are uncalibrated image-space measurements (pixels, pixels per second).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from math import atan2, degrees, floor, hypot, isfinite
from typing import Any

import cv2
import numpy as np


INVESTIGATION_SCHEMA = "nearmiss.investigation/v1"
IMAGE_UNITS = {
    "position": "image pixels (uncalibrated; origin top-left, y increases downward)",
    "distance": "pixels",
    "speed": "pixels_per_second",
    "heading": "degrees in image space (0 = toward image right, 90 = toward image bottom)",
    "time": "seconds from the start of the source video",
}
FRAME_SOURCE_NOTE = (
    "Original source-video frame decoded with OpenCV at the requested timestamp "
    "(nearmiss.video.frame_at_timestamp); overlays are drawn on a copy."
)
OBSERVATION_NOTE = (
    "Rows are tracker observations exactly as stored. No interpolation, "
    "smoothing or re-detection is applied."
)
SYNTHETIC_NOTE = (
    "SYNTHETIC DEMONSTRATION: generated footage with scripted track observations. "
    "Not real traffic data, not calibrated road measurements."
)
REVIEW_NOTE = (
    "Prediction events and suspected incidents are review candidates. Only a human "
    "reviewer can confirm or dismiss an incident; this investigation does not change "
    "any review decision."
)
SYNTHETIC_SOURCE_KINDS = {"synthetic", "synthetic_demo", "demo", "generated", "scripted"}

OBJECT_TYPE_COLORS = {
    "vehicle": (60, 146, 251),
    "pedestrian": (191, 212, 45),
    "cyclist": (230, 120, 200),
}
DEFAULT_COLOR = (200, 200, 200)
MUTED_COLOR = (130, 130, 130)
TRAIL_GAP_FRAMES = 5

# Each singular ID is followed by its stitched raw-ID array. Conflict detection merges
# fragmented tracker IDs, so the array can name raw track IDs the singular key does not.
_EVENT_TRACK_KEYS = (
    "participant_a_track_id",
    "participant_a_track_ids",
    "participant_b_track_id",
    "participant_b_track_ids",
    "vehicle_a_track_id",
    "vehicle_a_track_ids",
    "vehicle_b_track_id",
    "vehicle_b_track_ids",
    "vehicle_track_id",
    "vehicle_track_ids",
    "pedestrian_track_id",
    "pedestrian_track_ids",
    "cyclist_track_id",
    "cyclist_track_ids",
)


# ---------------------------------------------------------------------------
# Small conversions
# ---------------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _finite(value)
    if number is None or number != int(number):
        return None
    return int(number)


def _bbox(row: dict) -> list[float] | None:
    bbox = row.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    values = [_finite(value) for value in bbox]
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = values
    if x2 < x1 or y2 < y1:
        return None
    return [x1, y1, x2, y2]


def _ground_point(bbox: list[float]) -> tuple[float, float]:
    """Bottom-centre of a box, matching the trail convention in nearmiss.video."""

    return ((bbox[0] + bbox[2]) / 2.0, bbox[3])


def metadata_fields(metadata: Any) -> dict[str, float | int]:
    """Read fps/frame_count/width/height from a VideoMetadata, dict or None."""

    if is_dataclass(metadata) and not isinstance(metadata, type):
        raw = asdict(metadata)
    elif isinstance(metadata, dict):
        raw = metadata
    else:
        raw = {}
    fps = _finite(raw.get("fps")) or 0.0
    return {
        "fps": fps if fps > 0 else 0.0,
        "frame_count": max(0, _int(raw.get("frame_count")) or 0),
        "width": max(0, _int(raw.get("width")) or 0),
        "height": max(0, _int(raw.get("height")) or 0),
        "duration_seconds": max(0.0, _finite(raw.get("duration_seconds")) or 0.0),
    }


def is_synthetic_source(source_kind: str | None, tracks: Iterable[dict] = ()) -> bool:
    """True when the caller or any track row declares synthetic provenance."""

    kind = str(source_kind or "").strip().lower()
    if kind in SYNTHETIC_SOURCE_KINDS or kind.startswith("synthetic"):
        return True
    for row in tracks or ():
        if isinstance(row, dict) and "synthetic" in str(row.get("data_source", "")).lower():
            return True
    return False


def frame_index_for_timestamp(
    timestamp_seconds: float, fps: float, frame_count: int | None = None
) -> int:
    """Frame whose display interval contains the timestamp, clamped to the video."""

    if fps <= 0:
        return 0
    seconds = max(0.0, _finite(timestamp_seconds) or 0.0)
    index = int(floor(seconds * fps + 1e-6))
    if frame_count:
        index = min(index, max(0, int(frame_count) - 1))
    return index


def timestamp_for_frame_index(frame_index: int, fps: float) -> float:
    """Start time of a frame; nearmiss.video.frame_at_timestamp decodes exactly it."""

    if fps <= 0:
        return 0.0
    return max(0, int(frame_index)) / float(fps)


# ---------------------------------------------------------------------------
# Observation selection and filtering
# ---------------------------------------------------------------------------


def clean_observations(tracks: Iterable[dict] | None) -> list[dict]:
    """Copy rows with a usable track ID, frame index and bounding box.

    Malformed rows are dropped rather than repaired so that every returned row is
    a real stored observation.
    """

    cleaned: list[dict] = []
    for raw in tracks or ():
        if not isinstance(raw, dict):
            continue
        track_id = _int(raw.get("track_id"))
        frame_index = _int(raw.get("frame_index"))
        bbox = _bbox(raw)
        if track_id is None or frame_index is None or frame_index < 0 or bbox is None:
            continue
        row = dict(raw)
        row["track_id"] = track_id
        row["frame_index"] = frame_index
        row["bbox"] = bbox
        row["timestamp_seconds"] = _finite(raw.get("timestamp_seconds"))
        row["object_type"] = str(raw.get("object_type") or "other")
        row["class_name"] = str(raw.get("class_name") or row["object_type"])
        cleaned.append(row)
    cleaned.sort(key=lambda row: (row["frame_index"], row["track_id"]))
    return cleaned


def _as_set(values: Iterable[Any] | None, cast=str) -> set | None:
    if values is None:
        return None
    result = set()
    for value in values:
        try:
            result.add(cast(value))
        except (TypeError, ValueError):
            continue
    return result


def filter_observations(
    tracks: Iterable[dict] | None,
    *,
    track_ids: Iterable[int] | None = None,
    object_types: Iterable[str] | None = None,
    class_names: Iterable[str] | None = None,
) -> list[dict]:
    """Filter cleaned rows. ``None`` means "no filter"; an empty list matches nothing."""

    wanted_ids = _as_set(track_ids, int)
    wanted_types = _as_set(object_types)
    wanted_classes = _as_set(class_names)
    return [
        row
        for row in clean_observations(tracks)
        if (wanted_ids is None or row["track_id"] in wanted_ids)
        and (wanted_types is None or row["object_type"] in wanted_types)
        and (wanted_classes is None or row["class_name"] in wanted_classes)
    ]


def observations_at_frame(
    tracks: Iterable[dict] | None,
    frame_index: int,
    *,
    track_ids: Iterable[int] | None = None,
    object_types: Iterable[str] | None = None,
    class_names: Iterable[str] | None = None,
    tolerance_frames: int = 0,
) -> list[dict]:
    """Return stored rows at a frame, one per track, never synthesizing a row.

    With ``tolerance_frames > 0`` a track without an exact row may contribute its
    nearest stored row within that many frames; such rows are labeled
    ``match = "nearest_within_tolerance"`` and keep their own frame index and
    timestamp, plus ``frame_offset`` relative to the request.
    """

    requested = int(frame_index)
    tolerance = max(0, int(tolerance_frames))
    best: dict[int, dict] = {}
    for row in filter_observations(
        tracks, track_ids=track_ids, object_types=object_types, class_names=class_names
    ):
        offset = row["frame_index"] - requested
        if abs(offset) > tolerance:
            continue
        current = best.get(row["track_id"])
        # Prefer the closest row; on ties prefer the earlier (already-seen) frame.
        if current is None or abs(offset) < abs(current["frame_offset"]):
            best[row["track_id"]] = {
                **row,
                "frame_offset": offset,
                "match": "exact" if offset == 0 else "nearest_within_tolerance",
            }
    return [best[track_id] for track_id in sorted(best)]


def nearest_observed_frame(
    tracks: Iterable[dict] | None, track_id: int, frame_index: int
) -> int | None:
    """Closest frame index with a stored row for the track, or None if never seen."""

    frames = [row["frame_index"] for row in filter_observations(tracks, track_ids=[track_id])]
    if not frames:
        return None
    return min(frames, key=lambda frame: (abs(frame - int(frame_index)), frame))


# ---------------------------------------------------------------------------
# Evidence (prediction events and suspected incidents)
# ---------------------------------------------------------------------------


def evidence_track_ids(record: dict) -> list[int]:
    """Participant track IDs named by a prediction event or incident record."""

    ids: list[int] = []
    for key in _EVENT_TRACK_KEYS:
        raw = record.get(key)
        if isinstance(raw, (set, frozenset)):
            values = sorted(raw, key=repr)
        elif isinstance(raw, np.ndarray):
            values = raw.ravel().tolist()
        elif isinstance(raw, (list, tuple)):
            values = list(raw)
        else:
            values = [raw]
        for item in values:
            # bool is an int subclass; True/False are never track IDs.
            if isinstance(item, (bool, np.bool_)):
                continue
            value = _int(item)
            if value is not None and value not in ids:
                ids.append(value)
    return ids


def _evidence_row(record: dict, kind: str) -> dict | None:
    # Navigation time is when the evidence first applies: first suspected impact
    # for incidents, first alert for predictions. The representative measurement
    # (``timestamp_seconds``/``frame_index``) is carried separately.
    if kind == "suspected_incident":
        time_fields = ("first_suspected_impact_timestamp_seconds", "timestamp_seconds")
        identifier = record.get("incident_id")
    else:
        time_fields = ("first_alert_timestamp_seconds", "timestamp_seconds")
        identifier = record.get("event_id")
    time_field = next((key for key in time_fields if _finite(record.get(key)) is not None), None)
    if time_field is None:
        return None
    if time_field == "first_alert_timestamp_seconds":
        event_frame = _int(record.get("start_frame_index"))
    elif time_field == "timestamp_seconds":
        event_frame = _int(record.get("frame_index"))
    else:
        event_frame = None
    measurement_time = _finite(record.get("timestamp_seconds"))
    row = {
        "evidence_kind": kind,
        "evidence_id": str(identifier) if identifier is not None else None,
        "event_time_seconds": round(float(record[time_field]), 6),
        "event_time_field": time_field,
        "event_frame_index": event_frame,
        "measurement_timestamp_seconds": (
            round(measurement_time, 6) if measurement_time is not None else None
        ),
        "measurement_frame_index": _int(record.get("frame_index")),
        "participant_track_ids": evidence_track_ids(record),
        "severity": record.get("severity"),
        "interaction_type": record.get("interaction_type"),
        "description": record.get("description"),
    }
    if kind == "prediction_event":
        row["first_alert_timestamp_seconds"] = _finite(
            record.get("first_alert_timestamp_seconds")
        )
    else:
        row["review_status"] = record.get("review_status") or "Not reviewed"
    return row


def evidence_timeline(
    events: Iterable[dict] | None, incidents: Iterable[dict] | None
) -> list[dict]:
    """All timed evidence records, ordered by event time. Untimed records are skipped."""

    rows: list[dict] = []
    for kind, records in (("prediction_event", events), ("suspected_incident", incidents)):
        for record in records or ():
            if isinstance(record, dict):
                row = _evidence_row(record, kind)
                if row is not None:
                    rows.append(row)
    rows.sort(key=lambda row: (row["event_time_seconds"], row["evidence_kind"]))
    return rows


def nearby_evidence(
    events: Iterable[dict] | None,
    incidents: Iterable[dict] | None,
    timestamp_seconds: float,
    *,
    window_seconds: float = 2.0,
    track_ids: Iterable[int] | None = None,
) -> list[dict]:
    """Evidence within ±window of a timestamp, closest first, with explicit offsets.

    ``offset_seconds`` is event time minus requested time (negative = earlier).
    When ``track_ids`` is given, only evidence naming at least one of them is kept.
    """

    requested = _finite(timestamp_seconds) or 0.0
    window = max(0.0, _finite(window_seconds) or 0.0)
    wanted = _as_set(track_ids, int)
    selected: list[dict] = []
    for row in evidence_timeline(events, incidents):
        offset = row["event_time_seconds"] - requested
        if abs(offset) > window + 1e-9:
            continue
        if wanted is not None and not wanted.intersection(row["participant_track_ids"]):
            continue
        selected.append({**row, "offset_seconds": round(offset, 6)})
    selected.sort(key=lambda row: (abs(row["offset_seconds"]), row["event_time_seconds"]))
    return selected


# ---------------------------------------------------------------------------
# Participants, trails and movement
# ---------------------------------------------------------------------------


def participant_catalog(
    tracks: Iterable[dict] | None,
    *,
    frame_index: int | None = None,
    events: Iterable[dict] | None = None,
    incidents: Iterable[dict] | None = None,
) -> list[dict]:
    """One summary per track, ranked for investigation.

    Ranking: visible at the requested frame, then named in more evidence records,
    then more observations, then lower track ID.
    """

    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in clean_observations(tracks):
        grouped[row["track_id"]].append(row)
    evidence_counts: Counter[int] = Counter()
    for row in evidence_timeline(events, incidents):
        evidence_counts.update(row["participant_track_ids"])

    catalog = []
    for track_id, rows in grouped.items():
        frames = [row["frame_index"] for row in rows]
        catalog.append(
            {
                "track_id": track_id,
                "object_type": Counter(row["object_type"] for row in rows).most_common(1)[0][0],
                "class_name": Counter(row["class_name"] for row in rows).most_common(1)[0][0],
                "observation_count": len(rows),
                "first_frame_index": min(frames),
                "last_frame_index": max(frames),
                "visible_at_frame": frame_index is not None and int(frame_index) in frames,
                "evidence_count": evidence_counts.get(track_id, 0),
            }
        )
    catalog.sort(
        key=lambda item: (
            not item["visible_at_frame"],
            -item["evidence_count"],
            -item["observation_count"],
            item["track_id"],
        )
    )
    for rank, item in enumerate(catalog, start=1):
        item["rank"] = rank
    return catalog


def evidence_focus(
    catalog: list[dict],
    evidence_row: dict,
    *,
    object_types: Iterable[str] | None = None,
    class_names: Iterable[str] | None = None,
) -> dict:
    """Filters and track selection that keep one evidence record's participants in view.

    Returns the evidence participants that have stored observations (stitched raw
    IDs included) plus the current type/class filters widened just enough to
    offer them. ``None`` filters mean "no filter" and stay ``None``.
    """

    by_id = {item["track_id"]: item for item in catalog}
    track_ids = [
        track_id for track_id in evidence_row.get("participant_track_ids", []) if track_id in by_id
    ]

    def widened(current: Iterable[str] | None, field: str) -> list[str] | None:
        if current is None:
            return None
        values = list(current)
        for track_id in track_ids:
            if by_id[track_id][field] not in values:
                values.append(by_id[track_id][field])
        return values

    return {
        "track_ids": track_ids,
        "object_types": widened(object_types, "object_type"),
        "class_names": widened(class_names, "class_name"),
    }


def filter_participants(
    catalog: list[dict],
    *,
    track_ids: Iterable[int] | None = None,
    object_types: Iterable[str] | None = None,
    class_names: Iterable[str] | None = None,
) -> list[dict]:
    """Filter a participant catalog; ``None`` means no filter, preserving rank order."""

    wanted_ids = _as_set(track_ids, int)
    wanted_types = _as_set(object_types)
    wanted_classes = _as_set(class_names)
    return [
        item
        for item in catalog
        if (wanted_ids is None or item["track_id"] in wanted_ids)
        and (wanted_types is None or item["object_type"] in wanted_types)
        and (wanted_classes is None or item["class_name"] in wanted_classes)
    ]


def _row_time(row: dict, fps: float) -> float | None:
    if row.get("timestamp_seconds") is not None:
        return float(row["timestamp_seconds"])
    return row["frame_index"] / fps if fps > 0 else None


def track_trail(
    tracks: Iterable[dict] | None,
    track_id: int,
    frame_index: int,
    *,
    trail_frames: int = 30,
) -> list[dict]:
    """Observed ground points for one track in ``[frame - trail_frames, frame]``.

    The trail never extends past the requested frame (no look-ahead) and contains
    only stored rows; gaps remain gaps.
    """

    end = int(frame_index)
    start = end - max(0, int(trail_frames))
    points = []
    for row in filter_observations(tracks, track_ids=[track_id]):
        if start <= row["frame_index"] <= end:
            x, y = _ground_point(row["bbox"])
            points.append(
                {
                    "frame_index": row["frame_index"],
                    "timestamp_seconds": row["timestamp_seconds"],
                    "x": round(x, 2),
                    "y": round(y, 2),
                }
            )
    return points


def _direction_label(dx: float, dy: float) -> str:
    vertical = "down" if dy > 0 else "up"
    horizontal = "right" if dx > 0 else "left"
    if abs(dx) < 0.5 * abs(dy):
        return f"toward image {'bottom' if dy > 0 else 'top'}"
    if abs(dy) < 0.5 * abs(dx):
        return f"toward image {horizontal}"
    return f"toward image {vertical}-{horizontal}"


def movement_summary(
    tracks: Iterable[dict] | None,
    track_id: int,
    frame_index: int,
    *,
    fps: float,
    window_frames: int = 30,
    stationary_pixels: float = 2.0,
) -> dict:
    """Image-space movement of one track over observed rows in the trail window."""

    rows = [
        row
        for row in filter_observations(tracks, track_ids=[track_id])
        if int(frame_index) - max(0, int(window_frames)) <= row["frame_index"] <= int(frame_index)
    ]
    all_rows = filter_observations(tracks, track_ids=[track_id])
    summary: dict[str, Any] = {
        "track_id": int(track_id),
        "object_type": all_rows[0]["object_type"] if all_rows else None,
        "class_name": all_rows[0]["class_name"] if all_rows else None,
        "observed_at_requested_frame": any(
            row["frame_index"] == int(frame_index) for row in all_rows
        ),
        "nearest_observed_frame_index": nearest_observed_frame(all_rows, track_id, frame_index),
        "window_start_frame_index": max(0, int(frame_index) - max(0, int(window_frames))),
        "window_end_frame_index": int(frame_index),
        "observations_in_window": len(rows),
        "missing_frames_in_observed_span": None,
        "first_observed_frame_index": rows[0]["frame_index"] if rows else None,
        "last_observed_frame_index": rows[-1]["frame_index"] if rows else None,
        "elapsed_seconds": None,
        "displacement_pixels": None,
        "path_length_pixels": None,
        "mean_speed_pixels_per_second": None,
        "heading_image_degrees": None,
        "direction": None,
        "units": "image pixels; uncalibrated",
    }
    if not rows:
        summary["direction"] = "no observations in window"
        return summary
    span = rows[-1]["frame_index"] - rows[0]["frame_index"] + 1
    summary["missing_frames_in_observed_span"] = span - len(rows)
    if len(rows) < 2:
        summary["direction"] = "single observation; movement not measurable"
        return summary

    points = [_ground_point(row["bbox"]) for row in rows]
    path = sum(
        hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:], strict=False)
    )
    dx = points[-1][0] - points[0][0]
    dy = points[-1][1] - points[0][1]
    start_time = _row_time(rows[0], fps)
    end_time = _row_time(rows[-1], fps)
    elapsed = (end_time - start_time) if start_time is not None and end_time is not None else None
    summary.update(
        {
            "elapsed_seconds": round(elapsed, 4) if elapsed is not None else None,
            "displacement_pixels": round(hypot(dx, dy), 2),
            "path_length_pixels": round(path, 2),
            "mean_speed_pixels_per_second": (
                round(path / elapsed, 2) if elapsed is not None and elapsed > 0 else None
            ),
        }
    )
    if hypot(dx, dy) < stationary_pixels:
        summary["direction"] = "stationary in image"
    else:
        summary["heading_image_degrees"] = round(degrees(atan2(dy, dx)) % 360.0, 1)
        summary["direction"] = _direction_label(dx, dy)
    return summary


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _clip_point(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    return (int(round(min(max(x, 0), width - 1))), int(round(min(max(y, 0), height - 1))))


def draw_investigation_frame(
    frame_bgr: np.ndarray,
    observations: Iterable[dict],
    trails: dict[int, list[dict]] | None = None,
    *,
    selected_track_ids: Iterable[int] | None = None,
    track_types: dict[int, str] | None = None,
    gap_frames: int = TRAIL_GAP_FRAMES,
) -> np.ndarray:
    """Draw stored boxes and trails on a copy of an original frame.

    Selected tracks get thick coloured boxes and labels; others a thin muted box.
    Boxes are clipped to the frame; boxes entirely outside it and malformed rows
    are skipped. Trail segments are broken where consecutive observations are
    more than ``gap_frames`` apart so missing frames are not drawn as motion.
    ``track_types`` maps track ID to object type for trail colours.
    """

    if not isinstance(frame_bgr, np.ndarray) or frame_bgr.ndim not in (2, 3) or frame_bgr.size == 0:
        raise ValueError("Investigation overlays need a decoded image array.")
    canvas = frame_bgr.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    if canvas.dtype != np.uint8:
        canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    height, width = canvas.shape[:2]
    selected = _as_set(selected_track_ids, int) or set()

    for track_id, points in (trails or {}).items():
        color = (
            OBJECT_TYPE_COLORS.get(str((track_types or {}).get(int(track_id))), DEFAULT_COLOR)
            if int(track_id) in selected
            else MUTED_COLOR
        )
        previous = None
        for point in points:
            x, y = _finite(point.get("x")), _finite(point.get("y"))
            if x is None or y is None:
                previous = None
                continue
            current = (_clip_point(x, y, width, height), int(point["frame_index"]))
            if previous is not None and current[1] - previous[1] <= gap_frames:
                cv2.line(canvas, previous[0], current[0], color, 2, cv2.LINE_AA)
            cv2.circle(canvas, current[0], 2, color, -1, cv2.LINE_AA)
            previous = current

    for row in observations:
        bbox = _bbox(row) if isinstance(row, dict) else None
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        if x2 < 0 or y2 < 0 or x1 > width - 1 or y1 > height - 1:
            continue
        top_left = _clip_point(x1, y1, width, height)
        bottom_right = _clip_point(x2, y2, width, height)
        track_id = _int(row.get("track_id"))
        is_selected = track_id in selected
        color = (
            OBJECT_TYPE_COLORS.get(str(row.get("object_type")), DEFAULT_COLOR)
            if is_selected
            else MUTED_COLOR
        )
        cv2.rectangle(canvas, top_left, bottom_right, color, 3 if is_selected else 1)
        if is_selected:
            label = f"#{track_id} {row.get('class_name') or row.get('object_type') or ''}".strip()
            if row.get("match") == "nearest_within_tolerance":
                label += f" (frame {row.get('frame_index')})"
            cv2.putText(
                canvas,
                label,
                (top_left[0] + 3, max(16, top_left[1] - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )
    return canvas


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_investigation_export(
    *,
    video_id: str | None,
    source_kind: str | None,
    metadata: Any,
    tracks: Iterable[dict] | None,
    events: Iterable[dict] | None,
    incidents: Iterable[dict] | None,
    frame_index: int,
    selected_track_ids: Iterable[int],
    object_types: Iterable[str] | None = None,
    class_names: Iterable[str] | None = None,
    trail_frames: int = 30,
    evidence_window_seconds: float = 2.0,
    frame_decoded: bool | None = None,
) -> dict:
    """Assemble a self-describing record of one investigation view.

    ``observed_rows`` holds only stored rows at exactly the requested frame for
    the selected tracks. Selected tracks without such a row are listed in
    ``selected_tracks_without_observation`` with a reason and their nearest
    observed frame; no position is invented for them.
    """

    rows = clean_observations(tracks)
    meta = metadata_fields(metadata)
    fps = float(meta["fps"])
    requested_frame = max(0, int(frame_index))
    requested_time = timestamp_for_frame_index(requested_frame, fps)
    selected = sorted(_as_set(selected_track_ids, int) or set())
    types = sorted(_as_set(object_types)) if object_types is not None else None
    classes = sorted(_as_set(class_names)) if class_names is not None else None

    observed = observations_at_frame(
        rows, requested_frame, track_ids=selected, object_types=types, class_names=classes
    )
    observed_ids = {row["track_id"] for row in observed}
    unfiltered_ids = {
        row["track_id"] for row in observations_at_frame(rows, requested_frame, track_ids=selected)
    }
    missing = [
        {
            "track_id": track_id,
            "reason": (
                "excluded_by_type_or_class_filter"
                if track_id in unfiltered_ids
                else "no_stored_row_at_frame"
            ),
            "nearest_observed_frame_index": nearest_observed_frame(rows, track_id, requested_frame),
        }
        for track_id in selected
        if track_id not in observed_ids
    ]
    synthetic = is_synthetic_source(source_kind, rows)
    data_sources = sorted({str(row["data_source"]) for row in rows if row.get("data_source")})

    export = {
        "schema": INVESTIGATION_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "video_id": video_id,
            "source_kind": source_kind,
            "synthetic": synthetic,
            "synthetic_notice": SYNTHETIC_NOTE if synthetic else None,
            "track_data_sources": data_sources,
            "frame_source": FRAME_SOURCE_NOTE,
            "frame_decoded": frame_decoded,
            "observation_source": OBSERVATION_NOTE,
            "interpolated_rows_included": False,
            "units": IMAGE_UNITS,
            "review_context": REVIEW_NOTE,
        },
        "request": {
            "frame_index": requested_frame,
            "timestamp_seconds": round(requested_time, 6),
            "fps": fps,
            "frame_count": meta["frame_count"],
            "frame_width": meta["width"],
            "frame_height": meta["height"],
        },
        "selection": {
            "track_ids": selected,
            "object_types": types,
            "class_names": classes,
            "trail_frames": max(0, int(trail_frames)),
            "evidence_window_seconds": float(evidence_window_seconds),
        },
        "observed_rows": [
            {key: value for key, value in row.items() if key not in ("match", "frame_offset")}
            for row in observed
        ],
        "selected_tracks_without_observation": missing,
        "movement_summaries": [
            movement_summary(rows, track_id, requested_frame, fps=fps, window_frames=trail_frames)
            for track_id in selected
        ],
        "nearby_evidence": nearby_evidence(
            events,
            incidents,
            requested_time,
            window_seconds=evidence_window_seconds,
            track_ids=selected or None,
        ),
    }
    return _json_safe(export)


def investigation_json(export: dict) -> bytes:
    """Serialize an export as UTF-8 JSON (numpy values and NaN made JSON-safe)."""

    return json.dumps(_json_safe(export), indent=2, sort_keys=False, allow_nan=False).encode(
        "utf-8"
    )
