/* Slide-specific scenes. Slides 1, 3 and 5 play the real traffic clip
 * (Mike Bird / Pexels, ordinary highway traffic) and draw NearMiss's actual
 * stored YOLO11n + ByteTrack boxes over it, redrawn for every presented frame
 * from data/real-metrics.js. A freeze shows an exact-frame still decoded with
 * OpenCV from the same file, with that frame's boxes. Slide 4 plays the app's
 * own annotated render. No motion on these slides is scripted.
 * Each scene exposes enter(), step(k), final() and leave(); deck.js calls them. */
(function () {
  const R = window.NEARMISS_REAL;
  const S = window.DECK_SYNC;
  const NS = 'http://www.w3.org/2000/svg';
  const C = {amber: '#F2A93B', coral: '#E5676F', white: '#F5F5F4', muted: '#A8A29E', ink: '#0B0B0C', line: '#27272A', low: '#78716C'};
  const {width: W, height: H, fps: FPS, frames: N, duration_seconds: DURATION} = R.source.frame;
  const reduced = () => window.DECK && window.DECK.reduced;
  const dur = (s) => (reduced() ? 0 : s);
  const $ = (id) => document.getElementById(id);
  const NB = ' '; // keeps a number and its unit on one line

  const el = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };
  const kill = (...targets) => targets.forEach((t) => gsap.killTweensOf(t));

  /* ---------- real clip + synchronized overlay ----------
   * Layers, bottom to top: <video>, exact-frame still <img>, SVG overlay.
   * The video stays rendered under the still so frame callbacks keep firing;
   * the still covers it until the first new frame arrives, and again at a freeze. */
  function realClip(host, view, opts = {}) {
    host.innerHTML = '';
    const {k, left, top} = S.coverView(view, host.clientWidth || opts.width, host.clientHeight || opts.height);
    const px = (n) => n / k; // screen pixels -> source pixels
    const frame = document.createElement('div');
    frame.className = 'real-frame';
    Object.assign(frame.style, {width: `${W * k}px`, height: `${H * k}px`, left: `${left}px`, top: `${top}px`});
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.setAttribute('muted', '');
    video.setAttribute('playsinline', '');
    video.src = R.assets.source;
    const still = document.createElement('img');
    still.className = 'still';
    still.alt = '';
    const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, class: 'real-overlay', role: 'img', 'aria-label': 'Real traffic frame with NearMiss stored track boxes'});
    frame.append(video, still, svg);
    host.appendChild(frame);
    const layer = {all: el('g', {}, svg), trails: el('g', {}, svg), extra: el('g', {}, svg), focus: el('g', {}, svg)};
    const focus = opts.focus || {};
    const thin = {fill: 'none', 'vector-effect': 'non-scaling-stroke'};
    let gen = 0;
    const api = {frame: -1, video, still, svg, px, playing: false};

    const draw = (f) => {
      api.frame = f;
      for (const g of [layer.all, layer.trails, layer.focus]) g.innerHTML = '';
      const rows = S.boxesAt(R, f).map((b) => b.slice());
      // At a measurement frame, the event's stored boxes (a track may reuse its previous row).
      for (const [id, b] of Object.entries((opts.overrideAt || {})[f] || {})) {
        const i = rows.findIndex((r) => r[0] === Number(id));
        if (i >= 0) rows[i] = [Number(id), ...b]; else rows.push([Number(id), ...b]);
      }
      for (const [id, x1, y1, x2, y2] of rows) {
        const color = focus[id];
        if (!color) {
          el('rect', {...thin, x: x1, y: y1, width: x2 - x1, height: y2 - y1, stroke: C.white, 'stroke-opacity': 0.42, 'stroke-width': 1.5}, layer.all);
          continue;
        }
        el('rect', {...thin, x: x1, y: y1, width: x2 - x1, height: y2 - y1, stroke: color, 'stroke-width': 3.5, 'data-track': id}, layer.focus);
        const label = el('text', {x: x1, y: y1 - px(9), fill: color, 'font-family': 'JetBrains Mono', 'font-size': px(20), 'font-weight': 500,
          'paint-order': 'stroke', stroke: C.ink, 'stroke-width': px(5), 'stroke-linejoin': 'round'}, layer.focus);
        label.textContent = `${R.classes[id]} #${id}`;
      }
      if (opts.trailFrames) {
        for (const [id, color] of Object.entries(focus)) {
          const pts = S.trail(R, Number(id), f - opts.trailFrames, f);
          if (pts.length > 1) el('polyline', {...thin, points: pts.map((p) => p.join(',')).join(' '), stroke: color, 'stroke-width': 3, 'stroke-opacity': 0.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'}, layer.trails);
        }
      }
    };
    const coverWith = (f) => {
      const src = R.assets.stills[String(f)];
      if (src) { still.src = src; still.style.visibility = 'visible'; } else still.style.visibility = 'hidden';
    };
    const seek = (f) => { try { video.currentTime = S.timeFor(f, FPS); } catch (e) { /* metadata not loaded yet */ } };

    // Show exactly frame f, paused: its still (if extracted) and its boxes.
    api.show = (f) => {
      gen++;
      api.playing = false;
      video.pause();
      seek(f);
      coverWith(f);
      draw(f);
    };
    // Play [from, to] at `rate`, redrawing boxes for each presented frame, then freeze on `to`.
    api.play = (from, to, rate, done) => {
      api.show(from);
      const my = gen;
      api.playing = true;
      const finish = () => { if (my !== gen) return; api.show(to); done?.(); };
      const start = () => {
        if (my !== gen) return;
        video.playbackRate = rate;
        try { video.currentTime = from / FPS; } catch (e) { /* ignore */ }
        const onFrame = (t) => {
          if (my !== gen) return;
          const f = S.frameAt(t, FPS, N);
          if (f >= to) { finish(); return; }
          if (f !== api.frame) draw(f);
          if (f > from) still.style.visibility = 'hidden';
          next();
        };
        const next = () => (video.requestVideoFrameCallback
          ? video.requestVideoFrameCallback((_now, meta) => onFrame(meta.mediaTime))
          : requestAnimationFrame(() => onFrame(video.currentTime)));
        const playing = video.play();
        if (playing && playing.catch) playing.catch(finish);
        next();
        // Safety net: if the browser never presents frames, still land on the freeze on time.
        setTimeout(() => { if (my === gen) finish(); }, ((to - from) / FPS / rate) * 1000 + 1500);
      };
      if (video.readyState >= 1) start(); else video.addEventListener('loadedmetadata', start, {once: true});
    };
    api.stop = () => { gen++; api.playing = false; video.pause(); };
    api.frozen = (on) => frame.classList.toggle('frozen', on);
    api.line = (from, to, color) => {
      const len = Math.hypot(to[0] - from[0], to[1] - from[1]);
      return el('line', {x1: from[0], y1: from[1], x2: to[0], y2: to[1], stroke: color, 'stroke-width': px(3.5), 'stroke-linecap': 'round', 'stroke-dasharray': len, 'stroke-dashoffset': len}, layer.extra);
    };
    api.ring = (at, color, r) => el('circle', {cx: at[0], cy: at[1], r: px(r), fill: 'none', stroke: color, 'stroke-width': px(3.5)}, layer.extra);
    return api;
  }

  const CASE = R.case;
  const INC = R.case_incident;
  const [IA, IB] = CASE.track_ids;
  const sec = (s, d = 2) => `${s.toFixed(d)}${NB}s`;

  /* 1 · real traffic plays to the case's first alert and freezes */
  const s1 = (() => {
    const M1 = R.moments.slide1;
    let clip;
    const note = () => $('s1-freeze');
    const build = () => { clip = realClip($('s1-scene'), [0, 0, W, H], {focus: {[IA]: C.amber, [IB]: C.amber}, width: 1040, height: 585}); };
    const frozen = (animate) => {
      clip.frozen(true);
      note().innerHTML = `<span class="tag">Frame ${M1.freeze_frame} · ${CASE.first_alert_clock} · first alert</span><br/>` +
        `Experimental ${CASE.severity} flag · car${NB}#${IA} / car${NB}#${IB}<br/>` +
        `<span class="amber">Ordinary traffic. Unverified: a person must check.</span>`;
      gsap.fromTo(note(), {opacity: 0, y: 12}, {opacity: 1, y: 0, duration: dur(animate ? 0.5 : 0), delay: animate ? dur(0.25) : 0});
    };
    return {
      enter() { clip?.stop(); build(); clip.show(M1.from_frame); kill(note()); gsap.set(note(), {opacity: 0}); note().innerHTML = ''; },
      step(k) {
        if (k !== 1) return;
        if (reduced()) { clip.show(M1.freeze_frame); frozen(false); return; }
        clip.play(M1.from_frame, M1.freeze_frame, M1.rate, () => frozen(true));
      },
      final() { clip?.stop(); build(); clip.show(M1.freeze_frame); frozen(false); },
      leave() { clip?.stop(); },
    };
  })();

  /* 2 · token moving through the workflow */
  const s2 = (() => {
    const token = () => $('s2-token');
    return {
      enter() { kill(token()); gsap.set(token(), {left: '0%'}); },
      step(k) {
        if (k !== 1) return;
        kill(token());
        if (reduced()) { gsap.set(token(), {left: '100%'}); return; }
        gsap.fromTo(token(), {left: '0%'}, {left: '100%', duration: 3.2, ease: 'power1.inOut', delay: 0.3});
      },
      final() { kill(token()); gsap.set(token(), {left: '100%'}); },
    };
  })();

  /* 3 · the case's representative measurement frame (not its first alert): both
   * boxes, both projection origins and the ETAs/gap come from that one frame. */
  const s3 = (() => {
    const m = CASE.measurement;
    const M3 = R.moments.slide3;
    const {high_time_gap_seconds: high, medium_time_gap_seconds: med, low_time_gap_seconds: low} = R.pipeline.settings;
    const corners = Object.values(m.boxes).flatMap(([x1, y1, x2, y2]) => [[x1, y1], [x2, y2]]);
    const view = S.fitView([...corners, CASE.conflict_point], 110, 900 / 640, W, H);
    const [ea, eb] = m.eta_seconds;
    const gap = CASE.arrival_gap_seconds;
    let clip, lines = [], ring, placeMarker;
    const counter = {k: 0}, marker = {v: low};
    const buildRuler = () => {
      const r = $('s3-ruler');
      const RW = 720, x = (v) => (v / low) * RW;
      r.innerHTML =
        `<div class="band" style="left:0;width:${x(high)}px;background:${C.coral}"></div>` +
        `<div class="band" style="left:${x(high)}px;width:${x(med) - x(high)}px;background:${C.amber}"></div>` +
        `<div class="band" style="left:${x(med)}px;width:${x(low) - x(med)}px;background:#57534E"></div>` +
        `<div class="lbl" style="left:${x(high) / 2}px">HIGH ≤ ${high.toFixed(2)} s</div>` +
        `<div class="lbl" style="left:${(x(high) + x(med)) / 2}px">MEDIUM ≤ ${med.toFixed(2)} s</div>` +
        `<div class="lbl" style="left:${(x(med) + x(low)) / 2}px">LOW ≤ ${low.toFixed(2)} s</div>` +
        `<div class="marker" id="s3-marker"><span>gap ${gap.toFixed(2)} s</span></div>`;
      return (v) => { $('s3-marker').style.left = `${x(v)}px`; };
    };
    const stale = Object.entries(m.observed_frame).filter(([, f]) => f !== m.frame);
    const writeArrivals = (k) => {
      $('s3-arrivals').innerHTML =
        `car #${IA} reaches the shared point in ${sec(ea * k)}<br/>car #${IB} reaches it in ${sec(eb * k)}<br/>` +
        `<span class="gap">arrival gap ${sec(gap)} → ${CASE.severity}</span>` +
        `<span class="when">Measured on frame${NB}${m.frame} (${m.clock}). First alert frame${NB}${CASE.first_alert_frame} (${CASE.first_alert_clock}).` +
        (stale.length ? ` #${stale.map(([id, f]) => `${id} box from frame${NB}${f}`).join(', ')} (latest observation).` : '') + '</span>';
    };
    const build = () => {
      clip = realClip($('s3-scene'), view, {focus: {[IA]: C.amber, [IB]: C.amber}, trailFrames: Math.round(0.8 * FPS), overrideAt: {[m.frame]: m.boxes}, width: 900, height: 640});
      // Projections from the stored anchors to the stored conflict positions of this frame.
      lines = [IA, IB].map((id) => clip.line(m.positions[id], m.conflict_positions[id], C.amber));
      ring = clip.ring(CASE.conflict_point, C.coral, 16);
      gsap.set(ring, {opacity: 0});
      $('s3-tag').textContent = `Measurement frame ${m.frame} · ${m.clock}`;
      const ex = CASE.explanation;
      $('s3-explain').innerHTML = `<b>${ex.headline}</b><ul>${ex.bullets.slice(1, 3).map((b) => `<li>${b}</li>`).join('')}</ul>`;
      placeMarker = buildRuler();
    };
    const freeze = () => { if (clip.frame !== M3.freeze_frame || clip.playing) clip.show(M3.freeze_frame); };
    return {
      enter() {
        clip?.stop(); build(); kill(counter, marker); writeArrivals(0); placeMarker(low);
        if (reduced()) clip.show(M3.freeze_frame);
        else clip.play(M3.from_frame, M3.freeze_frame, M3.rate);
      },
      step(k) {
        if (k === 1) {
          freeze();
          lines.forEach((l, i) => gsap.to(l, {attr: {'stroke-dashoffset': 0}, duration: dur(1.1), delay: dur(0.2 + i * 0.15), ease: 'power2.inOut'}));
          gsap.to(ring, {opacity: 1, duration: dur(0.4), delay: dur(1.2)});
        }
        if (k === 2) { counter.k = 0; gsap.to(counter, {k: 1, duration: dur(1.2), ease: 'power2.out', onUpdate: () => writeArrivals(counter.k), onComplete: () => writeArrivals(1)}); }
        if (k === 3) { marker.v = low; gsap.to(marker, {v: gap, duration: dur(1.4), ease: 'power3.inOut', onUpdate: () => placeMarker(marker.v), onComplete: () => placeMarker(gap)}); }
      },
      final() {
        clip?.stop(); build(); clip.show(M3.freeze_frame);
        lines.forEach((l) => l.setAttribute('stroke-dashoffset', 0));
        gsap.set(ring, {opacity: 1});
        writeArrivals(1); placeMarker(gap);
      },
      leave() { clip?.stop(); },
    };
  })();

  /* 4 · the app's annotated render of the real clip, then an actual Investigation capture */
  const s4 = (() => {
    const video = () => $('s4-video');
    const sevColor = (s) => (s === 'HIGH' ? C.coral : s === 'MEDIUM' ? C.amber : C.low);
    const markers = [
      ...R.events.map((e) => ({time: e.first_alert_seconds, color: sevColor(e.severity), title: `${e.first_alert_clock} ${e.severity} ${e.event_id}`})),
      ...R.incidents.map((i) => ({time: i.first_contact_seconds, color: C.coral, contact: true, title: `${i.first_contact_clock} suspected contact`})),
    ];
    const cap = R.capture_event;
    const cards = [
      {time: cap.first_alert_seconds, clock: cap.first_alert_clock, tag: cap.severity, color: sevColor(cap.severity),
        title: `${cap.pattern_label} · car #${cap.track_ids.join(' / car #')}`, detail: 'Opened in Investigation below (frame 34)'},
      {time: CASE.first_alert_seconds, clock: CASE.first_alert_clock, tag: CASE.severity, color: sevColor(CASE.severity),
        title: `${CASE.pattern_label} · car #${IA} / car #${IB}`, detail: `arrival gap ${sec(CASE.arrival_gap_seconds)} · slide 3`},
      {time: INC.first_contact_seconds, clock: INC.first_contact_clock, tag: 'Contact', color: C.coral,
        title: `Suspected contact · car #${INC.track_ids.join(' / car #')}`, detail: `${INC.evidence_signal_count} signals · unverified · slide 5`},
    ];
    const VIDEO_CAPTION = 'Actual NearMiss annotated render of the real clip (app overlays and credit) · click a marker to jump';
    const INVEST_CAPTION = 'Actual app · Investigation · original frame 34, tracks #20 and #22, stored observations only';
    let built = false;
    const build = () => {
      if (built) return;
      built = true;
      const tl = $('s4-timeline');
      for (const it of markers) {
        const b = document.createElement('button');
        b.style.left = `${(it.time / DURATION) * 100}%`;
        b.style.borderColor = it.color;
        if (it.contact) b.className = 'contact';
        b.title = it.title;
        b.addEventListener('click', (ev) => { ev.stopPropagation(); seek(it.time); });
        tl.appendChild(b);
      }
      const c = R.counts, bs = c.warnings_by_severity;
      const list = $('s4-events');
      list.innerHTML = `<div class="summary-card"><div><b>${c.warnings}</b> warning candidates <span>${bs.HIGH} HIGH · ${bs.MEDIUM} MEDIUM · ${bs.LOW} LOW</span></div>` +
        `<div><b>${c.suspected_incidents}</b> suspected contacts <span>${c.confirmed} confirmed</span></div>` +
        `<div><b>${c.track_ids}</b> tracker IDs <span>not a vehicle count</span></div></div>`;
      for (const it of cards) {
        const card = document.createElement('div');
        card.className = 'event-card';
        card.style.borderLeftColor = it.color;
        card.innerHTML = `<div class="row"><span>${it.clock}</span><span class="tag" style="border-color:${it.color};color:${it.color};font-size:14px;padding:2px 8px">${it.tag}</span></div><div class="t">${it.title}</div><div class="d">${it.detail}</div>`;
        card.addEventListener('click', (ev) => { ev.stopPropagation(); seek(it.time); });
        list.appendChild(card);
        it.node = card;
      }
      const v = video();
      const update = () => {
        $('s4-fill').style.width = `${(v.currentTime / DURATION) * 100}%`;
        for (const it of cards) it.node.style.opacity = v.currentTime + 0.05 >= it.time ? 1 : 0.4;
      };
      v.addEventListener('timeupdate', update);
      v.addEventListener('seeked', update);
      $('s4-note').innerHTML = `Investigation redraws the stored boxes on the original frame; nothing is re-detected. Shown: frame${NB}34 for cars #20 and #22, whose ${cap.severity} flag first fired on frame${NB}${cap.first_alert_frame}.`;
      // Highlight the "Original frame 34 with stored observations only" caption (capture pixels 732-1008 x 861-879).
      const k = 1.028, ox = 306, oy = 250, hl = $('s4-hl');
      Object.assign(hl.style, {left: `${(732 - ox) * k - 10}px`, top: `${(861 - oy) * k - 9}px`, width: `${276 * k + 20}px`, height: `${18 * k + 18}px`});
    };
    const seek = (t) => { const v = video(); v.pause(); v.currentTime = Math.max(0, t) + 0.5 / FPS; };
    const caption = (text) => { $('s4-caption').textContent = text; };
    return {
      enter() { build(); seek(CASE.first_alert_seconds); caption(VIDEO_CAPTION); },
      step(k) {
        const v = video();
        if (k === 1) { if (reduced()) seek(CASE.first_alert_seconds); else { v.currentTime = 0; v.play().catch(() => {}); } }
        if (k === 2) {
          v.pause();
          caption(INVEST_CAPTION);
          gsap.fromTo('#s4-hl', {opacity: 0, scale: 1.15}, {opacity: 1, scale: 1, duration: dur(0.5), delay: dur(0.4), ease: 'power3.out'});
        }
      },
      final() { build(); seek(CASE.first_alert_seconds); gsap.set('#s4-hl', {opacity: 1, scale: 1}); caption(INVEST_CAPTION); },
      leave() { video().pause(); },
    };
  })();

  /* 5 · the linked suspected contact, replayed at half speed on the real clip */
  const signalWords = {persistent_bounding_box_contact: 'Persistent box contact', significant_bounding_box_overlap: 'Significant box overlap', previously_converging_trajectories: 'Converging before contact', abrupt_motion_change: 'Abrupt motion change', sudden_deceleration: 'Sudden deceleration', stopped_after_contact: 'Stopped after contact', post_contact_track_loss: 'Track lost after contact'};
  const s5 = (() => {
    const M5 = R.moments.slide5;
    const f0 = M5.freeze_frame;
    const corners = INC.track_ids.flatMap((id) => { const b = S.boxOf(R, f0, id); return b ? [[b[1], b[2]], [b[3], b[4]]] : []; });
    const view = S.fitView([...corners, INC.contact_point], 120, 980 / 640, W, H);
    let clip, ring;
    const contactTag = () => $('s5-contact');
    const build = () => {
      const [a, b] = INC.track_ids;
      clip = realClip($('s5-scene'), view, {focus: {[a]: C.coral, [b]: C.coral}, trailFrames: 12, width: 980, height: 640});
      ring = clip.ring(INC.contact_point, C.coral, 18);
      gsap.set(ring, {opacity: 0});
      $('s5-signals').innerHTML = INC.detection_signals.map((s) => `<li>${signalWords[s] || s.replace(/_/g, ' ')}</li>`).join('') +
        (INC.associated_prediction_event_id ? `<li class="lead">Warning ${INC.associated_prediction_event_id} came ${sec(INC.prediction_lead_seconds)} before first contact. Correlated measurements, not independent votes.</li>` : '');
      const secs = (INC.contact_persistence_frames / FPS).toFixed(1);
      $('s5-read').innerHTML = `<p class="mini-title">Our reading of the frame · not a recorded review</p>` +
        `<p>Box “contact” lasted ${INC.contact_persistence_frames} frames (${secs}${NB}s). #${IB} is the nearer car in the same lane, partly hiding #${IA}: overlap from perspective. It looks like queued traffic, not contact.</p>` +
        `<p class="status">App: ${R.counts.suspected_incidents} candidates Uncertain · ${R.counts.confirmed} confirmed · ${R.counts.notices} notices</p>`;
      contactTag().innerHTML = `<span class="tag solid" style="background:${C.coral};border-color:${C.coral}">First box contact · frame ${f0} · ${INC.first_contact_clock}</span>`;
    };
    const hit = (animate) => {
      clip.frozen(true);
      gsap.fromTo(ring, {opacity: 0}, {opacity: 1, duration: dur(animate ? 0.5 : 0)});
      gsap.to(contactTag(), {opacity: 1, duration: dur(animate ? 0.4 : 0)});
    };
    return {
      enter() {
        clip?.stop(); build(); kill(contactTag()); gsap.set(contactTag(), {opacity: 0});
        if (reduced()) { clip.show(f0); hit(false); return; }
        clip.play(M5.from_frame, f0, M5.rate, () => hit(true));
      },
      step(k) {
        if (k === 1 && !reduced()) gsap.from('#s5-signals li', {opacity: 0, x: 24, duration: 0.4, stagger: 0.15, ease: 'power2.out'});
      },
      final() { clip?.stop(); build(); clip.show(f0); hit(false); },
      leave() { clip?.stop(); },
    };
  })();

  /* 6 · dispatch gate, crossing arithmetic and the actual community brief */
  const s6 = (() => {
    const cr = R.streetlab.crossing;
    const maxS = Math.max(...cr.rows.map((r) => r.current_seconds));
    const BW = 330;
    const md = (s) => s.replace(/\\([\\`*_{}[\]()#+\-.!|>])/g, '$1').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\s*\(https?:[^)]*\)/g, '');
    const briefExcerpt = () => {
      if (!R.brief) return '<p style="color:#E5676F">Host capture pending: community-brief.md</p>';
      const lines = R.brief.split('\n');
      const title = (lines.find((l) => l.startsWith('# ')) || '').replace(/^#\s*/, '');
      const section = (name) => {
        const i = lines.indexOf(`## ${name}`);
        const out = [];
        if (i < 0) return out;
        for (const l of lines.slice(i + 1)) { if (l.startsWith('## ')) break; if (l.startsWith('- ')) out.push(l.slice(2)); }
        return out;
      };
      const head = lines.filter((l) => l.startsWith('- ')).slice(0, 3);
      const credit = head.find((l) => l.startsWith('- Real traffic footage')) || '';
      const summary = section('Evidence summary').filter((l) => /^(Vehicles|Potential|Suspected)/.test(l));
      const bounds = section('Boundaries').slice(0, 2);
      return `<h4>${md(title)}</h4><blockquote>${md(credit.slice(2))}</blockquote><h5>Evidence summary</h5><ul>${summary.map((l) => `<li>${md(l)}</li>`).join('')}</ul>` +
        `<h5>Boundaries</h5><ul>${bounds.map((l) => `<li>${md(l)}</li>`).join('')}</ul>`;
    };
    const build = () => {
      const a = cr.assumptions;
      $('s6-bars').innerHTML = cr.rows.map((r) =>
        `<div class="bar-group"><div class="w">${r.walker} · ${r.speed} ${a.unit}/s</div>` +
        `<div class="bar-row"><div class="b cur" data-w="${(r.current_seconds / maxS) * BW}"></div><span>${r.current_seconds} s now</span></div>` +
        `<div class="bar-row"><div class="b hyp" data-w="${(r.proposed_seconds / maxS) * BW}"></div><span>${r.proposed_seconds} s hypothetical</span></div></div>`).join('') +
        `<div class="assume">Stated assumptions: ${a.current_distance} → ${a.proposed_distance} ${a.unit} crossing · start-up ${a.start_up_seconds} s</div>`;
      $('s6-caveat').textContent = 'Arithmetic on entered assumptions. Not a road-safety measurement or crash reduction.';
      const c = R.counts;
      $('s6-gate').innerHTML = `<div class="gate-flow"><span>Candidate</span><i>→</i><span class="coral">Person confirms</span><i>→</i><span>Local notice</span></div>` +
        `<p>Simulated: nothing leaves the computer.</p>` +
        `<div class="gate-now"><div><b>${c.suspected_incidents}</b>candidates</div><div><b>${c.confirmed}</b>confirmed</div><div><b>${c.notices}</b>notices</div></div>`;
      $('s6-brief').innerHTML = briefExcerpt();
    };
    const bars = () => document.querySelectorAll('#s6-bars .b');
    return {
      enter() { build(); bars().forEach((b) => (b.style.width = '0px')); },
      step(k) { if (k === 1) bars().forEach((b, i) => gsap.to(b, {width: `${b.dataset.w}px`, duration: dur(0.9), delay: dur(0.25 + i * 0.12), ease: 'power3.out'})); },
      final() { build(); bars().forEach((b) => (b.style.width = `${b.dataset.w}px`)); },
    };
  })();

  /* 7 · verified list from the latest extraction run */
  const s7 = (() => {
    const build = () => {
      const t = R.tests;
      const c = R.counts;
      const items = [
        t ? `${t.exit_code === 0 && /^\d+ passed/.test(t.summary) ? `All ${t.summary.match(/^(\d+)/)[1]} automated tests pass` : `pytest: ${t.summary.replace(/ in [\d.]+s.*$/, '')}`} (local, ${t.run_at.slice(0, 10)}). They check code behaviour, not detector accuracy` : 'Automated tests: not recorded for this build',
        `Replay from the cached tracks reproduces the app’s ${c.warnings} warnings and ${c.suspected_incidents} contact candidates exactly`,
        'Clip, tracks and metadata bound by SHA-256 in the app manifest; the deck checks them',
        'Real-footage label and credit carried on frames, pages and exports',
        'Confirm, dismiss and uncertain states covered by tests (SQLite review record)',
      ];
      $('s7-verified').innerHTML = items.map((i) => `<li>${i}</li>`).join('');
      $('s7-unproven').innerHTML = [
        'Accuracy on real footage: not measured. This clip has no ground-truth labels',
        `All ${c.warnings} warnings and ${c.suspected_incidents} contact candidates are unverified; perspective and occlusion cause false alarms`,
        `${c.track_ids} tracker IDs are not a vehicle count`,
        'Image pixels only: no metres, speeds or probabilities',
        'No crash-reduction claim. Dispatch is simulated',
      ].map((i) => `<li>${i}</li>`).join('');
    };
    return {enter: build, step() {}, final: build};
  })();

  const none = {enter() {}, step() {}, final() {}};
  window.DECK_SCENES = {moment: s1, purpose: s2, earned: s3, source: s4, review: s5, followup: s6, verified: s7, pilot: none};
})();
