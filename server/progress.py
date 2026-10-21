"""Per-state learning progress, and adding test questions aimed at one state.

Progress of a state, in four steps (the "learning rail" on the state page):
  define   its region and answer options are set
  judge    it can be judged automatically right now (reference images / colour rule / built-in rule / a plugin's label source)
  test     enough human answers to know how well it is judged (MIN_ANSWERS, MIN_PER_CLASS per answer)
  model    the trained model learned it and passed its test (runtime.judge.model_test)

Targeted questions: the frozen test set (testset/candidates.json) was drawn before some states existed, so it may
never show e.g. a rare warning. add_questions() draws extra frames where the automatic labels say each answer of
one state appears, spread over devices and time, appends them as a new batch and refreshes the question list."""
import collections
import json
import math
import os
import random
import time

import schema as schema_mod
from labeler import generic
from runtime import judge

from . import DATA_ROOT, WORK_ROOT, data, review
from i18n import N_, _

TESTSET = os.path.join(WORK_ROOT, "testset")


def _counts(sid):
    """answer value (str) -> number of human/Claude answers for one state"""
    c = collections.Counter()
    for r in review.test_decisions().values():
        v = (r.get("answers") or {}).get(sid)
        if v is not None:
            c[str(v)] += 1
    return c


def _answer_classes(st):
    return [c for c in st.get("classes", []) if c["value"] != "hidden"]


def short_answers(st, answered):
    """Answers of one state with fewer than MIN_PER_CLASS test questions, split by whether more questions can be
    drawn: (askable, unseen). unseen = the automatic labels never found that answer in any recording (never been
    there, or the labels cannot recognise it yet), so answering more questions cannot help."""
    in_labels = collections.Counter(str(r.get(st["id"])) for r in data.labels().values())
    askable, unseen = [], []
    for c in _answer_classes(st):
        n = answered.get(str(c["value"]), 0)
        if n < judge.MIN_PER_CLASS:
            (askable if in_labels.get(str(c["value"])) else unseen).append((c["name"], n))
    return askable, unseen


UNSEEN_HINT = (N_("自動標註從沒在錄過的畫面裡判斷出這種答案:可能還沒錄到這種畫面,或自動標註還認不得它。先錄到這種畫面,再到「畫面瀏覽」用那張畫面建立參考圖;用不到這個答案的話,可以不用管。"))


