"""Category "window" (應用程式視窗): any program's window on this computer - an NVR client, a browser, office
software. Its picture is copied from Windows (drivers/windows.py); its hand is mouse and keyboard (drivers/winput.py).

Each source is one window, found by its own settings (SOURCE_PARAMS, kept on the source): title (exact or a part of
it), program, window class, the child window that holds the picture, and the part of the window to keep (region).
A window whose title changes (a browser tab) is best found by a part of its title or by its program.

Positions: the picture is put into the project's coordinate space the way the source's "fit" says (drivers/fit.py);
a tap there is mapped back to the window's own pixels (and the region) with the same numbers, whatever size the
window has now."""
import ctypes
import ctypes.wintypes as W
import json

from . import Device, winput, windows
from .fit import Fit, project_size
from i18n import N_, _

LABEL = N_("應用程式視窗")
PARAMS = {
    "input": {"label": N_("動作怎麼送"), "type": "select", "options": {
        "message": N_("背景送訊息(不動滑鼠,視窗可在後面;有些程式不吃)"), "mouse": N_("真的移動滑鼠(視窗會被拉到最前面)")}},
    "back_key": {"label": N_("「返回」用哪個鍵"), "type": "select", "options": {"esc": "Esc", "back": "Backspace", "none": N_("不支援")}},
    "only": {"label": N_("掃描時只列這些程式"), "type": "text", "help": N_("程式名稱用逗號分開,例如 chrome.exe,msedge.exe;空白 = 全部")},
}
SOURCE_PARAMS = {
    "title": {"label": N_("視窗標題"), "type": "text"},
    "title_mode": {"label": N_("標題比對"), "type": "select", "options": {"exact": N_("完全相同"), "contains": N_("包含這段文字")}},
    "process": {"label": N_("程式名稱"), "type": "text", "help": N_("例如 chrome.exe;可不填")},
    "class": {"label": N_("視窗類別"), "type": "text", "help": N_("可不填")},
    "child_class": {"label": N_("畫面所在的子視窗類別"), "type": "text", "help": N_("可不填")},
    "region": {"label": N_("只取一塊(x,y,寬,高)"), "type": "text", "help": N_("視窗自己的像素;空白 = 整個視窗")},
    "fit": {"label": N_("畫面怎麼放進專案的大小"), "type": "select", "options": {"contain": N_("等比例,補黑邊(不變形,建議)"), "stretch": N_("拉伸填滿(形狀不同會變形)"), "cover": N_("等比例填滿,裁掉多的部分")}},
}
PRESETS = {
    "any": {"label": N_("任意程式"), "order": 5, "params": {"input": "message", "back_key": "esc"}, "shows": ["input", "back_key", "only"],
            "note": N_("掃描後挑一個視窗;之後用標題(或其中一段)和程式名稱找它。被縮到最小時拿不到畫面")},
    "browser": {"label": N_("瀏覽器分頁(Chrome、Edge、Firefox)"), "order": 5,
                "params": {"input": "mouse", "back_key": "none", "only": "chrome.exe,msedge.exe,firefox.exe"},
                "shows": ["input", "back_key", "only"],
                "note": N_("分頁標題會變:建議用標題裡不變的一段(包含)加程式名稱;瀏覽器多半要「真的移動滑鼠」才點得到")},
}


def _region(opts):
    r = str((opts or {}).get("region") or "").replace("，", ",")
    try:
        v = [int(float(x)) for x in r.split(",")] if r.strip() else None
        return v if v and len(v) == 4 and v[2] > 0 and v[3] > 0 else None
    except ValueError:
        return None


def spec_of(opts):
    o = opts or {}
    return {"title": o.get("title") or "", "title_mode": o.get("title_mode") or "exact", "process": o.get("process") or "",
            "class": o.get("class") or "", "child_class": o.get("child_class") or ""}


