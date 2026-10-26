# Threshold sensitivity comparison — host integration and report

Owned files: `nearmiss/comparison.py` (pure logic), `nearmiss/comparison_ui.py` (Streamlit
section), `tests/test_comparison.py`, `tests/test_comparison_ui.py`, this document. Nothing
else was edited. `app.py` is not touched; the integrating worker wires it in.

## What it does

It re-runs the real `conflict_detector.detect_conflicts` twice on the **already stored track
rows**, followed by the same post-processing `app.py` uses (`normalize_events` then
`deduplicate_events`). There is no YOLO re-inference and no model download.

- **Baseline:** a deep copy of `cfg`, unchanged.
- **Changed:** a deep copy with **only** `low_time_gap_seconds` replaced. This is the
  "Maximum qualifying arrival gap", shown as "Maximum arrival gap" in the sidebar. A
  candidate whose projected arrival gap is above it is never flagged. `changed_settings()`
  checks that no other key differs, and the comparison refuses to run if one does.

Tracks, source, zone and every other setting stay fixed. The caller's `tracks`, `events` and
`cfg` are never mutated (tested, including a detector that tries to mutate its inputs). No
shared library, saved run, SQLite review or baseline event list is written. The only state
the page writes is `comparison_{video_id}_*` session keys and, when a jump button is
clicked, the Investigation keys described below.

The page shows the baseline and changed values, episode counts (HIGH/MEDIUM/LOW counts are
in the export), and retained / removed / added tables with start, end and arrival-gap times.
Each row has an "Investigate" button. The page always shows this disclaimer: *sensitivity
exploration only, not a safety rating; fewer flags does not mean safer traffic.*

## Public signature (unchanged from the brief)

```python
from nearmiss.comparison_ui import render_comparison

render_comparison(
    *,
    tracks: list[dict] | None,          # stored track rows (raw, not zone-enriched; either works)
    events: list[dict] | None,          # app's baseline events after normalize + deduplicate
    cfg: dict | None,                   # the conflict_config passed to detect_conflicts
    zone_polygon: list | None,          # applied zone; < 3 points => whole frame
    frame_size: tuple[int, int] | list[int] | None,   # (width, height)
    data_source: str | None,            # provenance["data_source"], e.g. "synthetic_demo"
    video_id: str | None,               # video_hash; namespaces session keys
) -> None
```

### Suggested insertion in `app.py` (owned by the integrating worker)

Insert it after `conflict_config["zone_is_user_defined"] = ...` and after `events` is computed
(around `app.py:1117-1128`). It can go on its own page or in an expander on Analysis:

```python
from nearmiss.comparison_ui import render_comparison

render_comparison(
    tracks=tracks,
    events=events,
    cfg=conflict_config,          # must already contain zone_is_user_defined
    zone_polygon=applied_zone,    # or analysis_zone; see note below
    frame_size=(metadata.width, metadata.height),
    data_source=source_kind,
    video_id=video_hash,
)
```

How the zone is resolved: with 3 or more points, the polygon is used as given. With fewer, the
whole frame from `frame_size` is used, which is exactly what `app.py` does. `cfg` already holds
`zone_is_user_defined`, so that value is kept. If the key is missing, it is derived from the
zone (`setdefault`).

Pass the same `events` the rest of the app shows. The page re-runs the baseline and checks
whether the re-run matches them. It compares episode summaries: ID, level, participants,
times, frames and metrics. If they differ (for example, the events came from other settings),
a visible warning says the comparison uses the re-run.

### Jump to Investigation (existing state contract)

`open_in_investigation(video_id, frame_index, track_ids)` sets the same keys as
`app.py:open_investigation`:

- `investigation_{video_id}_frame`
- `investigation_{video_id}_tracks`
- `_types` and `_classes` are popped
- `_next_page = "Investigation"`

It runs as a button `on_click` callback, so the page switch happens on the next rerun.

- **Frame:** `start_frame_index` (first alert), falling back to `frame_index`.
- **Tracks:** `nearmiss.investigation.evidence_track_ids(event)`. This includes stitched raw
  IDs, ordered current ID first, then the stitched IDs.
- **Added episodes:** the Investigation evidence list shows baseline events only, so it does
  not list them. The page states this.

## Validation and errors (all visible in the UI)

- **Threshold checks:** `high_time_gap_seconds`, `medium_time_gap_seconds` and
  `low_time_gap_seconds` must be present, finite and greater than 0, with HIGH ≤ MEDIUM ≤ LOW.
  `low` must be within 0.50–3.00 s, the sidebar slider range. If the baseline fails any of
  these, `st.error` is shown and no run button appears.
- **Allowed changed value:** `[max(0.50, medium), 3.00]`, step 0.05, through `number_input`.
  `app.py` sets `medium = max(high, 1.0)`, so by default the lower bound is 1.00 s.
  `build_changed_config` raises `ComparisonError` for out-of-range, non-finite or
  ordering-breaking values.
- **Errors:** `ComparisonError` messages and any detector exception
  (`"The conflict detector failed: <Type>: <msg>"`) are shown with `st.error`, and no result
  is shown. Example: a track row without `center` produces a visible `KeyError`, the same
  failure `app.py`'s zone enrichment would hit.
- **Empty or zero cases:** with no tracks there is a warning and no run. When there are zero
  episodes under both settings, an info message says this is *not evidence the scene is safe*.
- **Stale results:** a result is shown only if its input fingerprint matches the current
  inputs and value. After a change, the user must re-run.
