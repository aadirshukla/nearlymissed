"""Video validation, YOLO/ByteTrack analysis, annotation, and cache handling."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from nearmiss import __version__
from nearmiss.config import (
    COCO_CLASS_NAMES,
    TRACKED_CLASS_IDS,
    TrackingConfig,
    object_type_for_class,
)


CACHE_ROOT = Path(".nearmiss_cache")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class VideoError(RuntimeError):
    """Raised when a video cannot be validated or processed."""


def cache_summary() -> tuple[int, int]:
    """Return cached video count and bytes, excluding reusable model settings."""

    if not CACHE_ROOT.exists():
        return 0, 0
    video_directories = [
        path for path in CACHE_ROOT.iterdir() if path.is_dir() and path.name != "ultralytics"
    ]
    total_bytes = sum(
        path.stat().st_size
        for directory in video_directories
        for path in directory.rglob("*")
        if path.is_file()
    )
    return len(video_directories), total_bytes


def clear_analysis_cache() -> tuple[int, int]:
    """Remove all cached uploads, tracks, and annotated videos.

    Ultralytics settings/model downloads are preserved so clearing results does
    not force another model download. Returns removed video count and bytes.
    """

    video_count, total_bytes = cache_summary()
    if not CACHE_ROOT.exists():
        return video_count, total_bytes
    root = CACHE_ROOT.resolve()
    for target in CACHE_ROOT.iterdir():
        if not target.is_dir() or target.name == "ultralytics":
            continue
        resolved = target.resolve()
        if resolved.parent != root:
            raise VideoError("Refusing to clear a cache path outside the NearMiss cache root.")
        shutil.rmtree(resolved)
    return video_count, total_bytes


@dataclass(frozen=True)
class VideoMetadata:
    fps: float
    frame_count: int
    width: int
    height: int
    duration_seconds: float


@dataclass(frozen=True)
class AnalysisArtifacts:
    cache_dir: Path
    source_path: Path
    tracks_path: Path
    metadata_path: Path
    metadata: VideoMetadata


def video_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload(data: bytes, filename: str) -> None:
    """Perform quick, friendly validation before OpenCV reads the upload."""

    if not data:
        raise VideoError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise VideoError("The video is larger than the 500 MB prototype limit.")
    if not filename.lower().endswith(".mp4"):
        raise VideoError("Please upload an MP4 video.")
    if b"ftyp" not in data[:64]:
        raise VideoError("This file does not appear to be a valid MP4 container.")


def save_upload(data: bytes, filename: str) -> tuple[str, Path]:
    """Validate and save an uploaded video in the content-addressed cache."""

    validate_upload(data, filename)
    digest = video_digest(data)
    source_dir = CACHE_ROOT / digest
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "source.mp4"
    if not source_path.exists() or source_path.stat().st_size != len(data):
        source_path.write_bytes(data)
    return digest, source_path


def inspect_video(path: Path) -> tuple[VideoMetadata, np.ndarray]:
    """Read metadata and the first frame, rejecting undecodable uploads."""

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise VideoError("OpenCV could not open this MP4. Try re-encoding it as H.264.")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ok, frame = capture.read()
    finally:
        capture.release()

    if not ok or frame is None or width <= 0 or height <= 0:
        raise VideoError("The MP4 has no readable video frames.")
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0
    if frame_count <= 0:
        frame_count = 1
    metadata = VideoMetadata(
        fps=fps,
        frame_count=frame_count,
        width=width,
        height=height,
        duration_seconds=frame_count / fps,
    )
    return metadata, frame


def frame_at_timestamp(path: Path, timestamp_seconds: float) -> np.ndarray:
    """Read one actual BGR frame at or immediately after a video timestamp."""

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise VideoError("OpenCV could not open the source video for evidence review.")
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp_seconds)) * 1000.0)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        raise VideoError("The requested evidence frame could not be decoded.")
    return frame


def annotate_incident_frame(frame_bgr: np.ndarray, incident: dict) -> np.ndarray:
    """Draw one suspected-collision evidence record on an actual source frame."""

    frame = frame_bgr.copy()
    color = (20, 20, 255)
    for prefix in ("vehicle_a", "vehicle_b"):
        bbox = incident.get(f"{prefix}_bbox")
        track_id = incident.get(f"{prefix}_track_id", "?")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = (int(float(value)) for value in bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
        cv2.putText(
            frame,
            f"V#{track_id}",
            (x1 + 4, max(18, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )
    point = incident.get("contact_point")
    if isinstance(point, (list, tuple)) and len(point) == 2:
        contact = tuple(int(float(value)) for value in point)
        cv2.circle(frame, contact, 20, color, 3, cv2.LINE_AA)
        cv2.drawMarker(frame, contact, color, cv2.MARKER_CROSS, 30, 4)
    banner = (
        f'SUSPECTED COLLISION  {float(incident.get("timestamp_seconds", 0.0)):.2f}s  '
        f'evidence={int(incident.get("evidence_signal_count", 0))}'
    )
    cv2.rectangle(frame, (0, 0), (min(frame.shape[1], 560), 38), (15, 23, 42), -1)
    cv2.putText(
        frame,
        banner,
        (12, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        color,
        2,
        cv2.LINE_AA,
    )
    return frame


def transcode_for_browser(raw: Path, output: Path) -> Path:
    """Re-encode an OpenCV mp4v file as browser-playable H.264, then remove it.

    Falls back to copying the raw file when no ffmpeg binary is available.
    """

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError, OSError):
            ffmpeg = None
    if ffmpeg:
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, timeout=600)
        if completed.returncode != 0:
            shutil.copyfile(raw, output)
    else:
        shutil.copyfile(raw, output)
    raw.unlink(missing_ok=True)
    return output


def extract_event_clip(
    artifacts: AnalysisArtifacts,
    event_id: str,
    timestamp_seconds: float,
    before_seconds: float = 2.0,
    after_seconds: float = 2.0,
) -> Path:
    """Create a cached source-footage excerpt around a detector alert."""

    start = max(0.0, float(timestamp_seconds) - max(0.0, before_seconds))
    end = min(
        artifacts.metadata.duration_seconds,
        float(timestamp_seconds) + max(0.0, after_seconds),
    )
    safe_id = "".join(character for character in str(event_id) if character.isalnum() or character in "-_")
    digest = hashlib.sha256(f"{safe_id}:{start:.3f}:{end:.3f}".encode()).hexdigest()[:10]
    output = artifacts.cache_dir / f"evidence_{safe_id}_{digest}.mp4"
    if output.exists() and output.stat().st_size > 0:
        return output

    raw = artifacts.cache_dir / f"evidence_{safe_id}_{digest}_raw.mp4"
    capture = cv2.VideoCapture(str(artifacts.source_path))
    capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    writer = cv2.VideoWriter(
        str(raw),
        cv2.VideoWriter_fourcc(*"mp4v"),
        artifacts.metadata.fps,
        (artifacts.metadata.width, artifacts.metadata.height),
    )
    if not writer.isOpened():
        capture.release()
        raise VideoError("OpenCV could not create the event evidence clip.")
    try:
        while True:
            position = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if position > end:
                break
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
    finally:
        capture.release()
        writer.release()

    transcode_for_browser(raw, output)
    return output


def _analysis_key(video_hash: str, config: TrackingConfig) -> str:
    # Trail length affects drawing only, not YOLO or ByteTrack output. Excluding
    # it here lets users restyle trajectories without rerunning inference.
    payload = {
        "pipeline_version": __version__,
        "video_hash": video_hash,
        "tracking": {
            "model_name": config.model_name,
            "confidence": config.confidence,
            "iou_threshold": config.iou_threshold,
            "device": config.device,
        },
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _artifact_paths(
    video_hash: str, source_path: Path, config: TrackingConfig, metadata: VideoMetadata
) -> AnalysisArtifacts:
    cache_dir = CACHE_ROOT / video_hash / _analysis_key(video_hash, config)
    return AnalysisArtifacts(
        cache_dir=cache_dir,
        source_path=source_path,
        tracks_path=cache_dir / "tracks.json",
        metadata_path=cache_dir / "metadata.json",
        metadata=metadata,
    )


def cached_analysis(
    video_hash: str, source_path: Path, config: TrackingConfig, metadata: VideoMetadata
) -> AnalysisArtifacts | None:
    artifacts = _artifact_paths(video_hash, source_path, config, metadata)
    if artifacts.tracks_path.exists() and artifacts.metadata_path.exists():
        return artifacts
    return None


def analyze_video(
    video_hash: str,
    source_path: Path,
    config: TrackingConfig,
    progress: Callable[[float, str], None] | None = None,
) -> AnalysisArtifacts:
    """Run YOLO detection with persistent ByteTrack IDs and cache track rows."""

    metadata, _ = inspect_video(source_path)
    artifacts = _artifact_paths(video_hash, source_path, config, metadata)
    cached = cached_analysis(video_hash, source_path, config, metadata)
    if cached:
        if progress:
            progress(1.0, "Loaded cached tracking results")
        return cached

    try:
        ultralytics_config = (CACHE_ROOT / "ultralytics").resolve()
        ultralytics_config.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("YOLO_CONFIG_DIR", str(ultralytics_config))
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise VideoError(
            "Ultralytics is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    artifacts.cache_dir.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(0.01, f"Loading {config.model_name}")

    try:
        model = YOLO(config.model_name)
    except Exception as exc:  # model download errors vary by platform
        raise VideoError(
            f"Could not load {config.model_name}. The first run needs internet access "
            "to download the pretrained weights."
        ) from exc

    capture = cv2.VideoCapture(str(source_path))
    records: list[dict[str, Any]] = []
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            try:
                results = model.track(
                    source=frame,
                    persist=True,
                    tracker="bytetrack.yaml",
                    classes=TRACKED_CLASS_IDS,
                    conf=config.confidence,
                    iou=config.iou_threshold,
                    device=config.device,
                    verbose=False,
                )
            except Exception as exc:
                raise VideoError(f"YOLO tracking failed at frame {frame_index}: {exc}") from exc

            result = results[0] if results else None
            boxes = getattr(result, "boxes", None)
            if boxes is not None and boxes.id is not None:
                xyxy = boxes.xyxy.detach().cpu().numpy()
                track_ids = boxes.id.detach().cpu().numpy().astype(int)
                class_ids = boxes.cls.detach().cpu().numpy().astype(int)
                confidences = boxes.conf.detach().cpu().numpy()
                for bbox, track_id, class_id, confidence in zip(
                    xyxy, track_ids, class_ids, confidences, strict=True
                ):
                    x1, y1, x2, y2 = (float(value) for value in bbox)
                    records.append(
                        {
                            "track_id": int(track_id),
                            "class_id": int(class_id),
                            "class_name": COCO_CLASS_NAMES.get(
                                int(class_id), str(int(class_id))
                            ),
                            "object_type": object_type_for_class(int(class_id)),
                            "frame_index": frame_index,
                            "timestamp_seconds": round(frame_index / metadata.fps, 6),
                            "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                            "center": [round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2)],
                            "confidence": round(float(confidence), 5),
                        }
                    )

            frame_index += 1
            if progress and (frame_index == 1 or frame_index % 5 == 0):
                fraction = min(frame_index / max(metadata.frame_count, 1), 0.99)
                progress(fraction, f"Tracking frame {frame_index:,} of {metadata.frame_count:,}")
    finally:
        capture.release()

    if frame_index == 0:
        raise VideoError("The video stopped decoding before the first frame.")

    actual_metadata = VideoMetadata(
        fps=metadata.fps,
        frame_count=frame_index,
        width=metadata.width,
        height=metadata.height,
        duration_seconds=frame_index / metadata.fps,
    )
    artifacts.tracks_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    artifacts.metadata_path.write_text(
        json.dumps(asdict(actual_metadata), indent=2), encoding="utf-8"
    )
    artifacts = AnalysisArtifacts(
        cache_dir=artifacts.cache_dir,
        source_path=source_path,
        tracks_path=artifacts.tracks_path,
        metadata_path=artifacts.metadata_path,
        metadata=actual_metadata,
    )
    if progress:
        progress(1.0, f"Tracked {frame_index:,} frames")
    return artifacts


def load_artifacts(artifacts: AnalysisArtifacts) -> tuple[list[dict], VideoMetadata]:
    tracks = json.loads(artifacts.tracks_path.read_text(encoding="utf-8"))
    raw_metadata = json.loads(artifacts.metadata_path.read_text(encoding="utf-8"))
    return tracks, VideoMetadata(**raw_metadata)


def _render_key(
    zone: list[list[float]],
    trail_length: int,
    events: list[dict] | None = None,
    incidents: list[dict] | None = None,
    show_boxes: bool = True,
    show_trajectories: bool = True,
    show_track_ids: bool = True,
) -> str:
    encoded = json.dumps(
        {
            "renderer_version": 11,
            "zone": zone,
            "trail_length": trail_length,
            "events": events or [],
            "incidents": incidents or [],
            "show_boxes": show_boxes,
            "show_trajectories": show_trajectories,
            "show_track_ids": show_track_ids,
        },
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def render_annotated_video(
    artifacts: AnalysisArtifacts,
    tracks: list[dict],
    zone: list[list[float]],
    trail_length: int = 30,
    progress: Callable[[float, str], None] | None = None,
    events: list[dict] | None = None,
    incidents: list[dict] | None = None,
    show_boxes: bool = True,
    show_trajectories: bool = True,
    show_track_ids: bool = True,
) -> Path:
    """Draw tracks, predictions, suspected incidents, and the selected zone."""

    events = events or []
    incidents = incidents or []
    render_key = _render_key(
        zone,
        trail_length,
        events,
        incidents,
        show_boxes,
        show_trajectories,
        show_track_ids,
    )
    output_path = artifacts.cache_dir / f"annotated_{render_key}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        if progress:
            progress(1.0, "Loaded cached annotated video")
        return output_path

    by_frame: dict[int, list[dict]] = defaultdict(list)
    for record in tracks:
        by_frame[int(record["frame_index"])].append(record)

    capture = cv2.VideoCapture(str(artifacts.source_path))
    raw_path = artifacts.cache_dir / f"annotated_{render_key}_raw.mp4"
    writer = cv2.VideoWriter(
        str(raw_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        artifacts.metadata.fps,
        (artifacts.metadata.width, artifacts.metadata.height),
    )
    if not writer.isOpened():
        capture.release()
        raise VideoError("OpenCV could not create the annotated MP4.")

    trails: dict[int, deque[tuple[int, int]]] = defaultdict(
        lambda: deque(maxlen=trail_length)
    )
    frame_index = 0
    zone_array = np.asarray(zone, dtype=np.int32) if len(zone) >= 3 else None
    severity_colors = {
        "HIGH": (94, 63, 244),
        "MEDIUM": (60, 146, 251),
        "LOW": (21, 204, 250),
    }
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if zone_array is not None:
                overlay = frame.copy()
                cv2.fillPoly(overlay, [zone_array], (248, 189, 56))
                cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
                cv2.polylines(frame, [zone_array], True, (248, 189, 56), 2)

            frame_records = by_frame.get(frame_index, [])
            visible_track_ids = {int(record["track_id"]) for record in frame_records}

            active_events: list[dict] = []
            for event in events:
                event_frame = int(event.get("frame_index", 0))
                start_frame = int(event.get("start_frame_index", event_frame))
                end_frame = int(event.get("end_frame_index", event_frame))
                padding = max(1, int(round(0.35 * artifacts.metadata.fps)))
                if start_frame <= frame_index <= end_frame + padding:
                    active_events.append(event)

            active_events.sort(
                key=lambda item: (
                    {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(
                        str(item.get("severity", "LOW")).upper(), 0
                    ),
                    float(item.get("risk_score", 0.0)),
                ),
                reverse=True,
            )
            hidden_active_count = max(0, len(active_events) - 3)
            active_events = active_events[:3]
            highlighted_ids: dict[int, dict] = {}
            for event_number, event in enumerate(active_events):
                severity = str(event.get("severity", "LOW")).upper()
                color = severity_colors.get(severity, severity_colors["LOW"])
                first_start = event.get("participant_a_position") or event.get("vehicle_position")
                first_end = (
                    event.get("participant_a_conflict_position")
                    or event.get("participant_a_predicted_end")
                    or event.get("vehicle_predicted_end")
                )
                second_start = event.get("participant_b_position") or event.get("pedestrian_position")
                second_end = (
                    event.get("participant_b_conflict_position")
                    or event.get("participant_b_predicted_end")
                    or event.get("pedestrian_predicted_end")
                )
                conflict_point = event.get("conflict_point")
                first_path_color = (255, 210, 80)
                second_path_color = (210, 90, 255)
                if show_trajectories and first_start and first_end:
                    cv2.arrowedLine(
                        frame,
                        tuple(int(value) for value in first_start),
                        tuple(int(value) for value in first_end),
                        first_path_color,
                        3,
                        cv2.LINE_AA,
                        tipLength=0.08,
                    )
                if show_trajectories and second_start and second_end:
                    cv2.arrowedLine(
                        frame,
                        tuple(int(value) for value in second_start),
                        tuple(int(value) for value in second_end),
                        second_path_color,
                        3,
                        cv2.LINE_AA,
                        tipLength=0.08,
                    )
                if conflict_point:
                    point = tuple(int(value) for value in conflict_point)
                    region_radius = int(
                        min(60, max(8, float(event.get("conflict_region_radius_pixels", 12.0))))
                    )
                    cv2.circle(frame, point, region_radius, color, 2, cv2.LINE_AA)
                    cv2.drawMarker(
                        frame,
                        point,
                        color,
                        markerType=cv2.MARKER_TILTED_CROSS,
                        markerSize=24,
                        thickness=4,
                    )
                first_ids = event.get("participant_a_track_ids") or event.get("vehicle_track_ids") or [
                    event.get("participant_a_track_id", event.get("vehicle_track_id"))
                ]
                second_ids = event.get("participant_b_track_ids") or event.get("pedestrian_track_ids") or [
                    event.get("participant_b_track_id", event.get("pedestrian_track_id"))
                ]
                for track_id in first_ids + second_ids:
                    if track_id is not None:
                        highlighted_ids.setdefault(int(track_id), event)

                # If ByteTrack misses one alert participant briefly, retain a
                # clearly labelled last-known box instead of making the second
                # vehicle disappear from the warning.
                for track_id, bbox, box_color in (
                    (
                        event.get("participant_a_track_id"),
                        event.get("participant_a_bbox"),
                        first_path_color,
                    ),
                    (
                        event.get("participant_b_track_id"),
                        event.get("participant_b_bbox"),
                        second_path_color,
                    ),
                ):
                    if (
                        not show_boxes
                        or track_id is None
                        or not bbox
                        or int(track_id) in visible_track_ids
                    ):
                        continue
                    x1, y1, x2, y2 = (int(value) for value in bbox)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                    cv2.putText(
                        frame,
                        f"#{int(track_id)}",
                        (x1, min(artifacts.metadata.height - 6, y2 + 14)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        box_color,
                        1,
                        cv2.LINE_AA,
                    )

                if event_number < 3:
                    banner_y = 30 + 30 * event_number
                    first_type = str(event.get("participant_a_type", "vehicle"))[:1].upper()
                    second_type = str(event.get("participant_b_type", "pedestrian"))[:1].upper()
                    first_id = event.get("participant_a_track_id", event.get("vehicle_track_id", "?"))
                    second_id = event.get("participant_b_track_id", event.get("pedestrian_track_id", "?"))
                    banner = (
                        f'{severity}  alert={float(event.get("first_alert_timestamp_seconds", 0.0)):.1f}s  '
                        f'{first_type}#{first_id}  '
                        f'{second_type}#{second_id}  '
                        f'TTC={float(event.get("time_to_conflict_seconds", 0.0)):.2f}s  '
                        f'gap={float(event.get("arrival_time_gap_seconds", 0.0)):.2f}s  '
                    )
                    cv2.putText(
                        frame,
                        banner,
                        (16, banner_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        color,
                        2,
                        cv2.LINE_AA,
                    )
            if hidden_active_count:
                cv2.putText(
                    frame,
                    f"+{hidden_active_count} lower-ranked active flags hidden",
                    (16, 124),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

            active_incidents: list[dict] = []
            for incident in incidents:
                start_frame = int(incident.get("frame_index", 0))
                end_frame = int(incident.get("end_frame_index", start_frame))
                padding = max(1, int(round(0.75 * artifacts.metadata.fps)))
                if start_frame <= frame_index <= end_frame + padding:
                    active_incidents.append(incident)
            active_incidents = sorted(
                active_incidents,
                key=lambda item: int(item.get("evidence_signal_count", 0)),
                reverse=True,
            )[:2]
            incident_highlighted_ids: dict[int, dict] = {}
            for incident_number, incident in enumerate(active_incidents):
                for key in ("vehicle_a_track_id", "vehicle_b_track_id"):
                    if incident.get(key) is not None:
                        incident_highlighted_ids[int(incident[key])] = incident
                point = incident.get("contact_point")
                if point:
                    contact_point = tuple(int(value) for value in point)
                    cv2.circle(frame, contact_point, 18, (20, 20, 255), 3, cv2.LINE_AA)
                    cv2.drawMarker(
                        frame,
                        contact_point,
                        (20, 20, 255),
                        cv2.MARKER_CROSS,
                        28,
                        4,
                    )
                banner_y = 30 + 30 * (len(active_events) + incident_number)
                banner = (
                    f'SUSPECTED COLLISION  V#{incident.get("vehicle_a_track_id", "?")} / '
                    f'V#{incident.get("vehicle_b_track_id", "?")}  '
                    f't={float(incident.get("timestamp_seconds", 0.0)):.2f}s  '
                    f'evidence={int(incident.get("evidence_signal_count", 0))}'
                )
                cv2.putText(
                    frame,
                    banner,
                    (16, banner_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.62,
                    (20, 20, 255),
                    2,
                    cv2.LINE_AA,
                )

            for record in frame_records:
                track_id = int(record["track_id"])
                x1, y1, x2, y2 = (int(value) for value in record["bbox"])
                center = (int((x1 + x2) / 2), y2)
                is_person = record["object_type"] == "pedestrian"
                if active_events or active_incidents:
                    color = (82, 91, 108)
                else:
                    color = (191, 212, 45) if is_person else (60, 146, 251)
                highlighted_event = highlighted_ids.get(track_id)
                highlighted_incident = incident_highlighted_ids.get(track_id)
                thickness = 1 if active_events or active_incidents else 2
                if highlighted_event:
                    severity = str(highlighted_event.get("severity", "LOW")).upper()
                    color = severity_colors.get(severity, severity_colors["LOW"])
                    thickness = 4
                if highlighted_incident:
                    color = (20, 20, 255)
                    thickness = 4
                trails[track_id].append(center)
                if show_boxes:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                suffix = (
                    "  SUSPECTED"
                    if highlighted_incident
                    else f'  {str(highlighted_event.get("severity")).upper()}'
                    if highlighted_event
                    else ""
                )
                if show_track_ids:
                    label = f'{record["class_name"]}  #{track_id}{suffix}'
                    cv2.rectangle(
                        frame,
                        (x1, max(0, y1 - 24)),
                        (x1 + 10 + 9 * len(label), y1),
                        color,
                        -1,
                    )
                    cv2.putText(
                        frame,
                        label,
                        (x1 + 5, max(15, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (15, 23, 42),
                        1,
                        cv2.LINE_AA,
                    )
                points = np.asarray(trails[track_id], dtype=np.int32)
                if show_trajectories and len(points) >= 2:
                    cv2.polylines(frame, [points], False, color, 2 if highlighted_event else 1)

            cv2.putText(
                frame,
                "PREDICTION / SUSPECTED INCIDENT - HUMAN REVIEW REQUIRED",
                (16, artifacts.metadata.height - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
            frame_index += 1
            if progress and frame_index % 15 == 0:
                progress(
                    min(frame_index / max(artifacts.metadata.frame_count, 1), 0.99),
                    "Rendering annotated video",
                )
    finally:
        capture.release()
        writer.release()

    transcode_for_browser(raw_path, output_path)

    if progress:
        progress(1.0, "Annotated video ready")
    return output_path


def tracks_to_csv(tracks: list[dict]) -> bytes:
    """Serialize flat track observations for download."""

    fieldnames = [
        "track_id",
        "class_id",
        "class_name",
        "object_type",
        "frame_index",
        "timestamp_seconds",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "center_x",
        "center_y",
        "confidence",
        "in_conflict_zone",
    ]
    if any(isinstance(record, dict) and "data_source" in record for record in tracks):
        # Provenance travels with every row, e.g. scripted synthetic demo tracks.
        fieldnames.append("data_source")
    from io import StringIO

    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    for record in tracks:
        bbox = record.get("bbox", [None] * 4)
        center = record.get("center", [None] * 2)
        writer.writerow(
            {
                **{key: record.get(key) for key in fieldnames},
                "bbox_x1": bbox[0],
                "bbox_y1": bbox[1],
                "bbox_x2": bbox[2],
                "bbox_y2": bbox[3],
                "center_x": center[0],
                "center_y": center[1],
            }
        )
    return stream.getvalue().encode("utf-8")

