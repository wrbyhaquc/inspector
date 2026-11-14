"""Record human touches from the emulator's kernel input devices (`getevent -lt`) and turn them into gestures.
Taps injected with `adb shell input` go through the Android framework and do NOT show up here."""
import ctypes
import ctypes.wintypes as W
import re
import subprocess
import threading
import time
from i18n import _


_k = ctypes.WinDLL("kernel32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None   # Windows only
if _k:
    _k.CreateJobObjectW.restype = W.HANDLE
    _k.CreateJobObjectW.argtypes = (W.LPVOID, W.LPCWSTR)
    _k.SetInformationJobObject.argtypes = (W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD)
    _k.AssignProcessToJobObject.argtypes = (W.HANDLE, W.HANDLE)
JOB_EXTENDED_LIMITS = 9               # JobObjectExtendedLimitInformation
JOB_SILENT_BREAKAWAY = 0x1000         # what a child starts stays out of the job: adb may start the shared adb server
JOB_KILL_ON_CLOSE = 0x2000
_job = None                           # closed by Windows when this process ends, however it ends
_job_lock = threading.Lock()
LINE = re.compile(r"\[\s*(\d+\.\d+)\]\s+(/dev/input/event\d+):\s+(\S+)\s+(\S+)\s+(\S+)")
TAP_MAX_MOVE = 15      # px
TAP_MAX_TIME = 0.5     # s; longer without moving = long press
PATH_MIN_STEP = 0.05   # s between recorded path points
AXIS = re.compile(r"(ABS_MT_POSITION_[XY]|ABS_[XY])\s*:.*?\bmax (\d+)")
VIEWPORT = re.compile(r"DisplayViewport\{[^}]*valid=true[^}]*orientation=(\d)")


class _JobLimits(ctypes.Structure):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION"""
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD),
                ("IoCounters", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _end_with_parent(proc):
    """A child ends when this process ends, also when it is force-ended: nothing gets to kill the child then, and a
    getevent waiting for the next touch never notices it is alone. Windows only; elsewhere this does nothing."""
    global _job
    if _k is None:
        return
    with _job_lock:
        if _job is None:
            job = _k.CreateJobObjectW(None, None)
            limits = _JobLimits(LimitFlags=JOB_KILL_ON_CLOSE | JOB_SILENT_BREAKAWAY)
            if not job or not _k.SetInformationJobObject(job, JOB_EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            _job = job
    if not _k.AssignProcessToJobObject(_job, int(proc._handle)) and proc.poll() is None:      # (already gone: nothing to end)
        raise ctypes.WinError(ctypes.get_last_error())


def parse_ranges(text):
    """`getevent -lp` -> {device path: (largest x, largest y)} of what reports touches."""
    out, path, axes = {}, None, {}
    for line in text.splitlines():
        if line.startswith("add device"):
            path, axes = line.split(":", 1)[1].strip(), {}
        m = AXIS.search(line)
        if m and path:
            if "MT" in m.group(1) or m.group(1)[-1] not in axes:      # (the multitouch axes when it has both)
                axes[m.group(1)[-1]] = int(m.group(2))
            if len(axes) == 2:
                out[path] = (axes["X"], axes["Y"])
    return out


def parse_rotation(text):
    """`dumpsys display` -> how far the screen is turned now (0..3), or None."""
    m = VIEWPORT.search(text)
    return int(m.group(1)) if m else None


def to_fraction(x, y, rng, rotation):
    """A touch in the device's own range -> where on the screen as shown, as fractions. The range turns with the hardware,
    not with what is shown: an app shown sideways has the two swapped."""
    nx, ny = x / max(1, rng[0]), y / max(1, rng[1])
    return {0: (nx, ny), 1: (ny, 1 - nx), 2: (1 - nx, 1 - ny), 3: (1 - ny, nx)}[rotation]


class _Touch:
    __slots__ = ("t0", "x0", "y0", "x", "y", "path", "last_path_t")

    def __init__(self, t):
        self.t0 = t; self.x0 = self.y0 = self.x = self.y = None
        self.path = []; self.last_path_t = -1


OWN_IDS = range(61000, 65000)   # touch tracking ids of a finger the program holds itself (drivers/android hold)


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
        self.ranges = None
        self.rotation = 0

    def _shell(self, *args):
        return subprocess.run([self.adb, "-s", self.serial, "shell", *args], capture_output=True, timeout=10).stdout.decode("utf-8", "replace")

    def to_screen(self, g):
        """A gesture's two ends as fractions of the screen: (x0, y0, x1, y1), None when this device does not say its range."""
        try:
            if self.ranges is None:
                self.ranges = parse_ranges(self._shell("getevent", "-lp"))
            turned = parse_rotation(self._shell("dumpsys", "display"))
            self.rotation = self.rotation if turned is None else turned
        except Exception:                                 # noqa: BLE001 - the last known way round
            pass
        rng = (self.ranges or {}).get(g["input"])
        if not rng:
            return None
        return (*to_fraction(g["x0"], g["y0"], rng, self.rotation), *to_fraction(g["x1"], g["y1"], rng, self.rotation))

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
                try:
                    _end_with_parent(self.proc)
                except OSError as e:    # touches still arrive; only the clean-up after a force-end is lost
                    print(_("[{name}] 觸控監聽錯誤: {e}", name=self.name, e=e))
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
        kt, path, typ, code, val = float(m.group(1)), m.group(2), m.group(3), m.group(4), m.group(5)
        if not self._own(path, typ, code, val):           # a finger the program itself holds (hold) is no person
            self.last_event = host_now
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

    def _own(self, path, typ, code, val):
        """this event is the program's own held finger (a tracking id from OWN_IDS), or says nothing of a person
        (the slot chosen; a sync / touch key while only its own finger is down)"""
        d = self.dev.setdefault(path, {"slot": 0, "touches": {}, "dirty": set(), "st": None, "st_xy": [None, None]})
        own = d.setdefault("own", set())
        if typ == "EV_ABS" and code == "ABS_MT_SLOT":
            return True
        if typ == "EV_ABS" and code == "ABS_MT_TRACKING_ID" and d is not None:
            v = int(val, 16)
            if v == 0xFFFFFFFF:
                if d["slot"] in own:
                    own.discard(d["slot"])
                    d["touches"].pop(d["slot"], None)      # not a gesture of a person
                    d["own_tail"] = True                   # (its touch key and sync after it too)
                    return True
                d["own_tail"] = False
                return False
            if v in OWN_IDS:
                own.add(d["slot"])
                return True
            own.discard(d["slot"])
            d["own_tail"] = False
            return False
        if typ == "EV_ABS" and d is not None and d["slot"] in own:
            return True
        if typ in ("EV_SYN", "EV_KEY") and d is not None and ((own and set(d["touches"]) <= own)
                                                               or (d.get("own_tail") and not d["touches"])):
            return True
        if d is not None:
            d["own_tail"] = False
        return False

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
