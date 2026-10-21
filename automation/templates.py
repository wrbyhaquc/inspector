"""Ready-made scripts, sub-scripts and guard rules (「從範本新增」): a starting point to change, never saved as is.

Two kinds:
  built in   generic skeletons that fit any project (do something every day, every N minutes, tap until something
             shows, close windows until ...); a condition starts on the project's first state, to be changed
  project    the project's own ready-made items: <project>/meta/templates.json
             {"templates": [{"id", "kind": "script" | "sub" | "guard_rules", "name", "description", "item": {...}}]}
             (a script / sub-script, or a list of guard rules, exactly as they are to be copied)

templates(data_root) lists both; make(...) returns {"kind", "item"} with ids that are not taken yet. Guard-rule
templates are rules to add to the global guard rules."""
import copy
import json
import os
from i18n import N_, _, tr

FILE = os.path.join("meta", "templates.json")

TEMPLATES = [
    {"id": "daily", "kind": "script", "name": N_("每天定時做一件事"),
     "description": N_("每天在指定時段內做一次(例如 05:00 呼叫某個子腳本)。")},
    {"id": "every", "kind": "script", "name": N_("每隔一段時間做一件事"),
     "description": N_("條件「總是」加上冷卻時間,例如每 30 分鐘通知一次或點一次某個按鈕。")},
    {"id": "tap_until", "kind": "sub", "name": N_("點擊直到畫面出現"),
     "description": N_("點一個位置,等到某個狀態成立;沒成立就再點,最多 3 次。適合開視窗、切分頁。(條件先用第一個狀態,請改成你要等的)")},
    {"id": "close_until", "kind": "sub", "name": N_("一直關視窗直到回到主畫面"),
     "description": N_("反覆點關閉鈕,直到某個狀態成立(回到主畫面),最多 5 次。(條件先用第一個狀態,請改成你要的)")},
]


def _rule(rid, name, when, action, **kw):
    from .spec import action_steps
    return {"id": rid, "name": name, "enabled": True, "cooldown": kw.pop("cooldown", 10), "when": when, "do": action_steps(action), **kw}


def _project(data_root):
    p = os.path.join(data_root, FILE) if data_root else None
    if not p or not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("templates", [])


def templates(data_root=None):
    """Every template: the project's first, then the built-in ones (without their contents)."""
    own = [{k: t[k] for k in ("id", "kind", "name", "description")} | {"from": "project"} for t in _project(data_root)]
    return own + [t | {"from": "builtin"} for t in tr(TEMPLATES) if t["id"] not in {x["id"] for x in own}]


def _free(base, taken):
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _cond(states):
    """A placeholder condition: the project's first state, its first answer."""
    s = next((x for x in states or [] if x.get("classes")), None)
    if not s:
        return {"kind": "always"}
    return {"state": s["id"], "op": "is", "value": s["classes"][0]["value"], "min_conf": 0.7}


def make(tid, taken=(), subs=None, states=None, data_root=None):
    """A fresh copy of template tid, with a script / sub-script id that is not in taken. states: the schema's states."""
    taken, subs = set(taken), subs or {}
    own = next((t for t in _project(data_root) if t["id"] == tid), None)
    if own:
        item = copy.deepcopy(own["item"])
        if own["kind"] in ("script", "sub"):
            item["id"] = _free(item.get("id") or tid, taken)
        return {"kind": own["kind"], "item": item}
    t = next((x for x in tr(TEMPLATES) if x["id"] == tid), None)
    if not t:
        raise ValueError(_("沒有這個範本"))
    base = {"description": t["description"], "enabled": True, "devices": {"*": "shadow"},
            "otherwise": {"type": "none", "text": _("不動作")}}
    if tid == "daily":
        act = {"type": "call", "sub": next(iter(subs), None), "args": {}, "text": _("每天的工作")} if subs else {"type": "notify", "text": _("每天的提醒")}
        item = {**base, "id": _free("daily", taken), "name": t["name"], "initial": "main", "situations": [
            {"id": "main", "name": _("一般"), "rules": [
                _rule("r1", _("每天 05:00 做一次"), [[{"kind": "time", "from": "05:00", "to": "05:10", "days": []}]], act,
                      cooldown=60, max_per_day=1)]}]}
        return {"kind": "script", "item": item}
    if tid == "every":
        item = {**base, "id": _free("every", taken), "name": t["name"], "initial": "main", "situations": [
            {"id": "main", "name": _("一般"), "rules": [
                _rule("r1", _("每 30 分鐘一次"), [[{"kind": "always"}]], {"type": "notify", "text": _("定時提醒")}, cooldown=1800)]}]}
        return {"kind": "script", "item": item}
    if tid == "tap_until":
        item = {"id": _free("tap_until", taken), "name": t["name"], "description": t["description"], "timeout": 60,
                "params": [{"name": "target", "label": _("要點的位置"), "type": "point"}],
                "steps": [{"type": "retry", "times": 3, "delay": 1, "steps": [
                    {"type": "tap", "target": {"param": "target"}},
                    {"type": "wait_until", "when": [[_cond(states)]], "timeout": 4, "on_timeout": "fail"}]}],
                "cleanup": []}
        return {"kind": "sub", "item": item}
    item = {"id": _free("close_until", taken), "name": t["name"], "description": t["description"], "timeout": 60,
            "params": [{"name": "close", "label": _("關閉鈕的位置"), "type": "point"}],
            "steps": [{"type": "repeat_until", "when": [[_cond(states)]], "max_times": 5, "max_seconds": 40,
                       "steps": [{"type": "tap", "target": {"param": "close"}}, {"type": "wait", "seconds": 1.5}]}],
            "cleanup": []}
    return {"kind": "sub", "item": item}
