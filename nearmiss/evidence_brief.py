"""Explain & Share: plain-language evidence explanations and Markdown briefs.

Everything here is a pure function of fields the detectors and the local store
already produced. Nothing is re-detected, scored or estimated: when a field is
missing or malformed it is reported as missing instead of being filled in.
Measurements stay in uncalibrated image pixels; no accuracy percentage, safety
rating, crash probability or real-world danger score is produced. Operator
confirmation and simulated dispatch are only described when a persisted review
or notification record is supplied, and synthetic sources are labeled in every
output.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from nearmiss.events import format_timestamp


PREDICTION = "prediction"
INCIDENT = "incident"

SYNTHETIC_BANNER = (
    "SYNTHETIC DEMONSTRATION: generated footage and scripted tracks. "
    "Not a real location, real traffic or a real incident."
)

SOURCE_KIND_LABELS = {
    "synthetic_demo": "Synthetic demonstration (generated footage, scripted tracks)",
    "uploaded_video": "Operator-supplied video",
}

# Review prompts for the quality checklist. These are disclosure thresholds,
# not accuracy limits: crossing one does not make a result right or wrong.
SHORT_CLIP_SECONDS = 20.0
LOW_FRAME_RATE_FPS = 10.0
SPARSE_TRACK_ROWS = 10
LARGE_FRAME_GAP = 5

PREDICTION_FIELDS = {
    "participant_a_track_id": "participant A track ID",
    "participant_b_track_id": "participant B track ID",
    "first_alert_timestamp_seconds": "warning timestamp",
    "arrival_time_gap_seconds": "arrival gap",
    "time_to_conflict_seconds": "time to projected conflict point",
    "path_separation_pixels": "projected separation",
    "persistence_frames": "persistence",
    "closing_speed_pixels_per_second": "closing speed",
}

INCIDENT_FIELDS = {
    "vehicle_a_track_id": "vehicle A track ID",
    "vehicle_b_track_id": "vehicle B track ID",
    "first_suspected_impact_timestamp_seconds": "first suspected-contact timestamp",
    "contact_persistence_frames": "contact persistence",
    "detection_signals": "detection signals",
    "measurements.converging": "convergence result",
    "measurements.distance_reduction_pixels": "distance reduction before contact",
    "measurements.motion_response": "motion-response measurements",
}

SIGNAL_TEXT = {
    "persistent_bounding_box_contact": "vehicle boxes stayed in contact across consecutive frames",
    "significant_bounding_box_overlap": "box overlap passed the strong-overlap threshold",
    "previously_converging_trajectories": "the vehicles were closing on each other before contact",
    "abrupt_motion_change": "abrupt change in motion after contact",
    "sudden_deceleration": "sudden slowdown after contact",
    "stopped_after_approach": "a vehicle stopped after approaching",
    "post_contact_track_loss": "a track ended shortly after contact",
}

MOTION_SIGNALS = (
    "abrupt_motion_change",
    "sudden_deceleration",
    "stopped_after_approach",
    "post_contact_track_loss",
)

NOT_CLAIMED = [
    "It is not proof that a collision or near miss happened; it is computer-vision evidence for human review.",
    "It contains no crash probability, safety rating, accuracy figure or real-world danger score.",
    "Distances and speeds are image pixels, not metres or road speeds; no field calibration was applied.",
    "NearMiss has no external alerting integration. No police, emergency or agency alert was sent.",
    "It is not an official crash report and does not identify a street location.",
]


# ------------------------------------------------------------------ helpers


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number == int(number) else None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")


def md(value: Any) -> str:
    """Escape a supplied value for inline Markdown (single line, no HTML)."""

    text = " ".join(str(value).split())
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f} s"


def _clock(value: float | None) -> str:
    return "—" if value is None else f"{format_timestamp(value)} ({value:.2f} s)"


def _pixels(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} px"


def _pixel_speed(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} px/s"


def _nested(record: dict, dotted: str) -> Any:
    value: Any = record
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _usable(key: str, value: Any) -> bool:
    """Whether a supplied field has the type the explanation needs."""

    if key.endswith("converging"):
        return isinstance(value, bool)
    if key.endswith("detection_signals"):
        return isinstance(value, list) and any(isinstance(item, str) for item in value)
    if key.endswith("motion_response"):
        return isinstance(value, dict) and bool(value)
    return _finite(value) is not None


def missing_fields(kind: str, record: Any) -> list[str]:
    """Human-readable names of expected detector fields that are absent or unusable."""

    expected = PREDICTION_FIELDS if kind == PREDICTION else INCIDENT_FIELDS
    if not isinstance(record, dict):
        return list(expected.values())
    missing = []
    for key, label in expected.items():
        value = _nested(record, key)
        if key == "first_alert_timestamp_seconds" and not _usable(key, value):
            value = record.get("timestamp_seconds")
        if not _usable(key, value):
            missing.append(label)
    return missing


def metadata_dict(metadata: Any) -> dict:
    """Accept a VideoMetadata dataclass, a dict, an object or None."""

    if metadata is None:
        return {}
    if is_dataclass(metadata) and not isinstance(metadata, type):
        return asdict(metadata)
    if isinstance(metadata, dict):
        return dict(metadata)
    return {
        key: getattr(metadata, key)
        for key in ("fps", "frame_count", "width", "height", "duration_seconds")
        if hasattr(metadata, key)
    }


def _is_synthetic_marker(value: Any) -> bool:
    return isinstance(value, str) and "synthetic" in value.lower()


def describe_source(
    source_kind: Any,
    video_id: Any = None,
    tracks: Any = None,
    records: Any = None,
) -> dict:
    """Describe provenance. Any synthetic marker wins over a non-synthetic label."""

    kind = _text(source_kind) or "unspecified"
    markers = [kind, _text(video_id)]
    for collection in (tracks, records):
        if isinstance(collection, list):
            markers.extend(row.get("data_source") for row in collection if isinstance(row, dict))
    is_synthetic = any(_is_synthetic_marker(marker) for marker in markers)
    if is_synthetic:
        label = SOURCE_KIND_LABELS["synthetic_demo"]
        statement = SYNTHETIC_BANNER
        note = (
            None
            if _is_synthetic_marker(kind)
            else "The source was labeled as non-synthetic, but its ID or track rows "
            "carry a synthetic marker, so it is treated as synthetic."
        )
    elif kind in SOURCE_KIND_LABELS:
        label = SOURCE_KIND_LABELS[kind]
        statement = (
            "Operator-supplied footage. NearMiss cannot verify where or when it was "
            "recorded, and results depend on camera angle, lighting and occlusion."
        )
        note = None
    else:
        label = "Unspecified source"
        statement = "The source kind was not supplied; treat provenance as unknown."
        note = None
    return {
        "source_kind": kind,
        "label": label,
        "is_synthetic": is_synthetic,
        "statement": statement,
        "note": note,
    }


# --------------------------------------------------------- record accessors


def _participants(kind: str, record: dict) -> list[dict]:
    prefixes = ("participant_a", "participant_b") if kind == PREDICTION else ("vehicle_a", "vehicle_b")
    output = []
    for prefix in prefixes:
        track_id = _integer(record.get(f"{prefix}_track_id"))
        label = _text(record.get(f"{prefix}_class")) or _text(record.get(f"{prefix}_type"))
        source_ids = record.get(f"{prefix}_track_ids")
        ids = []
        if isinstance(source_ids, (list, tuple)):
            ids = [value for value in (_integer(item) for item in source_ids) if value is not None]
        if track_id is not None and track_id not in ids:
            ids.insert(0, track_id)
        output.append({"track_id": track_id, "class": label, "track_ids": ids})
    return output


def participant_label(participant: dict) -> str:
    name = participant.get("class") or "road user"
    track_id = participant.get("track_id")
    return f"{name} #{track_id}" if track_id is not None else f"{name} (track ID missing)"


def _record_time(kind: str, record: dict) -> float | None:
    if kind == PREDICTION:
        value = _finite(record.get("first_alert_timestamp_seconds"))
        return value if value is not None else _finite(record.get("timestamp_seconds"))
    value = _finite(record.get("first_suspected_impact_timestamp_seconds"))
    return value if value is not None else _finite(record.get("timestamp_seconds"))


def _record_id(kind: str, record: dict, index: int) -> str:
    key = "event_id" if kind == PREDICTION else "incident_id"
    return _text(record.get(key)) or f"{kind}-{index + 1} (no ID supplied)"


def evidence_options(events: Any, incidents: Any) -> list[dict]:
    """Selectable evidence items, suspected incidents and predictions, ordered by time."""

    options: list[dict] = []
    for kind, collection in ((INCIDENT, incidents), (PREDICTION, events)):
        if not isinstance(collection, list):
            continue
        for index, record in enumerate(collection):
            if not isinstance(record, dict):
                continue
            record_id = _record_id(kind, record, index)
            timestamp = _record_time(kind, record)
            pair = " / ".join(participant_label(item) for item in _participants(kind, record))
            prefix = "Suspected incident" if kind == INCIDENT else "Prediction warning"
            options.append(
                {
                    "key": f"{kind}:{record_id}",
                    "kind": kind,
                    "id": record_id,
                    "timestamp_seconds": timestamp,
                    "label": f"{prefix} · {format_timestamp(timestamp)} · {pair} · {record_id}",
                    "record": record,
                }
            )
    options.sort(key=lambda item: (item["timestamp_seconds"] is None, item["timestamp_seconds"] or 0.0, item["kind"] != INCIDENT))
    return options


# --------------------------------------------------------- review/dispatch


def _rows(collection: Any) -> list[dict]:
    if isinstance(collection, dict):
        return [row for row in collection.values() if isinstance(row, dict)]
    if isinstance(collection, list):
        return [row for row in collection if isinstance(row, dict)]
    return []


def review_state(incident: dict, reviews: Any) -> dict:
    """Operator review from persisted rows only; the incident's own field is not proof."""

    incident_id = _text(incident.get("incident_id"))
    video_id = _text(incident.get("source_video_id"))
    match = None
    if incident_id:
        for row in _rows(reviews):
            if _text(row.get("incident_id")) != incident_id:
                continue
            row_video = _text(row.get("video_id"))
            if video_id and row_video and row_video != video_id:
                continue
            match = row
            break
    status = _text(match.get("review_status")) if match else None
    reviewed_at = _text(match.get("reviewed_at")) if match else None
    when = f" ({reviewed_at})" if reviewed_at else ""
    if status == "Confirmed Incident":
        statement = (
            f"An operator marked this as a Confirmed Incident in NearMiss{when}. "
            "This is a human judgment made from the footage, not an official crash report."
        )
    elif status == "False Alarm":
        statement = f"An operator reviewed this and dismissed it as a false alarm{when}."
    elif status == "Uncertain":
        statement = f"An operator reviewed this and left it Uncertain{when}. It remains unconfirmed."
    elif status:
        statement = f"A saved review has an unrecognized status ({md(status)}); it is treated as unconfirmed."
    else:
        statement = "No saved operator review was supplied. This remains an unconfirmed candidate."
    inconsistency = None
    claimed = _text(incident.get("review_status"))
    if claimed == "Confirmed Incident" and status != "Confirmed Incident":
        inconsistency = (
            "The incident record says Confirmed Incident, but no matching saved review "
            "confirms it, so it is shown as unconfirmed."
        )
    return {
        "status": status or "Not reviewed",
        "confirmed": status == "Confirmed Incident",
        "reviewed_at": reviewed_at,
        "camera_id": _text(match.get("camera_id")) if match else _text(incident.get("camera_id")),
        "statement": statement,
        "inconsistency": inconsistency,
    }


