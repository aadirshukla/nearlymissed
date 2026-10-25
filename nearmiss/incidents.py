"""Heuristic suspected-collision detection from tracked vehicle evidence.

This module is intentionally separate from trajectory prediction. It analyzes
observable post-approach evidence and can report an incident even when no prior
prediction event exists. All measurements are uncalibrated image coordinates;
the output is a review candidate, never proof that a collision occurred.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from itertools import combinations
from math import acos, degrees, isfinite
from typing import Any

import numpy as np


DEFAULT_COLLISION_CONFIG = {
    "minimum_overlap_fraction": 0.12,
    "minimum_iou": 0.05,
    "minimum_strong_overlap_fraction": 0.35,
    "minimum_strong_iou": 0.14,
    "contact_persistence_frames": 2,
    "maximum_contact_frame_gap": 2,
    "pre_contact_window_seconds": 0.80,
    "post_contact_window_seconds": 0.60,
    "minimum_convergence_samples": 3,
    "minimum_closing_speed_pixels_per_second": 12.0,
    "minimum_distance_reduction_pixels": 8.0,
    "minimum_preimpact_speed_pixels_per_second": 15.0,
    "deceleration_speed_ratio": 0.55,
    "minimum_velocity_change_pixels_per_second": 20.0,
    "abrupt_direction_change_degrees": 35.0,
    "stationary_speed_pixels_per_second": 4.0,
    "track_loss_grace_seconds": 0.12,
    "minimum_post_contact_absence_seconds": 0.30,
    "minimum_evidence_signals": 3,
    "incident_merge_seconds": 1.25,
    "prediction_association_seconds": 2.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _setting(config: dict, key: str) -> float:
    return _number(config.get(key), float(DEFAULT_COLLISION_CONFIG[key]))


def _position(record: dict) -> np.ndarray | None:
    bbox = record.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x1, _y1, x2, y2 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            return None
        point = np.asarray([(x1 + x2) / 2.0, y2], dtype=float)
        return point if np.all(np.isfinite(point)) else None
    return None


def _normalized_vehicle_records(tracks: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for raw in tracks:
        if not isinstance(raw, dict) or raw.get("object_type") != "vehicle":
            continue
        point = _position(raw)
        bbox = raw.get("bbox")
        try:
            track_id = int(raw["track_id"])
            frame_index = int(raw["frame_index"])
            timestamp = float(raw["timestamp_seconds"])
            normalized_bbox = [float(value) for value in bbox]
        except (KeyError, TypeError, ValueError):
            continue
        if point is None or not isfinite(timestamp) or len(normalized_bbox) != 4:
            continue
        grouped[track_id].append(
            {
                **raw,
                "track_id": track_id,
                "frame_index": frame_index,
                "timestamp_seconds": timestamp,
                "bbox": normalized_bbox,
                "bottom_center": point,
            }
        )
    for records in grouped.values():
        records.sort(key=lambda row: (row["timestamp_seconds"], row["frame_index"]))
    return grouped


def _bbox_evidence(first: list[float], second: list[float]) -> dict[str, float]:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return {
        "intersection_area_pixels": intersection,
        "overlap_fraction_smaller_box": intersection / max(min(first_area, second_area), 1e-9),
        "intersection_over_union": intersection / max(union, 1e-9),
        "intersection_center_x": (left + right) / 2.0 if intersection > 0 else 0.0,
        "intersection_center_y": (top + bottom) / 2.0 if intersection > 0 else 0.0,
    }


def _velocity(records: list[dict], start: float, end: float) -> np.ndarray | None:
    window = [row for row in records if start <= row["timestamp_seconds"] <= end]
    if len(window) < 3:
        return None
    times = np.asarray([row["timestamp_seconds"] for row in window], dtype=float)
    points = np.asarray([row["bottom_center"] for row in window], dtype=float)
    times = times - times.mean()
    denominator = float(np.dot(times, times))
    if denominator <= 1e-9:
        return None
    center = points.mean(axis=0)
    velocity = np.sum(times[:, None] * (points - center), axis=0) / denominator
    return velocity if np.all(np.isfinite(velocity)) else None


def _direction_change(first: np.ndarray | None, second: np.ndarray | None) -> float | None:
    if first is None or second is None:
        return None
    first_speed = float(np.linalg.norm(first))
    second_speed = float(np.linalg.norm(second))
    if first_speed <= 1e-9 or second_speed <= 1e-9:
        return None
    cosine = float(np.dot(first, second) / (first_speed * second_speed))
    return degrees(acos(float(np.clip(cosine, -1.0, 1.0))))


def _convergence(
    first_by_frame: dict[int, dict],
    second_by_frame: dict[int, dict],
    impact_time: float,
    config: dict,
) -> dict[str, Any]:
    start = impact_time - _setting(config, "pre_contact_window_seconds")
    frames = sorted(set(first_by_frame) & set(second_by_frame))
    samples: list[tuple[float, float]] = []
    for frame in frames:
        first, second = first_by_frame[frame], second_by_frame[frame]
        timestamp = max(first["timestamp_seconds"], second["timestamp_seconds"])
        if start <= timestamp <= impact_time:
            distance = float(np.linalg.norm(first["bottom_center"] - second["bottom_center"]))
            samples.append((timestamp, distance))
    minimum_samples = max(2, int(_setting(config, "minimum_convergence_samples")))
    if len(samples) < minimum_samples:
        return {
            "converging": False,
            "samples": len(samples),
            "closing_speed_pixels_per_second": None,
            "distance_reduction_pixels": None,
        }
    times = np.asarray([item[0] for item in samples], dtype=float)
    distances = np.asarray([item[1] for item in samples], dtype=float)
    centered_times = times - times.mean()
    denominator = float(np.dot(centered_times, centered_times))
    slope = float(np.dot(centered_times, distances - distances.mean()) / max(denominator, 1e-9))
    closing_speed = -slope
    distance_reduction = float(distances[0] - distances[-1])
    converging = (
        closing_speed >= _setting(config, "minimum_closing_speed_pixels_per_second")
        and distance_reduction >= _setting(config, "minimum_distance_reduction_pixels")
    )
    return {
        "converging": converging,
        "samples": len(samples),
        "closing_speed_pixels_per_second": round(closing_speed, 2),
        "distance_reduction_pixels": round(distance_reduction, 2),
    }


def _prediction_for_pair(
    first_id: int,
    second_id: int,
    impact_time: float,
    predictions: list[dict],
    config: dict,
) -> dict | None:
    maximum_gap = _setting(config, "prediction_association_seconds")
    matches: list[tuple[float, dict]] = []
    for event in predictions:
        first_ids = set(
            int(value)
            for value in event.get("participant_a_track_ids", [event.get("participant_a_track_id")])
            if value is not None
        )
        second_ids = set(
            int(value)
            for value in event.get("participant_b_track_ids", [event.get("participant_b_track_id")])
            if value is not None
        )
        pair_matches = (first_id in first_ids and second_id in second_ids) or (
            first_id in second_ids and second_id in first_ids
        )
        if not pair_matches:
            continue
        warning_time = _number(
            event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds")),
            float("nan"),
        )
        if not isfinite(warning_time):
            continue
        # Only a warning raised strictly before first contact is a prediction.
        # A warning at or after contact would have a zero/negative lead and
        # must not be presented as "predicted earlier".
        gap = impact_time - warning_time
        if 0.0 < gap <= maximum_gap:
            matches.append((gap, event))
    return min(matches, key=lambda item: item[0])[1] if matches else None


def _incident_identifier(source_video_id: str, pair: tuple[int, int], timestamp: float) -> str:
    payload = f"{source_video_id}:{pair[0]}:{pair[1]}:{timestamp:.3f}".encode("utf-8")
    return f"incident-{sha256(payload).hexdigest()[:12]}"


def _motion_response(
    first_records: list[dict],
    second_records: list[dict],
    impact_time: float,
    peak_time: float,
    video_end: float,
    config: dict,
) -> dict[str, Any]:
    pre_window = _setting(config, "pre_contact_window_seconds")
    post_window = _setting(config, "post_contact_window_seconds")
    minimum_pre_speed = _setting(config, "minimum_preimpact_speed_pixels_per_second")
    ratio_threshold = _setting(config, "deceleration_speed_ratio")
    velocity_change_threshold = _setting(config, "minimum_velocity_change_pixels_per_second")
    direction_threshold = _setting(config, "abrupt_direction_change_degrees")
    stationary_threshold = _setting(config, "stationary_speed_pixels_per_second")

    details: list[dict[str, Any]] = []
    any_abrupt = any_deceleration = any_stopped = any_loss = False
    for records in (first_records, second_records):
        track_id = int(records[0]["track_id"])
        before = _velocity(records, impact_time - pre_window, impact_time)
        after = _velocity(records, impact_time + 0.05, impact_time + post_window)
        before_speed = float(np.linalg.norm(before)) if before is not None else None
        after_speed = float(np.linalg.norm(after)) if after is not None else None
        change = (
            float(np.linalg.norm(after - before))
            if before is not None and after is not None
            else None
        )
        angle = _direction_change(before, after)
        decelerated = bool(
            before_speed is not None
            and after_speed is not None
            and before_speed >= minimum_pre_speed
            and after_speed <= before_speed * ratio_threshold
            and before_speed - after_speed >= 8.0
        )
        stopped = bool(
            before_speed is not None
            and after_speed is not None
            and before_speed >= minimum_pre_speed
            and after_speed <= stationary_threshold
        )
        abrupt = bool(
            change is not None
            and change >= velocity_change_threshold
            and (angle is None or angle >= direction_threshold or decelerated)
        )
        last_time = float(records[-1]["timestamp_seconds"])
        lost_after_contact = bool(
            last_time <= peak_time + _setting(config, "track_loss_grace_seconds")
            and video_end - last_time
            >= _setting(config, "minimum_post_contact_absence_seconds")
        )
        any_abrupt |= abrupt
        any_deceleration |= decelerated
        any_stopped |= stopped
        any_loss |= lost_after_contact
        details.append(
            {
                "track_id": track_id,
                "preimpact_velocity_pixels_per_second": None
                if before is None
                else [round(float(value), 2) for value in before],
                "postimpact_velocity_pixels_per_second": None
                if after is None
                else [round(float(value), 2) for value in after],
                "preimpact_speed_pixels_per_second": None
                if before_speed is None
                else round(before_speed, 2),
                "postimpact_speed_pixels_per_second": None
                if after_speed is None
                else round(after_speed, 2),
                "velocity_change_pixels_per_second": None if change is None else round(change, 2),
                "direction_change_degrees": None if angle is None else round(angle, 2),
                "sudden_deceleration": decelerated,
                "stopped_after_approach": stopped,
                "abrupt_motion_change": abrupt,
                "track_lost_after_contact": lost_after_contact,
            }
        )
    return {
        "abrupt_motion_change": any_abrupt,
        "sudden_deceleration": any_deceleration,
        "stopped_after_approach": any_stopped,
        "post_contact_track_loss": any_loss,
        "vehicles": details,
    }


def _contact_episodes(
    first_by_frame: dict[int, dict], second_by_frame: dict[int, dict], config: dict
) -> list[list[dict]]:
    contact_rows: list[dict] = []
    for frame in sorted(set(first_by_frame) & set(second_by_frame)):
        first, second = first_by_frame[frame], second_by_frame[frame]
        evidence = _bbox_evidence(first["bbox"], second["bbox"])
        contact = (
            evidence["overlap_fraction_smaller_box"]
            >= _setting(config, "minimum_overlap_fraction")
            or evidence["intersection_over_union"] >= _setting(config, "minimum_iou")
        )
        if contact:
            contact_rows.append(
                {
                    "frame_index": frame,
                    "timestamp_seconds": max(
                        first["timestamp_seconds"], second["timestamp_seconds"]
                    ),
                    "first": first,
                    "second": second,
                    **evidence,
                }
            )
    maximum_gap = max(1, int(_setting(config, "maximum_contact_frame_gap")))
    episodes: list[list[dict]] = []
    for row in contact_rows:
        if not episodes or row["frame_index"] - episodes[-1][-1]["frame_index"] > maximum_gap:
            episodes.append([row])
        else:
            episodes[-1].append(row)
    return episodes


def detect_suspected_collisions(
    tracks: list[dict],
    prediction_events: list[dict] | None,
    source_video_id: str,
    config: dict | None = None,
) -> list[dict]:
    """Return deduplicated suspected-collision evidence events.

    A qualifying event requires persistent box contact, prior convergence, and
    at least one motion-response signal (abrupt motion, deceleration/stopping,
    or post-contact track loss). Prediction events are associated afterward and
    never control whether the collision evidence detector fires.
    """

    config = {**DEFAULT_COLLISION_CONFIG, **(config or {})}
    predictions = prediction_events if isinstance(prediction_events, list) else []
    grouped = _normalized_vehicle_records(tracks if isinstance(tracks, list) else [])
    video_end = max(
        (row["timestamp_seconds"] for records in grouped.values() for row in records),
        default=0.0,
    )
    candidates: list[dict] = []
    minimum_frames = max(2, int(_setting(config, "contact_persistence_frames")))
    minimum_signals = max(3, int(_setting(config, "minimum_evidence_signals")))

    for first_id, second_id in combinations(sorted(grouped), 2):
        first_records, second_records = grouped[first_id], grouped[second_id]
        first_by_frame = {row["frame_index"]: row for row in first_records}
        second_by_frame = {row["frame_index"]: row for row in second_records}
        for episode in _contact_episodes(first_by_frame, second_by_frame, config):
            if len(episode) < minimum_frames:
                continue
            impact = episode[0]
            peak = max(
                episode,
                key=lambda row: (
                    row["overlap_fraction_smaller_box"], row["intersection_over_union"]
                ),
            )
            convergence = _convergence(
                first_by_frame,
                second_by_frame,
                float(impact["timestamp_seconds"]),
                config,
            )
            response = _motion_response(
                first_records,
                second_records,
                float(impact["timestamp_seconds"]),
                float(peak["timestamp_seconds"]),
                video_end,
                config,
            )
            signals = ["persistent_bounding_box_contact"]
            strong_overlap = (
                peak["overlap_fraction_smaller_box"]
                >= _setting(config, "minimum_strong_overlap_fraction")
                or peak["intersection_over_union"]
                >= _setting(config, "minimum_strong_iou")
            )
            if strong_overlap:
                signals.append("significant_bounding_box_overlap")
            if convergence["converging"]:
                signals.append("previously_converging_trajectories")
            for key in (
                "abrupt_motion_change",
                "sudden_deceleration",
                "stopped_after_approach",
                "post_contact_track_loss",
            ):
                if response[key]:
                    signals.append(key)
            has_motion_response = any(
                response[key]
                for key in (
                    "abrupt_motion_change",
                    "sudden_deceleration",
                    "stopped_after_approach",
                    "post_contact_track_loss",
                )
            )
            if (
                not (strong_overlap or response["post_contact_track_loss"])
                or
                not convergence["converging"]
                or not has_motion_response
                or len(signals) < minimum_signals
            ):
                continue

            pair = (first_id, second_id)
            impact_time = float(impact["timestamp_seconds"])
            prediction = _prediction_for_pair(
                first_id, second_id, impact_time, predictions, config
            )
            warning_time = (
                _number(
                    prediction.get(
                        "first_alert_timestamp_seconds", prediction.get("timestamp_seconds")
                    ),
                    impact_time,
                )
                if prediction
                else None
            )
            # The timestamp, frame and boxes describe first contact, so the
            # drawn contact marker must come from that same frame. The peak
            # overlap location is kept separately as supporting evidence.
            contact_point = [
                round(float(impact["intersection_center_x"]), 2),
                round(float(impact["intersection_center_y"]), 2),
            ]
            incident_id = _incident_identifier(source_video_id, pair, impact_time)
            candidates.append(
                {
                    "incident_id": incident_id,
                    "event_type": "suspected_collision",
                    "timestamp_seconds": round(impact_time, 3),
                    "first_suspected_impact_timestamp_seconds": round(impact_time, 3),
                    "frame_index": int(impact["frame_index"]),
                    "end_frame_index": int(episode[-1]["frame_index"]),
                    "vehicle_a_track_id": first_id,
                    "vehicle_b_track_id": second_id,
                    "vehicle_a_class": str(impact["first"].get("class_name", "vehicle")),
                    "vehicle_b_class": str(impact["second"].get("class_name", "vehicle")),
                    "vehicle_a_bbox": [round(value, 2) for value in impact["first"]["bbox"]],
                    "vehicle_b_bbox": [round(value, 2) for value in impact["second"]["bbox"]],
                    "contact_point": contact_point,
                    "detection_signals": signals,
                    "evidence_signal_count": len(signals),
                    "contact_persistence_frames": len(episode),
                    "associated_prediction_event_id": None
                    if prediction is None
                    else prediction.get("event_id"),
                    "prediction_warning_timestamp_seconds": warning_time,
                    "prediction_lead_seconds": None
                    if warning_time is None
                    else round(impact_time - warning_time, 3),
                    "source_video_id": str(source_video_id),
                    "review_status": "Uncertain",
                    "measurements": {
                        "peak_overlap_fraction_smaller_box": round(
                            float(peak["overlap_fraction_smaller_box"]), 3
                        ),
                        "peak_intersection_over_union": round(
                            float(peak["intersection_over_union"]), 3
                        ),
                        "intersection_area_pixels": round(
                            float(peak["intersection_area_pixels"]), 2
                        ),
                        "first_contact_overlap_fraction_smaller_box": round(
                            float(impact["overlap_fraction_smaller_box"]), 3
                        ),
                        "peak_overlap_frame_index": int(peak["frame_index"]),
                        "peak_overlap_timestamp_seconds": round(
                            float(peak["timestamp_seconds"]), 3
                        ),
                        "peak_contact_point": [
                            round(float(peak["intersection_center_x"]), 2),
                            round(float(peak["intersection_center_y"]), 2),
                        ],
                        **convergence,
                        "motion_response": response,
                    },
                    "description": (
                        "Suspected collision for operator review: persistent vehicle-box "
                        "contact followed prior convergence and coincided with "
                        + ", ".join(signal.replace("_", " ") for signal in signals[2:])
                        + "."
                    ),
                }
            )

    # Merge repeated evidence episodes for the same raw pair while preserving
    # the first suspected-impact time and the strongest evidence record.
    candidates.sort(
        key=lambda item: (
            item["vehicle_a_track_id"],
            item["vehicle_b_track_id"],
            item["timestamp_seconds"],
        )
    )
    merged: list[dict] = []
    cooldown = _setting(config, "incident_merge_seconds")
    for candidate in candidates:
        previous = merged[-1] if merged else None
        same_pair = previous is not None and (
            previous["vehicle_a_track_id"], previous["vehicle_b_track_id"]
        ) == (candidate["vehicle_a_track_id"], candidate["vehicle_b_track_id"])
        if not same_pair or candidate["timestamp_seconds"] - previous["timestamp_seconds"] > cooldown:
            merged.append(candidate)
            continue
        if candidate["evidence_signal_count"] > previous["evidence_signal_count"]:
            strongest = dict(candidate)
            strongest["incident_id"] = previous["incident_id"]
            strongest["timestamp_seconds"] = previous["timestamp_seconds"]
            strongest["first_suspected_impact_timestamp_seconds"] = previous[
                "first_suspected_impact_timestamp_seconds"
            ]
            strongest["frame_index"] = previous["frame_index"]
            # Keep frame-specific evidence aligned with the preserved first
            # suspected-impact frame and its prediction lead.
            for key in (
                "vehicle_a_bbox",
                "vehicle_b_bbox",
                "contact_point",
                "associated_prediction_event_id",
                "prediction_warning_timestamp_seconds",
                "prediction_lead_seconds",
            ):
                strongest[key] = previous[key]
            merged[-1] = strongest
        merged[-1]["end_frame_index"] = max(
            merged[-1]["end_frame_index"], candidate["end_frame_index"]
        )
    return sorted(merged, key=lambda item: item["timestamp_seconds"])
