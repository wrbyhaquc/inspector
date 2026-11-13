"""walk_to (走到地圖上的位置): find "me" on a map by colour, learn which way a push goes, walk through the points."""
import math
from concurrent.futures import Future

import numpy as np

from automation import mapnav
from automation.runner import SubRun


def test_find_me_takes_the_biggest_patch_and_leaves_out_the_anchor():
    f = np.zeros((200, 300, 3), np.uint8)
    f[50:60, 100:110] = (210, 85, 50)                 # me
    f[150:154, 20:24] = (212, 86, 52)                 # a speck
    f[100:115, 200:215] = (208, 100, 70)              # the anchor (same colour)
    assert mapnav.find_me(f, [0, 0, 300, 200], [210, 84, 50], 30, 6, [[195, 95, 25, 25]]) == [104, 54] or \
        mapnav.find_me(f, [0, 0, 300, 200], [210, 84, 50], 30, 6, [[195, 95, 25, 25]]) == [105, 55]
    assert mapnav.find_me(f, [0, 0, 90, 90], [210, 84, 50], 30, 6) is None


class World:
    """me on a map: a push at angle a goes (a + turn) on the map, speed px per ms (both unknown to the walker)."""
    def __init__(self, turn, speed, start=(0.0, 0.0)):
        self.turn, self.speed, self.pos = turn, speed, list(start)


def test_the_plan_learns_the_turn_and_gets_there():
    w = World(turn=0.9, speed=0.01)
    plan = mapnav.Walk([{"x": 60, "y": -40}, {"x": 150, "y": -90}], near=6, push_ms=1500, max_moves=40)
    for _ in range(40):
        what = plan.step(w.pos)
        if what[0] != "push":
            break
        a, ms = what[1], what[2]
        w.pos[0] += w.speed * ms * math.cos(a + w.turn)
        w.pos[1] += w.speed * ms * math.sin(a + w.turn)
    assert what == ("arrived",), (what, w.pos, plan.moves)
    assert plan.moves < 25


def test_a_wall_is_stuck():
    plan = mapnav.Walk([{"x": 100, "y": 0}])
    assert [plan.step((0, 0))[0] for _ in range(7)][-1] == "stuck"


class Exec:
    def __init__(self, world, stick):
        self.w, self.stick, self.log = world, stick, []

    def submit(self, device, kind, **kw):
        self.log.append(kind)
        if kind == "swipe":
            a = math.atan2(kw["y2"] - self.stick["y"], kw["x2"] - self.stick["x"])   # from the control's centre
            self.w.pos[0] += self.w.speed * kw["ms"] * math.cos(a + self.w.turn)
            self.w.pos[1] += self.w.speed * kw["ms"] * math.sin(a + self.w.turn)
        fu = Future()
        fu.set_result(None)
        return fu


class Env:
    def __init__(self, world):
        self.w = world

    def ctx(self, device):
        return {}

    def map_me(self, n, anchor, me):
        return (400, 300), (400 + self.w.pos[0], 300 + self.w.pos[1])


def test_the_step_walks_there_in_strides():
    w = World(turn=-0.5, speed=0.02)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 80, "y": 30}, {"x": 200, "y": -60}],
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 8}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st, {"type": "wait", "seconds": 0.01}]}}
    run, logs, ex = SubRun("A", "go", {}, lib, 0.0), [], Exec(w, st["stick"])
    run._env = Env(w)
    t = 0.0
    while not run.done and t < 600:
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), Env(w))
        t += 0.5
    assert run.result == "success", logs[-5:]
    assert math.dist(w.pos, (200, -60)) <= 8 and ex.log.count("swipe") >= 2 and ex.log[-1] == "tap"


class EnvOut(Env):
    """"until": out once x passes 50"""
    def ctx(self, device):
        return {"vars": {"out": 1 if self.w.pos[0] > 50 else 0}}


def test_until_ends_the_walk_early():
    w = World(turn=0.0, speed=0.02)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 300, "y": 0}],
          "stick": {"x": 192, "y": 570, "r": 60, "press": "edge"}, "push_ms": 1500,
          "until": [[{"kind": "var", "var": "out", "op": "is", "value": 1}]]}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st]}}
    run, ex = SubRun("A", "go", {}, lib, 0.0), Exec(w, st["stick"])
    t = 0.0
    while not run.done and t < 600:
        run.advance({}, t, ex, {}, lambda text, level="": None, EnvOut(w))
        t += 0.5
    assert run.result == "success" and 50 < w.pos[0] < 200


