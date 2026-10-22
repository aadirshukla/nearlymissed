"""Small geometry helpers shared by the UI and detector integration."""

from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np


def point_in_polygon(point: Iterable[float], polygon: list[list[float]]) -> bool:
    """Return whether a point is inside or on a polygon boundary."""

    if len(polygon) < 3:
        return False
    contour = np.asarray(polygon, dtype=np.float32)
    x, y = point
    return cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0


def enrich_tracks_with_zone(
    tracks: list[dict], zone: list[list[float]]
) -> list[dict]:
    """Copy records and attach an ``in_conflict_zone`` boolean to each one."""

    enriched: list[dict] = []
    for record in tracks:
        item = dict(record)
        item["in_conflict_zone"] = point_in_polygon(item["center"], zone)
        enriched.append(item)
    return enriched


def normalized_polygon(zone: list[list[float]], width: int, height: int) -> list[list[float]]:
    """Convert a pixel-space polygon to 0..1 coordinates for exports."""

    if width <= 0 or height <= 0:
        return []
    return [[round(x / width, 6), round(y / height, 6)] for x, y in zone]

