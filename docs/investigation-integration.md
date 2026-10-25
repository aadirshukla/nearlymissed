# Investigation workspace — host integration

Owned files: `nearmiss/investigation.py` (pure helpers), `nearmiss/investigation_ui.py`
(Streamlit page), `tests/test_investigation.py`. Nothing in `app.py` or other modules was
changed.

## What it does

The page lets someone step through **original source frames** (decoded with
`nearmiss.video.frame_at_timestamp`, no YOLO inference) and overlay **only stored track
rows** at that frame. Users can:

- move by frame slider, ◀ / ▶ buttons, or "Jump to evidence" (prediction events and
  suspected incidents, ordered by event time);
- filter by participant type and detector class, then multi-select track IDs (ranked:
  visible now → named in evidence → most observed);
- see a selected-track table (observed / not observed at this frame, nearest observed
  frame, missing frames, path length in px, mean speed in px/s, image-space direction);
- see evidence within ±N s with explicit event time, offset and human-review status;
- download an investigation JSON.

A track with no row at the requested frame is reported as "not observed (nearest frame N)";
it is never drawn at a guessed position. Trails show only past stored rows, and segments
break across gaps of more than 5 frames.

## Host call

```python
from nearmiss.investigation_ui import render_investigation_page

render_investigation_page(
    *,
    source_path: Path | str | None,   # original video file (synthetic demo mp4 is fine)
    metadata: VideoMetadata | dict | None,  # needs fps and frame_count
    tracks: list[dict] | None,        # rows as from load_artifacts / demo generator
    events: list[dict] | None,        # normalized + deduplicated prediction events
    incidents: list[dict] | None,     # suspected incidents, ideally with review_status merged
    source_kind: str | None,          # e.g. "synthetic" for the demo, "upload" otherwise
    video_id: str | None,             # video_hash; namespaces session_state keys
) -> None
```

`source_kind` counts as synthetic if it is one of `synthetic`, `synthetic_demo`, `demo`,
`generated`, `scripted`, or starts with `synthetic`. Any track row whose `data_source`
contains "synthetic" also turns on the banner. When synthetic, the page shows a
`st.warning` banner, prefixes the image caption with "SYNTHETIC —", sets
`provenance.synthetic = true` in the JSON, and prefixes the download filename with
`synthetic_`.

### Insertion in `app.py` (core worker)

1. Add `"Investigation"` to the sidebar `navigation` radio options (around `app.py:402`),
   for example `["Overview", "Analysis", "Investigation", "Incidents", "Dispatch"]`.
2. After `incidents` have their persisted `review_status` merged (the loop after
   `persisted_reviews = ...`, around `app.py:674-677`), add:

```python
if navigation == "Investigation":
    page_header(navigation, "Investigation", "Step through original frames and stored track evidence.")
    render_investigation_page(
        source_path=source_path,
        metadata=metadata,
        tracks=tracks,              # raw tracks, not zone-enriched copies (either works)
        events=events,
        incidents=incidents,
        source_kind=active_video.get("source_kind", "upload"),  # use whatever the demo flag is
        video_id=video_hash,
    )
    st.stop()  # or the same branch structure as the other pages
```

Use whatever variable the demo flow already uses to mark synthetic input. Pass `incidents`
after the review merge so the evidence table shows the current human-review status. The page
is read-only and never calls `review_incident`.

### Session-state keys

All keys are `investigation_{video_id}_*` (`_frame`, `_types`, `_classes`, `_tracks`,
`_trail`, `_evidence_window`, `_context`, `_jump_choice`, `_jump`, `_back`, `_next`,
`_download`). To deep-link from another page, for example "Investigate this incident",
set `st.session_state[f"investigation_{video_hash}_frame"] = frame_index` before switching
`navigation`, then rerun.

## Pure helper API (`nearmiss.investigation`)

