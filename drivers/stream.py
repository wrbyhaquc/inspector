"""Category "stream" (影像串流): a camera or a recorder's live picture - RTSP (IP cameras, NVR / DVR channels), HTTP
(MJPEG streams or a snapshot address polled), USB cameras and capture cards. Only a picture: no hand of its own (its
actions, if any, go to another source or an output - see drivers/sources.py "hand").

Each source is one stream (SOURCE_PARAMS, kept on the source): its address (or USB number), how the picture fits
the project's space (drivers/fit.py), the part to keep. A reader thread per stream keeps only the newest frame
(a stream that is read slowly would fall minutes behind otherwise), reconnects on its own (waiting a little longer
each time, up to a minute) and says how old the newest frame is.

Addresses look like (the camera's / recorder's manual has the exact one):
  rtsp://user:password@192.168.1.10:554/Streaming/Channels/101            many NVRs: channel 1, main stream
  rtsp://user:password@192.168.1.10:554/cam/realmonitor?channel=1&subtype=0
  http://192.168.1.10/video.mjpg    http://192.168.1.10/snapshot.jpg"""
import re
import threading
import time
import urllib.request

import numpy as np

from . import Device
from .fit import Fit, project_size
from i18n import N_, _

LABEL = N_("影像串流")
PARAMS = {"timeout": {"label": N_("幾秒沒畫面算斷線"), "type": "text", "help": N_("預設 10")}}
FIT = {"label": N_("畫面怎麼放進專案的大小"), "type": "select", "options": {"contain": N_("等比例,補黑邊(不變形,建議)"), "stretch": N_("拉伸填滿(形狀不同會變形)"), "cover": N_("等比例填滿,裁掉多的部分")}}
SOURCE_PARAMS = {
    "url": {"label": N_("串流位址"), "type": "text", "help": N_("rtsp://… 或 http://…;USB 攝影機填編號 0、1…")},
    "http_mode": {"label": N_("HTTP 是"), "type": "select", "options": {"mjpeg": N_("連續影像(MJPEG)"), "snapshot": N_("一張張的快照(每次重新抓)")}},
    "snapshot_every": {"label": N_("快照間隔(秒)"), "type": "text", "help": N_("HTTP 快照才用;預設 1")},
    "region": {"label": N_("只取一塊(x,y,寬,高)"), "type": "text", "help": N_("串流自己的像素;空白 = 整個畫面")},
    "fit": FIT,
}
PRESETS = {
    "rtsp": {"label": N_("IP 攝影機 / NVR(RTSP)"), "order": 7, "params": {}, "shows": ["timeout"], "manual": True,
             "note": N_("填攝影機或錄影機的 RTSP 位址;NVR 的每個頻道是一個來源。位址格式見機器的說明書,常見的如 rtsp://帳號:密碼@IP:554/Streaming/Channels/101")},
    "http": {"label": N_("HTTP 影像(MJPEG / 快照網址)"), "order": 7, "params": {}, "shows": ["timeout"], "manual": True,
             "note": N_("網頁上看得到的攝影機畫面網址;連續影像選 MJPEG,只給一張圖的選快照")},
    "usb": {"label": N_("USB 攝影機 / 擷取卡"), "order": 7, "params": {}, "shows": ["timeout"],
            "note": N_("按掃描會列出這台電腦上的攝影機(編號 0、1…)")},
}


def mask(url):
    """An address to show: the password hidden."""
    return re.sub(r"(//[^:/@]+:)[^@]*@", r"\1••••@", str(url or ""))


