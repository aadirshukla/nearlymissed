// Renders representative frames for visual QA into ../exports/stills/.
//   node scripts/render-stills.mjs [frame ...]
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const video = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.resolve(video, '..', 'exports', 'stills');
fs.mkdirSync(out, {recursive: true});
// One or two frames per scene, chosen at moments where everything is on screen.
const DEFAULT = [60, 300, 470, 640, 780, 1000, 1500, 1630, 1900, 2100, 2390, 2700, 3080, 3420, 3800, 4180, 4560, 4740, 4900];
const frames = process.argv.slice(2).map(Number).filter(Number.isFinite);
for (const frame of frames.length ? frames : DEFAULT) {
  const file = path.join(out, `frame-${String(frame).padStart(4, '0')}.jpg`);
  execFileSync('npx', ['remotion', 'still', 'src/index.ts', 'NearMissDemo', file, `--frame=${frame}`, '--image-format=jpeg', '--jpeg-quality=88', '--log=error'], {cwd: video, stdio: 'inherit'});
  console.log(`still ${path.relative(video, file)}`);
}
