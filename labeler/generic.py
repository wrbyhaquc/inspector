"""Generic screen rules, configured entirely on the state-definition page (no code per state).

  color_ratio  share of pixels in one region whose colour falls in any of the given HSV ranges
               ratio >= high_min -> high_value;  ratio <= low_max -> low_value;  in between -> undecided
  template     every class has reference crops of the region (made on the state-definition page); the frame's
               region is compared with each (normalised cross-correlation, +-search px) -> the most similar
               class, if the best score is high enough and clearly ahead of the best other class.
               params.fallback (optional): the class to answer when nothing is similar enough. For things that are
               either there or not (an error window, a dialog), give references only for "there", fall back to "not".

  digits       read a number (a "number" state): pixels of the text colour (params.colors, like color_ratio) are cut
               into characters (columns without text between them); each is compared with the characters taught on
               the state-definition page (references whose value is the character: 0-9 . , / % - :). The text
               becomes a number: params.part = "all" (the whole, commas dropped) | "left" / "right" (of a "/", e.g.
               "1250/2000"). A character that looks like none of them (score < params.match_min) -> undecided.
               A mark much shorter than the digits is told by its place and shape, untaught (small_char()): "." at
               the bottom of the line, "," reaching below it, "-" across the middle; any other one is a speck.

  bar          how full a bar is (a "ratio" state: a progress bar, a water level, a battery): the region is the whole bar,
               from where it starts filling (0%) to where it is full (100%). params.dir = the way it fills: "right"
               (from the left, default) | "left" | "up" (from the bottom) | "down". The fill's colour is taken where
               the bar starts (params.fill = "auto": a bar that turns red on a warning or grey still reads), or
               given as colours (params.colors, like color_ratio). White / pale text on the bar (the "45 / 100") is
               left out (params.ignore_text, text = saturation <= 80 and value >= params.text_v, default 150).
               The end is the cut with the most filled columns before it and empty ones after it. Undecided rather than a
               wrong number when: the start cannot be told, the bar looks washed out (mostly text-like pixels, e.g.
               an error screen), too few columns can be told, or the fill colour shows up again past the end (a
               see-through bar over a scene of the same colour). The fill must be about as bright as where it starts
               and as vivid (params.min_vivid, default 0.75 of its saturation; a grey fill: params.min_bright, 0.8 of
               its brightness): the empty part of many bars is the same colour, only faded or dark.
               A bar that starts dark is undecided (params.dark_start = "unsure", default) or empty ("empty": 0).
               A slanted bar (a parallelogram): params.slant = how many pixels its top row sits further along than
               its bottom row (a vertical bar: its left column than its right one); the region is the bottom row's
               (right column's) extent, and each row is read shifted by its part of the slant.

Optional for all: params.gate_state = another state id. When that state is undecided or "hidden" in the same
frame (e.g. a panel covers the status bar), this state is "hidden" too (or undecided if it has no "hidden" class).

Colours use Pillow's HSV scale: hue, saturation and value are all 0-255 (hue 0 = red, 43 = yellow, 85 = green,
170 = blue). A hue range with lo > hi wraps around red (e.g. [245, 10]).

Reference crops live in <data_root>\\meta\\rule_templates\\<state id>\\ with index.json {file: {value, frame, box, created}}."""
import atomic
import hashlib
import json
import os
import time

import numpy as np
from PIL import Image
from i18n import N_, _

try:
    import cv2                                   # optional: fast template matching
except ImportError:
    cv2 = None

KINDS = {"color_ratio": N_("顏色比例"), "template": N_("參考圖比對"), "digits": N_("讀數字"), "bar": N_("長條比例")}
BAR_DIRS = {"right": N_("由左往右填滿"), "left": N_("由右往左填滿"), "up": N_("由下往上填滿"), "down": N_("由上往下填滿")}
CHARS = "0123456789.,/%-:"
PARTS = {"all": N_("整段數字"), "left": N_("「/」左邊"), "right": N_("「/」右邊")}
GLYPH_SIZE = (12, 18)          # characters are compared at this size (w, h)
FEATURES = {"gray": N_("灰階(看形狀)"), "color": N_("彩色(形狀和顏色)"), "minch": N_("最暗通道(不受背景顏色影響)")}


class Unfinished(ValueError):
    """A color-ratio rule whose thresholds / classes are not set yet (it can still be previewed)."""


