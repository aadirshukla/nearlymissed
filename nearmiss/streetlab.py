"""Street Lab: connect processed evidence to a community street-safety review.

Boundaries, stated in every output:
- Evidence comes only from the active video's processed tracks, warnings,
  suspected incidents, and operator reviews (synthetic demo or uploaded).
- The crossing comparison is arithmetic on user-entered assumptions. It is an
  illustration of exposure time, not a measured crash reduction, an engineering
  recommendation, or real city data.
- Any design idea is a review hypothesis that requires field measurement.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from math import isfinite
from typing import Any
from xml.sax.saxutils import escape

from nearmiss.events import format_timestamp
from nearmiss.explain import PATTERN_LABELS, interaction_pattern
from nearmiss.safety import deduplicate_events, event_pair_key


HYPOTHESIS_STATEMENT = (
    "Any design change discussed here is a review hypothesis. It requires field "
    "measurement, local context, and qualified engineering review before any decision."
)
CROSSING_BOUNDARY = (
    "Crossing times are arithmetic on the assumptions entered above (distance ÷ walking "
    "speed + start-up time). They illustrate time spent in the roadway; they are not a "
    "measured crash reduction or a prediction of safety outcomes."
)
DATA_BOUNDARY = (
    "No crash records, city data, or real incidents are used. Counts below come only "
    "from the active video's processed detections and this operator's reviews."
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def frame_region(point: Any, width: int, height: int) -> str | None:
    """Describe an image location in camera-frame terms (not a street address)."""

    if not isinstance(point, (list, tuple)) or len(point) != 2 or width <= 0 or height <= 0:
        return None
    x, y = _number(point[0]), _number(point[1])
    if x is None or y is None or not (0 <= x <= width and 0 <= y <= height):
        return None
    column = ("left", "center", "right")[min(2, int(3 * x / width))]
    row = ("upper", "middle", "lower")[min(2, int(3 * y / height))]
    if row == "middle" and column == "center":
        return "center of frame"
    return f"{row}-{column} of frame" if row != "middle" else f"middle-{column} of frame"


def evidence_summary(
    *,
    provenance: dict,
    tracks: list[dict],
    events: list[dict],
    incidents: list[dict],
    duration_seconds: float,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Summarize which candidate interactions warrant human review and why."""

    unique_events = deduplicate_events(events)
    object_ids: dict[str, set[int]] = {"vehicle": set(), "pedestrian": set()}
    for record in tracks:
        kind = record.get("object_type")
        if kind in object_ids and record.get("track_id") is not None:
            object_ids[kind].add(int(record["track_id"]))
    severity = Counter(str(event.get("severity", "")).upper() for event in unique_events)
    patterns = Counter(interaction_pattern(event) for event in unique_events)
    reviews = Counter(str(incident.get("review_status", "Uncertain")) for incident in incidents)
    pair_counts = Counter(event_pair_key(event) for event in unique_events)
    incident_predictions = {
        incident.get("associated_prediction_event_id"): incident
        for incident in incidents
        if incident.get("associated_prediction_event_id")
    }
    regions = Counter(
        region
        for region in (frame_region(event.get("conflict_point"), width, height) for event in unique_events)
        if region
    )

    review_items: list[dict[str, Any]] = []
    for event in unique_events:
        reasons = []
        if str(event.get("severity", "")).upper() == "HIGH":
            reasons.append("HIGH-priority timing")
        linked = incident_predictions.get(event.get("event_id"))
        if linked is not None:
            reasons.append("preceded a suspected collision")
            if linked.get("review_status") == "Confirmed Incident":
                reasons.append("operator confirmed that incident")
        pair = event_pair_key(event)
        if pair is not None and pair_counts[pair] > 1:
            reasons.append("same pair flagged repeatedly")
        if not reasons:
            reasons.append("qualifying warning; lower priority")
        review_items.append(
            {
                "kind": "Warning",
                "id": str(event.get("event_id", "—")),
                "time": format_timestamp(
                    event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
                ),
                "pattern": PATTERN_LABELS[interaction_pattern(event)],
                "priority": str(event.get("severity", "—")).upper(),
                "location": frame_region(event.get("conflict_point"), width, height) or "—",
                "why_review": "; ".join(reasons),
            }
        )
    for incident in incidents:
        status = str(incident.get("review_status", "Uncertain"))
        review_items.append(
            {
                "kind": "Suspected incident",
                "id": str(incident.get("incident_id", "—")),
                "time": format_timestamp(incident.get("timestamp_seconds")),
                "pattern": "Contact + motion response",
                "priority": "REVIEW",
                "location": frame_region(incident.get("contact_point"), width, height) or "—",
                "why_review": f"{int(incident.get('evidence_signal_count', 0))} evidence signals; "
                f"operator decision: {status}",
            }
        )
    review_items.sort(key=lambda item: item["time"])
    return {
        "source_label": str(provenance.get("label", "Unknown source")),
        "data_source": str(provenance.get("data_source", "unknown")),
        "source_summary": str(provenance.get("summary", "")),
        "duration": format_timestamp(duration_seconds),
        "vehicles_tracked": len(object_ids["vehicle"]),
        "pedestrians_tracked": len(object_ids["pedestrian"]),
        "warnings_total": len(unique_events),
        "warnings_by_priority": {key: severity.get(key, 0) for key in ("HIGH", "MEDIUM", "LOW")},
        "patterns": {PATTERN_LABELS[key]: count for key, count in patterns.most_common()},
        "pattern_keys": sorted(patterns),
        "incidents_total": len(incidents),
        "incident_reviews": {
            "Confirmed": reviews.get("Confirmed Incident", 0),
            "Dismissed": reviews.get("False Alarm", 0),
            "Uncertain": reviews.get("Uncertain", 0),
        },
        "busiest_region": regions.most_common(1)[0][0] if regions else None,
        "review_items": review_items,
    }


