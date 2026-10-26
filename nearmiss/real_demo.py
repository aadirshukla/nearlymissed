"""Bundled real-traffic sample: real footage with precomputed actual tracking.

``static/real-demo/`` ships a short, openly licensed clip of real traffic
together with the YOLO + ByteTrack rows NearMiss produced for it
locally at the default tracking settings. Starting the sample validates every
file against ``manifest.json`` (SHA-256 digests, metadata, track schema and
the tracking config) and copies them into the normal cache layout, so the app
opens it instantly and offline with no model load. Prediction, incident
evidence, review and the simulated inbox then run live on those rows.

Nothing here generates, edits or reorders track rows. Missing or altered
files raise :class:`RealDemoError`; there is no fallback to other data.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from nearmiss import video as video_module
from nearmiss.config import COCO_CLASS_NAMES, TRACKED_CLASS_IDS, TrackingConfig, object_type_for_class
from nearmiss.store import delete_video_records
from nearmiss.video import AnalysisArtifacts, VideoError, VideoMetadata, _artifact_paths, inspect_video


REAL_DEMO_DIR = Path(__file__).resolve().parents[1] / "static" / "real-demo"
REAL_DEMO_DATA_SOURCE = "real_traffic_demo"
REAL_DEMO_LABEL = "Real traffic sample"
REAL_DEMO_FILENAME = "real_traffic_sample.mp4"
REAL_DEMO_CAMERA_ID = "SAMPLE-CAM-01 (stock footage)"
SOURCE_FILE, TRACKS_FILE, METADATA_FILE, MANIFEST_FILE, ANNOTATED_FILE = (
    "source.mp4",
    "tracks.json",
    "metadata.json",
    "manifest.json",
    "annotated.mp4",
)
REQUIRED_ROW_KEYS = (
    "track_id", "class_id", "class_name", "object_type", "frame_index",
    "timestamp_seconds", "bbox", "center", "confidence",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Decoder-reported frame counts can differ slightly from the decoded count.
FRAME_COUNT_TOLERANCE = 2
PIXEL_TOLERANCE = 1.0

_VALIDATED: dict[tuple, "RealDemoBundle"] = {}


class RealDemoError(VideoError):
    """The bundled real-traffic sample is missing or does not match its manifest."""


class RealDemoBundle:
    """Validated bundle contents. Construct with :func:`load_bundle`."""

    def __init__(self, directory: Path, manifest: dict, metadata: VideoMetadata,
                 config: TrackingConfig, row_count: int) -> None:
        self.directory = directory
        self.manifest = manifest
        self.metadata = metadata
        self.tracking_config = config
        self.row_count = row_count

    @property
    def video_id(self) -> str:
        return str(self.manifest["video_id"])

    @property
    def credit(self) -> dict[str, str]:
        return _credit(self.manifest)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fail(problem: str) -> RealDemoError:
    return RealDemoError(
        f"The bundled real-traffic sample could not be opened: {problem} "
        "Restore the original files in static/real-demo/ from the NearMiss repository and "
        "try again. Nothing was substituted; the controlled synthetic example is still "
        "available separately."
    )


def _credit(manifest: dict) -> dict[str, str]:
    raw = manifest.get("provenance")
    if not isinstance(raw, dict):
        raise _fail("manifest.json has no provenance section.")
    credit = {
        "credit": str(raw.get("creator") or raw.get("credit") or "").strip(),
        "source_url": str(raw.get("source_url") or "").strip(),
        "license_url": str(raw.get("license_url") or "").strip(),
    }
    missing = [key for key, value in credit.items() if not value]
    if missing:
        raise _fail(f"manifest.json provenance is missing {', '.join(missing)}.")
    credit["title"] = str(raw.get("title") or "Untitled clip").strip()
    credit["license"] = str(raw.get("license") or credit["license_url"]).strip()
    return credit


def _signature(directory: Path) -> tuple:
    parts: list[Any] = [str(directory)]
    for name in (SOURCE_FILE, TRACKS_FILE, METADATA_FILE, MANIFEST_FILE):
        path = directory / name
        try:
            stat = path.stat()
        except OSError:
            raise _fail(f"static/real-demo/{name} is missing.") from None
        parts.append((name, stat.st_size, stat.st_mtime_ns))
    return tuple(parts)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"static/real-demo/{path.name} is not readable JSON ({exc}).") from None


def _tracking_config(raw: Any) -> TrackingConfig:
    names = {item.name for item in fields(TrackingConfig)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise _fail(f"manifest.json tracking_config must contain exactly {sorted(names)}.")
    try:
        config = TrackingConfig(**raw)
    except TypeError as exc:
        raise _fail(f"manifest.json tracking_config is invalid ({exc}).") from None
    if config.as_dict() != raw:
        raise _fail("manifest.json tracking_config does not round-trip.")
    return config


def _metadata(raw: Any) -> VideoMetadata:
    names = {item.name for item in fields(VideoMetadata)}
    if not isinstance(raw, dict) or set(raw) != names:
        raise _fail(f"metadata.json must contain exactly {sorted(names)}.")
    try:
        metadata = VideoMetadata(**raw)
    except TypeError as exc:
        raise _fail(f"metadata.json is invalid ({exc}).") from None
    if not (metadata.fps > 0 and metadata.frame_count > 0 and metadata.width > 0 and metadata.height > 0):
        raise _fail("metadata.json has non-positive dimensions, frame rate or frame count.")
    if not math.isclose(metadata.duration_seconds, metadata.frame_count / metadata.fps, rel_tol=1e-6):
        raise _fail("metadata.json duration does not equal frame_count / fps.")
    return metadata


def _check_rows(rows: Any, metadata: VideoMetadata, config: TrackingConfig) -> int:
    """Schema and consistency checks that real YOLO/ByteTrack rows always satisfy."""

    if not isinstance(rows, list):
        raise _fail("tracks.json must be a list of track rows.")
    seen: set[tuple[int, int]] = set()
    for index, row in enumerate(rows):
        where = f"tracks.json row {index}"
        if not isinstance(row, dict) or any(key not in row for key in REQUIRED_ROW_KEYS):
            raise _fail(f"{where} is missing required fields {list(REQUIRED_ROW_KEYS)}.")
        if row.get("data_source") not in (None, REAL_DEMO_DATA_SOURCE):
            raise _fail(f"{where} declares data_source {row.get('data_source')!r}.")
        frame_index, class_id = row["frame_index"], row["class_id"]
        if not (isinstance(frame_index, int) and 0 <= frame_index < metadata.frame_count):
            raise _fail(f"{where} frame_index {frame_index!r} is outside the source video.")
        if class_id not in TRACKED_CLASS_IDS or row["class_name"] != COCO_CLASS_NAMES.get(class_id):
            raise _fail(f"{where} has an unexpected class ({class_id!r}, {row['class_name']!r}).")
        if row["object_type"] != object_type_for_class(class_id):
            raise _fail(f"{where} object_type does not match its class.")
        if row["timestamp_seconds"] != round(frame_index / metadata.fps, 6):
            raise _fail(f"{where} timestamp does not match frame_index / fps.")
        bbox, center = row["bbox"], row["center"]
        if not (isinstance(bbox, list) and len(bbox) == 4 and isinstance(center, list) and len(center) == 2):
            raise _fail(f"{where} bbox/center have the wrong shape.")
        x1, y1, x2, y2 = (float(value) for value in bbox)
        if not (
            -PIXEL_TOLERANCE <= x1 <= x2 <= metadata.width + PIXEL_TOLERANCE
            and -PIXEL_TOLERANCE <= y1 <= y2 <= metadata.height + PIXEL_TOLERANCE
        ):
            raise _fail(f"{where} bbox lies outside the {metadata.width}×{metadata.height} frame.")
        if abs(center[0] - (x1 + x2) / 2) > 0.02 or abs(center[1] - (y1 + y2) / 2) > 0.02:
            raise _fail(f"{where} center is not the bbox midpoint.")
        confidence = float(row["confidence"])
        if not (config.confidence - 1e-6 <= confidence <= 1.0):
            raise _fail(f"{where} confidence {confidence} is below the manifest threshold.")
        key = (int(row["track_id"]), frame_index)
        if key in seen:
            raise _fail(f"{where} repeats track {key[0]} in frame {frame_index}.")
        seen.add(key)
    return len(rows)


def _check_counts(manifest: dict, metadata: VideoMetadata, rows: list[dict]) -> None:
    """The producer's recorded counts must describe the bundled files."""

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise _fail("manifest.json has no counts section.")
    observed = {
        "frames": metadata.frame_count,
        "track_rows": len(rows),
        "track_ids": len({row["track_id"] for row in rows}),
    }
    for key, expected in observed.items():
        if counts.get(key) != expected:
            raise _fail(f"manifest.json records {key}={counts.get(key)!r}, but the bundle has {expected}.")


