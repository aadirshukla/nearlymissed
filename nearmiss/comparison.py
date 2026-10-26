"""Controlled one-setting threshold sensitivity comparison.

The real conflict detector is re-run on the already stored track rows (no YOLO
re-inference) twice: once with the baseline settings exactly as supplied and
once with a copy in which only the maximum qualifying arrival gap
(``low_time_gap_seconds``) differs. Warning episodes are matched by logical
participants (stitched raw track IDs) and overlapping episode intervals, never
by the sequential ``conflict-NNN`` IDs, which renumber whenever the set of
episodes changes.

This is sensitivity exploration of a screening heuristic. It is not a safety
rating: fewer flags under a stricter setting does not mean safer traffic.
"""

from __future__ import annotations

import copy
import hashlib
import json
from math import isfinite
from typing import Any, Callable

import numpy as np

from conflict_detector import detect_conflicts
from nearmiss.events import normalize_events
from nearmiss.geometry import enrich_tracks_with_zone
from nearmiss.investigation import evidence_track_ids, is_synthetic_source
from nearmiss.safety import deduplicate_events


COMPARISON_SCHEMA = "nearmiss.threshold_comparison/1"
PARAMETER = "low_time_gap_seconds"
PARAMETER_LABEL = "Maximum qualifying arrival gap"
PARAMETER_UNIT = "seconds"
# Same range and step as the sidebar "Maximum arrival gap" slider in app.py.
MINIMUM_VALUE = 0.50
MAXIMUM_VALUE = 3.00
STEP = 0.05
THRESHOLD_KEYS = ("high_time_gap_seconds", "medium_time_gap_seconds", "low_time_gap_seconds")
INTERVAL_TOLERANCE_SECONDS = 1e-6

DISCLAIMER = (
    "Sensitivity exploration only, not a safety rating. Both runs use the same stored "
    "tracks, source and zone; only the maximum qualifying arrival gap differs. Fewer "
    "flags under a stricter setting does not mean the traffic is safer, and more flags "
    "does not mean it is more dangerous."
)

Detector = Callable[[list, list, dict], Any]


class ComparisonError(ValueError):
    """Raised for invalid comparison inputs; the message is shown to the user."""


def _finite(value: Any) -> float | None:
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _int(value: Any) -> int | None:
    number = _finite(value)
    if number is None or number != int(number):
        return None
    return int(number)


def json_safe(value: Any) -> Any:
    """Convert numpy scalars/arrays, tuples and sets; non-finite floats become None."""

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if isfinite(number) else None
    if value is None or isinstance(value, (int, str)):
        return value
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_threshold_config(cfg: Any) -> list[str]:
    """Return readable problems with the arrival-gap thresholds (empty if valid)."""

    if not isinstance(cfg, dict):
        return ["Detector settings must be a dictionary."]
    errors: list[str] = []
    values: dict[str, float] = {}
    for key in THRESHOLD_KEYS:
        if key not in cfg:
            errors.append(f"`{key}` is missing.")
            continue
        number = _finite(cfg[key])
        if number is None:
            errors.append(f"`{key}` must be a finite number (got {cfg[key]!r}).")
        elif number <= 0:
            errors.append(f"`{key}` must be greater than 0 (got {number:g}).")
        else:
            values[key] = number
    if len(values) == len(THRESHOLD_KEYS):
        high, medium, low = (values[key] for key in THRESHOLD_KEYS)
        if not high <= medium <= low:
            errors.append(
                "Arrival-gap thresholds must satisfy HIGH ≤ MEDIUM ≤ LOW "
                f"(got {high:g} / {medium:g} / {low:g} s)."
            )
    low = values.get(PARAMETER)
    if low is not None and not MINIMUM_VALUE <= low <= MAXIMUM_VALUE:
        errors.append(
            f"{PARAMETER_LABEL} must be between {MINIMUM_VALUE:.2f} and "
            f"{MAXIMUM_VALUE:.2f} s (got {low:g})."
        )
    return errors


def allowed_range(cfg: dict) -> tuple[float, float]:
    """Inclusive range for the changed value that keeps MEDIUM ≤ LOW."""

    medium = _finite(cfg.get("medium_time_gap_seconds")) or MINIMUM_VALUE
    return max(MINIMUM_VALUE, medium), MAXIMUM_VALUE


