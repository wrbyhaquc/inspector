"""Sub-scripts (子腳本): reusable step sequences that main scripts (and other sub-scripts) call like functions.

Stored like scripts, one folder per sub-script under <data_root>/meta/subscripts/<id>/ (v<N>.json + current.json).

A sub-script:
  {"id", "name", "description",
   "params":  [{"name", "label", "type": "point" | "number" | "text" | "list", "item": item type of a list, "default"}],
   "steps":   [step, ...],
   "cleanup": [simple step, ...],   run when it is interrupted or fails (e.g. close the window it opened)
   "timeout": seconds}              the whole sub-script, including what it calls

Steps (nested blocks hold their own step lists):
  tap / long_press {"target", "ms"}       target = {"button"} | {"x", "y"} | {"param": name of a point parameter}
  swipe        {"from", "to", "ms"}       from/to: like target
  back         {}
  input_text   {"text"}                   type into the text box that has the focus (tap it first); {variable} filled in
  launch_app   {"package"}                start the app (or bring it to the front): after it was closed
  pick         {"target", "max_swipes", "settle"}   a name of a list (a place, an account): scroll the list until it
                                          shows, tap it once it has stayed put "settle" seconds (the list glides on)
  wait         {"seconds"}
  wait_until   {"when", "timeout", "on_timeout": "fail" | "continue"}
  if           {"when", "then": [...], "elif": [{"when", "then": [...]}, ...], "else": [...]}   (elif optional: 否則如果)
  retry        {"times", "delay", "steps": [...]}             a failure inside starts the block again
  repeat_until {"when", "steps": [...], "max_times", "max_seconds"}   run the steps, stop once the condition holds
  for_each     {"list": a list parameter, "as": name, "as_label", "steps": [...], "on_item_fail": "fail" | "continue"}
               run the steps once per item of the list; inside, parameter <as> is the item and <as>_no its number (1, 2..)
  call         {"sub", "args": {param: value}, "on_fail": "fail" | "continue"}
  notify       {"text"}
  ask          {"text", "options": [{"label", "then": [...]}], "timeout", "default": option no. | 0, "var"}
               ask people (a paired chat, the runner page, the operation panel) and wait for the answer; then run the
               steps of the option chosen. Nobody answers in "timeout" seconds: the "default" option (0 = fail).
               "var" (optional) keeps the chosen option's number (0 = nobody answered and no default)
  output       {"output", "command", "value"}   send to an output (automation/outputs.py)
  set_var      {"var", "mode": "set" | "add" | "now", "value"}   change a variable (see automation/__init__.py)
  succeed      {"text"}                   end this sub-script now, successfully
  fail         {"text"}                   fail here (a surrounding retry tries again)
  stop         {"text"}                   stop this device now (停下來, as from the page), saying why
  goto         {"situation"}              switch the main script to another situation (a main script's rules /
                                          entries only - a library sub-script has no situations)
  stay / hold  {"text"}                   a rule's only step: do nothing (and let no lower rule act) / keep the
                                          other scripts from acting while this guard rule holds
Every input step (tap, long_press, swipe, back, input_text, launch_app) may wait after it:
  "after": {"seconds": n} | {"until": when, "timeout": n, "on_timeout": "fail" | "continue"}
call "on_fail": "fail" (default) | "continue" | "stop" (stop this device).
when = [[cond, ...], ...] like a rule (groups OR-ed, conditions AND-ed).

A main script's rules and situation entries are step lists too (automation/__init__.py): they are checked here with a
"_place" ({"label", "kind": "rule" | "enter", "guard", "situations"}) that allows goto / stay / hold."""
import os
import re
import shutil
import time

from . import VAR_MODES, _read, _write, spec, values
from .conds import check as check_cond
from i18n import N_, _

STEP_TYPES = {"tap": N_("點擊"), "long_press": N_("長按"), "swipe": N_("滑動"), "back": N_("返回鍵"), "input_text": N_("輸入文字"), "launch_app": N_("啟動 App"), "pick": N_("在清單中找到並點擊"), "capture_list": N_("擷取清單(掃描新項目)"), "wait": N_("等待秒數"),
              "wait_until": N_("等到條件成立"), "if": N_("如果…否則"), "retry": N_("失敗就重試"), "repeat_until": N_("重複直到"),
              "for_each": N_("對每一個…"),
              "call": N_("呼叫子腳本"), "set_var": N_("設定變數"), "notify": N_("通知"), "ask": N_("問使用者"), "output": N_("送到輸出"),
              "succeed": N_("結束(成功)"), "fail": N_("結束(失敗)"),
              "goto": N_("切換情境"), "stop": N_("停下這台"), "stay": N_("原地等著(不動作)"), "hold": N_("暫停其他腳本")}
