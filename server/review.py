"""Human-checked test set: <project>\\testset\\testset.jsonl (append-only; latest entry per frame wins).

Each entry stores {"answers": {state_id: value}} for the states whose review is enabled in the state
definitions. Entries written before the schema existed stored their answers at the top level (next to "answers");
they are read as answers too.

Who answered is stored in "reviewer": "human" (the UI, default) or "claude" (bulk pre-labels). Claude's entries
carry "unsure" (Claude could not tell) and "spot_check" (randomly picked for a human to double-check); those two
kinds show up in the review page as "needs your check" until a human answers the same frame. A Claude entry never
replaces an existing human answer."""
import collections
import json
import os
import threading
import time

import schema as schema_mod

from . import DATA_ROOT, WORK_ROOT
from . import data
from i18n import _

PATH = os.path.join(WORK_ROOT, "testset", "testset.jsonl")
_lock = threading.Lock()


def _state_ids():
    import schema as schema_mod
    try:
        return {s["id"] for s in schema_mod.load(DATA_ROOT)["states"]}
    except Exception:
        return set()


def _answers(rec, ids=None):
    a = dict(rec.get("answers") or {})
    for legacy in (_state_ids() if ids is None else ids) & set(rec):           # early entries kept answers next to "answers"
        if legacy not in a and rec.get(legacy) is not None:
            a[legacy] = rec[legacy]
    return a


def _history():
    if not os.path.exists(PATH):
        return []
    out = []
    ids = _state_ids()
    for r in data.read_jsonl(PATH):
        r["answers"] = _answers(r, ids)
        r.setdefault("reviewer", "human")
        out.append(r)
    return out


def decisions():
    """Latest entry per frame; a Claude entry written after a human one does not replace it."""
    out = {}
    for r in _history():
        prev = out.get(r["frame"])
        if r["reviewer"] == "claude" and prev and prev["reviewer"] == "human" and not prev.get("deleted"):
            continue
        out[r["frame"]] = r
    return {k: v for k, v in out.items() if not v.get("deleted")}


def test_decisions():
    """Decisions that are test questions. Frames saved while scripts run are mostly answered as training data
    (use = "train"): they teach the model, so they must not also grade it."""
    return {k: v for k, v in decisions().items() if v.get("use") != "train"}


def use_for(frame_id):
    """Answered frames saved while scripts run: 3 of 4 become training data, 1 of 4 a test question (stable per frame)."""
    try:
        return "test" if int(frame_id) % 4 == 0 else "train"
    except (TypeError, ValueError):
        return "test"


def needs_human(rec):
    return bool(rec) and rec.get("reviewer") == "claude" and bool(rec.get("unsure") or rec.get("spot_check"))


