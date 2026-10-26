"""Overview traffic story: exact recomputed numbers, stored-row drawing, safe markup."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import nearmiss.store as store_module
import nearmiss.video as video_module
from nearmiss import demo, motion
from nearmiss.config import DEFAULT_CONFLICT_CONFIG
from nearmiss.incidents import DEFAULT_COLLISION_CONFIG


APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(scope="module")
def recomputed():
    return motion.recompute_demo(DEFAULT_CONFLICT_CONFIG, DEFAULT_COLLISION_CONFIG)


@pytest.fixture(scope="module")
def story():
    return motion.demo_story(DEFAULT_CONFLICT_CONFIG, DEFAULT_COLLISION_CONFIG)


def chapter(story, chapter_id):
    return next(item for item in story["chapters"] if item["id"] == chapter_id)


def fact(story, chapter_id, label):
    return next(item["value"] for item in chapter(story, chapter_id)["facts"] if item["label"] == label)


def test_recompute_matches_the_guided_demo_regression(recomputed):
    # Same counts the AppTest walk-through asserts on the Analysis page.
    assert len(recomputed["events"]) == 3
    assert len(recomputed["incidents"]) == 1
    assert all(row["data_source"] == "synthetic_demo" for row in recomputed["tracks"])


def test_story_follows_the_warning_linked_to_the_incident(recomputed, story):
    incident = recomputed["incidents"][0]
    event = next(e for e in recomputed["events"] if e["event_id"] == incident["associated_prediction_event_id"])
    assert story["event"]["event_id"] == event["event_id"]
    assert story["incident"]["incident_id"] == incident["incident_id"]
    assert [c["id"] for c in story["chapters"]] == list(motion.CHAPTERS)
    # The predict scene freezes on the measurement frame its projections come from.
    assert chapter(story, "predict")["frame"] == event["frame_index"]
    assert event["frame_index"] < event["start_frame_index"]
    assert chapter(story, "verify")["frame"] == incident["frame_index"]
    assert chapter(story, "observe")["frame"] < chapter(story, "predict")["frame"]


def test_every_number_comes_from_the_recomputed_records(recomputed, story):
    incident = recomputed["incidents"][0]
    event = next(e for e in recomputed["events"] if e["event_id"] == incident["associated_prediction_event_id"])
    fps = demo.FPS
    assert fact(story, "predict", "First warning") == (
        f"{event['first_alert_timestamp_seconds']:.2f} s · frame {event['start_frame_index']} · {event['severity']}"
    )
    assert fact(story, "predict", "Arrival gap") == f"{event['arrival_time_gap_seconds']:.2f} s"
    assert fact(story, "predict", "Time to projected meeting") == f"{event['time_to_conflict_seconds']:.2f} s"
    assert fact(story, "verify", "Warning lead") == f"{incident['prediction_lead_seconds']:.2f} s"
    assert fact(story, "verify", "Supporting signals") == str(len(incident["detection_signals"]))
    assert fact(story, "verify", "First suspected contact") == (
        f"{incident['first_suspected_impact_timestamp_seconds']:.2f} s · frame {incident['frame_index']}"
    )
    assert chapter(story, "predict")["clock"] == f"t = {event['frame_index'] / fps:.2f} s · frame {event['frame_index']}"
    assert fact(story, "predict", "Projection measured") == f"{event['frame_index'] / fps:.2f} s · frame {event['frame_index']}"
    # Today's demo values, so a silent pipeline change cannot slip through.
    assert fact(story, "predict", "First warning") == "7.10 s · frame 142 · HIGH"
    assert fact(story, "verify", "Warning lead") == "0.60 s"
    assert fact(story, "predict", "Projection measured") == "7.00 s · frame 140"


def test_story_is_recomputed_when_thresholds_change():
    strict = {**DEFAULT_CONFLICT_CONFIG, "high_time_gap_seconds": 0.02}
    story = motion.demo_story(strict, DEFAULT_COLLISION_CONFIG)
    assert story is not None
    # The 0.03 s arrival gap no longer qualifies as HIGH at 0.02 s.
    assert "HIGH" not in fact(story, "predict", "First warning")
    assert fact(story, "predict", "HIGH threshold") == "≤ 0.02 s arrival gap"


def test_follow_up_uses_street_lab_arithmetic_and_labels_assumptions(story):
    from nearmiss import streetlab

    crossing = streetlab.crossing_comparison(motion.EXAMPLE_CROSSING)
    typical = crossing["rows"][0]
    assert fact(story, "follow_up", typical["walker"]) == (
        f"{typical['current_seconds']:.1f} s → {typical['proposed_seconds']:.1f} s"
    )
    assert "assumed" in fact(story, "follow_up", "Example crossing")
    assert any("not measured from this scene" in text for text in chapter(story, "follow_up")["body"])


def test_no_warning_means_no_story_and_no_incident_is_stated(recomputed):
    common = dict(
        tracks=recomputed["tracks"], conflict_config=recomputed["config"], fps=demo.FPS,
        duration_seconds=12.0, layout=motion.demo_layout(),
    )
    assert motion.build_story(events=[], incidents=[], **common) is None
    story = motion.build_story(events=recomputed["events"], incidents=[], **common)
    verify = chapter(story, "verify")
    assert story["incident"] is None
    assert "nothing to confirm" in verify["title"]
    assert "verify" not in verify["layers"]


def test_drawn_positions_are_stored_rows_and_trails_never_look_ahead(recomputed, story):
    stored = {(r["track_id"], r["frame_index"]): r["bbox"] for r in recomputed["tracks"]}
    for item in story["chapters"]:
        svg = motion.scene_svg(story, item["id"])
        for actor in story["actors"]:
            row = motion._row_at(actor, item["frame"])
            match = re.search(rf'data-actor="{actor["id"]}" x="([\d.]+)" y="([\d.]+)"', svg)
            assert match
            if row is None:
                assert re.search(rf'data-actor="{actor["id"]}"[^>]*visibility="hidden"', svg)
                continue
            assert row[0] <= item["frame"]
            x1, y1 = stored[(actor["id"], row[0])][:2]
            assert float(match.group(1)) == pytest.approx(x1, abs=0.05)
            assert float(match.group(2)) == pytest.approx(y1, abs=0.05)
            points = re.search(rf'data-trail="{actor["id"]}"[^>]*points="([^"]*)"', svg).group(1)
            expected = [r for r in actor["rows"] if story["start_frame"] <= r[0] <= item["frame"]]
            assert len(points.split()) == len(expected)


def test_row_lookup_never_invents_rows():
    actor = {"rows": [[10, 0, 0, 1, 1], [12, 5, 5, 6, 6]]}
    assert motion._row_at(actor, 9) is None
    assert motion._row_at(actor, 11)[0] == 10  # latest stored row, not an interpolation
    assert motion._row_at(actor, 12)[0] == 12
    assert motion._row_at(actor, 13) is None


def test_markup_is_readable_without_script_and_self_contained(story):
    markup = motion.story_markup(story)
    assert "<script" not in markup.lower()
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", markup)
    for item in story["chapters"]:
        assert item["title"] in markup.replace("&#x27;", "'")
        # One static endpoint per chapter for stacked/no-script reading.
        assert f'data-chapter="{item["id"]}"' in markup
    assert markup.count('class="nm-endpoint"') == 4
    assert motion.SYNTHETIC_RIBBON.split(" · ")[0] in markup
    assert "SYNTHETIC DEMO" in motion.scene_svg(story, "observe")
    # The toggle only appears once the script has run.
    assert re.search(r"data-motion-toggle hidden", markup)


def test_styles_and_script_stay_local_scoped_and_clean_up():
    for source in (motion.STORY_CSS, motion.STORY_JS):
        assert "http" not in source and "@import" not in source and "@font-face" not in source
    js = motion.STORY_JS
    assert "parentElement.querySelector" in js
    assert "document.querySelector" not in js and "window.parent" not in js and "fetch(" not in js
    assert "prefers-reduced-motion" in js and "prefers-reduced-motion" in motion.STORY_CSS
    for cleanup in ("observer.disconnect()", "cancelAnimationFrame(raf)", "removeEventListener('change'",
                    "removeEventListener('click'", "return cleanup"):
        assert cleanup in js
    assert "position:sticky" in motion.STORY_CSS


def test_component_name_tracks_the_markup(story):
    markup = motion.story_markup(story)
    assert motion.story_component_name(markup) == motion.story_component_name(markup)
    assert motion.story_component_name(markup) != motion.story_component_name(markup + " ")


def test_overview_landing_mounts_the_story_below_the_preserved_hero(tmp_path, monkeypatch):
    monkeypatch.setattr(video_module, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(store_module, "DEFAULT_DATABASE_PATH", tmp_path / "data" / "nearmiss.db")
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    html = "\n".join(str(item.value) for item in at.markdown)
    assert "See the moments" in html and "illustrative context only" in html
    assert at.button(key="start_demo").proto.type == "primary"
    assert len(at.get("file_uploader")) == 1
    components = at.get("bidi_component")
    assert len(components) == 1
    proto = components[0].proto
    assert proto.component_name.startswith("nearmiss_story_")
    assert proto.isolate_styles  # shadow root in the page, not an iframe
    assert "Observe, predict, verify, follow up" in proto.html_content
    assert "7.10 s · frame 142 · HIGH" in proto.html_content
    assert any(item.key == "presenter_open_story" for item in at.button)
    # Nothing was generated on disk just to tell the story.
    assert not (tmp_path / "cache").exists()


def test_projected_paths_start_at_the_drawn_boxes(story):
    """No detached dashed paths: each projection starts at its box's ground point."""

    svg = motion.scene_svg(story, "predict")
    frame_index = chapter(story, "predict")["frame"]
    event = story["event"]
    for role, start in (("a", event["a_position"]), ("b", event["b_position"])):
        actor = next(a for a in story["actors"] if a["role"] == role)
        row = motion._row_at(actor, frame_index)
        assert row[0] == frame_index
        assert ((row[1] + row[3]) / 2, row[4]) == pytest.approx(tuple(start), abs=0.05)
        assert f'x1="{start[0]}" y1="{start[1]}"' in svg
    # Measurement time and first-alert time are labeled separately in the diagram.
    assert "paths measured 7.00 s (frame 140) · first warning 7.10 s (frame 142)" in svg


