import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {ramp, rise} from '../anim';
import {SplitBeat} from '../components/Beat';
import {CaptureView} from '../components/CaptureView';
import {Intersection} from '../components/Intersection';
import {Serif, SyntheticTag, Tag} from '../components/Text';
import {incident, linkedEvent, Point, signalLabel} from '../data';
import {C, F} from '../theme';

// 72-105 s. Independent contact evidence -> human decision -> local simulated notice.
export const REVIEW_BEATS = {contact: [0, 270], decide: [270, 600], notice: [600, 990]} as const;

const CAP_W = 1120;
const CAP_H = 760;

const ContactBeat: React.FC = () => {
  const frame = useCurrentFrame();
  if (!incident) {
    return (
      <SplitBeat duration={270} kicker="Step 6 · A separate detector" title="No suspected incident in this run.">
        <div />
      </SplitBeat>
    );
  }
  const contactT = incident.first_contact_seconds;
  const startT = contactT - 0.8;
  const t = Math.min(contactT, startT + Math.max(0, frame - 20) / 60); // half speed
  const reached = t >= contactT;
  const freezeAt = 20 + 0.8 * 60;
  const [idA, idB] = incident.track_ids;
  return (
    <SplitBeat
      duration={270}
      kicker="Step 6 · A separate detector"
      title={<>Contact needs <Serif color={C.coral}>more than overlap.</Serif></>}
      extra={
        <div style={{marginTop: 30}}>
          {incident.detection_signals.map((s, i) => (
            <div key={s} style={{display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14, ...rise(frame, 80 + i * 16, 16)}}>
              <div style={{width: 14, height: 14, borderRadius: 7, background: C.coral}} />
              <span style={{fontFamily: F.sans, fontSize: 30, color: C.white}}>{signalLabel(s)}</span>
            </div>
          ))}
          {linkedEvent && incident.prediction_lead_seconds !== null && (
            <div style={{fontFamily: F.sans, fontSize: 26, color: C.amber, marginTop: 24, lineHeight: 1.35, ...rise(frame, 180, 16)}}>
              Prediction {linkedEvent.event_id} was raised {incident.prediction_lead_seconds.toFixed(2)} s before first contact, but it does not decide this.
            </div>
          )}
          <div style={{fontFamily: F.sans, fontSize: 24, color: C.muted, marginTop: 18, lineHeight: 1.35, ...rise(frame, 205, 16)}}>
            Correlated measurements of one event, not independent votes.
          </div>
        </div>
      }
    >
      <div style={{position: 'relative', width: CAP_W, height: CAP_H, borderRadius: 14, overflow: 'hidden', outline: `1px solid ${C.line}`}}>
        <Intersection
          t={t}
          width={CAP_W}
          height={CAP_H}
          view={[300, 110, 290, 187]}
          highlight={{[idA]: C.coral, [idB]: C.coral}}
          trailsFrom={startT - 0.6}
          rings={reached ? [{at: incident.contact_point as Point, r: 40 - 24 * ramp(frame, freezeAt, freezeAt + 14), color: C.coral}] : []}
        />
        <div style={{position: 'absolute', left: 20, top: 20, display: 'flex', gap: 12}}>
          <SyntheticTag />
          <Tag>Diagram · scripted tracks · half speed</Tag>
        </div>
        <div style={{position: 'absolute', right: 20, bottom: 20, opacity: reached ? 1 : 0}}>
          <Tag color={C.coral} solid>First contact {incident.first_contact_clock}</Tag>
        </div>
      </div>
    </SplitBeat>
  );
};

const DecideBeat: React.FC = () => (
  <SplitBeat
    duration={330}
    kicker="Step 7 · A person decides"
    title={<>Confirm, dismiss, or <Serif color={C.amber}>leave it uncertain.</Serif></>}
    body="A suspected incident is a review candidate, not proof. The reviewer checks the first-contact frame and replay. Only Confirm creates a notification."
  >
    <CaptureView
      name="incidents.png"
      width={CAP_W}
      height={CAP_H}
      cams={[{at: 10, rect: [0.26, 0, 0.74, 0.56]}, {at: 150, rect: [0.26, 0, 0.74, 0.56]}, {at: 210, rect: [0.6, 0.02, 0.4, 0.96]}]}
      highlights={[
        {from: 40, to: 160, rect: [0.27, 0.0, 0.44, 0.51], color: C.coral, label: 'Source frame at first contact', labelSide: 'bottom'},
        {from: 230, rect: [0.752, 0.846, 0.235, 0.052], label: 'Operator decision', labelSide: 'top'},
      ]}
      caption="Actual app · Incidents (review recorded by host on the synthetic demo)"
    />
  </SplitBeat>
);

const NoticeBeat: React.FC = () => (
  <SplitBeat
    duration={390}
    kicker="Step 8 · Local, simulated notice"
    title={<>Exactly one notice. <Serif color={C.amber}>Nothing leaves the computer.</Serif></>}
    body="Confirming creates one local notification to acknowledge. If the decision is reversed later, the notice is marked Withdrawn instead of staying confirmed. No emergency service is contacted."
  >
    <CaptureView
      name="dispatch.png"
      width={CAP_W}
      height={CAP_H}
      cams={[{at: 10, rect: [0.26, 0.15, 0.74, 0.35]}, {at: 170, rect: [0.26, 0.15, 0.74, 0.35]}, {at: 230, rect: [0.26, 0.52, 0.74, 0.48]}]}
      highlights={[
        {from: 50, to: 180, rect: [0.268, 0.38, 0.72, 0.085], label: 'New · Acknowledged · Withdrawn', labelSide: 'bottom'},
        {from: 250, rect: [0.268, 0.605, 0.238, 0.03], label: 'Local simulation only', labelSide: 'top'},
      ]}
      caption="Actual app · Dispatch (simulated inbox)"
    />
  </SplitBeat>
);

export const S4Review: React.FC = () => (
  <AbsoluteFill style={{background: C.ink}}>
    {(
      [
        ['contact', ContactBeat],
        ['decide', DecideBeat],
        ['notice', NoticeBeat],
      ] as const
    ).map(([key, Beat]) => (
      <Sequence key={key} from={REVIEW_BEATS[key][0]} durationInFrames={REVIEW_BEATS[key][1] - REVIEW_BEATS[key][0]}>
        <Beat />
      </Sequence>
    ))}
  </AbsoluteFill>
);
