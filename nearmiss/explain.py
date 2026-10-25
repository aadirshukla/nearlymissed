"""Plain-language explanations of the measured evidence behind each flag.

Every sentence is derived from fields the detectors already computed; nothing
here adds evidence, scores, or probabilities.
"""

from __future__ import annotations

from math import acos, degrees, isfinite
from typing import Any

from nearmiss.config import DEFAULT_CONFLICT_CONFIG


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _angle_between(first: Any, second: Any) -> float | None:
    try:
        ax, ay = (float(value) for value in first)
        bx, by = (float(value) for value in second)
    except (TypeError, ValueError):
        return None
    first_speed = (ax * ax + ay * ay) ** 0.5
    second_speed = (bx * bx + by * by) ** 0.5
    if first_speed <= 1e-9 or second_speed <= 1e-9:
        return None
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (first_speed * second_speed)))
    return degrees(acos(cosine))


PATTERN_LABELS = {
    "crossing": "Crossing paths",
    "following": "Same-direction following",
    "opposing": "Opposing / turning paths",
    "stationary": "Approach to a stopped vehicle",
    "unknown": "Unclassified interaction",
}


def interaction_pattern(event: dict) -> str:
    """Classify a warning by the measured geometry of its two participants."""

    if event.get("conflict_geometry") == "same_direction_following":
        return "following"
    first = event.get("participant_a_velocity_pixels_per_second")
    second = event.get("participant_b_velocity_pixels_per_second")
    angle = _angle_between(first, second)
    if angle is None:
        speeds = []
        for velocity in (first, second):
            try:
                speeds.append(sum(float(value) ** 2 for value in velocity) ** 0.5)
            except (TypeError, ValueError):
                speeds.append(None)
        if any(speed is not None and speed <= 2.0 for speed in speeds):
            return "stationary"
        return "unknown"
    if angle < 30.0:
        return "following"
    if angle > 150.0:
        return "opposing"
    if 45.0 <= angle <= 135.0:
        return "crossing"
    return "opposing"


def _participant(event: dict, side: str) -> str:
    track_id = event.get(f"participant_{side}_track_id", "?")
    kind = event.get(f"participant_{side}_class") or event.get(f"participant_{side}_type") or "road user"
    return f"{kind} #{track_id}"


