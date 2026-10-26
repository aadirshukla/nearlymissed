import React from 'react';
import {AbsoluteFill, Freeze, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {fadeInOut, ramp, rise} from '../anim';
import {SplitBeat} from '../components/Beat';
import {CaptureView} from '../components/CaptureView';
import {Intersection} from '../components/Intersection';
import {Kicker, Serif, SyntheticTag, Tag} from '../components/Text';
import {actorById, arrivalTimes, events, firstEvent, fitView, geometryLabel, incident, metrics, participants, Point} from '../data';
import {C, F} from '../theme';

// 27-72 s. Actual app: start -> annotated warnings -> counts -> why -> source frame.
export const APP_BEATS = {start: [0, 240], clip: [240, 690], counts: [690, 930], why: [930, 1170], source: [1170, 1350]} as const;

const CAP_W = 1120;
const CAP_H = 760;

const severityColor = (s: string) => (s === 'HIGH' ? C.coral : s === 'MEDIUM' ? C.amber : C.muted);

const StartBeat: React.FC = () => (
  <SplitBeat
    duration={240}
    kicker="Step 1 · Start"
    title={<>One click opens the <Serif color={C.amber}>labeled demo.</Serif></>}
    body="No upload, network or model download. The street image is context only; it is never analyzed."
  >
    <CaptureView
      name="overview.png"
      width={CAP_W}
      height={CAP_H}
      cams={[{at: 50, rect: [0, 0, 1, 1]}, {at: 130, rect: [0.34, 0.47, 0.5, 0.27]}]}
      highlights={[{from: 125, rect: [0.4, 0.587, 0.388, 0.048], label: 'Start guided demo', labelSide: 'bottom'}]}
      caption="Actual app · Overview"
    />
  </SplitBeat>
);

const CLIP_START = 40;
const CLIP_FRAMES = 360; // 12 s demo clip resampled to 30 fps

const ClipBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const o = fadeInOut(frame, 0, 450, 12);
  const duration = metrics.source.frame.duration_seconds;
  const t = Math.max(0, Math.min(duration, (frame - CLIP_START) / 30));
  const items = [
    ...events.map((e) => ({
      time: e.first_alert_seconds,
      clock: e.first_alert_clock,
      tag: e.severity,
      color: severityColor(e.severity),
      title: `${geometryLabel(e)} · ${participants(e)}`,
      detail:
        e.geometry === 'same_direction_following' && e.time_headway_seconds !== null
          ? `time headway ${e.time_headway_seconds.toFixed(2)} s`
          : `arrival gap ${e.arrival_gap_seconds?.toFixed(2)} s`,
    })),
    ...(incident
      ? [{
          time: incident.first_contact_seconds,
          clock: incident.first_contact_clock,
          tag: 'Suspected contact',
          color: C.coral,
          title: `Contact · vehicles #${incident.track_ids.join(' / #')}`,
          detail: `${incident.evidence_signal_count} supporting signals · needs human review`,
        }]
      : []),
  ].sort((a, b) => a.time - b.time);
  const VW = 1240;
  const VH = 698;

  return (
    <AbsoluteFill style={{opacity: o}}>
      <div style={{position: 'absolute', left: 120, top: 150}}>
        <Kicker at={2}>Step 2 · Warnings, computed</Kicker>
        <div style={{fontFamily: F.sans, fontSize: 44, fontWeight: 600, color: C.white, marginTop: 14, ...rise(frame, 6)}}>
          The app’s own annotated render, <Serif color={C.amber}>in real time.</Serif>
        </div>
      </div>
      <div style={{position: 'absolute', left: 120, top: 290, width: VW, height: VH, borderRadius: 14, overflow: 'hidden', outline: `1px solid ${C.line}`, background: '#000'}}>
        {frame < CLIP_START + CLIP_FRAMES ? (
          <Sequence from={CLIP_START} layout="none">
            <OffthreadVideo src={staticFile('clips/demo-annotated-30fps.mp4')} muted style={{width: VW, height: VH}} />
          </Sequence>
        ) : (
          <Freeze frame={CLIP_FRAMES - 1}>
            <OffthreadVideo src={staticFile('clips/demo-annotated-30fps.mp4')} muted style={{width: VW, height: VH}} />
          </Freeze>
        )}
        <div style={{position: 'absolute', left: 16, top: 16}}>
          <SyntheticTag />
        </div>
      </div>
      {/* timeline under the clip */}
      <div style={{position: 'absolute', left: 120, top: 290 + VH + 26, width: VW, height: 40}}>
        <div style={{position: 'absolute', left: 0, right: 0, top: 18, height: 4, background: C.line, borderRadius: 2}} />
        <div style={{position: 'absolute', left: 0, top: 18, height: 4, width: (t / duration) * VW, background: C.white, borderRadius: 2}} />
        {items.map((it) => (
          <div key={it.clock + it.tag} style={{position: 'absolute', left: (it.time / duration) * VW - 9, top: 11, width: 18, height: 18, borderRadius: 9, background: t >= it.time ? it.color : C.ink, border: `3px solid ${it.color}`}} />
        ))}
        <div style={{position: 'absolute', left: (t / duration) * VW - 1, top: 4, width: 3, height: 32, background: C.white}} />
      </div>
      <div style={{position: 'absolute', left: 120, top: 290 + VH + 72, fontFamily: F.mono, fontSize: 18, color: C.muted}}>
        {`Actual NearMiss annotated render of the synthetic demo · ${metrics.source.frame.width}×${metrics.source.frame.height} · ${duration.toFixed(0)} s · t = ${t.toFixed(1)} s`}
      </div>
      {/* evidence cards appear when the playhead reaches them */}
      <div style={{position: 'absolute', left: 120 + VW + 36, top: 290, width: 1920 - 240 - VW - 36, display: 'flex', flexDirection: 'column', gap: 18}}>
        {items.map((it) => {
          const shown = ramp(frame, CLIP_START + it.time * 30, CLIP_START + it.time * 30 + 10);
          return (
            <div key={it.clock + it.tag} style={{opacity: shown, transform: `translateX(${(1 - shown) * 30}px)`, borderLeft: `4px solid ${it.color}`, background: C.card, padding: '16px 18px', borderRadius: 6}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                <span style={{fontFamily: F.mono, fontSize: 24, color: C.white}}>{it.clock}</span>
                <Tag color={it.color} style={{fontSize: 15, padding: '3px 8px'}}>{it.tag}</Tag>
              </div>
              <div style={{fontFamily: F.sans, fontSize: 22, color: C.white, marginTop: 10, lineHeight: 1.3}}>{it.title}</div>
              <div style={{fontFamily: F.sans, fontSize: 20, color: C.muted, marginTop: 6}}>{it.detail}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const CountsBeat: React.FC = () => (
  <SplitBeat
    duration={240}
    kicker="Step 3 · Counted, not scripted"
    title={<>Staged scenes. <Serif color={C.amber}>Computed warnings.</Serif></>}
    body={
      <>
        {metrics.tracks.vehicles} vehicles, {metrics.streetlab.warnings_total} potential conflicts and {metrics.streetlab.incidents_total} suspected incident, returned by the same code that runs on uploaded footage. Only YOLO + ByteTrack are replaced, by scripted tracks.
      </>
    }
  >
    <CaptureView
      name="analysis.png"
      width={CAP_W}
      height={CAP_H}
      cams={[{at: 20, rect: [0, 0, 1, 1]}, {at: 90, rect: [0.25, 0.52, 0.75, 0.24]}]}
      highlights={[{from: 95, rect: [0.265, 0.625, 0.73, 0.095], label: 'Detector output for this run'}]}
      caption="Actual app · Analysis"
    />
  </SplitBeat>
);

const NB = '\u00a0'; // keeps a number and its unit on one line

const WhyBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const e = firstEvent;
  const a = actorById(e.track_ids[0]);
  const b = actorById(e.track_ids[1]);
  // Everything in this diagram is the representative measurement row (not the first alert):
  // both road users, both projections and the ETAs/gap come from the same frame.
  const m = e.measurement;
  const t = m.seconds;
  const conflict = e.conflict_point as Point;
  const anchorA = m.anchors[String(a.track_id)];
  const anchorB = m.anchors[String(b.track_id)];
  const corners = Object.values(m.boxes).flatMap(([x1, y1, x2, y2]) => [[x1, y1], [x2, y2]] as Point[]);
  const view = fitView([...corners, conflict], 44, 520 / 360);
  const arrivals = arrivalTimes(e);
  const high = Number(metrics.settings.high_time_gap_seconds);
  const grow = ramp(frame, 30, 80);
  return (
    <SplitBeat
      duration={240}
      kicker="Step 4 · How a warning is earned"
      title={<>Two arrival times, <Serif color={C.amber}>one gap.</Serif></>}
      extra={
        <div style={{marginTop: 30, ...rise(frame, 20)}}>
          <div style={{borderRadius: 10, overflow: 'hidden', outline: `1px solid ${C.line}`, position: 'relative'}}>
            <Intersection
              t={t}
              width={520}
              height={360}
              view={view}
              highlight={{[a.track_id]: C.amber, [b.track_id]: C.amber}}
              projections={[
                {from: anchorA, to: conflict, color: C.amber, progress: grow},
                {from: anchorB, to: conflict, color: C.amber, progress: grow},
              ]}
              rings={[{at: conflict, r: 12, color: C.coral, opacity: ramp(frame, 70, 85)}]}
            />
            <div style={{position: 'absolute', left: 10, bottom: 10}}><Tag style={{fontSize: 14, padding: '3px 8px'}}>Diagram · measurement frame {m.frame} · {m.clock}</Tag></div>
          </div>
          {arrivals && (
            <div style={{fontFamily: F.mono, fontSize: 24, color: C.white, marginTop: 22, lineHeight: 1.6, opacity: ramp(frame, 85, 100)}}>
              {a.class_name} #{a.track_id} → {arrivals[0].toFixed(2)}{NB}s<br />
              {b.class_name} #{b.track_id} → {arrivals[1].toFixed(2)}{NB}s<br />
              <span style={{color: C.coral}}>gap {e.arrival_gap_seconds?.toFixed(2)}{NB}s ≤ {high.toFixed(2)}{NB}s → {e.severity}</span>
              <div style={{fontSize: 17, color: C.muted, lineHeight: 1.4, marginTop: 10}}>
                Measured at {m.clock} (frame{NB}{m.frame}). First alert {e.first_alert_clock}.
              </div>
            </div>
          )}
        </div>
      }
    >
      <CaptureView
        name="warning.png"
        width={CAP_W}
        height={CAP_H}
        cams={[{at: 10, rect: [0.26, 0.2, 0.74, 0.42]}, {at: 120, rect: [0.27, 0.32, 0.6, 0.3]}]}
        highlights={[{from: 110, rect: [0.302, 0.43, 0.27, 0.032], label: 'Arrival gap vs thresholds', labelSide: 'bottom'}]}
        caption="Actual app · Why each warning was raised"
      />
    </SplitBeat>
  );
};

const SourceBeat: React.FC = () => (
  <SplitBeat
    duration={180}
    kicker="Step 5 · Back to the source"
    title={<>Jump to the <Serif color={C.amber}>exact frame.</Serif></>}
    body={
      <>
        Frame {firstEvent.first_alert_frame} ({firstEvent.first_alert_clock}) is the warning’s first alert. The boxes are stored observations for tracks #{firstEvent.track_ids.join(' and #')}; nothing is re-detected.
      </>
    }
  >
    <CaptureView
      name="investigation.png"
      width={CAP_W}
      height={CAP_H}
      cams={[{at: 10, rect: [0.26, 0, 0.74, 0.78]}, {at: 120, rect: [0.26, 0.05, 0.74, 0.95]}]}
      highlights={[{from: 40, rect: [0.505, 0.745, 0.24, 0.026], label: 'Original frame, stored observations only', labelSide: 'bottom'}]}
      caption="Actual app · Investigation"
    />
  </SplitBeat>
);

export const S3App: React.FC = () => (
  <AbsoluteFill style={{background: C.ink}}>
    {(
      [
        ['start', StartBeat],
        ['clip', ClipBeat],
        ['counts', CountsBeat],
        ['why', WhyBeat],
        ['source', SourceBeat],
      ] as const
    ).map(([key, Beat]) => (
      <Sequence key={key} from={APP_BEATS[key][0]} durationInFrames={APP_BEATS[key][1] - APP_BEATS[key][0]}>
        <Beat />
      </Sequence>
    ))}
  </AbsoluteFill>
);
