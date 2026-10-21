"""Evaluate a script (see automation/__init__.py) on one device's smoothed model state."""
import json
import time

from . import ACTIONS, situation as get_situation
from . import conds
from .conds import DEFAULT_MIN_CONF, MATCH, NO, UNSURE   # noqa: F401  (used by runner / runtime)
from project import word
from i18n import _


class Tracker:
    """Remembers since when each condition has held (for "for N seconds"), per device and script."""

    def __init__(self):
        self.since = {}

    def held(self, key, true, now):
        if not true:
            self.since.pop(key, None)
            return 0.0
        self.since.setdefault(key, now)
        return now - self.since[key]


def names_from_schema(schema):
    """state id -> {"name", "type", "classes": {value(str): name}} for readable reasons."""
    return {s["id"]: {"name": s["name"], "type": s["type"],
                      "classes": {json.dumps(c["value"]): c["name"] for c in s.get("classes", [])}}
            for s in schema["states"]}


def describe(c, names, var_labels=None):
    return conds.describe(c, names, var_labels)


def _group(group, state, tracker, prefix, now, ctx=None):
    res = [conds.evaluate(c, state, tracker, f"{prefix}:{i}", now, ctx) for i, c in enumerate(group)]
    if NO in res:
        return NO
    return UNSURE if UNSURE in res else MATCH


def tap_point(action):
    """The tap position of a target (a find button: where it was picked; the runtime looks for it first)."""
    t = action.get("target") or {}
    if "button" in t:
        from . import buttons
        b = buttons.load().get(t["button"])
        return [b["x"], b["y"]] if b else None
    if "x" in t and "y" in t:
        return [t["x"], t["y"]]
    return None


def evaluate(script, state, tracker, names, device="", now=None, subs=None, situation=None, ctx=None):
    """The decision of one script on one device, from the rules of the device's current situation.
    subs = the sub-script library, to name and outline what a "call" action would run.
    ctx = history / variables / other devices for the time and memory conditions (automation/conds.py)."""
    sit = get_situation(script, situation or script.get("initial"))
    d = _evaluate(script, sit.get("rules") or [], state, tracker, names, device, now, subs or {}, ctx or {})
    d["situation"], d["situation_name"] = sit["id"], sit.get("name")
    missing = sorted({c["state"] for r in sit.get("rules") or [] if r.get("enabled", True)
                      for g in r["when"] for c in g if names and c.get("state") and c["state"] not in names})
    if missing:
        d["warnings"] = [_("用到不存在的狀態:{p1}(可能在狀態定義裡改了代號或刪除),相關規則已略過", p1=_("、").join(missing))]
    return d


def _evaluate(script, rules, state, tracker, names, device="", now=None, subs=None, ctx=None):
    """-> {"script", "script_name", "action", "text", "reason", "tap", "rule", "rule_name"}"""
    now = time.time() if now is None else now
    base = {"script": script["id"], "script_name": script["name"]}
    warnings = []
    if state is None:
        return {**base, "action": "no_window", "text": _("無法判斷"), "reason": _("找不到{p1}視窗,或視窗被縮到最小", p1=word("device")),
                "tap": None, "rule": None, "rule_name": None}
    unsure_first, warnings = None, []
    for r in rules:
        if not r.get("enabled", True):
            continue
        missing = sorted({c["state"] for g in r["when"] for c in g if names and c.get("state") and c["state"] not in names})
        if missing:          # the state was renamed or deleted in the state definitions: skip, don't block the rest
            warnings.append(_("規則「{name}」用到不存在的狀態 {p2},已略過", name=r.get('name', ''), p2=_("、").join(missing)))
            continue
        results = [_group(g, state, tracker, f"{device}:{script['id']}:{r['id']}:{gi}", now, ctx) for gi, g in enumerate(r["when"])]
        if MATCH in results:
            g = r["when"][results.index(MATCH)]
            from . import rule_action
            a = r.get("action") or rule_action(script, r)
            text = a.get("text") or _(ACTIONS.get(a.get("type"), ""))
            call = a.get("type") == "call"
            sub = (subs or {}).get(a.get("sub")) if call else None
            if call and not a.get("text"):
                text = _("呼叫子腳本「{name}」", name=(sub or {}).get('name', a.get('sub')))
            if a.get("type") == "output" and not a.get("text"):
                from .outputs import describe as out_text
                text = out_text(a)
            if a.get("type") == "goto" and not a.get("text"):
                text = _("切換到「{name}」", name=get_situation(script, a.get('situation')).get('name', a.get('situation')))
            from .subs import outline
            return {**base, "action": a.get("type", "none"), "text": text,
                    "reason": _("、").join(describe(c, names, (ctx or {}).get("var_labels")) for c in g), "tap": tap_point(a) if a.get("type") in ("tap", "long_press") else None,
                    "target": a.get("target") if a.get("type") in ("tap", "long_press") else None,
                    "rule": r["id"], "rule_name": r.get("name"), "cooldown": r.get("cooldown", 0), "max_per_hour": r.get("max_per_hour"),
                    "urgent": bool(r.get("urgent")), "max_per_day": r.get("max_per_day"),
                    "var": a.get("var"), "var_mode": a.get("mode"), "var_value": a.get("value"),
                    "output": a.get("output"), "command": a.get("command"),
                    "sub": a.get("sub") if call else None, "args": a.get("args") if call else None,
                    "on_success": a.get("on_success") if call else None, "on_fail": a.get("on_fail") if call else None,
                    "goto": a.get("situation") if a.get("type") == "goto" else None,
                    "sub_steps": outline(sub.get("steps"), names, subs, sub.get("params")) if sub else None}
        if UNSURE in results and unsure_first is None:
            unsure_first = r
            break                     # a higher-priority rule could not be checked: do not fall through
    if unsure_first is not None:
        needed = sorted({names.get(c["state"], {"name": c["state"]})["name"] if c.get("state") else conds.kind_label(c.get("kind"))
                         for g in unsure_first["when"] for c in g})
        return {**base, "action": "uncertain", "text": _("不動作"), "tap": None, "rule": unsure_first["id"],
                "rule_name": unsure_first.get("name"),
                "reason": _("模型對{p1}沒有把握,無法確認「{name}」", p1=_("、").join(needed), name=unsure_first.get('name', ''))}
    o = script.get("otherwise") or {"type": "none", "text": _("不動作")}
    return {**base, "action": o.get("type", "none"), "text": o.get("text", _("不動作")), "reason": _("沒有規則符合"),
            "tap": None, "rule": None, "rule_name": None}
