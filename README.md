# NearMiss

NearMiss is a local, CPU-friendly traffic incident monitoring prototype. It
uses a pretrained Ultralytics YOLO nano model, ByteTrack identities, OpenCV,
Streamlit, and Plotly to move through a four-stage operator workflow:
**Predict → Detect → Verify → Notify**.

> NearMiss produces experimental, image-coordinate conflict indicators. A flag
> is not a verified crash, near miss, probability, or roadway safety rating.
> Human review is required. Dispatch alerts are local simulations and are never
> sent to emergency services or external systems.

## Product workflow

1. Upload an original MP4 and optionally draw a conflict-zone polygon.
2. **Predict:** project tracked vehicle trajectories and flag potential conflicts.
3. **Detect:** independently screen for persistent contact plus impact evidence.
4. **Verify:** review the source frame and ±2-second clip, then confirm, reject,
   or leave the incident uncertain.
5. **Notify:** a confirmed incident creates exactly one local simulated dispatch
   message that an operator can acknowledge.
6. Download CSV/JSON evidence, the annotated MP4, or the PDF safety report.

Cars, motorcycles, buses, and trucks participate in vehicle-pair analysis.
People and bicycles remain visible in the tracking output. The dashboard reports
actual processed counts; a zero-event result remains zero and is never replaced
with sample data.

YOLO and ByteTrack are existing open-source detection and tracking technologies.
NearMiss's custom logic is the timestamp-based trajectory predictor, explainable
conflict gates, multi-signal suspected-collision detector, evidence association,
deduplication, operator review workflow, and simulated dispatch audit trail.

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
- handles same-direction following separately: collinear paths would otherwise
  place the conflict at the lead vehicle's current position (ETA 0). When two
  moving, aligned vehicles fail that gate, the trailing vehicle is checked for
  projected footprint contact within the horizon; severity uses time headway
  (`conflict_geometry = "same_direction_following"`).

The heuristic score is used only to rank active flags. It combines projected
path overlap, arrival-time agreement, closing motion, and zone eligibility; it
is not a probability.

Configurable sidebar thresholds include prediction horizon, HIGH arrival gap,
maximum qualifying arrival gap, minimum trajectory history, and HIGH temporal
confirmation frames. Defaults are documented in `nearmiss/config.py`.

### Mathematical trajectory prediction

For bounding-box bottom-center observations `pᵢ` at real video timestamps `tᵢ`,
NearMiss estimates segment velocity as:

```text
vᵢ = (pᵢ - pᵢ₋₁) / (tᵢ - tᵢ₋₁)
```

Outlier segments are removed around the median, remaining velocities receive
recency weights, and the future image-space path is projected over horizon `H`:

```text
p(t) = p₀ + v·t,  0 ≤ t ≤ H
```

Closest points on the two finite projected segments provide the shared conflict
region and arrival estimates. The difference between those estimated arrivals,
closing motion, zone membership, footprint overlap, and temporal persistence
determine the provisional LOW/MEDIUM/HIGH label.

## Suspected-collision evidence

`nearmiss/incidents.py` operates independently of prediction. It groups
same-frame vehicle pairs into contact episodes and requires:

- persistent bounding-box contact across multiple frames;
- significant overlap, or contact followed by track loss;
- measured convergence before contact; and
- at least one motion response: abrupt velocity change, sudden image-space
  deceleration, stopping, or post-contact track loss.

Bounding-box overlap alone is rejected. A matching prediction is attached as
supporting context, but a missed prediction cannot block detection. All velocity,
overlap, and deceleration thresholds are explicit heuristics, not scientific
impact measurements or probabilities.

## Verification and simulated dispatch

Operator decisions are persisted in `.nearmiss_data/nearmiss.db` using SQLite.
The incident ID is the primary key, preventing duplicate review rows. Confirming
an incident inserts one dispatch notification using a unique incident constraint;
repeated confirmation cannot create duplicates. False alarms and uncertain
reviews do not create notifications. Acknowledgement status is also persistent.
If an operator later changes a confirmed incident to False Alarm or Uncertain,
its notification becomes **Withdrawn** (kept as an audit record, no longer
acknowledgeable); re-confirming restores it to New. Prediction warnings are
linked to an incident only when raised strictly before first contact, and the
incident's contact marker, boxes and timestamp all come from the first-contact
frame (peak overlap is kept separately in `measurements`).

## Project layout

