"""Sources (來源): which devices this computer uses, what each is called, where its actions go.

Kept where it runs (<runtime dir>/sources.json): the same project can run on another computer with other devices.
  {"kinds": {"<category>/<preset>": {"params": {...}}},    the preset's 進階設定 that differ from its suggestion
                                                           (a kind is looked in while a source in use is of it: in_use())
   "items": [{"id", "kind", "match", "name", "enabled", "added", "hand", "params", "tags"}],
   "seen": {"<kind>|<match>": first seen}, "ignored": [...], "retired": [ids never given out again]}
  id      the code everything else uses (scripts' deployment, schedules, settings and lists per device, variables,
          the panel, notification filters, recordings): never changes once given
  match   the kind's own name for it now (an LDPlayer instance name, an adb device): re-bind it when that changes
  name    what people read (pages, notifications, chats); empty = the id
  tags    names of groups it belongs to (北棟, 魚池 ...): wherever sources are chosen - a script's deployment, a
          schedule, a notification filter, the operation panel, a chat command - "#<tag>" means every source with it
          (expand()); a source given by its id wins over its tags, tags that disagree give the most careful mode
  params  the source's own settings, for a category that has them (a window: title, program ...; a screen: which one,
          the rectangle) - it is found by these, not by match (match is then only what it was called when added)
  hand    where its actions (tap, swipe, back, text ...) go - the eye and the hand are separate:
            {"to": "self"}                 the same device (the natural pair: an emulator taps itself) - the default
            {"to": "source", "id": <id>}   another source's own input (one source watches, another acts)
            {"to": "output", "id": <id>}   an output (automation/outputs.py: HTTP, later MQTT ...): each action is sent
                                           as a message {"device", "command": tap | swipe | ..., "value": {x, y ...}}
            {"to": "none"}                 only watch: steps that act are refused when a script is saved

Nothing found is used until someone ticks it (a new source is announced once). The first time (no sources.json) the
sources the project declares (project.json "sources") and the devices it already refers to (scripts' deployment,
schedules, the panel) are taken as they are (id = their name); others running on this computer are only found.

Sources(...) is the driver the rest of the platform talks to (drivers.current()): list / capture / input /
watch_touch by id, over every kind that is on."""
import atomic
import json
import os
import re
import threading
import time
from i18n import N_, _

FILE = "sources.json"
INPUT = ("tap", "long_press", "swipe", "back", "launch", "text")       # what a hand does (drivers.CAPS)
EYE = ("screen", "touch_watch")
HANDS = {"self": N_("同一台"), "source": N_("另一個來源"), "output": N_("輸出"), "none": N_("不動作(只看)")}
_lock = threading.RLock()


def _path():
    import project
    return os.path.join(project.runtime_dir(), FILE)


_cache = [None, None]               # (mtime, settings): read again only when the file changes (read every tick)


def _read():
    p = _path()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return None
    if _cache[0] == m and _cache[1] is not None:
        return json.loads(json.dumps(_cache[1]))       # a copy: callers change what they get
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    _cache[0], _cache[1] = m, d
    return json.loads(json.dumps(d))


def _write(cfg):
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, cfg, ensure_ascii=False, indent=1)


def _referenced(root):
    """Device ids the project already uses (so the first start keeps them)."""
    ids = set()
    try:
        import automation
        for s in automation.load_all(root):
            ids |= {k for k in (s.get("devices") or {}) if k != "*"}
        from automation import schedules
        for s in schedules.load(root):
            ids |= set(s.get("devices") or [])
    except Exception:
        pass
    try:
        with open(os.path.join(root, "meta", "panel.json"), encoding="utf-8") as f:
            ids |= set(json.load(f).get("devices") or [])
    except (OSError, ValueError):
        pass
    return ids


def _migrate(cfg):
    """Kind names from before categories ("ldplayer" -> "android/ldplayer" ...). -> True if anything changed."""
    from . import OLD_KINDS
    changed = False
    for old, new in OLD_KINDS.items():
        if old in cfg["kinds"]:
            cfg["kinds"][new] = cfg["kinds"].pop(old)
            changed = True
        for it in cfg["items"]:
            if it.get("kind") == old:
                it["kind"] = new
                changed = True
        for key in list(cfg["seen"]):
            if key.startswith(old + "|"):
                cfg["seen"][new + key[len(old):]] = cfg["seen"].pop(key)
                changed = True
        ig = cfg.get("ignored") or []
        if any(x.startswith(old + "|") for x in ig):
            cfg["ignored"] = [new + x[len(old):] if x.startswith(old + "|") else x for x in ig]
            changed = True
    for it in cfg["items"]:
        if "hand" not in it:
            it["hand"] = {"to": "self"}
            changed = True
    return changed


