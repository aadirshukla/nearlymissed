/* Frame-exact helpers shared by the real-footage scenes (scenes.js) and the
 * Node regression tests (tools/sync.test.mjs). Pure functions, no DOM.
 * Frame f of the 24 fps clip is presented from f/fps to (f+1)/fps (PTS start 0). */
(function (root) {
  // Frame shown at media time t. The small slack absorbs float error in
  // requestVideoFrameCallback mediaTime (exactly f/fps, give or take 1e-9).
  const frameAt = (t, fps, frames) => Math.max(0, Math.min(frames - 1, Math.floor(t * fps + 1e-3)));
  // Seek target for frame f: its middle, so decoders cannot land on a neighbour.
  const timeFor = (f, fps) => (f + 0.5) / fps;
  // object-fit: cover of the source-pixel window view = [x0, y0, w, h] into a w x h host.
  const coverView = (view, hostW, hostH) => {
    const [x0, y0, vw, vh] = view;
    const k = Math.max(hostW / vw, hostH / vh);
    return {k, left: (hostW - vw * k) / 2 - x0 * k, top: (hostH - vh * k) / 2 - y0 * k};
  };
  // Smallest window of the frame holding every point plus padding, at the host aspect.
  const fitView = (pts, pad, aspect, W, H) => {
    let x0 = Math.min(...pts.map((p) => p[0])) - pad, x1 = Math.max(...pts.map((p) => p[0])) + pad;
    let y0 = Math.min(...pts.map((p) => p[1])) - pad, y1 = Math.max(...pts.map((p) => p[1])) + pad;
    if ((x1 - x0) / (y1 - y0) < aspect) { const g = ((y1 - y0) * aspect - (x1 - x0)) / 2; x0 -= g; x1 += g; }
    else { const g = ((x1 - x0) / aspect - (y1 - y0)) / 2; y0 -= g; y1 += g; }
    const w = x1 - x0, h = y1 - y0;
    if (w <= W) x0 = Math.max(0, Math.min(x0, W - w));
    if (h <= H) y0 = Math.max(0, Math.min(y0, H - h));
    return [x0, y0, w, h];
  };
  // Tracked rows of frame f as [id, x1, y1, x2, y2]; a track missing that frame is absent (not interpolated).
  const boxesAt = (R, f) => R.frames[f] || [];
  const boxOf = (R, f, id) => boxesAt(R, f).find((b) => b[0] === id) || null;
  // Bottom-centre anchors (the detector's reference point) of one track over frames [from, to].
  const trail = (R, id, from, to) => {
    const pts = [];
    for (let f = Math.max(0, from); f <= to; f++) {
      const b = boxOf(R, f, id);
      if (b) pts.push([(b[1] + b[3]) / 2, b[4]]);
    }
    return pts;
  };
  const api = {frameAt, timeFor, coverView, fitView, boxesAt, boxOf, trail};
  root.DECK_SYNC = api;
})(typeof window !== 'undefined' ? window : globalThis);
