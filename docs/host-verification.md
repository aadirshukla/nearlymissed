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
