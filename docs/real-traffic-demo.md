# Real-traffic guided demo

**Start guided demo** opens real traffic footage with the actual YOLO + ByteTrack
rows NearMiss produced for it, bundled so the demo opens instantly and offline.
The deterministic synthetic intersection remains available as **Controlled
synthetic example**. It is the one the regression tests pin.

## Ownership

| Path | Owner | Notes |
| --- | --- | --- |
| `static/real-demo/*` | host | Source, rows, metadata, manifest, annotated preview. The app never writes here. |
| `nearmiss/real_demo.py` | app | Validation, cache restore, provenance, reset. |
| `app.py` | app | Entry points, Overview preview, banners, exports. |

## Bundle contract (`static/real-demo/`)

| File | Contents |
| --- | --- |
| `source.mp4` | Browser-playable H.264 clip that was tracked. Its SHA-256 is the video ID. |
| `tracks.json` | Actual `analyze_video` rows (optionally tagged `data_source: "real_traffic_demo"`). |
| `metadata.json` | `VideoMetadata` for the decoded clip. |
| `annotated.mp4` | `render_annotated_video` output at default thresholds (Overview preview). |
| `manifest.json` | Digests, tracking config, provenance, producer and counts (below). |

Required manifest fields that are validated:

- `video_id` == `source_sha256`, plus `tracks_sha256` and `metadata_sha256`
  (64-hex). `annotated_sha256` is checked when present.
- `tracking_config`: exactly the `TrackingConfig.as_dict()` keys. The rows are
  restored at `_artifact_paths(video_id, …, TrackingConfig(**tracking_config), …)`.
- `provenance`: `creator` (or `credit`), `title`, `source_url`, `license`,
  `license_url`.
- `counts`: `frames`, `track_rows` and `track_ids` must equal the bundle.
  `warnings` and `suspected_incidents` are checked by a test that recomputes them
  at default thresholds.
- `evaluation_note` (optional) is appended to the provenance boundary text.

Per-row checks: required schema fields, COCO class/object type consistency,
`timestamp_seconds == round(frame_index / fps, 6)`, `frame_index` within the
clip, bbox inside the frame (±1 px), center equals the bbox midpoint, confidence
≥ the manifest threshold, no repeated track ID within a frame, and no
`data_source` other than `real_traffic_demo`. The metadata must match the decoded
`source.mp4` (size, fps, frame count within 2).

Any failure raises `RealDemoError`. The message names the file and asks for the
original files to be restored. The app shows it as a visible error and never
substitutes synthetic or other data. The Overview preview shows the same message
as a warning.

## Runtime behavior

- **Start guided demo**, the gate's **Start guided demo**, the preview's
  **Open this footage in the guided demo**, and Presenter mode with no footage
  all call `real_demo_active_video()`. That function validates the bundle
  (memoized per file size/mtime), copies it into `.nearmiss_cache/<sha256>/`
  with a full digest check, and returns the same `active_video` shape as an
  upload. No model import, no `analyze_video`, no network.
- Model settings work as they do for an upload. The default settings hit the
  bundled rows. Any other model, confidence or overlap misses the cache and
  shows "Analysis is not ready" until the normal **Analyze Footage** runs, so
  rows from another config are never used.
- After **Clear processed videos**, starting the sample restores it from the
  bundle. A cached copy that differs from the manifest is overwritten from the
  bundle.
