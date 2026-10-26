# NearMiss presentation guide

Two deliverables, each built from a metrics file derived from the app's own
pipeline so every number matches the app:

| Deliverable | Footage | Editable source | Data | Output |
|---|---|---|---|---|
| 165 s challenge video (text + music, no voice) | **Controlled synthetic demonstration** (generated footage, scripted tracks), unchanged | `presentation/video/` (Remotion, React/TypeScript) | `presentation/data/demo-metrics.json` | `presentation/exports/NearMiss-demo.mp4` (soundtrack), `NearMiss-demo-silent.mp4` (no audio), `NearMiss-demo-poster.png` |
| 3-minute, 8-slide live deck | **Real footage** (Mike Bird / Pexels) with actual NearMiss output | `presentation/deck/index.html`, `deck.css`, `scenes.js`, `sync.js`, `deck.js`, `notes.js` | `presentation/data/real-metrics.json` (`deck/data/real-metrics.js`) | Opens in a browser from disk; PDF backup `presentation/exports/NearMiss-deck.pdf` |

The film and the deck now show different footage on purpose. The film remains
the earlier controlled synthetic demonstration (a known, scripted incident used
to walk through review and simulated dispatch). The deck shows ordinary real
traffic with no incident labels: every warning and suspected contact on it is
an unverified, experimental candidate.

Credits, licences and provenance: `docs/creative-credits.md`.

**Final exports verified (2026-10-25, America/Los_Angeles):** soundtrack and silent MP4s are rendered at 1920×1080, 30 fps, 4,950 frames: exactly 165 seconds of video. The soundtrack container lasts 165.013 seconds because of AAC padding; the silent container lasts 165.000 seconds. Both video streams have the same SHA-256. The soundtrack has nonzero audio (mean −24.7 dB, peak −7.3 dB); the backup has no audio stream. See `presentation/exports/verification.json`.

The final MP4 was opened for playback. The revised real-footage browser deck and eight-page PDF were independently reviewed and inspected by the host, including moving playback, synchronized freezes, source captures, reduced motion and notes. Copyable speaking notes: `presentation/speaker-notes.md`.

## Reproduce everything

All commands start from the repo root unless a `cd` is shown. Install Python requirements into `.venv`, and have Node.js, npm and FFmpeg available. On a fresh checkout, run `npm ci` once in each of `presentation/video/` and `presentation/deck/`. The exported MP4/PDF and bundled browser deck work without the authoring dependencies.

```sh
# 1a. Film: facts from the synthetic demo pipeline. Writes presentation/data/demo-metrics.json
#     and copies it to video/src/data/ (and, historically, deck/data/; the deck no longer reads it).
.venv/bin/python presentation/scripts/extract_metrics.py --tests
#     Add --clips to regenerate the demo clips in .scratch/ (needs ffmpeg).

# 1b. Deck: facts from the real traffic sample (+ full pytest run for slide 7).
#     No detection or tracking is run: the cached YOLO11n + ByteTrack rows in
#     static/real-demo/tracks.json go through the app's post-processing at default
#     settings, and the script stops unless the counts match static/real-demo/manifest.json.
#     Writes presentation/data/real-metrics.json and deck/data/real-metrics.js, and copies the
#     clip, exact-frame stills (OpenCV), host captures and community brief to deck/assets/real/.
.venv/bin/python presentation/scripts/extract_real_metrics.py --tests

# 2. Gather fonts, hero image, host captures and music manifest (plain Node, no bundler).
cd presentation/video && node scripts/prepare-assets.mjs
#    (Deck fonts, GSAP and hero: cd presentation/deck && npm run vendor.)

# 3. Static checks for the video source (no bundler, no render).
npm run typecheck && npm run lint

# 4. Deck: PDF backup, static checks, engine behaviour tests (no browser).
cd ../deck
npm run pdf        # .venv ReportLab -> ../exports/NearMiss-deck.pdf, fails if anything enters the HUD band
npm run check      # 8 slides, 180 s, speakers, local assets, notes tile 0:00-3:00, PDF has 8 pages,
                   # clip/tracks hashes match the app manifest, stills for every freeze, no synthetic labels
npm test           # engine.test.mjs (navigation, timer, rehearsal, leave) + sync.test.mjs (video/overlay sync)
```

