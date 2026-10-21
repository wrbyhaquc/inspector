"""Values in the script spec (automation/spec.py): a number or text field may hold the value itself, or say where it
comes from when the script runs:

  3, 1.5, "hello"     the value itself
  {"param": name}     a parameter of the sub-script (or a for_each item)            sub-scripts only
  {"setting": id}     a user setting, this device's value (automation/settings.py)
  {"var": name}       a variable, as this device sees it now (automation/__init__.py)
  {"state": id}       a state's value on this device now (a number read off the screen, e.g. "庫存數量");
                      nothing while the model is not sure enough (MIN_CONF), so a condition using it stays unsure
  {"sum": [v, ...]}   the values added up (each a number or any of the above), e.g. 訂單 + 安全庫存;
                      nothing if any of them has none

Text fields may also name variables and parameters inside: "第 {round} 輪" -> "第 3 輪" (render()).

The runtime hands a lookup in: an env dict {"params": {...}, "vars": {...}, "setting": fn(id) -> value,
"states": {id: {"value", "conf"}}} (the conditions' ctx has the same keys), so the same rules hold for steps, rule
actions and conditions."""
import re
from i18n import N_, _

REFS = {"param": N_("參數"), "setting": N_("使用者設定"), "var": N_("變數"), "state": N_("狀態"), "sum": N_("相加")}
MIN_CONF = 0.7                    # = automation/conds.py DEFAULT_MIN_CONF


def is_ref(v):
    return isinstance(v, dict) and len(v) == 1 and next(iter(v)) in REFS


def resolve(v, env, default=None):
    """The value a field has now (env: {"params", "vars", "setting"})."""
    if v is None:
        return default
    if not is_ref(v):
        return v
    env = env or {}
    k, name = next(iter(v.items()))
    if k == "sum":
        total = 0.0
        for x in name if isinstance(name, list) else []:
            r = resolve(x, env)
            try:
                total += float(r)
            except (TypeError, ValueError):
                return default
        return int(total) if total.is_integer() else total
    if k == "param":
        out = (env.get("params") or {}).get(name)
    elif k == "var":
        out = (env.get("vars") or {}).get(name)
    elif k == "state":
        s = (env.get("states") or {}).get(name)
        out = s.get("value") if isinstance(s, dict) and s.get("conf", 1) >= MIN_CONF else None
    else:
        fn = env.get("setting")
        out = fn(name) if fn else None
    return default if out is None else out


def number(v, env, default=0.0):
    r = resolve(v, env, default)
    try:
        return float(r)
    except (TypeError, ValueError):
        return default


def integer(v, env, default=0):
    return int(round(number(v, env, default)))


_PLACE = re.compile(r"\{([\w一-鿿]+)\}")


def render(text, env):
    """Text with {name} replaced by the value of that parameter or variable - else of that state on this device
    (a number read off the screen), else of that user setting. Unknown names stay as they are."""
    if not text:
        return text
    t = resolve(text, env, "") if is_ref(text) else text
    env = env or {}
    pool = {**(env.get("params") or {}), **(env.get("vars") or {})}

    def sub(m):
        name = m.group(1)
        v = pool.get(name)
        if v is None:
            v = resolve({"state": name}, env)
        if v is None and env.get("setting"):
            v = resolve({"setting": name}, env)
        if v is None or isinstance(v, (dict, list)):
            return m.group(0)
        return f"{v:g}" if isinstance(v, float) else str(v)
    return _PLACE.sub(sub, str(t))


def describe(v, labels=None):
    """A field's value in words, e.g. 參數「秒數」. labels: {name: label}, or per kind {"state": {...}, "var": {...}}."""
    if not is_ref(v):
        return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
    k, name = next(iter(v.items()))
    if k == "sum":
        return " + ".join(describe(x, labels) for x in (name if isinstance(name, list) else []))
    lab = labels or {}
    if isinstance(lab.get(k), dict):
        lab = lab[k]
    x = lab.get(name, name)
    return _("設定「{x}」", x=x) if k == "setting" else _("變數「{x}」", x=x) if k == "var" else _("「{x}」", x=x)


def check(v, where, kind="number", params=None, settings=None, var_names=None, allow_params=True, states=None):
    """Raise ValueError when a field's value cannot work. kind: number | text. states: {id: state def} (None: not checked)."""
    if v is None:
        return
    if isinstance(v, dict):
        if not is_ref(v):
            raise ValueError(_("{where}:值的寫法不正確", where=where))
        k, name = next(iter(v.items()))
        if k == "sum":
            if kind != "number" or not isinstance(name, list) or not name:
                raise ValueError(_("{where}:相加要有要加的數字", where=where))
            for x in name:
                check(x, where, "number", params, settings, var_names, allow_params, states)
            return
        if k == "param":
            ps = {p["name"]: p for p in params or []}
            if not allow_params:
                raise ValueError(_("{where}:主腳本沒有參數,請改用固定值、使用者設定或變數", where=where))
            if name not in ps:
                raise ValueError(_("{where}:沒有「{name}」這個參數", where=where, name=name))
            if kind == "number" and ps[name].get("type") not in ("number", None):
                raise ValueError(_("{where}:參數「{name}」不是數字", where=where, name=name))
        elif k == "setting":
            if settings is not None:
                if name not in settings:
                    raise ValueError(_("{where}:沒有「{name}」這個使用者設定", where=where, name=name))
                if kind == "number" and settings[name].get("type") not in ("number", "time"):
                    raise ValueError(_("{where}:使用者設定「{name}」不是數字", where=where, name=name))
        elif k == "state":
            if states:
                if name not in states:
                    raise ValueError(_("{where}:沒有「{name}」這個狀態", where=where, name=name))
                if kind == "number" and states[name].get("type") not in ("number", "ratio"):
                    raise ValueError(_("{where}:狀態「{name}」不是數字(要用數值或比例的狀態)", where=where, name=states[name].get('name', name)))
        elif var_names is not None and name not in var_names:
            raise ValueError(_("{where}:沒有「{name}」這個變數", where=where, name=name))
        return
    if kind == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
        try:
            float(v)
        except (TypeError, ValueError):
            raise ValueError(_("{where}:要填數字", where=where)) from None
