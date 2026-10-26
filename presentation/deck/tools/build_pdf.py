"""Eight-page PDF backup of the NearMiss deck, every reveal in its final state.

Editable source: layout mirrors presentation/deck/index.html + deck.css; all
numbers come from presentation/data/real-metrics.json (real footage, actual
NearMiss output, no new inference). Frames are exact-frame stills of the real
clip with that frame's stored boxes drawn over them; screenshots are the host's
captures of the live app on the same clip.

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
R = json.loads((PRESENTATION / "data" / "real-metrics.json").read_text(encoding="utf-8"))

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


# ------------------------------------------------------------ real frames

FR = R["source"]["frame"]
FW, FH, FPS = FR["width"], FR["height"], FR["fps"]
CASE, INC = R["case"], R["case_incident"]
IA, IB = CASE["track_ids"]
COUNTS = R["counts"]
SIGNALS = {
    "persistent_bounding_box_contact": "Persistent box contact",
    "significant_bounding_box_overlap": "Significant box overlap",
    "previously_converging_trajectories": "Converging before contact",
    "abrupt_motion_change": "Abrupt motion change",
    "sudden_deceleration": "Sudden deceleration",
    "stopped_after_contact": "Stopped after contact",
    "post_contact_track_loss": "Track lost after contact",
}
NB = " "  # keeps a number and its unit on one line
LOW_GREY = HexColor("#78716C")


def boxes_at(f):
    return R["frames"][f] if 0 <= f < len(R["frames"]) else []


def box_of(f, tid):
    return next((b for b in boxes_at(f) if b[0] == tid), None)


def fit_view(points, pad, aspect):
    """Same as DECK_SYNC.fitView in sync.js."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    if (x1 - x0) / (y1 - y0) < aspect:
        g = ((y1 - y0) * aspect - (x1 - x0)) / 2
        x0, x1 = x0 - g, x1 + g
    else:
        g = ((x1 - x0) / aspect - (y1 - y0)) / 2
        y0, y1 = y0 - g, y1 + g
    w, h = x1 - x0, y1 - y0
    if w <= FW:
        x0 = max(0, min(x0, FW - w))
    if h <= FH:
        y0 = max(0, min(y0, FH - h))
    return [x0, y0, w, h]


