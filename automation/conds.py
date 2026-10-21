"""Conditions of rules and sub-script steps. Every condition has a "kind" (default "state"):

  state    {"state", "op", "value", "for", "min_conf"}             the model's state now (op is/is_not, or < <= > >=)
  became   {"state", "value", "within"}                            changed to value within the last N seconds
  count    {"state", "value", "within", "op", "times"}             became value at least/most K times in N seconds
  change   {"state", "dir": "drop" | "rise", "amount", "within"}   a ratio (a water level...) fell / rose by amount in N seconds
  time     {"from": "HH:MM", "to": "HH:MM", "days": [0..6]}        clock time window (may pass midnight; 0 = Monday)
  always   {}                                                      always true (with a cooldown = "every N seconds")
  var      {"var", "op", "value"}                                  a variable (counter...) compared with a number
  elapsed  {"var", "op", "value"}                                  seconds since the time stored in a variable
  device   {"device", "state", "op", "value"}                      another emulator's state (as last seen)
  visible  {"target": {"button"} | {"param"}, "op": "is" | "is_not"}  a "find" button can be seen on the screen now
  compare  {"left": value, "op", "right": value}                  two numbers, each a number, a state read off the
                                                                  screen, a setting, a variable or a sum of them
                                                                  (automation/values.py), e.g. 庫存 >= 訂單 + 安全庫存

ctx (built by the runtime for one device):
  {"history": {state id: [(t, value), ...]},   class states: one entry per change; ratios: every tick
   "vars": {name: value}, "devices": {device name: state dict}}"""
import datetime
import json

from . import values
from i18n import N_, _
from project import word as _word

DEFAULT_MIN_CONF = 0.7
MATCH, NO, UNSURE = "match", "no", "unsure"
KINDS = {"state": N_("狀態"), "became": N_("剛變成"), "count": N_("一段時間內幾次"), "change": N_("變化量"), "time": N_("時段"),
         "always": N_("總是"), "var": N_("變數"), "elapsed": N_("距離上次"), "device": N_("其他{device}"), "visible": N_("看得到按鈕"),
         "compare": N_("比較兩個數字")}
OPS = {"is": N_("是"), "is_not": N_("不是"), "lt": "<", "lte": "≤", "gt": ">", "gte": "≥"}
DAYS = [N_("一"), N_("二"), N_("三"), N_("四"), N_("五"), N_("六"), N_("日")]


def kind_label(kind):
    """A kind of condition in the current language."""
    return _(KINDS[kind], device=_word("device")) if kind in KINDS else kind


def kind_labels():
    return {k: kind_label(k) for k in KINDS}


def op_labels():
    return {k: _(v) for k, v in OPS.items()}
HISTORY_SECONDS = 3600          # how far back became / count / change can look


def _cmp(v, op, want):
    if op == "is":
        return v == want
    if op == "is_not":
        return v != want
    try:
        v, want = float(v), float(want)
    except (TypeError, ValueError):
        return None
    return {"lt": v < want, "lte": v <= want, "gt": v > want, "gte": v >= want}[op]


def _hhmm(s):
    h, m = (int(x) for x in str(s).split(":"))
    return h * 60 + m


def in_window(c, now):
    d = datetime.datetime.fromtimestamp(now)
    mins = d.hour * 60 + d.minute
    a, b = _hhmm(c.get("from", "00:00")), _hhmm(c.get("to", "23:59"))
    days = c.get("days")
    if a <= b:
        ok, day = a <= mins <= b, d.weekday()
    else:                                         # passes midnight: 22:00-06:00; the early part belongs to yesterday
        ok = mins >= a or mins <= b
        day = d.weekday() if mins >= a else (d.weekday() - 1) % 7
    return ok and (not days or day in days)


