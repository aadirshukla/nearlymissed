"""Four-chapter traffic story shown below the Overview hero.

Observe -> Predict -> Verify -> Follow-up, told about one interaction in the
labeled synthetic demonstration. Every number and every drawn position comes
from recomputing that demo through the normal pipeline (scripted track rows ->
conflict prediction -> independent incident evidence) with the current
thresholds. Nothing is typed in by hand, and the diagram is a functional
top-down plot of stored track rows, not a picture of a real place.

Progressive enhancement:

- The chapter text and one static SVG "scene endpoint" per chapter are plain
  markup, so every caption is readable if the component script never runs.
- With script, wide screens show one sticky diagram that steps through stored
  frames as chapters scroll past (native page scroll, IntersectionObserver).
  Narrow screens keep the stacked endpoints.
- Motion follows ``prefers-reduced-motion`` and a visible toggle.

The component uses ``st.components.v2`` with style isolation (a shadow root in
the page, not an iframe) and touches nothing outside its own root.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from html import escape
from typing import Any

from conflict_detector import detect_conflicts
from nearmiss import demo, streetlab
from nearmiss.events import normalize_events
from nearmiss.explain import PATTERN_LABELS, SIGNAL_TEXT, interaction_pattern
from nearmiss.geometry import enrich_tracks_with_zone
from nearmiss.incidents import detect_suspected_collisions
from nearmiss.safety import deduplicate_events


CHAPTERS = ("observe", "predict", "verify", "follow_up")
SYNTHETIC_RIBBON = (
    "SYNTHETIC DEMO · Diagram plotted from scripted track rows, recomputed through the "
    "normal NearMiss pipeline. Not a real location, real traffic or a real incident."
)
# Street Lab's own example assumptions (feet). They are placeholders, not
# measurements of the synthetic scene, and are labeled that way everywhere.
EXAMPLE_CROSSING = streetlab.CrossingAssumptions(
    unit="ft",
    current_distance=60.0,
    proposed_distance=40.0,
    walking_speed=3.5,
    slower_walking_speed=2.5,
    start_up_seconds=2.0,
)
# One breakpoint for the sticky stage, shared by the CSS and the script.
STAGE_QUERY = "(min-width: 960px)"
LEAD_IN_SECONDS = 2.0
LEAD_OUT_SECONDS = 1.0
_SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ---------------------------------------------------------------- pipeline


def demo_layout() -> dict[str, Any]:
    """Road geometry of the generated clip, in source pixels."""

    return {
        "width": demo.WIDTH,
        "height": demo.HEIGHT,
        "road_h": list(demo.ROAD_H),
        "road_v": list(demo.ROAD_V),
    }


def recompute_demo(conflict_config: dict, collision_config: dict) -> dict[str, Any]:
    """Run the scripted demo rows through prediction and incident evidence.

    Mirrors app.py for the demo: full-frame zone, the same normalisation and
    deduplication, and the incident detector on the unenriched rows.
    """

    tracks = demo.synthetic_tracks()
    zone = [
        [0.0, 0.0],
        [float(demo.WIDTH), 0.0],
        [float(demo.WIDTH), float(demo.HEIGHT)],
        [0.0, float(demo.HEIGHT)],
    ]
    config = {**conflict_config, "zone_is_user_defined": False}
    raw = detect_conflicts(enrich_tracks_with_zone(tracks, zone), zone, config)
    events, _warnings = normalize_events(raw, demo.FPS)
    events = deduplicate_events(events)
    incidents = detect_suspected_collisions(
        tracks, events, source_video_id=demo.DEMO_VIDEO_ID, config=collision_config
    )
    return {"tracks": tracks, "events": events, "incidents": incidents, "config": config}


def focus_evidence(events: list[dict], incidents: list[dict]) -> tuple[dict | None, dict | None]:
    """The warning (and linked suspected incident) the story follows.

    Prefers the earliest incident that a warning preceded; otherwise the
    highest-priority, earliest warning with no incident.
    """

    by_id = {event.get("event_id"): event for event in events}
    linked = sorted(
        (item for item in incidents if item.get("associated_prediction_event_id") in by_id),
        key=lambda item: float(item.get("timestamp_seconds") or 0.0),
    )
    if linked:
        return by_id[linked[0]["associated_prediction_event_id"]], linked[0]
    if not events:
        return None, None
    ranked = sorted(
        events,
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 3),
            float(item.get("first_alert_timestamp_seconds") or 0.0),
        ),
    )
    return ranked[0], None


def _direction(velocity: Any) -> str:
    try:
        dx, dy = float(velocity[0]), float(velocity[1])
    except (TypeError, ValueError, IndexError):
        return "moving"
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return "stationary"
    if abs(dx) >= abs(dy):
        return "moving right" if dx > 0 else "moving left"
    return "moving down" if dy > 0 else "moving up"


def _speed(velocity: Any) -> float | None:
    try:
        return (float(velocity[0]) ** 2 + float(velocity[1]) ** 2) ** 0.5
    except (TypeError, ValueError, IndexError):
        return None


def clock(frame_index: int, fps: float) -> str:
    return f"t = {frame_index / fps:.2f} s · frame {frame_index}"


def _fact(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def build_story(
    *,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    conflict_config: dict,
    fps: float,
    duration_seconds: float,
    layout: dict[str, Any],
    crossing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Assemble chapters, scene endpoints and animation rows. Pure function.

    Returns ``None`` when there is no warning to follow, so the caller shows
    nothing rather than an invented story.
    """

    event, incident = focus_evidence(events, incidents)
    if event is None:
        return None
    crossing = crossing or streetlab.crossing_comparison(EXAMPLE_CROSSING)
    last_frame = max(0, int(round(duration_seconds * fps)) - 1)

    a_id, b_id = int(event["participant_a_track_id"]), int(event["participant_b_track_id"])
    a_class, b_class = event.get("participant_a_class", "road user"), event.get("participant_b_class", "road user")
    alert_frame = int(event.get("start_frame_index", event.get("frame_index", 0)))
    measure_frame = int(event.get("frame_index", alert_frame))
    candidate_t = float(event.get("candidate_start_timestamp_seconds", event["timestamp_seconds"]))
    observe_frame = max(0, int(round(candidate_t * fps)) - 1)
    contact_frame = int(incident["frame_index"]) if incident else None
    end_anchor = contact_frame if contact_frame is not None else alert_frame
    start_frame = max(0, alert_frame - int(round(LEAD_IN_SECONDS * fps)))
    end_frame = min(last_frame, end_anchor + int(round(LEAD_OUT_SECONDS * fps)))
    observe_frame = max(start_frame, min(observe_frame, measure_frame))

    actors: dict[int, dict] = {}
    for row in sorted(tracks, key=lambda item: (int(item["track_id"]), int(item["frame_index"]))):
        frame_index = int(row["frame_index"])
        if not start_frame <= frame_index <= end_frame:
            continue
        track_id = int(row["track_id"])
        actor = actors.setdefault(
            track_id,
            {
                "id": track_id,
                "kind": str(row.get("object_type") or "vehicle"),
                "role": "a" if track_id == a_id else "b" if track_id == b_id else "context",
                "rows": [],
            },
        )
        actor["rows"].append([frame_index] + [round(float(value), 2) for value in row["bbox"]])

    def rows_until(track_id: int, frame_index: int) -> int:
        return sum(
            1 for row in tracks if int(row["track_id"]) == track_id and int(row["frame_index"]) <= frame_index
        )

    vehicles = {int(r["track_id"]) for r in tracks if r.get("object_type") == "vehicle"}
    pedestrians = {int(r["track_id"]) for r in tracks if r.get("object_type") == "pedestrian"}
    min_age = int(conflict_config.get("min_track_age_frames", 0))
    pattern = PATTERN_LABELS[interaction_pattern(event)]
    a_speed = _speed(event.get("participant_a_velocity_pixels_per_second"))
    b_speed = _speed(event.get("participant_b_velocity_pixels_per_second"))
    a_dir = _direction(event.get("participant_a_velocity_pixels_per_second"))
    b_dir = _direction(event.get("participant_b_velocity_pixels_per_second"))
    alert_t = float(event["first_alert_timestamp_seconds"])
    gap = event.get("arrival_time_gap_seconds")
    ttc = event.get("time_to_conflict_seconds")
    following = interaction_pattern(event) == "following"
    gap_label = "Time headway" if following else "Arrival gap"
    gap_value = event.get("time_headway_seconds", gap) if following else gap
    # Same minimums conflict_detector applies when it confirms each priority.
    required_frames = {
        "HIGH": max(2, int(conflict_config.get("high_persistence_frames", 3))),
        "MEDIUM": max(2, int(conflict_config.get("medium_persistence_frames", 2))),
    }.get(str(event.get("severity")), max(1, int(conflict_config.get("min_event_persistence_frames", 2))))

    observe = {
        "id": "observe",
        "number": 1,
        "kicker": "Observe",
        "title": "Every road user becomes a stored track",
        "body": [
            f"Across the {duration_seconds:.1f} s synthetic clip, {len(vehicles)} vehicles and "
            f"{len(pedestrians)} pedestrians have stored track rows: one box per frame, with a "
            "persistent ID.",
            f"This story follows {a_class} #{a_id} ({a_dir}) and {b_class} #{b_id} ({b_dir}). "
            "The fading lines are their observed ground points, drawn only from rows already "
            "recorded, never ahead of the current frame.",
        ],
        "facts": [
            _fact("Scene shown", clock(observe_frame, fps)),
            _fact(f"Rows stored for #{a_id}", str(rows_until(a_id, observe_frame))),
            _fact(f"Rows stored for #{b_id}", str(rows_until(b_id, observe_frame))),
            _fact("History required to predict", f"{min_age} frames per track"),
        ],
        "frame": observe_frame,
        "layers": [],
    }
    predict = {
        "id": "predict",
        "number": 2,
        "kicker": "Predict",
        "title": "Projected paths meet, then the warning is confirmed",
        "body": [
            f"Recent motion is projected up to {float(conflict_config['prediction_horizon_seconds']):.1f} s "
            f"ahead. The scene shows the warning's representative measurement at "
            f"{measure_frame / fps:.2f} s (frame {measure_frame}): the boxes and the dashed paths "
            f"of #{a_id} and #{b_id} come from that same frame, and the paths meet at the ringed "
            f"point ({pattern.lower()}).",
            f"The {event.get('severity')} warning was confirmed at {alert_t:.2f} s (frame {alert_frame}) "
            f"after {required_frames} consecutive confirming frames. It is a forecast for review, "
            "not a probability.",
        ],
        "facts": [
            _fact("Projection measured", f"{measure_frame / fps:.2f} s · frame {measure_frame}"),
            _fact("First warning", f"{alert_t:.2f} s · frame {alert_frame} · {event.get('severity')}"),
            _fact(gap_label, "—" if gap_value is None else f"{float(gap_value):.2f} s"),
            _fact("Time to projected meeting", "—" if ttc is None else f"{float(ttc):.2f} s"),
            _fact(
                "HIGH threshold",
                f"≤ {float(conflict_config['high_time_gap_seconds']):.2f} s arrival gap",
            ),
            _fact(
                "Measured speeds (image pixels)",
                f"#{a_id} {a_speed:.0f} px/s · #{b_id} {b_speed:.0f} px/s"
                if a_speed is not None and b_speed is not None
                else "—",
            ),
        ],
        # Boxes and projections must come from the same frame, so the scene
        # freezes on the measurement, not the (later) first-alert frame.
        "frame": measure_frame,
        "layers": ["predict"],
    }
    if incident is not None:
        measurements = incident.get("measurements") or {}
        overlap = measurements.get("peak_overlap_fraction_smaller_box")
        lead = incident.get("prediction_lead_seconds")
        signals = [str(signal) for signal in incident.get("detection_signals", [])]
        values = {
            "frames": incident.get("contact_persistence_frames", "?"),
            "overlap": float(overlap or 0.0),
            "closing": measurements.get("closing_speed_pixels_per_second", "?"),
            "reduction": measurements.get("distance_reduction_pixels", "?"),
        }
        signal_text = [
            SIGNAL_TEXT[signal].format(**values) if signal in SIGNAL_TEXT else signal.replace("_", " ")
            for signal in signals
        ]
        contact_t = float(incident.get("first_suspected_impact_timestamp_seconds", incident["timestamp_seconds"]))
        verify = {
            "id": "verify",
            "number": 3,
            "kicker": "Verify",
            "title": "A separate check finds contact; a person decides",
            "body": [
                f"Independently of the forecast, the incident detector found box contact at "
                f"{contact_t:.2f} s (frame {contact_frame})"
                + (
                    f", {float(lead):.2f} s after the warning."
                    if lead is not None and float(lead) > 0
                    else "."
                ),
                "Every suspected incident opens as Uncertain. The operator replays the source "
                "frames and chooses Confirm, Dismiss or Uncertain. Only Confirm creates a "
                "local, simulated notification; nothing is sent anywhere.",
            ],
            "facts": [
                _fact("First suspected contact", f"{contact_t:.2f} s · frame {contact_frame}"),
                _fact(
                    "Warning lead",
                    "—" if lead is None else f"{float(lead):.2f} s",
                ),
                _fact("Supporting signals", f"{len(signals)}"),
                _fact(
                    "Peak overlap",
                    "—" if overlap is None else f"{float(overlap):.0%} of the smaller box",
                ),
                _fact("Review status at start", "Uncertain (needs a person)"),
            ],
            "signals": signal_text,
            "frame": contact_frame,
            "layers": ["verify"],
        }
    else:
        verify = {
            "id": "verify",
            "number": 3,
            "kicker": "Verify",
            "title": "No contact followed, so there is nothing to confirm",
            "body": [
                "The independent incident detector found no qualifying contact after this "
                "warning with the current thresholds. NearMiss does not fabricate an incident "
                "for review.",
                "Warnings stay forecasts: they are never confirmed as incidents and never "
                "create a notification.",
            ],
            "facts": [_fact("Suspected incidents in clip", str(len(incidents)))],
            "signals": [],
            "frame": measure_frame,
            "layers": ["predict"],
        }
    typical, slower = crossing["rows"][0], crossing["rows"][1]
    unit = crossing["assumptions"]["unit"]
    follow_up = {
        "id": "follow_up",
        "number": 4,
        "kicker": "Follow-up",
        "title": "From one reviewed moment to a community brief",
        "body": [
            "Street Lab summarises the reviewed warnings and incidents and adds a crossing-time "
            "illustration. The distances are example assumptions you replace with field "
            "measurements; they are not measured from this scene.",
            "The exported brief states its data boundary and that any design idea is a review "
            "hypothesis needing qualified engineering review.",
        ],
        "facts": [
            _fact(
                "Example crossing",
                f"{crossing['assumptions']['current_distance']:.0f} {unit} now · "
                f"{crossing['assumptions']['proposed_distance']:.0f} {unit} hypothetical (assumed)",
            ),
            _fact(
                typical["walker"],
                f"{typical['current_seconds']:.1f} s → {typical['proposed_seconds']:.1f} s",
            ),
            _fact(
                slower["walker"],
                f"{slower['current_seconds']:.1f} s → {slower['proposed_seconds']:.1f} s",
            ),
            _fact("Brief formats", "PDF and Markdown, generated locally"),
        ],
        "frame": end_anchor,
        "layers": ["follow"],
    }
    chapters = [observe, predict, verify, follow_up]
    for chapter in chapters:
        chapter["clock"] = clock(int(chapter["frame"]), fps)
    return {
        "fps": float(fps),
        "layout": layout,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "event": {
            "event_id": event.get("event_id"),
            "measure_frame": measure_frame,
            "alert_frame": alert_frame,
            "a_label": f"{a_class} #{a_id} ({a_dir})",
            "b_label": f"{b_class} #{b_id} ({b_dir})",
            "a_id": a_id,
            "b_id": b_id,
            "a_position": event.get("participant_a_position"),
            "b_position": event.get("participant_b_position"),
            "a_end": event.get("participant_a_predicted_end"),
            "b_end": event.get("participant_b_predicted_end"),
            "conflict_point": event.get("conflict_point"),
            "conflict_radius": float(event.get("conflict_region_radius_pixels") or 16.0),
        },
        "incident": None
        if incident is None
        else {
            "incident_id": incident.get("incident_id"),
            "contact_point": incident.get("contact_point"),
            "a_bbox": incident.get("vehicle_a_bbox"),
            "b_bbox": incident.get("vehicle_b_bbox"),
        },
        "crossing": {
            "current": float(crossing["assumptions"]["current_distance"]),
            "proposed": float(crossing["assumptions"]["proposed_distance"]),
            "unit": unit,
        },
        "actors": [actors[key] for key in sorted(actors)],
        "chapters": chapters,
    }


