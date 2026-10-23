# NearMiss

NearMiss is a local, CPU-friendly computer-vision prototype for reviewing potential vehicle–vehicle conflicts in intersection video. It detects road users with a pretrained YOLO nano model, maintains identities with ByteTrack, visualizes trajectories and a user-defined conflict zone, and passes structured observations to a project-owned conflict detector. Vehicle–pedestrian analysis remains an optional sidebar mode.

> NearMiss produces decision-support evidence. Any events returned by the detector are **heuristic potential-conflict flags**, not verified accidents or near misses.

## What works

- MP4 upload and validation
- YOLO detection for people, bicycles, cars, motorcycles, buses, and trucks
- Vehicle-risk pairing for cars, motorcycles, buses, and trucks (bicycles remain tracked but are not included in this mode)
- Persistent ByteTrack IDs, boxes, labels, confidence values, and movement trails
- Click-to-draw polygonal conflict zone
- Content-addressed on-disk cache for tracking results and annotated videos
- Annotated playback, unique road-user counts, event timeline, data table, and class chart
- Smoothed image-coordinate trajectory prediction and geometric path comparison
- Provisional LOW / MEDIUM / HIGH flags with inspectable measurements and duplicate suppression
- Track CSV, event CSV, full JSON, and annotated H.264 MP4 downloads

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

The first analysis downloads the selected public YOLO nano weight file (roughly a few megabytes). After that, processing is local and requires no API key or paid service. A bundled FFmpeg binary converts annotated output to browser-compatible H.264; an existing system FFmpeg installation is used when available.

For a fast CPU demo, start with a stationary-camera clip under 30 seconds at 720p. Runtime depends on CPU, frame size, and clip length.

## Use the app

1. Upload an MP4.
2. Optionally click at least three boundary points in order on the first frame, then select **Use this conflict zone**. Without one, NearMiss analyzes the whole frame and labels the result less reliable.
3. Select **Analyze video**. Subsequent runs with the same file and settings use cached tracks.
4. Review highlighted pairs, predicted paths, conflict points, the timeline, and supporting measurements.
5. Export tracks, detected-event evidence, the complete analysis bundle, or the annotated MP4.

Generated videos and tracking records live in `.nearmiss_cache/`, which is ignored by Git. Delete that directory manually if you want to clear local analysis data.

## Project layout

```text
app.py                     Streamlit workflow and dashboard
conflict_detector.py       Trajectory prediction, path comparison, risk rules, deduplication
nearmiss/config.py         Model classes and configuration
nearmiss/video.py          Validation, YOLO + ByteTrack, annotation, cache, CSV
nearmiss/geometry.py       Point-in-polygon and zone enrichment
nearmiss/events.py         Detector-output validation for display/export
tests/                     Contract and utility tests
```

## Conflict detector

The application calls [`detect_conflicts()`](conflict_detector.py) after tracking. A selected polygon is preferred; otherwise it passes a full-frame polygon:

```python
events = detect_conflicts(tracks, zone, config)
```

### `tracks`

`tracks` is a list of observation dictionaries—one dictionary per tracked object per frame. Coordinates are pixels in the original video, with `(0, 0)` at the upper-left.

```python
{
    "track_id": 12,                  # ByteTrack identity (int)
    "class_id": 0,                   # COCO class ID (int)
    "class_name": "person",          # person/car/bus/etc. (str)
    "object_type": "pedestrian",     # "pedestrian" or "vehicle"
    "frame_index": 84,               # zero-based frame (int)
    "timestamp_seconds": 2.8,        # seconds from video start (float)
    "bbox": [410.2, 201.0, 458.7, 330.4],
    "center": [434.45, 265.7],
    "confidence": 0.87321,
    "in_conflict_zone": True,
}
```

The list is ordered by frame. The detector derives the bottom-center ground-contact approximation `((x1 + x2) / 2, y2)` from each bbox. Missing detections simply produce no observation for that track/frame.

### `zone`

`zone` is an ordered polygon in original-frame pixel coordinates:

```python
[[120.0, 180.0], [940.0, 175.0], [1010.0, 610.0], [85.0, 620.0]]
```

