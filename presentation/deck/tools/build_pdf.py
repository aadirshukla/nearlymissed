"""Eight-page PDF backup of the NearMiss deck, every reveal in its final state.

Editable source: layout mirrors presentation/deck/index.html + deck.css; all
numbers come from presentation/data/demo-metrics.json, all screenshots from
the host captures, diagrams from the scripted demo samples.

    .venv/bin/python presentation/deck/tools/build_pdf.py
    -> presentation/exports/NearMiss-deck.pdf (+ prints a page/asset report)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

DECK = Path(__file__).resolve().parents[1]
PRESENTATION = DECK.parent
OUT = PRESENTATION / "exports" / "NearMiss-deck.pdf"
ASSETS = DECK / "assets"
M = json.loads((PRESENTATION / "data" / "demo-metrics.json").read_text(encoding="utf-8"))
BRIEF_PATH = ASSETS / "captures" / "brief.md"
BRIEF = BRIEF_PATH.read_text(encoding="utf-8") if BRIEF_PATH.exists() else None

W, H = 1920, 1080
INK, CARD, LINE = HexColor("#0B0B0C"), HexColor("#131315"), HexColor("#27272A")
AMBER, CORAL, WHITE = HexColor("#F2A93B"), HexColor("#E5676F"), HexColor("#F5F5F4")
MUTED, GREEN, PAPER, PAPER_INK = HexColor("#A8A29E"), HexColor("#6BBE9F"), HexColor("#F4F1EA"), HexColor("#1A1816")

FONTS = {
    "Sans": "Inter-Regular.ttf",
    "Sans-Semi": "Inter-SemiBold.ttf",
    "Sans-Bold": "Inter-Bold.ttf",
    "Serif-Italic": "InstrumentSerif-Italic.ttf",
    "Mono": "JetBrainsMono-Regular.ttf",
    "Mono-Medium": "JetBrainsMono-Medium.ttf",
}
for name, file in FONTS.items():
    pdfmetrics.registerFont(TTFont(name, str(ASSETS / "fonts" / file)))

used_assets: set[str] = set()
missing_assets: set[str] = set()

# The browser deck keeps its presenter HUD in the bottom 64 px of the stage
# (deck.css --hud-band). The PDF mirrors that layout, so every text line and
# capture must end at BAND_TOP or above; main() fails the build otherwise.
BAND_TOP = H - 64
band_overflows: list[str] = []
page = {"n": 0, "oy": 0.0, "k": 1.0}  # current page and any vertical scale (slide 4 media)


def occupy(bottom: float, what: str) -> None:
    actual = page["oy"] + (bottom - page["oy"]) * page["k"]
    if actual > BAND_TOP + 0.5:
        band_overflows.append(f"slide {page['n']}: {what[:48]!r} ends at y={actual:.0f}")


def asset(rel: str) -> Path | None:
    path = ASSETS / rel
    if path.exists():
        used_assets.add(rel)
        return path
    missing_assets.add(rel)
    return None


# ------------------------------------------------------------ primitives
# All coordinates are top-left based in the deck's 1920x1080 stage.

def Y(y: float) -> float:
    return H - y


def rect(c, x, y, w, h, fill=None, stroke=None, width=1, radius=0, alpha=1.0):
    c.saveState()
    if fill is not None:
        c.setFillColor(fill)
        c.setFillAlpha(alpha)
    if stroke is not None:
        c.setStrokeColor(stroke)
        c.setLineWidth(width)
    if radius:
        c.roundRect(x, Y(y + h), w, h, radius, stroke=stroke is not None, fill=fill is not None)
    else:
        c.rect(x, Y(y + h), w, h, stroke=stroke is not None, fill=fill is not None)
    c.restoreState()


def text(c, s, x, y, font="Sans", size=24, color=WHITE, anchor="left", spacing=0):
    """Draw one line; y is the top of the line box."""
    c.saveState()
    c.setFillColor(color)
    obj = c.beginText()
    obj.setFont(font, size)
    obj.setCharSpace(spacing)
    width = pdfmetrics.stringWidth(s, font, size) + spacing * max(len(s) - 1, 0)
    if anchor == "right":
        x -= width
    elif anchor == "center":
        x -= width / 2
    obj.setTextOrigin(x, Y(y + size * 0.82))
    obj.textOut(s)
    c.drawText(obj)
    c.restoreState()
    occupy(y + size * 1.05, s)
    return width


def para(c, s, x, y, max_w, font="Sans", size=24, color=WHITE, leading=1.4):
    lines = simpleSplit(s, font, size, max_w)
    for i, line in enumerate(lines):
        text(c, line, x, y + i * size * leading, font, size, color)
    return y + len(lines) * size * leading


def runs(c, parts, x, y, max_w, size, leading=1.08):
    """Word-wrapped mixed-style line(s). parts = [(text, font, color), ...]."""
    words = []
    for s, font, color in parts:
        for i, word in enumerate(s.split(" ")):
            if word:
                words.append((word, font, color))
    line_y, cursor = y, x
    space = lambda font: pdfmetrics.stringWidth(" ", font, size)  # noqa: E731
    for word, font, color in words:
        w = pdfmetrics.stringWidth(word, font, size)
        if cursor > x and cursor + w > x + max_w:
            line_y += size * leading
            cursor = x
        text(c, word, cursor, line_y, font, size, color)
        cursor += w + space(font)
    return line_y + size * leading


def kicker(c, s, x, y, color=AMBER, size=24):
    text(c, s.upper(), x, y, "Mono-Medium", size, color, spacing=4)


def tag(c, s, x, y, color=AMBER, solid=False, size=18):
    label = s.upper()
    w = pdfmetrics.stringWidth(label, "Mono-Medium", size) + 2 * (len(label) - 1) + 24
    h = size + 14
    rect(c, x, y, w, h, fill=color if solid else INK, stroke=color, width=1.5, radius=4, alpha=1 if solid else 0.8)
    text(c, label, x + 12, y + 7, "Mono-Medium", size, INK if solid else color, spacing=2)
    return w


def image_cover(c, path, x, y, w, h):
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    k = max(w / iw, h / ih)
    dw, dh = iw * k, ih * k
    clip(c, x, y, w, h)
    c.drawImage(img, x + (w - dw) / 2, Y(y + (h + dh) / 2), dw, dh)
    c.restoreState()


def clip(c, x, y, w, h, radius=0):
    c.saveState()
    p = c.beginPath()
    if radius:
        p.roundRect(x, Y(y + h), w, h, radius)
    else:
        p.rect(x, Y(y + h), w, h)
    c.clipPath(p, stroke=0, fill=0)


def image_crop(c, rel, x, y, w, h, img_w, left, top, radius=10, caption=None):
    """Mirror of the CSS crops: image scaled to img_w px wide, offset by left/top."""
    path = asset(rel)
    rect(c, x, y, w, h, fill=INK, radius=radius)
    if path is None:
        text(c, f"Host capture pending: {rel}", x + 20, y + h / 2, "Mono", 22, CORAL)
    else:
        img = ImageReader(str(path))
        iw, ih = img.getSize()
        k = img_w / iw
        clip(c, x, y, w, h, radius)
        c.drawImage(img, x + left, Y(y + top + ih * k), img_w, ih * k)
        c.restoreState()
    rect(c, x, y, w, h, stroke=LINE, width=1, radius=radius)
    occupy(y + h, rel)
    if caption:
        text(c, caption, x, y + h + 10, "Mono", 17, MUTED)


def shade(c, top_alpha, bottom_alpha):
    """Vertical ink gradient as one RGBA image (stacked translucent bands show seams)."""
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGBA", (1, 256))
    for i in range(256):
        a = top_alpha + (bottom_alpha - top_alpha) * i / 255
        img.putpixel((0, i), (11, 11, 12, round(255 * a)))
    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, W, H, mask="auto")


# ------------------------------------------------------------ diagram

def actor_at(actor, t):
    step = actor["sample_step_seconds"]
    samples = actor["samples"]
    i = int(t // step)
    clamp = lambda j: max(0, min(j, len(samples) - 1))  # noqa: E731
    p, q = samples[clamp(i)], samples[clamp(i + 1)]
    if p is None:
        return None
    if q is None:
        return p
    k = t / step - i
    return [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k]


def actor(track_id):
    return next(a for a in M["actors"] if a["track_id"] == track_id)


def intersection(c, x, y, w, h, view, t, highlight, trail_from=None, dashed=(), rings=(), saturation=1.0):
    vx, vy, vw, vh = view
    k = max(w / vw, h / vh)  # slice, like the SVG
    ox = x + (w - vw * k) / 2 - vx * k
    oy = y + (h - vh * k) / 2 - vy * k
    P = lambda px, py: (ox + px * k, oy + py * k)  # noqa: E731 - demo px -> stage
    clip(c, x, y, w, h, 14)

    def drect(px, py, pw, ph, color, stroke=None, sw=1, radius=0):
        sx, sy = P(px, py)
        rect(c, sx, sy, pw * k, ph * k, fill=color, stroke=stroke, width=sw, radius=radius * k)

    (h0, h1), (v0, v1) = M["source"]["road"]["horizontal_y"], M["source"]["road"]["vertical_x"]
    FW, FH = M["source"]["frame"]["width"], M["source"]["frame"]["height"]
    cy, cx = (h0 + h1) / 2, (v0 + v1) / 2
    drect(0, 0, FW, FH, HexColor("#1B1E1A"))
    for x1, y1, x2, y2 in ((30, 24, 330, 150), (630, 24, 930, 150), (30, 390, 330, 516), (630, 390, 930, 516)):
        drect(x1, y1, x2 - x1, y2 - y1, HexColor("#24271F"), HexColor("#3A3E39"))
    drect(0, h0 - 22, FW, h1 - h0 + 44, HexColor("#47453F"))
    drect(v0 - 22, 0, v1 - v0 + 44, FH, HexColor("#47453F"))
    drect(0, h0, FW, h1 - h0, HexColor("#28292B"))
    drect(v0, 0, v1 - v0, FH, HexColor("#28292B"))

    def dline(a, b, color, width, dash=None, alpha=1.0):
        c.saveState()
        c.setStrokeColor(color)
        c.setStrokeAlpha(alpha)
        c.setLineWidth(width)
        c.setLineCap(1)
        if dash:
            c.setDash(*dash)
        (ax, ay), (bx, by) = P(*a), P(*b)
        c.line(ax, Y(ay), bx, Y(by))
        c.restoreState()

    lane = HexColor("#D79628")
    for o in (-3, 3):
        dline((0, cy + o), (v0 - 46, cy + o), lane, 2 * k)
        dline((v1 + 46, cy + o), (FW, cy + o), lane, 2 * k)
        dline((cx + o, 0), (cx + o, h0 - 46), lane, 2 * k)
        dline((cx + o, h1 + 46), (cx + o, FH), lane, 2 * k)
    stripe = HexColor("#CDCDC8")
    for sy in range(h0 + 6, h1 - 4, 16):
        drect(v0 - 40, sy, 28, 8, stripe)
        drect(v1 + 12, sy, 28, 8, stripe)
    for sx in range(v0 + 6, v1 - 4, 16):
        drect(sx, h0 - 40, 8, 28, stripe)
        drect(sx, h1 + 12, 8, 28, stripe)
    for a, b in (((v0 - 46, cy + 6), (v0 - 46, h1)), ((v1 + 46, h0), (v1 + 46, cy - 6)),
                 ((v0, h0 - 46), (cx - 6, h0 - 46)), ((cx + 6, h1 + 46), (v1, h1 + 46))):
        dline(a, b, stripe, 3 * k)

    if trail_from is not None:
        for tid, color in highlight.items():
            a = actor(tid)
            pts = []
            s = trail_from
            while s <= t + 1e-9:
                p = actor_at(a, s)
                if p:
                    pts.append(p)
                s += a["sample_step_seconds"]
            for p, q in zip(pts, pts[1:]):
                dline(p, q, color, 3 * k * vw / 960, alpha=0.75)
    for a_pt, b_pt, color in dashed:
        dline(a_pt, b_pt, color, 3 * k * vw / 960, dash=(10 * k * vw / 960, 7 * k * vw / 960))

    for a in M["actors"]:
        p = actor_at(a, t)
        if p is None:
            continue
        accent = highlight.get(a["track_id"])
        if a["class_name"] == "person":
            sx, sy = P(*p)
            c.saveState()
            c.setFillColor(HexColor("#E6E6E6"))
            c.circle(sx, Y(sy), 6 * k, stroke=0, fill=1)
            c.restoreState()
            continue
        aw, ah = a["size"]
        color = HexColor(a["color"])
        if saturation < 1 and not accent:
            color = mix(color, HexColor("#555555"), 1 - saturation)
        drect(p[0] - aw / 2, p[1] - ah / 2, aw, ah, color, HexColor("#151515"), 1, 3)
        if accent:
            sx, sy = P(p[0] - aw / 2 - 5, p[1] - ah / 2 - 5)
            rect(c, sx, sy, (aw + 10) * k, (ah + 10) * k, stroke=accent, width=3 * k * vw / 960, radius=4 * k)
            lx, ly = P(p[0] + aw / 2 + 8, p[1] - ah / 2 - 24 * vw / 960)
            text(c, f"#{a['track_id']}", lx, ly, "Mono-Medium", 18 * k * vw / 960, accent)
    for at, r, color in rings:
        sx, sy = P(*at)
        c.saveState()
        c.setStrokeColor(color)
        c.setLineWidth(3 * k * vw / 960)
        c.circle(sx, Y(sy), r * k, stroke=1, fill=0)
        c.restoreState()
    c.restoreState()
    rect(c, x, y, w, h, stroke=LINE, width=1, radius=14)


def mix(a, b, k):
    return HexColor("#{:02x}{:02x}{:02x}".format(*(int(255 * (getattr(a, ch) * (1 - k) + getattr(b, ch) * k)) for ch in ("red", "green", "blue"))))


# ------------------------------------------------------------ data helpers

E1 = M["events"][0]
INC = M["incidents"][0] if M["incidents"] else None
LINKED = next((e for e in M["events"] if INC and e["event_id"] == INC["associated_prediction_event_id"]), None)
FPS = M["source"]["frame"]["fps"]
SIGNALS = {
    "persistent_bounding_box_contact": "Persistent box contact",
    "significant_bounding_box_overlap": "Significant box overlap",
    "previously_converging_trajectories": "Converging before contact",
    "abrupt_motion_change": "Abrupt motion change",
    "sudden_deceleration": "Sudden deceleration",
    "stopped_after_contact": "Stopped after contact",
    "post_contact_track_loss": "Track lost after contact",
}


def arrivals():
    eta = E1["measurement"]["eta_seconds"]
    if None not in eta:
        return tuple(eta)
    for bullet in E1["explanation"]["bullets"]:
        m = re.search(r"reach it in ([\d.]+)s and .*? in ([\d.]+)s", bullet)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def clock(seconds):
    return f"00:{seconds:05.2f}"


NB = "\u00a0"  # keeps a number and its unit on one line


def fit_view(points, pad, aspect):
    """Same as fitView in scenes.js: smallest frame view holding every point plus padding."""
    fw, fh = M["source"]["frame"]["width"], M["source"]["frame"]["height"]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    if (x1 - x0) / (y1 - y0) < aspect:
        g = ((y1 - y0) * aspect - (x1 - x0)) / 2
        x0, x1 = x0 - g, x1 + g
    else:
        g = ((x1 - x0) / aspect - (y1 - y0)) / 2
        y0, y1 = y0 - g, y1 + g
    w, h = x1 - x0, y1 - y0
    if w <= fw:
        x0 = max(0, min(x0, fw - w))
    if h <= fh:
        y0 = max(0, min(y0, fh - h))
    return [x0, y0, w, h]


def page_header(c, kick, parts, kcolor=AMBER, size=60):
    kicker(c, kick, 120, 110, kcolor)
    runs(c, parts, 120, 156, 1680, size, 1.04)


def footer(c, n):
    text(c, f"NearMiss · {n}/8", 1860, 40, "Mono", 14, HexColor("#78716C"), anchor="right")


# ------------------------------------------------------------ slides

def slide1(c):
    hero = asset("hero/nearmiss-hero.jpg")
    rect(c, 0, 0, W, H, fill=INK)
    if hero:
        image_cover(c, hero, 0, 0, W, H)
    shade(c, 0.25, 0.95)
    text(c, "Illustrative image · not analyzed footage", 1860, BAND_TOP - 8 - 18, "Mono", 18, MUTED, anchor="right")
    freeze_t = 3.45
    ida, idb = E1["track_ids"]
    intersection(c, 760, 110, 1040, 585, [0, 0, 960, 540], freeze_t, {ida: AMBER, idb: AMBER}, trail_from=1.6,
                 rings=[(E1["conflict_point"], 26, CORAL)], saturation=0.35)
    x = 776
    x += tag(c, "Synthetic demo", x, 126, solid=True) + 10
    tag(c, "Scripted tracks · nearmiss/demo.py", x, 126)
    tw = pdfmetrics.stringWidth(f"FRAME {round(freeze_t * FPS):03d} · {clock(freeze_t)}".upper(), "Mono-Medium", 18) + 2 * 20 + 24
    tag(c, f"Frame {round(freeze_t * FPS):03d} · {clock(freeze_t)}", 1782 - tw, 524, CORAL)
    text(c, f"car #{idb} brakes and stops short. No contact.", 1782, 568, "Sans", 26, WHITE, anchor="right")
    text(c, f"The warning came first: {E1['first_alert_clock']} · {E1['severity']}", 1782, 604, "Sans", 26, AMBER, anchor="right")
    text(c, f"arrival gap {E1['arrival_gap_seconds']:.2f}{NB}s, measured at {E1['measurement']['clock']}", 1782, 640, "Sans", 26, AMBER, anchor="right")
    runs(c, [("A near miss disappears", "Sans-Semi", WHITE), ("in seconds.", "Serif-Italic", WHITE)], 120, 708, 1700, 104)
    text(c, "Its evidence shouldn’t.", 120, 830, "Serif-Italic", 124, CORAL)
    footer(c, 1)


def slide2(c):
    rect(c, 0, 0, W, H, fill=INK)
    hero = asset("hero/nearmiss-hero.jpg")
    if hero:
        image_cover(c, hero, 0, 0, W, H)
    rect(c, 0, 0, W, H, fill=INK, alpha=0.88)
    page_header(c, "What NearMiss does", [("Turns fixed-camera traffic footage into", "Sans-Semi", WHITE), ("evidence a person can check.", "Serif-Italic", AMBER)], size=84)
    steps = [("Predict", "Projects tracked paths and flags potential conflicts."),
             ("Detect", "Separately screens for contact plus a motion response."),
             ("Verify", "A person reviews the source frame and clip."),
             ("Notify", "Confirmation creates one local, simulated notice.")]
    colw = (1680 - 3 * 28) / 4
    rect(c, 120, 418, 1680, 3, fill=LINE)
    for i, (name, copy) in enumerate(steps):
        x = 120 + i * (colw + 28)
        rect(c, x, 420, colw, 3, fill=CORAL if i == 2 else AMBER)
        text(c, f"0{i + 1}", x, 446, "Mono", 22, MUTED)
        text(c, name, x, 478, "Sans-Semi", 44)
        para(c, copy, x, 538, colw - 10, "Sans", 28, MUTED, 1.35)
    c.saveState()
    c.setFillColor(AMBER)
    c.circle(120 + 1680, Y(419.5), 8.5, stroke=0, fill=1)
    c.restoreState()
    kicker(c, "Built by", 120, 690, MUTED)
    runs(c, [("Srivibhav Padakandla", "Serif-Italic", WHITE), ("·", "Sans", WHITE), ("Aadi Shukla", "Serif-Italic", WHITE)], 120, 730, 900, 64)
    kicker(c, "Who it is for", 1060, 690, MUTED)
    para(c, "People who review intersections: safety staff, and neighbors preparing a street-safety conversation.", 1060, 730, 740, "Sans", 34, WHITE, 1.35)
    w = tag(c, "Synthetic demo", 120, 920, solid=True)
    para(c, "Every app scene in this talk uses NearMiss’s labeled demo: generated footage, scripted tracks. No real place, no real crash.",
         120 + w + 20, 918, 1680 - w - 20, "Sans", 28, WHITE, 1.3)
    footer(c, 2)


def slide3(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "How a warning is earned", [("Two projected arrival times.", "Sans-Semi", WHITE), ("One gap.", "Serif-Italic", AMBER)])
    # Everything here is the representative measurement row (not the first alert):
    # both road users, both projection origins and the ETAs/gap come from that frame.
    ida, idb = E1["track_ids"]
    m = E1["measurement"]
    t = m["seconds"]
    cp = E1["conflict_point"]
    corners = [pt for x1, y1, x2, y2 in m["boxes"].values() for pt in ((x1, y1), (x2, y2))]
    intersection(c, 120, 330, 900, 640, fit_view([*corners, cp], 56, 900 / 640), t, {ida: AMBER, idb: AMBER}, trail_from=t - 0.8,
                 dashed=[(m["anchors"][str(ida)], cp, AMBER), (m["anchors"][str(idb)], cp, AMBER)],
                 rings=[(cp, 12, CORAL)])
    x = 136
    x += tag(c, "Synthetic demo", x, 346, solid=True) + 10
    tag(c, f"Diagram · measurement frame {m['frame']} · {m['clock']}", x, 346)
    arr = arrivals()
    side = 1080
    if arr:
        text(c, f"car #{ida} reaches the shared point in {arr[0]:.2f}{NB}s", side, 330, "Mono", 30)
        text(c, f"car #{idb} reaches it in {arr[1]:.2f}{NB}s", side, 378, "Mono", 30)
    text(c, f"arrival gap {E1['arrival_gap_seconds']:.2f}{NB}s → {E1['severity']}", side, 426, "Mono", 30, CORAL)
    text(c, f"Measured at {m['clock']} (frame{NB}{m['frame']}). First alert {E1['first_alert_clock']} (frame{NB}{E1['first_alert_frame']}).",
         side, 478, "Mono", 19, MUTED)
    s = M["settings"]
    hi, me, lo = s["high_time_gap_seconds"], s["medium_time_gap_seconds"], s["low_time_gap_seconds"]
    rw = 720
    X = lambda v: side + v / lo * rw  # noqa: E731
    ry = 556
    rect(c, side, ry + 34, X(hi) - side, 26, fill=CORAL)
    rect(c, X(hi), ry + 34, X(me) - X(hi), 26, fill=AMBER)
    rect(c, X(me), ry + 34, X(lo) - X(me), 26, fill=HexColor("#57534E"))
    text(c, f"HIGH ≤ {hi:.2f} s", (side + X(hi)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    text(c, f"MEDIUM ≤ {me:.2f} s", (X(hi) + X(me)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    text(c, f"LOW ≤ {lo:.2f} s", (X(me) + X(lo)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    mx = X(E1["arrival_gap_seconds"])
    rect(c, mx, ry, 4, 70, fill=WHITE)
    text(c, f"gap {E1['arrival_gap_seconds']:.2f} s", mx + 12, ry - 6, "Mono-Medium", 22)
    image_crop(c, "captures/warning.png", side, 736, 720, 138, 1280, -350, -196,
               caption="Actual app · Analysis → “Why each warning was raised”")
    text(c, "Image-space pixels and constant-velocity projection. Not a measured speed, distance or collision probability.", 120, BAND_TOP - 8 - 20, "Sans", 20, MUTED)
    footer(c, 3)


def slide4(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "Inspect the source", [("Every flag points back to", "Sans-Semi", WHITE), ("the exact frame.", "Serif-Italic", AMBER)])
    s = 1616 / 1600
    # deck.css scales .source-media to 0.9 about its top-left corner to clear the HUD band.
    c.saveState()
    c.translate(120, Y(330))
    c.scale(0.9, 0.9)
    c.translate(-120, -Y(330))
    page.update(oy=330, k=0.9)
    image_crop(c, "captures/investigation.png", 120, 330, 1160, 653, 1616, -436, 0, radius=14)
    rect(c, 120 + (815 - 432) * s - 8, 330 + 586 * s - 8, 380 * s + 16, 18 * s + 16, stroke=AMBER, width=4, radius=8)
    duration = M["source"]["frame"]["duration_seconds"]
    items = [(e["first_alert_seconds"], e["first_alert_clock"], e["severity"], CORAL if e["severity"] == "HIGH" else AMBER,
              f"{e['explanation']['pattern_label']} · " + " / ".join(f"{cl} #{tid}" for cl, tid in zip(e["classes"], e["track_ids"])),
              f"time headway {e['time_headway_seconds']:.2f} s" if e["geometry"] == "same_direction_following" and e["time_headway_seconds"] is not None
              else f"arrival gap {e['arrival_gap_seconds']:.2f} s") for e in M["events"]]
    items += [(i["first_contact_seconds"], i["first_contact_clock"], "Contact", CORAL, "Suspected contact · vehicles #" + " / #".join(map(str, i["track_ids"])),
               f"{i['evidence_signal_count']} supporting signals · needs review") for i in M["incidents"]]
    items.sort(key=lambda it: it[0])
    ty = 330 + 653 + 16
    rect(c, 120, ty + 18, 1160, 4, fill=LINE, radius=2)
    rect(c, 120, ty + 18, 1160 * E1["first_alert_seconds"] / duration, 4, fill=WHITE, radius=2)
    for t, *_rest in items:
        color = _rest[2]
        cx = 120 + 1160 * t / duration
        c.saveState()
        c.setFillColor(INK)
        c.setStrokeColor(color)
        c.setLineWidth(3)
        c.circle(cx, Y(ty + 20), 11, stroke=1, fill=1)
        c.restoreState()
    text(c, "Actual app · Investigation · frame view with stored observations", 120, ty + 46, "Mono", 17, MUTED)
    c.restoreState()
    page.update(oy=0, k=1.0)
    y = 330
    for _t, clk, sev, color, title, detail in items:
        rect(c, 1320, y, 480, 112, fill=CARD, radius=6)
        rect(c, 1320, y, 4, 112, fill=color)
        text(c, clk, 1340, y + 12, "Mono", 22)
        tag(c, sev, 1800 - 16 - (pdfmetrics.stringWidth(sev.upper(), "Mono-Medium", 14) + 2 * (len(sev) - 1) + 24), y + 10, color, size=14)
        para(c, title, 1340, y + 46, 450, "Sans", 20, WHITE, 1.25)
        text(c, detail, 1340, y + 80, "Sans", 18, MUTED)
        y += 124
    para(c, f"Jump to evidence opens frame {round(E1['first_alert_seconds'] * FPS)} ({E1['first_alert_clock']}), the first alert, with tracks "
            f"#{' and #'.join(map(str, E1['track_ids']))} selected. Boxes are stored observations; nothing is re-detected.",
         1320, y + 10, 480, "Sans", 21, WHITE, 1.4)
    footer(c, 4)


def slide5(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "Human review", [("Contact needs more than overlap.", "Sans-Semi", WHITE), ("A person decides.", "Serif-Italic", AMBER)], kcolor=CORAL)
    if INC:
        a, b = INC["track_ids"]
        intersection(c, 120, 330, 980, 640, [300, 110, 290, 187], INC["first_contact_seconds"], {a: CORAL, b: CORAL},
                     trail_from=INC["first_contact_seconds"] - 1.4, rings=[(INC["contact_point"], 16, CORAL)])
        x = 136
        x += tag(c, "Synthetic demo", x, 346, solid=True) + 10
        tag(c, "Diagram · half speed", x, 346)
        label = f"First contact {INC['first_contact_clock']}"
        lw = pdfmetrics.stringWidth(label.upper(), "Mono-Medium", 18) + 2 * (len(label) - 1) + 24
        tag(c, label, 1100 - 16 - lw, 970 - 16 - 32, CORAL, solid=True)
        y = 330
        for sname in INC["detection_signals"]:
            c.saveState()
            c.setFillColor(CORAL)
            c.circle(1156, Y(y + 18), 6.5, stroke=0, fill=1)
            c.restoreState()
            text(c, SIGNALS.get(sname, sname.replace("_", " ")), 1176, y + 2, "Sans", 28)
            y += 44
        if LINKED:
            y = para(c, f"Prediction {LINKED['event_id']} came {INC['prediction_lead_seconds']:.2f} s before first contact, but does not decide this. "
                        "Correlated measurements, not independent votes.", 1176, y + 4, 620, "Sans", 22, AMBER, 1.35)
    else:
        text(c, "No suspected incident in this run.", 120, 400, "Sans", 36)
        y = 330
    dy = y + 20
    colw = (650 - 24) / 3
    for i, (name, sub) in enumerate((("Confirm", "creates one local, simulated notice"), ("Dismiss", "no notice"), ("Uncertain", "no notice"))):
        x = 1150 + i * (colw + 12)
        rect(c, x, dy, colw, 96, fill=HexColor("#1A1610") if i == 0 else None, stroke=AMBER if i == 0 else LINE, width=1.5, radius=8)
        text(c, name, x + 14, dy + 12, "Sans-Semi", 24)
        para(c, sub, x + 14, dy + 46, colw - 24, "Sans", 17, MUTED, 1.25)
    image_crop(c, "captures/incidents.png", 1150, dy + 116, 650, 170, 1733, -1083, -639,
               caption="Actual app · Incidents (review recorded on the synthetic demo)")
    footer(c, 5)


def brief_excerpt():
    if not BRIEF:
        return None
    lines = BRIEF.split("\n")
    title = next((l for l in lines if l.startswith("# ")), "")[2:]
    quote = next((l for l in lines if l.startswith(">")), "").lstrip("> ").strip()

    def section(name):
        out, on = [], False
        for l in lines:
            if l.startswith("## "):
                on = l == f"## {name}"
                continue
            if on and l.strip():
                out.append(l)
        return out

    clean = lambda s: re.sub(r"\\(.)", r"\1", s).replace("**", "")  # noqa: E731
    first_para = lambda name: next((l for l in section(name) if not l.startswith(("-", "|", ">"))), "")  # noqa: E731
    bullets = [l[2:] for l in section("What this brief does not claim") if l.startswith("- ")][:3]
    return clean(title), clean(quote), clean(first_para("Human review")), clean(first_para("Simulated dispatch")), [clean(b) for b in bullets]


def slide6(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "From evidence to follow-up", [("One local notice, a plan, and", "Sans-Semi", WHITE), ("a brief anyone can check.", "Serif-Italic", AMBER)])
    colw = (1680 - 80) / 3
    x1, x2, x3 = 120, 120 + colw + 40, 120 + 2 * (colw + 40)
    image_crop(c, "captures/dispatch.png", x1, 330, colw, 560, 1500, -405, -173, caption="Actual app · Dispatch · local simulation, nothing sent")
    cr = M["streetlab"]["crossing"]
    a = cr["assumptions"]
    kicker(c, "Street Lab · crossing-time arithmetic", x2, 330, AMBER, 18)
    max_s = max(r["current_seconds"] for r in cr["rows"])
    y = 370
    for r in cr["rows"]:
        text(c, f"{r['walker']} · {r['speed']} {a['unit']}/s", x2, y, "Sans", 24)
        for label, value, color in (("now", r["current_seconds"], HexColor("#78716C")), ("hypothetical", r["proposed_seconds"], AMBER)):
            y += 40
            bw = value / max_s * 330
            rect(c, x2, y, bw, 30, fill=color, radius=3)
            text(c, f"{value} s {label}", x2 + bw + 12, y + 4, "Mono", 20)
        y += 64
    para(c, f"{a['current_distance']} → {a['proposed_distance']} {a['unit']} crossing · start-up {a['start_up_seconds']} s · placeholder assumptions", x2, y, colw, "Mono", 18, MUTED, 1.35)
    para(c, "Arithmetic on entered assumptions. Not a measured crash reduction.", x2, y + 60, colw, "Sans", 20, CORAL, 1.4)
    kicker(c, "Actual export · evidence brief (.md)", x3, 330, AMBER, 18)
    rect(c, x3, 366, colw, 560, fill=PAPER, radius=10)
    ex = brief_excerpt()
    if ex:
        title, quote, review, dispatch, bullets = ex
        clip(c, x3, 366, colw, 560, 10)
        yy = para(c, title, x3 + 26, 390, colw - 52, "Serif-Italic", 28, PAPER_INK, 1.15) + 6
        qh = len(simpleSplit(quote, "Sans", 15, colw - 80)) * 15 * 1.4 + 14
        rect(c, x3 + 26, yy, colw - 52, qh, fill=HexColor("#FBEBD0"))
        rect(c, x3 + 26, yy, 5, qh, fill=AMBER)
        para(c, quote, x3 + 40, yy + 7, colw - 80, "Sans", 15, PAPER_INK, 1.4)
        yy += qh + 12
        for head, body in (("Human review", review), ("Simulated dispatch", dispatch)):
            text(c, head, x3 + 26, yy, "Sans-Bold", 17, PAPER_INK)
            yy = para(c, body, x3 + 26, yy + 26, colw - 52, "Sans", 15, PAPER_INK, 1.4) + 8
        text(c, "What this brief does not claim", x3 + 26, yy, "Sans-Bold", 17, PAPER_INK)
        yy += 26
        for bl in bullets:
            yy = para(c, "• " + bl, x3 + 26, yy, colw - 52, "Sans", 15, PAPER_INK, 1.4)
        c.restoreState()
    else:
        text(c, "Host capture pending: brief.md", x3 + 26, 400, "Mono", 20, CORAL)
    para(c, "Street Lab’s community brief and the Analysis PDF report are separate exports.", x3, 940, colw, "Sans", 20, MUTED, 1.4)
    footer(c, 6)


def slide7(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "What we built · verified · have not proven",
                [("Open-source eyes.", "Sans-Semi", WHITE), ("Our own judgment layer.", "Serif-Italic", AMBER), ("Honest limits.", "Serif-Italic", CORAL)])
    total = 1680 - 2 * 56
    widths = [total * 1.15 / 3.15, total / 3.15, total / 3.15]
    xs = [120, 120 + widths[0] + 56, 120 + widths[0] + widths[1] + 112]
    t = M.get("tests")
    verified = [
        f"Automated tests: {re.sub(r' in [0-9.]+s$', '', t['summary'])} (local pytest, {t['run_at'][:10]})" if t else "Automated tests: not recorded for this build",
        f"Deterministic demo: ID {M['source']['video_id']}; {len(M['events'])} warnings and {len(M['incidents'])} suspected incident every run at default settings",
        "Annotated clip regenerated for this deck matches the app’s cached render byte for byte",
        "Synthetic label carried through frames, pages and exports",
        "Confirm, dismiss and acknowledge states covered by the tests (SQLite review record)",
    ]
    unproven = ["Accuracy on real-world footage has not been measured", "Image pixels only: no calibrated metres, speeds or probabilities",
                "No crash-reduction or safety-rating claim", "Dispatch is simulated; nothing leaves the computer", "One camera view, short clips"]
    cols = [
        ("Built", AMBER, [("Existing open source", ["Ultralytics YOLO: detects road users", "ByteTrack: keeps IDs across frames", "OpenCV, Streamlit, Plotly, ReportLab"]),
                          ("NearMiss custom logic", ["Trajectory prediction and conflict gates", "Same-direction following check", "Multi-signal suspected-collision detector",
                                                     "Evidence association and de-duplication", "Review record and simulated dispatch audit trail", "Investigation, briefs, Street Lab, run library"])]),
        ("Verified", GREEN, [(None, verified)]),
        ("Not yet proven", CORAL, [(None, unproven)]),
    ]
    for (title, color, groups), x, w in zip(cols, xs, widths):
        text(c, title.upper(), x, 330, "Mono-Medium", 26, color, spacing=3)
        rect(c, x, 372, w, 3, fill=color)
        y = 386
        for sub, items in groups:
            if sub:
                text(c, sub.upper(), x, y + 14, "Mono", 18, MUTED, spacing=2)
                y += 44
            for item in items:
                text(c, "•", x + 2, y + 6, "Sans", 26, WHITE)
                y = para(c, item, x + 24, y + 6, w - 24, "Sans", 24, WHITE, 1.3) + 6
    footer(c, 7)


def slide8(c):
    rect(c, 0, 0, W, H, fill=INK)
    hero = asset("hero/nearmiss-hero.jpg")
    if hero:
        image_cover(c, hero, 0, 0, W, H)
    rect(c, 0, 0, W, H, fill=INK, alpha=0.86)
    page_header(c, "Proposed next step", [("A supervised pilot", "Sans-Semi", WHITE), ("before any claims.", "Serif-Italic", AMBER)])
    colw = (1680 - 72) / 3
    for i, item in enumerate(["Permissioned footage from one fixed camera", "Compare NearMiss flags with human-labelled events to measure accuracy",
                              "Calibrate the camera view so pixels can become metres"]):
        x = 120 + i * (colw + 36)
        rect(c, x, 300, colw, 3, fill=AMBER)
        text(c, f"0{i + 1}", x, 322, "Mono", 22, MUTED)
        para(c, item, x, 360, colw, "Sans", 32, WHITE, 1.3)
    half = (1680 - 50) / 2
    kicker(c, "AI assistance", 120, 560, AMBER, 18)
    para(c, "OpenAI Codex and Anthropic Claude (Opus) assisted with writing, reviewing and testing code, and with building this deck. Results shown come from running the app and its tests.",
         120, 592, half, "Sans", 22, MUTED, 1.45)
    kicker(c, "Open source", 120 + half + 50, 560, AMBER, 18)
    para(c, "Ultralytics YOLO · ByteTrack · OpenCV · Streamlit · Plotly · ReportLab · GSAP · Inter, Instrument Serif, JetBrains Mono (OFL)",
         120 + half + 50, 592, half, "Sans", 22, MUTED, 1.45)
    runs(c, [("A near miss disappears", "Sans-Semi", WHITE), ("in seconds.", "Serif-Italic", WHITE), ("Its evidence shouldn’t.", "Serif-Italic", CORAL)], 120, 790, 1700, 64)
    text(c, "NearMiss · Srivibhav Padakandla · Aadi Shukla", 120, 880, "Sans", 30, MUTED)
    text(c, "Illustrative image · not analyzed footage", 1860, BAND_TOP - 8 - 18, "Mono", 18, MUTED, anchor="right")
    footer(c, 8)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(OUT), pagesize=(W / 2, H / 2))
    c.setTitle("NearMiss — 3-minute presentation (PDF backup)")
    c.setAuthor("Srivibhav Padakandla, Aadi Shukla")
    c.setSubject("Synthetic demo. All app scenes are the labeled NearMiss synthetic demonstration.")
    for n, draw in enumerate((slide1, slide2, slide3, slide4, slide5, slide6, slide7, slide8), 1):
        page.update(n=n, oy=0, k=1.0)
        c.saveState()
        c.scale(0.5, 0.5)
        draw(c)
        c.restoreState()
        c.showPage()
    c.save()
    print(f"wrote {OUT.relative_to(PRESENTATION.parent)}: 8 pages")
    print(f"assets used: {', '.join(sorted(used_assets))}")
    status = 0
    if missing_assets:
        print(f"MISSING assets: {', '.join(sorted(missing_assets))}")
        status = 1
    if band_overflows:
        print(f"HUD band overlap (content must end at y<={BAND_TOP}):\n  " + "\n  ".join(band_overflows))
        status = 1
    else:
        print(f"footer band clear: all content ends at y<={BAND_TOP} on all 8 pages")
    return status


if __name__ == "__main__":
    sys.exit(main())
