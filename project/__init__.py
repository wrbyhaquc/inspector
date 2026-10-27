"""Where the work is (專案) and what it is about. Everything that differs between one use of the platform and another
(an app on emulators, a fish pond on cameras) is set here or in the project's own data - never in the code.

Two levels:
  this machine   ~/.inspector/inspector.json (~/.config/inspector/ outside Windows; INSPECTOR_CONFIG names
                 another file): paths on this computer. Never in the program folder, so replacing the program keeps it;
                 one left there by an older version is moved on the first start.
                 {"project": "<project folder>", "runtime": "<folder on a fast disk for the files rewritten every tick>",
                  "ldplayer_dir": "<LDPlayer install folder, for the ldplayer driver>"}
                 INSPECTOR_PROJECT / INSPECTOR_RUNTIME in the environment override them.
  the project    <project folder>/project.json  (part of the design: it travels with the project / a pack)
                 {"id", "name", "description",
                  "screen": {"width", "height"},   the coordinate space: every frame is brought to this size, every
                                                   position (buttons, regions, taps) is in it
                  "app": {"package"},              what the 啟動 App step starts when it names none (may be empty)
                  "words": {"device": "裝置", "item": "項目", ...},   what the pages call things in this project
                  "devices": {"driver", "params"},  the kind of source a new computer starts with; after that the
                                                   來源 page decides (<runtime>/sources.json, drivers/sources.py)
                  "sources": {"<id>": {"kind", "name", "params"}},  the sources the design uses, made so on a new
                                                   computer (e.g. a camera's stream address); nothing else found
                                                   there is added (or announced) on its own then
                  "run": {"interval", "max_per_min", "confirm"},  how the design is meant to run (a scene that
                                                   must react quickly: 0.3 s, 60 actions a minute, confirm 1 = act on the first look
                                                   instead of two alike) - the defaults here; what is set on this
                                                   computer wins, and the platform's limits hold (run_defaults())
                  "plugins": ["<name>", ...]}      packs/<name>/ to load (rules, label sources, sources, outputs ...)
Without any of these, the data folder layout below is used in <that same folder>/data (made on first use).
"project" (or INSPECTOR_PROJECT) keeps an older single project folder working; its runtime folder is then "runtime"
or <project>/.runtime.

The data folder layout (inspector.json "data", or INSPECTOR_DATA) keeps every pack apart from the platform and from
each other; the platform folder then holds code only:
  <data>/active.json             {"pack": "<id>"}   which pack runs (INSPECTOR_PACK overrides it)
  <data>/packs/<id>/             what a pack ships: pack.json, plugin/, design/ (project.json + meta/), models/
  <data>/work/<id>/              what working on it makes: sessions, labels, testset, models, shadow, caches
                                 (inspector.json "work" / INSPECTOR_WORK puts <work>/<id>/ on another disk)
  <data>/runtime/<id>/           this machine only: values, live state, secrets
data_root() is the design folder, work_root() the work folder; in the single-folder layout both are the project."""
import atomic
import json
import os
import re
import time
from i18n import N_, _, tr

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the work folder's own parts: a path written where it was before it moved is found again by them (rel_of)
WORK_PART = re.compile(r"[\\/](sessions|shadow|labels|testset|models)[\\/]")


def _home():
    # not %LOCALAPPDATA%: the Microsoft Store's Python quietly keeps what it writes there in a folder of its own
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), ".inspector")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(os.path.join("~", ".config")), "inspector")


HOME = os.environ.get("INSPECTOR_HOME") or _home()              # this computer's settings (and, by default, data)
MACHINE = os.environ.get("INSPECTOR_CONFIG") or os.path.join(HOME, "inspector.json")
OLD_MACHINE = os.path.join(APP_DIR, "inspector.json")            # where versions before 0.1.0 kept it


def _move_old_machine():
    """An inspector.json in the program folder (older versions): moved to MACHINE once; the old file is renamed."""
    if os.path.exists(MACHINE) or not os.path.exists(OLD_MACHINE) or os.environ.get("INSPECTOR_CONFIG"):
        return
    import shutil
    os.makedirs(os.path.dirname(MACHINE), exist_ok=True)
    shutil.copy2(OLD_MACHINE, MACHINE)
    try:
        os.replace(OLD_MACHINE, OLD_MACHINE + ".moved")
    except OSError:
        pass


