"""Device drivers (裝置轉接器): where the frames come from and where the actions go.

Sources are grouped by where the picture comes from (categories: android, video, a plugin's); a category has presets
(細項) - suggested settings for one product, e.g. android/ldplayer, android/mumu - and every setting can be changed
(進階設定). A kind is "<category>/<preset>". Which kinds are on, which devices are used, what they are called and where
their actions go is set where it runs (drivers/sources.py: 來源); current() is the one driver the collector, the
script runner and the web pages talk to - every enabled source, by its id - through this interface:

  label                          what the pages call it
  caps                           what it can do (CAPS below); a script using what it cannot do is refused when saved
  list()                         -> [Device] running now
  capture(name, prefer, fallback) -> Capture: grab() -> (image in the project's coordinate space, how it was taken,
                                  native (w, h)) or None; .slow = the last grab was costly (take them less often)
  input(name, kind, **p)         do one action now (kind in CAPS: tap, long_press, swipe, back, launch, text); raises on
                                  failure
  watch_touch(name, on_gesture)  -> an object with start(), close(), last_touch, last_event: a person's touches on the
                                  device (for 操作中 / pausing scripts while someone operates it), or None

Built in: android (anything adb reaches; presets LDPlayer - its console names instances, its window is copied, it
types Chinese -, MuMu, BlueStacks, Nox, MEmu, phones, other), window (any program's window; mouse and keyboard),
screen (a rectangle of a screen), stream (RTSP / HTTP / USB cameras, NVR channels: a picture only), video (video
files played as sources: frames only) and recording (this project's own recordings played back: frames only).
A category whose sources each need their own settings (a window's title, a screen rectangle) declares per_source and
find(opts) -> Device | None; capture() and input() then also get opts (the source's own settings).
A project's plugin can add a category (registry kind "source": a class taking (params, preset), with PRESETS)."""
from dataclasses import dataclass, field
from i18n import N_, _, tr

CAPS = {"screen": N_("取得畫面"), "tap": N_("點擊"), "long_press": N_("長按"), "swipe": N_("滑動"), "back": N_("返回鍵"),
        "launch": N_("啟動 App"), "text": N_("輸入文字"), "touch_watch": N_("偵測有人操作")}


@dataclass
class Device:
    name: str
    ok: bool = True              # can be captured / controlled now
    detail: str = ""             # shown on the pages, e.g. "adb emulator-5562"
    pid: int = None              # the process behind it on this computer (lets a recorder find its connections)
    size: tuple = None           # native screen size
    info: dict = field(default_factory=dict)


class NotSupported(RuntimeError):
    pass


class Kind:
    """One preset of one category (kind id "<category>/<preset>"): called with its settings it makes the driver."""

    def __init__(self, cat_id, cat, preset_id, preset):
        self.id = f"{cat_id}/{preset_id}"
        self.category, self.category_label = cat_id, cat["label"]
        self.preset, self.preset_label = preset_id, preset.get("label", preset_id)
        self.label = preset.get("label", preset_id) if preset_id != "default" else cat["label"]
        self.cls, self.order = cat["cls"], preset.get("order", 1)
        self.note = preset.get("note", "")
        self.signature = preset.get("window_signature") or {}    # what this product's windows look like
        self.manual = bool(preset.get("manual"))                   # added by typing its settings (an address), not found
        self.defaults = dict(preset.get("params") or {})
        allp = cat.get("params") or {}
        self.params = {k: allp[k] for k in (preset.get("shows") or allp) if k in allp}     # the 進階設定 it offers
        self.capture_modes = getattr(cat["cls"], "capture_modes", {}) or {}
        self.per_source = getattr(cat["cls"], "per_source", None) or {}    # settings each source of it has (a window's title ...)

    def __call__(self, params=None):
        try:
            return self.cls(params or {}, self.preset)
        except TypeError:                                  # a plugin's class taking only params
            return self.cls(params or {})

    @property
    def caps(self):
        return self.caps_with(None)

    def caps_with(self, params):
        c = getattr(self.cls, "caps", None)
        if isinstance(c, (set, frozenset, list, tuple)):
            return set(c)
        try:
            return set(self(params).caps)
        except Exception:
            return set()