- **Synthetic data:** `is_synthetic_source` triggers a `st.warning` banner. The export gets
  `provenance.synthetic = true` and a SYNTHETIC label, and the download filename gets a
  `synthetic_` prefix.

## Episode matching

Sequential `conflict-NNN` IDs renumber whenever the episode set changes, so they are never
used for matching.

- **Participant sets:** each side of an episode is the set of its current track ID plus its
  stitched `participant_*_track_ids` (and the `vehicle_*` aliases).
- **Candidate pairs:** two episodes are candidates when their participant sets intersect side
  to side (either orientation) **and** their `[first_alert, end]` intervals overlap, with a
  1e-6 s tolerance.
- **Matching:** one-to-one greedy, ranked by overlap duration, then start distance, then list
  position, so it is deterministic.
- **Unmatched episodes** are `removed` (baseline only) or `added` (changed only). If one of
  them overlaps an already-matched episode of the same pair (a merge or split), the partner
  appears in `overlaps_*_event_ids` and in the "Overlaps (merge/split)" column.

## Export (`comparison_json`)

The export is deterministic: sorted keys, no wall-clock timestamp, `allow_nan=False`. numpy
values are converted, and NaN/inf become `null`. Same inputs give byte-identical JSON (tested).

| Key | Contents |
|---|---|
| `schema` | `nearmiss.threshold_comparison/1` |
| `disclaimer` | the not-a-safety-rating text |
| `provenance` | `video_id`, `data_source`, `synthetic`, `label`, `track_rows`, `tracks_sha256`, `zone_polygon`, `zone_is_user_defined`, `frame_size`, `detector`, `post_processing`, `re_inference: false`, supplied-events count and sha256, `supplied_events_match_baseline_rerun` |
| `parameter` | key, label, unit, `baseline_value`, `changed_value`, `allowed_range`, `identical_setting` |
| `settings` | full `baseline` and `changed` dicts, their sha256 values, `differing_keys` |
| `counts` | baseline/changed episode counts, retained/removed/added, retained-with-level-change, per-level counts |
| `episodes` | `retained` (baseline + changed summary, `severity_changed`, `interval_changed`), `removed`, `added` |

Each episode summary contains:

- `event_id` and level
- participant ID lists and types
- start, end and measurement timestamps and frames
- arrival gap, time to conflict, heuristic risk index and persistence
- Investigation frame and track IDs

## Detector behaviour worth knowing (from reading `conflict_detector.py`)

- **Risk index:** `low_time_gap_seconds` also feeds the timing component of the heuristic
  risk index (`1 - gap / low`), so a retained episode's index can change.
- **Episode boundaries:** LOW-level candidate frames take part in episode grouping and
  persistence, so a retained HIGH/MEDIUM episode's end time can shift slightly. Example: on
  the demo at 1.00 s, episode 1 ends at 3.3 s instead of 3.4 s. The page reports this as
  `interval_changed`; it is not a new episode.

## Verified results (actual)

- **Synthetic demo (`demo.synthetic_tracks()`, whole frame, defaults):** 3 episodes (HIGH,
  HIGH, MEDIUM; arrival gaps 0.241 / 0.032 / 0.484 s) at every tested value: 1.00, 1.25, 1.5,
  1.75, 2.0, 2.5 and 3.0 s. With 1.25 s the comparison reports 3 retained, 0 removed, 0
  added. The demo is therefore **not** a good showcase for this parameter: it honestly shows
  no change. A judge-facing demo of added/removed needs footage with gaps between about 1.0
  and 3.0 s.
- **Hand-built crossing fixture (tests):** pair 1/2 (0.3 s gap) is retained. Pair 3/4 has a
  1.6 s gap and a stitched ID switch 4→9. It is removed at 1.25 s and added when going from a
  1.25 s baseline to 1.75 s. The removed episode starts at 6.5 s (frame 130) with
  Investigation tracks `[3, 9, 4]`.

## Host tests

`.venv/bin/python -m pytest tests/test_comparison.py tests/test_comparison_ui.py -q` →
**35 passed**. Full suite `.venv/bin/python -m pytest -q` → **205 passed** (19.4 s), run with
the other workers' uncommitted changes in the tree.

The tests cover:

- an identical setting giving an identical result (byte-identical JSON)
- a changed value producing removed and added episodes
- all other settings staying fixed
- no mutation of inputs, including through the page and a mutating detector
- matching that ignores IDs, uses stitched participants and handles reversed sides
- the same pair without overlap counting as removed plus added
- merges
- invalid baseline settings (ordering, NaN, string, 0, out of range, missing key, non-dict)
- invalid changed values
- zone resolution
- a detector exception propagating (core) and shown with `st.error` (UI)
- a malformed-row error
- an honest zero result
- stale-result hiding
- the jump writing the Investigation state contract
- the synthetic demo label, banner and export

## Gaps / not done

- **Not wired in:** `app.py` integration and visual QA are left to the host and integrating
  worker. I did not check the page's look in a browser.
- **Performance:** the page computes an input fingerprint (sha256 of the tracks) on every
  rerun to detect stale results, about 0.7 s for 100k rows on this machine. Each comparison
  runs the detector twice, and on long footage that can take as long as the original
  prediction step.
- **One setting only:** HIGH/MEDIUM thresholds, look-ahead and persistence cannot be changed
  here, by design.
- **No interpretation:** no accuracy, safety or savings claim is made or computed. The counts
  are detector-output differences only.
