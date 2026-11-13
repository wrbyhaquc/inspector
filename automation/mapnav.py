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
brings "me" no nearer counts towards "stuck" (it then tries to the side, and gives up after STUCK of them).
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

    def __init__(self, points, near=NEAR, push_ms=PUSH_MS, max_moves=MAX_MOVES, turn=None, speed=None):
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
        if getattr(self, "route", 0) is None:                     # a network: plan the way at the first look
            if not self.plan_from(me):
                return ("no_way",)
        if self.last is not None and self.push is not None:      # learn from the last push
            dx, dy = me[0] - self.last[0], me[1] - self.last[1]
            moved = math.hypot(dx, dy)
            target = self.points[self.idx] if self.idx < len(self.points) else None
            gained = math.dist(self.last, target) - math.dist(me, target) if target else moved
            if moved >= 2 and not getattr(self, "blind", False):     # (a stretch walked without looking: not learnt from)
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
        if getattr(self, "blind", False):                        # a checkpoint after a stretch walked without looking
            self.blind = False
            if self.idx < len(self.points) and math.dist(me, self.points[self.idx]) > self.nears[self.idx]:
                self.no_blind = list(getattr(self, "no_blind", [])) + list(self.stretch)   # not without looking again
            if self.idx < len(self.points) and getattr(self, "links", None) and                     math.dist(me, self.points[self.idx]) > max(OFF, 3 * self.nears[self.idx]):
                self.notes.append(("off", self.labels[self.route[self.idx]]))
                if not self.plan_from(me):                        # far off the way: from the nearest point again
                    return ("no_way",)
                self.stuck = 0
        nears = getattr(self, "nears", None) or [self.near] * len(self.points)
        while self.idx < len(self.points) and math.dist(me, self.points[self.idx]) <= nears[self.idx]:
            self.idx += 1
            self.leg = getattr(self, "leg", 0) + 1
        if self.idx >= len(self.points):
            return ("arrived",)
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
            while ms > SWIPE_MS:                                   # one push is at most SWIPE_MS: the rest after it
                legs.append((_wrap(angle), SWIPE_MS))
                ms -= SWIPE_MS - PUSH_LAG
            legs.append((_wrap(angle), ms))
            stretch.append(f"{a}>{b}")
            pos, j = (tx, ty), j + 1
            if b in (getattr(self, "checks", None) or []) or b in (getattr(self, "ends", None) or []):
                break
        if legs:
            self.idx, self.stretch = j - 1, stretch
        return legs

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


def stick_end(stick, angle):
    """Where a push at angle ends on the control."""
    r = float(stick.get("r", 60))
    return [int(round(float(stick["x"]) + r * math.cos(angle))), int(round(float(stick["y"]) + r * math.sin(angle)))]