@lru_cache(maxsize=16)
def _story_from_json(conflict_json: str, collision_json: str) -> dict[str, Any] | None:
    conflict_config, collision_config = json.loads(conflict_json), json.loads(collision_json)
    result = recompute_demo(conflict_config, collision_config)
    return build_story(
        tracks=result["tracks"],
        events=result["events"],
        incidents=result["incidents"],
        conflict_config=result["config"],
        fps=demo.FPS,
        duration_seconds=demo.frame_count() / demo.FPS,
        layout=demo_layout(),
    )


def demo_story(conflict_config: dict, collision_config: dict) -> dict[str, Any] | None:
    """Story for the current thresholds, recomputed once per distinct setting."""

    return _story_from_json(
        json.dumps(conflict_config, sort_keys=True, default=str),
        json.dumps(collision_config, sort_keys=True, default=str),
    )


# ---------------------------------------------------------------- drawing

_ROLE_FILL = {"a": "#F2A93B", "b": "#E7E5E4", "context": "#57534E"}


def _attr(value: Any) -> str:
    return escape(str(value), quote=True)


def _row_at(actor: dict, frame_index: int) -> list[float] | None:
    """Latest stored row at or before the frame, while the track is still alive."""

    rows = actor["rows"]
    if not rows or frame_index < rows[0][0] or frame_index > rows[-1][0]:
        return None
    best = None
    for row in rows:
        if row[0] > frame_index:
            break
        best = row
    return best


