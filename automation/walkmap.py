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
             "proven": [[[x, y], ...], ...] (ways walked through to the end: where it was at each look),
             "speed": map px per second of push (learnt walking), "updated"}
"""
import heapq
import json
import math
import os
import time

import numpy as np

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
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []


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