# how the step menu is grouped on the page
STEP_GROUPS = [(N_("操作畫面"), ["tap", "long_press", "swipe", "back", "input_text", "pick", "launch_app", "capture_list"]),
               (N_("等待"), ["wait", "wait_until"]),
               (N_("判斷與重複"), ["if", "repeat_until", "for_each", "retry"]),
               (N_("呼叫與結束"), ["call", "succeed", "fail", "stop", "goto"]),
               (N_("溝通"), ["notify", "ask", "output"]),
               (N_("記錄"), ["set_var"]),
               (N_("規則專用"), ["stay", "hold"])]
AFTER_STEPS = {"tap", "long_press", "swipe", "back", "input_text", "launch_app"}   # may wait after: "after"
ON_FAIL = {"fail": N_("整個失敗"), "continue": N_("繼續下一步"), "stop": N_("停下這台")}
INPUT_STEPS = {"tap", "long_press", "swipe", "back", "input_text", "pick", "launch_app", "capture_list"}
CLEANUP_STEPS = {"tap", "long_press", "swipe", "back", "wait", "notify", "set_var", "output"}
PARAM_TYPES = {"point": N_("位置"), "number": N_("數字"), "text": N_("文字"), "list": N_("清單")}
ITEM_TYPES = {"point": N_("位置"), "number": N_("數字"), "text": N_("文字")}
# a point parameter (or a list parameter of points) may say "from_list": <list id> - its values are names of that list
# (lists.py; per device if the list is), e.g. the accounts of a device or the places of a map
MAX_DEPTH = 5          # nested calls
MAX_TIMEOUT = 43200          # 12 hours: a schedule may go through many items of a list


def _app():
    """The app a 啟動 App step without a package starts: the project's (project.json "app")."""
    import project
    return project.app_package()


def _dir(data_root, sid=None):
    d = os.path.join(data_root, "meta", "subscripts")
    return os.path.join(d, sid) if sid else d


def ids(data_root):
    d = _dir(data_root)
    if not os.path.isdir(d):
        return []
    return sorted(s for s in os.listdir(d) if os.path.exists(os.path.join(d, s, "current.json")))


def load(data_root, sid, version=None):
    d = _dir(data_root, sid)
    v = version or _read(os.path.join(d, "current.json"))["version"]
    obj = _read(os.path.join(d, f"v{int(v)}.json"))
    spec.check(obj, _("子腳本 {sid}", sid=sid))
    return spec.upgrade(obj)


def load_all(data_root):
    out = {}
    for s in ids(data_root):
        try:
            out[s] = load(data_root, s)
        except ValueError as e:                      # written by a newer spec: left out, not misread
            print(e, flush=True)
    return out


def signature(data_root):
    d = _dir(data_root)
    if not os.path.isdir(d):
        return ""
    return "|".join(f"{s}:{os.path.getmtime(os.path.join(d, s, 'current.json'))}" for s in ids(data_root))


def history(data_root, sid):
    d = _dir(data_root, sid)
    out = []
    for f in os.listdir(d):
        m = re.fullmatch(r"v(\d+)\.json", f)
        if m:
            s = _read(os.path.join(d, f))
            out.append({"version": s["version"], "created": s.get("created"), "note": s.get("note", "")})
    return sorted(out, key=lambda x: x["version"])


# ---------------------------------------------------------------- walking the step tree
def children(step):
    """The nested step lists of a block step."""
    t = step.get("type")
    if t == "if":
        return [step.get("then") or []] + [e.get("then") or [] for e in step.get("elif") or []] + [step.get("else") or []]
    if t in ("retry", "repeat_until", "for_each"):
        return [step.get("steps") or []]
    if t == "ask":
        return [o.get("then") or [] for o in step.get("options") or []]
    return []


def loop_params(st, params):
    """The parameters a for_each block adds for its steps: the item and its number."""
    lst = next((p for p in params or [] if p["name"] == st.get("list")), {})
    var = st.get("as") or "item"
    return [{"name": var, "label": st.get("as_label") or _("目前的{p1}", p1=lst.get('label') or lst.get('name') or _("項目")),
             "type": lst.get("item", "point"), **({"from_list": lst["from_list"]} if lst.get("from_list") else {})},
            {"name": f"{var}_no", "label": _("{p1}是第幾個", p1=st.get('as_label') or _("目前")), "type": "number"}]


