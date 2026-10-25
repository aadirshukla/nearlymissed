# NearMiss Congressional App Challenge build brief

## Outcome

Make the existing NearMiss prototype easier to understand and demonstrate: a judge should be able to enter a clearly labeled synthetic example without providing footage or downloading a model, inspect explainable conflict evidence, review an incident, and connect observed patterns to a practical street-safety discussion.

Production detector accuracy, deployment, emergency integration, and real-world safety reductions are outside this build. Synthetic examples must remain labeled in the interface and exports. Preserve original-video analysis.

## Implementation bundle

1. A one-click synthetic intersection demonstration, using generated footage and deterministic track observations. Reuse the existing prediction, independent incident detector, rendering, review and simulated dispatch workflow; bypass only YOLO inference for this explicitly synthetic input. Offer a return to real footage. A visible source banner must distinguish the demonstration everywhere.
2. A Street Lab page: explain which candidate interaction patterns warrant human review, let the operator explore crossing-distance assumptions and draft a local improvement checklist, and export a concise community review brief. Calculated crossing time is an illustration under user-supplied assumptions, not measured crash reduction or an engineering recommendation.
3. A clearer product introduction and explanation of the detection pipeline, thresholds and evidence boundaries. Add a compact demo walkthrough and challenge presentation guide.
4. Repair the small correctness issues that would undermine a demonstration: later warnings called earlier, stale saved report downloads, confirmation reversal remaining confirmed in dispatch, and contact markers drawn from a different frame. Add a targeted same-lane motion fix only with meaningful regression coverage.

## Acceptance

- Existing original upload/analysis workflow remains available.
- All synthetic inputs and outputs identify their provenance.
- Demo starts without network, user footage or model weights and produces an inspectable candidate incident through the existing detector.
- Confirm, dismiss and acknowledgment states remain coherent across the UI and SQLite records.
- Street Lab responds to inputs, states assumptions and exports matching content.
- Existing tests and targeted new regressions pass.
- Browser checks cover desktop and a narrow viewport; screenshots and direct interaction establish that the new UI is usable.
- Commits and pushes to GitHub main are explicitly authorized by the user. No public deployment, external messages or competition submission.

## Model route

User requested Opus 5.5 using Codex on Crack. After the user signed in, the official Claude Code subscription route ran exact `claude-opus-5-5` implementation workers for the integrated workflow, Library, Investigation, and Explain & Share. Codex performed integration acceptance, browser checks and Git publication. No model or provider fallback was used.

## Judging reference

The official 2026 rules describe idea quality, implementation/UX, and programming skill as judging criteria, and permit judges to request access to verify stated functionality. Build a demonstrable interface and accurately label unfinished or simulated capabilities.

Source: https://www.congressionalappchallenge.us/wp-content/uploads/2026/05/2026-CAC-Rules.pdf