def dispatch_state(incident: dict, notifications: Any, review: dict | None = None) -> dict:
    """Describe the local simulated dispatch record. External alerts are never sent."""

    incident_id = _text(incident.get("incident_id"))
    match = None
    if incident_id:
        match = next(
            (row for row in _rows(notifications) if _text(row.get("incident_id")) == incident_id),
            None,
        )
    local_only = "Simulated and local only: NearMiss sent nothing outside this computer."
    inconsistency = None
    if match is None:
        status = "None"
        statement = (
            "No simulated dispatch notice exists for this item. "
            "NearMiss has no external alerting integration, so no external alert was sent."
        )
    else:
        status = _text(match.get("status")) or "Unknown"
        generated = _text(match.get("generated_at"))
        acknowledged = _text(match.get("acknowledged_at"))
        if status == "Withdrawn":
            statement = (
                "A simulated dispatch notice was created and later withdrawn after the "
                f"review decision changed. {local_only}"
            )
        elif status == "Acknowledged":
            statement = (
                "A simulated dispatch notice was created"
                + (f" ({generated})" if generated else "")
                + " and acknowledged in the local inbox"
                + (f" ({acknowledged})" if acknowledged else "")
                + f". {local_only}"
            )
        else:
            statement = (
                f"A simulated dispatch notice is in the local inbox with status {md(status)}"
                + (f" ({generated})" if generated else "")
                + f". {local_only}"
            )
        if status != "Withdrawn" and review is not None and not review.get("confirmed"):
            inconsistency = (
                "A simulated notice exists, but no confirmed review was supplied, so the "
                "item is still treated as unconfirmed."
            )
    return {
        "status": status,
        "notification_id": _text(match.get("notification_id")) if match else None,
        "generated_at": _text(match.get("generated_at")) if match else None,
        "acknowledged_at": _text(match.get("acknowledged_at")) if match else None,
        "external_alert_sent": False,
        "statement": statement,
        "inconsistency": inconsistency,
    }


