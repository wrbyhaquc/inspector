"""How each source is doing (健康狀態), from what the runner gets every tick - nothing extra is captured.

  ok      frames arrive and change
  slow    frames arrive, but taking one takes long (the source or the computer is busy)
  lost    no frame for LOST_S seconds (closed, disconnected, minimised)
  frozen  every frame the same for the freeze time (control "freeze_seconds", default FREEZE_S; 0 = never): the
          program hung, the stream stopped moving, the picture is a still
A change to lost / frozen is told once (an alert, so notifications follow), and so is getting back to normal."""
import collections
import time

import numpy as np
from i18n import _

LOST_S = 15
FREEZE_S = 300
SLOW_MS = 1000
SAME = 0.6           # mean difference (0-255) of a small thumbnail below which two frames are "the same"


class Health:
    def __init__(self):
        self.d = {}                   # device -> {"ok": deque of times, "ms": deque, "last", "thumb", "same_since", "state"}

    def _dev(self, n):
        return self.d.setdefault(n, {"ok": collections.deque(maxlen=120), "ms": collections.deque(maxlen=30), "last": 0.0,
                                     "thumb": None, "same_since": None, "state": "ok", "since": time.time()})

    def frame(self, n, img, ms, now):
        """A frame was taken (img) in ms milliseconds."""
        h = self._dev(n)
        h["ok"].append(now)
        h["ms"].append(ms)
        h["last"] = now
        t = np.asarray(img[::24, ::24], dtype=np.int16)
        if h["thumb"] is not None and t.shape == h["thumb"].shape and float(np.abs(t - h["thumb"]).mean()) < SAME:
            h["same_since"] = h["same_since"] or now
        else:
            h["same_since"] = None
        h["thumb"] = t

    def miss(self, n, ms, now):
        h = self._dev(n)
        h["ms"].append(ms)

    def check(self, n, now, freeze_s=FREEZE_S):
        """-> (state, text, changed): changed = the state is different from last time."""
        h = self._dev(n)
        age = now - h["last"] if h["last"] else None
        recent = [t for t in h["ok"] if now - t <= 30]
        fps = round(len(recent) / min(30, max(1, now - (recent[0] if recent else now))), 2) if len(recent) > 1 else 0
        ms = sum(h["ms"]) / len(h["ms"]) if h["ms"] else 0
        if age is None or age > LOST_S:
            state, text = "lost", _("沒有畫面") + (_("({p1} 秒)", p1=int(age)) if age else "")
        elif freeze_s and h["same_since"] and now - h["same_since"] >= freeze_s:
            still = now - h["same_since"]
            state, text = "frozen", _("畫面 {p1} 分鐘沒有變化(可能當機或畫面停住)", p1=int(still // 60)) if still >= 60 else _("畫面 {p1} 秒沒有變化(可能當機或畫面停住)", p1=int(still))
        elif ms > SLOW_MS:
            state, text = "slow", _("取畫面很慢(每張 {p1} 秒)", p1=format(ms / 1000, '.1f'))
        else:
            state, text = "ok", _("正常")
        changed = state != h["state"]
        if changed:
            h["state"], h["since"] = state, now
        return state, text, changed, {"fps": fps, "age": None if age is None else round(age, 1), "ms": round(ms),
                                      "since": h["since"]}

    def forget(self, n):
        self.d.pop(n, None)