def load_bundle(directory: Path | None = None) -> RealDemoBundle:
    """Validate the bundle against its manifest. Results are memoized per file state."""

    directory = Path(directory or REAL_DEMO_DIR)
    signature = _signature(directory)
    if signature in _VALIDATED:
        return _VALIDATED[signature]

    manifest = _read_json(directory / MANIFEST_FILE)
    if not isinstance(manifest, dict):
        raise _fail("manifest.json must be a JSON object.")
    for key in ("video_id", "source_sha256", "tracks_sha256", "metadata_sha256"):
        if not _HEX64.match(str(manifest.get(key, ""))):
            raise _fail(f"manifest.json {key} is not a SHA-256 hex digest.")
    if manifest["video_id"] != manifest["source_sha256"]:
        raise _fail("manifest.json video_id is not the source video's SHA-256.")
    for name, key in ((SOURCE_FILE, "source_sha256"), (TRACKS_FILE, "tracks_sha256"),
                      (METADATA_FILE, "metadata_sha256")):
        if _sha256(directory / name) != manifest[key]:
            raise _fail(f"static/real-demo/{name} does not match the SHA-256 recorded in manifest.json.")
    _credit(manifest)
    config = _tracking_config(manifest.get("tracking_config"))
    metadata = _metadata(_read_json(directory / METADATA_FILE))

    try:
        probed, _frame = inspect_video(directory / SOURCE_FILE)
    except VideoError as exc:
        raise _fail(f"static/real-demo/source.mp4 could not be decoded ({exc}).") from None
    if (probed.width, probed.height) != (metadata.width, metadata.height) or not math.isclose(
        probed.fps, metadata.fps, abs_tol=0.01
    ) or abs(probed.frame_count - metadata.frame_count) > FRAME_COUNT_TOLERANCE:
        raise _fail(
            f"metadata.json ({metadata.width}×{metadata.height}, {metadata.fps:g} fps, "
            f"{metadata.frame_count} frames) does not describe source.mp4 "
            f"({probed.width}×{probed.height}, {probed.fps:g} fps, {probed.frame_count} frames)."
        )

    rows = _read_json(directory / TRACKS_FILE)
    row_count = _check_rows(rows, metadata, config)
    _check_counts(manifest, metadata, rows)
    bundle = RealDemoBundle(directory, manifest, metadata, config, row_count)
    _VALIDATED[signature] = bundle
    return bundle


