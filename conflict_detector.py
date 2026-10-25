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
    confidence: float


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
    observation_count: int
    mean_confidence: float
    velocity_samples: int

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
                confidence=float(record.get("confidence", 0.0) or 0.0),
            )
        )
    return sorted(observations, key=lambda item: (item.timestamp, item.frame_index, item.track_id))


def _velocity_segments(observations: list[Observation], smoothing_frames: int) -> list[np.ndarray]:
    """Return recent timestamp-based velocities after rejecting jitter jumps."""

    recent = observations[-max(3, smoothing_frames) :]
    segments: list[np.ndarray] = []
    for previous, current in zip(recent, recent[1:]):
        elapsed = current.timestamp - previous.timestamp
        if elapsed <= EPSILON:
            continue
        velocity = (current.position - previous.position) / elapsed
        if np.all(np.isfinite(velocity)):
            segments.append(velocity)
    if len(segments) <= 2:
        return segments
    values = np.asarray(segments, dtype=float)
    median = np.median(values, axis=0)
    deviations = np.linalg.norm(values - median, axis=1)
    limit = max(35.0, 3.5 * float(np.median(deviations)))
    filtered = [value for value, deviation in zip(values, deviations) if deviation <= limit]
    return filtered or [median]


def _estimate_velocity(observations: list[Observation], smoothing_frames: int) -> np.ndarray:
    """Compute a recency-weighted rolling velocity from robust segments."""

    segments = _velocity_segments(observations, smoothing_frames)
    if not segments:
        return np.zeros(2, dtype=float)
    values = np.asarray(segments, dtype=float)
    weights = np.arange(1, len(values) + 1, dtype=float)
    return np.average(values, axis=0, weights=weights)


def _smoothed_position(
    observations: list[Observation], velocity: np.ndarray, smoothing_frames: int
) -> np.ndarray:
    recent = observations[-max(3, smoothing_frames) :]
    latest_time = recent[-1].timestamp
    projected = [
        item.position + velocity * (latest_time - item.timestamp) for item in recent
    ]
    return np.median(np.asarray(projected, dtype=float), axis=0)


def _vehicle_family(class_name: str) -> str:
    if class_name in {"truck", "bus"}:
        return "heavy"
    if class_name == "motorcycle":
        return "motorcycle"
    return "car"


