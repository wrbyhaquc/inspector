"""Model or screen rule: when the two disagree on a live frame, believe the one that has been right more often when
they disagreed like this before (same state, the rule giving the same answer), on frames a person answered. The same
for every state that has a rule - the ones a plugin of the project provides and the ones made on the state page.

Where they disagreed before (the decision itself):
  test questions of the run in use (its predictions next to the raw rule output), and frames saved while scripts
  ran with this very model (saved because the two disagreed) once a person answered them. Those are what the model
  really meets, the fixed test set is not: they count RUNTIME_WEIGHT times as much.

  rule  how often it was right when it gave this answer, on frames a person answered (raw rule output from the
        labeler's rule cache, not the smoothed labels)
  model how often it was right at about this confidence: on the test questions of the run in use (predictions.jsonl)
        and on frames saved while scripts ran since that model was made, once a person answered them - the cases
        it really meets (the test set alone is mostly easy frames and makes it look better than it is)

Guard rails, so the bar never creeps up until the model can no longer be used at all:
  - the model at MODEL_SURE or more is always believed (a fixed cap, never raised by the data)
  - the rule overrides only with at least MIN_RULE_N answers for that value, and only when it is clearly better
    (MARGIN); with fewer, the model keeps its answer
  - both rates are smoothed toward a prior, so a handful of frames cannot swing them
  - below CONF_LOW the model is "unsure" anyway: any rule answer is taken (as before)
Rebuilt when the model changes and every REFRESH seconds (new answers count right away)."""
import collections
import json
import os
import time
from i18n import _
import project

MODEL_SURE = 0.95       # at or above: always the model
CONF_LOW = 0.6          # below: the rule's answer, if it has one
MIN_RULE_N = 10         # rule answers of one value needed before it may overrule the model
MARGIN = 0.02           # how much better the rule must be
WINDOW = 0.07           # model accuracy "at about this confidence": test answers within +-WINDOW
PRIOR_N = 5             # smoothing weight (in frames)
REFRESH = 180           # seconds: new answers count within minutes
RUNTIME_WEIGHT = 3      # an answered frame from running counts this many test questions
MIN_DISAGREE = 3        # weighted disagreements needed before the rule may overrule the model
RULE_WINS = 0.6         # ... and the rule must have been right in this share of them (smoothed 1:1)


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        pass
    except OSError:
        return


def _human_answers(data_root):
    """frame (data-root relative, '/') -> answers, the latest human entry per frame."""
    out = {}
    for r in _jsonl(os.path.join(project.work_of(data_root), "testset", "testset.jsonl")):
        if (r.get("reviewer") or "human") != "human":
            continue
        if r.get("deleted"):
            out.pop(r["frame"], None)
        else:
            out[r["frame"]] = r.get("answers") or {}
    return out


def _rule_outputs(data_root, frames):
    """frame -> the raw rule output (label_frame) of the newest rule-cache entry, for the frames asked about."""
    vers = sorted((d for d in os.listdir(os.path.join(project.work_of(data_root), "labels")) if d.startswith("v") and d[1:].isdigit()),
                  key=lambda d: int(d[1:])) if os.path.isdir(os.path.join(project.work_of(data_root), "labels")) else []
    out = {}
    for v in vers:                                         # newer versions overwrite older ones
        for r in _jsonl(os.path.join(project.work_of(data_root), "labels", v, "rule_cache.jsonl")):
            rel = project.rel_of(r["path"], data_root)
            if rel in frames:
                out[rel] = r["rule"]
    return out