def _label_y(role: str, y1: float, y2: float) -> float:
    """Participant A is labeled below its box so the two labels never collide."""

    return y2 + 26 if role == "a" else y1 - 10


def _trail_points(actor: dict, start_frame: int, frame_index: int) -> str:
    return " ".join(
        f"{(row[1] + row[3]) / 2:.1f},{row[4]:.1f}"
        for row in actor["rows"]
        if start_frame <= row[0] <= frame_index
    )


def _background(layout: dict) -> str:
    width, height = layout["width"], layout["height"]
    (h0, h1), (v0, v1) = layout["road_h"], layout["road_v"]
    cy, cx = (h0 + h1) / 2, (v0 + v1) / 2
    parts = [
        f'<rect width="{width}" height="{height}" fill="#121513"/>',
        f'<rect x="0" y="{h0 - 22}" width="{width}" height="{h1 - h0 + 44}" fill="#2B2E2F"/>',
        f'<rect x="{v0 - 22}" y="0" width="{v1 - v0 + 44}" height="{height}" fill="#2B2E2F"/>',
        f'<rect x="0" y="{h0}" width="{width}" height="{h1 - h0}" fill="#1C1B1A"/>',
        f'<rect x="{v0}" y="0" width="{v1 - v0}" height="{height}" fill="#1C1B1A"/>',
        f'<path d="M0 {cy}H{v0 - 46}M{v1 + 46} {cy}H{width}M{cx} 0V{h0 - 46}M{cx} {h1 + 46}V{height}" '
        'stroke="#6B5530" stroke-width="3" stroke-dasharray="18 14"/>',
    ]
    stripes = []
    for y in range(h0 + 6, h1 - 4, 16):
        stripes.append(f'<rect x="{v0 - 40}" y="{y}" width="28" height="8"/>')
        stripes.append(f'<rect x="{v1 + 12}" y="{y}" width="28" height="8"/>')
    for x in range(v0 + 6, v1 - 4, 16):
        stripes.append(f'<rect x="{x}" y="{h0 - 40}" width="8" height="28"/>')
        stripes.append(f'<rect x="{x}" y="{h1 + 12}" width="8" height="28"/>')
    parts.append('<g fill="#4A4A47">' + "".join(stripes) + "</g>")
    return "".join(parts)


