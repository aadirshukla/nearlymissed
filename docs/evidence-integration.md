# Explain & Share: integration guide

Owner files: `nearmiss/evidence_brief.py` (pure functions), `nearmiss/evidence_ui.py` (Streamlit page), `tests/test_evidence_brief.py`. The feature does not touch `app.py`; the core worker wires it in as described below.

## What it does

The user picks one prediction warning or suspected incident. The page then shows:

- a plain-language explanation
- the evidence facts the detector actually supplied
- a processing-quality checklist
- a **Download evidence brief** button, which saves a Markdown file

The feature does not detect, score or estimate anything. If a field is missing or malformed, the page and the brief call it missing rather than filling it in.

This is separate from the PDF safety report, which summarises the whole clip, and from Street Lab, which is a planner.

Guarantees, all covered by tests:

- **Claims need evidence.** Each statement depends on usable supplied evidence. The event type or a label alone never counts. Every explanation includes `evidence_status`, which is `"established"`, `"partial"` or `"insufficient"`. It also appears as an "Evidence completeness" fact, and the page shows a warning whenever the status is not `established`.
  - **Prediction warnings:** the "projected paths reach a shared point" headline needs both a timing measure (the arrival gap, or the time headway when vehicles follow in the same lane) and a projected-path measure (projected separation or time to the conflict point).
  - **Suspected incidents:** "boxes touching" needs contact evidence: contact persistence above 0, box overlap or IoU above 0, or a `persistent_bounding_box_contact` signal. An incident is `established` only when box contact, prior convergence and a motion response are all supplied, which mirrors what the detector itself requires.
  - **Partial or empty records:** these say that the available evidence cannot establish the result, and list only the values that were supplied.
  - **Linked prediction:** "No earlier prediction warning" is said only when `associated_prediction_event_id` is present and empty. If the field is absent, the link is reported as unknown.
- **Confirmed only with a saved review.** An incident counts as confirmed only when a saved review row with the same `incident_id` (and a matching `video_id`, if present) has `review_status == "Confirmed Incident"`. The incident's own `review_status` field is never treated as proof. If the two disagree, a visible note says so.
- **Dispatch is described as local and simulated.** It always reports `external_alert_sent: False`. When no notification exists, the text says no external alert was sent.
- **Synthetic sources are labeled.** A source is synthetic if any of these contains "synthetic": `source_kind`, the video ID, any track row's `data_source`, or any record's `data_source`. A synthetic marker overrides a non-synthetic label. A synthetic brief gets a `[SYNTHETIC]` title, a banner, a footer label and a `SYNTHETIC_` filename prefix.
- **Pixels stay pixels.** No accuracy figure, safety rating, crash probability or danger score is produced. The detector's own `severity` and `risk_score` appear only with a caveat that they are heuristic review-priority values.
- **Supplied text is escaped.** Source names, class names and IDs are escaped before they go into the Markdown, so they cannot inject markup or HTML.

## Integration (app.py, core worker)

1. Import:

   ```python
   from nearmiss.evidence_ui import render_evidence_page
   ```

2. Add a sidebar page. In the `st.radio("Workspace", ...)` list (currently `["Overview", "Analysis", "Incidents", "Dispatch"]`), add `"Explain & Share"` after `"Incidents"`.

3. Add a branch after the `elif navigation == "Incidents":` block and before `elif navigation == "Dispatch":`. By that point `tracks`, `metadata`, `events`, `incidents`, `persisted_reviews` and `dispatch_notifications` already exist (see app.py around lines 637–680). If the demo worker has changed how a synthetic source is identified, use whatever flag it provides for `source_kind`. Any value containing "synthetic" works.

   ```python
   elif navigation == "Explain & Share":
       page_header(
           "Explain & Share",
           "Why was this flagged?",
           "Plain-language evidence for one flagged moment, with a downloadable brief.",
       )
       render_evidence_page(
           source_name=source_filename,
           video_id=video_hash,
           source_kind="synthetic_demo" if active_video.get("synthetic") else "uploaded_video",
           metadata=metadata,                      # VideoMetadata, dict, or None
           tracks=tracks,                          # raw track rows (list[dict])
           events=events,                          # normalized + deduplicated prediction events
           incidents=incidents,                    # detect_suspected_collisions output
           reviews=persisted_reviews,              # dict keyed by incident_id, or list_reviews(...) list
           notifications=dispatch_notifications,   # list_notifications(video_hash)
       )
   ```

   - The page renders its own synthetic banner, section headings (`nm-section-title`, `nm-section-copy`) and empty state (`nm-empty`). It does not call `page_header`.
   - Widget keys are namespaced by `video_id`, so they will not collide with other pages.
   - Optional: on the Incidents page, add `st.button("Explain & share", on_click=queue_page, args=("Explain & Share",))` next to the review controls.

