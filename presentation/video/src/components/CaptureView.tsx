import React from 'react';
import {Img, staticFile, useCurrentFrame} from 'remotion';
import {easeInOut, lerp, ramp} from '../anim';
import {captures} from '../data';
import {C, F} from '../theme';

// A host screenshot with a deterministic camera (pan/zoom between normalized
// rectangles) and highlight boxes. Rects are [x, y, w, h] as fractions of the
// image, so they survive a re-capture at a different pixel size.
export type Rect = [number, number, number, number];
export type Cam = {at: number; rect: Rect};
export type Highlight = {from: number; to?: number; rect: Rect; color?: string; label?: string; labelSide?: 'top' | 'bottom'};

type Props = {
  name: string;
  width: number;
  height: number;
  cams: Cam[];
  highlights?: Highlight[];
  caption?: string;
  style?: React.CSSProperties;
};

const FULL: Rect = [0, 0, 1, 1];

const rectAt = (cams: Cam[], frame: number): Rect => {
  if (!cams.length) return FULL;
  if (frame <= cams[0].at) return cams[0].rect;
  for (let i = 0; i < cams.length - 1; i++) {
    const a = cams[i];
    const b = cams[i + 1];
    if (frame <= b.at) {
      const k = ramp(frame, a.at, b.at, 0, 1, easeInOut);
      return [0, 1, 2, 3].map((j) => lerp(a.rect[j], b.rect[j], k)) as Rect;
    }
  }
  return cams[cams.length - 1].rect;
};

export const CaptureView: React.FC<Props> = ({name, width, height, cams, highlights = [], caption, style}) => {
  const frame = useCurrentFrame();
  const info = captures.files[name];
  if (!info || info.kind !== 'image') {
    return (
      <div style={{width, height, border: `2px dashed ${C.coral}`, borderRadius: 14, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.coral, fontFamily: F.mono, fontSize: 30, background: C.card, ...style}}>
        Host capture pending: {name}
      </div>
    );
  }
  const base = Math.min(width / info.width, height / info.height);
  const dispW = info.width * base;
  const dispH = info.height * base;
  const r = rectAt(cams, frame);
  const z = Math.min(width / (r[2] * dispW), height / (r[3] * dispH));
  const cx = (r[0] + r[2] / 2) * dispW;
  const cy = (r[1] + r[3] / 2) * dispH;
  const tx = width / 2 - cx * z;
  const ty = height / 2 - cy * z;
  const toScreen = (nx: number, ny: number) => [tx + nx * dispW * z, ty + ny * dispH * z];

  return (
    <div style={{position: 'relative', width, height, overflow: 'hidden', borderRadius: 14, background: C.ink, boxShadow: '0 30px 80px rgba(0,0,0,0.55)', outline: `1px solid ${C.line}`, ...style}}>
      <div style={{position: 'absolute', left: 0, top: 0, width: dispW, height: dispH, transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${z})`}}>
        <Img src={staticFile(`captures/${name}`)} style={{width: dispW, height: dispH, display: 'block'}} />
      </div>
      {highlights.map((h, i) => {
        const o = Math.min(ramp(frame, h.from, h.from + 10), h.to === undefined ? 1 : 1 - ramp(frame, h.to - 8, h.to));
        if (o <= 0) return null;
        const [x1, y1] = toScreen(h.rect[0], h.rect[1]);
        const [x2, y2] = toScreen(h.rect[0] + h.rect[2], h.rect[1] + h.rect[3]);
        const color = h.color ?? C.amber;
        const grow = (1 - ramp(frame, h.from, h.from + 14)) * 14;
        return (
          <React.Fragment key={i}>
            <div style={{position: 'absolute', left: x1 - 8 - grow, top: y1 - 8 - grow, width: x2 - x1 + 16 + grow * 2, height: y2 - y1 + 16 + grow * 2, border: `4px solid ${color}`, borderRadius: 10, opacity: o, boxShadow: `0 0 0 9999px rgba(11,11,12,${0.38 * o})`}} />
            {h.label && (
              <div style={{position: 'absolute', left: x1 - 8, top: h.labelSide === 'bottom' ? y2 + 18 : y1 - 64, opacity: o, fontFamily: F.sans, fontWeight: 600, fontSize: 26, color: C.ink, background: color, padding: '8px 16px', borderRadius: 6, whiteSpace: 'nowrap'}}>
                {h.label}
              </div>
            )}
          </React.Fragment>
        );
      })}
      {caption && (
        <div style={{position: 'absolute', left: 18, bottom: 16, fontFamily: F.mono, fontSize: 18, letterSpacing: 1, color: C.white, background: 'rgba(11,11,12,0.8)', padding: '6px 12px', borderRadius: 4}}>{caption}</div>
      )}
    </div>
  );
};
