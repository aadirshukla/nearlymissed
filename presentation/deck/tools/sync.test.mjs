// Video-sync regressions for the real-footage slides, in plain Node (no browser):
//  - frame/time mapping used by requestVideoFrameCallback and seeks
//  - overlay data is the actual model output (tracks.json) and the case's stored boxes
//  - the real scenes.js, run against a fake DOM and a fake <video>, draws the boxes
//    of exactly the presented frame, freezes on the exact still, and stops on leave()
//   node --test tools/sync.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const deck = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = path.resolve(deck, '..', '..');
const read = (f) => fs.readFileSync(path.join(deck, f), 'utf8');
// Loaded the way the browser loads them: plain scripts that set window globals.
const dataBox = {window: {}};
vm.runInNewContext(read('sync.js'), dataBox);
vm.runInNewContext(read('data/real-metrics.js'), dataBox);
const S = dataBox.window.DECK_SYNC;
const R = dataBox.window.NEARMISS_REAL;
const {fps: FPS, frames: N} = R.source.frame;

test('frame mapping: rVFC media times, mid-frame seeks and float noise all land on the right frame', () => {
  for (let f = 0; f < N; f++) {
    assert.equal(S.frameAt(f / FPS, FPS, N), f);
    assert.equal(S.frameAt(f / FPS - 1e-9, FPS, N), f, 'mediaTime a hair early');
    assert.equal(S.frameAt(S.timeFor(f, FPS), FPS, N), f, 'seek target is inside frame f');
    assert.equal(S.frameAt((f + 0.99) / FPS, FPS, N), f, 'late in the frame (fallback currentTime)');
  }
  assert.equal(S.frameAt(99, FPS, N), N - 1);
  assert.equal(S.frameAt(-1, FPS, N), 0);
});

test('cover view maps the chosen source window onto the whole panel', () => {
  const view = [205, 159, 595, 423];
  const {k, left, top} = S.coverView(view, 900, 640);
  assert.ok(left + view[0] * k <= 1e-9 && top + view[1] * k <= 1e-9);
  assert.ok(left + (view[0] + view[2]) * k >= 900 - 1e-9 && top + (view[1] + view[3]) * k >= 640 - 1e-9);
});

test('overlay frames are exactly the cached YOLO11n + ByteTrack rows (no scripted or interpolated boxes)', () => {
  const tracks = JSON.parse(fs.readFileSync(path.join(repo, 'static/real-demo/tracks.json'), 'utf8'));
  const total = R.frames.reduce((a, rows) => a + rows.length, 0);
  assert.equal(total, tracks.length);
  for (const row of tracks) {
    const b = S.boxOf(R, row.frame_index, row.track_id);
    assert.ok(b, `missing ${row.track_id}@${row.frame_index}`);
    row.bbox.forEach((v, i) => assert.ok(Math.abs(b[i + 1] - v) <= 0.05 + 1e-9));
  }
});

test('the case keeps its measurement frame apart from its first alert, with the stored boxes', () => {
  const m = R.case.measurement;
  assert.equal(R.case.event_id, 'conflict-029');
  assert.notEqual(m.frame, R.case.first_alert_frame);
  assert.equal(R.moments.slide1.freeze_frame, R.case.first_alert_frame);
  assert.equal(R.moments.slide3.freeze_frame, m.frame);
  for (const [id, f] of Object.entries(m.observed_frame)) {
    assert.ok(m.frame - f <= 2, 'within max_observation_age');
    assert.deepEqual(S.boxOf(R, f, Number(id)).slice(1), m.boxes[id]);
  }
  assert.ok(m.eta_seconds.every((t) => t < R.pipeline.settings.prediction_horizon_seconds), 'ETAs are measured, not horizon-capped');
  assert.equal(R.case_incident.associated_prediction_event_id, R.case.event_id);
  assert.equal(R.moments.slide5.freeze_frame, R.case_incident.first_contact_frame);
});

