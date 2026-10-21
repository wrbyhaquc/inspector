"""Which way each state is judged while a script runs (no torch here, the web server imports this):

  model  the trained model has a head for it and passed its test (or there is no other way to judge it); where the
         state also has a screen rule, the rule backs the model up on frames it is not sure of (runtime/arbiter.py)
  rule   it has a screen rule (reference images / colour ratio made on the state page, or one a plugin provides) and
         the model was not trained on it yet, or did not pass its test: the rule is evaluated on the live frame, so a
         new state works without retraining
  none   neither (hand-answered states, the place-name gallery, ...): scripts cannot use it yet

Each state's 判斷方式 (state setting "judge"): "auto" (default, as above), "model" (only the model: the rule neither
backs it up nor overrules it) or "rule" (only the screen rule). A choice that cannot be followed (no model head / no
rule) falls back to auto and says so.

The model "passes" a state when the test (human answers) is big enough to mean something, every answer class was
tested a few times, it is at least as good as the screen rule on the same frames, and it holds up on the emulator it
never saw in training. See model_test()."""
import glob
import json
import os

from labeler import generic
from project import word
from i18n import N_, _
import project

MIN_ANSWERS = 20          # test questions per state before an accuracy means much
MIN_PER_CLASS = 3         # ... and per answer class (else e.g. "on" is never tested, only "off")
HOLDOUT_MIN = 0.90        # accuracy on the emulator the model never saw in training
HOLDOUT_MIN_N = 10        # (only judged when it has at least this many test frames)
RULE_MARGIN = 0.02        # the rule takes a whole state over only when it scored at least this much better ...
RULE_MARGIN_N = 3         # ... and that many more test questions right (else the difference means nothing)
CRITERIA = {"min_answers": MIN_ANSWERS, "min_per_class": MIN_PER_CLASS, "holdout_min": HOLDOUT_MIN,
            "rule_margin": RULE_MARGIN, "rule_margin_n": RULE_MARGIN_N}
MODES = {"auto": N_("自動"), "model": N_("只用模型"), "rule": N_("只用規則")}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


MODEL_FILES = ("model.onnx", "model_best.pt")    # what a training run's model may be kept as (ONNX: no PyTorch needed)


def model_file(run_dir):
    """The model of a training run: model.onnx (with its model.json) when it can be run here, else model_best.pt;
    None when the run has neither."""
    if not run_dir:
        return None
    onnx = os.path.join(run_dir, "model.onnx")
    if os.path.exists(onnx) and os.path.exists(os.path.join(run_dir, "model.json")) and onnx_ok():
        return onnx
    pt = os.path.join(run_dir, "model_best.pt")
    if os.path.exists(pt):
        return pt
    return onnx if os.path.exists(onnx) else None


def onnx_ok():
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def model_time(run_dir):
    """When the run's model was made (its file's time), or None."""
    p = model_file(run_dir)
    return os.path.getmtime(p) if p else None


def latest_run(data_root):
    """The newest finished training run's folder (has a model and eval.json), or None."""
    runs = {os.path.dirname(p) for f in MODEL_FILES for p in glob.glob(os.path.join(project.models_of(data_root), "*", f))}
    runs = sorted((r for r in runs if os.path.exists(os.path.join(r, "eval.json"))), key=lambda r: model_time(r) or 0)
    return runs[-1] if runs else None


def model_test(e):
    """One head of eval.json -> (result, reason). result: pass / partial (passed, but some answer class was hardly
    tested) / fail."""
    if not e:
        return "fail", _("這次學習沒有考這個狀態")
    if e.get("kind") == "ratio":
        mae = e.get("test_mae")
        return "pass", _("平均誤差 {p1}%", p1=format(mae * 100, '.1f')) if mae is not None else ""
    n, acc = e.get("n") or 0, e.get("model_acc")
    if n < MIN_ANSWERS or acc is None:
        return "fail", _("考題只有 {n} 題(至少 {MIN_ANSWERS} 題),還不知道準不準", n=n, MIN_ANSWERS=MIN_ANSWERS)
    rule = (e.get("rule") or {}).get("acc_overall")
    if rule is not None and rule - acc >= RULE_MARGIN and (rule - acc) * n >= RULE_MARGIN_N:
        return "fail", _("模型 {acc} 比畫面規則 {rule} 明顯差", acc=format(acc, '.1%'), rule=format(rule, '.1%'))
    close = _(";略低於畫面規則 {rule},差 {p2} 題,看不出差別", rule=format(rule, '.1%'), p2=round((rule - acc) * n)) if rule is not None and acc < rule else ""
    hold = (e.get("by_group") or {}).get("holdout") or {}
    if (hold.get("n") or 0) >= HOLDOUT_MIN_N and hold.get("acc") is not None and hold["acc"] < HOLDOUT_MIN:
        return "fail", _("沒看過的{p1}只答對 {acc}(至少 {HOLDOUT_MIN})", p1=word("device"), acc=format(hold['acc'], '.1%'), HOLDOUT_MIN=format(HOLDOUT_MIN, '.0%'))
    counts = [sum(r) for r in e.get("confusion") or []]
    few = [_("「{nm}」{c} 題", nm=nm, c=c) for v, nm, c in zip(e.get("classes") or [], e.get("class_names") or [], counts)
           if v != "hidden" and c < MIN_PER_CLASS]
    if few:
        return "partial", _("考試通過 {acc}{close},但", acc=format(acc, '.1%'), close=close) + _("、").join(few) + _(",這種畫面還不確定")
    return "pass", _("考試通過 {acc}{close}", acc=format(acc, '.1%'), close=close)


