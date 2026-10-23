"""Category "recording" (錄製重播): what this project recorded (the Recording page), played back as sources - to try
states, scripts, the run page, notifications and the operation panel on situations that already happened, without
the real thing and without waiting for them. Frames only, no hand (its actions, if any, go to another source or an
output, as a camera's do).

Each recorded camera of each finished recording is one source (found by scanning, named "<recording> <device>").
It plays in the recorded timing - a long pause in the recording (the recorder waiting) is shortened to a few seconds -
from when it is first captured, and starts over at the end. The recorder does not record these (a recording of a
recording would only repeat the same frames)."""
import glob
import json
import os
import threading
import time

import numpy as np
from PIL import Image

from . import Device
from i18n import N_, _

LABEL = N_("錄製重播")
PARAMS = {"speed": {"label": N_("播放速度(倍)"), "type": "text", "help": N_("預設 1;2 = 兩倍速")},
          "max_gap": {"label": N_("停頓最多幾秒"), "type": "text", "help": N_("錄製時的長停頓縮短成這麼多秒;預設 5")}}
PRESETS = {"default": {"label": N_("這個專案錄好的畫面"), "order": 9, "params": {},
                       "note": N_("按掃描會列出錄好的每一段、每一台;拿錄過的狀況當成即時畫面,試狀態、腳本、執行和操作面板。只能看,不能點")}}


def _sessions():
    import project
    return os.path.join(project.work_root(), "sessions")


def _num(v, default):
    try:
        x = float(v)
        return x if x > 0 else default
    except (TypeError, ValueError):
        return default


def recorded():
    """[(name, session, device, samples, seconds, started)] - every camera of every finished recording, newest first."""
    out = []
    for d in sorted(glob.glob(os.path.join(_sessions(), "*")), reverse=True):
        try:
            with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        if not meta.get("ended"):                                   # still recording
            continue
        sid = os.path.basename(d)
        for dev, v in sorted((meta.get("devices") or {}).items()):
            if (v or {}).get("samples"):
                out.append((f"{sid} {dev}", sid, dev, v["samples"], meta["ended"] - (meta.get("started") or meta["ended"]),
                            meta.get("started")))
    return out


class Recording:
    label = LABEL
    caps = {"screen"}
    capture_modes = {}

    def __init__(self, params=None, preset="default"):
        p = params or {}
        self.speed = _num(p.get("speed"), 1.0)
        self.max_gap = _num(p.get("max_gap"), 5.0)

    def list(self):
        return [Device(name, ok=True, detail=_("{when} · {minutes} 分鐘 · {n} 張", when=time.strftime("%m/%d %H:%M", time.localtime(start or 0)),
                                                 minutes=round(secs / 60, 1), n=n),
                       info={"session": sid, "device": dev})
                for name, sid, dev, n, secs, start in recorded()]

    def capture(self, name, prefer=None, fallback=True):
        hit = next((r for r in recorded() if r[0] == name), None)
        if not hit:
            raise RuntimeError(_("找不到錄製 {name}", name=name))
        return Player(os.path.join(_sessions(), hit[1], "devices", hit[2]), self.speed, self.max_gap)

    def input(self, name, kind, **p):
        raise RuntimeError(_("錄製重播只能看;動作請在「來源」交給另一個來源或送到輸出"))

    def watch_touch(self, name, on_gesture):
        return None


class Player:
    """Plays one recorded camera: grab() gives the frame of now, in the recording's timing."""

    def __init__(self, folder, speed=1.0, max_gap=5.0):
        self.folder, self.slow, self.lock = folder, False, threading.Lock()
        with open(os.path.join(folder, "samples.jsonl"), encoding="utf-8") as f:
            rows = sorted((json.loads(l) for l in f if l.strip()), key=lambda r: r["t_req"])
        rows = [r for r in rows if os.path.exists(os.path.join(folder, r.get("frame") or f"frames/{r['id']}.png"))]
        self.frames, self.at, t = [], [], 0.0                     # when each frame shows, from the start (seconds)
        for i, r in enumerate(rows):
            if i:
                t += min(r["t_req"] - rows[i - 1]["t_req"], max_gap) / speed
            self.frames.append(os.path.join(folder, r.get("frame") or f"frames/{r['id']}.png"))
            self.at.append(t)
        self.length = t + (min(1.0, max_gap) / speed if rows else 0)
        self.t0, self.shown, self.img = time.time(), -1, None

    def position(self):
        """(frame index, seconds into the recording) now"""
        import bisect
        pos = (time.time() - self.t0) % self.length if self.length else 0.0
        return max(0, bisect.bisect_right(self.at, pos) - 1), pos

    def grab(self):
        import project
        if not self.frames:
            return None
        with self.lock:
            k, _pos = self.position()
            if k != self.shown or self.img is None:
                im = Image.open(self.frames[k]).convert("RGB")
                size = im.size
                w, h = project.screen()
                if size != (w, h):
                    im = im.resize((w, h), Image.BILINEAR)
                self.img, self.shown = (np.asarray(im), size), k
            return self.img[0], "recording", self.img[1]
