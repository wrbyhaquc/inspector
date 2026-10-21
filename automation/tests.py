"""Script tests (腳本測試): a recorded stretch + what the scripts are expected to do on it, checked by a replay.

<project>/meta/tests.json  {"tests": [test, ...]}
  test   {"id", "name", "description",
          "session", "device", "start": seconds from the start of the recording, "minutes",
          "sub_result": "success" | "fail"   what called sub-scripts are assumed to return (they are not run),
          "sub_results": {sub id: "success" | "fail"}   per sub-script, overriding sub_result,
          "expect": [expectation, ...]}
  expectation (every one may have "within": [from s, to s] counted from the stretch's first frame)
    {"kind": "situation", "script", "situation", "when": "end" | "ever" | "never"}
    {"kind": "call", "sub", "script"?, "when": "ever" | "never", "min"?, "max"?}
    {"kind": "input", "script"?, "rule"?, "when": "ever" | "never", "min"?, "max"?}
    {"kind": "output", "output"?, "when": "ever" | "never", "min"?, "max"?}   sent to an output (never really sent)
    {"kind": "stop", "script"?, "when": "ever" | "never"}             a script stopped itself
    {"kind": "alert", "text"?, "when": "ever" | "never"}             a warning (text: part of it)

A test runs on the saved scripts, the newest model and the recording (runtime/replaytest.py); it passes when every
expectation holds. suggest() turns one replay into expectations ("what it did is right"), to edit from there."""
import json
import os
import re
import time
from . import spec
from i18n import N_, _

KINDS = {"situation": N_("情境"), "call": N_("呼叫子腳本"), "input": N_("點擊"), "output": N_("送到輸出"), "stop": N_("停止腳本"), "alert": N_("警示")}
WHEN = {"end": N_("結束時"), "ever": N_("會"), "never": N_("不會")}


def _path(data_root):
    return os.path.join(data_root, "meta", "tests.json")


def load(data_root):
    try:
        with open(_path(data_root), encoding="utf-8") as f:
            return json.load(f).get("tests") or []
    except (OSError, ValueError):
        return []


def validate(tests):
    ids = set()
    for t in tests:
        where = _("測試「{p1}」", p1=t.get('name') or t.get('id'))
        if not re.fullmatch(r"[\w\-]+", t.get("id") or "") or t["id"] in ids:
            raise ValueError(_("{where}:代號不正確或重複", where=where))
        ids.add(t["id"])
        if not (t.get("name") or "").strip():
            raise ValueError(_("{where}:請取個名字", where=where))
        if not re.fullmatch(r"[\w\-]+", t.get("session") or "") or not re.fullmatch(r"[\w\-]+", t.get("device") or ""):
            raise ValueError(_("{where}:請選擇錄影", where=where))
        if not (0 < float(t.get("minutes") or 0) <= 240) or float(t.get("start") or 0) < 0:
            raise ValueError(_("{where}:時間範圍不正確(最多 240 分鐘)", where=where))
        if t.get("sub_result", "success") not in ("success", "fail") or any(
                v not in ("success", "fail") for v in (t.get("sub_results") or {}).values()):
            raise ValueError(_("{where}:子腳本假設的結果只能是成功或失敗", where=where))
        for i, e in enumerate(t.get("expect") or [], 1):
            k = e.get("kind")
            if k not in KINDS:
                raise ValueError(_("{where} 第 {i} 項:種類不正確", where=where, i=i))
            ok_when = ("end", "ever", "never") if k == "situation" else ("ever", "never")
            if e.get("when") not in ok_when:
                raise ValueError(_("{where} 第 {i} 項:「何時」不正確", where=where, i=i))
            if k == "situation" and not (e.get("script") and e.get("situation")):
                raise ValueError(_("{where} 第 {i} 項:請選擇腳本和情境", where=where, i=i))
            if k == "call" and not e.get("sub"):
                raise ValueError(_("{where} 第 {i} 項:請選擇子腳本", where=where, i=i))
            w = e.get("within")
            if w is not None and not (isinstance(w, list) and len(w) == 2 and 0 <= float(w[0]) < float(w[1])):
                raise ValueError(_("{where} 第 {i} 項:時間範圍不正確", where=where, i=i))
            for m in ("min", "max"):
                if e.get(m) is not None and int(e[m]) < 0:
                    raise ValueError(_("{where} 第 {i} 項:次數不正確", where=where, i=i))


