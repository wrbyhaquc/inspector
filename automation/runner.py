"""Running a sub-script on one device, a little every watch-loop tick: nothing here ever waits.

A "wait 2 s" or "wait until the map is open" only leaves a bookmark; every tick advance() looks at it, does what is
due (at most one input per tick) and returns right away, so one device's long sub-script never holds up the others.

The bookmark is a stack of frames: the sub-script being run (call), and inside it the blocks being run (an if's
branch, a retry, a repeat). A failure unwinds the stack to the nearest retry that has attempts left (that block
starts again) or to a call with on_fail = continue; otherwise the whole run fails. Every sub-script that ends by
failing or by being interrupted runs its cleanup steps first (innermost first)."""
import json
import re

from . import engine
from . import values as V
from .subs import MAX_DEPTH, cond_text, describe_step
from i18n import _

UNSURE_WAIT = 5        # seconds an "if" may wait for the model to become sure before failing


def if_branch(st, steps):
    """Which branch of an if step a step list is: "then", "elif:<k>" or "else"; of an ask step: "opt:<k>"."""
    for k, o in enumerate(st.get("options") or []):
        if steps is o.get("then"):
            return f"opt:{k}"
    if steps is st.get("else"):
        return "else"
    for k, e in enumerate(st.get("elif") or []):
        if steps is e.get("then"):
            return f"elif:{k}"
    return "then"


def branch_steps(st, branch):
    if branch.startswith("opt:"):
        k = int(branch[4:])
        return (st.get("options") or [])[k].get("then") if k < len(st.get("options") or []) else None
    if branch.startswith("elif:"):
        e = (st.get("elif") or [])[int(branch[5:])] if int(branch[5:]) < len(st.get("elif") or []) else {}
        return e.get("then")
    return st.get(branch)


def _around(msg, **values):
    """msg in this language cut at its values: _around("等到 {p1}(最多 {p2} 秒", p1=0, p2=1) -> the text before
    {p1}, between {p1} and {p2}, ... - to read back a reason the runtime wrote in any language."""
    marks = {k: chr(1 + v) for k, v in values.items()}
    return re.split("[-	]", _(msg, **marks))


def _quoted(text):
    """The quoted names in a text, whatever quotes this language uses."""
    return [a or b or c or d for a, b, c, d in re.findall(r"「([^」]+)」|“([^”]+)”|‘([^’]+)’|\"([^\"]+)\"", text or "")]


def plain_fail(st, reason, cond=None):
    """A failure in plain words when the design gives none: what was expected and did not happen, without the
    settings (time limits, matching) a designer reads in the technical reason. cond: the condition waited for, when
    the caller knows it (else it is read back from the reason)."""
    r = reason or ""
    wait = _around("等到 {p1}(最多 {p2} 秒", p1=0, p2=1)
    tap = _around("畫面上找不到{p1}的目標", p1=0)
    pick = _around("在清單中找到並點擊{label} {p2}(停穩 {p3} 秒才點,最多滑 {p4} 次)", label=0, p2=1, p3=2, p4=3)
    timeout = _around("{p1}:逾時", p1=0)[-1]
    t = (st or {}).get("type")
    if not t:                                             # no step at hand (a record kept before): tell by the wording
        t = "wait_until" if r.startswith(wait[0]) and wait[1].strip() in r else             "tap" if r.startswith(tap[0]) and tap[-1].strip() in r else             "pick" if r.startswith(pick[0]) and pick[1].strip() in r else None
    names = _quoted(r)
    if (t == "wait_until" or cond is not None) and timeout.strip() and r.endswith(timeout.strip()):
        if cond is None and r.startswith(wait[0]) and wait[1].strip():
            cond = r[len(wait[0]):].split(wait[1].strip())[0]
        cond = (cond or "").strip()
        return _("等了很久,一直沒等到「{cond}」", cond=cond) if cond else _("等了很久,畫面一直沒有變成要的樣子")
    if t in ("tap", "long_press") and (tap[-1].strip() or tap[0].strip()) in r:
        return _("畫面上找不到「{p1}」", p1=names[-1]) if names else _("畫面上找不到要點的地方")
    if t == "pick":
        return _("清單裡找不到「{p1}」", p1=names[-1]) if names else _("清單裡找不到要選的項目")
    if t == "capture_list":
        return _("清單沒有掃描完")
    if t == "ask":
        return _("問的問題沒有人回答")
    if t == "repeat_until":
        return _("試了好幾次都沒有成功")
    if _around("動作送不出去:{e}", e=0)[0].strip() in r:
        return _("點擊沒有送出去(來源可能斷線)")
    return reason or _("失敗")


class _Frame:
    def __init__(self, kind, steps, now, **kw):
        self.kind, self.steps, self.i, self.t0, self.step_t0 = kind, steps or [], 0, now, now
        self.sub = kw.get("sub")              # call: the sub-script
        self.args = kw.get("args") or {}      # call: resolved parameter values
        self.on_fail = kw.get("on_fail", "fail")
        self.fail_goto = kw.get("fail_goto")    # call: on failure (on_fail continue) switch the main script here
        self.times = int(kw.get("times", 1))  # retry
        self.attempt = 1
        self.delay = float(kw.get("delay", 0))
        self.delay_until = None
        self.when = kw.get("when")            # repeat
        self.max_times = int(kw.get("max_times", 10))
        self.max_seconds = float(kw.get("max_seconds", 600))
        self.count = 0
        self.items = kw.get("items") or []    # for_each
        self.var = kw.get("var")
        self.idx = 0
        self.on_item_fail = kw.get("on_item_fail", "fail")