/* ---------- the real scenes.js against a fake DOM ---------- */
function fakeDom() {
  const ids = {};
  const sizes = {'s1-scene': [1040, 585], 's3-scene': [900, 640], 's5-scene': [980, 640]};
  const videos = [];
  const make = (tag) => {
    const n = {
      tagName: tag, attrs: {}, style: {}, dataset: {}, children: [], listeners: {}, _html: '', textContent: '',
      classList: {set: new Set(), toggle(c, on) { (on ?? !this.set.has(c)) ? this.set.add(c) : this.set.delete(c); }, contains(c) { return this.set.has(c); }, add(c) { this.set.add(c); }},
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; },
      appendChild(c) { this.children.push(c); return c; }, append(...cs) { cs.forEach((c) => this.children.push(c)); },
      addEventListener(t, f) { this.listeners[t] = f; }, querySelectorAll: () => [],
      get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; this.children = []; },
    };
    if (tag === 'video') {
      Object.assign(n, {currentTime: 0, paused: true, playbackRate: 1, readyState: 4, pending: [],
        play() { this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; },
        requestVideoFrameCallback(cb) { this.pending.push(cb); }});
      videos.push(n);
    }
    return n;
  };
  const byId = (id) => (ids[id] ??= Object.assign(make('div'), {clientWidth: sizes[id]?.[0] ?? 0, clientHeight: sizes[id]?.[1] ?? 0}));
  ids['s4-video'] = make('video');
  const timers = [];
  const window = {
    NEARMISS_REAL: R, DECK_SYNC: S, DECK: {reduced: false}, Math, Number, String, Object, Promise, console,
    setTimeout: (f, ms) => timers.push({f, ms}), requestAnimationFrame() {},
    gsap: {killTweensOf() {}, set() {}, to(t, v) { v.onComplete?.(); }, fromTo(t, a, b) { b.onComplete?.(); }, from() {}},
    document: {getElementById: byId, createElement: make, createElementNS: (_ns, tag) => make(tag), querySelectorAll: () => []},
  };
  window.window = window;
  Object.assign(window, {gsap: window.gsap, document: window.document});
  vm.createContext(window);
  vm.runInContext(read('scenes.js'), window);
  const host = (id) => byId(id);
  const parts = (id) => {
    const frame = host(id).children[0];
    const [video, still, svg] = frame.children;
    return {frame, video, still, svg, focus: svg.children[3]};
  };
  // Present one frame: the browser calls every pending rVFC callback with its media time.
  const present = (video, f) => { const cbs = video.pending.splice(0); cbs.forEach((cb) => cb(0, {mediaTime: f / FPS})); };
  const focusBox = (p, id) => {
    const r = p.focus.children.find((c) => c.tagName === 'rect' && c.attrs['data-track'] === String(id));
    return r ? [Number(r.attrs.x), Number(r.attrs.y), Number(r.attrs.x) + Number(r.attrs.width), Number(r.attrs.y) + Number(r.attrs.height)] : null;
  };
  return {window, scenes: window.DECK_SCENES, host, parts, present, focusBox, byId, timers, videos};
}
const near = (a, b) => a && b && a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
const [IA, IB] = R.case.track_ids;

test('slide 1 draws the boxes of each presented frame, then freezes on the exact first-alert still', async () => {
  const d = fakeDom();
  const s1 = d.scenes.moment;
  const M1 = R.moments.slide1;
  s1.enter();
  let p = d.parts('s1-scene');
  assert.equal(p.still.src, R.assets.stills[String(M1.from_frame)]);
  s1.step(1);
  p = d.parts('s1-scene');
  assert.equal(p.video.paused, false);
  assert.equal(p.video.playbackRate, M1.rate);
  for (let f = M1.from_frame + 1; f < M1.freeze_frame; f++) {
    d.present(p.video, f);
    for (const id of [IA, IB]) {
      const want = S.boxOf(R, f, id);
      const got = d.focusBox(p, id);
      assert.ok(want ? near(got, want.slice(1)) : got === null, `frame ${f} track ${id}: overlay ${got} vs stored ${want}`);
    }
    assert.equal(p.still.style.visibility, 'hidden', 'live video shows through once it advances');
  }
  d.present(p.video, M1.freeze_frame + 1); // the browser may present one frame past the target
  assert.equal(p.video.paused, true);
  assert.equal(p.still.style.visibility, 'visible');
  assert.equal(p.still.src, R.assets.stills[String(M1.freeze_frame)]);
  assert.ok(near(d.focusBox(p, IA), S.boxOf(R, M1.freeze_frame, IA).slice(1)), 'freeze overlay = boxes of the still frame');
  assert.ok(p.frame.classList.contains('frozen'));
  assert.match(d.byId('s1-freeze').innerHTML, new RegExp(`Frame ${M1.freeze_frame} `));
});

