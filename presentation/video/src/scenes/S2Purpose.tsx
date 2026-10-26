import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import {fadeInOut, rise} from '../anim';
import {Body, Headline, Kicker, Serif, SyntheticTag} from '../components/Text';
import {C, F} from '../theme';

// 12-27 s. What NearMiss is, who built it, who it is for.
const STEPS = [
  ['Predict', 'Projects tracked paths and flags potential conflicts.'],
  ['Detect', 'Separately screens for contact plus a motion response.'],
  ['Verify', 'A person reviews the source frame and clip.'],
  ['Notify', 'Confirmation creates one local, simulated notice.'],
];

export const S2Purpose: React.FC = () => {
  const frame = useCurrentFrame();
  const a = fadeInOut(frame, 0, 160, 14);
  const b = fadeInOut(frame, 160, 300, 14);
  const c = fadeInOut(frame, 300, 450, 14);
  return (
    <AbsoluteFill style={{background: C.ink}}>
      <AbsoluteFill style={{opacity: 0.22}}>
        <Img src={staticFile('hero/nearmiss-hero.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(14px) saturate(0.6)', transform: 'scale(1.08)'}} />
      </AbsoluteFill>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 30% 40%, rgba(11,11,12,0.55), rgba(11,11,12,0.95))'}} />

      <AbsoluteFill style={{padding: '190px 120px 0', opacity: a}}>
        <Kicker at={4}>What NearMiss does</Kicker>
        <Headline at={10} size={84} style={{marginTop: 26, maxWidth: 1500}}>
          Turns fixed-camera traffic footage into <Serif color={C.amber}>evidence a person can check.</Serif>
        </Headline>
        <div style={{display: 'flex', gap: 28, marginTop: 90}}>
          {STEPS.map(([name, copy], i) => (
            <div key={name} style={{flex: 1, borderTop: `3px solid ${i === 2 ? C.coral : C.amber}`, paddingTop: 22, ...rise(frame, 40 + i * 14)}}>
              <div style={{fontFamily: F.mono, fontSize: 22, color: C.muted, letterSpacing: 2}}>0{i + 1}</div>
              <div style={{fontFamily: F.sans, fontSize: 44, fontWeight: 600, color: C.white, marginTop: 6}}>{name}</div>
              <div style={{fontFamily: F.sans, fontSize: 28, color: C.muted, marginTop: 10, lineHeight: 1.35}}>{copy}</div>
            </div>
          ))}
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{padding: '300px 120px 0', opacity: b}}>
        <Kicker at={164}>Built by</Kicker>
        <div style={{display: 'flex', gap: 120, marginTop: 40}}>
          {['Srivibhav Padakandla', 'Aadi Shukla'].map((name, i) => (
            <div key={name} style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 128, color: C.white, lineHeight: 1, ...rise(frame, 172 + i * 12, 36, 22)}}>
              {name}
            </div>
          ))}
        </div>
        <Body at={200} size={32} color={C.muted} style={{marginTop: 50}}>
          Congressional App Challenge entry · runs locally on a laptop
        </Body>
      </AbsoluteFill>

      <AbsoluteFill style={{padding: '250px 120px 0', opacity: c}}>
        <Kicker at={304}>Who it is for</Kicker>
        <Headline at={310} size={72} style={{marginTop: 26, maxWidth: 1560}}>
          People who review intersections: safety staff, and neighbors preparing a <Serif color={C.amber}>street-safety conversation.</Serif>
        </Headline>
        <div style={{marginTop: 80, display: 'flex', alignItems: 'center', gap: 22, ...rise(frame, 345)}}>
          <SyntheticTag />
          <span style={{fontFamily: F.sans, fontSize: 30, color: C.white}}>
            Every app scene that follows uses NearMiss’s labeled demo: generated footage and scripted tracks. No real place, no real crash.
          </span>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