# ------------------------------------------------------------- explanations


def _fact(label: str, value: str, note: str = "") -> dict:
    return {"label": label, "value": value, "note": note}


ESTABLISHED, PARTIAL, INSUFFICIENT = "established", "partial", "insufficient"
_STATUS_FACT = {
    ESTABLISHED: "Complete for the detector's own criteria",
    PARTIAL: "Partial: some required evidence is missing",
    INSUFFICIENT: "Insufficient: no usable supporting evidence",
}


def _pair_subject(first: dict, second: dict) -> str:
    if first["track_id"] is None and second["track_id"] is None:
        return "two road users whose track IDs were not supplied"
    return f"{md(participant_label(first))} and {md(participant_label(second))}"


def explain_prediction(event: Any) -> dict:
    """Plain-language explanation of a trajectory-prediction warning."""

    record = event if isinstance(event, dict) else {}
    first, second = _participants(PREDICTION, record)
    a, b = md(participant_label(first)), md(participant_label(second))
    warning = _record_time(PREDICTION, record)
    end = _finite(record.get("end_timestamp_seconds"))
    gap = _finite(record.get("arrival_time_gap_seconds"))
    ttc = _finite(record.get("time_to_conflict_seconds"))
    separation = _finite(record.get("path_separation_pixels"))
    persistence = _integer(record.get("persistence_frames"))
    closing = _finite(record.get("closing_speed_pixels_per_second"))
    headway = _finite(record.get("time_headway_seconds"))
    following = record.get("conflict_geometry") == "same_direction_following"

    # The headline claim needs both a timing measure and a projected-geometry
    # measure; an event type or geometry label on its own establishes nothing.
    has_timing = gap is not None or (following and headway is not None)
    has_geometry = separation is not None or ttc is not None
    supplied = [value for value in (gap, ttc, separation, persistence, closing, headway) if value is not None]
    if has_timing and has_geometry:
        status = ESTABLISHED
    elif supplied:
        status = PARTIAL
    else:
        status = INSUFFICIENT
    subject = _pair_subject(first, second)

    sentences = []
    when = f"At {format_timestamp(warning)}" if warning is not None else "At an unknown time (no usable warning timestamp)"
    if status == ESTABLISHED and following:
        sentences.append(
            f"{when}, NearMiss projected the motion of {subject} forward and found a "
            "trailing vehicle closing on a slower vehicle ahead in the same direction."
        )
    elif status == ESTABLISHED:
        sentences.append(
            f"{when}, NearMiss projected the paths of {subject} forward and found they "
            "would reach a shared point close together in time."
        )
    elif status == PARTIAL:
        lacking = []
        if not has_timing:
            lacking.append("an arrival-timing measure")
        if not has_geometry:
            lacking.append("a projected-path measure")
        sentences.append(
            f"{when}, a prediction warning was recorded for {subject}, but the record lacks "
            + " and ".join(lacking)
            + ", so the available evidence cannot establish that their projected paths converge. "
            "Only the values below were supplied."
        )
    else:
        sentences.append(
            f"A prediction warning record was supplied for {subject}, but it contains no usable "
            "timing or projected-path measurements, so the available evidence cannot establish "
            "why it was flagged or that the paths converge."
        )
    if gap is not None:
        sentences.append(f"Their projected arrival times differed by {gap:.2f} s (the arrival gap).")
    if headway is not None and following:
        sentences.append(f"The time headway between them was {headway:.2f} s.")
    if ttc is not None:
        sentences.append(f"The projected conflict point was about {ttc:.2f} s ahead when the warning was raised.")
    if separation is not None:
        sentences.append(f"Their projected paths came within {separation:.1f} px of each other in the image.")
    if persistence is not None:
        span = f" (until {format_timestamp(end)})" if end is not None else ""
        sentences.append(f"The warning condition held for {persistence} analysed frames{span}.")
    if closing is not None:
        sentences.append(f"They were closing at about {closing:.1f} px/s in image coordinates.")
    sentences.append(
        "A prediction warning is a forecast from tracked motion, not an observed contact, and it "
        "does not mean a crash happened or was likely."
    )

    severity = _text(record.get("severity"))
    risk_index = _finite(record.get("risk_score"))
    facts = [
        _fact("Evidence completeness", _STATUS_FACT[status], "Whether timing and projected-path measures were both supplied."),
        _fact("Participants", f"{participant_label(first)} and {participant_label(second)}"),
        _fact("Warning time", _clock(warning), "First frame the warning condition was met."),
        _fact("Warning ended", _clock(end)),
        _fact("Arrival gap", _seconds(gap), "Difference between projected arrival times."),
        _fact("Time to projected conflict point", _seconds(ttc)),
        _fact("Projected separation", _pixels(separation), "Closest approach of projected paths, image pixels."),
        _fact("Persistence", "—" if persistence is None else f"{persistence} frames"),
        _fact("Closing speed", _pixel_speed(closing), "Image pixels per second, not road speed."),
    ]
    if following and headway is not None:
        facts.append(_fact("Time headway", _seconds(headway)))
    if severity:
        facts.append(
            _fact("Detector priority label", severity, "Provisional heuristic category for review order, not a danger rating.")
        )
    if risk_index is not None:
        facts.append(
            _fact(
                "Heuristic review-priority index",
                f"{risk_index:.1f}",
                "Unitless detector sorting value; not a probability or safety score.",
            )
        )
    return {
        "kind": PREDICTION,
        "id": _text(record.get("event_id")) or "—",
        "title": "Prediction warning (forecast, not an incident)",
        "participants": [first, second],
        "timestamp_seconds": warning,
        "evidence_status": status,
        "explanation": sentences,
        "facts": facts,
        "motion_rows": [],
        "missing_fields": missing_fields(PREDICTION, event),
    }