## Public API (`nearmiss.evidence_brief`)

| Function | Signature | Returns |
|---|---|---|
| `describe_source` | `(source_kind, video_id=None, tracks=None, records=None) -> dict` | `source_kind, label, is_synthetic, statement, note` |
| `evidence_options` | `(events, incidents) -> list[dict]` | Items `{key, kind, id, timestamp_seconds, label, record}`, sorted by time; malformed records skipped |
| `explain_prediction` | `(event) -> dict` | `kind, id, title, participants, timestamp_seconds, evidence_status, explanation: list[str], facts: list[{label,value,note}], motion_rows, missing_fields` |
| `explain_incident` | `(incident, reviews=None, notifications=None) -> dict` | Same keys, plus `review` and `dispatch` |
| `explain_evidence` | `(kind, record, reviews=None, notifications=None) -> dict` | Calls one of the two functions above |
| `review_state` | `(incident, reviews) -> dict` | `status` (`"Not reviewed"` / `"Confirmed Incident"` / `"False Alarm"` / `"Uncertain"`), `confirmed`, `reviewed_at`, `camera_id`, `statement`, `inconsistency` |
| `dispatch_state` | `(incident, notifications, review=None) -> dict` | `status` (`"None"` / `"New"` / `"Acknowledged"` / `"Withdrawn"`), `notification_id`, `generated_at`, `acknowledged_at`, `external_alert_sent=False`, `statement`, `inconsistency` |
| `processing_quality` | `(*, kind, record, metadata, tracks, source) -> list[dict]` | Rows `{check, status: "ok"/"caution"/"info", detail}` |
| `missing_fields` | `(kind, record) -> list[str]` | Readable names of absent or unusable expected fields |
| `build_evidence_brief` | `(*, source_name, video_id, source_kind, metadata, tracks, kind, record, reviews=None, notifications=None, generated_at=None) -> str` | Markdown brief |
| `brief_filename` | `(kind, record, is_synthetic) -> str` | Safe `.md` filename |

`kind` is `"prediction"` or `"incident"` (the constants `PREDICTION` and `INCIDENT`).

## Fields used

**Prediction warnings:**

- `participant_{a,b}_track_id`, `_track_ids`, `_class` / `_type`
- `first_alert_timestamp_seconds` (falls back to `timestamp_seconds`), `end_timestamp_seconds`
- `arrival_time_gap_seconds`, `time_to_conflict_seconds`, `path_separation_pixels`
- `persistence_frames`, `closing_speed_pixels_per_second`
- `conflict_geometry`, `time_headway_seconds`, `severity`, `risk_score`, `zone_is_user_defined`

**Suspected incidents:**

- `incident_id`, `source_video_id`
- `vehicle_{a,b}_track_id`, `_class`
- `first_suspected_impact_timestamp_seconds`, `contact_persistence_frames`, `detection_signals`
- `associated_prediction_event_id`, `prediction_warning_timestamp_seconds`, `prediction_lead_seconds`
- `measurements.{peak_overlap_fraction_smaller_box, peak_intersection_over_union, converging, distance_reduction_pixels, closing_speed_pixels_per_second, samples, motion_response.{flags, vehicles[]}}`

## Quality checklist thresholds

These thresholds only trigger a disclosure in the checklist. They are not accuracy limits.

- **Short clip:** under 20 s
- **Low frame rate:** under 10 fps
- **Sparse track:** fewer than 10 rows, or a frame gap larger than 5
- **Field calibration:** always reported as absent, because the pipeline has none
- **Detector confidence:** reported as the model's own score, never as accuracy. For synthetic tracks it says the value is scripted.

## Tests

```
.venv/bin/python -m pytest tests/test_evidence_brief.py -q
```

There are 44 tests, all passing. They cover:

- explanation claims gated on evidence, across empty, malformed, partial and normal valid detector records
- malformed and missing fields
- synthetic provenance, including relabeled sources
- unreviewed vs. confirmed vs. withdrawn reviews, using the real SQLite store
- dispatch inconsistencies and the absence of any external alert
- explained metrics matching real `detect_suspected_collisions` output
- brief headings and content, escaping, and filename safety
- the Streamlit page, via `AppTest`: empty state, incident view, prediction view and the incomplete-record warning
