import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

// Local OFL fonts copied from @fontsource by scripts/prepare-assets.mjs.
// loadFont() holds rendering (delayRender) until each face is ready.
const faces: Array<[string, string, string, 'normal' | 'italic']> = [
  ['Inter', 'inter-400.woff2', '400', 'normal'],
  ['Inter', 'inter-500.woff2', '500', 'normal'],
  ['Inter', 'inter-600.woff2', '600', 'normal'],
  ['Inter', 'inter-700.woff2', '700', 'normal'],
  ['Instrument Serif', 'instrument-serif-400.woff2', '400', 'normal'],
  ['Instrument Serif', 'instrument-serif-400-italic.woff2', '400', 'italic'],
  ['JetBrains Mono', 'jetbrains-mono-400.woff2', '400', 'normal'],
  ['JetBrains Mono', 'jetbrains-mono-500.woff2', '500', 'normal'],
];

let started = false;
export const ensureFonts = () => {
  if (started) return;
  started = true;
  for (const [family, file, weight, style] of faces) {
    loadFont({family, url: staticFile(`fonts/${file}`), weight, style, format: 'woff2'});
  }
};