def _layer_predict(story: dict) -> str:
    event = story["event"]
    try:
        lines = "".join(
            f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" '
            f'stroke="{_ROLE_FILL[role]}" stroke-width="4" stroke-dasharray="12 10" '
            'stroke-linecap="round"/>'
            for role, start, end in (
                ("a", event["a_position"], event["a_end"]),
                ("b", event["b_position"], event["b_end"]),
            )
        )
        point = event["conflict_point"]
        ring = (
            f'<circle cx="{point[0]}" cy="{point[1]}" r="{event["conflict_radius"]:.1f}" '
            'fill="rgba(242,169,59,.16)" stroke="#F2A93B" stroke-width="3"/>'
        )
    except (TypeError, IndexError, KeyError):
        return ""
    fps = story["fps"]
    note = (
        f'<text class="svg-note" x="18" y="{story["layout"]["height"] - 18}">'
        f'paths measured {event["measure_frame"] / fps:.2f} s (frame {event["measure_frame"]}) · '
        f'first warning {event["alert_frame"] / fps:.2f} s (frame {event["alert_frame"]})</text>'
    )
    return f'<g class="layer layer-predict">{lines}{ring}{note}</g>'


def _layer_verify(story: dict) -> str:
    incident = story.get("incident")
    if not incident or not incident.get("contact_point"):
        return ""
    x, y = incident["contact_point"]
    return (
        '<g class="layer layer-verify">'
        f'<circle cx="{x}" cy="{y}" r="30" fill="none" stroke="#E5676F" stroke-width="4"/>'
        f'<circle cx="{x}" cy="{y}" r="6" fill="#E5676F"/>'
        f'<text x="{x + 38}" y="{y - 30}" class="svg-label" fill="#F2B5BA">contact</text>'
        "</g>"
    )


