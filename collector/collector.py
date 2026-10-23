"""Orchestrates discovery, per-device screenshot sampling and dataset writing.

What else is recorded beside the screen comes from the project's plugins (registry kind "recorder", e.g. the
readings of a sensor next to a camera): a recorder is made per session with recorder(collector) and may define
  start() / stop()                    begin / end its own capture
  devices_changed(instances)          after every device scan
  snapshot(name, t)                   -> fields stored with every sample and touch of that device at time t
  sample_fields(name)                 -> more fields for every sample
  name_gesture(g)                     -> {"action", "element", ...}: what a touch at that spot means
  live(name)                          -> {"connected", "meters", "info", "summary"} for the web page
  console(name)                       -> text for the console status line
  session_meta()                      -> more fields for session.json
It reports events with collector.on_event(name, ts, kind, detail, burst) (burst = take extra screenshots) and may
ask for a device scan with collector.rescan_now.set()."""
import atomic
import collections
import concurrent.futures
import datetime
import json
import os
import threading
import time

from PIL import Image
import drivers
from .config import Settings
from i18n import _
import project


def _now_str(ts=None):
    return datetime.datetime.fromtimestamp(ts or time.time()).strftime("%H:%M:%S")


def _write_png(path, img, level):
    Image.fromarray(img).save(path, compress_level=level)


class Frame:
    __slots__ = ("t_req", "t_done", "img", "sid", "src")

    def __init__(self, t_req, t_done, img, src=""):
        self.t_req, self.t_done, self.img, self.sid, self.src = t_req, t_done, img, None, src