def walk(steps):
    for st in steps or []:
        yield st
        for kids in children(st):
            yield from walk(kids)


def calls(sub):
    return {st.get("sub") for st in walk(sub.get("steps")) if st.get("type") == "call"}


def used_by(data_root, scripts=None, subs=None):
    """sub id -> ["主腳本「X」規則「Y」", "子腳本「Z」", ...]"""
    from . import load_all as load_scripts
    scripts = scripts if scripts is not None else load_scripts(data_root)
    subs = subs if subs is not None else load_all(data_root)
    from . import normalize
    out = {}
    for sc in scripts:
        sc = normalize(sc)
        for sit in sc["situations"]:
            uses = [(_("規則「{name}」", name=r.get('name', '')), r.get("do") or []) for r in sit.get("rules") or []]
            if sit.get("on_enter"):
                uses.append((_("情境「{name}」的進入動作", name=sit.get('name', '')), sit["on_enter"]))
            for label, steps in uses:
                for c in {st.get("sub") for st in walk(steps) if st.get("type") == "call"}:
                    out.setdefault(c, []).append(_("主腳本「{name}」{label}", name=sc['name'], label=label))
    for sid, sub in subs.items():
        for c in calls(sub):
            out.setdefault(c, []).append(_("子腳本「{name}」", name=sub['name']))
    return out


# ---------------------------------------------------------------- describing
def point_text(p, params=None):
    p = p or {}
    if set(p) == {"setting"}:
        from . import settings
        return _("使用者設定「{label}」", label=(settings.load().get(p['setting']) or {}).get('label', p['setting']))
    if "param" in p:
        label = next((x.get("label") or x["name"] for x in params or [] if x["name"] == p["param"]), p["param"])
        return _("參數「{label}」", label=label)
    if "button" in p:
        from . import buttons
        b = buttons.load().get(p["button"])
        return _("按鈕「{label}」", label=b['label']) + (_("(找圖)") if b.get("find") else "") if b else _("按鈕「{button}」(已刪除)", button=p['button'])
    if "x" in p and "y" in p:
        return f"({p['x']}, {p['y']})"
    return "?"


def cond_text(when, names, var_labels=None):
    from .conds import describe
    return _(" 或 ").join(_("、").join(describe(c, names, var_labels) for c in g) for g in when or [])


def _v(v, params=None):
    """A value field for the page: the number itself, or where it comes from."""
    if values.is_ref(v):
        labels = {p["name"]: p.get("label") or p["name"] for p in params or []}
        return values.describe(v, labels)
    return f"{v:g}" if isinstance(v, float) else str(v)


def describe_step(st, names, subs=None, params=None):
    text = _describe_step(st, names, subs, params)
    a = st.get("after") or {}
    if st.get("type") in AFTER_STEPS and a:
        if a.get("until"):
            text += _(",然後等到 {p1}(最多 {p2} 秒", p1=cond_text(a['until'], names), p2=_v(a.get('timeout', 10), params)) + \
                    (_(",逾時就繼續)") if a.get("on_timeout") == "continue" else _(",逾時就失敗)"))
        elif a.get("seconds") is not None:
            text += _(",然後等 {p1} 秒", p1=_v(a['seconds'], params))
    return text