- Runtime provenance: the app builds a single provenance object per run with
  `provenance_for(video_id, tracking_config, artifacts.tracks_path)` (Overview
  uses `real_demo.runtime_provenance(tracking_config)`) and passes that same
  object to the banner, analysis JSON, PDF report, Street Lab brief, Explain &
  Share and Presenter evidence briefs, and the Library snapshot. It always has
  `data_source: "real_traffic_demo"`, label **Real traffic sample**, and the
  manifest's creator, title, URL and license, because the stock source stays
  the same. Its `tracking_origin` is derived from the actual settings and rows:
  - `bundled_precomputed`: the settings match the manifest and the cached rows
    are byte-identical to the bundled `tracks.json`. The boundary says the rows
    are actual YOLO/ByteTrack output precomputed locally and includes the
    producer's evaluation note.
  - `local_inference`: any other cached rows, for example after **Analyze
    Footage** with YOLOv8 or confidence 0.50. The boundary says the rows come
    from a fresh local analysis with the selected model, confidence, overlap and
    device. It omits the bundled settings, the "precomputed" wording and the
    producer note.
  - `not_analyzed`: the settings differ and no rows exist yet.

  Every variant says the heuristics are provisional and accuracy is unmeasured.
  The Library snapshot records `provenance.tracking_origin` and a matching
  `detector` suffix. A brief built without runtime provenance makes no claim
  about the tracking origin. Track rows are tagged in memory, so tracks,
  warnings and incidents CSV, analysis JSON (`video_sha256` is the true digest),
  report, briefs and Library (`source_kind`) all carry `real_traffic_demo`.
  Export filenames are prefixed `real_traffic_sample_`.
- Library comparisons: only a synthetic-versus-real pairing is a `PROVENANCE
  MISMATCH`, which names the real source. Comparing the bundled sample with an
  upload sets `source_difference` and a **SOURCE DIFFERENCE** caveat that names
  both real sources and never implies generated footage.
- The source banner is compact: title, creator, a **Pexels** link, the tracking
  origin (for example "actual YOLO + ByteTrack tracking, precomputed locally" or
  "fresh local YOLO + ByteTrack analysis with your selected settings"), and one
  sentence saying the candidates need
  human review and may be false alarms. URLs, license, settings, video ID and the
  producer's evaluation note are in a collapsed **Source and technical details**
  expander. Exports keep the full provenance text.
- The Analysis metric reads **Vehicle track IDs** for this sample, because a
  tracker-ID count is not a count of physical vehicles.
- **Reset demo reviews** for the sample clears only records for its video ID.
  **Return to your footage** behaves as it does for the synthetic demo.

## Honest framing

The final clip is fixed-camera roadside highway traffic: Mike Bird, “Traffic
Flow In The Highway” (Pexels). An earlier rotating-camera aerial candidate was
rejected, and the credit is always read from the manifest. At default thresholds the
heuristics emit dozens of warning candidates and several suspected contacts.
None are verified, and on this footage they are best read as evidence of
false-alarm behavior. Guided-step hints and the provenance boundary say so. The
Overview schematic story is headed **Controlled schematic example** and states
that it is not the real footage.

## Tests

`tests/test_real_demo.py`:

- A fixture bundle covers cache-layout restore, config-specific cache hits and
  misses, repair of a damaged cache, recovery after a cache clear, every digest,
  missing-file, row, count and manifest failure, the metadata/source mismatch,
  provenance text, and reset scoping.
- The shipped bundle is checked for integrity and for counts reproduced from its
  rows at default thresholds.
- App tests cover the default entry with ultralytics blocked and `analyze_video`
  patched to fail, labels across all pages, the Library, return-to-upload, the
  settings-change cache miss, cache clear and restart, a corrupt bundle (visible
  error, no fallback), the separately reachable synthetic example, and a
  read-only Presenter mode on the sample.
- Runtime-provenance tests write correctly keyed tiny cached artifacts under
  settings other than the manifest's, without running inference. They check
  `provenance_for`, the generated evidence brief, the Street Lab Markdown brief
  and the uncompressed PDF report, then an app run at confidence 0.50 (banner,
  details, Library snapshot, Explain & Share). In every case the output says
  fresh local inference with the actual settings and never "precomputed".
- `tests/test_history.py` checks that sample-versus-upload comparisons are a
  source difference with no synthetic wording in either order, while the
  synthetic mismatch coverage is kept.

Tests that intentionally exercise the synthetic regression now click
`start_synthetic_demo` or `presenter_open_story`, and their assertions are
unchanged.