def test_every_endpoint_has_a_meaningful_text_alternative(story):
    for item in story["chapters"]:
        svg = motion.scene_svg(story, item["id"])
        label = re.search(r'<svg[^>]*aria-label="([^"]*)"', svg).group(1)
        assert item["clock"] in label and "car #3" in label and "truck #4" in label
    predict = motion.scene_description(story, chapter(story, "predict"))
    assert "measured at frame 140" in predict and "first warning followed at frame 142" in predict
    assert "contact marker" in motion.scene_description(story, chapter(story, "verify"))
    assert "not measurements" in motion.scene_description(story, chapter(story, "follow_up"))


def test_desktop_hides_endpoints_visually_but_keeps_them_accessible():
    css = motion.STORY_CSS
    desktop = css[css.index("@media " + motion.STAGE_QUERY):]
    endpoint_rule = re.search(r"\.nm-story\.is-enhanced \.nm-endpoint \{([^}]*)\}", desktop).group(1)
    assert "display:none" not in endpoint_rule and "clip-path:inset(50%)" in endpoint_rule
    assert "@media __STAGE_QUERY__" not in css
    markup_stage = '<div class="nm-stage" aria-hidden="true">'
    story = motion.demo_story(DEFAULT_CONFLICT_CONFIG, DEFAULT_COLLISION_CONFIG)
    assert markup_stage in motion.story_markup(story)  # duplicate visual only


