# NearMiss — three-minute speaker notes

Srivibhav: slides 1–4 (0:00–1:30). Aadi: slides 5–8 (1:30–3:00). Speaking assignments do not assert individual feature authorship. Derived from the browser deck notes and current demo metrics; edit `deck/notes.js` for the live deck.

## 1. The moment worth reviewing — Srivibhav

**0:00–0:07** A near miss is over in a couple of seconds. Nobody is hurt, so usually nothing is written down.

**0:07–0:15** Here, in our labeled synthetic demo, car #2 brakes and stops short. NearMiss exists so that a moment like this leaves evidence a person can check.

## 2. What NearMiss does — Srivibhav

**0:15–0:25** NearMiss turns fixed-camera traffic footage into reviewable evidence in four stages: predict, detect, verify, notify.

**0:25–0:31** We are Srivibhav Padakandla and Aadi Shukla. It is meant for people who review intersections, including neighbors preparing a street-safety conversation.

**0:31–0:35** Everything you see from the app today is the synthetic demo, labeled that way on every page.

## 3. How a warning is earned — Srivibhav

**0:35–0:45** NearMiss projects each tracked vehicle forward. Measured at 00:02.7, cars #1 and #2 head for the same point; the warning first fires at 00:02.8.

**0:45–0:55** It estimates when each one arrives: 0.75 and 0.99 seconds. The gap is 0.24 seconds, under the 0.50-second HIGH threshold, so it is flagged HIGH.

**0:55–1:05** The app shows those exact measurements in plain language. They are image pixels, not real speeds or probabilities, and every threshold is adjustable.

## 4. Inspect the source — Srivibhav

**1:05–1:15** This is the app’s own annotated render. 3 warnings appear as the clip plays, plus one suspected contact.

**1:15–1:25** From any warning you can jump to the source: frame 56, with the stored boxes for both tracks. Nothing is re-detected.

**1:25–1:30** Aadi will take it from here, to what a person does with that evidence.

## 5. Human judgment — Aadi

**1:30–1:40** A separate detector looks for contact. At 00:07.7, vehicles #3 and #4 show 5 supporting signals: contact, overlap, convergence and a motion response.

**1:40–1:47** The prediction conflict-002 came 0.60 seconds earlier, but it does not decide this.

**1:47–1:55** It is still only a candidate. A person confirms, dismisses or leaves it uncertain.

## 6. Evidence into follow-up — Aadi

**1:55–2:03** Confirming creates exactly one local, simulated notice. Nothing goes to emergency services or anyone else.

**2:03–2:12** Street Lab turns flags into a follow-up plan. With placeholder distances of 60 and 40 ft, crossing time goes from 19.1 to 13.4 seconds. That is arithmetic, not a crash reduction.

**2:12–2:20** And each record exports as a Markdown brief carrying the synthetic label, the review and what it does not claim.

## 7. What we built and verified — Aadi

**2:20–2:28** YOLO and ByteTrack are existing open source. Our code is the prediction, the contact detector, the evidence links, the review record and the tools around them.

**2:28–2:36** Verified: 237 passed locally, and the demo is deterministic.

**2:36–2:45** Not yet proven: accuracy on real footage, calibrated distances, and any safety benefit.

## 8. The next useful pilot — Aadi

**2:45–2:53** So the next step is a supervised pilot: permissioned footage from one camera, compared with human-labelled events.

**2:53–3:00** We built this with AI coding assistance and open source, credited here. A near miss disappears in seconds. Its evidence shouldn’t. Thank you.