class Reader:
    """Keeps the newest frame of one stream (a thread); reconnects on its own."""

    def __init__(self, url, http_mode="mjpeg", every=1.0):
        self.url, self.http_mode, self.every = url, http_mode, every
        self.frame, self.t, self.error, self.state = None, 0.0, None, "connecting"
        self.size = None
        self.stop = threading.Event()
        self.used = time.time()
        threading.Thread(target=self._run, daemon=True, name=f"stream-{mask(url)[:30]}").start()

    def _open(self):
        import cv2
        u = self.url.strip()
        if u.isdigit():
            return cv2.VideoCapture(int(u), cv2.CAP_DSHOW)
        cap = cv2.VideoCapture(u, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _snapshot(self):
        import cv2
        with urllib.request.urlopen(self.url, timeout=10) as r:
            data = np.frombuffer(r.read(), np.uint8)
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError(_("網址回來的不是圖片"))
        return bgr

    def _got(self, bgr):
        self.frame = np.ascontiguousarray(bgr[:, :, ::-1])
        self.size = (bgr.shape[1], bgr.shape[0])
        self.t, self.state, self.error = time.time(), "ok", None

    def _run(self):
        wait = 2.0
        while not self.stop.is_set():
            if time.time() - self.used > 600:             # nobody asked for 10 minutes: stop reading
                return
            try:
                if self.url.startswith("http") and self.http_mode == "snapshot":
                    self._got(self._snapshot())
                    wait = 2.0
                    self.stop.wait(self.every)
                    continue
                cap = self._open()
                if not cap.isOpened():
                    raise RuntimeError(_("連不上(位址、帳號密碼或網路)"))
                while not self.stop.is_set() and time.time() - self.used < 600:
                    ok, bgr = cap.read()
                    if not ok or bgr is None:
                        raise RuntimeError(_("串流中斷了"))
                    self._got(bgr)
                    wait = 2.0
                cap.release()
            except Exception as e:
                self.state, self.error = "error", str(e)
                self.stop.wait(wait)
                wait = min(wait * 2, 60)

    def age(self):
        return time.time() - self.t if self.t else None


_readers = {}
_lock = threading.Lock()


def reader(opts):
    url = str((opts or {}).get("url") or "").strip()
    if not url:
        return None
    key = (url, (opts or {}).get("http_mode") or "mjpeg")
    with _lock:
        r = _readers.get(key)
        if r is None or (not r.stop.is_set() and time.time() - r.used > 600):
            try:
                every = float((opts or {}).get("snapshot_every") or 1)
            except ValueError:
                every = 1.0
            r = _readers[key] = Reader(url, key[1], max(0.2, every))
        r.used = time.time()
        return r


def _region(opts, size):
    r = str((opts or {}).get("region") or "").replace("，", ",")
    try:
        v = [int(float(x)) for x in r.split(",")] if r.strip() else None
    except ValueError:
        v = None
    if v and len(v) == 4 and v[2] > 0 and v[3] > 0:
        return v
    return [0, 0, size[0], size[1]]


class Stream:
    label = LABEL
    caps = {"screen"}
    capture_modes = {"stream": N_("讀串流")}
    per_source = SOURCE_PARAMS

    def __init__(self, params=None, preset="rtsp"):
        self.preset = preset
        self.p = {**(PRESETS.get(preset) or {}).get("params", {}), **{k: v for k, v in (params or {}).items() if v not in (None, "")}}
        try:
            self.timeout = float(self.p.get("timeout") or 10)
        except ValueError:
            self.timeout = 10.0

    def list(self):
        """USB cameras on this computer (the others are added by their address)."""
        if self.preset != "usb":
            return []
        import cv2
        out = []
        for k in range(4):
            cap = cv2.VideoCapture(k, cv2.CAP_DSHOW)
            if cap.isOpened():
                w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                out.append(Device(_("USB 攝影機 {k}", k=k), ok=True, detail=_("編號 {k}", k=k), size=(w, h) if w and h else None,
                                  info={"fit": "contain", "opts": {"url": str(k), "fit": "contain"}}))
            cap.release()
        return out

    def find(self, opts):
        r = reader(opts)
        if r is None:
            return None
        age = r.age()
        ok = age is not None and age < self.timeout
        detail = mask(r.url) + ("" if ok else " · " + (_("連線中…") if r.state == "connecting" else _("沒有畫面:{error}", error=r.error or "")))
        size = None
        if r.size:
            reg = _region(opts, r.size)
            size = (reg[2], reg[3])
        return Device(mask(r.url)[-50:], ok=ok, detail=detail, size=size,
                      info={"fit": (opts or {}).get("fit") or "contain", "age": age, "error": r.error})

    def capture(self, name, prefer=None, fallback=True, opts=None):
        return _Cap(opts, self.timeout)

    def input(self, name, kind, opts=None, **p):
        raise RuntimeError(_("影像串流只能看;動作請在「來源」交給另一個來源或送到輸出"))

    def watch_touch(self, name, on_gesture):
        return None


class _Cap:
    def __init__(self, opts, timeout):
        self.opts, self.timeout, self.slow, self.last_src = opts, timeout, False, None

    def grab(self):
        r = reader(self.opts)
        if r is None or r.frame is None or (r.age() or 1e9) > self.timeout:
            return None
        img = r.frame
        x, y, w, h = _region(self.opts, r.size)
        img = img[y:y + h, x:x + w]
        self.last_src = f"stream {img.shape[1]}x{img.shape[0]}"
        return Fit((img.shape[1], img.shape[0]), project_size(), (self.opts or {}).get("fit") or "contain").image(img), \
            self.last_src, (img.shape[1], img.shape[0])
