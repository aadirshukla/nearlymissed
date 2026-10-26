// Verifies exported files against the brief: 1920x1080, 30 fps, 4950 frames
// (165 s), audio only in the soundtrack version, poster present.
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const video = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const exportsDir = path.resolve(video, '..', 'exports');
const timeline = JSON.parse(fs.readFileSync(path.join(video, 'src/timeline.json'), 'utf8'));
let failed = false;
const report = (ok, msg) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${msg}`);
  if (!ok) failed = true;
};

const probe = (file) =>
  JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames:format=duration', '-of', 'json', file], {encoding: 'utf8'}));

for (const [name, wantAudio] of [['NearMiss-demo.mp4', true], ['NearMiss-demo-silent.mp4', false]]) {
  const file = path.join(exportsDir, name);
  if (!fs.existsSync(file)) {
    report(false, `${name} missing`);
    continue;
  }
  const info = probe(file);
  const v = info.streams.find((s) => s.codec_type === 'video');
  const a = info.streams.find((s) => s.codec_type === 'audio');
  report(v.width === timeline.width && v.height === timeline.height, `${name} ${v.width}x${v.height}`);
  report(v.r_frame_rate === `${timeline.fps}/1`, `${name} ${v.r_frame_rate} fps`);
  report(Number(v.nb_read_frames) === timeline.durationInFrames, `${name} ${v.nb_read_frames} frames (want ${timeline.durationInFrames})`);
  report(Boolean(a) === wantAudio, `${name} audio ${a ? `${a.codec_name}` : 'none'}`);
  console.log(`     duration ${Number(info.format.duration).toFixed(3)} s, ${(fs.statSync(file).size / 1e6).toFixed(1)} MB`);
}
const poster = path.join(exportsDir, 'NearMiss-demo-poster.png');
report(fs.existsSync(poster), 'poster NearMiss-demo-poster.png');
process.exit(failed ? 1 : 0);