def _describe_step(st, names, subs=None, params=None):
    t = st.get("type")
    label = _("「{x}」", x=st["label"]) if st.get("label") else ""
    if t == "goto":
        return _("切換到情境「{p1}」", p1=st.get('situation_name') or st.get('situation'))
    if t in ("stop", "stay", "hold"):
        return _("{step}:{text}", step=_(STEP_TYPES[t]), text=_v(st["text"], params)) if st.get("text") else _(STEP_TYPES[t])
    if t in ("tap", "long_press"):
        return _("{step}{label} {target}", step=_(STEP_TYPES[t]), label=label, target=point_text(st.get("target"), params))
    if t == "swipe":
        return _("滑動 {p1} → {p2}", p1=point_text(st.get('from'), params), p2=point_text(st.get('to'), params))
    if t == "input_text":
        return _("輸入文字「{p1}」", p1=_v(st.get('text', ''), params))
    if t == "launch_app":
        return _("啟動 App「{p1}」(已開著就切到前面)", p1=st.get('package') or _app())
    if t == "capture_list":
        from . import lists
        from .buttons import DATA_ROOT
        spec = lists.load(DATA_ROOT).get(st.get("list") or "") or {}
        return _("擷取清單「{p1}」(從頭滑到尾,新的項目存進按鈕庫)", p1=spec.get('title') or st.get('list'))
    if t == "pick":
        return _("在清單中找到並點擊{label} {p2}(停穩 {p3} 秒才點,最多滑 {p4} 次)", label=label, p2=point_text(st.get('target'), params), p3=_v(st.get('settle', 1), params), p4=_v(st.get('max_swipes', 25), params))
    if t == "wait":
        return _("等待 {p1} 秒", p1=_v(st.get('seconds', 1), params))
    if t == "wait_until":
        return _("等到 {p1}(最多 {p2} 秒", p1=cond_text(st.get('when'), names), p2=_v(st.get('timeout', 10), params)) + \
               (_(",逾時就繼續)") if st.get("on_timeout") == "continue" else _(",逾時就失敗)"))
    if t == "if":
        return _("如果 {p1}", p1=cond_text(st.get('when'), names))
    if t == "retry":
        return _("失敗就重試,最多 {p1} 次", p1=_v(st.get('times', 3), params))
    if t == "repeat_until":
        return _("重複,直到 {p1}(最多 {p2} 次)", p1=cond_text(st.get('when'), names), p2=_v(st.get('max_times', 10), params))
    if t == "for_each":
        lst = next((p for p in params or [] if p["name"] == st.get("list")), {})
        return _("對每一個「{p1}」", p1=lst.get('label') or st.get('list')) + (_("(某一個失敗就略過,繼續下一個)") if st.get("on_item_fail") == "continue" else "")
    if t == "call":
        name = ((subs or {}).get(st.get("sub")) or {}).get("name", st.get("sub"))
        args = _("、").join(f"{k}={_v(v, params) if values.is_ref(v) and 'param' not in v else point_text(v) if isinstance(v, dict) else v}"
                        for k, v in (st.get("args") or {}).items())
        return _("呼叫子腳本「{name}」", name=name) + (_("({n})", n=args) if args else "") + \
            {"continue": _("(失敗也繼續)"), "stop": _("(失敗就停下這台)")}.get(st.get("on_fail"), "")
    if t == "set_var":
        return _("變數「{var}」", var=st.get('var')) + (_("記下現在時間") if st.get("mode") == "now" else f"{_(VAR_MODES.get(st.get('mode'), ''))} {_v(st.get('value'), params)}")
    if t in ("notify", "succeed", "fail"):
        return _("{step}:{text}", step=_(STEP_TYPES[t]), text=_v(st["text"], params)) if st.get("text") else _(STEP_TYPES[t])
    if t == "ask":
        opts = [o.get("label", "") for o in st.get("options") or []]
        d = int(st.get("default") or 0)
        wait = _v(st.get("timeout", 300), params)
        return (_("問使用者「{p1}」({p2};等 {wait} 秒", p1=_v(st.get('text', ''), params), p2=' / '.join(opts), wait=wait)
                + (_(",沒人回答就選「{p1}」)", p1=opts[d - 1]) if 0 < d <= len(opts) else _(",沒人回答就失敗)")))
    if t == "output":
        from .outputs import describe as out_text
        return out_text(st)
    return _(STEP_TYPES.get(t, str(t)))


def outline(steps, names, subs=None, params=None, depth=0):
    """Readable indented lines of a step list (for the page and the logs)."""
    out = []
    for i, st in enumerate(steps or [], 1):
        out.append("  " * depth + f"{i}. {describe_step(st, names, subs, params)}")
        if st.get("type") == "ask":
            for o in st.get("options") or []:
                out.append("  " * depth + _("   選「{label}」:", label=o.get('label')))
                out += outline(o.get("then"), names, subs, params, depth + 1)
        elif st.get("type") == "if":
            out += outline(st.get("then"), names, subs, params, depth + 1)
            for e in st.get("elif") or []:
                out.append("  " * depth + _("   否則如果 {p1}:", p1=cond_text(e.get('when'), names)))
                out += outline(e.get("then"), names, subs, params, depth + 1)
            if st.get("else"):
                out.append("  " * depth + _("   否則:"))
                out += outline(st.get("else"), names, subs, params, depth + 1)
        else:
            inner = params + loop_params(st, params) if st.get("type") == "for_each" else params
            for kids in children(st):
                out += outline(kids, names, subs, inner, depth + 1)
    return out


