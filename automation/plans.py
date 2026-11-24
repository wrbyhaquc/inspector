"""Each device's own plan (每台行程表): the people who run it put entries on a week for each device - "Monday 10:00,
do this with these choices" - from the things the design lets them plan (可以排的事).

  things to plan   <data_root>/meta/plan_tasks.json   part of the design
                   {"tasks": [{"id", "name", "sub",                     the sub-script run when an entry is due
                               "params": {param: {"label", "from": "list:<id>" | "catalog:<id>" | [{"label", "value"}],
                                                  "sets": [user setting ids]}},   what the user picks for each
                                                  of the sub's parameters; "sets": while an entry of it is kept
                                                  (keep), the pick stands for these settings
                               "pause_others": bool (default true), "max_minutes": minutes}]}
  the plans        <runtime dir>/device_plans.json    what the users planned (a runtime's, never the design's)
                   {"plans": {"<device>" | "#<tag>": [{"id", "task", "days": [0..6] (Monday = 0), "at": "HH:MM",
                                                       "keep": bool, "enabled": bool, "args": {param: value}}]}}

An entry is due on its weekdays at its time, within WINDOW minutes (missed after that: not run late). It runs as a
schedule for that one device (automation/schedules.py): one thing at a time on a device, the later one waits; at the
same time an entry goes before the project's schedules; "done today" per entry.

keep = from its time until the next kept entry of the week, the entry's picks stand for the settings its task "sets"
(a run reads them through settings.run_value): the main scripts keep to them (e.g. back to that spot after dying). The
built-in task RESET ("回到平常的設定") ends that: back to the settings as the users set them. Which entry stands is
worked out from the clock alone (the last kept one of the week up to now), so a missed run or a restart changes
nothing about it. The users' own setting values are never changed."""
import datetime
import json
import os
import re

import atomic
from i18n import _

TASKS_FILE = os.path.join("meta", "plan_tasks.json")
PLANS_FILE = "device_plans.json"
RESET = "_reset"            # the built-in task: end what a kept entry set, back to the users' own settings
PLAN_PREFIX = "_plan_"      # a plan entry run as a schedule: its schedule id
WINDOW = 10                 # minutes after its time an entry may still start (later: missed)
_cache = {}


def _read(path):
    m = os.path.getmtime(path) if os.path.exists(path) else 0
    hit = _cache.get(path)
    if hit and hit[0] == m:
        return hit[1]
    d = {}
    if m:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    _cache[path] = (m, d)
    return d


def tasks(data_root):
    """{task id: task} - the things the design lets the users plan, and the built-in RESET"""
    out = {t["id"]: t for t in _read(os.path.join(data_root, TASKS_FILE)).get("tasks", [])}
    out[RESET] = {"id": RESET, "name": _("回到平常的設定"), "sub": None, "params": {}, "builtin": True}
    return out


def save_tasks(data_root, items):
    """the design's things to plan, checked: their sub-scripts, parameters and settings exist"""
    from . import subs as subs_mod, settings as settings_mod
    lib, decl = subs_mod.load_all(data_root), settings_mod.load(data_root)
    seen = set()
    for t in items:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(t.get("id") or "")) or t["id"] in seen:
            raise ValueError(_("「可以排的事」的代號不正確或重複:{id}", id=t.get("id")))
        seen.add(t["id"])
        if not str(t.get("name") or "").strip():
            raise ValueError(_("每件「可以排的事」都要有名稱"))
        sub = lib.get(t.get("sub"))
        if not sub:
            raise ValueError(_("「{name}」要執行的子腳本不存在", name=t["name"]))
        names = {p["name"]: p for p in sub.get("params") or []}
        for pn, p in (t.get("params") or {}).items():
            if pn not in names:
                raise ValueError(_("「{name}」:子腳本沒有參數「{p}」", name=t["name"], p=pn))
            if not p.get("from"):
                raise ValueError(_("「{name}」:參數「{p}」要設定從哪裡選", name=t["name"], p=pn))
            for sid in p.get("sets") or []:
                if sid not in decl:
                    raise ValueError(_("「{name}」:沒有使用者設定「{s}」", name=t["name"], s=sid))
        missing = [n for n, p in names.items() if p.get("default") is None and n not in (t.get("params") or {})]
        if missing:
            raise ValueError(_("「{name}」:子腳本的參數「{p}」沒有讓使用者選", name=t["name"], p="、".join(missing)))
    p = os.path.join(data_root, TASKS_FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, {"tasks": items})
    return items


