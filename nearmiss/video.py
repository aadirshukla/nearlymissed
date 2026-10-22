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


def _render_key(zone: list[list[float]], trail_length: int) -> str:
    encoded = json.dumps(
        {
            "renderer_version": 2,
            "zone": zone,
            "trail_length": trail_length,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def render_annotated_video(
    artifacts: AnalysisArtifacts,
    tracks: list[dict],
    zone: list[list[float]],
    trail_length: int = 30,
    progress: Callable[[float, str], None] | None = None,
) -> Path:
    """Fast second pass that draws boxes, IDs, trajectories, and the zone."""

    render_key = _render_key(zone, trail_length)
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
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if zone_array is not None:
                overlay = frame.copy()
                cv2.fillPoly(overlay, [zone_array], (56, 189, 248))
                cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
                cv2.polylines(frame, [zone_array], True, (56, 189, 248), 2)

            for record in by_frame.get(frame_index, []):
                track_id = int(record["track_id"])
                x1, y1, x2, y2 = (int(value) for value in record["bbox"])
                center = tuple(int(value) for value in record["center"])
                is_person = record["object_type"] == "pedestrian"
                color = (94, 234, 212) if is_person else (251, 146, 60)
                trails[track_id].append(center)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f'{record["class_name"]}  #{track_id}'
                cv2.rectangle(frame, (x1, max(0, y1 - 24)), (x1 + 10 + 9 * len(label), y1), color, -1)
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
                if len(points) >= 2:
                    cv2.polylines(frame, [points], False, color, 2)

            cv2.putText(
                frame,
                "POTENTIAL CONFLICT ANALYSIS - NOT ACCIDENT VERIFICATION",
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
            str(raw_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output_path),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, timeout=600)
        if completed.returncode != 0:
            shutil.copyfile(raw_path, output_path)
    else:
        shutil.copyfile(raw_path, output_path)
    raw_path.unlink(missing_ok=True)

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

