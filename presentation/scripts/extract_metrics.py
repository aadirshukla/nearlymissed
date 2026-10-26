"""Derive presentation facts from the NearMiss synthetic demo pipeline.

Runs the same steps the Analysis page runs for the guided demo (scripted
tracks -> full-frame zone -> detect_conflicts -> normalize_events ->
deduplicate_events -> detect_suspected_collisions -> Street Lab summary) with
the default settings, and writes one JSON file that the deck and the video
read. Nothing is written to the app cache or the review database.

Usage (from the repo root):
    .venv/bin/python presentation/scripts/extract_metrics.py          # metrics only
    .venv/bin/python presentation/scripts/extract_metrics.py --clips  # + demo clips
    .venv/bin/python presentation/scripts/extract_metrics.py --tests  # + pytest summary

``--clips`` regenerates the synthetic source clip and the app's annotated
render in a throwaway cache under .scratch/ (never the app's own cache) and
copies them to presentation/video/public/clips/ and presentation/deck/assets/.

Writes presentation/data/demo-metrics.json and copies it to
presentation/deck/data/ and presentation/video/src/data/.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conflict_detector import detect_conflicts  # noqa: E402
from nearmiss import demo, streetlab  # noqa: E402
from nearmiss.config import DEFAULT_CONFLICT_CONFIG  # noqa: E402
from nearmiss.events import format_timestamp, normalize_events  # noqa: E402
from nearmiss.explain import explain_event  # noqa: E402
from nearmiss.geometry import enrich_tracks_with_zone  # noqa: E402
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG, detect_suspected_collisions  # noqa: E402
from nearmiss.safety import deduplicate_events  # noqa: E402

OUT = ROOT / "presentation" / "data" / "demo-metrics.json"
COPIES = [
    ROOT / "presentation" / "deck" / "data" / "demo-metrics.json",
    ROOT / "presentation" / "video" / "src" / "data" / "demo-metrics.json",
]


def _round(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _settings_digest(conflict: dict, collision: dict) -> str:
    encoded = json.dumps({"conflict": conflict, "collision": collision}, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def pipeline():
    tracks = demo.synthetic_tracks()
    meta = demo.demo_metadata()
    zone = [[0.0, 0.0], [float(meta.width), 0.0], [float(meta.width), float(meta.height)], [0.0, float(meta.height)]]
    conflict_config = {**DEFAULT_CONFLICT_CONFIG, "zone_is_user_defined": False}
    collision_config = dict(DEFAULT_COLLISION_CONFIG)

    raw = detect_conflicts(enrich_tracks_with_zone(tracks, zone), zone, conflict_config)
    events, warnings = normalize_events(raw, meta.fps)
    events = deduplicate_events(events)
    incidents = detect_suspected_collisions(tracks, events, demo.DEMO_VIDEO_ID, config=collision_config)
    for incident in incidents:
        incident.setdefault("review_status", "Uncertain")
        incident.setdefault("camera_id", demo.DEMO_CAMERA_ID)
        incident.setdefault("data_source", demo.DEMO_DATA_SOURCE)
    return tracks, meta, zone, conflict_config, collision_config, events, warnings, incidents


def build() -> dict:
    tracks, meta, zone, conflict_config, collision_config, events, warnings, incidents = pipeline()
    summary = streetlab.evidence_summary(
        provenance=demo.DEMO_PROVENANCE,
        tracks=tracks,
        events=events,
        incidents=incidents,
        duration_seconds=meta.duration_seconds,
        width=meta.width,
        height=meta.height,
    )
    crossing = streetlab.crossing_comparison(streetlab.CrossingAssumptions())

    rows_by_frame: dict[tuple[int, int], dict] = {
        (int(row["frame_index"]), int(row["track_id"])): row for row in tracks
    }

    def measurement(event: dict) -> dict:
        """The event's representative row: the frame its ETAs and gap were measured on.

        This is not the first alert. The app's explanation (and the diagrams)
        quote the ETAs, gap and separation from this one frame, so the
        diagrams must place both road users at this frame, not at the first alert.
        """

        frame = int(event["frame_index"])
        ids = [event.get("vehicle_a_track_id"), event.get("vehicle_b_track_id")]
        boxes, anchors = {}, {}
        for track_id in ids:
            row = rows_by_frame.get((frame, int(track_id)))
            if row is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in row["bbox"])
            boxes[str(track_id)] = [_round(v, 1) for v in (x1, y1, x2, y2)]
            # Same anchor as conflict_detector._bottom_center.
            anchors[str(track_id)] = [_round((x1 + x2) / 2.0, 1), _round(y2, 1)]
        return {
            "seconds": _round(event.get("timestamp_seconds")),
            "frame": frame,
            "clock": format_timestamp(event.get("timestamp_seconds")),
            "eta_seconds": [_round(event.get("vehicle_a_eta_seconds")), _round(event.get("vehicle_b_eta_seconds"))],
            "boxes": boxes,
            "anchors": anchors,
        }

    def event_row(event: dict) -> dict:
        first_alert = event.get("first_alert_timestamp_seconds", event.get("timestamp_seconds"))
        return {
            "event_id": event.get("event_id"),
            "severity": str(event.get("severity", "")).upper(),
            "geometry": event.get("conflict_geometry"),
            "track_ids": [event.get("vehicle_a_track_id"), event.get("vehicle_b_track_id")],
            "classes": [event.get("vehicle_a_class"), event.get("vehicle_b_class")],
            "first_alert_seconds": _round(first_alert),
            "first_alert_clock": format_timestamp(first_alert),
            "first_alert_frame": event.get("start_frame_index"),
            "measurement": measurement(event),
            "arrival_gap_seconds": _round(event.get("arrival_time_gap_seconds")),
            "time_to_conflict_seconds": _round(event.get("time_to_conflict_seconds")),
            "time_headway_seconds": _round(event.get("time_headway_seconds")),
            "path_separation_pixels": _round(event.get("path_separation_pixels"), 1),
            "closing_speed_pixels_per_second": _round(event.get("closing_speed_pixels_per_second"), 1),
            "persistence_frames": event.get("persistence_frames"),
            "conflict_point": [_round(v, 1) for v in (event.get("conflict_point") or [])],
            "explanation": explain_event(event, conflict_config),
        }

    def incident_row(incident: dict) -> dict:
        return {
            "incident_id": incident.get("incident_id"),
            "track_ids": [incident.get("vehicle_a_track_id"), incident.get("vehicle_b_track_id")],
            "first_contact_seconds": _round(incident.get("timestamp_seconds")),
            "first_contact_clock": format_timestamp(incident.get("timestamp_seconds")),
            "evidence_signal_count": incident.get("evidence_signal_count"),
            "detection_signals": incident.get("detection_signals"),
            "contact_persistence_frames": incident.get("contact_persistence_frames"),
            "associated_prediction_event_id": incident.get("associated_prediction_event_id"),
            "prediction_lead_seconds": _round(incident.get("prediction_lead_seconds")),
            "contact_point": [_round(v, 1) for v in (incident.get("contact_point") or [])],
        }

    # Full scripted paths every 0.05 s (null while inactive) so the diagrams
    # replay the same geometry the detectors saw.
    step = 1.0 / meta.fps
    actors = []
    for actor in demo.ACTORS:
        samples = []
        for index in range(meta.frame_count):
            t = index * step
            if actor.start_time <= t <= actor.end_time:
                samples.append([_round(c, 1) for c in demo.actor_center(actor, t)])
            else:
                samples.append(None)
        b, g, r = actor.color_bgr
        actors.append({
            "track_id": actor.track_id,
            "class_name": actor.class_name,
            "size": list(actor.size),
            "direction": list(actor.direction),
            "color": f"#{r:02x}{g:02x}{b:02x}",
            "sample_step_seconds": step,
            "samples": samples,
        })

    return {
        "generated_by": "presentation/scripts/extract_metrics.py",
        "source": {
            "label": demo.DEMO_LABEL,
            "data_source": demo.DEMO_DATA_SOURCE,
            "video_id": demo.DEMO_VIDEO_ID,
            "camera_id": demo.DEMO_CAMERA_ID,
            "summary": demo.DEMO_PROVENANCE["summary"],
            "pipeline_boundary": demo.DEMO_PROVENANCE["pipeline_boundary"],
            "frame": {"width": meta.width, "height": meta.height, "fps": meta.fps,
                      "frames": meta.frame_count, "duration_seconds": meta.duration_seconds},
            "road": {"horizontal_y": list(demo.ROAD_H), "vertical_x": list(demo.ROAD_V)},
        },
        "settings": {
            "digest": _settings_digest(conflict_config, collision_config),
            "analysis_mode": conflict_config["analysis_mode"],
            "prediction_horizon_seconds": conflict_config["prediction_horizon_seconds"],
            "high_time_gap_seconds": conflict_config["high_time_gap_seconds"],
            "medium_time_gap_seconds": conflict_config["medium_time_gap_seconds"],
            "low_time_gap_seconds": conflict_config["low_time_gap_seconds"],
            "high_persistence_frames": conflict_config["high_persistence_frames"],
            "min_track_age_frames": conflict_config["min_track_age_frames"],
            "contact_persistence_frames": collision_config["contact_persistence_frames"],
            "minimum_evidence_signals": collision_config["minimum_evidence_signals"],
        },
        "tracks": {"rows": len(tracks), "vehicles": summary["vehicles_tracked"],
                   "pedestrians": summary["pedestrians_tracked"]},
        "normalize_warnings": warnings,
        "events": [event_row(e) for e in sorted(events, key=lambda e: e.get("first_alert_timestamp_seconds", e.get("timestamp_seconds", 0)))],
        "incidents": [incident_row(i) for i in incidents],
        "streetlab": {
            "warnings_total": summary["warnings_total"],
            "warnings_by_priority": summary["warnings_by_priority"],
            "patterns": summary["patterns"],
            "incidents_total": summary["incidents_total"],
            "busiest_region": summary["busiest_region"],
            "review_items": summary["review_items"],
            "crossing": crossing,
            "checklist_count": len(streetlab.checklist_items(summary)),
        },
        "actors": actors,
    }


def render_clips() -> list[Path]:
    """Regenerate the demo source and annotated clips in a scratch cache."""

    import nearmiss.video as video_module

    scratch = ROOT / ".scratch" / "nearmiss_cache"
    video_module.CACHE_ROOT = scratch
    source_path, artifacts = demo.ensure_demo_assets()
    tracks, _meta, _zone, _cc, _col, events, _w, incidents = pipeline()
    # The app passes the user zone (empty for the demo) and default overlays.
    annotated = video_module.render_annotated_video(
        artifacts, tracks, [], trail_length=30, events=events, incidents=incidents
    )
    targets = [ROOT / "presentation" / "video" / "public" / "clips",
               ROOT / "presentation" / "deck" / "assets" / "clips"]
    written = []
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        for src, name in ((source_path, "demo-source.mp4"), (annotated, "demo-annotated.mp4")):
            shutil.copyfile(src, target / name)
            written.append(target / name)
    # Lossless-enough 30 fps copy for frame-exact use in the 30 fps video timeline.
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        out = targets[0] / "demo-annotated-30fps.mp4"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(annotated), "-vf", "fps=30",
                        "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
        written.append(out)
    return written


def run_tests() -> dict:
    """Run the repo test suite once and keep only its summary line."""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                            cwd=ROOT, capture_output=True, text=True)
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    # The team is in America/Los_Angeles; the date shown on slides is that local date.
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return {"summary": lines[-1] if lines else "no output", "exit_code": result.returncode,
            "run_at": now.isoformat(timespec="seconds"),
            "run_date_local": now.strftime("%Y-%m-%d"),
            "time_zone": "America/Los_Angeles"}


def main() -> None:
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if "--clips" in sys.argv:
        for path in render_clips():
            print(f"clip {path.relative_to(ROOT)}")
    data = build()
    # Test results are kept from the last --tests run unless rerun now.
    data["tests"] = run_tests() if "--tests" in sys.argv else previous.get("tests")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for path in [OUT, *COPIES]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    # The deck may be opened from file://, where fetch() of JSON is blocked.
    script = ROOT / "presentation" / "deck" / "data" / "demo-metrics.js"
    script.write_text("window.NEARMISS_METRICS = " + text.strip() + ";\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} (+{len(COPIES)} copies); "
          f"{len(data['events'])} warnings, {len(data['incidents'])} suspected incident(s), "
          f"settings {data['settings']['digest']}")


if __name__ == "__main__":
    main()
