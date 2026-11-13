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

A push that went well off the way it was pushed (sliding along a wall or a rail) is not learnt from, and a push that
brings "me" no nearer counts towards "stuck" (it then tries to the side, and gives up after STUCK of them).
"""
import math

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

NEAR, PUSH_MS, MIN_MS, MAX_MOVES = 10, 1500, 250, 40
CHECK_EVERY, MIN_RESP, MASK, MINI_MS = 5, 0.15, 14, 2500   # MINI_MS: the longest push read on the small map
TURN_OK = math.radians(40)       # a push that went further off than this slid along something: not learnt from
FLAT = 3.0                       # a small map whose gray spread is below this has nothing to follow
MINI_ERR = 10                    # map px: the small map's guess further off than this (at a look) -> not trusted here
STUCK = 5                       # pushes in a row that hardly moved: stuck (a wall)
SIDE = [0.6, -0.6, 1.2, -1.2]
STUCK_MS = 1500                 # how long a push is while feeling the way round something   # when a push hardly moved: try this much to the side (radians), in turn


def find_me(frame, box, color, tol=40, min_px=6, exclude=()):
    """(x, y) of the biggest patch of pixels within tol of color inside box (screen coordinates), or None.
    exclude: boxes [x, y, w, h] to leave out (a sign of the same colour, e.g. the anchor itself)."""
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


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Walk:
    """The plan of one walk_to: where to push next, from where "me" is now (relative to the anchor)."""

    def __init__(self, points, near=NEAR, push_ms=PUSH_MS, max_moves=MAX_MOVES):
        self.points = [(float(p["x"]), float(p["y"])) for p in points or []]
        self.nears = [float(p.get("near") or near) for p in points or []]
        self.near, self.push_ms, self.max_moves = float(near), float(push_ms), int(max_moves)
        self.idx, self.moves, self.stuck = 0, 0, 0
        self.turn = None                 # map angle minus pushed angle (learnt)
        self.speed = None                # map pixels per ms of push (learnt)
        self.last, self.push = None, None

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        w = cls.__new__(cls)
        w.__dict__.update(d)
        w.points = [tuple(p) for p in w.points]
        w.last = tuple(w.last) if w.last else None
        w.push = tuple(w.push) if w.push else None
        return w

    def step(self, me):
        """me = (dx, dy) from the anchor -> ("arrived",) | ("push", angle (radians, screen: 0 = right, y down), ms)
        | ("stuck",) | ("too_far",)."""
        me = (float(me[0]), float(me[1]))
        if self.last is not None and self.push is not None:      # learn from the last push
            dx, dy = me[0] - self.last[0], me[1] - self.last[1]
            moved = math.hypot(dx, dy)
            target = self.points[self.idx] if self.idx < len(self.points) else None
            gained = math.dist(self.last, target) - math.dist(me, target) if target else moved
            if moved >= 2:
                t = _wrap(math.atan2(dy, dx) - self.push[0])
                odd = getattr(self, "odd", None)
                ok = (gained >= 0.3 * moved if self.turn is None else abs(_wrap(t - self.turn)) <= TURN_OK) or \
                    (odd is not None and abs(_wrap(t - odd)) <= TURN_OK)          # off twice the same way: the turn it is
                self.odd = None if ok else t
                if ok:          # went about where it was pushed (not sliding along a wall): learn the turn and the speed
                    self.turn = t if self.turn is None else _wrap(self.turn + 0.5 * _wrap(t - self.turn))
                    sp = moved / max(self.push[1], 1)
                    self.speed = sp if self.speed is None else 0.5 * self.speed + 0.5 * sp
            if moved >= 2 and gained >= 2:
                self.stuck = 0
            else:                                                 # hardly moved, or moved but no nearer
                self.stuck += 1
        nears = getattr(self, "nears", None) or [self.near] * len(self.points)
        while self.idx < len(self.points) and math.dist(me, self.points[self.idx]) <= nears[self.idx]:
            self.idx += 1
        if self.idx >= len(self.points):
            return ("arrived",)
        if self.stuck >= STUCK:
            return ("stuck",)
        if self.moves >= self.max_moves:
            return ("too_far",)
        tx, ty = self.points[self.idx]
        dist = math.hypot(tx - me[0], ty - me[1])
        angle = _wrap(math.atan2(ty - me[1], tx - me[0]) - (self.turn or 0.0))
        if self.stuck:                                            # hardly moved: try to the side
            angle = _wrap(angle + SIDE[(self.stuck - 1) % len(SIDE)])
        ms = self.push_ms if not self.speed else max(MIN_MS, min(self.push_ms, dist / self.speed))
        if self.stuck:                                            # feeling the way round: short pushes
            ms = min(ms, STUCK_MS)
        self.last, self.push = me, (angle, ms)
        self.moves += 1
        return ("push", angle, int(ms))


def stick_end(stick, angle):
    """Where a push at angle ends on the control."""
    r = float(stick.get("r", 60))
    return [int(round(float(stick["x"]) + r * math.cos(angle))), int(round(float(stick["y"]) + r * math.sin(angle)))]