# ---------------------------------------------------------------- colour ratio

def color_mask(hsv, colors):
    """hsv: H x W x 3 int array (Pillow scale) -> bool mask of pixels inside any range."""
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = np.zeros(h.shape, bool)
    for c in colors:
        hl, hh = c.get("h", [0, 255])
        hm = (h >= hl) & (h <= hh) if hl <= hh else (h >= hl) | (h <= hh)
        sl, sh = c.get("s", [0, 255])
        vl, vh = c.get("v", [0, 255])
        m |= hm & (s >= sl) & (s <= sh) & (v >= vl) & (v <= vh)
    return m


def crop(img, box):
    x, y, w, h = box
    return img[y:y + h, x:x + w]


def color_ratio(img, box, colors):
    hsv = np.asarray(Image.fromarray(crop(img, box)).convert("HSV"), dtype=np.int16)
    return float(color_mask(hsv, colors).mean()) if colors else 0.0


def eval_color(state, img):
    p = state["source"].get("params", {})
    box = _box(state, p.get("roi"))
    r = color_ratio(img, box, p.get("colors", []))
    if r >= p.get("high_min", 1.01):
        return p.get("high_value"), {"ratio": round(r, 4)}
    if r <= p.get("low_max", -1):
        return p.get("low_value"), {"ratio": round(r, 4)}
    return None, {"ratio": round(r, 4)}


