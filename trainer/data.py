"""Which frames go where, and what each model head should learn from them. No torch here, so the web server
can preview a split without loading the GPU stack.

Splits (decided per frame):
  test     frames with an answer in the human-checked test set (testset.jsonl) -> the only honest score
  val      frames from the hold-out devices (never trained on) -> weak labels, used to pick the best epoch
  excluded frames within NEIGHBOR_SECONDS of a test frame on the same device (near duplicates would leak
           the test answers into training)
  train    everything else that has at least one usable target

Targets come from the latest labels (screen rules + the plugins' label sources). A rule that could not decide gives no target
(the head simply skips that frame), except for "covered" flags which become the "hidden" class (which flags mean
that is up to the rule: labeler.rules.hidden)."""
import collections
import hashlib
import json
import os

import schema as schema_mod
from i18n import _
import project

NEIGHBOR_SECONDS = 3.0


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rel(data_root, path):
    return project.rel_of(path, data_root)


def latest_labels(data_root):
    d = os.path.join(project.work_of(data_root), "labels")
    vs = sorted((v for v in os.listdir(d) if v.startswith("v") and v[1:].isdigit()), key=lambda v: int(v[1:])) if os.path.isdir(d) else []
    if not vs:
        raise RuntimeError(_("還沒有標籤,請先到「進階工具 › 自動標註」產生"))
    return vs[-1], _read_jsonl(os.path.join(d, vs[-1], "labels.jsonl"))


def labels_status(data_root):
    """Are the latest labels older than what they are made from? -> {"version", "built", "stale", "reasons"}.

    Labels depend on: the recorded samples, the state definitions, reference crops of the generic rules, what the
    project's label sources read (e.g. a name gallery), and the code: the labeler and the project's plugins."""
    import glob
    d = os.path.join(project.work_of(data_root), "labels")
    vs = sorted((v for v in os.listdir(d) if v.startswith("v") and v[1:].isdigit()), key=lambda v: int(v[1:])) if os.path.isdir(d) else []
    summ = os.path.join(d, vs[-1], "summary.json") if vs else None
    if not summ or not os.path.exists(summ):
        return {"version": None, "built": None, "stale": True, "reasons": [_("還沒有產生過標籤")]}
    built = os.path.getmtime(summ)
    newer = lambda p: os.path.exists(p) and os.path.getmtime(p) > built
    reasons = []
    new_sessions = sorted({os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p))))
                           for p in glob.glob(os.path.join(project.work_of(data_root), "sessions", "*", "devices", "*", "samples.jsonl")) if newer(p)})
    if new_sessions:
        reasons.append(_("有新收集的資料(場次 {p1})", p1=_("、").join(new_sessions)))
    if newer(os.path.join(data_root, "meta", "states", "current.json")):
        reasons.append(_("狀態定義改過"))
    changed = [os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(data_root, "meta", "rule_templates", "*", "index.json")) if newer(p)]
    if changed:
        reasons.append(_("參考圖改過(狀態 {p1})", p1=_("、").join(changed)))
    from project.plugins import plugin_dir, registry
    reg = registry(data_root)
    from labeler import gallery
    galleries = gallery.Source()
    galleries.configure(schema_mod.load(data_root), data_root)
    for src in list(reg.all("label_source").values()) + [galleries]:
        for p, why in (src.inputs(data_root) if hasattr(src, "inputs") else []):
            if newer(p) and why not in reasons:
                reasons.append(why)
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = [os.path.join(app, "labeler")] + [plugin_dir(p["name"]) for p in reg.loaded if p["ok"]]
    if any(newer(p) for c in code for p in glob.glob(os.path.join(c, "*.py")) + glob.glob(os.path.join(c, "templates", "*.png"))):
        reasons.append(_("標籤程式、外掛或內建參考圖更新了"))
    return {"version": vs[-1], "built": built, "stale": bool(reasons), "reasons": reasons, "new_sessions": new_sessions}


def test_answers(data_root):
    """frame (relative path) -> answers; latest entry per frame, a Claude entry never replaces a human one."""
    out = {}
    ids = {s["id"] for s in schema_mod.load(data_root)["states"]}
    for r in _read_jsonl(os.path.join(project.work_of(data_root), "testset", "testset.jsonl")):
        a = dict(r.get("answers") or {})
        for legacy in ids & set(r):                     # early entries kept answers next to "answers"
            if legacy not in a and r.get(legacy) is not None:
                a[legacy] = r[legacy]
        r["answers"], who = a, r.get("reviewer", "human")
        prev = out.get(r["frame"])
        if who == "claude" and prev and prev.get("reviewer", "human") == "human" and not prev.get("deleted"):
            continue
        out[r["frame"]] = r
    return {k: v for k, v in out.items() if not v.get("deleted")}