# ---------------------------------------------------------------- validation
def _check_point(p, params, where):
    p = p or {}
    if set(p) == {"setting"}:
        from . import settings
        if p["setting"] not in settings.load():
            raise ValueError(_("{where}:沒有「{setting}」這個使用者設定", where=where, setting=p['setting']))
        return
    if "param" in p:
        if not any(x["name"] == p["param"] and x["type"] == "point" for x in params):
            raise ValueError(_("{where}:沒有「{param}」這個位置參數", where=where, param=p['param']))
        return
    if "button" in p:
        from . import buttons
        if p["button"] not in buttons.load():
            raise ValueError(_("{where}:按鈕庫裡沒有「{button}」", where=where, button=p['button']))
        return
    import project
    W, H = project.screen()
    if isinstance(p.get("x"), int) and isinstance(p.get("y"), int) and 0 <= p["x"] < W and 0 <= p["y"] < H:
        return
    raise ValueError(_("{where}:請選擇要點的位置", where=where))


def _check_when(when, states, where, var_names=None, params=None):
    if not when or not all(when):
        raise ValueError(_("{where}:請設定條件", where=where))
    for g in when:
        for c in g:
            check_cond(c, states, var_names, where, params=params if params is not None else [])


def _check_steps(steps, sub, lib, states, path, allowed=None, var_names=None):
    from . import settings
    params = sub.get("params") or []
    decls = settings.load()
    place = sub.get("_place")
    for i, st in enumerate(steps or [], 1):
        where = _("{place}{path}第 {i} 步", place=place["label"] if place else _("子腳本「{name}」", name=sub.get("name", "")), path=path, i=i)
        t = st.get("type")

        def num(key, default, lo, hi, msg):
            """A number field: a value in range, or where it comes from (checked when it runs)."""
            v = st.get(key, default)
            values.check(v, where, "number", params=params, settings=decls, var_names=var_names, states=states)
            if not values.is_ref(v) and not (lo <= float(v) <= hi):
                raise ValueError(f"{where}:{msg}")
        if t not in STEP_TYPES or (allowed and t not in allowed):
            raise ValueError(_("{where}:這裡不能用「{p2}」", where=where, p2=_(STEP_TYPES.get(t, t))))
        if t == "goto" or st.get("fail_goto"):
            if not place or place.get("guard"):
                raise ValueError(_("{where}:「切換情境」只能用在主腳本的規則裡(子腳本和守門規則沒有情境)", where=where))
            if (st.get("situation") if t == "goto" else st.get("fail_goto")) not in place.get("situations", []):
                raise ValueError(_("{where}:請選擇要切換到哪個情境", where=where))
        if t in ("stay", "hold"):
            if not place or place.get("kind") != "rule" or path or len(steps) != 1:
                raise ValueError(_("{where}:「{p2}」只能是一條規則唯一的步驟", where=where, p2=_(STEP_TYPES[t])))
            if t == "hold" and not place.get("guard"):
                raise ValueError(_("{where}:「暫停其他腳本」只能用在全域守門規則", where=where))
        if st.get("after"):
            a = st["after"]
            if t not in AFTER_STEPS or not isinstance(a, dict):
                raise ValueError(_("{where}:「{p2}」後面不能接等待", where=where, p2=_(STEP_TYPES.get(t, t))))
            if a.get("until"):
                _check_when(a["until"], states, _("{where} › 然後等到", where=where), var_names, params)
                v = a.get("timeout", 10)
                values.check(v, where, "number", params=params, settings=decls, var_names=var_names, states=states)
                if not values.is_ref(v) and not 0.001 <= float(v) <= 1800:
                    raise ValueError(_("{where}:然後等到的最多秒數要在 0~1800", where=where))
                if a.get("on_timeout", "fail") not in ("fail", "continue"):
                    raise ValueError(_("{where}:逾時要失敗還是繼續?", where=where))
            elif a.get("seconds") is not None:
                values.check(a["seconds"], where, "number", params=params, settings=decls, var_names=var_names, states=states)
                if not values.is_ref(a["seconds"]) and not 0 <= float(a["seconds"]) <= 3600:
                    raise ValueError(_("{where}:然後等待的秒數要在 0~3600", where=where))
        if t == "call" and st.get("on_fail", "fail") not in ON_FAIL:
            raise ValueError(_("{where}:子腳本失敗時要怎麼做?", where=where))
        if t in ("tap", "long_press", "pick"):
            _check_point(st.get("target"), params, where)
        if t == "launch_app" and values.is_ref(st.get("package")):
            values.check(st["package"], where, "text", params=params, settings=decls, var_names=var_names, states=states)
        elif t == "launch_app" and not re.fullmatch(r"[A-Za-z0-9_.]+", st.get("package") or _app()):
            raise ValueError(_("{where}:App 名稱不正確(例如 com.example.app);沒填就用專案設定的 App", where=where))
        if t == "capture_list":
            from . import lists
            from .buttons import DATA_ROOT
            if st.get("list") not in lists.load(DATA_ROOT):
                raise ValueError(_("{where}:請選擇要擷取的清單", where=where))
            num("timeout", 300, 30, 1800, _("最多執行秒數要在 30~1800"))
        if t == "pick":
            num("max_swipes", 25, 1, 60, _("最多滑動次數要在 1~60"))
            num("settle", 1, 0, 10, _("停穩秒數要在 0~10"))
        if t in ("long_press", "swipe") and "ms" in st:
            num("ms", 0, 50, 10000, _("按住 / 滑動的毫秒數要在 50~10000"))
        if t == "swipe":
            _check_point(st.get("from"), params, where)
            _check_point(st.get("to"), params, where)
        elif t == "wait":
            num("seconds", 1, 0.001, 7200, _("等待秒數要在 0~7200(2 小時)"))
        elif t in ("wait_until", "if", "repeat_until"):
            _check_when(st.get("when"), states, where, var_names, params)
            if t == "if":
                if not isinstance(st.get("elif") or [], list) or len(st.get("elif") or []) > 20:
                    raise ValueError(_("{where}:「否則如果」最多 20 個", where=where))
                for k, e in enumerate(st.get("elif") or [], 1):
                    _check_when(e.get("when"), states, _("{where} › 第 {k} 個否則如果", where=where, k=k), var_names, params)
        elif t == "set_var":
            if var_names is not None and st.get("var") not in var_names:
                raise ValueError(_("{where}:請選擇變數", where=where))
            if st.get("mode") not in VAR_MODES or (st["mode"] != "now" and st.get("value") is None):
                raise ValueError(_("{where}:請設定變數要怎麼改", where=where))
            if st["mode"] != "now":
                values.check(st["value"], where, "number", params=params, settings=decls, var_names=var_names, states=states)
        if t == "input_text":
            if st.get("text") in (None, ""):
                raise ValueError(_("{where}:請填要輸入的文字", where=where))
            values.check(st["text"], where, "text", params=params, settings=decls, var_names=var_names, states=states)
        if t == "output":
            from . import outputs
            outputs.check_action(st, where, params=params, var_names=var_names)
        if t in ("notify", "succeed", "fail") and values.is_ref(st.get("text")):
            values.check(st["text"], where, "text", params=params, settings=decls, var_names=var_names, states=states)
        if t == "ask":
            if not st.get("text"):
                raise ValueError(_("{where}:請填要問的問題", where=where))
            if values.is_ref(st["text"]):
                values.check(st["text"], where, "text", params=params, settings=decls, var_names=var_names, states=states)
            opts = st.get("options") or []
            labels = [str(o.get("label") or "").strip() for o in opts]
            if not 2 <= len(opts) <= 6:
                raise ValueError(_("{where}:選項要有 2~6 個", where=where))
            if any(not x or len(x) > 20 for x in labels) or len(set(labels)) != len(labels):
                raise ValueError(_("{where}:每個選項都要有名稱(20 字以內)而且不能重複", where=where))
            num("timeout", 300, 10, 86400, _("等待回答的秒數要在 10~86400(一天)"))
            if not isinstance(st.get("default", 0), int) or not 0 <= st.get("default", 0) <= len(opts):
                raise ValueError(_("{where}:沒人回答時要選的選項不正確", where=where))
            if st.get("var") and var_names is not None and st["var"] not in var_names:
                raise ValueError(_("{where}:變數「{var}」不存在", where=where, var=st['var']))
        if t == "wait_until":
            num("timeout", 10, 0.001, 1800, _("最多等待秒數要在 0~1800"))
        if t == "retry":
            num("times", 3, 1, 20, _("重試次數要在 1~20"))
            num("delay", 0, 0, 3600, _("重試間隔要在 0~3600 秒"))
        if t == "repeat_until":
            num("max_times", 10, 1, 1000, _("重複次數上限要在 1~1000"))
            num("max_seconds", 600, 1, 43200, _("重複的時間上限要在 1~43200 秒"))
        if t == "for_each":
            lst = next((p for p in params if p["name"] == st.get("list")), None)
            if not lst or lst["type"] != "list":
                raise ValueError(_("{where}:請選擇要逐一處理的清單參數(先在參數加一個「清單」)", where=where))
            if not re.fullmatch(r"[a-z][a-z0-9_]*", st.get("as") or "item"):
                raise ValueError(_("{where}:目前項目的代號只能用小寫英文、數字、底線", where=where))
            if (st.get("as") or "item") in {p["name"] for p in params}:
                raise ValueError(_("{where}:目前項目的代號「{p2}」和參數重複", where=where, p2=st.get('as')))
        if t in ("retry", "repeat_until", "for_each") and not st.get("steps"):
            raise ValueError(_("{where}:裡面至少要有一個步驟", where=where))
        if t == "if" and not (st.get("then") or st.get("else") or any(e.get("then") for e in st.get("elif") or [])):
            raise ValueError(_("{where}:「成立時」「否則如果」或「否則」至少要有一個步驟", where=where))
        if t == "call":
            target = lib.get(st.get("sub"))
            if not target:
                raise ValueError(_("{where}:找不到子腳本「{sub}」", where=where, sub=st.get('sub')))
            for p in target.get("params") or []:
                v = (st.get("args") or {}).get(p["name"], p.get("default"))
                if v is None:
                    raise ValueError(_("{where}:呼叫「{name}」要填參數「{p3}」", where=where, name=target['name'], p3=p.get('label') or p['name']))
                if p["type"] == "point":
                    _check_point(v, params, where)
                elif values.is_ref(v):
                    values.check(v, _("{where}:參數「{p2}」", where=where, p2=p.get('label') or p['name']), "number" if p["type"] == "number" else "text",
                                 params=params, settings=decls, var_names=var_names, states=states)
        inner = {**sub, "params": params + loop_params(st, params)} if t == "for_each" else sub
        kids_all = children(st)
        for k, kids in enumerate(kids_all):
            if t == "if":
                sub_path = _("成立時 › ") if k == 0 else _("否則 › ") if k == len(kids_all) - 1 else _("第 {k} 個否則如果 › ", k=k)
            elif t == "ask":
                sub_path = _("選「{label}」 › ", label=(st.get('options') or [{}])[k].get('label'))
            else:
                sub_path = f"{_(STEP_TYPES[t])} › "
            _check_steps(kids, inner, lib, states, _("{path}第 {i} 步 › {sub_path}", path=path, i=i, sub_path=sub_path), allowed, var_names)