def save(data_root, tests):
    validate(tests)
    p = _path(data_root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(spec.stamp({"tests": tests, "saved": time.time()}), f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


# ---------------------------------------------------------------- names for the pages
class Names:
    """Script / situation / sub-script / rule names of the project (ids stay readable when one was deleted)."""

    def __init__(self, data_root):
        import automation
        from . import subs
        self.scripts = {s["id"]: s for s in automation.load_all(data_root)}
        self.subs = subs.load_all(data_root)

    def script(self, sid):
        return (self.scripts.get(sid) or {}).get("name", sid)

    def situation(self, sid, sit):
        for x in (self.scripts.get(sid) or {}).get("situations") or []:
            if x["id"] == sit:
                return x["name"]
        return sit

    def sub(self, sid):
        return (self.subs.get(sid) or {}).get("name", sid)

    def rule(self, sid, rid):
        for x in (self.scripts.get(sid) or {}).get("situations") or []:
            for r in x.get("rules") or []:
                if r.get("id") == rid:
                    return r.get("name") or rid
        return rid


def describe(e, names):
    """An expectation in words."""
    w = e.get("within")
    span = _("在第 {p1}~{p2} 秒", p1=format(float(w[0]), 'g'), p2=format(float(w[1]), 'g')) if w else ""
    k, when = e["kind"], e["when"]
    count = ""
    if e.get("min") is not None or e.get("max") is not None:
        lo, hi = e.get("min"), e.get("max")
        count = _("{lo} 次", lo=lo) if lo == hi else _("至少 {lo} 次", lo=lo) if hi is None else _("最多 {hi} 次", hi=hi) if lo is None else _("{lo}~{hi} 次", lo=lo, hi=hi)
    if k == "situation":
        verb = {"end": _("結束時在"), "ever": _("會進入"), "never": _("不會進入")}[when]
        return _("{span}「{p2}」{verb}情境「{p4}」", span=span, p2=names.script(e['script']), verb=verb, p4=names.situation(e['script'], e['situation']))
    if k == "call":
        by = _("「{x}」", x=names.script(e["script"])) if e.get("script") else ""
        v = {"span": span, "by": by, "sub": names.sub(e["sub"]), "count": count}
        return _("{span}{by}會呼叫子腳本「{sub}」{count}", **v) if when == "ever" else _("{span}{by}不會呼叫子腳本「{sub}」{count}", **v)
    if k == "input":
        by = _("「{x}」", x=names.script(e["script"])) if e.get("script") else ""
        rule = _("(規則「{p1}」)", p1=names.rule(e['script'], e['rule'])) if e.get("rule") and e.get("script") else ""
        v = {"span": span, "by": by, "rule": rule, "count": count}
        return _("{span}{by}會點擊{rule}{count}", **v) if when == "ever" else _("{span}{by}不會點擊{rule}{count}", **v)
    if k == "output":
        v = {"span": span, "output": _("「{x}」", x=e["output"]) if e.get("output") else "", "count": count}
        return _("{span}會送到輸出{output}{count}", **v) if when == "ever" else _("{span}不會送到輸出{output}{count}", **v)
    if k == "stop":
        who = _("「{x}」", x=names.script(e["script"])) if e.get("script") else _("任何腳本")
        return _("{span}{who}會停止", span=span, who=who) if when == "ever" else _("{span}{who}不會停止", span=span, who=who)
    v = {"span": span, "text": _("「…{x}…」", x=e["text"]) if e.get("text") else ""}
    return _("{span}會出現警示{text}", **v) if when == "ever" else _("{span}不會出現警示{text}", **v)


# ---------------------------------------------------------------- checking a replay
def _hits(e, ticks, t0):
    """The moments (seconds from the start) the expectation's event happened in a replay."""
    out = []
    for tk in ticks:
        for d in tk.get("data") or []:
            k = d.get("kind")
            if e["kind"] == "call" and k == "call" and d.get("sub") == e["sub"] and (not e.get("script") or d.get("script") == e["script"]):
                out.append(d["t"] - t0)
            elif e["kind"] == "input" and k == "input" and (not e.get("script") or d.get("script") == e["script"]) \
                    and (not e.get("rule") or d.get("rule") == e["rule"]):
                out.append(d["t"] - t0)
            elif e["kind"] == "output" and k == "output" and (not e.get("output") or d.get("output") == e["output"]):
                out.append(d["t"] - t0)
            elif e["kind"] == "stop" and k == "stop" and (not e.get("script") or d.get("script") == e["script"]):
                out.append(d["t"] - t0)
        if e["kind"] == "alert":
            out += [ev["t"] - t0 for ev in tk.get("events") or [] if ev.get("kind") == "alert" and (e.get("text") or "") in ev.get("text", "")]
        if e["kind"] == "situation" and (tk.get("situation_ids") or {}).get(e["script"]) == e["situation"]:
            out.append(tk["t"] - t0)
    return out


def check(test, result, names):
    """-> [{"ok", "text", "detail"}] one per expectation."""
    ticks = result.get("ticks") or []
    t0 = ticks[0]["t"] if ticks else 0
    out = []
    for e in test.get("expect") or []:
        text = describe(e, names)
        if e["kind"] == "situation" and e["when"] == "end":
            last = (ticks[-1].get("situation_ids") or {}).get(e["script"]) if ticks else None
            ok = last == e["situation"]
            out.append({"ok": ok, "text": text, "detail": "" if ok else
                        _("結束時在「{p1}」", p1=names.situation(e['script'], last)) if last else _("這個腳本沒有在這台執行")})
            continue
        hits = _hits(e, ticks, t0)
        w = e.get("within")
        if w:
            hits = [h for h in hits if float(w[0]) <= h <= float(w[1])]
        n = len(hits) if e["kind"] != "situation" else int(bool(hits))
        if e["when"] == "never":
            ok = n == 0
            detail = "" if ok else _("第 {p1} 秒發生了", p1=format(hits[0], '.0f')) + (_("(共 {n} 次)", n=n) if n > 1 else "")
        else:
            lo = e.get("min") if e.get("min") is not None else 1
            hi = e.get("max")
            ok = n >= lo and (hi is None or n <= hi)
            detail = "" if ok else (_("一次都沒有發生") if n == 0 else _("發生了 {n} 次", n=n))
        out.append({"ok": ok, "text": text, "detail": detail})
    return out


def suggest(result, names):
    """Expectations that describe what happened in one replay (the user then keeps, edits or deletes them)."""
    ticks = result.get("ticks") or []
    out = []
    if not ticks:
        return out
    last = ticks[-1].get("situation_ids") or {}
    for sid, sit in last.items():                                   # where each script with situations ended
        if len((names.scripts.get(sid) or {}).get("situations") or []) > 1:
            out.append({"kind": "situation", "script": sid, "situation": sit, "when": "end"})
    data = [d for tk in ticks for d in tk.get("data") or []]
    calls = []
    for d in data:
        if d["kind"] == "call" and d.get("sub") not in calls:
            calls.append(d["sub"])
    out += [{"kind": "call", "sub": s, "when": "ever"} for s in calls]
    if not any(d["kind"] == "input" for d in data):
        out.append({"kind": "input", "when": "never"})
    stops = {d.get("script") for d in data if d["kind"] == "stop"}
    out += [{"kind": "stop", "script": s, "when": "ever"} for s in stops] or [{"kind": "stop", "when": "never"}]
    if not any(ev.get("kind") == "alert" for tk in ticks for ev in tk.get("events") or []):
        out.append({"kind": "alert", "when": "never"})
    return out