def test_playback_is_gated_on_the_desktop_breakpoint():
    js = motion.STORY_JS
    assert f"window.matchMedia('{motion.STAGE_QUERY}')" in js
    assert "if (!enabled) return;" in js  # no rAF while the stage is hidden
    assert "wide.addEventListener('change', onWidth)" in js
    assert "wide.removeEventListener('change', onWidth)" in js
    disable = js[js.index("const disable"):js.index("const onWidth")]
    assert "cancelAnimationFrame(raf)" in disable and "observer.disconnect()" in disable


def test_frame_bound_overlays_appear_only_once_the_frame_arrives():
    """Back-scrolling Verify -> Predict must not show frame-140 paths over frames 154..141."""

    js = motion.STORY_JS
    go_to = js[js.index("const goTo"):js.index("const activate")]
    arrive = js[js.index("const arrive"):js.index("const goTo")]
    # Layers are set only in arrive(), right after drawing the target frame.
    assert arrive.index("draw(chapter.frame)") < arrive.index("setAttribute('data-layers', chapter.layers")
    assert "chapter.layers" not in go_to
    # While frames move, every overlay is hidden; the tween ends by arriving.
    assert go_to.index("setAttribute('data-layers', '')") < go_to.index("requestAnimationFrame(step)")
    assert "else arrive(chapter)" in go_to and "arrive(chapter); return;" in go_to
    # Switching to reduced motion mid-transition also lands on frame plus overlays together.
    sync = js[js.index("const syncReduced"):js.index("const onToggle")]
    assert "arrive(byId.get(activeId))" in sync
    # The stage CSS hides overlays when no layer is named.
    assert ".nm-scene[data-stage] .layer { opacity:0; }" in motion.STORY_CSS


