"""Walking to a place on a map (走到地圖上的位置): the step walk_to.

Many screens show "me" on a map (a game's map, a robot's floor plan) and move "me" with a direction control (a
joystick). walk_to goes there in strides: open the map, see where "me" is (a coloured marker) next to a fixed sign
on the map (the anchor: a find button), close the map, push the control towards the next point for a moment, again.
The places are given relative to the anchor, so a map that opens centred on "me" (moved each time) still works.

Which way a push goes on the map, and how far a push goes, is not set by hand: it is learnt while walking (the first
push goes straight, later ones are corrected by how the marker really moved), so a slanted view, a turned map or a
slow walker need no setting up.

step: {"type": "walk_to",
       "open": target, "close": target,        tap to open / close the map
       "anchor": {"button": id},               a find button on the map (the positions are relative to it)
       "anchors": [{"button": id, "x", "y"}],  optional: other signs and where they are (from the anchor): used when
                                               the anchor is not on the screen (a map that follows "me" far from it)
       "me": {"color": [r, g, b], "tol": 40, "min_px": 6, "box": [x, y, w, h]},   the marker: pixels this close to
                                               the colour, inside box (the map on the screen); the biggest patch
       "points": [{"x": dx, "y": dy, "near"}, ...],   where to go, in order (screen pixels of the map, from the
                                               anchor); "near" of a point: how close counts for it (default: the step's)
       "stick": {"x", "y", "r", "press"},      the direction control: centre and how far to push; press "drag" (from
                                               the centre out, the default; a control that starts where it is touched)
                                               or "edge" (hold it at the edge: full speed the whole push)
       "near": 10,                             close enough (pixels of the map)
       "push_ms": 1500,                        the longest push
       "max_moves": 40,                        give up after this many pushes
       "turn": 0, "speed": 14,                 optional: how the map is turned from the control (degrees; set: not
                                               learnt) and map pixels per second of push (set: a start, refined)
       "until": when,                          optional: done as soon as this holds (checked before each look at the
                                               map), e.g. "the place name says I am out of the safe area"
       "mini": {"box": [x, y, w, h], "mask": 14, "check_every": 5, "min_resp": 0.15}}
                                               optional: the small map that follows "me" (me in its middle). Between two
                                               looks at the big map, how far a push went is read from how the small map
                                               scrolled (the scale to the big map is learnt), so the big map opens only
                                               to learn the scale, every check_every pushes, near the end, or when the
                                               small map cannot tell. Where it cannot tell (plain ground: a bridge, a
                                               floor) or its guess turns out wrong at a look, it is not used again
                                               until the next point (full pushes, the big map after each)

A route network (路線網): when points have "links" (the numbers of the points it can walk straight to, either way),
the points are a network and the last point is where to go (and every point with "end": true: "here counts as there
too", e.g. each place where a bridge reaches the same platform). At the first look it goes to the nearest point (put
points on every bridge / corridor, so the nearest one is reachable from there), then along the shortest way through
the links. A link that turns out stuck is not used again in this walk and the way is planned again from where "me"
is (at most REPLANS times).

Walking a stretch without looking (照路線直接走): once "me" is at a point and the turn and speed are learnt, the
next links are pushed one after another without opening the map, each the way and as long as it takes (from the
map), until a checkpoint ("check": true), an end or the last point; there the map is looked at. A link may say how
to push it instead: "moves": [{"to": point number, "dir": 1-9 (as on a number pad: 6 right, 9 up right, 8 up...
of the control on the screen), "s": seconds}] (the way back is the opposite direction, the same seconds). At the
look: a little off (bumped into someone) -> pushes with a look after each to the point; far off (OFF) -> on a network
the way is planned again from the nearest point.

A push that went well off the way it was pushed (sliding along a wall or a rail) is not learnt from, and a push that
brings "me" no nearer counts towards "stuck" (it then tries to the side; after STUCK of them, off
the way, it first goes back to the point it came from and tries that leg again with a look after each push; then it
gives up the leg).
"""
import math

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

NEAR, PUSH_MS, MIN_MS, MAX_MOVES = 10, 1500, 250, 40
BLIND_MS = 30000                 # the longest link of a stretch walked without looking
SWIPE_MS = 8000                  # the longest single push (a longer one is sent as several in a row)
ON_LINK = 12                     # map px: this close to a link (a bridge between two points) = on it: start from it
OFF = 40                         # map px: further than this (and 3 x near) from where a stretch should end: off the way
NUMPAD = {6: 0, 3: 45, 2: 90, 1: 135, 4: 180, 7: -135, 8: -90, 9: -45}   # number pad -> degrees on the screen (y down)
PUSH_LAG = 350                   # ms of each push before "me" moves (a short push goes less far for its length)
FIRST_MS = 2500                  # the longest push while the speed is not learnt yet (a long one may overshoot a point)
CHECK_EVERY, MIN_RESP, MASK, MINI_MS = 5, 0.15, 14, 2500   # MINI_MS: the longest push read on the small map
TURN_OK = math.radians(40)       # a push that went further off than this slid along something: not learnt from
FLAT = 3.0                       # a small map whose gray spread is below this has nothing to follow
MINI_ERR = 10                    # map px: the small map's guess further off than this (at a look) -> not trusted here
STUCK = 5                       # pushes in a row that hardly moved: stuck (a wall)
SIDE = [0.6, -0.6, 1.2, -1.2]
REPLANS = 3                     # a route network: how many times a stuck link is given up for another way
AREA_PUSH_MS = 8000             # a walk map: the longest push before the next look (being stopped by something shows
SURE_MS = 12000                 # on the screen at once - see moving() - so a long one is no risk); a way walked
                                # through: at most this long without a look
