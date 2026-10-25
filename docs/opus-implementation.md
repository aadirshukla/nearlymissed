# Opus implementation report: NearMiss challenge bundle

Branch `codex/congressional-demo`, merged with `origin/main`. The user
authorized commits and pushes, including pushing to main. The **host session**
made every Git commit, merge commit and push. This worker made none of them,
and nothing was deployed or sent to an external service. Early on, a scratch
tuning script was briefly written to `/tmp/nmdemo/`. It was moved into the
gitignored `.pytest_cache/` and deleted.

## Files

**Modified**
- `app.py`: guided demo entry, source banners, guided steps, Street Lab page,
  evidence explanations, PDF cache-key fix, withdrawn-notification handling,
  provenance in exports, refreshed styling. It also wires in the parallel
  worker's Investigation, Explain & Share and Library pages, following their
  integration docs.
- `conflict_detector.py`: targeted same-direction following branch, also
  mirrored in diagnostics.
- `nearmiss/config.py`: three defaults for the following branch.
- `nearmiss/incidents.py`: strict positive prediction lead; first-contact
  contact point; merge keeps frame-aligned fields.
- `nearmiss/store.py`: withdraw/restore notifications; scoped
  `delete_video_records`; DB default resolved at call time.
- `nearmiss/report.py`: `report_cache_key`; provenance banner and title.
- `nearmiss/video.py`: shared `transcode_for_browser` helper (replaces two
  duplicated ffmpeg blocks); `data_source` CSV column when rows carry it.
- `README.md`: demo, Street Lab, tool pages, fixes, test count.

**New (mine)**
- `nearmiss/demo.py`, `nearmiss/explain.py`, `nearmiss/streetlab.py`
- `tests/test_challenge_regressions.py` (15), `tests/test_demo_streetlab.py` (13),
  `tests/test_app_demo_flow.py` (7 AppTest flows)
- `docs/challenge-demo-guide.md`, this file