class Trust:
    @classmethod
    def empty(cls):
        """No evidence yet: the model is believed except where it is unsure."""
        t = cls.__new__(cls)
        t.data_root = t.run_dir = None
        t.built = 0.0
        t.rule = collections.defaultdict(lambda: [0, 0])
        t.model = collections.defaultdict(list)
        t.model_all = {}
        t.dis = collections.defaultdict(lambda: [0.0, 0.0])
        return t

    def __init__(self, data_root, run_dir, schema, rules_mod):
        self.data_root, self.run_dir = data_root, run_dir
        self.built = time.time()
        ids = {s["id"] for s in schema["states"] if s["type"] == "class"}
        human = _human_answers(data_root)
        # ---- rule: right how often per (state, answer)
        self.rule = collections.defaultdict(lambda: [0, 0])          # (state, value json) -> [right, total]
        test_rows = list(_jsonl(os.path.join(run_dir, "predictions.jsonl"))) if run_dir else []
        rule_out = _rule_outputs(data_root, set(human) | {r["frame"] for r in test_rows})

        def rule_answer(sid, r):
            return rules_mod.live_answer(sid, r)          # as the live rule answers it
        self.dis = collections.defaultdict(lambda: [0.0, 0.0])     # (state, rule answer) -> [rule right, model right]
        for row in test_rows:
            rr = rule_out.get(row["frame"])
            for sid, a in (row.get("answers") or {}).items():
                p = (row.get("pred") or {}).get(sid)
                if not rr or sid not in ids or not isinstance(p, dict):
                    continue
                rv = rule_answer(sid, rr)
                if rv is not None and rv != p.get("value"):
                    c = self.dis[(sid, json.dumps(rv))]
                    c[0] += int(rv == a)
                    c[1] += int(p.get("value") == a)
        for frame, r in {f: rule_out[f] for f in human if f in rule_out}.items():
            ans = human[frame]
            for sid in ids:
                if sid not in ans:
                    continue
                rv = rule_answer(sid, r)
                if rv is None:
                    continue
                c = self.rule[(sid, json.dumps(rv))]
                c[0] += int(rv == ans[sid])
                c[1] += 1
        # ---- model: (confidence, right) per state on the run's test questions (frames it never trained on)
        self.model = collections.defaultdict(list)
        for row in test_rows:
            for sid, a in (row.get("answers") or {}).items():
                p = (row.get("pred") or {}).get(sid)
                if sid in ids and isinstance(p, dict) and p.get("conf") is not None:
                    self.model[sid].append((float(p["conf"]), p.get("value") == a))
        # ... and frames saved while scripts ran with this very model, answered since (the model never trained on them)
        from . import judge
        since = judge.model_time(run_dir) or time.time()
        for r in _jsonl(os.path.join(project.work_of(data_root), "shadow", "uncertain.jsonl")):
            ans = human.get(r.get("frame"))
            if not ans or r.get("t", 0) < since:
                continue
            for sid, a in ans.items():
                c = (r.get("conf") or {}).get(sid)
                if sid in ids and c is not None:
                    self.model[sid].append((float(c), (r.get("pred") or {}).get(sid) == a))
            for x in r.get("reasons") or []:                # saved because the two disagreed: who was right?
                sid = x.get("state")
                if x.get("kind") == "disagree" and sid in ans and sid in ids:
                    c = self.dis[(sid, json.dumps(x.get("rule")))]
                    c[0] += RUNTIME_WEIGHT * int(x.get("rule") == ans[sid])
                    c[1] += RUNTIME_WEIGHT * int(x.get("value") == ans[sid])
        self.model_all = {sid: sum(ok for _x, ok in v) / len(v) for sid, v in self.model.items() if v}

    # ---------- the two rates ----------
    def rule_rate(self, sid, value):
        right, n = self.rule.get((sid, json.dumps(value)), (0, 0))
        return (right + PRIOR_N * 0.8) / (n + PRIOR_N), n

    def model_rate(self, sid, conf):
        pts = self.model.get(sid) or []
        near = [ok for c, ok in pts if abs(c - conf) <= WINDOW]
        prior = conf          # few cases near this confidence: take the model at its word (not its overall score,
                              # which the many easy frames push up)
        return (sum(near) + PRIOR_N * prior) / (len(near) + PRIOR_N)

    # ---------- the decision ----------
    def decide(self, sid, mv, mconf, rv):
        """-> (use_rule, why). mv / mconf: the model's answer and confidence; rv: the rule's answer (None = none)."""
        if rv is None or mconf is None:
            return False, ""
        if mconf >= MODEL_SURE:
            return False, ""
        if mv == rv:
            return False, ""
        if mconf < CONF_LOW:
            return True, _("模型沒把握({mconf})", mconf=format(mconf, '.2f'))
        rule_right, model_right = self.dis.get((sid, json.dumps(rv)), (0.0, 0.0))
        n = rule_right + model_right
        share = (rule_right + 1) / (n + 2)                  # smoothed: no record = a coin toss = the model stays
        if n >= MIN_DISAGREE and share >= RULE_WINS:
            return True, _("之前這樣意見不同時,規則對 {share}(加權 {n} 次)", share=format(share, '.0%'), n=format(n, 'g'))
        return False, ""

    def agree_conf(self, sid, value, mconf):
        """Model and rule give the same answer: two separate ways of looking say so, so it is at least as sure as the
        rule has been right with that answer (a rule that is often wrong with it adds nothing)."""
        rr, _n = self.rule_rate(sid, value)
        return max(mconf or 0.0, rr)

    def table(self, names=None):
        """For the page: per state, the rule's rate per answer, the model's overall rate, who won disagreements."""
        out = collections.defaultdict(dict)
        for (sid, v), (rr, mr) in self.dis.items():
            out[sid].setdefault("disagree", {})[v] = {"rule_right": rr, "model_right": mr}
        for (sid, v), (right, n) in self.rule.items():
            out[sid].setdefault("rule", {})[v] = {"right": right, "n": n, "rate": round(self.rule_rate(sid, json.loads(v))[0], 3)}
        for sid, acc in self.model_all.items():
            out[sid]["model"] = {"acc": round(acc, 3), "n": len(self.model[sid])}
        return dict(out)
