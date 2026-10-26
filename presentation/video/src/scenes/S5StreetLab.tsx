import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {AbsoluteFill, continueRender, delayRender, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {easeInOut, rise} from '../anim';
import {SplitBeat} from '../components/Beat';
import {CaptureView} from '../components/CaptureView';
import {MarkdownPage} from '../components/MarkdownPage';
import {Serif, SyntheticTag, Tag} from '../components/Text';
import {briefText, metrics} from '../data';
import {C, F} from '../theme';

// 105-130 s. Street Lab review list + crossing arithmetic, then the actual
// exported per-record evidence brief (Markdown).
export const LAB_BEATS = {lab: [0, 360], brief: [360, 750]} as const;

const CAP_W = 1120;
const CAP_H = 760;

const LabBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const crossing = metrics.streetlab.crossing;
  const a = crossing.assumptions;
  return (
    <SplitBeat
      duration={360}
      kicker="Step 9 · Street Lab"
      title={<>From flags to a <Serif color={C.amber}>follow-up plan.</Serif></>}
      body="Street Lab lists which interactions deserve a human look and why, then compares crossing times under assumptions you enter."
      extra={
        <div style={{marginTop: 28, ...rise(frame, 170, 16)}}>
          <div style={{fontFamily: F.mono, fontSize: 20, color: C.muted, marginBottom: 10}}>
            {a.current_distance} {a.unit} → {a.proposed_distance} {a.unit} · start-up {a.start_up_seconds} s
          </div>
          {crossing.rows.map((r) => (
            <div key={r.walker} style={{fontFamily: F.mono, fontSize: 24, color: C.white, lineHeight: 1.6}}>
              {r.speed} {a.unit}/s: {r.current_seconds} s → <span style={{color: C.amber}}>{r.proposed_seconds} s</span>
            </div>
          ))}
          <div style={{fontFamily: F.sans, fontSize: 22, color: C.coral, marginTop: 14, lineHeight: 1.35}}>
            Arithmetic on placeholder assumptions. Not a crash reduction.
          </div>
        </div>
      }
    >
      <CaptureView
        name="streetlab.png"
        width={CAP_W}
        height={CAP_H}
        cams={[{at: 10, rect: [0.26, 0, 0.74, 0.27]}, {at: 150, rect: [0.26, 0, 0.74, 0.27]}, {at: 210, rect: [0.26, 0.58, 0.74, 0.42]}]}
        highlights={[
          {from: 40, to: 160, rect: [0.272, 0.07, 0.715, 0.18], label: 'Why each item needs review', labelSide: 'bottom'},
          {from: 230, rect: [0.37, 0.72, 0.5, 0.2], label: 'Current vs hypothetical crossing time', labelSide: 'top'},
        ]}
        caption="Actual app · Street Lab (placeholder assumptions)"
      />
    </SplitBeat>
  );
};

const BriefBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const text = briefText();
  const o = Math.min(interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'}), interpolate(frame, [378, 390], [1, 0], {extrapolateLeft: 'clamp'}));
  const title = text?.split('\n').find((l) => l.startsWith('# '))?.replace(/^#\s*/, '') ?? '';
  const PAGE_H = 820;
  // Measure the rendered brief once the local fonts have loaded, so the scroll
  // stops land on the headings; the frame is held until the stops are applied.
  const docRef = useRef<HTMLDivElement>(null);
  const [handle] = useState(() => delayRender('measure brief after fonts load'));
  const released = useRef(false);
  const [stops, setStops] = useState<number[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      const root = docRef.current;
      if (!root) {
        setStops([0, 0, 0]);
        return;
      }
      const max = Math.max(0, root.scrollHeight - PAGE_H);
      const at = (heading: string) => {
        const el = root.querySelector<HTMLElement>(`[data-heading="${heading}"]`);
        return el ? Math.min(max, Math.max(0, el.offsetTop - 40)) : max;
      };
      setStops([0, at('Human review'), at('What this brief does not claim')]);
    };
    document.fonts.ready.then(measure, measure);
    return () => {
      cancelled = true;
    };
  }, []);
  useLayoutEffect(() => {
    if (stops && !released.current) {
      released.current = true;
      continueRender(handle);
    }
  }, [stops, handle]);
  useEffect(
    () => () => {
      // Unmounted before measuring: never leave the render waiting.
      if (!released.current) {
        released.current = true;
        continueRender(handle);
      }
    },
    [handle],
  );
  const s0 = stops ?? [0, 0, 0];
  // Hold on the header, then the review/dispatch record, then the limits.
  const y = interpolate(frame, [0, 110, 150, 250, 290, 390], [s0[0], s0[0], s0[1], s0[1], s0[2], s0[2]], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeInOut,
  });
  return (
    <AbsoluteFill style={{opacity: o}}>
      <div style={{position: 'absolute', left: 120, top: 170, width: 520}}>
        <div style={{fontFamily: F.mono, fontSize: 24, letterSpacing: 4, textTransform: 'uppercase', color: C.amber, ...rise(frame, 2, 14)}}>Step 10 · The evidence travels</div>
        <div style={{fontFamily: F.sans, fontWeight: 600, fontSize: 58, letterSpacing: -1.7, lineHeight: 1.04, color: C.white, marginTop: 22, ...rise(frame, 6)}}>
          A brief anyone can <Serif color={C.amber}>check later.</Serif>
        </div>
        <div style={{fontFamily: F.sans, fontSize: 28, color: C.muted, lineHeight: 1.4, marginTop: 28, ...rise(frame, 14, 18)}}>
          This is the actual file downloaded from the app: a per-record evidence brief in Markdown. It carries the synthetic label, the human review, the simulated notice, and what it does not claim.
        </div>
        <div style={{fontFamily: F.sans, fontSize: 22, color: C.muted, lineHeight: 1.4, marginTop: 24, ...rise(frame, 30, 18)}}>
          Street Lab’s community brief and the Analysis PDF report are separate exports.
        </div>
        <div style={{marginTop: 28, display: 'flex', gap: 12, ...rise(frame, 40, 18)}}>
          <SyntheticTag />
          <Tag>brief.md</Tag>
        </div>
      </div>
      <div style={{position: 'absolute', right: 120, top: 150, width: CAP_W, height: PAGE_H, overflow: 'hidden', borderRadius: 14, background: C.paper, boxShadow: '0 30px 80px rgba(0,0,0,0.55)'}}>
        {text ? (
          <div ref={docRef} style={{transform: `translateY(${-y}px)`}}>
            <MarkdownPage text={text} width={CAP_W} scale={1.05} />
          </div>
        ) : (
          <div style={{padding: 60, fontFamily: F.mono, fontSize: 30, color: C.coral}}>Host capture pending: brief.md</div>
        )}
      </div>
      {title && (
        <div style={{position: 'absolute', right: 120, top: 150 + PAGE_H + 14, fontFamily: F.mono, fontSize: 18, color: C.muted}}>
          Actual export · “{title}”
        </div>
      )}
    </AbsoluteFill>
  );
};

export const S5StreetLab: React.FC = () => (
  <AbsoluteFill style={{background: C.ink}}>
    <Sequence from={LAB_BEATS.lab[0]} durationInFrames={LAB_BEATS.lab[1] - LAB_BEATS.lab[0]}>
      <LabBeat />
    </Sequence>
    <Sequence from={LAB_BEATS.brief[0]} durationInFrames={LAB_BEATS.brief[1] - LAB_BEATS.brief[0]}>
      <BriefBeat />
    </Sequence>
  </AbsoluteFill>
);
