"""Replay: run the scripts over a recorded stretch of one emulator, to see what they would have done.

It is the real watch loop (runtime/shadow.py: model, screen rules, situations, guard rules, cooldowns, limits) fed
with recorded frames, using each frame's recording time as the clock. Nothing reaches an emulator: taps are only
written down, and a called sub-script is not run (the recording would not react to its taps anyway) - its result
is assumed (sub_result: success / fail), which drives the situation it would switch to.
Every script that is not "off" for that emulator is treated as live, with the master switch on.

  python -m runtime.replay --input <replay input json>     (written by the web server)
  input:  {"id", "session", "device", "start": seconds from the start of the recording, "minutes",
           "script": an unsaved script that replaces the saved one with the same id (optional),
           "sub_result": "success" | "fail", "sub_results": {sub id: "success" | "fail"} (per sub-script, optional)}
  output: <runtime dir>/replays/<id>.json  {"ticks": [...], "summary": {...}}
Every tick keeps what happened as data too (events: kind input / call / switch / stop / alert / info with the script,
rule, sub-script, situation ids), so script tests (automation/tests.py) can check it."""
import argparse
import collections
import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np
from PIL import Image

import automation

from . import shadow as S
from i18n import _
import project

MAX_FRAMES = 5000


class _Cap:
    def __init__(self):
        self.frame = None

    def grab(self):
        return (self.frame, "replay", (self.frame.shape[1], self.frame.shape[0])) if self.frame is not None else None


class _NoInput:
    """Stands in for the executor: a replay must never touch a device. Inputs are only written down
    (by Replay._executed); this returns an already finished command."""

    def submit(self, *a, **k):
        f = concurrent.futures.Future()
        f.set_result(True)
        return f


class _AssumedRun:
    """A sub-script call during a replay: not run, ends at once with the assumed result."""

    def __init__(self, device, sub_id, lib, origin, result, now):
        self.device, self.sub_id, self.origin, self.started = device, sub_id, origin, now
        self.name = (lib.get(sub_id) or {}).get("name", sub_id)
        self.result, self.message, self.done = None, "", False
        # a rule's own steps (automation.inline_subs): their switches / stop still happen, at the end
        self.steps = (lib.get(sub_id) or {}).get("steps") if (lib.get(sub_id) or {}).get("inline") else None
        self.stop_why, self.gotos = None, []
        self._assume = result
        self.paused_at, self.paused_total, self.pause_why, self.skipped = None, 0.0, None, []   # as automation.runner.SubRun

    def pause(self, now):
        self.paused_at = now

    def resume(self, now):
        self.paused_at = None

    def snapshot(self, now):
        return None

    def info(self, names):
        return {"sub": self.sub_id, "sub_name": self.name, "chain": [{"sub": self.name, "step": 1, "steps": 1}],
                "now": _("(重播:不執行,假設結果)"), "retry": None, "cleaning": False, "started": self.started,
                "script": self.origin.get("script"), "script_name": self.origin.get("script_name"),
                "rule_name": self.origin.get("rule_name"), "result": self.result, "message": self.message}

    def advance(self, *a, **k):
        self.result = self._assume
        self.message = _("重播假設成功") if self._assume == "success" else _("重播假設失敗")
        self.done = True
        for st in self.steps or []:                       # the top-level control steps, as far as they get
            t = st.get("type")
            if t == "call" and self._assume != "success":
                if st.get("on_fail") == "stop":
                    self.stop_why = _("(重播假設)子腳本失敗,停下這台")
                if st.get("on_fail") != "continue":
                    break
            elif t == "goto":
                self.gotos.append(st.get("situation"))
            elif t == "stop":
                self.stop_why = st.get("text") or _("腳本要求停下來")
                break

    def abort(self, reason, now, cleanup=True):
        self.result, self.message, self.done = "interrupted", reason, True


ASSUMED_GRACE = 60.0      # seconds after an assumed sub-script in which situation switches are not a loop


