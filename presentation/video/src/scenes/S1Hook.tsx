import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {easeInOut, fadeInOut, lerp, ramp, rise} from '../anim';
import {Intersection} from '../components/Intersection';
import {Serif, SyntheticTag, Tag} from '../components/Text';
import {actorById, firstEvent, frameIndexAt, Point} from '../data';
import {C, F} from '../theme';

// 0-12 s. Photo -> the synthetic intersection replays the scripted near miss
// in real time, then freezes the frame where car #1 crosses the shared point.
const FREEZE_T = 3.45;
const START_T = 1.6;
const DIAGRAM_IN = 100;
const FREEZE_F = DIAGRAM_IN + 10 + Math.round((FREEZE_T - START_T) * 30);

export const S1Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const photo = 1 - ramp(frame, DIAGRAM_IN, DIAGRAM_IN + 30, 0, 1, easeInOut);
  const diagram = ramp(frame, DIAGRAM_IN, DIAGRAM_IN + 30, 0, 1, easeInOut) * (1 - ramp(frame, 330, 358));
  const t = Math.min(FREEZE_T, START_T + Math.max(0, frame - DIAGRAM_IN - 10) / 30);
  const frozen = frame >= FREEZE_F;
  const zoomK = ramp(frame, FREEZE_F + 8, FREEZE_F + 90, 0, 1, easeInOut);
  const view: [number, number, number, number] = [lerp(0, 250, zoomK), lerp(0, 168, zoomK), lerp(960, 560, zoomK), lerp(540, 315, zoomK)];
  const a = actorById(firstEvent.track_ids[0]);
  const b = actorById(firstEvent.track_ids[1]);
  const conflict = firstEvent.conflict_point as Point;
  const flash = frozen ? 1 - ramp(frame, FREEZE_F, FREEZE_F + 10) : 0;

  return (
    <AbsoluteFill style={{background: C.ink}}>
      <AbsoluteFill style={{opacity: photo}}>
        <Img src={staticFile('hero/nearmiss-hero.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${interpolate(frame, [0, 130], [1.1, 1.02])})`}} />
        <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(11,11,12,0.25) 0%, rgba(11,11,12,0.55) 55%, rgba(11,11,12,0.92) 100%)'}} />
        <div style={{position: 'absolute', right: 60, bottom: 44, fontFamily: F.mono, fontSize: 18, color: C.muted, letterSpacing: 1}}>
          Illustrative image · not analyzed footage
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{opacity: diagram, filter: frozen ? `saturate(${lerp(1, 0.35, ramp(frame, FREEZE_F, FREEZE_F + 12))})` : undefined}}>
        <Intersection
          t={t}
          width={1920}
          height={1080}
          view={view}
          highlight={{[a.track_id]: C.amber, [b.track_id]: C.amber}}
          trailsFrom={START_T}
          rings={frozen ? [{at: conflict, r: lerp(60, 26, ramp(frame, FREEZE_F, FREEZE_F + 16)), color: C.coral}] : []}
        />
        <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(11,11,12,0) 45%, rgba(11,11,12,0.88) 100%)'}} />
        <AbsoluteFill style={{background: C.white, opacity: flash * 0.5}} />
        <div style={{position: 'absolute', right: 60, top: 50, display: 'flex', gap: 14, alignItems: 'center'}}>
          <span style={{fontFamily: F.mono, fontSize: 18, color: C.muted}}>Scripted tracks · nearmiss/demo.py</span>
          <SyntheticTag />
        </div>
        {frozen && (
          <div style={{position: 'absolute', right: 60, top: 120, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 14}}>
            <div style={rise(frame, FREEZE_F + 4, 12)}>
              <Tag color={C.coral}>Frame {String(frameIndexAt(FREEZE_T)).padStart(3, '0')} · 00:0{FREEZE_T.toFixed(2)}</Tag>
            </div>
            <div style={{...rise(frame, FREEZE_F + 30, 12), fontFamily: F.sans, fontSize: 30, color: C.white, textAlign: 'right', lineHeight: 1.35}}>
              Scripted: car #{b.track_id} brakes and stops short. No contact.
              <br />
              <span style={{color: C.amber}}>
                First alert {firstEvent.first_alert_clock} · {firstEvent.severity} · arrival gap {firstEvent.arrival_gap_seconds?.toFixed(2)}{'\u00a0'}s, measured at {firstEvent.measurement.clock}
              </span>
            </div>
          </div>
        )}
      </AbsoluteFill>

      <div style={{position: 'absolute', left: 120, bottom: 150, opacity: fadeInOut(frame, 18, 345, 14)}}>
        <div style={{fontFamily: F.sans, fontWeight: 600, fontSize: 104, letterSpacing: -3, color: C.white, lineHeight: 1.02, ...rise(frame, 18, 30, 22)}}>
          A near miss disappears <Serif>in seconds.</Serif>
        </div>
        <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 124, color: C.coral, lineHeight: 1.1, marginTop: 10, ...rise(frame, 228, 30, 22)}}>
          Its evidence shouldn’t.
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const HOOK_FREEZE_FRAME = FREEZE_F;