class MiniEnv(Env):
    """The small map: a textured world around "me", 1 small-map px = 1.85 big-map px; frames carry the time."""
    SCALE = 1.85

    def __init__(self, world):
        super().__init__(world)
        rng = np.random.default_rng(3)
        tex = rng.integers(0, 255, (900, 900)).astype(np.uint8)
        import cv2
        self.tex = cv2.GaussianBlur(tex, (0, 0), 3)
        self.t = 0.0

    def latest_frame(self, n):
        f = np.zeros((720, 1280, 3), np.uint8)
        cx, cy = 450 + int(round(self.w.pos[0] / self.SCALE)), 450 + int(round(self.w.pos[1] / self.SCALE))
        crop = self.tex[cy - 74:cy + 74, cx - 83:cx + 83]
        f[130:278, 1078:1244] = crop[:, :, None]
        return self.t, f


def test_with_the_small_map_the_big_map_opens_only_now_and_then():
    w = World(turn=0.3, speed=0.02)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 150, "y": 0}, {"x": 300, "y": -100}],
          "stick": {"x": 192, "y": 570, "r": 60, "press": "edge"}, "near": 10, "push_ms": 1500,
          "mini": {"box": [1078, 130, 166, 148], "check_every": 6}}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st]}}
    run, ex, env, logs = SubRun("A", "go", {}, lib, 0.0), Exec(w, st["stick"]), MiniEnv(w), []
    t = 0.0
    while not run.done and t < 900:
        env.t = t
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), env)
        t += 0.5
    assert run.result == "success", logs[-6:]
    assert math.dist(w.pos, (300, -100)) <= 10
    opens = sum(1 for k in ex.log if k == "tap") // 2
    pushes = ex.log.count("swipe")
    assert pushes >= 6 and opens < pushes / 2, (opens, pushes)
    assert any("看小地圖" in x for x in logs)


class FlatEnv(MiniEnv):
    """A small map with nothing on it (a plain bridge): it cannot tell how far a push went."""
    def latest_frame(self, n):
        f = np.full((720, 1280, 3), 90, np.uint8)
        return self.t, f


class SwipeLog(Exec):
    def __init__(self, world, stick):
        super().__init__(world, stick)
        self.ms = []

    def submit(self, device, kind, **kw):
        if kind == "swipe":
            self.ms.append(kw["ms"])
        return super().submit(device, kind, **kw)


def test_where_the_small_map_cannot_tell_it_walks_on_the_big_map_with_full_pushes():
    w = World(turn=0.0, speed=0.01)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 300, "y": 0}],
          "stick": {"x": 192, "y": 570, "r": 60, "press": "edge"}, "near": 10, "push_ms": 5000,
          "mini": {"box": [1078, 130, 166, 148]}}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st]}}
    run, ex, env, logs = SubRun("A", "go", {}, lib, 0.0), SwipeLog(w, st["stick"]), FlatEnv(w), []
    t = 0.0
    while not run.done and t < 900:
        env.t = t
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), env)
        t += 0.5
    assert run.result == "success", logs[-6:]
    assert ex.ms[0] <= mapnav.MINI_MS and max(ex.ms[1:]) > mapnav.MINI_MS, ex.ms     # one short try, then full pushes
    assert sum("靠不住" in x for x in logs) == 1


class Rail(World):
    """A bridge: whatever the push, "me" only moves along the x axis (slides along the rails)."""


class RailExec(Exec):
    def submit(self, device, kind, **kw):
        if kind == "swipe":
            a = math.atan2(kw["y2"] - self.stick["y"], kw["x2"] - self.stick["x"])
            self.w.pos[0] += self.w.speed * kw["ms"] * math.cos(a)
        return super().submit(device, "tap" if kind == "swipe" else kind, **kw)


def test_sliding_along_a_rail_is_not_learnt_as_a_turn():
    """The point is off the rail: it must give up (stuck), not swing back and forth learning a wrong turn."""
    w = Rail(turn=0.0, speed=0.01)
    plan = mapnav.Walk([{"x": 10, "y": 60}], near=8, push_ms=3000, max_moves=40)
    seen = []
    for _ in range(40):
        what = plan.step(w.pos)
        if what[0] != "push":
            break
        w.pos[0] += w.speed * what[2] * math.cos(what[1])
        seen.append(round(w.pos[0]))
    assert what == ("stuck",), (what, seen)
    assert plan.moves <= 10 and abs(plan.turn or 0.0) < mapnav.TURN_OK