def _layer_follow(story: dict) -> str:
    layout, crossing = story["layout"], story["crossing"]
    (h0, h1), (_v0, v1) = layout["road_h"], layout["road_v"]
    x = v1 + 54
    length = h1 - h0
    proposed = length * min(1.0, crossing["proposed"] / max(crossing["current"], 1e-9))
    top = h0 + (length - proposed) / 2
    unit = crossing["unit"]
    return (
        '<g class="layer layer-follow">'
        f'<rect x="{v1 + 10}" y="{h0}" width="32" height="{length}" fill="rgba(242,169,59,.14)" '
        'stroke="#F2A93B" stroke-width="2"/>'
        f'<path d="M{x} {h0}V{h1}M{x - 8} {h0}H{x + 8}M{x - 8} {h1}H{x + 8}" stroke="#A8A29E" stroke-width="3"/>'
        f'<path d="M{x + 26} {top:.1f}V{top + proposed:.1f}M{x + 18} {top:.1f}H{x + 34}M{x + 18} '
        f'{top + proposed:.1f}H{x + 34}" stroke="#F2A93B" stroke-width="4"/>'
        f'<text x="{x + 46}" y="{h0 + 24}" class="svg-label" fill="#D6D3D1">'
        f'{crossing["current"]:.0f} {unit} assumed</text>'
        f'<text x="{x + 46}" y="{h0 + 56}" class="svg-label" fill="#F5C373">'
        f'{crossing["proposed"]:.0f} {unit} hypothetical</text>'
        "</g>"
    )


def _point(value: Any) -> str:
    try:
        return f"({float(value[0]):.0f}, {float(value[1]):.0f}) px"
    except (TypeError, ValueError, IndexError):
        return "an unrecorded point"


def scene_description(story: dict, chapter: dict) -> str:
    """Text alternative for one scene endpoint: what is drawn, and from what."""

    event, layers = story["event"], chapter["layers"]
    frame_index = int(chapter["frame"])
    shown = [a for a in story["actors"] if _row_at(a, frame_index) is not None]
    others = sum(1 for a in shown if a["role"] == "context")
    parts = [
        f"Top-down synthetic diagram at {chapter['clock']}, plotted from stored track rows.",
        f"Amber box: {event['a_label']}. Light box: {event['b_label']}. "
        "Solid lines are their observed ground points so far.",
        f"{others} other road user(s) in grey." if others else "No other road users in view.",
    ]
    if "predict" in layers:
        parts.append(
            f"Dashed projected paths, measured at frame {event['measure_frame']}, meet in a ring at "
            f"{_point(event['conflict_point'])}. The first warning followed at frame {event['alert_frame']}."
        )
    if "verify" in layers and story.get("incident"):
        parts.append(f"A red contact marker sits at {_point(story['incident']['contact_point'])}, where the boxes overlap.")
    if "follow" in layers:
        crossing = story["crossing"]
        parts.append(
            f"Road users are dimmed. The right-hand crosswalk is highlighted with brackets for an assumed "
            f"{crossing['current']:.0f} {crossing['unit']} current and {crossing['proposed']:.0f} "
            f"{crossing['unit']} hypothetical crossing, which are not measurements of this scene."
        )
    return " ".join(parts)