def explain_incident(incident: Any, reviews: Any = None, notifications: Any = None) -> dict:
    """Plain-language explanation of a suspected-incident evidence record."""

    record = incident if isinstance(incident, dict) else {}
    first, second = _participants(INCIDENT, record)
    impact = _record_time(INCIDENT, record)
    persistence = _integer(record.get("contact_persistence_frames"))
    measurements = record.get("measurements") if isinstance(record.get("measurements"), dict) else {}
    peak_overlap = _finite(measurements.get("peak_overlap_fraction_smaller_box"))
    peak_iou = _finite(measurements.get("peak_intersection_over_union"))
    converging = measurements.get("converging")
    reduction = _finite(measurements.get("distance_reduction_pixels"))
    closing = _finite(measurements.get("closing_speed_pixels_per_second"))
    samples = _integer(measurements.get("samples"))
    response = measurements.get("motion_response") if isinstance(measurements.get("motion_response"), dict) else {}
    raw_signals = record.get("detection_signals")
    signals = [str(item) for item in raw_signals if isinstance(item, str)] if isinstance(raw_signals, list) else []
    fired_motion = [key for key in MOTION_SIGNALS if response.get(key) is True or key in signals]
    warning = _finite(record.get("prediction_warning_timestamp_seconds"))
    lead = _finite(record.get("prediction_lead_seconds"))
    prediction_id = _text(record.get("associated_prediction_event_id"))

    # Each claim is gated on its own usable evidence. The incident detector
    # itself requires contact, prior convergence and a motion response.
    has_contact = (
        (persistence is not None and persistence > 0)
        or (peak_overlap is not None and peak_overlap > 0)
        or (peak_iou is not None and peak_iou > 0)
        or "persistent_bounding_box_contact" in signals
    )
    has_convergence = converging is True
    parts = {
        "box contact": has_contact,
        "prior convergence": has_convergence,
        "a motion response": bool(fired_motion),
    }
    if all(parts.values()):
        status = ESTABLISHED
    elif any(parts.values()):
        status = PARTIAL
    else:
        status = INSUFFICIENT
    subject = _pair_subject(first, second)
    anchor = "contact" if has_contact else "the flagged time"

    sentences = []
    if has_contact:
        when = f"Starting at {format_timestamp(impact)}" if impact is not None else "At an unknown time (no usable contact timestamp)"
        contact = f"{when}, the detector reported the boxes around {subject} touching"
        if persistence is not None and persistence > 0:
            contact += f" for {persistence} consecutive frames"
        if peak_overlap is not None and peak_overlap > 0:
            contact += f", overlapping up to {peak_overlap * 100:.0f}% of the smaller box"
        sentences.append(contact + ".")
    else:
        sentences.append(
            f"The record for {subject} contains no usable box-contact evidence (contact "
            "persistence, box overlap or a contact signal), so it cannot establish that "
            "their boxes touched."
        )
    if converging is True:
        detail = []
        if reduction is not None:
            detail.append(f"their distance shrank by {reduction:.1f} px")
        if closing is not None:
            detail.append(f"at about {closing:.1f} px/s")
        if samples is not None:
            detail.append(f"across {samples} paired samples")
        sentences.append(
            f"Before {anchor}, "
            + (" ".join(detail) if detail else "the detector reported the vehicles converging")
            + "."
        )
    elif converging is False:
        sentences.append(f"The supplied measurements do not show the vehicles converging before {anchor}.")
    else:
        sentences.append(f"Convergence before {anchor} could not be checked because the field is missing or unusable.")
    if fired_motion:
        sentences.append(
            f"After {anchor} the tracker recorded: "
            + "; ".join(SIGNAL_TEXT[key] for key in fired_motion)
            + "."
        )
    else:
        sentences.append("No motion-response signal (slowdown, stop, abrupt change or track loss) was supplied.")
    if prediction_id and lead is not None and lead > 0:
        sentences.append(
            f"Prediction warning {md(prediction_id)} for this pair was raised {lead:.2f} s before {anchor}."
        )
    elif "associated_prediction_event_id" in record and not prediction_id:
        sentences.append(
            "No earlier prediction warning was linked to this pair; the incident detector runs independently."
        )
    else:
        sentences.append("Whether a prediction warning preceded this is unknown from the supplied fields.")
    if status == ESTABLISHED:
        sentences.append(
            "The supplied evidence includes all three parts the incident detector requires: "
            "box contact, prior convergence and a motion response."
        )
    else:
        absent = [name for name, present in parts.items() if not present]
        sentences.append(
            "The available evidence cannot establish a suspected incident: it lacks "
            + ", ".join(absent)
            + ", which the incident detector requires."
        )
    review = review_state(record, reviews)
    dispatch = dispatch_state(record, notifications, review)
    sentences.append(review["statement"])
    sentences.append(
        "A suspected incident is a computer-vision candidate for human review, not proof of a collision."
    )

    facts = [
        _fact("Evidence completeness", _STATUS_FACT[status], "Box contact, prior convergence and a motion response."),
        _fact("Vehicles", f"{participant_label(first)} and {participant_label(second)}"),
        _fact("First suspected contact", _clock(impact), "First frame with qualifying box contact."),
        _fact("Contact persistence", "—" if persistence is None else f"{persistence} frames"),
        _fact(
            "Peak box overlap",
            "—" if peak_overlap is None else f"{peak_overlap * 100:.0f}% of smaller box",
            "Image-box geometry, not a damage measure.",
        ),
        _fact("Peak intersection-over-union", "—" if peak_iou is None else f"{peak_iou:.3f}"),
        _fact(
            "Converging before contact",
            "Yes" if converging is True else "No" if converging is False else "—",
        ),
        _fact("Distance reduction before contact", _pixels(reduction)),
        _fact("Closing speed before contact", _pixel_speed(closing), "Image pixels per second, not road speed."),
        _fact(
            "Motion-response signals",
            ", ".join(key.replace("_", " ") for key in fired_motion) or "None supplied",
        ),
        _fact(
            "Linked prediction warning",
            prediction_id or ("None" if "associated_prediction_event_id" in record else "Not supplied"),
        ),
        _fact("Prediction warning time", _clock(warning)),
        _fact("Warning lead before contact", _seconds(lead)),
        _fact("Detector signals", ", ".join(signal.replace("_", " ") for signal in signals) or "None supplied"),
        _fact("Operator review", review["status"]),
        _fact("Simulated dispatch", dispatch["status"], "Local inbox only; no external alert."),
    ]
    motion_rows = []
    vehicles = response.get("vehicles") if isinstance(response.get("vehicles"), list) else []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        flags = [key.replace("_", " ") for key in (
            "sudden_deceleration", "stopped_after_approach", "abrupt_motion_change", "track_lost_after_contact"
        ) if vehicle.get(key) is True]
        motion_rows.append(
            {
                "track_id": _integer(vehicle.get("track_id")),
                "speed_before": _pixel_speed(_finite(vehicle.get("preimpact_speed_pixels_per_second"))),
                "speed_after": _pixel_speed(_finite(vehicle.get("postimpact_speed_pixels_per_second"))),
                "direction_change": "—"
                if _finite(vehicle.get("direction_change_degrees")) is None
                else f"{_finite(vehicle.get('direction_change_degrees')):.0f}°",
                "signals": ", ".join(flags) or "none",
            }
        )
    return {
        "kind": INCIDENT,
        "id": _text(record.get("incident_id")) or "—",
        "title": "Suspected incident (review candidate)",
        "participants": [first, second],
        "timestamp_seconds": impact,
        "evidence_status": status,
        "explanation": sentences,
        "facts": facts,
        "motion_rows": motion_rows,
        "missing_fields": missing_fields(INCIDENT, incident),
        "review": review,
        "dispatch": dispatch,
    }