def provided_rules(schema):
    """State ids a plugin's rule answers (they can back the model up, or judge the state on their own)."""
    from labeler import rules
    out = set()
    for p in rules._providers():          # asks the plugins only (the configured generic rules stay as they are)
        try:
            p.configure(schema, None)
            out |= set(p.states())
        except Exception:
            pass
    return out


def sources(schema, run_dir, provided=None):
    """-> {"run", "run_name", "criteria", "states": {state id: {"source", "reason", "test", "test_reason", "mode",
    "only"?, "acc"?, "holdout_acc"?, "mae"?, "rule"?}}}   test = pass / partial / fail / None (never learned);
    mode = the state's 判斷方式; only = the model alone (no rule backing it up)."""
    cfg = _read(os.path.join(run_dir, "config.json")) if run_dir else None
    ev = _read(os.path.join(run_dir, "eval.json")) if run_dir else None
    heads = {h["id"] for h in (cfg or {}).get("heads", [])}
    ev_heads = (ev or {}).get("heads", {})
    run_name = ((cfg or {}).get("config") or {}).get("name") or (os.path.basename(run_dir) if run_dir else None)
    provided = provided_rules(schema) if provided is None else provided
    out = {}
    for s in schema["states"]:
        sid = s["id"]
        mode = s.get("judge") or "auto"
        own = generic.is_generic(s) and s["type"] in ("class", "number", "ratio")
        plug = sid in provided and s["type"] == "class"
        has_rule = own or plug
        rule_name = s["source"].get("rule") if own else (s["source"].get("rule") or "plugin")
        rule_text = _("「{x}」", x=_(generic.KINDS[s["source"]["rule"]])) if own else _("畫面規則") if plug else ""
        info = {"test": None, "test_reason": "", "mode": mode}
        if sid in heads:
            e = ev_heads.get(sid, {})
            test, why = model_test(e)
            hold = (e.get("by_group") or {}).get("holdout", {})
            info.update({"test": test, "test_reason": why, "acc": e.get("model_acc"), "holdout_acc": hold.get("acc"),
                         "mae": e.get("test_mae")})
        note = ""
        if mode == "rule":
            if has_rule:
                out[sid] = {**info, "source": "rule", "rule": rule_name, "reason": _("設定為只用規則:用{rule_text}判斷", rule_text=rule_text)}
                continue
            note = _("設定為只用規則,但這個狀態沒有畫面規則;")
        elif mode == "model":
            if sid in heads:
                extra = _(";模型還沒通過考試({test_reason})", test_reason=info['test_reason']) if info["test"] == "fail" else ""
                out[sid] = {**info, "source": "model", "only": True,
                            "reason": _("設定為只用模型(「{run_name}」),畫面規則不參與{extra}", run_name=run_name, extra=extra)}
                continue
            note = _("設定為只用模型,但模型還沒學過這個狀態;")
        if sid in heads:
            test, why = info["test"], info["test_reason"]
            rule_acc = ((ev_heads.get(sid) or {}).get("rule") or {}).get("acc_overall")
            worse = rule_acc is not None and info.get("acc") is not None and rule_acc < info["acc"]
            if test == "fail" and has_rule and worse:     # failing, but the rule did even worse: no reason to switch
                out[sid] = {**info, "source": "model",
                            "reason": _("{note}模型還沒通過考試({why}),但{rule_text}考得更差({rule_acc},模型 {acc}),仍以模型為主;模型沒把握時由{rule_text2}幫忙確認", note=note, why=why, rule_text=rule_text, rule_acc=format(rule_acc, '.1%'), acc=format(info['acc'], '.1%'), rule_text2=rule_text)}
            elif test == "fail" and has_rule:
                out[sid] = {**info, "source": "rule", "rule": rule_name,
                            "reason": _("{note}模型還沒通過考試({why}),先用{rule_text}判斷", note=note, why=why, rule_text=rule_text)}
            else:
                extra = "" if test != "fail" else _(";還沒通過考試({why}),但沒有其他判斷方式", why=why)
                backup = _(";模型沒把握時由{rule_text}幫忙確認", rule_text=rule_text) if has_rule else ""
                out[sid] = {**info, "source": "model", "reason": _("{note}模型已學過(「{run_name}」){extra}{backup}", note=note, run_name=run_name, extra=extra, backup=backup)}
        elif has_rule:
            why = _("模型還沒學過這個狀態") if run_dir else _("還沒有訓練好的模型")
            out[sid] = {**info, "source": "rule", "rule": rule_name,
                        "reason": note + (_("用{rule_text}判斷(數值由規則直接讀,模型不學)", rule_text=rule_text) if s["type"] in ("number", "ratio")
                                          else _("{why},用{rule_text}判斷;下次學習會一起學", why=why, rule_text=rule_text))}
        elif s["source"].get("kind") == "manual":
            out[sid] = {**info, "source": "none", "reason": note + _("人工標註的狀態只進測試集,腳本執行時不判斷")}
        elif s["type"] == "gallery":
            out[sid] = {**info, "source": "none", "reason": note + _("名稱庫比對目前不在腳本執行時判斷")}
        else:
            out[sid] = {**info, "source": "none",
                        "reason": note + _("模型還沒學過,這種規則在腳本執行時也還不能判斷;學習後才能用")}
    return {"run": os.path.basename(run_dir) if run_dir else None, "run_name": run_name, "criteria": CRITERIA,
            "states": out}