def scene_svg(story: dict, chapter_id: str, *, stage: bool = False) -> str:
    """Static SVG endpoint for a chapter, or the animated stage when ``stage``."""

    chapter = next(item for item in story["chapters"] if item["id"] == chapter_id)
    frame_index = int(chapter["frame"])
    layers = chapter["layers"]
    layout = story["layout"]
    actors_markup, trails_markup = [], []
    for actor in story["actors"]:
        row = _row_at(actor, frame_index)
        role = actor["role"]
        hidden = "" if row is not None else ' visibility="hidden"'
        x1, y1, x2, y2 = row[1:] if row is not None else (0, 0, 0, 0)
        trail_class = "trail" if role != "context" else "trail context"
        trails_markup.append(
            f'<polyline class="{trail_class}" data-trail="{actor["id"]}" fill="none" '
            f'stroke="{_ROLE_FILL[role]}" '
            f'points="{_trail_points(actor, story["start_frame"], frame_index) if row is not None else ""}"/>'
        )
        radius = 7 if actor["kind"] == "pedestrian" else 4
        label = (
            f'<text class="svg-label actor-label" data-label="{actor["id"]}" '
            f'data-below="{"true" if role == "a" else "false"}" x="{x1:.1f}" '
            f'y="{_label_y(role, y1, y2):.1f}" fill="{_ROLE_FILL[role]}"{hidden}>#{actor["id"]}</text>'
            if role != "context"
            else ""
        )
        actors_markup.append(
            f'<rect class="actor {role}" data-actor="{actor["id"]}" x="{x1:.1f}" y="{y1:.1f}" '
            f'width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" rx="{radius}" '
            f'fill="{_ROLE_FILL[role]}"{hidden}/>' + label
        )
    overlays = ""
    if stage or "predict" in layers:
        overlays += _layer_predict(story)
    if stage or "verify" in layers:
        overlays += _layer_verify(story)
    if stage or "follow" in layers:
        overlays += _layer_follow(story)
    description = scene_description(story, chapter)
    role_attr = 'data-stage="true" ' if stage else ""
    return (
        f'<svg class="nm-scene{" is-follow" if "follow" in layers else ""}" {role_attr}'
        f'viewBox="0 0 {layout["width"]} {layout["height"]}" role="img" '
        f'aria-label="{_attr(description)}" data-layers="{_attr(" ".join(layers))}" '
        'xmlns="http://www.w3.org/2000/svg">'
        f"{_background(layout)}"
        f'<g class="trails">{"".join(trails_markup)}</g>'
        f'<g class="actors">{"".join(actors_markup)}</g>'
        f"{overlays}"
        f'<text class="svg-clock" x="18" y="34" data-clock="true">{escape(chapter["clock"])}</text>'
        f'<text class="svg-tag" x="{layout["width"] - 18}" y="{layout["height"] - 18}" '
        'text-anchor="end">SYNTHETIC DEMO</text>'
        "</svg>"
    )


def story_markup(story: dict) -> str:
    """Complete, script-free story markup: header, stage and four chapters."""

    chapters_html = []
    for chapter in story["chapters"]:
        facts = "".join(
            f"<div><dt>{escape(fact['label'])}</dt><dd>{escape(fact['value'])}</dd></div>"
            for fact in chapter["facts"]
        )
        signals = (
            '<ul class="nm-signals">'
            + "".join(f"<li>{escape(text)}</li>" for text in chapter.get("signals", []))
            + "</ul>"
            if chapter.get("signals")
            else ""
        )
        body = "".join(f"<p>{escape(text)}</p>" for text in chapter["body"])
        chapters_html.append(
            f'<section class="nm-chapter" data-chapter="{chapter["id"]}" '
            f'aria-labelledby="nm-story-{chapter["id"]}">'
            f'<p class="nm-chapter-kicker">{chapter["number"]} · {escape(chapter["kicker"])}</p>'
            f'<h3 id="nm-story-{chapter["id"]}">{escape(chapter["title"])}</h3>'
            f"{body}<dl class=\"nm-facts\">{facts}</dl>{signals}"
            f'<figure class="nm-endpoint">{scene_svg(story, chapter["id"])}'
            f"<figcaption>{escape(chapter['kicker'])} endpoint · {escape(chapter['clock'])}</figcaption>"
            "</figure></section>"
        )
    return (
        '<div class="nm-story" data-story="true">'
        '<header class="nm-story-head">'
        '<p class="nm-story-kicker">How one warning is earned</p>'
        "<h2>Observe, predict, verify, follow up</h2>"
        "<p class=\"nm-story-intro\">Four steps through one interaction in the generated demo "
        "intersection. Each figure is plotted from stored track rows; each number was just "
        "recomputed with the thresholds in Advanced settings.</p>"
        f'<p class="nm-ribbon" role="note">{escape(SYNTHETIC_RIBBON)}</p>'
        '<button type="button" class="nm-motion-toggle" data-motion-toggle hidden '
        'aria-pressed="false">Reduce motion</button>'
        "</header>"
        '<div class="nm-story-grid">'
        f'<div class="nm-stage" aria-hidden="true">{scene_svg(story, "observe", stage=True)}</div>'
        f'<div class="nm-chapters">{"".join(chapters_html)}</div>'
        "</div></div>"
    )


def animation_data(story: dict) -> dict[str, Any]:
    """Only what the stage script needs: stored rows and chapter endpoints."""

    return {
        "fps": story["fps"],
        "start_frame": story["start_frame"],
        "actors": [{"id": a["id"], "rows": a["rows"]} for a in story["actors"]],
        "chapters": [
            {"id": c["id"], "frame": int(c["frame"]), "layers": c["layers"], "kicker": c["kicker"]}
            for c in story["chapters"]
        ],
    }


