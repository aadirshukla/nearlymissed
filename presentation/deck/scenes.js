/* Slide-specific animated scenes. The intersection geometry mirrors
 * nearmiss/demo.py and road users move along the scripted samples in
 * data/demo-metrics.js, so every diagram replays the demo the detectors saw.
 * Each scene exposes enter(), step(k), final(); deck.js calls them. */
(function () {
  const M = window.NEARMISS_METRICS;
  const NS = 'http://www.w3.org/2000/svg';
  const C = {amber: '#F2A93B', coral: '#E5676F', white: '#F5F5F4', muted: '#A8A29E', ink: '#0B0B0C', line: '#27272A'};
  const reduced = () => window.DECK && window.DECK.reduced;
  const dur = (s) => (reduced() ? 0 : s);

  const el = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };
  const actor = (id) => M.actors.find((a) => a.track_id === id);
  const actorAt = (a, t) => {
    const step = a.sample_step_seconds;
    const i = Math.floor(t / step);
    const clampI = (j) => Math.max(0, Math.min(j, a.samples.length - 1));
    const p = a.samples[clampI(i)];
    const q = a.samples[clampI(i + 1)];
    if (!p) return null;
    if (!q) return p;
    const k = t / step - i;
    return [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k];
  };
  const clock = (s) => `00:${s < 10 ? '0' : ''}${s.toFixed(2)}`;
  const NB = '\u00a0'; // keeps a number and its unit on one line
  // Smallest view of the demo frame that holds every point plus padding, at the host's aspect ratio.
  const fitView = (pts, pad, aspect) => {
    const W = M.source.frame.width, H = M.source.frame.height;
    let x0 = Math.min(...pts.map((p) => p[0])) - pad, x1 = Math.max(...pts.map((p) => p[0])) + pad;
    let y0 = Math.min(...pts.map((p) => p[1])) - pad, y1 = Math.max(...pts.map((p) => p[1])) + pad;
    if ((x1 - x0) / (y1 - y0) < aspect) { const g = ((y1 - y0) * aspect - (x1 - x0)) / 2; x0 -= g; x1 += g; }
    else { const g = ((x1 - x0) / aspect - (y1 - y0)) / 2; y0 -= g; y1 += g; }
    const w = x1 - x0, h = y1 - y0;
    // Keep the view on the drawn frame when it fits, so no empty margin shows.
    if (w <= W) x0 = Math.max(0, Math.min(x0, W - w));
    if (h <= H) y0 = Math.max(0, Math.min(y0, H - h));
    return [x0, y0, w, h];
  };

  function intersection(host, view, highlight, trailFrom) {
    host.innerHTML = '';
    const [h0, h1] = M.source.road.horizontal_y;
    const [v0, v1] = M.source.road.vertical_x;
    const W = M.source.frame.width, H = M.source.frame.height;
    const cy = (h0 + h1) / 2, cx = (v0 + v1) / 2;
    const unit = view[2] / 960;
    const svg = el('svg', {viewBox: view.join(' '), preserveAspectRatio: 'xMidYMid slice', role: 'img', 'aria-label': 'Synthetic demo intersection diagram'}, host);
    el('rect', {x: 0, y: 0, width: W, height: H, fill: '#1B1E1A'}, svg);
    for (const [x1, y1, x2, y2] of [[30, 24, 330, 150], [630, 24, 930, 150], [30, 390, 330, 516], [630, 390, 930, 516]]) {
      el('rect', {x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: '#24271F', stroke: '#3A3E39'}, svg);
    }
    el('rect', {x: 0, y: h0 - 22, width: W, height: h1 - h0 + 44, fill: '#47453F'}, svg);
    el('rect', {x: v0 - 22, y: 0, width: v1 - v0 + 44, height: H, fill: '#47453F'}, svg);
    el('rect', {x: 0, y: h0, width: W, height: h1 - h0, fill: '#28292B'}, svg);
    el('rect', {x: v0, y: 0, width: v1 - v0, height: H, fill: '#28292B'}, svg);
    for (const o of [-3, 3]) {
      const g = el('g', {stroke: '#D79628', 'stroke-width': 2}, svg);
      el('line', {x1: 0, y1: cy + o, x2: v0 - 46, y2: cy + o}, g);
      el('line', {x1: v1 + 46, y1: cy + o, x2: W, y2: cy + o}, g);
      el('line', {x1: cx + o, y1: 0, x2: cx + o, y2: h0 - 46}, g);
      el('line', {x1: cx + o, y1: h1 + 46, x2: cx + o, y2: H}, g);
    }
    const stripes = el('g', {fill: '#CDCDC8'}, svg);
    for (let y = h0 + 6; y < h1 - 4; y += 16) {
      el('rect', {x: v0 - 40, y, width: 28, height: 8}, stripes);
      el('rect', {x: v1 + 12, y, width: 28, height: 8}, stripes);
    }
    for (let x = v0 + 6; x < v1 - 4; x += 16) {
      el('rect', {x, y: h0 - 40, width: 8, height: 28}, stripes);
      el('rect', {x, y: h1 + 12, width: 8, height: 28}, stripes);
    }
    const bars = el('g', {stroke: '#CDCDC8', 'stroke-width': 3}, svg);
    el('line', {x1: v0 - 46, y1: cy + 6, x2: v0 - 46, y2: h1}, bars);
    el('line', {x1: v1 + 46, y1: h0, x2: v1 + 46, y2: cy - 6}, bars);
    el('line', {x1: v0, y1: h0 - 46, x2: cx - 6, y2: h0 - 46}, bars);
    el('line', {x1: cx + 6, y1: h1 + 46, x2: v1, y2: h1 + 46}, bars);

    const trails = el('g', {}, svg);
    const overlay = el('g', {}, svg);
    const actorsLayer = el('g', {}, svg);
    const nodes = M.actors.map((a) => {
      const g = el('g', {}, actorsLayer);
      const accent = highlight[a.track_id];
      let body;
      if (a.class_name === 'person') body = el('circle', {r: 6, fill: '#E6E6E6'}, g);
      else {
        body = el('rect', {width: a.size[0], height: a.size[1], rx: 3, fill: a.color, stroke: '#151515'}, g);
        if (accent) {
          el('rect', {x: -5, y: -5, width: a.size[0] + 10, height: a.size[1] + 10, rx: 4, fill: 'none', stroke: accent, 'stroke-width': 3 * unit}, g);
          const label = el('text', {x: a.size[0] + 8, y: -6, fill: accent, 'font-family': 'JetBrains Mono', 'font-size': 18 * unit, 'font-weight': 500}, g);
          label.textContent = `#${a.track_id}`;
        }
      }
      const trail = accent ? el('polyline', {fill: 'none', stroke: accent, 'stroke-width': 3 * unit, 'stroke-opacity': 0.75, 'stroke-linecap': 'round'}, trails) : null;
      return {a, g, body, trail};
    });
    const api = {
      svg, overlay, unit, t: 0,
      setTime(t) {
        api.t = t;
        for (const n of nodes) {
          const p = actorAt(n.a, t);
          if (!p) { n.g.setAttribute('visibility', 'hidden'); continue; }
          n.g.setAttribute('visibility', 'visible');
          if (n.a.class_name === 'person') n.g.setAttribute('transform', `translate(${p[0]},${p[1]})`);
          else n.g.setAttribute('transform', `translate(${p[0] - n.a.size[0] / 2},${p[1] - n.a.size[1] / 2})`);
          if (n.trail && trailFrom !== undefined) {
            const pts = [];
            for (let s = trailFrom; s <= t; s += n.a.sample_step_seconds) { const q = actorAt(n.a, s); if (q) pts.push(q.join(',')); }
            pts.push(p.join(','));
            n.trail.setAttribute('points', pts.join(' '));
          }
        }
      },
      ring(at, color) { return el('circle', {cx: at[0], cy: at[1], r: 0, fill: 'none', stroke: color, 'stroke-width': 3 * unit}, overlay); },
      dashed(from, to, color) {
        const len = Math.hypot(to[0] - from[0], to[1] - from[1]);
        const line = el('line', {x1: from[0], y1: from[1], x2: to[0], y2: to[1], stroke: color, 'stroke-width': 3 * unit, 'stroke-linecap': 'round', 'stroke-dasharray': `${len}`, 'stroke-dashoffset': `${len}`}, overlay);
        line.dataset.len = len;
        return line;
      },
    };
    return api;
  }

  const kill = (...targets) => targets.forEach((t) => gsap.killTweensOf(t));

  /* 1 · near miss replay and freeze */
  const e1 = M.events[0];
  const s1 = (() => {
    const START = 1.6, FREEZE = 3.45;
    const [ida, idb] = e1.track_ids;
    let scene, ring, proxy = {t: START};
    const note = () => document.getElementById('s1-freeze');
    const freezeText = () => {
      note().innerHTML = `<span class="tag">Frame ${String(Math.round(FREEZE * M.source.frame.fps)).padStart(3, '0')} · ${clock(FREEZE)}</span><br/>car #${idb} brakes and stops short. No contact.<br/><span style="color:${C.amber}">The warning came first: ${e1.first_alert_clock} · ${e1.severity}<br/>arrival gap ${e1.arrival_gap_seconds.toFixed(2)}${NB}s, measured at ${e1.measurement.clock}</span>`;
    };
    const build = () => {
      scene = intersection(document.getElementById('s1-scene'), [0, 0, 960, 540], {[ida]: C.amber, [idb]: C.amber}, START);
      ring = scene.ring(e1.conflict_point, C.coral);
    };
    const frozen = (animate) => {
      freezeText();
      gsap.to(scene.svg, {filter: 'saturate(0.35)', duration: dur(animate ? 0.4 : 0)});
      gsap.fromTo(ring, {attr: {r: 60}, opacity: 0}, {attr: {r: 26}, opacity: 1, duration: dur(animate ? 0.5 : 0), ease: 'power3.out'});
      gsap.fromTo(note(), {opacity: 0, y: 12}, {opacity: 1, y: 0, duration: dur(animate ? 0.5 : 0), delay: animate ? dur(0.3) : 0});
    };
    return {
      enter() {
        build(); kill(proxy); proxy.t = START; scene.setTime(START);
        gsap.set(ring, {opacity: 0}); gsap.set(note(), {opacity: 0}); note().innerHTML = '';
      },
      step(k) {
        if (k !== 1) return;
        kill(proxy); proxy.t = START;
        if (reduced()) { proxy.t = FREEZE; scene.setTime(FREEZE); frozen(false); return; }
        gsap.to(proxy, {t: FREEZE, duration: FREEZE - START, ease: 'none', delay: 0.35, onUpdate: () => scene.setTime(proxy.t), onComplete: () => frozen(true)});
      },
      final() { build(); kill(proxy); proxy.t = FREEZE; scene.setTime(FREEZE); frozen(false); },
    };
  })();

  /* 2 · token moving through the workflow */
  const s2 = (() => {
    const token = () => document.getElementById('s2-token');
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

  /* 3 · projections, arrival times, threshold ruler. Everything here is the event's
   * representative measurement row (not the first alert): both road users, both
   * projection origins and the ETAs/gap come from that one frame. */
  const arrivals = (() => {
    const [ea, eb] = e1.measurement.eta_seconds;
    if (ea != null && eb != null) return [ea, eb];
    for (const b of e1.explanation.bullets) {
      const m = b.match(/reach it in ([\d.]+)s and .*? in ([\d.]+)s/);
      if (m) return [Number(m[1]), Number(m[2])];
    }
    return null;
  })();
  const s3 = (() => {
    const [ida, idb] = e1.track_ids;
    const high = M.settings.high_time_gap_seconds, med = M.settings.medium_time_gap_seconds, low = M.settings.low_time_gap_seconds;
    let scene, lines = [], ring, counter = {k: 0}, marker = {v: low};
    const buildRuler = () => {
      const r = document.getElementById('s3-ruler');
      const W = 720, x = (v) => (v / low) * W;
      r.innerHTML =
        `<div class="band" style="left:0;width:${x(high)}px;background:${C.coral}"></div>` +
        `<div class="band" style="left:${x(high)}px;width:${x(med) - x(high)}px;background:${C.amber}"></div>` +
        `<div class="band" style="left:${x(med)}px;width:${x(low) - x(med)}px;background:#57534E"></div>` +
        `<div class="lbl" style="left:${x(high) / 2}px">HIGH ≤ ${high.toFixed(2)} s</div>` +
        `<div class="lbl" style="left:${(x(high) + x(med)) / 2}px">MEDIUM ≤ ${med.toFixed(2)} s</div>` +
        `<div class="lbl" style="left:${(x(med) + x(low)) / 2}px">LOW ≤ ${low.toFixed(2)} s</div>` +
        `<div class="marker" id="s3-marker"><span>gap ${e1.arrival_gap_seconds.toFixed(2)} s</span></div>`;
      return (v) => { document.getElementById('s3-marker').style.left = `${x(v)}px`; };
    };
    let placeMarker;
    const writeArrivals = (k) => {
      const box = document.getElementById('s3-arrivals');
      if (!arrivals) { box.textContent = e1.explanation.bullets[0]; return; }
      const m = e1.measurement;
      box.innerHTML = `car #${ida} reaches the shared point in ${(arrivals[0] * k).toFixed(2)}${NB}s<br/>car #${idb} reaches it in ${(arrivals[1] * k).toFixed(2)}${NB}s<br/><span class="gap">arrival gap ${e1.arrival_gap_seconds.toFixed(2)}${NB}s → ${e1.severity}</span>` +
        `<span class="when">Measured at ${m.clock} (frame${NB}${m.frame}). First alert ${e1.first_alert_clock} (frame${NB}${e1.first_alert_frame}).</span>`;
    };
    const build = () => {
      const m = e1.measurement;
      const t = m.seconds;
      // Both whole boxes, their labels and the conflict point stay inside the 900x640 panel.
      const corners = Object.values(m.boxes).flatMap(([x1, y1, x2, y2]) => [[x1, y1], [x2, y2]]);
      scene = intersection(document.getElementById('s3-scene'), fitView([...corners, e1.conflict_point], 56, 900 / 640), {[ida]: C.amber, [idb]: C.amber}, t - 0.8);
      scene.setTime(t);
      // Projections start at the stored bottom-centre anchors the detector used.
      lines = [scene.dashed(m.anchors[String(ida)], e1.conflict_point, C.amber),
               scene.dashed(m.anchors[String(idb)], e1.conflict_point, C.amber)];
      ring = scene.ring(e1.conflict_point, C.coral);
      gsap.set(ring, {attr: {r: 12}, opacity: 0});
      document.getElementById('s3-tag').textContent = `Diagram · measurement frame ${m.frame} · ${m.clock}`;
      placeMarker = buildRuler();
    };
    return {
      enter() { build(); kill(counter, marker); writeArrivals(0); placeMarker(low); },
      step(k) {
        if (k === 1) {
          lines.forEach((l, i) => gsap.to(l, {attr: {'stroke-dashoffset': 0}, duration: dur(1.1), delay: dur(0.2 + i * 0.15), ease: 'power2.inOut'}));
          gsap.to(ring, {opacity: 1, duration: dur(0.4), delay: dur(1.2)});
        }
        if (k === 2) { counter.k = 0; gsap.to(counter, {k: 1, duration: dur(1.2), ease: 'power2.out', onUpdate: () => writeArrivals(counter.k), onComplete: () => writeArrivals(1)}); }
        if (k === 3) { marker.v = low; gsap.to(marker, {v: e1.arrival_gap_seconds, duration: dur(1.4), ease: 'power3.inOut', onUpdate: () => placeMarker(marker.v), onComplete: () => placeMarker(e1.arrival_gap_seconds)}); }
      },
      final() {
        build();
        lines.forEach((l) => l.setAttribute('stroke-dashoffset', 0));
        gsap.set(ring, {opacity: 1});
        writeArrivals(1); placeMarker(e1.arrival_gap_seconds);
      },
    };
  })();

  /* 4 · annotated clip with event timeline, then the Investigation frame */
  const s4 = (() => {
    const video = () => document.getElementById('s4-video');
    const duration = M.source.frame.duration_seconds;
    const items = [
      ...M.events.map((e) => ({time: e.first_alert_seconds, clock: e.first_alert_clock, tag: e.severity, color: e.severity === 'HIGH' ? C.coral : C.amber,
        title: `${e.explanation.pattern_label} · ${e.track_ids.map((id, i) => `${e.classes[i]} #${id}`).join(' / ')}`,
        detail: e.geometry === 'same_direction_following' && e.time_headway_seconds != null ? `time headway ${e.time_headway_seconds.toFixed(2)} s` : `arrival gap ${e.arrival_gap_seconds.toFixed(2)} s`})),
      ...M.incidents.map((i) => ({time: i.first_contact_seconds, clock: i.first_contact_clock, tag: 'Contact', color: C.coral,
        title: `Suspected contact · vehicles #${i.track_ids.join(' / #')}`, detail: `${i.evidence_signal_count} supporting signals · needs review`})),
    ].sort((a, b) => a.time - b.time);
    let built = false;
    const build = () => {
      if (built) return;
      built = true;
      const tl = document.getElementById('s4-timeline');
      const list = document.getElementById('s4-events');
      for (const it of items) {
        const b = document.createElement('button');
        b.style.left = `${(it.time / duration) * 100}%`;
        b.style.borderColor = it.color;
        b.title = `${it.clock} ${it.tag}`;
        b.addEventListener('click', (ev) => { ev.stopPropagation(); seek(it.time); });
        tl.appendChild(b);
        const card = document.createElement('div');
        card.className = 'event-card';
        card.style.borderLeftColor = it.color;
        card.innerHTML = `<div class="row"><span>${it.clock}</span><span class="tag" style="border-color:${it.color};color:${it.color};font-size:14px;padding:2px 8px">${it.tag}</span></div><div class="t">${it.title}</div><div class="d">${it.detail}</div>`;
        card.addEventListener('click', (ev) => { ev.stopPropagation(); seek(it.time); });
        list.appendChild(card);
      }
      const v = video();
      const update = () => {
        document.getElementById('s4-fill').style.width = `${(v.currentTime / duration) * 100}%`;
        [...list.children].forEach((c, i) => { c.style.opacity = v.currentTime + 0.05 >= items[i].time ? 1 : 0.35; });
      };
      v.addEventListener('timeupdate', update);
      v.addEventListener('seeked', update);
      const fps = M.source.frame.fps;
      document.getElementById('s4-note').innerHTML = `Jump to evidence opens frame ${Math.round(e1.first_alert_seconds * fps)} (${e1.first_alert_clock}), the first alert, with tracks #${e1.track_ids.join(' and #')} selected. Boxes are stored observations; nothing is re-detected.`;
      // Highlight the "Original frame N with stored observations only" caption (capture-pixel coordinates).
      const s = 1616 / 1600, hl = document.getElementById('s4-hl');
      Object.assign(hl.style, {left: `${(815 - 432) * s - 8}px`, top: `${586 * s - 8}px`, width: `${380 * s + 16}px`, height: `${18 * s + 16}px`});
    };
    const seek = (t) => { const v = video(); v.pause(); v.currentTime = Math.max(0, t); };
    return {
      enter() { build(); seek(e1.first_alert_seconds); document.getElementById('s4-caption').textContent = 'Actual NearMiss annotated render of the synthetic demo · click a marker to jump'; },
      step(k) {
        const v = video();
        if (k === 1) { v.currentTime = 0; if (!reduced()) v.play().catch(() => {}); else seek(e1.first_alert_seconds); }
        if (k === 2) {
          v.pause();
          document.getElementById('s4-caption').textContent = 'Actual app · Investigation · frame view with stored observations';
          gsap.fromTo('#s4-hl', {opacity: 0, scale: 1.15}, {opacity: 1, scale: 1, duration: dur(0.5), delay: dur(0.4), ease: 'power3.out'});
        }
      },
      final() { build(); seek(e1.first_alert_seconds); gsap.set('#s4-hl', {opacity: 1, scale: 1}); document.getElementById('s4-caption').textContent = 'Actual app · Investigation · frame view with stored observations'; },
      leave() { video().pause(); },
    };
  })();

  /* 5 · contact replay at half speed + signals */
  const inc = M.incidents[0];
  const signalWords = {persistent_bounding_box_contact: 'Persistent box contact', significant_bounding_box_overlap: 'Significant box overlap', previously_converging_trajectories: 'Converging before contact', abrupt_motion_change: 'Abrupt motion change', sudden_deceleration: 'Sudden deceleration', stopped_after_contact: 'Stopped after contact', post_contact_track_loss: 'Track lost after contact'};
  const s5 = (() => {
    let scene, ring, proxy = {t: 0};
    const contactTag = () => document.getElementById('s5-contact');
    const build = () => {
      if (!inc) { document.getElementById('s5-scene').textContent = 'No suspected incident in this run.'; return false; }
      const [a, b] = inc.track_ids;
      scene = intersection(document.getElementById('s5-scene'), [300, 110, 290, 187], {[a]: C.coral, [b]: C.coral}, inc.first_contact_seconds - 1.4);
      ring = scene.ring(inc.contact_point, C.coral);
      gsap.set(ring, {opacity: 0});
      const list = document.getElementById('s5-signals');
      list.innerHTML = inc.detection_signals.map((s) => `<li>${signalWords[s] || s.replace(/_/g, ' ')}</li>`).join('');
      const linked = M.events.find((e) => e.event_id === inc.associated_prediction_event_id);
      if (linked) list.innerHTML += `<li class="lead">Prediction ${linked.event_id} came ${inc.prediction_lead_seconds.toFixed(2)} s before first contact, but does not decide this. Correlated measurements, not independent votes.</li>`;
      contactTag().innerHTML = `<span class="tag solid" style="background:${C.coral};border-color:${C.coral}">First contact ${inc.first_contact_clock}</span>`;
      return true;
    };
    const hit = (animate) => {
      gsap.fromTo(ring, {attr: {r: 40}, opacity: 0}, {attr: {r: 16}, opacity: 1, duration: dur(animate ? 0.5 : 0)});
      gsap.to(contactTag(), {opacity: 1, duration: dur(animate ? 0.4 : 0)});
    };
    return {
      enter() {
        if (!build()) return;
        kill(proxy);
        const t1 = inc.first_contact_seconds, t0 = t1 - 0.8;
        proxy.t = t0; scene.setTime(t0); gsap.set(contactTag(), {opacity: 0});
        if (reduced()) { proxy.t = t1; scene.setTime(t1); hit(false); return; }
        gsap.to(proxy, {t: t1, duration: 1.6, delay: 0.6, ease: 'none', onUpdate: () => scene.setTime(proxy.t), onComplete: () => hit(true)});
      },
      step(k) {
        if (k === 1 && !reduced()) gsap.from('#s5-signals li', {opacity: 0, x: 24, duration: 0.4, stagger: 0.18, ease: 'power2.out'});
      },
      final() { if (!build()) return; kill(proxy); scene.setTime(inc.first_contact_seconds); hit(false); },
    };
  })();

  /* 6 · crossing bars + brief excerpt */
  const s6 = (() => {
    const cr = M.streetlab.crossing;
    const maxS = Math.max(...cr.rows.map((r) => r.current_seconds));
    const W = 330;
    const md = (s) => s.replace(/\\([\\`*_{}[\]()#+\-.!|>])/g, '$1').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    const briefExcerpt = () => {
      const text = window.NEARMISS_BRIEF;
      if (!text) return '<p style="color:#E5676F">Host capture pending: brief.md</p>';
      const lines = text.split('\n');
      const title = (lines.find((l) => l.startsWith('# ')) || '').replace(/^#\s*/, '');
      const quote = (lines.find((l) => l.startsWith('>')) || '').replace(/^>\s*/, '');
      const section = (name) => {
        const out = [];
        const i = lines.indexOf(`## ${name}`);
        if (i < 0) return out;
        for (const l of lines.slice(i + 1)) { if (l.startsWith('## ')) break; if (l.trim()) out.push(l); }
        return out;
      };
      const para = (name) => section(name).find((l) => !l.startsWith('-') && !l.startsWith('|') && !l.startsWith('>')) || '';
      const bullets = section('What this brief does not claim').filter((l) => l.startsWith('- ')).slice(0, 3);
      return `<h4>${md(title)}</h4><blockquote>${md(quote)}</blockquote><h5>Human review</h5><p>${md(para('Human review'))}</p><h5>Simulated dispatch</h5><p>${md(para('Simulated dispatch'))}</p><h5>What this brief does not claim</h5><ul>${bullets.map((b) => `<li>${md(b.slice(2))}</li>`).join('')}</ul>`;
    };
    const build = () => {
      const a = cr.assumptions;
      document.getElementById('s6-bars').innerHTML = cr.rows.map((r) =>
        `<div class="bar-group"><div class="w">${r.walker} · ${r.speed} ${a.unit}/s</div>` +
        `<div class="bar-row"><div class="b cur" data-w="${(r.current_seconds / maxS) * W}"></div><span>${r.current_seconds} s now</span></div>` +
        `<div class="bar-row"><div class="b hyp" data-w="${(r.proposed_seconds / maxS) * W}"></div><span>${r.proposed_seconds} s hypothetical</span></div></div>`).join('') +
        `<div style="font:18px 'JetBrains Mono';color:#A8A29E">${a.current_distance} → ${a.proposed_distance} ${a.unit} crossing · start-up ${a.start_up_seconds} s · placeholder assumptions</div>`;
      document.getElementById('s6-caveat').textContent = 'Arithmetic on entered assumptions. Not a measured crash reduction.';
      document.getElementById('s6-brief').innerHTML = briefExcerpt();
    };
    const bars = () => document.querySelectorAll('#s6-bars .b');
    return {
      enter() { build(); bars().forEach((b) => (b.style.width = '0px')); },
      step(k) { if (k === 1) bars().forEach((b, i) => gsap.to(b, {width: `${b.dataset.w}px`, duration: dur(0.9), delay: dur(0.25 + i * 0.12), ease: 'power3.out'})); },
      final() { build(); bars().forEach((b) => (b.style.width = `${b.dataset.w}px`)); },
    };
  })();

  /* 7 · verified list from the latest metrics run */
  const s7 = (() => {
    const build = () => {
      const t = M.tests;
      const items = [
        t ? `Automated tests: ${t.summary.replace(/ in [\d.]+s$/, '')} (local pytest, ${t.run_at.slice(0, 10)})` : 'Automated tests: not recorded for this build',
        `Deterministic demo: ID ${M.source.video_id}; ${M.events.length} warnings and ${M.incidents.length} suspected incident every run at default settings`,
        'Annotated clip regenerated for this deck matches the app’s cached render byte for byte',
        'Synthetic label carried through frames, pages and exports',
        'Confirm, dismiss and acknowledge states covered by the tests (SQLite review record)',
      ];
      document.getElementById('s7-verified').innerHTML = items.map((i) => `<li>${i}</li>`).join('');
    };
    return {enter: build, step() {}, final: build};
  })();

  const none = {enter() {}, step() {}, final() {}};
  window.DECK_SCENES = {moment: s1, purpose: s2, earned: s3, source: s4, review: s5, followup: s6, verified: s7, pilot: none};
})();
