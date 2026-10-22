"""Validation and display helpers for user-supplied conflict events."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
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