| Function | Purpose |
|---|---|
| `metadata_fields(metadata) -> dict` | fps / frame_count / width / height / duration from dataclass, dict or None |
| `is_synthetic_source(source_kind, tracks=()) -> bool` | provenance check |
| `frame_index_for_timestamp(t, fps, frame_count=None) -> int` | floor(t·fps), clamped |
| `timestamp_for_frame_index(frame, fps) -> float` | frame / fps; `frame_at_timestamp` decodes exactly this frame (tested) |
| `clean_observations(tracks) -> list[dict]` | copies valid rows; drops malformed rows without repairing them |
| `filter_observations(tracks, *, track_ids=None, object_types=None, class_names=None)` | `None` = no filter, `[]` = match nothing |
| `observations_at_frame(tracks, frame, *, track_ids=None, object_types=None, class_names=None, tolerance_frames=0)` | one stored row per track; rows within the tolerance are labeled `match="nearest_within_tolerance"` with `frame_offset` |
| `nearest_observed_frame(tracks, track_id, frame) -> int \| None` | |
| `participant_catalog(tracks, *, frame_index=None, events=None, incidents=None)` | ranked per-track summary |
| `filter_participants(catalog, *, track_ids=None, object_types=None, class_names=None)` | |
| `track_trail(tracks, track_id, frame, *, trail_frames=30)` | bbox bottom-centre points in `[frame-trail_frames, frame]`, no look-ahead |
| `movement_summary(tracks, track_id, frame, *, fps, window_frames=30, stationary_pixels=2.0)` | px / px·s⁻¹ / image heading |
| `evidence_timeline(events, incidents)` | timed evidence sorted by time; untimed records skipped |
| `nearby_evidence(events, incidents, t, *, window_seconds=2.0, track_ids=None)` | adds `offset_seconds` (event − requested) |
| `evidence_track_ids(record) -> list[int]` | participant IDs from event or incident keys, including stitched raw-ID arrays (see below) |
| `draw_investigation_frame(frame_bgr, observations, trails=None, *, selected_track_ids=None, track_types=None, gap_frames=5) -> ndarray` | draws on a copy; clips boxes and skips off-frame or malformed rows |
| `build_investigation_export(*, video_id, source_kind, metadata, tracks, events, incidents, frame_index, selected_track_ids, object_types=None, class_names=None, trail_frames=30, evidence_window_seconds=2.0, frame_decoded=None) -> dict` | |
| `investigation_json(export) -> bytes` | JSON-safe for numpy values and NaN |

Incident time uses `first_suspected_impact_timestamp_seconds` and falls back to
`timestamp_seconds`. The field actually used is recorded in `event_time_field`. Event time
is `timestamp_seconds`, and `first_alert_timestamp_seconds` is carried when present.

Evidence participant IDs combine each singular key with its stitched array, in this order:
`participant_a_track_id`, `participant_a_track_ids`, `participant_b_track_id`,
`participant_b_track_ids`, then the `vehicle_a`, `vehicle_b`, `vehicle`, `pedestrian`
and `cyclist` pairs. IDs are deduplicated in first-seen order. So an event with
`participant_a_track_id: 1, participant_a_track_ids: [1, 7], participant_b_track_id: 2`
gives `[1, 7, 2]`. Selecting raw track 7 then shows that event in nearby evidence, in the
export, and in the participant ranking. Lists, tuples, numpy arrays and sets are accepted
(sets are sorted). A scalar or numeric string in an array key counts as one ID. `None`,
NaN/inf, non-integral numbers, booleans, nested lists and dicts are skipped.

## Export schema (`nearmiss.investigation/v1`)

- `provenance`: `video_id`, `source_kind`, `synthetic`, `synthetic_notice`,
  `track_data_sources`, `frame_source`, `frame_decoded`, `observation_source`,
  `interpolated_rows_included: false`, `units`, `review_context`.
- `request`: exact `frame_index`, `timestamp_seconds` (= frame / fps), `fps`,
  `frame_count`, `frame_width`, `frame_height`.
- `selection`: `track_ids`, `object_types`, `class_names`, `trail_frames`,
  `evidence_window_seconds`.
- `observed_rows`: stored rows at **exactly** the requested frame for selected tracks
  that pass the filters.
- `selected_tracks_without_observation`: `track_id`, `reason`
  (`no_stored_row_at_frame` | `excluded_by_type_or_class_filter`),
  `nearest_observed_frame_index`.
- `movement_summaries`, `nearby_evidence`.

## Verification

- `.venv/bin/python -m pytest tests/test_investigation.py -q` → **21 passed** (2026-10-25).
- `nearmiss.investigation` and `nearmiss.investigation_ui` import cleanly. The public
  signatures match the tables above.
- No visual or screenshot QA was done by the investigation worker. The host does
  rendered-page checks.

## Limitations

- All measurements are uncalibrated image pixels. There is no road-speed, distance or
  crash-probability meaning.
- The frame-exact decode was verified on OpenCV `mp4v` files at constant frame rate.
  Variable-frame-rate sources can land on a neighbouring frame.
- Each slider move decodes one frame (cached per path, timestamp and mtime). This is fine
  for a demo but is not a scrubbing video player.
- Tolerance matching (`tolerance_frames`) exists in the helpers. The UI uses exact-frame
  matching only.
