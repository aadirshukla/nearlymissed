"""Validation and display helpers for user-supplied conflict events."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from io import StringIO
from typing import Any


def normalize_events(events: Any, fps: float) -> tuple[list[dict], list[str]]:
    """Normalize detector output without inventing or scoring any events.

    The detector may return dictionaries or dataclass instances. Unknown fields
    are preserved so experimental metrics remain exportable.
    """

    if events is None:
        return [], []
    if not isinstance(events, list):
        return [], ["detect_conflicts must return a list; its output was ignored."]

    normalized: list[dict] = []
    warnings: list[str] = []
    for index, raw_event in enumerate(events):
        if is_dataclass(raw_event):
            event = asdict(raw_event)
        elif isinstance(raw_event, dict):
            event = dict(raw_event)
        else:
            warnings.append(f"Event {index + 1} is not a dictionary and was ignored.")
            continue

        timestamp = event.get("timestamp_seconds", event.get("start_time_seconds"))
        if timestamp is None and event.get("frame_index") is not None and fps > 0:
            timestamp = float(event["frame_index"]) / fps

        try:
            event["timestamp_seconds"] = float(timestamp)
        except (TypeError, ValueError):
            warnings.append(
                f"Event {index + 1} has no usable timestamp; it will be exported "
                "but omitted from the timeline."
            )
            event["timestamp_seconds"] = None

        event.setdefault("event_id", index + 1)
        event.setdefault("severity", "flagged")
        event.setdefault("description", "Potential conflict flagged by detector")
        normalized.append(event)

    return normalized, warnings


def format_timestamp(seconds: float | None) -> str:
    """Format seconds from the beginning of a video as MM:SS.s."""

    if seconds is None:
        return "—"
    minutes, remaining = divmod(max(0.0, float(seconds)), 60)
    return f"{int(minutes):02d}:{remaining:04.1f}"


def events_to_csv(events: list[dict]) -> bytes:
    """Serialize conflict events, preserving nested evidence as JSON cells."""

    if not events:
        return b"event_id,timestamp_seconds,severity\n"
    preferred = [
        "event_id",
        "timestamp_seconds",
        "first_alert_timestamp_seconds",
        "severity",
        "risk_score",
        "interaction_type",
        "participant_a_track_id",
        "participant_b_track_id",
        "participant_a_type",
        "participant_b_type",
        "vehicle_a_track_id",
        "vehicle_b_track_id",
        "vehicle_track_id",
        "pedestrian_track_id",
        "arrival_time_gap_seconds",
        "participant_a_eta_seconds",
        "participant_b_eta_seconds",
        "vehicle_eta_seconds",
        "pedestrian_eta_seconds",
        "path_separation_pixels",
        "closing_speed_pixels_per_second",
        "conflict_point",
        "description",
    ]
    all_fields = {key for event in events for key in event}
    fieldnames = [name for name in preferred if name in all_fields]
    fieldnames.extend(sorted(all_fields - set(fieldnames)))
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for event in events:
        row = {
            key: json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list, tuple))
            else value
            for key, value in event.items()
        }
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")