def explain_evidence(kind: str, record: Any, reviews: Any = None, notifications: Any = None) -> dict:
    if kind == INCIDENT:
        return explain_incident(record, reviews, notifications)
    return explain_prediction(record)


# ------------------------------------------------------- processing quality


def _check(name: str, status: str, detail: str) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _track_profile(tracks: Any, track_ids: list[int]) -> dict[int, dict]:
    rows: dict[int, list[tuple[int | None, float | None, float | None]]] = {track_id: [] for track_id in track_ids}
    if isinstance(tracks, list):
        for row in tracks:
            if not isinstance(row, dict):
                continue
            track_id = _integer(row.get("track_id"))
            if track_id in rows:
                rows[track_id].append(
                    (_integer(row.get("frame_index")), _finite(row.get("timestamp_seconds")), _finite(row.get("confidence")))
                )
    profile = {}
    for track_id, samples in rows.items():
        frames = sorted(frame for frame, _time, _conf in samples if frame is not None)
        times = [time for _frame, time, _conf in samples if time is not None]
        confidences = [conf for _frame, _time, conf in samples if conf is not None]
        gaps = [later - earlier for earlier, later in zip(frames, frames[1:])]
        profile[track_id] = {
            "rows": len(samples),
            "span_seconds": (max(times) - min(times)) if times else None,
            "largest_frame_gap": max(gaps) if gaps else None,
            "confidences": confidences,
        }
    return profile