def real_frame(c, x, y, w, h, frame, view, focus, override=None, trail_frames=0, lines=(), rings=(), frozen=False):
    """Exact-frame still (OpenCV-decoded from the real clip) with the stored boxes of that frame.

    Mirrors realClip() in scenes.js: cover crop of `view`, faint boxes for every
    tracked row, focus tracks in colour with labels, optional trails/lines/rings.
    """
    from io import BytesIO

    from PIL import Image, ImageEnhance

    rel = R["assets"]["stills"][str(frame)].removeprefix("assets/")
    path = asset(rel)
    vx, vy, vw, vh = view
    k = max(w / vw, h / vh)
    ox, oy = x + (w - vw * k) / 2 - vx * k, y + (h - vh * k) / 2 - vy * k
    P = lambda px, py: (ox + px * k, oy + py * k)  # noqa: E731 - source px -> stage
    rect(c, x, y, w, h, fill=HexColor("#000000"), radius=14)
    clip(c, x, y, w, h, 14)
    if path:
        img = Image.open(path).convert("RGB")
        if frozen:
            img = ImageEnhance.Brightness(ImageEnhance.Color(img).enhance(0.45)).enhance(0.82)
        buf = BytesIO()
        img.save(buf, "JPEG", quality=90)
        buf.seek(0)
        c.drawImage(ImageReader(buf), ox, Y(oy + FH * k), FW * k, FH * k)
    rows = [list(b) for b in boxes_at(frame)]
    for tid, b in (override or {}).items():
        rows = [r for r in rows if r[0] != int(tid)] + [[int(tid), *b]]

    def line(a, b, color, width, alpha=1.0):
        c.saveState()
        c.setStrokeColor(color)
        c.setStrokeAlpha(alpha)
        c.setLineWidth(width)
        c.setLineCap(1)
        c.setLineJoin(1)
        (ax, ay), (bx, by) = P(*a), P(*b)
        c.line(ax, Y(ay), bx, Y(by))
        c.restoreState()

    for tid, x1, y1, x2, y2 in rows:
        if tid in focus:
            continue
        sx, sy = P(x1, y1)
        c.saveState()
        c.setStrokeColor(WHITE)
        c.setStrokeAlpha(0.42)
        c.setLineWidth(1.5)
        c.rect(sx, Y(sy + (y2 - y1) * k), (x2 - x1) * k, (y2 - y1) * k, stroke=1, fill=0)
        c.restoreState()
    for tid, color in focus.items():
        if trail_frames:
            pts = [((b[1] + b[3]) / 2, b[4]) for f in range(frame - trail_frames, frame + 1) if (b := box_of(f, tid))]
            for a, b in zip(pts, pts[1:]):
                line(a, b, color, 3, 0.8)
    for a, b, color in lines:
        line(a, b, color, 3.5)
    for at, r, color in rings:
        sx, sy = P(*at)
        c.saveState()
        c.setStrokeColor(color)
        c.setLineWidth(3.5)
        c.circle(sx, Y(sy), r, stroke=1, fill=0)
        c.restoreState()
    for tid, x1, y1, x2, y2 in rows:
        color = focus.get(tid)
        if not color:
            continue
        sx, sy = P(x1, y1)
        rect(c, sx, sy, (x2 - x1) * k, (y2 - y1) * k, stroke=color, width=3.5)
        label = f"{R['classes'][str(tid)]} #{tid}"
        c.saveState()
        obj = c.beginText()
        obj.setFont("Mono-Medium", 20)
        obj.setTextRenderMode(1)
        c.setStrokeColor(INK)
        c.setLineWidth(5)
        c.setLineJoin(1)
        obj.setTextOrigin(sx, Y(sy - 9))
        obj.textOut(label)
        c.drawText(obj)
        c.restoreState()
        c.saveState()
        c.setFillColor(color)
        obj = c.beginText()
        obj.setFont("Mono-Medium", 20)
        obj.setTextOrigin(sx, Y(sy - 9))
        obj.textOut(label)
        c.drawText(obj)
        c.restoreState()
    c.restoreState()
    rect(c, x, y, w, h, stroke=LINE, width=1, radius=14)
    occupy(y + h, f"real frame {frame}")


def tag_right(c, s, right, y, color=AMBER, solid=False, size=18):
    label = s.upper()
    w = pdfmetrics.stringWidth(label, "Mono-Medium", size) + 2 * (len(label) - 1) + 24
    return tag(c, s, right - w, y, color, solid, size)


def card(c, x, y, w, h, color=None):
    rect(c, x, y, w, h, fill=CARD, radius=6)
    if color is not None:
        rect(c, x, y, 4, h, fill=color)


def page_header(c, kick, parts, kcolor=AMBER, size=60):
    kicker(c, kick, 120, 110, kcolor)
    runs(c, parts, 120, 156, 1680, size, 1.04)


def footer(c, n):
    text(c, f"NearMiss · {n}/8 · real footage, experimental flags", 1860, 40, "Mono", 14, HexColor("#78716C"), anchor="right")


def sec(v, d=2):
    return f"{v:.{d}f}{NB}s"


# ------------------------------------------------------------ slides

