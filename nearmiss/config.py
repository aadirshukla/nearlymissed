"""Configuration and COCO class mappings used by the tracking pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass


COCO_CLASS_NAMES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

PERSON_CLASS_IDS = {0}
BICYCLE_CLASS_IDS = {1}
VEHICLE_CLASS_IDS = {2, 3, 5, 7}
TRACKED_CLASS_IDS = sorted(PERSON_CLASS_IDS | BICYCLE_CLASS_IDS | VEHICLE_CLASS_IDS)


DEFAULT_CONFLICT_CONFIG = {
    "analysis_mode": "vehicle_vehicle",
    "prediction_horizon_seconds": 2.0,
    "high_time_gap_seconds": 0.50,
    "medium_time_gap_seconds": 1.00,
    "low_time_gap_seconds": 1.75,
    "path_intersection_tolerance_pixels": 8.0,
    "min_closing_speed_pixels_per_second": 2.0,
    "stationary_speed_pixels_per_second": 2.0,
    "closing_speed_reference_pixels_per_second": 50.0,
    "velocity_smoothing_frames": 8,
    "min_track_age_frames": 6,
    "max_observation_age_seconds": 0.12,
    "minimum_time_to_conflict_seconds": 0.05,
    "duplicate_cooldown_seconds": 2.0,
    "candidate_episode_gap_seconds": 0.20,
    "min_event_persistence_frames": 2,
    "medium_persistence_frames": 2,
    "high_persistence_frames": 3,
    "persistence_max_frame_gap": 3,
    "id_stitch_gap_seconds": 0.50,
    "id_stitch_distance_pixels": 60.0,
    "id_stitch_distance_box_ratio": 1.75,
    "vehicle_footprint_width_fraction": 0.20,
    "maximum_vehicle_radius_pixels": 24.0,
}


@dataclass(frozen=True)
class TrackingConfig:
    """Settings that affect YOLO detections and ByteTrack associations."""

    model_name: str = "yolo11n.pt"
    confidence: float = 0.30
    iou_threshold: float = 0.50
    device: str = "cpu"
    trail_length: int = 30

    def as_dict(self) -> dict:
        return asdict(self)


def object_type_for_class(class_id: int) -> str:
    """Map a COCO class ID to the simplified categories used by the UI."""

    if class_id in PERSON_CLASS_IDS:
        return "pedestrian"
    if class_id in VEHICLE_CLASS_IDS:
        return "vehicle"
    if class_id in BICYCLE_CLASS_IDS:
        return "cyclist"
    return "other"

