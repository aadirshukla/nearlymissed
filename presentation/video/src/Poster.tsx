import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {Serif, SyntheticTag} from './components/Text';
import {ensureFonts} from './fonts';
import {C, F} from './theme';

ensureFonts();

// Static poster frame for the MP4 (title card over the landing image).
export const Poster: React.FC = () => (
  <AbsoluteFill style={{background: C.ink}}>
    <Img src={staticFile('hero/nearmiss-hero.jpg')} style={{width: '100%', height: '100%', objectFit: 'cover', opacity: 0.6}} />
    <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(11,11,12,0.2) 0%, rgba(11,11,12,0.6) 50%, rgba(11,11,12,0.95) 100%)'}} />
    <div style={{position: 'absolute', left: 120, top: 100, display: 'flex', alignItems: 'center', gap: 18}}>
      <svg width={44} height={44} viewBox="0 0 30 30">
        <circle cx={15} cy={15} r={9} fill="none" stroke={C.amber} strokeWidth={3} />
        <circle cx={15} cy={15} r={3} fill={C.amber} />
      </svg>
      <span style={{fontFamily: F.sans, fontWeight: 600, fontSize: 42, color: C.white}}>NearMiss</span>
    </div>
    <div style={{position: 'absolute', left: 120, bottom: 160}}>
      <div style={{fontFamily: F.sans, fontWeight: 600, fontSize: 108, letterSpacing: -3, color: C.white, lineHeight: 1.02}}>
        A near miss disappears <Serif>in seconds.</Serif>
      </div>
      <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 128, color: C.coral, marginTop: 8}}>Its evidence shouldn’t.</div>
      <div style={{fontFamily: F.sans, fontSize: 34, color: C.muted, marginTop: 40}}>Srivibhav Padakandla · Aadi Shukla · 2:45 demo, text and music</div>
    </div>
    <div style={{position: 'absolute', right: 60, bottom: 44, display: 'flex', gap: 18, alignItems: 'center'}}>
      <span style={{fontFamily: F.mono, fontSize: 18, color: C.muted}}>Illustrative image · app scenes use the labeled synthetic demo</span>
      <SyntheticTag />
    </div>
  </AbsoluteFill>
);
