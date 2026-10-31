"""Teach it once (教一次): do the job on the device and it becomes the steps of a sub-script.

A session is one device: its scripts are paused (暫停) when one starts and stay so until a person presses 繼續. What is done
is written down as it happens - pressed on the workbench's picture (it really goes to the device) or done on the device
itself (the driver's touch watcher, where there is one). For each step: the picture just before it; the existing button
at that spot, if any; afterwards, which states changed by the next step (so the step can wait for the screen, not for a
number of seconds). The steps stay in memory until the page saves them into the draft."""
import collections
import concurrent.futures
import os
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import drivers
import project
from automation import subs as subs_mod
from i18n import _

from . import DATA_ROOT
from .wb_draft import read_with_draft, spot
from .workbench import _grab, _runner_sees, find_buttons, freeze

router = APIRouter()
RING = 6                        # recent pictures kept while teaching (a person's touch is known only once it ended)
RING_S = 0.7
SETTLE = 2.0                    # seconds after a step in which the screen is still answering it
INPUTS = {"tap", "long_press", "swipe", "back", "text"}
_sessions, _guard = {}, threading.Lock()
_out = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="wb-teach")


class Session:
    def __init__(self, device):
        self.device, self.started, self.steps = device, time.time(), []
        self.ring = collections.deque(maxlen=RING)
        self.samples = collections.deque(maxlen=600)      # (time, states) of every picture: what moves with nobody touching
        self.touched = collections.deque(maxlen=600)      # also a touch that became no step (too short, two fingers)
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.watcher = None
        self.paused_here = False
        self.error = None
        threading.Thread(target=self._watch_screen, name=f"wb-ring-{device}", daemon=True).start()
        try:
            self.watcher = drivers.current(DATA_ROOT).watch_touch(device, self.on_gesture)
            if self.watcher:
                self.watcher.start()
        except Exception:                                 # noqa: BLE001 - pressing on the picture still works
            self.watcher = None

    def _watch_screen(self):
        while not self.stop_flag.is_set():
            try:
                t, img = time.time(), _grab(self.device)
                self.ring.append((t, img))
                self.samples.append((t, self._read(img)))
                ev = getattr(self.watcher, "last_event", 0)
                if ev and (not self.touched or self.touched[-1] != ev):
                    self.touched.append(ev)
            except Exception:                             # noqa: BLE001 - the window can come back
                pass
            self.stop_flag.wait(RING_S)

    def before(self, t):
        """The newest picture taken before this time."""
        got = [f for f in list(self.ring) if f[0] <= t]
        return got[-1][1] if got else (self.ring[0][1] if self.ring else None)

    def on_gesture(self, g):
        """A person's touch on the device itself."""
        if g.get("fingers", 1) != 1:
            return
        W, H = project.screen(DATA_ROOT)
        got = self.watcher.to_screen(g)
        x, y, x2, y2 = (g["x0"], g["y0"], g["x1"], g["y1"]) if got is None else \
            (round(got[0] * (W - 1)), round(got[1] * (H - 1)), round(got[2] * (W - 1)), round(got[3] * (H - 1)))
        step = {"op": g["kind"], "x": x, "y": y, "by": "hand"}
        if g["kind"] == "swipe":
            step["x2"], step["y2"] = x2, y2
        if g["kind"] in ("swipe", "long_press"):
            step["ms"] = max(100, round(g["duration"] * 1000))
        self.note(step, g["t_down"])

    def note(self, step, t, img=None):
        """One step, with the picture before it: what is at that spot, what the states read."""
        img = self.before(t) if img is None else img
        step.update(t=t, id=f"s{int(t * 1000)}")
        if img is not None:
            sees = _runner_sees(self.device)
            kept = freeze(self.device, img)
            step["frame"] = kept["id"]
            step["states"] = self._read(img, sees)
            if step.get("x") is not None:
                at = spot(img, [step["x"], step["y"], 0, 0], [], find_buttons(img, self.device))
                step["buttons"] = at["buttons"][:3]
        with self.lock:
            self.steps.append(step)
        return step

    def _read(self, img, sees=None):
        sees = _runner_sees(self.device) if sees is None else sees
        return {k: v.get("value") for k, v in read_with_draft(img, sees).items() if v.get("source") != "none"}

    def now_states(self):
        return self.samples[-1][1] if self.samples else {}

    def close(self):
        self.stop_flag.set()
        if self.watcher:
            try:
                self.watcher.close()
            except Exception:                             # noqa: BLE001
                pass