def build_changed_config(baseline: dict, value: Any) -> dict:
    """Deep copy of ``baseline`` with only the maximum qualifying gap replaced."""

    problems = validate_threshold_config(baseline)
    if problems:
        raise ComparisonError("Baseline settings are invalid: " + " ".join(problems))
    number = _finite(value)
    if number is None:
        raise ComparisonError(f"{PARAMETER_LABEL} must be a finite number (got {value!r}).")
    changed = copy.deepcopy(baseline)
    changed[PARAMETER] = round(number, 6)
    problems = validate_threshold_config(changed)
    if problems:
        raise ComparisonError("Changed setting is invalid: " + " ".join(problems))
    return changed


def changed_settings(baseline: dict, changed: dict) -> list[str]:
    """Keys whose values differ between two settings dictionaries."""

    keys = set(baseline) | set(changed)
    return sorted(
        key for key in keys
        if _canonical(baseline.get(key, "<missing>")) != _canonical(changed.get(key, "<missing>"))
    )


def resolve_zone(zone_polygon: Any, frame_size: Any) -> tuple[list[list[float]], bool]:
    """Return the zone used by the detector and whether it was user-drawn.

    Mirrors app.py: fewer than three points means the whole frame is analyzed.
    """

    if isinstance(zone_polygon, (list, tuple)) and len(zone_polygon) >= 3:
        points: list[list[float]] = []
        for point in zone_polygon:
            if not isinstance(point, (list, tuple, np.ndarray)) or len(point) != 2:
                raise ComparisonError("Zone polygon points must be [x, y] pairs.")
            x, y = _finite(point[0]), _finite(point[1])
            if x is None or y is None:
                raise ComparisonError("Zone polygon contains a non-finite coordinate.")
            points.append([x, y])
        return points, True
    if not isinstance(frame_size, (list, tuple)) or len(frame_size) != 2:
        raise ComparisonError("Frame size (width, height) is required when no zone is drawn.")
    width, height = _finite(frame_size[0]), _finite(frame_size[1])
    if width is None or height is None or width <= 0 or height <= 0:
        raise ComparisonError(f"Frame size must be positive (got {frame_size!r}).")
    return [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]], False


def run_detector(
    tracks: list[dict], zone: list[list[float]], cfg: dict, detector: Detector | None = None
) -> list[dict]:
    """Run the detector plus app.py's post-processing on private copies."""

    detector = detector or detect_conflicts
    detector_tracks = enrich_tracks_with_zone(copy.deepcopy(tracks), copy.deepcopy(zone))
    raw = detector(detector_tracks, copy.deepcopy(zone), copy.deepcopy(cfg))
    # Detector rows always carry timestamp_seconds, so fps is never used for a fallback.
    events, warnings = normalize_events(raw, 0.0)
    if warnings:
        raise ComparisonError("Detector output was malformed: " + " ".join(warnings))
    return deduplicate_events(events)


def _participant_sets(event: dict) -> tuple[frozenset[int], frozenset[int]] | None:
    sides = []
    for side in ("a", "b"):
        ids: set[int] = set()
        for prefix in (f"participant_{side}", f"vehicle_{side}"):
            single = _int(event.get(f"{prefix}_track_id"))
            if single is not None:
                ids.add(single)
            many = event.get(f"{prefix}_track_ids")
            if isinstance(many, (list, tuple, set, frozenset, np.ndarray)):
                ids.update(value for value in (_int(item) for item in many) if value is not None)
        if not ids:
            return None
        sides.append(frozenset(ids))
    return sides[0], sides[1]


def same_participants(first: dict, second: dict) -> bool:
    """True when both episodes involve the same two logical (stitched) tracks."""

    a, b = _participant_sets(first) or (None, None), _participant_sets(second) or (None, None)
    if None in a or None in b:
        return False
    return bool((a[0] & b[0]) and (a[1] & b[1])) or bool((a[0] & b[1]) and (a[1] & b[0]))


def episode_interval(event: dict) -> tuple[float, float] | None:
    start = next(
        (
            value
            for value in (
                _finite(event.get(key))
                for key in ("first_alert_timestamp_seconds", "start_timestamp_seconds", "timestamp_seconds")
            )
            if value is not None
        ),
        None,
    )
    if start is None:
        return None
    end = _finite(event.get("end_timestamp_seconds"))
    measurement = _finite(event.get("timestamp_seconds"))
    end = max(value for value in (start, end, measurement) if value is not None)
    return start, end