@dataclass(frozen=True)
class CrossingAssumptions:
    unit: str = "ft"  # "ft" or "m"
    current_distance: float = 60.0
    proposed_distance: float = 40.0
    walking_speed: float = 3.5
    slower_walking_speed: float = 2.5
    start_up_seconds: float = 2.0


def _change_words(amount: float, unit: str, less: str, more: str) -> str:
    """Direction-aware wording for a current-minus-hypothetical amount."""

    if round(amount, 1) == 0:
        return "no change"
    return f"{abs(amount):.1f}{unit} {less if amount > 0 else more}"


def crossing_comparison(assumptions: CrossingAssumptions) -> dict[str, Any]:
    """Arithmetic crossing-time illustration under explicit user assumptions."""

    values = asdict(assumptions)
    for key in ("current_distance", "proposed_distance", "walking_speed", "slower_walking_speed"):
        if not (_number(values[key]) or 0.0) > 0:
            raise ValueError(f"{key.replace('_', ' ')} must be greater than zero.")
    if (_number(assumptions.start_up_seconds) or 0.0) < 0:
        raise ValueError("start-up time cannot be negative.")
    if assumptions.unit not in {"ft", "m"}:
        raise ValueError("unit must be 'ft' or 'm'.")

    def crossing_time(distance: float, speed: float) -> float:
        return assumptions.start_up_seconds + distance / speed

    rows = []
    for label, speed in (
        ("Typical walking speed", assumptions.walking_speed),
        ("Slower walking speed", assumptions.slower_walking_speed),
    ):
        current = crossing_time(assumptions.current_distance, speed)
        proposed = crossing_time(assumptions.proposed_distance, speed)
        in_road_current = assumptions.current_distance / speed
        in_road_proposed = assumptions.proposed_distance / speed
        rows.append(
            {
                "walker": label,
                "speed": round(speed, 2),
                "current_seconds": round(current, 1),
                "proposed_seconds": round(proposed, 1),
                "difference_seconds": round(current - proposed, 1),
                "in_roadway_change_percent": round(
                    100.0 * (in_road_current - in_road_proposed) / in_road_current, 1
                ),
            }
        )
        row = rows[-1]
        row["difference_text"] = _change_words(row["difference_seconds"], " s", "shorter", "longer")
        row["in_roadway_change_text"] = _change_words(
            row["in_roadway_change_percent"], "%", "less time", "more time"
        )
    return {
        "assumptions": values,
        "distance_change": round(assumptions.current_distance - assumptions.proposed_distance, 1),
        "rows": rows,
        "boundary": CROSSING_BOUNDARY,
        "hypothesis": HYPOTHESIS_STATEMENT,
    }


