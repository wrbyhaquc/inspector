"""Schedules (排程): run a sub-script on some emulators at a time of day, at most once a day per emulator.

<data_root>/meta/schedules.json  {"day_start": "HH:MM" (a day begins then: "ran today" resets, windows end), "schedules": [{
    "id", "name", "enabled",
    "at": "HH:MM",                 starts at this time (local) ...
    "days": [0..6],                ... on these weekdays (Monday = 0; empty = every day)
    "window": minutes,             ... unless it is later than this many minutes after "at" (missed; 0 = until midnight)
    "devices": ["<device>", ...],  which devices
    "sub", "args",                 the sub-script and its parameters
    "device_args": {device: {...}},  per-emulator parameters (e.g. other accounts), merged over "args"
    "pause_others": bool,          the main scripts do nothing on that emulator while it runs (guard rules still do)
    "max_minutes": minutes}]}      stop it if it runs longer than this

What the users change on the operation panel - a schedule's switch, start time and emulators - is kept where it
runs, over the design: <runtime dir>/schedule_overrides.json {"schedules": {id: {"enabled", "at", "devices"}}}.
effective() is the design with those on top; that is what runs.

Several due on one emulator: one after the other, in the order of their start time (then list order). "Done today"
is kept per schedule and emulator (whatever the result) and can be reset from the page."""
import atomic
import datetime
import json
import os
import re
import time
from project import word
from . import spec
import i18n
from i18n import _

FILE = os.path.join("meta", "schedules.json")
_cache = {}


def _read(data_root):
    p = os.path.join(data_root, FILE)
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


def load(data_root):
    return _read(data_root).get("schedules", [])


OVERRIDES = "schedule_overrides.json"
OVERRIDE_FIELDS = ("enabled", "at", "devices", "args", "device_args")   # args: a runtime's panel (the design is read-only)


def overrides(runtime_dir):
    p = os.path.join(runtime_dir, OVERRIDES)
    m = os.path.getmtime(p) if os.path.exists(p) else 0
    hit = _cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    d = {}
    if m:
        with open(p, encoding="utf-8") as f:
            d = json.load(f).get("schedules", {})
    _cache[p] = (m, d)
    return d


def effective(data_root, runtime_dir):
    """The schedules as they run: the design, with what the users changed on top ("overridden": which fields)."""
    from drivers.sources import expand
    ov = overrides(runtime_dir)
    out = []
    for s in load(data_root):
        o = {k: v for k, v in (ov.get(s["id"]) or {}).items() if k in OVERRIDE_FIELDS}
        e = {**s, **o, "overridden": sorted(o)} if o else dict(s)
        if any(str(d).startswith("#") for d in e.get("devices") or []):     # "#<tag>": every source with it, now
            e["devices_chosen"], e["devices"] = e["devices"], expand(e["devices"])
        out.append(e)
    return out


def set_override(data_root, runtime_dir, sid, field, value):
    """A user's change of a schedule's switch / start time / emulators (None = back to the design)."""
    if field not in OVERRIDE_FIELDS:
        raise ValueError(_("這個欄位不能在面板上改"))
    if not any(s["id"] == sid for s in load(data_root)):
        raise ValueError(_("這個排程已經不存在"))
    if value is not None:
        if field == "enabled" and not isinstance(value, bool):
            raise ValueError(_("請選擇開或關"))
        if field == "at" and _hhmm(value) is None:
            raise ValueError(_("開始時間要像 20:00"))
        if field == "devices" and (not isinstance(value, list) or not all(isinstance(d, str) for d in value)):
            raise ValueError(_("機台清單不正確"))
        if field in ("args", "device_args") and not isinstance(value, dict):
            raise ValueError(_("參數不正確"))
    p = os.path.join(runtime_dir, OVERRIDES)
    d = {k: dict(v) for k, v in overrides(runtime_dir).items()}
    mine = d.setdefault(sid, {})
    if value is None:
        mine.pop(field, None)
    else:
        mine[field] = value
    d = {k: v for k, v in d.items() if v}
    os.makedirs(runtime_dir, exist_ok=True)
    atomic.write_json(p, {"schedules": d, "saved": time.time()}, ensure_ascii=False, indent=1)
    _cache.pop(p, None)


def day_start(data_root):
    """Minutes after midnight when a day begins (an app's daily reset, e.g. 04:30)."""
    return _hhmm(_read(data_root).get("day_start") or "00:00") or 0