def slide1(c):
    hero = asset("hero/nearmiss-hero.jpg")
    rect(c, 0, 0, W, H, fill=INK)
    if hero:
        image_cover(c, hero, 0, 0, W, H)
    shade(c, 0.25, 0.95)
    text(c, "Illustrative image · not analyzed footage", 1860, BAND_TOP - 8 - 18, "Mono", 18, MUTED, anchor="right")
    m1 = R["moments"]["slide1"]
    f = m1["freeze_frame"]
    real_frame(c, 760, 110, 1040, 585, f, [0, 0, FW, FH], {IA: AMBER, IB: AMBER}, frozen=True)
    x = 776
    x += tag(c, "Real footage", x, 126, solid=True) + 10
    tag(c, "Actual YOLO11n + ByteTrack boxes · experimental flags", x, 126)
    credit = "Footage: Mike Bird / Pexels"
    cw = pdfmetrics.stringWidth(credit, "Mono", 15) + 16
    rect(c, 776, 695 - 12 - 26, cw, 26, fill=INK, radius=4, alpha=0.72)
    text(c, credit, 784, 695 - 12 - 22, "Mono", 15, WHITE)
    lines = [f"Experimental {CASE['severity']} flag · car{NB}#{IA} / car{NB}#{IB}", "Ordinary traffic. Unverified: a person must check."]
    bw = max(pdfmetrics.stringWidth(s, "Sans", 26) for s in lines) + 32
    rect(c, 1782 - bw, 695 - 16 - 146, bw, 146, fill=INK, radius=8, alpha=0.8)
    tag_right(c, f"Frame {f} · {CASE['first_alert_clock']} · first alert", 1766, 695 - 16 - 134, CORAL)
    text(c, lines[0], 1766, 695 - 16 - 84, "Sans", 26, WHITE, anchor="right")
    text(c, lines[1], 1766, 695 - 16 - 48, "Sans", 26, AMBER, anchor="right")
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
    w = tag(c, "Real footage", 120, 920, solid=True)
    para(c, "Ordinary highway traffic (Mike Bird / Pexels), no incident labels. Boxes and flags are actual NearMiss output: experimental, unverified, human review required.",
         120 + w + 20, 906, 1680 - w - 20, "Sans", 28, WHITE, 1.35)
    footer(c, 2)