BASE_CHECKLIST = [
    ("measure_crossing", "Measure curb-to-curb crossing distance on each leg and record lane widths.",
     "Replaces the assumed distances above with field measurements."),
    ("observation_log", "Record date, time, weather, lighting, and camera position for every observation.",
     "Makes repeated observations comparable."),
    ("repeat_periods", "Repeat observation on several days, including peak and off-peak periods.",
     "One clip cannot show whether a pattern is typical."),
    ("accessibility", "Check curb ramps, detectable warnings, pushbutton reach, and crossing signal timing.",
     "Accessibility gaps affect slower walkers most."),
    ("community_input", "Talk with people who use the intersection daily (residents, crossing guards, bus riders).",
     "Local experience explains context the camera cannot see."),
]

PATTERN_CHECKLIST = {
    "crossing": ("crossing_rightofway",
                 "At flagged crossing-path moments, note who had right-of-way and whether sight lines "
                 "were blocked (parked vehicles, vegetation, building corners).",
                 "Crossing-path warnings were flagged in this footage."),
    "following": ("following_braking",
                  "On the flagged approach, observe queues and sudden stops and note what triggered braking "
                  "(pedestrian, turning vehicle, signal change).",
                  "Same-direction following warnings were flagged in this footage."),
    "opposing": ("turning_conflicts",
                 "Observe turning movements across opposing traffic and the gaps drivers accept.",
                 "Opposing or turning-path warnings were flagged in this footage."),
    "stationary": ("stopped_vehicles",
                   "Note why vehicles stop where they do (loading, queue spillback, blocked lane).",
                   "Approaches to stopped vehicles were flagged in this footage."),
}


def checklist_items(summary: dict[str, Any]) -> list[dict[str, str]]:
    """Practical follow-up observations, ordered evidence-driven first."""

    items: list[dict[str, str]] = []
    for key in summary.get("pattern_keys", []):
        if key in PATTERN_CHECKLIST:
            item_id, text, why = PATTERN_CHECKLIST[key]
            items.append({"id": item_id, "text": text, "why": why})
    if summary.get("incidents_total"):
        items.append(
            {
                "id": "incident_records",
                "text": "Ask whether the responsible agency has its own records for the flagged time; "
                "do not assume a crash occurred.",
                "why": "A suspected-incident candidate was found and needs independent confirmation.",
            }
        )
    if summary.get("pedestrians_tracked"):
        items.append(
            {
                "id": "pedestrian_counts",
                "text": "Count pedestrian crossings by leg and time of day, including crossings outside "
                "the crosswalk.",
                "why": "Pedestrians were tracked in this footage.",
            }
        )
    items.extend({"id": item_id, "text": text, "why": why} for item_id, text, why in BASE_CHECKLIST)
    return items


