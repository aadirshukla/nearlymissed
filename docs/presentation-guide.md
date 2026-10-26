# NearMiss presentation guide

Two deliverables, both built from the same metrics file so every number matches
the app:

| Deliverable | Editable source | Output |
|---|---|---|
| 165 s challenge video (text + music, no voice) | `presentation/video/` (Remotion, React/TypeScript) | `presentation/exports/NearMiss-demo.mp4` (soundtrack), `NearMiss-demo-silent.mp4` (no audio), `NearMiss-demo-poster.png` |
| 3-minute, 8-slide live deck | `presentation/deck/index.html`, `deck.css`, `scenes.js`, `deck.js`, `notes.js` | Opens in a browser from disk; PDF backup `presentation/exports/NearMiss-deck.pdf` |

Credits, licences and provenance: `docs/creative-credits.md`.

**Final exports verified (2026-10-25, America/Los_Angeles):** soundtrack and silent MP4s are rendered at 1920×1080, 30 fps, 4,950 frames: exactly 165 seconds of video. The soundtrack container lasts 165.013 seconds because of AAC padding; the silent container lasts 165.000 seconds. Both video streams have the same SHA-256. The soundtrack has nonzero audio (mean −24.7 dB, peak −7.3 dB); the backup has no audio stream. See `presentation/exports/verification.json`.

The final MP4 was opened for playback, and the browser deck and eight-page PDF were inspected. Copyable speaking notes: `presentation/speaker-notes.md`.

## Reproduce everything

All commands start from the repo root unless a `cd` is shown. Install Python requirements into `.venv`, and have Node.js, npm and FFmpeg available. On a fresh checkout, run `npm ci` once in each of `presentation/video/` and `presentation/deck/`. The exported MP4/PDF and bundled browser deck work without the authoring dependencies.

```sh
# 1. Facts from the synthetic demo pipeline (+ full pytest run for slide 7).
#    No camera, no model download, no network. Writes presentation/data/demo-metrics.json
#    and copies it to deck/data/ (.json and .js) and video/src/data/.
.venv/bin/python presentation/scripts/extract_metrics.py --tests
#    Add --clips to regenerate the demo clips in .scratch/ (needs ffmpeg).

# 2. Gather fonts, hero image, host captures and music manifest (plain Node, no bundler).
cd presentation/video && node scripts/prepare-assets.mjs

# 3. Static checks for the video source (no bundler, no render).
npm run typecheck && npm run lint

# 4. Deck: PDF backup, static checks, engine behaviour tests (no browser).
cd ../deck
npm run pdf        # .venv ReportLab -> ../exports/NearMiss-deck.pdf, fails if anything enters the HUD band
npm run check      # 8 slides, 180 s, speakers, local assets, notes tile 0:00-3:00, PDF has 8 pages
npm test           # node --test tools/engine.test.mjs
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
- Presenter notes are about 427 words (~2.4 words/s); each cue shows its window.
- The HUD sits in the bottom 64 px of the stage (`--hud-band` in `deck.css`).
  No slide content goes there; the PDF build fails if any does.

### Numbers on slide 3 (and the video's "why" beat)

The warning `conflict-001` has two different times, and the slides keep them apart:

- **Measurement row, 00:02.7 (frame 54).** The ETAs (0.75 s and 0.99 s), the
  0.24 s gap and the separation are measured on this frame. The diagram draws
  both cars at this frame, starts the projections at the stored bottom-centre
  anchors from this frame, and labels itself "measurement frame 54 · 00:02.7".
  The view is fitted to both whole boxes and the conflict point, so neither car
  is clipped.
- **First alert, 00:02.8 (frame 56).** When the warning is first raised, and
  where "Jump to evidence" opens (slide 4). It is used only for navigation and
  timelines.

Times and units are joined with non-breaking spaces so "0.24 s" never wraps.

## Implementation report (source pass, 2026-10-25, America/Los_Angeles)

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
