"""Urgent rules act on the first sighting (no second look) and may interrupt any sub-script, so the states they read
must be judged very reliably. This checks them:

  model-judged state: its exam in the latest training run (judge.sources): passed, >= 99%, and >= 99% on the
                      emulator it never trained on
  rule-judged state:  the CURRENT screen rule run on every frame you answered for that state (cached until the
                      state or the answers change)

urgent_states() also tells the review queue which saved frames matter most."""
import hashlib
import json
import os
import threading

import numpy as np
from PIL import Image

import automation
import schema as schema_mod
from labeler import generic

from . import data, review
from project import word
from i18n import _

MIN_ACC = 0.99           # an urgent rule's state should be at least this accurate
MIN_N = 30               # ... measured on at least this many answers (a rule-judged state)
MIN_PER_ANSWER = 10      # ... with at least this many of every answer (e.g. "alarm: yes")
_cache, _lock = {}, threading.Lock()


def urgent_states(data_root):
    """state id -> ["script name · rule name", ...] for every enabled urgent rule."""
    out = {}
    for sc in automation.load_all(data_root):
        if not sc.get("enabled", True):
            continue
        for r in automation.all_rules(sc):
            if not r.get("urgent") or not r.get("enabled", True):
                continue
            for group in r.get("when") or []:
                for c in group:
                    if c.get("state"):
                        out.setdefault(c["state"], [])
                        label = f"{sc['name']} · {r.get('name') or r['id']}"
                        if label not in out[c["state"]]:
                            out[c["state"]].append(label)
    return out


def rule_check(data_root, state):
    """The current screen rule of a state vs your answers -> {"n", "correct", "wrong": [frames], "unsure"}."""
    answers = [(f, d["answers"][state["id"]]) for f, d in review.decisions().items()
               if d.get("reviewer", "human") == "human" and state["id"] in (d.get("answers") or {})]
    tpl_idx = generic.tpl_index(data_root, state["id"]) if state["source"].get("rule") == "template" else {}
    key = hashlib.sha1(json.dumps([state, sorted(tpl_idx), answers], sort_keys=True, default=str).encode()).hexdigest()
    with _lock:
        if _cache.get(state["id"], (None,))[0] == key:
            return _cache[state["id"]][1]
    tpls = generic.load_templates(data_root, state) if tpl_idx else None
    res = {"n": 0, "correct": 0, "unsure": 0, "wrong": [], "by_answer": {}}
    for frame, want in answers:
        try:
            im = Image.open(data.abs_path(frame)).convert("RGB")
        except (OSError, ValueError):
            continue
        img = np.asarray(im if im.size == __import__("project").screen() else im.resize(__import__("project").screen()))
        got, _x = generic.evaluate(state, img, tpls)   # no gate context: as strict as possible
        res["n"] += 1
        b = res["by_answer"].setdefault(json.dumps(want), [0, 0])     # answer -> [asked, right]
        b[0] += 1
        b[1] += got == want
        if got is None:
            res["unsure"] += 1
        elif got == want:
            res["correct"] += 1
        elif len(res["wrong"]) < 20:
            res["wrong"].append({"frame": frame, "answer": want, "rule": got})
    with _lock:
        _cache[state["id"]] = (key, res)
    return res


def check(data_root, judged, sids=None):
    """judged = judge.sources(...)["states"]. -> {state id: {"level": ok | warn | bad, "text", "used_by"}} for the
    given states (default: the ones read by saved urgent rules)."""
    sch = schema_mod.load(data_root)
    hot = urgent_states(data_root)
    out = {}
    for sid in (sids if sids is not None else list(hot)):
        used_by = hot.get(sid, [])
        st = schema_mod.state(sch, sid)
        j = judged.get(sid) or {}
        if not st:
            out[sid] = {"level": "bad", "text": _("這個狀態已經不存在"), "used_by": used_by}
            continue
        if j.get("source") == "model":
            acc, hold = j.get("acc"), j.get("holdout_acc")
            if j.get("test") == "fail" or acc is None:
                level, text = "bad", _("模型沒通過考試:{p1}", p1=j.get('test_reason') or _("沒有成績"))
            elif acc < MIN_ACC:
                level, text = "warn", _("模型考試 {acc},緊急規則建議 {MIN_ACC} 以上", acc=format(acc, '.1%'), MIN_ACC=format(MIN_ACC, '.0%'))
            elif j.get("test") == "partial":
                level, text = "warn", j.get("test_reason") or _("有些答案的考題太少")
            elif hold is None:
                level, text = "warn", _("模型考試 {acc},但還沒在沒學過的{p2}上考過", acc=format(acc, '.1%'), p2=word("device"))
            elif hold < MIN_ACC:
                level, text = "warn", _("模型考試 {acc},沒學過的{p2} {hold}(建議 {MIN_ACC} 以上)", acc=format(acc, '.1%'), p2=word("device"), hold=format(hold, '.1%'), MIN_ACC=format(MIN_ACC, '.0%'))
            else:
                level, text = "ok", _("模型考試 {acc},沒學過的{p2} {hold}", acc=format(acc, '.1%'), p2=word("device"), hold=format(hold, '.1%'))
        elif j.get("source") == "rule":
            r = rule_check(data_root, st)
            n = r["n"]
            acc = r["correct"] / n if n else None
            if n < MIN_N:
                level, text = "bad", _("畫面規則只有 {n} 題您的答案可以檢查(至少 {MIN_N} 題),還不知道準不準", n=n, MIN_N=MIN_N)
            elif acc < MIN_ACC:
                level = "warn"
                text = _("畫面規則在您答過的 {n} 張只對 {acc}(錯 {p3}、沒把握 {unsure})", n=n, acc=format(acc, '.1%'), p3=len(r['wrong']), unsure=r['unsure'])
            else:
                level, text = "ok", _("畫面規則在您答過的 {n} 張對 {acc}", n=n, acc=format(acc, '.1%'))
            names = {json.dumps(c["value"]): c["name"] for c in st.get("classes") or []}
            few = [_("「{p1}」{p2} 題", p1=names[k], p2=r['by_answer'].get(k, [0])[0]) for k in names
                   if json.loads(k) != "hidden" and r["by_answer"].get(k, [0])[0] < MIN_PER_ANSWER]
            if few and level != "bad":
                level, text = "warn", text + _(",但") + _("、").join(few) + _(",這種畫面還沒驗證夠")
        else:
            level, text = "bad", j.get("reason") or _("執行時不判斷這個狀態")
        out[sid] = {"level": level, "text": text, "used_by": used_by}
    return out