def check_calls(lib):
    """No sub-script may (directly or indirectly) call itself, and calls nest at most MAX_DEPTH deep."""
    def depth(sid, seen):
        if sid in seen:
            chain = " → ".join(lib[s]["name"] for s in seen + [sid] if s in lib)
            raise ValueError(_("子腳本不能互相無限呼叫:{chain}", chain=chain))
        sub = lib.get(sid)
        if not sub:
            return 0
        return 1 + max([depth(c, seen + [sid]) for c in calls(sub)] or [0])
    for sid in lib:
        if depth(sid, []) > MAX_DEPTH:
            raise ValueError(_("子腳本「{name}」呼叫的層數超過 {MAX_DEPTH} 層", name=lib[sid]['name'], MAX_DEPTH=MAX_DEPTH))


def validate(sub, lib, schema=None, var_names=None):
    from . import lists as lists_mod
    from .buttons import DATA_ROOT
    have_lists = lists_mod.load(DATA_ROOT)
    for p in sub.get("params") or []:
        if p.get("item") not in (None, *ITEM_TYPES):
            raise ValueError(_("參數「{p1}」的每一項要是位置、數字或文字", p1=p.get('label') or p.get('name')))
        if p.get("from_list") and (p["from_list"] not in have_lists or p["type"] not in ("point", "list")
                                   or p["type"] == "list" and p.get("item", "point") != "point"):
            raise ValueError(_("參數「{p1}」的清單「{from_list}」不存在,或這個參數不是位置", p1=p.get('label') or p.get('name'), from_list=p['from_list']))
    if not re.fullmatch(r"[a-z][a-z0-9_]*", sub.get("id", "")):
        raise ValueError(_("子腳本代號只能用小寫英文、數字、底線,且以英文開頭"))
    if not sub.get("name"):
        raise ValueError(_("請替子腳本取個名稱"))
    names = [p.get("name") for p in sub.get("params") or []]
    for p in sub.get("params") or []:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", p.get("name") or ""):
            raise ValueError(_("參數代號「{name}」只能用小寫英文、數字、底線", name=p.get('name')))
        if p.get("type") not in PARAM_TYPES:
            raise ValueError(_("參數「{name}」的種類不正確", name=p.get('name')))
        if p["type"] == "list" and p.get("item", "point") not in ITEM_TYPES:
            raise ValueError(_("清單參數「{name}」的項目種類不正確", name=p.get('name')))
    if len(set(names)) != len(names):
        raise ValueError(_("參數代號重複"))
    if not sub.get("steps"):
        raise ValueError(_("至少要有一個步驟"))
    if not (1 <= float(sub.get("timeout", 300)) <= MAX_TIMEOUT):
        raise ValueError(_("整個子腳本最多執行秒數要在 1~{MAX_TIMEOUT}", MAX_TIMEOUT=MAX_TIMEOUT))
    states = {s["id"]: s for s in (schema or {}).get("states", [])}
    full = {**lib, sub["id"]: sub}
    _check_steps(sub.get("steps"), sub, full, states, "", None, var_names)
    _check_steps(sub.get("cleanup"), sub, full, states, _("收尾 › "), CLEANUP_STEPS, var_names)
    check_calls(full)