def suggest_ratio(ratios, answers=(), min_side=0.03):
    """Thresholds for a colour-ratio rule from the ratios of many frames.

    answers: [(ratio, "high" | "low")] for frames a person answered. With at least 3 of each, the thresholds keep
    every answer right: low_max just under the lowest "high" answer that is above every "low" one, high_min just
    over the highest "low" answer below every "high" one (answers on both sides of each other stay undecided).
    Without them: the widest empty stretch between two groups of frames (each at least min_side of them), its
    middle third left undecided. -> {"low_max", "high_min", "basis": "answers" | "gap", "high", "low", "unsure",
    "wrong", "unsure_answers"} or {"none": why} when the frames do not split."""
    rs = sorted(float(r) for r in ratios if r is not None)
    hi = sorted(r for r, a in answers if a == "high")
    lo = sorted(r for r, a in answers if a == "low")
    if len(hi) >= 3 and len(lo) >= 3:
        if max(lo) < min(hi):                                       # apart: the thresholds in the empty stretch
            a, b = max(lo), min(hi)
            low, high = a + (b - a) / 3, a + 2 * (b - a) / 3
        else:                                                       # mixed: the mixed stretch stays undecided
            below = [r for r in lo if r < min(hi)]
            above = [r for r in hi if r > max(lo)]
            if not below or not above:
                return {"none": "answers_mixed"}
            low, high = max(below), min(above)
            low, high = low + (min(hi) - low) / 2, high - (high - max(lo)) / 2
        basis = "answers"
    else:
        if len(rs) < 10:
            return {"none": "few_frames"}
        need = max(2, int(len(rs) * min_side))
        best = None                                 # the widest stretch for its place: 0.003 -> 0.009 beats 0.012 -> 0.02
        for i in range(need - 1, len(rs) - need):
            gap = rs[i + 1] - rs[i]
            score = gap / max(rs[i + 1], 0.002, rs[-1] / 20)
            if gap >= 0.0005 and (best is None or score > best[0]):
                best = (score, rs[i], rs[i + 1])
        steps = sorted(y - x for x, y in zip(rs, rs[1:]) if y > x)
        usual = steps[len(steps) // 2] if steps else 0
        if best is None or best[0] < 0.3 or best[2] - best[1] < 15 * usual:    # not much wider than the frames' own spacing
            return {"none": "one_group"}
        _score, a, b = best
        low, high = a + (b - a) / 3, a + 2 * (b - a) / 3
        basis = "gap"
    low, high = _nice(low, "down"), _nice(high, "up")
    if high <= low:
        high = round(low + 0.0001, 4)
    out = {"low_max": low, "high_min": high, "basis": basis,
           "high": sum(r >= high for r in rs), "low": sum(r <= low for r in rs)}
    out["unsure"] = len(rs) - out["high"] - out["low"]
    out["wrong"] = sum(1 for r, a in answers if (a == "high" and r <= low) or (a == "low" and r >= high))
    out["unsure_answers"] = sum(1 for r, a in answers if low < r < high)
    return out


def _nice(x, way):
    """x with 2 significant digits (0.00437 -> 0.0043 down / 0.0044 up), at least 0.0001"""
    import math
    if x <= 0:
        return 0.0 if way == "down" else 0.0001
    step = 10 ** (math.floor(math.log10(x)) - 1)
    v = (math.floor if way == "down" else math.ceil)(x / step) * step
    return round(max(v, 0.0001 if way == "up" else 0.0), 6)


# ---------------------------------------------------------------- templates
def tpl_dir(data_root, state_id):
    return os.path.join(data_root, "meta", "rule_templates", state_id)


def tpl_index(data_root, state_id):
    p = os.path.join(tpl_dir(data_root, state_id), "index.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write_index(data_root, state_id, idx):
    d = tpl_dir(data_root, state_id)
    os.makedirs(d, exist_ok=True)
    atomic.write_json(os.path.join(d, "index.json"), idx, ensure_ascii=False, indent=1)


def _tpl_name(idx):
    """A file name not in use: two references within one millisecond must not overwrite each other."""
    stamp = int(time.time() * 1000)
    while f"{stamp}.png" in idx:
        stamp += 1
    return f"{stamp}.png"


def tpl_add(data_root, state_id, value, img, box, frame):
    """-> file name of the new reference, or of the existing one when this frame/region/class is already there."""
    idx = tpl_index(data_root, state_id)
    for name, meta in idx.items():
        if meta["frame"] == frame and meta["box"] == list(box) and meta["value"] == value:
            return name
    x, y, w, h = box
    name = _tpl_name(idx)
    d = tpl_dir(data_root, state_id)
    os.makedirs(d, exist_ok=True)
    Image.fromarray(img[y:y + h, x:x + w]).save(os.path.join(d, name))
    idx[name] = {"value": value, "frame": frame, "box": list(box), "created": time.time()}
    _write_index(data_root, state_id, idx)
    return name


def _mark_apart(m):
    """Where a comma or point that shares no empty column with the character beside it starts: the first column whose
    rows do not meet the column before and that leaves a much shorter part on one side; None if there is none."""
    rows = np.nonzero(m.any(axis=1))[0]
    tall = rows[-1] - rows[0] + 1 if len(rows) else 0
    for k in range(1, m.shape[1]):
        if not (m[:, k - 1] & m[:, k]).any() and not (m[:-1, k - 1] & m[1:, k]).any() and not (m[1:, k - 1] & m[:-1, k]).any():
            short = min(m[:, :k].any(axis=0).sum(), m[:, k:].any(axis=0).sum())
            part = np.nonzero(m[:, k:].any(axis=1) if m[:, k:].sum() < m[:, :k].sum() else m[:, :k].any(axis=1))[0]
            if len(part) and part[-1] - part[0] + 1 < 0.4 * tall and short <= 0.4 * tall:
                return k
    return None


def glyphs(img, box, colors, min_h=3):
    """The characters in a region: [(x0, x1, y0, y1) in frame coordinates, bool mask)] from left to right.
    Text pixels = colours in range; a character = a run of columns that have text, cut where a column has none."""
    x, y, w, h = box
    hsv = np.asarray(Image.fromarray(crop(img, box)).convert("HSV"), dtype=np.int16)
    m = color_mask(hsv, colors or [])
    cols = m.any(axis=0)
    out, i = [], 0
    while i < w:
        if not cols[i]:
            i += 1
            continue
        j = i
        while j < w and cols[j]:
            j += 1
        k = _mark_apart(m[:, i:j])
        j = i + k if k else j
        rows = np.nonzero(m[:, i:j].any(axis=1))[0]
        if len(rows) and (rows[-1] - rows[0] + 1 >= min_h or j - i >= 3 * min_h):     # a thin minus counts too
            y0, y1 = rows[0], rows[-1] + 1
            out.append(((x + i, x + j, y + y0, y + y1), m[y0:y1, i:j]))
        i = j
    if out:                                       # specks of background much shorter than the text are not characters,
        tall = max(b[3] - b[2] for b, _x in out)  # but a point, a comma or a minus is (small_char())
        line = text_line(out)
        out = [g for g in out if (g[0][3] - g[0][2]) >= 0.5 * tall or g[1].sum() >= 0.3 * tall * tall
               or small_char(g[0], line)]
    full = [g for g in out if (g[0][3] - g[0][2]) >= 0.5 * max(b[3] - b[2] for b, _x in out)] if out else []
    if len(full) >= 3:                            # two characters touching: much wider than the others -> cut evenly
        med = float(np.median([b[1] - b[0] for b, _x in full]))     # (the full-height ones: a point is narrow)
        split = []
        for (x0, x1, y0, y1), m in out:
            k = int(round((x1 - x0) / med)) if med > 0 else 1
            if k >= 2 and (x1 - x0) >= 1.6 * med:
                edges = np.linspace(0, x1 - x0, k + 1).round().astype(int)
                for a, b in zip(edges[:-1], edges[1:]):
                    rows = np.nonzero(m[:, a:b].any(axis=1))[0]
                    if len(rows):
                        split.append(((x0 + a, x0 + b, y0 + rows[0], y0 + rows[-1] + 1), m[rows[0]:rows[-1] + 1, a:b]))
            else:
                split.append(((x0, x1, y0, y1), m))
        out = split
    return out


def text_line(gs):
    """(top, bottom) of the line of text: the span of its full-height characters."""
    tall = max(b[3] - b[2] for b, _x in gs)
    full = [b for b, _x in gs if (b[3] - b[2]) >= 0.5 * tall]
    return min(b[2] for b in full), max(b[3] for b in full)


def small_char(b, line):
    """A mark much shorter than the digits, told by where it sits and its shape (no teaching needed): "." at the
    bottom of the line, "," reaching below it, "-" across the middle; None = a speck (or a full-height character)."""
    x0, x1, y0, y1 = b
    top, bottom = line
    tall = bottom - top
    w, h = x1 - x0, y1 - y0
    if tall <= 0 or h >= 0.5 * tall:
        return None
    mid = (y0 + y1) / 2
    if w >= 1.5 * h and top + 0.3 * tall <= mid <= top + 0.75 * tall and w <= 0.9 * tall:
        return "-"
    if y0 >= top + 0.55 * tall and w <= 0.5 * tall and y1 >= bottom - 0.15 * tall:
        return "," if y1 > bottom + 0.1 * tall and h > 1.3 * w else "."
    return None


def read_chars(img, gs, refs):
    """[(character, score)] for glyphs(): a point, comma or minus by its place and shape, the rest by the taught
    characters (read_glyph)."""
    if not gs:
        return []
    line = text_line(gs)
    out = []
    for b, _x in gs:
        c = small_char(b, line)
        out.append((c, 1.0) if c else read_glyph(_glyph_rgb(img, b), refs))
    return out


def _glyph_feat(rgb):
    """A character's look: its grey levels at a fixed size (the colour mask only finds where characters are;
    anti-aliased, half-transparent text gives a different mask every frame but the same picture)."""
    im = Image.fromarray(rgb).convert("L").resize(GLYPH_SIZE, Image.BILINEAR)
    return np.asarray(im, np.float32)


def _glyph_rgb(img, box):
    x0, x1, y0, y1 = box
    return np.ascontiguousarray(img[max(0, y0 - 1):y1 + 1, max(0, x0 - 1):x1 + 1])


def glyph_add(data_root, state_id, char, img, box, frame):
    """Teach one character: its picture (the frame cut at box = (x0, x1, y0, y1)) is saved as a reference whose
    value is the character."""
    idx = tpl_index(data_root, state_id)
    name = _tpl_name(idx)
    d = tpl_dir(data_root, state_id)
    os.makedirs(d, exist_ok=True)
    Image.fromarray(_glyph_rgb(img, box)).save(os.path.join(d, name))
    idx[name] = {"value": char, "frame": frame, "box": [int(v) for v in box], "created": time.time()}
    _write_index(data_root, state_id, idx)
    return name


def read_glyph(rgb, refs):
    """-> (character, score) of the most similar taught character (None when there are none)."""
    if not refs:
        return None, 0.0
    f = _glyph_feat(rgb)
    aspect = rgb.shape[1] / max(1, rgb.shape[0])
    by = {}
    for c, t, a in refs:
        sc = _ncc(f, t) - min(0.5, abs(aspect - a))      # shapes alike and about as wide (a 1 is not a squeezed 7)
        by.setdefault(c, []).append(sc)
    # a character's score: the mean of its best two examples (one badly taught example cannot decide alone)
    best_c, best = max(((c, float(np.mean(sorted(v, reverse=True)[:2]))) for c, v in by.items()), key=lambda x: x[1])
    return best_c, round(best, 3)


def to_number(text, part="all"):
    if part in ("left", "right"):
        if "/" not in text:
            return None
        text = text.split("/")[0 if part == "left" else 1]
    t = text.replace(",", "").replace("%", "").replace(":", "")
    if not t or t in ("-", ".") or t.count(".") > 1 or "-" in t[1:]:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if v.is_integer() and "." not in t else v


def eval_digits(state, img, refs):
    p = state["source"].get("params", {})
    box = _box(state, p.get("roi"))
    gs = glyphs(img, box, p.get("colors"))
    chars, scores = [], []
    for c, sc in read_chars(img, gs, refs):
        chars.append(c or "?")
        scores.append(sc)
    text = "".join(chars)
    info = {"text": text, "chars": len(gs), "min_score": min(scores) if scores else None}
    if not gs or not refs or min(scores) < p.get("match_min", 0.6) or "?" in text:
        return None, info
    v = to_number(text, p.get("part", "all"))
    lo, hi = state.get("min"), state.get("max")
    if v is None or (lo is not None and v < lo) or (hi is not None and v > hi):
        return None, info                                 # not a number, or outside what this state can be
    return v, info


def _along(a, direction):
    """The bar region turned so that it fills from column 0 towards the last column."""
    if direction == "left":
        return a[:, ::-1]
    if direction == "up":
        return a.transpose(1, 0, 2)[:, ::-1]
    if direction == "down":
        return a.transpose(1, 0, 2)
    return a


def _bar_pixels(img, box, slant, direction):
    """The bar region, slanted bars straightened (each row / column shifted by its share of the slant)."""
    x, y, w, h = box
    if not slant:
        return crop(img, box)
    H, W = img.shape[:2]
    out = np.zeros((h, w, 3), img.dtype)
    if direction in ("right", "left"):
        for r in range(h):
            off = int(round(slant * (h - 1 - r) / max(1, h - 1)))
            x0 = min(max(0, x + off), W - w)
            out[r] = img[y + r, x0:x0 + w]
    else:
        for c in range(w):
            off = int(round(slant * (w - 1 - c) / max(1, w - 1)))
            y0 = min(max(0, y + off), H - h)
            out[:, c] = img[y0:y0 + h, x + c]
    return out


def eval_bar(state, img):
    """-> (ratio 0..1 or None, info {"ratio", "end", "fill", "why"})."""
    p = state["source"].get("params", {})
    box = _box(state, p.get("roi"))
    px = _bar_pixels(img, box, int(p.get("slant", 0) or 0), p.get("dir", "right"))
    hsv = _along(np.asarray(Image.fromarray(px).convert("HSV"), dtype=np.int16), p.get("dir", "right"))
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    rows, cols = h.shape
    text = (s <= 80) & (v >= p.get("text_v", 150)) if p.get("ignore_text", True) else np.zeros(h.shape, bool)
    if text.mean() > 0.5:
        return None, {"ratio": None, "why": _("長條看起來泛白(例如畫面變暗或閃白),先不判斷")}
    near = text.copy()                                   # the text and the pale blend around it count for neither
    near[1:] |= text[:-1]; near[:-1] |= text[1:]; near[:, 1:] |= text[:, :-1]; near[:, :-1] |= text[:, 1:]
    head_w = max(3, cols // 30)
    if p.get("colors") and p.get("fill", "auto") != "auto":
        fill = color_mask(hsv, p["colors"]) & ~near
        empty = ~fill & ~near
        kind = "colors"
    else:
        head = hsv[:, :head_w][~text[:, :head_w]]
        if len(head) < max(6, rows):
            return None, {"ratio": None, "why": _("長條起點被擋住,看不出顏色")}
        hs, ss, vs = head[:, 0].astype(float), head[:, 1], head[:, 2]
        # the fill's look at the start: the colour most of its pixels have (a bit of a frame or a screen tint may
        # show there too), and how vivid the most vivid of them are
        coloured = (ss >= 90) & (vs >= p.get("min_v", 60))
        if coloured.mean() >= 0.4:                                             # a coloured fill: keep its hue
            hb = (hs[coloured] // 16).astype(int) % 16
            top = int(np.bincount(hb, minlength=16).argmax())
            dd = np.minimum(abs(hs - (top * 16 + 8)), 256 - abs(hs - (top * 16 + 8)))
            sel = coloured & (dd <= 16)
            ang = hs[sel] * (2 * np.pi / 256)                                  # red sits on both ends of the hue circle
            hue = int(round(np.angle(np.mean(np.exp(1j * ang))) * 256 / (2 * np.pi))) % 256
            ref_s = float(np.percentile(ss[sel], 75))
            d = np.minimum(abs(h - hue), 256 - abs(h - hue))
            # as vivid as the start: the empty part of many bars is the same colour, only faded or dark
            vivid = max(40, p.get("min_vivid", 0.75) * ref_s)
            fill = (d <= p.get("hue_tol", 14)) & (s >= vivid) & (v >= p.get("min_v", 60)) & ~near
            empty = ~near & ~fill
            kind = f"hue {hue}"
        elif (ss < 70).mean() >= 0.5 and np.percentile(vs[ss < 70], 75) >= 75:  # a grey fill
            ref_v = float(np.percentile(vs[ss < 70], 75))
            bright = max(75, p.get("min_bright", 0.8) * ref_v)
            fill = (s < 70) & (v >= bright) & ~near
            empty = ~near & ~fill
            kind = "grey"
        elif np.median(vs) < p.get("min_v", 60):                                # starts dark
            if p.get("dark_start", "unsure") == "empty":
                return 0.0, {"ratio": 0.0, "end": 0, "fill": "empty"}
            return None, {"ratio": None, "why": _("長條起點是暗的(可能是空的,或畫面變暗),先不判斷")}
        else:
            return None, {"ratio": None, "why": _("長條起點的顏色看不出是填滿還是空的")}
    nf, ne = fill.sum(axis=0), empty.sum(axis=0)
    known = nf + ne >= max(2, rows // 4)
    if known.mean() < 0.5:
        return None, {"ratio": None, "why": _("長條大部分被文字或東西擋住")}
    isfill = known & (nf > ne)
    isempty = known & ~isfill
    # the end: the cut that leaves the most filled columns before it and empty ones after it (a few columns judged
    # wrongly - a crack in the bar, an icon - do not move it)
    before = np.concatenate([[0], np.cumsum(isfill)])
    after = np.concatenate([np.cumsum(isempty[::-1])[::-1], [0]])
    score = before + after
    end = int(np.flatnonzero(score == score.max())[-1])
    if kind != "colors" and end < head_w / 2:
        return None, {"ratio": None, "end": end, "fill": kind, "why": _("長條起點的顏色和後面接不上(可能不是長條,例如載入畫面),先不判斷")}
    left, right = known[:end].sum(), known[end:].sum()
    if left >= 8 and isfill[:end].sum() / left < 0.7:
        return None, {"ratio": None, "end": end, "fill": kind, "why": _("長條前段有一大段看起來是空的,先不判斷")}
    if right >= 8 and isfill[end:].sum() / right > 0.3:
        return None, {"ratio": None, "end": end, "fill": kind, "why": _("長條後段又出現同樣的顏色(可能是透出的背景),先不判斷")}
    r = round(min(1.0, end / cols), 4)
    return r, {"ratio": r, "end": end, "fill": kind}


def tpl_delete(data_root, state_id, name):
    idx = tpl_index(data_root, state_id)
    if name not in idx:
        raise ValueError(_("找不到這張參考圖"))
    del idx[name]
    _write_index(data_root, state_id, idx)
    try:
        os.remove(os.path.join(tpl_dir(data_root, state_id), name))
    except OSError:
        pass


def _feature(a, kind):
    a = a.astype(np.float32)
    if kind == "minch":
        return a.min(axis=2)
    if kind == "color":
        return a
    return a @ np.array([0.299, 0.587, 0.114], np.float32)


feature = _feature          # (the live workbench makes a reference picture before it is saved)


def _ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def load_templates(data_root, state):
    """[(value, feature array sized to the current region)] for one state; for a digits rule
    [(character, glyph feature, width / height)]."""
    p = state["source"].get("params", {})
    if state["source"].get("rule") == "digits":
        out = []
        for name, meta in tpl_index(data_root, state["id"]).items():
            path = os.path.join(tpl_dir(data_root, state["id"]), name)
            if os.path.exists(path):
                rgb = np.asarray(Image.open(path).convert("RGB"))
                out.append((meta["value"], _glyph_feat(rgb), rgb.shape[1] / max(1, rgb.shape[0])))
        return out
    box = _box(state, p.get("roi"))
    kind = p.get("feature", "gray")
    out = []
    for name, meta in tpl_index(data_root, state["id"]).items():
        path = os.path.join(tpl_dir(data_root, state["id"]), name)
        if not os.path.exists(path):
            continue
        im = Image.open(path).convert("RGB")
        if im.size != (box[2], box[3]):                  # region was resized after the reference was made
            im = im.resize((box[2], box[3]), Image.BILINEAR)
        out.append((meta["value"], _feature(np.asarray(im), kind)))
    return out


def _best_match(reg, t, w, h):
    """Highest normalised cross-correlation of template t (h x w) over every position inside reg."""
    if reg.shape[0] < h or reg.shape[1] < w:
        return -1.0
    if cv2 is not None and t.ndim == 2:              # same score as _ncc at every shift, ~25x faster
        return float(cv2.matchTemplate(reg, t, cv2.TM_CCOEFF_NORMED).max())
    sc = -1.0
    for yy in range(reg.shape[0] - h + 1):
        for xx in range(reg.shape[1] - w + 1):
            sc = max(sc, _ncc(reg[yy:yy + h, xx:xx + w], t))
    return sc


def eval_template(state, img, tpls):
    p = state["source"].get("params", {})
    x, y, w, h = _box(state, p.get("roi"))
    if not tpls:
        return p.get("fallback"), {"scores": {}}
    s = int(p.get("search", 3))
    y0, x0 = max(0, y - s), max(0, x - s)            # the region plus the search margin, inside the frame
    reg = _feature(img[y0:min(img.shape[0], y + h + s), x0:min(img.shape[1], x + w + s)], p.get("feature", "gray"))
    best = {}
    for value, t in tpls:
        sc = _best_match(reg, t, w, h)
        k = json.dumps(value)
        best[k] = max(best.get(k, -1.0), sc)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    top_k, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    scores = {"scores": {str(json.loads(k)): round(v, 3) for k, v in best.items()}}
    if top < p.get("match_min", 0.6):
        return p.get("fallback"), scores               # nothing looks like a reference
    if top - second < p.get("margin", 0.05):
        return None, scores
    return json.loads(top_k), scores


# ---------------------------------------------------------------- engine
def _box(state, roi_id):
    for r in state.get("rois", []):
        if r["id"] == roi_id:
            return r["box"]
    return state["rois"][0]["box"]


def is_generic(state):
    return state.get("source", {}).get("kind") == "rule" and state["source"].get("rule") in KINDS


def evaluate(state, img, tpls=None, context=None):
    """One generic state on one frame -> (value or None, scores). context = values of other states (for gates)."""
    p = state["source"].get("params", {})
    gate = p.get("gate_state")
    if gate and context is not None and context.get(gate) in (None, "hidden"):
        has_hidden = any(c["value"] == "hidden" for c in state.get("classes", []))
        return ("hidden" if has_hidden else None), {"gated": gate}
    if state["source"]["rule"] == "color_ratio":
        return eval_color(state, img)
    if state["source"]["rule"] == "digits":
        return eval_digits(state, img, tpls or [])
    if state["source"]["rule"] == "bar":
        return eval_bar(state, img)
    return eval_template(state, img, tpls or [])


class Engine:
    """All generic states of one schema, with their reference crops loaded once."""

    def __init__(self, schema, data_root):
        self.states = [s for s in schema["states"] if is_generic(s) and s["type"] in ("class", "number", "ratio")]
        self.tpls = {s["id"]: load_templates(data_root, s) for s in self.states if s["source"]["rule"] in ("template", "digits")}

    def ids(self):
        return [s["id"] for s in self.states]

    def label(self, img, context):
        """-> ({state id: value}, {state id: scores}, flags). Later states may gate on earlier ones."""
        values, scores, flags = {}, {}, []
        ctx = dict(context)
        for s in self.states:
            v, sc = evaluate(s, img, self.tpls.get(s["id"]), ctx)
            values[s["id"]] = ctx[s["id"]] = v
            scores[s["id"]] = sc
            if v is None:
                flags.append(f"{s['id']}_uncertain")
        return values, scores, flags


def signature(schema, data_root):
    """Changes whenever a generic rule's settings or reference crops change (-> rule cache key)."""
    parts = []
    for s in schema["states"]:
        if is_generic(s):
            parts.append({"id": s["id"], "rois": s.get("rois"), "source": s.get("source"),
                          "tpl": sorted(tpl_index(data_root, s["id"]).keys()) if s["source"]["rule"] in ("template", "digits") else None})
    return hashlib.md5(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:10]


def validate(state):
    """Raise ValueError for an unusable generic rule definition."""
    p = state["source"].get("params") or {}
    sid = state["id"]
    if state["source"]["rule"] == "bar":
        if state["type"] != "ratio":
            raise ValueError(_("{sid}:「長條比例」規則只能用在比例型的狀態", sid=sid))
        if p.get("roi") not in {r["id"] for r in state.get("rois", [])}:
            raise ValueError(_("{sid}:規則要看的範圍不存在,請重新選擇", sid=sid))
        if p.get("dir", "right") not in BAR_DIRS:
            raise ValueError(_("{sid}:長條填滿的方向不正確", sid=sid))
        if p.get("fill", "auto") not in ("auto", "colors"):
            raise ValueError(_("{sid}:長條的顏色要選「自動」或指定顏色", sid=sid))
        if p.get("fill") == "colors" and not p.get("colors"):
            raise ValueError(_("{sid}:請點選長條填滿的顏色", sid=sid))
        if p.get("dark_start", "unsure") not in ("unsure", "empty"):
            raise ValueError(_("{sid}:長條起點是暗的時候要「先不判斷」還是「當作空的」", sid=sid))
        for k, lo, hi in (("gap", 1, 50), ("hue_tol", 1, 60), ("text_v", 0, 255), ("min_v", 0, 255), ("min_bright", 0, 1), ("min_vivid", 0, 1), ("slant", -200, 200)):
            if k in p and not (isinstance(p[k], (int, float)) and lo <= p[k] <= hi):
                raise ValueError(_("{sid}:長條參數 {k} 要在 {lo}~{hi}", sid=sid, k=k, lo=lo, hi=hi))
        return
    if state["source"]["rule"] == "digits":
        if state["type"] != "number":
            raise ValueError(_("{sid}:「讀數字」規則只能用在數值型的狀態", sid=sid))
        if p.get("roi") not in {r["id"] for r in state.get("rois", [])}:
            raise ValueError(_("{sid}:規則要看的範圍不存在,請重新選擇", sid=sid))
        if not p.get("colors"):
            raise ValueError(_("{sid}:請點選數字的顏色", sid=sid))
        if p.get("part", "all") not in PARTS:
            raise ValueError(_("{sid}:要取哪一段數字不正確", sid=sid))
        return
    if state["type"] != "class":
        raise ValueError(_("{sid}:「{p2}」規則只能用在分類型的狀態", sid=sid, p2=_(KINDS[state['source']['rule']])))
    if p.get("roi") not in {r["id"] for r in state.get("rois", [])}:
        raise ValueError(_("{sid}:規則要看的範圍不存在,請重新選擇", sid=sid))
    values = [c["value"] for c in state.get("classes", [])]
    if state["source"]["rule"] == "color_ratio":
        if not p.get("colors"):
            raise ValueError(_("{sid}:顏色比例規則至少要有一種顏色", sid=sid))
        for c in p["colors"]:
            for k in ("h", "s", "v"):
                r = c.get(k)
                if not (isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in r)):
                    raise ValueError(_("{sid}:顏色範圍 {k} 必須是 0~255 的兩個數字", sid=sid, k=k))
        if p.get("high_value") not in values or p.get("low_value") not in values:
            raise Unfinished(_("{sid}:請選擇比例高、比例低時各代表哪個類別", sid=sid))
        if not (0 <= p.get("low_max", -1) <= p.get("high_min", 2) <= 1):
            raise Unfinished(_("{sid}:門檻要在 0~1 之間,而且「低於」要小於等於「高於」", sid=sid))
    else:
        if p.get("feature", "gray") not in FEATURES:
            raise ValueError(_("{sid}:比對方式不正確", sid=sid))
        if p.get("fallback") is not None and p["fallback"] not in values:
            raise Unfinished(_("{sid}:「都不像時」的類別不存在", sid=sid))
