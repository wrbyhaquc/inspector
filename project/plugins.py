"""Plugins (外掛): what a project adds to the platform without the platform knowing about it.

A plugin is a folder with a plugin.py that defines register(reg): the active pack's plugin/ (data folder layout) or
<app folder>/packs/<name>/. The project names the plugins it uses (project.json "plugins"). register() adds things
to the registry by kind:

  rule          screen rule types (an algorithm that answers a state from the frame)
  label_source  more answers for 自動標註 besides the screen rules (e.g. data a device reports itself)
  source        a device driver: where frames come from and where actions go (drivers/__init__.py; a class
                taking params, declaring what it can do in caps)
  notify        notification channel types (notify/channels.py has the built-in ones)
  output        a kind of output scripts send to (automation/outputs.py): a class with label, fields, send()
  recorder      what the collector records beside the screen (collector/collector.py), a factory fn(collector)
  gallery_cut   how a name gallery cuts its row (labeler/gallery.py): fn(img, box, params) -> (x0, x1) or None
  api           a FastAPI router, served at /api/plugins/<name>/ (the plugin's own tools)

    def register(reg):
        reg.add("notify", "telegram", Telegram, label="Telegram")

The platform itself only asks the registry ("which rule types are there?"); it never names a plugin."""
import importlib
import importlib.util
import os
import sys

from . import APP_DIR, load, pack_dir, pack_info
from i18n import N_, _

KINDS = {"rule": N_("畫面規則"), "label_source": N_("標註來源"), "source": N_("裝置來源"), "output": N_("輸出種類"), "notify": N_("通知管道"),
         "api": N_("網頁 API"),
         "gallery_cut": N_("名稱庫切割方式"), "recorder": N_("收集時另外記錄")}
PACKS = os.path.join(APP_DIR, "packs")


def plugin_dir(name):
    """Where plugin <name> is: inside the active pack when that pack carries it, else <app folder>/packs/<name>."""
    d = pack_dir()
    if d and pack_info().get("plugin", name) == name and os.path.exists(os.path.join(d, "plugin", "plugin.py")):
        return os.path.join(d, "plugin")
    return os.path.join(PACKS, name)


def mount(name):
    """Make plugin <name> importable as the package packs.<name>, wherever its folder is (worker processes call this
    through packs/__init__.py, so pickled plugin objects load there too)."""
    full = f"packs.{name}"
    d = plugin_dir(name)
    importlib.import_module("packs")                  # its __init__ mounts the active pack's plugin first
    if full in sys.modules or os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.join(PACKS, name)):
        return
    spec = importlib.util.spec_from_file_location(full, os.path.join(d, "__init__.py"), submodule_search_locations=[d])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    try:
        spec.loader.exec_module(mod)
        setattr(sys.modules["packs"], name, mod)
    except BaseException:
        sys.modules.pop(full, None)
        raise


class Registry:
    def __init__(self):
        self.items = {k: {} for k in KINDS}
        self.labels = {k: {} for k in KINDS}
        self.loaded = []                  # [{"name", "ok", "error"}]
        self._current = None

    def add(self, kind, name, obj, label=None):
        if kind not in KINDS:
            raise ValueError(_("沒有「{kind}」這種外掛點", kind=kind))
        if name in self.items[kind]:
            raise ValueError(_("{p1}「{name}」已經有了(外掛 {_current} 想再加一次)", p1=_(KINDS[kind]), name=name, _current=self._current))
        self.items[kind][name] = obj
        self.labels[kind][name] = label or name

    def get(self, kind, name):
        return self.items[kind].get(name)

    def all(self, kind):
        return dict(self.items[kind])


def ui(reg):
    """Texts the pages show for plugin things: flag meanings, what each region of a plugin rule is read for, the
    names of the label-source kinds."""
    flags, roi_uses = {}, {}
    for kind in ("rule", "label_source"):
        for obj in reg.all(kind).values():
            flags.update(getattr(obj, "FLAG_TEXTS", None) or {})
            roi_uses.update(getattr(obj, "ROI_USES", None) or {})
    return {"flags": flags, "rule_roi_uses": roi_uses, "source_kinds": dict(reg.labels["label_source"])}


_reg = None
_for = None


def registry(root=None):
    """The registry of the current project's plugins (loaded once per project)."""
    global _reg, _for
    names = tuple(load(root).get("plugins") or [])
    if _reg is not None and _for == names:
        return _reg
    reg = Registry()
    blocked = None
    if pack_dir():                                    # a pack that cannot run on this Inspector loads no plugin
        from . import manifest
        errors = [t for lv, t in manifest.check(pack_info(), pack_dir()) if lv == "error"]
        blocked = "; ".join(errors) or None
    for name in names:
        path = os.path.join(plugin_dir(name), "plugin.py")
        reg._current = name
        try:
            if blocked and plugin_dir(name) != os.path.join(PACKS, name):
                raise RuntimeError(blocked)
            if not os.path.exists(path):
                raise FileNotFoundError(_("找不到 {path}", path=path))
            if APP_DIR not in sys.path:                  # packs.<name> is a package (worker processes import it too)
                sys.path.insert(0, APP_DIR)
            mount(name)
            mod = importlib.import_module(f"packs.{name}.plugin")
            mod.register(reg)
            reg.loaded.append({"name": name, "ok": True, "error": None})
        except Exception as e:            # a broken plugin must not take the platform down
            reg.loaded.append({"name": name, "ok": False, "error": str(e)})
            print(_("外掛「{name}」載入失敗:{e}", name=name, e=e), flush=True)
    reg._current = None
    _reg, _for = reg, names
    return reg