### Render the video (host only)

On this machine Remotion's esbuild step hangs when its working directory is
under `~/Documents`; the same binary works elsewhere. Render from a copy
outside `~/Documents`:

```sh
cd presentation/video
REMOTION_BROWSER_EXECUTABLE=/path/to/chrome npm run render:isolated   # env var optional
# or: node scripts/render-isolated.mjs --cache=$HOME/.cache/nearmiss-render-20261025
```

`scripts/render-isolated.mjs` runs `prepare-assets` here, copies `video/`
(with `node_modules`) to `<cache>/video`, runs `node scripts/render.mjs` there
(output `<cache>/exports`, ending with `scripts/check.mjs`: 1920x1080, 30 fps,
4950 frames, audio only in the soundtrack file), and only then copies the three
files back to `presentation/exports/`. A draft render (missing capture) is
never copied. The host used the same prepared-copy → isolated render → check → copy-back flow for the final export. The optional wrapper was syntax-checked and independently reviewed; it was not separately used for a second full render.

Music file: `presentation/video/public/music/traffic-bed.mp3` ("Signal to
Noise", Scott Buckley, CC BY 4.0; first 165 s, 1.5 s fade-in, 4 s fade-out,
volume 0.5). The silent file is an ffmpeg stream copy without audio.

## The 3-minute deck

Open `presentation/deck/index.html`. Keys: → / Space next reveal, ← back,
Shift+→/← whole slide, 1–8 jump, N notes, T reset timer, R 180 s
auto-rehearsal, M reduced motion, F fullscreen, ? help. `index.html?print`
shows all eight final states for printing.

| # | Slide | Speaker | Time | Reveals |
|---|---|---|---|---|
| 1 | The moment counts | Srivibhav | 0:00–0:15 | 2 |
| 2 | What NearMiss does | Srivibhav | 0:15–0:35 | 3 |
| 3 | How a warning is earned | Srivibhav | 0:35–1:05 | 4 |
| 4 | Inspect the source | Srivibhav | 1:05–1:30 | 3 |
| 5 | Human review | Aadi | 1:30–1:55 | 3 |
| 6 | From evidence to follow-up | Aadi | 1:55–2:20 | 2 |
| 7 | Built · verified · not yet proven | Aadi | 2:20–2:45 | 3 |
| 8 | Proposed next step | Aadi | 2:45–3:00 | 2 |

Timing notes:

- The elapsed timer waits on page load and starts when you interact with the presentation, including a key or click reveal. Press T to restart it, or R to run the scheduled rehearsal.
- Auto-rehearsal (R) spaces reveals evenly within each slide's window. If the
  tab was in the background (or keys were pressed), the next frame restores the
  exact scheduled slide and reveal without animation. It clears REHEARSAL at 3:00.
- Presenter notes are about 443 words (~2.46 words/s); each cue shows its window.
- The HUD sits in the bottom 64 px of the stage (`--hud-band` in `deck.css`).
  No slide content goes there; the PDF build fails if any does.

### Real footage on the deck: what is shown and what is not claimed

Source: Mike Bird, “Traffic Flow In The Highway”, Pexels video 2103099,
Pexels License; first 15 s, 1280×720, 24 fps, 360 frames, source SHA-256
`e25026291ef2990862e588cc8648883e61f6c7adcc66d182e3b72881ec73a2e4`. Tracking
rows are the app's precomputed YOLO11n + ByteTrack output (5,666 rows, 78
tracker IDs; IDs are not a verified count of vehicles). At default settings the
pipeline emits 41 warning candidates (7 HIGH, 16 MEDIUM, 18 LOW) and 5
suspected contact candidates. The clip is ordinary traffic with no ground-truth
labels; none of these is verified, perspective and occlusion produce false
alarms, and no detector accuracy follows from it. Nothing was confirmed and no
notice exists for any real candidate.

