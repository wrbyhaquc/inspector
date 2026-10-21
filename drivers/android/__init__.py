"""Category "android" (Android 裝置): anything Android that adb reaches - emulators of any brand, phones, boxes.

One category, many presets (細項). A preset is only a set of suggested settings; every setting can be changed (進階
設定), and a preset may offer what one product can do better (LDPlayer: its console names the instances, its window
can be copied, it types Chinese). Nothing here is about one app or one use.

Settings (params) - see PARAMS:
  discovery    how devices are found and named: "adb" (adb devices, after connecting to "ports") or "ldconsole"
  capture      "window" (copy the emulator's window: fast, costs the emulator nothing; falls back to adb when allowed)
               or "adb" (screencap inside Android: always works, slower)
  window_*     which window is the device's (title may use {name}: the device's own name)
  text_input   "adb" (ASCII only) or "ldconsole" (LDPlayer: any text)
  touch_watch  read the touch screen (getevent): a person operating it pauses the scripts
Input (tap, long press, swipe, back, launch, text) goes through adb; Android framework input, never seen by getevent."""
import re
import subprocess
import time

import numpy as np
from PIL import Image

from .. import Device
from . import ldconsole, paths, screen
from .touch import TouchRecorder
from i18n import N_, _

LABEL = N_("Android 裝置")
CAPTURE = {"window": N_("視窗擷取(不拖慢,建議)"), "adb": N_("裝置內截圖(較慢,會拖慢模擬器)")}
PARAMS = {
    "discovery": {"label": N_("怎麼找到裝置"), "type": "select", "options": {"adb": N_("adb 裝置清單"), "ldconsole": N_("雷電的 ldconsole(名字好認)")}},
    "ports": {"label": N_("也連這些埠號(127.0.0.1)"), "type": "text", "help": N_("模擬器的 adb 埠號,用逗號分開;空白 = 只看已連上的")},
    "capture": {"label": N_("取畫面的方式"), "type": "select", "options": CAPTURE},
    "window_title": {"label": N_("視窗標題"), "type": "text", "help": N_("{name} = 裝置的名字;空白 = 不用視窗擷取")},
    "window_title_mode": {"label": N_("標題比對"), "type": "select", "options": {"exact": N_("完全相同"), "contains": N_("包含")}},
    "window_class": {"label": N_("視窗類別"), "type": "text", "help": N_("可不填")},
    "window_child": {"label": N_("畫面所在的子視窗類別"), "type": "text", "help": N_("可不填")},
    "text_input": {"label": N_("輸入文字的方式"), "type": "select", "options": {"adb": N_("adb(只能英數)"), "ldconsole": N_("雷電的輸入介面(可輸入中文)")}},
    "touch_watch": {"label": N_("偵測有人在操作"), "type": "bool", "help": N_("讀觸控事件:有人在操作時腳本先讓開")},
    "adb": {"label": N_("adb.exe 的位置"), "type": "text", "help": N_("空白 = 自動找")},
    "ldplayer_dir": {"label": N_("雷電安裝資料夾"), "type": "text", "help": N_("空白 = C:\\LDPlayer\\LDPlayer9")},
}
BASE = {"discovery": "adb", "ports": "", "capture": "adb", "window_title": "", "window_title_mode": "exact", "window_class": "",
        "window_child": "", "text_input": "adb", "touch_watch": True, "adb": "", "ldplayer_dir": ""}
