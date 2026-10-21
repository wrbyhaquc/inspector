"""User settings (使用者設定): the parameters a design opens to the people who run it, e.g. which items of a
list each device goes through, or how long to stay on each. The design declares them; the values belong to whoever runs it.

  declarations  <data_root>/meta/user_settings.json   part of the design (it travels with the scripts)
                {"settings": [{"id", "label", "description",
                               "type": "number" | "text" | "bool" | "time" | "point" | "list",
                               "item": for a list: "point" | "number" | "text",
                               "pick_from": for a point or a list of points: "list:<list id>" (the names of a
                                            list - that emulator's if the list is per device); the value must be
                                            one of them,
                               "scope": "shared" (one value) | "device" (one per emulator),
                               "default", "device_default": {device: value},
                               "min", "max" (a number), "min_items", "max_items" (a list)}]}
  values        <runtime dir>/user_settings_values.json   what the users chose
                {"values": {setting id: {"*": value, device: value}}}

A script, schedule or call passes a setting instead of a fixed value: an argument {"setting": id}. It is read when the
run starts (the device's own value, else the shared one, else the device default, else the default), so a change
applies from the next run on and never in the middle of one."""
import json
import os
import re
import time
from project import word
from . import spec
from i18n import N_, _

FILE = os.path.join("meta", "user_settings.json")
VALUES = "user_settings_values.json"
TYPES = {"number": N_("數字"), "text": N_("文字"), "bool": N_("開關"), "time": N_("時間"), "point": N_("位置(單選)"), "list": N_("清單(多選)")}
ITEMS = {"point": N_("位置"), "number": N_("數字"), "text": N_("文字")}
SCOPES = {"device": N_("每台各自"), "shared": N_("全部共用")}
_cache = {}


def _default_root(data_root):
    import project
    return data_root or project.data_root()


def _read(p):
    m = os.path.getmtime(p) if os.path.exists(p) else 0
    hit = _cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    d = {}
    if m:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    _cache[p] = (m, d)
    return d


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)
    _cache.pop(p, None)


def load(data_root=None):
    """Declarations by id, in their order."""
    return {s["id"]: s for s in _read(os.path.join(_default_root(data_root), FILE)).get("settings", [])}


def values(runtime_dir):
    return _read(os.path.join(runtime_dir, VALUES)).get("values", {})


def value(data_root, runtime_dir, sid, device=None):
    """What a run on `device` gets for setting `sid` (None if there is no such setting)."""
    s = load(data_root).get(sid)
    if not s:
        return None
    mine = values(runtime_dir).get(sid) or {}
    if s.get("scope") == "device" and device and device in mine:
        v = mine[device]
    elif "*" in mine:
        v = mine["*"]
    elif s.get("scope") == "device" and device in (s.get("device_default") or {}):
        v = s["device_default"][device]
    else:
        v = s.get("default")
    return v


def run_value(data_root, runtime_dir, sid, device=None):
    """What a run gets: value(), without the names of a list that are gone or were not seen in its last walk."""
    s = load(data_root).get(sid)
    return _present(data_root, s, value(data_root, runtime_dir, sid, device)) if s else None


def _present(data_root, s, v):
    """A list of names of a list: without the ones gone from the library or not seen in the last walk of the list
    (lists.py "missing_since") - a run does not spend minutes looking for a name that is not there."""
    if s.get("type") != "list" or not str(s.get("pick_from") or "").startswith("list:") or not isinstance(v, list):
        return v
    from . import buttons as bm
    lib = bm.load(data_root)
    return [x for x in v if not (isinstance(x, dict) and "button" in x)
            or (x["button"] in lib and not lib[x["button"]].get("missing_since"))]


