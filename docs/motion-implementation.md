# Overview traffic story, Presenter Mode and threshold integration: implementation report

Worker: Claude Opus 5.5. Owned paths: `app.py`, `requirements.txt`, `nearmiss/motion.py`,
`nearmiss/presenter.py`, `tests/test_motion.py`, `tests/test_presenter.py`, this file.
I did not edit any other path. Nothing was committed, pushed, reset or merged. No browser or
desktop control was used. Visual QA and Git belong to the host.

## Verification (actual results)

- Full suite after the acceptance fixes (below): `.venv/bin/python -m pytest -q` → **235 passed**
  (23.7 s). Before my work it was 205 passed, with the comparison worker's files already in
  the tree.
- New tests: `tests/test_motion.py` (16) and `tests/test_presenter.py` (14). All pass.
- Both component scripts pass `node --check`. An AST check found no unused imports in the new
  or changed files. No linter is installed in the venv.
- I rasterised the four static SVG scene endpoints with macOS `qlmanage`, a CLI thumbnailer,
  and inspected them. This led to two fixes:
  - Car #3's label now sits below its box, because the truck covered it.
  - Verify now shows only the contact layer.
- This was not a browser check. Sticky behaviour, scroll triggering, mobile layout and
  keyboard shortcuts in a real browser are **unverified** (see "Host QA" below).
- Streamlit installed in `.venv`: 1.66.1. `requirements.txt` now pins `streamlit>=1.66.1,<2`.

## 1. Overview story (`nearmiss/motion.py`)

There are four chapters below the unchanged hero: Observe → Predict → Verify → Follow-up. The
photograph, headline, primary **Start guided demo** button, uploader, credit line and "How a
warning is earned" all remain. The story renders inside the existing opaque
`overview_explainer` panel (`app.py:985`), so the hero is untouched.

### Numbers are recomputed

`recompute_demo()` runs `demo.synthetic_tracks()` through the same steps `app.py` uses for
the demo:

1. full-frame zone
2. `detect_conflicts`
3. `normalize_events`
4. `deduplicate_events`
5. `detect_suspected_collisions` on the unenriched rows

It uses the **current sidebar thresholds**. Results are cached per distinct config with
`lru_cache` and take about 0.18 s on a cold start. Nothing is written to disk: a test asserts
that the cache directory is not created.