class DeviceCtx:
    """Everything recorded for one device within a session."""

    def __init__(self, collector, inst):
        self.c, self.inst = collector, inst           # inst: drivers.Device
        self.dir = os.path.join(collector.session_dir, "devices", inst.name)
        os.makedirs(os.path.join(self.dir, "frames"), exist_ok=True)
        self.samples_f = open(os.path.join(self.dir, "samples.jsonl"), "a", encoding="utf-8")
        self.events_f = open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8")
        self.touches_f = open(os.path.join(self.dir, "touches.jsonl"), "a", encoding="utf-8")
        self.lock = threading.RLock()
        self.events_lock = threading.Lock()
        self.triggers = []          # (due_ts, label)
        self.ring = collections.deque()   # recent Frames kept in memory
        self.last_burst = 0.0
        self.n_samples = self.n_events = self.n_fail = self.n_touches = 0
        self.stop = threading.Event()
        self.thread = None
        self.touch = None
        self.cap = None             # the driver's capture of this device
        self.last_src = None        # how the latest shot was taken (from the driver, e.g. "window 1280x720" / "adb")
        self.n_slow = 0             # shots taken the costly way

    # ----- sampling -----
    def start(self):
        drv = self.c.driver
        if self.inst.ok and "screen" in drv.caps and not (self.thread and self.thread.is_alive()):
            if self.cap is None:
                self.cap = drv.capture(self.inst.name, prefer=self.c.s.capture)
            self.stop.clear()
            self.thread = threading.Thread(target=self._loop, name=f"shot-{self.inst.name}", daemon=True)
            self.thread.start()
        if self.c.s.record_touches and self.inst.ok and "touch_watch" in drv.caps \
                and not (self.touch and self.touch.thread.is_alive()):
            self.touch = drv.watch_touch(self.inst.name, self.on_gesture)
            if self.touch:
                self.touch.start()

    def on_gesture(self, g):
        """A finished human gesture: store it with the last full frame captured before the finger went down,
        what the recorders knew at that moment, and a best-guess action name."""
        with self.lock:
            before = [f for f in self.ring if f.t_done <= g["t_down"]]
            pre = before[-1] if before else None
        pre_id = self._save(pre, "pre_touch") if pre else None
        rec = {"session": self.c.session_id, "device": self.inst.name, **g, **self.c.name_gesture(g),
               "pre_frame": f"frames/{pre_id}.png" if pre_id else None,
               "pre_frame_age": round(g["t_down"] - pre.t_done, 3) if pre else None}
        rec.update(self.c.snapshot(self.inst.name, g["t_down"]))
        with self.lock:
            self.touches_f.write(json.dumps(rec, ensure_ascii=False) + "\n"); self.touches_f.flush()
            self.n_touches += 1
        self.c.on_event(self.inst.name, g["t_up"], "touch",
                        {"kind": g["kind"], "action": rec["action"], "x0": g["x0"], "y0": g["y0"],
                         "x1": g["x1"], "y1": g["y1"], "duration": g["duration"]})

    def _active(self, now):
        return bool(self.touch) and now - self.touch.last_touch < self.c.s.active_window

    def schedule_burst(self, ts, kind):
        with self.lock:
            if ts - self.last_burst < self.c.s.event_cooldown:
                return
            self.last_burst = ts
            for off in self.c.s.event_offsets:
                self.triggers.append((ts + off, f"event:{kind}+{off}"))

    def _loop(self):
        """Grab screenshots into the in-memory ring (0.3 s while active, 1 s idle);
        save one as a sample every active_interval / base_interval, or when an event is due."""
        s = self.c.s
        last_grab = last_saved = 0.0
        while not self.stop.is_set():
            now = time.time()
            active = self._active(now)
            with self.lock:
                due = [t for t in self.triggers if t[0] <= now]
                self.triggers = [t for t in self.triggers if t[0] > now]
            forced = due[0][1] if due else None
            slow = bool(self.cap and self.cap.slow)  # costly shots (e.g. inside the emulator): take them less often
            gap = (s.slow_ring_active_interval if active else s.slow_ring_idle_interval) if slow else \
                (s.ring_active_interval if active else s.ring_idle_interval)
            if not forced and now - last_grab < gap:
                self.stop.wait(0.02)
                continue
            last_grab = now
            f = self._grab()
            if f is None:
                continue
            if forced:
                self._save(f, forced)
            elif f.t_req - last_saved >= (s.active_interval if active else s.base_interval):
                self._save(f, "active" if active else "base")
                last_saved = f.t_req

    def _grab(self):
        t_req = time.time()
        try:
            got = self.cap.grab()
        except Exception as e:
            got = None; print(_("[{name}] 截圖失敗: {e}", name=self.inst.name, e=e))
        if got is None:
            self.n_fail += 1
            return None
        img, src, _x = got
        if self.cap.slow:
            if self.last_src is not None and not self.last_src == src:
                print(_("{p1} {name} 改用 {src} 截圖(較耗資源,頻率自動降低)", p1=_now_str(), name=self.inst.name, src=src))
            self.n_slow += 1
        elif self.last_src is not None and src != self.last_src and self.n_slow:
            print(_("{p1} {name} 恢復 {src}", p1=_now_str(), name=self.inst.name, src=src))
        self.last_src = src
        f = Frame(t_req, time.time(), img, src)
        with self.lock:
            self.ring.append(f)
            while self.ring and f.t_done - self.ring[0].t_done > self.c.s.ring_seconds:
                self.ring.popleft()
        return f

    def _save(self, f, trigger):
        """Write a ring frame as a sample (full PNG in the background) and return its id. Idempotent.
        Lock order is always recorder locks -> self.lock, so the snapshot is taken before self.lock."""
        snap = self.c.snapshot(self.inst.name, f.t_req)
        more = self.c.sample_fields(self.inst.name)
        with self.lock:
            if f.sid:
                return f.sid
            f.sid = str(int(f.t_req * 1000))
            self.c.writer.submit(_write_png, os.path.join(self.dir, "frames", f.sid + ".png"),
                                 f.img, self.c.s.png_level)
            rec = {"id": f.sid, "session": self.c.session_id, "device": self.inst.name, "trigger": trigger,
                   "t_req": round(f.t_req, 3), "t_done": round(f.t_done, 3), "frame": f"frames/{f.sid}.png",
                   "capture": f.src, **more}
            rec.update(snap)
            self.samples_f.write(json.dumps(rec, ensure_ascii=False) + "\n"); self.samples_f.flush()
            self.n_samples += 1
            return f.sid

    def event(self, ts, kind, detail):
        line = json.dumps({"t": round(ts, 3), "event": kind, **detail}, ensure_ascii=False) + "\n"
        with self.events_lock:     # written from the recorders' threads and the touch thread
            self.events_f.write(line); self.events_f.flush()
            self.n_events += 1

    def close(self):
        self.stop.set()
        if self.touch:
            self.touch.close()
        if self.thread:
            self.thread.join(timeout=5)
        self.samples_f.close(); self.events_f.close(); self.touches_f.close()