def _hhmm(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def validate(items, subs):
    ids = set()
    for s in items:
        where = _("排程「{p1}」", p1=s.get('name') or s.get('id'))
        if not re.fullmatch(r"[a-z][a-z0-9_]*", s.get("id") or ""):
            raise ValueError(_("{where}:代號只能用小寫英文、數字、底線,且以英文開頭", where=where))
        if s["id"] in ids:
            raise ValueError(_("{where}:代號重複", where=where))
        ids.add(s["id"])
        if not s.get("name"):
            raise ValueError(_("{where}:請取個名稱", where=where))
        if _hhmm(s.get("at")) is None:
            raise ValueError(_("{where}:開始時間要像 20:00", where=where))
        if any(d not in range(7) for d in s.get("days") or []):
            raise ValueError(_("{where}:星期設定不正確", where=where))
        if not 0 <= int(s.get("window", 120)) <= 1440:
            raise ValueError(_("{where}:錯過多久內補做要在 0~1440 分鐘", where=where))
        if not 1 <= int(s.get("max_minutes", 240)) <= 1440:
            raise ValueError(_("{where}:最長執行時間要在 1~1440 分鐘", where=where))
        if s.get("sub") not in subs:
            raise ValueError(_("{where}:找不到子腳本「{sub}」", where=where, sub=s.get('sub')))
        if not s.get("devices"):
            raise ValueError(_("{where}:請選擇至少一台{p2}", where=where, p2=word("device")))


def save(data_root, items, subs, start=None):
    validate(items, subs)
    start = start if start is not None else _read(data_root).get("day_start", "00:00")
    if _hhmm(start) is None:
        raise ValueError(_("每天的開始時間要像 04:30"))
    keep = ("id", "name", "enabled", "at", "days", "window", "devices", "sub", "args", "device_args", "pause_others", "max_minutes")
    out = [{k: s[k] for k in keep if k in s} for s in items]
    p = os.path.join(data_root, FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, spec.stamp({"day_start": start, "schedules": out, "saved": time.time()}), ensure_ascii=False, indent=1)
    _cache.pop(p, None)
    return out


def args_for(s, device):
    return {**(s.get("args") or {}), **((s.get("device_args") or {}).get(device) or {})}


def _day(now, ds):
    """The day (a date) that now belongs to, when days begin ds minutes after midnight."""
    return (datetime.datetime.fromtimestamp(now) - datetime.timedelta(minutes=ds)).date()


def window(s, now, ds=0):
    """(start, end) of this day's window as timestamps, or None if it does not run this day. A day runs from
    ds minutes after midnight to the same time the next morning; a start time before that belongs to the morning."""
    d = _day(now, ds)
    if s.get("days") and d.weekday() not in s["days"]:
        return None
    mid = datetime.datetime(d.year, d.month, d.day).timestamp()
    day_end = mid + ds * 60 + 86400 - 1
    at = _hhmm(s["at"])
    start = mid + at * 60 + (86400 if at < ds else 0)
    w = int(s.get("window", 120))
    end = day_end if w == 0 else min(day_end, start + w * 60)
    return start, end


def today(now, ds=0):
    return _day(now, ds).strftime("%Y-%m-%d")


class State:
    """Which schedule ran today on which emulator (kept in the runtime dir; a new day starts empty)."""

    def __init__(self, path, ds=0):
        self.path = path
        self.day_start = ds                          # minutes after midnight a day begins (kept up to date by the caller)
        try:
            self.data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("day", None)
        self.data.setdefault("done", {})

    def _roll(self, now):
        if self.data["day"] != today(now, self.day_start):
            self.data = {"day": today(now, self.day_start), "done": {}}
            self.write()

    def done(self, sid, dev, now):
        self._roll(now)
        return (self.data["done"].get(sid) or {}).get(dev)

    def mark(self, sid, dev, now, result, message="", run_id=None, plain=""):
        """message: the technical reason (the designer's pages); plain: the same in plain words (the users')."""
        self._roll(now)
        self.data["done"].setdefault(sid, {})[dev] = {"t": round(now, 3), "result": result, "message": message, "run": run_id,
                                                      **({"plain": plain} if plain and plain != message else {})}
        self.write()

    def reset(self, sid, dev=None):
        if dev:
            (self.data["done"].get(sid) or {}).pop(dev, None)
        else:
            self.data["done"].pop(sid, None)
        self.write()

    def write(self):
        try:
            atomic.write_json(self.path, self.data, ensure_ascii=False)
        except OSError:
            pass


def due(items, dev, now, state):
    """Schedules that should start on dev now, in order (earliest start first)."""
    out = []
    for i, s in enumerate(items):
        if not s.get("enabled", True) or dev not in (s.get("devices") or []):
            continue
        w = window(s, now, state.day_start)
        if w and w[0] <= now <= w[1] and not state.done(s["id"], dev, now):
            out.append((w[0], i, s))
    return [s for _x, _x, s in sorted(out, key=lambda x: (x[0], x[1]))]


def describe(s, dev, now, state, running=None):
    """Today's status of a schedule on one emulator for the page: (code, text)."""
    d = state.done(s["id"], dev, now)
    if running:
        return "running", _("執行中")
    if d:
        r = {"success": _("完成"), "partial": _("部分完成"), "failed": _("失敗"), "interrupted": _("中斷"), "missed": _("錯過")}.get(d["result"], d["result"])
        from .runner import plain_fail
        why = d.get("plain") or (plain_fail({}, d["message"]) if d.get("message") and d["result"] in ("failed", "partial") else d.get("message"))
        why = i18n.relang(why)
        when = f"{r} {datetime.datetime.fromtimestamp(d['t']):%H:%M}"
        if not why or (d["result"] == "success" and why == _("完成")):     # "完成 09:40", not "完成 09:40:完成"
            return d["result"], when
        return d["result"], _("{p1}:{p2}", p1=when, p2=why)
    if not s.get("enabled", True):
        return "off", _("停用")
    w = window(s, now, state.day_start)
    if not w:
        return "not_today", _("今天不執行")
    if now < w[0]:
        return "later", _("{at} 開始", at=s['at'])
    if now > w[1]:
        return "missed", _("已錯過")
    return "due", _("等待開始")