def save(data_root, sub, note=""):
    import schema as schema_mod
    from . import variables
    lib = load_all(data_root)
    validate(sub, {k: v for k, v in lib.items() if k != sub["id"]}, schema_mod.load(data_root),
             {v["name"] for v in variables(data_root)})
    import drivers
    drivers.check_script(sub, _("子腳本「{name}」", name=sub.get('name', '')), data_root)
    d = _dir(data_root, sub["id"])
    os.makedirs(d, exist_ok=True)
    vs = [h["version"] for h in history(data_root, sub["id"])] if os.path.exists(os.path.join(d, "current.json")) else []
    v = (max(vs) if vs else 0) + 1
    out = spec.stamp({**sub, "version": v, "created": time.time(), "note": note})
    _write(os.path.join(d, f"v{v}.json"), out)
    _write(os.path.join(d, "current.json"), {"version": v})
    return out


# ---------------------------------------------------------------- library layout (groups)
# How the sub-script library is arranged on the page: user-made groups (folders) and the order inside them. Kept
# apart from the sub-scripts themselves, so tidying the library never makes a new version of anything:
#   meta/subscripts/layout.json   {"groups": [{"id", "name"}], "of": {sub id: group id}, "order": [sub id, ...]}
# Sub-scripts in no group are shown under "not grouped"; ids that no longer exist are ignored.
MAX_GROUPS = 50


