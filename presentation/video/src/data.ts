// Typed access to the generated data files. Every number on screen comes from
// demo-metrics.json (presentation/scripts/extract_metrics.py), the host
// captures manifest, or the music manifest. Nothing here is typed in by hand.
import capturesJson from './data/captures.json';
import mediaJson from './data/media.json';
import metricsJson from './data/demo-metrics.json';

export type Point = [number, number];

export type EventRow = {
  event_id: string;
  severity: string;
  geometry: string;
  track_ids: number[];
  classes: string[];
  first_alert_seconds: number;
  first_alert_clock: string;
  first_alert_frame: number;
  // The representative row the ETAs, gap and separation were measured on.
  // Not the first alert; diagrams of those numbers must use this frame.
  measurement: {
    seconds: number;
    frame: number;
    clock: string;
    eta_seconds: [number | null, number | null];
    boxes: Record<string, [number, number, number, number]>;
    anchors: Record<string, Point>;
  };
  arrival_gap_seconds: number | null;
  time_to_conflict_seconds: number | null;
  time_headway_seconds: number | null;
  closing_speed_pixels_per_second: number | null;
  conflict_point: number[];
  explanation: {headline: string; pattern_label: string; bullets: string[]; caveat: string};
};

export type IncidentRow = {
  incident_id: string;
  track_ids: number[];
  first_contact_seconds: number;
  first_contact_clock: string;
  evidence_signal_count: number;
  detection_signals: string[];
  contact_persistence_frames: number;
  associated_prediction_event_id: string | null;
  prediction_lead_seconds: number | null;
  contact_point: number[];
};

export type Actor = {
  track_id: number;
  class_name: string;
  size: Point;
  direction: Point;
  color: string;
  sample_step_seconds: number;
  samples: Array<Point | null>;
};

type Metrics = {
  source: {
    label: string;
    data_source: string;
    video_id: string;
    camera_id: string;
    frame: {width: number; height: number; fps: number; frames: number; duration_seconds: number};
    road: {horizontal_y: Point; vertical_x: Point};
  };
  settings: Record<string, number | string>;
  tracks: {rows: number; vehicles: number; pedestrians: number};
  events: EventRow[];
  incidents: IncidentRow[];
  streetlab: {
    warnings_total: number;
    warnings_by_priority: Record<string, number>;
    incidents_total: number;
    crossing: {
      assumptions: {unit: string; current_distance: number; proposed_distance: number; walking_speed: number; slower_walking_speed: number; start_up_seconds: number};
      rows: Array<{walker: string; speed: number; current_seconds: number; proposed_seconds: number; difference_text: string; in_roadway_change_text: string}>;
      boundary: string;
      hypothesis: string;
    };
  };
  actors: Actor[];
  tests: {summary: string; exit_code: number; run_at: string; run_date_local?: string; time_zone?: string} | null;
};

export const metrics = metricsJson as unknown as Metrics;
export const captures = capturesJson as unknown as {
  files: Record<string, {kind: 'image'; width: number; height: number} | {kind: 'markdown'; text: string; bytes: number}>;
  missing: string[];
};
export const media = mediaJson as unknown as {
  music: {file: string; duration: number | null; title: string | null; artist: string | null} | null;
  licenceFiles: string[];
  licenceText: string;
};

export const events = metrics.events;
export const incident = metrics.incidents[0] ?? null;
export const firstEvent = events[0];
export const linkedEvent = incident
  ? events.find((e) => e.event_id === incident.associated_prediction_event_id) ?? null
  : null;

const SIGNAL_WORDS: Record<string, string> = {
  persistent_bounding_box_contact: 'Persistent box contact',
  significant_bounding_box_overlap: 'Significant box overlap',
  previously_converging_trajectories: 'Converging before contact',
  abrupt_motion_change: 'Abrupt motion change',
  sudden_deceleration: 'Sudden deceleration',
  stopped_after_contact: 'Stopped after contact',
  post_contact_track_loss: 'Track lost after contact',
};
export const signalLabel = (key: string) =>
  SIGNAL_WORDS[key] ?? key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

export const geometryLabel = (e: EventRow) => e.explanation.pattern_label;

export const participants = (e: {track_ids: number[]; classes?: string[]}) =>
  e.track_ids.map((id, i) => `${e.classes?.[i] ?? 'vehicle'} #${id}`).join(' / ');

// Projected arrival times from the event's representative measurement row.
export const arrivalTimes = (e: EventRow): [number, number] | null => {
  const [a, b] = e.measurement.eta_seconds;
  return a === null || b === null ? null : [a, b];
};

// "2026-10-25 (America/Los_Angeles)": the local date the suite was run, with its zone named.
export const testDateLabel = (t: NonNullable<Metrics['tests']>): string =>
  t.run_date_local && t.time_zone ? `${t.run_date_local}, ${t.time_zone}` : `${t.run_at.slice(0, 10)} UTC`;

// A viewBox around the given points with padding, widened or heightened to the target aspect.
export const fitView = (pts: Point[], pad: number, aspect: number): [number, number, number, number] => {
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  let x0 = Math.min(...xs) - pad;
  let x1 = Math.max(...xs) + pad;
  let y0 = Math.min(...ys) - pad;
  let y1 = Math.max(...ys) + pad;
  const w = x1 - x0;
  const h = y1 - y0;
  if (w / h < aspect) {
    const grow = (h * aspect - w) / 2;
    x0 -= grow;
    x1 += grow;
  } else {
    const grow = (w / aspect - h) / 2;
    y0 -= grow;
    y1 += grow;
  }
  return [x0, y0, x1 - x0, y1 - y0];
};

export const frameIndexAt = (seconds: number) => Math.round(seconds * metrics.source.frame.fps);

export const actorById = (id: number) => metrics.actors.find((a) => a.track_id === id)!;

// Linear interpolation between the 0.05 s scripted samples.
export const actorAt = (actor: Actor, t: number): Point | null => {
  const step = actor.sample_step_seconds;
  const i = Math.floor(t / step);
  const a = actor.samples[Math.max(0, Math.min(i, actor.samples.length - 1))];
  const b = actor.samples[Math.max(0, Math.min(i + 1, actor.samples.length - 1))];
  if (!a) return null;
  if (!b) return a;
  const k = t / step - i;
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
};

export const actorTrail = (actor: Actor, t0: number, t1: number): Point[] => {
  const pts: Point[] = [];
  const step = actor.sample_step_seconds;
  for (let t = t0; t <= t1 + 1e-9; t += step) {
    const p = actorAt(actor, t);
    if (p) pts.push(p);
  }
  const end = actorAt(actor, t1);
  if (end) pts.push(end);
  return pts;
};

export const hasCapture = (name: string) => Boolean(captures.files[name]);
export const briefText = (): string | null => {
  const f = captures.files['brief.md'];
  return f && f.kind === 'markdown' ? f.text : null;
};

// The credit line is taken verbatim from the host's music LICENSE.txt.
const requiredCredit = media.licenceText.match(/^Required credit:\s*(.+)$/m)?.[1]?.trim() ?? null;
export const MUSIC_CREDIT = media.music
  ? requiredCredit ?? `${media.music.title ?? 'Music'}${media.music.artist ? ` by ${media.music.artist}` : ''} (licence file not supplied)`
  : null;
