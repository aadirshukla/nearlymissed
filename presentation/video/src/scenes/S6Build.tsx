import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {fadeInOut, ramp, rise} from '../anim';
import {Headline, Kicker, Serif} from '../components/Text';
import {metrics, testDateLabel} from '../data';
import {C, F} from '../theme';

// 130-153 s. What is open source, what NearMiss adds, what is verified and
// what is not. Facts follow README.md and docs/challenge-demo-guide.md.
export const BUILD_BEATS = {tools: [0, 330], limits: [330, 690]} as const;

const OPEN_SOURCE = [
  ['Ultralytics YOLO', 'detects road users'],
  ['ByteTrack', 'keeps their IDs across frames'],
  ['OpenCV', 'reads, draws and writes video'],
  ['Streamlit · Plotly', 'interface and charts'],
];
const CUSTOM = [
  'Timestamp-based trajectory prediction and conflict gates',
  'Same-direction following check',
  'Multi-signal suspected-collision detector',
  'Evidence association and de-duplication',
  'SQLite review record and simulated dispatch audit trail',
  'Investigation, evidence briefs, Street Lab, run library',
];

const ToolsBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const o = fadeInOut(frame, 0, 330, 12);
  const arrow = ramp(frame, 60, 100);
  return (
    <AbsoluteFill style={{opacity: o, padding: '160px 120px 0'}}>
      <Kicker at={2}>Step 11 · What we used, what we wrote</Kicker>
      <Headline at={6} size={62} style={{marginTop: 20}}>
        Open-source eyes. <Serif color={C.amber}>Our own judgment layer.</Serif>
      </Headline>
      <div style={{display: 'flex', gap: 0, marginTop: 70, alignItems: 'stretch'}}>
        <div style={{width: 560, border: `1.5px solid ${C.line}`, borderRadius: 12, padding: '28px 32px', ...rise(frame, 20)}}>
          <div style={{fontFamily: F.mono, fontSize: 20, letterSpacing: 3, color: C.muted, textTransform: 'uppercase'}}>Existing open source</div>
          {OPEN_SOURCE.map(([name, role], i) => (
            <div key={name} style={{marginTop: 24, ...rise(frame, 30 + i * 8, 12)}}>
              <div style={{fontFamily: F.sans, fontSize: 32, fontWeight: 600, color: C.white}}>{name}</div>
              <div style={{fontFamily: F.sans, fontSize: 24, color: C.muted}}>{role}</div>
            </div>
          ))}
        </div>
        <div style={{width: 160, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <svg width={120} height={40} viewBox="0 0 120 40">
            <line x1={10} y1={20} x2={10 + 90 * arrow} y2={20} stroke={C.amber} strokeWidth={4} strokeLinecap="round" />
            <path d="M96 8 L112 20 L96 32" fill="none" stroke={C.amber} strokeWidth={4} opacity={arrow} strokeLinejoin="round" />
          </svg>
        </div>
        <div style={{flex: 1, border: `2px solid ${C.amber}`, borderRadius: 12, padding: '28px 36px', background: 'rgba(242,169,59,0.06)', ...rise(frame, 70)}}>
          <div style={{fontFamily: F.mono, fontSize: 20, letterSpacing: 3, color: C.amber, textTransform: 'uppercase'}}>NearMiss custom logic</div>
          {CUSTOM.map((item, i) => (
            <div key={item} style={{display: 'flex', gap: 18, alignItems: 'baseline', marginTop: 22, ...rise(frame, 90 + i * 14, 12)}}>
              <span style={{fontFamily: F.mono, fontSize: 22, color: C.amber}}>{String(i + 1).padStart(2, '0')}</span>
              <span style={{fontFamily: F.sans, fontSize: 30, color: C.white}}>{item}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{fontFamily: F.sans, fontSize: 24, color: C.muted, marginTop: 34, ...rise(frame, 200, 12)}}>
        In the demo, scripted tracks stand in for YOLO + ByteTrack. Everything after detection is the same code used for uploaded MP4s.
      </div>
    </AbsoluteFill>
  );
};

const LimitsBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const o = fadeInOut(frame, 0, 360, 12);
  const tests = metrics.tests;
    const verified = [
    tests ? `Automated tests: ${tests.summary.replace(/ in [\d.]+s$/, '')} (local pytest, ${testDateLabel(tests)})` : 'Automated tests: not run for this render',
    `Deterministic demo: ID ${metrics.source.video_id}, same warnings every run`,
    'Annotated clip regenerated for this video matches the app’s cached render byte for byte',
    'Synthetic label carried through frames, pages and exports',
  ];
  const unproven = [
    'Accuracy on real-world footage has not been measured',
    'Image pixels only: no calibrated metres, speeds or probabilities',
    'No crash-reduction or safety-rating claim',
    'Dispatch is simulated; nothing leaves the computer',
  ];
  const Column: React.FC<{title: string; color: string; items: string[]; at: number; mark: string}> = ({title, color, items, at, mark}) => (
    <div style={{flex: 1}}>
      <div style={{fontFamily: F.mono, fontSize: 22, letterSpacing: 3, color, textTransform: 'uppercase', borderBottom: `3px solid ${color}`, paddingBottom: 14, ...rise(frame, at, 12)}}>{title}</div>
      {items.map((item, i) => (
        <div key={item} style={{display: 'flex', gap: 20, marginTop: 28, ...rise(frame, at + 12 + i * 16, 14)}}>
          <span style={{fontFamily: F.mono, fontSize: 30, color, width: 30}}>{mark}</span>
          <span style={{fontFamily: F.sans, fontSize: 32, color: C.white, lineHeight: 1.3}}>{item}</span>
        </div>
      ))}
    </div>
  );
  return (
    <AbsoluteFill style={{opacity: o, padding: '160px 120px 0'}}>
      <Kicker at={2}>Step 12 · Verified and not yet proven</Kicker>
      <Headline at={6} size={62} style={{marginTop: 20}}>
        Honest about <Serif color={C.coral}>the limits.</Serif>
      </Headline>
      <div style={{display: 'flex', gap: 90, marginTop: 70}}>
        <Column title="Verified in this build" color={C.green} items={verified} at={20} mark="✓" />
        <Column title="Not yet proven" color={C.coral} items={unproven} at={110} mark="—" />
      </div>
    </AbsoluteFill>
  );
};

export const S6Build: React.FC = () => (
  <AbsoluteFill style={{background: C.ink}}>
    <Sequence from={BUILD_BEATS.tools[0]} durationInFrames={BUILD_BEATS.tools[1] - BUILD_BEATS.tools[0]}>
      <ToolsBeat />
    </Sequence>
    <Sequence from={BUILD_BEATS.limits[0]} durationInFrames={BUILD_BEATS.limits[1] - BUILD_BEATS.limits[0]}>
      <LimitsBeat />
    </Sequence>
  </AbsoluteFill>
);