def on_its_own(samples, times):
    """States that go back and forth with nobody touching anything: they say nothing about what a step did. One change is
    not enough for that - a slow screen can come to what a step asked for long after it."""
    flips, last, out = collections.Counter(), None, set()
    for t, states in samples:
        if any(m <= t < m + SETTLE for m in times):
            flips.clear()
            last = None
            continue
        for k, v in states.items() if last else ():
            if v is not None and last.get(k) not in (v, None):
                flips[k] += 1
                if flips[k] >= 2:
                    out.add(k)
        last = states
    return out


def _away(state, at):
    """How far a touch is from where this state looks (0 = on it)."""
    if not at:
        return 0
    far = [max(r["box"][0] - at[0], at[0] - r["box"][0] - r["box"][2], r["box"][1] - at[1], at[1] - r["box"][1] - r["box"][3], 0)
           for r in state.get("rois") or [] if r.get("box")]
    return min(far, default=0)


def changes(before, after, at=None, own=()):
    """Which states changed between two moments: what a step can wait for, the likeliest first. Numbers that run on their
    own (a ratio, a number) would change anyway, so only what has named values."""
    import schema as schema_mod
    from .wb_draft import merged_states
    defs = {s["id"]: s for s in merged_states() or schema_mod.load(DATA_ROOT)["states"]}
    out = []
    for k, v in (after or {}).items():
        s = defs.get(k)
        was = (before or {}).get(k)
        if s and s.get("type") == "class" and v is not None and was not in (v, None):
            name = next((c["name"] for c in s.get("classes") or [] if c["value"] == v), str(v))
            # "can be seen no more" says least, "can be seen again" often only follows what really happened
            sure = 2 if v == "hidden" else 1 if was == "hidden" else 0
            out.append(((k in own, sure, _away(s, at)), {"state": k, "name": s.get("name"), "value": v, "value_name": name, "own": k in own}))
    return [c for _key, c in sorted(out, key=lambda x: x[0])]


def known_subs(steps):
    """A run of taps that is what an existing sub-script already does: [{"sub", "name", "from", "to"}] (by the steps' indexes)."""
    pressed = [{b["id"] for b in s.get("buttons") or []} if s.get("op") == "tap" else set() for s in steps]
    out = []
    for sid, sub in subs_mod.load_all(DATA_ROOT).items():
        taps = [st for st in sub.get("steps") or [] if st.get("type") == "tap"]
        want = [(st.get("target") or {}).get("button") for st in taps]
        if not want or not all(want) or sub.get("params"):
            continue
        for i in range(len(pressed) - len(want) + 1):
            if all(b in pressed[i + k] for k, b in enumerate(want)):
                out.append({"sub": sid, "name": sub.get("name"), "from": i, "to": i + len(want) - 1})
                break
    return out


def view(sess):
    with sess.lock:
        steps = [dict(s) for s in sess.steps]
    own = on_its_own(list(sess.samples), [s["t"] for s in steps] + list(sess.touched))
    for i, s in enumerate(steps):
        after = steps[i + 1]["states"] if i + 1 < len(steps) and "states" in steps[i + 1] else (sess.now_states() if i == len(steps) - 1 else {})
        s["changes"] = changes(s.get("states"), after, (s["x"], s["y"]) if s.get("x") is not None else None, own)
        s["gap"] = round(steps[i + 1]["t"] - s["t"], 1) if i + 1 < len(steps) else None
    caps = drivers.current(DATA_ROOT).caps_of(sess.device)
    return {"active": True, "device": sess.device, "started": sess.started, "steps": steps, "known": known_subs(steps),
            "paused_here": sess.paused_here, "watching": bool(sess.watcher), "caps": sorted(c for c in caps if c in INPUTS or c == "tap"),
            "sees": _runner_sees(sess.device)}


class Device(BaseModel):
    device: str


