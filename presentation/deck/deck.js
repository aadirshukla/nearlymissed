/* NearMiss deck engine: scaling, step reveals, keyboard navigation, elapsed
 * timer, presenter notes, 180 s auto-rehearsal, reduced motion and print. */
(function () {
  const params = new URLSearchParams(location.search);
  const slides = [...document.querySelectorAll('.slide')];
  const scenes = window.DECK_SCENES;
  const notes = window.NEARMISS_NOTES(window.NEARMISS_METRICS);
  const plan = slides.map((s) => ({id: s.dataset.id, seconds: Number(s.dataset.seconds), steps: Number(s.dataset.steps || 0), speaker: s.dataset.speaker, title: s.querySelector('.kicker')?.textContent.trim() || s.dataset.id}));
  const TOTAL = plan.reduce((a, p) => a + p.seconds, 0); // 180
  const startOf = (i) => plan.slice(0, i).reduce((a, p) => a + p.seconds, 0);
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const DECK = (window.DECK = {reduced: motionQuery.matches || params.has('reduced'), index: 0, step: 0});
  DECK.elapsed = () => timer.elapsed(); // read by tools/engine.test.mjs
  motionQuery.addEventListener?.('change', (e) => { DECK.reduced = e.matches; hud(); });

  /* ---------- scaling ---------- */
  const stage = document.getElementById('stage');
  const fit = () => {
    if (document.body.classList.contains('print-mode')) return;
    const k = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    stage.style.transform = `scale(${k})`;
  };
  window.addEventListener('resize', fit);

  /* ---------- reveals ---------- */
  const stepEls = (slide) => [...slide.querySelectorAll('[data-step]')];
  const setReveals = (slide, step, animate) => {
    for (const node of stepEls(slide)) {
      const k = Number(node.dataset.step);
      gsap.killTweensOf(node);
      if (k <= step) {
        if (animate && k === step && !DECK.reduced) gsap.fromTo(node, {opacity: 0, y: 26}, {opacity: 1, y: 0, duration: 0.6, ease: 'power3.out'});
        else gsap.set(node, {opacity: 1, y: 0});
      } else gsap.set(node, {opacity: 0, y: 26});
    }
  };
  const entrance = (slide) => {
    if (DECK.reduced) return;
    const parts = slide.querySelectorAll('.pad > .kicker, .pad > .headline, .hook-1');
    gsap.fromTo(parts, {opacity: 0, y: 24}, {opacity: 1, y: 0, duration: 0.7, stagger: 0.08, ease: 'power3.out'});
  };

  /* ---------- navigation ---------- */
  const go = (index, step = 0, {final = false, animate = true} = {}) => {
    index = Math.max(0, Math.min(slides.length - 1, index));
    const prev = slides[DECK.index];
    if (prev && DECK.index !== index) scenes[prev.dataset.id].leave?.();
    slides.forEach((s, i) => s.classList.toggle('active', i === index));
    const slide = slides[index];
    const scene = scenes[slide.dataset.id];
    const steps = plan[index].steps;
    DECK.index = index;
    DECK.step = final ? steps : Math.max(0, Math.min(steps, step));
    if (final) { scene.final(); setReveals(slide, steps, false); }
    else {
      scene.enter();
      if (animate) entrance(slide);
      // Rebuilding a mid-slide position (e.g. stepping backwards) lands on final states for earlier steps.
      for (let k = 1; k <= DECK.step; k++) scene.step(k);
      setReveals(slide, DECK.step, false);
    }
    if (!timer.started) timer.start();
    hud(); renderNotes();
    history.replaceState(null, '', `#${index + 1}`);
  };
  const next = () => {
    if (!timer.started) timer.start(); // the first reveal starts the clock, by key or by click
    const steps = plan[DECK.index].steps;
    if (DECK.step < steps) {
      DECK.step++;
      scenes[slides[DECK.index].dataset.id].step(DECK.step);
      setReveals(slides[DECK.index], DECK.step, true);
      hud(); renderNotes();
    } else if (DECK.index < slides.length - 1) go(DECK.index + 1);
  };
  const prev = () => {
    if (DECK.step > 0) go(DECK.index, DECK.step - 1, {animate: false, final: false});
    else if (DECK.index > 0) go(DECK.index - 1, 0, {final: true});
  };
  const replay = () => go(DECK.index, 0);

  /* ---------- timer ---------- */
  const timer = {
    started: false, t0: 0,
    start() { this.started = true; this.t0 = performance.now(); },
    reset() { this.t0 = performance.now(); this.started = true; },
    elapsed() { return this.started ? (performance.now() - this.t0) / 1000 : 0; },
  };

  /* ---------- HUD + notes ---------- */
  const $ = (id) => document.getElementById(id);
  const hud = () => {
    const p = plan[DECK.index];
    $('hud-slide').textContent = `${DECK.index + 1}/${slides.length} ${p.id}`;
    $('hud-step').textContent = `step ${DECK.step}/${p.steps}`;
    $('hud-target').textContent = `plan ${mmss(startOf(DECK.index))}–${mmss(startOf(DECK.index) + p.seconds)} · ${p.speaker}`;
    $('hud-mode').textContent = [rehearsal.on ? 'REHEARSAL' : '', DECK.reduced ? 'reduced motion' : ''].filter(Boolean).join(' · ');
  };
  const tick = () => {
    const e = timer.elapsed();
    const el = $('hud-timer');
    el.textContent = `${mmss(e)} / ${mmss(TOTAL)}`;
    el.classList.toggle('over', e > startOf(DECK.index) + plan[DECK.index].seconds);
    if (rehearsal.on) rehearsal.tick();
    requestAnimationFrame(tick);
  };
  const renderNotes = () => {
    const box = $('notes');
    const p = plan[DECK.index];
    const n = notes[DECK.index];
    const following = plan[DECK.index + 1];
    box.innerHTML =
      `<h4>${DECK.index + 1}. ${p.title}</h4>` +
      `<div class="meta">${p.speaker} · ${p.seconds} s · ${mmss(startOf(DECK.index))}–${mmss(startOf(DECK.index) + p.seconds)} · step ${DECK.step}/${p.steps}</div>` +
      n.cues.map(([t, text]) => `<p class="cue"><b>${t}</b>${text}</p>`).join('') +
      (following ? `<p class="next">Next: ${following.title} (${following.speaker})</p>` : '<p class="next">End of talk.</p>');
  };

  /* ---------- auto-rehearsal: 180 s, reveals spaced evenly within each slide ---------- */
  const rehearsal = {
    on: false, t0: 0,
    schedule: plan.flatMap((p, i) => Array.from({length: p.steps + 1}, (_, k) => ({i, k, at: startOf(i) + (k * p.seconds) / (p.steps + 1)}))),
    toggle() {
      this.on = !this.on;
      $('rehearsal-bar').classList.toggle('on', this.on);
      if (this.on) { this.t0 = performance.now(); timer.reset(); this.last = -1; go(0); }
      hud();
    },
    tick() {
      const e = (performance.now() - this.t0) / 1000;
      $('rehearsal-bar').firstElementChild.style.width = `${Math.min(100, (e / TOTAL) * 100)}%`;
      let idx = -1;
      for (let j = 0; j < this.schedule.length; j++) if (this.schedule[j].at <= e) idx = j;
      if (idx > this.last) {
        this.last = idx;
        const {i, k} = this.schedule[idx];
        // The very next reveal animates. Anything else (a background tab throttled
        // requestAnimationFrame past several entries, or the presenter pressed keys)
        // restores the exact scheduled slide and step without animation.
        const isNext = (i === DECK.index && k === DECK.step + 1) || (i === DECK.index + 1 && k === 0 && DECK.step === plan[DECK.index].steps);
        if (isNext) next();
        else if (i !== DECK.index || k !== DECK.step) go(i, k, {animate: false});
      }
      if (e >= TOTAL) { this.on = false; $('rehearsal-bar').classList.remove('on'); hud(); }
    },
  };

  /* ---------- keyboard / pointer ---------- */
  const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.());
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (['ArrowRight', ' ', 'PageDown', 'Enter'].includes(k)) { e.preventDefault(); e.shiftKey && k === 'ArrowRight' ? go(DECK.index + 1, 0, {final: true}) : next(); }
    else if (['ArrowLeft', 'PageUp', 'Backspace'].includes(k)) { e.preventDefault(); e.shiftKey && k === 'ArrowLeft' ? go(DECK.index - 1, 0, {final: true}) : prev(); }
    else if (k === 'Home') go(0);
    else if (k === 'End') go(slides.length - 1, 0, {final: true});
    else if (/^[1-8]$/.test(k)) go(Number(k) - 1);
    else if (k === 'f' || k === 'F') fullscreen();
    else if (k === 'n' || k === 'N') $('notes').classList.toggle('on');
    else if (k === 't' || k === 'T') timer.reset();
    else if (k === 'r' || k === 'R') rehearsal.toggle();
    else if (k === 'm' || k === 'M') { DECK.reduced = !DECK.reduced; go(DECK.index, DECK.step, {animate: false}); }
    else if (k === 'a' || k === 'A') replay();
    else if (k === '?' || k === 'h' || k === 'H') $('help').hidden = !$('help').hidden;
    else if (k === 'Escape') $('help').hidden = true;
  });
  stage.addEventListener('click', (e) => { if (!e.target.closest('button, .event-card, video')) next(); });

  /* ---------- print: every slide in its final state ---------- */
  const printMode = () => {
    document.body.classList.add('print-mode');
    stage.style.transform = 'none';
    slides.forEach((s, i) => {
      s.classList.add('active');
      DECK.index = i;
      scenes[s.dataset.id].final();
      setReveals(s, plan[i].steps, false);
    });
  };
  window.addEventListener('beforeprint', () => { if (!document.body.classList.contains('print-mode')) { DECK.reduced = true; printMode(); } });
  window.addEventListener('afterprint', () => { if (!params.has('print')) location.reload(); });

  /* ---------- boot ---------- */
  const missing = [...document.images].filter((img) => img.complete && img.naturalWidth === 0).map((img) => img.getAttribute('src'));
  if (missing.length) console.warn('Missing images:', missing);
  if (params.has('print')) { DECK.reduced = true; printMode(); return; }
  fit();
  const fromHash = Number(location.hash.slice(1)) - 1;
  timer.started = false;
  go(Number.isFinite(fromHash) && fromHash >= 0 ? fromHash : 0);
  timer.started = false; // timer starts on the first navigation after load
  hud();
  requestAnimationFrame(tick);
  window.addEventListener('keydown', () => { if (!timer.started) timer.start(); }, {once: true});
})();
