"""approach (走向畫面上的目標): push the direction control toward a thing seen on the screen until it is near "me"."""
import math
from concurrent.futures import Future

import numpy as np

from automation.runner import SubRun

ME = (640, 330)
STICK = {"x": 190, "y": 570, "r": 60}


class World:
    """the view follows "me": a thing at a place in the world shows at ME + (place - me) on the screen"""
    def __init__(self, thing, speed=0.4, shown=True):
        self.me, self.thing, self.speed, self.shown, self.now = [0.0, 0.0], list(thing), speed, shown, 0.0


class Exec:
    def __init__(self, w):
        self.w, self.log = w, []

    def submit(self, device, kind, **kw):
        self.log.append((kind, kw))
        if kind == "swipe":
            a = math.atan2(kw["y2"] - STICK["y"], kw["x2"] - STICK["x"])
            self.w.me[0] += self.w.speed * kw["ms"] * math.cos(a)
            self.w.me[1] += self.w.speed * kw["ms"] * math.sin(a)
        fu = Future()
        fu.set_result(None)
        return fu


class Env:
    def __init__(self, w):
        self.w = w

    def ctx(self, device):
        return {}

    def latest_frame(self, n):
        return self.w.now, np.zeros((4, 4, 3), np.uint8)

    def resolve_point(self, n, target):
        if not self.w.shown:
            return None
        return [int(ME[0] + self.w.thing[0] - self.w.me[0]), int(ME[1] + self.w.thing[1] - self.w.me[1])]


def run_it(w, **more):
    st = {"type": "approach", "target": {"button": "door"}, "from": {"x": ME[0], "y": ME[1]}, "stick": STICK, "near": 120, **more}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st]}}
    run, logs, ex, env = SubRun("A", "go", {}, lib, 0.0), [], Exec(w), Env(w)
    run._env = env
    while not run.done and w.now < 120:
        run.advance({}, w.now, ex, {}, lambda text, level="": logs.append(text), env)
        w.now += 0.5
    return run, logs, ex


def test_it_walks_up_to_the_thing_and_stops_next_to_it():
    w = World((700, -500))                                # up and to the right, off where "me" stands
    run, logs, ex = run_it(w)
    assert run.result == "success", logs[-5:]
    left = math.hypot(w.thing[0] - w.me[0], w.thing[1] - w.me[1])
    assert left <= 120 and len([e for e in ex.log if e[0] == "swipe"]) >= 2
    kw = ex.log[0][1]                                     # the first push: toward the thing (right and up)
    assert kw["x2"] > STICK["x"] and kw["y2"] < STICK["y"]


def test_already_next_to_it_no_push():
    w = World((60, -80))
    run, logs, ex = run_it(w)
    assert run.result == "success" and ex.log == []


def test_a_thing_not_on_the_screen_fails():
    w = World((700, -500), shown=False)
    run, logs, ex = run_it(w)
    assert run.result != "success" and ex.log == []
    assert any("看不到目標" in x for x in logs), logs[-3:]


def test_it_gives_up_after_the_most_seconds():
    w = World((7000, -5000), speed=0.01)                  # far and slow: never there in time
    run, logs, ex = run_it(w, max_seconds=5)
    assert run.result != "success" and w.now < 30
    assert any("秒內沒有走到" in x for x in logs), logs[-3:]


class Hides(Env):
    """a bar across the screen (y 190~250) hides the thing while it passes behind it"""
    def resolve_point(self, n, target):
        p = super().resolve_point(n, target)
        return None if p and 190 <= p[1] <= 250 else p


def run_hidden():
    w = World((0, -200), speed=0.1)                       # at y 130 on the screen; each push brings it 30~60 px down
    st = {"type": "approach", "target": {"button": "door"}, "from": {"x": ME[0], "y": ME[1]}, "stick": STICK, "near": 60}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st]}}
    run, logs, ex, env = SubRun("A", "go", {}, lib, 0.0), [], Exec(w), Hides(w)
    run._env = env
    while not run.done and w.now < 60:
        run.advance({}, w.now, ex, {}, lambda text, level="": logs.append(text), env)
        w.now += 0.5
    return run, logs


def test_lost_behind_a_bar_it_goes_on_the_way_it_was_last_seen():
    run, logs = run_hidden()
    assert run.result == "success", logs[-5:]
