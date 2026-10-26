// Renders from a copy of this folder outside ~/Documents, where Remotion's
// esbuild bundler hangs on this machine when its working directory is under
// ~/Documents (the same esbuild binary works from any other directory).
//
//   node scripts/render-isolated.mjs [--cache=DIR] [render.mjs flags...]
//
// 1. prepare-assets runs here, in the original folder.
// 2. video/ (node_modules included, symlinks kept as-is) is copied to
//    DIR/video; DIR defaults to ~/.cache/nearmiss-render-YYYYMMDD.
// 3. `node scripts/render.mjs` runs in DIR/video and writes DIR/exports;
//    REMOTION_BROWSER_EXECUTABLE is passed through if set.
// 4. Only after render.mjs (which ends with scripts/check.mjs) succeeds are
//    the exports copied back to presentation/exports/. Drafts stay in DIR.
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const video = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const exportsDir = path.resolve(video, '..', 'exports');
const args = process.argv.slice(2);
const stamp = new Date().toLocaleDateString('en-CA', {timeZone: 'America/Los_Angeles'}).replaceAll('-', '');
const cache = path.resolve(args.find((a) => a.startsWith('--cache='))?.slice(8) ?? path.join(os.homedir(), '.cache', `nearmiss-render-${stamp}`));
const renderArgs = args.filter((a) => !a.startsWith('--cache='));
if (cache.startsWith(path.join(os.homedir(), 'Documents') + path.sep)) throw new Error(`--cache must be outside ~/Documents (got ${cache})`);

execFileSync('node', ['scripts/prepare-assets.mjs'], {cwd: video, stdio: 'inherit'});

const isolated = path.join(cache, 'video');
console.log(`copying ${video} -> ${isolated}`);
fs.cpSync(video, isolated, {recursive: true, force: true, verbatimSymlinks: true, filter: (src) => !/[/\\](out|\.remotion)$/.test(src) || src.includes('node_modules')});

const env = {...process.env};
if (env.REMOTION_BROWSER_EXECUTABLE) console.log(`browser: ${env.REMOTION_BROWSER_EXECUTABLE}`);
execFileSync('node', ['scripts/render.mjs', ...renderArgs], {cwd: isolated, stdio: 'inherit', env});

const captures = JSON.parse(fs.readFileSync(path.join(isolated, 'src/data/captures.json'), 'utf8'));
if (captures.missing.length) {
  console.warn(`Draft render (missing ${captures.missing.join(', ')}); left in ${path.join(isolated, 'out')}, nothing copied.`);
  process.exit(0);
}
const rendered = path.join(cache, 'exports');
fs.mkdirSync(exportsDir, {recursive: true});
for (const name of ['NearMiss-demo.mp4', 'NearMiss-demo-silent.mp4', 'NearMiss-demo-poster.png']) {
  const file = path.join(rendered, name);
  if (!fs.existsSync(file)) continue;
  fs.copyFileSync(file, path.join(exportsDir, name));
  console.log(`copied ${name} -> ${path.relative(path.resolve(video, '..', '..'), path.join(exportsDir, name))}`);
}
