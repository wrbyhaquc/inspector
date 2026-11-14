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


class TwoSigns(Env):
    """the map follows "me": the first sign shows only while me.x < 150, the second (at (300, 0)) only from 100 on"""
    def map_me(self, n, anchor, me, others=()):
        x, y = self.w.pos
        if anchor.get("button") == "sign" and x < 150:
            return (400, 300), (400 + x, 300 + y)
        if anchor.get("button") == "far" and x >= 100:
            return (700, 300), (700 + x - 300, 300 + y)
        return None


def test_another_sign_is_used_where_the_first_is_off_the_screen():
    w = World(turn=0.0, speed=0.05)
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "anchors": [{"button": "far", "x": 300, "y": 0}],
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 120, "y": 0}, {"x": 280, "y": 10}],
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 8}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st, {"type": "wait", "seconds": 0.01}]}}
    run, logs, ex = SubRun("A", "go", {}, lib, 0.0), [], Exec(w, st["stick"])
    run._env = TwoSigns(w)
    t = 0.0
    while not run.done and t < 600:
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), TwoSigns(w))
        t += 0.5
    assert run.result == "success", logs[-5:]
    assert math.dist(w.pos, (280, 10)) <= 8


class Pocket(World):
    """open ground, but a wall north-east of (60, 0): from below it, pushing up-right goes nowhere"""
    def push(self, a, ms):
        for _ in range(int(self.speed * lag(ms))):
            nx, ny = self.pos[0] + math.cos(a), self.pos[1] + math.sin(a)
            if 50 <= nx <= 70 and -40 <= ny <= -5:
                break
            self.pos = [nx, ny]


def test_stuck_in_a_pocket_off_the_way_it_goes_back_to_the_last_point_first():
    w = Pocket(turn=0.0, speed=0.05, start=(0.0, 0.0))
    plan = mapnav.Walk([{"x": 0, "y": 0}, {"x": 60, "y": -60}, {"x": 120, "y": -60}], near=8, max_moves=60)
    w.pos = [58.0, 2.0]                                        # drifted under the wall on the way to the 2nd point
    plan.idx = 1
    what = None
    for _ in range(60):
        what = plan.step(w.pos)
        if what[0] != "push":
            break
        w.push(what[1], what[2])
        for a, ms in (what[3] if len(what) > 3 else []):
            w.push(a, ms)
    assert ("back", "#1") in plan.notes, plan.notes
    assert what == ("arrived",), (w.pos, plan.notes)


# ---------- a walk map (automation/walkmap.py): find the way on it ----------
def _bridge_map(tmp_path, wall):
    from automation import walkmap
    w = Bridges((0, 0), wall=wall)
    ys, xs = np.mgrid[-140:20, -80:420]
    free = np.vectorize(w.ok)(xs, ys)
    walkmap.save(str(tmp_path), "bridges", free, (-80, -140), "bridges")
    return (str(tmp_path), "bridges")


def test_a_walk_map_plan_keeps_off_the_edges_and_skips_the_dead_end_bridge(tmp_path):
    from automation import walkmap
    root, wid = _bridge_map(tmp_path, wall=True)
    pts = walkmap.plan(walkmap.load(root, wid), (0, -110), (350, -50))
    assert pts and pts[-1] == (350.0, -50.0)
    w = Bridges((0, -110), wall=True)
    for a, b in zip([(0, -110)] + pts, pts):              # every straight stretch is walkable all along
        for k in range(21):
            assert w.ok(a[0] + (b[0] - a[0]) * k / 20, a[1] + (b[1] - a[1]) * k / 20)
    assert all(not (40 < x < 300 and y < -90) for x, y in pts)        # not the top bridge (it ends in the void)
    assert any(-20 <= y <= 0 for x, y in pts if 100 < x < 250)        # the bottom one (a wall on the middle one)


class BlockedBelow(Bridges):
    """a wall on the bottom bridge too - one the map does not show"""
    def ok(self, x, y):
        return super().ok(x, y) and not (150 <= x <= 160 and -20 <= y <= 0)


def test_with_a_walk_map_it_finds_its_way_and_walks_round_what_the_map_does_not_show(tmp_path):
    area = _bridge_map(tmp_path, wall=False)            # the map shows neither wall
    w = BlockedBelow((0, -10))
    plan = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=3000, max_moves=80, turn=0, speed=50, area=area)
    assert walk(plan, w)[0] == "arrived"
    assert plan.marks                                     # stuck at the wall: marked, the way planned again round it
    assert w.pos[0] > 300


def test_spots_found_blocked_are_kept_and_the_next_walk_goes_round_them(tmp_path):
    from automation import walkmap
    area = _bridge_map(tmp_path, wall=False)
    first = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=3000, max_moves=80, turn=0, speed=50, area=area)
    assert walk(first, BlockedBelow((0, -10)))[0] == "arrived" and first.marks
    assert walkmap.add_marks(*area, first.marks) == len(first.marks)
    assert walkmap.add_marks(*area, first.marks) == 0                 # not kept twice
    again = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=3000, max_moves=80, turn=0, speed=50, area=area)
    assert walk(again, BlockedBelow((0, -10)))[0] == "arrived" and not again.marks   # round it at once


