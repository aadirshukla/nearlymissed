import React from 'react';
import {useCurrentFrame} from 'remotion';
import {ramp} from '../anim';
import timeline from '../timeline.json';
import {C, F} from '../theme';

// Persistent wordmark, chapter label and progress hairline. Hidden during the
// opening hook and the closing card so those frames stay clean.
export const Chrome: React.FC = () => {
  const frame = useCurrentFrame();
  const scenes = timeline.scenes;
  const index = scenes.findIndex((s) => frame >= s.from && frame < s.to);
  const scene = scenes[Math.max(index, 0)];
  const visible = Math.min(ramp(frame, 372, 400), 1 - ramp(frame, 4770, 4800));
  if (visible <= 0) return null;
  const local = frame - scene.from;
  const labelOpacity = Math.min(ramp(local, 0, 14), 1 - ramp(local, scene.to - scene.from - 14, scene.to - scene.from));
  // Source badge stays on (no chapter fade) across app, review and streetlab,
  // where camera zoom can crop the app's own synthetic-data banner.
  const sourceScenes = scenes.filter((s) => ['app', 'review', 'streetlab'].includes(s.id));
  const showSource = frame >= Math.min(...sourceScenes.map((s) => s.from)) && frame < Math.max(...sourceScenes.map((s) => s.to));
  return (
    <div style={{position: 'absolute', inset: 0, opacity: visible, pointerEvents: 'none'}}>
      <div style={{position: 'absolute', left: 120, top: 46, display: 'flex', alignItems: 'center', gap: 18}}>
        <svg width={30} height={30} viewBox="0 0 30 30">
          <circle cx={15} cy={15} r={9} fill="none" stroke={C.amber} strokeWidth={3} />
          <circle cx={15} cy={15} r={3} fill={C.amber} />
        </svg>
        <span style={{fontFamily: F.sans, fontWeight: 600, fontSize: 26, color: C.white, letterSpacing: -0.3}}>NearMiss</span>
        <span style={{fontFamily: F.mono, fontSize: 18, letterSpacing: 3, color: C.muted, textTransform: 'uppercase', opacity: labelOpacity}}>
          {String(index + 1).padStart(2, '0')} / {scene.label}
        </span>
      </div>
      {showSource ? (
        <div style={{position: 'absolute', right: 120, top: 46, padding: '5px 14px', border: `1px solid ${C.amber}`, borderRadius: 6, background: C.ink, fontFamily: F.mono, fontSize: 18, lineHeight: '18px', fontWeight: 600, letterSpacing: 2, color: C.amber, whiteSpace: 'nowrap'}}>
          SYNTHETIC DEMO · LOCAL PROTOTYPE
        </div>
      ) : null}
      <div style={{position: 'absolute', left: 120, right: 120, bottom: 40, height: 3, display: 'flex', gap: 8}}>
        {scenes.map((s) => {
          const k = Math.max(0, Math.min(1, (frame - s.from) / (s.to - s.from)));
          return (
            <div key={s.id} style={{flex: s.to - s.from, background: C.line, borderRadius: 2, overflow: 'hidden'}}>
              <div style={{width: `${k * 100}%`, height: '100%', background: C.amber}} />
            </div>
          );
        })}
      </div>
    </div>
  );
};