def build_brief(
    *,
    summary: dict[str, Any],
    crossing: dict[str, Any],
    checklist: list[dict[str, str]],
    checked_ids: set[str] | list[str],
    notes: str,
    source_filename: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble one structured brief; Markdown and PDF render this same data."""

    checked = set(checked_ids)
    return {
        "title": "NearMiss Community Review Brief",
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_filename": source_filename,
        "summary": summary,
        "crossing": crossing,
        "checklist": [{**item, "done": item["id"] in checked} for item in checklist],
        "notes": notes.strip(),
        "boundaries": [DATA_BOUNDARY, CROSSING_BOUNDARY, HYPOTHESIS_STATEMENT],
    }


def _source_line(brief: dict[str, Any]) -> str:
    summary = brief["summary"]
    line = f"{summary['source_label']} ({summary['data_source']}): {brief['source_filename']}"
    return line


def brief_markdown(brief: dict[str, Any]) -> str:
    summary, crossing = brief["summary"], brief["crossing"]
    unit = crossing["assumptions"]["unit"]
    lines = [f"# {brief['title']}", ""]
    if summary["data_source"] == "synthetic_demo":
        lines += ["> **SYNTHETIC DEMO** — generated footage and scripted tracks; "
                  "not a real location, real traffic, or a real incident.", ""]
    lines += [
        f"- Source: {_source_line(brief)}",
        f"- Generated: {brief['generated_at']}",
        f"- {summary['source_summary']}",
        "",
        "## Evidence summary",
        "",
        f"- Footage analyzed: {summary['duration']}",
        f"- Vehicles tracked: {summary['vehicles_tracked']}; pedestrians tracked: "
        f"{summary['pedestrians_tracked']}",
        f"- Potential-conflict warnings: {summary['warnings_total']} "
        f"(HIGH {summary['warnings_by_priority']['HIGH']}, MEDIUM "
        f"{summary['warnings_by_priority']['MEDIUM']}, LOW {summary['warnings_by_priority']['LOW']})",
        f"- Suspected incidents: {summary['incidents_total']} (confirmed "
        f"{summary['incident_reviews']['Confirmed']}, dismissed "
        f"{summary['incident_reviews']['Dismissed']}, uncertain "
        f"{summary['incident_reviews']['Uncertain']})",
    ]
    if summary["patterns"]:
        lines.append(
            "- Patterns: " + ", ".join(f"{name} ({count})" for name, count in summary["patterns"].items())
        )
    if summary["busiest_region"]:
        lines.append(f"- Most warnings located: {summary['busiest_region']} (camera image, not an address)")
    lines += ["", "## Interactions that warrant human review", ""]
    if summary["review_items"]:
        lines += ["| Time | Type | Pattern | Priority | Frame location | Why review |",
                  "|---|---|---|---|---|---|"]
        lines += [
            f"| {item['time']} | {item['kind']} | {item['pattern']} | {item['priority']} | "
            f"{item['location']} | {item['why_review']} |"
            for item in summary["review_items"]
        ]
    else:
        lines.append("No qualifying warnings or suspected incidents. A zero count is not proof of safety.")
    lines += [
        "",
        "## Crossing-distance illustration (assumptions, not measurements)",
        "",
        f"- Current crossing distance: {crossing['assumptions']['current_distance']:g} {unit}",
        f"- Hypothetical crossing distance: {crossing['assumptions']['proposed_distance']:g} {unit}",
        f"- Start-up time: {crossing['assumptions']['start_up_seconds']:g} s",
        "",
        f"| Walker | Speed ({unit}/s) | Current (s) | Hypothetical (s) | Hypothetical vs current | Time in roadway |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row['walker']} | {row['speed']:g} | {row['current_seconds']:.1f} | "
        f"{row['proposed_seconds']:.1f} | {row['difference_text']} | "
        f"{row['in_roadway_change_text']} |"
        for row in crossing["rows"]
    ]
    lines += ["", f"_{crossing['boundary']}_", "", f"**{crossing['hypothesis']}**", "",
              "## Follow-up observation checklist", ""]
    lines += [
        f"- [{'x' if item['done'] else ' '}] {item['text']} — _{item['why']}_"
        for item in brief["checklist"]
    ]
    if brief["notes"]:
        lines += ["", "## Reviewer notes", "", brief["notes"]]
    lines += ["", "## Boundaries", ""] + [f"- {text}" for text in brief["boundaries"]]
    return "\n".join(lines) + "\n"


def brief_pdf(brief: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    summary, crossing = brief["summary"], brief["crossing"]
    unit = crossing["assumptions"]["unit"]
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch, title=brief["title"], author="NearMiss",
    )
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    small = ParagraphStyle("BriefSmall", parent=body, fontSize=8, leading=10)
    banner = ParagraphStyle("BriefBanner", parent=body, backColor=colors.HexColor("#F2A93B"),
                            textColor=colors.HexColor("#111111"), borderPadding=6, fontSize=10)
    section = ParagraphStyle("BriefSection", parent=styles["Heading2"],
                             textColor=colors.HexColor("#7A4E0B"), spaceBefore=10)

    def paragraph(text: str, style=body) -> Paragraph:
        return Paragraph(escape(str(text)), style)

    def table(rows: list[list[str]], widths: list[float]) -> Table:
        cells = [[Paragraph(escape(str(cell)), small) for cell in row] for row in rows]
        result = Table(cells, colWidths=[width * inch for width in widths], repeatRows=1)
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4E3C3")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A8A29E")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return result

    story = [Paragraph(escape(brief["title"]), styles["Title"])]
    if summary["data_source"] == "synthetic_demo":
        story += [paragraph("SYNTHETIC DEMO — generated footage and scripted tracks; not a real "
                            "location, real traffic, or a real incident.", banner), Spacer(1, 8)]
    story += [
        paragraph(f"Source: {_source_line(brief)}"),
        paragraph(f"Generated: {brief['generated_at']}"),
        paragraph(summary["source_summary"], small),
        Paragraph("Evidence summary", section),
        table(
            [
                ["Measure", "Value"],
                ["Footage analyzed", summary["duration"]],
                ["Vehicles / pedestrians tracked",
                 f"{summary['vehicles_tracked']} / {summary['pedestrians_tracked']}"],
                ["Potential-conflict warnings",
                 f"{summary['warnings_total']} (HIGH {summary['warnings_by_priority']['HIGH']}, MEDIUM "
                 f"{summary['warnings_by_priority']['MEDIUM']}, LOW {summary['warnings_by_priority']['LOW']})"],
                ["Suspected incidents",
                 f"{summary['incidents_total']} (confirmed {summary['incident_reviews']['Confirmed']}, "
                 f"dismissed {summary['incident_reviews']['Dismissed']}, uncertain "
                 f"{summary['incident_reviews']['Uncertain']})"],
                ["Patterns", ", ".join(f"{k} ({v})" for k, v in summary["patterns"].items()) or "—"],
                ["Most warnings located", summary["busiest_region"] or "—"],
            ],
            [2.3, 4.7],
        ),
        Paragraph("Interactions that warrant human review", section),
    ]
    if summary["review_items"]:
        story.append(table(
            [["Time", "Type", "Pattern", "Priority", "Frame location", "Why review"]]
            + [[item["time"], item["kind"], item["pattern"], item["priority"], item["location"],
                item["why_review"]] for item in summary["review_items"]],
            [0.6, 1.0, 1.3, 0.7, 1.1, 2.3],
        ))
    else:
        story.append(paragraph("No qualifying warnings or suspected incidents. A zero count is not "
                               "proof of safety."))
    assumptions = crossing["assumptions"]
    story += [
        Paragraph("Crossing-distance illustration (assumptions, not measurements)", section),
        paragraph(f"Current crossing distance: {assumptions['current_distance']:g} {unit}; hypothetical: "
                  f"{assumptions['proposed_distance']:g} {unit}; start-up time "
                  f"{assumptions['start_up_seconds']:g} s."),
        table(
            [["Walker", f"Speed ({unit}/s)", "Current (s)", "Hypothetical (s)",
              "Hypothetical vs current", "Time in roadway"]]
            + [[row["walker"], f"{row['speed']:g}", f"{row['current_seconds']:.1f}",
                f"{row['proposed_seconds']:.1f}", row["difference_text"],
                row["in_roadway_change_text"]] for row in crossing["rows"]],
            [1.6, 0.9, 0.9, 1.1, 1.0, 1.5],
        ),
        Spacer(1, 4),
        paragraph(crossing["boundary"], small),
        paragraph(crossing["hypothesis"]),
        Paragraph("Follow-up observation checklist", section),
    ]
    story += [
        paragraph(f"[{'x' if item['done'] else ' '}] {item['text']} — {item['why']}", small)
        for item in brief["checklist"]
    ]
    if brief["notes"]:
        story += [Paragraph("Reviewer notes", section), paragraph(brief["notes"])]
    story += [Paragraph("Boundaries", section)] + [paragraph(text, small) for text in brief["boundaries"]]
    document.build(story)
    return output.getvalue()