class Collector:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(project.work_of(settings.data_root), "sessions", self.session_id)
        os.makedirs(self.session_dir, exist_ok=True)
        self.devs = {}              # instance name -> DeviceCtx
        self.lock = threading.RLock()
        self.rescan_now = threading.Event()
        self.driver = drivers.current(settings.data_root)
        from project.plugins import registry
        self.recorders = {n: f(self) for n, f in registry(settings.data_root).all("recorder").items()}
        self.writer = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="png")
        self.stopping = threading.Event()
        self.started = time.time()

    # ----- discovery -----
    def rescan(self):
        insts = [i for i in self.driver.list() if not str((i.info or {}).get("kind", "")).startswith("recording/")]   # replays: already recorded
        if self.s.only:
            insts = [i for i in insts if i.name in self.s.only]
        self._ask("devices_changed", insts)
        with self.lock:
            seen = set()
            for inst in insts:
                seen.add(inst.name)
                ctx = self.devs.get(inst.name)
                if ctx is None:
                    ctx = self.devs[inst.name] = DeviceCtx(self, inst)
                    print(_("{p1} 發現 {name}({detail})", p1=_now_str(), name=inst.name, detail=inst.detail))
                    if not inst.ok:
                        print(_("          ⚠ {name} 現在無法取得畫面:{detail}", name=inst.name, detail=inst.detail))
                else:
                    if inst.detail != ctx.inst.detail:
                        print(_("{p1} {name} 變更:{detail} → {detail2}", p1=_now_str(), name=inst.name, detail=ctx.inst.detail, detail2=inst.detail))
                    ctx.inst = inst
                ctx.start()
            for name in list(self.devs):
                if name not in seen and self.devs[name].thread and self.devs[name].thread.is_alive():
                    print(_("{p1} {name} 已關閉,停止截圖", p1=_now_str(), name=name))
                    self.devs[name].stop.set()

    # ----- recorders -----
    def _ask(self, method, *args):
        """{recorder name: result} of every recorder that has this hook (a failing recorder is skipped)."""
        out = {}
        for n, r in self.recorders.items():
            if hasattr(r, method):
                try:
                    out[n] = getattr(r, method)(*args)
                except Exception as e:
                    print(_("{p1} 錄製外掛 {n}.{method} 失敗:{e}", p1=_now_str(), n=n, method=method, e=e))
        return out

    def snapshot(self, name, t):
        out = {}
        for v in self._ask("snapshot", name, t).values():
            out.update(v or {})
        return out

    def sample_fields(self, name):
        out = {}
        for v in self._ask("sample_fields", name).values():
            out.update(v or {})
        return out

    def name_gesture(self, g):
        for v in self._ask("name_gesture", g).values():
            if v:
                return v
        kind = g["kind"]
        if kind == "swipe":
            dx, dy = g["x1"] - g["x0"], g["y1"] - g["y0"]
            action = f"drag_{('right' if dx > 0 else 'left') if abs(dx) >= abs(dy) else ('down' if dy > 0 else 'up')}"
        else:
            action = "hold" if kind == "long_press" else "tap"
        return {"action": action, "element": None}

    def on_event(self, name, ts, kind, detail, burst=True):
        """An event of a device (a touch, or from a recorder): written to events.jsonl; burst = extra screenshots."""
        ctx = self.devs.get(name)
        if not ctx:
            return
        ctx.event(ts, kind, detail)
        if burst:
            ctx.schedule_burst(ts, kind)

    # ----- run -----
    def status(self):
        up = int(time.time() - self.started)
        print(_("\n{p1} ── 已執行 {p2}:{p3}:{p4} ── {session_dir}", p1=_now_str(), p2=up // 3600, p3=format(up % 3600 // 60, '02d'), p4=format(up % 60, '02d'), session_dir=self.session_dir))
        with self.lock:
            for name, c in sorted(self.devs.items()):
                alive = _("截圖中") if c.thread and c.thread.is_alive() else _("未截圖")
                more = "  ".join(v for v in self._ask("console", name).values() if v)
                print(_("  {name} {alive}  {more}  樣本 {n_samples}  事件 {n_events}  觸控 {n_touches}  失敗 {n_fail}  截圖 {p8}", name=format(name, '<18'), alive=alive, more=more, n_samples=format(c.n_samples, '>6'), n_events=format(c.n_events, '>6'), n_touches=format(c.n_touches, '>5'), n_fail=c.n_fail, p8=c.last_src or '-'))

    # ----- control files (used by the web UI; the CLI works the same) -----
    @property
    def status_path(self):
        return os.path.join(project.work_of(self.s.data_root), "collector_status.json")

    @property
    def stop_path(self):
        return os.path.join(project.work_of(self.s.data_root), "collector.stop")

    def live_status(self, running=True):
        now = time.time()
        devs = []
        with self.lock:
            for name, c in sorted(self.devs.items()):
                devs.append({
                    "name": name, "ok": c.inst.ok, "detail": c.inst.detail,
                    "capturing": bool(c.thread and c.thread.is_alive()), "active": c._active(now),
                    "extra": self._ask("live", name),        # recorder name -> {"connected", "meters", "info", "summary"}
                    "samples": c.n_samples, "events": c.n_events, "touches": c.n_touches, "failed_shots": c.n_fail,
                    "capture": c.last_src, "slow": bool(c.cap and c.cap.slow), "slow_shots": c.n_slow,
                })
        return {"running": running, "pid": os.getpid(), "session": self.session_id, "session_dir": self.session_dir,
                "started": self.started, "updated": now, "settings": vars(self.s), "devices": devs,
                "recorders": {n: getattr(r, "label", n) for n, r in self.recorders.items()}}

    def _write_status(self, running=True):
        """Best effort: the status file is only for the web UI and must never stop the recording.
        On Windows the replace fails while the UI happens to be reading the file: atomic retries briefly, then skip."""
        try:
            atomic.write_json(self.status_path, self.live_status(running), ensure_ascii=False, default=str)
        except PermissionError:
            pass
        except OSError as e:
            print(_("{p1} 狀態檔寫入失敗(不影響錄製):{e}", p1=_now_str(), e=e))

    def run(self):
        print(_("資料目錄:{session_dir}", session_dir=self.session_dir))
        if os.path.exists(self.stop_path):
            os.remove(self.stop_path)                 # stale request from a previous run
        self.rescan()
        self._ask("start")
        extra = _("、").join(getattr(r, "label", n) for n, r in self.recorders.items()) or _("無")
        print(_("{p1} 開始錄製(另外記錄:{extra}),按 Ctrl+C 停止\n", p1=_now_str(), extra=extra))
        self._write_session(end=False)
        last_scan = last_status = time.time()
        last_file = 0.0
        try:
            while not self.stopping.is_set():
                now = time.time()
                if self.s.duration and now - self.started >= self.s.duration:
                    break
                if os.path.exists(self.stop_path):
                    print(_("\n{p1} 收到停止要求(介面),正在停止…", p1=_now_str()))
                    os.remove(self.stop_path)
                    break
                if now - last_file >= self.s.status_file_every:
                    self._write_status(); last_file = now
                if self.rescan_now.is_set() or now - last_scan >= self.s.rescan_every:
                    self.rescan_now.clear(); self.rescan(); last_scan = now
                if now - last_status >= self.s.status_every:
                    self.status(); last_status = now
                time.sleep(0.2)
        except KeyboardInterrupt:
            print(_("\n收到 Ctrl+C,正在停止…"))
        finally:
            self._ask("stop")
            for c in self.devs.values():
                c.close()
            self.writer.shutdown(wait=True)          # finish writing queued PNGs
            self.status()
            self._write_session(end=True)
            self._write_status(running=False)
            print(_("\n已停止。資料在 {session_dir}", session_dir=self.session_dir))

    def _write_session(self, end):
        meta = {
            "session": self.session_id, "started": self.started, "ended": time.time() if end else None,
            "settings": {k: v for k, v in vars(self.s).items()},
            "driver": getattr(self.driver, "label", ""),
            "devices": {n: {"detail": c.inst.detail, "samples": c.n_samples,
                            "events": c.n_events, "touches": c.n_touches, "failed_shots": c.n_fail,
                            "capture": c.last_src, "slow_shots": c.n_slow}
                        for n, c in self.devs.items()},
        }
        for v in self._ask("session_meta").values():
            meta.update(v or {})
        try:
            with open(os.path.join(self.session_dir, "session.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
        except OSError as e:                     # never let bookkeeping stop or break the recording
            print(_("{p1} session.json 寫入失敗:{e}", p1=_now_str(), e=e))
