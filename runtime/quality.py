"""How well the model is doing while it runs (品質監測): a model that was fine can get worse when the screen changes
(an app update, a new banner, lighting for a camera). Nobody answers questions all day, so the runtime keeps
cheap counts and says when a state starts going wrong.

Every tick, for each state the model answered on each device: how sure it was, whether that was below CONF_LOW, and -
where a screen rule also looked - whether the rule said something else. Counts are summed per BUCKET (10 minutes) and
written to <runtime dir>/quality/<YYYYMMDD>.jsonl:
  {"t": bucket start, "model": run id, "device", "state", "n", "conf": mean, "low": n below CONF_LOW,
   "rule_n": frames a rule also looked at, "dis": of those, the rule said something else, "values": {answer: n}}

A state is "getting worse" on a device when over the last RECENT buckets its share of unsure answers (or of
disagreements with the rule) is well above what this same model usually does (BASELINE_DAYS, the model's own
history; nothing is said before there is enough history). Then on_alert(device, text) - at most once per
ALERT_EVERY per device and state."""
import collections
import datetime
import glob
import json
import os
import time
from i18n import _

BUCKET = 600
RECENT = 3                    # buckets (30 minutes) compared with the baseline
BASELINE_DAYS = 7
BASELINE_MIN_N = 2000         # answers of that state in the baseline before it can say "worse"
RECENT_MIN_N = 150
LOW_ABS, DIS_ABS = 0.25, 0.30           # never alarm below these shares ...
LOW_FACTOR, DIS_FACTOR = 2.0, 2.0       # ... nor below this many times the usual share (+ a little)
ALERT_EVERY = 6 * 3600
CONF_LOW = 0.6


def files(qdir, days):
    today = datetime.date.today()
    want = {(today - datetime.timedelta(days=k)).strftime("%Y%m%d") for k in range(days + 1)}
    return sorted(p for p in glob.glob(os.path.join(qdir, "*.jsonl")) if os.path.basename(p)[:8] in want)


def read(qdir, days, model=None):
    rows = []
    for p in files(qdir, days):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if model is None or r.get("model") == model:
                    rows.append(r)
    return rows


def rates(rows):
    n = sum(r["n"] for r in rows)
    rn = sum(r["rule_n"] for r in rows)
    return {"n": n, "conf": sum(r["conf"] * r["n"] for r in rows) / n if n else None,
            "low": sum(r["low"] for r in rows) / n if n else None,
            "rule_n": rn, "dis": sum(r["dis"] for r in rows) / rn if rn else None}


class Quality:
    def __init__(self, runtime_dir, model, names, on_alert):
        """names() -> {state id: {"name", ...}} (the current schema); on_alert(device, text)."""
        self.dir = os.path.join(runtime_dir, "quality")
        os.makedirs(self.dir, exist_ok=True)
        self.model, self.names, self.on_alert = model, names, on_alert
        self.bucket = None
        self.cur = {}                                        # (device, state) -> counts of this bucket
        self.recent = collections.deque(maxlen=RECENT * 64)  # rows of the last buckets (all devices / states)
        self.base, self.base_t = {}, 0.0                     # state -> rates of this model's history
        self.alerted = {}

    def add(self, now, device, st, rule_vals):
        b = int(now // BUCKET) * BUCKET
        if self.bucket is None:
            self.bucket = b
        if b != self.bucket:
            self._flush(now)
            self.bucket = b
        for sid, v in st.items():
            if v.get("source") != "model" or v.get("conf") is None:
                continue
            c = self.cur.get((device, sid))
            if c is None:
                c = self.cur[(device, sid)] = {"n": 0, "conf": 0.0, "low": 0, "rule_n": 0, "dis": 0, "values": {}}
            c["n"] += 1
            c["conf"] += v["conf"]
            c["low"] += v["conf"] < CONF_LOW
            k = json.dumps(v.get("value"), ensure_ascii=False)
            c["values"][k] = c["values"].get(k, 0) + 1
            if sid in rule_vals:
                c["rule_n"] += 1
                c["dis"] += rule_vals[sid][0] != v.get("value")

    def _flush(self, now):
        rows = [{"t": self.bucket, "model": self.model, "device": d, "state": s, "n": c["n"], "conf": round(c["conf"] / c["n"], 4),
                 "low": c["low"], "rule_n": c["rule_n"], "dis": c["dis"], "values": c["values"]}
                for (d, s), c in self.cur.items() if c["n"]]
        self.cur = {}
        if not rows:
            return
        p = os.path.join(self.dir, datetime.datetime.fromtimestamp(self.bucket).strftime("%Y%m%d") + ".jsonl")
        try:
            with open(p, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self.recent.extend(rows)
        try:
            self._check(now)
        except Exception as e:                               # never stop the loop for this
            print(_("品質監測:檢查失敗 {e}", e=e), flush=True)

    def _baseline(self, now):
        if now - self.base_t > 3600:
            cut = self.bucket - RECENT * BUCKET              # the recent half hour is not part of "usual"
            hist = [r for r in read(self.dir, BASELINE_DAYS, self.model) if r["t"] < cut]
            by = collections.defaultdict(list)
            for r in hist:
                by[r["state"]].append(r)
            self.base, self.base_t = {s: rates(rs) for s, rs in by.items()}, now
        return self.base

    def _check(self, now):
        base = self._baseline(now)
        lo = self.bucket - (RECENT - 1) * BUCKET
        by = collections.defaultdict(list)
        for r in self.recent:
            if r["t"] >= lo and r["model"] == self.model:
                by[(r["device"], r["state"])].append(r)
        for (dev, sid), rs in by.items():
            b = base.get(sid)
            if not b or b["n"] < BASELINE_MIN_N:
                continue
            cur = rates(rs)
            name = (self.names().get(sid) or {}).get("name", sid)
            msgs = []
            if cur["n"] >= RECENT_MIN_N and cur["low"] >= max(LOW_ABS, b["low"] * LOW_FACTOR + 0.05):
                msgs.append(("low", _("模型對「{name}」常常沒把握:最近 30 分鐘 {low} 的畫面信心低於 {CONF_LOW}(這個模型平常 {low2})", name=name, low=format(cur['low'], '.0%'), CONF_LOW=CONF_LOW, low2=format(b['low'], '.0%'))))
            if cur["rule_n"] >= RECENT_MIN_N // 3 and b["dis"] is not None and cur["dis"] >= max(DIS_ABS, b["dis"] * DIS_FACTOR + 0.05):
                msgs.append(("dis", _("模型和畫面規則對「{name}」常常意見不同:最近 30 分鐘 {dis}(平常 {dis2})", name=name, dis=format(cur['dis'], '.0%'), dis2=format(b['dis'], '.0%'))))
            if not msgs or now - self.alerted.get((dev, sid), 0) < ALERT_EVERY:
                continue
            self.alerted[(dev, sid)] = now                   # one message per state, whatever went wrong
            self.on_alert(dev, _(";").join(t for _x, t in msgs) + _("。可能畫面變了(改版、新的活動、光線);到「回答問題」補答這個狀態,再重新訓練。"))

    def close(self, now):
        if self.cur:
            self._flush(now)
