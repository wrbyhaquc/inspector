"""How well the buttons are found while scripts run (按鈕監測): after an app update a button's picture often changes,
and every script that taps it starts failing one by one. The runtime counts, per button, how often a picture button
was looked for to be tapped and how often it was found, and says when one that is usually found stops being found.

Every look for a find button that a step wants to tap (lists' names are left out: their rows come and go) is counted
per BUCKET (1 hour) and written to <runtime dir>/quality/buttons/<YYYYMMDD>.jsonl:
  {"t": bucket start, "button", "device", "n": looks, "found": of those, found, "score": mean best score}

A button "stopped being found" when, over the last RECENT_HOURS on all devices together, it was looked for at least
RECENT_MIN_N times and found in at most RECENT_FOUND_MAX of them, while over the BASELINE_DAYS before it was found in at
least BASELINE_FOUND_MIN of at least BASELINE_MIN_N looks. Then on_alert(text) - at most once per ALERT_EVERY per button.
Looks are counted on every tick a step waits for its button, so the shares are compared with the button's own usual
share, never read as a share of taps."""
import collections
import datetime
import glob
import json
import os
from i18n import _

BUCKET = 3600
RECENT_HOURS = 3
RECENT_MIN_N = 8
RECENT_FOUND_MAX = 0.3
BASELINE_DAYS = 7
BASELINE_MIN_N = 30
BASELINE_FOUND_MIN = 0.8
ALERT_EVERY = 12 * 3600


def read(bdir, days, today=None):
    today = today or datetime.date.today()
    want = {(today - datetime.timedelta(days=k)).strftime("%Y%m%d") for k in range(days + 1)}
    rows = []
    for p in sorted(glob.glob(os.path.join(bdir, "*.jsonl"))):
        if os.path.basename(p)[:8] not in want:
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def found_share(rows):
    n = sum(r["n"] for r in rows)
    return n, (sum(r["found"] for r in rows) / n if n else None)


class ButtonHealth:
    def __init__(self, runtime_dir, labels, on_alert):
        """labels() -> {button id: its label}; on_alert(text)."""
        self.dir = os.path.join(runtime_dir, "quality", "buttons")
        os.makedirs(self.dir, exist_ok=True)
        self.labels, self.on_alert = labels, on_alert
        self.bucket = None
        self.cur = {}                     # (button, device) -> {"n", "found", "score"}
        self.recent = []                  # rows written in this run (the last hours)
        self.alerted = {}

    def add(self, now, button, device, found, score):
        b = int(now // BUCKET * BUCKET)
        if self.bucket is not None and b != self.bucket:
            self._flush(now)
        self.bucket = b
        c = self.cur.setdefault((button, device), {"n": 0, "found": 0, "score": 0.0})
        c["n"] += 1
        c["found"] += 1 if found else 0
        c["score"] += float(score or 0.0)

    def _flush(self, now):
        rows = [{"t": self.bucket, "button": bid, "device": dev, "n": c["n"], "found": c["found"],
                 "score": round(c["score"] / c["n"], 3)} for (bid, dev), c in self.cur.items() if c["n"]]
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
        self.recent = [r for r in self.recent if r["t"] > now - 24 * 3600] + rows
        try:
            self.check(now)
        except Exception as e:                               # never stop the loop for this
            print(_("按鈕監測:檢查失敗 {e}", e=e), flush=True)

    def check(self, now, history=None):
        """Alert for the buttons that stopped being found. history: the rows to compare with (default: the files)."""
        lo = now - RECENT_HOURS * BUCKET
        hist = read(self.dir, BASELINE_DAYS) if history is None else history
        recent, base = collections.defaultdict(list), collections.defaultdict(list)
        for r in self.recent:
            if r["t"] >= lo:
                recent[r["button"]].append(r)
        for r in hist:
            if r["t"] < lo:
                base[r["button"]].append(r)
        for bid, rs in recent.items():
            n, share = found_share(rs)
            bn, bshare = found_share(base.get(bid, []))
            if n < RECENT_MIN_N or share > RECENT_FOUND_MAX or bn < BASELINE_MIN_N or bshare < BASELINE_FOUND_MIN:
                continue
            if now - self.alerted.get(bid, 0) < ALERT_EVERY:
                continue
            self.alerted[bid] = now
            devs = sorted({r["device"] for r in rs})
            self.on_alert(_("按鈕「{name}」最近常找不到:最近 {h} 小時找了 {n} 次只找到 {share}(平常 {usual}),在 {devs}。可能 App 改版、按鈕的樣子變了;到「按鈕」用新的畫面重新截圖。",
                            name=self.labels().get(bid, bid), h=RECENT_HOURS, n=n, share=format(share, ".0%"),
                            usual=format(bshare, ".0%"), devs=_("、").join(devs)))

    def close(self, now):
        if self.cur:
            self._flush(now)