The story follows the earliest incident that a warning preceded. At default thresholds that is
`conflict-002` (car #3 / truck #4) → `incident-…` at frame 154. With default thresholds the
chapters show these values, taken from the records:

| Chapter | Facts |
|---|---|
| Observe | Frame 139 (6.95 s). 8 vehicles and 2 pedestrians in the 12.0 s clip. #3 has 38 stored rows, #4 has 5. Prediction needs 6 frames of history. |
| Predict | Scene frozen at the measurement frame 140 (7.00 s), where the projections come from. First warning at 7.10 s, frame 142, HIGH, labeled separately. Arrival gap 0.03 s. Time to projected meeting 0.81 s. HIGH threshold ≤ 0.50 s. Speeds 180 / 150 px/s. Confirmed after 3 frames. |
| Verify | First suspected contact at 7.70 s, frame 154. Warning lead 0.60 s. 5 signals. Peak overlap 57% of the smaller box. Opens as Uncertain. |
| Follow-up | Street Lab's own example assumptions (60 ft vs 40 ft, 3.5 / 2.5 ft/s, 2 s start-up). Typical walker 19.1 s → 13.4 s, slower walker 26.0 s → 18.0 s. Labeled "assumed" and "not measured from this scene". |

A test checks that changing `high_time_gap_seconds` to 0.02 s changes the Predict chapter. When
no warning exists, `build_story` returns `None` and only the pipeline explainer shows. When
there is a warning but no incident, Verify says there is nothing to confirm.

### Drawing is stored rows only

The diagram is a functional top-down plot, in source pixels (960×540), of the generated
intersection's road geometry and the stored boxes.

- **Positions:** each drawn position is the latest stored row at or before the shown frame.
  There is no interpolation (`_row_at`, which is tested). The script snaps to stored frames
  the same way.
- **Trails:** trails are observed ground points (box bottom-centre, as the detector uses)
  from the story window start up to the frame. They never look ahead, and they disappear once
  a track has left the frame.
- **Projected paths and meeting ring:** these come straight from the event's
  `participant_*_position`, `participant_*_predicted_end`, `conflict_point` and
  `conflict_region_radius_pixels`.
- **Contact marker:** this is the incident's `contact_point`.
- **Labels:** every SVG carries a "SYNTHETIC DEMO" tag, and the header has a full synthetic
  ribbon.

### Progressive enhancement and motion

- **Component:** the story uses `st.components.v2.component(..., isolate_styles=True)`. It is
  a shadow root in the page, **not an iframe**, so there is no nested scrolling.
- **Script-free reading:** each chapter's text, facts and one static SVG "scene endpoint" are
  plain HTML in the component's `html`. The component name includes a hash of that markup,
  so the script-free HTML always matches the data. Without the script, every caption is
  readable as stacked chapters with endpoints.
- **Desktop with script (≥ 960 px):** the root gets `is-enhanced`. One sticky diagram sits
  beside the chapters, and the per-chapter figures hide. An `IntersectionObserver` with the
  viewport as root (native page scroll) activates the chapter crossing mid-screen. The diagram
  then steps through stored frames in real time, between 0.5 and 2.4 s.
- **Narrow screens:** these keep the stacked endpoints.
- **Reduced motion:** the script follows `prefers-reduced-motion`. A visible **Reduce motion**
  toggle (`aria-pressed`, shown only once the script runs) saves the choice to `localStorage`.
  When motion is reduced, the diagram jumps to the endpoints.
- **Scope:** the script only queries inside its own `parentElement`. It never touches the
  Streamlit DOM, makes no network calls and loads no fonts or CDN assets. Its cleanup
  disconnects the observer and removes listeners and the animation frame, and it is
  idempotent across re-invocations.
- **Clipping guard:** `app.py:261-263` sets `overflow:visible` on the explainer's Streamlit
  wrappers so that no ancestor clips the sticky element.
- **Tables:** no evidence table is animated.

## 2. Presenter Mode (`nearmiss/presenter.py`)

### Entry and exit

- **Entry points:** a **Presenter mode** button under the sidebar navigation (`app.py:771`),
  plus **Present this walkthrough** at the end of the story (`app.py:989`). The eight
  navigation pages are unchanged; Presenter is a state mode, not a ninth radio option.
- **Starting state:** if no footage is open, entry starts the guided demo first
  (`open_presenter`, `app.py:669`). It uses the active footage when there is some.
- **Leaving:**
  - **Return to workspace** goes back to the page presenting started from.
  - Choosing any sidebar page exits via the radio's `on_change` (`presenter.stop`). This does
    not redirect, so the chosen page wins.
  - **Open … in the workspace** goes to the step's page through the existing state contracts.
    The source frame step uses the Investigation frame and tracks. The review step uses the
    selected incident.
- **No clicks or DOM injection:** all transitions are `on_click` / `on_change` callbacks.
  Nothing injects clicks or reaches into the DOM.

### Steps

| # | Step | Source |
|---|---|---|
| 1 | The warning | Decoded source frame at the first-alert frame (142), with stored boxes and trails (`draw_investigation_frame`) and the detector's projected paths. Plus the `explain_event` bullets. |
| 2 | Source frame | The same frame as decoded, with no overlays, and a static table of the stored rows at that frame. |
| 3 | Incident review | `annotate_incident_frame` at first contact, `explain_incident`, and the **read-only** operator review and simulated-dispatch status from `evidence_brief.explain_evidence`. |
| 4 | Street Lab | `streetlab.evidence_summary` metrics, and `crossing_comparison` with the example assumptions, labeled as placeholders. |
| 5 | Exported brief | Downloads from `evidence_brief.build_evidence_brief` and `streetlab.brief_markdown`, plus an expandable preview. |

### Controls

- **Keyboard:** **← Back** and **Next →** are native `st.button(..., shortcut="Left"/"Right")`.
  Streamlit scopes and clears them on every rerun, so there is no custom document listener.
  The buttons disable at the first and last steps.
- **Timer:** a tiny v2 component. Its `setInterval` is cleared in cleanup, and the elapsed
  time survives reruns through `presenter_started_at`. **Restart timer** is a native button.
  Without the script it reads "timer needs JavaScript; Back and Next still work".
- **Source ribbon:** shown on every step. It reads SYNTHETIC DEMO for the demo and UPLOADED
  FOOTAGE for uploads.

### Read-only and honest status

- **Read-only:**
  - The module imports nothing from `nearmiss.store`. An AST test forbids
    `review_incident`, `acknowledge_notification`, `reset_demo_reviews` and
    `delete_video_records`.
  - An AppTest confirms a demo incident, walks all steps, and checks that reviews and
    notifications are byte-for-byte unchanged. A pre-existing real-footage review also
    survives.
- **Evidence status panel**, on every step:
  - "Verified locally" lists the live recomputed counts for this run, frames that are
    decoded or plotted from stored rows, and local SQLite storage. For the demo it also
    states that automated tests pin the scripted clip's expected output and that this
    "checks the pipeline, not real-world accuracy".
  - "Not measured" lists real-footage accuracy and false-alarm/miss rates, safety outcomes,
    calibrated distances and speeds, and real dispatch.
  - No test count is shown as a metric. A test asserts that "170" and "passed" are absent.
- **Unanalysed uploads:** the presenter says the upload has not been analyzed and offers
  **Return to workspace**.

## 3. Threshold comparison on Library

The contract is in `docs/comparison-integration.md`, owned by the comparison worker. The
signature is unchanged and was confirmed from their file.

- **Placement:** Library shows a collapsed **Explore one threshold** expander
  (`st.expander(key="library_threshold", on_change="rerun")`, `app.py:1097`). It appears only
  when footage is open.
- **Lazy loading:** while collapsed, the page stops exactly as before. When the expander is
  open, the script continues into the normal analysis and imports
  `nearmiss.comparison_ui.render_comparison` lazily (`app.py:1987`). It renders inside the
  box with these arguments:
  - `tracks=tracks_for_detector`
  - `events=events`, the same events the app shows
  - `cfg=conflict_config`
  - `zone_polygon=analysis_zone`
  - `frame_size=(width, height)`
  - `data_source=source_kind`
  - `video_id=video_hash`
- **Errors surface:** import or render failures are not suppressed.
- **Snapshot:** the Library run does **not** rebuild `history_current_snapshot`
  (`app.py:1205`). Otherwise the "open Analysis to recompute before saving" notice would
  silently clear. If the footage has not been analyzed, the box says so.
- **Tests:** both states are tested. Collapsed shows no comparison controls; opening it (via
  session state) shows the run button and the synthetic banner.

## Size

- `app.py`: +127 / −32 lines. 26 of the removed and re-added lines are the re-indented
  snapshot block.
- New modules: `motion.py` 869 lines, about 210 of which are CSS/JS strings. `presenter.py`
  583 lines.

## Host QA needed (not verified by me)

1. At 1280×900:
   - The story diagram stays sticky while the chapters scroll, and switches near mid-screen.
   - The Streamlit wrappers do not clip it. If sticky fails, a wrapper outside
     `overview_explainer` likely has `overflow` set.
2. At 390×844, the stacked endpoints render and no sticky stage appears.
3. With OS reduce-motion on, the diagram jumps between endpoints. The toggle flips and
   persists.
4. With component JS blocked, the chapters are still readable.
5. In Presenter:
   - ← and → work.
   - They do not fire while typing in a sidebar text field or using sliders. This relies on
     Streamlit's shortcut handling and is untested in a browser.
   - The timer ticks and restarts.
   - Downloads open correctly.
6. The visual balance of the "Present this walkthrough" button and the sidebar button.

## Gaps

- No browser screenshots were taken by me. Contrast was chosen against the existing palette
  (light text `#D6D3D1`/`#F5F5F4` on `#0B0B0C`) but not measured.
- The story always tells the synthetic demo, even when uploads exist. It is shown only on the
  no-footage landing.
- Presenter's Street Lab step uses the example assumptions, not any values the user typed on
  Street Lab.
- The `localStorage` motion preference is per browser and is not synced to Python.

## Acceptance fixes (host and native review, second pass)

1. **Projection and frame alignment**, in the story and in Presenter step 1.
   - **Story:** the Predict scene now freezes on the event's measurement frame
     (`frame_index` 140, 7.00 s), the same frame its `participant_*_position` and projected
     paths come from. The dashed paths therefore start at the drawn boxes, with no detached
     paths. The diagram note reads "paths measured 7.00 s (frame 140) · first warning 7.10 s
     (frame 142)". The facts list "Projection measured" and "First warning" as separate rows.
     The no-incident Verify fallback uses the same frame.
   - **Presenter:** the warning image now decodes and draws frame 140. Its caption and the
     side text give the measurement time and the first-alert time separately.
   - **Tests:** both check that each projection origin equals the stored box ground point at
     the drawn frame.
   - I re-rendered both views offline into `.scratch/motion/svg/` and confirmed the paths now
     start at the boxes. The decoded demo frame's own stamp reads t=07.00s.
2. **Accessibility at every viewport.**
   - Each static endpoint SVG now has a full text alternative (`scene_description`): time and
     frame, which box is which participant and its direction, the number of other road users,
     the projection measurement and first-alert frames, the contact point, and the crossing
     assumptions.
   - On desktop the endpoints are **visually hidden with a clip, not `display:none`**, so they
     stay in the accessibility tree.
   - The sticky stage stays `aria-hidden` because it is a visual duplicate.
3. **Playback is gated on the desktop breakpoint.**
   - One `STAGE_QUERY` (`(min-width: 960px)`) is shared by the CSS and the script.
   - Below it the script does not observe chapters or run `requestAnimationFrame`.
   - Crossing the breakpoint calls `disable()`, which cancels the frame and disconnects the
     observer, or `enable()`. Cleanup removes the width listener too.
4. **Presenter status labels.** In step 3, operator review and simulated dispatch are now
   plain wrapping text ("**Operator review:** Confirmed Incident", "**Simulated dispatch:**
   Acknowledged") instead of `st.metric` columns, so they are never truncated and they stack
   on narrow screens. Tests assert the full words appear and that no metric is used.

Still for host browser QA: the 1600 px step-3 layout with the sidebar open, 390 px stacking,
and that the stage stays idle below 960 px. Desktop scrolling and ArrowRight were already
confirmed by the host.