_move_old_machine()
FILE = "project.json"
DEFAULT = {"id": "default", "name": N_("新專案"), "description": "",
           "screen": {"width": 1280, "height": 720},
           "app": {"package": ""},
           "words": {"device": N_("裝置"), "item": N_("項目")},
           "plugins": []}
_cache = {}


def _read(p, default):
    try:                       # time, size and the file itself: one replaced within the clock's step (save()) still shows
        st = os.stat(p)
        m = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        m = 0
    hit = _cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    d = default
    if m:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = default
    _cache[p] = (m, d)
    return d


def machine():
    return _read(MACHINE, {})


def set_machine(**values):
    """Change settings of this machine (inspector.json); a value None removes it."""
    d = dict(machine())
    for k, v in values.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    os.makedirs(os.path.dirname(MACHINE), exist_ok=True)
    atomic.write_json(MACHINE, d, ensure_ascii=False, indent=1)
    _where["at"] = -1e9


_where = {"at": -1e9}


def _layout():
    """Where things are, worked out at most every 2 s (paths are asked for thousands of times a request)."""
    now = time.monotonic()
    if now - _where["at"] < 2:
        return _where
    home = os.environ.get("INSPECTOR_DATA") or machine().get("data") or None
    if not home and not (os.environ.get("INSPECTOR_PROJECT") or machine().get("project")):
        home = os.path.join(HOME, "data")             # a new computer: the data folder layout, beside the settings
    pid = (os.environ.get("INSPECTOR_PACK") or _read(os.path.join(home, "active.json"), {}).get("pack") or "default")         if home else None
    if home:
        pack = os.path.join(home, "packs", pid)
        design = os.path.join(pack, "design")
        if not os.path.exists(os.path.join(design, FILE)):
            os.makedirs(design, exist_ok=True)
            save({**DEFAULT, "id": pid}, design)
        if not os.path.exists(os.path.join(pack, "pack.json")):      # a pack begun here: its pack.json too
            from . import manifest
            manifest.write(pack, manifest.stamp({"id": pid, "name": _(DEFAULT["name"]), "plugin": None}))   # its design: this spec
        work = os.path.join(os.environ.get("INSPECTOR_WORK") or machine().get("work") or os.path.join(home, "work"), pid)
        os.makedirs(work, exist_ok=True)
    else:
        env = os.environ.get("INSPECTOR_PROJECT")
        pack = None
        design = work = env or machine().get("project") or os.path.join(APP_DIR, "projects", "default")
        if not os.path.exists(os.path.join(design, FILE)) and not env and not machine().get("project"):
            os.makedirs(design, exist_ok=True)        # a first start: an empty project to begin with
            save({**DEFAULT}, design)
    _where.update(at=now, home=home, pid=pid, pack=pack, design=design, work=work,
                  design_key=os.path.normcase(os.path.abspath(design)))
    return _where


_edition = []


def edition():
    """"studio": design, teach, export packs. "runtime": install packs, run them, the operation panel - the design is
    read-only. One program for both: inspector.json "edition" (or INSPECTOR_EDITION) says which; without it, an
    installation with PyTorch (requirements.txt) is a studio and one without (requirements-runtime.txt) a runtime."""
    e = os.environ.get("INSPECTOR_EDITION") or machine().get("edition")
    if e in ("studio", "runtime"):
        return e
    if not _edition:
        import importlib.util
        _edition.append("studio" if importlib.util.find_spec("torch") is not None else "runtime")
    return _edition[0]


def data_home():
    """The data folder (the layout with packs apart), or None for the single project folder."""
    return _layout()["home"]


def active_pack():
    """The id of the pack that runs (data folder layout only)."""
    return _layout()["pid"]


def pack_dir():
    """<data>/packs/<id>, or None in the single-folder layout."""
    return _layout()["pack"]


def pack_info():
    """The active pack's pack.json ({} when there is none)."""
    d = pack_dir()
    return _read(os.path.join(d, "pack.json"), {}) if d else {}


def data_root():
    """The design: project.json + meta/."""
    return _layout()["design"]


def work_root():
    """What working on the project makes (sessions, labels, testset, models, shadow, caches)."""
    return _layout()["work"]


