# Analysis Library integration (history)

Owned files: `nearmiss/history.py`, `nearmiss/history_ui.py`, `tests/test_history.py`.
No changes to `app.py` or `nearmiss/store.py` were made; the core worker wires it in.

## What it does

- Saves a footage-free **snapshot** of a processed run to a new SQLite table
  `analysis_runs` (same default file as the store: `.nearmiss_data/nearmiss.db`,
  with its own connection helper `connect_history`).
- Snapshot ID = `run-` + SHA-256 of {video digest, `source_kind`, tracking config,
  conflict config, collision config, zone pixels}, after canonicalising (key order,
  `1` vs `1.0`, tuples vs lists). Re-saving identical analysis upserts one row and
  keeps `created_at`; any setting/zone/digest/source-kind change creates a new row.
  Source name and camera label are mutable metadata, not identity.
- Stored: source name, camera label, `source_kind` (`synthetic_demo` | `uploaded_video`),
  duration, track-record/tracker-ID/event/incident counts, summary metrics, full
  settings, zone, video metadata, provenance, created/updated timestamps. No video,
  frames, paths or per-frame tracks.
- `distinct_vehicle_track_ids` is reported; `unique_physical_vehicles` is always `None`
  with an explanatory note. `candidate_participants_with_stitched_ids` counts event
  participants whose ID was stitched across tracker IDs.
- Comparisons report counts, exposure duration and deltas, list every setting/zone
  difference, and attach caveats (provenance mismatch, short exposure < 10 min,
  different footage, settings-only change, camera labels). `ranking` is always `None`.

## Public API (all keyword-only)

```python
from nearmiss.history import (
    build_analysis_snapshot, save_analysis_snapshot, list_analysis_snapshots,
    load_analysis_snapshot, compare_analysis_snapshots, compare_saved_snapshots,
    diff_snapshot_settings, snapshots_to_csv, snapshots_to_json,
    comparison_to_csv, comparison_to_json, DEFAULT_DATABASE_PATH,
)
from nearmiss.history_ui import render_history_page

build_analysis_snapshot(*, video_sha256: str, source_name: str, camera_label: str,
    source_kind: str, duration_seconds: float, tracks: list[dict], events: list[dict],
    incidents: list[dict], tracking_config, conflict_config, collision_config,
    zone_pixels=None, video_metadata=None, notes: str = "") -> dict
    # pure; no DB access. Raises ValueError on empty digest / unknown source_kind / bad zone.

save_analysis_snapshot(*, snapshot: dict, database_path=DEFAULT_DATABASE_PATH) -> tuple[dict, bool]
    # (saved_row, created). Raises ValueError if snapshot_id doesn't match its contents.

list_analysis_snapshots(*, database_path=DEFAULT_DATABASE_PATH, video_sha256: str | None = None,
    source_kind: str | None = None, limit: int | None = None) -> list[dict]   # newest first

load_analysis_snapshot(*, snapshot_id: str, database_path=DEFAULT_DATABASE_PATH) -> dict | None

compare_analysis_snapshots(*, baseline: dict, candidate: dict) -> dict
compare_saved_snapshots(*, baseline_id: str, candidate_id: str,
    database_path=DEFAULT_DATABASE_PATH) -> dict          # KeyError if either missing

render_history_page(*, current_snapshot: dict | None = None,
    database_path=DEFAULT_DATABASE_PATH, key_prefix: str = "history") -> None
```

`tracking_config` may be a `TrackingConfig` (uses `.as_dict()`), a dataclass or a dict;
`video_metadata` may be the `VideoMetadata` dataclass or a dict.

## app.py insertion (for the core worker)

1. Imports (top of file):

   ```python
   from nearmiss.history import build_analysis_snapshot
   from nearmiss.history_ui import render_history_page
   ```

2. Navigation: add `"Library"` to the sidebar radio list
   `["Overview", "Analysis", "Incidents", "Dispatch"]`.