class Replay(S.Shadow):
    def __init__(self, data_root, ckpt, device, draft=None, sub_result="success", sub_results=None):
        self.tmp = tempfile.mkdtemp(prefix="replay_")
        super().__init__(data_root, ckpt, 1.0, fast_dir=self.tmp)
        self.dir = os.path.join(self.tmp, "shadow")                  # logs of the replay stay in the temp dir
        os.makedirs(os.path.join(self.dir, "log"), exist_ok=True)
        self.exec = _NoInput()
        self.device, self.draft, self.sub_result = device, draft, sub_result
        self.sub_results = sub_results or {}
        self.now = 0.0
        self.clock = lambda: self.now
        self.events = []                                             # (t, kind, text, data) since the last tick
        with open(os.path.join(self.tmp, "control.json"), "w", encoding="utf-8") as f:
            json.dump({"auto_save": False, "manual_pause_s": 0, "max_per_min": 60, "max_strikes": 10, "start_wait_s": 0}, f)
        self.vars = {"day": None, "global": {}, "device": {}}         # start from the initial values
        self.caps = {device: _Cap()}
        self.assumed_end = {}                                         # device -> when its last assumed sub-script ended

    def reload(self):
        first = self.script_sig is None
        super().reload()
        if not first:
            return
        if self.draft:                                               # the script being edited, unsaved
            d = automation.normalize(self.draft)
            self.scripts = [d if s["id"] == d["id"] else s for s in self.scripts]
            if not any(s["id"] == d["id"] for s in self.scripts):
                self.scripts.append(d)
            self.prio = {s["id"]: i for i, s in enumerate(self.scripts)}
        for s in self.scripts:                                       # not off -> live
            if automation.mode_for(s, self.device) != "off":
                s["devices"] = {"*": "live"}

    def _start_sub(self, n, dec, now):
        self.events.append((now, "call", _("呼叫子腳本「{name}」({script_name})", name=(self.subs.get(dec['sub']) or {}).get('name', dec['sub']), script_name=dec['script_name']),
                            {"sub": dec["sub"], "script": dec.get("script"), "rule": dec.get("rule")}))
        return _AssumedRun(n, dec["sub"], self.subs, {**{k: dec.get(k) for k in ("script", "script_name", "rule", "rule_name",
                                                                                 "on_success", "on_fail")},
                                                      "situation": dec.get("situation")},
                           self.sub_results.get(dec["sub"], self.sub_result), now)

    def _executed(self, n, dec, st, frame):
        self.events.append((self.now, "input", f"{dec['text']}({dec['script_name']} · {dec.get('rule_name') or ''})",
                            {"script": dec.get("script"), "rule": dec.get("rule"), "action": dec.get("action")}))
        self.incidents.note(n, self.now, "action", f"[{dec['script_name']}] {dec['text']}({dec.get('rule_name') or dec['reason']})", frame=frame)

    def alert(self, device, text, level="warn", kind=None):
        self.events.append((self.now, "alert" if level == "warn" else "info", text, {}))
        if device:
            self.incidents.note(device, self.now, "alert", text, level=level)

    def send_output(self, n, out_id, command, value, by=""):
        """A replay never sends anything: written down only."""
        self.events.append((self.now, "output", _("送到輸出「{out_id}」:{p2}({by})", out_id=out_id, p2=command or '', by=by),
                            {"output": out_id, "command": command, "value": value}))
        f = concurrent.futures.Future()
        f.set_result(True)
        return f

    def _run_ended(self, n, run):
        self.assumed_end[n] = self.now
        for g in getattr(run, "gotos", None) or []:
            self.step_goto(n, run.origin, g, _("規則「{p1}」", p1=run.origin.get('rule_name') or ''))
        return super()._run_ended(n, run)

    def _loop_counts(self, n, now):
        """A sub-script is assumed to have worked, but the recorded frames do not change with it (still where it was
        before it "moved"): the switches that follow are the replay's, not the script's. They do not count towards
        the loop guard for ASSUMED_GRACE seconds after an assumed sub-script ended."""
        t = self.assumed_end.get(n)
        return t is None or now - t > ASSUMED_GRACE

    def _stuck_snap(self, n, frame, st, why):                     # a replay keeps no screens
        self.events.append((self.now, "info", _("(卡住:{why})", why=why), None))

    def _note_switch(self, n, sc, old, new, why):
        if new == "stop":
            self.events.append((self.now, "stop", _("[{name}] 停止腳本:{why}", name=sc['name'], why=why), {"script": sc["id"]}))
        else:
            self.events.append((self.now, "switch", "", {"script": sc["id"], "from": old, "to": new}))

    def _live(self, name, frame):
        pass

    def _schedule_tick(self, *a, **k):                               # schedules run on the real clock only
        pass

    def _schedule_requests(self, now):
        pass

    def _save_vars(self):
        pass

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _frames(data_root, session, device, start, minutes):
    from server import data                                          # same reading as the web pages
    items = sorted(data.samples(session, device), key=lambda s: s.get("t_done") or s["t_req"])
    if not items:
        return []
    t0 = items[0].get("t_done") or items[0]["t_req"]
    lo, hi = t0 + start, t0 + start + minutes * 60
    ddir = data.device_dir(session, device)
    out = []
    for s in items:
        t = s.get("t_done") or s["t_req"]
        if lo <= t <= hi:
            path = os.path.join(ddir, s.get("frame") or f"frames/{s['id']}.png")
            if os.path.exists(path):
                out.append((t, path))
    return out[:MAX_FRAMES]


