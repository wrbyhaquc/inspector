"""Shadow mode: watch every emulator with the trained model and log what the script *would* do. Never clicks.

Every `interval` seconds:
  each source's capture (e.g. an emulator's window copied: no load on it)
  -> one batched model call on the GPU
  -> smoothing over the last few ticks (a single odd frame does not flip the state)
  -> every enabled script (designed on the web page, automation/) decides for every device where it is not "off"
  -> a decision counts once it is the same on 2 ticks in a row
Scripts and state definitions are reloaded as soon as they are saved.

停下來 / 暫停 (one device, a tag or all; a rule's "stop" is a 停下來 too): while held, a device's scripts are not
evaluated at all - no situation switches, no timers, no entry actions (only a rule that stopped it is read, to tell
whether its cause is still there). 繼續 after 停下來 starts them over (situations back to their start, conditions counted
from then, the start check again); 繼續 after 暫停 carries on in the same situation and step (the paused time does not
count toward a time limit).

Live execution (the device's mode for a script is "live") only happens when ALL of these hold:
  the device is not stopped or paused (停下來 / 暫停: one device, a tag or all - device_hold.json; kept across
  restarts), its start check is over (START_WAIT: a picture and a healthy source for a few seconds after the runner
  starts or the source comes back), the decision is stable, the rule's cooldown has passed, the device is under its
  taps-per-minute limit, and the rule is not paused.
  停下來 cancels what the device is doing (cleanup steps first) and nothing acts until 繼續 - the guard rules neither
  (they still judge, and say what they would have done); 暫停 holds a running sub-script where it is, 繼續 carries on
  from the same step. Either way the device is still watched and every decision is recorded. A rule that fires more than max_strikes times in a row while its condition never
  goes away (e.g. a switch pressed but it never turns on) is paused and an alert is raised instead of tapping forever.
Control of a device: a rule's "call" starts a sub-script (automation/runner.py), which then has control of that
device until it ends; meanwhile the other rules are still evaluated every tick but do not act. Main scripts have
one priority order: a stable decision of a higher-priority script - or any "urgent" rule - interrupts the running
sub-script (its cleanup steps run first, then the new action on a following tick). Different devices never wait
for each other: a sub-script only leaves a bookmark between ticks, and every device has its own command lane.

Situations: each main script keeps, per device, the situation (情境) it is in; only that situation's rules are
checked. "goto" switches (in trial mode too: switching sends no input), a situation's entry action runs once on
entering (like a rule's action: control, limits, 停下來 / 暫停), "max_seconds" sends a device that stayed too
long to "on_timeout", and a sub-script's success / failure can switch the situation that called it. A script that
switches more than MAX_SWITCHES_PER_HOUR times in an hour on one device is stopped (a loop in the design); only
switches while it can really act count (live, not stopped / paused) - in a trial an entry action never runs, so a
situation that waits for it times out and comes back again and again by design.
The guard rules ("guards", always first): "stop" stops the device - the same 停下來 as from the page, with the rule
and why kept, until 繼續 (a script's own "stop" too) -, "hold" keeps every other script from acting while it holds and
interrupts a running sub-script.

Time and memory: every device's recent state values are kept (HISTORY_SECONDS) for the conditions "became",
"count" and "change"; variables (counters, "last time") live in vars.json in the runtime dir, so a restart keeps
them; "daily" ones go back to their initial value at midnight. The page can change them (var_requests/).

Manual operation: every device's touch screen is watched (getevent, like the collector). For manual_pause_s seconds after
a real touch the device is paused (暫停) on its own: its scripts and situations do not move and the time does not count
toward a situation's limit; then it carries on where it was (like 繼續 after 暫停). Pressing 繼續 on a stopped / paused
device ends that wait at once (the person is done); a touch after it starts a new one. A running schedule waits and carries
on from the same step; a running sub-script of a rule is cancelled (no cleanup: the person has the device and changed
the screen) - the rules decide again afterwards and call it again if it is still needed. Taps sent by the script go through the source's hand (e.g. on Android `adb shell input`) and do not
show up there, so the script never pauses itself.

Learning from use: when the model is unsure about a state (confidence < CONF_LOW) or disagrees with that state's
screen rule, the frame is saved (rate-limited) as a question for the "回答問題" page (uncertain.jsonl). Answered,
most of them become training data and some test questions - instead of recording all day.

Files under <data_root>/shadow/:
  status.json          live state for the web page (per device: state, confidences, decision)
  live/<device>.jpg    the latest frame of each device (small)
  log/<date>.jsonl     every change of a device's decision
  flags.jsonl          frames the user marked as "judged wrong" (saved in full as a session shadow_<date>,
                       so they can be answered and join the test set)
  uncertain.jsonl      frames saved automatically because the model was unsure (same kind of session)
Runtime dir: vars.json (variables), var_requests/ (the page asks to change a variable)
  flag_requests/       the web server drops a file here to ask for the current frame of a device
  stop                 the web server creates this to stop the loop"""
import collections
import datetime
import glob
import json
import os
import re
import threading
import time

import numpy as np
from PIL import Image

import automation
import schema as schema_mod
from automation import engine
from automation.executor import Executor
from automation import buttons as buttons_mod, conds, lists as lists_mod, schedules, subs as subs_mod
from automation.runner import SubRun
from automation import outputs as outputs_mod, values
import drivers
from labeler import generic, rules as auto_rules

from . import arbiter

from . import incidents as incidents_mod, judge, quality as quality_mod
from .joblog import JobLog
from project import word
from i18n import _
import project

SMOOTH = 3            # ticks averaged per decision
STABLE = 2            # identical decisions in a row before a decision counts
CONTROL_DEFAULT = {"max_per_min": 12, "max_strikes": 3, "unblock": 0,
                   "manual_pause_s": 60,        # after a real touch, don't act on that device for this long (0 = off)
                   "auto_save": True,           # save frames the model is unsure about as questions
                   "auto_save_per_hour": 20,    # ... at most this many per hour (all devices)
                   "live_view": True,
                   "start_wait_s": 5,           # after starting / a source coming back: this long with a picture before acting
                   "freeze_seconds": 300}       # a source whose picture does not change this long is "frozen" (0 = never)
LIVE_VIEW_IDLE = 15      # seconds without a page asking for a live frame = nobody is watching, stop writing them
CONF_LOW = 0.6           # model confidence below this = unsure
SAVE_GAP = 60            # seconds between two saved frames of one device
GONE_GRACE = 30          # a source in use missing from the scans this long is gone (one empty scan is not)
STUCK_WAIT = 300         # a live main script waiting / unsure this long counts as stuck: its screen is kept
SAVE_STATE_PER_HOUR = 6  # saved frames per device and state per hour
STATE_SHARE = 0.5        # one state may take at most this share of the hourly save budget (all devices together)
MAX_SWITCHES_PER_HOUR = 30   # situation switches of one script on one device; more = a loop, the script stops


def _write_json(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, default=str)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:          # the web page is reading it right now
                time.sleep(0.05 * (attempt + 1))
    except OSError:
        pass