def forget_button(data_root, runtime_dir, bid):
    """A name removed from a list: out of every value the users chose (a list loses it, a single choice goes back to
    its default)."""
    p = os.path.join(runtime_dir, VALUES)
    d = json.loads(json.dumps(_read(p) or {}))
    changed = False
    for sid, per in (d.get("values") or {}).items():
        for k, v in list(per.items()):
            if isinstance(v, list) and any(isinstance(x, dict) and x.get("button") == bid for x in v):
                per[k] = [x for x in v if not (isinstance(x, dict) and x.get("button") == bid)]
                changed = True
            elif isinstance(v, dict) and v.get("button") == bid:
                del per[k]
                changed = True
    if changed:
        d["updated"] = time.time()
        _write(p, d)


def choices(data_root, s, device=None):
    """The values a point / list-of-points setting may take: [{"label", "value"}], or None if anything goes."""
    src = s.get("pick_from")
    if not src:
        return None
    from . import buttons as bm
    if src.startswith("list:"):
        from . import lists
        spec = lists.load(data_root).get(src[5:])
        return [{"label": b["label"], "value": {"button": b["id"]}} for b in lists.ordered(data_root, spec, device)] if spec else []
    return None


def check_value(data_root, s, v, device=None):
    """Raise ValueError if v is not a valid value of setting s (for this device); return it as stored."""
    t, name = s.get("type"), s.get("label") or s["id"]
    if t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(_("「{name}」要填數字", name=name))
        if s.get("min") is not None and v < s["min"] or s.get("max") is not None and v > s["max"]:
            raise ValueError(_("「{name}」要在 {min}~{max} 之間", name=name, min=s.get('min', ''), max=s.get('max', '')))
        return v
    if t == "bool":
        if not isinstance(v, bool):
            raise ValueError(_("「{name}」請選擇開或關", name=name))
        return v
    if t == "time":
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(v)):
            raise ValueError(_("「{name}」時間要像 20:00", name=name))
        return v
    if t == "text":
        if not isinstance(v, str) or len(v) > 200:
            raise ValueError(_("「{name}」要填 200 字以內的文字", name=name))
        return v
    allowed = choices(data_root, s, device)
    key = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)
    ok = {key(c["value"]) for c in allowed} if allowed is not None else None
    if t == "point":
        if not isinstance(v, dict) or (ok is not None and key(v) not in ok):
            raise ValueError(_("「{name}」的選項不正確,請重新整理頁面", name=name))
        return v
    if t == "list":
        if not isinstance(v, list):
            raise ValueError(_("「{name}」要是一個清單", name=name))
        if s.get("min_items") is not None and len(v) < s["min_items"] or s.get("max_items") is not None and len(v) > s["max_items"]:
            raise ValueError(_("「{name}」要選 {min_items}~{max_items} 個", name=name, min_items=s.get('min_items', 0), max_items=s.get('max_items', _("不限"))))
        if len({key(x) for x in v}) != len(v):
            raise ValueError(_("「{name}」有重複的項目", name=name))
        item = s.get("item", "point")
        for x in v:
            if item == "number" and (isinstance(x, bool) or not isinstance(x, (int, float))) or item == "text" and not isinstance(x, str) \
                    or item == "point" and (not isinstance(x, dict) or (ok is not None and key(x) not in ok)):
                raise ValueError(_("「{name}」裡有不正確的項目,請重新整理頁面", name=name))
        return v
    raise ValueError(_("「{name}」的種類不正確", name=name))


