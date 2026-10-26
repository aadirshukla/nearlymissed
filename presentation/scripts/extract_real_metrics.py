"""Derive the deck's real-footage facts from the bundled real traffic sample.

No detection or tracking is run. The cached YOLO11n + ByteTrack rows in
static/real-demo/tracks.json go through the same post-processing the app uses
(full-frame zone -> enrich_tracks_with_zone -> detect_conflicts ->
normalize_events -> deduplicate_events -> detect_suspected_collisions) at
DEFAULT_CONFLICT_CONFIG with zone_is_user_defined=False. The counts must match
static/real-demo/manifest.json or the script stops.

The footage is ordinary traffic with no ground-truth labels. Every warning and
suspected contact here is an unverified, experimental candidate.

Usage (from the repo root):
    .venv/bin/python presentation/scripts/extract_real_metrics.py          # data, stills, assets
    .venv/bin/python presentation/scripts/extract_real_metrics.py --tests  # + pytest summary

Writes presentation/data/real-metrics.json, presentation/deck/data/real-metrics.js
and copies the clip, exact-frame stills, host captures and the community brief
into presentation/deck/assets/real/. Does not touch the app, its cache or the
165-second film.
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

import cv2  # noqa: E402

from conflict_detector import detect_conflicts  # noqa: E402
from nearmiss import streetlab  # noqa: E402
from nearmiss.config import DEFAULT_CONFLICT_CONFIG  # noqa: E402
from nearmiss.events import format_timestamp, normalize_events  # noqa: E402
from nearmiss.explain import explain_event, interaction_pattern, PATTERN_LABELS  # noqa: E402
from nearmiss.geometry import enrich_tracks_with_zone  # noqa: E402
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG, detect_suspected_collisions  # noqa: E402
from nearmiss.safety import deduplicate_events  # noqa: E402

REAL = ROOT / "static" / "real-demo"
CAPTURES = ROOT / ".scratch" / "deck-real-captures"
OUT = ROOT / "presentation" / "data" / "real-metrics.json"
DECK = ROOT / "presentation" / "deck"
ASSETS = DECK / "assets" / "real"

# The one flag the deck follows from first alert to review. Chosen because both
# ETAs fall inside the 2 s look-ahead (not capped), its measurement frame differs
# from its first alert, and the contact detector also flagged the same pair, so
# one real case can be followed through slides 1, 3, 4 and 5.
CASE_EVENT = "conflict-029"
# Host capture of the Investigation page shows this pair (frame 34).
CAPTURE_EVENT = "conflict-007"
SLIDE1_PLAY_FROM = 168      # 7.0 s; the slide plays forward to the first alert and freezes
SLIDE3_PLAY_SECONDS = 1.0   # replay before freezing on the measurement frame
SLIDE5_PLAY_SECONDS = 1.0   # source seconds replayed (at half speed) before first contact


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def r1(v):
    return None if v is None else round(float(v), 1)


def r3(v):
    return None if v is None else round(float(v), 3)


def pipeline(tracks, meta, video_id):
    w, h = float(meta["width"]), float(meta["height"])
    zone = [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]
    config = dict(DEFAULT_CONFLICT_CONFIG, zone_is_user_defined=False)
    raw = detect_conflicts(enrich_tracks_with_zone(tracks, zone), zone, config)
    events, warnings = normalize_events(raw, meta["fps"])
    events = deduplicate_events(events)
    incidents = detect_suspected_collisions(tracks, events, source_video_id=video_id)
    return zone, config, events, warnings, incidents


def extract_frames(video: Path, frames: list[int], prefix: str) -> dict[int, str]:
    """Decode exact frames with OpenCV (sequential read, no seeking error)."""

    wanted = set(frames)
    out = {}
    cap = cv2.VideoCapture(str(video))
    index = 0
    while wanted:
        ok, image = cap.read()
        if not ok:
            break
        if index in wanted:
            name = f"{prefix}-{index:03d}.jpg"
            cv2.imwrite(str(ASSETS / name), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            out[index] = name
            wanted.discard(index)
        index += 1
    cap.release()
    if wanted:
        raise SystemExit(f"could not decode frames {sorted(wanted)} from {video}")
    return out


def run_tests() -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                            cwd=ROOT, capture_output=True, text=True)
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return {"summary": lines[-1] if lines else "no output", "exit_code": result.returncode,
            "run_at": now.isoformat(timespec="seconds"), "time_zone": "America/Los_Angeles",
            "scope": "Code behaviour on synthetic and regression fixtures; not a measure of detector accuracy."}


def main() -> None:
    manifest = json.loads((REAL / "manifest.json").read_text(encoding="utf-8"))
    meta = json.loads((REAL / "metadata.json").read_text(encoding="utf-8"))
    tracks = json.loads((REAL / "tracks.json").read_text(encoding="utf-8"))
    hashes = {
        "source_sha256": sha256(REAL / "source.mp4"),
        "annotated_sha256": sha256(REAL / "annotated.mp4"),
        "tracks_sha256": sha256(REAL / "tracks.json"),
        "metadata_sha256": sha256(REAL / "metadata.json"),
    }
    for key in ("source_sha256", "tracks_sha256", "metadata_sha256"):
        if hashes[key] != manifest[key]:
            raise SystemExit(f"{key} does not match static/real-demo/manifest.json")
    video_id = hashes["source_sha256"]
    fps, n_frames = float(meta["fps"]), int(meta["frame_count"])

    zone, config, events, warnings, incidents = pipeline(tracks, meta, video_id)
    counts = {
        "frames": n_frames,
        "track_rows": len(tracks),
        "track_ids": len({r["track_id"] for r in tracks}),
        "warnings": len(events),
        "suspected_incidents": len(incidents),
    }
    if counts != manifest["counts"]:
        raise SystemExit(f"pipeline counts {counts} differ from manifest {manifest['counts']}")
    by_severity = {s: sum(1 for e in events if str(e.get("severity")).upper() == s) for s in ("HIGH", "MEDIUM", "LOW")}

    rows = {(int(r["frame_index"]), int(r["track_id"])): r for r in tracks}
    classes = {}
    frames: list[list] = [[] for _ in range(n_frames)]
    for r in sorted(tracks, key=lambda r: (r["frame_index"], r["track_id"])):
        tid = int(r["track_id"])
        classes[str(tid)] = r["class_name"]
        frames[int(r["frame_index"])].append([tid, *(r1(v) for v in r["bbox"])])

    def event_row(e: dict) -> dict:
        first = e.get("first_alert_timestamp_seconds", e.get("timestamp_seconds"))
        return {
            "event_id": e["event_id"],
            "severity": str(e["severity"]).upper(),
            "pattern_label": PATTERN_LABELS.get(interaction_pattern(e), interaction_pattern(e)),
            "track_ids": [e["vehicle_a_track_id"], e["vehicle_b_track_id"]],
            "classes": [e["vehicle_a_class"], e["vehicle_b_class"]],
            "first_alert_seconds": r3(first),
            "first_alert_frame": e["start_frame_index"],
            "first_alert_clock": format_timestamp(first),
            "measurement_frame": e["frame_index"],
            "arrival_gap_seconds": r3(e.get("arrival_time_gap_seconds")),
        }

    def incident_row(i: dict) -> dict:
        return {
            "incident_id": i["incident_id"],
            "track_ids": [i["vehicle_a_track_id"], i["vehicle_b_track_id"]],
            "first_contact_seconds": r3(i["timestamp_seconds"]),
            "first_contact_frame": i["frame_index"],
            "first_contact_clock": format_timestamp(i["timestamp_seconds"]),
            "evidence_signal_count": i["evidence_signal_count"],
            "detection_signals": i["detection_signals"],
            "contact_persistence_frames": i["contact_persistence_frames"],
            "associated_prediction_event_id": i.get("associated_prediction_event_id"),
            "prediction_lead_seconds": r3(i.get("prediction_lead_seconds")),
            "contact_point": [r1(v) for v in i.get("contact_point") or []],
            "review_status": i.get("review_status"),
        }

    by_id = {e["event_id"]: e for e in events}
    case = by_id[CASE_EVENT]
    ida, idb = int(case["vehicle_a_track_id"]), int(case["vehicle_b_track_id"])
    mframe = int(case["frame_index"])
    # The event's stored boxes must be tracked rows: the latest observation of each
    # vehicle at or before the measurement frame, within max_observation_age_seconds
    # (a track may miss a frame; the detector then uses its previous row).
    max_age_frames = int(config["max_observation_age_seconds"] * fps + 1e-9)
    observed_frame = {}
    for tid, key in ((ida, "vehicle_a_bbox"), (idb, "vehicle_b_bbox")):
        stored = [round(float(v), 2) for v in case[key]]
        f = next((f for f in range(mframe, mframe - max_age_frames - 1, -1) if (f, tid) in rows), None)
        row = [round(float(v), 2) for v in rows[(f, tid)]["bbox"]] if f is not None else None
        if stored != row:
            raise SystemExit(f"{CASE_EVENT} {key} {stored} != latest tracks row {row} (frame {f}) for measurement frame {mframe}")
        observed_frame[str(tid)] = f
    linked = next((i for i in incidents if i.get("associated_prediction_event_id") == CASE_EVENT), None)
    if linked is None or {int(linked["vehicle_a_track_id"]), int(linked["vehicle_b_track_id"])} != {ida, idb}:
        raise SystemExit(f"no suspected-contact candidate linked to {CASE_EVENT} for the same pair")

    case_out = {
        **event_row(case),
        "measurement": {
            "frame": mframe,
            "seconds": r3(case["timestamp_seconds"]),
            "clock": format_timestamp(case["timestamp_seconds"]),
            "eta_seconds": [r3(case["vehicle_a_eta_seconds"]), r3(case["vehicle_b_eta_seconds"])],
            "boxes": {str(ida): [r1(v) for v in case["vehicle_a_bbox"]], str(idb): [r1(v) for v in case["vehicle_b_bbox"]]},
            "observed_frame": observed_frame,
            # Projection origin and end as stored on the event (smoothed bottom-centre anchors).
            "positions": {str(ida): [r1(v) for v in case["vehicle_a_position"]], str(idb): [r1(v) for v in case["vehicle_b_position"]]},
            "conflict_positions": {str(ida): [r1(v) for v in case["vehicle_a_conflict_position"]], str(idb): [r1(v) for v in case["vehicle_b_conflict_position"]]},
        },
        "conflict_point": [r1(v) for v in case["conflict_point"]],
        "conflict_geometry": case.get("conflict_geometry"),
        "time_to_conflict_seconds": r3(case.get("time_to_conflict_seconds")),
        "path_separation_pixels": r1(case.get("path_separation_pixels")),
        "closing_speed_pixels_per_second": r1(case.get("closing_speed_pixels_per_second")),
        "persistence_frames": case.get("persistence_frames"),
        "high_persistence_frames": case.get("high_persistence_frames"),
        "explanation": explain_event(case, config),
    }
    incident_out = incident_row(linked)

    capture_event = event_row(by_id[CAPTURE_EVENT])

    # Moments the slides play and freeze on. Every freeze frame has an exact still.
    moments = {
        "slide1": {"from_frame": SLIDE1_PLAY_FROM, "freeze_frame": case["start_frame_index"], "rate": 1.0,
                   "meaning": "first alert of the case flag"},
        "slide3": {"from_frame": mframe - round(SLIDE3_PLAY_SECONDS * fps), "freeze_frame": mframe, "rate": 1.0,
                   "meaning": "representative measurement frame of the case flag"},
        "slide5": {"from_frame": linked["frame_index"] - round(SLIDE5_PLAY_SECONDS * fps), "freeze_frame": linked["frame_index"], "rate": 0.5,
                   "meaning": "first box-contact frame of the linked suspected-contact candidate"},
        "slide4": {"poster_frame": case["start_frame_index"]},
    }

    ASSETS.mkdir(parents=True, exist_ok=True)
    for name in ("source.mp4", "annotated.mp4"):
        shutil.copyfile(REAL / name, ASSETS / name)
    still_frames = sorted({m[k] for m in moments.values() for k in ("from_frame", "freeze_frame") if k in m})
    stills = {f: n for f, n in extract_frames(REAL / "source.mp4", still_frames, "source").items()}
    poster = extract_frames(REAL / "annotated.mp4", [moments["slide4"]["poster_frame"]], "annotated")

    captures = {}
    if CAPTURES.exists():
        for path in sorted(CAPTURES.iterdir()):
            if path.suffix == ".png" or path.name == "community-brief.md":
                shutil.copyfile(path, ASSETS / path.name)
                captures[path.name] = sha256(path)
    brief_path = ASSETS / "community-brief.md"
    brief = brief_path.read_text(encoding="utf-8") if brief_path.exists() else None

    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    prov = manifest["provenance"]
    data = {
        "generated_by": "presentation/scripts/extract_real_metrics.py",
        "label": "REAL FOOTAGE + experimental predictions · human review required",
        "source": {
            "title": prov["title"], "creator": prov["creator"], "credit": prov["credit"],
            "source_url": prov["source_url"], "license": prov["license"], "license_url": prov["license_url"],
            "modifications": prov["modifications"],
            "video_id": video_id, **hashes,
            "frame": {"width": meta["width"], "height": meta["height"], "fps": fps, "frames": n_frames,
                      "duration_seconds": meta["duration_seconds"]},
            "ground_truth": None,
            "boundary": "Ordinary traffic with no incident labels. Warnings and contact candidates are unverified; perspective and occlusion produce false alarms. Track IDs are not a verified vehicle count.",
        },
        "pipeline": {
            "inference": "none in this script; cached YOLO11n + ByteTrack rows from tracks.json",
            "steps": ["enrich_tracks_with_zone", "detect_conflicts", "normalize_events", "deduplicate_events", "detect_suspected_collisions"],
            "zone": zone,
            "zone_is_user_defined": False,
            "config": "DEFAULT_CONFLICT_CONFIG",
            "collision_config": "DEFAULT_COLLISION_CONFIG",
            "settings": {k: config[k] for k in ("prediction_horizon_seconds", "high_time_gap_seconds", "medium_time_gap_seconds", "low_time_gap_seconds", "high_persistence_frames")},
            "contact_persistence_frames": DEFAULT_COLLISION_CONFIG["contact_persistence_frames"],
            "matches_manifest_counts": True,
            "normalize_warnings": warnings,
        },
        "counts": {**counts, "warnings_by_severity": by_severity, "confirmed": 0, "notices": 0},
        "case": case_out,
        "case_incident": incident_out,
        "capture_event": capture_event,
        "moments": moments,
        "events": [event_row(e) for e in sorted(events, key=lambda e: (e.get("first_alert_timestamp_seconds", e["timestamp_seconds"]), e["event_id"]))],
        "incidents": [incident_row(i) for i in incidents],
        "streetlab": {"crossing": streetlab.crossing_comparison(streetlab.CrossingAssumptions())},
        "assets": {
            "source": "assets/real/source.mp4",
            "annotated": "assets/real/annotated.mp4",
            "stills": {str(f): f"assets/real/{n}" for f, n in stills.items()},
            "annotated_stills": {str(f): f"assets/real/{n}" for f, n in poster.items()},
            "captures": captures,
            "captures_note": "Host browser captures of the live app on this clip, 2026-10-25 (see captures README). Investigation shows frame 34, tracks #20/#22; Incidents shows candidate #16/#20, status Uncertain.",
        },
        "brief": brief,
        "classes": classes,
        "frames": frames,
    }
    data["tests"] = run_tests() if "--tests" in sys.argv else previous.get("tests")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    # The deck may be opened from file://, where fetch() of JSON is blocked.
    (DECK / "data" / "real-metrics.js").write_text("window.NEARMISS_REAL = " + text + ";\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} and deck/data/real-metrics.js: {counts['warnings']} warnings "
          f"{by_severity}, {counts['suspected_incidents']} contact candidates; case {CASE_EVENT} "
          f"first alert frame {case['start_frame_index']}, measured frame {mframe}; "
          f"stills {sorted(stills)}; {len(captures)} host captures; tests {data['tests'] and data['tests']['summary']}")


if __name__ == "__main__":
    main()
