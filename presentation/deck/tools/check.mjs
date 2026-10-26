// Static checks for the browser deck (no browser needed):
//  - 8 slides, durations 15/20/30/25/25/25/25/15 = 180 s, speakers 1-4 / 5-8
//  - every local asset referenced by HTML/CSS/JS exists (no missing images)
//  - no network URLs are loaded at playback (no CDN)
//  - notes exist for every slide and their cue windows tile 0:00-3:00
//  - the PDF backup exists with exactly 8 pages
//  - real footage: deck clip copies match the app's hash-bound real-demo files,
//    every play/freeze frame has its exact still, no synthetic-demo labels remain
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const deck = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (f) => fs.readFileSync(path.join(deck, f), 'utf8');
let failed = 0;
const check = (ok, msg) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${msg}`);
  if (!ok) failed++;
};

const html = read('index.html');
const css = read('deck.css');
const slides = [...html.matchAll(/<section class="slide" data-id="([^"]+)" data-seconds="(\d+)" data-speaker="([^"]+)" data-steps="(\d+)"/g)].map((m) => ({id: m[1], seconds: Number(m[2]), speaker: m[3], steps: Number(m[4])}));
check(slides.length === 8, `8 slides (found ${slides.length})`);
const durations = slides.map((s) => s.seconds).join('/');
check(durations === '15/20/30/25/25/25/25/15', `durations ${durations}`);
check(slides.reduce((a, s) => a + s.seconds, 0) === 180, 'total 180 s');
check(slides.slice(0, 4).every((s) => s.speaker === 'Srivibhav') && slides.slice(4).every((s) => s.speaker === 'Aadi'), 'Srivibhav slides 1-4, Aadi slides 5-8');
for (const s of slides) {
  const block = html.split(`data-id="${s.id}"`)[1].split('</section>')[0];
  const maxStep = Math.max(0, ...[...block.matchAll(/data-step="(\d+)"/g)].map((m) => Number(m[1])));
  check(maxStep === s.steps, `slide ${s.id}: ${s.steps} declared steps, highest data-step ${maxStep}`);
}

const refs = new Set();
for (const m of html.matchAll(/(?:src|href)="([^"#?]+)"/g)) refs.add(m[1]);
for (const m of css.matchAll(/url\(([^)]+)\)/g)) refs.add(m[1].replace(/['"]/g, ''));
for (const m of html.matchAll(/--img:url\(([^)]+)\)/g)) refs.add(m[1]);
const local = [...refs].filter((r) => !/^(https?:|data:)/.test(r));
const missing = local.filter((r) => !fs.existsSync(path.join(deck, r)));
check(missing.length === 0, `all ${local.length} referenced local files exist${missing.length ? `; missing: ${missing.join(', ')}` : ''}`);
const network = [html, css, read('deck.js'), read('scenes.js'), read('notes.js'), read('sync.js')].join('\n').match(/https?:\/\/[^\s"')]+/g) || [];
const loaded = network.filter((u) => !u.startsWith('http://www.w3.org/2000/svg'));
check(loaded.length === 0, `no network URLs loaded at playback${loaded.length ? `: ${loaded.join(', ')}` : ''}`);
check(fs.existsSync(path.join(deck, 'vendor/gsap.min.js')), 'GSAP bundled locally');

const sandbox = {window: {}};
vm.createContext(sandbox);
vm.runInContext(read('data/real-metrics.js'), sandbox);
vm.runInContext(read('notes.js'), sandbox);
const R = sandbox.window.NEARMISS_REAL;
const notes = sandbox.window.NEARMISS_NOTES(R);
check(notes.length === 8, `notes for 8 slides (found ${notes.length})`);
const toSec = (s) => s.split(':').reduce((a, v) => a * 60 + Number(v), 0);
let cursor = 0;
let start = 0;
let tiled = true;
notes.forEach((n, i) => {
  for (const [win] of n.cues) {
    const [a, b] = win.split('–').map(toSec);
    if (a !== cursor) tiled = false;
    cursor = b;
  }
  start += slides[i]?.seconds ?? 0;
  if (cursor !== start) tiled = false;
});
check(tiled && cursor === 180, 'note cue windows tile 0:00–3:00 and match slide boundaries');
const words = notes.flatMap((n) => n.cues.map((c) => c[1])).join(' ').split(/\s+/).length;
console.log(`     spoken words: ${words} (~${(words / 180).toFixed(2)} words/s)`);

const repo = path.resolve(deck, '..', '..');
const sha = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const manifest = JSON.parse(fs.readFileSync(path.join(repo, 'static/real-demo/manifest.json'), 'utf8'));
check(sha(path.join(deck, R.assets.source)) === manifest.source_sha256 && R.source.source_sha256 === manifest.source_sha256,
  `deck source clip SHA-256 matches static/real-demo manifest (${manifest.source_sha256.slice(0, 12)}…)`);
check(sha(path.join(deck, R.assets.annotated)) === sha(path.join(repo, 'static/real-demo/annotated.mp4')) && sha(path.join(deck, R.assets.annotated)) === R.source.annotated_sha256,
  'deck annotated clip matches the app render static/real-demo/annotated.mp4');
check(sha(path.join(repo, 'static/real-demo/tracks.json')) === R.source.tracks_sha256 && R.source.tracks_sha256 === manifest.tracks_sha256,
  'overlay data was derived from the manifest-bound tracks.json');
const c = R.counts;
check(c.warnings === manifest.counts.warnings && c.suspected_incidents === manifest.counts.suspected_incidents && c.track_ids === manifest.counts.track_ids,
  `counts match manifest: ${c.warnings} warnings, ${c.suspected_incidents} contact candidates, ${c.track_ids} tracker IDs`);
const frozen = Object.values(R.moments).flatMap((m) => [m.from_frame, m.freeze_frame].filter((f) => f !== undefined));
const noStill = frozen.filter((f) => !R.assets.stills[String(f)] || !fs.existsSync(path.join(deck, R.assets.stills[String(f)])));
check(noStill.length === 0, `exact-frame stills for play/freeze frames ${[...new Set(frozen)].join(', ')}${noStill.length ? `; missing ${noStill}` : ''}`);
check(R.case.measurement.frame !== R.case.first_alert_frame, `case keeps measurement frame ${R.case.measurement.frame} apart from first alert ${R.case.first_alert_frame}`);
const shown = [html, read('scenes.js'), read('notes.js')].join('\n');
const stale = shown.match(/synthetic demo|scripted tracks|demo-metrics|assets\/captures\/|assets\/clips\//gi) || [];
check(stale.length === 0, `no synthetic-demo labels or assets in the deck${stale.length ? `: ${[...new Set(stale)].join(', ')}` : ''}`);
check(['moment', 'purpose', 'earned', 'review'].every((id) => html.split(`data-id="${id}"`)[1].split('</section>')[0].includes('Real footage')), 'slides 1, 2, 3 and 5 carry the Real footage label');
check(html.includes('Mike Bird') && /no incident labels/.test(html), 'footage credit and the no-labels boundary are on screen');

const pdf = path.resolve(deck, '..', 'exports', 'NearMiss-deck.pdf');
if (fs.existsSync(pdf)) {
  const pages = (fs.readFileSync(pdf, 'latin1').match(/\/Type\s*\/Page[^s]/g) || []).length;
  check(pages === 8, `PDF backup has ${pages} pages`);
} else check(false, 'PDF backup missing (npm run pdf)');
process.exit(failed ? 1 : 0);
