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


def lag(ms):
    """a push moves "me" only after a moment (as on a real screen)"""
    return max(0.0, ms - mapnav.PUSH_LAG)


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
        w.pos[0] += w.speed * lag(ms) * math.cos(a + w.turn)
        w.pos[1] += w.speed * lag(ms) * math.sin(a + w.turn)
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
            self.w.pos[0] += self.w.speed * lag(kw["ms"]) * math.cos(a + self.w.turn)
            self.w.pos[1] += self.w.speed * lag(kw["ms"]) * math.sin(a + self.w.turn)
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
            self.w.pos[0] += self.w.speed * lag(kw["ms"]) * math.cos(a)
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


class Bridges:
    """a left platform, three bridges to the right one: the top one ends in the void, the middle one may have a wall
    on it, the bottom one goes through. Walking stops at the edge (no sliding)."""
    def __init__(self, start, wall=False):
        self.pos, self.wall = list(start), wall

    def ok(self, x, y):
        if self.wall and 150 <= x <= 160 and -60 <= y <= -40:
            return False
        return (-60 <= x <= 40 and -120 <= y <= 0) or (300 <= x <= 400 and -120 <= y <= 0) or \
            (40 <= x <= 250 and -120 <= y <= -100) or (40 <= x <= 300 and -60 <= y <= -40) or (40 <= x <= 300 and -20 <= y <= 0)

    def push(self, a, ms, speed=0.05):
        for _ in range(int(speed * lag(ms))):
            nx, ny = self.pos[0] + math.cos(a), self.pos[1] + math.sin(a)
            if not self.ok(nx, ny):
                break
            self.pos = [nx, ny]


NET = [{"x": 150, "y": -110, "label": "top bridge", "links": [2]}, {"x": 20, "y": -110, "label": "top bridge head", "links": [3]},
       {"x": 0, "y": -60, "label": "left", "links": [4, 6]}, {"x": 60, "y": -50, "label": "middle head", "links": [5]},
       {"x": 290, "y": -50, "label": "middle end", "links": [8]}, {"x": 30, "y": -10, "label": "bottom head", "links": [7]},
       {"x": 290, "y": -10, "label": "bottom end", "links": [8]}, {"x": 350, "y": -50, "label": "goal"}]   # the last: where to go


def walk(plan, w, n=120):
    what = None
    for _ in range(n):
        what = plan.step(w.pos)
        if what[0] != "push":
            break
        w.push(what[1], what[2])
        for a, ms in (what[3] if len(what) > 3 else []):     # a stretch without looking
            w.push(a, ms)
    return what


def test_without_a_network_a_landing_on_the_wrong_bridge_gets_stuck():
    w = Bridges((150, -110))
    assert walk(mapnav.Walk([{"x": 350, "y": -50}], near=8, max_moves=60), w)[0] != "arrived"


def test_a_route_network_goes_back_round_from_the_wrong_bridge():
    w = Bridges((150, -110))
    plan = mapnav.Walk(NET, near=8, max_moves=80)
    assert walk(plan, w) == ("arrived",), (w.pos, plan.notes)
    assert ("route", ["top bridge", "top bridge head", "left", "middle head", "middle end", "goal"]) in plan.notes


def test_a_link_that_is_stuck_is_given_up_for_another_way():
    w = Bridges((0, -60), wall=True)
    plan = mapnav.Walk(NET, near=8, max_moves=120)
    assert walk(plan, w, 200) == ("arrived",), (w.pos, plan.notes)
    assert ("blocked", "middle head", "middle end") in plan.notes
    assert any(nt[0] == "route" and "bottom end" in nt[1] for nt in plan.notes)


def test_the_runner_logs_the_way():
    w = Bridges((150, -110))
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": NET,
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 8, "max_moves": 80}

    class Ex(Exec):
        def submit(self, device, kind, **kw):
            if kind == "swipe":
                w.push(math.atan2(kw["y2"] - 570, kw["x2"] - 192), kw["ms"])
            fu = Future()
            fu.set_result(None)
            return fu

    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st, {"type": "wait", "seconds": 0.01}]}}
    run, logs = SubRun("A", "go", {}, lib, 0.0), []
    run._env = Env(w)
    t = 0.0
    ex = Ex(w, st["stick"])
    while not run.done and t < 3000:
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), Env(w))
        t += 0.5
    assert run.result == "success", logs[-8:]
    assert any(m.startswith("路線:top bridge → top bridge head → left") for m in logs), logs[:6]


