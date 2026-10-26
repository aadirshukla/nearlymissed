// Gathers every local asset the video and deck need and writes manifests the
// compositions read. Never edits host captures; only reads them.
//
//   node scripts/prepare-assets.mjs
//
// Outputs:
//   public/hero/nearmiss-hero.jpg      copy of static/nearmiss-hero.jpg
//   public/fonts/*.woff2               OFL fonts from @fontsource (local, no CDN)
//   public/fonts/OFL-*.txt             the full SIL OFL 1.1 text shipped with each family
//   src/data/captures.json             which host captures exist (+ pixel sizes, brief text)
//   src/data/media.json                music availability, duration, licence notes
//   ../deck/assets/{hero,captures}/   the same images for the browser deck
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const video = path.resolve(here, '..');
const presentation = path.resolve(video, '..');
const repo = path.resolve(presentation, '..');
const deck = path.join(presentation, 'deck');

export const EXPECTED_CAPTURES = [
  'overview.png',
  'analysis.png',
  'warning.png',
  'investigation.png',
  'incidents.png',
  'dispatch.png',
  'streetlab.png',
  'evidence.png',
  'brief.md',
];
// evidence.png is an extra host capture the video does not show. Everything
// else is drawn on screen (warning.png in S3App's WhyBeat), so it is required:
// a production render refuses to start without it (scripts/render.mjs).
const OPTIONAL = new Set(['evidence.png']);

const FONTS = [
  ['@fontsource/inter/files/inter-latin-400-normal.woff2', 'inter-400.woff2'],
  ['@fontsource/inter/files/inter-latin-500-normal.woff2', 'inter-500.woff2'],
  ['@fontsource/inter/files/inter-latin-600-normal.woff2', 'inter-600.woff2'],
  ['@fontsource/inter/files/inter-latin-700-normal.woff2', 'inter-700.woff2'],
  ['@fontsource/instrument-serif/files/instrument-serif-latin-400-normal.woff2', 'instrument-serif-400.woff2'],
  ['@fontsource/instrument-serif/files/instrument-serif-latin-400-italic.woff2', 'instrument-serif-400-italic.woff2'],
  ['@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2', 'jetbrains-mono-400.woff2'],
  ['@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2', 'jetbrains-mono-500.woff2'],
];

const copy = (from, to) => {
  fs.mkdirSync(path.dirname(to), {recursive: true});
  fs.copyFileSync(from, to);
};

function pngSize(file) {
  const buffer = fs.readFileSync(file);
  if (buffer.toString('ascii', 1, 4) !== 'PNG') return null;
  return {width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20)};
}

function jpegSize(file) {
  const buffer = fs.readFileSync(file);
  let offset = 2;
  while (offset < buffer.length) {
    if (buffer[offset] !== 0xff) return null;
    const marker = buffer[offset + 1];
    const length = buffer.readUInt16BE(offset + 2);
    if (marker >= 0xc0 && marker <= 0xc3) {
      return {height: buffer.readUInt16BE(offset + 5), width: buffer.readUInt16BE(offset + 7)};
    }
    offset += 2 + length;
  }
  return null;
}

function probeDuration(file) {
  try {
    const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration:format_tags=title,artist', '-of', 'json', file], {encoding: 'utf8'});
    const parsed = JSON.parse(out);
    return {duration: Number(parsed.format?.duration) || null, tags: parsed.format?.tags ?? {}};
  } catch {
    return {duration: null, tags: {}};
  }
}

// --- hero + fonts --------------------------------------------------------
const hero = path.join(repo, 'static', 'nearmiss-hero.jpg');
if (!fs.existsSync(hero)) throw new Error(`Missing ${hero}`);
for (const target of [path.join(video, 'public', 'hero'), path.join(deck, 'assets', 'hero')]) {
  copy(hero, path.join(target, 'nearmiss-hero.jpg'));
}
for (const [from, name] of FONTS) {
  const source = path.join(video, 'node_modules', from);
  copy(source, path.join(video, 'public', 'fonts', name));
}
// OFL 1.1 requires the copyright notice and licence to travel with the fonts.
for (const [pkg, name] of [['inter', 'Inter'], ['instrument-serif', 'InstrumentSerif'], ['jetbrains-mono', 'JetBrainsMono']]) {
  const licence = path.join(video, 'node_modules', '@fontsource', pkg, 'LICENSE');
  if (!fs.readFileSync(licence, 'utf8').includes('SIL OPEN FONT LICENSE Version 1.1')) throw new Error(`${licence} is not the OFL 1.1 text`);
  copy(licence, path.join(video, 'public', 'fonts', `OFL-${name}.txt`));
}

// --- metrics ---------------------------------------------------------------
const metrics = path.join(presentation, 'data', 'demo-metrics.json');
if (!fs.existsSync(metrics)) {
  throw new Error('Run `.venv/bin/python presentation/scripts/extract_metrics.py --clips --tests` from the repo root first.');
}
copy(metrics, path.join(video, 'src', 'data', 'demo-metrics.json'));

// --- host captures (read only) --------------------------------------------
const capturesDir = path.join(video, 'public', 'captures');
const files = {};
const missing = [];
for (const name of EXPECTED_CAPTURES) {
  const file = path.join(capturesDir, name);
  if (!fs.existsSync(file) || fs.statSync(file).size === 0) {
    if (!OPTIONAL.has(name)) missing.push(name);
    continue;
  }
  if (name.endsWith('.md')) {
    const text = fs.readFileSync(file, 'utf8');
    files[name] = {kind: 'markdown', bytes: Buffer.byteLength(text), text};
  } else {
    files[name] = {kind: 'image', ...(pngSize(file) ?? jpegSize(file) ?? {width: 1600, height: 1000})};
  }
  copy(file, path.join(deck, 'assets', 'captures', name));
}
// Any extra host files are listed but not used automatically.
const extras = fs.existsSync(capturesDir)
  ? fs.readdirSync(capturesDir).filter((n) => !EXPECTED_CAPTURES.includes(n) && !n.startsWith('.'))
  : [];
fs.writeFileSync(
  path.join(video, 'src', 'data', 'captures.json'),
  JSON.stringify({files, missing, extras}, null, 2) + '\n',
);

// --- music -----------------------------------------------------------------
const musicDir = path.join(video, 'public', 'music');
const musicFile = path.join(musicDir, 'traffic-bed.mp3');
const licenceFiles = fs.existsSync(musicDir)
  ? fs.readdirSync(musicDir).filter((n) => /\.(txt|md|json)$/i.test(n))
  : [];
const media = {music: null, licenceFiles, licenceText: licenceFiles.map((n) => fs.readFileSync(path.join(musicDir, n), 'utf8').trim()).join('\n\n')};
if (fs.existsSync(musicFile) && fs.statSync(musicFile).size > 0) {
  const {duration, tags} = probeDuration(musicFile);
  media.music = {file: 'music/traffic-bed.mp3', duration, title: tags.title ?? null, artist: tags.artist ?? null};
}
fs.writeFileSync(path.join(video, 'src', 'data', 'media.json'), JSON.stringify(media, null, 2) + '\n');

console.log(`captures present: ${Object.keys(files).join(', ') || 'none'}`);
console.log(`captures missing: ${missing.join(', ') || 'none'}`);
if (extras.length) console.log(`extra host files (unused): ${extras.join(', ')}`);
console.log(`music: ${media.music ? `${media.music.file} (${media.music.duration?.toFixed(1)} s, "${media.music.title}" by ${media.music.artist})` : 'not supplied; video renders silent'}`);
console.log(`music licence files: ${licenceFiles.join(', ') || 'none found'}`);
