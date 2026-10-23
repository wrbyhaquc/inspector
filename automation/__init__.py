"""Scripts designed on the web page (no code): prioritised "if ... then ..." rules over the model's states.

Stored like the state definitions, one folder per script under <data_root>/meta/scripts/<script id>/:
  v<N>.json      every saved version (never modified)
  current.json   {"version": N}
  settings.json  SETTINGS - where it runs, on / off, each rule's on / off and limits: adjusting them makes no new
                 version, and loading an old version keeps them (project/overlay.py)

A main script (主腳本, always running while enabled) is a small state machine of situations (情境):
  {"id", "name", "description", "enabled",
   "devices": {"*": mode, "<device>": mode},     mode = "off" | "shadow" | "live"  ("*" = every other device)
   "initial": situation id,                     where every device starts (default: the first)
   "situations": [ {"id", "name",
                    "rules": [rule, ...],        only the rules of a device's current situation are checked
                    "on_enter": [step, ...],     done once on entering (e.g. call a sub-script)
                    "max_seconds": n | null,     staying longer -> go to "on_timeout" (default: initial)
                    "on_timeout": situation id} ],
   "otherwise": {"type": "none", "text": ...}}
  rule   = {"id", "name", "enabled", "urgent", "when": [[cond, ...], ...], "do": [step, ...],
            "cooldown": seconds, "max_per_hour": n}       groups are OR-ed, conditions inside a group AND-ed
  The steps are those of a sub-script (automation/subs.py), plus goto (switch situation), stay (do nothing, and no
  lower rule acts) and, in the guard rules, hold (the other scripts wait). [] = do nothing.
  The runtime acts on one "action" per rule (rule_action()): a single simple step is done as itself (a tap, a
  notice, a switch ...), a call followed by a switch keeps the call's on_success / on_fail, and anything longer runs
  as a sub-script of its own (inline_subs(), id "~<script>.<rule>").
  action = {"type": "tap" | "long_press" | "back" | "call" | "goto" | "set_var" | "wait" | "none" | "notify" | "stop" | "hold",
            "target", "sub", "args", "on_success", "on_fail", "situation", "var", "mode", "value", "output",
            "command", "text"}                                       (the runtime's form; scripts store "do")
  rule "max_per_day": n = at most n times per calendar day (per device), like max_per_hour
  cond: see automation/conds.py (state, became, count, change, time, always, var, elapsed, device)

Variables (meta/variables.json): [{"name", "label", "scope": "device" | "global", "reset": "daily" | "never",
"initial"}]. "device" = every emulator has its own value; "global" = one value shared by all. Their values live with
the runtime folder (vars.json) and are shown / editable on the runner page.
A script saved without situations (just "rules") is read as one situation.

The global guard rules (全域守門規則) are the script "guards": one rule list (no situations), checked before every
main script on every device, always first in priority. Its "stop" stops every script on that device; "hold" keeps
every other script from acting while it holds (and interrupts a running sub-script).

Rules are checked top to bottom; the first whose conditions hold decides. If the model is not sure enough about
a state a rule needs (confidence < min_conf) before any rule matched, the script decides "uncertain" and stops:
a lower-priority rule must not run just because a higher one could not be checked.
urgent: the rule acts on the first tick it matches (no second look) and may interrupt any sub-script running on
the device. Main scripts have one priority order (meta/scripts/order.json); on one device only one script acts at
a time (see runtime/shadow.py)."""
import atomic
import json
import os
import re
import shutil
import time


from . import spec
from .conds import OPS, check as check_cond
from project import word
from i18n import N_, _

GUARD_ID = "guards"
MODES = {"off": N_("關閉"), "shadow": N_("試跑(只看不點)"), "live": N_("正式執行")}
ACTIONS = {"tap": N_("點擊"), "long_press": N_("長按"), "back": N_("返回鍵"), "call": N_("呼叫子腳本"), "goto": N_("切換情境"),
           "set_var": N_("設定變數"), "wait": N_("等待"), "none": N_("不動作"), "notify": N_("通知"), "stop": N_("停止腳本"),
           "hold": N_("暫停其他腳本"), "output": N_("送到輸出")}