The last point is implicitly connected to the first. The detector is called only when there are at least three vertices.

### Mathematical logic

For every active vehicle pair at time `t` (or vehicle–pedestrian pair in the optional mode):

1. Fit separate least-squares lines to recent `x(t)` and `y(t)` observations. Their slopes give a smoothed pixel velocity vector `v = (vx, vy)`.
2. Project a finite path segment over horizon `H`: `p_future = p_now + vH`.
3. Find the closest points on the two finite projected segments. Exact line intersection has zero separation; near overlap is accepted only within the configured pixel tolerance.
4. Convert each closest-point segment fraction to an estimated arrival time: `ETA = fraction × H`. Stationary objects receive ETA zero at their current point, with division by zero avoided.
5. Require positive closing motion. With relative position `r = p_ped - p_vehicle` and relative velocity `vr = v_ped - v_vehicle`, closing speed is `-dot(r, vr) / ||r||` pixels/second.
6. Require the estimated conflict point to fall inside the selected polygon (or the clearly labelled whole-frame fallback) and the arrival gap `|ETA_A - ETA_B|` to meet a configured risk threshold.
7. Merge consecutive qualifying frames for the same logical pair into one event. Very short, spatially consistent ByteTrack ID fragments can be stitched before this step.

The displayed 0–100 risk score is a **heuristic ranking index**, not a probability. It combines projected-path proximity (35 points), arrival-time agreement (35), closing motion (20), and membership in the analysis area (10). LOW / MEDIUM / HIGH categories are determined by the independently adjustable arrival-gap thresholds.

### Adjustable thresholds

The sidebar exposes the values most useful during a demo:

- prediction horizon (default 2.0 seconds),
- HIGH / MEDIUM / LOW maximum arrival gaps (0.50 / 1.00 / 1.75 seconds),
- projected path tolerance (35 pixels),
- minimum closing motion (2 pixels/second),
- velocity smoothing observations (5),
- minimum track age (3 observations), and
- duplicate suppression window (2 seconds).

Additional conservative ID-stitching and observation-age defaults live in `DEFAULT_CONFLICT_CONFIG` in `nearmiss/config.py`.

### Event evidence

Each returned event includes the real track IDs, timestamp, category, predicted point and path endpoints, both pixel velocity vectors, both ETAs, arrival gap, projected path separation, closing motion, episode bounds, and the non-probabilistic heuristic index:

```python
[
    {
        "event_id": "conflict-001",
        "timestamp_seconds": 8.4,
        "severity": "HIGH",
        "risk_score": 87.5,
        "vehicle_a_track_id": 7,
        "vehicle_b_track_id": 12,
        "conflict_point": [521.4, 408.2],
        "participant_a_eta_seconds": 0.72,
        "participant_b_eta_seconds": 0.91,
        "arrival_time_gap_seconds": 0.19,
        "path_separation_pixels": 3.4,
        "closing_speed_pixels_per_second": 42.1,
        "description": "Evidence-based provisional explanation",
    }
]
```

The dashboard and exports contain only events derived from processed observations. No placeholder events or arbitrary accident probabilities are generated.

## Test the detector

Run the included suite:

```bash
pytest -q
```

`tests/test_conflict_detector.py` clearly labels its trajectories as synthetic and covers same-time crossing, different-time crossing, movement away, parallel paths, a stationary vehicle, missing frames, a brief ID switch, multiple vehicles, and duplicate-event prevention. Unit tests establish deterministic math; real-video review is still required to judge whether detector boxes and track identities support each flag.

## Notes and limitations

- Pretrained COCO detection is general-purpose and can miss small, occluded, or unusual road users.
- Short ID changes may be stitched by time and projected position; long occlusions and crowded scenes can still cause identity errors.
- Pixel distances and velocities are perspective-dependent and vary across the image. Physical speed, distance, and scientifically validated collision probability require camera calibration or a homography.
- Constant-velocity projection cannot anticipate braking, acceleration, turning, or intent.
- The selected conflict polygon and pixel thresholds must be reviewed for each camera view.
- Uploaded videos are written locally to `.nearmiss_cache/`; they are not sent to a hosted API.
- This MVP does not classify accidents and must not be used as an automated enforcement system.