def load(root=None):
    """The settings (made the first time from the project's old single driver and what is there now)."""
    with _lock:
        cfg = _read()
        if cfg is not None:
            cfg.setdefault("kinds", {})
            cfg.setdefault("items", [])
            cfg.setdefault("seen", {})
            if _migrate(cfg):
                _write(cfg)
            return cfg
        import project
        from . import OLD_KINDS, kinds
        pj = project.load(root)
        old = pj.get("devices") or {}
        kind = OLD_KINDS.get(old.get("driver") or "ldplayer", old.get("driver") or "android/ldplayer")
        cfg = {"kinds": {kind: {"params": old.get("params") or {}}}, "items": [], "seen": {}}
        now = time.time()
        declared = {k: v for k, v in (pj.get("sources") or {}).items() if isinstance(v, dict) and v.get("kind") in kinds()}
        for n, d in sorted(declared.items()):             # what the pack says it uses: as it says (this computer may change it)
            cfg["kinds"].setdefault(d["kind"], {"params": {}})
            cfg["items"].append({"id": n, "kind": d["kind"], "match": d.get("match") or n, "name": d.get("name") or "",
                                 "enabled": True, "added": now,
                                 "hand": {"to": "self" if "tap" in (getattr(kinds()[d["kind"]], "caps", ()) or ()) else "none"},
                                 **({"params": dict(d["params"])} if d.get("params") else {})})
        # what else runs on this computer (every emulator, every window) is only found: the Sources page lists it to
        # be picked - a new computer must not start using devices nobody chose
        for n in sorted(_referenced(root or project.data_root()) - set(declared)):
            cfg["items"].append({"id": n, "kind": kind, "match": n, "name": "", "enabled": True, "added": now, "hand": {"to": "self"}})
        _write(cfg)
        return cfg


def save(cfg, root=None):
    """Check and store. Ids are unique and never reused for another device; one device is one source."""
    seen_ids, seen_match = set(), set()
    from . import kinds
    have = kinds()
    for k, v in (cfg.get("kinds") or {}).items():
        if k not in have:
            raise ValueError(_("沒有「{k}」這種來源", k=k))
        allowed = have[k].params
        ps = {}
        for a, b in (v.get("params") or {}).items():
            if a in allowed and b not in (None, ""):
                ps[a] = bool(b) if allowed[a].get("type") == "bool" and isinstance(b, bool) else str(b)
        v["params"] = ps
        v.pop("on", None)                                  # (before in_use(): a kind was switched on by hand)
    ids = {it.get("id") for it in cfg.get("items") or []}
    for it in cfg.get("items") or []:
        if not re.fullmatch(r"[\w\-.]{1,40}", it.get("id") or "") or it["id"] in seen_ids or it["id"] in (cfg.get("retired") or []):
            raise ValueError(_("來源代號「{id}」不正確或重複(英文、數字、中文、- _ .,不能有空白,40 字以內)", id=it.get('id')))
        seen_ids.add(it["id"])
        key = (it.get("kind"), it.get("match"))
        if it.get("match") and key in seen_match:
            raise ValueError(_("「{match}」同時接到兩個來源", match=it.get('match')))
        seen_match.add(key)
        if it.get("kind") not in have:
            raise ValueError(_("來源「{id}」的種類不正確", id=it['id']))
        it["name"] = str(it.get("name") or "").strip()[:40]
        it["enabled"] = bool(it.get("enabled"))
        tags = []
        for t in it.get("tags") or []:
            t = str(t).strip().lstrip("#")
            if not re.fullmatch(r"[\w\-.]{1,20}", t):
                raise ValueError(_("來源「{id}」的標籤「{t}」不正確(英文、數字、中文、- _ .,20 字以內,不能有空白)", id=it['id'], t=t))
            if t not in tags:
                tags.append(t)
        it["tags"] = tags
        ps = have[it["kind"]].per_source
        it["params"] = {a: str(b) for a, b in (it.get("params") or {}).items() if a in ps and b not in (None, "")}
        h = it.get("hand") or {"to": "self"}
        if h.get("to") not in HANDS:
            raise ValueError(_("來源「{id}」:動作要送到哪裡不正確", id=it['id']))
        if h["to"] == "source" and (h.get("id") not in ids or h.get("id") == it["id"]):
            raise ValueError(_("來源「{id}」:動作要交給哪一個來源?", id=it['id']))
        if h["to"] == "output":
            from automation import outputs
            import project
            if h.get("id") not in outputs.load(root or project.data_root()):
                raise ValueError(_("來源「{id}」:請選擇要送到哪個輸出(先在「素材庫 › 輸出」新增)", id=it['id']))
        it["hand"] = {"to": h["to"], **({"id": h["id"]} if h["to"] in ("source", "output") else {})}
    names = [it["name"] for it in cfg.get("items") or [] if it["name"]]
    if len(names) != len(set(names)):
        raise ValueError(_("兩個來源取了同樣的名稱"))
    with _lock:
        _write(cfg)
    return cfg