VIEW_MIN = 60                   # view px: a walk map's view scale along an axis is learnt from at least this much
MOVE_REGION = (240, 140, 800, 400)   # the screen around "me" (the game's view follows it): it scrolls while walking
STILL_PX = 1.5                  # ... it moved less than this (screen px, about) between two pictures: standing
SURE_SHORT = 0.85               # ... the last push of such a stretch this much of what it seems to need (short of
                                # the point rather than past it: the speed varies; what is left is pushed after a look)
MERGE_DEG = 10                  # ... stretches this near the same way pushed as one (a new push starts slow)
CAREFUL = 3                     # ... after such a stretch went off the way: this many looks a push at a time
TRIES_APART = 60                # map px: stuck this far from where it was stuck last = another place (tries anew)
AREA_STUCK = 3                  # a walk map: pushes in a row that got no nearer: stuck there (marked, walked round)
AREA_REPLANS = 3                # a walk map: how many times stuck (each walked round) before giving up
MARK_AHEAD = 8                  # map px: a spot found blocked is marked this far ahead of where it got stuck
MARK_R = 7                      # map px: its size
STUCK_MS = 1500                 # how long a push is while feeling the way round something   # when a push hardly moved: try this much to the side (radians), in turn


def find_me(frame, box, color, tol=40, min_px=6, exclude=(), more=(), own=()):
    """(x, y) of the biggest patch of pixels within tol of color inside box (screen coordinates), or None.
    exclude: boxes [x, y, w, h] to leave out (a sign of the same colour, e.g. the anchor itself).
    more: other colours "me" may have (the map drawn another way at times, e.g. at night): tried after color.
    own: [(x, y, mask)] pixels to leave out - a sign's own pixels where it is (mask True), so "me" standing on the
    sign still shows."""
    for c in [color] + list(more or ()):
        got = _find_one(frame, box, c, tol, min_px, exclude, own)
        if got:
            return got
    return None