VAR_MODES = {"set": N_("設成"), "add": N_("加上"), "now": N_("記下現在時間")}
VAR_SCOPES = {"device": N_("每台{device}各自一份"), "global": N_("全部共用一份")}
VAR_RESETS = {"daily": N_("每天 0 點歸零"), "never": N_("不歸零")}
GUARD_ONLY = {"hold"}


def mode_label(mode):
    """A deploy mode in the current language."""
    return _(MODES.get(mode, mode)) if mode is not None else ""
SCRIPT_ONLY = {"goto"}
TAPPING = {"tap", "long_press", "back", "call", "output"}   # actions that act on something in live mode



def _dir(data_root, sid=None):
    d = os.path.join(data_root, "meta", "scripts")
    return os.path.join(d, sid) if sid else d


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write(p, obj):
    atomic.write_json(p, obj, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- situations
def normalize(script):
    """A script with "situations" (a script saved as plain "rules" becomes one situation)."""
    s = dict(script)
    if not s.get("situations"):
        s["situations"] = [{"id": "main", "name": _("一般"), "rules": s.get("rules") or []}]
    s.pop("rules", None)
    if s.get("initial") not in {x["id"] for x in s["situations"]}:
        s["initial"] = s["situations"][0]["id"]
    return s


def situation(script, sid):
    for x in script["situations"]:
        if x["id"] == sid:
            return x
    return script["situations"][0]


def all_rules(script):
    return [r for x in script["situations"] for r in x.get("rules") or []]


def is_guard(script):
    return script.get("id") == GUARD_ID


# ---------------------------------------------------------------- variables
def _var_path(data_root):
    return os.path.join(data_root, "meta", "variables.json")


def variables(data_root):
    p = _var_path(data_root)
    return _read(p).get("vars", []) if os.path.exists(p) else []


def check_variables(defs):
    names = [v.get("name") for v in defs]
    if len(set(names)) != len(names):
        raise ValueError(_("變數代號重複"))
    for v in defs:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v.get("name") or ""):
            raise ValueError(_("變數代號「{name}」只能用小寫英文、數字、底線,且以英文開頭", name=v.get('name')))
        if v.get("scope") not in VAR_SCOPES or v.get("reset") not in VAR_RESETS:
            raise ValueError(_("變數「{p1}」的範圍或歸零方式不正確", p1=v.get('label') or v['name']))
        if not isinstance(v.get("initial", 0), (int, float)):
            raise ValueError(_("變數「{p1}」的初始值要是數字", p1=v.get('label') or v['name']))


def save_variables(data_root, defs):
    check_variables(defs)
    in_use = {}
    for sc in load_all(data_root):
        for r in all_rules(sc):
            for g in r.get("when") or []:
                for c in g:
                    if c.get("var"):
                        in_use.setdefault(c["var"], sc["name"])
            from .subs import walk
            for st in walk(r.get("do") or []):
                if st.get("var"):
                    in_use.setdefault(st["var"], sc["name"])
    gone = [n for n in in_use if n not in {v["name"] for v in defs}]
    if gone:
        raise ValueError(_("還有腳本在用這些變數:") + _("、").join(_("{var}(「{x}」)", var=n, x=in_use[n]) for n in gone))
    os.makedirs(os.path.dirname(_var_path(data_root)), exist_ok=True)
    _write(_var_path(data_root), spec.stamp({"vars": defs, "saved": time.time()}))
    return defs


# ---------------------------------------------------------------- storage
def ids(data_root):
    """The scripts there are (reading never makes one: a new project starts with none, a pack ships its own)."""
    d = _dir(data_root)
    if not os.path.isdir(d):
        return []
    return sorted(s for s in os.listdir(d) if os.path.exists(os.path.join(d, s, "current.json")))