def in_use(cfg):
    """The kinds looked in all the time: those of the sources in use (nothing to switch on or off by hand)."""
    return sorted({it["kind"] for it in cfg.get("items") or [] if it.get("enabled")})


MODE_ORDER = {"off": 0, "shadow": 1, "live": 2}


def tags(root=None):
    """tag -> [ids that have it] (every source, used or not)."""
    out = {}
    for it in load(root)["items"]:
        for t in it.get("tags") or []:
            out.setdefault(t, []).append(it["id"])
    return out


def expand(keys, root=None):
    """A list of sources as people choose them - ids and "#<tag>" - -> the ids, in order, each once."""
    by_tag = tags(root)
    out = []
    for k in keys or []:
        for i in (by_tag.get(k[1:], []) if isinstance(k, str) and k.startswith("#") else [k]):
            if i not in out:
                out.append(i)
    return out


def mode_of(devices, dev_id, root=None):
    """A script's deployment ({"*" | id | "#tag": mode}) for one source: its id, else its tags (the most careful of
    them when they disagree), else "*"."""
    devices = devices or {}
    if dev_id in devices:
        return devices[dev_id]
    if any(isinstance(k, str) and k.startswith("#") for k in devices):
        mine = next((it.get("tags") or [] for it in load(root)["items"] if it["id"] == dev_id), [])
        hits = [devices[f"#{t}"] for t in mine if f"#{t}" in devices]
        if hits:
            return min(hits, key=lambda m: MODE_ORDER.get(m, 0))
    return devices.get("*", "off")


def names(root=None):
    """id -> what people read."""
    return {it["id"]: it.get("name") or it["id"] for it in load(root)["items"]}


def label(dev_id, root=None):
    return names(root).get(dev_id, dev_id) if dev_id else dev_id


def new_id(cfg, native):
    base = re.sub(r"[^\w\-.]", "_", native)[:36] or "source"
    taken = {it["id"] for it in cfg["items"]} | set(cfg.get("retired") or [])
    if base not in taken:
        return base
    k = 2
    while f"{base}_{k}" in taken:
        k += 1
    return f"{base}_{k}"


def kind_caps(kind, root=None):
    """What a kind can do with the settings saved for it."""
    from . import kinds
    k = kinds().get(kind)
    if k is None:
        return set()
    return k.caps_with((load(root)["kinds"].get(kind) or {}).get("params"))


def caps_of(dev_id, root=None):
    """What one source can do: its eye (screen, someone operating it) from its own kind, its hand from where it acts."""
    cfg = load(root)
    by = {it["id"]: it for it in cfg["items"]}
    it = by.get(dev_id)
    if not it:
        return set()
    own = kind_caps(it["kind"], root)
    eye = own & set(EYE)
    h = it.get("hand") or {"to": "self"}
    if h["to"] == "self":
        hand = own & set(INPUT)
    elif h["to"] == "source":
        other = by.get(h.get("id"))
        hand = kind_caps(other["kind"], root) & set(INPUT) if other else set()
    elif h["to"] == "output":
        hand = set(INPUT)                                  # every action becomes a message to the output
    else:
        hand = set()
    return eye | hand


def hand_text(it, root=None):
    h = it.get("hand") or {"to": "self"}
    if h["to"] == "source":
        return _("交給「{p1}」", p1=label(h.get('id'), root))
    if h["to"] == "output":
        try:
            from automation import outputs
            import project
            o = outputs.load(root or project.data_root()).get(h.get("id"))
            return _("送到輸出「{name}」", name=(o or {}).get('name', h.get('id')))
        except Exception:
            return _("送到輸出「{id}」", id=h.get('id'))
    return _(HANDS.get(h["to"], h["to"]))