def categories():
    """category id -> {"label", "cls", "params": {name: {"label", "type", "options", "help"}}, "presets": {...}}.
    Built in: android, video. A plugin adds a category with registry kind "source": a class with label, caps,
    params ({name: label} or the full form) and optionally PRESETS."""
    from . import android, desktop, recording, stream, video, window
    from project.plugins import registry
    out = {"android": {"label": android.LABEL, "cls": android.Android, "params": android.PARAMS, "presets": android.PRESETS},
           "window": {"label": window.LABEL, "cls": window.Window, "params": window.PARAMS, "presets": window.PRESETS},
           "screen": {"label": desktop.LABEL, "cls": desktop.Desktop, "params": desktop.PARAMS, "presets": desktop.PRESETS},
           "stream": {"label": stream.LABEL, "cls": stream.Stream, "params": stream.PARAMS, "presets": stream.PRESETS},
           "video": {"label": video.LABEL, "cls": video.VideoFiles, "params": video.PARAMS, "presets": video.PRESETS},
           "recording": {"label": recording.LABEL, "cls": recording.Recording, "params": recording.PARAMS, "presets": recording.PRESETS}}
    for name, cls in registry().all("source").items():
        ps = getattr(cls, "params", {}) or {}
        ps = {k: (v if isinstance(v, dict) else {"label": v, "type": "text"}) for k, v in ps.items()}
        out[name] = {"label": getattr(cls, "label", name), "cls": cls, "params": ps,
                     "presets": getattr(cls, "PRESETS", None) or {"default": {"label": getattr(cls, "label", name), "params": {}}}}
    return out


def kinds():
    """kind id ("<category>/<preset>") -> Kind, in the order presets claim devices (the best informed first)."""
    out = {}
    for cid, cat in categories().items():
        for pid, p in cat["presets"].items():
            k = Kind(cid, cat, pid, p)
            out[k.id] = k
    return dict(sorted(out.items(), key=lambda kv: kv[1].order))


OLD_KINDS = {"ldplayer": "android/ldplayer", "adb": "android/other", "video": "video/files"}     # before categories


def config(root=None):
    """(kind, params) of the first kind in use (older pages / tools that know only one); ("", {}) when none is."""
    from . import sources
    cfg = sources.load(root)
    use = sources.in_use(cfg)
    return (use[0], (cfg["kinds"].get(use[0]) or {}).get("params") or {}) if use else ("", {})


_cur = {}


def current(root=None):
    """The sources of this computer as one driver (drivers/sources.py)."""
    from . import sources
    key = root or ""
    if key not in _cur:
        _cur[key] = sources.Sources(root)
    return _cur[key]


# what a script step / action needs from the driver
STEP_NEEDS = {"tap": ("tap",), "long_press": ("long_press",), "swipe": ("swipe",), "back": ("back",),
              "launch_app": ("launch",), "pick": ("tap", "swipe"), "capture_list": ("swipe",), "input_text": ("text",)}


def check_script(obj, what, root=None):
    """Raise ValueError when a script / sub-script has a step or action its sources cannot do: a main script against
    the sources it runs on for real (正式執行; every enabled one when that is the default), a sub-script against what
    any source can do."""
    from . import sources
    try:
        d = current(root)
        cfg = sources.load(root)
    except (RuntimeError, OSError):
        return
    have = kinds()
    by_id = {it["id"]: it for it in cfg["items"]}
    on = {it["id"] for it in cfg["items"] if it.get("enabled")}
    deployed = obj.get("devices") if isinstance(obj.get("devices"), dict) else None
    if deployed is not None:
        # only where it runs for real: a trial (試跑) never acts, so a source that only watches may run it
        ids = {i for i in by_id if sources.mode_of(deployed, i, root) == "live" and (i in on or i in deployed)}
        targets = [(i, sources.caps_of(i, root)) for i in sorted(ids) if i in by_id]
    else:
        targets = [("", d.caps)]
    found = set()

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") in STEP_NEEDS:
                found.add(x["type"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    for t in sorted(found):
        for cap in STEP_NEEDS[t]:
            for dev, caps in targets:
                if caps and cap not in caps:
                    if dev:
                        raise ValueError(_("{what}:部署在「{p2}」,但它不能{p3}(動作:{p4}),用不了這個腳本裡的步驟(到「部署」把它改成試跑或關閉,或在「來源」改它的動作要送到哪裡)", what=what, p2=sources.label(dev, root), p3=_(CAPS.get(cap, cap)), p4=sources.hand_text(by_id[dev], root)))
                    raise ValueError(_("{what}:目前沒有任何來源能{p2},用不了這個腳本裡的步驟", what=what, p2=_(CAPS.get(cap, cap))))


def describe():
    """For the pages: categories, each with its presets (label, note, what it can do, its 進階設定 and suggestions)."""
    out = {}
    for kid, k in kinds().items():
        out[kid] = {"label": _(k.label), "category": k.category, "category_label": _(k.category_label), "preset": k.preset,
                    "note": _(k.note), "caps": sorted(k.caps), "params": tr(k.params), "defaults": k.defaults,
                    "capture_modes": tr(k.capture_modes), "per_source": tr(k.per_source), "manual": k.manual,
                    "has_hand": bool(set(k.caps) & {"tap", "swipe", "back", "text"})}
    return out
