"""Local Analysis Library: saved processed-run snapshots and run comparisons.

A snapshot is a compact, footage-free summary of one processed analysis. Its
identity is a digest of the video SHA-256, source kind, tracking/conflict/
collision settings, and analysis zone, so saving the same analysis twice
updates one row instead of creating duplicates, while any setting change
produces a new snapshot.

Counts are computer-vision candidates from image-space measurements. They are
not verified collisions, calibrated speeds, crash probabilities, or measured
safety outcomes, and comparisons never rank roads as safer or less safe.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = Path(".nearmiss_data/nearmiss.db")
SNAPSHOT_SCHEMA_VERSION = "1.0"
SOURCE_KINDS = {
    "synthetic_demo": "Synthetic demonstration (generated footage and scripted tracks)",
    "uploaded_video": "Uploaded video (computer-vision estimates)",
}
# Clips shorter than this are described as too short for pattern statements.
SHORT_EXPOSURE_SECONDS = 600.0
PHYSICAL_VEHICLE_NOTE = (
    "Distinct tracker IDs are not unique physical vehicles: occlusion and ID "
    "switches can split one vehicle into several IDs, and one vehicle can "
    "leave and re-enter. NearMiss does not count physical vehicles."
)
BASE_CAVEATS = [
    "Counts are computer-vision candidates for human review, not verified collisions.",
    "Measurements are uncalibrated image-space estimates; no road speeds or crash "
    "probabilities are implied.",
    PHYSICAL_VEHICLE_NOTE,
]
COMPARISON_METRICS = [
    ("duration_seconds", "Exposure duration (s)"),
    ("candidate_warnings", "Candidate warnings"),
    ("high_candidates", "High-priority candidates"),
    ("medium_candidates", "Medium-priority candidates"),
    ("low_candidates", "Low-priority candidates"),
    ("suspected_incidents", "Suspected incidents"),
    ("distinct_vehicle_track_ids", "Distinct vehicle tracker IDs"),
    ("distinct_track_ids", "Distinct tracker IDs (all objects)"),
    ("distinct_candidate_pairs", "Distinct candidate track pairs"),
    ("candidate_warnings_per_footage_minute", "Candidate warnings per footage minute"),
]

_COLUMNS = (
    "snapshot_id",
    "schema_version",
    "video_sha256",
    "source_kind",
    "source_name",
    "camera_label",
    "duration_seconds",
    "track_record_count",
    "distinct_track_ids",
    "event_count",
    "incident_count",
    "summary_json",
    "config_json",
    "zone_json",
    "video_json",
    "provenance_json",
    "created_at",
    "updated_at",
)
_JSON_COLUMNS = ("summary_json", "config_json", "zone_json", "video_json", "provenance_json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_history(database_path: Path | str = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open the SQLite database and ensure the ``analysis_runs`` table exists."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            snapshot_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            video_sha256 TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_name TEXT NOT NULL,
            camera_label TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            track_record_count INTEGER NOT NULL,
            distinct_track_ids INTEGER NOT NULL,
            event_count INTEGER NOT NULL,
            incident_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL,
            config_json TEXT NOT NULL,
            zone_json TEXT NOT NULL,
            video_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS analysis_runs_video ON analysis_runs(video_sha256);
        """
    )
    return connection


def _canonical(value: Any) -> Any:
    """Normalise values so equivalent settings hash identically."""

    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        rounded = round(value, 6)
        return int(rounded) if rounded.is_integer() else rounded
    if hasattr(value, "as_dict"):
        return _canonical(value.as_dict())
    if hasattr(value, "item"):  # numpy scalars
        return _canonical(value.item())
    return str(value)


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    elif hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        value = asdict(value)
    if not isinstance(value, dict):
        raise TypeError("Settings must be a mapping or dataclass.")
    return _canonical(value)


def _zone(zone_pixels: Any) -> list[list[float]]:
    points = []
    for point in zone_pixels or []:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Zone points must be [x, y] pairs.")
        points.append([float(point[0]), float(point[1])])
    if points and len(points) < 3:
        raise ValueError("A custom zone needs at least three points.")
    return _canonical(points)


