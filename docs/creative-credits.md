# NearMiss presentation: creative and technical credits

These credits cover the challenge video (`presentation/video/`, controlled
synthetic demonstration), the browser deck (`presentation/deck/`, real traffic
footage) and its PDF backup. They are also shown on the
video's end card and on the deck's last slide.

## People

- **Srivibhav Padakandla** and **Aadi Shukla**, NearMiss team. This file does
  not divide authorship of the app between them. The presenter notes split
  the speaking only: Srivibhav takes slides 1 to 4 and Aadi takes slides 5 to 8.

## AI assistance

- **OpenAI Codex** and **Anthropic Claude (Opus)** helped write, review and test
  NearMiss code. `docs/challenge-build-brief.md` records how the work was routed:
  Claude Opus workers implemented features, and Codex did integration,
  browser checks and Git.
- **Claude Opus** (`claude-opus-5-5`) built the presentation source in this folder:
  the Remotion project, the deck, the metrics extractor, the PDF builder, the
  presenter notes and on-screen wording, and these credits. A later Claude Opus
  (`claude-opus-5-5`) session made the corrections listed in
  `docs/presentation-guide.md` (measurement frame vs first alert, footer band,
  rehearsal timing, provenance wording). A further Claude Opus
  (`claude-opus-5-5`) session moved the deck and its PDF to the real traffic
  sample: `extract_real_metrics.py`, `sync.js`, the real-footage scenes, notes,
  checks and tests. The film was not changed.
- The host session supplied the app screenshots, the exported brief, the
  music file and its licence, and processed the real traffic sample. It renders
  the video and does the visual QA.
- AI wrote no voice-over (the video has none) and no music. The on-screen text
  was drafted with AI assistance.

## Visual sources

### Deck and PDF backup (real footage)

- **Traffic footage:** Mike Bird, “Traffic Flow In The Highway”,
  [Pexels video 2103099](https://www.pexels.com/video/traffic-flow-in-the-highway-2103099/),
  used under the [Pexels License](https://www.pexels.com/license/) (checked by
  the host 2026-10-25). First 15 s, 1280×720, 24 fps, no audio; source SHA-256
  `e25026291ef2990862e588cc8648883e61f6c7adcc66d182e3b72881ec73a2e4`. No creator
  endorsement is implied. Credited on slides 1, 2 and 8, the PDF metadata and
  the community brief. Copies: `deck/assets/real/source.mp4` and exact-frame
  stills `deck/assets/real/source-NNN.jpg` (OpenCV-decoded).
- **Overlays:** actual YOLO11n + ByteTrack rows precomputed by the app
  (`static/real-demo/tracks.json`) and NearMiss's own post-processing, drawn by
  the deck (SVG) and the PDF (ReportLab) over the real frames. No box or path is
  scripted. Every warning and suspected contact is an unverified, experimental
  candidate on ordinary traffic with no incident labels.
- **Annotated clip** (`deck/assets/real/annotated.mp4`): the app's real
  annotated render with its baked credit; byte-identical to
  `static/real-demo/annotated.mp4` (checked by `npm run check`).
- **App captures** (`deck/assets/real/*.png`): screenshots of the live app on
  this clip (Analysis, Investigation, Incidents, Street Lab), taken by the host
  session at 1440×1000 on 2026-10-25. `community-brief.md` is the actual
  Street Lab download from that session.

### 165-second film (controlled synthetic demonstration, unchanged)

- **App captures** (`presentation/video/public/captures/`): screenshots of the
  actual NearMiss app running the synthetic demo, taken by the host session.
- **Annotated clip**: the app's own annotated render of the synthetic demo. Its
  SHA-256 matches the app's cached render in `.nearmiss_cache/` (checked
  2026-10-25).
- **Traffic diagrams**: functional diagrams drawn in code (React) from the
  scripted positions in `presentation/data/demo-metrics.json`. They are not
  images of real traffic.
- **Background street image**: `static/nearmiss-hero.jpg`, inherited from the
  app's landing page. **Its origin is unverified:** its creator, how it was made
  (camera, stock or AI-generated) and its licence have not been confirmed.
  It appears only as an illustrative background, is labelled "Illustrative image
  · not analyzed footage", and is never analyzed. Replace it with an image of
  known origin before any public release.

## Music (soundtrack version of the video only)