def order(data_root):
    """Script ids by priority (first = highest): the guard rules always first, then the main scripts in the saved
    order; scripts not listed yet come last, by id."""
    p = os.path.join(_dir(data_root), "order.json")
    listed = _read(p).get("order", []) if os.path.exists(p) else []
    have = [s for s in ids(data_root) if s != GUARD_ID]
    main = [s for s in listed if s in have] + [s for s in have if s not in listed]
    return ([GUARD_ID] if os.path.exists(os.path.join(_dir(data_root, GUARD_ID), "current.json")) else []) + main


def set_order(data_root, sids):
    have = {s for s in ids(data_root) if s != GUARD_ID}
    sids = [s for s in sids if s != GUARD_ID]
    if set(sids) != have:
        raise ValueError(_("順序清單要剛好包含每個主腳本"))
    os.makedirs(_dir(data_root), exist_ok=True)
    _write(os.path.join(_dir(data_root), "order.json"), spec.stamp({"order": list(sids)}))


# not the design: changing only these saves no new version (project/overlay.py)
SETTINGS = ("devices", "enabled", "situations[].rules[].enabled", "situations[].rules[].cooldown",
            "situations[].rules[].max_per_hour", "situations[].rules[].max_per_day")


ENTRY_ARGS = "entry_args.json"