| Slide | What plays | Overlay |
|---|---|---|
| 1 | Source clip frames 168→231 at 1×, then freezes on the exact still of frame 231 | Stored boxes of every presented frame (all tracks faint, #38/#86 amber) |
| 3 | Frames 219→243, freeze on the measurement frame 243 | Event's stored boxes, 0.8 s bottom-centre trails, projections from the stored anchors to the stored conflict positions |
| 4 | The app's own annotated render (`static/real-demo/annotated.mp4`, overlays and credit baked in) | 46 timeline markers (41 warnings coloured by severity, 5 contacts filled) |
| 5 | Frames 218→242 at 0.5×, freeze on first box contact, frame 242 | Stored boxes of #38/#86 in coral, contact point |

Sync: `sync.js` maps `requestVideoFrameCallback` media time to the presented
frame (rAF + `currentTime` fallback) and the overlay is redrawn from that
frame's stored rows; tracks missing a frame are not interpolated. Every freeze
shows a still decoded by OpenCV from the same file at the same frame index, so
the picture and boxes match exactly in the browser, in reduced motion and in
print. `tools/sync.test.mjs` checks this against the real `scenes.js`.

**The case followed on slides 1, 3, 4 and 5** is warning `conflict-029`
(HIGH, car #38 / car #86) and its linked suspected contact
`incident-31370bdbe7ff`. It was chosen because both ETAs are measured (inside
the 2 s look-ahead, not capped), its measurement frame differs from its first
alert, and the same pair was flagged by both detectors. The deck says plainly
that to our eyes it is queued traffic overlapping in perspective (#86 is the
nearer car in the same lane), labelled "our reading, not a recorded review".

- **First alert: frame 231, 00:09.6.** Slide 1 freezes here; slide 4's card jumps here.
- **Measurement row: frame 243, 00:10.1.** ETAs 1.146 s (#38) and 1.196 s (#86),
  arrival gap 0.05 s → HIGH (≤ 0.50 s), time to conflict 1.17 s, 18-frame
  episode. #86 has no detection on frame 243; the detector used its frame-242
  row (one frame old, inside the 0.12 s observation age), and slide 3 says so.
  `explain_event()` classifies the pattern as same-direction following.
- **Linked suspected contact: frame 242, 00:10.1.** 5 signals (persistent box
  contact, significant overlap, converging before contact, abrupt motion change,
  sudden deceleration); box "contact" persists 116 frames (4.8 s); warning came
  0.458 s earlier. App status: Uncertain (default), like all five candidates.

None of the synthetic film's values (ETAs 0.75/0.99 s, gap 0.24 s, frames
54/56) appear on the deck.

**Host captures** (`.scratch/deck-real-captures/`, copied to
`deck/assets/real/`): live app in Chrome at 1440×1000 on this clip.
Investigation shows original frame 34 with tracks #20/#22 (warning
`conflict-007`, first alert frame 35; the slide does not claim the capture is
frame 35). Incidents is cropped to the candidate-independent perspective caveat
and the Confirm / Dismiss / Uncertain controls (captured on candidate #16/#20).
Street Lab shows 41 warnings, 7 HIGH, 5 suspected, 0 confirmed. The community
brief is the actual Street Lab Markdown download (no review decisions changed;
its "78 vehicles tracked" means 78 tracker IDs).

**Street Lab arithmetic** on slide 6 uses the app's default stated assumptions
(60 ft → 40 ft crossing, 3.5 and 2.5 ft/s, 2 s start-up): 19.1 → 13.4 s and
26.0 → 18.0 s. It is arithmetic on assumptions, not a road-safety measurement.

## Implementation report: real-footage deck pass (2026-10-25, America/Los_Angeles)

Claude Opus (`claude-opus-5-5`), deck and PDF only; the app and the 165-second
film were not touched.

1. **Data:** new `presentation/scripts/extract_real_metrics.py` derives
   `presentation/data/real-metrics.json` / `deck/data/real-metrics.js` from the
   cached real tracks with `enrich_tracks_with_zone`, `detect_conflicts`,
   `normalize_events`, `deduplicate_events`, `detect_suspected_collisions`
   (full-frame zone, `DEFAULT_CONFLICT_CONFIG`, `zone_is_user_defined=False`).
   It verifies source/tracks/metadata hashes and counts against the manifest
   and the case's stored boxes against the tracked rows. Full Python suite:
   **271 passed** (run by the script, 2026-10-25).
2. **Deck:** slides 1, 3 and 5 replace the synthetic SVG intersection with the
   real clip, frame-synchronised stored boxes and exact-frame freezes; slide 4
   plays the app's real annotated render and shows the Investigation capture;
   slides 2, 5, 6, 7 and 8 carry the real-footage label, credit and limits;
   dispatch is explained only conditionally (0 confirmed, 0 notices). Synthetic
   captures and `data/brief.js` were removed from the deck. Brand, keyboard
   navigation, reduced motion, 15/20/30/25/25/25/25/15 s timing and speaker
   split are unchanged; content stays above the HUD band.
3. **Checks:** `npm run check` (27 checks), `npm test` (18 tests: 7 engine incl.
   `leave()` on every navigation path, 11 sync incl. frame mapping, overlay =
   tracks.json, freeze stills, leave/re-enter cancellation, reduced motion,
   print final states), `npm run pdf` (8 pages, band clear). Browser QA is the
   host's.

## Implementation report (earlier synthetic-deck source pass, 2026-10-25, America/Los_Angeles)

Historical: this pass describes the earlier synthetic version of the deck.

Done and checked in this pass (Claude Opus `claude-opus-5-5`):

1. **Video source:** `npm run typecheck` and `npm run lint` pass. The
   measurement/first-alert split, BriefBeat font-ready measurement, required
   `warning.png` capture and OFL notices were already in place and kept.
   The hero is now labelled "Illustrative image" (was "photograph"), because
   its origin is unverified.
2. **Deck slide 3** (`scenes.js`, `build_pdf.py`): diagram, projection origins,
   tag and ETAs use the 2.7 s measurement row; the first alert (2.8 s) appears
   only as a labelled navigation time. Both cars fully in view. Slide 1 note
   separates the first alert from the measured gap. Notes for slide 3 say 2.7 s
   measured vs 2.8 s warning. Slide 1's "The question for us was…" became the
   product purpose.
3. **Footer band:** content ends at y ≤ 1016 on all 8 slides. Slide 4 media is
   scaled to 0.9; the slide 4 side note and slide 5 side column were tightened;
   photo label and footnote sit above the band. Design, palette and type are
   unchanged.
4. **Deck engine** (`deck.js`): rehearsal restores the exact scheduled
   `{slide, reveal}` with `go(i, k, {animate: false})`; the first click reveal
   starts the timer. `tools/engine.test.mjs` runs the real `deck.js` in Node
   against a minimal fake DOM: 6 tests pass (timer idle before navigation;
   pointer and keyboard start it; restore after a long frame gap; restore after
   a stray key; frame-by-frame run visits all 30 slide/reveal states, ends 8/8 and clears
   REHEARSAL).
5. **Metrics:** full Python suite **237 passed** (run 2026-10-25 18:48 PDT via
   `extract_metrics.py --tests`). Metrics, deck data, `prepare-assets` and the
   PDF were regenerated from the final code. Deck and video clips are
   byte-identical (SHA-256) to the app's cached annotated render.
6. **Credits:** AI assistance itemised; music credit and OFL notices kept; no
   voice; hero image origin marked unverified.
7. **PDF:** `presentation/exports/NearMiss-deck.pdf`, 8 pages, built by
   `deck/tools/build_pdf.py` with the band check passing. The host opened and inspected it after generation.
8. **Wrapper:** `video/scripts/render-isolated.mjs` (`npm run render:isolated`),
   syntax-checked only.

The source pass did not render or browse. Host acceptance then inspected corrected deck slides, notes, reduced motion, pointer timer behavior, PDF pages, and representative video frames; rendered the final video in the isolated build folder; checked both exports; and opened the final MP4. Extra QA stills remain in the host scratch folder rather than the delivery package.

## App entry after the real-traffic update

The app’s primary **Start guided demo** now opens real traffic with actual
precomputed tracking. The eight-slide deck now uses that same real footage
(see “Real footage on the deck” above). The 165-second film continues to
demonstrate the explicitly labeled controlled synthetic scenario. To
reproduce those captures or present the known incident-review sequence, choose
**Controlled synthetic example** on Overview, or **Present the controlled
synthetic walkthrough** below the schematic. The separate 15-second
`presentation/exports/NearMiss-real-traffic-demo.mp4` shows the new real-footage
overlays; its source and model-output boundaries are in `static/real-demo/`.