def processing_quality(
    *,
    kind: str,
    record: Any,
    metadata: Any,
    tracks: Any,
    source: dict,
) -> list[dict]:
    """Readable checklist of processing limits. Statuses: ok, caution, info."""

    record = record if isinstance(record, dict) else {}
    meta = metadata_dict(metadata)
    checks = []

    if source.get("is_synthetic"):
        checks.append(_check("Source provenance", "caution", "Synthetic source: generated footage with scripted tracks. It illustrates the workflow only."))
    elif source.get("source_kind") in SOURCE_KIND_LABELS:
        checks.append(_check("Source provenance", "info", source.get("statement", "")))
    else:
        checks.append(_check("Source provenance", "caution", "Source kind was not supplied; provenance is unknown."))

    duration = _finite(meta.get("duration_seconds"))
    if duration is None or duration <= 0:
        checks.append(_check("Clip length", "caution", "Clip duration is unknown."))
    elif duration < SHORT_CLIP_SECONDS:
        checks.append(_check("Clip length", "caution", f"Short clip ({duration:.1f} s). Too little footage to describe typical conditions at this location."))
    else:
        checks.append(_check("Clip length", "ok", f"{duration:.1f} s analysed. Still one sample, not a long-term count."))

    fps = _finite(meta.get("fps"))
    if fps is None or fps <= 0:
        checks.append(_check("Frame rate", "caution", "Frame rate is unknown, so timing values cannot be cross-checked."))
    elif fps < LOW_FRAME_RATE_FPS:
        checks.append(_check("Frame rate", "caution", f"Low frame rate ({fps:.1f} fps) coarsens timing and motion estimates."))
    else:
        checks.append(_check("Frame rate", "ok", f"{fps:.1f} fps."))

    track_ids: list[int] = []
    for participant in _participants(kind, record):
        for track_id in participant["track_ids"]:
            if track_id not in track_ids:
                track_ids.append(track_id)
    if not isinstance(tracks, list) or not tracks:
        checks.append(_check("Track coverage", "caution", "No track rows were supplied, so track coverage cannot be checked."))
        profile = {}
    elif not track_ids:
        checks.append(_check("Track coverage", "caution", "Participant track IDs are missing, so track coverage cannot be checked."))
        profile = {}
    else:
        profile = _track_profile(tracks, track_ids)
        details, sparse = [], False
        for track_id in track_ids:
            item = profile[track_id]
            if item["rows"] == 0:
                sparse = True
                details.append(f"track #{track_id}: no rows supplied")
                continue
            gap = item["largest_frame_gap"]
            if item["rows"] < SPARSE_TRACK_ROWS or (gap is not None and gap > LARGE_FRAME_GAP):
                sparse = True
            span = "" if item["span_seconds"] is None else f" over {item['span_seconds']:.1f} s"
            gap_text = "" if gap is None else f", largest gap {gap} frame{'s' if gap != 1 else ''}"
            details.append(f"track #{track_id}: {item['rows']} rows{span}{gap_text}")
        prefix = "Sparse or broken tracks; motion estimates are less reliable. " if sparse else ""
        checks.append(_check("Track coverage", "caution" if sparse else "ok", prefix + "; ".join(details) + "."))

    missing = missing_fields(kind, record)
    if missing:
        checks.append(_check("Detector fields", "caution", "Missing or unusable: " + ", ".join(missing) + "."))
    else:
        checks.append(_check("Detector fields", "ok", "All expected detector fields are present."))

    checks.append(
        _check(
            "Field calibration",
            "caution",
            "No field calibration. Distances and speeds are image pixels and pixels per second; "
            "they are not metres or road speeds and change with perspective.",
        )
    )

    if kind == PREDICTION and record.get("zone_is_user_defined") is False:
        checks.append(_check("Analysis area", "info", "The whole frame was analysed; no custom analysis zone was set."))

    confidences = [value for item in profile.values() for value in item["confidences"]]
    if confidences:
        mean = sum(confidences) / len(confidences)
        if source.get("is_synthetic"):
            detail = f"Scripted tracks report confidence {mean:.2f}; this is not a detector measurement."
        else:
            detail = f"Mean model confidence for these tracks is {mean:.2f}. This is the model's own score, not an accuracy rate."
        checks.append(_check("Detector confidence", "info", detail))
    return checks