def _entry_args():
    """A runtime's values for the arguments of situation entries the operation panel sets (the design is read-only):
    <runtime>/entry_args.json {script id: {situation id: {param: value}}}. {} in a studio."""
    import project
    if project.edition() != "runtime":
        return {}
    try:
        with open(os.path.join(project.runtime_dir(), ENTRY_ARGS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_entry_arg(sid, situation, param, value):
    import project
    d = _entry_args()
    d.setdefault(sid, {}).setdefault(situation, {})[param] = value
    os.makedirs(project.runtime_dir(), exist_ok=True)
    _write(os.path.join(project.runtime_dir(), ENTRY_ARGS), d)


def load(data_root, sid, version=None):
    from project import overlay
    d = _dir(data_root, sid)
    v = version or _read(os.path.join(d, "current.json"))["version"]
    obj = _read(os.path.join(d, f"v{int(v)}.json"))
    spec.check(obj, _("腳本 {sid}", sid=sid))
    out = normalize(overlay.apply(spec.upgrade(obj), overlay.read(d), SETTINGS))
    for sit_id, args in (_entry_args().get(sid) or {}).items():
        call = enter_call(next((x for x in out.get("situations") or [] if x.get("id") == sit_id), None) or {})
        if call is not None:
            call["args"] = {**(call.get("args") or {}), **args}
    return out


def load_all(data_root):
    """All scripts in priority order (the guard rules first, if there are any). One written by a newer spec is left
    out (with a message) rather than misread."""
    out = []
    for s in order(data_root):
        try:
            out.append(load(data_root, s))
        except ValueError as e:
            print(e, flush=True)
    return out


def signature(data_root):
    """Changes whenever any script, the order or a sub-script is saved (the runtime reloads then)."""
    from . import subs
    d = _dir(data_root)
    if not os.path.isdir(d):
        return ""
    op, vp = os.path.join(d, "order.json"), _var_path(data_root)
    from project import overlay
    return "|".join(f"{s}:{os.path.getmtime(os.path.join(d, s, 'current.json'))}:{overlay.mtime(os.path.join(d, s))}"
                    for s in sorted(os.listdir(d)) if os.path.exists(os.path.join(d, s, "current.json"))) + \
        f"|order:{os.path.getmtime(op) if os.path.exists(op) else 0}|subs:{subs.signature(data_root)}" + \
        f"|vars:{os.path.getmtime(vp) if os.path.exists(vp) else 0}|entry:{_entry_args_mtime()}"


def _entry_args_mtime():
    import project
    p = os.path.join(project.runtime_dir(), ENTRY_ARGS)
    return os.path.getmtime(p) if project.edition() == "runtime" and os.path.exists(p) else 0


def history(data_root, sid):
    d = _dir(data_root, sid)
    out = []
    for f in os.listdir(d):
        m = re.fullmatch(r"v(\d+)\.json", f)
        if m:
            s = _read(os.path.join(d, f))
            out.append({"version": s["version"], "created": s.get("created"), "note": s.get("note", "")})
    return sorted(out, key=lambda x: x["version"])


# ---------------------------------------------------------------- what the runtime does for a step list
INLINE = "~"


def inline_id(script_id, key):
    return f"{INLINE}{script_id}.{key}"


def _say(st):
    return st.get("say") or st.get("text")


def steps_action(steps, sub_id, name=""):
    """The runtime's one action for a rule's / an entry's steps (see the module doc). sub_id: the id its own
    sub-script would have when it needs one."""
    steps = list(steps or [])
    simple = len(steps) == 1 and not steps[0].get("after")
    st = steps[0] if steps else {}
    t = st.get("type")
    if not steps:
        return {"type": "none", "text": _("不動作")}
    if simple and t == "stay":
        return {"type": "wait", "text": st.get("text") or _("等待")}
    if simple and t in ("hold", "stop", "notify"):
        return {"type": t, "text": st.get("text") or _(ACTIONS[t])}
    if simple and t == "goto":
        return {"type": "goto", "situation": st.get("situation"), **({"text": _say(st)} if _say(st) else {})}
    if simple and t in ("tap", "long_press", "back"):
        return {"type": t, **({"target": st.get("target") or {}} if t != "back" else {}),
                **({"ms": st["ms"]} if "ms" in st else {}), **({"text": _say(st)} if _say(st) else {})}
    if simple and t == "set_var":
        return {"type": "set_var", **{k: st[k] for k in ("var", "mode", "value") if k in st}}
    if simple and t == "output":
        return {"type": "output", **{k: st[k] for k in ("output", "command", "value") if k in st}}
    if t == "call" and not st.get("after") and len(steps) <= 2:
        tail = steps[1] if len(steps) == 2 else None
        fail = st.get("on_fail", "fail")
        if tail is None or (tail.get("type") in ("goto", "stop") and fail in ("fail", "stop")):
            a = {"type": "call", "sub": st.get("sub"), "args": st.get("args") or {}}
            if st.get("say"):
                a["text"] = st["say"]
            if fail == "stop":
                a["on_fail"] = "stop"
            elif fail == "continue" and st.get("fail_goto"):
                a["on_fail"] = st["fail_goto"]
            if tail is not None:
                a["on_success"] = tail.get("situation") if tail["type"] == "goto" else "stop"
            if tail is None or fail == "stop" or tail["type"] == "goto":
                return a
    return {"type": "call", "sub": sub_id, "args": {}, "text": name or _("依序做這些步驟")}


def rule_action(script, r):
    return steps_action(r.get("do"), inline_id(script["id"], r.get("id")), r.get("name") or "")


def enter_action(script, sit):
    """A situation's entry as one action (None: nothing to do on entering)."""
    if not sit.get("on_enter"):
        return None
    return steps_action(sit["on_enter"], inline_id(script["id"], f"enter.{sit['id']}"), _("進入「{name}」", name=sit.get('name', '')))


def enter_call(sit):
    """The first call step of a situation's entry (its arguments can be set from the operation panel), or None."""
    from .subs import walk
    return next((st for st in walk(sit.get("on_enter") or []) if st.get("type") == "call"), None)


def inline_subs(scripts):
    """id -> sub-script, for the step lists that run as a sub-script of their own (rules / entries of the scripts)."""
    out = {}
    for sc in scripts:
        for sit in sc.get("situations") or []:
            items = [(r.get("do"), rule_action(sc, r), r.get("name") or r.get("id")) for r in sit.get("rules") or []]
            if sit.get("on_enter"):
                items.append((sit["on_enter"], enter_action(sc, sit), _("進入「{name}」", name=sit.get('name', ''))))
            for steps, a, name in items:
                if a.get("type") == "call" and str(a.get("sub", "")).startswith(INLINE):
                    out[a["sub"]] = {"id": a["sub"], "name": f"{sc['name']}:{name}", "steps": steps, "params": [],
                                     "cleanup": [], "timeout": 3600, "inline": True}
    return out


# ---------------------------------------------------------------- validation
def engine_tap_point(p):
    from .engine import tap_point
    return tap_point({"target": p})


def _check_action(a, label, script, lib, situation_ids, var_names=None):
    guard = is_guard(script)
    t = a.get("type")
    if t not in ACTIONS or (t in GUARD_ONLY and not guard) or (t in SCRIPT_ONLY and guard):
        raise ValueError(_("{label}:動作不正確", label=label))
    if t == "goto" and a.get("situation") not in situation_ids:
        raise ValueError(_("{label}:請選擇要切換到哪個情境", label=label))
    if t == "call":
        sub = (lib or {}).get(a.get("sub"))
        if not sub:
            raise ValueError(_("{label}:請選擇要呼叫的子腳本", label=label))
        for p in sub.get("params") or []:
            v = (a.get("args") or {}).get(p["name"], p.get("default"))
            if v is None:
                raise ValueError(_("{label}:呼叫「{name}」要填參數「{p3}」", label=label, name=sub['name'], p3=p.get('label') or p['name']))
            if isinstance(v, dict) and set(v) == {"setting"}:     # a user setting: checked when it is saved
                from . import settings
                if v["setting"] not in settings.load():
                    raise ValueError(_("{label}:參數「{p2}」用的使用者設定「{setting}」不存在", label=label, p2=p.get('label') or p['name'], setting=v['setting']))
                continue
            if p["type"] == "point" and engine_tap_point(v) is None:
                raise ValueError(_("{label}:參數「{p2}」請選擇位置", label=label, p2=p.get('label') or p['name']))
        for k in ("on_success", "on_fail"):
            v = a.get(k)
            if v is not None and v != "stop" and (guard or v not in situation_ids):
                raise ValueError(_("{label}:子腳本結束後要切到的情境不存在", label=label))
    if t == "output":
        from . import outputs
        outputs.check_action(a, label, var_names=var_names, allow_params=False)
    if t in ("tap", "long_press") and engine_tap_point(a.get("target") or {}) is None:
        raise ValueError(_("{label}:請選擇要點的位置", label=label))
    if t == "set_var":
        if var_names is not None and a.get("var") not in var_names:
            raise ValueError(_("{label}:請選擇變數(變數在左邊「變數」新增)", label=label))
        if a.get("mode") not in VAR_MODES:
            raise ValueError(_("{label}:變數要設成、加上,還是記下時間?", label=label))
        if a["mode"] != "now":
            if a.get("value") is None:
                raise ValueError(_("{label}:請填數字", label=label))
            from . import settings, values
            values.check(a["value"], label, "number", settings=settings.load(), var_names=var_names, allow_params=False)


def _check_do(steps, label, script, lib, sids, states, var_names, kind):
    """A rule's / an entry's steps: the steps of a sub-script, plus goto / stay / hold where they belong."""
    from . import subs
    if not isinstance(steps, list):
        raise ValueError(_("{label}:要做的事寫法不正確", label=label))
    place = {"label": f"{label} › ", "kind": kind, "guard": is_guard(script), "situations": sids}
    subs._check_steps(steps, {"name": label, "params": [], "_place": place}, lib or {}, states, "", None, var_names)


def validate(script, schema=None, lib=None, var_names=None):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", script.get("id", "")):
        raise ValueError(_("腳本代號只能用小寫英文、數字、底線,且以英文開頭"))
    if not script.get("name"):
        raise ValueError(_("請替腳本取個名稱"))
    for dev, mode in (script.get("devices") or {}).items():
        if mode not in MODES:
            raise ValueError(_("{dev}:執行方式不正確", dev=dev))
    sits = script.get("situations") or []
    if not sits:
        raise ValueError(_("至少要有一個情境"))
    if is_guard(script) and len(sits) != 1:
        raise ValueError(_("全域守門規則沒有情境,只有一份規則清單"))
    sids = [x.get("id") for x in sits]
    if len(set(sids)) != len(sids) or not all(re.fullmatch(r"[a-z][a-z0-9_]*", x or "") for x in sids):
        raise ValueError(_("情境代號空白、重複,或不是小寫英文開頭"))
    if script.get("initial") not in sids:
        raise ValueError(_("請選擇一開始的情境"))
    states = {s["id"]: s for s in (schema or {}).get("states", [])}
    rids = set()
    for sit in sits:
        where = _("情境「{name}」", name=sit.get('name', '')) if len(sits) > 1 else ""
        if not sit.get("name"):
            raise ValueError(_("情境 {id}:請取個名稱", id=sit.get('id')))
        if sit.get("on_enter"):
            _check_do(sit["on_enter"], _("{where}的進入時動作", where=where), script, lib, sids, states, var_names, "enter")
        if sit.get("max_seconds") is not None:
            if not 1 <= float(sit["max_seconds"]) <= 86400:
                raise ValueError(_("{where}:最長停留秒數要在 1~86400", where=where))
            if sit.get("on_timeout") not in sids:
                raise ValueError(_("{where}:請選擇逾時後要切到的情境", where=where))
        for i, r in enumerate(sit.get("rules") or [], 1):
            label = _("{where}第 {i} 條規則「{name}」", where=where, i=i, name=r.get('name', ''))
            if not r.get("id") or r["id"] in rids:
                raise ValueError(_("{label}:代號空白或重複", label=label))
            rids.add(r["id"])
            if not r.get("when") or not all(r["when"]):
                raise ValueError(_("{label}:至少要有一個條件", label=label))
            for group in r["when"]:
                for c in group:
                    check_cond(c, states, var_names, label)
            if r.get("max_per_day") is not None and not (isinstance(r["max_per_day"], int) and r["max_per_day"] >= 1):
                raise ValueError(_("{label}:每天最多幾次要是 1 以上的整數", label=label))
            _check_do(r.get("do") or [], label, script, lib, sids, states, var_names, "rule")


def save(data_root, script, note=""):
    import schema as schema_mod
    from . import subs
    script = normalize(spec.upgrade({k: v for k, v in script.items() if k != "flows"}))
    validate(script, schema_mod.load(data_root) if os.path.isdir(os.path.join(data_root, "meta", "states")) else None,
             subs.load_all(data_root), {v["name"] for v in variables(data_root)})
    import drivers
    drivers.check_script(script, _("腳本「{name}」", name=script.get('name', '')), data_root)
    from project import overlay
    d = _dir(data_root, script["id"])
    os.makedirs(d, exist_ok=True)
    cur = load(data_root, script["id"]) if os.path.exists(os.path.join(d, "current.json")) else None
    same = cur and overlay.strip(cur, SETTINGS) == overlay.strip(normalize(script), SETTINGS)
    import project
    if not same and project.edition() == "runtime":   # a runtime keeps its settings, never a new design
        raise ValueError(_("執行版只能改腳本的設定(哪台跑、啟用、次數限制),腳本內容要在 Studio 修改"))
    overlay.write(d, overlay.extract(script, SETTINGS))
    if same:
        return {**load(data_root, script["id"]), "settings_only": True}       # only settings changed: no new version
    vs = [h["version"] for h in history(data_root, script["id"])] if os.path.isdir(d) else []
    v = (max(vs) if vs else 0) + 1
    out = spec.stamp({**script, "version": v, "created": time.time(), "note": note})
    _write(os.path.join(d, f"v{v}.json"), out)
    _write(os.path.join(d, "current.json"), {"version": v})
    return out


def delete(data_root, sid):
    """Moved to <scripts>/.deleted/<id>_<time> (versions kept, not used any more)."""
    d = _dir(data_root, sid)
    if not os.path.isdir(d):
        raise ValueError(_("找不到這個腳本"))
    trash = os.path.join(_dir(data_root), ".deleted")
    os.makedirs(trash, exist_ok=True)
    shutil.move(d, os.path.join(trash, f"{sid}_{int(time.time())}"))


def mode_for(script, device):
    """off / shadow / live on one source: its id, else its tags (#<tag>, the most careful), else "*" (drivers/sources.py)."""
    from drivers.sources import mode_of
    return mode_of(script.get("devices") or {}, device)
