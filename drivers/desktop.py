"""Category "screen" (螢幕區域): a rectangle of one of this computer's screens - whatever shows there (a program that
cannot be copied as a window, a video wall, several windows side by side). Its hand is the real mouse and keyboard.

Each source is one rectangle (SOURCE_PARAMS, kept on the source): which screen, and x, y, width, height on it
(empty = the whole screen)."""
import ctypes
import ctypes.wintypes as W

import numpy as np
from PIL import Image, ImageGrab

from . import Device, winput
from .fit import Fit, project_size
from i18n import N_, _

LABEL = N_("螢幕區域")
PARAMS = {"back_key": {"label": N_("「返回」用哪個鍵"), "type": "select", "options": {"esc": "Esc", "back": "Backspace", "none": N_("不支援")}}}
SOURCE_PARAMS = {
    "monitor": {"label": N_("第幾個螢幕"), "type": "text", "help": N_("1 = 主螢幕")},
    "region": {"label": N_("範圍(x,y,寬,高)"), "type": "text", "help": N_("那個螢幕上的像素;空白 = 整個螢幕")},
    "fit": {"label": N_("畫面怎麼放進專案的大小"), "type": "select", "options": {"contain": N_("等比例,補黑邊(不變形,建議)"), "stretch": N_("拉伸填滿(形狀不同會變形)"), "cover": N_("等比例填滿,裁掉多的部分")}},
}
PRESETS = {"region": {"label": N_("螢幕上的一塊"), "order": 6, "params": {"back_key": "esc"}, "shows": ["back_key"],
                      "note": N_("看得到的都能拿;動作會真的移動滑鼠和鍵盤,執行時不要同時用滑鼠")}}


def monitors():
    """[(x, y, w, h)] of each screen, the main one first."""
    out = []
    if not hasattr(ctypes, "windll"):
        return out
    cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)

    def cb(h, dc, r, _x):
        rc = r.contents
        out.append((rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top))
        return True
    ctypes.windll.user32.EnumDisplayMonitors(None, None, cb_t(cb), 0)
    out.sort(key=lambda m: (m[0] != 0 or m[1] != 0, m[0], m[1]))     # the main screen sits at (0, 0)
    return out


def area(opts):
    """The rectangle in desktop pixels, or None."""
    ms = monitors()
    try:
        k = int(str((opts or {}).get("monitor") or "1")) - 1
    except ValueError:
        k = 0
    if not 0 <= k < len(ms):
        return None
    mx, my, mw, mh = ms[k]
    r = str((opts or {}).get("region") or "").replace("，", ",")
    try:
        v = [int(float(x)) for x in r.split(",")] if r.strip() else None
    except ValueError:
        v = None
    if v and len(v) == 4 and v[2] > 0 and v[3] > 0:
        return mx + v[0], my + v[1], min(v[2], mw - v[0]), min(v[3], mh - v[1])
    return mx, my, mw, mh


class Desktop:
    label = LABEL
    caps = {"screen", "tap", "long_press", "swipe", "back", "text"}
    capture_modes = {"screen": N_("螢幕擷取")}
    per_source = SOURCE_PARAMS

    def __init__(self, params=None, preset="region"):
        self.p = {**(PRESETS.get(preset) or {}).get("params", {}), **{k: v for k, v in (params or {}).items() if v not in (None, "")}}

    def list(self):
        return [Device(_("螢幕 {p1}", p1=k + 1), ok=True, detail=f"{w}×{h}" + (_("(主螢幕)") if k == 0 else ""), size=(w, h),
                       info={"fit": "contain", "opts": {"monitor": str(k + 1), "region": "", "fit": "contain"}}) for k, (x, y, w, h) in enumerate(monitors())]

    def find(self, opts):
        a = area(opts)
        if not a:
            return None
        return Device(_("螢幕 {p1}", p1=(opts or {}).get('monitor') or 1), ok=True, detail=f"{a[2]}×{a[3]} @ {a[0]},{a[1]}", size=(a[2], a[3]),
                      info={"fit": (opts or {}).get("fit") or "stretch"})

    def capture(self, name, prefer=None, fallback=True, opts=None):
        return _Cap(opts)

    def input(self, name, kind, opts=None, **p):
        import project
        a = area(opts)
        if not a:
            raise RuntimeError(_("找不到這個螢幕"))
        f = Fit((a[2], a[3]), project_size(), (opts or {}).get("fit") or "stretch")
        at = lambda x, y: (a[0] + f.to_native(x, y)[0], a[1] + f.to_native(x, y)[1])
        if kind in ("tap", "long_press"):
            winput.mouse_press(*at(p["x"], p["y"]), ms=int(p.get("ms", 800)) if kind == "long_press" else 60)
        elif kind == "swipe":
            (x1, y1), (x2, y2) = at(p["x1"], p["y1"]), at(p["x2"], p["y2"])
            winput.mouse_drag(x1, y1, x2, y2, ms=int(p.get("ms", 400)))
        elif kind == "back":
            if self.p.get("back_key", "esc") == "none":
                raise RuntimeError(_("這個來源沒有「返回」"))
            winput.key_press(self.p.get("back_key", "esc"))
        elif kind == "text":
            winput.key_text(str(p["text"]))
        else:
            raise RuntimeError(_("螢幕區域不能{kind}", kind=kind))
        return True

    def watch_touch(self, name, on_gesture):
        return None


class _Cap:
    def __init__(self, opts):
        self.opts, self.slow, self.last_src = opts, False, None

    def grab(self):
        import project
        a = area(self.opts)
        if not a:
            return None
        im = ImageGrab.grab(bbox=(a[0], a[1], a[0] + a[2], a[1] + a[3]), all_screens=True).convert("RGB")
        size = im.size
        self.last_src = f"screen {size[0]}x{size[1]}"
        return Fit(size, project_size(), (self.opts or {}).get("fit") or "stretch").image(np.asarray(im)), self.last_src, size