def _dominant_family(observations: list[Observation]) -> str:
    families = [_vehicle_family(item.class_name) for item in observations]
    return max(set(families), key=families.count)


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
    max_box_ratio = max(0.25, _setting(config, "id_stitch_distance_box_ratio", 1.75))
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
            if (
                candidate.object_type == "vehicle"
                and len(candidate.observations) >= 3
                and len(fragment.observations) >= 3
                and _dominant_family(candidate.observations)
                != _dominant_family(fragment.observations)
            ):
                continue
            velocity = _estimate_velocity(candidate.observations, smoothing_frames)
            projected_endpoint = last.position + velocity * gap
            distance = float(np.linalg.norm(first.position - projected_endpoint))
            last_width = max(1.0, last.bbox[2] - last.bbox[0])
            first_width = max(1.0, first.bbox[2] - first.bbox[0])
            allowed_distance = min(max_distance, max_box_ratio * max(last_width, first_width))
            direction_consistent = True
            if len(candidate.observations) >= 4 and len(fragment.observations) >= 4:
                fragment_velocity = _estimate_velocity(fragment.observations, smoothing_frames)
                first_speed = float(np.linalg.norm(velocity))
                second_speed = float(np.linalg.norm(fragment_velocity))
                if first_speed > 5.0 and second_speed > 5.0:
                    cosine = float(
                        np.dot(velocity, fragment_velocity) / (first_speed * second_speed)
                    )
                    direction_consistent = cosine >= 0.25
            if direction_consistent and distance <= allowed_distance and distance < best_distance:
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
    min_age = max(3, int(_setting(config, "min_track_age_frames", 6)))
    if len(history) < min_age:
        return None
    latest = history[-1]
    observation_age = timestamp - latest.timestamp
    max_age = max(0.0, _setting(config, "max_observation_age_seconds", 0.12))
    if observation_age < -EPSILON or observation_age > max_age:
        return None
    smoothing_frames = max(3, int(_setting(config, "velocity_smoothing_frames", 8)))
    velocity = _estimate_velocity(history, smoothing_frames)
    position = _smoothed_position(history, velocity, smoothing_frames)
    position = position + velocity * max(0.0, observation_age)
    recent = history[-max(3, smoothing_frames) :]
    return MotionState(
        logical_id=track.logical_id,
        object_type=track.object_type,
        class_name=latest.class_name,
        current_track_id=latest.track_id,
        source_track_ids=tuple(sorted({item.track_id for item in history})),
        frame_index=latest.frame_index,
        timestamp=timestamp,
        position=position,
        velocity=velocity,
        bbox=latest.bbox,
        observation_count=len(history),
        mean_confidence=float(np.mean([item.confidence for item in recent])),
        velocity_samples=len(_velocity_segments(history, smoothing_frames)),
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


def _vehicle_radius(state: MotionState, config: dict) -> float:
    width = max(1.0, float(state.bbox[2]) - float(state.bbox[0]))
    fraction = max(0.05, _setting(config, "vehicle_footprint_width_fraction", 0.20))
    maximum = max(2.0, _setting(config, "maximum_vehicle_radius_pixels", 24.0))
    return min(maximum, max(2.0, width * fraction))


def _following_conflict(
    first: MotionState,
    second: MotionState,
    conflict_region_radius: float,
    effective_margin: float,
    horizon: float,
    min_future_time: float,
    config: dict,
) -> dict[str, Any] | None:
    """Same-direction (rear-end) geometry for two moving, aligned vehicles.

    Collinear finite paths make the crossing-path closest point collapse onto
    the lead vehicle's *current* position (ETA 0), which the future-conflict
    gate correctly rejects for crossing traffic but which hides a trailing
    vehicle closing on a slower leader. This branch is used only when that
    gate would reject the pair. Contact time is the first moment the relative
    bottom-center motion (offsets and lateral drift included) brings the
    centers within the combined footprint radius; the timing measure is time
    headway (seconds between the leader and follower passing the same point).
    """

    if not bool(config.get("same_direction_following_enabled", True)):
        return None
    min_speed = max(0.0, _setting(config, "following_min_speed_pixels_per_second", 20.0))
    stationary_speed = max(0.0, _setting(config, "stationary_speed_pixels_per_second", 2.0))
    if min(first.speed, second.speed) <= max(stationary_speed, EPSILON):
        return None
    cosine = float(np.dot(first.velocity, second.velocity) / (first.speed * second.speed))
    if cosine < _setting(config, "following_min_direction_cosine", 0.94):
        return None
    direction = first.velocity / first.speed + second.velocity / second.speed
    direction = direction / max(float(np.linalg.norm(direction)), EPSILON)
    offset = second.position - first.position
    longitudinal = float(np.dot(offset, direction))
    lateral = abs(_cross_2d(direction, offset))
    if lateral > conflict_region_radius + effective_margin:
        return None
    follower, leader = (first, second) if longitudinal > 0 else (second, first)
    gap = abs(longitudinal)
    follower_speed = float(np.dot(follower.velocity, direction))
    closing = follower_speed - float(np.dot(leader.velocity, direction))
    if closing <= EPSILON or follower_speed < max(min_speed, EPSILON) or gap <= conflict_region_radius:
        return None
    # First time the footprint circles touch: solve |r + v*t| = R on the full
    # relative motion so lateral offset and lateral drift are both respected.
    relative_position = leader.position - follower.position
    relative_velocity = leader.velocity - follower.velocity
    a = float(np.dot(relative_velocity, relative_velocity))
    b = 2.0 * float(np.dot(relative_position, relative_velocity))
    c = float(np.dot(relative_position, relative_position)) - conflict_region_radius**2
    discriminant = b * b - 4.0 * a * c
    if a <= EPSILON or c <= 0.0 or discriminant < 0.0:
        return None
    contact_time = (-b - float(np.sqrt(discriminant))) / (2.0 * a)
    if not (min_future_time <= contact_time <= horizon):
        return None
    headway = gap / follower_speed
    first_point = first.position + first.velocity * contact_time
    second_point = second.position + second.velocity * contact_time
    return {
        "first_point": first_point,
        "second_point": second_point,
        "path_distance": lateral,
        "first_eta": contact_time,
        "second_eta": contact_time,
        "arrival_gap": headway,
        "time_headway_seconds": headway,
        "following_gap_pixels": gap,
        "follower_track_id": follower.current_track_id,
        "leader_track_id": leader.current_track_id,
    }


def _candidate_event(
    first: MotionState,
    second: MotionState,
    zone: list[list[float]],
    config: dict,
) -> dict[str, Any] | None:
    horizon = max(0.1, _setting(config, "prediction_horizon_seconds", 2.0))
    path_margin = max(
        0.1,
        _setting(
            config,
            "path_intersection_tolerance_pixels",
            _setting(config, "max_distance_pixels", 8.0),
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
    first_radius = _vehicle_radius(first, config)
    second_radius = _vehicle_radius(second, config)
    conflict_region_radius = first_radius + second_radius
    effective_margin = min(path_margin, 0.25 * conflict_region_radius)
    footprint_overlap = path_distance <= conflict_region_radius
    if path_distance > conflict_region_radius + effective_margin:
        return None

    first_eta = first_fraction * horizon
    second_eta = second_fraction * horizon
    arrival_gap = abs(first_eta - second_eta)
    following = None
    if (not first_stationary and first_eta < min_future_time) or (
        not second_stationary and second_eta < min_future_time
    ):
        following = _following_conflict(
            first,
            second,
            conflict_region_radius,
            effective_margin,
            horizon,
            min_future_time,
            config,
        )
        if following is None:
            return None
        first_point = following["first_point"]
        second_point = following["second_point"]
        path_distance = following["path_distance"]
        footprint_overlap = path_distance <= conflict_region_radius
        first_eta = following["first_eta"]
        second_eta = following["second_eta"]
        arrival_gap = following["arrival_gap"]

    conflict_point = (first_point + second_point) / 2.0
    if not _point_in_polygon(conflict_point, zone):
        return None

    severity = _severity(arrival_gap, config)
    if severity is None:
        return None
    if not footprint_overlap:
        severity = "LOW"

    low_gap = max(
        _setting(config, "low_time_gap_seconds", 1.75),
        _setting(config, "medium_time_gap_seconds", 1.00),
        _setting(config, "high_time_gap_seconds", 0.50),
        EPSILON,
    )
    closing_reference = max(
        _setting(config, "closing_speed_reference_pixels_per_second", 50.0), EPSILON
    )
    path_component = max(
        0.0,
        1.0 - path_distance / max(conflict_region_radius + effective_margin, EPSILON),
    )
    timing_component = max(0.0, 1.0 - arrival_gap / low_gap)
    closing_component = min(1.0, max(0.0, closing_speed / closing_reference))
    # An explainable prioritization index, never an accident probability.
    heuristic_score = round(
        35.0 * path_component + 35.0 * timing_component + 20.0 * closing_component + 10.0,
        1,
    )
    geometry: dict[str, Any] = {"conflict_geometry": "crossing_paths"}
    if following is not None:
        geometry = {
            "conflict_geometry": "same_direction_following",
            "time_headway_seconds": round(following["time_headway_seconds"], 3),
            "following_gap_pixels": round(following["following_gap_pixels"], 2),
            "follower_track_id": following["follower_track_id"],
            "leader_track_id": following["leader_track_id"],
        }
    return {
        "timestamp_seconds": round(float(max(first.timestamp, second.timestamp)), 3),
        "frame_index": max(first.frame_index, second.frame_index),
        "severity": severity,
        "risk_score": heuristic_score,
        **geometry,
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
        "participant_a_bbox": [round(float(value), 2) for value in first.bbox],
        "participant_b_bbox": [round(float(value), 2) for value in second.bbox],
        "participant_a_predicted_end": [round(float(value), 2) for value in first_end],
        "participant_b_predicted_end": [round(float(value), 2) for value in second_end],
        "participant_a_conflict_position": [
            round(float(value), 2) for value in first_point
        ],
        "participant_b_conflict_position": [
            round(float(value), 2) for value in second_point
        ],
        "participant_a_velocity_pixels_per_second": [
            round(float(value), 2) for value in first.velocity
        ],
        "participant_b_velocity_pixels_per_second": [
            round(float(value), 2) for value in second.velocity
        ],
        "participant_a_eta_seconds": round(first_eta, 3),
        "participant_b_eta_seconds": round(second_eta, 3),
        "time_to_conflict_seconds": round((first_eta + second_eta) / 2.0, 3),
        "arrival_time_gap_seconds": round(arrival_gap, 3),
        "path_separation_pixels": round(path_distance, 2),
        "projected_footprints_overlap": footprint_overlap,
        "conflict_region_radius_pixels": round(conflict_region_radius, 2),
        "path_uncertainty_margin_pixels": round(effective_margin, 2),
        "closing_speed_pixels_per_second": round(closing_speed, 2),
        "participant_a_observations": first.observation_count,
        "participant_b_observations": second.observation_count,
        "participant_a_mean_confidence": round(first.mean_confidence, 3),
        "participant_b_mean_confidence": round(second.mean_confidence, 3),
        "participant_a_velocity_samples": first.velocity_samples,
        "participant_b_velocity_samples": second.velocity_samples,
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
    path_margin = max(
        0.1,
        _setting(
            config,
            "path_intersection_tolerance_pixels",
            _setting(config, "max_distance_pixels", 8.0),
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
    first_radius = _vehicle_radius(first, config)
    second_radius = _vehicle_radius(second, config)
    conflict_region_radius = first_radius + second_radius
    effective_margin = min(path_margin, 0.25 * conflict_region_radius)
    footprint_overlap = path_distance <= conflict_region_radius
    first_eta = first_fraction * horizon
    second_eta = second_fraction * horizon
    arrival_gap = abs(first_eta - second_eta)
    conflict_geometry = "crossing_paths"
    not_in_future = (not first_stationary and first_eta < min_future_time) or (
        not second_stationary and second_eta < min_future_time
    )
    if (
        not_in_future
        and closing_speed >= min_closing
        and path_distance <= conflict_region_radius + effective_margin
    ):
        following = _following_conflict(
            first,
            second,
            conflict_region_radius,
            effective_margin,
            horizon,
            min_future_time,
            config,
        )
        if following is not None:
            not_in_future = False
            conflict_geometry = "same_direction_following"
            first_point = following["first_point"]
            second_point = following["second_point"]
            path_distance = following["path_distance"]
            footprint_overlap = path_distance <= conflict_region_radius
            first_eta = following["first_eta"]
            second_eta = following["second_eta"]
            arrival_gap = following["arrival_gap"]
    conflict_point = (first_point + second_point) / 2.0
    inside_zone = _point_in_polygon(conflict_point, zone)

    reason = "accepted"
    if closing_speed < min_closing:
        reason = "not_closing"
    elif first_stationary and second_stationary:
        reason = "both_stationary"
    elif path_distance > conflict_region_radius + effective_margin:
        reason = "projected_paths_separated"
    elif not_in_future:
        reason = "conflict_is_not_in_future"
    elif not inside_zone:
        reason = "conflict_point_outside_zone"
    elif _severity(arrival_gap, config) is None:
        reason = "arrival_gap_above_low_threshold"
    elif not footprint_overlap:
        reason = "accepted_low_uncertainty_margin_only"

    return {
        "frame_index": max(first.frame_index, second.frame_index),
        "timestamp_seconds": round(max(first.timestamp, second.timestamp), 3),
        "participant_a_track_id": first.current_track_id,
        "participant_b_track_id": second.current_track_id,
        "participant_a_class": first.class_name,
        "participant_b_class": second.class_name,
        "participant_a_position": [round(float(value), 2) for value in first.position],
        "participant_b_position": [round(float(value), 2) for value in second.position],
        "participant_a_velocity_pixels_per_second": [round(float(value), 2) for value in first.velocity],
        "participant_b_velocity_pixels_per_second": [round(float(value), 2) for value in second.velocity],
        "participant_a_speed_pixels_per_second": round(first.speed, 2),
        "participant_b_speed_pixels_per_second": round(second.speed, 2),
        "participant_a_predicted_position": [round(float(value), 2) for value in first_end],
        "participant_b_predicted_position": [round(float(value), 2) for value in second_end],
        "projected_paths_overlap": footprint_overlap,
        "path_separation_pixels": round(path_distance, 2),
        "conflict_region_radius_pixels": round(conflict_region_radius, 2),
        "participant_a_eta_seconds": round(first_eta, 3),
        "participant_b_eta_seconds": round(second_eta, 3),
        "arrival_time_gap_seconds": round(arrival_gap, 3),
        "time_to_conflict_seconds": round((first_eta + second_eta) / 2.0, 3),
        "closing_speed_pixels_per_second": round(closing_speed, 2),
        "conflict_point": [round(float(value), 2) for value in conflict_point],
        "inside_conflict_zone": inside_zone,
        "conflict_geometry": conflict_geometry,
        "participant_a_mean_confidence": round(first.mean_confidence, 3),
        "participant_b_mean_confidence": round(second.mean_confidence, 3),
        "participant_a_velocity_samples": first.velocity_samples,
        "participant_b_velocity_samples": second.velocity_samples,
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
    min_age = max(3, int(_setting(config, "min_track_age_frames", 6)))
    for timestamp in sorted(updates):
        for logical_id, observation in updates[timestamp]:
            histories[logical_id].append(observation)
        active_ids = [
            logical_id
            for logical_id, history in histories.items()
            if history and timestamp - history[-1].timestamp <= max(0.0, _setting(config, "max_observation_age_seconds", 0.12))
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
                "participant_a_mean_confidence": round(
                    float(np.mean([item.confidence for item in first_history[-8:]])), 3
                ),
                "participant_b_mean_confidence": round(
                    float(np.mean([item.confidence for item in second_history[-8:]])), 3
                ),
                "temporal_confirmation_frames_required": max(
                    2, int(_setting(config, "high_persistence_frames", 3))
                ),
                "_logical_pair": tuple(sorted((first_id, second_id))),
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

    # Explain the final temporal gate as well as the geometric gates. This is
    # deliberately diagnostic-only: it mirrors the detector policy without
    # creating or upgrading an event.
    runs: dict[tuple[int, int], dict[str, int | None]] = defaultdict(
        lambda: {"low": 0, "medium": 0, "high": 0, "previous_frame": None}
    )
    max_frame_gap = max(1, int(_setting(config, "persistence_max_frame_gap", 3)))
    required = {
        "LOW": max(1, int(_setting(config, "min_event_persistence_frames", 2))),
        "MEDIUM": max(2, int(_setting(config, "medium_persistence_frames", 2))),
        "HIGH": max(2, int(_setting(config, "high_persistence_frames", 3))),
    }
    for row in rows:
        pair = row.pop("_logical_pair", None)
        if pair is None:
            continue
        state = runs[pair]
        frame = int(row["frame_index"])
        previous_frame = state["previous_frame"]
        consecutive = previous_frame is None or 0 < frame - int(previous_frame) <= max_frame_gap
        accepted_geometry = row.get("rejection_reason") in {
            "accepted",
            "accepted_low_uncertainty_margin_only",
        }
        if not accepted_geometry or not consecutive:
            state["low"] = state["medium"] = state["high"] = 0
        if accepted_geometry:
            projected_severity = _severity(float(row["arrival_time_gap_seconds"]), config)
            if row.get("rejection_reason") == "accepted_low_uncertainty_margin_only":
                projected_severity = "LOW"
            row["projected_risk_class"] = projected_severity
            rank = SEVERITY_RANK.get(projected_severity or "", 0)
            state["low"] = int(state["low"]) + 1
            state["medium"] = int(state["medium"]) + 1 if rank >= 2 else 0
            state["high"] = int(state["high"]) + 1 if rank >= 3 else 0
            observed = int(state[projected_severity.lower()])
            needed = required[projected_severity]
            row["temporal_confirmation_frames_observed"] = observed
            row["temporal_confirmation_frames_required"] = needed
            row["temporal_confirmation_met"] = observed >= needed
            if observed < needed:
                row["rejection_reason"] = "pending_temporal_confirmation"
        else:
            row["projected_risk_class"] = None
            row["temporal_confirmation_frames_observed"] = 0
            row["temporal_confirmation_met"] = False
        state["previous_frame"] = frame
    return rows


def _longest_run(group: list[dict], minimum_rank: int, max_frame_gap: int) -> int:
    longest = current = 0
    previous_frame: int | None = None
    for item in group:
        frame = int(item["frame_index"])
        qualifies = SEVERITY_RANK[item["severity"]] >= minimum_rank
        if qualifies and (previous_frame is None or 0 < frame - previous_frame <= max_frame_gap):
            current += 1
        elif qualifies:
            current = 1
        else:
            current = 0
        longest = max(longest, current)
        previous_frame = frame
    return longest


def _first_confirmed_candidate(
    group: list[dict], minimum_rank: int, required: int, max_frame_gap: int
) -> dict:
    run: list[dict] = []
    for item in group:
        if SEVERITY_RANK[item["severity"]] < minimum_rank:
            run = []
            continue
        if run and not (
            0 < int(item["frame_index"]) - int(run[-1]["frame_index"]) <= max_frame_gap
        ):
            run = []
        run.append(item)
        if len(run) >= required:
            return item
    return group[-1]


def _best_episode_candidate(group: list[dict], config: dict) -> dict:
    by_frame: dict[int, dict] = {}
    for item in group:
        frame = int(item["frame_index"])
        previous = by_frame.get(frame)
        if previous is None or (SEVERITY_RANK[item["severity"]], item["risk_score"]) > (
            SEVERITY_RANK[previous["severity"]], previous["risk_score"]
        ):
            by_frame[frame] = item
    group = sorted(by_frame.values(), key=lambda item: item["timestamp_seconds"])
    best = max(
        group,
        key=lambda item: (
            SEVERITY_RANK[item["severity"]],
            item["risk_score"],
            -item["arrival_time_gap_seconds"],
        ),
    )
    event = dict(best)
    event["participant_a_track_ids"] = sorted(
        {track_id for item in group for track_id in item["participant_a_track_ids"]}
    )
    event["participant_b_track_ids"] = sorted(
        {track_id for item in group for track_id in item["participant_b_track_ids"]}
    )
    event["candidate_start_timestamp_seconds"] = group[0]["timestamp_seconds"]
    event["end_timestamp_seconds"] = group[-1]["timestamp_seconds"]
    event["end_frame_index"] = max(item["frame_index"] for item in group)
    event["persistence_frames"] = len(group)
    max_gap = max(1, int(_setting(config, "persistence_max_frame_gap", 3)))
    high_required = max(2, int(_setting(config, "high_persistence_frames", 3)))
    medium_required = max(2, int(_setting(config, "medium_persistence_frames", 2)))
    high_run = _longest_run(group, SEVERITY_RANK["HIGH"], max_gap)
    medium_run = _longest_run(group, SEVERITY_RANK["MEDIUM"], max_gap)
    if high_run >= high_required:
        event["severity"] = "HIGH"
        first_alert = _first_confirmed_candidate(
            group, SEVERITY_RANK["HIGH"], high_required, max_gap
        )
    elif medium_run >= medium_required:
        event["severity"] = "MEDIUM"
        first_alert = _first_confirmed_candidate(
            group, SEVERITY_RANK["MEDIUM"], medium_required, max_gap
        )
    else:
        event["severity"] = "LOW"
        low_required = max(1, int(_setting(config, "min_event_persistence_frames", 2)))
        first_alert = _first_confirmed_candidate(
            group, SEVERITY_RANK["LOW"], low_required, max_gap
        )
    event["first_alert_timestamp_seconds"] = first_alert["timestamp_seconds"]
    event["start_timestamp_seconds"] = first_alert["timestamp_seconds"]
    event["start_frame_index"] = first_alert["frame_index"]
    event["high_persistence_frames"] = high_run
    event["medium_or_high_persistence_frames"] = medium_run
    return event


def _deduplicate_candidates(candidates: list[dict], config: dict) -> list[dict]:
    """Collapse consecutive candidate frames into one event per pair/episode."""

    cooldown = max(0.0, _setting(config, "duplicate_cooldown_seconds", 2.0))
    episode_gap = max(0.01, _setting(config, "candidate_episode_gap_seconds", 0.20))
    max_frame_gap = max(1, int(_setting(config, "persistence_max_frame_gap", 3)))
    minimum_frames = max(1, int(_setting(config, "min_event_persistence_frames", 2)))
    by_pair: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_pair[candidate["_logical_pair"]].append(candidate)

    episodes: list[dict] = []
    for pair_candidates in by_pair.values():
        pair_candidates.sort(key=lambda item: item["timestamp_seconds"])
        group: list[dict] = []
        previous_time: float | None = None
        previous_frame: int | None = None
        for candidate in pair_candidates:
            timestamp = float(candidate["timestamp_seconds"])
            frame = int(candidate["frame_index"])
            if previous_time is not None and (
                timestamp - previous_time > episode_gap
                or (previous_frame is not None and frame - previous_frame > max_frame_gap)
            ):
                episode = _best_episode_candidate(group, config)
                if episode["persistence_frames"] >= minimum_frames:
                    episodes.append(episode)
                group = []
            group.append(candidate)
            previous_time = timestamp
            previous_frame = frame
        if group:
            episode = _best_episode_candidate(group, config)
            if episode["persistence_frames"] >= minimum_frames:
                episodes.append(episode)

    # A brief detector dropout can split one continuous physical interaction
    # into two candidate episodes. Merge only already-qualified episodes for
    # the same logical pair inside the explicit cooldown; this preserves the
    # temporal-confirmation safeguard while preventing duplicate alerts.
    episodes.sort(
        key=lambda item: (item["_logical_pair"], item["first_alert_timestamp_seconds"])
    )
    merged_episodes: list[dict] = []
    for event in episodes:
        previous = merged_episodes[-1] if merged_episodes else None
        same_pair = previous is not None and previous["_logical_pair"] == event["_logical_pair"]
        gap = (
            float(event["candidate_start_timestamp_seconds"])
            - float(previous["end_timestamp_seconds"])
            if same_pair
            else float("inf")
        )
        if not same_pair or gap > cooldown:
            merged_episodes.append(event)
            continue
        strongest = max(
            (previous, event),
            key=lambda item: (SEVERITY_RANK[item["severity"]], item["risk_score"]),
        )
        merged = dict(strongest)
        merged["candidate_start_timestamp_seconds"] = min(
            previous["candidate_start_timestamp_seconds"],
            event["candidate_start_timestamp_seconds"],
        )
        merged["first_alert_timestamp_seconds"] = min(
            previous["first_alert_timestamp_seconds"], event["first_alert_timestamp_seconds"]
        )
        merged["start_timestamp_seconds"] = merged["first_alert_timestamp_seconds"]
        merged["start_frame_index"] = min(
            previous["start_frame_index"], event["start_frame_index"]
        )
        merged["end_timestamp_seconds"] = max(
            previous["end_timestamp_seconds"], event["end_timestamp_seconds"]
        )
        merged["end_frame_index"] = max(
            previous["end_frame_index"], event["end_frame_index"]
        )
        merged["persistence_frames"] = (
            int(previous["persistence_frames"]) + int(event["persistence_frames"])
        )
        merged["high_persistence_frames"] = max(
            int(previous["high_persistence_frames"]), int(event["high_persistence_frames"])
        )
        merged["medium_or_high_persistence_frames"] = max(
            int(previous["medium_or_high_persistence_frames"]),
            int(event["medium_or_high_persistence_frames"]),
        )
        for participant in ("a", "b"):
            key = f"participant_{participant}_track_ids"
            merged[key] = sorted(set(previous[key]) | set(event[key]))
        merged_episodes[-1] = merged

    episodes = sorted(
        merged_episodes, key=lambda item: item["first_alert_timestamp_seconds"]
    )
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
                "bbox",
                "conflict_position",
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
                "bbox",
                "conflict_position",
                "predicted_end",
                "velocity_pixels_per_second",
                "eta_seconds",
            ):
                event[f"vehicle_{suffix}"] = event[f"{vehicle_prefix}_{suffix}"]
                event[f"pedestrian_{suffix}"] = event[f"{pedestrian_prefix}_{suffix}"]
        area_label = "selected zone" if event.get("zone_is_user_defined", True) else "whole frame"
        if event.get("conflict_geometry") == "same_direction_following":
            event["description"] = (
                f'{event["severity"]} provisional image-coordinate flag: a trailing vehicle '
                f'is closing on a slower vehicle in the same direction inside the {area_label}; '
                f'projected footprint contact in {event["time_to_conflict_seconds"]:.2f}s '
                f'with a {event["arrival_time_gap_seconds"]:.2f}s time headway.'
            )
        else:
            event["description"] = (
                f'{event["severity"]} provisional image-coordinate flag: projected paths '
                f'converge inside the {area_label} with a {event["arrival_time_gap_seconds"]:.2f}s '
                f'arrival gap and {event["path_separation_pixels"]:.1f}px projected separation.'
            )
        event["metrics"] = {
            "arrival_time_gap_seconds": event["arrival_time_gap_seconds"],
            "time_to_conflict_seconds": event["time_to_conflict_seconds"],
            "participant_a_eta_seconds": event["participant_a_eta_seconds"],
            "participant_b_eta_seconds": event["participant_b_eta_seconds"],
            "path_separation_pixels": event["path_separation_pixels"],
            "closing_speed_pixels_per_second": event[
                "closing_speed_pixels_per_second"
            ],
            "heuristic_risk_index": event["risk_score"],
            "persistence_frames": event["persistence_frames"],
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
