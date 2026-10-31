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
INPUTS = {"tap", "long_press", "swipe", "back", "text"}
_sessions, _guard = {}, threading.Lock()
_out = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="wb-teach")


def _to_project(device, x, y):
    """A touch is reported in the device's own pixels."""
    W, H = project.screen(DATA_ROOT)
    try:
        d = next((i for i in drivers.current(DATA_ROOT).list() if i.name == device), None)
        size = d.size if d else None
    except Exception:                                     # noqa: BLE001 - as they are
        size = None
    if size and all(size) and sorted(size) != sorted((W, H)):      # (a turned screen says its size the other way round)
        w, h = sorted(size, reverse=W >= H)
        return round(x * W / w), round(y * H / h)
    return int(x), int(y)


class Session:
    def __init__(self, device):
        self.device, self.started, self.steps = device, time.time(), []
        self.ring = collections.deque(maxlen=RING)
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
                self.ring.append((time.time(), _grab(self.device)))
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
        x, y = _to_project(self.device, g["x0"], g["y0"])
        step = {"op": g["kind"], "x": x, "y": y, "by": "hand"}
        if g["kind"] == "swipe":
            step["x2"], step["y2"] = _to_project(self.device, g["x1"], g["y1"])
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
            step["states"] = {k: v.get("value") for k, v in read_with_draft(img, sees).items() if v.get("source") != "none"}
            if step.get("x") is not None:
                at = spot(img, [step["x"], step["y"], 0, 0], [], find_buttons(img, self.device))
                step["buttons"] = at["buttons"][:3]
        with self.lock:
            self.steps.append(step)
        return step

    def now_states(self):
        got = self.ring[-1][1] if self.ring else None
        if got is None:
            return {}
        return {k: v.get("value") for k, v in read_with_draft(got, _runner_sees(self.device)).items() if v.get("source") != "none"}

    def close(self):
        self.stop_flag.set()
        if self.watcher:
            try:
                self.watcher.close()
            except Exception:                             # noqa: BLE001
                pass


def changes(before, after):
    """Which states changed between two moments: what a step can wait for. Numbers that run on their own (a ratio, a
    number) would change anyway, so only what has named values."""
    import schema as schema_mod
    from .wb_draft import merged_states
    defs = {s["id"]: s for s in merged_states() or schema_mod.load(DATA_ROOT)["states"]}
    out = []
    for k, v in (after or {}).items():
        s = defs.get(k)
        if s and s.get("type") == "class" and v is not None and (before or {}).get(k) not in (v, None):
            name = next((c["name"] for c in s.get("classes") or [] if c["value"] == v), str(v))
            out.append({"state": k, "name": s.get("name"), "value": v, "value_name": name})
    return sorted(out, key=lambda c: c["value"] == "hidden")      # "can be seen no more" says less than something that came


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
    for i, s in enumerate(steps):
        after = steps[i + 1]["states"] if i + 1 < len(steps) and "states" in steps[i + 1] else (sess.now_states() if i == len(steps) - 1 else {})
        s["changes"] = changes(s.get("states"), after)
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