class Window:
    label = LABEL
    caps = {"screen", "tap", "long_press", "swipe", "back", "text"}
    capture_modes = {"window": N_("視窗擷取")}
    per_source = SOURCE_PARAMS

    def __init__(self, params=None, preset="any"):
        self.preset = preset
        self.p = {**(PRESETS.get(preset) or {}).get("params", {}), **{k: v for k, v in (params or {}).items() if v not in (None, "")}}
        self.caps = {"screen", "tap", "long_press", "swipe", "text"} | ({"back"} if self.p.get("back_key", "esc") != "none" else set())

    def list(self):
        """Every visible window (to pick from); each says the settings that would find it again."""
        only = {x.strip().lower() for x in str(self.p.get("only") or "").split(",") if x.strip()}
        out = []
        for w in windows.windows():
            if only and w["process"].lower() not in only:
                continue
            mini = bool(windows._u.IsIconic(w["hwnd"]))
            if not mini and (w["size"][0] < 64 or w["size"][1] < 36):
                continue
            name = f"{w['title'][:60]}"
            out.append(Device(name, ok=not mini, detail=f"{w['process']} · {w['class']}" + (_(" · 目前縮到最小(拿不到畫面)") if mini else ""),
                              size=None if mini else w["size"], pid=w["pid"],
                              info={"fit": "contain", "opts": {"title": w["title"], "title_mode": "contains", "process": w["process"], "class": w["class"], "fit": "contain"}}))
        return sorted(out, key=lambda d: not d.ok)          # the ones on screen first

    def find(self, opts):
        """The window a source's settings point at now -> Device (named by its title) or None."""
        top, render = windows.find(spec_of(opts))
        if not render:
            return None
        r = W.RECT()
        windows._u.GetClientRect(render, ctypes.byref(r))
        size = (r.right, r.bottom)
        reg = _region(opts)
        return Device(windows.text(top)[:60] or _("(沒有標題)"), ok=not windows._u.IsIconic(top), info={"fit": (opts or {}).get("fit") or "stretch"},
                      detail=f"{windows.process(top)[0]}" + (_(" · 被縮到最小") if windows._u.IsIconic(top) else ""),
                      size=(reg[2], reg[3]) if reg else size, pid=windows.process(top)[1])

    def capture(self, name, prefer=None, fallback=True, opts=None):
        return _Cap(windows.WindowCapture(spec_of(opts), size=None, region=_region(opts)), (opts or {}).get("fit") or "stretch")

    def _where(self, opts, x, y):
        """Project coordinates -> (window to send to, its own pixels)."""
        top, render = windows.find(spec_of(opts))
        if not render:
            raise RuntimeError(_("找不到這個視窗(關掉了,或標題變了:到「來源」改它的設定)"))
        r = W.RECT()
        windows._u.GetClientRect(render, ctypes.byref(r))
        reg = _region(opts) or [0, 0, r.right, r.bottom]
        nx, ny = Fit((reg[2], reg[3]), project_size(), (opts or {}).get("fit") or "stretch").to_native(x, y)
        return top, render, reg[0] + nx, reg[1] + ny

    def input(self, name, kind, opts=None, **p):
        mode = self.p.get("input", "message")
        if kind in ("tap", "long_press"):
            top, h, x, y = self._where(opts, p["x"], p["y"])
            ms = int(p.get("ms", 800)) if kind == "long_press" else 60
            if mode == "mouse":
                winput.bring_front(top)
                winput.mouse_press(*winput.to_screen(h, x, y), ms=ms)
            else:
                winput.msg_press(h, x, y, ms=ms)
        elif kind == "swipe":
            top, h, x1, y1 = self._where(opts, p["x1"], p["y1"])
            _x, _x, x2, y2 = self._where(opts, p["x2"], p["y2"])
            if mode == "mouse":
                winput.bring_front(top)
                a, b = winput.to_screen(h, x1, y1), winput.to_screen(h, x2, y2)
                winput.mouse_drag(a[0], a[1], b[0], b[1], ms=int(p.get("ms", 400)))
            else:
                winput.msg_drag(h, x1, y1, x2, y2, ms=int(p.get("ms", 400)))
        elif kind in ("back", "text"):
            top, h, _x, _x = self._where(opts, 0, 0)
            if kind == "back":
                key = self.p.get("back_key", "esc")
                if key == "none":
                    raise RuntimeError(_("這個來源沒有「返回」"))
                winput.bring_front(top) if mode == "mouse" else None
                (winput.key_press if mode == "mouse" else lambda k: winput.msg_key(h, k))(key)
            else:
                if mode == "mouse":
                    winput.bring_front(top)
                    winput.key_text(str(p["text"]))
                else:
                    winput.msg_text(h, str(p["text"]))
        else:
            raise RuntimeError(_("視窗不能{kind}", kind=kind))
        return True

    def watch_touch(self, name, on_gesture):
        return None


class _Cap:
    def __init__(self, wc, fit):
        self.wc, self.fit, self.slow, self.last_src = wc, fit, False, None

    def grab(self):
        got = self.wc.grab()
        if not got:
            return None
        img, size = got
        self.last_src = f"window {size[0]}x{size[1]}"
        return Fit(size, project_size(), self.fit).image(img), self.last_src, size


def opts_key(opts):
    return json.dumps(spec_of(opts), sort_keys=True, ensure_ascii=False)