def heads(sch):
    """Model heads from the state definitions: class states the screen shows, and ratio bars."""
    out = []
    for s in sch["states"]:
        if s["type"] == "class" and s["source"]["kind"] in ("rule", "manual"):
            out.append({"id": s["id"], "name": s["name"], "kind": "class", "classes": [c["value"] for c in s["classes"]],
                        "class_names": [c["name"] for c in s["classes"]]})
        elif s["type"] == "ratio":
            out.append({"id": s["id"], "name": s["name"], "kind": "ratio", "label_key": f"{s['id']}_ratio"})
    return out


def target(head, rec, hidden=None):
    """Weak target for one head from a labels.jsonl record (class index / ratio), or None.
    hidden: labeler.rules.hidden() - rule flags that mean "not visible" (and flags that must come with them)."""
    if head["kind"] == "ratio":
        v = rec.get(head["label_key"])
        return None if v is None else float(v)
    v = rec.get(head["id"])
    flags = set(rec.get("flags", []))
    hid, need = (hidden or {}).get(head["id"], (set(), None))
    if v is None and hid & flags and (need is None or need & flags):
        v = "hidden"
    return head["classes"].index(v) if v in head["classes"] else None


def build(data_root, holdout=(), sch=None):
    sch = sch or schema_mod.load(data_root)
    hs = heads(sch)
    from labeler import rules
    hidden = rules.hidden(sch)
    version, labels = latest_labels(data_root)
    answers = test_answers(data_root)
    holdout = set(holdout)

    train_answers = {f: a for f, a in answers.items() if a.get("use") == "train"}   # human labels to learn from
    answers = {f: a for f, a in answers.items() if a.get("use") != "train"}
    test_times = collections.defaultdict(list)          # (session, device) -> [t]
    for r in labels:
        if rel(data_root, r["frame"]) in answers:
            test_times[(r["session"], r["device"])].append(r["t"])

    items = []
    for r in labels:
        f = rel(data_root, r["frame"])
        it = {"frame": f, "session": r["session"], "device": r["device"], "id": r["id"], "t": r["t"],
              "targets": {h["id"]: target(h, r, hidden) for h in hs},
              "rule": {h["id"]: r.get(h["id"]) for h in hs if h["kind"] == "class"}}
        if f in train_answers:                          # a human answer beats the automatic label
            for h in hs:
                v = train_answers[f]["answers"].get(h["id"])
                if h["kind"] == "class" and v in h["classes"]:
                    it["targets"][h["id"]] = h["classes"].index(v)
            it["human"] = True
        if f in answers:
            it["split"] = "test"
            it["answers"] = answers[f]["answers"]
            it["reviewer"] = answers[f].get("reviewer", "human")
        elif any(abs(r["t"] - t) <= NEIGHBOR_SECONDS for t in test_times.get((r["session"], r["device"]), ())):
            it["split"] = "excluded"
        elif r["device"] in holdout:
            it["split"] = "val"
        elif any(v is not None for v in it["targets"].values()):
            it["split"] = "train"
        else:
            it["split"] = "excluded"
        items.append(it)
    return {"labels_version": version, "schema_version": sch["version"], "heads": hs, "items": items}


def summary(ds):
    """Counts per split and per head/class (what the model will actually see)."""
    out = {"labels_version": ds["labels_version"], "schema_version": ds["schema_version"], "splits": {}, "heads": []}
    by_split = collections.defaultdict(list)
    for it in ds["items"]:
        by_split[it["split"]].append(it)
    for sp, its in by_split.items():
        out["splits"][sp] = {"frames": len(its), "devices": dict(collections.Counter(i["device"] for i in its))}
    for h in ds["heads"]:
        row = {"id": h["id"], "name": h["name"], "kind": h["kind"], "splits": {}}
        for sp in ("train", "val", "test"):
            its = by_split.get(sp, [])
            if h["kind"] == "class":
                if sp == "test":
                    c = collections.Counter(str(i["answers"].get(h["id"])) for i in its if i["answers"].get(h["id"]) is not None)
                else:
                    c = collections.Counter(str(h["classes"][i["targets"][h["id"]]]) for i in its if i["targets"][h["id"]] is not None)
                row["splits"][sp] = dict(c)
            else:
                row["splits"][sp] = {"labeled": sum(1 for i in its if i["targets"][h["id"]] is not None)}
        if h["kind"] == "class":
            row["classes"] = [str(c) for c in h["classes"]]
            row["class_names"] = h["class_names"]
        out["heads"].append(row)
    return out


def cache_key(frames, size):
    return hashlib.sha1(("|".join(sorted(frames)) + f"|{size}").encode()).hexdigest()[:16]
