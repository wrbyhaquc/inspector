"""The script spec (腳本規範): the format of every design file the automation reads - scripts, sub-scripts, variables,
buttons, schedules, user settings, tests, the operation panel.

Every such file carries "format": the spec version it was written in (a file without one: version 0). Inspector
upgrades older files when it reads them (upgrade()); an older Inspector refuses a file written by a newer one instead
of misreading it (check()).

The current version is FORMAT; its JSON Schema (automation/spec_schema.py, files in docs/spec/v<FORMAT>/) is the
contract: no field of a released version is renamed, removed or given a new meaning. Anything new (a step, action or
condition kind, an optional field) raises FORMAT and comes with an upgrade() step and a new schema.

Values: a number or text field of a step / action / condition may hold
  a value itself                  3, "hello"
  {"param": name}                 a parameter of the sub-script (or a for_each item)
  {"setting": id}                 a user setting (automation/settings.py)
  {"var": name}                   a variable (automation/__init__.py)
  {"state": id}                   a number state's value on this device now; unsure = no value, so a condition
                                  using it stays unsure
  {"sum": [v, ...]}               several values added together
(automation/values.py resolves them; the JSON Schema describes every field.)

What each version added (older files are upgraded by upgrade()):
  1  scripts, sub-scripts, variables, outputs, tests
  2  the step "ask" {"text", "options": [{"label", "then": [steps]}], "timeout", "default", "var"}; operation panel
     controls "chat" (the name in a chat bot) and "chat_off" (only on the page); the panel gets a schema
  3  wherever sources are chosen, "#<tag>" means every source with that tag (drivers/sources.py): a main script's
     "devices" ({"*" | id | "#tag": mode}; a source's id wins over its tags, tags that disagree give the most
     careful mode), a schedule's "devices", the operation panel's "devices"
  4  operation panel "pages": [{"id", "title"}] (tabs), a block's "page" and "width" ("auto" | "narrow" | "wide"),
     the watch widget "list" {"list", "scan_sub", "rename", "remove"}
  5  plain words for the people running it: a step's "say" / "say_fail", a sub-script's "say" / "say_fail"
     (without them the runtime words a failure itself: automation/runner.py plain_fail)
  6  operation panel "sources": {"kinds": [kind | "<category>/*"], "q": text, "help": text,
     "new_mode": "shadow" | "live"}: which sources the people running it may scan for and pick
  7  values {"state": id}
  8  one kind of "what to do" everywhere: a rule's "do" and a situation's "on_enter" are step lists, with the same
     steps as a sub-script
       rule      {"id", "name", "enabled", "urgent", "when", "do": [step, ...], "cooldown", "max_per_hour",
                 "max_per_day"}; [] = do nothing
       new steps goto {"situation"} (a main script's rules only), stop {"text"} (stop this device), stay {"text"}
                 (do nothing and let no lower rule act; a rule's only step), hold {"text"} (keep every other
                 script still while this guard rule holds; a guard rule's only step)
       every input step (tap, long_press, swipe, back, input_text, launch_app) may wait after it:
                 "after": {"seconds": n} | {"until": when, "timeout": n, "on_timeout": "fail" | "continue"}
       call      "on_fail": "fail" | "continue" | "stop"
       condition compare {"left", "op", "right"}: two numbers; values may be {"sum": [...]}
     7 -> 8: every rule's "action" becomes "do", every "on_enter" a list.
  9  operation panel controls "devices": [source id | "#tag"] - a per-device control only for these sources (e.g. the
     greenhouse's buttons only on the greenhouse camera); without it, every source"""
from i18n import _

FORMAT = 9


def stamp(obj):
    """obj (a dict about to be written) with the current format."""
    return {**obj, "format": FORMAT}


def version(obj):
    return int((obj or {}).get("format") or 0)


def check(obj, what):
    if version(obj) > FORMAT:
        raise ValueError(_("{what} 是較新的腳本規範(第 {p2} 版)寫的,這個 Inspector 只認得到第 {FORMAT} 版,請先更新", what=what, p2=version(obj), FORMAT=FORMAT))


def readable(obj):
    """False for a file written by a newer spec (it is skipped, not misread)."""
    return version(obj) <= FORMAT


def upgrade(obj):
    """An older file brought to the current format.
    0 -> 1: the wait step's "seconds_param" (the only field that could take a parameter) becomes
            "seconds": {"param": ...} like every other value.
    1 -> 2, 2 -> 3, 3 -> 4, 4 -> 5, 5 -> 6, 6 -> 7, 8 -> 9: nothing to change (they only add).
    7 -> 8: a rule's "action" becomes "do" (a step list), a situation's "on_enter" a step list (action_steps())."""
    if version(obj) >= FORMAT or not isinstance(obj, dict):
        return obj
    import copy
    out = copy.deepcopy(obj)

    def walk(steps):
        for st in steps or []:
            if st.get("type") == "wait" and st.get("seconds_param"):
                st["seconds"] = {"param": st.pop("seconds_param")}
            for k in ("then", "else", "steps"):
                walk(st.get(k))
            for e in (st.get("elif") or []) + (st.get("options") or []):
                walk(e.get("then"))
    walk(out.get("steps"))
    walk(out.get("cleanup"))
    for sit in out.get("situations") or ([{"rules": out["rules"]}] if out.get("rules") else []):
        for r in sit.get("rules") or []:
            if "action" in r:
                r["do"] = action_steps(r.pop("action"))
        if isinstance(sit.get("on_enter"), dict):
            sit["on_enter"] = action_steps(sit["on_enter"])
    out["format"] = FORMAT
    return out


def action_steps(a):
    """A rule action of format 7 and before as the steps of format 8 (the same behaviour)."""
    a = dict(a or {})
    t = a.get("type", "none")
    text = a.get("text")
    if t == "none":
        return []
    if t in ("tap", "long_press"):
        st = {"type": t, "target": a.get("target") or {}}
        if a.get("ms") is not None:
            st["ms"] = a["ms"]
    elif t == "back":
        st = {"type": "back"}
    elif t == "notify":
        return [{"type": "notify", "text": text or _("通知")}]
    elif t in ("stop", "hold", "wait"):
        return [{"type": {"wait": "stay"}.get(t, t), **({"text": text} if text else {})}]
    elif t == "goto":
        return [{"type": "goto", "situation": a.get("situation"), **({"say": text} if text else {})}]
    elif t == "set_var":
        st = {k: a[k] for k in ("var", "mode", "value") if k in a}
        st["type"] = "set_var"
    elif t == "output":
        st = {k: a[k] for k in ("output", "command", "value") if k in a}
        st["type"] = "output"
    elif t == "call":
        st = {"type": "call", "sub": a.get("sub"), "args": a.get("args") or {}}
        fail, ok = a.get("on_fail"), a.get("on_success")
        if fail == "stop":
            st["on_fail"] = "stop"
        elif fail:
            st["on_fail"], st["fail_goto"] = "continue", fail     # kept as it was: on failure switch there
        out = [st]
        if ok == "stop":
            out.append({"type": "stop", "text": _("子腳本完成後停止")})
        elif ok:
            out.append({"type": "goto", "situation": ok})
        if text and not text.startswith("呼叫子腳本"):
            st["say"] = text
        return out
    else:
        return []
    if text:
        st["say"] = text
    return [st]