class Press(BaseModel):
    device: str
    op: str                     # tap | long_press | swipe | back | text
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    ms: int | None = None
    text: str | None = None


class Forget(BaseModel):
    device: str
    id: str


def _session(device):
    s = _sessions.get(os.path.basename(device))
    if not s:
        raise HTTPException(400, _("還沒有開始教"))
    return s


def _pause(device):
    """Its scripts stop where they are while a person shows the way; a person presses 繼續 afterwards. -> did we pause it"""
    from .app import Act, _act_send
    sees = _runner_sees(device)
    if not sees.get("here") or sees.get("hold") or sees.get("hold_all"):
        return False
    _act_send(Act(device=device, kind="pause", mode="pause"), _("工作台"))
    return True


def _held(sess):
    """Is it safe to press: nothing else may be acting on this device (the runner off counts as safe)."""
    sees = _runner_sees(sess.device)
    if not sees.get("here"):
        return True
    return bool(sees.get("hold") or sees.get("hold_all"))


@router.get("/api/wb/teach/{device}")
def teach_view(device: str):
    s = _sessions.get(os.path.basename(device))
    if not s:
        return {"active": False, "device": os.path.basename(device), "steps": [], "known": []}
    return view(s)


@router.post("/api/wb/teach/start")
def teach_start(req: Device):
    device = os.path.basename(req.device)
    caps = drivers.current(DATA_ROOT).caps_of(device)
    if not caps & {"tap", "swipe", "back", "text"}:
        raise HTTPException(400, _("這個來源只能看,不能操作,沒辦法教它做事"))
    _grab(device)                                         # the picture works before anything changes
    with _guard:
        if device not in _sessions:
            paused = _pause(device)
            _sessions[device] = Session(device)
            _sessions[device].paused_here = paused
    return view(_sessions[device])


@router.post("/api/wb/teach/press")
def teach_press(req: Press):
    """Do one thing on the device from the workbench, and write it down."""
    s = _session(req.device)
    if req.op not in INPUTS:
        raise HTTPException(400, _("不支援的操作"))
    if not _held(s):
        raise HTTPException(400, _("這台的腳本又開始跑了,先按「暫停」再繼續教,才不會互相打架"))
    W, H = project.screen(DATA_ROOT)
    pts = [(req.x, req.y)] + ([(req.x2, req.y2)] if req.op == "swipe" else [])
    if req.op in ("tap", "long_press", "swipe") and not all(a is not None and b is not None and 0 <= a < W and 0 <= b < H for a, b in pts):
        raise HTTPException(400, _("位置不在畫面裡"))
    p = {"tap": {"x": req.x, "y": req.y},
         "long_press": {"x": req.x, "y": req.y, "ms": req.ms or 800},
         "swipe": {"x1": req.x, "y1": req.y, "x2": req.x2, "y2": req.y2, "ms": req.ms or 400},
         "back": {}, "text": {"text": req.text or ""}}[req.op]
    t = time.time()
    img = s.ring[-1][1] if s.ring else _grab(s.device)
    try:
        _out.submit(drivers.current(DATA_ROOT).input, s.device, req.op, **p).result(timeout=20)
    except Exception as e:                                # noqa: BLE001 - any driver: said on the page
        raise HTTPException(400, _("沒有做成:{e}", e=e)) from None
    step = {"op": req.op, "by": "page", **{k: v for k, v in req.model_dump().items() if k in ("x", "y", "x2", "y2", "ms", "text") and v is not None}}
    s.note(step, t, img)
    return view(s)


@router.post("/api/wb/teach/forget")
def teach_forget(req: Forget):
    """A step that was a mistake."""
    s = _session(req.device)
    with s.lock:
        s.steps[:] = [x for x in s.steps if x["id"] != req.id]
    return view(s)


@router.post("/api/wb/teach/stop")
def teach_stop(req: Device):
    """Stop writing down (the device stays paused: a person presses 繼續). The steps stay on the page until saved."""
    device = os.path.basename(req.device)
    with _guard:
        s = _sessions.pop(device, None)
    if not s:
        return {"active": False, "device": device, "steps": [], "known": []}
    out = view(s)
    s.close()
    return {**out, "active": False}