def replay(data_root, inp, model=None, progress=True):
    """Run the scripts over a recorded stretch -> the result dict (see the module docstring)."""
    frames = _frames(data_root, inp["session"], inp["device"], float(inp.get("start", 0)), float(inp.get("minutes", 30)))
    if progress:
        print(_("重播 {session} / {device}:{p3} 張畫面", session=inp['session'], device=inp['device'], p3=len(frames)), flush=True)
    if not frames:
        raise RuntimeError(_("這段時間沒有錄到畫面"))
    r = Replay(data_root, model or S.latest_model(data_root), inp["device"], inp.get("script"), inp.get("sub_result", "success"),
               inp.get("sub_results"))
    ticks, counts = [], collections.Counter()
    pool = concurrent.futures.ThreadPoolExecutor(1)                  # read the next frame while this one is judged

    def load(p):
        im = Image.open(p).convert("RGB")
        return np.asarray(im if im.size == __import__("project").screen() else im.resize(__import__("project").screen()))
    nxt = pool.submit(load, frames[0][1])
    try:
        for i, (t, path) in enumerate(frames):
            img = nxt.result()
            if i + 1 < len(frames):
                nxt = pool.submit(load, frames[i + 1][1])
            r.now, r.caps[r.device].frame, r.events = t, img, []
            devs, _x = r.tick([r.device])
            d = devs[0]
            for e in r.events:
                counts[e[1]] += 1
            ticks.append({
                "t": round(t, 3), "frame": project.rel_of(path, data_root),
                "state": {k: [v.get("value"), round(v["conf"], 2) if v.get("conf") is not None else None, v.get("source")]
                          for k, v in (d["state"] or {}).items()},
                "situations": {k: v["name"] for k, v in (d.get("situations") or {}).items()},
                "situation_ids": {k: v["id"] for k, v in (d.get("situations") or {}).items()},
                "held": d.get("held"),
                "decisions": [{k: x.get(k) for k in ("script", "script_name", "situation_name", "action", "text", "reason",
                                                     "exec", "rule", "rule_name", "guard", "on_enter")} for x in d["decisions"]],
                "events": [{"t": round(et, 3), "kind": k, "text": tx, **(data or {})} for et, k, tx, data in r.events if k not in ("switch", "stop")],
                "data": [{"t": round(et, 3), "kind": k, **(data or {})} for et, k, tx, data in r.events if data],
            })
            if progress and (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(frames)}", flush=True)
    finally:
        pool.shutdown(wait=False)
        r.close()
    summary = {"frames": len(frames), "from": frames[0][0], "to": frames[-1][0], "inputs": counts["input"],
               "calls": counts["call"], "alerts": counts["alert"], "infos": counts["info"], "switches": counts["switch"]}
    return {"id": inp.get("id"), "session": inp["session"], "device": inp["device"], "start": float(inp.get("start", 0)),
            "minutes": float(inp.get("minutes", 30)), "sub_result": inp.get("sub_result", "success"),
            "sub_results": inp.get("sub_results") or {}, "draft": bool(inp.get("script")), "created": time.time(),
            "summary": summary, "ticks": ticks}


def run(data_root, runtime_dir, inp):
    out_dir = os.path.join(runtime_dir, "replays")
    os.makedirs(out_dir, exist_ok=True)
    res = replay(data_root, inp)
    path = os.path.join(out_dir, f"{inp['id']}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, default=str)
    os.replace(path + ".tmp", path)
    print(_("完成:{summary}", summary=res['summary']), flush=True)


def main():
    ap = argparse.ArgumentParser(prog="python -m runtime.replay")
    ap.add_argument("--input", required=True)
    ap.add_argument("--data", default=__import__("project").data_root())
    ap.add_argument("--fast-dir", default=__import__("project").runtime_dir())
    a = ap.parse_args()
    with open(a.input, encoding="utf-8") as f:
        inp = json.load(f)
    try:
        run(a.data, a.fast_dir, inp)
    except RuntimeError as e:
        print(_("重播失敗:{e}", e=e), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
