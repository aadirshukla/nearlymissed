"""Labeled synthetic intersection demonstration.

Generates a short, clearly illustrative top-down intersection clip and the
matching deterministic track rows locally, with no network access and no model
weights. The scripted rows stand in for YOLO/ByteTrack output only; prediction,
independent incident evidence, rendering, review, and simulated dispatch use
the normal NearMiss pipeline. Every generated frame is stamped SYNTHETIC DEMO
and every artifact carries ``data_source = "synthetic_demo"``.

Nothing in this module describes a real location, real traffic, or a real
incident.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from nearmiss.config import TrackingConfig
from nearmiss.store import delete_video_records
from nearmiss import video as video_module
from nearmiss.video import (
    AnalysisArtifacts,
    VideoError,
    VideoMetadata,
    _artifact_paths,
    transcode_for_browser,
)


DEMO_VERSION = 1
DEMO_DATA_SOURCE = "synthetic_demo"
DEMO_LABEL = "SYNTHETIC DEMO"
DEMO_ID_PREFIX = "synthetic-demo-"
DEMO_FILENAME = "nearmiss_synthetic_intersection_demo.mp4"
DEMO_CAMERA_ID = "DEMO-CAM-01 (synthetic)"
WIDTH, HEIGHT, FPS, DURATION_SECONDS = 960, 540, 20.0, 12.0

# Scripted rows replace model inference, so model settings never apply. A
# fixed tracking config keeps the demo artifacts at one stable cache path.
DEMO_TRACKING_CONFIG = TrackingConfig(
    model_name="scripted-synthetic-tracks",
    confidence=1.0,
    iou_threshold=1.0,
    device="none",
)

DEMO_PROVENANCE = {
    "data_source": DEMO_DATA_SOURCE,
    "label": DEMO_LABEL,
    "summary": (
        "Generated illustrative intersection footage with scripted, deterministic "
        "track rows. Not a real location, real traffic, or a real incident."
    ),
    "pipeline_boundary": (
        "Scripted track rows replace YOLO + ByteTrack inference. Conflict prediction, "
        "independent incident evidence, annotated playback, human review, and the "
        "local simulated dispatch inbox run unchanged on those rows."
    ),
    "generator": "nearmiss.demo",
    "generator_version": DEMO_VERSION,
}

UPLOAD_PROVENANCE = {
    "data_source": "uploaded_video",
    "label": "Uploaded footage",
    "summary": (
        "Operator-supplied MP4 analyzed locally with pretrained YOLO detection and "
        "ByteTrack identities. Results are provisional image-space screening signals."
    ),
    "pipeline_boundary": (
        "Detection, tracking, prediction, incident evidence and review run on this "
        "footage. Dispatch remains a local simulation."
    ),
}


@dataclass(frozen=True)
class Actor:
    """One scripted road user moving along a straight line.

    ``speed_knots`` are (absolute time, speed px/s) pairs; speed is linearly
    interpolated between knots and held constant outside them.
    """

    track_id: int
    class_name: str
    start_time: float
    start_center: tuple[float, float]
    direction: tuple[float, float]
    size: tuple[float, float]  # (width, height) of the axis-aligned box
    speed_knots: tuple[tuple[float, float], ...]
    color_bgr: tuple[int, int, int] = (170, 170, 170)
    end_time: float = DURATION_SECONDS


CLASS_IDS = {"person": 0, "car": 2, "truck": 7}
OBJECT_TYPES = {"person": "pedestrian", "car": "vehicle", "truck": "vehicle"}

# Road layout (pixels). Horizontal road y 190..350; vertical road x 400..560.
ROAD_H = (190, 350)
ROAD_V = (400, 560)
EAST_LANE_Y, WEST_LANE_Y = 310.0, 230.0
NORTH_LANE_X, SOUTH_LANE_X = 520.0, 440.0

ACTORS: tuple[Actor, ...] = (
    # Background traffic that crosses early and should not be flagged.
    Actor(10, "car", 0.0, (760.0, WEST_LANE_Y), (-1.0, 0.0), (56, 26),
          ((0.0, 200.0),), (150, 150, 150)),
    Actor(9, "car", 0.0, (SOUTH_LANE_X, 380.0), (0.0, 1.0), (26, 56),
          ((0.0, 200.0),), (120, 132, 140)),
    # Scene 1 - near miss: eastbound car #1 vs northbound car #2, which brakes.
    Actor(1, "car", 0.4, (-60.0, EAST_LANE_Y), (1.0, 0.0), (56, 26),
          ((0.0, 190.0),), (205, 160, 70)),
    Actor(2, "car", 1.9, (NORTH_LANE_X, 600.0), (0.0, -1.0), (26, 56),
          ((2.85, 170.0), (3.55, 0.0), (4.0, 0.0), (4.6, 200.0)), (90, 200, 245)),
    # Scene 2 - suspected collision: westbound car #3 vs southbound truck #4.
    Actor(3, "car", 4.6, (1020.0, WEST_LANE_Y), (-1.0, 0.0), (56, 26),
          ((7.7, 180.0), (8.05, 0.0)), (80, 95, 225)),
    Actor(4, "truck", 5.85, (SOUTH_LANE_X, -90.0), (0.0, 1.0), (32, 84),
          ((7.7, 150.0), (8.0, 0.0)), (200, 200, 205)),
    # Scene 3 - same-direction following: car #6 closes on slowing car #5.
    Actor(5, "car", 8.0, (-60.0, EAST_LANE_Y), (1.0, 0.0), (56, 26),
          ((9.3, 160.0), (9.8, 40.0), (11.0, 40.0), (11.8, 160.0)), (120, 190, 120)),
    Actor(6, "car", 9.0, (-60.0, EAST_LANE_Y), (1.0, 0.0), (56, 26),
          ((10.0, 170.0), (10.45, 40.0)), (210, 140, 190)),
    # Pedestrians are tracked and drawn; default analysis is vehicle-to-vehicle.
    Actor(7, "person", 0.8, (378.0, 150.0), (0.0, 1.0), (14, 22),
          ((0.0, 42.0),), (230, 230, 230), 7.2),
    Actor(8, "person", 7.6, (582.0, 392.0), (0.0, -1.0), (14, 22),
          ((0.0, 40.0),), (230, 230, 230)),
)


# What was *staged*. The UI shows this next to what the detectors actually
# returned, so a viewer can check the pipeline rather than trust a caption.
DEMO_SCENES = (
    {"window": "0–5 s", "scene": "Near miss",
     "staged": "Eastbound car #1 crosses while northbound car #2 approaches, brakes hard, "
               "and stops short of its path. No contact."},
    {"window": "5–8 s", "scene": "Collision candidate",
     "staged": "Westbound car #3 and southbound truck #4 converge, their boxes overlap, "
               "and both stop abruptly."},
    {"window": "8–12 s", "scene": "Same-direction following",
     "staged": "Car #6 closes on car #5 after #5 slows, then brakes and stops behind it. No contact."},
    {"window": "throughout", "scene": "Pedestrians",
     "staged": "Pedestrians #7 and #8 use two crosswalks. They are tracked but only analyzed when "
               "the prediction mode includes pedestrians."},
)


def scenario_spec() -> dict[str, Any]:
    return {
        "version": DEMO_VERSION,
        "frame": [WIDTH, HEIGHT, FPS, DURATION_SECONDS],
        "actors": [asdict(actor) for actor in ACTORS],
    }


def _scenario_digest() -> str:
    encoded = json.dumps(scenario_spec(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


DEMO_VIDEO_ID = DEMO_ID_PREFIX + _scenario_digest()


def is_demo_video_id(video_id: str | None) -> bool:
    """Real uploads use 64-hex SHA-256 IDs, which can never carry this prefix."""

    return str(video_id or "").startswith(DEMO_ID_PREFIX)


def provenance_for(
    video_id: str | None, tracking_config: TrackingConfig | None = None, tracks_path: Path | None = None
) -> dict[str, Any]:
    """Source provenance. For the real sample, ``tracking_config`` and ``tracks_path``
    describe the rows actually in use (see ``real_demo.real_provenance``)."""

    if is_demo_video_id(video_id):
        return dict(DEMO_PROVENANCE)
    # Imported here: nearmiss.real_demo depends on the same video/store modules.
    from nearmiss import real_demo

    if real_demo.is_real_demo_video_id(video_id):
        return real_demo.real_provenance(tracking_config=tracking_config, tracks_path=tracks_path)
    return dict(UPLOAD_PROVENANCE)


def _speed(actor: Actor, timestamp: float) -> float:
    knots = actor.speed_knots
    if timestamp <= knots[0][0]:
        return knots[0][1]
    for (t0, v0), (t1, v1) in zip(knots, knots[1:]):
        if timestamp <= t1:
            return v0 + (v1 - v0) * (timestamp - t0) / max(t1 - t0, 1e-9)
    return knots[-1][1]


def _distance(actor: Actor, timestamp: float) -> float:
    """Exact integral of the piecewise-linear speed profile from start_time."""

    if timestamp <= actor.start_time:
        return 0.0
    breakpoints = sorted(
        {actor.start_time, timestamp}
        | {t for t, _ in actor.speed_knots if actor.start_time < t < timestamp}
    )
    return float(
        sum(
            0.5 * (_speed(actor, a) + _speed(actor, b)) * (b - a)
            for a, b in zip(breakpoints, breakpoints[1:])
        )
    )


def actor_center(actor: Actor, timestamp: float) -> tuple[float, float]:
    travelled = _distance(actor, timestamp)
    return (
        actor.start_center[0] + actor.direction[0] * travelled,
        actor.start_center[1] + actor.direction[1] * travelled,
    )


def _bbox(actor: Actor, center: tuple[float, float]) -> list[float]:
    half_w, half_h = actor.size[0] / 2.0, actor.size[1] / 2.0
    return [center[0] - half_w, center[1] - half_h, center[0] + half_w, center[1] + half_h]


def frame_count() -> int:
    return int(round(DURATION_SECONDS * FPS))


def synthetic_tracks() -> list[dict[str, Any]]:
    """Deterministic scripted track rows in the standard NearMiss schema.

    A row exists only while the whole box is inside the frame, mimicking a
    detector that cannot report objects before they are visible.
    """

    rows: list[dict[str, Any]] = []
    for frame_index in range(frame_count()):
        timestamp = round(frame_index / FPS, 6)
        for actor in ACTORS:
            if not (actor.start_time <= timestamp <= actor.end_time):
                continue
            box = _bbox(actor, actor_center(actor, timestamp))
            if box[0] < 0 or box[1] < 0 or box[2] > WIDTH - 1 or box[3] > HEIGHT - 1:
                continue
            x1, y1, x2, y2 = (round(value, 2) for value in box)
            rows.append(
                {
                    "track_id": actor.track_id,
                    "class_id": CLASS_IDS[actor.class_name],
                    "class_name": actor.class_name,
                    "object_type": OBJECT_TYPES[actor.class_name],
                    "frame_index": frame_index,
                    "timestamp_seconds": timestamp,
                    "bbox": [x1, y1, x2, y2],
                    "center": [round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2)],
                    "confidence": 1.0,
                    "data_source": DEMO_DATA_SOURCE,
                }
            )
    return rows


# ---------------------------------------------------------------- rendering

AMBER = (59, 169, 242)  # BGR for #F2A93B
INK = (16, 14, 12)


def _scene_background() -> np.ndarray:
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:] = (30, 36, 32)  # dark blocks
    # Building footprints in each corner block.
    for x1, y1, x2, y2 in (
        (30, 24, 330, 150), (630, 24, 930, 150), (30, 390, 330, 516), (630, 390, 930, 516)
    ):
        cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 46, 44), -1)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (58, 64, 62), 1, cv2.LINE_AA)
    # Sidewalks.
    cv2.rectangle(frame, (0, ROAD_H[0] - 22), (WIDTH, ROAD_H[1] + 22), (70, 74, 76), -1)
    cv2.rectangle(frame, (ROAD_V[0] - 22, 0), (ROAD_V[1] + 22, HEIGHT), (70, 74, 76), -1)
    # Asphalt.
    asphalt = (44, 42, 40)
    cv2.rectangle(frame, (0, ROAD_H[0]), (WIDTH, ROAD_H[1]), asphalt, -1)
    cv2.rectangle(frame, (ROAD_V[0], 0), (ROAD_V[1], HEIGHT), asphalt, -1)
    # Center lines (double amber) outside the box junction.
    center_y = (ROAD_H[0] + ROAD_H[1]) // 2
    center_x = (ROAD_V[0] + ROAD_V[1]) // 2
    line = (40, 150, 215)
    for offset in (-3, 3):
        cv2.line(frame, (0, center_y + offset), (ROAD_V[0] - 46, center_y + offset), line, 2)
        cv2.line(frame, (ROAD_V[1] + 46, center_y + offset), (WIDTH, center_y + offset), line, 2)
        cv2.line(frame, (center_x + offset, 0), (center_x + offset, ROAD_H[0] - 46), line, 2)
        cv2.line(frame, (center_x + offset, ROAD_H[1] + 46), (center_x + offset, HEIGHT), line, 2)
    # Crosswalk stripes on all four legs.
    stripe = (205, 205, 200)
    for y in range(ROAD_H[0] + 6, ROAD_H[1] - 4, 16):
        cv2.rectangle(frame, (ROAD_V[0] - 40, y), (ROAD_V[0] - 12, y + 8), stripe, -1)
        cv2.rectangle(frame, (ROAD_V[1] + 12, y), (ROAD_V[1] + 40, y + 8), stripe, -1)
    for x in range(ROAD_V[0] + 6, ROAD_V[1] - 4, 16):
        cv2.rectangle(frame, (x, ROAD_H[0] - 40), (x + 8, ROAD_H[0] - 12), stripe, -1)
        cv2.rectangle(frame, (x, ROAD_H[1] + 12), (x + 8, ROAD_H[1] + 40), stripe, -1)
    # Stop bars for approaching lanes.
    cv2.line(frame, (ROAD_V[0] - 46, center_y + 6), (ROAD_V[0] - 46, ROAD_H[1]), stripe, 3)
    cv2.line(frame, (ROAD_V[1] + 46, ROAD_H[0]), (ROAD_V[1] + 46, center_y - 6), stripe, 3)
    cv2.line(frame, (ROAD_V[0], ROAD_H[0] - 46), (center_x - 6, ROAD_H[0] - 46), stripe, 3)
    cv2.line(frame, (center_x + 6, ROAD_H[1] + 46), (ROAD_V[1], ROAD_H[1] + 46), stripe, 3)
    # Signal heads at the four corners.
    for x, y in ((ROAD_V[0] - 30, ROAD_H[0] - 30), (ROAD_V[1] + 18, ROAD_H[0] - 30),
                 (ROAD_V[0] - 30, ROAD_H[1] + 18), (ROAD_V[1] + 18, ROAD_H[1] + 18)):
        cv2.rectangle(frame, (x, y), (x + 12, y + 12), (20, 20, 20), -1)
        cv2.circle(frame, (x + 6, y + 6), 3, AMBER, -1, cv2.LINE_AA)
    return frame


def _draw_actor(frame: np.ndarray, actor: Actor, center: tuple[float, float]) -> None:
    x1, y1, x2, y2 = (int(round(value)) for value in _bbox(actor, center))
    if actor.class_name == "person":
        cx, cy = int(round(center[0])), int(round(center[1]))
        cv2.ellipse(frame, (cx, cy + 3), (6, 8), 0, 0, 360, (150, 150, 150), -1, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy - 5), 5, actor.color_bgr, -1, cv2.LINE_AA)
        return
    cv2.rectangle(frame, (x1, y1), (x2, y2), actor.color_bgr, -1, cv2.LINE_AA)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (25, 25, 25), 1, cv2.LINE_AA)
    dx, dy = actor.direction
    # Windshield toward the direction of travel.
    if abs(dx) > abs(dy):
        front = x2 - 16 if dx > 0 else x1 + 6
        cv2.rectangle(frame, (front, y1 + 4), (front + 10, y2 - 4), (45, 40, 35), -1)
    else:
        front = y2 - 16 if dy > 0 else y1 + 6
        cv2.rectangle(frame, (x1 + 4, front), (x2 - 4, front + 10), (45, 40, 35), -1)
    if actor.class_name == "truck":
        split = y1 + 24 if dy > 0 else y2 - 24
        cv2.line(frame, (x1 + 2, split), (x2 - 2, split), (90, 90, 90), 2)


def _draw_labels(frame: np.ndarray, timestamp: float) -> None:
    # Bottom-right pill stays clear of the annotated renderer's left-side text.
    cv2.rectangle(frame, (WIDTH - 238, HEIGHT - 46), (WIDTH - 14, HEIGHT - 14), AMBER, -1)
    cv2.putText(frame, DEMO_LABEL, (WIDTH - 226, HEIGHT - 23), cv2.FONT_HERSHEY_DUPLEX,
                0.7, INK, 1, cv2.LINE_AA)
    cv2.putText(frame, "Generated illustration - not real footage", (WIDTH - 330, HEIGHT - 56),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (225, 225, 225), 1, cv2.LINE_AA)
    cv2.putText(frame, f"{DEMO_LABEL}  t={timestamp:05.2f}s", (WIDTH - 250, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, AMBER, 1, cv2.LINE_AA)


def render_demo_frame(frame_index: int, background: np.ndarray | None = None) -> np.ndarray:
    timestamp = frame_index / FPS
    frame = (background if background is not None else _scene_background()).copy()
    for actor in sorted(ACTORS, key=lambda item: item.class_name != "person"):
        if actor.start_time <= timestamp <= actor.end_time:
            _draw_actor(frame, actor, actor_center(actor, timestamp))
    _draw_labels(frame, timestamp)
    return frame


# ------------------------------------------------------------ cache artifacts


def demo_directory() -> Path:
    return video_module.CACHE_ROOT / DEMO_VIDEO_ID


def demo_metadata() -> VideoMetadata:
    return VideoMetadata(
        fps=FPS,
        frame_count=frame_count(),
        width=WIDTH,
        height=HEIGHT,
        duration_seconds=frame_count() / FPS,
    )


def ensure_demo_assets() -> tuple[Path, AnalysisArtifacts]:
    """Generate (or reuse) the demo MP4 and its scripted track artifacts.

    Files follow the standard cache layout:
    ``CACHE_ROOT/<video id>/source.mp4`` and
    ``CACHE_ROOT/<video id>/<analysis key>/{tracks,metadata}.json``.
    """

    directory = demo_directory()
    directory.mkdir(parents=True, exist_ok=True)
    source_path = directory / "source.mp4"
    metadata = demo_metadata()
    if not source_path.exists() or source_path.stat().st_size == 0:
        raw_path = directory / "source_raw.mp4"
        writer = cv2.VideoWriter(
            str(raw_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)
        )
        if not writer.isOpened():
            raise VideoError("OpenCV could not create the synthetic demo video.")
        background = _scene_background()
        try:
            for frame_index in range(frame_count()):
                writer.write(render_demo_frame(frame_index, background))
        finally:
            writer.release()
        transcode_for_browser(raw_path, source_path)
    (directory / "provenance.json").write_text(
        json.dumps({**DEMO_PROVENANCE, "video_id": DEMO_VIDEO_ID}, indent=2), encoding="utf-8"
    )

    artifacts = _artifact_paths(DEMO_VIDEO_ID, source_path, DEMO_TRACKING_CONFIG, metadata)
    if not (artifacts.tracks_path.exists() and artifacts.metadata_path.exists()):
        artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
        artifacts.tracks_path.write_text(json.dumps(synthetic_tracks(), indent=2), encoding="utf-8")
        artifacts.metadata_path.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")
    return source_path, artifacts


def demo_active_video() -> dict[str, Any]:
    """Session record for the demo, matching the shape used for uploads."""

    source_path, _artifacts = ensure_demo_assets()
    return {
        "name": DEMO_FILENAME,
        "video_hash": DEMO_VIDEO_ID,
        "source_path": str(source_path),
        "synthetic": True,
    }


def reset_demo_reviews(
    video_id: str, database_path: Path | str | None = None
) -> tuple[int, int]:
    """Clear reviews/notifications for the synthetic demo only."""

    if not is_demo_video_id(video_id):
        raise ValueError("Only the synthetic demonstration can be reset.")
    return delete_video_records(video_id, database_path)