# presets: suggested settings for one product (order: the ones that know their devices best claim them first);
# window_signature: what its windows look like (program / class), so a window scan can tell "this is that emulator"
PRESETS = {
    "ldplayer": {"label": N_("雷電模擬器(LDPlayer 9)"), "order": 0, "params": {
        "discovery": "ldconsole", "capture": "window", "window_title": "{name}", "window_class": "LDPlayerMainFrame",
        "window_child": "RenderWindow", "text_input": "ldconsole"},
        "shows": ["discovery", "capture", "text_input", "touch_watch", "ldplayer_dir", "window_title", "window_class", "window_child"],
        "note": N_("建議用 ldconsole 找模擬器(名字就是雷電裡的名字)、視窗擷取(不拖慢模擬器)、雷電的輸入介面(可輸入中文)"),
        "window_signature": {"process": ["dnplayer.exe"], "class": ["LDPlayerMainFrame"]}},
    "mumu": {"label": N_("MuMu 模擬器"), "order": 1, "params": {"ports": "16384,16416,16448,16480,16512,16544,7555"},
             "shows": ["ports", "capture", "window_title", "window_title_mode", "window_class", "window_child", "touch_watch", "adb"],
             "note": N_("MuMu 12 第一台的埠號是 16384,之後每台加 32;要用視窗擷取,填 MuMu 視窗的標題"),
             "window_signature": {"process": ["MuMuPlayer.exe", "MuMuNxDevice.exe", "NemuPlayer.exe"]}},
    "bluestacks": {"label": "BlueStacks", "order": 1, "params": {"ports": "5555,5565,5575,5585"},
                   "shows": ["ports", "capture", "window_title", "window_title_mode", "window_class", "window_child", "touch_watch", "adb"],
                   "note": N_("在 BlueStacks 設定裡打開 adb;埠號顯示在同一頁"), "window_signature": {"process": ["HD-Player.exe"]}},
    "nox": {"label": N_("夜神模擬器(Nox)"), "order": 1, "params": {"ports": "62001,62025,62026,62027"}, "window_signature": {"process": ["Nox.exe"]},
            "shows": ["ports", "capture", "window_title", "window_title_mode", "window_class", "window_child", "touch_watch", "adb"]},
    "memu": {"label": N_("逍遙模擬器(MEmu)"), "order": 1, "params": {"ports": "21503,21513,21523,21533"}, "window_signature": {"process": ["MEmu.exe"]},
             "shows": ["ports", "capture", "window_title", "window_title_mode", "window_class", "window_child", "touch_watch", "adb"]},
    "phone": {"label": N_("手機 / 平板(USB 或 Wi-Fi adb)"), "order": 2, "params": {"touch_watch": False},
              "shows": ["ports", "touch_watch", "adb"], "note": N_("手機要先打開「USB 偵錯」;Wi-Fi 的話在埠號填手機顯示的位置")},
    "other": {"label": N_("其他(自己設定)"), "order": 3, "params": {}, "shows": list(PARAMS)},
}


def preset_params(preset, params=None):
    """Every setting: the base, the preset's suggestion, then what was set."""
    out = {**BASE, **(PRESETS.get(preset) or {}).get("params", {})}
    for k, v in (params or {}).items():
        if k in PARAMS and v not in (None, ""):
            out[k] = (str(v).lower() in ("1", "true", "on", "yes")) if PARAMS[k]["type"] == "bool" else str(v)
    return out


class Capture:
    def __init__(self, drv, name, prefer, fallback):
        import project
        self.drv, self.name, self.fallback = drv, name, fallback
        p = drv.p
        self.win = None
        if prefer == "window" and p["window_title"]:
            from ..windows import WindowCapture
            spec = {"title": p["window_title"].replace("{name}", name), "title_mode": p["window_title_mode"],
                    "class": p["window_class"], "child_class": p["window_child"]}
            self.win = WindowCapture(spec, size=project.screen())
        self.slow = False
        self.last_src = None

    def grab(self):
        import project
        img = src = size = None
        if self.win:
            got = self.win.grab()
            if got:
                img, size = got
                src = f"window {size[0]}x{size[1]}"
        if img is None and (self.fallback or not self.win):
            serial = self.drv.serial(self.name)
            if serial:
                img = screen.grab(self.drv.adb, serial)
                if img is not None:
                    size, src = (img.shape[1], img.shape[0]), "adb"
                    want = project.screen()
                    if size != want:
                        img = np.asarray(Image.fromarray(img).resize(want, Image.BICUBIC))
        if img is None:
            return None
        self.slow = src == "adb"
        self.last_src = src
        return img, src, size