HARNESS = r"""
import run from './story.mjs';
const story = JSON.parse(process.argv[2]);
const el = () => { const attrs = {}; return { attrs, dataset: {}, hidden: true, textContent: '',
  classList: { toggle() {}, add() {}, remove() {} },
  setAttribute(k, v) { attrs[k] = String(v); }, removeAttribute(k) { delete attrs[k]; },
  addEventListener() {}, removeEventListener() {} }; };
const stage = el(); const clock = el(); const parts = {};
stage.querySelector = (sel) => sel === '[data-clock]' ? clock : (parts[sel] ||= el());
const chapters = story.chapters.map((c) => { const s = el(); s.dataset.chapter = c.id; return s; });
const root = el();
root.querySelector = (sel) => sel.startsWith('svg') ? stage : null;
root.querySelectorAll = () => chapters;
let observe; let now = 0; let queue = [];
globalThis.window = { matchMedia: (q) => ({ matches: q.includes('min-width'), addEventListener() {}, removeEventListener() {} }),
  localStorage: { getItem: () => null, setItem() {} } };
globalThis.IntersectionObserver = class { constructor(cb) { observe = cb; } observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => { queue.push(f); return queue.length; };
globalThis.cancelAnimationFrame = () => { queue = []; };
globalThis.performance = { now: () => now };
run({ data: story, parentElement: { querySelector: () => root } });
const log = [];
const record = () => log.push([Number(clock.textContent.split('frame ')[1]), stage.attrs['data-layers'] || '']);
const visit = (id) => {
  observe([{ isIntersecting: true, target: chapters.find((c) => c.dataset.chapter === id) }]); record();
  while (queue.length) { const f = queue.shift(); now += 16; f(now); record(); }
};
for (const id of process.argv.slice(3)) visit(id);
console.log(JSON.stringify(log));
"""


def test_stage_script_never_shows_overlays_on_other_frames(story, tmp_path):
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; the structural guard above still applies.")
    (tmp_path / "story.mjs").write_text(motion.STORY_JS, encoding="utf-8")
    (tmp_path / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    data = motion.animation_data(story)
    order = ["observe", "predict", "verify", "predict", "observe"]  # includes back-scroll
    result = subprocess.run(
        [node, str(tmp_path / "harness.mjs"), json.dumps(data), *order],
        capture_output=True, text=True, check=True, timeout=60,
    )
    log = json.loads(result.stdout)
    frames = {item["id"]: item["frame"] for item in data["chapters"]}
    assert any(layers == "" for _frame, layers in log)  # overlays hidden mid-transition
    for frame, layers in log:
        if "predict" in layers.split():
            assert frame == frames["predict"], (frame, layers)
        if "verify" in layers.split():
            assert frame == frames["verify"], (frame, layers)
    # The back-scroll to Predict ends with paths and boxes on the measurement frame.
    second_predict = [entry for entry in log if "predict" in entry[1].split()]
    assert second_predict and second_predict[-1][0] == frames["predict"] == 140
