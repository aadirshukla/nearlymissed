import React from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame} from 'remotion';
import {fadeInOut, ramp, rise} from '../anim';
import {Kicker, Serif} from '../components/Text';
import {MUSIC_CREDIT} from '../data';
import {C, F} from '../theme';

// 153-165 s. AI + open-source credits and the proposed next step, then close.
export const S7Close: React.FC<{withMusic: boolean}> = ({withMusic}) => {
  const frame = useCurrentFrame();
  const credits = fadeInOut(frame, 0, 190, 12);
  const close = ramp(frame, 190, 210);
  const out = 1 - ramp(frame, 330, 360);
  const Block: React.FC<{title: string; at: number; children: React.ReactNode}> = ({title, at, children}) => (
    <div style={{...rise(frame, at, 14)}}>
      <div style={{fontFamily: F.mono, fontSize: 20, letterSpacing: 3, color: C.amber, textTransform: 'uppercase'}}>{title}</div>
      <div style={{fontFamily: F.sans, fontSize: 28, color: C.white, lineHeight: 1.4, marginTop: 12}}>{children}</div>
    </div>
  );
  return (
    <AbsoluteFill style={{background: C.ink, opacity: out}}>
      <AbsoluteFill style={{opacity: credits, padding: '150px 120px 0'}}>
        <Kicker at={2}>Credits and next step</Kicker>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 100, rowGap: 46, marginTop: 44}}>
          <Block title="AI assistance" at={8}>
            OpenAI Codex and Anthropic Claude (Opus) assisted with writing, reviewing and testing code, and with building this video. Results shown come from running the app and its tests.
          </Block>
          <Block title="Open source" at={18}>
            Ultralytics YOLO · ByteTrack · OpenCV · Streamlit · Plotly · ReportLab · Remotion · Inter, Instrument Serif and JetBrains Mono fonts (OFL)
          </Block>
          <Block title="Proposed next step" at={28}>
            A supervised pilot with permissioned footage from one fixed camera, measuring accuracy against human-labelled events before making any claims.
          </Block>
          {/* The silent export is a remux of the same frames, so the credit names the soundtrack version. */}
          <Block title={MUSIC_CREDIT && withMusic ? 'Music (soundtrack version)' : 'Sound'} at={38}>
            {MUSIC_CREDIT && withMusic ? MUSIC_CREDIT : 'Text only; no soundtrack.'}
          </Block>
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{opacity: close}}>
        <AbsoluteFill style={{opacity: 0.35}}>
          <Img src={staticFile('hero/nearmiss-hero.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${1 + ramp(frame, 190, 360) * 0.04})`}} />
        </AbsoluteFill>
        <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(11,11,12,0.5), rgba(11,11,12,0.92))'}} />
        <div style={{position: 'absolute', left: 120, top: 330}}>
          <div style={{fontFamily: F.sans, fontWeight: 600, fontSize: 96, letterSpacing: -3, color: C.white, ...rise(frame, 196, 30, 22)}}>
            A near miss disappears <Serif>in seconds.</Serif>
          </div>
          <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 116, color: C.coral, marginTop: 6, ...rise(frame, 214, 30, 22)}}>Its evidence shouldn’t.</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 22, marginTop: 70, ...rise(frame, 236, 20)}}>
            <svg width={40} height={40} viewBox="0 0 30 30">
              <circle cx={15} cy={15} r={9} fill="none" stroke={C.amber} strokeWidth={3} />
              <circle cx={15} cy={15} r={3} fill={C.amber} />
            </svg>
            <span style={{fontFamily: F.sans, fontWeight: 600, fontSize: 40, color: C.white}}>NearMiss</span>
            <span style={{fontFamily: F.sans, fontSize: 32, color: C.muted, marginLeft: 20}}>Srivibhav Padakandla · Aadi Shukla</span>
          </div>
        </div>
        <div style={{position: 'absolute', right: 60, bottom: 44, fontFamily: F.mono, fontSize: 18, color: C.muted}}>
          Illustrative image · not analyzed footage
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
