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
