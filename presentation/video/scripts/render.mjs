// Full render: one Remotion pass with music, then an ffmpeg stream-copy remux
// for the silent version (no second render), then the poster still.
//   node scripts/render.mjs [--allow-missing] [--concurrency=4]
// Set REMOTION_BROWSER_EXECUTABLE to use an installed Chrome (see remotion.config.ts).
// --allow-missing writes a DRAFT to video/out/ only; exports/ never receives a
// render with a missing host capture placeholder.
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const video = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const exportsDir = path.resolve(video, '..', 'exports');
const args = process.argv.slice(2);
const allowMissing = args.includes('--allow-missing');
const concurrency = args.find((a) => a.startsWith('--concurrency='))?.split('=')[1] ?? '4';

const captures = JSON.parse(fs.readFileSync(path.join(video, 'src/data/captures.json'), 'utf8'));
const media = JSON.parse(fs.readFileSync(path.join(video, 'src/data/media.json'), 'utf8'));
if (captures.missing.length && !allowMissing) {
  console.error(`Missing host captures: ${captures.missing.join(', ')}. Add them or pass --allow-missing for a draft.`);
  process.exit(1);
}

const run = (cmd, cmdArgs) => execFileSync(cmd, cmdArgs, {cwd: video, stdio: 'inherit'});
const draft = captures.missing.length > 0;
const outDir = draft ? path.join(video, 'out') : exportsDir;
fs.mkdirSync(outDir, {recursive: true});
if (draft) console.warn(`DRAFT render (missing ${captures.missing.join(', ')}): writing to ${path.relative(video, outDir)}/ only.`);
const withMusic = Boolean(media.music);
const main = path.join(outDir, withMusic ? 'NearMiss-demo.mp4' : 'NearMiss-demo-silent.mp4');
const silent = path.join(outDir, 'NearMiss-demo-silent.mp4');

run('npx', [
  'remotion', 'render', 'src/index.ts', 'NearMissDemo', main,
  `--concurrency=${concurrency}`, '--codec=h264', '--crf=18', '--pixel-format=yuv420p',
  '--audio-codec=aac', '--audio-bitrate=192k', `--props=${JSON.stringify({music: withMusic, musicVolume: 0.5})}`,
  ...(withMusic ? [] : ['--muted']),
]);
if (withMusic) {
  run('ffmpeg', ['-y', '-loglevel', 'error', '-i', main, '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', silent]);
} else {
  console.warn('No music supplied: only the silent version was rendered. NearMiss-demo.mp4 was NOT produced.');
}
run('npx', ['remotion', 'still', 'src/index.ts', 'NearMissPoster', path.join(outDir, 'NearMiss-demo-poster.png'), '--log=error']);
if (!draft) run('node', ['scripts/check.mjs']);