def test_a_walk_map_push_is_short_enough_to_look_again_on_the_way(tmp_path):
    area = _bridge_map(tmp_path, wall=False)
    plan = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=8000, max_moves=80, turn=0, speed=20, area=area)
    what = plan.step((0, -10))
    assert what[0] == "push" and what[2] <= mapnav.AREA_PUSH_MS and len(what) == 3


def test_me_may_have_another_colour_at_times():
    f = np.zeros((100, 100, 3), np.uint8)
    f[40:50, 40:50] = (76, 105, 199)                  # "me" drawn blue (the map at night)
    assert mapnav.find_me(f, [0, 0, 100, 100], [210, 84, 50], 30, 6) is None
    assert mapnav.find_me(f, [0, 0, 100, 100], [210, 84, 50], 30, 6, (), [[76, 105, 199]]) in ([44, 44], [45, 45])


def test_me_standing_on_a_sign_of_its_colour_still_shows():
    pic = np.zeros((20, 20, 3), np.uint8)
    pic[5:15, 5:15] = (210, 84, 50)                   # the sign: the colour of "me"
    f = np.zeros((100, 100, 3), np.uint8)
    f[40:60, 40:60] = pic
    f[36:46, 52:60] = (212, 86, 52)                   # "me" on its corner
    own = mapnav.sign_pixels(f, pic, (40, 40))
    assert mapnav.find_me(f, [0, 0, 100, 100], [210, 84, 50], 30, 6, [[34, 34, 32, 32]]) is None
    got = mapnav.find_me(f, [0, 0, 100, 100], [210, 84, 50], 30, 6, (), (), [own])
    assert got and 50 <= got[0] <= 60 and 35 <= got[1] <= 46


def _go(plan, w, n=60):
    looks, one_go = 0, False
    for _ in range(n):
        what = plan.step(w.pos)
        looks += 1
        if what[0] != "push":
            return what, looks, one_go
        one_go = one_go or plan.sure()
        w.push(what[1], what[2])
        for a, ms in (what[3] if len(what) > 3 else []):
            w.push(a, ms)
    return what, looks, one_go


def test_a_way_walked_through_before_is_walked_in_one_go_next_time(tmp_path):
    from automation import walkmap
    area = _bridge_map(tmp_path, wall=False)
    first = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=8000, max_moves=80, turn=0, speed=50, area=area)
    what, looks1, one_go = _go(first, Bridges((-50, -110)))
    assert what[0] == "arrived" and not one_go          # a new way: a look after every stretch
    walkmap.add_walk(*area, first.track, first.speed * 1000)
    again = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=8000, max_moves=80, turn=0, speed=50, area=area)
    what, looks2, one_go = _go(again, Bridges((-45, -105)))
    assert what[0] == "arrived" and one_go and looks2 < looks1 and looks2 <= 5


def test_someone_in_a_way_walked_through_is_walked_round(tmp_path):
    from automation import walkmap
    area = _bridge_map(tmp_path, wall=False)
    first = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=8000, max_moves=80, turn=0, speed=50, area=area)
    assert _go(first, Bridges((0, -10)))[0][0] == "arrived"
    walkmap.add_walk(*area, first.track, first.speed * 1000)
    again = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=8000, max_moves=80, turn=0, speed=50, area=area)
    what, _l, one_go = _go(again, BlockedBelow((0, -10)))    # now something stands on the bottom bridge
    assert one_go and what[0] == "arrived" and again.marks


def test_stuck_three_times_it_gives_up(tmp_path):
    from automation import walkmap
    root, wid = _bridge_map(tmp_path, wall=False)

    class Nowhere(Bridges):                               # walls the map does not show, on every bridge
        def ok(self, x, y):
            return super().ok(x, y) and not (150 <= x <= 160)
    plan = mapnav.Walk([{"x": 350, "y": -50}], near=6, push_ms=3000, max_moves=200, turn=0, speed=50, area=(root, wid))
    assert walk(plan, Nowhere((0, -10)), 200)[0] in ("stuck", "no_way")
    assert len(plan.marks) <= mapnav.AREA_REPLANS + 1


def test_a_walk_map_with_several_ends_goes_to_the_nearest(tmp_path):
    area = _bridge_map(tmp_path, wall=False)
    plan = mapnav.Walk([{"x": 350, "y": -110, "end": True}, {"x": 350, "y": -10}], near=6, push_ms=3000, max_moves=80,
                       turn=0, speed=50, area=area)
    w = Bridges((0, -10))
    assert walk(plan, w)[0] == "arrived" and math.dist(w.pos, (350, -10)) <= 6      # the bottom one: nearer


def test_the_view_scrolling_tells_moving_from_standing():
    rng = np.random.default_rng(1)
    world = (rng.random((900, 1500, 3)) * 255).astype(np.uint8)
    a = world[100:820, 100:1380]
    b = world[100:820, 112:1392]                           # the view followed "me" 12 px to the right
    assert mapnav.moving(a, b) >= 8
    assert mapnav.moving(a, a.copy()) < mapnav.STILL_PX