class SubRun:
    """One sub-script running on one device (with whatever it calls). origin = the rule that started it."""
    setting_lookup = None                     # (device, setting id) -> value; set by the runtime (automation/settings.py)

    def __init__(self, device, sub_id, args, lib, now, origin=None):
        self.device, self.lib, self.origin = device, lib, origin or {}
        self.sub_id = sub_id
        self.started = now
        self.stack = []
        self.pending = None                   # Future of the action of the current input step
        self.tracker = engine.Tracker()
        self.cleanup, self.ci, self.c_t0 = [], 0, now     # [(frame, step)] being run
        self.done, self.result, self.message = False, None, ""
        self.plain = ""                          # the failure in plain words, for the people running it (plain_fail)
        self.stop_why = None                     # a "stop" step (or a call with on_fail stop): the runtime stops the device
        self.unsure_since = None
        self.skipped = []                     # items a for_each gave up on (on_item_fail = continue): not a full success
        self.paused_at, self.paused_total = None, 0.0       # paused (the person took over for a while)
        self._state, self._env, self._ctx = {}, None, {}
        self._push_call(sub_id, args or {}, now, "fail", caller_args={})

    # ---------- frames ----------
    def _calls(self):
        return [f for f in self.stack if f.kind == "call"]

    def _args(self):
        """The parameters the current step sees: its sub-script's, plus the items of the for_each blocks around it."""
        out, loops = {}, []
        for f in reversed(self.stack):
            if f.kind == "each":
                loops.append(f)
            elif f.kind == "call":
                out = dict(f.args)
                break
        for f in reversed(loops):
            if f.idx < len(f.items):
                out[f.var] = f.items[f.idx]
                out[f"{f.var}_no"] = f.idx + 1
        return out

    def _push_call(self, sub_id, args, now, on_fail, caller_args, fail_goto=None):
        sub = self.lib.get(sub_id)
        if not sub:
            raise RuntimeError(_("找不到子腳本「{sub_id}」", sub_id=sub_id))
        if len(self._calls()) >= MAX_DEPTH + 1:
            raise RuntimeError(_("呼叫層數超過 {MAX_DEPTH} 層", MAX_DEPTH=MAX_DEPTH))
        resolved = {}
        for p in sub.get("params") or []:
            v = args.get(p["name"], p.get("default"))
            if isinstance(v, dict) and "param" in v:          # passing the caller's own parameter along
                v = caller_args.get(v["param"])
            elif isinstance(v, dict) and set(v) == {"var"}:      # a variable's value when it is called
                v = ((self._ctx or {}).get("vars") or {}).get(v["var"])
            elif isinstance(v, dict) and set(v) == {"setting"}:  # a user setting: its value for this device, now
                if SubRun.setting_lookup is None:
                    raise RuntimeError(_("讀不到使用者設定「{setting}」", setting=v['setting']))
                sid = v["setting"]
                v = SubRun.setting_lookup(self.device, sid)
                if v is None:
                    raise RuntimeError(_("使用者設定「{sid}」不存在或還沒有值", sid=sid))
            resolved[p["name"]] = v
        self.stack.append(_Frame("call", sub.get("steps"), now, sub=sub, args=resolved, on_fail=on_fail, fail_goto=fail_goto))

    def _venv(self, args=None):
        """What value fields see (automation/values.py): this step's parameters, the variables, the user settings."""
        lookup = SubRun.setting_lookup
        return {"params": self._args() if args is None else args, "vars": (self._ctx or {}).get("vars") or {},
                "setting": (lambda sid: lookup(self.device, sid)) if lookup else None, "states": self._state or {}}

    def _params(self):
        """Parameter definitions the current step sees (for describing it): its sub-script's and the loop items."""
        out = []
        for f in self.stack:
            if f.kind == "call":
                out = list(f.sub.get("params") or [])
            elif f.kind == "each":
                out += [{"name": f.var, "label": getattr(f, "var_label", f.var), "type": "point"},
                        {"name": f"{f.var}_no", "label": _("{p1}是第幾個", p1=getattr(f, 'var_label', f.var)), "type": "number"}]
        return out

    def _point(self, p, args):
        p = p or {}
        if "param" in p:
            p = args.get(p["param"]) or {}
        if set(p) == {"setting"}:                             # a user setting: this device's choice, now
            p = (SubRun.setting_lookup(self.device, p["setting"]) if SubRun.setting_lookup else None) or {}
            if not isinstance(p, dict):
                return None
        if "button" in p and self._env is not None:           # a find button: where it is in the frame now
            return self._env.resolve_point(self.device, p)
        return engine.tap_point({"target": p})

    def _next(self, f, now):
        f.i += 1
        f.step_t0 = now
        self.unsure_since = None

    def _cond(self, f, when, now):
        args = self._args()
        when = [[{**c, "target": args.get(c["target"]["param"]) or {}} if isinstance(c.get("target"), dict) and "param" in c["target"] else c
                 for c in g] for g in when or []]
        ctx = {**(self._ctx or {}), **{k: v for k, v in self._venv(args).items() if k != "vars"}}
        res = [engine._group(g, self._state, self.tracker, f"{id(f)}:{f.i}:{gi}", now, ctx) for gi, g in enumerate(when or [])]
        return engine.MATCH if engine.MATCH in res else engine.UNSURE if engine.UNSURE in res else engine.NO

    def _unsure_text(self, when, names):
        """Which states could not be told, and how sure the model was: "無法確定「閘門」是什麼(模型信心 0.62,需要 0.70)"."""
        from .conds import DEFAULT_MIN_CONF
        out = []
        for g in when or []:
            for c in g:
                sid = c.get("state")
                if not sid:
                    continue
                v = self._state.get(sid) or {}
                need = float(c.get("min_conf", DEFAULT_MIN_CONF))
                conf = v.get("conf")
                if v.get("value") is None or conf is None or conf < need:
                    label = (names.get(sid) or {}).get("name", sid)
                    got = _("看不到這個狀態") if not v else _("判斷是「{p1}」,但信心只有 {p2}", p1=(names.get(sid) or {}).get('classes', {}).get(json.dumps(v.get('value')), v.get('value')) if v.get('value') is not None else "?", p2=format(conf or 0, '.2f'))
                    out.append(_("無法確定「{label}」({got},需要 {need})", label=label, got=got, need=format(need, '.2f')))
        return _(";").join(dict.fromkeys(out)) or _("條件一直沒辦法確定(模型沒把握)")

    # ---------- public ----------
    def info(self, names):
        f = self.stack[-1] if self.stack else None
        chain = [{"sub": c.sub["name"], "step": c.i + 1, "steps": len(c.steps)} for c in self._calls()]
        retry = next((x for x in reversed(self.stack) if x.kind == "retry"), None)
        now_text = ""
        if self.cleanup and self.ci < len(self.cleanup):
            fr, st = self.cleanup[self.ci]
            now_text = _("收尾:{p1}", p1=describe_step(st, names, self.lib, fr.sub.get('params')))
        elif f and f.i < len(f.steps):
            now_text = self._live_text(f, names)
        return {"sub": self.sub_id, "sub_name": (self.lib.get(self.sub_id) or {}).get("name", self.sub_id),
                "chain": chain, "now": now_text, "retry": _("第 {attempt}/{times} 次", attempt=retry.attempt, times=retry.times) if retry else None,
                "loop": " › ".join(f"{lbl} {i}/{n}" for lbl, i, n in self.loops()) or None,
                "cleaning": bool(self.cleanup) and self.ci < len(self.cleanup), "started": self.started,
                "paused": self.paused_at is not None,
                "script": self.origin.get("script"), "script_name": self.origin.get("script_name"), "schedule_name": self.origin.get("schedule_plain"),
                "rule_name": self.origin.get("rule_name"), "result": self.result, "message": self.message,
                "progress": self._progress(),
                "say": next((x.steps[x.i].get("say") for x in reversed(self.stack) if x.i < len(x.steps) and x.steps[x.i].get("say")), None)
                or next((x.sub.get("say") for x in reversed(self.stack) if x.kind == "call" and x.sub.get("say")), None),
                "plain": self.plain}

    def _progress(self):
        """For the pages: how far the run is - its outermost for_each ({"label", "i", "n"}), how long the current wait
        has left ({"wait_left", "wait_total"} s), and about how long until it is over ("eta" s: the items done so far
        took this long each; None when it cannot be told yet)."""
        now = self.paused_at if self.paused_at is not None else getattr(self, "_now", None)
        if now is None:
            return None
        out = {}
        f = next((x for x in self.stack if x.kind == "each" and x.items), None)
        if f:
            out.update(label=getattr(f, "label", f.var), i=f.idx + 1, n=len(f.items))
        top = self.stack[-1] if self.stack else None
        wait = None
        if top and top.i < len(top.steps) and top.steps[top.i].get("type") == "wait":
            secs = V.number(top.steps[top.i].get("seconds", 1), self._venv(), None)
            if secs:
                wait = (float(secs), max(0.0, float(secs) - (now - top.step_t0)))
                out.update(wait_total=round(wait[0]), wait_left=round(wait[1]))
        if f:
            item_t0 = getattr(f, "item_t0", None) or f.t0
            if f.idx > 0 and item_t0 > f.t0:
                per = (item_t0 - f.t0) / f.idx               # what one item took so far
                out["eta"] = round(max(0.0, per * (len(f.items) - f.idx) - (now - item_t0)))
            elif wait:                                      # the first item: its wait is most of it
                out["eta"] = round(wait[1] + max(wait[0], now - item_t0) * (len(f.items) - 1))
        return out or None

    def _live_text(self, f, names):
        """The current step for the page, with the real numbers: a wait shows how long (its parameter's value, not
        the parameter's name) and how long is left."""
        st = f.steps[f.i]
        if st.get("type") != "wait":
            return describe_step(st, names, self.lib, self._params())
        secs = V.number(st.get("seconds", 1), self._venv(), None)
        if secs is None:
            return describe_step(st, names, self.lib, self._params())
        now = self.paused_at if self.paused_at is not None else getattr(self, "_now", f.step_t0)
        left = max(0, round(secs - (now - f.step_t0)))
        span = lambda x: f"{x // 3600}:{x // 60 % 60:02d}:{x % 60:02d}" if x >= 3600 else f"{x // 60}:{x % 60:02d}"
        total = _("{p1} 分鐘", p1=format(secs / 60, 'g')) if secs >= 60 and secs % 60 == 0 else _("{secs} 秒", secs=format(secs, 'g'))
        src = ""
        if V.is_ref(st.get("seconds")):
            labels = {p["name"]: re.sub(r"[（(].*?[)）]", "", p.get("label") or p["name"]).strip() for p in self._params()}
            src = f"({V.describe(st['seconds'], labels)})"
        return _("等待 {total}{src} · 還剩 {p3}", total=total, src=src, p3=span(int(left)))

    # ---------- saving / carrying on after the runtime restarted ----------
    def snapshot(self, now):
        """Where this run is (JSON): every frame's position, timers relative to now. None while it is ending."""
        if self.done or self.cleanup or self.result is not None:
            return None
        frames = []
        for k, f in enumerate(self.stack):
            d = {"kind": f.kind, "i": f.i, "t0": f.t0 - now, "step_t0": f.step_t0 - now, "attempt": f.attempt,
                 "count": f.count, "idx": f.idx, "delay_until": None if f.delay_until is None else f.delay_until - now}
            if f.kind == "call":
                d.update(sub=f.sub["id"], args=f.args, on_fail=f.on_fail, fail_goto=f.fail_goto)
            else:
                parent = self.stack[k - 1]
                st = parent.steps[parent.i]
                d["branch"] = if_branch(st, f.steps) if f.kind == "seq" else "steps"
                d.update(times=f.times, delay=f.delay, when=f.when, max_times=f.max_times, max_seconds=f.max_seconds,
                         items=f.items, var=f.var, on_item_fail=f.on_item_fail,
                         label=getattr(f, "label", None), var_label=getattr(f, "var_label", None))
            if getattr(f, "after_t0", None) is not None:                  # done the input, waiting after it
                d["after"] = f.after_t0 - now
            if getattr(f, "ask", None) and f.ask["t0"] == f.step_t0:      # waiting for an answer: the same question
                d["ask"] = f.ask["id"]
            frames.append(d)
        return {"sub_id": self.sub_id, "origin": self.origin, "started": self.started - now,
                "paused_total": self.paused_total + (now - self.paused_at if self.paused_at is not None else 0), "frames": frames,
                "skipped": self.skipped}

    @classmethod
    def restore(cls, device, snap, lib, now):
        """Rebuild a run from snapshot(): it carries on from the same step (the time it was stopped counts for nothing).
        Raises RuntimeError if the sub-scripts were changed so much that the position no longer fits."""
        r = cls.__new__(cls)
        r.device, r.lib, r.origin, r.sub_id = device, lib, snap.get("origin") or {}, snap["sub_id"]
        r.started, r.stack, r.pending, r.tracker = now + snap["started"], [], None, engine.Tracker()
        r.cleanup, r.ci, r.c_t0 = [], 0, now
        r.done, r.result, r.message, r.unsure_since = False, None, "", None
        r.plain, r.stop_why = "", None
        r.paused_at, r.paused_total = None, float(snap.get("paused_total", 0))
        r.skipped = list(snap.get("skipped") or [])
        r._state, r._env, r._ctx = {}, None, {}
        kinds = {"retry": "retry", "repeat": "repeat_until", "each": "for_each", "seq": "if"}
        for d in snap["frames"]:
            if d["kind"] == "call":
                sub = lib.get(d["sub"])
                if not sub:
                    raise RuntimeError(_("找不到子腳本「{sub}」", sub=d['sub']))
                f = _Frame("call", sub.get("steps"), now, sub=sub, args=d.get("args") or {}, on_fail=d.get("on_fail", "fail"),
                           fail_goto=d.get("fail_goto"))
            else:
                parent = r.stack[-1] if r.stack else None
                st = parent.steps[parent.i] if parent and parent.i < len(parent.steps) else {}
                if st.get("type") != kinds.get(d["kind"]) and not (d["kind"] == "seq" and st.get("type") == "ask"):
                    raise RuntimeError(_("子腳本已經改過,接不上中斷時的位置"))
                steps = branch_steps(st, d["branch"]) if d["kind"] == "seq" else st.get("steps")
                f = _Frame(d["kind"], steps, now, times=d.get("times", 1), delay=d.get("delay", 0), when=d.get("when"),
                           max_times=d.get("max_times", 10), max_seconds=d.get("max_seconds", 600), items=d.get("items"),
                           var=d.get("var"), on_item_fail=d.get("on_item_fail", "fail"))
                if d.get("label"):
                    f.label = d["label"]
                if d.get("var_label"):
                    f.var_label = d["var_label"]
            f.i, f.attempt, f.count, f.idx = d["i"], d.get("attempt", 1), d.get("count", 0), d.get("idx", 0)
            f.t0, f.step_t0 = now + d["t0"], now + d["step_t0"]
            f.delay_until = None if d.get("delay_until") is None else now + d["delay_until"]
            if d.get("after") is not None:
                f.after_t0 = now + d["after"]
            if d.get("ask"):
                f.ask = {"t0": f.step_t0, "id": d["ask"]}
            if f.i > len(f.steps):
                raise RuntimeError(_("子腳本已經改過,接不上中斷時的位置"))
            r.stack.append(f)
        if not r.stack:
            raise RuntimeError(_("沒有可以接續的步驟"))
        return r

    def pause(self, now):
        """Stop doing anything for now (nothing fails meanwhile); resume() carries on from the same step."""
        if self.paused_at is None and not self.done:
            self.paused_at = now

    def resume(self, now):
        """Carry on; the time spent paused counts for no wait, time limit or retry delay."""
        if self.paused_at is None:
            return
        d = now - self.paused_at
        self.paused_at, self.paused_total = None, self.paused_total + d
        for f in self.stack:
            f.t0 += d
            f.step_t0 += d
            if f.delay_until is not None:
                f.delay_until += d
            if getattr(f, "after_t0", None) is not None:
                f.after_t0 += d
        self.c_t0 += d
        if self.unsure_since is not None:
            self.unsure_since += d

    def abort(self, reason, now, cleanup=True):
        """Stop now. cleanup=True runs the cleanup steps of every sub-script on the stack first (innermost first)."""
        if self.done:
            return
        self.result, self.message = "interrupted", reason
        frames = list(reversed(self._calls())) if cleanup else []
        self.stack.clear()
        self.cleanup = [(fr, st) for fr in frames for st in fr.sub.get("cleanup") or []]
        self.ci, self.c_t0, self.pending = 0, now, None
        if not self.cleanup:
            self.done = True

    def advance(self, state, now, executor, names, log, env=None):
        """Do what is due this tick. log(text, level) records what happens (level "notify" = tell the user).
        env (the runtime): .ctx(device) -> history / variables / other devices for conditions,
                           .set_var(device, name, mode, value) for the "set_var" step."""
        self._state = state or {}
        self._now = now
        self._env = env
        self._ctx = env.ctx(self.device) if env else {}
        for _x in range(200):                              # several instant steps may run in one tick
            if self.done:
                return
            if self.cleanup and self.ci < len(self.cleanup):
                if not self._advance_cleanup(now, executor, names, log):
                    return
                continue
            if self.cleanup:                              # cleanup finished
                self.cleanup, self.ci = [], 0
                if not self.stack:
                    self.done = True
                    return
            if not self.stack:
                self.done = True
                return
            for c in self._calls():                       # a sub-script past its time limit fails as a whole
                if now - c.t0 > float(c.sub.get("timeout", 300)):
                    self._fail(_("子腳本「{name}」超過 {p2} 秒", name=c.sub['name'], p2=format(float(c.sub.get('timeout', 300)), 'g')), now, log, through=c)
                    break
            else:
                if not self._step(now, executor, names, log):
                    return
                continue
            continue

    # ---------- picking a name off a list ----------
    def _capture(self, f, st, now, names, log, params):
        """Walk a whole list (lists.py) and save the new names: the runtime does it in a thread; wait for it."""
        cs = getattr(f, "capture", None)
        if not cs or cs["t0"] != f.step_t0:              # a new capture step
            if self._env is None or not hasattr(self._env, "list_capture"):
                self._fail(_("{p1}:這裡不能擷取清單", p1=describe_step(st, names, self.lib, params)), now, log)
                return True
            log(describe_step(st, names, self.lib, params), "step")
            cs = f.capture = {"t0": f.step_t0, "job": self._env.list_capture(self.device, st.get("list"), self)}
            return False
        job = cs["job"]
        if not job["done"]:
            timeout = V.number(st.get("timeout", 300), self._venv(), 300)
            if now - f.step_t0 > timeout:
                job["cancel"] = True
                self._fail(_("{p1}:超過 {timeout} 秒", p1=describe_step(st, names, self.lib, params), timeout=format(timeout, 'g')), now, log)
                return True
            return False
        if job["error"]:
            self._fail(f"{describe_step(st, names, self.lib, params)}:{job['error']}", now, log)
            return True
        r = job["result"]
        miss = r.get("missing") or []
        log(_("清單擷取完:共 {total} 個,新增 {p2} 個", total=r.get('total', len(r['known']) + len(r['new'])), p2=len(r['new']))
            + (f"({_("、").join(b['label'] for b in r['new'])})" if r["new"] else "")
            + (_(",{p1} 個這次沒看到(先不輪到它們,到操作面板確認要移除或保留)", p1=len(miss)) if miss else "")
            + ("" if r.get("complete", True) else _(";清單沒有走到底,沒看到的不算")), "notify")   # whoever asked wants to know
        self._next(f, now)
        return True

    def _pick(self, f, st, args, now, executor, names, log, params):
        """Scroll the list on the screen until the name shows, then tap it (several ticks)."""
        ps = getattr(f, "pick", None)
        if not ps or ps["t0"] != f.step_t0:              # a new pick step
            ps = f.pick = {"t0": f.step_t0, "swipes": 0, "until": 0.0, "fut": None, "lost": None, "seen": None, "seen_t": 0.0}
            log(describe_step(st, names, self.lib, params), "step")
        if ps["fut"] is not None:
            if not ps["fut"].done():
                return False
            try:
                ps["fut"].result()
            except Exception as e:
                self._fail(_("動作送不出去:{e}", e=e), now, log)
                return True
            ps["fut"] = None
        if now < ps["until"]:                             # the list is still moving
            return False
        target = st.get("target") or {}
        if "param" in target:
            target = args.get(target["param"]) or {}
        found = self._env.list_find(self.device, target) if self._env is not None and "button" in target else None
        if found is None:
            p = self._point(target, args)                 # not a list name (or a fixed point): tap it if it is there
            if p:
                self.pending = executor.submit(self.device, "tap", x=p[0], y=p[1])
                return False
            ps["lost"] = ps["lost"] or now
            if now - ps["lost"] < 3:                      # the list may still be opening
                return False
            self._fail(_("{p1}:畫面上沒有看到這個清單", p1=describe_step(st, names, self.lib, params)), now, log)
            return True
        ps["lost"] = None
        if "point" in found:
            # the list may still be gliding after a swipe: tap only once the name has stayed put for "settle" seconds
            p = found["point"]
            s0 = ps["seen"]
            if not (s0 and abs(s0[0] - p[0]) <= 3 and abs(s0[1] - p[1]) <= 3):
                ps["seen"], ps["seen_t"] = p, now
                return False
            if now - ps["seen_t"] < V.number(st.get("settle", 1), self._venv(args), 1):
                return False
            self.pending = executor.submit(self.device, "tap", x=p[0], y=p[1])
            return False
        ps["seen"] = None
        if ps["swipes"] >= V.integer(st.get("max_swipes", 25), self._venv(args), 25):
            self._fail(_("{p1}:滑了 {swipes} 次還是沒看到", p1=describe_step(st, names, self.lib, params), swipes=ps['swipes']), now, log)
            return True
        x, y1, y2 = found["move"]
        ps["swipes"] += 1
        ps["fut"] = executor.submit(self.device, "swipe", x1=x, y1=y1, x2=x, y2=y2, ms=900)
        ps["until"] = now + 1.3
        return False

    # ---------- one step ----------
    def _step(self, now, executor, names, log):
        """-> True to keep going this tick, False to come back next tick."""
        f = self.stack[-1]
        args = self._args()
        if self.pending is not None:                      # the action of the current input step
            if not self.pending.done():
                return False
            try:
                self.pending.result()
            except Exception as e:
                self.pending = None
                self._fail(_("動作送不出去:{e}", e=e), now, log)
                return True
            self.pending = None
            if (f.steps[f.i].get("after") or {}) if f.i < len(f.steps) else None:
                f.after_t0 = now                          # now wait as the step says ("after")
                return True
            self._next(f, now)
            return True
        if getattr(f, "after_t0", None) is not None:      # an input step done: its "after" wait
            return self._after(f, f.steps[f.i], args, now, names, log)
        if f.delay_until is not None:                     # pause between two retry attempts
            if now < f.delay_until:
                return False
            f.delay_until = None
        if f.i >= len(f.steps):
            self._end_block(f, now, log)
            return True
        st = f.steps[f.i]
        t = st.get("type")
        params = self._params()
        if t in ("tap", "long_press", "swipe", "back", "launch_app", "input_text"):
            log(describe_step(st, names, self.lib, params), "step")
            if t == "back":
                self.pending = executor.submit(self.device, "back")
            elif t == "input_text":
                text = V.render(st.get("text"), self._venv(args))
                if not text:
                    self._fail(_("要輸入的文字是空的"), now, log)
                    return True
                self.pending = executor.submit(self.device, "text", text=text)
            elif t == "launch_app":
                from .subs import _app
                self.pending = executor.submit(self.device, "launch", package=V.resolve(st.get("package"), self._venv(args)) or _app())
            elif t == "swipe":
                a, b = self._point(st.get("from"), args), self._point(st.get("to"), args)
                if not a or not b:
                    self._fail(_("滑動的位置沒有設定"), now, log)
                    return True
                self.pending = executor.submit(self.device, "swipe", x1=a[0], y1=a[1], x2=b[0], y2=b[1],
                                               ms=V.integer(st.get("ms", 400), self._venv(args), 400))
            else:
                p = self._point(st.get("target"), args)
                if not p:
                    self._fail(_("畫面上找不到{p1}的目標", p1=describe_step(st, names, self.lib, params)) if "button" in (st.get("target") or {})
                               else _("點擊的位置沒有設定"), now, log)
                    return True
                if t == "tap":
                    self.pending = executor.submit(self.device, "tap", x=p[0], y=p[1])
                else:
                    self.pending = executor.submit(self.device, "long_press", x=p[0], y=p[1],
                                                   ms=V.integer(st.get("ms", 800), self._venv(args), 800))
            return False                                  # at most one input per tick
        if t == "output":
            log(describe_step(st, names, self.lib, params), "step")
            if self._env is None or not hasattr(self._env, "send_output"):
                self._fail(_("這裡不能送到輸出"), now, log)
                return True
            env = self._venv(args)
            self.pending = self._env.send_output(self.device, st.get("output"), V.render(st.get("command"), env),
                                                 V.resolve(st.get("value"), env), self.origin.get("script_name") or "")
            return False
        if t == "capture_list":
            return self._capture(f, st, now, names, log, params)
        if t == "pick":
            return self._pick(f, st, args, now, executor, names, log, params)
        if t == "wait":
            secs = V.number(st.get("seconds", 1), self._venv(args), None)
            if secs is None:
                self._fail(_("等待的秒數沒有設定"), now, log)
                return True
            if now - f.step_t0 < secs:
                return False
            self._next(f, now)
            return True
        if t == "wait_until":
            if self._cond(f, st.get("when"), now) == engine.MATCH:
                self._next(f, now)
                return True
            timeout = V.number(st.get("timeout", 10), self._venv(args), 10)
            if now - f.step_t0 >= timeout:
                if st.get("on_timeout") == "continue":
                    log(_("等了 {timeout} 秒條件沒成立,繼續", timeout=format(timeout, 'g')), "step")
                    self._next(f, now)
                    return True
                self._fail(_("{p1}:逾時", p1=describe_step(st, names, self.lib, params)), now, log,
                           cond=cond_text(st.get("when"), names))
                return True
            return False
        if t == "if":
            # 如果 / 否則如果 ... in order: the first that holds wins; one that cannot be told yet waits (then fails)
            branch, said = None, _("不成立")
            for k, (when, steps) in enumerate([(st.get("when"), st.get("then"))] + [(e.get("when"), e.get("then")) for e in st.get("elif") or []]):
                r = self._cond(f, when, now)
                if r == engine.UNSURE:
                    self.unsure_since = self.unsure_since or now
                    if now - self.unsure_since < UNSURE_WAIT:
                        return False
                    self._fail(f"{describe_step(st, names, self.lib, params)}:{self._unsure_text(when, names)}", now, log)
                    return True
                if r == engine.MATCH:
                    branch, said = steps, _("成立") if k == 0 else _("第 {k} 個「否則如果」成立", k=k)
                    break
            else:
                branch = st.get("else")
            log(f"{describe_step(st, names, self.lib, params)} → {said}", "step")
            self.unsure_since = None
            if branch:
                self.stack.append(_Frame("seq", branch, now))
            else:
                self._next(f, now)
            return True
        if t == "retry":
            env = self._venv(args)
            self.stack.append(_Frame("retry", st.get("steps"), now, times=V.integer(st.get("times", 3), env, 3),
                                     delay=V.number(st.get("delay", 0), env, 0)))
            return True
        if t == "repeat_until":
            env = self._venv(args)
            self.stack.append(_Frame("repeat", st.get("steps"), now, when=st.get("when"),
                                     max_times=V.integer(st.get("max_times", 10), env, 10),
                                     max_seconds=V.number(st.get("max_seconds", 600), env, 600)))
            return True
        if t == "for_each":
            items = args.get(st.get("list"))
            items = items if isinstance(items, list) else []
            label = next((p.get("label") or p["name"] for p in params or [] if p["name"] == st.get("list")), st.get("list"))
            if not items:
                log(_("清單「{label}」是空的,略過", label=label), "step")
                self._next(f, now)
                return True
            self.stack.append(_Frame("each", st.get("steps"), now, items=items, var=st.get("as") or "item",
                                     on_item_fail=st.get("on_item_fail", "fail")))
            self.stack[-1].label = label
            self.stack[-1].var_label = st.get("as_label") or _("目前的{label}", label=label)
            log(_("「{label}」第 1/{p2} 個", label=label, p2=len(items)), "step")
            return True
        if t == "goto":
            log(describe_step(st, names, self.lib, params), "step")
            if self._env is not None and hasattr(self._env, "step_goto"):
                self._env.step_goto(self.device, self.origin, st.get("situation"),
                                    _("規則「{p1}」", p1=self.origin.get('rule_name') or self.origin.get('script_name') or ''))
            self._next(f, now)
            return True
        if t == "stop":
            self.stop_why = V.render(st.get("text"), self._venv(args)) or _("腳本要求停下來")
            log(_("停下這台:{stop_why}", stop_why=self.stop_why), "warn")
            self.stack.clear()
            self.done, self.result, self.message = True, "success", _("停下這台:{stop_why}", stop_why=self.stop_why)
            return True
        if t in ("stay", "hold"):                            # a rule's own decision (runtime/shadow.py), nothing to do here
            self._next(f, now)
            return True
        if t == "call":
            try:
                self._push_call(st.get("sub"), st.get("args") or {}, now, st.get("on_fail", "fail"), args, st.get("fail_goto"))
            except RuntimeError as e:
                self._fail(str(e), now, log)
                return True
            log(_("呼叫子腳本「{name}」", name=self.stack[-1].sub['name']), "step")
            return True
        if t == "notify":
            log(V.render(st.get("text"), self._venv(args)) or _("通知"), "notify")
            self._next(f, now)
            return True
        if t == "ask":
            return self._ask(f, st, args, now, names, log, params)
        if t == "set_var":
            if self._env:
                self._env.set_var(self.device, st.get("var"), st.get("mode"), V.resolve(st.get("value"), self._venv(args)), now)
                self._ctx = self._env.ctx(self.device)       # later conditions in this tick see the new value
            log(describe_step(st, names, self.lib, params), "step")
            self._next(f, now)
            return True
        if t == "succeed":
            if st.get("text"):
                log(V.render(st["text"], self._venv(args)), "step")
            while self.stack and self.stack[-1].kind != "call":
                self.stack.pop()
            self._end_block(self.stack[-1], now, log)
            return True
        if t == "fail":
            self._fail(V.render(st.get("text"), self._venv(args)) or _("子腳本指定結束(失敗)"), now, log)
            return True
        self._fail(_("不認得的步驟「{t}」", t=t), now, log)
        return True

    def _after(self, f, st, args, now, names, log):
        """After an input step: wait the seconds, or until its condition holds ("after")."""
        a = st.get("after") or {}
        env = self._venv(args)
        if a.get("until"):
            if self._cond(f, a["until"], now) == engine.MATCH:
                f.after_t0 = None
                self._next(f, now)
                return True
            timeout = V.number(a.get("timeout", 10), env, 10)
            if now - f.after_t0 < timeout:
                return False
            f.after_t0 = None
            if a.get("on_timeout") == "continue":
                log(_("等了 {timeout} 秒條件沒成立,繼續", timeout=format(timeout, 'g')), "step")
                self._next(f, now)
                return True
            self._fail(_("{p1}:逾時", p1=describe_step(st, names, self.lib, self._params())), now, log,
                       cond=cond_text(a.get("until"), names))
            return True
        if now - f.after_t0 < V.number(a.get("seconds", 0), env, 0):
            return False
        f.after_t0 = None
        self._next(f, now)
        return True

    def _ask(self, f, st, args, now, names, log, params):
        """Ask people and wait (several ticks); then run the chosen option's steps."""
        opts = st.get("options") or []
        default = int(st.get("default") or 0)
        q = getattr(f, "ask", None)
        if not q or q["t0"] != f.step_t0:                # a new ask step
            text = V.render(st.get("text"), self._venv(args)) or "?"
            timeout = V.number(st.get("timeout", 300), self._venv(args), 300)
            if self._env is None or not hasattr(self._env, "ask"):
                if not default:                           # nobody here to answer (a replay without answers)
                    self._fail(_("{p1}:這裡沒有人可以回答", p1=describe_step(st, names, self.lib, params)), now, log)
                    return True
                return self._chosen(f, st, default, _("沒人可以回答,用預設"), now, log, params)
            f.ask = {"t0": f.step_t0, "id": self._env.ask(self.device, text, [o.get("label") for o in opts], timeout, default or None,
                                                          self.origin.get("script_name") or "")}
            log(_("問使用者:{text}({p2})", text=text, p2=' / '.join(o.get('label') for o in opts)), "ask")
            return False
        got = self._env.ask_answer(q["id"]) if self._env is not None and hasattr(self._env, "ask_answer") else None
        if got:
            self._env.ask_close(q["id"], "answered")
            return self._chosen(f, st, int(got["option"]), _("{p1}回答", p1=got.get('by') or _("有人")), now, log, params)
        timeout = V.number(st.get("timeout", 300), self._venv(args), 300)
        if now - f.step_t0 >= timeout:
            if self._env is not None and hasattr(self._env, "ask_close"):
                self._env.ask_close(q["id"], "timeout")
            if not default:
                self._fail(_("問使用者:{timeout} 秒沒有人回答", timeout=format(timeout, 'g')), now, log)
                return True
            return self._chosen(f, st, default, _("{timeout} 秒沒有人回答,用預設", timeout=format(timeout, 'g')), now, log, params)
        return False

    def _chosen(self, f, st, option, why, now, log, params):
        opts = st.get("options") or []
        o = opts[option - 1] if 0 < option <= len(opts) else {}
        log(_("問使用者 → 「{label}」({why})", label=o.get('label'), why=why), "step")
        if st.get("var") and self._env is not None:
            self._env.set_var(self.device, st["var"], "set", option, now)
            self._ctx = self._env.ctx(self.device)
        if o.get("then"):
            self.stack.append(_Frame("seq", o["then"], now))
        else:
            self._next(f, now)
        return True

    def _end_block(self, f, now, log):
        """The steps of the top frame are all done."""
        if f.kind == "repeat":
            if self._cond(f, f.when, now) != engine.MATCH:
                f.count += 1
                if f.count >= f.max_times or now - f.t0 > f.max_seconds:
                    self._fail(_("重複了 {count} 次條件都沒成立", count=f.count), now, log)
                    return
                f.i, f.step_t0 = 0, now
                return
        if f.kind == "each" and f.idx + 1 < len(f.items):
            f.idx += 1
            f.i, f.step_t0, f.item_t0 = 0, now, now
            log(_("「{p1}」第 {p2}/{p3} 個", p1=getattr(f, 'label', f.var), p2=f.idx + 1, p3=len(f.items)), "step")
            return
        self.stack.pop()
        if f.kind == "call":
            log(_("子腳本「{name}」完成", name=f.sub['name']), "step")
            if not self.stack:
                if self.skipped:                          # went through, but some items failed: not done in full
                    by = {}
                    for s in self.skipped:
                        by.setdefault((s["list"], s["of"]), []).append(s)
                    self.done, self.result = True, "partial"
                    self.message = _(";").join(
                        _("{lst} 完成 {p2}/{of},失敗:", lst=lst, p2=of - len(xs), of=of) + _("、").join(_("第 {no} 個({p2})", no=x['no'], p2=x['reason'][:40]) for x in xs)
                        for (lst, of), xs in by.items())
                    self.plain = _(";").join(
                        _("{lst} 完成 {p2}/{of},沒做完的:", lst=lst, p2=of - len(xs), of=of) + _("、").join(_("第 {no} 個({p2})", no=x['no'], p2=x.get('plain') or x['reason'][:40]) for x in xs)
                        for (lst, of), xs in by.items())
                else:
                    self.done, self.result, self.message = True, "success", _("完成")
                return
        if self.stack:
            self._next(self.stack[-1], now)

    def _fail(self, reason, now, log, through=None, cond=None):
        """Unwind: retry the nearest retry block with attempts left, or continue after a call with on_fail =
        continue; else the whole run fails. through = a call frame that must end no matter what (its time limit)."""
        plain = self._plain(reason, through, cond)
        log(_("失敗:{reason}", reason=reason), "warn")
        self.pending = None
        ended = []
        forced = through is not None
        stopping = False
        while self.stack:
            f = self.stack[-1]
            if not forced and not stopping and f.kind == "each" and f.on_item_fail == "continue":
                log(_("「{p1}」第 {p2} 個失敗,略過", p1=getattr(f, 'label', f.var), p2=f.idx + 1), "step")
                self.skipped.append({"list": getattr(f, "label", f.var), "no": f.idx + 1, "of": len(f.items), "reason": reason,
                                     "plain": plain})
                self._start_cleanup(ended, now)
                self._end_block(f, now, log)              # the next item, or past the block
                return
            if not forced and not stopping and f.kind == "retry" and f.attempt < f.times:
                f.attempt += 1
                f.i, f.step_t0 = 0, now
                f.delay_until = now + f.delay if f.delay else None
                log(_("重試第 {attempt} 次(最多 {times} 次)", attempt=f.attempt, times=f.times), "step")
                self._start_cleanup(ended, now)
                return
            self.stack.pop()
            if f.kind == "call":
                ended.append(f)
                if f is through:
                    forced = False
                if not forced and not stopping and f.on_fail == "stop":
                    stopping = True                       # the device stops: nothing above may catch it
                    self.stop_why = _("「{name}」失敗:{p2}", name=f.sub['name'], p2=plain or reason)
                if not forced and not stopping and f.on_fail == "continue" and self.stack:
                    log(_("子腳本「{name}」失敗,繼續下一步", name=f.sub['name']), "step")
                    if f.fail_goto and self._env is not None and hasattr(self._env, "step_goto"):
                        self._env.step_goto(self.device, self.origin, f.fail_goto, _("子腳本「{name}」失敗", name=f.sub['name']))
                    self._next(self.stack[-1], now)
                    self._start_cleanup(ended, now)
                    return
        self.result, self.message, self.plain = "failed", reason, plain
        self._start_cleanup(ended, now)
        if not self.cleanup:
            self.done = True

    def loops(self):
        """Where each "for each" block is: [(its list's name, which one (from 1), how many)], outermost first."""
        return [(getattr(f, "label", f.var), f.idx + 1, len(f.items)) for f in self.stack if f.kind == "each"]

    def _plain(self, reason, through=None, cond=None):
        """The failure in plain words: the failing step's own say_fail, else the nearest sub-script's, else the
        runtime's own wording of what happened (plain_fail)."""
        f = self.stack[-1] if self.stack else None
        st = f.steps[f.i] if f is not None and f.i < len(f.steps) else {}
        if through is not None:                           # a sub-script ran out of time: say it of that one
            return through.sub.get("say_fail") or _("「{p1}」做太久,沒有做完", p1=through.sub.get('say') or through.sub['name'])
        if st.get("say_fail"):
            return st["say_fail"]
        for fr in reversed(self.stack):
            if fr.kind == "call" and fr.sub.get("say_fail"):
                return fr.sub["say_fail"]
        return plain_fail(st, reason, cond)

    def _start_cleanup(self, frames, now):
        self.cleanup = [(fr, st) for fr in frames for st in fr.sub.get("cleanup") or []]
        self.ci, self.c_t0 = 0, now

    def _advance_cleanup(self, now, executor, names, log):
        fr, st = self.cleanup[self.ci]
        if self.pending is not None:
            if not self.pending.done():
                return False
            self.pending = None
            self.ci, self.c_t0 = self.ci + 1, now
            return True
        t = st.get("type")
        env = self._venv(fr.args)
        if t == "wait":
            if now - self.c_t0 < V.number(st.get("seconds", 1), env, 1):
                return False
        elif t == "notify":
            log(V.render(st.get("text"), env) or _("通知"), "notify")
        elif t == "set_var":
            if self._env:
                self._env.set_var(self.device, st.get("var"), st.get("mode"), V.resolve(st.get("value"), env), now)
        elif t == "output":
            if self._env is not None and hasattr(self._env, "send_output"):
                self.pending = self._env.send_output(self.device, st.get("output"), V.render(st.get("command"), env),
                                                     V.resolve(st.get("value"), env), _("收尾"))
                return False
        else:
            log(_("收尾:{p1}", p1=describe_step(st, names, self.lib, fr.sub.get('params'))), "step")
            if t == "back":
                self.pending = executor.submit(self.device, "back")
            elif t == "launch_app":
                from .subs import _app
                self.pending = executor.submit(self.device, "launch", package=V.resolve(st.get("package"), env) or _app())
            else:
                key = "from" if t == "swipe" else "target"
                p = self._point(st.get(key), fr.args)
                if p is None:
                    self.ci += 1
                    return True
                if t == "swipe":
                    q = self._point(st.get("to"), fr.args) or p
                    self.pending = executor.submit(self.device, "swipe", x1=p[0], y1=p[1], x2=q[0], y2=q[1],
                                                   ms=V.integer(st.get("ms", 400), env, 400))
                elif t == "long_press":
                    self.pending = executor.submit(self.device, "long_press", x=p[0], y=p[1], ms=V.integer(st.get("ms", 800), env, 800))
                else:
                    self.pending = executor.submit(self.device, "tap", x=p[0], y=p[1])
            return False
        self.ci, self.c_t0 = self.ci + 1, now
        return True
