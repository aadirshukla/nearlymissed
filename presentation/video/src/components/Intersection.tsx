import React from 'react';
import {actorAt, actorTrail, metrics, Point} from '../data';
import {F} from '../theme';

// Functional diagram of the synthetic demo intersection. Geometry mirrors
// nearmiss/demo.py (_scene_background) in the demo's own 960x540 pixel space,
// and road users are placed from the scripted samples in demo-metrics.json.

export type Projection = {from: Point; to: Point; color: string; label?: string; progress?: number};
export type Ring = {at: Point; r: number; color: string; opacity?: number};

type Props = {
  t: number;
  width: number;
  height: number;
  view?: [number, number, number, number];
  highlight?: Record<number, string>;
  trailsFrom?: number;
  projections?: Projection[];
  rings?: Ring[];
  dim?: number;
  showIds?: boolean;
  style?: React.CSSProperties;
};

const STRIPE = '#CDCDC8';
const LANE = '#D79628';

const Background: React.FC = () => {
  const [h0, h1] = metrics.source.road.horizontal_y;
  const [v0, v1] = metrics.source.road.vertical_x;
  const W = metrics.source.frame.width;
  const H = metrics.source.frame.height;
  const cy = (h0 + h1) / 2;
  const cx = (v0 + v1) / 2;
  const stripesY: number[] = [];
  for (let y = h0 + 6; y < h1 - 4; y += 16) stripesY.push(y);
  const stripesX: number[] = [];
  for (let x = v0 + 6; x < v1 - 4; x += 16) stripesX.push(x);
  return (
    <g>
      <rect x={0} y={0} width={W} height={H} fill="#1B1E1A" />
      {[
        [30, 24, 330, 150],
        [630, 24, 930, 150],
        [30, 390, 330, 516],
        [630, 390, 930, 516],
      ].map(([x1, y1, x2, y2]) => (
        <rect key={`${x1}-${y1}`} x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="#24271F" stroke="#3A3E39" strokeWidth={1} />
      ))}
      <rect x={0} y={h0 - 22} width={W} height={h1 - h0 + 44} fill="#47453F" />
      <rect x={v0 - 22} y={0} width={v1 - v0 + 44} height={H} fill="#47453F" />
      <rect x={0} y={h0} width={W} height={h1 - h0} fill="#28292B" />
      <rect x={v0} y={0} width={v1 - v0} height={H} fill="#28292B" />
      {[-3, 3].map((o) => (
        <g key={o} stroke={LANE} strokeWidth={2}>
          <line x1={0} y1={cy + o} x2={v0 - 46} y2={cy + o} />
          <line x1={v1 + 46} y1={cy + o} x2={W} y2={cy + o} />
          <line x1={cx + o} y1={0} x2={cx + o} y2={h0 - 46} />
          <line x1={cx + o} y1={h1 + 46} x2={cx + o} y2={H} />
        </g>
      ))}
      {stripesY.map((y) => (
        <g key={`y${y}`} fill={STRIPE}>
          <rect x={v0 - 40} y={y} width={28} height={8} />
          <rect x={v1 + 12} y={y} width={28} height={8} />
        </g>
      ))}
      {stripesX.map((x) => (
        <g key={`x${x}`} fill={STRIPE}>
          <rect x={x} y={h0 - 40} width={8} height={28} />
          <rect x={x} y={h1 + 12} width={8} height={28} />
        </g>
      ))}
      <g stroke={STRIPE} strokeWidth={3}>
        <line x1={v0 - 46} y1={cy + 6} x2={v0 - 46} y2={h1} />
        <line x1={v1 + 46} y1={h0} x2={v1 + 46} y2={cy - 6} />
        <line x1={v0} y1={h0 - 46} x2={cx - 6} y2={h0 - 46} />
        <line x1={cx + 6} y1={h1 + 46} x2={v1} y2={h1 + 46} />
      </g>
    </g>
  );
};

export const Intersection: React.FC<Props> = ({t, width, height, view, highlight = {}, trailsFrom, projections = [], rings = [], dim = 0, showIds = true, style}) => {
  const vb = view ?? [0, 0, metrics.source.frame.width, metrics.source.frame.height];
  const unit = vb[2] / 960; // keep strokes visually constant when cropped
  return (
    <svg width={width} height={height} viewBox={vb.join(' ')} preserveAspectRatio="xMidYMid slice" style={{display: 'block', ...style}}>
      <Background />
      {trailsFrom !== undefined &&
        metrics.actors
          .filter((a) => highlight[a.track_id])
          .map((a) => {
            const pts = actorTrail(a, Math.max(trailsFrom, 0), t);
            if (pts.length < 2) return null;
            return (
              <polyline
                key={`trail-${a.track_id}`}
                points={pts.map((p) => p.join(',')).join(' ')}
                fill="none"
                stroke={highlight[a.track_id]}
                strokeWidth={3 * unit}
                strokeOpacity={0.75}
                strokeLinecap="round"
              />
            );
          })}
      {projections.map((p, i) => {
        const k = p.progress ?? 1;
        const to: Point = [p.from[0] + (p.to[0] - p.from[0]) * k, p.from[1] + (p.to[1] - p.from[1]) * k];
        return (
          <line key={`proj-${i}`} x1={p.from[0]} y1={p.from[1]} x2={to[0]} y2={to[1]} stroke={p.color} strokeWidth={3 * unit} strokeDasharray={`${10 * unit} ${7 * unit}`} strokeLinecap="round" />
        );
      })}
      {metrics.actors.map((a) => {
        const p = actorAt(a, t);
        if (!p) return null;
        const accent = highlight[a.track_id];
        if (a.class_name === 'person') {
          return <circle key={a.track_id} cx={p[0]} cy={p[1]} r={6} fill="#E6E6E6" opacity={dim ? 1 - dim * 0.6 : 1} />;
        }
        const [w, h] = a.size;
        return (
          <g key={a.track_id} opacity={accent ? 1 : 1 - dim * 0.7}>
            <rect x={p[0] - w / 2} y={p[1] - h / 2} width={w} height={h} rx={3} fill={a.color} stroke="#151515" strokeWidth={1} />
            {accent && (
              <rect x={p[0] - w / 2 - 5} y={p[1] - h / 2 - 5} width={w + 10} height={h + 10} rx={4} fill="none" stroke={accent} strokeWidth={3 * unit} />
            )}
            {accent && showIds && (
              <text x={p[0] + w / 2 + 8} y={p[1] - h / 2 - 6} fill={accent} fontFamily={F.mono} fontSize={18 * unit} fontWeight={500}>
                #{a.track_id}
              </text>
            )}
          </g>
        );
      })}
      {rings.map((r, i) => (
        <circle key={`ring-${i}`} cx={r.at[0]} cy={r.at[1]} r={r.r} fill="none" stroke={r.color} strokeWidth={3 * unit} opacity={r.opacity ?? 1} />
      ))}
    </svg>
  );
};