test('leaving a slide mid-replay pauses its video and ignores late frame callbacks', () => {
  const d = fakeDom();
  const s1 = d.scenes.moment;
  s1.enter();
  s1.step(1);
  const p = d.parts('s1-scene');
  d.present(p.video, R.moments.slide1.from_frame + 5);
  const before = JSON.stringify(d.focusBox(p, IA));
  p.video.requestVideoFrameCallback.call(p.video, () => {}); // a stale callback still queued
  s1.leave();
  assert.equal(p.video.paused, true);
  d.present(p.video, R.moments.slide1.from_frame + 30);
  assert.equal(JSON.stringify(d.focusBox(p, IA)), before, 'no redraw after leave()');
  d.timers.forEach((t) => t.f()); // the safety-net timer must not resurrect a left slide
  assert.equal(p.video.paused, true);
});

test('re-entering a slide cancels the previous replay (back/forward navigation)', () => {
  const d = fakeDom();
  const s5 = d.scenes.review;
  s5.enter();
  const old = d.parts('s5-scene');
  s5.enter();
  const fresh = d.parts('s5-scene');
  assert.notEqual(old.video, fresh.video);
  assert.equal(old.video.paused, true);
  assert.equal(fresh.video.playbackRate, R.moments.slide5.rate, 'contact replays at half speed');
  d.present(old.video, R.moments.slide5.freeze_frame);
  assert.equal(fresh.still.src, R.assets.stills[String(R.moments.slide5.from_frame)], 'stale callback did not freeze the new replay');
});

test('slide 3 final state is the measurement frame with the event’s stored boxes (including a reused observation)', () => {
  const d = fakeDom();
  d.scenes.earned.final();
  const p = d.parts('s3-scene');
  const m = R.case.measurement;
  assert.equal(p.still.src, R.assets.stills[String(m.frame)]);
  assert.equal(p.video.paused, true);
  for (const id of [IA, IB]) assert.ok(near(d.focusBox(p, id), m.boxes[String(id)]), `track ${id}`);
  assert.match(d.byId('s3-arrivals').innerHTML, new RegExp(`Measured on frame.${m.frame}`));
  assert.match(d.byId('s3-arrivals').innerHTML, /First alert frame.231/);
});

test('reduced motion shows the freeze frames directly, with no playback', () => {
  const d = fakeDom();
  d.window.DECK.reduced = true;
  d.scenes.review.enter();
  const p = d.parts('s5-scene');
  assert.equal(p.video.paused, true);
  assert.equal(p.still.src, R.assets.stills[String(R.moments.slide5.freeze_frame)]);
  d.scenes.moment.enter();
  d.scenes.moment.step(1);
  assert.equal(d.parts('s1-scene').still.src, R.assets.stills[String(R.moments.slide1.freeze_frame)]);
});

test('slide 4 plays the annotated render and pauses it on leave', () => {
  const d = fakeDom();
  const s4 = d.scenes.source;
  const v = d.byId('s4-video');
  s4.enter();
  assert.equal(S.frameAt(v.currentTime, FPS, N), R.case.first_alert_frame, 'parked on the case’s first alert');
  s4.step(1);
  assert.equal(v.paused, false);
  s4.leave();
  assert.equal(v.paused, true);
});

test('print mode: every scene renders its final state, with real numbers and no synthetic wording', () => {
  const d = fakeDom();
  for (const id of ['moment', 'purpose', 'earned', 'source', 'review', 'followup', 'verified', 'pilot']) d.scenes[id].final();
  const gate = d.byId('s6-gate').innerHTML;
  assert.match(gate, new RegExp(`<b>${R.counts.suspected_incidents}</b>candidates`));
  assert.match(gate, /<b>0<\/b>confirmed/);
  assert.match(gate, /<b>0<\/b>notices/);
  assert.match(d.byId('s6-brief').innerHTML, /Mike Bird/);
  assert.doesNotMatch(d.byId('s6-brief').innerHTML, /https?:/, 'links stripped from the on-slide excerpt');
  const verified = d.byId('s7-verified').innerHTML + d.byId('s7-unproven').innerHTML;
  assert.match(verified, /not detector accuracy/);
  assert.match(verified, new RegExp(`${R.counts.track_ids} tracker IDs are not a vehicle count`));
  assert.match(d.byId('s5-read').innerHTML, /not a recorded review/i);
  for (const id of ['s1-freeze', 's3-arrivals', 's4-note', 's5-read', 's6-gate', 's6-brief', 's7-verified']) {
    assert.doesNotMatch(d.byId(id).innerHTML, /synthetic|scripted/i, id);
  }
});
