"""Persistent local review and simulated-dispatch storage for NearMiss."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = Path(".nearmiss_data/nearmiss.db")
REVIEW_STATUSES = {"Confirmed Incident", "False Alarm", "Uncertain"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(database_path: Path | str | None = None) -> sqlite3.Connection:
    # Resolve the default at call time so the app and tests can redirect it.
    path = Path(database_path if database_path is not None else DEFAULT_DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS incident_reviews (
            incident_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            incident_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dispatch_notifications (
            notification_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL UNIQUE,
            video_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            acknowledged_at TEXT,
            status TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            FOREIGN KEY (incident_id) REFERENCES incident_reviews(incident_id)
        );
        """
    )
    return connection


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    output = dict(row)
    for key in ("incident_json", "summary_json"):
        if key in output:
            output[key.removesuffix("_json")] = json.loads(output.pop(key))
    return output


def review_incident(
    incident: dict,
    review_status: str,
    camera_id: str,
    database_path: Path | str | None = None,
) -> tuple[dict, dict | None]:
    """Persist a review and create one local dispatch alert when confirmed."""

    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {review_status}")
    incident_id = str(incident.get("incident_id", "")).strip()
    video_id = str(incident.get("source_video_id", "")).strip()
    if not incident_id or not video_id:
        raise ValueError("Incident ID and source video ID are required.")
    camera_id = str(camera_id).strip() or f"CAM-{video_id[:8].upper()}"
    now = _utc_now()
    persisted_incident = {**incident, "review_status": review_status, "camera_id": camera_id}

    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO incident_reviews (
                incident_id, video_id, camera_id, review_status, reviewed_at, incident_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(incident_id) DO UPDATE SET
                video_id=excluded.video_id,
                camera_id=excluded.camera_id,
                review_status=excluded.review_status,
                reviewed_at=excluded.reviewed_at,
                incident_json=excluded.incident_json
            """,
            (
                incident_id,
                video_id,
                camera_id,
                review_status,
                now,
                json.dumps(persisted_incident, sort_keys=True),
            ),
        )
        notification = None
        existing = _row(
            connection.execute(
                "SELECT * FROM dispatch_notifications WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        )
        if review_status != "Confirmed Incident" and existing is not None:
            # A reversed confirmation must not keep claiming "confirmed" in
            # the inbox. The row is kept (withdrawn) as an audit trail.
            summary = {
                **existing.get("summary", {}),
                "operator_confirmation": review_status,
                "withdrawn_at": now,
                "notice": "Simulated dispatch notification withdrawn after the operator "
                "changed the review decision; nothing was sent externally.",
            }
            connection.execute(
                """
                UPDATE dispatch_notifications
                SET status = 'Withdrawn', summary_json = ?
                WHERE incident_id = ?
                """,
                (json.dumps(summary, sort_keys=True), incident_id),
            )
        if review_status == "Confirmed Incident":
            notification_id = "dispatch-" + sha256(incident_id.encode("utf-8")).hexdigest()[:12]
            summary = {
                "incident_id": incident_id,
                "timestamp_seconds": incident.get("timestamp_seconds"),
                "camera_id": camera_id,
                "vehicle_track_ids": [
                    incident.get("vehicle_a_track_id"),
                    incident.get("vehicle_b_track_id"),
                ],
                "detection_signals": incident.get("detection_signals", []),
                "operator_confirmation": review_status,
                "source_video_id": video_id,
                "notice": "Simulated dispatch notification only; nothing was sent externally.",
            }
            if incident.get("data_source"):
                summary["data_source"] = incident["data_source"]
            if existing is not None and existing["status"] == "Withdrawn":
                summary["reconfirmed_at"] = now
                connection.execute(
                    """
                    UPDATE dispatch_notifications
                    SET status = 'New', acknowledged_at = NULL, camera_id = ?, summary_json = ?
                    WHERE incident_id = ?
                    """,
                    (camera_id, json.dumps(summary, sort_keys=True), incident_id),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO dispatch_notifications (
                    notification_id, incident_id, video_id, camera_id,
                    generated_at, acknowledged_at, status, summary_json
                ) VALUES (?, ?, ?, ?, ?, NULL, 'New', ?)
                """,
                (
                    notification_id,
                    incident_id,
                    video_id,
                    camera_id,
                    now,
                    json.dumps(summary, sort_keys=True),
                ),
            )
            notification = _row(
                connection.execute(
                    "SELECT * FROM dispatch_notifications WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
            )
        review = _row(
            connection.execute(
                "SELECT * FROM incident_reviews WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        )
    return review or {}, notification


def list_reviews(
    video_id: str | None = None,
    database_path: Path | str | None = None,
) -> list[dict]:
    with _connect(database_path) as connection:
        if video_id is None:
            rows = connection.execute(
                "SELECT * FROM incident_reviews ORDER BY reviewed_at DESC"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM incident_reviews WHERE video_id = ? ORDER BY reviewed_at DESC",
                (str(video_id),),
            ).fetchall()
    return [_row(row) for row in rows if row is not None]


def list_notifications(
    video_id: str | None = None,
    database_path: Path | str | None = None,
) -> list[dict]:
    with _connect(database_path) as connection:
        if video_id is None:
            rows = connection.execute(
                "SELECT * FROM dispatch_notifications ORDER BY generated_at DESC"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM dispatch_notifications WHERE video_id = ? ORDER BY generated_at DESC",
                (str(video_id),),
            ).fetchall()
    return [_row(row) for row in rows if row is not None]


def acknowledge_notification(
    notification_id: str,
    database_path: Path | str | None = None,
) -> dict | None:
    now = _utc_now()
    with _connect(database_path) as connection:
        connection.execute(
            """
            UPDATE dispatch_notifications
            SET status = 'Acknowledged', acknowledged_at = COALESCE(acknowledged_at, ?)
            WHERE notification_id = ? AND status != 'Withdrawn'
            """,
            (now, str(notification_id)),
        )
        result = connection.execute(
            "SELECT * FROM dispatch_notifications WHERE notification_id = ?",
            (str(notification_id),),
        ).fetchone()
    return _row(result)


def delete_video_records(
    video_id: str,
    database_path: Path | str | None = None,
) -> tuple[int, int]:
    """Delete reviews and simulated notifications for exactly one video ID.

    Used only to reset the labeled synthetic demonstration; callers are
    responsible for refusing real-footage IDs. Returns (reviews, notifications).
    """

    video_id = str(video_id).strip()
    if not video_id:
        raise ValueError("A video ID is required.")
    with _connect(database_path) as connection:
        notifications = connection.execute(
            "DELETE FROM dispatch_notifications WHERE video_id = ?", (video_id,)
        ).rowcount
        reviews = connection.execute(
            "DELETE FROM incident_reviews WHERE video_id = ?", (video_id,)
        ).rowcount
    return reviews, notifications