**Other workers' modules:** `nearmiss/{history,history_ui,evidence_brief,
evidence_ui}.py`, their tests, and `docs/*-integration.md` are integrated
without editing. `nearmiss/investigation.py` and `investigation_ui.py` were
edited in the final acceptance pass (below), after their author finished.

## Product: eight sections

Overview, Analysis, Investigation, Incidents, Explain & Share, Dispatch,
Street Lab, Library. The guided steps cover the five core ones (Overview →
Analysis → Incidents → Dispatch → Street Lab).

## Merge with collaborator commit f2bfe01 ("sleek background")

`git merge --no-ff --no-commit origin/main` produced seven conflict hunks in
`app.py`. Each was resolved by combining both sides:

- **Kept from the collaborator:** the full-photo Overview shell
  (`apply_overview_shell`, `static/nearmiss-hero.jpg`), the "See the moments /
  before impact." hero, its uploader styling and proof line, the translucent
  sidebar and collapsed-control styling, and the hidden Streamlit
  Deploy/menu.
- **Kept from this branch:** the guided demo, the source banners, all eight
  pages, explanations, and "How a warning is earned".
- **Combined landing page.** The hero now holds a primary **Start guided
  demo** button, the uploader, and an "illustrative context only, not analyzed
  footage" credit. The explainer sits below the hero on an opaque dark panel.
  The photo shell is applied only on the Overview landing state, with no
  footage. Once the demo or an upload is active, Overview and every other page
  use the dark interface, so tables never sit on the photograph.
- **Replaced:** the earlier inline SVG illustration and its pulse animation
  were dropped in favor of the collaborator's photograph.
- **Sidebar:** `initial_sidebar_state="auto"` was kept instead of the
  collaborator's `"collapsed"`. Navigation stays discoverable for eight pages
  on desktop, it is collapsed on narrow screens, and it can always be opened.
  The ≥ 901 px expanded-only width rule replaces the collaborator's
  unconditional fixed width, which caused the earlier narrow-screen overlap.
- **Multiselect chips.** Selected multiselect chips were white text on white
  (the light theme primary). New CSS on `[data-baseweb="tag"]` / `span[data-tag]`
  gives a dark chip, light label and removal icon, an amber icon on hover, and
  an amber focus outline. It uses no generated Streamlit class names.

## Final acceptance pass

One consolidated correction pass, each with targeted regressions:

1. **Library stale snapshot** (`app.py`). The Analysis pipeline now stores a
   settings fingerprint (video ID, effective tracking config, conflict config,
   collision config, applied zone) next to `history_current_snapshot`. The
   Library recomputes the fingerprint from the current sidebar and hides the
   Save/Update button, with a "recompute before saving" note, on any mismatch.
   A video change, reset, or failed build also clears or invalidates it.
   Visiting Analysis rebuilds it with the new settings.
2. **Following contact time** (`conflict_detector.py`). The focused following
   policy is unchanged (direction, speed, lateral gate, closing). Contact time
   is now the first root of `|r + v·t| = R` on the full relative motion, so
   lateral offset and lateral drift count. A pair whose circles never touch
   inside the horizon is rejected. The reported repro (follower (10,50) at
   (20,0), leader (28,53.5) at (10,0), R = 4) now gives 1.606 s, not 1.4 s.
3. **Explanation wording** (`nearmiss/explain.py`). Persistence now reads
   "Across the observed episode, the longest consecutive run at HIGH lasted N
   frames…". It no longer says "before the warning". The incident headline is
   "N supporting signals observed across the contact episode", not
   "independent … at first contact".
4. **Investigation time anchor** (`nearmiss/investigation.py`). Predictions
   navigate to `first_alert_timestamp_seconds` (frame `start_frame_index`) and
   fall back to `timestamp_seconds` when the first alert is missing or not
   finite. `event_time_field` records which one was used. The representative
   measurement is kept separately as `measurement_timestamp_seconds` /
   `measurement_frame_index`. Demo conflict-001 now jumps to 0:02.8, which
   matches the Analysis first alert.
5. **Jump keeps its target visible** (`investigation.evidence_focus`,
   `investigation_ui._jump`). **Go** selects the evidence participants that
   have stored observations, including stitched raw IDs. It also widens the
   type/class filters just enough to include them, so the nearby-evidence
   panel shows the record just jumped to. The Incidents → "Step through
   frames" handoff selects the incident participants the same way.
6. **Street Lab sign** (`nearmiss/streetlab.py`, `app.py`). Rows carry
   `difference_text` and `in_roadway_change_text`. Examples: "5.7 s shorter" /
   "33.3% less time", "5.7 s longer" / "50.0% more time", and "no change".
   The UI table, Markdown and PDF all use these. Numeric fields are unchanged.

## Design decisions

- **Demo identity.** The ID is `synthetic-demo-<sha256(scenario)[:12]>`. It is
  stable across cache clears, and it can never collide with real 64-hex
  SHA-256 upload IDs. Reset refuses any ID without that prefix. Artifacts use
  the standard `CACHE_ROOT/<id>/<analysis key>/{tracks,metadata}.json` layout
  under a fixed `DEMO_TRACKING_CONFIG`, so sidebar model settings never
  invalidate the demo, while prediction and incident thresholds still apply
  live.
- **Scenario.** Three scenes, tuned against the real detectors (default
  thresholds): a crossing near miss (HIGH 0:02.8, no contact), a collision
  candidate (HIGH 0:07.1, then a suspected incident at 0:07.7 with 5 signals
  and a 0.60 s prediction lead), and same-direction following (MEDIUM 0:09.8,
  no contact). Background cars and pedestrians are placed so they produce no
  vehicle-mode warnings. The UI shows the staged script next to the computed
  output.
- **Provenance.** It appears in burned-in frame labels (bottom-right pill plus
  a top-right timestamp, placed away from the renderer's text), the source
  banner on every page, `data_source` on track rows, warnings, incidents and
  the dispatch summary, JSON `provenance`, the PDF banner and title, the brief
  banner, and a `synthetic_demo_` filename prefix.
- **Same-lane fix.** The branch is used only when the existing
  "conflict is not in the future" gate would reject two moving vehicles aligned
  within about 20° and within one footprint of lateral offset. The follower
  must be at or above 20 px/s. Contact time is the first moment the
  relative motion brings the footprint circles together (offset and lateral
  drift included), and severity uses time headway. It can be switched
  off with `same_direction_following_enabled`. Crossing-path behavior is
  unchanged; all original detector tests pass.
- **Prediction association.** Requires `0 < lead ≤ 2.0 s`. A warning at or
  after first contact is no longer shown as "predicted earlier", and the UI
  shows the lead in seconds.
- **Dispatch reversal.** Changing a decision to anything other than Confirmed
  sets the notification to `Withdrawn`, with an updated
  `operator_confirmation` and `withdrawn_at`. The row is kept as an audit
  record and cannot be acknowledged. Re-confirming restores `New`. No schema
  change.
- **PDF cache.** The session holds `{key, pdf}`. The key hashes video, source,
  provenance, tracking, conflict and collision configs, zone, events and
  reviews. On mismatch the stale download is hidden and the user is asked to
  regenerate.
- **Street Lab.** The evidence comes only from the active video. Crossing time
  is `start-up + distance / speed` for two user-set walker speeds. The page and
  brief state that it is arithmetic, not a crash reduction, and that any design
  idea is a review hypothesis requiring field measurement. Locations are camera
  frame regions, never addresses. The Markdown and PDF exports render from one
  `build_brief` dict.
- **UI.** Warm amber signal accent on the dark theme; the collaborator's
  photograph is the landing hero (see merge section), and rules rather than
  cards elsewhere. Amber `:focus-visible` outlines on buttons, tabs, inputs,
  sliders, checkboxes, chips and sidebar items. A global
  `prefers-reduced-motion: reduce` override shortens transitions and
  animations. The sidebar width is forced only at ≥ 901px while expanded, and
  `initial_sidebar_state="auto"`, so the narrow-screen overlay no longer covers
  content.

## Tests actually run

- `.venv/bin/python -m pytest -q` → **170 passed** (final run, after the
  merge with `origin/main`). That is 158 before the acceptance pass, plus 11
  acceptance regressions, plus 1 landing-page test. `git diff --check` is
  clean. Per file: app_demo_flow 8, challenge_regressions 15, conflict_detector 11, contract 9,
  demo_streetlab 13, evidence_brief 44, history 32, incident_workflow 7,
  investigation 23, safety_analysis 8.
- My Streamlit AppTest flows (temporary cache and DB via monkeypatch):
  - demo start → Analysis metrics → confirm → acknowledge → dismiss → Withdrawn
    in UI and SQLite → Street Lab input change → reset (a real-footage review
    survives) → return to real footage;
  - pages without footage offer the demo;
  - uploaded-footage path renders with no synthetic label;
  - Investigation, Explain & Share and Library render for the demo, and the
    deep link sets the frame;
  - the PDF download is withheld after a threshold change;
  - the Library hides Save after a sidebar threshold change (0.50 → 0.25) and
    offers it again after Analysis recomputes;
  - Investigation **Go** from an unrelated track/type selection selects the
    evidence participants and shows that record in the evidence table. A
    mutation check showed this test fails without the fix;
  - the merged photo landing has the collaborator headline, the full-photo
    shell, the illustrative credit, a primary **Start guided demo**, the
    uploader and the explainer. After the demo starts, Overview no longer
    applies the photo shell.
- Earlier in the build I inspected generated demo frames (PNG renders, since
  deleted). I did no browser QA. The host session checked the browser at
  desktop 1280 px and mobile 390 px: landing, the guided demo through Street
  Lab, Library save, Investigation jump (frame 56 / 2.8 s, tracks 1 and 2,
  warning visible) and evidence-brief download. The host will recheck the
  merged landing and the chip contrast.

## Known limitations

- During the acceptance pass a scratch copy of `investigation_ui.py` was
  written to `/tmp/iu.bak` by mistake. It was deleted right away and never
  read back.
- I did no browser visual QA. These need the host's browser to accept them:
  the merged photo landing at 1280 and 390 px, the chip contrast, the
  translucent sidebar over the photograph, and the amber primary button on
  the photograph. The CSS relies on Streamlit/BaseWeb DOM attributes
  (`aria-expanded`, `data-baseweb="tag"`, `data-testid`), which can change
  between Streamlit releases.
- The photo shell is applied on the run that shows the landing page. On the
  single run where an upload is accepted, the preview appears under the hero
  until the next interaction switches to the dark layout.
- The same-lane branch can add new warnings on real footage with slowing
  queues. It is regression-tested on synthetic tracks only. The README's
  earlier real-clip result (`01_Accident_001.mp4`) was not re-run because no
  footage or weights are present.
- Adding `conflict_geometry` to events, and `data_source` to incidents, changes
  annotated-video render keys, so previously cached real-footage renders are
  regenerated once.
- Demo MP4 bytes depend on the local OpenCV/ffmpeg build. Identity does not,
  because it comes from the scenario.
- Street Lab default distances and walking speeds are placeholders, labeled as
  such. They are not local design values.
- Explain & Share and my inline explanations overlap in purpose. Mine is a
  compact inline view; theirs is the fuller per-record brief.
- The navigation has 8 entries; the guided steps cover the 5 core ones.
- The Library only offers the current run after Analysis (or another analysis
  page) has recomputed it with the current settings. Changing a setting while
  on the Library asks the user to open Analysis first.
- Jumping to evidence replaces the current track selection with that record's
  participants. Earlier manual selections are not restored.
- Following-branch contact uses circular footprints (box width × 0.20,
  capped). Real vehicles are longer than they are wide, so contact timing is
  still an image-space approximation.