class Android:
    label = LABEL
    capture_modes = CAPTURE

    def __init__(self, params=None, preset="other"):
        self.preset = preset
        self.p = preset_params(preset, params)
        self.adb = paths.adb(self.p)
        self.serials, self.extra, self.last_scan = {}, {}, 0.0
        self.skip = set()                 # adb serials a preset that knows them better already has (sources.py)

    @property
    def caps(self):
        c = {"screen", "tap", "long_press", "swipe", "back", "launch", "text"}
        return c | ({"touch_watch"} if self.p["touch_watch"] else set())

    def _run(self, args, timeout=10):
        r = subprocess.run([self.adb, *args], capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")

    def _props(self, serial):
        out = self._run(["-s", serial, "shell", "getprop ro.product.model; wm size"], timeout=5)
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        size = None
        for x in lines:
            m = re.search(r"(\d+)x(\d+)", x)
            if "size" in x.lower() and m:
                size = (int(m[1]), int(m[2]))            # an override comes after the physical size: the last wins
        model = next((x for x in lines if "size" not in x.lower()), "")
        return model, size

    def list(self):
        if self.p["discovery"] == "ldconsole":
            insts = ldconsole.list_instances(paths.ldconsole(self.p))
            ldconsole.attach_adb(insts, self.adb)
            self.serials = {i.name: i.adb_serial for i in insts if i.adb_serial}
            self.last_scan = time.time()
            return [Device(i.name, ok=bool(i.adb_serial), detail=f"adb {i.adb_serial}" if i.adb_serial else _("沒有 adb"),
                           pid=i.vbox_pid, size=(i.width, i.height), info={"index": i.index, "adb": i.adb_serial})
                    for i in insts if i.adb_serial not in self.skip]
        def connect(port):
            try:
                self._run(["connect", f"127.0.0.1:{port}"], timeout=2)
            except Exception:
                pass
        ports_ = [int(x) for x in re.findall(r"\d+", self.p["ports"] or "")]
        if ports_:                                        # all at once: one closed port no longer waits for the next
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(8, len(ports_))) as ex:
                list(ex.map(connect, ports_))
        online = [m.group(1) for m in re.finditer(r"^(\S+)\s+device\b", self._run(["devices"]), re.M)]
        ports = {int(x) for x in re.findall(r"\d+", self.p["ports"] or "")}
        short = (PRESETS.get(self.preset) or {}).get("label", "Android").split("(")[0].split(" ")[0]
        out, serials = [], {}
        for s in online:
            if s in self.skip:
                continue
            port = int(s.rsplit(":", 1)[1]) if re.fullmatch(r"[\d.]+:\d+", s) else None
            if ports and self.preset not in ("phone", "other") and port not in ports:
                continue                                  # a brand's preset: only its own ports
            try:
                model, size = self._props(s)
            except Exception:
                model, size = "", None
            name = f"{short}-{port or s}"
            serials[name] = s
            out.append(Device(name, ok=True, detail=f"adb {s}" + (f" · {model}" if model else ""), size=size,
                              info={"adb": s, "model": model}))
        self.serials, self.last_scan = serials, time.time()
        return out

    def serial(self, name):
        if name not in self.serials or time.time() - self.last_scan > 60:
            try:
                self.list()
            except Exception:
                self.last_scan = time.time()
        return self.serials.get(name)

    def window_spec(self, name):
        """The window that shows device `name` (drivers/windows.py spec), or None: a window scan then knows that window
        is this device, not another source."""
        p = self.p
        if not p["window_title"]:
            return None
        return {"title": p["window_title"].replace("{name}", name), "title_mode": p["window_title_mode"],
                "class": p["window_class"], "child_class": p["window_child"]}

    def capture(self, name, prefer="window", fallback=True):
        return Capture(self, name, prefer if self.p["capture"] == "window" else "adb", fallback)

    def input(self, name, kind, **p):
        if kind == "tap":
            args = ["input", "tap", int(p["x"]), int(p["y"])]
        elif kind == "long_press":
            args = ["input", "swipe", int(p["x"]), int(p["y"]), int(p["x"]), int(p["y"]), int(p.get("ms", 800))]
        elif kind == "swipe":
            args = ["input", "swipe", int(p["x1"]), int(p["y1"]), int(p["x2"]), int(p["y2"]), int(p.get("ms", 400))]
        elif kind == "back":
            args = ["input", "keyevent", "4"]
        elif kind == "launch":                      # start the app, or bring it to the front if it is running
            pkg = str(p["package"])
            if not re.fullmatch(r"[A-Za-z0-9_.]+", pkg):
                raise ValueError(_("App 名稱不正確"))
            args = ["monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]
        elif kind == "text":                        # into the text box that has the focus
            text = str(p["text"])
            if text and all(32 <= ord(c) < 127 for c in text):
                # Android's input command: ASCII only; spaces as %s, everything else quoted for the shell
                args = ["input", "text", "'" + text.replace(" ", "%s").replace("'", "'\\''") + "'"]
            elif self.p["text_input"] == "ldconsole":
                ldconsole.text_input(paths.ldconsole(self.p), name, text)
                return True
            else:
                raise RuntimeError(_("adb 只能輸入英文、數字和符號;要輸入中文,請在來源的進階設定選有輸入介面的方式(例如雷電)"))
        else:
            raise ValueError(kind)
        s = self.serial(name)
        if not s:
            raise RuntimeError(_("{name} 沒有 adb 連線", name=name))
        r = subprocess.run([self.adb, "-s", s, "shell", *map(str, args)], capture_output=True, timeout=20)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or _("adb 失敗"))
        return True

    def watch_touch(self, name, on_gesture):
        if not self.p["touch_watch"]:
            return None
        s = self.serial(name)
        return TouchRecorder(s, on_gesture, name, self.adb) if s else None
