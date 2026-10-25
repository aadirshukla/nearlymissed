# NearMiss

NearMiss is a local, CPU-friendly intersection safety analysis prototype. It
uses a pretrained Ultralytics YOLO nano model, ByteTrack identities, OpenCV,
Streamlit, and Plotly to screen fixed-camera traffic footage for potential
vehicle-to-vehicle conflicts and preserve reviewable video evidence.

> NearMiss produces experimental, image-coordinate conflict indicators. A flag
> is not a verified crash, near miss, probability, or roadway safety rating.
> Human review is required.

## Product workflow

1. Upload an MP4 and optionally draw a conflict-zone polygon.
2. Run YOLO and ByteTrack locally to create timestamped track observations.
3. Review the annotated video, deduplicated conflict timeline, and diagnostics.
4. Explore a heatmap made only from detected event locations.
5. Label candidates as confirmed potential conflict, false positive, or uncertain.
6. Download CSV/JSON evidence, the annotated MP4, or a PDF safety report.

Cars, motorcycles, buses, and trucks participate in vehicle-pair analysis.
People and bicycles remain visible in the tracking output. The dashboard reports
actual processed counts; a zero-event result remains zero and is never replaced
with sample data.

## Install and run

Python 3.11 is recommended. From this directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.
The first analysis may download public YOLO nano weights. No paid API or API key
is used. A short, stationary-camera 720p clip is best for a CPU demonstration.

## Using diagnostics

Enable **Debug rejected vehicle pairs** in the sidebar, process the video, and
download `debug_conflicts.csv`. For every simultaneous vehicle pair, the table
includes IDs/classes, observation history, smoothed velocities, projected path
endpoints, intersection/footprint status, estimated arrival times, zone status,
temporal confirmation, and the exact rejection reason. The debug candidate
selector draws the considered projected paths on the real source frame.

Do not use a previously annotated export as the source when evaluating detection
quality. Labels, boxes, and paths become pixels in that export and can suppress
or confuse a second YOLO/ByteTrack pass. Upload the original camera footage.

## Conflict logic

`conflict_detector.py`:

- uses each bounding box's bottom center as an approximate ground-contact point;
- estimates velocity from actual timestamps across the recent 5–10 observations;
- rejects large segment deviations before applying recency-weighted smoothing;
- conservatively stitches brief, class/size/direction-consistent ID changes;
- projects finite constant-velocity paths over the configured horizon;
- computes the closest points on both path segments and includes a bounded
  image-space footprint radius derived from box width;
- requires closing motion, a future conflict region inside the selected zone,
  and a qualifying arrival-time gap;
- requires consecutive-frame evidence and merges repeat episodes for the same
  logical pair while preserving the earliest confirmed warning.

The heuristic score is used only to rank active flags. It combines projected
path overlap, arrival-time agreement, closing motion, and zone eligibility; it
is not a probability.

Configurable sidebar thresholds include prediction horizon, HIGH arrival gap,
maximum qualifying arrival gap, minimum trajectory history, and HIGH temporal
confirmation frames. Defaults are documented in `nearmiss/config.py`.

## Project layout

```text
app.py                     Streamlit workflow and safety dashboard
conflict_detector.py       Trajectory, pair screening, diagnostics, deduplication
nearmiss/config.py         Model classes and detector/tracker defaults
nearmiss/video.py          Upload, YOLO + ByteTrack, cache, rendering, evidence clips
nearmiss/geometry.py       Polygon membership and zone enrichment
nearmiss/events.py         Event normalization and CSV export
nearmiss/safety.py         Metrics, heatmap, timeline, review/export helpers
nearmiss/report.py         Source-backed PDF safety report
tests/                     Synthetic unit tests and application contracts
```

## Data contracts

Each track observation contains the ByteTrack ID, COCO class, frame index,
actual video timestamp, bounding box, center, detector confidence, and zone flag.
Coordinates are original-frame pixels with `(0, 0)` at the upper left.

Conflict events contain both current and stitched source IDs, participant
classes, first-alert and episode timestamps, projected conflict point, velocities,
arrival estimates, path separation, persistence, and a plain-language reason.
Nested evidence is preserved in CSV/JSON exports.

## Tests

```bash
pytest -q
```

Synthetic tests cover simultaneous and different-time crossings, parallel and
diverging traffic, a stationary vehicle, missed frames, ID changes, tracking
jitter, multiple vehicles, temporal confirmation, zone exclusion, deduplication,
heatmap alignment, timeline values, review labels, malformed events, and PDF
generation with zero or multiple events.

## Cache behavior

Uploads, tracks, annotated outputs, and evidence clips live under
`.nearmiss_cache/`. **Clear all cached videos** deletes every per-video cache
directory and session zone/review/report state while preserving only reusable
Ultralytics configuration/model data.

## Limitations

- Pixel velocity and distance are perspective-dependent and are not physical
  speed or distance measurements without camera calibration/homography.
- Constant-velocity projection cannot anticipate braking, acceleration, or turns.
- Small or occluded vehicles can be missed; ByteTrack IDs may change.
- Moving-camera footage can produce invalid apparent motion.
- General-purpose COCO labels can confuse a motorcycle and car.
- Short clips and raw event counts are not enough to compare intersection safety.
- NearMiss is decision support for further inspection, not automated enforcement.