def evaluate(c, state, tracker, key, now, ctx=None):
    """-> MATCH / NO / UNSURE for one condition on one device."""
    ctx = ctx or {}
    kind = c.get("kind", "state")
    if kind == "always":
        return MATCH
    if kind == "visible":
        seen = ctx.get("visible")
        t = c.get("target") or {}
        if not seen or "button" not in t:
            return UNSURE
        hit = bool(seen(t))
        return _held(c, tracker, key, hit == (c.get("op", "is") != "is_not"), now)
    if kind == "time":
        return MATCH if in_window(c, now) else NO
    if kind == "compare":
        env = {**ctx, "states": state or {}}
        a, b = values.resolve(c.get("left"), env), values.resolve(c.get("right"), env)
        ok = None if a is None or b is None else _cmp(a, c.get("op", "gte"), b)
        return UNSURE if ok is None else _held(c, tracker, key, ok, now)
    if kind in ("var", "elapsed"):
        v = (ctx.get("vars") or {}).get(c.get("var"))
        if kind == "elapsed":
            v = float("inf") if not v else now - float(v)       # never happened = a very long time ago
        elif v is None:
            v = 0
        ok = _cmp(v, c.get("op", "gte"), values.resolve(c.get("value"), ctx))
        return UNSURE if ok is None else _held(c, tracker, key, ok, now)
    hist = (ctx.get("history") or {}).get(c.get("state")) or []
    within = float(c.get("within", 10))
    if kind == "count":                           # only history: an unsure frame right now does not matter
        times = sum(1 for i, (t, x) in enumerate(hist) if i > 0 and x == c.get("value") and now - t <= within)
        return MATCH if _cmp(times, c.get("op", "gte"), values.resolve(c.get("times", 1), ctx, 1)) else NO
    if kind == "change":
        vals = [x for t, x in hist if now - t <= within and isinstance(x, (int, float))]
        if len(vals) < 2:
            return UNSURE
        diff = (max(vals) - vals[-1]) if c.get("dir", "drop") == "drop" else (vals[-1] - min(vals))
        return MATCH if diff >= values.number(c.get("amount", 0.1), ctx, 0.1) else NO
    st = state if kind != "device" else (ctx.get("devices") or {}).get(c.get("device"))
    if st is None:
        return UNSURE
    s = st.get(c.get("state"))
    if s is None or s.get("value") is None:
        return UNSURE
    if "conf" in s and s["conf"] < c.get("min_conf", DEFAULT_MIN_CONF):
        tracker.held(key, False, now)
        return UNSURE
    v = s["value"]
    if kind in ("state", "device"):
        ok = _cmp(v, c.get("op", "is"), values.resolve(c.get("value"), {**ctx, "states": state or {}}))
        return UNSURE if ok is None else _held(c, tracker, key, ok, now)
    if kind == "became":
        if v != c.get("value") or len(hist) < 2:
            return NO                             # not that value now, or never saw it change
        t_changed = hist[-1][0] if hist[-1][1] == v else None
        return MATCH if t_changed is not None and now - t_changed <= within else NO
    return UNSURE


def _held(c, tracker, key, ok, now):
    held = tracker.held(key, ok, now)
    if not ok:
        return NO
    return MATCH if held >= c.get("for", 0) else NO


# ---------------------------------------------------------------- describing
def _val(names, sid, value):
    n = names.get(sid, {"name": sid, "type": "class", "classes": {}})
    if values.is_ref(value):
        return n["name"], values.describe(value, {k: d.get("name", k) for k, d in names.items()} if "state" in value else None)
    if n["type"] == "number":
        return n["name"], f"{value}{n.get('unit') or ''}"
    if n["type"] == "ratio":
        return n["name"], f"{round(float(value) * 100)}%"
    return n["name"], n["classes"].get(json.dumps(value), str(value))


def _sec(s):
    s = float(s)
    if s >= 3600 and s % 3600 == 0:
        return _("{n} 小時", n=f"{s / 3600:g}")
    if s >= 60 and s % 60 == 0:
        return _("{n} 分鐘", n=f"{s / 60:g}")
    return _("{n} 秒", n=f"{s:g}")


def describe(c, names, var_labels=None):
    if c.get("kind") == "visible":
        from .subs import point_text
        target = point_text(c.get("target"))
        return _("畫面上看不到{target}", target=target) if c.get("op") == "is_not" else _("畫面上看得到{target}", target=target)
    kind = c.get("kind", "state")
    held = _("(持續 {time})", time=_sec(c["for"])) if c.get("for") else ""
    op = {"is": "=", "is_not": "≠"}.get(c.get("op"), OPS.get(c.get("op"), c.get("op")))
    if kind == "always":
        return _("總是")
    if kind == "compare":
        lab = value_labels(names, var_labels)
        return f"{values.describe(c.get('left'), lab)} {op} {values.describe(c.get('right'), lab)}{held}"
    if kind == "time":
        days = c.get("days")
        span = f"{c.get('from', '00:00')}~{c.get('to', '23:59')}"
        if not days or len(days) == 7:
            return span
        return _("每週{days} {time}", days=_("、").join(_(DAYS[i]) for i in sorted(days)), time=span)
    if kind in ("var", "elapsed"):
        label = (var_labels or {}).get(c.get("var"), c.get("var"))
        if kind == "elapsed":
            v = c.get("value", 0)
            return _("距離上次「{var}」{op} {value}", var=label, op=op,
                     value=values.describe(v, var_labels) if values.is_ref(v) else _sec(v)) + held
        return _("變數「{var}」{op} {value}", var=label, op=op, value=values.describe(c.get("value"), var_labels)) + held
    name, v = _val(names, c.get("state"), c.get("value", 0))
    if kind == "state":
        return f"{name} {op} {v}{held}"
    if kind == "device":
        return _("{device} 的{state} {op} {value}", device=c.get("device"), state=name, op=op, value=v) + held
    if kind == "became":
        return _("{state} 剛變成 {value}({time}內)", state=name, value=v, time=_sec(c.get("within", 10)))
    if kind == "count":
        return _("{time}內 {state} 變成 {value} {op} {times} 次", time=_sec(c.get("within", 600)), state=name, value=v,
                 op=OPS.get(c.get("op", "gte")), times=values.describe(c.get("times", 1)))
    if kind == "change":
        amt = c.get("amount", 0.1)
        n = names.get(c.get("state"), {})
        amt = values.describe(amt) if values.is_ref(amt) else f"{amt}{n.get('unit') or ''}" if n.get("type") == "number"             else f"{round(float(amt) * 100)}%"
        time = _sec(c.get("within", 10))
        if c.get("dir", "drop") == "drop":
            return _("{state} 在 {time}內下降 {amount} 以上", state=name, time=time, amount=amt)
        return _("{state} 在 {time}內上升 {amount} 以上", state=name, time=time, amount=amt)
    return kind