- **"Signal to Noise" by Scott Buckley**
  (https://www.scottbuckley.com.au/library/signal-to-noise/). Licence:
  Creative Commons Attribution 4.0 International. The host supplied the file and
  licence in `presentation/video/public/music/` (`LICENSE.txt`, verified by the
  host on 2026-10-25).
- The video uses the first 165 s of the track, with a 1.5 s fade-in and a 4 s
  fade-out at 0.5 volume. These are set in `presentation/video/src/Video.tsx`.
- Required credit, verbatim from `LICENSE.txt`; copy it as-is into any future
  upload description:

  > 'Signal to Noise' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au

- No voice is used in either version.
- `NearMiss-demo-silent.mp4` is a stream copy of the same frames with the audio
  removed. Its end card still shows the credit, labelled "Music (soundtrack
  version)".

## Open source used by NearMiss (the app)

Versions are the ones installed in this repo's `.venv` on 2026-10-25.

| Project | Role | Licence |
|---|---|---|
| Ultralytics YOLO (`ultralytics` 8.4.189) | Pretrained object detection for uploaded footage | AGPL-3.0 |
| ByteTrack (shipped inside Ultralytics) | Keeps track IDs across frames | MIT (original ByteTrack) |
| OpenCV (`opencv-python` 4.11) | Video decode/encode and drawing | Apache 2.0 |
| Streamlit (1.66) | App interface | Apache 2.0 |
| Plotly (6.9) | Charts | MIT |
| ReportLab (4.5.1) | PDF exports, and this deck's PDF backup | BSD |

The controlled synthetic example does not run YOLO or ByteTrack: scripted track
rows from `nearmiss/demo.py` replace them, and every later stage is the normal
pipeline. The bundled real traffic sample uses YOLO11n + ByteTrack rows
precomputed locally by the app; the deck runs no inference.

## Open source used by the presentation

| Project | Where | Licence |
|---|---|---|
| Remotion 4.0.538 (`remotion`, `@remotion/cli`, `@remotion/fonts`, `@remotion/media-utils`) | Video | Remotion licence: free for individuals and small teams; for-profit companies above the size threshold need a company licence (see `node_modules/remotion/LICENSE.md`) |
| React 19 | Video | MIT |
| GSAP 3.15.0 | Deck animation (bundled as `deck/vendor/gsap.min.js`) | GSAP Standard "no charge" licence |
| Inter, Instrument Serif, JetBrains Mono | Type in the video (via `@fontsource`), the deck and the PDF (TTF via `@expo-google-fonts`) | SIL Open Font License 1.1. The full licence text with each family's copyright notice ships beside the fonts: `video/public/fonts/OFL-*.txt` and `deck/assets/fonts/OFL-*.txt` |
| Google Chrome (installed on host) | Remotion renderer used for final exports via `REMOTION_BROWSER_EXECUTABLE` | Google Chrome / Chromium licences |
| FFmpeg | Clip resampling and the silent remux | LGPL/GPL (system install) |

## What is real and what is synthetic

- **Deck and PDF: real footage.** Every traffic scene is Mike Bird's real
  highway clip with NearMiss's actual model output, tagged "Real footage". It is
  ordinary traffic with no ground-truth labels: the 41 warnings and 5 suspected
  contacts are unverified, many are likely false alarms from perspective or
  occlusion, and 78 tracker IDs are not a vehicle count. The deck does not claim
  a near miss or collision, shows no confirmation or dispatch for these
  candidates (0 confirmed, 0 notices), and explains simulated dispatch only as
  what would follow a confirmation. The automated test suite checks code
  behaviour, not detector accuracy. Street Lab crossing times are arithmetic on
  stated assumptions, not a road-safety measurement.
- **165-second film: synthetic.** Every app scene in the film is the NearMiss
  controlled **synthetic demo**: generated footage and scripted tracks, with no
  real place, traffic or crash. Its dispatch is the app's local simulated inbox.
  Nothing was sent anywhere.

## Additional real-traffic overlay preview

`presentation/exports/NearMiss-real-traffic-demo.mp4` is a separate 15-second
preview added after the 165-second challenge film. It uses Mike Bird’s
[Traffic Flow In The Highway](https://www.pexels.com/video/traffic-flow-in-the-highway-2103099/)
under the [Pexels License](https://www.pexels.com/license/). NearMiss processed
the real clip locally with YOLO11 nano and ByteTrack, then drew its observed
boxes, IDs, trails and provisional screening overlays. The source credit is
baked into the preview. See `static/real-demo/README.md` and its hash-bound
manifest for the actual inference settings and limitations. This preview is
not synthetic traffic. The eight-slide deck now uses the same real clip; the
existing 165-second film still presents the separately labeled controlled
synthetic example.
