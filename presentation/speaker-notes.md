# NearMiss — three-minute speaker notes

Srivibhav: slides 1–4 (0:00–1:30). Aadi: slides 5–8 (1:30–3:00). Speaking assignments do not assert individual feature authorship. Derived from the browser deck notes (`deck/notes.js`) and `data/real-metrics.json`; edit `deck/notes.js` for the live deck.

Footage: real ordinary highway traffic, Mike Bird, “Traffic Flow In The Highway” (Pexels video 2103099, Pexels License). Boxes and flags are actual NearMiss output (YOLO11n + ByteTrack, precomputed; no new inference). The clip has no incident labels: every warning and suspected contact is an unverified, experimental candidate. Do not describe any of them as a near miss or collision. Nothing on these slides was confirmed or dispatched.

Case followed on slides 1, 3 and 5: **conflict-029** (HIGH, car #38 / car #86): first alert frame 231 (00:09.6), measured on frame 243 (00:10.1); linked suspected contact **incident-31370bdbe7ff** first box contact frame 242 (00:10.1).

## 1. The moment worth reviewing — Srivibhav

**0:00–0:05** A near miss is over in seconds, and usually nothing is written down.

**0:05–0:15** This is real highway traffic with NearMiss’s actual tracking on top. At 9.6 seconds it flags cars 38 and 86. Was that a near miss? A person has to check.

## 2. What NearMiss does — Srivibhav

**0:15–0:24** NearMiss turns fixed-camera traffic footage into reviewable evidence in four stages: predict, detect, verify, notify.

**0:24–0:30** We are Srivibhav Padakandla and Aadi Shukla. It is for people who review intersections, including neighbors preparing a street-safety conversation.

**0:30–0:35** The footage is real but unlabelled, so every flag is an unverified candidate.

## 3. How a warning is earned — Srivibhav

**0:35–0:45** NearMiss projects each tracked car forward. On frame 243, at 10.1 seconds, cars 38 and 86 head for the same image point. The flag first fired earlier, at 9.6.

**0:45–0:55** Projected arrivals: 1.15 and 1.20 seconds. A 0.05-second gap, under the 0.50-second HIGH line, so it is HIGH.

**0:55–1:05** But look at the frame: one lane, one car behind the other. In image pixels, perspective makes them meet. That is why it is a candidate, not a fact.

## 4. Inspect the source — Srivibhav

**1:05–1:15** This is the app’s own annotated render. 41 warnings and 5 suspected contacts in fifteen seconds of ordinary traffic. Many must be false alarms.

**1:15–1:25** Any flag jumps to its source frame. Investigation redraws the stored boxes, here cars 20 and 22 on frame 34. Nothing is re-detected.

**1:25–1:30** Aadi will show what a person does with that.

## 5. Human judgment — Aadi

**1:30–1:40** A separate detector looks for contact. At 10.1 seconds, the same two cars show 5 signals, from box contact to slowing.

**1:40–1:47** The warning came 0.46 seconds before. To our eyes, it is queued traffic overlapping in perspective.

**1:47–1:55** So it stays a candidate. A person confirms, dismisses or leaves it uncertain. All 5 here are uncertain.

## 6. Evidence into follow-up — Aadi

**1:55–2:03** Only a confirmation creates a notice, one local simulation; nothing is sent. Nothing was confirmed here, so there is no notice.

**2:03–2:12** Street Lab plans follow-up. Assume 60 and 40 ft: crossing time goes from 19.1 to 13.4 seconds. Arithmetic, not a safety measurement.

**2:12–2:20** And it exports a community brief carrying the footage credit, the counts and their boundaries.

## 7. What we built and verified — Aadi

**2:20–2:28** YOLO and ByteTrack are existing open source. Our code is the prediction, the contact detector, the evidence links, the review record and the tools around them.

**2:28–2:36** Verified: all 271 automated tests pass. They check our code, not detector accuracy. This replay reproduces the app’s counts exactly.

**2:36–2:45** Not yet proven: accuracy on real footage. This clip has no labels, and 78 tracker IDs are not a vehicle count.

## 8. The next useful pilot — Aadi

**2:45–2:53** So the next step is a supervised pilot: permissioned footage from one camera, compared with human-labelled events.

**2:53–3:00** We built this with AI coding assistance and open source, credited here. A near miss disappears in seconds. Its evidence shouldn’t. Thank you.