```text
app.py                     Streamlit workflow and safety dashboard
conflict_detector.py       Trajectory, pair screening, diagnostics, deduplication
nearmiss/config.py         Model classes and detector/tracker defaults
nearmiss/video.py          Upload, YOLO + ByteTrack, cache, rendering, evidence clips
nearmiss/incidents.py      Independent multi-signal collision-evidence detector
nearmiss/store.py          SQLite review and simulated dispatch persistence
nearmiss/geometry.py       Polygon membership and zone enrichment
nearmiss/events.py         Event normalization and CSV export
nearmiss/safety.py         Metrics, heatmap, timeline, review/export helpers
nearmiss/report.py         Source-backed PDF safety report
nearmiss/demo.py           Labeled synthetic demo footage + scripted track rows
nearmiss/explain.py        Plain-language evidence explanations
nearmiss/streetlab.py      Street Lab summary, crossing illustration, brief
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

Latest verified local result (2026-10-25): **157 passed** (including Streamlit
AppTest walk-throughs of the guided demo). The earlier 2026-10-24 baseline was 35. A fresh end-to-end
run of `01_Accident_001.mp4` at confidence 0.31 processed 224 frames into 504
track observations, returned one HIGH prediction at 1.033 seconds, and returned
one independently detected suspected collision at 1.200 seconds. The suspected
pair was associated with that prediction. These are clip-specific integration
results, not accuracy statistics.

Synthetic tests cover simultaneous and different-time crossings, parallel and
diverging traffic, a stationary vehicle, missed frames, ID changes, tracking
jitter, multiple vehicles, temporal confirmation, zone exclusion, deduplication,
heatmap alignment, timeline values, malformed events, sudden deceleration without
contact, perspective overlap, collision detection without prediction, duplicate
incident prevention, persistent review, exactly-once notification generation,
acknowledgement, and PDF generation with zero or multiple events.

## Cache behavior

Uploads, tracks, annotated outputs, and evidence clips live under
`.nearmiss_cache/`. **Clear all cached videos** deletes every per-video cache
directory and session zone/review/report state while preserving only reusable
Ultralytics configuration/model data.

Persistent operator reviews and simulated notifications are stored separately in
`.nearmiss_data/nearmiss.db`; clearing video-processing cache does not erase the
audit trail.

## Demonstration

### Guided synthetic demo (no footage or model needed)

Select **Start guided demo** on Overview. NearMiss generates a short, clearly
illustrative top-down intersection clip and deterministic scripted track rows
locally (`nearmiss/demo.py`), caches them in the standard
`.nearmiss_cache/<video id>/<analysis key>/` layout, and opens the results. Only
YOLO/ByteTrack inference is bypassed; prediction, independent incident evidence,
annotated playback, human review, and the simulated inbox are the normal
pipeline. Every frame is stamped **SYNTHETIC DEMO**, an amber source banner is
shown on every page, and exports carry `data_source = "synthetic_demo"` (tracks,
warnings and incidents CSV, analysis JSON `provenance`, safety-report PDF, and
the community brief). **Reset demo reviews** clears decisions for the demo ID
only; **Return to real footage** restores the previous upload. See
`docs/challenge-demo-guide.md` for a 2–3 minute script.

### Uploaded footage

1. Run `streamlit run app.py` and upload the original source MP4.
2. Select **Analyze Footage** and show the warning in annotated playback.
3. Open **Incidents**, replay the source clip, and select **Confirm incident**.
4. In **Dispatch**, acknowledge the newly created local message.

If either detector returns no event, the corresponding stage shows an honest
empty state. Synthetic data appears in the dashboard only through the labeled
guided demo.

### Street Lab and tool pages

- **Street Lab** summarizes which candidate interactions warrant human review and
  why, compares crossing times under user-entered assumptions (arithmetic only,
  not a crash reduction), builds a follow-up observation checklist, and exports
  a matching community review brief (PDF/Markdown).
- **Investigation** steps through original frames with stored track rows.
- **Explain & Share** explains one flagged moment and exports a Markdown brief.
- **Library** saves footage-free run snapshots and compares them.

## Limitations

- Pixel velocity and distance are perspective-dependent and are not physical
  speed or distance measurements without camera calibration/homography.
- Constant-velocity projection cannot anticipate braking, acceleration, or turns.
- Small or occluded vehicles can be missed; ByteTrack IDs may change.
- Moving-camera footage can produce invalid apparent motion.
- General-purpose COCO labels can confuse a motorcycle and car.
- Short clips and raw event counts are not enough to compare intersection safety.
- NearMiss is decision support for further inspection, not automated enforcement.
