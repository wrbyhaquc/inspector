"""Walk maps: where on a big map one can walk, for walk_to to find its own way (automation/mapnav.py).

A walk map is a picture of a big map turned into "can walk here" / "cannot": the dark parts of the map (walls, water,
rocks - whatever the map draws dark) are blocked, the rest is walkable. walk_to with "area" plans its way on it from
wherever "me" is: the shortest way that keeps a distance from anything blocked (so a push that goes a little off does
not run into it), cut into straight stretches between turning points. Where it still gets stuck, that spot is marked
blocked and the way is planned again round it. A way walked through to the end is kept: the next walk whose way runs
along it (nothing fixed in the way) goes in one go, a look only at the end; someone standing in the way then is an
accident, walked round from where it stopped.

Files under <data_root>/meta/walkmaps/:
  <id>.png   the map, one gray level per pixel: 255 = walkable, 0 = blocked
  <id>.json  {"id", "label", "origin": [x, y] (where the picture's top-left pixel is, in the walk's coordinates:
             map pixels from the anchor), "marks": [[x, y, r], ...] (spots found blocked by walking),
             "signs": [{"button", "x", "y"}] (made by shoot(): pictures cut from the map itself that tell where the
             map is on the screen - the first one is the anchor, (0, 0) - so nobody has to make one),
             "places": [{"id", "name", "x", "y", "near"?}] (where one can be sent: walk_to {"map", "place"}),
             "proven": [[[x, y], ...], ...] (ways walked through to the end: where it was at each look),
             "speed": map px per second of push (learnt walking), "updated"}
  _walk.json how walking is done in this project, the same on every map (walk settings): {"open", "close" (where to
             tap to open / close the big map), "me" {"color", "tol", "min_px", "box", "more"?, "size"?} (how "me" looks on it;
             its box = the map's part of the screen), "stick" {"x", "y", "r", "press"?}, "before" / "after" (a sub
             run before / after walking, e.g. a game's auto play off / on), and the rest of walk_to's knobs}
"""
import heapq
import json
import math
import os
import time

import numpy as np
from i18n import _

DARK = 35          # a map pixel this dark (its brightest colour channel) is blocked
CELL = 3           # map px per planning cell
CLEAR = 12         # map px: keep this far from anything blocked where there is room
HARD = 4           # map px: never nearer than this
SEG_MAX = 110      # map px: the longest straight stretch between two points of a planned way
MARK_R = 7         # map px: a spot found blocked by walking
PROVEN_R = 20      # map px: a planned way this near a way walked through before is "walked through"
PROVEN_GAP = 15    # map px: a bit of the way off it no longer than this does not count (where it looked from varies)
FIRST_FREE = 60    # map px: the way's first stretch (from wherever it starts) may be new up to this long
PROVEN_KEEP = 20   # ways walked through kept

_cache = {}


def _dir(data_root):
    return os.path.join(data_root, "meta", "walkmaps")


def list_ids(data_root):
    d = _dir(data_root)
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")) if os.path.isdir(d) else []