def snapshot_identity(
    *,
    video_sha256: str,
    source_kind: str,
    tracking_config: Any,
    conflict_config: Any,
    collision_config: Any,
    zone_pixels: Any,
) -> str:
    """Return the immutable snapshot ID for this footage + settings + zone."""

    payload = {
        "video_sha256": str(video_sha256).strip().lower(),
        "source_kind": str(source_kind),
        "tracking_config": _as_dict(tracking_config),
        "conflict_config": _as_dict(conflict_config),
        "collision_config": _as_dict(collision_config),
        "zone_pixels": _zone(zone_pixels),
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return "run-" + digest.hexdigest()[:20]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _track_id(value: Any) -> int | None:
    # Non-finite or malformed IDs (inf, NaN, "x") count as missing.
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _pair(event: dict) -> tuple[int, int] | None:
    first = _track_id(event.get("participant_a_track_id", event.get("vehicle_a_track_id")))
    second = _track_id(event.get("participant_b_track_id", event.get("vehicle_b_track_id")))
    if first is None or second is None:
        return None
    return (min(first, second), max(first, second))


def summarize_analysis(
    *,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    duration_seconds: float,
) -> dict[str, Any]:
    """Compute footage-free summary metrics from processed records."""

    tracks = [record for record in tracks or [] if isinstance(record, dict)]
    events = [event for event in events or [] if isinstance(event, dict)]
    incidents = [incident for incident in incidents or [] if isinstance(incident, dict)]
    ids_by_type: dict[str, set[int]] = {}
    all_ids: set[int] = set()
    for record in tracks:
        identifier = _track_id(record.get("track_id"))
        if identifier is None:
            continue
        all_ids.add(identifier)
        ids_by_type.setdefault(str(record.get("object_type", "other")), set()).add(identifier)
    severity = Counter(str(event.get("severity", "")).upper() for event in events)
    gaps = [
        gap
        for gap in (_number(event.get("arrival_time_gap_seconds")) for event in events)
        if gap is not None
    ]
    stitched_participants = sum(
        1
        for event in events
        for key in ("participant_a_track_ids", "participant_b_track_ids")
        if isinstance(event.get(key), (list, tuple)) and len(event[key]) > 1
    )
    review_status = Counter(str(incident.get("review_status") or "Unreviewed") for incident in incidents)
    duration = max(0.0, _number(duration_seconds) or 0.0)
    minutes = duration / 60.0
    return {
        "duration_seconds": round(duration, 3),
        "track_record_count": len(tracks),
        "distinct_track_ids": len(all_ids),
        "distinct_vehicle_track_ids": len(ids_by_type.get("vehicle", set())),
        "distinct_pedestrian_track_ids": len(ids_by_type.get("pedestrian", set())),
        "distinct_cyclist_track_ids": len(ids_by_type.get("cyclist", set())),
        "unique_physical_vehicles": None,
        "unique_physical_vehicles_note": PHYSICAL_VEHICLE_NOTE,
        "candidate_warnings": len(events),
        "high_candidates": severity["HIGH"],
        "medium_candidates": severity["MEDIUM"],
        "low_candidates": severity["LOW"],
        "distinct_candidate_pairs": len({pair for pair in map(_pair, events) if pair}),
        "candidate_participants_with_stitched_ids": stitched_participants,
        "average_arrival_gap_seconds": round(sum(gaps) / len(gaps), 4) if gaps else None,
        "candidate_warnings_per_footage_minute": (
            round(len(events) / minutes, 4) if minutes > 0 else None
        ),
        "suspected_incidents": len(incidents),
        "incident_review_status_at_save": dict(sorted(review_status.items())),
    }


def build_analysis_snapshot(
    *,
    video_sha256: str,
    source_name: str,
    camera_label: str,
    source_kind: str,
    duration_seconds: float,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    tracking_config: Any,
    conflict_config: Any,
    collision_config: Any,
    zone_pixels: Any = None,
    video_metadata: Any = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build an unsaved snapshot dict. No footage or per-frame records are kept."""

    video_sha256 = str(video_sha256 or "").strip().lower()
    if not video_sha256:
        raise ValueError("A video digest is required for a snapshot.")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(SOURCE_KINDS)}.")
    config = {
        "tracking_config": _as_dict(tracking_config),
        "conflict_config": _as_dict(conflict_config),
        "collision_config": _as_dict(collision_config),
    }
    zone = _zone(zone_pixels)
    summary = summarize_analysis(
        tracks=tracks, events=events, incidents=incidents, duration_seconds=duration_seconds
    )
    observed_sources = sorted(
        {
            str(item["data_source"])
            for collection in (tracks or [], events or [], incidents or [])
            for item in collection
            if isinstance(item, dict) and item.get("data_source")
        }
    )
    warnings = []
    if source_kind == "uploaded_video" and any("synthetic" in value.lower() for value in observed_sources):
        warnings.append(
            "Records carry a synthetic data_source tag although the run is labeled as uploaded video."
        )
    if source_kind == "synthetic_demo" and not observed_sources:
        warnings.append("Synthetic run saved without per-record data_source tags.")
    provenance = {
        "source_kind": source_kind,
        "source_label": SOURCE_KINDS[source_kind],
        "video_sha256": video_sha256,
        "record_data_sources": observed_sources,
        "detector": (
            "Scripted synthetic tracks (no YOLO inference)"
            if source_kind == "synthetic_demo"
            else f"YOLO ({config['tracking_config'].get('model_name', 'unknown model')}) + ByteTrack"
        ),
        "footage_stored": False,
        "warnings": warnings,
    }
    video = _as_dict(video_metadata) if video_metadata is not None else {}
    return {
        "snapshot_id": snapshot_identity(
            video_sha256=video_sha256,
            source_kind=source_kind,
            tracking_config=config["tracking_config"],
            conflict_config=config["conflict_config"],
            collision_config=config["collision_config"],
            zone_pixels=zone,
        ),
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "video_sha256": video_sha256,
        "source_kind": source_kind,
        "source_name": str(source_name or "").strip() or "Untitled footage",
        "camera_label": str(camera_label or "").strip() or f"CAM-{video_sha256[:8].upper()}",
        "duration_seconds": summary["duration_seconds"],
        "track_record_count": summary["track_record_count"],
        "distinct_track_ids": summary["distinct_track_ids"],
        "event_count": summary["candidate_warnings"],
        "incident_count": summary["suspected_incidents"],
        "summary": {**summary, "notes": str(notes or "")},
        "config": config,
        "zone": {"zone_pixels": zone, "user_defined": len(zone) >= 3},
        "video": video,
        "provenance": provenance,
    }


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    output = dict(row)
    for key in _JSON_COLUMNS:
        output[key.removesuffix("_json")] = json.loads(output.pop(key))
    return output


def save_analysis_snapshot(
    *,
    snapshot: dict[str, Any],
    database_path: Path | str = DEFAULT_DATABASE_PATH,
) -> tuple[dict[str, Any], bool]:
    """Upsert a snapshot from ``build_analysis_snapshot``.

    Returns ``(saved_snapshot, created)``; ``created`` is False when an
    identical snapshot already existed (its ``created_at`` is preserved).
    """

    required = {"video_sha256", "source_kind", "config", "zone"}
    missing = sorted(required - set(snapshot))
    if missing:
        raise ValueError(f"Snapshot is missing fields: {', '.join(missing)}")
    expected_id = snapshot_identity(
        video_sha256=snapshot["video_sha256"],
        source_kind=snapshot["source_kind"],
        tracking_config=snapshot["config"].get("tracking_config"),
        conflict_config=snapshot["config"].get("conflict_config"),
        collision_config=snapshot["config"].get("collision_config"),
        zone_pixels=snapshot["zone"].get("zone_pixels"),
    )
    if snapshot.get("snapshot_id") != expected_id:
        raise ValueError("Snapshot ID does not match its footage, settings and zone.")
    now = _utc_now()
    values = {
        "snapshot_id": expected_id,
        "schema_version": snapshot.get("schema_version", SNAPSHOT_SCHEMA_VERSION),
        "video_sha256": snapshot["video_sha256"],
        "source_kind": snapshot["source_kind"],
        "source_name": snapshot.get("source_name", "Untitled footage"),
        "camera_label": snapshot.get("camera_label", ""),
        "duration_seconds": float(snapshot.get("duration_seconds") or 0.0),
        "track_record_count": int(snapshot.get("track_record_count") or 0),
        "distinct_track_ids": int(snapshot.get("distinct_track_ids") or 0),
        "event_count": int(snapshot.get("event_count") or 0),
        "incident_count": int(snapshot.get("incident_count") or 0),
        "summary_json": json.dumps(snapshot.get("summary", {}), sort_keys=True),
        "config_json": json.dumps(snapshot["config"], sort_keys=True),
        "zone_json": json.dumps(snapshot["zone"], sort_keys=True),
        "video_json": json.dumps(snapshot.get("video", {}), sort_keys=True),
        "provenance_json": json.dumps(snapshot.get("provenance", {}), sort_keys=True),
        "created_at": now,
        "updated_at": now,
    }
    updatable = [
        column
        for column in _COLUMNS
        if column not in {"snapshot_id", "video_sha256", "source_kind", "config_json", "zone_json", "created_at"}
    ]
    with connect_history(database_path) as connection:
        created = (
            connection.execute(
                "SELECT 1 FROM analysis_runs WHERE snapshot_id = ?", (expected_id,)
            ).fetchone()
            is None
        )
        connection.execute(
            f"""
            INSERT INTO analysis_runs ({", ".join(_COLUMNS)})
            VALUES ({", ".join("?" for _ in _COLUMNS)})
            ON CONFLICT(snapshot_id) DO UPDATE SET
                {", ".join(f"{column}=excluded.{column}" for column in updatable)}
            """,
            tuple(values[column] for column in _COLUMNS),
        )
        saved = _row(
            connection.execute(
                "SELECT * FROM analysis_runs WHERE snapshot_id = ?", (expected_id,)
            ).fetchone()
        )
    connection.close()
    return saved or {}, created


def list_analysis_snapshots(
    *,
    database_path: Path | str = DEFAULT_DATABASE_PATH,
    video_sha256: str | None = None,
    source_kind: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return saved snapshots, most recently updated first."""

    clauses, parameters = [], []
    if video_sha256:
        clauses.append("video_sha256 = ?")
        parameters.append(str(video_sha256).strip().lower())
    if source_kind:
        clauses.append("source_kind = ?")
        parameters.append(source_kind)
    query = "SELECT * FROM analysis_runs"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC, created_at DESC, snapshot_id"
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(max(0, int(limit)))
    with connect_history(database_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    connection.close()
    return [_row(row) for row in rows]


def load_analysis_snapshot(
    *,
    snapshot_id: str,
    database_path: Path | str = DEFAULT_DATABASE_PATH,
) -> dict[str, Any] | None:
    """Return one saved snapshot, or None when it does not exist."""

    with connect_history(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM analysis_runs WHERE snapshot_id = ?", (str(snapshot_id),)
        ).fetchone()
    connection.close()
    return _row(row)


def diff_snapshot_settings(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """List every tracking/conflict/collision setting and zone difference."""

    differences = []
    for section in ("tracking_config", "conflict_config", "collision_config"):
        first = baseline.get("config", {}).get(section, {})
        second = candidate.get("config", {}).get(section, {})
        for key in sorted(set(first) | set(second)):
            if first.get(key) != second.get(key):
                differences.append(
                    {"section": section, "setting": key, "baseline": first.get(key), "candidate": second.get(key)}
                )
    first_zone = baseline.get("zone", {}).get("zone_pixels", [])
    second_zone = candidate.get("zone", {}).get("zone_pixels", [])
    if first_zone != second_zone:
        differences.append(
            {"section": "zone", "setting": "zone_pixels", "baseline": first_zone, "candidate": second_zone}
        )
    return differences


def _metric(snapshot: dict, key: str) -> float | None:
    if key == "duration_seconds":
        return _number(snapshot.get("duration_seconds"))
    return _number(snapshot.get("summary", {}).get(key))


def compare_analysis_snapshots(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Describe count/exposure deltas between two snapshots with caveats.

    The result never contains a safety ranking or verdict; it only reports
    what differs and why the difference may not reflect road conditions.
    """

    same_footage = baseline.get("video_sha256") == candidate.get("video_sha256")
    setting_changes = diff_snapshot_settings(baseline=baseline, candidate=candidate)
    kinds = {baseline.get("source_kind"), candidate.get("source_kind")}
    provenance_mismatch = len(kinds) > 1
    if baseline.get("snapshot_id") == candidate.get("snapshot_id"):
        comparison_kind = "identical_snapshot"
    elif same_footage:
        comparison_kind = "same_footage_different_settings"
    else:
        comparison_kind = "different_footage"

    rows = []
    for key, label in COMPARISON_METRICS:
        first, second = _metric(baseline, key), _metric(candidate, key)
        delta = None if first is None or second is None else round(second - first, 4)
        rows.append({"metric": key, "label": label, "baseline": first, "candidate": second, "delta": delta})

    caveats = list(BASE_CAVEATS)
    if provenance_mismatch:
        caveats.insert(
            0,
            "PROVENANCE MISMATCH: one run is a synthetic demonstration and the other is "
            "uploaded footage. Synthetic counts are scripted and must not be compared "
            "with real-footage results as evidence.",
        )
    if comparison_kind == "same_footage_different_settings":
        caveats.append(
            f"Same footage analysed with {len(setting_changes)} setting/zone change(s); "
            "differences reflect detector settings, not changes on the road."
        )
    elif comparison_kind == "different_footage":
        caveats.append(
            "Different footage: camera angle, lighting, traffic volume, time of day, and "
            "clip length all differ, so deltas do not show which location is safer."
        )
        if setting_changes:
            caveats.append(
                f"Settings or zone also differ ({len(setting_changes)} change(s)), which "
                "further limits comparability."
            )
    short = [
        snapshot.get("source_name", "run")
        for snapshot in (baseline, candidate)
        if (_number(snapshot.get("duration_seconds")) or 0.0) < SHORT_EXPOSURE_SECONDS
    ]
    if short:
        caveats.append(
            f"Short exposure (< {SHORT_EXPOSURE_SECONDS / 60:.0f} min of footage) for: "
            f"{', '.join(dict.fromkeys(short))}. Short clips cannot support statements "
            "about typical conditions."
        )
    if baseline.get("camera_label") != candidate.get("camera_label"):
        caveats.append("Camera labels differ; labels are operator-entered and not verified locations.")
    for snapshot in (baseline, candidate):
        for warning in snapshot.get("provenance", {}).get("warnings", []):
            caveats.append(f"{snapshot.get('source_name', 'run')}: {warning}")

    return {
        "baseline_snapshot_id": baseline.get("snapshot_id"),
        "candidate_snapshot_id": candidate.get("snapshot_id"),
        "comparison_kind": comparison_kind,
        "same_footage": same_footage,
        "provenance_mismatch": provenance_mismatch,
        "source_kinds": {"baseline": baseline.get("source_kind"), "candidate": candidate.get("source_kind")},
        "metrics": rows,
        "setting_changes": setting_changes,
        "caveats": caveats,
        "ranking": None,
        "ranking_note": "NearMiss does not rank locations or runs by safety.",
    }


def compare_saved_snapshots(
    *,
    baseline_id: str,
    candidate_id: str,
    database_path: Path | str = DEFAULT_DATABASE_PATH,
) -> dict[str, Any]:
    """Load two saved snapshots by ID and compare them."""

    baseline = load_analysis_snapshot(snapshot_id=baseline_id, database_path=database_path)
    candidate = load_analysis_snapshot(snapshot_id=candidate_id, database_path=database_path)
    if baseline is None or candidate is None:
        raise KeyError("Both snapshots must exist in the Analysis Library.")
    return compare_analysis_snapshots(baseline=baseline, candidate=candidate)


def snapshot_table_rows(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten snapshots into display/CSV rows."""

    rows = []
    for snapshot in snapshots:
        summary = snapshot.get("summary", {})
        rows.append(
            {
                "snapshot_id": snapshot.get("snapshot_id"),
                "source_kind": snapshot.get("source_kind"),
                "source_name": snapshot.get("source_name"),
                "camera_label": snapshot.get("camera_label"),
                "video_sha256": snapshot.get("video_sha256"),
                "duration_seconds": snapshot.get("duration_seconds"),
                "distinct_track_ids": snapshot.get("distinct_track_ids"),
                "distinct_vehicle_track_ids": summary.get("distinct_vehicle_track_ids"),
                "candidate_warnings": snapshot.get("event_count"),
                "high_candidates": summary.get("high_candidates"),
                "suspected_incidents": snapshot.get("incident_count"),
                "zone_user_defined": snapshot.get("zone", {}).get("user_defined"),
                "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"),
            }
        )
    return rows


_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formulas in string cells; numbers stay numeric."""

    if isinstance(value, (list, dict)):
        value = json.dumps(value)
    if not isinstance(value, str) or not value:
        return value
    # Leading tab/CR/LF/other control characters can also start a formula.
    if ord(value[0]) < 32 or value.lstrip().startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(value) for key, value in row.items()})
    return buffer.getvalue()


def snapshots_to_csv(snapshots: list[dict[str, Any]]) -> str:
    rows = snapshot_table_rows(snapshots)
    fieldnames = list(rows[0]) if rows else list(snapshot_table_rows([{}])[0])
    return _csv(rows, fieldnames)


def snapshots_to_json(snapshots: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "export_kind": "nearmiss_analysis_library",
            "caveats": BASE_CAVEATS,
            "snapshots": snapshots,
        },
        indent=2,
        sort_keys=True,
    )


def comparison_to_csv(comparison: dict[str, Any]) -> str:
    output = _csv(comparison.get("metrics", []), ["metric", "label", "baseline", "candidate", "delta"])
    caveats = io.StringIO()
    writer = csv.writer(caveats)
    writer.writerow([])
    writer.writerow(["caveat"])
    for caveat in comparison.get("caveats", []):
        writer.writerow([_csv_cell(caveat)])
    return output + caveats.getvalue()


def comparison_to_json(comparison: dict[str, Any]) -> str:
    return json.dumps(
        {"schema_version": SNAPSHOT_SCHEMA_VERSION, "export_kind": "nearmiss_run_comparison", **comparison},
        indent=2,
        sort_keys=True,
    )