def layout(data_root):
    p = os.path.join(_dir(data_root), "layout.json")
    lay = _read(p) if os.path.exists(p) else {}
    have = set(ids(data_root))
    groups = [g for g in lay.get("groups", []) if isinstance(g, dict) and g.get("id") and g.get("name")]
    gids = {g["id"] for g in groups}
    of = {k: v for k, v in (lay.get("of") or {}).items() if k in have and v in gids}
    listed = [s for s in lay.get("order", []) if s in have]
    return {"groups": groups, "of": of, "order": listed + sorted(have - set(listed))}


def set_layout(data_root, lay):
    groups, seen_ids, seen_names = [], set(), set()
    for g in lay.get("groups") or []:
        gid, name = str(g.get("id") or "").strip(), str(g.get("name") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", gid):
            raise ValueError(_("群組代號不正確"))
        if not name or len(name) > 30:
            raise ValueError(_("群組名稱要 1~30 個字"))
        if gid in seen_ids or name in seen_names:
            raise ValueError(_("群組「{name}」重複了", name=name))
        seen_ids.add(gid); seen_names.add(name)
        groups.append({"id": gid, "name": name})
    if len(groups) > MAX_GROUPS:
        raise ValueError(_("群組最多 {MAX_GROUPS} 個", MAX_GROUPS=MAX_GROUPS))
    have = set(ids(data_root))
    of = {str(k): str(v) for k, v in (lay.get("of") or {}).items() if k in have and v in seen_ids}
    order = [s for s in dict.fromkeys(lay.get("order") or []) if s in have]
    os.makedirs(_dir(data_root), exist_ok=True)
    _write(os.path.join(_dir(data_root), "layout.json"), spec.stamp({"groups": groups, "of": of, "order": order}))
    return layout(data_root)


def delete(data_root, sid):
    if sid not in ids(data_root):
        raise ValueError(_("找不到這個子腳本"))
    users = used_by(data_root).get(sid)
    if users:
        raise ValueError(_("還有地方在用這個子腳本:") + _("、").join(users))
    trash = os.path.join(_dir(data_root), ".deleted")
    os.makedirs(trash, exist_ok=True)
    shutil.move(_dir(data_root, sid), os.path.join(trash, f"{sid}_{int(time.time())}"))