STORY_CSS = """
:host { display:block; }
.nm-story { color:#F5F5F4; font:inherit; line-height:1.6; }
.nm-story-head { max-width:760px; margin:0 0 2rem; }
.nm-story-kicker, .nm-chapter-kicker { color:#F2A93B; font-size:.72rem; letter-spacing:.12em;
  text-transform:uppercase; font-weight:620; margin:0 0 .6rem; }
.nm-story h2 { font-size:2rem; line-height:1.1; letter-spacing:-.035em; font-weight:620; margin:0; }
.nm-story-intro { color:#C9C4BE; font-size:1rem; margin:.8rem 0 1rem; }
.nm-ribbon { border-left:3px solid #F2A93B; background:#17130C; color:#E7D8BF; font-size:.82rem;
  padding:.55rem .9rem; margin:0 0 1rem; border-radius:0 6px 6px 0; }
.nm-motion-toggle { font:inherit; font-size:.8rem; color:#E7E5E4; background:#161618;
  border:1px solid #44403C; border-radius:6px; padding:.4rem .8rem; min-height:2.2rem; cursor:pointer; }
.nm-motion-toggle[aria-pressed="true"] { border-color:#F2A93B; color:#F5C373; }
.nm-motion-toggle:focus-visible { outline:2px solid #F2A93B; outline-offset:2px; }
.nm-chapter { border-top:1px solid #27272A; padding:2rem 0; }
.nm-chapter h3 { font-size:1.35rem; line-height:1.25; letter-spacing:-.02em; font-weight:600; margin:0 0 .7rem; }
.nm-chapter p { color:#D6D3D1; font-size:.98rem; margin:0 0 .7rem; max-width:62ch; }
.nm-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.6rem 1rem;
  margin:1rem 0 0; }
.nm-facts div { border-top:1px solid #27272A; padding-top:.45rem; min-width:0; }
.nm-facts dt { color:#A8A29E; font-size:.72rem; }
.nm-facts dd { color:#F5F5F4; font-size:.92rem; margin:.15rem 0 0; font-variant-numeric:tabular-nums; }
.nm-signals { color:#C9C4BE; font-size:.86rem; margin:.9rem 0 0; padding-left:1.1rem; }
.nm-endpoint { margin:1.2rem 0 0; }
.nm-endpoint figcaption { color:#A8A29E; font-size:.76rem; margin-top:.4rem; }
.nm-scene { display:block; width:100%; height:auto; border-radius:8px; border:1px solid #27272A;
  background:#121513; }
.nm-scene .trail { stroke-width:4; stroke-linecap:round; stroke-linejoin:round; opacity:.7; }
.nm-scene .trail.context { stroke-width:2; opacity:.45; }
.nm-scene .actor { stroke:#0B0B0C; stroke-width:2; }
.nm-scene .svg-label { font:600 24px ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }
.nm-scene .svg-clock { font:600 24px ui-monospace, "SF Mono", Menlo, monospace; fill:#F5F5F4; }
.nm-scene .svg-note { font:600 19px ui-sans-serif, -apple-system, "Segoe UI", sans-serif; fill:#F5C373; }
.nm-scene .svg-tag { font:700 20px ui-sans-serif, -apple-system, sans-serif; letter-spacing:.08em; fill:#F2A93B; }
.nm-scene.is-follow .actors, .nm-scene.is-follow .trails,
.nm-scene[data-layers~="follow"] .actors, .nm-scene[data-layers~="follow"] .trails { opacity:.35; }
.nm-stage { display:none; }
.nm-scene .layer { transition:opacity 420ms cubic-bezier(.2,0,0,1); }
.nm-scene[data-stage] .layer { opacity:0; }
.nm-scene[data-stage][data-layers~="predict"] .layer-predict,
.nm-scene[data-stage][data-layers~="verify"] .layer-verify,
.nm-scene[data-stage][data-layers~="follow"] .layer-follow { opacity:1; }
.nm-scene .actors, .nm-scene .trails { transition:opacity 420ms cubic-bezier(.2,0,0,1); }
@media __STAGE_QUERY__ {
  .nm-story.is-enhanced .nm-story-grid { display:grid; grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);
    gap:3rem; align-items:start; }
  .nm-story.is-enhanced .nm-stage { display:block; position:sticky; top:5.5rem; }
  .nm-story.is-enhanced .nm-chapter { min-height:72vh; display:flex; flex-direction:column;
    justify-content:center; }
  /* Visually hidden, not removed: the endpoints keep each chapter's text
     alternative in the accessibility tree while the sticky stage is shown. */
  .nm-story.is-enhanced .nm-endpoint { position:absolute; width:1px; height:1px; margin:-1px;
    padding:0; border:0; overflow:hidden; clip:rect(0 0 0 0); clip-path:inset(50%); white-space:nowrap; }
  .nm-story.is-enhanced .nm-chapter:not(.is-active) h3 { color:#A8A29E; }
}
@media (prefers-reduced-motion: reduce) {
  .nm-scene .layer, .nm-scene .actors, .nm-scene .trails { transition:none; }
}
.nm-story.is-reduced .nm-scene .layer, .nm-story.is-reduced .nm-scene .actors,
.nm-story.is-reduced .nm-scene .trails { transition:none; }
@media (max-width: 640px) { .nm-story h2 { font-size:1.6rem; } }
"""