# ------------------------------------------------------------------- brief


def brief_filename(kind: str, record: Any, is_synthetic: bool) -> str:
    record = record if isinstance(record, dict) else {}
    raw = _text(record.get("event_id" if kind == PREDICTION else "incident_id")) or "unidentified"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")[:48] or "unidentified"
    prefix = "SYNTHETIC_" if is_synthetic else ""
    return f"{prefix}nearmiss_evidence_{kind}_{safe}.md"


_STATUS_WORD = {"ok": "OK", "caution": "Caution", "info": "Note"}


def build_evidence_brief(
    *,
    source_name: Any,
    video_id: Any,
    source_kind: Any,
    metadata: Any,
    tracks: Any,
    kind: str,
    record: Any,
    reviews: Any = None,
    notifications: Any = None,
    generated_at: str | None = None,
) -> str:
    """Markdown incident/prediction brief built only from supplied evidence."""

    kind = INCIDENT if kind == INCIDENT else PREDICTION
    source = describe_source(source_kind, video_id, tracks, [record] if isinstance(record, dict) else None)
    explanation = explain_evidence(kind, record, reviews, notifications)
    checks = processing_quality(kind=kind, record=record, metadata=metadata, tracks=tracks, source=source)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    synthetic = source["is_synthetic"]
    tag = "[SYNTHETIC] " if synthetic else ""

    lines = [f"# {tag}NearMiss evidence brief: {md(explanation['title'])}", ""]
    if synthetic:
        lines += [f"> **{SYNTHETIC_BANNER}**", ""]
    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| Source | {md(_text(source_name) or 'Not supplied')} |",
        f"| Source kind | {md(source['label'])} |",
        f"| Video ID | {md(_text(video_id) or 'Not supplied')} |",
        f"| Evidence type | {md(explanation['title'])} |",
        f"| Evidence ID | {md(explanation['id'])} |",
        f"| Brief generated | {md(generated_at)} |",
        "",
    ]
    if source.get("note"):
        lines += [f"*{md(source['note'])}*", ""]

    lines += ["## What NearMiss observed", "", " ".join(explanation["explanation"]), ""]

    lines += ["## Evidence facts", "", "| Measure | Value | Notes |", "|---|---|---|"]
    for fact in explanation["facts"]:
        lines.append(f"| {md(fact['label'])} | {md(fact['value'])} | {md(fact['note'])} |")
    lines.append("")
    if explanation["missing_fields"]:
        lines += ["Missing or unusable fields: " + md(", ".join(explanation["missing_fields"])) + ".", ""]

    if explanation["motion_rows"]:
        lines += [
            "## Motion response by vehicle",
            "",
            "| Track | Speed before | Speed after | Direction change | Signals |",
            "|---|---|---|---|---|",
        ]
        for row in explanation["motion_rows"]:
            track = "—" if row["track_id"] is None else f"#{row['track_id']}"
            lines.append(
                f"| {track} | {md(row['speed_before'])} | {md(row['speed_after'])} | "
                f"{md(row['direction_change'])} | {md(row['signals'])} |"
            )
        lines.append("")

    if kind == INCIDENT:
        review, dispatch = explanation["review"], explanation["dispatch"]
        lines += ["## Human review", "", review["statement"], ""]
        if review["inconsistency"]:
            lines += [f"> Note: {review['inconsistency']}", ""]
        lines += ["## Simulated dispatch", "", dispatch["statement"], ""]
        if dispatch["inconsistency"]:
            lines += [f"> Note: {dispatch['inconsistency']}", ""]
    else:
        lines += [
            "## Human review and dispatch",
            "",
            "Prediction warnings are not reviewed as incidents and never create a dispatch notice. "
            "No external alert was sent.",
            "",
        ]

    lines += ["## Processing-quality checklist", ""]
    for check in checks:
        lines.append(f"- **{_STATUS_WORD.get(check['status'], 'Note')}: {md(check['check'])}**: {md(check['detail'])}")
    lines.append("")

    lines += ["## What this brief does not claim", ""]
    lines += [f"- {item}" for item in NOT_CLAIMED]
    if synthetic:
        lines.append("- The source is synthetic. None of this describes real traffic, a real place or a real event.")
    lines += [
        "",
        "---",
        "",
        "Generated by NearMiss Explain & Share from detector output and local review records."
        + (" SYNTHETIC DEMONSTRATION." if synthetic else ""),
        "",
    ]
    return "\n".join(lines)