def _overlap(first: tuple[float, float], second: tuple[float, float]) -> float | None:
    low, high = max(first[0], second[0]), min(first[1], second[1])
    return high - low if low <= high + INTERVAL_TOLERANCE_SECONDS else None


def episode_summary(event: dict) -> dict[str, Any]:
    interval = episode_interval(event)
    sides = _participant_sets(event)
    frame = _int(event.get("start_frame_index"))
    if frame is None:
        frame = _int(event.get("frame_index"))
    return json_safe(
        {
            "event_id": event.get("event_id"),
            "severity": str(event.get("severity", "")).upper() or None,
            "participant_a_track_ids": sorted(sides[0]) if sides else [],
            "participant_b_track_ids": sorted(sides[1]) if sides else [],
            "participant_a_type": event.get("participant_a_type"),
            "participant_b_type": event.get("participant_b_type"),
            "conflict_geometry": event.get("conflict_geometry"),
            "start_timestamp_seconds": interval[0] if interval else None,
            "end_timestamp_seconds": interval[1] if interval else None,
            "measurement_timestamp_seconds": _finite(event.get("timestamp_seconds")),
            "start_frame_index": _int(event.get("start_frame_index")),
            "measurement_frame_index": _int(event.get("frame_index")),
            "arrival_time_gap_seconds": _finite(event.get("arrival_time_gap_seconds")),
            "time_to_conflict_seconds": _finite(event.get("time_to_conflict_seconds")),
            "heuristic_risk_index": _finite(event.get("risk_score")),
            "persistence_frames": _int(event.get("persistence_frames")),
            "investigation_frame_index": frame,
            "investigation_track_ids": evidence_track_ids(event),
        }
    )


def match_episodes(baseline: list[dict], changed: list[dict]) -> dict[str, Any]:
    """One-to-one match by logical participants and overlapping intervals.

    Candidate pairs are ranked by overlap duration, then start-time distance,
    then list position, so the result is deterministic. Unmatched episodes are
    removed/added; when one of them overlaps an already matched episode of the
    same pair (a merge or split), that partner is listed in ``overlaps``.
    """

    intervals_a = [episode_interval(event) for event in baseline]
    intervals_b = [episode_interval(event) for event in changed]
    candidates: list[tuple[float, float, int, int]] = []
    for i, event_a in enumerate(baseline):
        for j, event_b in enumerate(changed):
            if intervals_a[i] is None or intervals_b[j] is None:
                continue
            if not same_participants(event_a, event_b):
                continue
            overlap = _overlap(intervals_a[i], intervals_b[j])
            if overlap is None:
                continue
            candidates.append((-overlap, abs(intervals_a[i][0] - intervals_b[j][0]), i, j))
    candidates.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, _, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    partners_a = {i: [j for *_, ci, j in candidates if ci == i] for i in range(len(baseline))}
    partners_b = {j: [i for *_, i, cj in candidates if cj == j] for j in range(len(changed))}

    retained = []
    for i, j in sorted(pairs):
        before, after = episode_summary(baseline[i]), episode_summary(changed[j])
        retained.append(
            {
                "baseline": before,
                "changed": after,
                "severity_changed": before["severity"] != after["severity"],
                "interval_changed": (
                    before["start_timestamp_seconds"] != after["start_timestamp_seconds"]
                    or before["end_timestamp_seconds"] != after["end_timestamp_seconds"]
                ),
            }
        )
    removed = [
        {
            "baseline": episode_summary(baseline[i]),
            "overlaps_changed_event_ids": [changed[j].get("event_id") for j in sorted(partners_a[i])],
        }
        for i in range(len(baseline))
        if i not in used_a
    ]
    added = [
        {
            "changed": episode_summary(changed[j]),
            "overlaps_baseline_event_ids": [baseline[i].get("event_id") for i in sorted(partners_b[j])],
        }
        for j in range(len(changed))
        if j not in used_b
    ]
    return json_safe({"retained": retained, "removed": removed, "added": added})


def _severity_counts(events: list[dict]) -> dict[str, int]:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for event in events:
        severity = str(event.get("severity", "")).upper()
        if severity in counts:
            counts[severity] += 1
    return counts


def _episode_identity(events: list[dict]) -> list[str]:
    return sorted(_canonical(episode_summary(event)) for event in events)