# The stage only ever shows stored rows: each drawn frame snaps to the latest
# stored row at or before it, exactly like the static endpoints.
STORY_JS = """
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector('[data-story]');
  if (!root || !data) return;
  if (typeof root.__nmCleanup === 'function') root.__nmCleanup();
  const stage = root.querySelector('svg[data-stage]');
  const toggle = root.querySelector('[data-motion-toggle]');
  const chapters = Array.from(root.querySelectorAll('[data-chapter]'));
  const byId = new Map(data.chapters.map((c) => [c.id, c]));
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  let userReduced = null;
  try { const saved = window.localStorage.getItem('nearmiss.reduceMotion');
        if (saved !== null) userReduced = saved === 'true'; } catch (e) {}
  const reduced = () => (userReduced === null ? media.matches : userReduced);
  // The animated stage exists only at this width (see STORY_CSS); below it
  // nothing animates and the stacked endpoints carry the story.
  const wide = window.matchMedia('__STAGE_QUERY__');
  let current = data.start_frame, raf = 0, activeId = null, enabled = false;

  const rowAt = (rows, f) => {
    if (!rows.length || f < rows[0][0] || f > rows[rows.length - 1][0]) return null;
    let lo = 0, hi = rows.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (rows[mid][0] <= f) lo = mid; else hi = mid - 1; }
    return rows[lo];
  };
  const draw = (f) => {
    current = f;
    for (const actor of data.actors) {
      const rect = stage.querySelector(`[data-actor="${actor.id}"]`);
      const label = stage.querySelector(`[data-label="${actor.id}"]`);
      const trail = stage.querySelector(`[data-trail="${actor.id}"]`);
      const row = rowAt(actor.rows, f);
      if (rect) {
        if (row) {
          rect.setAttribute('x', row[1].toFixed(1)); rect.setAttribute('y', row[2].toFixed(1));
          rect.setAttribute('width', (row[3] - row[1]).toFixed(1));
          rect.setAttribute('height', (row[4] - row[2]).toFixed(1));
          rect.removeAttribute('visibility');
        } else { rect.setAttribute('visibility', 'hidden'); }
      }
      if (label) {
        if (row) { label.setAttribute('x', row[1].toFixed(1));
                   label.setAttribute('y', (label.dataset.below === 'true' ? row[4] + 26 : row[2] - 10).toFixed(1));
                   label.removeAttribute('visibility'); }
        else { label.setAttribute('visibility', 'hidden'); }
      }
      if (trail) {
        trail.setAttribute('points', !row ? '' : actor.rows
          .filter((r) => r[0] >= data.start_frame && r[0] <= f)
          .map((r) => `${((r[1] + r[3]) / 2).toFixed(1)},${r[4].toFixed(1)}`).join(' '));
      }
    }
    const clock = stage.querySelector('[data-clock]');
    if (clock) clock.textContent = `t = ${(f / data.fps).toFixed(2)} s · frame ${f}`;
  };
  const goTo = (chapter) => {
    cancelAnimationFrame(raf);
    if (!enabled) return;
    stage.setAttribute('data-layers', chapter.layers.join(' '));
    const from = current, to = chapter.frame;
    if (reduced() || from === to) { draw(to); return; }
    const duration = Math.min(2400, Math.max(500, (Math.abs(to - from) / data.fps) * 1000));
    const started = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - started) / duration);
      draw(Math.round(from + (to - from) * p));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  };
  const activate = (id) => {
    if (id === activeId || !byId.has(id)) return;
    activeId = id;
    for (const section of chapters) section.classList.toggle('is-active', section.dataset.chapter === id);
    goTo(byId.get(id));
  };
  const syncReduced = () => {
    root.classList.toggle('is-reduced', reduced());
    if (toggle) toggle.setAttribute('aria-pressed', String(reduced()));
    if (enabled && reduced() && activeId) { cancelAnimationFrame(raf); draw(byId.get(activeId).frame); }
  };
  const onToggle = () => {
    userReduced = !reduced();
    try { window.localStorage.setItem('nearmiss.reduceMotion', String(userReduced)); } catch (e) {}
    syncReduced();
  };
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((e) => e.isIntersecting);
    if (visible.length) activate(visible[visible.length - 1].target.dataset.chapter);
  }, { rootMargin: '-45% 0px -45% 0px', threshold: 0 });

  const enable = () => {
    if (enabled) return;
    enabled = true;
    activeId = null;
    draw(reduced() ? byId.get('observe').frame : data.start_frame);
    chapters.forEach((section) => observer.observe(section));
  };
  const disable = () => {
    enabled = false;
    cancelAnimationFrame(raf);
    observer.disconnect();
    activeId = null;
    for (const section of chapters) section.classList.remove('is-active');
  };
  const onWidth = () => (wide.matches ? enable() : disable());

  root.classList.add('is-enhanced');
  if (toggle) { toggle.hidden = false; toggle.addEventListener('click', onToggle); }
  media.addEventListener('change', syncReduced);
  wide.addEventListener('change', onWidth);
  syncReduced();
  onWidth();

  const cleanup = () => {
    disable();
    wide.removeEventListener('change', onWidth);
    media.removeEventListener('change', syncReduced);
    if (toggle) toggle.removeEventListener('click', onToggle);
    root.__nmCleanup = null;
  };
  root.__nmCleanup = cleanup;
  return cleanup;
}
"""

STORY_CSS = STORY_CSS.replace("__STAGE_QUERY__", STAGE_QUERY)
STORY_JS = STORY_JS.replace("__STAGE_QUERY__", STAGE_QUERY)

_COMPONENTS: dict[str, Any] = {}


def story_component_name(markup: str) -> str:
    """One registration per distinct markup, so the script-free HTML matches the data."""

    return "nearmiss_story_" + hashlib.sha256(markup.encode("utf-8")).hexdigest()[:12]


def render_story(story: dict, *, key: str = "nearmiss_story") -> None:
    """Mount the story in the page (shadow root, no iframe)."""

    import streamlit.components.v2 as components_v2

    markup = story_markup(story)
    name = story_component_name(markup)
    if name not in _COMPONENTS:
        _COMPONENTS[name] = components_v2.component(
            name, html=markup, css=STORY_CSS, js=STORY_JS, isolate_styles=True
        )
    _COMPONENTS[name](key=key, data=animation_data(story), height="content")