def slide3(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "How a warning is earned", [("Two projected arrival times.", "Sans-Semi", WHITE), ("One gap.", "Serif-Italic", AMBER)])
    # The representative measurement frame (not the first alert): both boxes, both
    # projection origins and the ETAs/gap come from that frame.
    m = CASE["measurement"]
    cp = CASE["conflict_point"]
    corners = [pt for x1, y1, x2, y2 in m["boxes"].values() for pt in ((x1, y1), (x2, y2))]
    view = fit_view([*corners, cp], 110, 900 / 640)
    real_frame(c, 120, 330, 900, 640, m["frame"], view, {IA: AMBER, IB: AMBER}, override=m["boxes"], trail_frames=round(0.8 * FPS),
               lines=[(m["positions"][str(t)], m["conflict_positions"][str(t)], AMBER) for t in (IA, IB)], rings=[(cp, 16, CORAL)])
    x = 136
    x += tag(c, "Real footage", x, 346, solid=True) + 10
    tag(c, f"Measurement frame {m['frame']} · {m['clock']}", x, 346)
    ea, eb = m["eta_seconds"]
    gap = CASE["arrival_gap_seconds"]
    side = 1080
    text(c, f"car #{IA} reaches the shared point in {sec(ea)}", side, 330, "Mono", 30)
    text(c, f"car #{IB} reaches it in {sec(eb)}", side, 378, "Mono", 30)
    text(c, f"arrival gap {sec(gap)} → {CASE['severity']}", side, 426, "Mono", 30, CORAL)
    stale = [f"#{tid} box from frame{NB}{f}" for tid, f in m["observed_frame"].items() if f != m["frame"]]
    when = (f"Measured on frame{NB}{m['frame']} ({m['clock']}). First alert frame{NB}{CASE['first_alert_frame']} ({CASE['first_alert_clock']})."
            + (f" {', '.join(stale)} (latest observation)." if stale else ""))
    yy = para(c, when, side, 478, 720, "Mono", 19, MUTED, 1.4)
    s = R["pipeline"]["settings"]
    hi, me, lo = s["high_time_gap_seconds"], s["medium_time_gap_seconds"], s["low_time_gap_seconds"]
    rw = 720
    X = lambda v: side + v / lo * rw  # noqa: E731
    ry = yy + 36
    rect(c, side, ry + 34, X(hi) - side, 26, fill=CORAL)
    rect(c, X(hi), ry + 34, X(me) - X(hi), 26, fill=AMBER)
    rect(c, X(me), ry + 34, X(lo) - X(me), 26, fill=HexColor("#57534E"))
    text(c, f"HIGH ≤ {hi:.2f} s", (side + X(hi)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    text(c, f"MEDIUM ≤ {me:.2f} s", (X(hi) + X(me)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    text(c, f"LOW ≤ {lo:.2f} s", (X(me) + X(lo)) / 2, ry + 72, "Mono", 18, MUTED, "center")
    mx = X(gap)
    rect(c, mx, ry, 4, 70, fill=WHITE)
    text(c, f"gap {gap:.2f} s", mx + 12, ry - 6, "Mono-Medium", 22)
    ex = CASE["explanation"]
    cy = ry + 150
    bullets = ex["bullets"][1:3]
    lines = simpleSplit(ex["headline"], "Sans-Bold", 21, 680)
    blines = [simpleSplit(b, "Sans", 19, 660) for b in bullets]
    ch = 28 + len(lines) * 29 + sum(len(b) for b in blines) * 26 + 8
    card(c, side, cy, 720, ch, CORAL)
    ty = para(c, ex["headline"], side + 18, cy + 14, 680, "Sans-Bold", 21, WHITE, 1.38) + 4
    for b in bullets:
        text(c, "•", side + 20, ty, "Sans", 19, MUTED)
        ty = para(c, b, side + 38, ty, 660, "Sans", 19, HexColor("#D6D3D1"), 1.38)
    text(c, "Actual explain_event() output · the app’s “Why each warning was raised” text", side, cy + ch + 10, "Mono", 15, MUTED)
    text(c, "Image pixels, constant-velocity projection: in perspective, two cars in one lane can “meet”. Not a measured speed, distance or probability.",
         120, BAND_TOP - 8 - 20, "Sans", 20, MUTED)
    footer(c, 3)


def slide4(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "Inspect the source", [("Every flag points back to", "Sans-Semi", WHITE), ("the exact frame.", "Serif-Italic", AMBER)])
    # deck.css scales .source-media to 0.9 about its top-left corner to clear the HUD band.
    c.saveState()
    c.translate(120, Y(330))
    c.scale(0.9, 0.9)
    c.translate(-120, -Y(330))
    page.update(oy=330, k=0.9)
    k = 1.028
    image_crop(c, "real/investigation.png", 120, 330, 1160, 653, 1440 * k, -306 * k, -250 * k, radius=14)
    rect(c, 120 + (732 - 306) * k - 10, 330 + (861 - 250) * k - 9, 276 * k + 20, 18 * k + 18, stroke=AMBER, width=4, radius=8)
    duration = FR["duration_seconds"]
    sev = lambda s: CORAL if s == "HIGH" else AMBER if s == "MEDIUM" else LOW_GREY  # noqa: E731
    marks = [(e["first_alert_seconds"], sev(e["severity"]), False) for e in R["events"]] + [(i["first_contact_seconds"], CORAL, True) for i in R["incidents"]]
    ty = 330 + 653 + 16
    rect(c, 120, ty + 18, 1160, 4, fill=LINE, radius=2)
    rect(c, 120, ty + 18, 1160 * CASE["first_alert_seconds"] / duration, 4, fill=WHITE, radius=2)
    for t, color, contact in sorted(marks, key=lambda m: m[0]):
        cx = 120 + 1160 * t / duration
        c.saveState()
        c.setFillColor(CORAL if contact else INK)
        c.setStrokeColor(color)
        c.setLineWidth(3)
        c.circle(cx, Y(ty + 20), 11, stroke=1, fill=1)
        c.restoreState()
    text(c, "Actual app · Investigation · original frame 34, tracks #20 and #22, stored observations only", 120, ty + 46, "Mono", 17, MUTED)
    c.restoreState()
    page.update(oy=0, k=1.0)
    bs = COUNTS["warnings_by_severity"]
    y = 330
    card(c, 1320, y, 480, 126)
    for i, (n, label, sub) in enumerate(((COUNTS["warnings"], "warning candidates", f"{bs['HIGH']} HIGH · {bs['MEDIUM']} MEDIUM · {bs['LOW']} LOW"),
                                         (COUNTS["suspected_incidents"], "suspected contacts", f"{COUNTS['confirmed']} confirmed"),
                                         (COUNTS["track_ids"], "tracker IDs", "not a vehicle count"))):
        ly = y + 10 + i * 36
        nw = text(c, str(n), 1336, ly, "Mono-Medium", 26)
        lw = text(c, label, 1336 + nw + 10, ly + 3, "Sans", 21)
        text(c, sub, 1336 + nw + lw + 18, ly + 6, "Sans", 17, MUTED)
    y += 138
    cap = R["capture_event"]
    cards = [(cap["first_alert_clock"], cap["severity"], sev(cap["severity"]), f"{cap['pattern_label']} · car #{cap['track_ids'][0]} / car #{cap['track_ids'][1]}", "Opened in Investigation (frame 34)"),
             (CASE["first_alert_clock"], CASE["severity"], sev(CASE["severity"]), f"{CASE['pattern_label']} · car #{IA} / car #{IB}", f"arrival gap {sec(CASE['arrival_gap_seconds'])} · slide 3"),
             (INC["first_contact_clock"], "Contact", CORAL, f"Suspected contact · car #{INC['track_ids'][0]} / car #{INC['track_ids'][1]}", f"{INC['evidence_signal_count']} signals · unverified · slide 5")]
    for clk, tg, color, title, detail in cards:
        card(c, 1320, y, 480, 112, color)
        text(c, clk, 1340, y + 12, "Mono", 22)
        tag_right(c, tg, 1800 - 16, y + 10, color, size=14)
        para(c, title, 1340, y + 46, 450, "Sans", 20, WHITE, 1.25)
        text(c, detail, 1340, y + 80, "Sans", 18, MUTED)
        y += 124
    para(c, f"Investigation redraws the stored boxes on the original frame; nothing is re-detected. Shown: frame{NB}34 for cars #20 and #22, "
            f"whose {cap['severity']} flag first fired on frame{NB}{cap['first_alert_frame']}.", 1320, y + 6, 480, "Sans", 21, WHITE, 1.4)
    footer(c, 4)


def slide5(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "Human review", [("Contact needs more than overlap.", "Sans-Semi", WHITE), ("A person decides.", "Serif-Italic", AMBER)], kcolor=CORAL)
    f0 = R["moments"]["slide5"]["freeze_frame"]
    corners = [pt for tid in INC["track_ids"] if (b := box_of(f0, tid)) for pt in ((b[1], b[2]), (b[3], b[4]))]
    view = fit_view([*corners, INC["contact_point"]], 120, 980 / 640)
    a, b = INC["track_ids"]
    real_frame(c, 120, 330, 980, 640, f0, view, {a: CORAL, b: CORAL}, trail_frames=12, rings=[(INC["contact_point"], 18, CORAL)], frozen=True)
    x = 136
    x += tag(c, "Real footage", x, 346, solid=True) + 10
    tag(c, "Half speed · stored boxes", x, 346)
    tag_right(c, f"First box contact · frame {f0} · {INC['first_contact_clock']}", 1100 - 16, 970 - 16 - 32, CORAL, solid=True)
    y = 330
    for sname in INC["detection_signals"]:
        c.saveState()
        c.setFillColor(CORAL)
        c.circle(1156, Y(y + 16), 6.5, stroke=0, fill=1)
        c.restoreState()
        text(c, SIGNALS.get(sname, sname.replace("_", " ")), 1176, y + 2, "Sans", 25)
        y += 38
    if INC["associated_prediction_event_id"]:
        y = para(c, f"Warning {INC['associated_prediction_event_id']} came {sec(INC['prediction_lead_seconds'])} before first contact. "
                    "Correlated measurements, not independent votes.", 1176, y + 2, 624, "Sans", 20, AMBER, 1.35)
    y += 16
    secs = INC["contact_persistence_frames"] / FPS
    read = (f"Box “contact” lasted {INC['contact_persistence_frames']} frames ({secs:.1f}{NB}s). #{IB} is the nearer car in the same lane, "
            f"partly hiding #{IA}: overlap from perspective. It looks like queued traffic, not contact.")
    status = f"App: {COUNTS['suspected_incidents']} candidates Uncertain · {COUNTS['confirmed']} confirmed · {COUNTS['notices']} notices"
    rl = simpleSplit(read, "Sans", 21, 610)
    sl = simpleSplit(status, "Mono", 17, 610)
    rh = 12 + 22 + len(rl) * 29.4 + 6 + len(sl) * 22 + 12
    card(c, 1150, y, 650, rh, AMBER)
    text(c, "OUR READING OF THE FRAME · NOT A RECORDED REVIEW", 1168, y + 12, "Mono-Medium", 15, AMBER, spacing=2)
    yy = para(c, read, 1168, y + 34, 610, "Sans", 21, WHITE, 1.4)
    para(c, status, 1168, yy + 6, 610, "Mono", 17, MUTED, 1.3)
    y += rh + 16
    image_crop(c, "real/incidents.png", 1150, y, 360, 216, 1440, -1046, -340,
               caption="Actual app · Incidents review controls on this clip")
    footer(c, 5)


def brief_excerpt():
    brief = R.get("brief")
    if not brief:
        return None
    lines = brief.split("\n")
    title = next((l for l in lines if l.startswith("# ")), "")[2:]

    def section(name):
        out, on = [], False
        for l in lines:
            if l.startswith("## "):
                on = l == f"## {name}"
                continue
            if on and l.startswith("- "):
                out.append(l[2:])
        return out

    clean = lambda s: re.sub(r"\s*\(https?:[^)]*\)", "", re.sub(r"\\(.)", r"\1", s)).replace("**", "")  # noqa: E731
    credit = next((l[2:] for l in lines[:12] if l.startswith("- Real traffic footage")), "")
    summary = [l for l in section("Evidence summary") if re.match(r"^(Vehicles|Potential|Suspected)", l)]
    return clean(title), clean(credit), [clean(l) for l in summary], [clean(l) for l in section("Boundaries")[:2]]


def slide6(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "From evidence to follow-up", [("No confirmation, no notice.", "Sans-Semi", WHITE), ("A plan anyone can check.", "Serif-Italic", AMBER)])
    colw = (1680 - 80) / 3
    x1, x2, x3 = 120, 120 + colw + 40, 120 + 2 * (colw + 40)
    kicker(c, "Dispatch · only after Confirm", x1, 330, AMBER, 18)
    gy = 366
    card(c, x1, gy, colw, 214)
    cx = x1 + 20
    for i, (label, color) in enumerate((("Candidate", LINE), ("Person confirms", CORAL), ("Local notice", LINE))):
        lw = pdfmetrics.stringWidth(label, "Sans", 19) + 18
        if cx + lw > x1 + colw - 16:
            cx, gy = x1 + 20, gy + 46
        rect(c, cx, gy + 18, lw, 36, stroke=color, width=1.5, radius=6)
        text(c, label, cx + 9, gy + 25, "Sans", 19)
        cx += lw + 8
        if i < 2:
            cx += text(c, "→", cx, gy + 25, "Sans", 19, MUTED) + 8
    gy = 366
    text(c, "Simulated: nothing leaves the computer.", x1 + 20, gy + 112, "Sans", 19, MUTED)
    rect(c, x1 + 20, gy + 146, colw - 40, 1, fill=LINE)
    for i, (n, label) in enumerate(((COUNTS["suspected_incidents"], "candidates"), (COUNTS["confirmed"], "confirmed"), (COUNTS["notices"], "notices"))):
        bx = x1 + 20 + i * (colw - 40) / 3
        text(c, str(n), bx, gy + 152, "Mono-Medium", 44)
        text(c, label, bx + 34 * len(str(n)) + 4, gy + 172, "Sans", 18, MUTED)
    image_crop(c, "real/streetlab.png", x1, gy + 240, colw, 112, 792, -185, -383, caption="Actual app · Street Lab summary for this clip")
    cr = R["streetlab"]["crossing"]
    a = cr["assumptions"]
    kicker(c, "Street Lab · crossing arithmetic", x2, 330, AMBER, 18)
    max_s = max(r["current_seconds"] for r in cr["rows"])
    y = 370
    for r in cr["rows"]:
        text(c, f"{r['walker']} · {r['speed']} {a['unit']}/s", x2, y, "Sans", 24)
        for label, value, color in (("now", r["current_seconds"], LOW_GREY), ("hypothetical", r["proposed_seconds"], AMBER)):
            y += 40
            bw = value / max_s * 330
            rect(c, x2, y, bw, 30, fill=color, radius=3)
            text(c, f"{value} s {label}", x2 + bw + 12, y + 4, "Mono", 20)
        y += 64
    y = para(c, f"Stated assumptions: {a['current_distance']} → {a['proposed_distance']} {a['unit']} crossing · start-up {a['start_up_seconds']} s", x2, y, colw, "Mono", 18, MUTED, 1.4)
    para(c, "Arithmetic on entered assumptions. Not a road-safety measurement or crash reduction.", x2, y + 14, colw, "Sans", 20, CORAL, 1.4)
    kicker(c, "Actual export · community brief", x3, 330, AMBER, 18)
    rect(c, x3, 366, colw, 560, fill=PAPER, radius=10)
    ex = brief_excerpt()
    if ex:
        title, credit, summary, bounds = ex
        clip(c, x3, 366, colw, 560, 10)
        yy = para(c, title, x3 + 26, 390, colw - 52, "Serif-Italic", 30, PAPER_INK, 1.15) + 6
        qh = len(simpleSplit(credit, "Sans", 16, colw - 80)) * 16 * 1.45 + 14
        rect(c, x3 + 26, yy, colw - 52, qh, fill=HexColor("#FBEBD0"))
        rect(c, x3 + 26, yy, 5, qh, fill=AMBER)
        para(c, credit, x3 + 40, yy + 7, colw - 80, "Sans", 16, PAPER_INK, 1.45)
        yy += qh + 12
        for head, items in (("Evidence summary", summary), ("Boundaries", bounds)):
            text(c, head, x3 + 26, yy, "Sans-Bold", 19, PAPER_INK)
            yy += 28
            for item in items:
                yy = para(c, "• " + item, x3 + 26, yy, colw - 52, "Sans", 17, PAPER_INK, 1.45) + 4
            yy += 8
        c.restoreState()
    else:
        text(c, "Host capture pending: community-brief.md", x3 + 26, 400, "Mono", 20, CORAL)
    para(c, "Downloaded from Street Lab on this clip; no review decisions changed.", x3, 940, colw, "Sans", 20, MUTED, 1.4)
    footer(c, 6)


def slide7(c):
    rect(c, 0, 0, W, H, fill=INK)
    page_header(c, "What we built · verified · have not proven",
                [("Open-source eyes.", "Sans-Semi", WHITE), ("Our own judgment layer.", "Serif-Italic", AMBER), ("Honest limits.", "Serif-Italic", CORAL)])
    total = 1680 - 2 * 56
    widths = [total * 1.15 / 3.15, total / 3.15, total / 3.15]
    xs = [120, 120 + widths[0] + 56, 120 + widths[0] + widths[1] + 112]
    t = R.get("tests")
    verified = [
        ((f"All {m.group(1)} automated tests pass" if t["exit_code"] == 0 and (m := re.match(r"(\d+) passed", t["summary"])) else f"pytest: {re.sub(r' in [0-9.]+s.*$', '', t['summary'])}")
         + f" (local, {t['run_at'][:10]}). They check code behaviour, not detector accuracy" if t else "Automated tests: not recorded for this build"),
        f"Replay from the cached tracks reproduces the app’s {COUNTS['warnings']} warnings and {COUNTS['suspected_incidents']} contact candidates exactly",
        "Clip, tracks and metadata bound by SHA-256 in the app manifest; the deck checks them",
        "Real-footage label and credit carried on frames, pages and exports",
        "Confirm, dismiss and uncertain states covered by tests (SQLite review record)",
    ]
    unproven = [
        "Accuracy on real footage: not measured. This clip has no ground-truth labels",
        f"All {COUNTS['warnings']} warnings and {COUNTS['suspected_incidents']} contact candidates are unverified; perspective and occlusion cause false alarms",
        f"{COUNTS['track_ids']} tracker IDs are not a vehicle count",
        "Image pixels only: no metres, speeds or probabilities",
        "No crash-reduction claim. Dispatch is simulated",
    ]
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
                text(c, "•", x + 2, y + 6, "Sans", 24, WHITE)
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
    kicker(c, "Footage · open source", 120 + half + 50, 560, AMBER, 18)
    para(c, "“Traffic Flow In The Highway”, Mike Bird / Pexels (Pexels License). Ultralytics YOLO · ByteTrack · OpenCV · Streamlit · Plotly · ReportLab · GSAP · Inter, Instrument Serif, JetBrains Mono (OFL)",
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
    c.setSubject("Real footage (Mike Bird / Pexels, Traffic Flow In The Highway, Pexels License) with experimental NearMiss predictions. "
                 "Ordinary unlabelled traffic: every warning and contact candidate is unverified; human review required.")
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
