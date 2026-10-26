// Timed presenter notes. Srivibhav speaks slides 1-4 (0:00-1:30), Aadi slides 5-8 (1:30-3:00).
// Numbers are read from data/demo-metrics.js so the script never drifts from the demo output.
// About 2.4 spoken words per second; each cue lists its target window.
window.NEARMISS_NOTES = function (m) {
  const ev = m.events;
  const e1 = ev[0];
  const m1 = e1.measurement; // the frame the ETAs and gap were measured on (not the first alert)
  const inc = m.incidents[0];
  const linked = inc ? ev.find((e) => e.event_id === inc.associated_prediction_event_id) : null;
  const rows = m.streetlab.crossing.rows;
  const a = m.streetlab.crossing.assumptions;
  const high = m.settings.high_time_gap_seconds;
  const fps = m.source.frame.fps;
  const tests = m.tests ? m.tests.summary.replace(/ in [\d.]+s$/, '') : 'the full test suite';
  return [
    {
      cues: [
        ['0:00–0:07', 'A near miss is over in a couple of seconds. Nobody is hurt, so usually nothing is written down.'],
        ['0:07–0:15', `Here, in our labeled synthetic demo, car #${e1.track_ids[1]} brakes and stops short. NearMiss exists so that a moment like this leaves evidence a person can check.`],
      ],
    },
    {
      cues: [
        ['0:15–0:25', 'NearMiss turns fixed-camera traffic footage into reviewable evidence in four stages: predict, detect, verify, notify.'],
        ['0:25–0:31', 'We are Srivibhav Padakandla and Aadi Shukla. It is meant for people who review intersections, including neighbors preparing a street-safety conversation.'],
        ['0:31–0:35', 'Everything you see from the app today is the synthetic demo, labeled that way on every page.'],
      ],
    },
    {
      cues: [
        ['0:35–0:45', `NearMiss projects each tracked vehicle forward. Measured at ${m1.clock}, cars #${e1.track_ids.join(' and #')} head for the same point; the warning first fires at ${e1.first_alert_clock}.`],
        ['0:45–0:55', `It estimates when each one arrives: ${m1.eta_seconds[0].toFixed(2)} and ${m1.eta_seconds[1].toFixed(2)} seconds. The gap is ${e1.arrival_gap_seconds.toFixed(2)} seconds, under the ${high.toFixed(2)}-second HIGH threshold, so it is flagged ${e1.severity}.`],
        ['0:55–1:05', 'The app shows those exact measurements in plain language. They are image pixels, not real speeds or probabilities, and every threshold is adjustable.'],
      ],
    },
    {
      cues: [
        ['1:05–1:15', `This is the app’s own annotated render. ${ev.length} warnings appear as the clip plays${inc ? ', plus one suspected contact' : ''}.`],
        ['1:15–1:25', `From any warning you can jump to the source: frame ${Math.round(e1.first_alert_seconds * fps)}, with the stored boxes for both tracks. Nothing is re-detected.`],
        ['1:25–1:30', 'Aadi will take it from here, to what a person does with that evidence.'],
      ],
    },
    {
      cues: inc
        ? [
            ['1:30–1:40', `A separate detector looks for contact. At ${inc.first_contact_clock}, vehicles #${inc.track_ids.join(' and #')} show ${inc.evidence_signal_count} supporting signals: contact, overlap, convergence and a motion response.`],
            ['1:40–1:47', linked ? `The prediction ${linked.event_id} came ${inc.prediction_lead_seconds.toFixed(2)} seconds earlier, but it does not decide this.` : 'No prediction was linked to this contact.'],
            ['1:47–1:55', 'It is still only a candidate. A person confirms, dismisses or leaves it uncertain.'],
          ]
        : [['1:30–1:55', 'No suspected incident was found in this run; explain that a zero is not proof of safety.']],
    },
    {
      cues: [
        ['1:55–2:03', 'Confirming creates exactly one local, simulated notice. Nothing goes to emergency services or anyone else.'],
        ['2:03–2:12', `Street Lab turns flags into a follow-up plan. With placeholder distances of ${a.current_distance} and ${a.proposed_distance} ${a.unit}, crossing time goes from ${rows[0].current_seconds} to ${rows[0].proposed_seconds} seconds. That is arithmetic, not a crash reduction.`],
        ['2:12–2:20', 'And each record exports as a Markdown brief carrying the synthetic label, the review and what it does not claim.'],
      ],
    },
    {
      cues: [
        ['2:20–2:28', 'YOLO and ByteTrack are existing open source. Our code is the prediction, the contact detector, the evidence links, the review record and the tools around them.'],
        ['2:28–2:36', `Verified: ${tests} locally, and the demo is deterministic.`],
        ['2:36–2:45', 'Not yet proven: accuracy on real footage, calibrated distances, and any safety benefit.'],
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