def test_any_point_marked_end_counts_as_there():
    net = [dict(p) for p in NET]
    net[1 - 1]["links"] = [2]
    net.insert(1, {"x": 200, "y": -110, "label": "top end", "end": True})      # the top bridge's own end counts too
    for p in net:                                                             # (numbers after it moved by one)
        if "links" in p and p["label"] != "top bridge":
            p["links"] = [j + 1 if j >= 2 else j for j in p["links"]]
    net[0]["links"] = [2, 3]
    w = Bridges((150, -110))
    plan = mapnav.Walk(net, near=8, max_moves=40)
    assert walk(plan, w) == ("arrived",), (w.pos, plan.notes)
    assert plan.notes[0] == ("route", ["top bridge", "top end"])


class FastEnv(Env):
    """frames with the time they were taken (the runtime between ticks)"""
    def __init__(self, world, clock):
        super().__init__(world)
        self.clock = clock

    def latest_frame(self, n):
        return self.clock[0], object()


def test_between_ticks_only_quick_steps_go_on():
    w = World(turn=0.0, speed=0.05)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 60, "y": 0}],
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 8}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [
        {"type": "wait", "seconds": 1}, st, {"type": "tap", "target": {"x": 5, "y": 5}}]}}
    run, ex, clock = SubRun("A", "go", {}, lib, 0.0), Exec(w, st["stick"]), [0.0]
    env = FastEnv(w, clock)
    assert run.quick()                                    # a plain wait: quick
    t = 0.0
    while run.stack[-1].steps[run.stack[-1].i]["type"] != "walk_to" and t < 5:
        t += 0.25
        clock[0] = t
        run.advance({}, t, ex, {}, lambda *a: None, env, between=True)
    assert run.quick() and t <= 1.25                      # the 1 s wait did not need a whole tick
    while run.quick() and t < 200:                      # between ticks: only the walk goes on
        t += 0.25
        clock[0] = t
        run.advance({}, t, ex, {}, lambda *a: None, env, between=True)
    assert ex.log.count("tap") >= 1 and "swipe" in ex.log
    assert math.dist(w.pos, (60, 0)) <= 8


def test_once_learnt_a_stretch_is_walked_without_looking():
    w = Bridges((0, -60))
    plan = mapnav.Walk(NET, near=8, max_moves=40)
    looks = 0
    what = None
    for _ in range(40):
        looks += 1
        what = plan.step(w.pos)
        if what[0] != "push":
            break
        w.push(what[1], what[2])
        for a, ms in (what[3] if len(what) > 3 else []):
            w.push(a, ms)
    assert what == ("arrived",), (w.pos, plan.notes)
    assert looks <= 6, looks                                  # not a look after every push


def test_a_link_may_say_which_way_to_push_on_a_number_pad():
    plan = mapnav.Walk([{"x": 0, "y": 0, "moves": [{"to": 2, "dir": 9, "s": 2}]}, {"x": 100, "y": -100}], near=8)
    plan.turn, plan.speed = 0.3, 0.05                          # (learnt: the set way wins on that link)
    what = plan.step((0, 0))
    assert what[0] == "push" and abs(math.degrees(what[1]) + 45) < 1 and what[2] == 2000
    assert plan.leg_moves["0>1"]["dir"] == 9 and plan.leg_moves["1>0"]["dir"] == 1   # the way back: the opposite


def test_on_a_bridge_it_goes_on_along_it_not_to_a_nearer_point_across_the_void():
    w = Bridges((175, -50))                                    # the middle bridge; "bottom end" is not far, below
    net = [dict(p) for p in NET]
    net[6] = {"x": 175, "y": -10, "label": "bottom mid", "links": [8]}
    plan = mapnav.Walk(net, near=8, max_moves=40)
    assert walk(plan, w) == ("arrived",), (w.pos, plan.notes)
    assert plan.notes[0][1][0] in ("middle end", "middle head"), plan.notes[0]


def test_a_long_link_is_pushed_in_several_pushes():
    plan = mapnav.Walk([{"x": 0, "y": 0}, {"x": 1000, "y": 0}], near=8)
    plan.turn, plan.speed = 0.0, 0.05
    plan.idx = 1
    what = plan.step((0, 0))
    pushes = [what[2]] + [m for _a, m in what[3]]
    assert max(pushes) <= mapnav.SWIPE_MS and sum(pushes) >= 1000 / 0.05


def test_a_set_turn_and_speed_walk_without_looking_from_the_first_point():
    w = World(turn=0.0, speed=0.014)
    plan = mapnav.Walk([{"x": 0, "y": 0}, {"x": 200, "y": -80}, {"x": 400, "y": -160}], near=8, turn=0, speed=14)
    what = plan.step((0, 0))
    assert what[0] == "push" and len(what) == 4                # at the first point: straight on, no learning first
    assert plan.turn == 0.0
