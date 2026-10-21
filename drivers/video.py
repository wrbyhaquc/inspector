"""Driver "video": video files played back as devices (frames only, no input), e.g. to try states, scripts and
collection on a recording without the real thing. Each file in the folder (params.folder) is one device named after
the file; it plays in real time from when it is first captured and starts over at the end."""
import glob
import os
import threading
import time

import numpy as np

from . import Device
from i18n import N_, _

EXT = (".mp4", ".mkv", ".avi", ".mov", ".webm")


class Capture:
    def __init__(self, path):
        import cv2
        self.cv2 = cv2
        self.v = cv2.VideoCapture(path)
        self.fps = self.v.get(cv2.CAP_PROP_FPS) or 30.0
        self.t0 = time.time()
        self.pos = 0                      # frames read so far
        self.img = None
        self.slow = False
        self.lock = threading.Lock()

    def grab(self):
        import project
        with self.lock:
            want = int((time.time() - self.t0) * self.fps)
            while self.pos <= want or self.img is None:
                ok = self.v.grab()
                if not ok:                       # the end: start over
                    self.v.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
                    self.t0, self.pos, want = time.time(), 0, 0
                    if not self.v.grab():
                        return None
                self.pos += 1
                if self.pos > want:
                    ok, bgr = self.v.retrieve()
                    if not ok:
                        return None
                    size = (bgr.shape[1], bgr.shape[0])
                    w, h = project.screen()
                    if size != (w, h):
                        bgr = self.cv2.resize(bgr, (w, h), interpolation=self.cv2.INTER_AREA)
                    self.img = (np.ascontiguousarray(bgr[:, :, ::-1]), size)
            return self.img[0], "video", self.img[1]


LABEL = N_("錄影檔重播")
PARAMS = {"folder": {"label": N_("放錄影檔的資料夾"), "type": "text", "help": N_("每個檔案是一個來源")}}
PRESETS = {"files": {"label": N_("資料夾裡的錄影檔"), "order": 0, "params": {}, "shows": ["folder"],
                     "note": N_("拿錄好的影片當成即時畫面,試狀態、腳本和錄製;只能看,不能點")}}


class VideoFiles:
    label = LABEL
    caps = {"screen"}
    capture_modes = {}

    def __init__(self, params=None, preset="files"):
        self.folder = (params or {}).get("folder") or ""
        self.caps_open = {}

    def _files(self):
        if not self.folder or not os.path.isdir(self.folder):
            return {}
        return {os.path.splitext(os.path.basename(p))[0]: p for p in sorted(glob.glob(os.path.join(self.folder, "*")))
                if p.lower().endswith(EXT)}

    def list(self):
        return [Device(n, ok=True, detail=os.path.basename(p)) for n, p in self._files().items()]

    def capture(self, name, prefer=None, fallback=True):
        p = self._files().get(name)
        if not p:
            raise RuntimeError(_("找不到錄影檔 {name}", name=name))
        return Capture(p)

    def input(self, name, kind, **p):
        from . import NotSupported
        raise NotSupported(_("錄影檔重播不能{kind}", kind=kind))

    def watch_touch(self, name, on_gesture):
        return None