class Sources:
    """The one driver the platform uses: every enabled source, by id, over every kind that is on."""
    label = N_("來源")

    def __init__(self, root=None):
        self.root = root
        self.drivers = {}             # kind -> (settings, driver instance)
        self.where = {}               # id -> (kind, match)
        self.last = {}                # kind -> [Device] of the last scan (natives)
        self.fresh = []               # [(kind, Device)] seen for the first time in the last list()
        self.found = {}               # id -> Device of the sources found by their own settings (windows, screens)
        self.lock = threading.RLock()

    # ---- drivers ----
    def _driver(self, kind, params):
        from . import kinds
        key = json.dumps(params or {}, sort_keys=True)
        d = self.drivers.get(kind)
        if d is None or d[0] != key:
            d = self.drivers[kind] = (key, kinds()[kind](params or {}))
        return d[1]

    def kinds_on(self):
        cfg = load(self.root)
        return {k: cfg["kinds"].get(k) or {"params": {}} for k in in_use(cfg)}

    @property
    def caps(self):
        out = set()
        for it in load(self.root)["items"]:
            if it.get("enabled"):
                out |= caps_of(it["id"], self.root)
        return out

    def caps_of(self, dev_id):
        return caps_of(dev_id, self.root)

    def kind_of(self, dev_id):
        return next((it["kind"] for it in load(self.root)["items"] if it["id"] == dev_id), None)

    # ---- scanning ----
    def scan(self, kinds_wanted=None):
        """Every device each kind finds now -> {kind: [Device]} (natives) and errors {kind: text}."""
        from . import kinds
        cfg = load(self.root)
        found, errors = {}, {}
        want = kinds_wanted or in_use(cfg)
        with self.lock:                         # what other kinds found last time (not scanned now) stays theirs
            claimed = {d.info.get("adb") for k, ds in self.last.items() if k not in want for d in ds if d.info.get("adb")}
        order = [k for k in kinds() if k in want]  # the presets that know their devices best claim them first
        for k in order:
            v = cfg["kinds"].get(k) or {"params": {}}
            try:
                drv = self._driver(k, v.get("params"))
                if hasattr(drv, "skip"):
                    drv.skip = set(claimed)
                devs = drv.list()
                found[k] = devs
                claimed |= {d.info.get("adb") for d in devs if d.info.get("adb")}
            except Exception as e:
                found[k], errors[k] = [], str(e)
        with self.lock:
            self.last.update(found)
        return found, errors

    def list(self):
        """The enabled sources there now, as Devices named by their id (Device.info: kind, match, name)."""
        from . import Device, kinds
        cfg = load(self.root)
        have = kinds()
        on = in_use(cfg)
        per = {k for k in on if k in have and have[k].per_source}
        found, _x = self.scan([k for k in on if k not in per])
        items = {(it["kind"], it["match"]): it for it in cfg["items"]}
        out, where, new = [], {}, False
        fresh, by_own = [], {}
        for it in cfg["items"]:                 # found by their own settings: no list of candidates to announce
            if it["kind"] in per and it.get("enabled"):
                try:
                    d = self._driver(it["kind"], (cfg["kinds"].get(it["kind"]) or {}).get("params")).find(it.get("params") or {})
                except Exception:
                    d = None
                if d is not None:
                    by_own[it["id"]] = d
                    where[it["id"]] = (it["kind"], it["match"])
                    out.append(Device(it["id"], ok=d.ok, detail=d.detail, pid=d.pid, size=d.size,
                                      info={**(d.info or {}), "kind": it["kind"], "match": d.name, "name": it.get("name") or it["id"]}))
        for k, devs in found.items():
            for d in devs:
                it = items.get((k, d.name))
                if it is None:
                    key = f"{k}|{d.name}"
                    if key not in cfg["seen"]:
                        cfg["seen"][key] = time.time()
                        new = True
                        if key not in (cfg.get("ignored") or []):
                            fresh.append((k, d))
                    continue
                if not it.get("enabled"):
                    continue
                where[it["id"]] = (k, d.name)
                out.append(Device(it["id"], ok=d.ok, detail=d.detail, pid=d.pid, size=d.size,
                                  info={**(d.info or {}), "kind": k, "match": d.name, "name": it.get("name") or it["id"]}))
        if new:
            with _lock:
                cur = _read() or cfg
                cur.setdefault("seen", {}).update(cfg["seen"])
                _write(cur)
        with self.lock:
            self.where = where
            self.found = by_own
            self.fresh = fresh                  # found for the first time in this scan: someone should be told
        return out

    def _opts(self, dev_id):
        it = next((x for x in load(self.root)["items"] if x["id"] == dev_id), None) or {}
        return it.get("params") or {}

    def _resolve(self, dev_id):
        w = self.where.get(dev_id)
        if w is None:
            self.list()
            w = self.where.get(dev_id)
        if w is None:
            raise RuntimeError(_("來源「{p1}」現在找不到或已停用", p1=label(dev_id, self.root)))
        k, match = w
        return self._driver(k, (load(self.root)["kinds"].get(k) or {}).get("params")), match

    # ---- the driver interface, by id ----
    def capture(self, dev_id, prefer="window", fallback=True):
        drv, match = self._resolve(dev_id)
        modes = getattr(drv, "capture_modes", {}) or {}
        mode = prefer if prefer in modes else next(iter(modes), None)
        if getattr(drv, "per_source", None):
            return drv.capture(match, mode, fallback, opts=self._opts(dev_id))
        return drv.capture(match, mode, fallback)

    def input(self, dev_id, kind, **p):
        """Do one action with the source's hand: itself, another source, an output, or nothing."""
        from . import CAPS, NotSupported
        it = next((x for x in load(self.root)["items"] if x["id"] == dev_id), None) or {}
        h = it.get("hand") or {"to": "self"}
        if h["to"] == "none":
            raise NotSupported(_("「{p1}」設定成只看不動作", p1=label(dev_id, self.root)))
        if h["to"] == "output":
            import project
            from automation import outputs
            f = outputs.send(self.root or project.data_root(), h["id"],
                             {"device": dev_id, "script": "", "command": kind, "value": dict(p)})
            f.result(timeout=20)                       # a failure raises: the step fails like a failed tap
            return True
        target = h.get("id") if h["to"] == "source" else dev_id
        drv, match = self._resolve(target)
        if kind not in (getattr(drv, "caps", ()) or ()):
            raise NotSupported(_("「{p1}」({label})不能{p3}", p1=label(target, self.root), label=_(drv.label), p3=_(CAPS.get(kind, kind))))
        if getattr(drv, "per_source", None):
            return drv.input(match, kind, opts=self._opts(target), **p)
        return drv.input(match, kind, **p)

    def watch_touch(self, dev_id, on_gesture):
        try:
            drv, match = self._resolve(dev_id)
        except RuntimeError:
            return None
        if "touch_watch" not in (getattr(drv, "caps", ()) or ()):
            return None
        return drv.watch_touch(match, on_gesture)