3. Library must open **without** active footage. Place this block *before*
   `if not active_video or not Path(active_video["source_path"]).exists():` (the
   "No footage selected" guard after the Overview branch, ~line 608), so an empty
   library is still browsable:

   ```python
   if navigation == "Library":
       page_header("Library", "Saved analyses",
                   "Compare saved runs by candidate counts and footage length. No footage is stored.")
       render_history_page(current_snapshot=st.session_state.get("history_current_snapshot"))
       st.stop()
   ```

4. After `incidents` have their `review_status` applied and before the
   `if navigation == "Analysis":` branch (~line 670), build the current snapshot:

   ```python
   st.session_state["history_current_snapshot"] = build_analysis_snapshot(
       video_sha256=video_hash,
       source_name=source_filename,
       camera_label=camera_id,
       source_kind="synthetic_demo" if <active run is the synthetic demo> else "uploaded_video",
       duration_seconds=metadata.duration_seconds,
       tracks=tracks_for_detector,
       events=events,                 # already normalized + deduplicated
       incidents=incidents,
       tracking_config=tracking_config,
       conflict_config=conflict_config,   # includes zone_is_user_defined
       collision_config=collision_config,
       zone_pixels=applied_zone,          # [] when no custom zone
       video_metadata=asdict(metadata),
   )
   ```

   Replace `<active run is the synthetic demo>` with whatever flag the demo path sets
   (e.g. `active_video.get("source_kind") == "synthetic_demo"`). Demo tracks should keep
   their `data_source` tag: a synthetic snapshot without tags, or an uploaded snapshot with
   synthetic-tagged records, gets a `provenance.warnings` entry shown in comparisons.

   Clear `history_current_snapshot` in `clear_interface_state()` (or when active video
   changes) so a stale run isn't offered for saving.

5. Optional: a "Save to library" button in the Analysis page's "Report and exports"
   expander:

   ```python
   from nearmiss.history import save_analysis_snapshot
   if st.button("Save to library", key=f"library_save_{video_hash}"):
       _, created = save_analysis_snapshot(snapshot=st.session_state["history_current_snapshot"])
       st.toast("Saved to library" if created else "Library entry updated")
   ```

The page reuses the existing `nm-section-title`, `nm-section-copy` and `nm-empty`
CSS classes, so it inherits `apply_styles()`; it renders no page header of its own.
Widget keys are prefixed with `key_prefix` (default `history`).

## Tests

`.venv/bin/python -m pytest tests/test_history.py -q` → 32 passed. Covers: identical-snapshot
upsert (reordered keys, int/float zone, renamed camera), new snapshot for each changed
tracking/conflict/collision setting, zone, cleared zone and digest; persisted fields and no
footage columns; tracker-ID vs physical-vehicle reporting; provenance and mislabel warnings;
tampered-ID rejection; filters; same-footage settings comparison; synthetic-vs-uploaded
mismatch notice; CSV/JSON exports; CSV formula-injection escaping of adversarial
camera/source labels and caveats (`=`, `+`, `-`, `@`, leading whitespace/control characters)
while negative numeric deltas stay numeric and JSON cells stay parseable; infinite/NaN/
malformed track IDs treated as missing; and a Streamlit `AppTest` render of the empty and
populated page, including the save button.

## CSV safety

All library and comparison CSVs go through one shared cell helper. String cells whose
first non-whitespace character is `=`, `+`, `-` or `@`, or that start with a control
character (tab, CR, LF, ...), get a leading `'` so spreadsheets treat them as text. Numbers
are written unchanged (a delta of `-2.0` stays `-2.0`). The database and JSON exports keep
the original label text.

## Limitations

- Snapshots hold counts at save time; incident review states changed later are not
  reflected unless the run is saved again (`incident_review_status_at_save`).
- No delete or rename UI (rename happens implicitly by re-saving with a new camera label).
- Summary metrics are computed by `history.summarize_analysis` from the events passed in;
  they match `safety_statistics` only if the same deduplicated events are passed.
- "Short exposure" cutoff (10 min) is a fixed descriptive threshold, not a statistical one.