class Predictor:
    """The trained multi-head model: RGB frames (the coordinate space) -> {state id: {"value", "conf"}} per frame.

    model.onnx runs on onnxruntime (DirectML = any GPU on Windows, else the CPU) and needs no PyTorch; a run that only
    has model_best.pt runs on PyTorch (CUDA, half precision). Both give the same answers (trainer/onnx_export.py)."""

    def __init__(self, path, device=None):
        if path.endswith(".onnx"):
            import onnxruntime as ort
            meta = json.load(open(os.path.join(os.path.dirname(path), "model.json"), encoding="utf-8"))
            self.heads, self.size = meta["heads"], tuple(meta["size"])
            want = ["DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
            try:
                self.sess = ort.InferenceSession(path, providers=[p for p in want if p in ort.get_available_providers()])
                x = np.zeros((1, 3, self.size[1], self.size[0]), np.float32)
                self.sess.run(None, {"frames": x})               # a GPU that cannot really run it fails here
            except Exception as e:                               # e.g. no DirectX 12 GPU, remote desktop: use the CPU
                print(_("顯示卡加速無法使用,改用 CPU:{e}", e=e), flush=True)
                self.sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
            self.backend = "ONNX " + self.sess.get_providers()[0].replace("ExecutionProvider", "")
            self._run = lambda x: self.sess.run(None, {"frames": x.astype(np.float32)})
        else:
            import torch
            from trainer.model import load
            dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
            torch.backends.cudnn.benchmark = True
            model, ck = load(path, dev)
            self.heads, self.size = ck["heads"], tuple(ck["size"])
            self.backend = f"PyTorch {dev}"

            def run(x):
                with torch.no_grad(), torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                    out = model(torch.from_numpy(x).to(dev).float())
                return [out[h["id"]].float().cpu().numpy() for h in self.heads]
            self._run = run

    def __call__(self, frames):
        x = np.stack([np.asarray(Image.fromarray(f).resize(self.size, Image.BOX)) for f in frames])   # same as training
        outs = self._run(np.ascontiguousarray(x.transpose(0, 3, 1, 2)))
        res = [{} for _x in frames]
        for h, o in zip(self.heads, outs):
            if h["kind"] == "class":
                e = np.exp(o - o.max(axis=1, keepdims=True))
                p = e / e.sum(axis=1, keepdims=True)
                for i in range(len(frames)):
                    res[i][h["id"]] = {"probs": p[i], "classes": h["classes"]}
            else:
                v = np.asarray(o).reshape(-1)
                for i in range(len(frames)):
                    res[i][h["id"]] = {"value": float(v[i])}
        return res


class NoModel:
    """No trained model yet: every state is judged by its screen rule (a new project can run right away)."""
    heads = []
    size = None

    def __init__(self):
        self.backend = _("沒有模型:只用畫面規則")

    def __call__(self, frames):
        return [{} for _x in frames]


def smooth(history):
    """Average the class probabilities (and take the median of ratios) over the last ticks."""
    out = {}
    for sid in history[-1]:
        items = [h[sid] for h in history if sid in h]
        if "probs" in items[0]:
            p = np.mean([it["probs"] for it in items], axis=0)
            j = int(p.argmax())
            out[sid] = {"value": items[0]["classes"][j], "conf": round(float(p[j]), 3)}
        else:
            out[sid] = {"value": round(float(np.median([it["value"] for it in items])), 4)}
    return out


class Shadow:
    def __init__(self, data_root, ckpt, interval=1.0, fast_dir=None):
        self.data_root, self.interval = data_root, interval
        self.dir = os.path.join(project.work_of(data_root), "shadow")    # kept: logs, audit frames, flags
        self.fast = fast_dir or self.dir                                  # rewritten every tick
        os.makedirs(os.path.join(self.dir, "log"), exist_ok=True)
        for sub in ("live", "flag_requests", "snap_requests", "snaps", "sub_requests", "schedule_requests", "schedule_jobs",
                    "act_requests"):
            os.makedirs(os.path.join(self.fast, sub), exist_ok=True)
        from automation import settings as user_settings
        # arguments passed as {"setting": id}: what the users chose, read when a run starts
        SubRun.setting_lookup = lambda device, sid: user_settings.run_value(data_root, self.fast, sid, device)
        from notify import Notifier
        self.notifier = Notifier(self.fast)                   # tells people (Discord ...) in its own thread
        self.ckpt = ckpt                                      # None: no model yet, screen rules only (NoModel)
        self.run_dir = os.path.dirname(ckpt) if ckpt else None
        self.pred = Predictor(ckpt) if ckpt else NoModel()
        self.caps = {}                                        # device name -> the driver's capture (light way only)
        from .health import Health
        self.health = Health()                                # how each source is doing (runtime/health.py)
        self.seen_sources = None                              # the sources found last time (one going away is told)
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=SMOOTH))
        self.recent = collections.defaultdict(lambda: collections.deque(maxlen=STABLE))   # (device, script) -> actions
        self.current = {}                                     # (device, script) -> {"decision", "since"}
        self.tracker = engine.Tracker()
        self.script_sig = None
        self.scripts, self.names = [], {}
        self.counts = collections.Counter()
        self.started = time.time()
        self.clock = time.time                                # replaced by the replay (recorded frame times)
        # live execution
        self.exec = Executor()
        self.procs = {}                                       # device -> SubRun (has control of that device)
        self.subs, self.prio = {}, {}                         # sub-script library; main script id -> priority (0 = first)
        self.situ = {}                                        # (device, script) -> {"id", "since", "enter"}: current situation
        self.switches = collections.defaultdict(collections.deque)   # (device, script) -> times of situation switches
        self.held = {}                                        # device -> guard rule text holding the other scripts
        self.timeline = collections.defaultdict(collections.deque)   # (device, state) -> [(t, value)] (changes; ratios every tick)
        self.last_states = {}                                 # device -> its state dict of the latest tick
        self.cur_frames = {}                                  # device -> frame of this tick (to look for find buttons)
        self.cur_frame_t = {}                                 # device -> when that frame was taken
        self._list_seen = {}                                  # the last list read off a frame (list_find)
        self.act_queue = collections.defaultdict(list)        # device -> page actions waiting for the device to be free
        self.page_hold = {}                                   # device -> who paused its schedule from the page
        self._migrate_switch()
        self.device_hold = self._load_hold()                  # device | "*" -> {"mode": stop | pause | run, "by", "t"}
        self.ready_since = {}                                 # device -> since when it has had a healthy picture
        self.parked = {}                                      # device -> a run set aside (paused) for an urgent rule
        self.manual_since = {}                                # device -> since when someone has been operating it (auto 暫停)
        self.manual_done = {}                                 # device -> 繼續 pressed at (time.time()): touches before it are over
        self.resumed_dev = {}                                 # device -> (time of 繼續, the cause it had stopped for)
        self.trust = arbiter.Trust.empty()                    # model or rule (runtime/arbiter.py); built in the background
        # how sure the model is per state while it runs; says so when a state starts going wrong (runtime/quality.py)
        self.quality = quality_mod.Quality(self.fast, os.path.basename(self.run_dir) if self.run_dir else "rules", lambda: self.names,
                                           lambda dev, text: self.alert(dev, _("[品質監測] {text}", text=text)))
        self._trust_job = None
        self._list_pics = {}                                  # where the names of a list fit on the last frame
        self.fire_days = {}                                   # (device, script, rule) -> [date, times fired that day]
        self.var_defs, self.var_labels = [], {}
        self.vars = self._load_vars()
        self.last_fire = {}                                   # (device, script, rule) -> time
        self.fire_times = collections.defaultdict(collections.deque)   # (device, script, rule) -> times in the last hour
        self.strikes = collections.Counter()                  # (device, script, rule) -> firings without effect
        self.blocked = {}                                     # (device, script, rule) -> reason
        self.no_effect = set()                                # the blocked keys paused for "no effect" (released when it no longer matches)
        self.tap_times = collections.defaultdict(collections.deque)
        self.alerts = collections.deque(maxlen=40)
        self.ctrl, self.unblocked_at = dict(CONTROL_DEFAULT), 0.0
        self.resumed_at = time.time()                         # resume requests older than this start are done
        self.rule_states, self.rule_tpls = [], {}
        self.check_states, self.check_tpls = [], {}           # model-judged states that also have a screen rule
        self.model_only = set()                               # states set to 只用模型
        self.touch = {}                                       # device -> the driver's touch watcher (manual operation)
        self.saved_times = collections.deque()                # times of automatically saved frames (last hour)
        self.incidents = incidents_mod.Incidents()            # urgent rules: their whole story, apart from the daily log
        self.incidents.on_event = lambda kind, dev, text, frame, now: self.notifier.emit(kind, dev, text, frame=frame, now=now)
        self.sched_state = schedules.State(os.path.join(self.fast, "schedules_state.json"))
        self.jobs = {}                                        # device -> JobLog of the schedule running there
        self.sched_force = {}                                 # device -> schedule to start now ("立即執行")
        self.sched_wait = {}                                  # (schedule, device) -> why it has not started yet
        self.saved_by = collections.defaultdict(collections.deque)   # (device, state) -> times
        self.wait_since = {}                                  # (device, script) -> (since, (action, rule)) while waiting
        self.stuck_told = set()                               # the stuck episodes whose screen was kept
        self.last_save = {}                                   # device -> time

    def control(self):
        self._var_requests()
        c = dict(CONTROL_DEFAULT)
        try:
            c.update(json.load(open(os.path.join(self.fast, "control.json"), encoding="utf-8")))
        except (OSError, ValueError):
            pass
        if c.get("unblock", 0) > self.unblocked_at:
            self.unblocked_at = c["unblock"]
            if self.blocked:
                self.alert("", _("解除 {p1} 條暫停的規則", p1=len(self.blocked)), "info")
            self.blocked.clear()
            self.no_effect.clear()
            self.strikes.clear()
        for r in c.get("resume") or []:                  # the page released one paused rule
            if r.get("t", 0) <= self.resumed_at:
                continue
            self.resumed_at = r["t"]
            if r.get("rule") not in (None, "", "(整個腳本)"):
                key = (r.get("device"), r.get("script"), r.get("rule"))
                self.no_effect.discard(key)
                if self.blocked.pop(key, None):
                    self.strikes.pop(key, None)
                    self.alert(r.get("device") or "", _("解除暫停的規則「{rule}」(從網頁)", rule=r.get('rule')), "info")
        self.ctrl = c

    def _append_log(self, rec):
        day = datetime.datetime.now().strftime("%Y%m%d")
        with open(os.path.join(self.dir, "log", f"{day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def alert(self, device, text, level="warn", kind=None):
        """Something people should know. kind (for notifications): "notify" for a script's 通知, else from the level."""
        a = {"t": round(self.clock(), 3), "device": device, "text": text, "level": level}
        self.notifier.emit(kind or ("warn" if level == "warn" else "info"), device, text, now=a["t"])
        self.alerts.appendleft(a)
        if device:
            self.incidents.note(device, a["t"], "alert", text, level=level)
        self._append_log({**a, "action": "alert", "reason": level})
        print(f"{datetime.datetime.now():%H:%M:%S} {device:14} ! {text}", flush=True)

    def _health_news(self, n, state, text):
        """Told once per change: lost / frozen (warn), back to normal (info). slow only shows on the pages."""
        from drivers.sources import label
        if state in ("lost", "frozen"):
            self.alert(n, _("來源「{p1}」{text}", p1=label(n, self.data_root), text=text))
        elif state == "ok" and getattr(self, "_told_bad", {}).get(n):
            self.alert(n, _("來源「{p1}」恢復正常", p1=label(n, self.data_root)), "info")
        self.__dict__.setdefault("_told_bad", {})[n] = state in ("lost", "frozen")

    def _source_news(self, drv, found, names=None):
        """A source found for the first time (not used until someone ticks it), or one whose screen is not the
        project's size (taps would land elsewhere): said once."""
        from drivers import describe, sources
        for k, d in getattr(drv, "fresh", None) or []:
            kind = (describe().get(k) or {}).get("label", k).split("(")[0]
            self.alert(None, _("發現新的來源「{name}」({kind}{p3}):到「來源」頁按「使用」才會用它", name=d.name, kind=kind, p3=' · ' + d.detail if d.detail else ''), "info")
        names = names if names is not None else {d.name for d in found}   # a source in use that is not there any more
        if self.seen_sources is not None:
            from drivers.sources import label, load as load_sources
            used = {it["id"] for it in load_sources(self.data_root)["items"] if it.get("enabled")}
            for n in (self.seen_sources - names) & used:
                self.alert(n, _("來源「{p1}」找不到了(關掉了、斷線,或名稱改了)", p1=label(n, self.data_root)))
            for n in names - self.seen_sources:
                if n in getattr(self, "_gone", set()):
                    self.alert(n, _("來源「{p1}」又找到了", p1=label(n, self.data_root)), "info")
            self.__dict__["_gone"] = (getattr(self, "_gone", set()) | (self.seen_sources - names)) - names
        self.seen_sources = names
        told = self.__dict__.setdefault("_size_told", set())
        for d in found:
            if d.name not in told:
                told.add(d.name)
                k = drivers.kinds().get((d.info or {}).get("kind"))
                w = sources.check_size(d, self.data_root, bool(k and k.per_source))
                if w:
                    self.alert(d.name, _("來源的畫面大小:{w}", w=w), "warn")

    def devices(self):
        try:
            drv = drivers.current(self.data_root)
            found = drv.list()
            names = [i.name for i in found]
        except Exception:
            return sorted(self.caps)
        # one scan that misses a source (the emulator's console answered with an empty list for a moment) is no
        # source gone: it is kept, its picture still taken, until it has been missing for GONE_GRACE seconds
        now, missing = time.time(), self.__dict__.setdefault("_missing", {})
        for n in names:
            missing.pop(n, None)
        from drivers import sources as sources_mod
        on = {it["id"] for it in sources_mod.load(self.data_root)["items"] if it.get("enabled")}   # turned off on purpose: gone now
        names += [n for n in sorted(self.caps) if n not in names and n in on and now - missing.setdefault(n, now) < GONE_GRACE]
        self._source_news(drv, found, set(names))
        for n in names:                                       # never the costly way: it would slow the device down
            if n not in self.caps and "screen" in drv.caps:
                try:
                    self.caps[n] = drv.capture(n, prefer="window", fallback=False)
                except Exception:
                    pass
        for n in list(self.caps):
            if n not in names:
                del self.caps[n]
        for n in names:                                       # watch each device's touch screen (manual operation)
            if n not in self.touch and "touch_watch" in drv.caps:
                w = drv.watch_touch(n, lambda g: None)
                if w:
                    self.touch[n] = w
                    w.start()
        for n in list(self.touch):
            if n not in names:
                self.touch.pop(n).close()
        return sorted(self.caps)

    def _manual(self, n, now):
        """None (pausing is off) or {"watched", "paused", "resume_in"}: someone touched the device recently."""
        rec, secs = self.touch.get(n), self.ctrl.get("manual_pause_s", 0)
        if not secs:
            return None
        if not rec:
            return {"watched": False, "paused": False, "resume_in": 0, "last": None}
        last = max(rec.last_event, rec.last_touch)
        if self.manual_done.get(n, 0) >= last:              # 繼續 was pressed after the last touch: the person is done
            return {"watched": True, "paused": False, "resume_in": 0, "last": round(last, 3) if last else None}
        ago = now - last
        return {"watched": True, "paused": ago < secs, "resume_in": max(0, round(secs - ago)),
                "last": round(now - ago, 3) if ago < 1e9 else None}

    # ---------- variables ----------
    def _load_vars(self):
        try:
            v = json.load(open(os.path.join(self.fast, "vars.json"), encoding="utf-8"))
        except (OSError, ValueError):
            v = {}
        return {"day": v.get("day"), "global": v.get("global") or {}, "device": v.get("device") or {}}

    def _save_vars(self):
        _write_json(os.path.join(self.fast, "vars.json"), self.vars)

    def _vars_today(self, now):
        """Fill in new variables, and reset the "daily" ones when the date has changed."""
        day = datetime.date.fromtimestamp(now).isoformat()
        changed = False
        for d in self.var_defs:
            init = d.get("initial", 0)
            if d["scope"] == "global":
                if d["name"] not in self.vars["global"] or (self.vars["day"] != day and d["reset"] == "daily"):
                    self.vars["global"][d["name"]] = init
                    changed = True
            else:
                for dev, vals in self.vars["device"].items():
                    if d["name"] not in vals or (self.vars["day"] != day and d["reset"] == "daily"):
                        vals[d["name"]] = init
                        changed = True
        if self.vars["day"] != day:
            self.vars["day"] = day
            changed = True
        if changed:
            self._save_vars()

    def var_values(self, n):
        """Every variable's value as device n sees it (its own copy of "device" variables, the shared "global")."""
        mine = self.vars["device"].setdefault(n, {})
        out = {}
        for d in self.var_defs:
            if d["scope"] == "global":
                out[d["name"]] = self.vars["global"].get(d["name"], d.get("initial", 0))
            else:
                out[d["name"]] = mine.setdefault(d["name"], d.get("initial", 0))
        return out

    def send_output(self, n, out_id, command, value, by=""):
        """Send to an output (automation/outputs.py) in the background -> Future. A failure is an alert."""
        f = outputs_mod.send(self.data_root, out_id, {"device": n, "script": by, "command": command, "value": value})
        now = self.clock()
        self._append_log({"t": round(now, 3), "device": n, "executed": True, "action": "output", "output": out_id,
                          "command": command, "value": value, "script_name": by})

        def done(fu, n=n, out_id=out_id):
            if fu.exception() is not None:
                self.alert(n, _("[{by}] 送到輸出「{out_id}」失敗:{p3}", by=by, out_id=out_id, p3=fu.exception()))
        f.add_done_callback(done)
        return f

    # ---- the 問使用者 step (notify/asks.py): the server posts it to the chats and takes the first answer ----
    def ask(self, n, text, options, timeout, default, by=""):
        from notify import asks
        qid = asks.create(self.fast, n, text, options, timeout, default, by)
        self._append_log({"t": round(self.clock(), 3), "device": n, "action": "ask", "ask": qid, "text": text, "options": options})
        return qid

    def ask_answer(self, qid):
        from notify import asks
        return asks.answer_of(self.fast, qid)

    def ask_close(self, qid, status):
        from notify import asks
        asks.close(self.fast, qid, status)

    def set_var(self, n, name, mode, value, now):
        d = next((x for x in self.var_defs if x["name"] == name), None)
        if not d:
            return
        store = self.vars["global"] if d["scope"] == "global" else self.vars["device"].setdefault(n, {})
        old = store.get(name, d.get("initial", 0))
        store[name] = round(now, 3) if mode == "now" else (float(old or 0) + float(value or 0)) if mode == "add" else value
        if isinstance(store[name], float) and store[name].is_integer() and mode != "now":
            store[name] = int(store[name])
        self._save_vars()
        self._append_log({"t": round(now, 3), "device": n, "action": "set_var", "var": name, "old": old, "new": store[name]})

    def _var_requests(self):
        rdir = os.path.join(self.fast, "var_requests")
        if not os.path.isdir(rdir):
            return
        for f in sorted(x for x in os.listdir(rdir) if x.endswith(".json")):   # not the .tmp being written
            p = os.path.join(rdir, f)
            try:
                req = json.load(open(p, encoding="utf-8"))
                os.remove(p)
            except (OSError, ValueError):
                continue
            d = next((x for x in self.var_defs if x["name"] == req.get("var")), None)
            if not d or not isinstance(req.get("value"), (int, float)):
                continue
            if isinstance(req["value"], float) and req["value"].is_integer():
                req["value"] = int(req["value"])
            if d["scope"] == "global":
                self.vars["global"][d["name"]] = req["value"]
            elif req.get("device"):
                self.vars["device"].setdefault(req["device"], {})[d["name"]] = req["value"]
            self._save_vars()
            self.alert(req.get("device") or "", _("變數「{p1}」改成 {value}(從網頁)", p1=d.get('label') or d['name'], value=req['value']), "info")

    def resolve_point(self, n, target):
        """Where to tap a button target on device n now: a find button is looked for in this tick's frame.
        A user setting as the target: this device's choice (a button or a position)."""
        if set(target or {}) == {"setting"}:
            target = (SubRun.setting_lookup(n, target["setting"]) if SubRun.setting_lookup else None) or {}
            if not isinstance(target, dict):
                return None
            if "x" in target and "y" in target and "button" not in target:
                return [int(target["x"]), int(target["y"])]
        b = buttons_mod.load(self.data_root).get((target or {}).get("button"))
        if not b:
            return None
        if not b.get("find"):
            return [b["x"], b["y"]]
        spec = lists_mod.load(self.data_root).get(b.get("list") or "")
        if spec and spec.get("match") == "run":           # names a character apart: told by the whole run of rows
            f = self.list_find(n, target)
            return f.get("point") if f else None
        frame = self.cur_frames.get(n)
        (x, y), score = buttons_mod.locate(b, frame, self.data_root)
        if x is None:
            return None
        if spec:                                          # a list name: no other name of the list may fit that row better
            for o, (oy, osc) in self._list_names(n, spec, frame).items():
                if o != b["id"] and abs(oy - y) < 25 and osc > score:
                    return None
        return [int(x), int(y)]

    def _list_names(self, n, spec, frame):
        """Where each name of a (picture-matched) list fits on this frame: {id: (y, score)}, once per frame."""
        seen = self._list_pics
        if not (seen.get("frame") is frame and seen.get("list") == spec["id"]):
            out = {}
            for o in lists_mod.items(self.data_root, spec, n):
                (ox, oy), osc = buttons_mod.locate(o, frame, self.data_root)
                if ox is not None:
                    out[o["id"]] = (oy, osc)
            seen = self._list_pics = {"frame": frame, "list": spec["id"], "names": out}
        return seen["names"]

    def list_capture(self, n, list_id, owner):
        """Walk a list (lists.py) on device n in a thread, saving the new names as buttons (the 擷取清單 step).
        -> a job {"done", "error", "result"} to poll. It uses this loop's frames (a fresh one after each move) and the
        device's command lane; it stops if `owner` (the run) no longer has the device or the job is cancelled."""
        job = {"done": False, "error": None, "result": None, "cancel": False}
        spec = lists_mod.load(self.data_root).get(list_id or "")
        if not spec:
            job.update(done=True, error=_("沒有清單「{list_id}」", list_id=list_id))
            return job

        def alive():
            if job["cancel"] or self.procs.get(n) is not owner:
                raise ValueError(_("被中斷了"))

        def fresh():
            alive()
            asked = self.clock()
            for _x in range(150):
                if self.cur_frame_t.get(n, 0) > asked and self.cur_frames.get(n) is not None:
                    return self.cur_frames[n]
                time.sleep(0.1)
            raise ValueError(_("等不到這台的畫面(視窗可能縮到最小)"))

        def swipe(x, y1, y2):
            alive()
            self.exec.submit(n, "swipe", x1=x, y1=y1, x2=x, y2=y2, ms=900).result(timeout=15)
            time.sleep(0.3)

        def tap(x, y):
            alive()
            self.exec.submit(n, "tap", x=x, y=y).result(timeout=15)

        def work():
            try:
                job["result"] = lists_mod.capture(self.data_root, spec, n, fresh, swipe, tap)
                lists_mod.note_scan(self.fast, spec, n, job["result"])
            except Exception as e:
                job["error"] = str(e)
            job["done"] = True
        threading.Thread(target=work, daemon=True, name=f"capture {n}").start()
        return job

    def list_find(self, n, target):
        """A name of a list (lists.py) on device n's screen now -> {"point"} where it is, {"swipe": "down" | "up",
        "move": [x, y1, y2]} which way it is (one page), or None (not a list name / no list rows on the screen)."""
        b = buttons_mod.load(self.data_root).get((target or {}).get("button"))
        spec = lists_mod.load(self.data_root).get((b or {}).get("list") or "")
        frame = self.cur_frames.get(n)
        if not spec or frame is None:
            return None
        seen = self._list_seen
        if not (seen.get("frame") is frame and seen.get("list") == spec["id"]):   # once per frame and list
            seen = self._list_seen = {"frame": frame, "list": spec["id"], "w": lists_mod.which(self.data_root, spec, frame, n)}
        w = seen["w"]
        rows = w["rows"]
        if not any(r["id"] for r in rows):
            return None
        for r in rows:
            if r["id"] == b["id"]:
                x, y, bw, bh = r["box"]
                return {"point": [x + bw // 2, y + bh // 2]}
        order = [x["id"] for x in lists_mod.ordered(self.data_root, spec, n)]
        if b["id"] not in order:
            return None
        sw = spec["swipe"]
        at = order.index(b["id"])
        down = at > w["top"] + len(rows) - 1
        away = at - (w["top"] + len(rows) - 1) if down else w["top"] - at
        y1, y2 = sw["page"] if down else sw["page"][::-1]
        if away > 2 and len(rows) >= 3:                   # far off: almost a page at once (slow drag, no fling)
            row_h = (rows[-1]["box"][1] - rows[0]["box"][1]) / (len(rows) - 1)
            px = int(min(away, len(rows) - 1) * row_h)
            mid = (rows[0]["box"][1] + rows[-1]["box"][1] + rows[-1]["box"][3]) // 2
            y1, y2 = (mid + px // 2, mid - px // 2) if down else (mid - px // 2, mid + px // 2)
        return {"swipe": "down" if down else "up", "move": [sw["x"], y1, y2]}

    def ctx(self, n):
        """What the time and memory conditions of device n can see (automation/conds.py)."""
        return {"history": {sid: list(q) for (dev, sid), q in self.timeline.items() if dev == n},
                "vars": self.var_values(n), "devices": self.last_states, "var_labels": self.var_labels,
                "states": self.last_states.get(n) or {},
                "setting": lambda sid, n=n: SubRun.setting_lookup(n, sid) if SubRun.setting_lookup else None,
                "visible": lambda target, n=n: self.resolve_point(n, target) is not None}

    def _remember(self, n, st, now):
        """Keep device n's recent values: class states when they change, ratios every tick."""
        for sid, v in (st or {}).items():
            if v.get("value") is None or v.get("conf", 1) < conds.DEFAULT_MIN_CONF:
                continue
            q = self.timeline[(n, sid)]
            ratio = (self.names.get(sid) or {}).get("type") == "ratio"
            if ratio or not q or q[-1][1] != v["value"]:
                q.append((now, v["value"]))
            while q and now - q[0][0] > conds.HISTORY_SECONDS:
                if len(q) > 1 and not ratio and now - q[1][0] > conds.HISTORY_SECONDS:
                    q.popleft()
                elif ratio:
                    q.popleft()
                else:
                    break                                 # keep the change that led to the current value

    def reload(self):
        sch = schema_mod.load(self.data_root)
        sig = automation.signature(self.data_root) + "|" + str(os.path.getmtime(
            os.path.join(self.data_root, "meta", "states", "current.json"))) + f"|{schema_mod.settings_mtime(self.data_root)}|" \
            + generic.signature(sch, self.data_root)
        if sig == self.script_sig:
            return
        self.script_sig = sig
        self.scripts = [s for s in automation.load_all(self.data_root) if s.get("enabled", True)]   # priority order
        self.prio = {s["id"]: i for i, s in enumerate(self.scripts)}
        self.var_defs = automation.variables(self.data_root)
        self.var_labels = {d["name"]: d.get("label") or d["name"] for d in self.var_defs}
        self.subs = {**subs_mod.load_all(self.data_root), **automation.inline_subs(self.scripts)}  # + rules' own step lists
        self.names = engine.names_from_schema(sch)
        # states the model was not trained on yet (or did not pass its test), but a screen rule can tell:
        # evaluate the rule on the live frame, so a new state works right away without retraining
        auto_rules.configure(sch, self.data_root)             # plugin-provided rules check the model too (arbiter)
        src = judge.sources(sch, self.run_dir, auto_rules.provided_ids())["states"]
        self.model_only = {sid for sid, v in src.items() if v.get("only")}     # 只用模型: no rule backs it up
        self.rule_names = {s["id"]: s["source"].get("rule") for s in sch["states"] if s.get("source", {}).get("kind") == "rule"}
        self._trust_refresh(sch, force=True)
        self.rule_states = [s for s in sch["states"] if (src.get(s["id"]) or {}).get("source") == "rule"]
        self.rule_tpls = {s["id"]: generic.load_templates(self.data_root, s) for s in self.rule_states
                          if generic.is_generic(s) and s["source"]["rule"] in ("template", "digits")}
        if self.rule_states:
            print(_("{p1} 用畫面規則判斷:", p1=format(datetime.datetime.now(), '%H:%M:%S')) + _("、").join(s["name"] for s in self.rule_states), flush=True)
        # states the model answers but a screen rule could also tell: a disagreement is worth a question
        self.check_states = [s for s in sch["states"] if (src.get(s["id"]) or {}).get("source") == "model"
                             and generic.is_generic(s) and s["type"] == "class" and s["id"] not in self.model_only]
        self.check_tpls = {s["id"]: generic.load_templates(self.data_root, s) for s in self.check_states
                           if s["source"]["rule"] == "template"}
        print(_("{p1} 載入腳本:", p1=format(datetime.datetime.now(), '%H:%M:%S')) + (_("、").join(s["name"] for s in self.scripts) or _("(沒有啟用的腳本)")), flush=True)

    def _trust_refresh(self, sch=None, force=False):
        """(Re)build the model-or-rule table in the background; until it is ready an empty one is used (the model is
        believed except where it is unsure)."""
        if not force and (self._trust_job or time.time() - self.trust.built < arbiter.REFRESH):
            return
        if not self.run_dir:                              # no model: nothing to weigh against the rules
            return
        sch = sch or schema_mod.load(self.data_root)

        def build():
            try:
                t = arbiter.Trust(self.data_root, self.run_dir, sch, auto_rules)
                self.trust = t
                print(_("{p1} 模型/規則可信度表已更新:", p1=format(datetime.datetime.now(), '%H:%M:%S')) + _("、").join(
                    _("{k} 規則{p2}種答案", k=k, p2=len(v.get('rule', {}))) for k, v in t.table().items()), flush=True)
            except Exception as e:                        # never stop the loop for this
                print(_("{p1} 可信度表建立失敗:{e}", p1=format(datetime.datetime.now(), '%H:%M:%S'), e=e), flush=True)
            finally:
                self._trust_job = None
        self._trust_job = threading.Thread(target=build, daemon=True)
        self._trust_job.start()

    # ---------- one tick ----------
    def tick(self, names):
        t0 = self.clock()
        self.reload()
        self._trust_refresh()
        self.control()
        self._schedule_requests(t0)
        self._act_requests(t0)
        frames, info = {}, {}
        for n in names:
            g0 = time.time()
            try:
                got = self.caps[n].grab()
            except Exception:
                got = None
            ms = (time.time() - g0) * 1000
            if got:
                frames[n], info[n] = got[0], f"{got[2][0]}x{got[2][1]}"
                self.health.frame(n, got[0], ms, self.clock())
            else:
                self.health.miss(n, ms, self.clock())
        preds = self.pred(list(frames.values())) if frames else []
        t_model = self.clock() - t0
        watching = self._watching()
        devs = []
        for n in names:
            if n in frames:
                self.hist[n].append(preds[list(frames).index(n)])
                st = smooth(list(self.hist[n]))
                for v in st.values():
                    v["source"] = "model"
                for rs in self.rule_states:                     # the rule answers these instead of the model
                    st.pop(rs["id"], None)
                ctx = {k: v["value"] for k, v in st.items()}
                plug = None                                     # a plugin's rules, run once if a state needs them
                for rs in self.rule_states:
                    if not generic.is_generic(rs):              # a rule a plugin provides (只用規則 / not learned)
                        plug = plug or auto_rules.label_frame(frames[n], generic=False)
                        v = auto_rules.live_answer(rs["id"], plug)
                        st[rs["id"]] = {"value": v, "conf": 1.0 if v is not None else 0.0, "source": "rule",
                                        "rule": self.rule_names.get(rs["id"], "rule"), "score": None}
                        ctx[rs["id"]] = v
                        continue
                    v, sc = generic.evaluate(rs, frames[n], self.rule_tpls.get(rs["id"]), ctx)
                    # undecided (two classes look alike) -> value None = "not sure", so scripts wait instead of guessing
                    st[rs["id"]] = {"value": v, "conf": 1.0 if v is not None else 0.0, "source": "rule",
                                    "rule": rs["source"]["rule"], "score": _rule_score(v, sc)}
                    ctx[rs["id"]] = v
                # model or screen rule: where they disagree, the one that has been right more often in that kind of case
                # (runtime/arbiter.py) - the same for every state that has a rule, built-in or made on the state page
                rule_vals = self._rule_values(n, frames[n], st, ctx)
                trust = self.trust
                fb = {}
                for sid, (rv, rule_name) in rule_vals.items():
                    m = st.get(sid) or {}
                    use, why = trust.decide(sid, m.get("value"), m.get("conf"), rv)
                    if use:
                        fb[sid] = {"value": rv, "conf": round(trust.rule_rate(sid, rv)[0], 3), "source": "rule", "rule": rule_name,
                                   "why": why, "model_unsure": {"value": m.get("value"), "conf": m.get("conf")}}
                    elif rv == m.get("value") and m.get("conf") is not None:
                        # both say the same: as sure as the rule has been with this answer (else a 0.64 "map closed" that
                        # the rule confirms would still leave a script waiting for 0.7)
                        c = trust.agree_conf(sid, rv, m["conf"])
                        if c > m["conf"]:
                            fb[sid] = {**m, "conf": round(c, 3), "model_conf": m["conf"], "source": "model+rule", "rule": rule_name,
                                       "why": _("模型 {conf} 和規則都說是這個", conf=format(m['conf'], '.2f'))}
                if watching:
                    self._live(n, frames[n])
                self._maybe_save(n, frames[n], st, t0, rule_vals)   # (the model's own answers: unsure / disagreeing = a question)
                self.quality.add(t0, n, st, rule_vals)
                st.update(fb)
                self._remember(n, st, t0)
                self.last_states[n] = st
                self.cur_frames[n] = frames[n]
                self.cur_frame_t[n] = t0
            else:
                self.hist[n].clear()
                st = None
            self._vars_today(t0)
            ctx = self.ctx(n)
            decisions = []
            manual = self._manual(n, t0)
            if n in self.parked and n not in self.procs:   # the urgent rule is done: carry on what was set aside
                pr = self.parked.pop(n)
                if self.hold_of(n):
                    self.procs[n] = pr                        # (paused or cancelled below, as any run would be)
                else:
                    pr.resume(t0)
                    self.procs[n] = pr
                    self.alert(n, _("接續「{sub_name}」(緊急規則處理完了)", sub_name=pr.info(self.names)['sub_name']), "info")
                    if n in self.jobs and pr.origin.get("schedule"):
                        self.jobs[n].add(t0, "resume", _("繼續(緊急規則處理完了)"), frame=frames.get(n), force=True)
            run = self.procs.get(n)
            hold = self.hold_of(n)
            if run and hold and hold["mode"] == "stop" and run.result is None:   # stopped meanwhile (e.g. a restart)
                run.abort(_("已停下來({p1})", p1=hold.get('by') or _("網頁")), t0, cleanup=True)
            elif run and (run.origin.get("schedule") or (hold and hold["mode"] == "pause") or getattr(run, "pause_why", None)):
                # 暫停 holds any run where it is; a schedule also steps aside for the person, and carries on afterwards
                self._schedule_pause(n, run, t0, _("暫停") if hold and hold["mode"] == "pause" else
                                     _("手動操作") if manual and manual["paused"] and run.origin.get("schedule") else None)
            elif run and manual and manual["paused"] and run.result is None:   # the person took over the device
                run.abort(_("偵測到手動操作"), t0, cleanup=False)
            self._sub_if_requested(n, st, t0)
            self._act_tick(n, st, t0, manual)
            self._schedule_tick(n, st, t0, manual, frames.get(n))
            run = self.procs.get(n)
            sched_hold = run.origin.get("schedule_name") if run and run.origin.get("schedule") and run.origin.get("pause_others") else None
            # every script is evaluated on every tick, even while a sub-script has control: an urgent rule or a
            # higher-priority script must be able to step in - unless the device is stopped / paused: then nothing of
            # its scripts moves (停下來: 繼續 starts them over; 暫停: 繼續 carries on where they were)
            enter = []                                        # entry actions due this tick
            hold = self.hold_of(n)
            operating = bool(manual and manual["paused"])
            if operating and not hold:                          # someone operates it: 暫停 on its own
                if n not in self.manual_since:
                    self.manual_since[n] = t0
                    self.alert(n, _("偵測到手動操作:暫停(腳本和情境停在原地)"), "info")
            elif n in self.manual_since:                      # nobody for manual_pause_s: carry on (as 繼續 after 暫停)
                since = self.manual_since.pop(n)
                if not hold:
                    self._carry_on(n, {"t": since}, now=t0)
                    self.alert(n, _("手動操作結束:接著做(同一個情境)"), "info")
            if operating and not hold:
                hold = {"mode": "pause", "manual": True}
            for sc in self.scripts if hold else []:
                mode = automation.mode_for(sc, n)
                if mode == "off":
                    continue
                cause = hold.get("cause") or {}
                if cause.get("rule") and cause.get("script") == sc["id"]:   # is what stopped it still so? (only read)
                    cur = self.situ.get((n, sc["id"])) or {"id": sc["initial"]}
                    dec = engine.evaluate(sc, st, self.tracker, self.names, device=n, now=t0, subs=self.subs, situation=cur["id"], ctx=ctx)
                    decisions.append({**dec, "mode": mode, "guard": automation.is_guard(sc), "stable": True, "since": None})
                    continue
                decisions.append({"script": sc["id"], "script_name": sc["name"], "mode": mode, "guard": automation.is_guard(sc),
                                  "action": "none", "text": _("手動操作中") if hold.get("manual") else _("已停下來") if hold["mode"] == "stop" else _("暫停中"),
                                  "reason": _("有人在操作,{resume_in} 秒沒有操作後從同一個情境接著做", resume_in=manual['resume_in']) if hold.get("manual")
                                  else _("腳本和情境都停住,按「繼續」從頭開始") if hold["mode"] == "stop"
                                  else _("停在原地,按「繼續」從同一個情境接著做"), "rule": None, "stable": True, "exec": "", "tap": None})
            for sc in [] if hold else self.scripts:
                mode = automation.mode_for(sc, n)
                if mode == "off":
                    continue
                if sched_hold and not automation.is_guard(sc):      # a schedule runs here: the main scripts wait
                    decisions.append({"script": sc["id"], "script_name": sc["name"], "mode": mode, "guard": False, "action": "none",
                                      "text": _("排程中暫停"), "reason": _("{sched_hold}執行中,這個腳本暫停", sched_hold=sched_hold), "rule": None,
                                      "stable": True, "exec": "", "tap": None})
                    continue
                sit = self._situation(n, sc, t0, st)
                if sit["enter"]:
                    enter.append(self._enter_decision(n, sc, mode, sit))
                dec = engine.evaluate(sc, st, self.tracker, self.names, device=n, now=t0, subs=self.subs, situation=sit["id"], ctx=ctx)
                dec["mode"] = mode
                dec["guard"] = automation.is_guard(sc)
                key = (n, sc["id"])
                self.recent[key].append((dec["action"], dec.get("rule")))
                dec["stable"] = len(self.recent[key]) == STABLE and len(set(self.recent[key])) == 1
                cur = self.current.get(key)
                if dec["stable"] and (not cur or cur["decision"]["action"] != dec["action"]
                                      or cur["decision"].get("rule") != dec.get("rule")):
                    self.current[key] = {"decision": dec, "since": t0}
                    self._log(n, dec, st)
                dec["since"] = (self.current.get(key) or {}).get("since")
                decisions.append(dec)
            self._guard_hold(n, decisions, t0)
            # an entry action goes right after its script's guard/higher-priority neighbours: just before its own decision
            for e in enter:
                i = next((k for k, d in enumerate(decisions) if d["script"] == e["script"]), len(decisions))
                decisions.insert(i, e)
            self._urgent_watch(decisions)
            self.incidents.begin(os.path.join(self.dir, "incidents"), n, t0, st, decisions, frames.get(n))
            self._execute(n, st, decisions, frames.get(n), t0, manual)
            for e in enter:                                   # done, unless it is only waiting for its turn
                if not e.get("wait"):
                    s = self.situ.get((n, e["script"]))
                    if s and s["id"] == e["situation"]:
                        s["enter"] = False
            run = self.procs.get(n)
            if run and run.paused_at is None:                 # one bookmark step of the running sub-script
                run.advance(st, t0, self.exec, self.names, lambda text, level, n=n, run=run: self._run_event(n, run, text, level), env=self)
                if run.done:
                    del self.procs[n]
                    self._run_ended(n, run)
                elif run.origin.get("schedule"):
                    self._schedule_save(n, run, t0)
            self._flag_if_requested(n, frames.get(n), st, decisions)
            self._snap_if_requested(n, frames.get(n))
            run = self.procs.get(n)
            hs, htext, hchanged, hinfo = self.health.check(n, self.clock(), int(self.ctrl.get("freeze_seconds", 300) or 0))
            if hchanged:
                self._health_news(n, hs, htext)
                if hs == "frozen":
                    self._stuck_snap(n, frames.get(n), st, _("畫面沒有變化:{htext}", htext=htext))
            self._stuck_check(n, frames.get(n), st, decisions, t0)
            if hs in ("ok", "slow"):                               # the start check counts from a healthy picture
                self.ready_since.setdefault(n, self.clock())
            else:
                self.ready_since.pop(n, None)
            devs.append({"name": n, "window": info.get(n), "state": st, "decisions": decisions,
                         "health": {"state": hs, "text": htext, **hinfo},
                         "proc": run.info(self.names) if run else None, "held": self.held.get(n),
                         "situations": {sid: {"id": v["id"], "since": v["since"],
                                              "name": automation.situation(self._script(sid), v["id"]).get("name") if self._script(sid) else v["id"],
                                              "count": len(self._script(sid)["situations"]) if self._script(sid) else 1}
                                        for (dn, sid), v in self.situ.items() if dn == n},
                         "taps_last_min": len(self.tap_times[n]), "manual": manual, "hold": self.hold_of(n),
                         "cause_now": self._cause_now(n, decisions),
                         "start_wait": round(self.start_wait(n, self.clock()), 1) if not self.hold_of(n) else 0})
            self.incidents.tick(n, t0, st, decisions, frames.get(n), devs[-1]["proc"], devs[-1]["held"], devs[-1]["situations"])
        return devs, t_model

    # ---------- live execution ----------
    def _execute(self, n, st, decisions, frame, now, manual=None):
        c = self.ctrl
        q = self.tap_times[n]
        while q and now - q[0] > 60:
            q.popleft()
        acted = False
        # "no effect" pauses last one episode: once that rule no longer matches (e.g. the error screen is gone), it may act again
        firing = {(n, d["script"], d.get("rule")) for d in decisions}
        for key in [k for k, why in self.blocked.items() if k[0] == n and k not in firing and k in self.no_effect]:
            del self.blocked[key]
            self.no_effect.discard(key)
            self.strikes[key] = 0
            sc = next((x for x in self.scripts if x["id"] == key[1]), {})
            rname = next((r.get("name") for r in automation.all_rules(sc) if r.get("id") == key[2]), key[2]) if sc else key[2]
            self.alert(n, _("[{name}] 規則「{rname}」的條件已經不成立,解除暫停(下次成立時會再執行)", name=sc.get('name', key[1]), rname=rname), "info")
        for dec in decisions:
            if dec["action"] == "stop":
                if dec["mode"] != "live":
                    dec["exec"] = _("試跑(不停止)")
                    continue
                hold = self.hold_of(n)
                if hold:                                      # already stopped / paused (maybe by this very rule)
                    dec["exec"] = (_("已停下來") if hold["mode"] == "stop" else _("暫停中")) + _("(按「繼續」恢復)")
                    dec["wait"] = True
                    continue
                if not dec.get("stable") and not dec.get("urgent"):
                    dec["exec"], dec["wait"] = _("確認中"), True
                    continue
                self._rule_stop(n, dec["script"], dec.get("rule"), _("規則「{p1}」", p1=dec.get('rule_name') or dec['text']),
                                f"{dec['text']}({dec['reason']})", now)
                dec["exec"] = _("已停下來這台")
                dec["wait"] = True
                continue
            if dec["action"] == "goto":                       # no input: switches in trial mode too
                if not dec.get("stable") and not dec.get("urgent"):
                    dec["exec"], dec["wait"] = _("確認中"), True
                    continue
                sc = self._script(dec["script"])
                if sc:
                    self._goto(n, sc, dec["goto"], now, _("規則「{rule_name}」:{reason}", rule_name=dec.get('rule_name'), reason=dec['reason']))
                dec["exec"] = _("已切換")
                continue
            if dec["action"] == "hold":
                dec["exec"] = _("暫停其他腳本中") if dec["mode"] == "live" and self.held.get(n) else (_("試跑(不暫停其他腳本)") if dec["mode"] != "live" else _("確認中"))
                dec["wait"] = dec["mode"] == "live" and not self.held.get(n)
                continue
            if self.held.get(n) and not dec.get("guard") and dec["mode"] == "live" and dec["action"] in automation.TAPPING | {"notify", "set_var"}:
                dec["exec"] = _("暫停中:守門規則「{p1}」", p1=self.held[n])
                dec["wait"] = True
                continue
            if dec["mode"] != "live":
                dec["exec"] = (_("試跑(不執行子腳本)") if dec["action"] == "call" else _("試跑(不點擊)")) if dec["action"] in automation.TAPPING else ""
                continue
            if dec["action"] not in automation.TAPPING and dec["action"] not in ("notify", "set_var"):
                dec["exec"] = ""
                continue
            key = (n, dec["script"], dec.get("rule"))
            if manual and manual["paused"] and dec["action"] != "notify":
                dec["exec"] = _("手動操作中,暫停(沒有操作 {resume_in} 秒後恢復)", resume_in=manual['resume_in'])
                dec["wait"] = True
                continue
            hold = self.hold_of(n)
            if hold and dec["action"] != "notify":
                dec["exec"] = (_("已停下來") if hold["mode"] == "stop" else _("暫停中")) + _("(只記錄,按「繼續」恢復)")
                dec["wait"] = True
                if dec.get("guard") and dec.get("stable"):
                    self._guard_held_news(n, dec, hold)
                continue
            wait = self.start_wait(n, now)
            if wait and dec["action"] != "notify":
                dec["exec"] = _("啟動確認中(還有 {wait} 秒)", wait=format(wait, '.0f')) if wait < 1e6 else _("啟動確認中(等畫面正常)")
                dec["wait"] = True
                continue
            if frame is None or st is None:
                dec["exec"] = _("沒有畫面,不執行")
                dec["wait"] = True
                continue
            if not dec.get("stable") and not dec.get("urgent") and not dec.get("on_enter"):
                dec["exec"], dec["wait"] = _("確認中"), True
                continue
            run = self.procs.get(n)
            if run and dec["action"] in automation.TAPPING and not self._may_take_over(n, run, dec, now):
                continue
            if key in self.blocked:
                dec["exec"] = _("已暫停:{p1}", p1=self.blocked[key])
                continue
            wait = (dec.get("cooldown") or 0) - (now - self.last_fire[key]) if key in self.last_fire else 0
            if wait > 0:
                dec["exec"] = _("冷卻中(還有 {wait} 秒)", wait=format(wait, '.0f'))
                continue
            if acted:
                dec["exec"] = _("這台這次已執行其他動作")
                dec["wait"] = True
                continue
            fh = self.fire_times[key]
            while fh and now - fh[0] > 3600:
                fh.popleft()
            if dec.get("max_per_hour") and len(fh) >= dec["max_per_hour"]:
                if not dec.get("_hour_alerted") and len(fh) == dec["max_per_hour"] and key not in self.blocked:
                    self.blocked[key] = _("一小時內已執行 {p1} 次(上限)", p1=len(fh))
                    self.alert(n, _("[{script_name}] 規則「{rule_name}」一小時內已執行 {p3} 次,已暫停", script_name=dec['script_name'], rule_name=dec.get('rule_name'), p3=len(fh)))
                dec["exec"] = _("已達每小時 {max_per_hour} 次上限", max_per_hour=dec['max_per_hour'])
                continue
            today = datetime.date.fromtimestamp(now).isoformat()
            fd = self.fire_days.get(key)
            if fd is None or fd[0] != today:
                fd = self.fire_days[key] = [today, 0]
            if dec.get("max_per_day") and fd[1] >= dec["max_per_day"]:
                dec["exec"] = _("今天已執行 {p1} 次(每天最多 {max_per_day} 次)", p1=fd[1], max_per_day=dec['max_per_day'])
                continue
            if dec["action"] not in ("notify", "set_var") and len(q) >= c["max_per_min"]:
                dec["exec"] = _("已達每分鐘 {max_per_min} 次上限", max_per_min=c['max_per_min'])
                dec["wait"] = True
                continue
            # no effect since last time = the same decision has held ever since this rule last fired
            cur = self.current.get((n, dec["script"])) or {}
            if dec.get("on_enter"):                           # once per entry; loops are caught by MAX_SWITCHES_PER_HOUR
                self.strikes[key] = 0
            elif key in self.last_fire and cur.get("since", now) <= self.last_fire[key]:
                self.strikes[key] += 1
            else:
                self.strikes[key] = 1
            if self.strikes[key] > c["max_strikes"]:
                self.blocked[key] = _("執行 {max_strikes} 次條件都沒有改變", max_strikes=c['max_strikes'])
                self.no_effect.add(key)
                self.alert(n, _("[{script_name}] 規則「{rule_name}」執行 {max_strikes} 次都沒有效果,已暫停(到「執行」頁解除)", script_name=dec['script_name'], rule_name=dec.get('rule_name'), max_strikes=c['max_strikes']))
                dec["exec"] = _("已暫停:{p1}", p1=self.blocked[key])
                continue
            if dec["action"] in ("tap", "long_press") and ("button" in (dec.get("target") or {}) or "setting" in (dec.get("target") or {})):
                p = self.resolve_point(n, dec["target"])
                if not p:
                    dec["exec"] = _("畫面上找不到按鈕,這次不點")
                    continue
                dec["tap"] = p
            self.last_fire[key] = now
            fh.append(now)
            fd[1] += 1
            if dec["action"] == "set_var":
                self.set_var(n, dec.get("var"), dec.get("var_mode"), values.resolve(dec.get("var_value"), self.ctx(n)), now)
                dec["exec"] = _("已設定變數")
                continue
            if dec["action"] == "notify":
                self.alert(n, f"[{dec['script_name']}] {values.render(dec['text'], self.ctx(n))}:{dec['reason']}", "info", kind="notify")
                dec["exec"] = _("已通知")
                continue
            if dec["action"] == "output":
                ctx = self.ctx(n)
                self.send_output(n, dec.get("output"), values.render(dec.get("command"), ctx),
                                 values.resolve(dec.get("var_value"), ctx), dec["script_name"])
                dec["exec"] = _("已送出")
                continue
            if dec["action"] == "call":
                try:
                    self.procs[n] = self._start_sub(n, dec, now)
                except RuntimeError as e:
                    self.alert(n, _("[{script_name}] 無法呼叫子腳本:{e}", script_name=dec['script_name'], e=e))
                    dec["exec"] = _("無法呼叫:{e}", e=e)
                    continue
            elif dec["action"] == "back":
                self.exec.submit(n, "back")
            else:
                x, y = dec["tap"]
                self.exec.submit(n, "long_press" if dec["action"] == "long_press" else "tap", x=x, y=y)
            q.append(now)
            acted = True
            dec["exec"], dec["done"] = _("已執行"), True
            self._executed(n, dec, st, frame)

    def _executed(self, n, dec, st, frame):
        """Audit trail: every real input with its reason and the frame it was based on."""
        t = self.clock()
        adir = os.path.join(self.dir, "actions", datetime.datetime.now().strftime("%Y%m%d"))
        os.makedirs(adir, exist_ok=True)
        img = f"{int(t * 1000)}_{n}.jpg"
        try:
            Image.fromarray(frame).resize((640, 360), Image.BILINEAR).save(os.path.join(adir, img), quality=80)
        except OSError:
            img = None
        self._append_log({"t": round(t, 3), "device": n, "executed": True, "image": img,
                          **{k: dec.get(k) for k in ("script", "script_name", "mode", "rule", "rule_name", "action",
                                                     "text", "reason", "tap", "sub", "args")},
                          "state": {k: v["value"] for k, v in (st or {}).items()}})
        self.counts["executed"] += 1
        self.incidents.note(n, t, "action", f"[{dec['script_name']}] {dec['text']}({dec.get('rule_name') or dec['reason']})", frame=frame,
                            urgent=bool(dec.get("urgent")))
        print(_("{p1} {n} > 執行 [{script_name}] {text}({reason})", p1=format(datetime.datetime.now(), '%H:%M:%S'), n=format(n, '14'), script_name=dec['script_name'], text=dec['text'], reason=dec['reason']), flush=True)

    def _start_sub(self, n, dec, now):
        """A rule (or a situation's entry) calls a sub-script on device n (the replay replaces this)."""
        return SubRun(n, dec["sub"], dec.get("args") or {}, self.subs, now,
                      origin={**{k: dec.get(k) for k in ("script", "script_name", "rule", "rule_name", "on_success", "on_fail")},
                              "situation": dec.get("situation")})

    # ---------- control of a device ----------
    def _may_take_over(self, n, run, dec, now):
        """A sub-script has control of device n. May this decision act? (It may interrupt the sub-script.)"""
        holder = run.origin
        name = run.info(self.names)["sub_name"]
        if run.result is not None:                        # already ending: its cleanup is running
            dec["exec"] = _("等待子腳本「{name}」收尾", name=name)
            dec["wait"] = True
            return False
        if holder.get("script") == dec["script"]:
            dec["exec"] = _("子腳本「{name}」執行中", name=name)
            dec["wait"] = True
            return False
        # a schedule, or a sub-script run once from the page: only urgent rules interrupt it
        held_prio = -1 if holder.get("schedule") or holder.get("manual") else self.prio.get(holder.get("script"), 1e9)
        higher = self.prio.get(dec["script"], 1e9) < held_prio
        if not (dec.get("urgent") or higher):
            dec["exec"] = _("控制權在「{script_name}」的子腳本「{name}」", script_name=holder.get('script_name'), name=name)
            dec["wait"] = True
            return False
        if dec.get("urgent") and n not in self.parked:
            # set it aside, paused, and carry on from the same step once the urgent rule is done (a disconnect while
            # a schedule goes through accounts must not end the schedule)
            run.pause(now)
            run.pause_why = _("緊急規則「{rule_name}」", rule_name=dec.get('rule_name'))
            self.parked[n] = run
            del self.procs[n]
            self.alert(n, _("[{script_name}] 緊急規則「{rule_name}」先處理:「{name}」暫停,處理完從同一步接著做", script_name=dec['script_name'], rule_name=dec.get('rule_name'), name=name), "info")
            if n in self.jobs and run.origin.get("schedule"):
                self.jobs[n].add(now, "pause", _("暫停:緊急規則「{rule_name}」", rule_name=dec.get('rule_name')), frame=self.cur_frames.get(n), force=True)
            return True
        why = _("緊急規則") if dec.get("urgent") else _("優先順序較高")
        run.abort(_("被「{script_name}」的規則「{rule_name}」打斷({why})", script_name=dec['script_name'], rule_name=dec.get('rule_name'), why=why), now, cleanup=True)
        self.alert(n, _("[{script_name}] {why}:打斷子腳本「{name}」", script_name=dec['script_name'], why=why, name=name))
        if not run.done:                                  # its cleanup runs first; this rule acts once it is gone
            dec["exec"] = _("已打斷「{name}」,等它收尾後執行", name=name)
            dec["wait"] = True
            return False
        del self.procs[n]
        self._run_ended(n, run)
        return True

    def _run_event(self, n, run, text, level):
        o = run.origin
        self._append_log({"t": round(self.clock(), 3), "device": n, "executed": True, "action": "sub_step",
                          "script": o.get("script"), "script_name": o.get("script_name"), "sub": run.sub_id,
                          "text": _("子腳本「{sub_name}」", sub_name=run.info(self.names)['sub_name']), "reason": text, "level": level})
        self.incidents.note(n, self.clock(), "sub", _("子腳本「{sub_name}」{text}", sub_name=run.info(self.names)['sub_name'], text=text))
        job = self.jobs.get(n) if o.get("schedule") else None
        if job:
            job.add(self.clock(), level if level != "ask" else "notify", text, frame=self.cur_frames.get(n),
                    force=level in ("warn", "notify", "ask"))
        if level == "notify":
            self.alert(n, f"[{run.info(self.names)['sub_name']}] {text}", "info", kind="notify")
        elif level == "ask":                          # the bots post the question with buttons; the others just say so
            self.alert(n, _("[{sub_name}] {text}。請到執行頁或操作面板回答", sub_name=run.info(self.names)['sub_name'], text=text), "info", kind="ask")
        else:
            print(_("{p1} {n} > 子腳本「{sub_name}」{text}", p1=format(datetime.datetime.now(), '%H:%M:%S'), n=format(n, '14'), sub_name=run.info(self.names)['sub_name'], text=text), flush=True)

    def step_goto(self, n, origin, target, why):
        """A "goto" step of a rule's steps: switch the main script that started the run (not the guard rules)."""
        sc = self._script((origin or {}).get("script"))
        if sc and not automation.is_guard(sc) and target in {x["id"] for x in sc["situations"]}:
            self._goto(n, sc, target, self.clock(), why)

    def _run_ended(self, n, run):
        self._run_ended_main(n, run)
        why = getattr(run, "stop_why", None)
        if why and not self.hold_of(n):                   # a "stop" step / a call that fails with on_fail stop
            o = run.origin or {}
            by = _("規則「{rule_name}」", rule_name=o['rule_name']) if o.get("rule_name") else (o.get("schedule_name") or _("子腳本「{sub_name}」", sub_name=run.info(self.names)['sub_name']))
            self._rule_stop(n, o.get("script"), None, by, why, self.clock())

    def _run_ended_main(self, n, run):
        name = run.info(self.names)["sub_name"]
        o = run.origin
        if o.get("schedule"):                             # a schedule: done for today, whatever the result
            now = self.clock()
            try:
                os.remove(self._schedule_job_path(n))
            except OSError:
                pass
            job = self.jobs.pop(n, None)
            if job:
                job.finish(now, run.result, run.message, self.cur_frames.get(n))
            plain = getattr(run, "plain", "") or run.message
            self.sched_state.mark(o["schedule"], n, now, run.result, run.message, job.id if job else None, plain=plain)
            r = {"success": _("完成"), "partial": _("部分完成:{plain}", plain=plain), "failed": _("失敗:{plain}", plain=plain),
                 "interrupted": _("中斷:{message}", message=run.message)}.get(run.result, run.result)
            self.alert(n, f"{o.get('schedule_name')}{r}", "info" if run.result == "success" else "warn")
            if run.result == "failed":
                self._stuck_snap(n, self.cur_frames.get(n), None, _("{schedule_name}失敗:{message}", schedule_name=o.get('schedule_name'), message=run.message))
            return
        if run.result == "success":
            self.alert(n, _("子腳本「{name}」完成", name=name), "info")
        elif run.result == "failed":
            self.alert(n, _("子腳本「{name}」失敗:{p2}", name=name, p2=getattr(run, 'plain', '') or run.message))
            self._stuck_snap(n, self.cur_frames.get(n), None, _("子腳本「{name}」失敗:{message}", name=name, message=run.message))
        else:
            self.alert(n, _("子腳本「{name}」中斷:{message}", name=name, message=run.message), "info")
        o = run.origin
        target = o.get("on_success") if run.result in ("success", "partial") else o.get("on_fail") if run.result == "failed" else None
        sc = self._script(o.get("script"))
        cur = self.situ.get((n, o.get("script")))
        if target and sc and cur and cur["id"] == o.get("situation"):   # only if the caller is still where it was
            self._goto(n, sc, target, self.clock(), _("子腳本「{name}」", name=name) + (_("完成") if run.result == "success" else _("失敗:{message}", message=run.message)))

    # ---------- situations ----------
    def _script(self, sid):
        return next((s for s in self.scripts if s["id"] == sid), None)

    def _situation(self, n, sc, now, st):
        """The device's current situation in this script (created on first sight; checked for its time limit)."""
        key = (n, sc["id"])
        cur = self.situ.get(key)
        ids = {x["id"] for x in sc["situations"]}
        if not cur or cur["id"] not in ids:               # first time, or the script was changed
            cur = self.situ[key] = {"id": sc["initial"], "since": now, "enter": False}
        sit = automation.situation(sc, cur["id"])
        if sit.get("max_seconds") and now - cur["since"] > float(sit["max_seconds"]) and not self.hold_of(n):
            self._goto(n, sc, sit.get("on_timeout") or sc["initial"], now, _("在「{name}」超過 {p2} 秒", name=sit['name'], p2=format(float(sit['max_seconds']), 'g')))
            cur = self.situ[key]
        return cur

    def _goto(self, n, sc, target, now, why):
        key = (n, sc["id"])
        if target == "stop":
            if not self.hold_of(n):
                self._rule_stop(n, sc["id"], None, _("腳本「{name}」", name=sc['name']), why, now)
            else:
                self._note_switch(n, sc, self.situ.get(key, {}).get("id"), "stop", why)
            return
        q = self.switches[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if not (automation.mode_for(sc, n) == "live" and not self.hold_of(n)):
            q.clear()      # nothing can act (trial, switch off): a situation that times out and comes back is no loop
        elif self._loop_counts(n, now):
            q.append(now)
        if len(q) > MAX_SWITCHES_PER_HOUR:
            q.clear()
            self._rule_stop(n, sc["id"], None, _("腳本「{name}」", name=sc['name']),
                            _("一小時內切換情境超過 {MAX_SWITCHES_PER_HOUR} 次,可能在兩個情境之間來回", MAX_SWITCHES_PER_HOUR=MAX_SWITCHES_PER_HOUR), now)
            return
        old = self.situ.get(key, {}).get("id")
        sit = automation.situation(sc, target)
        self.situ[key] = {"id": sit["id"], "since": now, "enter": bool(sit.get("on_enter"))}
        self.recent.pop(key, None)                        # decisions start over in the new situation
        self.current.pop(key, None)
        self.alert(n, _("[{name}] 情境「{p2}」→「{name2}」:{why}", name=sc['name'], p2=automation.situation(sc, old).get('name', old) if old else '—', name2=sit.get('name'), why=why), "info")
        self._note_switch(n, sc, old, sit["id"], why)

    def _loop_counts(self, n, now):
        """Does a situation switch now count towards the loop guard? (A replay leaves some out.)"""
        return True

    def _note_switch(self, n, sc, old, new, why):
        """A script changed situation (new = "stop": it stopped). Only replays write these down (runtime/replay.py)."""

    def _enter_decision(self, n, sc, mode, cur):
        """The entry action of the device's situation, as a decision (so it goes through the same checks as rules)."""
        sit = automation.situation(sc, cur["id"])
        a = automation.enter_action(sc, sit) or {"type": "none"}
        sub = self.subs.get(a.get("sub")) if a.get("type") == "call" else None
        text = a.get("text") or (_("呼叫子腳本「{name}」", name=(sub or {}).get('name', a.get('sub'))) if a.get("type") == "call"
                                 else _(automation.ACTIONS.get(a.get("type"), "")))
        return {"script": sc["id"], "script_name": sc["name"], "mode": mode, "action": a.get("type", "none"),
                "text": text, "reason": _("進入情境「{name}」", name=sit['name']), "rule": f"enter:{sit['id']}", "rule_name": _("進入時動作"),
                "tap": engine.tap_point(a) if a.get("type") in ("tap", "long_press") else None,
                "sub": a.get("sub"), "args": a.get("args"), "on_success": a.get("on_success"), "on_fail": a.get("on_fail"),
                "var": a.get("var"), "var_mode": a.get("mode"), "var_value": a.get("value"),
                "output": a.get("output"), "command": a.get("command"),
                "situation": sit["id"], "situation_name": sit["name"], "on_enter": True, "stable": True, "cooldown": 0,
                "guard": False, "since": cur["since"]}

    def _guard_hold(self, n, decisions, now):
        """A guard rule says "hold": the other scripts must not act on this device (only in live mode)."""
        g = next((d for d in decisions if d.get("guard") and d["action"] == "hold" and d["mode"] == "live"
                  and (d.get("stable") or d.get("urgent"))), None)
        was = self.held.get(n)
        self.held[n] = g.get("rule_name") if g else None
        if g and not was:
            self.alert(n, _("守門規則「{rule_name}」:暫停其他腳本({reason})", rule_name=g.get('rule_name'), reason=g['reason']), "info")
            run = self.procs.get(n)
            if run and run.result is None:
                run.abort(_("守門規則「{rule_name}」暫停其他腳本", rule_name=g.get('rule_name')), now, cleanup=True)
        elif was and not g:
            self.alert(n, _("守門規則「{was}」解除,其他腳本恢復", was=was), "info")

    def _watching(self):
        """Someone has the page open (the server touches live/_viewed on every live-frame request) and live view is on,
        or someone asked for one screen (a chat command touches live/_asked; the live-view switch only hides the page's)."""
        def recent(f):
            try:
                return time.time() - os.path.getmtime(os.path.join(self.fast, "live", f)) < LIVE_VIEW_IDLE
            except OSError:
                return False
        return recent("_asked") or (self.ctrl.get("live_view", True) and recent("_viewed"))

    def _live(self, name, frame):
        path = os.path.join(self.fast, "live", f"{name}.jpg")
        try:
            Image.fromarray(frame).resize((640, 360), Image.BILINEAR).save(path + ".tmp.jpg", quality=80)
            for attempt in range(5):
                try:
                    os.replace(path + ".tmp.jpg", path)
                    break
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))
        except OSError:
            pass

    def _urgent_watch(self, decisions):
        """The states an urgent decision's rule reads (the incident follows how they change)."""
        for d in decisions:
            if d.get("urgent") and d.get("rule") and "watch" not in d:
                sc = self._script(d["script"]) or {}
                r = next((x for x in automation.all_rules(sc) if x.get("id") == d["rule"]), None) if sc else None
                d["watch"] = sorted({c["state"] for g in (r or {}).get("when") or [] for c in g if c.get("state")})

    def _log(self, name, dec, st):
        self.counts[dec["action"]] += 1
        rec = {"t": round(self.clock(), 3), "device": name,
               **{k: dec.get(k) for k in ("script", "script_name", "mode", "rule", "rule_name", "action", "text", "reason", "tap",
                                          "sub", "args", "urgent")},
               "state": {k: v["value"] for k, v in (st or {}).items()}}
        day = datetime.datetime.now().strftime("%Y%m%d")
        with open(os.path.join(self.dir, "log", f"{day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(f"{datetime.datetime.now():%H:%M:%S} {name:14} [{dec['script_name']}] {dec['text']:8} {dec['reason']}", flush=True)

    # ---------- "judged wrong" -> save the frame as data ----------
    # ---------- schedules ----------
    def _schedule_requests(self, now):
        """From the page: run a schedule now on one emulator, or forget that it ran today."""
        d = os.path.join(self.fast, "schedule_requests")
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                req = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError):
                req = {}
            try:
                os.remove(p)
            except OSError:
                pass
            s = next((x for x in schedules.effective(self.data_root, self.fast) if x["id"] == req.get("id")), None)
            if not s:
                continue
            if req.get("action") == "reset":
                self.sched_state.reset(s["id"], req.get("device"))
                self.alert(req.get("device") or "", _("排程「{name}」今天的紀錄已重置,時間內會再執行", name=s['name']), "info")
            elif req.get("action") == "run_now" and req.get("device"):
                self.sched_force[req["device"]] = s

    def _schedule_tick(self, n, st, now, manual, frame):
        """Start a due schedule on device n (or the one asked for from the page); watch the one running there."""
        if n in self.parked:                              # a run is set aside for an urgent rule: it comes back first
            return
        run = self.procs.get(n)
        items = schedules.effective(self.data_root, self.fast)
        self.sched_state.day_start = schedules.day_start(self.data_root)
        if run and run.origin.get("schedule"):
            s = next((x for x in items if x["id"] == run.origin["schedule"]), {})
            if run.result is None and run.paused_at is None and now - run.started - run.paused_total > float(s.get("max_minutes", 240)) * 60:
                run.abort(_("超過最長執行時間 {max_minutes} 分鐘", max_minutes=s.get('max_minutes', 240)), now, cleanup=True)
            if n in self.jobs:
                self.jobs[n].tick(now, frame)
            return
        if not run and self._schedule_restore(n, items, now, frame):
            return
        forced = self.sched_force.pop(n, None)
        due = schedules.due(items, n, now, self.sched_state)
        s = forced or (due[0] if due else None)
        for x in due:
            self.sched_wait[(x["id"], n)] = _("排隊中") if x is not s else None
        if not s:
            return
        hold = self.hold_of(n)
        wait = self.start_wait(n, now)
        why = ((_("這台已停下來") if hold["mode"] == "stop" else _("這台暫停中")) + _("(按「繼續」恢復)") if hold
               else _("啟動確認中") if wait else _("這台沒有畫面") if st is None
               else _("等這台的子腳本做完") if run else _("手動操作中") if manual and manual.get("paused") else None)
        self.sched_wait[(s["id"], n)] = why
        if why:
            if forced:
                self.alert(n, _("立即執行排程「{name}」沒有開始:{why}", name=s['name'], why=why))
            return
        args = schedules.args_for(s, n)
        try:
            new = SubRun(n, s["sub"], args, self.subs, now,
                         origin={"script": f"schedule:{s['id']}", "script_name": _("排程「{name}」", name=s['name']), "rule_name": _("排程"),
                                 "schedule": s["id"], "schedule_name": _("排程「{name}」", name=s['name']), "schedule_plain": s["name"], "pause_others": s.get("pause_others", True),
                                 "by_hand": bool(forced)})                  # started by hand: the master switch is not needed
        except RuntimeError as e:
            self.sched_state.mark(s["id"], n, now, "failed", str(e))
            self.alert(n, _("排程「{name}」沒有開始:{e}", name=s['name'], e=e))
            return
        self.procs[n] = new
        self.jobs[n] = JobLog(os.path.join(self.dir, "schedules"), s, n, s["sub"], args, now, frame)
        self.sched_wait.pop((s["id"], n), None)
        self.alert(n, _("排程「{name}」開始(立即執行)", name=s["name"]) if forced else _("排程「{name}」開始", name=s["name"]), "info")
        self._append_log({"t": round(now, 3), "device": n, "executed": True, "action": "call", "script_name": _("排程「{name}」", name=s['name']),
                          "text": _("呼叫子腳本「{name}」", name=(self.subs.get(s['sub']) or {}).get('name', s['sub'])), "reason": _("排程時間到") if not forced else _("立即執行"),
                          "sub": s["sub"], "args": args})

    def _schedule_job_path(self, n):
        return os.path.join(self.fast, "schedule_jobs", f"{n}.json")

    def _schedule_save(self, n, run, now):
        """Keep where the schedule is, so it can carry on after the runtime restarts."""
        snap = run.snapshot(now)
        if snap is None:
            return
        snap.update(t=round(now, 3), job=self.jobs[n].id if n in self.jobs else None)
        _write_json(self._schedule_job_path(n), snap)

    def _schedule_restore(self, n, items, now, frame):
        """A schedule was running here when the runtime stopped: carry on from the same step. -> True if restored."""
        p = self._schedule_job_path(n)
        if not os.path.exists(p):
            return False
        try:
            snap = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            snap = None
        sid = ((snap or {}).get("origin") or {}).get("schedule")
        s = next((x for x in items if x["id"] == sid), None)
        if not snap or not s or self.sched_state.done(sid, n, now):
            os.remove(p)
            return False
        try:
            run = SubRun.restore(n, snap, self.subs, now)
        except (RuntimeError, KeyError, IndexError, TypeError) as e:
            os.remove(p)
            self.sched_state.mark(sid, n, now, "failed", _("重新啟動後接不上:{e}", e=e), snap.get("job"))
            self.alert(n, _("排程「{name}」重新啟動後接不上,停止:{e}", name=s['name'], e=e))
            return True
        self.procs[n] = run
        job = JobLog.reopen(os.path.join(self.dir, "schedules"), snap.get("job"), now, frame)
        self.jobs[n] = job or JobLog(os.path.join(self.dir, "schedules"), s, n, s["sub"], schedules.args_for(s, n), now, frame)
        self.alert(n, _("排程「{name}」從中斷的地方繼續({p2})", name=s['name'], p2=run.info(self.names)['now'] or ''), "info")
        return True

    def _schedule_pause(self, n, run, now, why):
        """暫停, or someone touches the device (a schedule): the run pauses where it is, and carries on (from the
        same step) once that is over."""
        if why and run.paused_at is None and run.result is None:
            run.pause(now)
            run.pause_why = why
            more = _("沒有操作一段時間後") if why == _("手動操作") else _("按「繼續」後")
            what = run.origin.get("schedule_name") or _("「{x}」", x=run.info(self.names)["sub_name"])
            self.alert(n, _("{what}暫停:{why},{more}會從同一步繼續", what=what, why=why, more=more), "info")
            if n in self.jobs:
                self.jobs[n].add(now, "pause", _("暫停:{why}", why=why), frame=self.cur_frames.get(n), force=True)
        elif not why and run.paused_at is not None:
            d = now - run.paused_at
            run.resume(now)
            run.pause_why = None
            what = run.origin.get("schedule_name") or _("「{x}」", x=run.info(self.names)["sub_name"])
            self.alert(n, _("{what}繼續(暫停了 {d} 秒)", what=what, d=format(d, '.0f')), "info")
            if n in self.jobs:
                self.jobs[n].add(now, "resume", _("繼續(暫停了 {d} 秒)", d=format(d, '.0f')), frame=self.cur_frames.get(n), force=True)

    def _schedule_status(self, names):
        now = self.clock()
        self.sched_state.day_start = schedules.day_start(self.data_root)
        out = []
        for s in schedules.effective(self.data_root, self.fast):
            devs = {}
            for n in s.get("devices") or []:
                run = self.procs.get(n) or self.parked.get(n)
                running = bool(run and run.origin.get("schedule") == s["id"])
                code, text = schedules.describe(s, n, now, self.sched_state, running)
                if code == "due" and self.sched_wait.get((s["id"], n)):
                    text = _("等待開始:{p1}", p1=self.sched_wait[(s['id'], n)])
                if running and run.paused_at is not None:
                    text = _("暫停中({why})", why=getattr(run, "pause_why", None) or _("手動操作"))
                elif running:                             # how far: "執行中 · 「名單」第 5/9 個(1 個失敗略過)"
                    loops = [_("「{p1}」第 {p2}/{p3} 個", p1=lbl, p2=i, p3=n) for lbl, i, n in run.loops()]
                    if loops:
                        text = _("執行中 · {p1}", p1=" › ".join(loops)) + (_("({p1} 個失敗略過)", p1=len(run.skipped)) if run.skipped else "")
                done = self.sched_state.done(s["id"], n, now) or {}
                devs[n] = {"code": code, "text": text, "online": n in names,
                           "detail": done.get("message") if done.get("result") in ("failed", "partial") and not running else None,
                           "run": self.jobs[n].id if running and n in self.jobs else (self.sched_state.done(s["id"], n, now) or {}).get("run")}
            out.append({"id": s["id"], "devices": devs})
        return out

    # ---------- actions asked for from the page (the monitor / the operation panel) ----------
    # ---------- 停下來 / 暫停 / 繼續 (one device, or "*" = all): nothing acts until 繼續, the guard rules neither ----------
    def _migrate_switch(self):
        """Before 停下來 / 暫停 / 繼續 there was a master switch and an emergency stop: what they said becomes a hold
        (switched off or an emergency -> all stopped; on -> running), once."""
        p = os.path.join(self.fast, "control.json")
        try:
            c = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not any(k in c for k in ("armed", "guards_armed", "emergency", "armed_only")):
            return
        on = (c.get("armed") or c.get("guards_armed")) and not c.get("emergency")
        if not on:
            h = self._load_hold()
            h["*"] = {"mode": "stop", "by": _("改版前的總開關是關的"), "t": time.time()}
            self.device_hold = h
            self._save_hold()
        for k in ("armed", "guards_armed", "emergency", "armed_only", "panel_before"):
            c.pop(k, None)
        _write_json(p, c)

    def hold_of(self, n):
        """This device's hold ({"mode": stop | pause, "by", "t"}) - its own, else all's - or None (it may act)."""
        h = self.device_hold.get(n)
        if h is not None and not isinstance(h, dict):
            h = None
        if h is None:
            h = self.device_hold.get("*")
        if h and h.get("mode", "stop") in ("stop", "pause"):
            return {"mode": "stop", **h} if "mode" not in h else h
        return None

    def start_wait(self, n, now):
        """Seconds still to wait before this device may act after the runner started or it came back (0 = may act;
        1e9 = it has no healthy picture yet)."""
        need = float(self.ctrl.get("start_wait_s", 5) or 0)
        since = self.ready_since.get(n)
        if since is None:
            return 1e9 if need else 0
        return max(0.0, need - (now - since))

    def _guard_held_news(self, n, dec, hold):
        """A guard rule would act on a stopped / paused device: say so once per rule (until it stops holding)."""
        told = self.__dict__.setdefault("_held_told", {})
        key = (n, dec.get("rule"))
        if time.time() - told.get(key, 0) < 600:
            return
        told[key] = time.time()
        v = {"rule": dec.get("rule_name"), "reason": dec.get("reason", "")[:60], "text": dec.get("text")}
        self.alert(n, _("守門規則「{rule}」成立({reason}),但這台已停下來,沒有執行「{text}」", **v) if hold["mode"] == "stop"
                   else _("守門規則「{rule}」成立({reason}),但這台暫停中,沒有執行「{text}」", **v))

    def _rule_stop(self, n, script, rule, by, why, now):
        """A rule / a script stops this device: the same 停下來 as from the page (kept in device_hold.json, ended by
        繼續), saying which rule and why. Stopped again the same way soon after a 繼續: the cause is still there."""
        cause = {"script": script, "rule": rule}
        last = self.resumed_dev.get(n)
        again = round(now - last[0]) if last and now - last[0] < 180 and last[1] == cause else None
        run = self.procs.pop(n, None)
        if n in self.parked:
            self.parked.pop(n).abort(_("{by}停下來", by=by), now, cleanup=False)
        if run and run.result is None:
            run.abort(_("{by}停下來", by=by), now, cleanup=False)
        self._set_hold(n, "stop", by, now, why=why, cause=cause, again=again)
        sc = self._script(script)
        if sc:                                                    # replays / script tests count it as a stop
            self._note_switch(n, sc, self.situ.get((n, script), {}).get("id"), "stop", why)
        self.alert(n, _("[{by}] 停下來:{why}", by=by, why=why) + (_(",中斷子腳本「{sub_name}」", sub_name=run.info(self.names)['sub_name']) if run else "")
                   + (_("(按「繼續」後 {again} 秒又停下來:原因還在)", again=again) if again is not None else ""))

    def _release_rules(self, n):
        """繼續 starts afresh: the rules paused on this device (all devices when n is None) may act again."""
        for key in [k for k in self.blocked if n is None or k[0] == n]:
            self.blocked.pop(key, None)
            self.no_effect.discard(key)
            self.strikes.pop(key, None)

    def _cause_now(self, n, decisions):
        """Is what stopped this device still so? True / False, or None (it cannot be told: stopped by hand or by a
        script's situation)."""
        h = self.hold_of(n) or {}
        c = h.get("cause")
        if not c or not c.get("rule"):
            return None
        d = next((x for x in decisions if x["script"] == c["script"] and x.get("rule") == c["rule"]), None)
        return bool(d and d["action"] == "stop")

    def _set_hold(self, n, mode, by, now, **extra):
        """mode stop | pause | run for one device (n) or all ("*"); extra (why, cause, again) is kept with it.
        run (繼續): a device that was stopped starts over (_start_over), one that was paused carries on (_carry_on)."""
        before = {}
        if mode == "run":
            known = set(self.caps) | {k[0] for k in self.situ} | {k for k in self.device_hold if k != "*"}
            before = {d: self.hold_of(d) for d in (known if n == "*" else {n})}
        self._set_hold_only(n, mode, by, now, **extra)
        for d, h in before.items():
            if h and not self.hold_of(d):
                # 繼續 also ends a manual-operation pause: whoever pressed it is done operating the device
                self.manual_done[d] = time.time()
                self.manual_since.pop(d, None)
                if h.get("mode", "stop") == "stop":
                    self._start_over(d)
                else:
                    self._carry_on(d, h)

    def _start_over(self, n):
        """After 停下來: the device's scripts begin again - every situation back to its start, conditions counted from
        now ("for N seconds", became / count), the start check again; nothing of before the stop carries over."""
        for key in [k for k in self.situ if k[0] == n]:
            del self.situ[key]
        for d in (self.recent, self.current, self.switches, self.wait_since):
            for key in [k for k in d if k[0] == n]:
                d.pop(key, None)
        for key in [k for k in self.tracker.since if k.startswith(f"{n}:")]:
            del self.tracker.since[key]
        for key in [k for k in self.timeline if k[0] == n]:
            self.timeline[key].clear()
        self.held.pop(n, None)
        self.ready_since.pop(n, None)
        self.alert(n, _("繼續:從頭開始(情境回到起點、條件重新計算)"), "info")

    def _carry_on(self, n, h, now=None):
        """After 暫停: carry on where it was; the time it was paused does not count toward a situation's time limit."""
        now = time.time() if now is None else now
        dt = max(0.0, now - float(h.get("t") or now))
        for (d, _sid), v in self.situ.items():
            if d == n:
                v["since"] = v.get("since", 0) + dt

    def _set_hold_only(self, n, mode, by, now, **extra):
        if n == "*":
            if mode == "run":
                self.device_hold = {}
            else:
                self.device_hold = {k: v for k, v in self.device_hold.items() if k == "*" or (v or {}).get("mode") != "run"}
                self.device_hold["*"] = {"mode": mode, "by": by, "t": time.time()}
        elif mode == "run":
            if self.device_hold.get("*"):
                self.device_hold[n] = {"mode": "run", "by": by, "t": time.time()}    # all stay stopped, this one runs
            else:
                self.device_hold.pop(n, None)
        else:
            self.device_hold[n] = {"mode": mode, "by": by, "t": time.time(), **{k: v for k, v in extra.items() if v is not None}}
        self._save_hold()
        for d in ([*self.procs, *self.parked] if n == "*" else [n]):
            if mode == "stop":
                for runs in (self.parked, self.procs):
                    r = runs.get(d)
                    if r is not None and r.result is None:
                        r.abort(_("從{by}停下來", by=by), now, cleanup=runs is self.procs)
                        if runs is self.parked:
                            runs.pop(d, None)

    def _load_hold(self):
        try:
            with open(os.path.join(self.fast, "device_hold.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_hold(self):
        p = os.path.join(self.fast, "device_hold.json")
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.device_hold, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    def _act_requests(self, now):
        """act_requests/*.json -> each device's queue. {"device", "kind": "schedule" | "sub" | "situation" | "stop" |
        "resume", "if_busy": "interrupt" | "queue", "by", ...}. Done on that device's turn of this tick (_act_tick)."""
        for p in sorted(glob.glob(os.path.join(self.fast, "act_requests", "*.json"))):
            try:
                req = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError):
                req = None
            try:
                os.remove(p)
            except OSError:
                pass
            if req and req.get("device") and time.time() - req.get("t", 0) < 120:   # older: left from before a restart
                if req["device"] == "*" and req.get("kind") in ("stop", "pause", "resume"):   # all: at once
                    by = req.get("by") or _("網頁")
                    mode = "run" if req["kind"] == "resume" else "pause" if req["kind"] == "pause" or req.get("mode") == "pause" else "stop"
                    if mode == "run":
                        for d, h in list(self.device_hold.items()):
                            if d != "*" and (h or {}).get("cause"):
                                self.resumed_dev[d] = (now, h["cause"])
                        self._release_rules(None)
                    self._set_hold("*", mode, by, now)
                    self.page_hold.clear()
                    self.alert("", f"[{by}] " + {"stop": _("全部停下來:正在做的事已取消,腳本和情境都停住(守門規則也是),按「繼續」從頭開始"),
                                                 "pause": _("全部暫停:正在做的事停在原地,按「繼續」從同一步接著做"),
                                                 "run": _("全部繼續")}[mode], "warn" if mode != "run" else "info")
                    continue
                req["asked"] = now
                self.act_queue[req["device"]].append(req)

    def _act_what(self, req):
        k = req.get("kind")
        if k == "schedule":
            s = next((x for x in schedules.effective(self.data_root, self.fast) if x["id"] == req.get("id")), None)
            return _("立即執行排程「{p1}」", p1=s['name'] if s else req.get('id'))
        if k == "sub":
            return _("執行子腳本「{name}」", name=(self.subs.get(req.get('sub')) or {}).get('name', req.get('sub')))
        if k == "situation":
            sc = self._script(req.get("script")) or {}
            sit = next((x for x in sc.get("situations") or [] if x["id"] == req.get("situation")), {})
            return _("「{name}」切到情境「{name2}」", name=sc.get('name', req.get('script')), name2=sit.get('name', req.get('situation')))
        if k == "stop" and req.get("mode") == "abort":
            return _("結束目前的動作")
        return {"stop": _("停下來"), "pause": _("暫停"), "resume": _("繼續")}.get("pause" if req.get("mode") == "pause" else k, k)

    def _act_done(self, n, req, now, text, ok=True):
        by = req.get("by") or _("網頁")
        self.alert(n, f"[{by}] {self._act_what(req)}:{text}", "info" if ok else "warn")
        self._append_log({"t": round(now, 3), "device": n, "executed": ok, "action": "page_act", "script_name": by,
                          "text": self._act_what(req), "reason": text, "act": {k: v for k, v in req.items() if k != "args"}})

    def _act_tick(self, n, st, now, manual):
        """Carry out this device's page actions (at most the first few that can go now; the others keep waiting)."""
        q = self.act_queue.get(n)
        while q:
            req = q[0]
            k = req.get("kind")
            run = self.procs.get(n)
            if now - req["asked"] > 1800:                  # waited half an hour for the device: give up
                q.pop(0)
                self._act_done(n, req, now, _("等了 30 分鐘這台都沒空,取消"), ok=False)
                continue
            if k in ("stop", "resume", "pause"):
                q.pop(0)
                by = req.get("by") or _("網頁")
                mode = "pause" if k == "pause" or req.get("mode") == "pause" else "stop"
                if k == "resume":
                    was = self.hold_of(n)
                    if was and was.get("cause"):
                        self.resumed_dev[n] = (now, was["cause"])
                    self._release_rules(n)
                    self.page_hold.pop(n, None)
                    self._set_hold(n, "run", by, now)
                    self._act_done(n, req, now, _("繼續") + (_("(從同一步接著做)") if was and was["mode"] == "pause" else "") if was
                                   else _("沒有停下來或暫停"), ok=bool(was))
                elif req.get("mode") in ("hold", "stop", "pause") or k == "pause":   # 停下來 / 暫停 the device
                    self._set_hold(n, mode, by, now)
                    self.page_hold.pop(n, None)
                    self._act_done(n, req, now, _("已停下來:正在做的事已取消,腳本和情境都停住(守門規則也是),按「繼續」從頭開始") if mode == "stop"
                                   else _("已暫停:正在做的事停在原地,按「繼續」從同一步接著做"))
                elif not run or run.result is not None:
                    self._act_done(n, req, now, _("這台目前沒有在執行動作"), ok=False)
                elif req.get("mode") == "pause" and run.origin.get("schedule"):
                    self.page_hold[n] = req.get("by") or _("網頁")
                    self._act_done(n, req, now, _("{schedule_name}暫停,按「繼續」會從同一步接著做", schedule_name=run.origin.get('schedule_name')))
                else:
                    run.abort(_("從{p1}停止", p1=req.get('by') or _("網頁")), now, cleanup=True)
                    self.page_hold.pop(n, None)
                    self._act_done(n, req, now, _("已停止「{sub_name}」", sub_name=run.info(self.names)['sub_name']))
                continue
            hold = self.hold_of(n)
            why = ((_("這台已停下來") if hold["mode"] == "stop" else _("這台暫停中")) + _(",先按「繼續」") if hold
                   else _("這台沒有畫面") if st is None else None)
            if why:
                q.pop(0)
                self._act_done(n, req, now, _("沒有開始:{why}", why=why), ok=False)
                continue
            if run and not run.done:                      # busy (or still cleaning up after a stop)
                if req.get("if_busy") == "interrupt" and run.result is None:
                    run.abort(_("改做:{p1}", p1=self._act_what(req)), now, cleanup=True)
                    self.page_hold.pop(n, None)
                    self.alert(n, _("中斷「{sub_name}」,改做{p2}", sub_name=run.info(self.names)['sub_name'], p2=self._act_what(req)), "info")
                if not req.get("_waiting"):
                    req["_waiting"] = True
                    if req.get("if_busy") != "interrupt":
                        self.alert(n, _("[{p1}] {p2}:排在目前的動作後面", p1=req.get('by') or _("網頁"), p2=self._act_what(req)), "info")
                return                                    # the device is busy (or still cleaning up): next tick
            if run is not None:
                return                                    # the old run ended: it is wrapped up first, start next tick
            q.pop(0)
            if k == "schedule":
                s = next((x for x in schedules.effective(self.data_root, self.fast) if x["id"] == req.get("id")), None)
                if not s or n not in (s.get("devices") or []):
                    self._act_done(n, req, now, _("這台不在這個排程裡"), ok=False)
                    continue
                self.sched_force[n] = s
                self._act_done(n, req, now, _("開始"))
            elif k == "sub":
                sub = self.subs.get(req.get("sub"))
                try:
                    if not sub:
                        raise RuntimeError(_("找不到這個子腳本"))
                    self.procs[n] = SubRun(n, req["sub"], req.get("args") or {}, self.subs, now,
                                           origin={"script": None, "script_name": _("手動執行({p1})", p1=req.get('by') or _("網頁")),
                                                   "rule_name": _("從網頁執行一次"), "manual": True})
                except RuntimeError as e:
                    self._act_done(n, req, now, _("沒有開始:{e}", e=e), ok=False)
                    continue
                self._act_done(n, req, now, _("開始"))
            elif k == "situation":
                sc = self._script(req.get("script"))
                if not sc or not any(x["id"] == req.get("situation") for x in sc.get("situations") or []):
                    self._act_done(n, req, now, _("找不到這個腳本或情境"), ok=False)
                    continue
                if automation.mode_for(sc, n) == "off":
                    self._act_done(n, req, now, _("這個腳本沒有部署在這台"), ok=False)
                    continue
                self._goto(n, sc, req["situation"], now, _("從{p1}切換", p1=req.get('by') or _("網頁")))
                sit = automation.situation(sc, req["situation"])
                enter = sit.get("on_enter") or {}
                self._act_done(n, req, now, _("已切換") + (_(",會做這個情境的進入動作") if enter else ""))
            else:
                self._act_done(n, req, now, _("不支援的操作"), ok=False)
            return                                        # one start per tick: let it take the device first

    def _sub_if_requested(self, n, st, now):
        """The page asks to run one sub-script once on this device (to test it). Real input: the device must not be
        stopped or paused, and nothing else may have control of it."""
        req_path = os.path.join(self.fast, "sub_requests", f"{n}.json")
        if not os.path.exists(req_path):
            return
        try:
            req = json.load(open(req_path, encoding="utf-8"))
        except (OSError, ValueError):
            req = {}
        try:
            os.remove(req_path)
        except OSError:
            pass
        sub = self.subs.get(req.get("sub"))
        hold = self.hold_of(n)
        why = (_("找不到這個子腳本") if not sub else ((_("這台已停下來") if hold["mode"] == "stop" else _("這台暫停中")) + _(",先按「繼續」"))
               if hold else _("這台沒有畫面") if st is None else _("這台正在執行別的子腳本") if n in self.procs else None)
        if why:
            self.alert(n, _("手動執行子腳本「{name}」沒有開始:{why}", name=(sub or {}).get('name', req.get('sub')), why=why))
            return
        try:
            self.procs[n] = SubRun(n, req["sub"], req.get("args") or {}, self.subs, now,
                                   origin={"script": None, "script_name": _("手動執行"), "rule_name": _("從網頁執行一次"), "manual": True})
        except RuntimeError as e:
            self.alert(n, _("手動執行子腳本「{name}」沒有開始:{e}", name=sub['name'], e=e))
            return
        self.alert(n, _("手動執行子腳本「{name}」開始", name=sub['name']), "info")
        self._append_log({"t": round(now, 3), "device": n, "executed": True, "action": "call", "script_name": _("手動執行"),
                          "text": _("呼叫子腳本「{name}」", name=sub['name']), "reason": _("從網頁執行一次"), "sub": req["sub"], "args": req.get("args")})

    def _snap_if_requested(self, name, frame):
        """The page asks for this device's frame in full size (to pick a button on it)."""
        req = os.path.join(self.fast, "snap_requests", f"{name}.json")
        if frame is None or not os.path.exists(req):
            return
        try:
            os.remove(req)
        except OSError:
            pass
        out = os.path.join(self.fast, "snaps", f"{name}.png")
        Image.fromarray(frame).save(out + ".tmp.png", compress_level=1)
        os.replace(out + ".tmp.png", out)

    def _flag_if_requested(self, name, frame, st, dec):
        req_path = os.path.join(self.fast, "flag_requests", f"{name}.json")
        if not os.path.exists(req_path):
            return
        try:
            req = json.load(open(req_path, encoding="utf-8"))
        except (OSError, ValueError):
            req = {}
        try:
            os.remove(req_path)
        except OSError:
            pass
        if frame is None:
            return
        rel, session, sid, pred, conf = self._save_frame(name, frame, st, "shadow_flag")
        with open(os.path.join(self.dir, "flags.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "device": name, "frame": rel, "session": session, "id": sid,
                                "pred": pred, "conf": conf, "decisions": dec, "note": req.get("note", "")},
                               ensure_ascii=False, default=str) + "\n")
        print(_("{p1} {name} 已標記「判斷錯了」,畫面存成 {rel}", p1=format(datetime.datetime.now(), '%H:%M:%S'), name=format(name, '14'), rel=rel), flush=True)

    # ---------- stuck: keep the screen, so the case can be seen and the scripts taught it ----------
    def _stuck_check(self, n, frame, st, decisions, now):
        """A live main script that keeps waiting (or cannot tell) for STUCK_WAIT: keep its screen, once per episode.
        Not while the device is stopped / paused, or a sub-script / schedule has it (that is not the script waiting)."""
        busy = self.hold_of(n) or self.procs.get(n)
        for d in decisions:
            key = (n, d["script"])
            if busy or d.get("guard") or d.get("mode") != "live" or d["action"] not in ("wait", "uncertain"):
                self.wait_since.pop(key, None)
                continue
            sig = (d["action"], d.get("rule"))
            since, was = self.wait_since.get(key, (now, sig))
            if was != sig:
                since = now
            self.wait_since[key] = (since, sig)
            if now - since >= STUCK_WAIT and (key, since) not in self.stuck_told:
                self.stuck_told.add((key, since))
                self._stuck_snap(n, frame, st, _("「{script_name}」{text}已經 {p3} 分鐘:{reason}", script_name=d.get('script_name'), text=d.get('text'), p3=int((now - since) // 60), reason=d.get('reason', '')))

    def _stuck_snap(self, n, frame, st, why):
        """Keep the screen of a device that got stuck (shadow/stuck.jsonl; 執行 › 紀錄 › 卡住時的畫面)."""
        if frame is None:
            return
        try:
            rel, session, sid, pred, conf = self._save_frame(n, frame, st, "stuck")
        except Exception as e:
            print(_("{p1} {n} 卡住的畫面沒有存下:{e}", p1=format(datetime.datetime.now(), '%H:%M:%S'), n=format(n, '14'), e=e), flush=True)
            return
        run = self.procs.get(n)
        with open(os.path.join(self.dir, "stuck.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "device": n, "frame": rel, "why": why, "pred": pred,
                                "situations": {sid_: v["id"] for (dn, sid_), v in self.situ.items() if dn == n},
                                "proc": run.info(self.names) if run else None}, ensure_ascii=False, default=str) + "\n")
        print(_("{p1} {n} 卡住了,畫面存成 {rel}:{why}", p1=format(datetime.datetime.now(), '%H:%M:%S'), n=format(n, '14'), rel=rel, why=why), flush=True)

    def _save_frame(self, name, frame, st, trigger):
        """Save a live frame in full as a sample of the session shadow_<date> (so it can be labelled, answered and
        trained on like any recording). -> (relative frame path, session, id, predicted values, confidences)"""
        now = time.time()
        session = f"shadow_{datetime.datetime.now():%Y%m%d}"
        ddir = os.path.join(project.work_of(self.data_root), "sessions", session, "devices", name)
        os.makedirs(os.path.join(ddir, "frames"), exist_ok=True)
        sid = str(int(now * 1000))
        Image.fromarray(frame).save(os.path.join(ddir, "frames", sid + ".png"), compress_level=3)
        pred = {k: v["value"] for k, v in (st or {}).items()}
        conf = {k: v["conf"] for k, v in (st or {}).items() if "conf" in v}
        with open(os.path.join(ddir, "samples.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": sid, "session": session, "device": name, "trigger": trigger,
                                "t_req": round(now, 3), "t_done": round(now, 3), "frame": f"frames/{sid}.png",
                                "capture": "window", "shadow_pred": pred}, ensure_ascii=False) + "\n")
        sp = os.path.join(project.work_of(self.data_root), "sessions", session, "session.json")
        meta = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {"session": session, "started": now, "devices": {}}
        meta["ended"] = now
        meta["devices"].setdefault(name, {"samples": 0, "touches": 0, "events": 0})["samples"] += 1
        _write_json(sp, meta)
        return f"sessions/{session}/devices/{name}/frames/{sid}.png", session, sid, pred, conf

    # ---------- the model is unsure -> save the frame as a question ----------
    def _rule_values(self, n, frame, st, ctx):
        """state id -> (the screen rule's answer, rule name) for the states the model answers that also have a rule and
        where the model is below arbiter.MODEL_SURE (above it the model is believed anyway)."""
        out = {}
        sure = arbiter.MODEL_SURE
        for cs in self.check_states:                      # rules made on the state page
            m = st.get(cs["id"])
            if m and m.get("conf") is not None and m["conf"] >= sure:
                continue
            v, _x = generic.evaluate(cs, frame, self.check_tpls.get(cs["id"]), ctx)
            if v is not None:
                out[cs["id"]] = (v, cs["source"]["rule"])
        rule_ids = {s["id"] for s in self.rule_states}
        provided = auto_rules.provided_ids() - self.model_only - rule_ids   # rules a plugin of the project provides
        if any(st.get(k) and (st[k].get("conf") is None or st[k]["conf"] < sure) for k in provided):
            b = auto_rules.label_frame(frame, generic=False)
            for k in provided:
                v, m = auto_rules.live_answer(k, b), st.get(k)
                if v is not None and m and (m.get("conf") is None or m["conf"] < sure):
                    out[k] = (v, self.rule_names.get(k, "rule"))
        return out

    def _maybe_save(self, n, frame, st, now, rule_vals=None):
        if not self.ctrl.get("auto_save") or not st:
            return
        reasons = []
        for sid, v in st.items():
            if v.get("source") == "model" and v.get("conf") is not None and v["conf"] < CONF_LOW:
                reasons.append({"state": sid, "kind": "low_conf", "value": v["value"], "conf": v["conf"]})
        # model and rule disagree: exactly the frames whose answer tells which of the two to believe next time
        for sid, (rv, _rule) in (rule_vals or {}).items():
            mv = st.get(sid)
            if mv and mv.get("value") is not None and rv != mv["value"] and not any(r["state"] == sid for r in reasons):
                reasons.append({"state": sid, "kind": "disagree", "value": mv["value"], "conf": mv.get("conf"), "rule": rv})
        if not reasons or now - self.last_save.get(n, 0) < SAVE_GAP:
            return
        for q in [self.saved_times, *self.saved_by.values()]:
            while q and now - q[0] > 3600:
                q.popleft()
        if len(self.saved_times) >= self.ctrl.get("auto_save_per_hour", 20):
            return
        reasons = [r for r in reasons if len(self.saved_by[(n, r["state"])]) < SAVE_STATE_PER_HOUR]
        # one state (all devices) takes at most STATE_SHARE of the hourly budget: a state that keeps disagreeing (a
        # flashing one) must not use every place, the others' questions are saved too
        cap = max(1, int(self.ctrl.get("auto_save_per_hour", 20) * STATE_SHARE))
        reasons = [r for r in reasons if sum(len(q) for (d, sid), q in self.saved_by.items() if sid == r["state"]) < cap]
        if not reasons:
            return
        rel, session, sid, pred, conf = self._save_frame(n, frame, st, "auto_uncertain")
        self.last_save[n] = now
        self.saved_times.append(now)
        for r in reasons:
            self.saved_by[(n, r["state"])].append(now)
        with open(os.path.join(self.dir, "uncertain.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(now, 3), "device": n, "frame": rel, "session": session, "id": sid,
                                "reasons": reasons, "pred": pred, "conf": conf}, ensure_ascii=False, default=str) + "\n")
        print(_("{p1} {n} 拿不準,存下畫面:", p1=format(datetime.datetime.now(), '%H:%M:%S'), n=format(n, '14')) + _("、").join(
            _("{name}({p2})", name=self.names.get(r['state'], {}).get('name', r['state']), p2=_("信心低") if r['kind'] == 'low_conf' else _("和參考圖不同"))
            for r in reasons), flush=True)

    # ---------- main loop ----------
    def run(self):
        stop = os.path.join(self.fast, "stop")
        if os.path.exists(stop):
            os.remove(stop)
        print(_("腳本執行開始:模型 {ckpt}({backend}),每 {interval} 秒看一次。試跑的腳本只記錄;正式執行的腳本在每台畫面正常 {start_wait_s} 秒後開始動作(停下來 / 暫停的除外)。", ckpt=self.ckpt or "-", backend=self.pred.backend, interval=self.interval, start_wait_s=self.ctrl.get('start_wait_s', 5)), flush=True)
        names, last_scan = self.devices(), time.time()
        print(f"{word("device")}:" + _("、").join(names), flush=True)
        from drivers import sources as sources_mod
        src_file = sources_mod._path()
        src_m = os.path.getmtime(src_file) if os.path.exists(src_file) else 0
        ticks = 0
        try:
            while not os.path.exists(stop):
                t0 = time.time()
                m = os.path.getmtime(src_file) if os.path.exists(src_file) else 0
                if t0 - last_scan > 10 or m != src_m:       # the 來源 page changed something: at once
                    names, last_scan, src_m = self.devices(), t0, m
                devs, t_model = self.tick(names)
                ticks += 1
                _write_json(os.path.join(self.fast, "status.json"), {
                    "running": True, "pid": os.getpid(), "started": self.started, "updated": time.time(),
                    "model": self.ckpt, "model_backend": self.pred.backend, "interval": self.interval, "ticks": ticks,
                    "tick_ms": round((time.time() - t0) * 1000), "model_ms": round(t_model * 1000),
                    "decisions": dict(self.counts), "devices": devs, "control": self.ctrl, "hold_all": self.device_hold.get("*"),
                    "saved_last_hour": len(self.saved_times),
                    "vars": {"defs": self.var_defs, "global": self.vars["global"],
                             "device": {k: v for k, v in self.vars["device"].items() if k in names}},
                    "alerts": list(self.alerts), "incidents_open": self.incidents.status(), "schedules": self._schedule_status(names),
                    "blocked": [{"device": k[0], "script": k[1], "rule": k[2], "reason": v} for k, v in self.blocked.items()]})
                time.sleep(max(0.0, self.interval - (time.time() - t0)))
        finally:
            self.incidents.close_all(time.time())
            self.quality.close(time.time())
            for n, run in list(self.procs.items()) + [(k, v) for k, v in self.parked.items() if k not in self.procs]:
                # a schedule (also one set aside for an urgent rule) carries on after the next start
                if run.origin.get("schedule") and not run.done:
                    now = time.time()
                    self._schedule_save(n, run, now)
                    if n in self.jobs:
                        self.jobs[n].add(now, "stop", _("腳本執行停止了:下次啟動會從這裡繼續"), frame=self.cur_frames.get(n), force=True)
                        self.jobs[n].save(now)
            try:
                st = json.load(open(os.path.join(self.fast, "status.json"), encoding="utf-8"))
            except (OSError, ValueError):
                st = {}
            st.update({"running": False, "updated": time.time()})
            for rec in self.touch.values():
                rec.close()
            _write_json(os.path.join(self.fast, "status.json"), st)
            print(_("腳本執行已停止"), flush=True)


def _rule_score(value, scores):
    """The number shown next to a rule-judged state: similarity of the chosen class (reference images),
    or the colour ratio."""
    if "ratio" in scores:
        return scores["ratio"]
    sc = scores.get("scores") or {}
    if value is not None and str(value) in sc:
        return sc[str(value)]
    return max(sc.values()) if sc else None


def latest_model(data_root):
    """The newest finished training run's model (model.onnx, or model_best.pt)."""
    run = judge.latest_run(data_root)
    return judge.model_file(run) if run else None           # None: no model yet, screen rules only
