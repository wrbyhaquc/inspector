"""Tidy the questions: look again, with the current model, at every frame saved while scripts ran that has no answer
yet, and decide per state whether it still needs one. A frame that asks nothing any more (the model has learned it)
or that repeats a kept frame (same emulator, a moment apart, same questions) is put aside; nothing is deleted.

    python -m runtime.tidy --data <data root>

Writes <data>/testset/tidy.json: {"model", "t", "frames": {frame: {"ask": [state], "conf": {state: c}, "pred": {...}}}}
and replaces the put-aside entries it made before (the user's own put-asides stay). Runs after every training too.

A state still needs an answer on a frame when
  - the frame has the screen rule's answer for it and the model says something else: the answer decides whom to
    believe (agreeing, the answer teaches nothing training does not learn from the rule already), or
  - there is no rule answer and the model is below what the scripts ask for (or SURE when no script reads it)."""
import argparse
import collections
import json
import os
import sys
import time

import numpy as np
from PIL import Image
from i18n import _
import project

SURE = 0.9              # no script reads the state: this sure and agreeing with the rule = learned
DUP_GAP = 120           # seconds: a frame of the same emulator this close, asking the same, teaches nothing new
TIDY_WHY = ("learned", "dupe")


def needed_conf(data_root):
    """state id -> the confidence the scripts ask for (the highest min_conf of any condition on it): below it a script
    waits or fails. States no script reads are not in it."""
    import automation
    from automation import conds as conds_mod, subs as subs_mod
    out = {}

    def take(when):
        for g in when or []:
            for c in g:
                if c.get("state"):
                    out[c["state"]] = max(out.get(c["state"], 0), float(c.get("min_conf", conds_mod.DEFAULT_MIN_CONF)))
    for sc in automation.load_all(data_root):
        for sit in sc.get("situations") or []:
            for r in sit.get("rules") or []:
                take(r.get("when"))
    for sub in subs_mod.load_all(data_root).values():
        for st in subs_mod.walk(sub.get("steps")):
            take(st.get("when"))
    return out


def path(data_root):
    return os.path.join(project.work_of(data_root), "testset", "tidy.json")


def load(data_root, model=None):
    """The last tidy result, or None (none yet, or made with another model than `model`)."""
    try:
        with open(path(data_root), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if model is None or d.get("model") == model else None


def asks(item, tidy):
    """The states still asked on a saved frame: the tidy result if it looked at it, else why it was saved."""
    t = (tidy or {}).get("frames", {}).get(item["frame"])
    return t["ask"] if t is not None else sorted({r["state"] for r in item.get("reasons") or []})


def _read_jsonl(p):
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    root = a.data
    import schema as schema_mod
    from runtime import judge
    from runtime.shadow import Predictor
    from server import data, review
    run = judge.latest_run(root)
    if not run:
        print(_("還沒有訓練好的模型,沒辦法整理"))
        return 1
    model = os.path.basename(run)
    sch = schema_mod.load(root)
    asked = {s["id"]: s for s in sch["states"] if s["type"] == "class" and (s.get("review") or {}).get("enabled")}
    needs = needed_conf(root)
    dec = review.decisions()
    labels = data.labels()                       # the screen rules' answers (frames that were labeled)
    mine = {f for f, v in review.dismissed().items() if isinstance(v, dict) and v.get("why") in TIDY_WHY}
    user_aside = {f for f in review.dismissed() if f not in mine}
    saved = [r for r in _read_jsonl(os.path.join(project.work_of(root), "shadow", "uncertain.jsonl"))]
    todo = []
    for r in saved:
        if r["frame"] in user_aside or dec.get(r["frame"]):
            continue
        if not os.path.exists(project.resolve(r["frame"], root)):
            continue
        todo.append(r)
    print(_("模型「{model}」重新看 {p2} 張還沒回答的畫面…", model=model, p2=len(todo)), flush=True)
    pred = Predictor(judge.model_file(run))
    frames, why = {}, collections.Counter()
    t0 = time.time()
    for n in range(0, len(todo), 16):
        batch = todo[n:n + 16]
        ims = [np.asarray(Image.open(project.resolve(r["frame"], root)).convert("RGB").resize(tuple(_screen()))) for r in batch]
        for r, p in zip(batch, pred(ims)):
            answered = (dec.get(r["frame"]) or {}).get("answers") or {}
            lab = labels.get((r.get("session"), r.get("device"), r.get("id"))) or {}
            rule = {k: v for k, v in lab.items() if k in asked and v is not None}     # None: the rule could not tell
            for x in r.get("reasons") or []:
                if x.get("kind") == "disagree" and "rule" in x:
                    rule.setdefault(x["state"], x["rule"])
            ask, conf, vals = [], {}, {}
            for sid in asked:
                if sid not in p or "probs" not in p[sid] or sid in answered:
                    continue
                k = int(np.argmax(p[sid]["probs"]))
                v, c = p[sid]["classes"][k], float(p[sid]["probs"][k])
                conf[sid], vals[sid] = round(c, 3), v
                was = any(x.get("state") == sid for x in r.get("reasons") or [])
                need = needs.get(sid)
                if need is None and not was:
                    continue                          # nobody reads it and it was not why the frame was saved
                if sid in rule:                       # training learns the rule's answer anyway: ask only when they differ
                    if str(rule[sid]) != str(v):
                        ask.append(sid); why["differs_from_rule"] += 1
                elif c < (need if need is not None else SURE):
                    ask.append(sid); why["unsure"] += 1
            frames[r["frame"]] = {"ask": ask, "conf": conf, "pred": vals, "device": r.get("device"), "t": r.get("t", 0)}
        if n and n % 160 == 0:
            print(_("  {n}/{p2}({p3} 秒)", n=n, p2=len(todo), p3=format(time.time() - t0, '.0f')), flush=True)
    # repeats: per emulator, a frame whose questions a kept frame a moment before already asks
    dupes, kept = set(), collections.defaultdict(list)
    for f, v in sorted(frames.items(), key=lambda kv: kv[1]["t"]):
        if not v["ask"]:
            continue
        near = [k for k in kept[v["device"]] if v["t"] - frames[k]["t"] < DUP_GAP]
        if any(set(v["ask"]) <= set(frames[k]["ask"]) for k in near):
            dupes.add(f)
        else:
            kept[v["device"]].append(f)
    learned = {f for f, v in frames.items() if not v["ask"]}
    os.makedirs(os.path.dirname(path(root)), exist_ok=True)
    with open(path(root) + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"model": model, "t": time.time(), "frames": frames, "learned": len(learned), "dupes": len(dupes)},
                  f, ensure_ascii=False, default=str)
    os.replace(path(root) + ".tmp", path(root))
    review.set_tidied({**{f: "learned" for f in learned}, **{f: "dupe" for f in dupes}})
    left = len(frames) - len(learned) - len(dupes)
    per = collections.Counter(s for f, v in frames.items() if f not in dupes for s in v["ask"])
    print(_("整理完成:{p1} 張裡,模型已學會 {p2} 張、重複 {p3} 張先收起;還要回答 {left} 張。", p1=len(frames), p2=len(learned), p3=len(dupes), left=left), flush=True)
    print(_("還要回答的題:") + _("、").join(f"{asked[s]['name']} {n}" for s, n in per.most_common()), flush=True)
    return 0


def _screen():
    import project
    return project.screen()


if __name__ == "__main__":
    sys.exit(main())