def logs_dir():
    """The service's logs (run_service.bat asks: python -m project logs): <data>/logs, never the program folder."""
    d = os.path.join(data_home(), "logs") if data_home() else os.path.join(work_root(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def work_of(root):
    """The work folder that goes with design folder <root> (itself in the single-folder layout)."""
    w = _layout()
    if root and w["pack"] and os.path.normcase(os.path.abspath(root)) == w["design_key"]:
        return w["work"]
    return root


def resolve(rel, root=None):
    """A path the data writes relative to the project ("meta/...", "sessions/...") made absolute: the design keeps
    project.json and meta/, the work folder everything else."""
    root = root or data_root()
    first = rel.replace("\\", "/").lstrip("/").split("/", 1)[0]
    return os.path.join(root if first in ("meta", FILE) else work_of(root), rel)


def rel_of(path, root=None):
    """The other way round: an absolute path in the design or the work folder as the data writes it."""
    root = root or data_root()
    key = os.path.normcase(path)                       # same length as path: slices line up
    for base in (work_of(root), root):
        bk = os.path.normcase(base).rstrip("\\/") + os.sep
        if key.startswith(bk):
            return path[len(bk):].replace("\\", "/")
    if os.path.isabs(path) or re.match(r"[A-Za-z]:[\\/]", path):   # written where the work folder was before it moved
        m = WORK_PART.search(path)                     # (another folder, disk or computer): from its own part on
        if m:
            return path[m.start() + 1:].replace("\\", "/")
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:                                 # another drive
        return path.replace("\\", "/")


def inside(path, folder):
    """Is path in folder (False for another drive)?"""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:
        return False


def models_of(root):
    """The models folder that goes with design folder <root>."""
    return models_dir() if pack_dir() and work_of(root) != root else os.path.join(root, "models")


def models_dir():
    """Trained models: the work folder's, or the ones the pack shipped with while nothing has been trained here."""
    own = os.path.join(work_root(), "models")
    shipped = os.path.join(pack_dir(), "models") if pack_dir() else None
    if shipped and os.path.isdir(shipped) and not os.path.isdir(own):
        return shipped
    return own


def runtime_dir():
    env = os.environ.get("INSPECTOR_RUNTIME")
    if env:
        return env
    if pack_dir():
        return os.path.join(data_home(), "runtime", active_pack())
    return machine().get("runtime") or os.path.join(data_root(), ".runtime")


def load(root=None):
    """The project's settings, every field filled in (defaults for the missing ones)."""
    p = _read(os.path.join(root or data_root(), FILE), {})
    out = {**DEFAULT, **p}
    for k in ("screen", "app", "words"):
        out[k] = {**tr(DEFAULT[k]), **(p.get(k) or {})}
    return out


def save(p, root=None):
    root = root or data_root()
    w, h = int(p["screen"]["width"]), int(p["screen"]["height"])
    if not (160 <= w <= 7680 and 90 <= h <= 4320):
        raise ValueError(_("畫面座標空間要在 160×90 ~ 7680×4320 之間"))
    path = os.path.join(root, FILE)
    atomic.write_json(path, p, ensure_ascii=False, indent=1)
    _cache.pop(path, None)


def run_defaults(root=None):
    """project.json "run" within the platform's limits (only those given): {"interval": 0.3..10 s, "max_per_min": 1..60,
    "confirm": 1 | 2 (looks that must agree before a decision counts; 1 also judges the model on the last look only)}."""
    r = load(root).get("run") or {}
    out = {}
    try:
        if r.get("interval") is not None:
            out["interval"] = min(10.0, max(0.3, float(r["interval"])))
        if r.get("max_per_min") is not None:
            out["max_per_min"] = min(60, max(1, int(r["max_per_min"])))
        if r.get("confirm") is not None:
            out["confirm"] = 1 if int(r["confirm"]) <= 1 else 2
    except (TypeError, ValueError):
        pass
    return out


def screen(root=None):
    """(width, height) of the coordinate space."""
    s = load(root)["screen"]
    return int(s["width"]), int(s["height"])


def app_package(root=None):
    return load(root)["app"].get("package") or ""


def word(key, root=None):
    """What this project calls a thing (project.json "words"), e.g. word("device") -> "模擬器" for an app on emulators."""
    return load(root)["words"].get(key) or _(DEFAULT["words"].get(key, key))
