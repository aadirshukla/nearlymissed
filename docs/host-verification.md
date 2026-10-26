# Host acceptance record

Verified locally on 2026-10-25 before publication to main.

- Full suite: `python -m pytest -q` in the project virtual environment: **237 passed**.
- Native Python acceptance review accepted the six targeted correctness fixes, with 12 targeted cases passing.
- Merged collaborator commit `f2bfe01` (photo landing) with the eight-page demo workflow. Preserved the photograph, headline, upload and explainer, with a prominent guided-demo entry.
- Browser checked the merged landing at 1280 × 900 and 390 × 844. Both fit; the mobile sidebar collapses without obscuring the page.
- The merged guided-demo entry produced 3 conflict warnings and 1 suspected incident from the generated 12-second clip, with synthetic labels visible.
- Investigation filter chips have light text (`#F5F5F4`) on dark backgrounds (`#24211D`). Evidence pages retain the dark layout.
- Browser checks also covered human confirmation, local dispatch acknowledgment, interactive Street Lab assumptions, saving a Library run, jumping to warning frame 56 at 2.8 seconds with tracks 1 and 2, and downloading a labeled evidence brief.
- Desktop and mobile screenshots were saved in the host workspace reports folder.

These checks establish the local demonstration and regression behavior. They do not establish real-footage detector accuracy, deployment, emergency integration or competition submission. Synthetic tracks, local simulated dispatch and Street Lab assumptions are labeled accordingly.

## Presentation and motion acceptance

- The four-chapter traffic story was checked at desktop and 390-pixel mobile widths, with no horizontal overflow. Reduced motion was toggled on and off.
- Presenter keyboard navigation advances the evidence workflow, while arrow keys on a focused sidebar slider adjust that slider without advancing the presentation.
- Prediction overlays use their measurement timestamp, separately labeled from the first warning; overlays remain hidden during position transitions.
- A controlled comparison at 1.75 versus 1.25 seconds retains all three demo warnings. The zero-difference result is displayed honestly and links back to source evidence.
- Motion contracts passed 32 targeted cases, including a behavioral JavaScript transition regression.

- Presentation source passed TypeScript and React Hooks lint. Native React and TypeScript reviews accepted the final layout, timing, and font-ready document measurement.
- The deck passed six behavioral tests, including full 180-second reveal scheduling, suspension recovery, and pointer/keyboard timer start. Host browser checks covered notes, keyboard navigation, reduced motion, and corrected slides 3, 4, and 7.
- The PDF contains eight pages. Host visually inspected the warning geometry, source-evidence page, and credits/next-step page after the footer-band fixes.
- Source and PDF checkpoint `a46169f` was pushed to main and the feature branch and verified by remote refs.

- Final soundtrack and silent MP4 exports each have 1920 × 1080 pixels, 30 fps and 4,950 frames (165.000 seconds of video). AAC padding makes the soundtrack container 165.013 seconds; the silent container is 165.000 seconds.
- Both exports have identical video-stream SHA-256 `287abaa57f676717d022bbe1b2b1beda127382af69635080520a9e2aed473ca4`. Soundtrack audio has mean −24.7 dB and peak −7.3 dB; the silent backup has no audio stream.
- Final MP4 playback was opened in the app browser. Checked close-ups retain the fixed SYNTHETIC DEMO / LOCAL PROTOTYPE label. The poster and eight-page PDF are included; hashes and probes are in `presentation/exports/verification.json`.

## Real-traffic follow-up (2026-10-25)

- Downloaded licensed Mike Bird / Pexels fixed-camera highway footage. Rejected an earlier rotating-camera aerial candidate; it is not bundled.
- Processed the 15-second, 1280 × 720, 24 fps clip with actual local YOLO11 nano and ByteTrack at confidence 0.30 / IoU 0.50. Source SHA-256: `e25026291ef2990862e588cc8648883e61f6c7adcc66d182e3b72881ec73a2e4`.
- Actual outputs: 360 frames, 5,666 track observations and 78 tracker IDs. IDs are not verified unique physical vehicles. Default heuristics produce 41 warning candidates and 5 suspected-contact candidates; none is verified, and the normal traffic clip exposes false-alarm limitations.
- Bundled source, metadata and track hashes pass the real-demo loader. The credited preview is H.264, 360 frames and exactly 15.000 seconds. The separate exported preview matches the bundled annotated preview byte for byte.
- Fresh-server browser checks verify that Start guided demo opens the real sample, with REAL TRAFFIC SAMPLE provenance and real-car overlays. Playback reached the end of the 15-second clip. At 482 pixels, document width equals content width with no horizontal overflow.
- Full follow-up suite: **271 passed**. Native Python acceptance reran 5 targeted regressions and accepted both provenance corrections: real-vs-upload comparisons no longer imply synthetic data, and changed-model tracking origin/settings propagate into actual Markdown/PDF exports and Library views.
- Source and uncertainty notice is compact, with full credit/settings in a collapsed details panel. The real sample labels the count as Vehicle track IDs, explaining ID switches. The default synthetic test assertions remain intact behind the separate controlled-example entry.