def sign_pixels(frame, pic, at, tol=40):
    """where a sign's picture (same colour order as frame) shows unchanged on frame with its top-left at at:
    (x, y, mask) for find_me's own (what differs from the picture - "me" on it - is not left out)"""
    x, y = int(at[0]), int(at[1])
    h, w = pic.shape[:2]
    a = np.asarray(frame)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(a.shape[1], x + w), min(a.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    d = np.abs(a[y0:y1, x0:x1, :3].astype(np.int16) - pic[y0 - y:y1 - y, x0 - x:x1 - x, :3].astype(np.int16)).max(axis=2)
    return (x0, y0, d <= tol)


def _find_one(frame, box, color, tol, min_px, exclude, own=()):
    if frame is None or not box or color is None:
        return None
    x0, y0, w, h = (int(v) for v in box)
    a = np.asarray(frame)[y0:y0 + h, x0:x0 + w, :3].astype(np.int16)
    if not a.size:
        return None
    m = (np.abs(a - np.array(color[:3], dtype=np.int16)).max(axis=2) <= int(tol)).astype(np.uint8)
    for ex in exclude or ():
        ex0, ey0, ew, eh = (int(v) for v in ex)
        m[max(0, ey0 - y0):max(0, ey0 - y0 + eh), max(0, ex0 - x0):max(0, ex0 - x0 + ew)] = 0
    for ox, oy, om in own or ():
        hh, ww = om.shape
        sy, sx = oy - y0, ox - x0
        ty0, tx0 = max(0, sy), max(0, sx)
        ty1, tx1 = min(m.shape[0], sy + hh), min(m.shape[1], sx + ww)
        if ty1 > ty0 and tx1 > tx0:
            m[ty0:ty1, tx0:tx1][om[ty0 - sy:ty1 - sy, tx0 - sx:tx1 - sx]] = 0
    if int(m.sum()) < int(min_px):
        return None
    if cv2 is None:
        ys, xs = np.nonzero(m)
        return [int(xs.mean()) + x0, int(ys.mean()) + y0]
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[best, cv2.CC_STAT_AREA] < int(min_px):
        return None
    cx, cy = cent[best]
    return [int(round(cx)) + x0, int(round(cy)) + y0]


def view_shift(before, after, region=MOVE_REGION):
    """how the game's view moved between two pictures: (dx, dy) screen px "me" went (the view's content went the other
    way), from the part around "me" - it follows "me"; None when it cannot tell"""
    if before is None or after is None or cv2 is None:
        return None
    a, b = _view_small(before, region), _view_small(after, region)
    if a is None or b is None or a.shape != b.shape:
        return None
    win = _hann(a.shape)
    (dx, dy), _r = cv2.phaseCorrelate(a, b, win)
    return (-4.0 * dx, -4.0 * dy)


def _view_small(img, region):
    x, y, w, h = region
    a = np.asarray(img)[y:y + h, x:x + w]
    if a.size == 0:
        return None
    a = cv2.cvtColor(np.ascontiguousarray(a[:, :, :3]), cv2.COLOR_RGB2GRAY) if a.ndim == 3 else a
    return cv2.resize(a, (a.shape[1] // 4, a.shape[0] // 4), interpolation=cv2.INTER_AREA).astype(np.float32)


_hanns = {}


def _hann(shape):
    if shape not in _hanns:
        _hanns[shape] = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
    return _hanns[shape]


def moving(before, after, region=MOVE_REGION):
    """how far the game's view scrolled between two pictures (screen px), from the part around "me" - it follows
    "me", so it stands still when "me" is stopped by something (whatever moves on it: monsters, effects)"""
    if before is None or after is None or cv2 is None:
        return None
    v = view_shift(before, after, region)
    return None if v is None else math.hypot(*v)


def mini_crop(frame, mini):
    """The small map as gray, its middle ("me", which never moves on it) flattened."""
    x, y, w, h = (int(v) for v in mini["box"])
    g = cv2.cvtColor(np.asarray(frame)[y:y + h, x:x + w, :3], cv2.COLOR_RGB2GRAY).astype(np.float32)
    m = int(mini.get("mask", MASK))
    if m:
        cy, cx = h // 2, w // 2
        g[max(0, cy - m):cy + m, max(0, cx - m):cx + m] = g.mean()
    return g


def mini_moved(before, after, mini):
    """How far "me" went between two small-map crops, in small-map pixels (the map scrolls the other way), or None
    when the two do not match well enough to tell (something covers it, a jump to another place)."""
    if before is None or after is None or before.shape != after.shape:
        return None
    if float(before.std()) < FLAT or float(after.std()) < FLAT:     # nothing on it to follow
        mini_moved.last = 0.0
        return None
    win = cv2.createHanningWindow(before.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(before, after, win)
    mini_moved.last = round(float(resp), 3)                  # how sure (for the log)
    if resp < float(mini.get("min_resp", MIN_RESP)):
        return None
    return (-dx, -dy)


def _seg_dist(p, a, b):
    """how far p is from the line between a and b"""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / max(dx * dx + dy * dy, 1e-9)))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Walk:
    """The plan of one walk_to: where to push next, from where "me" is now (relative to the anchor)."""

    def __init__(self, points, near=NEAR, push_ms=PUSH_MS, max_moves=MAX_MOVES, turn=None, speed=None, area=None,
                 tries=None):
        self.near, self.push_ms, self.max_moves = float(near), float(push_ms), int(max_moves)
        self.nodes = [(float(p["x"]), float(p["y"])) for p in points or []]
        self.node_nears = [float(p.get("near") or near) for p in points or []]
        self.labels = [p.get("label") or "#%d" % (i + 1) for i, p in enumerate(points or [])]
        n = len(self.nodes)
        self.links = sorted({tuple(sorted((i, int(j) - 1))) for i, p in enumerate(points or []) for j in p.get("links") or []
                             if 0 < int(j) <= n and int(j) - 1 != i})
        self.ends = sorted({n - 1} | {i for i, p in enumerate(points or []) if p.get("end")}) if n else []
        self.checks = [i for i, p in enumerate(points or []) if p.get("check")]
        self.leg_moves = {}                       # "a>b" (node numbers from 0) -> {"dir", "s"}: how to push that link
        for i, p in enumerate(points or []):
            for mv in p.get("moves") or []:
                j = int(mv.get("to") or 0) - 1
                if 0 <= j < n and j != i:
                    d = int(mv["dir"]) if mv.get("dir") in NUMPAD or str(mv.get("dir")) in map(str, NUMPAD) else None
                    self.leg_moves[f"{i}>{j}"] = {"dir": d, "s": mv.get("s")}
                    self.leg_moves.setdefault(f"{j}>{i}", {"dir": 10 - d if d else None, "s": mv.get("s")})
        self.blind = False                        # the last push was a stretch walked without looking
        self.route = None if self.links else list(range(n))     # node numbers to walk through (a network: planned at the first look)
        self.blocked, self.no_entry, self.replans, self.notes = [], [], 0, []
        self.points = [self.nodes[i] for i in self.route] if self.route is not None else []
        self.nears = [self.node_nears[i] for i in self.route] if self.route is not None else []
        self.idx, self.moves, self.stuck, self.leg = 0, 0, 0, 0
        self.turn = None if turn is None else math.radians(float(turn))   # map angle minus pushed angle (learnt unless set)
        self.turn_set = turn is not None
        self.speed = None if not speed else float(speed) / 1000           # map pixels per ms of push (learnt; set: a start)
        self.last, self.push = None, None
        self.area = area                          # (data root, walk map id): find the way on it to the last point
        if area:
            self.goal, self.goal_near, self.goal_label = self.nodes[-1], self.node_nears[-1], self.labels[-1]
            self.goals = [(self.nodes[i], self.node_nears[i], self.labels[i]) for i in self.ends]   # any of them will do
            self.route, self.marks = None, []     # planned at the first look; spots found blocked by walking
            self.tries = int(tries) if tries else AREA_REPLANS
            self.track, self.proven = [], False   # where it was at each look; the way planned was walked through before

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        w = cls.__new__(cls)
        w.__dict__.update(d)
        w.points = [tuple(p) for p in w.points]
        w.nodes = [tuple(p) for p in getattr(w, "nodes", w.points)]
        w.links = [tuple(k) for k in getattr(w, "links", [])]
        w.blocked = [tuple(k) for k in getattr(w, "blocked", [])]
        w.last = tuple(w.last) if w.last else None
        w.push = tuple(w.push) if w.push else None
        return w

    def step(self, me, chain=True):
        """me = (dx, dy) from the anchor -> ("arrived",) | ("push", angle (radians, screen: 0 = right, y down), ms)
        | ("push", angle, ms, [(angle, ms), ...]) (a stretch without looking: these pushes right after it)
        | ("stuck",) | ("too_far",) | ("no_way",) (a network with no way left)."""
        me = (float(me[0]), float(me[1]))
        if getattr(self, "route", 0) is None and not getattr(self, "area", None):   # a network: plan at the first look
            if not self.plan_from(me):
                return ("no_way",)
        if getattr(self, "area", None):
            self.track = list(getattr(self, "track", [])) + [[round(me[0], 1), round(me[1], 1)]]
            self.careful = max(0, getattr(self, "careful", 0) - 1)
        if self.last is not None and self.push is not None:      # learn from the last push
            dx, dy = me[0] - self.last[0], me[1] - self.last[1]
            moved = math.hypot(dx, dy)
            target = self.points[self.idx] if self.idx < len(self.points or []) else None
            gained = math.dist(self.last, target) - math.dist(me, target) if target else moved
            one = getattr(self, "blind", False) and len(getattr(self, "stretch", None) or []) == 1 and getattr(self, "area", None)
            if moved >= 2 and (not getattr(self, "blind", False) or one):   # (a stretch of turns without looking: not learnt from)
                t = _wrap(math.atan2(dy, dx) - self.push[0])
                odd = getattr(self, "odd", None)
                ok = (gained >= 0.3 * moved if self.turn is None else abs(_wrap(t - self.turn)) <= TURN_OK) or \
                    (odd is not None and abs(_wrap(t - odd)) <= TURN_OK)          # off twice the same way: the turn it is
                self.odd = None if ok else t
                if ok:          # went about where it was pushed (not sliding along a wall): learn the turn and the speed
                    if not getattr(self, "turn_set", False):
                        self.turn = t if self.turn is None else _wrap(self.turn + 0.5 * _wrap(t - self.turn))
                    sp = moved / max(self.push[1] - PUSH_LAG, 1)
                    self.speed = sp if self.speed is None else 0.5 * self.speed + 0.5 * sp
            d = math.dist(me, target) if target else 0.0
            if getattr(self, "best_leg", None) != self.leg:     # a new point to go to
                self.best_leg, self.best = self.leg, math.dist(self.last, target) if target else 0.0
            if d < self.best - 3:                                 # nearer than it ever was on this leg
                self.best, self.stuck = d, 0
            else:                                                 # no nearer (a wall, swaying to and fro): stuck
                self.stuck += 1
        if getattr(self, "area", None):
            return self._step_area(me)
        if getattr(self, "blind", False):                        # a checkpoint after a stretch walked without looking
            self.blind = False
            if self.idx < len(self.points) and math.dist(me, self.points[self.idx]) > self.nears[self.idx]:
                self.no_blind = list(getattr(self, "no_blind", [])) + list(self.stretch)   # not without looking again
            if self.idx < len(self.points) and getattr(self, "links", None) and                     math.dist(me, self.points[self.idx]) > max(OFF, 3 * self.nears[self.idx]):
                self.notes.append(("off", self.labels[self.route[self.idx]]))
                if getattr(self, "area", None):                   # someone in the way: a push at a time past it
                    self.careful = CAREFUL + 1
                if not self.plan_from(me):                        # far off the way: from the nearest point again
                    return ("no_way",)
                self.stuck = 0
        nears = getattr(self, "nears", None) or [self.near] * len(self.points)
        while self.idx < len(self.points) and math.dist(me, self.points[self.idx]) <= nears[self.idx]:
            self.idx += 1
            self.leg = getattr(self, "leg", 0) + 1
        if self.idx >= len(self.points):
            return ("arrived",)
        if self.stuck >= AREA_STUCK and getattr(self, "area", None):   # a walk map: that spot is blocked, round it
            if self.replans >= getattr(self, "tries", AREA_REPLANS):
                return ("stuck",)
            tx, ty = self.points[self.idx]
            d = math.dist(me, (tx, ty)) or 1.0
            k = min(MARK_AHEAD, d) / d
            self.marks.append([round(me[0] + (tx - me[0]) * k, 1), round(me[1] + (ty - me[1]) * k, 1), MARK_R])
            self.notes.append(("mark", (round(me[0]), round(me[1]))))
            if not self.plan_from(me):
                return ("no_way",)
            self.stuck, self.replans = 0, self.replans + 1
        if self.stuck >= STUCK and self.idx > 0 and math.dist(me, self.points[self.idx - 1]) > self.nears[self.idx - 1]                 and f"{self.route[self.idx - 1]}>{self.route[self.idx]}" not in (getattr(self, "backed", None) or []):
            back = self.route[self.idx - 1]                       # off the way in a pocket: first back to the point
            self.backed = list(getattr(self, "backed", None) or []) + [f"{back}>{self.route[self.idx]}"]   # before (it
            self.route.insert(self.idx, back)                     # was reached), then this leg again, a look each push
            self.points.insert(self.idx, self.nodes[back])
            self.nears.insert(self.idx, self.node_nears[back])
            self.notes.append(("back", self.labels[back]))
            self.stuck, self.leg = 0, getattr(self, "leg", 0) + 1
            self.no_blind = list(getattr(self, "no_blind", None) or []) + [f"{back}>{self.route[self.idx + 1]}"]
        if self.stuck >= STUCK:
            if not getattr(self, "links", None) or self.replans >= REPLANS:
                return ("stuck",)
            self.give_up_leg()                                     # a network: another way round
            if not self.plan_from(me):
                return ("no_way",)
            self.stuck, self.replans = 0, self.replans + 1
            nears = self.nears
            while self.idx < len(self.points) and math.dist(me, self.points[self.idx]) <= nears[self.idx]:
                self.idx += 1
            if self.idx >= len(self.points):
                return ("arrived",)
        if self.moves >= self.max_moves:
            return ("too_far",)
        if getattr(self, "area", None) and not getattr(self, "proven", False) and self.idx < len(self.points):
            from . import walkmap                                 # the rest of the way from here walked through before?
            self.proven = walkmap.proven(walkmap.load(*self.area), [me] + list(self.points[self.idx:]))
            if self.proven:
                self.notes.append(("proven",))
        chain = self._chain(me) if chain and not self.stuck else []
        if chain:                                                 # at a point: the next links without looking
            self.last, self.push, self.blind = me, (chain[0][0], sum(c[1] for c in chain)), True
            self.leg = getattr(self, "leg", 0) + 1
            self.moves += 1
            return ("push", chain[0][0], int(chain[0][1]), [(a, int(m)) for a, m in chain[1:]])
        tx, ty = self.points[self.idx]
        dist = math.hypot(tx - me[0], ty - me[1])
        angle = _wrap(math.atan2(ty - me[1], tx - me[0]) - (self.turn or 0.0))
        if self.stuck:                                            # hardly moved: try to the side
            angle = _wrap(angle + SIDE[(self.stuck - 1) % len(SIDE)])
        ms = min(self.push_ms, FIRST_MS) if not self.speed else max(MIN_MS, min(self.push_ms, dist / self.speed + PUSH_LAG))
        if getattr(self, "area", None):                           # a walk map: look again before it drifts far
            ms = min(ms, SURE_MS if self.sure() else AREA_PUSH_MS)
            if self.sure() and self.speed:
                ms = max(MIN_MS, PUSH_LAG + (ms - PUSH_LAG) * SURE_SHORT)
        if self.stuck:                                            # feeling the way round: short pushes
            ms = min(ms, STUCK_MS)
        self.last, self.push = me, (angle, ms)
        self.moves += 1
        return ("push", angle, int(ms))


    def _chain(self, me):
        """At a point (the one before self.idx): the links from it, each as (angle, ms), as far as the next checkpoint /
        end / the last point - each pushed as set on the link ("moves"), else as the map and the learnt turn and speed
        say (nothing when they are not learnt yet). self.idx moves to where the stretch ends."""
        if self.idx == 0 or math.dist(me, self.points[self.idx - 1]) > self.nears[self.idx - 1]:
            return []
        legs, pos, j, r = [], me, self.idx, self.route
        sure = self.sure()
        moves = getattr(self, "leg_moves", None) or {}
        stretch = []
        while j < len(self.points):
            a, b = r[j - 1], r[j]
            if f"{a}>{b}" in (getattr(self, "no_blind", None) or []):   # went wrong without looking before: with looks
                break
            mv = moves.get(f"{a}>{b}") or {}
            tx, ty = self.points[j]
            if mv.get("dir"):
                angle = math.radians(NUMPAD[int(mv["dir"])])
            elif self.turn is not None:
                angle = math.atan2(ty - pos[1], tx - pos[0]) - self.turn
            else:
                break
            if mv.get("s"):
                ms = float(mv["s"]) * 1000
            elif self.speed:
                ms = math.dist(pos, (tx, ty)) / self.speed + PUSH_LAG
            else:
                break
            ms = max(MIN_MS, min(ms, BLIND_MS))
            if sure and legs and sum(m for _a, m in legs) + ms > SURE_MS:   # a look now and then even so
                break
            if getattr(self, "area", None) and ms > AREA_PUSH_MS and not sure:   # a walk map: a long stretch with looks
                break
            while ms > SWIPE_MS:                                   # one push is at most SWIPE_MS: the rest after it
                legs.append((_wrap(angle), SWIPE_MS))
                ms -= SWIPE_MS - PUSH_LAG
            legs.append((_wrap(angle), ms))
            stretch.append(f"{a}>{b}")
            pos, j = (tx, ty), j + 1
            if (b in (getattr(self, "checks", None) or []) and not sure) or b in (getattr(self, "ends", None) or []):
                break
        if legs:
            if sure:
                a, m = legs[-1]
                legs[-1] = (a, max(MIN_MS, PUSH_LAG + (m - PUSH_LAG) * SURE_SHORT))
            self.idx, self.stretch = j - 1, stretch
        return legs

    def learn_view(self, s, d):
        """the game's view moved s (screen px, summed) while "me" went d on the map (between two looks): how many map
        px a view px is, along each axis (the view looks at the map from the side: the two differ)"""
        st = getattr(self, "view_st", None) or [0.0, 0.0, 0.0, 0.0]
        st = [st[0] + s[0] * s[0], st[1] + s[0] * d[0], st[2] + s[1] * s[1], st[3] + s[1] * d[1]]
        self.view_st = st
        k = list(getattr(self, "view", None) or [None, None])
        for i, (ss, sd) in enumerate(((st[0], st[1]), (st[2], st[3]))):
            if ss >= VIEW_MIN ** 2 and sd > 0:
                k[i] = sd / ss
        self.view = k

    def view_ok(self):
        v = getattr(self, "view", None)
        return bool(v) and all(x for x in v)

    def _area_way(self, wm, me):
        """the shortest way to any of the goals (the last point, and any point marked as an end); that goal is
        self.goal from now on"""
        from . import walkmap
        best = None
        for marks_too in (True, False):                           # spots found blocked before (a crowd of monsters,
            w = wm if marks_too else {**wm, "marks": []}          # maybe): without them when there is no way else
            for g, near, label in getattr(self, "goals", None) or [(self.goal, self.goal_near, self.goal_label)]:
                pts = walkmap.plan(w, me, g, self.marks)
                if pts:
                    d = sum(math.dist(a, b) for a, b in zip([me] + pts, pts))
                    if best is None or d < best[0]:
                        best = (d, pts, g, near, label)
            if best or not wm.get("marks"):
                break
        if not best:
            return None
        _d, pts, self.goal, self.goal_near, self.goal_label = best
        return pts

    def _step_area(self, me):
        """a walk map: the way planned again from where "me" is at every look (no going back to a point it missed);
        stuck = the way left got no shorter for AREA_STUCK pushes: that spot is marked blocked and walked round"""
        from . import walkmap
        wm = walkmap.load(*self.area)
        if not wm:
            return ("no_way",)
        if not self.view_ok() and wm.get("view") and not getattr(self, "view_st", None):
            self.view = list(wm["view"])                          # learnt on earlier walks
        if any(math.dist(me, g) <= near for g, near, _l in getattr(self, "goals", None) or [(self.goal, self.goal_near, 0)]):
            return ("arrived",)
        pts = self._area_way(wm, me)
        if not pts:
            return ("no_way",)
        left = sum(math.dist(a, b) for a, b in zip([me] + pts, pts))
        expect = getattr(self, "expect", None)                    # a stretch in one go that got far less far than
        gone = self.left - left if expect and getattr(self, "left", None) is not None else None
        if gone is not None and gone < 0.5 * expect:              # meant: someone in the way - a push at a time past it
            self.careful = CAREFUL
            self.notes.append(("off", self.labels[-1] if self.labels else ""))
        elif gone is not None and getattr(self, "sent", None):    # how fast it really goes, turns and all: learnt
            ms, n = self.sent
            if ms - n * PUSH_LAG > 500:
                sp = gone / (ms - n * PUSH_LAG)
                self.speed = sp if not self.speed else 0.5 * self.speed + 0.5 * sp
        self.expect, self.sent = None, None
        best = getattr(self, "best_left", None)
        if best is None or left < best - 3:
            self.best_left, self.stuck = left, 0
        else:
            self.stuck += 1
        if getattr(self, "force_stuck", False):              # stopped at once, hardly moved: the thing is right
            self.stuck, self.force_stuck = max(self.stuck, AREA_STUCK), False   # ahead - no trying it again
        if self.stuck >= AREA_STUCK:
            if self.marks and math.dist(me, self.marks[-1][:2]) > TRIES_APART:   # got on since the last one: a new
                self.replans = 0                                  # place, its own tries
            if self.replans >= getattr(self, "tries", AREA_REPLANS):
                return ("stuck",)
            tx, ty = pts[0]
            d = math.dist(me, (tx, ty)) or 1.0
            k = min(MARK_AHEAD, d) / d
            self.marks.append([round(me[0] + (tx - me[0]) * k, 1), round(me[1] + (ty - me[1]) * k, 1), MARK_R])
            self.notes.append(("mark", (round(me[0]), round(me[1]))))
            self.replans, self.stuck, self.best_left = self.replans + 1, 0, None
            pts = self._area_way(wm, me)
            if not pts:                                           # that was the only way: not blocked for good -
                self.marks.pop()                                  # someone in it, maybe; feel round it again
                self.notes.pop()
                self.notes.append(("squeeze", (round(me[0]), round(me[1]))))
                pts = self._area_way(wm, me)
                self.stuck = 1                                    # (pushes to the side)
            if not pts:
                return ("no_way",)
            left = sum(math.dist(a, b) for a, b in zip([me] + pts, pts))
        self.left = left
        n = len(pts)
        self.nodes = self.points = [tuple(p) for p in pts]
        self.node_nears = self.nears = [self.near] * (n - 1) + [self.goal_near]
        self.labels = [_ptlabel(i + 1) for i in range(n - 1)] + [self.goal_label]
        self.route, self.idx = list(range(n)), 0
        was = getattr(self, "proven", None)
        self.proven_k = walkmap.proven_upto(wm, [me] + self.points)   # how far along the way was walked through
        self.proven = self.proven_k > 0
        if was is None:
            self.notes.append(("area", n, round(left), self.proven))
        elif self.proven and not was:
            self.notes.append(("proven",))
        if self.moves >= self.max_moves:
            return ("too_far",)
        sure = self.sure()
        legs, pos, total = [], me, 0.0
        last = len(self.points) - 1
        for k, p in enumerate(self.points):
            if sure and legs and k >= self.proven_k:              # past the way walked through: a look first
                break
            if sure and k == last and legs:                       # the goal: not in one go with the rest (the speed
                break                                             # varies - a look first, then up to it)
            angle = _wrap(math.atan2(p[1] - pos[1], p[0] - pos[0]) - (self.turn or 0.0))
            go = math.dist(pos, p)
            if k == last:                                         # into the goal: only to its near side (it is there
                go = max(go - 0.5 * self.goal_near, 0.5 * go)     # once within goal_near)
            ms = go / self.speed + PUSH_LAG if self.speed else FIRST_MS
            if not sure:
                if self.stuck:                                    # no shorter: try to the side, short pushes
                    angle = _wrap(angle + SIDE[(self.stuck - 1) % len(SIDE)])
                    ms = min(ms, STUCK_MS)
                legs = [(angle, max(MIN_MS, min(ms, AREA_PUSH_MS, self.push_ms)))]
                break
            if legs and total + ms > SURE_MS:
                break
            if legs and abs(_wrap(angle - legs[-1][0])) < math.radians(MERGE_DEG):   # about the same way: one push
                legs[-1] = (legs[-1][0], legs[-1][1] + ms - PUSH_LAG)            # (no new start between them)
            else:
                legs.append((angle, max(MIN_MS, min(ms, SURE_MS))))
            total += ms
            pos = p
        if sure:
            a, m = legs[-1]
            legs[-1] = (a, max(MIN_MS, PUSH_LAG + (m - PUSH_LAG) * SURE_SHORT))
            self.expect = None
            q, d, t = me, 0.0, 0.0                                # how far along the way the pushes should take it
            for p in self.points:
                step = math.dist(q, p) / self.speed + PUSH_LAG
                if t + step > total + 1:
                    break
                t, d, q = t + step, d + math.dist(q, p), p
            self.expect = d * SURE_SHORT if d else None
            self.sent = (sum(m for _a, m in legs), len(legs))
        out = []
        for a, m in legs:                                         # one push is at most SWIPE_MS
            while m > SWIPE_MS:
                out.append((a, SWIPE_MS))
                m -= SWIPE_MS - PUSH_LAG
            out.append((a, m))
        self.blind = len(legs) > 1
        self.stretch = [f"{i}>{i + 1}" for i in range(len(legs))]
        self.idx = len(legs) - 1 if self.blind else 0
        self.last, self.push = me, (legs[0][0], sum(m for _a, m in legs))
        self.moves += 1
        if len(out) > 1:
            return ("push", out[0][0], int(out[0][1]), [(a, int(m)) for a, m in out[1:]])
        return ("push", out[0][0], int(out[0][1]))

    def sure(self):
        """a walk map: the way planned was walked through before (nothing fixed in the way): the rest of it in one go,
        a look only at the end (someone in the way now is an accident: walked round from where it stopped)"""
        return bool(getattr(self, "area", None)) and bool(getattr(self, "proven", False)) and bool(self.speed)             and not self.stuck and not getattr(self, "careful", 0)

    # ---------- a route network ----------
    def target_no(self):
        """the number (1..) of the point it is heading for, as in the step's list"""
        r = getattr(self, "route", None)
        return (r[self.idx] if r and self.idx < len(r) else self.idx) + 1

    def give_up_leg(self):
        """the leg it got stuck on is not used again: a link between two points, or from where it was to its first point"""
        to = self.route[self.idx]
        if self.idx > 0:
            frm = self.route[self.idx - 1]
            self.blocked.append(tuple(sorted((frm, to))))
            self.notes.append(("blocked", self.labels[frm], self.labels[to]))
        else:
            self.no_entry.append(to)
            self.notes.append(("blocked", None, self.labels[to]))

    def plan_from(self, me):
        """the way from me: to the nearest point it may start from, then the shortest way through the links to the last
        point. False when there is none."""
        if getattr(self, "area", None):
            return self._plan_area(me)
        n = len(self.nodes)
        if n == 0:
            return False
        ends = getattr(self, "ends", None) or [n - 1]
        nb = {i: [] for i in range(n)}
        for a, b in self.links:
            if (a, b) not in self.blocked:
                nb[a].append(b)
                nb[b].append(a)
        dist, prev, todo = {e: 0.0 for e in ends}, {}, set(ends)   # from the ends back (the links go both ways)
        while todo:
            u = min(todo, key=dist.get)
            todo.discard(u)
            for v in nb[u]:
                d = dist[u] + math.dist(self.nodes[u], self.nodes[v])
                if d < dist.get(v, float("inf")):
                    dist[v], prev[v] = d, u
                    todo.add(v)
        starts = [i for i in dist if i not in self.no_entry]
        if not starts:
            return False
        s = min(starts, key=lambda i: math.dist(me, self.nodes[i]))
        on = [(_seg_dist(me, self.nodes[a], self.nodes[b]), a, b) for a, b in self.links if (a, b) not in self.blocked]
        on = [o for o in on if o[0] <= ON_LINK and o[0] < math.dist(me, self.nodes[s])]
        if on:                                                    # on a link (a bridge): go on along it, to the nearer end
            _d, a, b = min(on)
            ends_ok = [i for i in (a, b) if i in starts]
            if ends_ok:
                s = min(ends_ok, key=lambda i: math.dist(me, self.nodes[i]) + dist[i])
        route = [s]
        while route[-1] not in ends:
            route.append(prev[route[-1]])
        self.route, self.idx, self.leg = route, 0, getattr(self, "leg", 0) + 1
        self.points = [self.nodes[i] for i in route]
        self.nears = [self.node_nears[i] for i in route]
        self.last = self.push = None                               # the next push is not learnt against the old way
        self.notes.append(("route", [self.labels[i] for i in route]))
        return True


    def _plan_area(self, me):
        """a walk map: the way from me to the goal on it, as a row of points (a look at each)"""
        from . import walkmap
        wm = walkmap.load(*self.area)
        pts = walkmap.plan(wm, me, self.goal, self.marks) if wm else None
        if wm and not pts and wm.get("marks"):                    # spots found blocked before (a crowd of monsters,
            pts = walkmap.plan({**wm, "marks": []}, me, self.goal, self.marks)   # maybe): without them
        if not pts:
            return False
        n = len(pts)
        self.nodes = [tuple(p) for p in pts]
        self.node_nears = [self.near] * (n - 1) + [self.goal_near]
        self.labels = [_ptlabel(i + 1) for i in range(n - 1)] + [self.goal_label]
        self.links = [(i, i + 1) for i in range(n - 1)]
        self.checks, self.ends = list(range(n)), [n - 1]
        self.blocked, self.no_entry, self.leg_moves, self.no_blind = [], [], {}, []
        self.route, self.idx, self.leg = list(range(n)), 0, getattr(self, "leg", 0) + 1
        self.points, self.nears = list(self.nodes), list(self.node_nears)
        self.last = self.push = None
        self.proven = walkmap.proven(wm, [me] + self.nodes)
        if wm.get("speed") and not getattr(self, "speed_from_map", False):   # the speed learnt on earlier walks
            self.speed, self.speed_from_map = float(wm["speed"]) / 1000, True
        self.notes.append(("area", n, round(sum(math.dist(a, b) for a, b in zip([me] + self.nodes, self.nodes))), self.proven))
        return True


def _ptlabel(i):
    from i18n import _
    return _("路徑點 {n}", n=i)


def stick_end(stick, angle):
    """Where a push at angle ends on the control."""
    r = float(stick.get("r", 60))
    return [int(round(float(stick["x"]) + r * math.cos(angle))), int(round(float(stick["y"]) + r * math.sin(angle)))]