class Slow:
    """a Future that is done only after a few looks (an adb swipe takes as long as it pushes)"""
    def __init__(self, n):
        self.n = n

    def done(self):
        self.n -= 1
        return self.n < 0

    def result(self):
        return None


class AreaExec:
    """pushes the control on a Bridges world: the push takes a few looks to finish"""
    def __init__(self, world, stick):
        self.w, self.stick, self.log = world, stick, []

    def submit(self, device, kind, **kw):
        self.log.append(kind)
        if kind == "swipe":
            a = math.atan2(kw["y2"] - self.stick["y"], kw["x2"] - self.stick["x"])
            self.w.push(a, kw["ms"])
            return Slow(4)
        fu = Future()
        fu.set_result(None)
        return fu


class AreaEnv:
    """the map read at once; the game's view: a picture that scrolls with "me" (stands still when "me" does)"""
    def __init__(self, world, root):
        self.w, self.data_root, self.t = world, root, 0.0
        self.view = (np.random.default_rng(3).random((1400, 2200, 3)) * 255).astype(np.uint8)

    def ctx(self, device):
        return {}

    def map_me(self, n, anchor, me, others=()):
        return (400, 300), (400 + self.w.pos[0], 300 + self.w.pos[1])

    def latest_frame(self, n):
        self.t += 0.25
        x, y = int(300 + 2 * self.w.pos[0]), int(400 + 2 * self.w.pos[1])
        return self.t, self.view[y:y + 720, x:x + 1280]


def test_the_runner_walks_a_walk_map_and_sees_being_stopped_on_the_screen(tmp_path):
    root, wid = _bridge_map(tmp_path, wall=False)
    w = BlockedBelow((0, -10))                            # a wall on the bottom bridge the map does not show
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 350, "y": -50, "near": 8}],
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 6, "turn": 0, "speed": 50, "area": wid, "max_moves": 80}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st, {"type": "wait", "seconds": 0.01}]}}
    run, logs, ex = SubRun("A", "go", {}, lib, 0.0), [], AreaExec(w, st["stick"])
    env = AreaEnv(w, root)
    run._env = env
    t = 0.0
    while not run.done and t < 900:
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), env)
        t += 0.25
    assert run.result == "success", logs[-8:]
    assert math.dist(w.pos, (350, -50)) <= 8


class HoldExec(AreaExec):
    """the control can also be held (and turned without letting go): "me" walks while it is held"""
    def __init__(self, world, stick):
        super().__init__(world, stick)
        self.angle = None

    def submit(self, device, kind, **kw):
        if kind == "hold":
            self.log.append("hold:" + kw["action"])
            if kw["action"] == "up":
                self.angle = None
            elif kw["action"] == "move":
                self.angle = math.atan2(kw["y"] - self.stick["y"], kw["x"] - self.stick["x"])
            fu = Future()
            fu.set_result(True)
            return fu
        return super().submit(device, kind, **kw)


class HoldEnv(AreaEnv):
    def __init__(self, world, root, ex):
        super().__init__(world, root)
        self.ex, self.looks = ex, 0

    def map_me(self, n, anchor, me, others=()):
        self.looks += 1
        return super().map_me(n, anchor, me, others)

    def latest_frame(self, n):
        if self.ex.angle is not None:                    # held: 0.25 s of walking
            self.w.push(self.ex.angle, 250 + mapnav.PUSH_LAG)
        return super().latest_frame(n)


def test_holding_the_control_it_steers_by_the_view_and_looks_seldom(tmp_path):
    from automation import walkmap
    root, wid = _bridge_map(tmp_path, wall=False)
    walkmap.set_view(root, wid, [0.5, 0.5])               # the view goes 2 px for a map px (learnt before)
    w = Bridges((-50, -110))
    st = {"type": "walk_to", "open": {"x": 1160, "y": 200}, "close": {"x": 1236, "y": 44}, "anchor": {"button": "sign"},
          "me": {"color": [210, 84, 50], "box": [300, 120, 900, 500]}, "points": [{"x": 350, "y": -50, "near": 10}],
          "stick": {"x": 192, "y": 570, "r": 60}, "near": 6, "turn": 0, "speed": 50, "area": wid, "max_moves": 80}
    lib = {"go": {"id": "go", "name": "GO", "params": [], "steps": [st, {"type": "wait", "seconds": 0.01}]}}
    run, logs, ex = SubRun("A", "go", {}, lib, 0.0), [], None
    ex = HoldExec(w, st["stick"])
    env = HoldEnv(w, root, ex)
    run._env = env
    t = 0.0
    while not run.done and t < 900:
        run.advance({}, t, ex, {}, lambda text, level="": logs.append(text), env)
        t += 0.25
    assert run.result == "success", logs[-8:]
    assert math.dist(w.pos, (350, -50)) <= 10
    assert "hold:down" in ex.log and ex.log.count("swipe") == 0 and env.looks <= 8, (env.looks, logs[-6:])
