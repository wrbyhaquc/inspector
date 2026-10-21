"""Record human touches from the emulator's kernel input devices (`getevent -lt`) and turn them into gestures.
Taps injected with `adb shell input` go through the Android framework and do NOT show up here."""
import re
import subprocess
import threading
import time
from i18n import _


LINE = re.compile(r"\[\s*(\d+\.\d+)\]\s+(/dev/input/event\d+):\s+(\S+)\s+(\S+)\s+(\S+)")
TAP_MAX_MOVE = 15      # px
TAP_MAX_TIME = 0.5     # s; longer without moving = long press
PATH_MIN_STEP = 0.05   # s between recorded path points


class _Touch:
    __slots__ = ("t0", "x0", "y0", "x", "y", "path", "last_path_t")

    def __init__(self, t):
        self.t0 = t; self.x0 = self.y0 = self.x = self.y = None
        self.path = []; self.last_path_t = -1


class TouchRecorder:
    def __init__(self, serial, on_gesture, name, adb):
        self.serial, self.on_gesture, self.name, self.adb = serial, on_gesture, name, adb
        self.proc = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"touch-{name}", daemon=True)
        self.offset = None            # host time - kernel uptime (minimum seen = least pipe delay)
        self.dev = {}                 # device path -> {"slot": int, "touches": {slot: _Touch}, "dirty": set, "st": _Touch}
        self.last_touch = 0.0
        self.last_event = 0.0         # host time of the latest raw input event (finger down, move, up)
        self.count = 0

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    # ---------- reading ----------
    def _run(self):
        while not self.stop.is_set():
            try:
                # -tt: run getevent on a pseudo-terminal. Without it getevent's output is block-buffered on the
                # emulator side: touches arrive seconds late in batches, and a few taps may never arrive at all.
                self.proc = subprocess.Popen([self.adb, "-s", self.serial, "shell", "-tt", "getevent", "-lt"],
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                for raw in self.proc.stdout:
                    if self.stop.is_set():
                        break
                    self._line(raw.decode("ascii", "replace"), time.time())
            except Exception as e:
                print(_("[{name}] 觸控監聽錯誤: {e}", name=self.name, e=e))
            if not self.stop.is_set():
                self.stop.wait(3)       # adb dropped: retry

    def _line(self, s, host_now):
        m = LINE.search(s)
        if not m:
            return
        self.last_event = host_now
        kt, path, typ, code, val = float(m.group(1)), m.group(2), m.group(3), m.group(4), m.group(5)
        off = host_now - kt
        if self.offset is None or off < self.offset:
            self.offset = off
        t = kt + self.offset
        d = self.dev.setdefault(path, {"slot": 0, "touches": {}, "dirty": set(), "st": None, "st_xy": [None, None]})
        if typ == "EV_ABS":
            v = int(val, 16)
            if code == "ABS_MT_SLOT":
                d["slot"] = v
            elif code == "ABS_MT_TRACKING_ID":
                if v == 0xFFFFFFFF:
                    tch = d["touches"].pop(d["slot"], None)
                    if tch:
                        self._emit(t, path, d["slot"], tch, len(d["touches"]) + 1)
                else:
                    d["touches"][d["slot"]] = _Touch(t)
            elif code == "ABS_MT_POSITION_X":
                tch = d["touches"].get(d["slot"])
                if tch: tch.x = v; d["dirty"].add(d["slot"])
            elif code == "ABS_MT_POSITION_Y":
                tch = d["touches"].get(d["slot"])
                if tch: tch.y = v; d["dirty"].add(d["slot"])
            elif code == "ABS_X":
                d["st_xy"][0] = v
            elif code == "ABS_Y":
                d["st_xy"][1] = v
        elif typ == "EV_KEY" and code == "BTN_TOUCH" and not d["touches"]:
            # single-touch devices without the multitouch protocol
            if val == "DOWN":
                d["st"] = _Touch(t)
            elif val == "UP" and d["st"]:
                st = d["st"]; d["st"] = None
                st.x, st.y = d["st_xy"]
                if st.x0 is None:
                    st.x0, st.y0 = st.x, st.y
                self._emit(t, path, -1, st, 1)
        elif typ == "EV_SYN" and code == "SYN_REPORT":
            for slot in d["dirty"]:
                tch = d["touches"].get(slot)
                if tch and tch.x is not None and tch.y is not None:
                    if tch.x0 is None:
                        tch.x0, tch.y0 = tch.x, tch.y
                    if t - tch.last_path_t >= PATH_MIN_STEP:
                        tch.path.append([round(t - tch.t0, 3), tch.x, tch.y]); tch.last_path_t = t
            d["dirty"].clear()
            if d["st"] and d["st_xy"][0] is not None and d["st"].x0 is None:
                d["st"].x0, d["st"].y0 = d["st_xy"]

    def _emit(self, t_up, path, slot, tch, fingers):
        if tch.x0 is None:
            return
        x1 = tch.x if tch.x is not None else tch.x0
        y1 = tch.y if tch.y is not None else tch.y0
        if not tch.path or tch.path[-1][1:] != [x1, y1]:
            tch.path.append([round(t_up - tch.t0, 3), x1, y1])
        dur = t_up - tch.t0
        if dur < 0.005 and len(tch.path) <= 1:
            return                  # zero-length contact reported by the virtual device, not a real tap
        moved = max(abs(p[1] - tch.x0) + abs(p[2] - tch.y0) for p in tch.path)
        kind = "tap" if moved <= TAP_MAX_MOVE and dur < TAP_MAX_TIME else \
               "long_press" if moved <= TAP_MAX_MOVE else "swipe"
        self.last_touch = t_up
        self.count += 1
        self.on_gesture({
            "t_down": round(tch.t0, 3), "t_up": round(t_up, 3), "duration": round(dur, 3), "kind": kind,
            "x0": tch.x0, "y0": tch.y0, "x1": x1, "y1": y1, "fingers": fingers,
            "path": tch.path[:200], "input": path, "slot": slot,
        })