def keeps(task):
    """a task whose entries can be kept: one of its picks stands for a setting"""
    return task.get("id") == RESET or any(p.get("sets") for p in (task.get("params") or {}).values())


def plans(runtime_dir):
    return _read(os.path.join(runtime_dir, PLANS_FILE)).get("plans", {})


def _hhmm(s):
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(s or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def options(data_root, param, device=None):
    """what a plan entry's parameter may be: [{"label", "value", "folder"?}]"""
    src = param.get("from")
    if isinstance(src, list):
        return src
    if isinstance(src, str) and src.startswith("catalog:"):
        from . import catalogs
        return catalogs.choices(data_root, src[8:])
    if isinstance(src, str) and src.startswith("list:"):
        from . import settings as settings_mod
        return settings_mod.choices(data_root, {"pick_from": src}, device) or []
    return []


def save_plan(data_root, runtime_dir, key, entries):
    """one device's (or "#tag"'s) entries as edited, checked; a new entry gets an id"""
    if not re.fullmatch(r"#?[^\s/\\]{1,80}", str(key or "")):
        raise ValueError(_("要排行程的{device}不正確", device=_device_word()))
    import time
    ts = tasks(data_root)
    used = {e.get("id") for p in plans(runtime_dir).values() for e in p} | {e.get("id") for e in entries}
    before = {e["id"]: e for e in plans(runtime_dir).get(key) or []}
    now = time.time()
    out, k = [], 1
    dev = None if key.startswith("#") else key
    for e in entries:
        t = ts.get(e.get("task"))
        if not t:
            raise ValueError(_("沒有這件可以排的事:{t}", t=e.get("task")))
        days = sorted({int(d) for d in e.get("days") or []})
        if not days or any(d < 0 or d > 6 for d in days):
            raise ValueError(_("「{name}」:請選星期幾", name=t["name"]))
        if _hhmm(e.get("at")) is None:
            raise ValueError(_("「{name}」:時間要是 時:分(例如 09:30)", name=t["name"]))
        keep = bool(e.get("keep")) or t["id"] == RESET
        if keep and not keeps(t):
            raise ValueError(_("「{name}」不能「維持到下一筆」:它沒有對應的設定", name=t["name"]))
        args = {}
        for pn, p in (t.get("params") or {}).items():
            v = (e.get("args") or {}).get(pn)
            allowed = [json.dumps(o["value"], sort_keys=True) for o in options(data_root, p, dev)]
            if v is None or json.dumps(v, sort_keys=True) not in allowed:
                raise ValueError(_("「{name}」:請選{label}", name=t["name"], label=p.get("label") or pn))
            args[pn] = v
        eid = str(e.get("id") or "")
        if not eid:
            while f"e{k}" in used:
                k += 1
            eid = f"e{k}"
            used.add(eid)
        q = {"id": eid, "task": t["id"], "days": days, "at": e["at"], "keep": keep,
             "enabled": e.get("enabled", True) is not False, "args": args}
        old = before.get(eid)                       # new, or what it does / when changed: it counts from now on
        same = old and all(old.get(k) == q[k] for k in ("task", "days", "at", "keep", "args"))
        q["since"] = old.get("since", 0) if same else round(now)
        out.append(q)
    out.sort(key=lambda e: (e["days"][0], _hhmm(e["at"])))
    p = os.path.join(runtime_dir, PLANS_FILE)
    d = dict(_read(p))
    allp = dict(d.get("plans") or {})
    if out:
        allp[key] = out
    else:
        allp.pop(key, None)
    os.makedirs(runtime_dir, exist_ok=True)
    atomic.write_json(p, {**d, "plans": allp})
    return out


def _device_word():
    from project import word
    return word("device")


def device_tags(device):
    """the tags a device has (drivers/sources.py)"""
    try:
        from drivers.sources import tags
        return [t for t, ids in tags().items() if device in ids]
    except Exception:                                    # noqa: BLE001 - no sources config: no tags
        return []


def entries_for(runtime_dir, device, tags=()):
    """a device's entries: its own and those of its tags (each with "for": where it was planned)"""
    ps = plans(runtime_dir)
    out = [{**e, "for": device} for e in ps.get(device) or []]
    for tg in tags or ():
        out += [{**e, "for": "#" + tg} for e in ps.get("#" + tg) or []]
    return out


def _week_minute(dt):
    return dt.weekday() * 1440 + dt.hour * 60 + dt.minute


def standing(entries, now):
    """the kept entry that stands now: the last enabled kept one of the week up to now (from last week's end when
    none yet this week) - only from its "since" on (made or changed then: its earlier times do not count); None
    when there is none, or it is a RESET"""
    dt = datetime.datetime.fromtimestamp(now)
    t = _week_minute(dt)
    monday = datetime.datetime(dt.year, dt.month, dt.day) - datetime.timedelta(days=dt.weekday())
    best, best_key = None, None
    for e in entries:
        if not e.get("enabled", True) or not e.get("keep"):
            continue
        at = _hhmm(e.get("at"))
        for d in e.get("days") or []:
            m = d * 1440 + at
            key = m if m <= t else m - 7 * 1440          # later this week = last week's
            if (monday + datetime.timedelta(minutes=key)).timestamp() < e.get("since", 0):
                continue
            if best_key is None or key > best_key:
                best, best_key = e, key
    return None if best is None or best.get("task") == RESET else best


def next_keep(entries, now):
    """(entry, its time as a timestamp) of the next enabled kept entry after now within a week, or (None, None)"""
    dt = datetime.datetime.fromtimestamp(now)
    t = _week_minute(dt)
    monday = datetime.datetime(dt.year, dt.month, dt.day) - datetime.timedelta(days=dt.weekday())
    best, best_m = None, None
    for e in entries:
        if not e.get("enabled", True) or not e.get("keep"):
            continue
        at = _hhmm(e.get("at"))
        for d in e.get("days") or []:
            m = d * 1440 + at
            m = m if m > t else m + 7 * 1440
            if best_m is None or m < best_m:
                best, best_m = e, m
    return (best, (monday + datetime.timedelta(minutes=best_m)).timestamp()) if best else (None, None)


def overlay(data_root, runtime_dir, device, now, tags=()):
    """{setting id: value} the standing kept entry sets on this device now ({} = the users' own settings)"""
    e = standing(entries_for(runtime_dir, device, tags), now)
    if not e:
        return {}
    t = tasks(data_root).get(e["task"]) or {}
    out = {}
    for pn, p in (t.get("params") or {}).items():
        if pn in (e.get("args") or {}):
            for sid in p.get("sets") or []:
                out[sid] = e["args"][pn]
    return out


def as_schedules(data_root, runtime_dir, device, tags=(), day_start=0):
    """this device's entries as schedules (automation/schedules.py) of it alone - id "_plan_<entry id>" (no design schedule starts with _; a file name) - so they
    queue with the project's schedules: one at a time, done today, max_minutes, carried on after a restart"""
    ts = tasks(data_root)
    out = []
    for e in entries_for(runtime_dir, device, tags):
        t = ts.get(e["task"])
        if not t or not t.get("sub"):
            continue
        at = _hhmm(e["at"])
        days = e["days"]
        if at < day_start:                         # before the day starts: the schedule day before (its morning)
            days = sorted({(d - 1) % 7 for d in days})
        out.append({"id": f"{PLAN_PREFIX}{e['id']}", "name": t["name"], "enabled": e.get("enabled", True), "at": e["at"],
                    "days": days, "window": WINDOW, "devices": [device], "sub": t["sub"], "args": dict(e.get("args") or {}),
                    "pause_others": t.get("pause_others", True), "max_minutes": t.get("max_minutes", 60),
                    "plan": e["id"], "plan_for": e["for"]})
    return out
