"""Professional PDF generation for source-backed NearMiss safety reports."""

from __future__ import annotations

from io import BytesIO
from math import isfinite
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage

from nearmiss.events import format_timestamp
from nearmiss.safety import deduplicate_events, event_pair_key, safety_statistics


def _image_buffer(image_rgb) -> BytesIO:
    stream = BytesIO()
    PILImage.fromarray(image_rgb).save(stream, format="PNG")
    stream.seek(0)
    return stream


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _measurement(value: Any) -> str:
    number = _safe_number(value)
    return "—" if number is None else f"{number:.3f}s"


def generate_safety_report(
    *,
    source_filename: str,
    duration_seconds: float,
    tracks: list[dict],
    events: list[dict],
    heatmap_rgb,
    review_labels: dict[str, str] | None = None,
    event_frames: dict[str, Any] | None = None,
) -> bytes:
    """Build a PDF using only the supplied processed tracks/events and frames."""

    try:
        from reportlab.graphics.shapes import Circle, Drawing, Line, String
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - environment dependency
        raise RuntimeError("ReportLab is required to generate safety reports.") from exc

    unique_events = deduplicate_events(events)
    statistics = safety_statistics(tracks, unique_events, duration_seconds)
    reviews = review_labels or {}
    frames = event_frames or {}
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="NearMiss Intersection Safety Report",
        author="NearMiss",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="NearMissTitle",
            parent=styles["Title"],
            textColor=colors.HexColor("#0f2744"),
            fontSize=23,
            leading=27,
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#0f5f75"),
            fontSize=15,
            leading=18,
            spaceBefore=10,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallCenter",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            fontSize=8,
            textColor=colors.HexColor("#475569"),
        )
    )
    story = [
        Paragraph("NearMiss Intersection Safety Report", styles["NearMissTitle"]),
        Paragraph(f"Source video: {escape(str(source_filename))}", styles["BodyText"]),
        Paragraph(
            "Experimental computer-vision decision support. Detected conflicts are "
            "heuristic candidates, not validated crashes or collision probabilities.",
            styles["Italic"],
        ),
        Paragraph("1. Executive Summary", styles["Section"]),
    ]
    summary_data = [
        ["Video duration", format_timestamp(duration_seconds)],
        ["Vehicles tracked", str(statistics["vehicles_tracked"])],
        ["Potential conflicts", str(statistics["total_conflicts"])],
        ["HIGH-priority flags", str(statistics["high_conflicts"])],
        ["Conflicts per minute", f'{statistics["conflicts_per_minute"]:.2f}'],
    ]
    summary_table = Table(summary_data, colWidths=[2.1 * inch, 2.0 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 8)])
    if unique_events:
        story.append(
            Paragraph(
                f"The analysis identified {len(unique_events)} unique candidate interaction(s). "
                "Each should be reviewed against the source footage before any engineering conclusion.",
                styles["BodyText"],
            )
        )
    else:
        story.append(
            Paragraph(
                "No qualifying conflict events were returned for this video and configuration. "
                "This measured zero must not be interpreted as proof that the intersection is safe.",
                styles["BodyText"],
            )
        )

    story.extend(
        [
            Paragraph("2. Intersection Conflict Heatmap", styles["Section"]),
            Image(_image_buffer(heatmap_rgb), width=7.1 * inch, height=2.95 * inch),
            Paragraph(
                "Blue/green indicates lower detected-event density; yellow/red indicates higher "
                "density. White markers are deduplicated conflict locations. No heat coloration "
                "is added when there are no valid event coordinates.",
                styles["SmallCenter"],
            ),
            Paragraph("3. Conflict Statistics", styles["Section"]),
        ]
    )
    average_gap = statistics["average_arrival_gap_seconds"]
    statistics_data = [
        ["LOW", "MEDIUM", "HIGH", "Distinct pairs", "Average arrival gap"],
        [
            statistics["low_conflicts"],
            statistics["medium_conflicts"],
            statistics["high_conflicts"],
            statistics["distinct_vehicle_pairs"],
            "—" if average_gap is None else f"{average_gap:.3f} s",
        ],
    ]
    stats_table = Table(statistics_data, repeatRows=1)
    stats_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f5f75")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([stats_table, Spacer(1, 10)])

    timeline = Drawing(500, 95)
    timeline.add(Line(30, 36, 470, 36, strokeColor=colors.HexColor("#64748b")))
    timeline.add(String(30, 17, "0:00", fontSize=8))
    timeline.add(String(440, 17, format_timestamp(duration_seconds), fontSize=8))
    severity_y = {"LOW": 48, "MEDIUM": 62, "HIGH": 78}
    severity_color = {
        "LOW": colors.HexColor("#eab308"),
        "MEDIUM": colors.HexColor("#f97316"),
        "HIGH": colors.HexColor("#e11d48"),
    }
    for event in unique_events:
        try:
            timestamp = float(
                event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
            )
        except (TypeError, ValueError):
            continue
        fraction = min(1.0, max(0.0, timestamp / max(duration_seconds, 1e-9)))
        severity = str(event.get("severity", "LOW")).upper()
        x = 30 + 440 * fraction
        y = severity_y.get(severity, 48)
        timeline.add(Circle(x, y, 4, fillColor=severity_color.get(severity), strokeColor=None))
    for severity, y in severity_y.items():
        timeline.add(String(2, y - 3, severity[0], fontSize=7))
    story.extend([timeline, Paragraph("Timeline uses first alert timestamps.", styles["SmallCenter"])])

    headers = ["Event", "First alert", "Pair", "Risk", "Gap", "TTC", "Review"]
    rows = [headers]
    for event in unique_events:
        event_id = str(event.get("event_id", "—"))
        pair = event_pair_key(event)
        rows.append(
            [
                event_id,
                format_timestamp(event.get("first_alert_timestamp_seconds")),
                "—" if pair is None else f"#{pair[0]} / #{pair[1]}",
                str(event.get("severity", "—")),
                _measurement(event.get("arrival_time_gap_seconds")),
                _measurement(event.get("time_to_conflict_seconds")),
                reviews.get(event_id, "Uncertain"),
            ]
        )
    event_table = Table(rows, repeatRows=1, colWidths=[0.8*inch, 0.8*inch, 0.8*inch, 0.6*inch, 0.65*inch, 0.65*inch, 1.15*inch])
    event_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f5f75")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([Spacer(1, 8), event_table, PageBreak(), Paragraph("4. Flagged Events", styles["Section"])])
    if not unique_events:
        story.append(Paragraph("No flagged events are available for evidence review.", styles["BodyText"]))
    for event in unique_events:
        event_id = str(event.get("event_id", "event"))
        pair = event_pair_key(event)
        story.append(
            Paragraph(
                f"<b>{escape(event_id)}</b> · {format_timestamp(event.get('first_alert_timestamp_seconds'))} · "
                f"{escape(str(event.get('severity', '—')))} · pair {pair or 'unavailable'}",
                styles["BodyText"],
            )
        )
        story.append(
            Paragraph(
                escape(str(event.get("description", "No explanation supplied."))),
                styles["BodyText"],
            )
        )
        if event_id in frames:
            story.append(Image(_image_buffer(frames[event_id]), width=5.6 * inch, height=2.35 * inch))
        story.append(Spacer(1, 8))

    story.extend(
        [
            Paragraph("5. Limitations and Suggested Review", styles["Section"]),
            Paragraph(
                "NearMiss uses pretrained object detection, ByteTrack identities, and constant-velocity "
                "image-coordinate projections. Uncalibrated pixels do not measure physical distance, "
                "real speed, or collision probability. Missed detections, identity changes, occlusion, "
                "camera perspective, moving cameras, lighting, and driver braking or turning can change "
                "results. A high candidate count does not by itself establish that a location is dangerous. "
                "Review flagged footage, rejected-pair diagnostics, camera comparability, and roadway context "
                "before considering field observation or engineering action.",
                styles["BodyText"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()
