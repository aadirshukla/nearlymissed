# Real traffic demonstration assets

Original footage: **Mike Bird**, “Traffic Flow In The Highway,”
[Pexels video 2103099](https://www.pexels.com/video/traffic-flow-in-the-highway-2103099/).
Used under the [Pexels License](https://www.pexels.com/license/), checked 2026-10-25.
The license permits use and modification in an app. No creator endorsement is implied.

`source.mp4` is the first 15 seconds, downscaled to 1280×720 at 24 fps with audio
removed. It contains real cars. It is not the generated intersection scenario.

`tracks.json` contains actual local YOLO11 nano detections associated by ByteTrack,
using the configuration and model checksum recorded in `manifest.json`. These are
precomputed model outputs, not scripted positions or human annotations.
`metadata.json` describes the processed clip. The manifest binds their hashes.

`annotated.mp4` is NearMiss's real annotation pipeline applied to this clip and
these tracks, with a source/credit label added to the preview. Any warning is an
experimental image-coordinate screening result, not a confirmed dangerous act.
No real-world detector accuracy or crash-reduction claim follows from this sample.

The original full-resolution download stays outside Git in the host scratch area.
The separately labeled synthetic scenario remains available for controlled
regression checks and a reproducible incident-review walkthrough.

## Local pipeline observation

At the recorded default configuration, this clip produced 360 frames, 5,666
track rows and 78 tracker IDs (IDs are not a verified count of distinct physical
vehicles). The heuristic pipeline emitted 41 warning candidates and 5 suspected
contact candidates. This normal traffic clip has no ground-truth incident labels.
None of these candidates is verified, and perspective/occlusion can produce false
alarms. It is included to demonstrate real-footage overlays and review, not to
claim detection accuracy. The first aerial candidate was rejected because its
camera rotated; only the fixed-camera Mike Bird footage is bundled.