def validate(data_root, decls):
    seen = set()
    for s in decls:
        sid = s.get("id") or ""
        where = _("使用者設定「{p1}」", p1=s.get('label') or sid)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", sid):
            raise ValueError(_("{where}:代號只能用小寫英文、數字、底線,且以英文開頭", where=where))
        if sid in seen:
            raise ValueError(_("{where}:代號重複", where=where))
        seen.add(sid)
        if not (s.get("label") or "").strip():
            raise ValueError(_("{where}:請取個名稱", where=where))
        if s.get("type") not in TYPES:
            raise ValueError(_("{where}:種類不正確", where=where))
        if s.get("scope") not in SCOPES:
            raise ValueError(_("{where}:請選擇每台各自或全部共用", where=where))
        if s["type"] == "list" and s.get("item", "point") not in ITEMS:
            raise ValueError(_("{where}:清單的每一項要是位置、數字或文字", where=where))
        src = s.get("pick_from")
        if src and not src.startswith("list:") or src and s["type"] not in ("point", "list"):
            raise ValueError(_("{where}:可選項目的來源不正確", where=where))
        if src and src.startswith("list:"):
            from . import lists
            spec = lists.load(data_root).get(src[5:])
            if not spec:
                raise ValueError(_("{where}:找不到清單「{p2}」", where=where, p2=src[5:]))
            if spec.get("per_device") and s["scope"] != "device":
                raise ValueError(_("{where}:清單「{p2}」每台不一樣,要選「每台各自」", where=where, p2=spec.get('title') or spec['id']))
        defaults = ([(None, s["default"])] if s.get("default") is not None else []) + list((s.get("device_default") or {}).items())
        for dev, v in defaults:
            try:
                check_value(data_root, s, v, dev)
            except ValueError as e:
                raise ValueError(_("{where}的預設值{p2}:{e}", where=where, p2=f'({dev})' if dev else '', e=e))


def save(data_root, decls):
    validate(data_root, decls)
    keep = ("id", "label", "description", "type", "item", "pick_from", "scope", "default", "device_default",
            "min", "max", "min_items", "max_items")
    out = [{k: s[k] for k in keep if k in s and s[k] is not None} for s in decls]
    _write(os.path.join(data_root, FILE), spec.stamp({"settings": out, "saved": time.time()}))
    return out


def set_value(data_root, runtime_dir, sid, device, v):
    """Store what a user chose (device None = the shared value). v None = back to the default. -> (old, new)"""
    s = load(data_root).get(sid)
    if not s:
        raise ValueError(_("這個設定已經不存在,請重新整理頁面"))
    if s.get("scope") == "device" and not device:
        raise ValueError(_("「{label}」是每台各自的設定,請指定{p2}", label=s['label'], p2=word("device")))
    key = device if s.get("scope") == "device" else "*"
    old = value(data_root, runtime_dir, sid, device)
    p = os.path.join(runtime_dir, VALUES)
    d = json.loads(json.dumps(_read(p) or {}))
    mine = d.setdefault("values", {}).setdefault(sid, {})
    if v is None:
        mine.pop(key, None)
    else:
        mine[key] = check_value(data_root, s, v, device)
    d["updated"] = time.time()
    _write(p, d)
    return old, value(data_root, runtime_dir, sid, device)


def used_by(data_root):
    """setting id -> where it is passed: ["排程「X」", "主腳本「Y」情境「Z」", "子腳本「W」"]"""
    import automation
    from . import schedules, subs
    out = {}

    def scan(obj, where):
        if isinstance(obj, dict):
            if isinstance(obj.get("setting"), str) and len(obj) == 1:
                out.setdefault(obj["setting"], [])
                if where not in out[obj["setting"]]:
                    out[obj["setting"]].append(where)
            for v in obj.values():
                scan(v, where)
        elif isinstance(obj, list):
            for v in obj:
                scan(v, where)
    for s in schedules.load(data_root):
        scan([s.get("args"), s.get("device_args")], _("排程「{name}」", name=s['name']))
    for sc in automation.load_all(data_root):
        scan(sc.get("situations"), _("主腳本「{name}」", name=sc['name']))
    for sub in subs.load_all(data_root).values():
        scan(sub.get("steps"), _("子腳本「{name}」", name=sub['name']))
    return out


def resolve(args, lookup):
    """args with every {"setting": id} replaced by lookup(id) (one level deep: a whole argument is a setting)."""
    return {k: (lookup(v["setting"]) if isinstance(v, dict) and set(v) == {"setting"} else v) for k, v in (args or {}).items()}