def value_labels(names, var_labels=None):
    """Labels for describing values of any kind (automation/values.py describe)."""
    try:
        from . import settings
        sets = {k: s.get("label", k) for k, s in settings.load().items()}
    except Exception:                                  # noqa: BLE001 - no project open (a test)
        sets = {}
    return {"state": {k: n.get("name", k) for k, n in (names or {}).items()}, "var": var_labels or {}, "setting": sets}


# ---------------------------------------------------------------- validation
def check(c, states, variables, where, params=None):
    """Raise ValueError for an unusable condition. states = {id: state def} (may be empty: not checked).
    params: the sub-script's parameters (None in a main script: there are none)."""
    def num(v):
        values.check(v, where, "number", params=params, var_names=variables, allow_params=params is not None, states=states)
    if c.get("kind") == "visible":
        t = c.get("target") or {}
        if not ("button" in t or "param" in t):
            raise ValueError(_("{where}:請選擇要看的按鈕(按鈕庫裡「找圖」的按鈕)", where=where))
        return
    kind = c.get("kind", "state")
    if kind not in KINDS:
        raise ValueError(_("{where}:條件種類不正確", where=where))
    if kind == "time":
        try:
            _hhmm(c.get("from", "")), _hhmm(c.get("to", ""))
        except (ValueError, TypeError):
            raise ValueError(_("{where}:時段請填 時:分,例如 22:00", where=where))
        if any(d not in range(7) for d in c.get("days") or []):
            raise ValueError(_("{where}:星期不正確", where=where))
        return
    if kind == "always":
        return
    if kind == "compare":
        if c.get("op") not in OPS:
            raise ValueError(_("{where}:比較方式不正確", where=where))
        for side, msg in (("left", N_("{where}:比較的左邊要填")), ("right", N_("{where}:比較的右邊要填"))):
            if c.get(side) is None:
                raise ValueError(_(msg, where=where))
            num(c.get(side))
        return
    if kind in ("var", "elapsed"):
        if variables is not None and c.get("var") not in variables:
            raise ValueError(_("{where}:變數「{var}」不存在", where=where, var=c.get("var")))
        if c.get("op") not in OPS or c.get("value") is None:
            raise ValueError(_("{where}:請設定比較方式和數字", where=where))
        num(c.get("value"))
        return
    st = states.get(c.get("state")) if states else None
    if states and not st:
        raise ValueError(_("{where}:狀態「{state}」不存在(可能在狀態定義裡刪掉了)", where=where, state=c.get("state")))
    if kind in ("state", "device"):
        if c.get("op") not in OPS:
            raise ValueError(_("{where}:比較方式不正確", where=where))
        if kind == "device" and not c.get("device"):
            raise ValueError(_("{where}:請選擇是哪一台{device}", where=where, device=_word("device")))
    if kind in ("state", "device", "became", "count") and st:
        if st["type"] == "class" and c.get("op", "is") in ("is", "is_not") and \
                c.get("value") not in [x["value"] for x in st.get("classes", [])]:
            raise ValueError(_("{where}:「{state}」沒有這個選項", where=where, state=st["name"]))
        if st["type"] in ("ratio", "number") and kind in ("state", "device"):
            if c.get("value") is None:
                raise ValueError(_("{where}:「{state}」要填數字", where=where, state=st["name"]))
            num(c.get("value"))
    if kind == "change" and st and st["type"] not in ("ratio", "number"):
        raise ValueError(_("{where}:變化量只能用在比例或數值(例如水位)", where=where))
    if kind == "change":
        num(c.get("amount", 0.1))
    if kind == "count":
        num(c.get("times", 1))
    if kind in ("became", "count", "change") and not 1 <= float(c.get("within", 10)) <= HISTORY_SECONDS:
        raise ValueError(_("{where}:時間範圍要在 1~{max} 秒", where=where, max=HISTORY_SECONDS))
