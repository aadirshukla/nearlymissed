# NearMiss

NearMiss is a local, CPU-friendly computer-vision prototype for reviewing vehicle–pedestrian interactions in intersection video. It detects road users with a pretrained YOLO nano model, maintains identities with ByteTrack, visualizes trajectories and a user-defined conflict zone, and passes structured observations to a project-owned conflict detector.

> NearMiss produces decision-support evidence. Any events returned by the detector are **heuristic potential-conflict flags**, not verified accidents or near misses.

## What works

- MP4 upload and validation
- YOLO detection for people, bicycles, cars, motorcycles, buses, and trucks
- Persistent ByteTrack IDs, boxes, labels, confidence values, and movement trails
- Click-to-draw polygonal conflict zone
- Content-addressed on-disk cache for tracking results and annotated videos
- Annotated playback, unique road-user counts, event timeline, data table, and class chart
- Track CSV, full JSON, and annotated MP4 downloads
- Clean extension point for a custom conflict algorithm—no fake events are generated

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

The first analysis downloads the selected public YOLO nano weight file (roughly a few megabytes). After that, processing is local and requires no API key or paid service. If `ffmpeg` is installed, NearMiss uses it to make the annotated MP4 broadly browser-compatible; otherwise it keeps OpenCV's MP4 output.

For a fast CPU demo, start with a stationary-camera clip under 30 seconds at 720p. Runtime depends on CPU, frame size, and clip length.

## Use the app

1. Upload an MP4.
2. Click at least three boundary points in order on the first frame, then select **Use this conflict zone**.
3. Select **Analyze video**. Subsequent runs with the same file and settings use cached tracks.
4. Review the annotated video and data. Until the custom detector is implemented, the conflict timeline correctly remains empty.
5. Export tracks, the complete analysis bundle, or the annotated MP4.

Generated videos and tracking records live in `.nearmiss_cache/`, which is ignored by Git. Delete that directory manually if you want to clear local analysis data.

## Project layout

```text
app.py                     Streamlit workflow and dashboard
conflict_detector.py       Your algorithm goes here (currently an empty stub)
nearmiss/config.py         Model classes and configuration
nearmiss/video.py          Validation, YOLO + ByteTrack, annotation, cache, CSV
nearmiss/geometry.py       Point-in-polygon and zone enrichment
nearmiss/events.py         Detector-output validation for display/export
tests/                     Contract and utility tests
```

## Implement the conflict detector

Edit only `detect_conflicts()` in [`conflict_detector.py`](conflict_detector.py). The application calls it after tracking and after a valid zone has been applied:

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

The list is ordered by frame. Missing detections simply produce no observation for that track/frame; do not assume every ID appears in every frame.

### `zone`

`zone` is an ordered polygon in original-frame pixel coordinates:

```python
[[120.0, 180.0], [940.0, 175.0], [1010.0, 610.0], [85.0, 620.0]]
```

The last point is implicitly connected to the first. The detector is called only when there are at least three vertices.

### `config`

The sidebar currently passes this dictionary through unchanged:

```python
{
    "ttc_threshold_seconds": 3.0,
    "max_distance_pixels": 120.0,
    "min_track_age_frames": 5,
}
```

You may evolve these thresholds, but keep defaults synchronized with `DEFAULT_CONFLICT_CONFIG` in `nearmiss/config.py` and the corresponding controls in `app.py`.

### Return value

Return a list of dictionaries. Unknown fields are preserved in JSON and the event table. For the best dashboard experience, return:

```python
[
    {
        "event_id": "evt-001",
        "timestamp_seconds": 8.4,
        "severity": "high",  # your heuristic label, not a verified outcome
        "vehicle_track_id": 7,
        "pedestrian_track_id": 12,
        "description": "Short, evidence-based explanation",
        "metrics": {"ttc_seconds": 1.2, "min_distance_pixels": 34.5},
    }
]
```

`timestamp_seconds` can be replaced by `start_time_seconds`, or by `frame_index` (the app converts it using the video FPS). Return `[]` when no event satisfies your rule. Do not create placeholder events.

## Test the detector

Run the included suite:

```bash
pytest -q
```

Add focused synthetic tests to `tests/test_conflict_detector.py`. Build short track lists by hand so expected event timing and involved IDs are deterministic; test at least:

- a vehicle and pedestrian far apart (must return no event),
- paths that cross inside the zone within the configured threshold,
- the same crossing outside the zone,
- a track with missing frames,
- a track shorter than `min_track_age_frames`, and
- malformed or empty inputs if your algorithm chooses to support them.

Then run one short real clip in the app and compare every returned event against the annotated frames. Unit tests establish math and edge cases; the video review checks whether detections and identity associations support the conclusion.

## Notes and limitations

- Pretrained COCO detection is general-purpose and can miss small, occluded, or unusual road users.
- ByteTrack IDs can switch after long occlusions.
- Pixel distances and pixel velocities are perspective-dependent. Physical speed or distance requires camera calibration or a homography.
- Uploaded videos are written locally to `.nearmiss_cache/`; they are not sent to a hosted API.
- This MVP does not classify accidents and must not be used as an automated enforcement system.
