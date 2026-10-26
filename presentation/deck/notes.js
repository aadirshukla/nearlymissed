// Timed presenter notes. Srivibhav speaks slides 1-4 (0:00-1:30), Aadi slides 5-8 (1:30-3:00).
// Numbers are read from data/real-metrics.js (real footage, actual model output) so the
// script never drifts from the data. About 2.4 spoken words per second; each cue lists its window.
window.NEARMISS_NOTES = function (r) {
  const c = r.case;
  const m = c.measurement; // the frame the ETAs and gap were measured on (not the first alert)
  const inc = r.case_incident;
  const n = r.counts;
  const rows = r.streetlab.crossing.rows;
  const a = r.streetlab.crossing.assumptions;
  const high = r.pipeline.settings.high_time_gap_seconds;
  const [ia, ib] = c.track_ids;
  const s1 = (v) => v.toFixed(1);
  const passed = r.tests && r.tests.exit_code === 0 && r.tests.summary.match(/^(\d+) passed/);
  const tests = passed ? `all ${passed[1]} automated tests pass` : r.tests ? `pytest reported ${r.tests.summary.replace(/ in [\d.]+s.*$/, '')}` : 'the test suite was not recorded';
  return [
    {
      cues: [
        ['0:00–0:05', 'A near miss is over in seconds, and usually nothing is written down.'],
        ['0:05–0:15', `This is real highway traffic with NearMiss’s actual tracking on top. At ${s1(c.first_alert_seconds)} seconds it flags cars ${ia} and ${ib}. Was that a near miss? A person has to check.`],
      ],
    },
    {
      cues: [
        ['0:15–0:24', 'NearMiss turns fixed-camera traffic footage into reviewable evidence in four stages: predict, detect, verify, notify.'],
        ['0:24–0:30', 'We are Srivibhav Padakandla and Aadi Shukla. It is for people who review intersections, including neighbors preparing a street-safety conversation.'],
        ['0:30–0:35', 'The footage is real but unlabelled, so every flag is an unverified candidate.'],
      ],
    },
    {
      cues: [
        ['0:35–0:45', `NearMiss projects each tracked car forward. On frame ${m.frame}, at ${s1(m.seconds)} seconds, cars ${ia} and ${ib} head for the same image point. The flag first fired earlier, at ${s1(c.first_alert_seconds)}.`],
        ['0:45–0:55', `Projected arrivals: ${m.eta_seconds[0].toFixed(2)} and ${m.eta_seconds[1].toFixed(2)} seconds. A ${c.arrival_gap_seconds.toFixed(2)}-second gap, under the ${high.toFixed(2)}-second HIGH line, so it is ${c.severity}.`],
        ['0:55–1:05', 'But look at the frame: one lane, one car behind the other. In image pixels, perspective makes them meet. That is why it is a candidate, not a fact.'],
      ],
    },
    {
      cues: [
        ['1:05–1:15', `This is the app’s own annotated render. ${n.warnings} warnings and ${n.suspected_incidents} suspected contacts in fifteen seconds of ordinary traffic. Many must be false alarms.`],
        ['1:15–1:25', 'Any flag jumps to its source frame. Investigation redraws the stored boxes, here cars 20 and 22 on frame 34. Nothing is re-detected.'],
        ['1:25–1:30', 'Aadi will show what a person does with that.'],
      ],
    },
    {
      cues: [
        ['1:30–1:40', `A separate detector looks for contact. At ${s1(inc.first_contact_seconds)} seconds, the same two cars show ${inc.evidence_signal_count} signals, from box contact to slowing.`],
        ['1:40–1:47', `The warning came ${inc.prediction_lead_seconds.toFixed(2)} seconds before. To our eyes, it is queued traffic overlapping in perspective.`],
        ['1:47–1:55', `So it stays a candidate. A person confirms, dismisses or leaves it uncertain. All ${n.suspected_incidents} here are uncertain.`],
      ],
    },
    {
      cues: [
        ['1:55–2:03', 'Only a confirmation creates a notice, one local simulation; nothing is sent. Nothing was confirmed here, so there is no notice.'],
        ['2:03–2:12', `Street Lab plans follow-up. Assume ${a.current_distance} and ${a.proposed_distance} ${a.unit}: crossing time goes from ${rows[0].current_seconds} to ${rows[0].proposed_seconds} seconds. Arithmetic, not a safety measurement.`],
        ['2:12–2:20', 'And it exports a community brief carrying the footage credit, the counts and their boundaries.'],
      ],
    },
    {
      cues: [
        ['2:20–2:28', 'YOLO and ByteTrack are existing open source. Our code is the prediction, the contact detector, the evidence links, the review record and the tools around them.'],
        ['2:28–2:36', `Verified: ${tests}. They check our code, not detector accuracy. This replay reproduces the app’s counts exactly.`],
        ['2:36–2:45', `Not yet proven: accuracy on real footage. This clip has no labels, and ${n.track_ids} tracker IDs are not a vehicle count.`],
      ],
    },
    {
      cues: [
        ['2:45–2:53', 'So the next step is a supervised pilot: permissioned footage from one camera, compared with human-labelled events.'],
        ['2:53–3:00', 'We built this with AI coding assistance and open source, credited here. A near miss disappears in seconds. Its evidence shouldn’t. Thank you.'],
      ],
    },
  ];
};