def explain_event(event: dict, config: dict | None = None) -> dict[str, Any]:
    """Return a headline plus evidence bullets for one prediction warning."""

    config = {**DEFAULT_CONFLICT_CONFIG, **(config or {})}
    first, second = _participant(event, "a"), _participant(event, "b")
    severity = str(event.get("severity", "flagged")).upper()
    gap = _number(event.get("arrival_time_gap_seconds"))
    ttc = _number(event.get("time_to_conflict_seconds"))
    high = _number(config.get("high_time_gap_seconds")) or 0.5
    medium = _number(config.get("medium_time_gap_seconds")) or 1.0
    low = _number(config.get("low_time_gap_seconds")) or 1.75
    horizon = _number(config.get("prediction_horizon_seconds")) or 2.0
    pattern = interaction_pattern(event)
    bullets: list[str] = []

    if pattern == "following":
        headway = _number(event.get("time_headway_seconds", gap))
        bullets.append(
            f"{first} and {second} travel in the same direction; the trailing vehicle "
            f"is closing on the one ahead."
        )
        if ttc is not None:
            bullets.append(
                f"At constant speed their footprints would meet in about {ttc:.2f}s, "
                f"inside the {horizon:.1f}s look-ahead window."
            )
        if headway is not None:
            bullets.append(
                f"Time headway is {headway:.2f}s (HIGH ≤ {high:.2f}s, MEDIUM ≤ {medium:.2f}s, "
                f"LOW ≤ {low:.2f}s)."
            )
    else:
        eta_a = _number(event.get("participant_a_eta_seconds"))
        eta_b = _number(event.get("participant_b_eta_seconds"))
        if eta_a is not None and eta_b is not None:
            bullets.append(
                f"Projected paths share a conflict point: {first} would reach it in "
                f"{eta_a:.2f}s and {second} in {eta_b:.2f}s."
            )
        if gap is not None:
            bullets.append(
                f"Arrival gap is {gap:.2f}s (HIGH ≤ {high:.2f}s, MEDIUM ≤ {medium:.2f}s, "
                f"LOW ≤ {low:.2f}s)."
            )
    separation = _number(event.get("path_separation_pixels"))
    radius = _number(event.get("conflict_region_radius_pixels"))
    if separation is not None and radius is not None:
        overlap = "overlap" if event.get("projected_footprints_overlap", True) else "nearly overlap"
        bullets.append(
            f"Projected footprints {overlap}: {separation:.1f}px apart against a "
            f"{radius:.1f}px combined footprint."
        )
    closing = _number(event.get("closing_speed_pixels_per_second"))
    if closing is not None:
        bullets.append(f"The pair was closing at {closing:.0f}px/s in image space.")
    persistence = event.get("high_persistence_frames") if severity == "HIGH" else event.get(
        "medium_or_high_persistence_frames"
    )
    if persistence:
        bullets.append(
            f"Across the observed episode, the longest consecutive run at {severity} lasted "
            f"{int(persistence)} frames; a minimum consecutive run is required, so a single "
            "noisy frame cannot raise this warning."
        )
    headline = {
        "following": f"{severity}: a trailing vehicle closed on a slower vehicle ahead",
        "crossing": f"{severity}: two vehicles were projected to reach the same point nearly together",
        "opposing": f"{severity}: opposing or turning paths were projected to meet",
        "stationary": f"{severity}: a moving vehicle was projected to reach a stopped one",
    }.get(pattern, f"{severity}: projected paths converged")
    return {
        "headline": headline,
        "pattern": pattern,
        "pattern_label": PATTERN_LABELS[pattern],
        "bullets": bullets,
        "caveat": "Image-space pixels and constant-velocity projection; not a measured speed, "
        "distance, or collision probability.",
    }


SIGNAL_TEXT = {
    "persistent_bounding_box_contact": "Vehicle boxes stayed in contact for {frames} frames.",
    "significant_bounding_box_overlap": "Peak box overlap reached {overlap:.0%} of the smaller box.",
    "previously_converging_trajectories": "Before contact, the vehicles were converging at "
    "{closing}px/s (gap shrank {reduction}px).",
    "abrupt_motion_change": "At least one vehicle changed velocity abruptly right after contact.",
    "sudden_deceleration": "At least one vehicle slowed sharply right after contact.",
    "stopped_after_approach": "At least one vehicle stopped after approaching at speed.",
    "post_contact_track_loss": "A vehicle track disappeared shortly after contact.",
}


def explain_incident(incident: dict) -> dict[str, Any]:
    """Return evidence bullets for one suspected-collision candidate."""

    measurements = incident.get("measurements", {}) or {}
    values = {
        "frames": incident.get("contact_persistence_frames", "?"),
        "overlap": _number(measurements.get("peak_overlap_fraction_smaller_box")) or 0.0,
        "closing": measurements.get("closing_speed_pixels_per_second", "?"),
        "reduction": measurements.get("distance_reduction_pixels", "?"),
    }
    bullets = []
    for signal in incident.get("detection_signals", []):
        template = SIGNAL_TEXT.get(str(signal))
        bullets.append(
            template.format(**values) if template else str(signal).replace("_", " ").capitalize()
        )
    lead = _number(incident.get("prediction_lead_seconds"))
    if incident.get("associated_prediction_event_id") and lead is not None and lead > 0:
        prediction = (
            f"Prediction warning {incident['associated_prediction_event_id']} was raised "
            f"{lead:.2f}s before first contact."
        )
    else:
        prediction = (
            "No prediction warning preceded first contact; the incident detector "
            "found this evidence independently."
        )
    return {
        "headline": f"{len(bullets)} supporting signals observed across the contact episode",
        "bullets": bullets,
        "prediction": prediction,
        "caveat": "A review candidate only. Box overlap can come from camera perspective; "
        "an operator must check the footage.",
    }