def progress():
    sch = schema_mod.load(DATA_ROOT)
    run = judge.latest_run(DATA_ROOT)
    jd = judge.sources(sch, run)
    dec = review.test_decisions()
    counts = collections.defaultdict(collections.Counter)
    for r in dec.values():
        for sid, v in (r.get("answers") or {}).items():
            if v is not None:
                counts[sid][str(v)] += 1
    out = {}
    for st in sch["states"]:
        sid, src = st["id"], st.get("source") or {}
        steps = []
        # 1. define
        ok = bool(st.get("rois")) and (st["type"] != "class" or len(_answer_classes(st)) >= 2)
        steps.append({"key": "define", "name": _("定義好"), "status": "ok" if ok else "todo",
                      "text": _("範圍與答案選項已設定") if ok else _("還要設定範圍和至少兩個答案選項"), "link": "/states"})
        # 2. judge automatically now
        if generic.is_generic(st) and st["type"] == "number":
            per = collections.Counter(str(m["value"]) for m in generic.tpl_index(DATA_ROOT, sid).values())
            digits = sum(1 for d in "0123456789" if per.get(d))
            steps.append({"key": "judge", "name": _("能判斷"), "status": "ok" if digits >= 10 else "todo",
                          "text": _("讀數字:教過 {p1} 種字元", p1=len(per)) + ("" if digits >= 10 else _("(0~9 還差 {p1} 個)", p1=10 - digits)),
                          "link": "/states"})
        elif generic.is_generic(st) and st["type"] == "class":
            if src["rule"] == "template":
                idx = generic.tpl_index(DATA_ROOT, sid)
                per = collections.Counter(str(m["value"]) for m in idx.values())
                fb = str((src.get("params") or {}).get("fallback"))
                missing = [c["name"] for c in _answer_classes(st) if not per.get(str(c["value"])) and str(c["value"]) != fb]
                text = _("參考圖:") + _("、").join(_("{name} {p2} 張", name=c['name'], p2=per.get(str(c['value']), 0)) for c in _answer_classes(st))
                steps.append({"key": "judge", "name": _("能判斷"), "status": "todo" if missing else "ok",
                              "text": text + (_(";「{p1}」還沒有參考圖", p1=_("、").join(missing)) if missing else ""), "link": "/states"})
            else:
                steps.append({"key": "judge", "name": _("能判斷"), "status": "ok", "text": _("用顏色比例判斷"), "link": "/states"})
        elif src.get("kind") == "manual":
            steps.append({"key": "judge", "name": _("能判斷"), "status": "todo",
                          "text": _("人工標註的狀態沒辦法自動判斷;要自動判斷請改成「畫面規則」"), "link": "/states"})
        elif st["type"] == "gallery":
            steps.append({"key": "judge", "name": _("能判斷"), "status": "ok", "text": _("用名稱庫比對"), "link": "/review"})
        else:
            steps.append({"key": "judge", "name": _("能判斷"), "status": "ok",
                          "text": _("標註來源提供真實值") if st["type"] == "ratio" else _("外掛的規則自動判斷"), "link": "/labels"})
        # 3. test questions
        if st["type"] == "ratio":
            steps.append({"key": "test", "name": _("有考題"), "status": "ok", "text": _("用標註來源的真實值當答案,不用出題"), "link": ""})
        elif st["type"] != "class":
            steps.append({"key": "test", "name": _("有考題"), "status": "na", "text": _("這種狀態目前不出題"), "link": ""})
        elif not (st.get("review") or {}).get("enabled"):
            steps.append({"key": "test", "name": _("有考題"), "status": "todo",
                          "text": _("還沒開啟「在『回答問題』出題」"), "link": "/states"})
        else:
            c = counts.get(sid, collections.Counter())
            n = sum(c.values())
            askable, unseen = short_answers(st, c)
            parts = _("、").join(f"{x['name']} {c.get(str(x['value']), 0)}" for x in _answer_classes(st))
            if n < judge.MIN_ANSWERS:
                stt, text = "todo", _("{n} 題(至少 {MIN_ANSWERS} 題):{parts}", n=n, MIN_ANSWERS=judge.MIN_ANSWERS, parts=parts)
            elif askable:
                stt, text = "todo", _("{n} 題,但", n=n) + _("、").join(_("「{nm}」{k} 題", nm=nm, k=k) for nm, k in askable) + _("(每種答案至少 {MIN_PER_CLASS} 題)", MIN_PER_CLASS=judge.MIN_PER_CLASS)
            elif unseen:
                stt, text = "partial", _("{n} 題:{parts}。", n=n, parts=parts) + _("「{names}」還沒錄到過,暫時沒辦法出題", names=_("」、「").join(nm for nm, _x in unseen))
            else:
                stt, text = "ok", _("{n} 題:{parts}", n=n, parts=parts)
            steps.append({"key": "test", "name": _("有考題"), "status": stt, "text": text, "link": f"/review?state={sid}"})
        # 4. model learned + passed
        j = jd["states"].get(sid, {})
        test = j.get("test")
        if test is None:
            stt, text = ("na", _("名稱庫比對不用模型")) if st["type"] == "gallery" else ("na", _("數值由規則直接讀,不用模型"))                 if st["type"] == "number" else ("todo", _("模型還沒學過;下次學習會一起學"))
        else:
            stt = {"pass": "ok", "partial": "partial", "fail": "todo"}[test]
            text = j.get("test_reason") or ""
        steps.append({"key": "model", "name": _("模型學會"), "status": stt, "text": text, "link": "/results"})
        cur = next((i for i, s in enumerate(steps) if s["status"] in ("todo",)), None)
        out[sid] = {"steps": steps, "current": cur, "source": j.get("source"), "source_reason": j.get("reason")}
    return {"run": jd["run"], "run_name": jd["run_name"], "criteria": jd["criteria"], "states": out}