def load(data_root, wid):
    """-> {"id", "origin", "marks", "free" (bool array, True = walkable), ...} or None; re-read when the files change"""
    import cv2
    base = os.path.join(_dir(data_root), wid)
    try:
        m = (os.path.getmtime(base + ".json"), os.path.getmtime(base + ".png"))
    except OSError:
        return None
    hit = _cache.get(base)
    if hit and hit[0] == m:
        return hit[1]
    with open(base + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    img = cv2.imdecode(np.fromfile(base + ".png", np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    wm = {**meta, "free": img >= 128}
    _cache[base] = (m, wm)
    return wm


def save(data_root, wid, free, origin, label="", marks=None):
    import cv2
    os.makedirs(_dir(data_root), exist_ok=True)
    base = os.path.join(_dir(data_root), wid)
    ok, buf = cv2.imencode(".png", np.where(free, 255, 0).astype(np.uint8))
    buf.tofile(base + ".png")
    old = {}
    if os.path.exists(base + ".json"):
        with open(base + ".json", encoding="utf-8") as f:
            old = json.load(f)
    meta = {**old, "id": wid, "label": label or old.get("label") or wid, "origin": [int(origin[0]), int(origin[1])],
            "marks": marks if marks is not None else old.get("marks", []), "updated": time.time()}
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return meta


def proven(wm, way):
    """the whole way runs along ways walked through before"""
    return proven_upto(wm, way) == len(way) - 1


def proven_upto(wm, way):
    """how many of the way's stretches (from its start) run along ways walked through before (all but a short first
    stretch): those are walked in one go, nothing fixed being in the way"""
    ways = [w for w in (wm or {}).get("proven") or [] if len(w) >= 2]
    if not ways or len(way) < 2:
        return 0
    segs = [(a, b) for w in ways for a, b in zip(w, w[1:])]

    def near(p):
        return any(_seg_dist(p, a, b) <= PROVEN_R for a, b in segs)
    gone, off_from = 0.0, None
    for i, (a, b) in enumerate(zip(way, way[1:])):
        n = max(1, int(math.dist(a, b) // 5))
        for k in range(n + 1):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            at = gone + math.dist(a, p)
            if at <= FIRST_FREE or near(p):
                off_from = None
            elif off_from is None:
                off_from = at
            elif at - off_from > PROVEN_GAP:
                return i
        gone += math.dist(a, b)
    return len(way) - 1


def _seg_dist(p, a, b):
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def set_view(data_root, wid, view):
    """the game's view scale learnt walking (map px per view px, along x and y): kept for the next walk"""
    base = os.path.join(_dir(data_root), wid)
    try:
        with open(base + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return False
    meta.update(view=[round(float(v), 5) for v in view], updated=time.time())
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return True


def add_walk(data_root, wid, track, speed=None):
    """a walk that got there: its way kept as walked through (the next walk along it goes in one go), its speed kept"""
    base = os.path.join(_dir(data_root), wid)
    try:
        with open(base + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return False
    if track and len(track) >= 2:
        meta["proven"] = (list(meta.get("proven") or []) + [[[round(float(x), 1), round(float(y), 1)] for x, y in track]])[-PROVEN_KEEP:]
    if speed:
        old = meta.get("speed")
        meta["speed"] = round(float(speed) if not old else 0.5 * float(old) + 0.5 * float(speed), 2)
    meta["updated"] = time.time()
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return True


def add_marks(data_root, wid, marks, apart=MARK_R):
    """spots found blocked by walking -> kept with the walk map (the next walk plans round them); one already kept
    within apart px is not kept again. -> how many were new"""
    base = os.path.join(_dir(data_root), wid)
    try:
        with open(base + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return 0
    kept = list(meta.get("marks") or [])
    new = 0
    for m in marks or []:
        if all(math.dist(m[:2], k[:2]) > apart for k in kept):
            kept.append([round(float(m[0]), 1), round(float(m[1]), 1), int(m[2] if len(m) > 2 else MARK_R)])
            new += 1
    if new:
        meta.update(marks=kept, updated=time.time())
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return new


def from_frame(frame, box, anchor_at, dark=DARK):
    """A big-map picture (BGR or RGB) -> (free, origin): walkable where the map is not dark, inside box [x, y, w, h]
    of the screen; anchor_at = where the anchor is on this screen (it may be off the screen: worked out from another
    sign), so origin = the box's top-left in the walk's coordinates."""
    x, y, w, h = [int(v) for v in box]
    crop = np.asarray(frame)[y:y + h, x:x + w]
    free = crop.max(axis=2) > dark
    return free, (x - anchor_at[0], y - anchor_at[1])


def merge(a, b):
    """Two walk maps (free, origin) of the same place seen from two spots -> one: walkable where either saw it walkable
    (what one of them did not cover - off its screen - counts as not seen)"""
    (fa, oa), (fb, ob) = a, b
    x0, y0 = min(oa[0], ob[0]), min(oa[1], ob[1])
    x1 = max(oa[0] + fa.shape[1], ob[0] + fb.shape[1])
    y1 = max(oa[1] + fa.shape[0], ob[1] + fb.shape[0])
    out = np.zeros((y1 - y0, x1 - x0), bool)
    for f, o in (a, b):
        out[o[1] - y0:o[1] - y0 + f.shape[0], o[0] - x0:o[0] - x0 + f.shape[1]] |= f
    return out, (x0, y0)


def _grid(wm, marks):
    """the planning grid: cost per cell (inf = not passable) and the cells' clearance in map px"""
    import cv2
    free = wm["free"].copy()
    ox, oy = wm["origin"]
    for mx, my, r in list(wm.get("marks") or []) + list(marks or []):
        cv2.circle(free.view(np.uint8), (int(round(mx - ox)), int(round(my - oy))), int(r), 0, -1)
    h, w = free.shape
    gh, gw = h // CELL, w // CELL
    cell_free = free[:gh * CELL, :gw * CELL].reshape(gh, CELL, gw, CELL).all(axis=(1, 3))
    dist = cv2.distanceTransform(cell_free.astype(np.uint8), cv2.DIST_L2, 5) * CELL
    cost = 1.0 + 4.0 * np.clip((CLEAR - dist) / CLEAR, 0, 1) ** 2
    cost[dist < HARD] = np.inf
    return cost, dist


def _nearest_ok(cost, c, r=12):
    """the passable cell nearest to cell c (it may stand where the grid says blocked: next to a wall)"""
    gh, gw = cost.shape
    y, x = c
    if 0 <= y < gh and 0 <= x < gw and np.isfinite(cost[y, x]):
        return c
    best = None
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            yy, xx = y + dy, x + dx
            if 0 <= yy < gh and 0 <= xx < gw and np.isfinite(cost[yy, xx]):
                d = dy * dy + dx * dx
                if best is None or d < best[0]:
                    best = (d, (yy, xx))
    return best[1] if best else None


def _astar(cost, s, g):
    gh, gw = cost.shape
    steps = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
    best = np.full(cost.shape, np.inf)
    prev = -np.ones(cost.shape, np.int64)
    best[s] = 0.0
    todo = [(0.0, s)]
    gy, gx = g
    while todo:
        f, (y, x) = heapq.heappop(todo)
        if (y, x) == g:
            break
        b = best[y, x]
        if f - math.hypot(y - gy, x - gx) > b + 1e-9:
            continue
        for dy, dx, k in steps:
            yy, xx = y + dy, x + dx
            if 0 <= yy < gh and 0 <= xx < gw:
                c = cost[yy, xx]
                if c == np.inf:
                    continue
                nb = b + k * 0.5 * (c + cost[y, x])
                if nb < best[yy, xx]:
                    best[yy, xx] = nb
                    prev[yy, xx] = y * gw + x
                    heapq.heappush(todo, (nb + math.hypot(yy - gy, xx - gx), (yy, xx)))
    if not np.isfinite(best[g]):
        return None
    path, c = [g], g
    while c != s:
        p = int(prev[c])
        c = (p // gw, p % gw)
        path.append(c)
    return path[::-1]


def _line_ok(dist, a, b, need):
    """the straight line between cells a and b keeps at least need (map px) from anything blocked"""
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    ys = np.linspace(a[0], b[0], n).round().astype(int)
    xs = np.linspace(a[1], b[1], n).round().astype(int)
    return bool((dist[ys, xs] >= need).all())


def plan(wm, start, goal, marks=()):
    """The way from start to goal ((x, y) in the walk's coordinates) on walk map wm -> the turning points after start,
    the last one = goal, or None (no way). marks: [[x, y, r], ...] more spots found blocked."""
    cost, dist = _grid(wm, marks)
    ox, oy = wm["origin"]
    cell = lambda p: (int((p[1] - oy) // CELL), int((p[0] - ox) // CELL))     # noqa: E731
    s, g = _nearest_ok(cost, cell(start)), _nearest_ok(cost, cell(goal))
    if s is None or g is None:
        return None
    path = _astar(cost, s, g)
    if path is None:
        return None
    pts, i = [], 0
    while i < len(path) - 1:          # as few straight stretches as keep about as clear as the planned way did
        j = i + 1
        lim = min(len(path) - 1, i + SEG_MAX // CELL * 2)
        for k in range(lim, i, -1):
            need = min(CLEAR, float(dist[tuple(np.array(path[i:k + 1]).T)].min()))
            if math.dist(path[i], path[k]) * CELL <= SEG_MAX and _line_ok(dist, path[i], path[k], need):
                j = k
                break
        pts.append((j, path[j]))
        i = j
    pts = [(0, path[0])] + pts
    k = 1
    while k < len(pts) - 1:           # a short zigzag left by a narrow spot: straight through when that stays clear enough
        (ia, a), (ib, b), (ic, c) = pts[k - 1], pts[k], pts[k + 1]
        short = min(math.dist(a, b), math.dist(b, c)) * CELL < 24
        bend = abs(math.degrees(math.atan2(c[0] - b[0], c[1] - b[1]) - math.atan2(b[0] - a[0], b[1] - a[1]))) % 360
        need = min(CLEAR * 0.6, float(dist[tuple(np.array(path[ia:ic + 1]).T)].min()))
        if (short or min(bend, 360 - bend) < 15) and math.dist(a, c) * CELL <= SEG_MAX and _line_ok(dist, a, c, need):
            del pts[k]
        else:
            k += 1
    pts = [p for _i, p in pts[1:]]
    out =[(ox + (x + 0.5) * CELL, oy + (y + 0.5) * CELL) for y, x in pts]
    if out:
        out[-1] = (float(goal[0]), float(goal[1]))
    return out


# ---------------------------------------------------------------- making and editing one (可走區域圖編輯器)
def bg_path(data_root, wid):
    """the map picture a walk map was made from (RGB, aligned with its mask): shown under it while editing"""
    return os.path.join(_dir(data_root), wid + ".bg.png")


def summary(data_root, wid):
    wm = load(data_root, wid)
    if not wm:
        return None
    h, w = wm["free"].shape
    return {"id": wid, "label": wm.get("label") or wid, "origin": wm["origin"], "size": [int(w), int(h)],
            "marks": wm.get("marks") or [], "proven": len(wm.get("proven") or []), "speed": wm.get("speed"),
            "has_bg": os.path.exists(bg_path(data_root, wid)), "updated": wm.get("updated"),
            "signs": wm.get("signs") or [], "places": wm.get("places") or []}


def make(data_root, wid, frame, box, anchor_at, dark=DARK, label="", merge_in=False):
    """A walk map from a big-map picture (RGB): new, or merged into the one there (what either saw walkable); the
    marks and the ways walked through are kept. The colour picture is kept aligned with it (shown while editing)."""
    import cv2
    free, origin = from_frame(frame, box, anchor_at, dark)
    x, y, w, h = [int(v) for v in box]
    bg = np.asarray(frame)[y:y + h, x:x + w, :3].astype(np.uint8)
    old = load(data_root, wid) if merge_in else None
    if not old:                                   # a new one (or made again): nothing learnt on the old one is kept
        remove(data_root, wid)
    if old:
        (free2, origin2) = merge((old["free"], tuple(old["origin"])), (free, origin))
        canvas = np.zeros(free2.shape + (3,), np.uint8)
        p = bg_path(data_root, wid)
        if os.path.exists(p):
            ob = cv2.cvtColor(cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            ox, oy = old["origin"][0] - origin2[0], old["origin"][1] - origin2[1]
            canvas[oy:oy + ob.shape[0], ox:ox + ob.shape[1]] = ob[:canvas.shape[0] - oy, :canvas.shape[1] - ox]
        nx, ny = origin[0] - origin2[0], origin[1] - origin2[1]
        canvas[ny:ny + h, nx:nx + w] = bg
        free, origin, bg = free2, origin2, canvas
    meta = save(data_root, wid, free, origin, label or (old or {}).get("label") or wid, None if old else [])
    ok, buf = cv2.imencode(".png", cv2.cvtColor(bg, cv2.COLOR_RGB2BGR))
    buf.tofile(bg_path(data_root, wid))
    return meta


def paint(data_root, wid, free, marks=None, clear_ways=False):
    """the mask as edited (True = walkable; the same size), the marks kept (or these), the ways walked through dropped"""
    wm = load(data_root, wid)
    if not wm:
        raise ValueError(wid)
    if free.shape != wm["free"].shape:
        raise ValueError("size")
    meta = save(data_root, wid, free, wm["origin"], wm.get("label") or wid, marks)
    if clear_ways:
        base = os.path.join(_dir(data_root), wid)
        with open(base + ".json", encoding="utf-8") as f:
            meta = json.load(f)
        meta["proven"] = []
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return meta


def remove(data_root, wid):
    for p in (os.path.join(_dir(data_root), wid + ".json"), os.path.join(_dir(data_root), wid + ".png"), bg_path(data_root, wid)):
        if os.path.exists(p):
            os.remove(p)
    _cache.pop(os.path.join(_dir(data_root), wid), None)


# ---------------------------------------------------------------- maps made by taking a picture (地圖:拍下來就好)
# Nobody makes a sign or measures anything: the picture of the big map is the map. Bits of it that look like nothing
# else on it are kept as its signs (find buttons) - wherever the map has scrolled to, one of them shows and tells where
# the map is on the screen. A place is a click on the picture; walk_to {"map", "place"} goes there with the project's
# walk settings (_walk.json), the map's signs and its walk map.
SETTINGS = "_walk.json"
WALK_KEYS = ("open", "close", "me", "stick", "near", "push_ms", "max_moves", "turn", "speed", "tries", "on_fail", "mini")
SIGN = (80, 64)        # map px: a sign's size (bigger: more of the map in it, fewer look-alikes)
SIGN_GRID = (4, 3)     # a sign looked for in each part of the map picture (columns, rows)
SIGN_MIN_STD = 16      # a bit of the map this plain (gray spread) is no sign
SIGN_UNIQUE = 0.8      # ... nor one that anything else on the map looks this much like
SIGN_SCORE = 0.9       # found where it looks at least this much like itself
SIGN_AVOID = 14        # px round "me" (its colour) no sign is taken from: "me" moves
PLACE_NEAR = 20        # map px: this near a place = there


def settings(data_root):
    try:
        with open(os.path.join(_dir(data_root), SETTINGS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data_root, s):
    me, stick = s.get("me") or {}, s.get("stick") or {}
    if not (isinstance(me.get("color"), list) and len(me["color"]) == 3 and isinstance(me.get("box"), list) and len(me["box"]) == 4):
        raise ValueError(_("請設定「自己」在地圖上的顏色和地圖在畫面上的範圍"))
    if not all(k in stick for k in ("x", "y", "r")):
        raise ValueError(_("請設定方向控制(搖桿)的位置"))
    if not (s.get("open") and s.get("close")):
        raise ValueError(_("請設定打開、關閉地圖的位置"))
    out = {k: s[k] for k in WALK_KEYS + ("before", "after") if s.get(k) not in (None, "", [], {})}
    os.makedirs(_dir(data_root), exist_ok=True)
    with open(os.path.join(_dir(data_root), SETTINGS), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return out


def _me_mask(crop, me):
    """where "me" (its colours) is on a map picture, grown by SIGN_AVOID: no sign from there"""
    import cv2
    a = np.asarray(crop)[..., :3].astype(np.int16)
    m = np.zeros(a.shape[:2], np.uint8)
    for c in [me.get("color")] + list(me.get("more") or ()):
        if c:
            m |= (np.abs(a - np.array(c[:3], np.int16)).max(axis=2) <= int(me.get("tol", 40))).astype(np.uint8)
    return cv2.dilate(m, np.ones((2 * SIGN_AVOID + 1, 2 * SIGN_AVOID + 1), np.uint8)) if m.any() else m


def pick_signs(crop, avoid=None, skip=(), size=SIGN, grid=SIGN_GRID):
    """bits of a map picture (RGB) that look like nothing else on it: [(x, y, w, h)] in the picture, at most one in
    each part of a grid (spread out: wherever the map has scrolled to, one shows), the plainest left out.
    avoid: a mask (1 = no sign here, e.g. round "me"); skip: boxes [x, y, w, h] already covered (another picture)"""
    import cv2
    g = cv2.cvtColor(np.asarray(crop)[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    H, W = g.shape
    w, h = size
    if W < 2 * w or H < 2 * h:
        return []
    ny, nx = H - h + 1, W - w + 1                           # windows by their top-left corner
    ii, ii2 = cv2.integral(g, sdepth=cv2.CV_64F), cv2.integral(g * g, sdepth=cv2.CV_64F)

    def wsum(t):
        return t[h:h + ny, w:w + nx] - t[0:ny, w:w + nx] - t[h:h + ny, 0:nx] + t[0:ny, 0:nx]
    n = float(w * h)
    mean = wsum(ii) / n
    std = np.sqrt(np.maximum(wsum(ii2) / n - mean * mean, 0)).astype(np.float32)
    bad = np.zeros((H, W), np.uint8)
    if avoid is not None and np.asarray(avoid).any():
        bad |= np.asarray(avoid, np.uint8)
    for sx, sy, sw, sh in skip or ():
        sx, sy = int(sx), int(sy)
        bad[max(0, sy):max(0, sy + int(sh)), max(0, sx):max(0, sx + int(sw))] = 1
    if bad.any():
        ib = cv2.integral(bad, sdepth=cv2.CV_64F)
        std[wsum(ib) > 0] = 0
    out = []
    cw, ch = nx / grid[0], ny / grid[1]
    for gy in range(grid[1]):
        for gx in range(grid[0]):
            x0, y0, x1, y1 = int(gx * cw), int(gy * ch), int((gx + 1) * cw), int((gy + 1) * ch)
            cell = std[y0:y1, x0:x1].copy()
            for _try in range(6):                           # the busiest bits of this part first
                if cell.size == 0 or float(cell.max()) < SIGN_MIN_STD:
                    break
                cy, cx = np.unravel_index(int(np.argmax(cell)), cell.shape)
                x, y = x0 + int(cx), y0 + int(cy)
                cell[max(0, cy - h):cy + h, max(0, cx - w):cx + w] = 0
                r = cv2.matchTemplate(g, g[y:y + h, x:x + w], cv2.TM_CCOEFF_NORMED)
                r[max(0, y - h // 2):y + h // 2 + 1, max(0, x - w // 2):x + w // 2 + 1] = -1   # itself, a little moved
                if float(r.max()) <= SIGN_UNIQUE:
                    out.append((x, y, w, h))
                    break
    return out


def shoot(data_root, wid, frame, label="", merge=False, dark=DARK):
    """A map from a picture of the big map (RGB, the screen): new, or another part of it added (merge: it must show
    some of what the first pictures showed). Its signs are cut from the picture itself; the map's part of the screen
    and how "me" looks come from the walk settings. -> summary"""
    from . import buttons
    s = settings(data_root)
    me = s.get("me") or {}
    if not me.get("box"):
        raise ValueError(_("請先設定走路的方式(地圖在畫面上的範圍、「自己」的顏色)"))
    frame = np.asarray(frame)[..., :3]
    x, y, w, h = (int(v) for v in me["box"])
    crop = frame[y:y + h, x:x + w]
    avoid = _me_mask(crop, me)
    lib = buttons.load(data_root)
    old = load(data_root, wid) if merge else None
    if merge and not old:
        raise ValueError(_("還沒有這張地圖,不能再加一塊"))
    signs, skip = [], []
    if old:
        at = []
        for sg in old.get("signs") or []:
            b = lib.get(sg["button"])
            if b:
                (px, py), _sc = buttons.locate(b, frame, data_root)
                if px is not None:
                    at.append((px - sg["x"], py - sg["y"]))
        if not at:
            raise ValueError(_("這張畫面上認不出「{label}」:請拍和之前那張有重疊的一塊(移一點就好)", label=old.get("label") or wid))
        anchor_at = (int(round(float(np.median([a[0] for a in at])))), int(round(float(np.median([a[1] for a in at])))))
        oh, ow = old["free"].shape
        skip = [(anchor_at[0] + old["origin"][0] - x, anchor_at[1] + old["origin"][1] - y, ow, oh)]
        signs = list(old.get("signs") or [])
    picks = pick_signs(crop, avoid, skip)
    if not old:
        if not picks:
            raise ValueError(_("這張地圖上找不到夠清楚、不會認錯的地方當記號(地圖太空白,或範圍不對)"))
        sx, sy, sw, sh = picks[0]
        anchor_at = (x + sx + sw // 2, y + sy + sh // 2)
        for bid in [b for b in lib if b.startswith(wid + "_sign")]:
            buttons.delete(data_root, bid)
    W = _screen_w(data_root)
    k = 1 + max([int(sg["button"].rsplit("_sign", 1)[1]) for sg in signs if sg["button"].rsplit("_sign", 1)[-1].isdigit()] or [0])
    name = label or (old or {}).get("label") or wid
    for sx, sy, sw, sh in picks:
        bid = f"{wid}_sign{k}"
        cx, cy = x + sx + sw // 2, y + sy + sh // 2
        buttons.save(data_root, {"id": bid, "label": _("地圖「{name}」的記號 {k}", name=name, k=k), "x": cx, "y": cy, "find": True,
                                 "box": [x + sx, y + sy, sw, sh], "search": W, "min_score": SIGN_SCORE,
                                 "folder": _("地圖記號")}, frame)
        signs.append({"button": bid, "x": int(cx - anchor_at[0]), "y": int(cy - anchor_at[1])})
        k += 1
    places = (old or {}).get("places") or []
    make(data_root, wid, frame, me["box"], anchor_at, dark, name, merge_in=bool(old))
    _update(data_root, wid, signs=signs, places=places)
    return summary(data_root, wid) | {"added_signs": len(picks)}


def _screen_w(data_root):
    import project
    return int(project.screen(data_root)[0])


def _update(data_root, wid, **kw):
    base = os.path.join(_dir(data_root), wid)
    with open(base + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    meta.update(kw, updated=time.time())
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return meta


def set_places(data_root, wid, places):
    """the map's places as edited: [{"id"?, "name", "x", "y", "near"?}] (walk coordinates); a new one gets an id"""
    wm = load(data_root, wid)
    if not wm:
        raise ValueError(_("找不到地圖「{id}」", id=wid))
    used = {str(p.get("id")) for p in places if p.get("id")}
    out, k = [], 1
    for p in places:
        name = str(p.get("name") or "").strip()
        if not name:
            raise ValueError(_("每個地點都要有名字"))
        pid = str(p.get("id") or "")
        if not pid:
            while f"p{k}" in used:
                k += 1
            pid = f"p{k}"
            used.add(pid)
        q = {"id": pid, "name": name, "x": round(float(p["x"]), 1), "y": round(float(p["y"]), 1)}
        if p.get("near"):
            q["near"] = float(p["near"])
        out.append(q)
    if len({p["name"] for p in out}) < len(out):
        raise ValueError(_("地點的名字不能重複"))
    _update(data_root, wid, places=out)
    return out


def place_of(data_root, wid, pid):
    wm = load(data_root, wid) if wid else None
    return next((p for p in (wm or {}).get("places") or [] if p["id"] == pid), None), wm


def walk_step(data_root, st):
    """walk_to {"map", "place"} -> the walk_to step that does it: the walk settings, the map's signs (the first the
    anchor), its walk map, the place as the one point; what the step itself sets wins"""
    place, wm = place_of(data_root, st.get("map"), st.get("place"))
    if not wm:
        raise ValueError(_("找不到地圖「{id}」", id=st.get("map")))
    if not place:
        raise ValueError(_("地圖「{map}」上沒有這個地點", map=wm.get("label") or st.get("map")))
    s = settings(data_root)
    out = {k: s[k] for k in WALK_KEYS if k in s}
    out.update(type="walk_to", area=st["map"])
    signs = wm.get("signs") or []
    if signs:
        out["anchor"] = {"button": signs[0]["button"]}
        if len(signs) > 1:
            out["anchors"] = [{"button": g["button"], "x": g["x"], "y": g["y"]} for g in signs[1:]]
    out["points"] = [{"x": place["x"], "y": place["y"], "label": place["name"], "near": place.get("near") or PLACE_NEAR}]
    out.update({k: v for k, v in st.items() if k not in ("map", "place", "type")})
    return out


def walk_sub(data_root, st):
    """walk_to {"map", "place"} run as a sub-script of its own (made up, this run only): the walk settings' "before"
    sub, the walk, their "after" sub"""
    s = settings(data_root)
    place, wm = place_of(data_root, st.get("map"), st.get("place"))
    name = _("走到「{map} › {place}」", map=(wm or {}).get("label") or st.get("map"), place=(place or {}).get("name") or st.get("place"))
    steps = [{"type": "call", "sub": s["before"]}] if s.get("before") else []
    steps.append(walk_step(data_root, st))
    if s.get("after"):
        steps.append({"type": "call", "sub": s["after"]})
    return {"id": f"_walk_{st.get('map')}_{st.get('place')}", "name": name, "params": [], "steps": steps}
