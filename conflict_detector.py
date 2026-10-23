"""Explainable image-coordinate traffic conflict detection.

This module works only with tracking records produced by NearMiss. Distances
and velocities are measured in image pixels; flags are provisional screening
signals, not collision probabilities or real-world speed measurements.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import isfinite
from itertools import combinations
from typing import Any

import numpy as np


EPSILON = 1e-9
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


@dataclass
class Observation:
    """One normalized observation using the bbox ground-contact point."""

    track_id: int
    object_type: str
    class_name: str
    frame_index: int
    timestamp: float
    position: np.ndarray
    bbox: list[float]


@dataclass
class LogicalTrack:
    """A physical track, possibly stitched across a short tracker ID switch."""

    logical_id: int
    object_type: str
    observations: list[Observation] = field(default_factory=list)
    source_track_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class MotionState:
    logical_id: int
    object_type: str
    class_name: str
    current_track_id: int
    source_track_ids: tuple[int, ...]
    frame_index: int
    timestamp: float
    position: np.ndarray
    velocity: np.ndarray
    bbox: list[float]

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.velocity))


def _setting(config: dict, name: str, default: float) -> float:
    try:
        value = float(config.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if isfinite(value) else default


def _bottom_center(record: dict) -> np.ndarray | None:
    """Use the bbox bottom center as a simple ground-plane approximation."""

    bbox = record.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x1, _y1, x2, y2 = (float(value) for value in bbox)
            point = np.asarray([(x1 + x2) / 2.0, y2], dtype=float)
            if np.all(np.isfinite(point)):
                return point
        except (TypeError, ValueError):
            pass
    center = record.get("center")
    if isinstance(center, (list, tuple)) and len(center) == 2:
        try:
            point = np.asarray([float(center[0]), float(center[1])], dtype=float)
            if np.all(np.isfinite(point)):
                return point
        except (TypeError, ValueError):
            pass
    return None


def _normalize_tracks(tracks: list[dict]) -> list[Observation]:
    observations: list[Observation] = []
    for record in tracks:
        if not isinstance(record, dict):
            continue
        object_type = record.get("object_type")
        if object_type not in {"vehicle", "pedestrian"}:
            continue
        position = _bottom_center(record)
        if position is None:
            continue
        try:
            timestamp = float(record["timestamp_seconds"])
            frame_index = int(record["frame_index"])
            track_id = int(record["track_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isfinite(timestamp):
            continue
        bbox = record.get("bbox", [position[0], position[1], position[0], position[1]])
        try:
            normalized_bbox = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue
        observations.append(
            Observation(
                track_id=track_id,
                object_type=object_type,
                class_name=str(record.get("class_name", object_type)),
                frame_index=frame_index,
                timestamp=timestamp,
                position=position,
                bbox=normalized_bbox,
            )
        )
    return sorted(observations, key=lambda item: (item.timestamp, item.frame_index, item.track_id))


def _estimate_velocity(observations: list[Observation], smoothing_frames: int) -> np.ndarray:
    """Fit x(t) and y(t) slopes over recent points to smooth detector jitter."""

    recent = observations[-max(2, smoothing_frames) :]
    if len(recent) < 2:
        return np.zeros(2, dtype=float)
    times = np.asarray([item.timestamp for item in recent], dtype=float)
    positions = np.asarray([item.position for item in recent], dtype=float)
    centered_times = times - float(np.mean(times))
    denominator = float(np.dot(centered_times, centered_times))
    if denominator <= EPSILON:
        return np.zeros(2, dtype=float)
    return np.sum(centered_times[:, None] * positions, axis=0) / denominator


def _raw_tracklets(observations: list[Observation]) -> list[LogicalTrack]:
    grouped: dict[tuple[str, int], list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.object_type, observation.track_id)].append(observation)
    tracklets: list[LogicalTrack] = []
    sorted_groups = sorted(grouped.items(), key=lambda entry: entry[1][0].timestamp)
    for logical_id, ((_object_type, track_id), items) in enumerate(sorted_groups, start=1):
        tracklets.append(
            LogicalTrack(
                logical_id=logical_id,
                object_type=items[0].object_type,
                observations=sorted(items, key=lambda item: item.timestamp),
                source_track_ids={track_id},
            )
        )
    return tracklets


def _stitch_tracklets(tracklets: list[LogicalTrack], config: dict) -> list[LogicalTrack]:
    """Conservatively reconnect brief, spatially consistent ID switches."""

    max_gap = max(0.0, _setting(config, "id_stitch_gap_seconds", 0.50))
    max_distance = max(0.0, _setting(config, "id_stitch_distance_pixels", 60.0))
    smoothing_frames = max(2, int(_setting(config, "velocity_smoothing_frames", 5)))
    logical_tracks: list[LogicalTrack] = []
    for fragment in sorted(tracklets, key=lambda item: item.observations[0].timestamp):
        first = fragment.observations[0]
        best_track: LogicalTrack | None = None
        best_distance = float("inf")
        for candidate in logical_tracks:
            if candidate.object_type != fragment.object_type:
                continue
            last = candidate.observations[-1]
            gap = first.timestamp - last.timestamp
            if gap <= EPSILON or gap > max_gap:
                continue
            velocity = _estimate_velocity(candidate.observations, smoothing_frames)
            projected_endpoint = last.position + velocity * gap
            distance = float(np.linalg.norm(first.position - projected_endpoint))
            if distance <= max_distance and distance < best_distance:
                best_distance = distance
                best_track = candidate
        if best_track is None:
            fragment.logical_id = len(logical_tracks) + 1
            logical_tracks.append(fragment)
        else:
            best_track.observations.extend(fragment.observations)
            best_track.observations.sort(key=lambda item: item.timestamp)
            best_track.source_track_ids.update(fragment.source_track_ids)
    return logical_tracks


def _point_in_polygon(point: np.ndarray, polygon: list[list[float]]) -> bool:
    """Ray-casting polygon test that treats boundary points as inside."""

    if len(polygon) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    previous_x, previous_y = (float(value) for value in polygon[-1])
    for vertex in polygon:
        current_x, current_y = (float(value) for value in vertex)
        segment = np.asarray([current_x - previous_x, current_y - previous_y])
        to_point = np.asarray([x - previous_x, y - previous_y])
        cross = abs(float(np.cross(segment, to_point)))
        if cross <= 1e-5:
            dot = float(np.dot(to_point, segment))
            squared_length = float(np.dot(segment, segment))
            if -EPSILON <= dot <= squared_length + EPSILON:
                return True
        intersects = (current_y > y) != (previous_y > y)
        if intersects:
            crossing_x = (previous_x - current_x) * (y - current_y) / (
                previous_y - current_y
            ) + current_x
            if x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _cross_2d(first: np.ndarray, second: np.ndarray) -> float:
    return float(first[0] * second[1] - first[1] * second[0])


def _point_segment_projection(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> tuple[np.ndarray, float]:
    segment = end - start
    denominator = float(np.dot(segment, segment))
    if denominator <= EPSILON:
        return start.copy(), 0.0
    fraction = float(np.dot(point - start, segment) / denominator)
    fraction = min(1.0, max(0.0, fraction))
    return start + fraction * segment, fraction


def _closest_points_on_paths(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    """Return closest points and fractions along two finite 2D segments."""

    first_vector = first_end - first_start
    second_vector = second_end - second_start
    denominator = _cross_2d(first_vector, second_vector)
    if abs(denominator) > EPSILON:
        offset = second_start - first_start
        first_fraction = _cross_2d(offset, second_vector) / denominator
        second_fraction = _cross_2d(offset, first_vector) / denominator
        if 0.0 <= first_fraction <= 1.0 and 0.0 <= second_fraction <= 1.0:
            point = first_start + first_fraction * first_vector
            return point, point.copy(), first_fraction, second_fraction, 0.0

    candidates: list[tuple[np.ndarray, np.ndarray, float, float]] = []
    projected, fraction = _point_segment_projection(first_start, second_start, second_end)
    candidates.append((first_start, projected, 0.0, fraction))
    projected, fraction = _point_segment_projection(first_end, second_start, second_end)
    candidates.append((first_end, projected, 1.0, fraction))
    projected, fraction = _point_segment_projection(second_start, first_start, first_end)
    candidates.append((projected, second_start, fraction, 0.0))
    projected, fraction = _point_segment_projection(second_end, first_start, first_end)
    candidates.append((projected, second_end, fraction, 1.0))
    first_point, second_point, first_fraction, second_fraction = min(
        candidates, key=lambda item: float(np.linalg.norm(item[0] - item[1]))
    )
    distance = float(np.linalg.norm(first_point - second_point))
    return first_point, second_point, first_fraction, second_fraction, distance


def _motion_state(
    track: LogicalTrack,
    history: list[Observation],
    timestamp: float,
    config: dict,
) -> MotionState | None:
    min_age = max(2, int(_setting(config, "min_track_age_frames", 5)))
    if len(history) < min_age:
        return None
    latest = history[-1]
    observation_age = timestamp - latest.timestamp
    max_age = max(0.0, _setting(config, "max_observation_age_seconds", 0.25))
    if observation_age < -EPSILON or observation_age > max_age:
        return None
    smoothing_frames = max(2, int(_setting(config, "velocity_smoothing_frames", 5)))
    velocity = _estimate_velocity(history, smoothing_frames)
    position = latest.position + velocity * max(0.0, observation_age)
    return MotionState(
        logical_id=track.logical_id,
        object_type=track.object_type,
        class_name=latest.class_name,
        current_track_id=latest.track_id,
        source_track_ids=tuple(sorted(track.source_track_ids)),
        frame_index=latest.frame_index,
        timestamp=timestamp,
        position=position,
        velocity=velocity,
        bbox=latest.bbox,
    )


def _severity(arrival_gap: float, config: dict) -> str | None:
    high = max(0.0, _setting(config, "high_time_gap_seconds", 0.50))
    medium = max(high, _setting(config, "medium_time_gap_seconds", 1.00))
    low = max(medium, _setting(config, "low_time_gap_seconds", 1.75))
    if arrival_gap <= high:
        return "HIGH"
    if arrival_gap <= medium:
        return "MEDIUM"
    if arrival_gap <= low:
        return "LOW"
    return None


def _candidate_event(
    first: MotionState,
    second: MotionState,
    zone: list[list[float]],
    config: dict,
) -> dict[str, Any] | None:
    horizon = max(0.1, _setting(config, "prediction_horizon_seconds", 2.0))
    path_tolerance = max(
        0.1,
        _setting(
            config,
            "path_intersection_tolerance_pixels",
            _setting(config, "max_distance_pixels", 35.0),
        ),
    )
    min_closing = max(0.0, _setting(config, "min_closing_speed_pixels_per_second", 2.0))
    stationary_speed = max(0.0, _setting(config, "stationary_speed_pixels_per_second", 2.0))
    min_future_time = max(0.0, _setting(config, "minimum_time_to_conflict_seconds", 0.05))

    relative_position = second.position - first.position
    separation = float(np.linalg.norm(relative_position))
    relative_velocity = second.velocity - first.velocity
    if separation <= EPSILON:
        closing_speed = float(np.linalg.norm(relative_velocity))
    else:
        closing_speed = -float(np.dot(relative_position, relative_velocity)) / separation
    if closing_speed < min_closing:
        return None

    first_stationary = first.speed <= stationary_speed
    second_stationary = second.speed <= stationary_speed
    if first_stationary and second_stationary:
        return None
    # Clamp regression noise on stationary objects so their ETA is exactly zero.
    first_end = (
        first.position.copy()
        if first_stationary
        else first.position + first.velocity * horizon
    )
    second_end = (
        second.position.copy()
        if second_stationary
        else second.position + second.velocity * horizon
    )
    closest = _closest_points_on_paths(
        first.position, first_end, second.position, second_end
    )
    first_point, second_point, first_fraction, second_fraction, path_distance = closest
    if path_distance > path_tolerance:
        return None

    first_eta = first_fraction * horizon
    second_eta = second_fraction * horizon
    if not first_stationary and first_eta < min_future_time:
        return None
    if not second_stationary and second_eta < min_future_time:
        return None

    conflict_point = (first_point + second_point) / 2.0
    if not _point_in_polygon(conflict_point, zone):
        return None

    arrival_gap = abs(first_eta - second_eta)
    severity = _severity(arrival_gap, config)
    if severity is None:
        return None

    low_gap = max(
        _setting(config, "low_time_gap_seconds", 1.75),
        _setting(config, "medium_time_gap_seconds", 1.00),
        _setting(config, "high_time_gap_seconds", 0.50),
        EPSILON,
    )
    closing_reference = max(
        _setting(config, "closing_speed_reference_pixels_per_second", 50.0), EPSILON
    )
    path_component = max(0.0, 1.0 - path_distance / path_tolerance)
    timing_component = max(0.0, 1.0 - arrival_gap / low_gap)
    closing_component = min(1.0, max(0.0, closing_speed / closing_reference))
    # An explainable prioritization index, never an accident probability.
    heuristic_score = round(
        35.0 * path_component + 35.0 * timing_component + 20.0 * closing_component + 10.0,
        1,
    )
    return {
        "timestamp_seconds": round(float(max(first.timestamp, second.timestamp)), 3),
        "frame_index": max(first.frame_index, second.frame_index),
        "severity": severity,
        "risk_score": heuristic_score,
        "participant_a_track_id": first.current_track_id,
        "participant_b_track_id": second.current_track_id,
        "participant_a_track_ids": list(first.source_track_ids),
        "participant_b_track_ids": list(second.source_track_ids),
        "participant_a_type": first.object_type,
        "participant_b_type": second.object_type,
        "participant_a_class": first.class_name,
        "participant_b_class": second.class_name,
        "conflict_point": [round(float(value), 2) for value in conflict_point],
        "participant_a_position": [round(float(value), 2) for value in first.position],
        "participant_b_position": [round(float(value), 2) for value in second.position],
        "participant_a_predicted_end": [round(float(value), 2) for value in first_end],
        "participant_b_predicted_end": [round(float(value), 2) for value in second_end],
        "participant_a_velocity_pixels_per_second": [
            round(float(value), 2) for value in first.velocity
        ],
        "participant_b_velocity_pixels_per_second": [
            round(float(value), 2) for value in second.velocity
        ],
        "participant_a_eta_seconds": round(first_eta, 3),
        "participant_b_eta_seconds": round(second_eta, 3),
        "arrival_time_gap_seconds": round(arrival_gap, 3),
        "path_separation_pixels": round(path_distance, 2),
        "closing_speed_pixels_per_second": round(closing_speed, 2),
        "inside_conflict_zone": True,
        "zone_is_user_defined": bool(config.get("zone_is_user_defined", True)),
        "prediction_horizon_seconds": horizon,
        "_logical_pair": tuple(sorted((first.logical_id, second.logical_id))),
    }


def _pair_diagnostic(
    first: MotionState,
    second: MotionState,
    zone: list[list[float]],
    config: dict,
) -> dict[str, Any]:
    """Return the same geometric gate measurements used by the detector.

    This intentionally reports rejection rather than changing detector policy.
    It is used only by the temporary dashboard diagnostics mode and tests.
    """

    horizon = max(0.1, _setting(config, "prediction_horizon_seconds", 2.0))
    path_tolerance = max(
        0.1,
        _setting(
            config,
            "path_intersection_tolerance_pixels",
            _setting(config, "max_distance_pixels", 35.0),
        ),
    )
    min_closing = max(0.0, _setting(config, "min_closing_speed_pixels_per_second", 2.0))
    stationary_speed = max(0.0, _setting(config, "stationary_speed_pixels_per_second", 2.0))
    min_future_time = max(0.0, _setting(config, "minimum_time_to_conflict_seconds", 0.05))
    relative_position = second.position - first.position
    separation = float(np.linalg.norm(relative_position))
    relative_velocity = second.velocity - first.velocity
    closing_speed = (
        float(np.linalg.norm(relative_velocity))
        if separation <= EPSILON
        else -float(np.dot(relative_position, relative_velocity)) / separation
    )
    first_stationary = first.speed <= stationary_speed
    second_stationary = second.speed <= stationary_speed
    first_end = first.position.copy() if first_stationary else first.position + first.velocity * horizon
    second_end = second.position.copy() if second_stationary else second.position + second.velocity * horizon
    first_point, second_point, first_fraction, second_fraction, path_distance = _closest_points_on_paths(
        first.position, first_end, second.position, second_end
    )
    first_eta = first_fraction * horizon
    second_eta = second_fraction * horizon
    conflict_point = (first_point + second_point) / 2.0
    inside_zone = _point_in_polygon(conflict_point, zone)
    arrival_gap = abs(first_eta - second_eta)

    reason = "accepted"
    if closing_speed < min_closing:
        reason = "not_closing"
    elif first_stationary and second_stationary:
        reason = "both_stationary"
    elif path_distance > path_tolerance:
        reason = "projected_paths_separated"
    elif (not first_stationary and first_eta < min_future_time) or (
        not second_stationary and second_eta < min_future_time
    ):
        reason = "conflict_is_not_in_future"
    elif not inside_zone:
        reason = "conflict_point_outside_zone"
    elif _severity(arrival_gap, config) is None:
        reason = "arrival_gap_above_low_threshold"

    return {
        "frame_index": max(first.frame_index, second.frame_index),
        "timestamp_seconds": round(max(first.timestamp, second.timestamp), 3),
        "participant_a_track_id": first.current_track_id,
        "participant_b_track_id": second.current_track_id,
        "participant_a_class": first.class_name,
        "participant_b_class": second.class_name,
        "participant_a_velocity_pixels_per_second": [round(float(value), 2) for value in first.velocity],
        "participant_b_velocity_pixels_per_second": [round(float(value), 2) for value in second.velocity],
        "participant_a_speed_pixels_per_second": round(first.speed, 2),
        "participant_b_speed_pixels_per_second": round(second.speed, 2),
        "projected_paths_overlap": path_distance <= path_tolerance,
        "path_separation_pixels": round(path_distance, 2),
        "participant_a_eta_seconds": round(first_eta, 3),
        "participant_b_eta_seconds": round(second_eta, 3),
        "arrival_time_gap_seconds": round(arrival_gap, 3),
        "closing_speed_pixels_per_second": round(closing_speed, 2),
        "conflict_point": [round(float(value), 2) for value in conflict_point],
        "inside_conflict_zone": inside_zone,
        "rejection_reason": reason,
    }


def diagnose_conflicts(tracks, zone, config) -> list[dict]:
    """Return per-frame vehicle-pair gate diagnostics without creating events.

    The function mirrors the detector's timestamp loop. Rows with insufficient
    history are retained so a user can distinguish a tracker limitation from a
    geometric rejection. It never changes `detect_conflicts` output.
    """

    if not isinstance(tracks, list) or not isinstance(zone, list) or len(zone) < 3:
        return []
    config = config if isinstance(config, dict) else {}
    observations = _normalize_tracks(tracks)
    logical_tracks = _stitch_tracklets(_raw_tracklets(observations), config)
    track_by_id = {track.logical_id: track for track in logical_tracks}
    updates: dict[float, list[tuple[int, Observation]]] = defaultdict(list)
    for track in logical_tracks:
        if track.object_type != "vehicle":
            continue
        for observation in track.observations:
            updates[observation.timestamp].append((track.logical_id, observation))

    histories: dict[int, list[Observation]] = defaultdict(list)
    rows: list[dict] = []
    min_age = max(2, int(_setting(config, "min_track_age_frames", 3)))
    for timestamp in sorted(updates):
        for logical_id, observation in updates[timestamp]:
            histories[logical_id].append(observation)
        active_ids = [
            logical_id
            for logical_id, history in histories.items()
            if history and timestamp - history[-1].timestamp <= max(0.0, _setting(config, "max_observation_age_seconds", 0.25))
        ]
        for first_id, second_id in combinations(sorted(active_ids), 2):
            first_history, second_history = histories[first_id], histories[second_id]
            first_last, second_last = first_history[-1], second_history[-1]
            base = {
                "frame_index": max(first_last.frame_index, second_last.frame_index),
                "timestamp_seconds": round(float(timestamp), 3),
                "participant_a_track_id": first_last.track_id,
                "participant_b_track_id": second_last.track_id,
                "participant_a_class": first_last.class_name,
                "participant_b_class": second_last.class_name,
                "participant_a_observations": len(first_history),
                "participant_b_observations": len(second_history),
            }
            if len(first_history) < min_age or len(second_history) < min_age:
                rows.append({**base, "rejection_reason": "insufficient_trajectory_observations"})
                continue
            first = _motion_state(track_by_id[first_id], first_history, timestamp, config)
            second = _motion_state(track_by_id[second_id], second_history, timestamp, config)
            if first is None or second is None:
                rows.append({**base, "rejection_reason": "stale_or_invalid_observation"})
                continue
            rows.append({**base, **_pair_diagnostic(first, second, zone, config)})
    return rows


def _best_episode_candidate(group: list[dict]) -> dict:
    best = max(
        group,
        key=lambda item: (
            SEVERITY_RANK[item["severity"]],
            item["risk_score"],
            -item["arrival_time_gap_seconds"],
        ),
    )
    event = dict(best)
    event["start_timestamp_seconds"] = group[0]["timestamp_seconds"]
    event["end_timestamp_seconds"] = group[-1]["timestamp_seconds"]
    event["start_frame_index"] = min(item["frame_index"] for item in group)
    event["end_frame_index"] = max(item["frame_index"] for item in group)
    # The start is the first time this pair met the heuristic, while the main
    # timestamp remains the strongest frame selected above.
    event["first_alert_timestamp_seconds"] = event["start_timestamp_seconds"]
    return event


def _deduplicate_candidates(candidates: list[dict], config: dict) -> list[dict]:
    """Collapse consecutive candidate frames into one event per pair/episode."""

    cooldown = max(0.0, _setting(config, "duplicate_cooldown_seconds", 2.0))
    by_pair: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_pair[candidate["_logical_pair"]].append(candidate)

    episodes: list[dict] = []
    for pair_candidates in by_pair.values():
        pair_candidates.sort(key=lambda item: item["timestamp_seconds"])
        group: list[dict] = []
        previous_time: float | None = None
        for candidate in pair_candidates:
            timestamp = float(candidate["timestamp_seconds"])
            if previous_time is not None and timestamp - previous_time > cooldown:
                episodes.append(_best_episode_candidate(group))
                group = []
            group.append(candidate)
            previous_time = timestamp
        if group:
            episodes.append(_best_episode_candidate(group))

    episodes.sort(key=lambda item: item["timestamp_seconds"])
    for index, event in enumerate(episodes, start=1):
        event["event_id"] = f"conflict-{index:03d}"
        event.pop("_logical_pair", None)
        first_type = event["participant_a_type"]
        second_type = event["participant_b_type"]
        event["interaction_type"] = f"{first_type}_to_{second_type}"
        if first_type == second_type == "vehicle":
            for suffix in (
                "track_id",
                "track_ids",
                "class",
                "position",
                "predicted_end",
                "velocity_pixels_per_second",
                "eta_seconds",
            ):
                event[f"vehicle_a_{suffix}"] = event[f"participant_a_{suffix}"]
                event[f"vehicle_b_{suffix}"] = event[f"participant_b_{suffix}"]
        # Keep vehicle/pedestrian aliases for existing consumers when optional
        # pedestrian analysis is selected. Vehicle-to-vehicle events use the
        # explicit participant_a / participant_b fields instead.
        if {first_type, second_type} == {"vehicle", "pedestrian"}:
            vehicle_is_first = first_type == "vehicle"
            vehicle_prefix = "participant_a" if vehicle_is_first else "participant_b"
            pedestrian_prefix = "participant_b" if vehicle_is_first else "participant_a"
            for suffix in (
                "track_id",
                "track_ids",
                "class",
                "position",
                "predicted_end",
                "velocity_pixels_per_second",
                "eta_seconds",
            ):
                event[f"vehicle_{suffix}"] = event[f"{vehicle_prefix}_{suffix}"]
                event[f"pedestrian_{suffix}"] = event[f"{pedestrian_prefix}_{suffix}"]
        area_label = "selected zone" if event.get("zone_is_user_defined", True) else "whole frame"
        event["description"] = (
            f'{event["severity"]} provisional image-coordinate flag: projected paths '
            f'converge inside the {area_label} with a {event["arrival_time_gap_seconds"]:.2f}s '
            f'arrival gap and {event["path_separation_pixels"]:.1f}px projected separation.'
        )
        event["metrics"] = {
            "arrival_time_gap_seconds": event["arrival_time_gap_seconds"],
            "participant_a_eta_seconds": event["participant_a_eta_seconds"],
            "participant_b_eta_seconds": event["participant_b_eta_seconds"],
            "path_separation_pixels": event["path_separation_pixels"],
            "closing_speed_pixels_per_second": event[
                "closing_speed_pixels_per_second"
            ],
            "heuristic_risk_index": event["risk_score"],
        }
    return episodes


def detect_conflicts(tracks, zone, config):
    """
    Analyze tracked objects and identify potentially dangerous interactions.
    Vehicle-to-vehicle
    analysis is the default; vehicle-to-pedestrian analysis remains optional.

    Args:
        tracks: Object positions across video frames.
        zone: Polygon defining the intersection area.
        config: Detection thresholds.

    Returns:
        List of potential conflict events.

    Notes:
        Positions, velocities, distances, and predictions are in image pixels.
        Risk labels are provisional heuristic categories, not accident
        probabilities or calibrated physical measurements.
    """

    if not isinstance(tracks, list) or not isinstance(zone, list) or len(zone) < 3:
        return []
    config = config if isinstance(config, dict) else {}
    analysis_mode = str(config.get("analysis_mode", "vehicle_vehicle")).lower()
    if analysis_mode not in {"vehicle_vehicle", "vehicle_pedestrian", "both"}:
        analysis_mode = "vehicle_vehicle"
    observations = _normalize_tracks(tracks)
    if not observations:
        return []

    logical_tracks = _stitch_tracklets(_raw_tracklets(observations), config)
    track_by_id = {track.logical_id: track for track in logical_tracks}
    updates: dict[float, list[tuple[int, Observation]]] = defaultdict(list)
    for track in logical_tracks:
        for observation in track.observations:
            updates[observation.timestamp].append((track.logical_id, observation))

    histories: dict[int, list[Observation]] = defaultdict(list)
    candidates: list[dict] = []
    for timestamp in sorted(updates):
        for logical_id, observation in updates[timestamp]:
            histories[logical_id].append(observation)

        vehicles: list[MotionState] = []
        pedestrians: list[MotionState] = []
        for logical_id, history in histories.items():
            state = _motion_state(track_by_id[logical_id], history, timestamp, config)
            if state is None:
                continue
            if state.object_type == "vehicle":
                vehicles.append(state)
            elif state.object_type == "pedestrian":
                pedestrians.append(state)

        pairs: list[tuple[MotionState, MotionState]] = []
        if analysis_mode in {"vehicle_vehicle", "both"}:
            pairs.extend(combinations(vehicles, 2))
        if analysis_mode in {"vehicle_pedestrian", "both"}:
            pairs.extend((vehicle, pedestrian) for vehicle in vehicles for pedestrian in pedestrians)
        for first, second in pairs:
            candidate = _candidate_event(first, second, zone, config)
            if candidate is not None:
                candidates.append(candidate)

    return _deduplicate_candidates(candidates, config)