def check_size(dev, root=None, mapped=False):
    """A warning when a source's own screen is not the project's coordinate space. mapped = its taps are mapped back to
    its own pixels (a window, a screen rectangle, a stream): then only the picture can be distorted - not when it keeps
    its shape (fit contain / cover, drivers/fit.py)."""
    if mapped and (dev.info or {}).get("fit") in ("contain", "cover"):
        return None
    import project
    w, h = project.screen() if root is None else (project.load(root)["screen"]["width"], project.load(root)["screen"]["height"])
    if not dev.size or not all(dev.size):
        return None
    sw, sh = dev.size
    if sorted((sw, sh)) == sorted((w, h)):           # the same screen turned: the app rotates it
        return None
    if mapped:
        if abs(sw / sh - w / h) > 0.02:
            return _("畫面比例不同:這個來源 {sw}×{sh},專案是 {w}×{h};點擊位置會換算回來,但畫面會被拉伸,辨識可能較不準(在「這個來源的設定」把畫面改成「等比例,補黑邊」,或只取一塊相同比例的範圍)", sw=sw, sh=sh, w=w, h=h)
        return None
    if abs(max(sw, sh) / min(sw, sh) - max(w, h) / min(w, h)) > 0.02:
        return _("畫面比例不同:這台 {sw}×{sh},專案是 {w}×{h}。點擊位置會跑掉,請把畫面大小改成 {w2}×{h2}", sw=sw, sh=sh, w=w, h=h, w2=w, h2=h)
    return _("解析度不同:這台 {sw}×{sh},專案是 {w}×{h}(比例相同,畫面會縮放;建議改成一樣,辨識最準)", sw=sw, sh=sh, w=w, h=h)
