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
VEHICLE_CLASS_IDS = {1, 2, 3, 5, 7}
TRACKED_CLASS_IDS = sorted(PERSON_CLASS_IDS | VEHICLE_CLASS_IDS)


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


DEFAULT_CONFLICT_CONFIG = {
    "ttc_threshold_seconds": 3.0,
    "max_distance_pixels": 120.0,
    "min_track_age_frames": 5,
}


def object_type_for_class(class_id: int) -> str:
    """Map a COCO class ID to the simplified categories used by the UI."""

    if class_id in PERSON_CLASS_IDS:
        return "pedestrian"
    if class_id in VEHICLE_CLASS_IDS:
        return "vehicle"
    return "other"

