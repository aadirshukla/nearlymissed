// Behaviour tests for deck.js in plain Node (no browser): the real deck.js runs
// in a vm against a minimal fake DOM, with a controllable clock and frame loop.
//   node --test tools/engine.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const deck = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(deck, 'index.html'), 'utf8');
const source = fs.readFileSync(path.join(deck, 'deck.js'), 'utf8');
const plan = [...html.matchAll(/<section class="slide" data-id="([^"]+)" data-seconds="(\d+)" data-speaker="([^"]+)" data-steps="(\d+)"/g)]
  .map((m) => ({id: m[1], seconds: m[2], speaker: m[3], steps: m[4]}));
const startOf = (i) => plan.slice(0, i).reduce((a, p) => a + Number(p.seconds), 0);
// Same spacing as rehearsal.schedule in deck.js.
const scheduledAt = (i, k) => startOf(i) + (k * Number(plan[i].seconds)) / (Number(plan[i].steps) + 1);

const classList = () => {
  const set = new Set();
  return {toggle: (c, on) => ((on ?? !set.has(c)) ? set.add(c) : set.delete(c)), add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c)};
};
const node = (extra = {}) => ({textContent: '', innerHTML: '', hidden: false, style: {}, classList: classList(), listeners: {}, addEventListener(t, f) { this.listeners[t] = f; }, ...extra});

function boot() {
  let now = 1000;
  let frame = null;
  const ids = {};
  const byId = (id) => (ids[id] ??= node(id === 'rehearsal-bar' ? {firstElementChild: {style: {}}} : {}));
  const docListeners = {};
  const slides = plan.map((p) => node({dataset: p, querySelector: () => ({textContent: p.id}), querySelectorAll: () => []}));
  const scene = {enter() {}, step() {}, final() {}};
  const sandbox = {
    URLSearchParams, Number, String, Math, console,
    location: {search: '', hash: ''},
    history: {replaceState() {}},
    performance: {now: () => now},
    requestAnimationFrame: (f) => { frame = f; },
    gsap: {killTweensOf() {}, set() {}, fromTo() {}},
    innerWidth: 1920, innerHeight: 1080,
    matchMedia: () => ({matches: false, addEventListener() {}}),
    addEventListener() {},
    DECK_SCENES: Object.fromEntries(plan.map((p) => [p.id, scene])),
    NEARMISS_NOTES: () => plan.map(() => ({cues: []})),
    document: {
      body: node(),
      images: [],
      querySelectorAll: () => slides,
      getElementById: byId,
      addEventListener: (t, f) => { docListeners[t] = f; },
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  const D = sandbox.DECK;
  return {
    D,
    advance(seconds) { now += seconds * 1000; frame?.(); },
    click: () => byId('stage').listeners.click({target: {closest: () => null}}),
    key: (key) => docListeners.keydown({key, preventDefault() {}}),
    mode: () => byId('hud-mode').textContent,
  };
}

test('the elapsed timer waits for the first navigation after load', () => {
  const deckState = boot();
  deckState.advance(5);
  assert.equal(deckState.D.elapsed(), 0);
});

test('a first pointer reveal starts the elapsed timer', () => {
  const deckState = boot();
  deckState.advance(3);
  deckState.click();
  assert.equal(deckState.D.step, 1, 'click revealed step 1 on slide 1');
  deckState.advance(2);
  assert.ok(Math.abs(deckState.D.elapsed() - 2) < 1e-9, `elapsed ${deckState.D.elapsed()} s, want 2 s from the click`);
});

test('a first keyboard reveal starts the elapsed timer', () => {
  const deckState = boot();
  deckState.advance(3);
  deckState.key('ArrowRight');
  deckState.advance(1.5);
  assert.ok(Math.abs(deckState.D.elapsed() - 1.5) < 1e-9);
});

test('rehearsal restores the exact scheduled slide and step after a long frame gap', () => {
  const deckState = boot();
  deckState.key('r');
  assert.match(deckState.mode(), /REHEARSAL/);
  // A background tab: no frames until slide 5 (review), step 2 is due.
  deckState.advance(scheduledAt(4, 2) + 0.05);
  assert.deepEqual([deckState.D.index, deckState.D.step], [4, 2]);
  // Then a gap that crosses into slide 7 (verified), step 1.
  deckState.advance(scheduledAt(6, 1) - scheduledAt(4, 2));
  assert.deepEqual([deckState.D.index, deckState.D.step], [6, 1]);
});

test('rehearsal puts the presenter back on schedule after a stray key', () => {
  const deckState = boot();
  deckState.key('r');
  deckState.advance(scheduledAt(2, 1) + 0.05);
  assert.deepEqual([deckState.D.index, deckState.D.step], [2, 1]);
  deckState.key('5');
  deckState.advance(scheduledAt(2, 2) - scheduledAt(2, 1));
  assert.deepEqual([deckState.D.index, deckState.D.step], [2, 2]);
});

test('a frame-by-frame rehearsal visits every reveal, reaches 8/8 and clears REHEARSAL at 180 s', () => {
  const deckState = boot();
  deckState.key('r');
  const seen = new Set();
  for (let t = 0; t <= 181; t += 1 / 30) {
    deckState.advance(1 / 30);
    seen.add(`${deckState.D.index}:${deckState.D.step}`);
  }
  const expected = plan.flatMap((p, i) => Array.from({length: Number(p.steps) + 1}, (_, k) => `${i}:${k}`));
  assert.deepEqual([...seen].sort(), expected.sort());
  assert.deepEqual([deckState.D.index, deckState.D.step], [7, 2]);
  assert.doesNotMatch(deckState.mode(), /REHEARSAL/);
});