def compare_threshold(
    *,
    tracks: list[dict],
    events: list[dict] | None,
    cfg: dict,
    zone_polygon: Any,
    frame_size: Any,
    data_source: str | None,
    video_id: str | None,
    changed_value: Any,
    detector: Detector | None = None,
) -> dict[str, Any]:
    """Re-run the detector at baseline and changed settings and match episodes.

    Inputs are deep-copied first and never modified. Raises ComparisonError for
    invalid inputs; detector exceptions propagate to the caller unchanged.
    """

    if not isinstance(tracks, list):
        raise ComparisonError("Stored tracks must be a list of track rows.")
    if not isinstance(cfg, dict):
        raise ComparisonError("Detector settings must be a dictionary.")
    tracks_copy = copy.deepcopy(tracks)
    supplied_events = copy.deepcopy(events) if isinstance(events, list) else []
    zone, user_defined = resolve_zone(copy.deepcopy(zone_polygon), frame_size)
    baseline_cfg = copy.deepcopy(cfg)
    baseline_cfg.setdefault("zone_is_user_defined", user_defined)
    changed_cfg = build_changed_config(baseline_cfg, changed_value)
    differing = changed_settings(baseline_cfg, changed_cfg)
    if differing not in ([], [PARAMETER]):
        raise ComparisonError(f"Only {PARAMETER} may change; found differences in {differing}.")

    baseline_events = run_detector(tracks_copy, zone, baseline_cfg, detector)
    changed_events = run_detector(tracks_copy, zone, changed_cfg, detector)
    matches = match_episodes(baseline_events, changed_events)
    synthetic = is_synthetic_source(data_source, tracks_copy)
    supplied_check = (
        _episode_identity(supplied_events) == _episode_identity(baseline_events)
        if isinstance(events, list)
        else None
    )
    result = {
        "schema": COMPARISON_SCHEMA,
        "disclaimer": DISCLAIMER,
        "provenance": {
            "video_id": video_id,
            "data_source": data_source,
            "synthetic": synthetic,
            "label": "SYNTHETIC DEMO — not a real location or incident" if synthetic else None,
            "track_rows": len(tracks_copy),
            "tracks_sha256": fingerprint(tracks_copy),
            "zone_polygon": zone,
            "zone_is_user_defined": user_defined,
            "frame_size": list(frame_size) if isinstance(frame_size, (list, tuple)) else None,
            "detector": "conflict_detector.detect_conflicts",
            "post_processing": ["nearmiss.events.normalize_events", "nearmiss.safety.deduplicate_events"],
            "re_inference": False,
            "supplied_baseline_events": len(supplied_events) if isinstance(events, list) else None,
            "supplied_baseline_events_sha256": (
                fingerprint(supplied_events) if isinstance(events, list) else None
            ),
            "supplied_events_match_baseline_rerun": supplied_check,
        },
        "parameter": {
            "key": PARAMETER,
            "label": PARAMETER_LABEL,
            "unit": PARAMETER_UNIT,
            "baseline_value": _finite(baseline_cfg[PARAMETER]),
            "changed_value": _finite(changed_cfg[PARAMETER]),
            "allowed_range": list(allowed_range(baseline_cfg)),
            "identical_setting": not differing,
        },
        "settings": {
            "baseline": baseline_cfg,
            "changed": changed_cfg,
            "baseline_sha256": fingerprint(baseline_cfg),
            "changed_sha256": fingerprint(changed_cfg),
            "differing_keys": differing,
        },
        "counts": {
            "baseline_episodes": len(baseline_events),
            "changed_episodes": len(changed_events),
            "retained": len(matches["retained"]),
            "removed": len(matches["removed"]),
            "added": len(matches["added"]),
            "retained_with_severity_change": sum(row["severity_changed"] for row in matches["retained"]),
            "baseline_by_severity": _severity_counts(baseline_events),
            "changed_by_severity": _severity_counts(changed_events),
        },
        "episodes": matches,
    }
    return json_safe(result)


def inputs_fingerprint(**inputs: Any) -> str:
    """Identity of comparison inputs, used to detect stale results in the UI."""

    return fingerprint(inputs)


def comparison_json(result: dict) -> bytes:
    """Deterministic, strictly valid JSON (sorted keys, no NaN/Infinity)."""

    return json.dumps(json_safe(result), sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
