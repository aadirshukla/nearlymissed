// Copies every runtime dependency into the deck so playback needs no network:
//   vendor/gsap.min.js, assets/fonts/*.ttf (+ OFL-*.txt), assets/hero/.
// The real clip, exact-frame stills, host app captures, community brief and
// data/real-metrics.js come from
//   .venv/bin/python presentation/scripts/extract_real_metrics.py
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const deck = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = path.resolve(deck, '..', '..');
const nm = path.join(deck, 'node_modules');
const copy = (from, to) => {
  fs.mkdirSync(path.dirname(to), {recursive: true});
  fs.copyFileSync(from, to);
};

copy(path.join(nm, 'gsap/dist/gsap.min.js'), path.join(deck, 'vendor/gsap.min.js'));
copy(path.join(nm, 'gsap/package.json'), path.join(deck, 'vendor/gsap.package.json'));

const fonts = {
  'Inter-Regular.ttf': '@expo-google-fonts/inter/400Regular/Inter_400Regular.ttf',
  'Inter-SemiBold.ttf': '@expo-google-fonts/inter/600SemiBold/Inter_600SemiBold.ttf',
  'Inter-Bold.ttf': '@expo-google-fonts/inter/700Bold/Inter_700Bold.ttf',
  'InstrumentSerif-Regular.ttf': '@expo-google-fonts/instrument-serif/400Regular/InstrumentSerif_400Regular.ttf',
  'InstrumentSerif-Italic.ttf': '@expo-google-fonts/instrument-serif/400Regular_Italic/InstrumentSerif_400Regular_Italic.ttf',
  'JetBrainsMono-Regular.ttf': '@expo-google-fonts/jetbrains-mono/400Regular/JetBrainsMono_400Regular.ttf',
  'JetBrainsMono-Medium.ttf': '@expo-google-fonts/jetbrains-mono/500Medium/JetBrainsMono_500Medium.ttf',
};
for (const [name, from] of Object.entries(fonts)) copy(path.join(nm, from), path.join(deck, 'assets/fonts', name));
// OFL 1.1 requires the copyright notice and licence to travel with the fonts
// (LICENSE_FONT is the font licence; the package LICENSE is Expo's MIT wrapper).
for (const [pkg, name] of [['inter', 'Inter'], ['instrument-serif', 'InstrumentSerif'], ['jetbrains-mono', 'JetBrainsMono']]) {
  const licence = path.join(nm, '@expo-google-fonts', pkg, 'LICENSE_FONT');
  if (!fs.readFileSync(licence, 'utf8').includes('SIL OPEN FONT LICENSE Version 1.1')) throw new Error(`${licence} is not the OFL 1.1 text`);
  copy(licence, path.join(deck, 'assets/fonts', `OFL-${name}.txt`));
}

copy(path.join(repo, 'static/nearmiss-hero.jpg'), path.join(deck, 'assets/hero/nearmiss-hero.jpg'));
console.log(`vendored gsap, ${Object.keys(fonts).length} fonts, hero`);
