# NearMiss — challenge demo guide

A truthful 2–3 minute walkthrough of the controlled synthetic demonstration, plus
what is implemented versus simulated and how to reproduce it.

The app has eight sections: Overview, Analysis, Investigation, Incidents,
Explain & Share, Dispatch, Street Lab, Library. The guided steps cover the
five core sections. The other three are optional detours, described below.

**Choose the right entry:** **Start guided demo** now opens real traffic with actual locally precomputed YOLO/ByteTrack overlays. This scripted incident-review walkthrough uses **Controlled synthetic example**, the separately labeled secondary button. For the real-footage source and limitations, see [the real-traffic guide](real-traffic-demo.md).

## Before you start

```bash
.venv/bin/python -m streamlit run app.py
```

No upload, network connection, or model weights are needed for the demo. The
first click generates a 12-second clip and its scripted track rows locally
(under a second on a laptop) and caches them in `.nearmiss_cache/`. If you want
a clean inbox before presenting, use **Reset demo reviews**. It clears decisions
and simulated notifications for the synthetic demo only.

All numbers below are what the detectors return with **default** thresholds. If
you change Advanced settings, the results change, and that is part of the point.

## Script (about 2½ minutes)

**0:00 — Overview (20 s).**
The landing page shows a full-bleed street photograph headed "See the moments
before impact." The photo is labeled as illustrative context, not analyzed
footage. "NearMiss looks for close calls in traffic footage: moments when two road users'
projected paths and timing converge. Every warning stays tied to evidence a
person can check. I'll use the guided demo. It is a generated intersection,
labeled SYNTHETIC DEMO everywhere, so no real place or real crash is shown."
Click **Controlled synthetic example**, the secondary button in the hero, above the uploader.

**0:20 — Analysis (50 s).**
Point at the amber source banner. "The footage and tracks are scripted. Only
object detection is skipped. Prediction, incident evidence, rendering, review,
and the inbox are the same code used for uploaded footage."
Play the annotated clip. With default thresholds the detectors return:
- **HIGH at about 0:02.8**: an eastbound car and a northbound car projected to
  reach the same point roughly 0.24 s apart. The northbound car brakes and stops,
  so there is no contact. That is a near miss.
- **HIGH at about 0:07.1**: a westbound car and a southbound truck, about 0.03 s
  apart.
- **MEDIUM at about 0:09.8**: a car closing on a slower car ahead in the same lane
  (time headway under 1 s).

Open **Why each warning was raised** and pick one. "Each line is a measurement:
arrival times, the gap compared with the HIGH/MEDIUM/LOW thresholds, footprint
overlap, closing speed, and the longest consecutive run of frames at that
severity during the episode. These are image-space
pixels, not real speeds or probabilities." Optionally open **Demo script versus
detector output** to show the scenes were staged but the warnings were computed.

**1:10 — Incidents (40 s).**
"A separate detector looks for suspected collisions. It needs persistent box
contact, converging motion beforehand, and a motion response such as sudden
braking. It does not rely on the prediction." Show the first-contact frame at
**0:07.7**, the replay clip, and the evidence list: five supporting signals
observed across the contact episode. They are correlated measurements of one
event, not independent votes. Also point out *Prediction warning … raised
0.60 s before first contact*. Click **Confirm incident**.

**1:50 — Dispatch (15 s).**
"Confirming creates exactly one local, simulated notification. Nothing is sent
to emergency services or anyone else." Click **Acknowledge**. If asked, mention
that dismissing a confirmed incident later marks the notification as
*Withdrawn* rather than leaving it saying "confirmed".

**2:05 — Street Lab (30 s).**
"Street Lab connects patterns to a community conversation. It lists which
interactions warrant human review and why." Adjust **Current crossing** or
**Walking speed**. "This crossing-time comparison is arithmetic on assumptions I
enter. It is not a crash reduction, and any design idea is a review hypothesis
that needs field measurement." Tick a checklist item and download the brief
(PDF or Markdown). It contains the same content as the page, including the
synthetic label. Changes are worded by direction ("33.3% less time",
"50.0% more time", "no change").

**Optional detours (if time allows).**
- **Investigation**: pick *Jump to evidence* → **Go**. The frame moves to the
  warning's first alert (conflict-001 at 0:02.8, the same time Analysis
  shows). The tracks named in that record are selected, so the evidence table
  lists it. Boxes are stored observations on the source frame.
- **Explain & Share**: per-record evidence brief (Markdown) carrying
  the review status and synthetic label.
- **Library**: save the current run to compare runs later. Only summaries and
  settings are stored, never footage. If you change a threshold while on the
  Library, Save is hidden until Analysis recomputes, so a run is never saved
  under settings it was not computed with.

**2:35 — Close (10 s).**
Click **Return to your footage**. "The same workflow runs on an uploaded MP4
with YOLO and ByteTrack."

## Implemented versus simulated

| Capability | Status in this build |
|---|---|
| YOLO + ByteTrack detection/tracking of uploaded MP4s | Implemented (needs model weights; first run downloads them) |
| Demo footage and track rows | **Synthetic**: generated locally, labeled in frames, UI, CSV/JSON (`data_source`), PDF, and brief |
| Conflict prediction (crossing paths and same-direction following) | Implemented, heuristic, image-space |
| Independent suspected-collision evidence | Implemented, heuristic, image-space |
| Plain-language evidence explanations | Implemented; derived only from detector fields |
| Human review persisted in SQLite | Implemented (local file `.nearmiss_data/nearmiss.db`) |
| Dispatch notifications | **Simulated** local inbox; nothing is ever sent |
| Street Lab crossing comparison | **Illustrative arithmetic** on user-entered assumptions |
| Crash reduction, safety rating, real city/crash data | **Not provided** |
| Frame-by-frame Investigation with evidence jump | Implemented; overlays stored observations only, runs no detector |
| Explain & Share evidence briefs | Implemented; derived from stored records and reviews |
| Analysis Library (local SQLite snapshots) | Implemented; summaries and settings only, no footage |
| Accuracy validation on real-world footage | **Not done** in this build |

## Reproduce

1. `.venv/bin/python -m pytest -q` → 170 passed in the final run (after
   merging `origin/main`). Browser checks at desktop 1280 px and mobile
   390 px were done by the host session. Commits and pushes were also made by
   the host session. The demo
   flow is covered end to end in `tests/test_app_demo_flow.py` (Streamlit
   AppTest with a temporary cache and database).
2. `.venv/bin/python -m streamlit run app.py`, then **Start guided demo**.
3. The demo is deterministic. Its ID `synthetic-demo-<digest>` is derived from
   the scripted scenario in `nearmiss/demo.py`, so reviews survive cache clears,
   and **Reset demo reviews** affects only that ID. Uploaded videos use 64-hex
   SHA-256 IDs, which can never match the demo prefix.

## Known limits

- Every measurement is in image-space pixels from one camera view. Nothing
  is calibrated to metres, real speeds or probabilities.
- Detectors are heuristic and regression-tested on synthetic tracks. They
  have not been validated for accuracy on real footage.
- Footprints are circles sized from box width, so following/contact timing
  is an approximation.
- Street Lab distances and walking speeds are user-entered placeholders.
