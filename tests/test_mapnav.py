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
            a = math.atan2(kw["y2"] - kw["y1"], kw["x2"] - kw["x1"])
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
