import {Config} from '@remotion/cli/config';

// Reasonable local resource limits; scripts/render.mjs passes the same values.
Config.setConcurrency(4);
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setCodec('h264');
Config.setCrf(18);
Config.setPixelFormat('yuv420p');

// Optional: render with an already-installed Chrome instead of Remotion's
// downloaded Chrome Headless Shell, e.g.
//   REMOTION_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
// Unset (the default), Remotion uses its own bundled browser as usual.
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE;
if (browserExecutable) Config.setBrowserExecutable(browserExecutable);