def save(d):
    sch = schema_mod.load(DATA_ROOT)
    answers = {k: v for k, v in (d.get("answers") or {}).items() if v is not None}
    skipped = sorted({k for k in (d.get("skipped") or []) if k not in answers})
    for sid in skipped:
        if not schema_mod.state(sch, sid):
            raise ValueError(_("沒有這個狀態「{sid}」", sid=sid))
    for sid, value in answers.items():
        st = schema_mod.state(sch, sid)
        if not st or st["type"] != "class":
            raise ValueError(_("沒有可以人工確認的狀態「{sid}」", sid=sid))
        if value not in [c["value"] for c in st["classes"]]:
            raise ValueError(_("「{name}」沒有「{value}」這個選項", name=st['name'], value=value))
    data.abs_path(d["frame"])                      # validates the path
    reviewer = d.get("reviewer") or "human"
    if reviewer not in ("human", "claude"):
        raise ValueError(_("未知的確認者「{reviewer}」", reviewer=reviewer))
    rec = {"frame": d["frame"], "session": d.get("session"), "device": d.get("device"), "id": d.get("id"),
           "answers": answers, "skipped": skipped, "schema_version": sch["version"], "note": d.get("note", ""),
           "deleted": bool(d.get("deleted")), "reviewed_at": time.time(), "reviewer": reviewer}
    if d.get("use") == "train":
        rec["use"] = "train"
    if reviewer == "claude":
        rec["unsure"] = bool(d.get("unsure"))
        rec["spot_check"] = bool(d.get("spot_check"))
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with _lock, open(PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


DISMISSED = os.path.join(WORK_ROOT, "testset", "dismissed.json")


def dismissed():
    """Frames saved while scripts ran that are put aside for now ({frame: time} put aside by the user,
    {frame: {"t", "why": "learned" | "dupe"}} by tidying the questions, runtime/tidy.py); nothing is deleted."""
    try:
        with open(DISMISSED, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_dismissed(frames, on=True):
    with _lock:
        d = dismissed() if on else {}
        if on:
            now = time.time()
            d.update({f: now for f in frames})
        os.makedirs(os.path.dirname(DISMISSED), exist_ok=True)
        with open(DISMISSED + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(DISMISSED + ".tmp", DISMISSED)
    return len(d)


def set_tidied(frames):
    """Replace what the last tidying put aside with {frame: why}; what the user put aside stays."""
    with _lock:
        d = {f: v for f, v in dismissed().items() if not isinstance(v, dict)}
        now = time.time()
        d.update({f: {"t": now, "why": w} for f, w in frames.items() if f not in d})
        os.makedirs(os.path.dirname(DISMISSED), exist_ok=True)
        with open(DISMISSED + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(DISMISSED + ".tmp", DISMISSED)
    return len(d)


def answer_one(frame, state_id, value):
    """Answer (or clear, value None) one state on one frame, keeping the frame's other answers: the quick answering
    in a state's page. The frame becomes / stays a test question."""
    parts = frame.replace("\\", "/").split("/")
    if len(parts) < 6 or parts[0] != "sessions" or parts[2] != "devices" or parts[4] != "frames":
        raise ValueError(_("只能回答錄下來的畫面"))
    prev = decisions().get(frame) or {}
    answers = dict(prev.get("answers") or {})
    if value is None:
        answers.pop(state_id, None)
    else:
        answers[state_id] = value
    return save({"frame": frame, "session": parts[1], "device": parts[3], "id": os.path.splitext(parts[5])[0],
                 "answers": answers, "skipped": [k for k in prev.get("skipped") or [] if k != state_id],
                 "use": prev.get("use"), "note": prev.get("note", ""), "reviewer": "human"})


def answers_for(state_id):
    """{frame: value} of the test questions answered for one state, and the counts per value."""
    out = {f: d["answers"][state_id] for f, d in test_decisions().items() if state_id in d.get("answers", {})}
    return {"answers": out, "counts": dict(collections.Counter(str(v) for v in out.values()))}


def _claude_check(sch):
    """For frames Claude pre-labelled and a human later answered: how often did Claude agree?"""
    last_claude, res = {}, collections.Counter()
    ids = [st["id"] for st in sch["states"] if st["type"] == "class" and st.get("review", {}).get("enabled")]
    wrong = []
    for r in _history():
        if r["reviewer"] == "claude":
            last_claude[r["frame"]] = r
        elif r["frame"] in last_claude and not r.get("deleted"):
            c = last_claude.pop(r["frame"])
            kind = "unsure" if c.get("unsure") else "spot"
            for sid in ids:
                h, a = r["answers"].get(sid), c["answers"].get(sid)
                if h is None or a is None:
                    continue
                ok = h == a
                res[f"{kind}_{'agree' if ok else 'differ'}"] += 1
                if not ok:
                    wrong.append({"frame": r["frame"], "field": sid, "human": h, "claude": a, "kind": kind})
    return {**dict(res), "differences": wrong[-50:]}


def stats(version=None):
    """How well do the current automatic labels agree with human answers? (= baseline accuracy per state)"""
    sch = schema_mod.load(DATA_ROOT)
    dec = test_decisions()
    by_frame = {data.rel(r["frame"]): r for r in data.labels(version).values()}
    hidden_values = {"hidden"}
    out = {"reviewed": len(dec), "states": {}, "disagreements": [],
           "by_reviewer": dict(collections.Counter(r["reviewer"] for r in dec.values())),
           "needs_human": sum(1 for r in dec.values() if needs_human(r)),
           "claude_check": _claude_check(sch)}
    for st in sch["states"]:
        if st["type"] != "class" or not st.get("review", {}).get("enabled"):
            continue
        sid = st["id"]
        dist, ev = collections.Counter(), collections.Counter()
        for frame, h in dec.items():
            human = h["answers"].get(sid)
            if human is None:
                continue
            dist[str(human)] += 1
            r = by_frame.get(frame)
            if not r or sid not in r:          # no automatic label for this state (e.g. manual-only state)
                continue
            auto = r.get(sid)
            if auto is None:
                ev["abstained_ok" if human in hidden_values else "abstained_missed"] += 1
            elif auto == human:
                ev["correct"] += 1
            else:
                ev["wrong"] += 1
                out["disagreements"].append({"frame": frame, "field": sid, "human": human, "rule": auto})
        judged = ev["correct"] + ev["wrong"]
        total = judged + ev["abstained_ok"] + ev["abstained_missed"]
        out["states"][sid] = {"name": st["name"], "distribution": dict(dist), "eval": dict(ev),
                              "accuracy": round(ev["correct"] / judged, 4) if judged else None,
                              "coverage": round(judged / total, 4) if total else None}
    out["disagreements"] = out["disagreements"][-100:]
    return out