def manifest_video_id(directory: Path | None = None) -> str | None:
    """The sample's video ID from the manifest, without full validation."""

    try:
        manifest = json.loads((Path(directory or REAL_DEMO_DIR) / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    video_id = str(manifest.get("video_id", "")) if isinstance(manifest, dict) else ""
    return video_id if _HEX64.match(video_id) else None


def is_real_demo_video_id(video_id: str | None) -> bool:
    expected = manifest_video_id()
    return bool(expected) and str(video_id or "") == expected


BUNDLED_PRECOMPUTED = "bundled_precomputed"
LOCAL_INFERENCE = "local_inference"
NOT_ANALYZED = "not_analyzed"


def _inference_settings(config: TrackingConfig) -> tuple:
    # Trail length is drawing-only and excluded from the analysis key, so it is here too.
    return (config.model_name, float(config.confidence), float(config.iou_threshold), config.device)


def tracking_origin(
    bundle: RealDemoBundle, tracking_config: TrackingConfig | None, tracks_path: Path | None
) -> str:
    """Where the rows in use came from, judged from the settings and the artifact bytes.

    Rows count as the bundled precomputed output only when the settings match
    the manifest and (if a cached file is given) the file is byte-identical to
    the bundled ``tracks.json``. Any other existing cached file was produced by
    a normal local analysis with ``tracking_config``.
    """

    config = tracking_config or bundle.tracking_config
    same_settings = _inference_settings(config) == _inference_settings(bundle.tracking_config)
    has_rows = tracks_path is not None and Path(tracks_path).is_file()
    if same_settings and (not has_rows or _sha256(Path(tracks_path)) == bundle.manifest["tracks_sha256"]):
        return BUNDLED_PRECOMPUTED
    return LOCAL_INFERENCE if has_rows else NOT_ANALYZED


def _settings_text(config: TrackingConfig) -> str:
    return (
        f"YOLO ({config.model_name}, confidence {config.confidence:.2f}, overlap "
        f"{config.iou_threshold:.2f}, {config.device}) + ByteTrack"
    )


def real_provenance(
    bundle: RealDemoBundle | None = None,
    tracking_config: TrackingConfig | None = None,
    tracks_path: Path | None = None,
) -> dict[str, Any]:
    """Runtime provenance for the sample: stock-footage credit plus the actual tracking origin.

    Without ``tracking_config`` this describes the bundled rows. The app passes
    the current settings and the artifact it loaded, so a re-analysis with other
    settings is described as fresh local inference with those settings.
    """

    bundle = bundle or load_bundle()
    credit = bundle.credit
    config = tracking_config or bundle.tracking_config
    origin = tracking_origin(bundle, config, tracks_path)
    evaluation = str(bundle.manifest.get("evaluation_note") or "").strip()
    caveat = (
        " All heuristics are provisional; detector accuracy on this footage has not been measured."
    )
    if origin == BUNDLED_PRECOMPUTED:
        boundary = (
            f"Track rows are actual {_settings_text(config)} output, precomputed locally and "
            "bundled. Prediction, incident evidence, review and the simulated inbox run live on "
            "those rows." + caveat + (f" Producer note: {evaluation}" if evaluation else "")
        )
    elif origin == LOCAL_INFERENCE:
        boundary = (
            f"Track rows come from a fresh local {_settings_text(config)} analysis run on this "
            "computer with the selected settings, not the bundled rows. Prediction, incident "
            "evidence, review and the simulated inbox run on those rows." + caveat
        )
    else:
        boundary = (
            f"Not yet analyzed with the selected settings ({_settings_text(config)}); the bundled "
            "rows apply only to the default settings." + caveat
        )
    return {
        "data_source": REAL_DEMO_DATA_SOURCE,
        "label": REAL_DEMO_LABEL,
        "summary": (
            f"Real traffic footage: \u201c{credit['title']}\u201d by {credit['credit']} "
            f"({credit['source_url']}; {credit['license']}, {credit['license_url']}). "
            "Bundled sample, not your upload."
        ),
        "pipeline_boundary": boundary,
        "video_id": bundle.video_id,
        "credit": credit["credit"],
        "title": credit["title"],
        "source_url": credit["source_url"],
        "license": credit["license"],
        "license_url": credit["license_url"],
        "tracking_config": config.as_dict(),
        "tracking_origin": origin,
        "tracks_precomputed": origin == BUNDLED_PRECOMPUTED,
        "evaluation_note": (evaluation or None) if origin == BUNDLED_PRECOMPUTED else None,
    }


def runtime_provenance(tracking_config: TrackingConfig) -> dict[str, Any]:
    """Provenance for the sample under ``tracking_config`` and its cached rows, if any."""

    bundle = load_bundle()
    source_path = video_module.CACHE_ROOT / bundle.video_id / "source.mp4"
    artifacts = _artifact_paths(bundle.video_id, source_path, tracking_config, bundle.metadata)
    return real_provenance(bundle, tracking_config, artifacts.tracks_path)


def _copy_if_different(source: Path, target: Path, expected_sha256: str, verify: bool) -> None:
    if target.exists() and target.stat().st_size == source.stat().st_size:
        if not verify or _sha256(target) == expected_sha256:
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(source.read_bytes())
    os.replace(partial, target)
    if _sha256(target) != expected_sha256:
        raise _fail(f"the cached copy of {source.name} does not match manifest.json after copying.")


def ensure_real_demo_assets(verify: bool = False) -> tuple[Path, AnalysisArtifacts]:
    """Validate the bundle and place it at the normal cache layout.

    ``CACHE_ROOT/<source sha256>/source.mp4`` plus
    ``CACHE_ROOT/<source sha256>/<analysis key for the manifest config>/{tracks,metadata}.json``.
    Track and metadata copies are always compared by digest; the source copy is
    compared by size unless ``verify`` is set.
    """

    bundle = load_bundle()
    directory = video_module.CACHE_ROOT / bundle.video_id
    source_path = directory / "source.mp4"
    _copy_if_different(bundle.directory / SOURCE_FILE, source_path, bundle.manifest["source_sha256"], verify)
    artifacts = _artifact_paths(bundle.video_id, source_path, bundle.tracking_config, bundle.metadata)
    _copy_if_different(bundle.directory / TRACKS_FILE, artifacts.tracks_path, bundle.manifest["tracks_sha256"], True)
    _copy_if_different(
        bundle.directory / METADATA_FILE, artifacts.metadata_path, bundle.manifest["metadata_sha256"], True
    )
    (directory / "provenance.json").write_text(json.dumps(real_provenance(bundle), indent=2), encoding="utf-8")
    return source_path, artifacts


def real_demo_active_video() -> dict[str, Any]:
    """Session record for the sample, matching the shape used for uploads."""

    source_path, _artifacts = ensure_real_demo_assets(verify=True)
    return {
        "name": REAL_DEMO_FILENAME,
        "video_hash": load_bundle().video_id,
        "source_path": str(source_path),
        "real_sample": True,
    }


def annotated_preview_path() -> Path:
    """The bundled overlay preview rendered by the real pipeline at default thresholds."""

    bundle = load_bundle()
    path = bundle.directory / ANNOTATED_FILE
    if not path.is_file() or path.stat().st_size == 0:
        raise _fail("static/real-demo/annotated.mp4 is missing.")
    expected = bundle.manifest.get("annotated_sha256")
    if expected:
        key = ("annotated", str(path), path.stat().st_size, path.stat().st_mtime_ns)
        if key not in _VALIDATED:
            if _sha256(path) != expected:
                raise _fail("static/real-demo/annotated.mp4 does not match manifest.json.")
            _VALIDATED[key] = bundle
    return path


def reset_real_demo_reviews(video_id: str, database_path: Path | str | None = None) -> tuple[int, int]:
    """Clear reviews/notifications recorded against the bundled sample only."""

    if not is_real_demo_video_id(video_id):
        raise ValueError("Only the bundled real-traffic sample can be reset here.")
    return delete_video_records(video_id, database_path)