# ---------------------------------------------------------------- targeted questions
def _frozen():
    p = os.path.join(TESTSET, "candidates.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []


def add_questions(state_id, n=30, gap=20.0, seed=None, dry=False, session=None, device=None):
    """Draw up to n new test frames for one state, about evenly over its answers (the rare answer gets all there
    is), at least `gap` seconds apart on one device and away from the frames already in the test set.
    session / device: only from that recording (e.g. the one made to catch this state)."""
    sch = schema_mod.load(DATA_ROOT)
    st = schema_mod.state(sch, state_id)
    if not st or st["type"] != "class":
        raise ValueError(_("只有分類型的狀態可以出題"))
    if not (st.get("review") or {}).get("enabled"):
        raise ValueError(_("「{name}」還沒開啟出題,請先到「要看的狀態」打開", name=st['name']))
    version = data.latest_label_version()
    if not version:
        raise ValueError(_("還沒有自動標註,請先產生"))
    labels = data.labels(version)
    if session:
        labels = {k: r for k, r in labels.items() if r["session"] == session and (not device or r["device"] == device)}
        if not labels:
            raise ValueError(_("場次 {session}{p2} 還沒有自動標註(是在上次產生標籤之後錄的),請先到「自動標註」按「產生標籤」", session=session, p2=' ' + device if device else ''))
    frozen = _frozen()
    frozen_set = {os.path.normcase(f) for f in frozen}
    taken = collections.defaultdict(list)                      # device -> times already in the test set
    for r in labels.values():
        if os.path.normcase(r["frame"]) in frozen_set:
            taken[r["device"]].append(r["t"])
    rnd = random.Random(seed if seed is not None else time.time())

    def far(r):
        return all(abs(r["t"] - t) >= gap for t in taken[r["device"]])

    classes = [str(c["value"]) for c in _answer_classes(st)]
    pools = {v: [] for v in classes}
    for r in labels.values():
        v = r.get(state_id)
        if v is not None and str(v) in pools and os.path.normcase(r["frame"]) not in frozen_set:
            pools[str(v)].append(r)
    have = _counts(state_id)
    # answers that have the fewest questions so far go first
    order = sorted(classes, key=lambda v: (have.get(v, 0), len(pools[v])))
    chosen, per = [], collections.Counter()
    want = {v: math.ceil(n / len(classes)) for v in classes}
    for v in order:
        groups = collections.defaultdict(list)                 # spread over sessions/devices
        for r in pools[v]:
            groups[(r["session"], r["device"])].append(r)
        for g in groups.values():
            rnd.shuffle(g)
        keys = list(groups)
        rnd.shuffle(keys)
        while per[v] < want[v] and any(groups[k] for k in keys):
            for k in keys:
                while groups[k]:
                    r = groups[k].pop()
                    if far(r):
                        chosen.append(r)
                        per[v] += 1
                        taken[r["device"]].append(r["t"])
                        break
                if per[v] >= want[v]:
                    break
        # an answer that ran short leaves room for the others
        left = [x for x in order[order.index(v) + 1:]]
        if left and per[v] < want[v]:
            extra = want[v] - per[v]
            for i, x in enumerate(left):
                want[x] += extra // len(left) + (1 if i < extra % len(left) else 0)
    if not chosen:
        raise ValueError(_("找不到新的「{name}」畫面可以出題{p2}(都已經在題目裡,或彼此太接近)", name=st['name'], p2=_("(這個場次)") if session else ''))

    names = {str(c["value"]): c["name"] for c in st["classes"]}
    if dry:
        return {"added": 0, "would_add": [data.rel(r["frame"]) for r in chosen], "by_answer": {names[v]: per[v] for v in classes},
                "available": {names[v]: len(pools[v]) for v in classes}}
    # append to the frozen list + record the batch
    os.makedirs(TESTSET, exist_ok=True)
    with open(os.path.join(TESTSET, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(frozen + [r["frame"] for r in chosen], f, ensure_ascii=False, indent=0)
    bp = os.path.join(TESTSET, "batches.json")
    batches = json.load(open(bp, encoding="utf-8")) if os.path.exists(bp) else []
    batches.append({"batch": len(batches) + 1, "count": len(chosen), "created": time.time(), "state": state_id,
                    "note": _("補考題:{name}", name=st['name']), "categories": {names[v]: per[v] for v in classes if per[v]}})
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(batches, f, ensure_ascii=False, indent=1)
    # the question list of the latest labels (the labeler rewrites it from candidates.json next time anyway)
    from labeler.build import CANDIDATE_SKIP
    with open(os.path.join(WORK_ROOT, "labels", version, "review_candidates.jsonl"), "a", encoding="utf-8") as f:
        for r in chosen:
            f.write(json.dumps({k: v for k, v in r.items() if k not in CANDIDATE_SKIP}, ensure_ascii=False) + "\n")
    return {"added": len(chosen), "by_answer": {names[v]: per[v] for v in classes},
            "available": {names[v]: len(pools[v]) for v in classes}, "batch": len(batches)}
