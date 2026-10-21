"""Build labels.jsonl for every collected frame: the screen rules' answers, then what the project's label sources add.

Label sources (registry kind "label_source", from the project's plugins) are objects with:
  configure(schema, data_root)   take their settings from the state definitions
  inputs(data_root)              -> [(file, reason)] whose change makes the labels out of date
  prepare(build, jobs)           once, before the records (jobs: [(session, device, dir, sample, path, rule answer)])
  begin(session, device, dir)    once per recorded device (e.g. read its event timeline)
  record(rec, sample, rule)      add answers / flags to one frame's record (may also correct the rule answers)
  finish(recs)                   after all records (e.g. smoothing over time)
  count(rec, counter)            what to count in summary.json
The platform knows no source by name; its own name galleries (gallery.py) run last."""
import collections
import concurrent.futures
import glob
import json
import os
import random

import numpy as np
from PIL import Image

from . import LABELER_VERSION
from . import gallery, generic, rules
from .rules import label_frame
import schema as schema_mod
from i18n import _
import project

CANDIDATE_SKIP = ("trigger", "group", "sources", "labeler_version", "schema_version", "t")
HARD_FLAG_ENDS = ("_uncertain", "_unmatched", "_conflict")   # frames worth a human look first (test set)


def label_sources():
    from project.plugins import registry
    return list(registry().all("label_source").values())


_configured = {}


def _configure(data_root, version):
    """Worker processes load the same state-definition version as the main process (once per process)."""
    if _configured.get(data_root) != version:
        s = schema_mod.load(data_root, version)
        rules.configure(s, data_root)
        _configured[data_root] = version


def _label_path(args):
    path, data_root, version = args
    _configure(data_root, version)
    img = np.array(Image.open(path).convert("RGB"))
    if img.shape[:2] != tuple(reversed(__import__("project").screen())):
        return {"flags": ["bad_size"], "scores": {}}
    return label_frame(img)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class Builder:
    def __init__(self, data_root, out_dir, workers, sessions=None):
        self.data_root, self.out_dir, self.workers = data_root, out_dir, workers
        self.sessions = sessions
        os.makedirs(out_dir, exist_ok=True)
        self.schema = schema_mod.load(data_root)
        rules.configure(self.schema, data_root)
        self.sources = label_sources() + [gallery.Source()]     # name galleries are the platform's own
        for src in self.sources:
            src.configure(self.schema, data_root)
        # rule cache is valid only for the same rule code AND the same regions / thresholds
        self.generic_ids = rules.ENGINE.ids() if rules.ENGINE else []
        self.rule_key = (f"{rules.version()}:{schema_mod.params_hash(self.schema, rules.provided_ids())}"
                         f":{generic.signature(self.schema, data_root)}")
        ruled = set(rules.provided_ids()) | set(self.generic_ids)       # states the screen rules answer, in schema order
        self.rule_ids = [st["id"] for st in self.schema["states"] if st["id"] in ruled]
        self.number_ids = {st["id"] for st in self.schema["states"] if st["type"] == "number"}
        print(_("狀態定義 v{version}(規則快取鍵 {rule_key})", version=self.schema['version'], rule_key=self.rule_key))
        self.cache_path = os.path.join(out_dir, "rule_cache.jsonl")
        self.cache = {}
        for r in _read_jsonl(self.cache_path):
            if r.get("v") == self.rule_key:
                self.cache[(r["path"], r["mtime"])] = r["rule"]

    def device_dirs(self):
        pattern = os.path.join(project.work_of(self.data_root), "sessions", "*", "devices", "*", "samples.jsonl")
        for p in sorted(glob.glob(pattern)):
            d = os.path.dirname(p)
            session = os.path.basename(os.path.dirname(os.path.dirname(d)))
            if not self.sessions or session in self.sessions:
                yield session, os.path.basename(d), d

    def run(self):
        jobs = []                                   # (session, device, dir, sample)
        for session, device, d in self.device_dirs():
            for s in _read_jsonl(os.path.join(d, "samples.jsonl")):
                path = os.path.join(d, s.get("frame") or f"frames/{s['id']}.png")
                if os.path.exists(path):
                    jobs.append((session, device, d, s, path))
        print(_("找到 {p1} 張有完整畫面的樣本", p1=len(jobs)))

        todo = [p for *_x, p in jobs if (p, os.path.getmtime(p)) not in self.cache]
        print(_("需要計算畫面規則:{p1} 張(其餘使用快取)", p1=len(todo)))
        if todo:
            with concurrent.futures.ProcessPoolExecutor(max_workers=self.workers) as ex, \
                    open(self.cache_path, "a", encoding="utf-8") as cf:
                for i, (p, r) in enumerate(zip(todo, ex.map(_label_path, [(p, self.data_root, self.schema["version"]) for p in todo], chunksize=16)), 1):
                    m = os.path.getmtime(p)
                    self.cache[(p, m)] = r
                    cf.write(json.dumps({"v": self.rule_key, "path": p, "mtime": m, "rule": r}, ensure_ascii=False) + "\n")
                    if i % 200 == 0:
                        print(f"  {i}/{len(todo)}")

        rule_of = lambda p: self.cache[(p, os.path.getmtime(p))]
        for src in self.sources:
            src.prepare(self, [(*j, rule_of(j[-1])) for j in jobs])
        out, counts, begun = [], collections.defaultdict(collections.Counter), set()
        for session, device, d, s, path in jobs:
            if (session, device) not in begun:
                begun.add((session, device))
                for src in self.sources:
                    src.begin(session, device, d)
            rule = rule_of(path)
            rec = {"frame": path, "session": session, "device": device, "id": s["id"], "t": s["t_req"],
                   "trigger": s.get("trigger"), "group": f"{session}/{device}",
                   **{sid: rule.get(sid) for sid in self.rule_ids},
                   "flags": list(rule.get("flags", [])), "scores": rule.get("scores", {}),
                   "labeler_version": LABELER_VERSION, "schema_version": self.schema["version"]}
            for src in self.sources:
                src.record(rec, s, rule)
            out.append(rec)
        for src in self.sources:
            src.finish(out)
        for rec in out:
            c = counts[f"{rec['session']}/{rec['device']}"]
            c["frames"] += 1
            for sid in self.rule_ids:
                if sid in self.number_ids:                # numbers: how many frames have one, not each value
                    c[f"{sid}_read"] += rec[sid] is not None
                else:
                    c[f"{sid}={rec[sid]}"] += 1
            for src in self.sources:
                src.count(rec, c)
            for fl in rec["flags"]:
                c[f"flag:{fl}"] += 1

        with open(os.path.join(self.out_dir, "labels.jsonl"), "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        total = collections.Counter()
        for c in counts.values():
            total.update(c)
        summary = {"labeler_version": LABELER_VERSION, "schema_version": self.schema["version"], "total": dict(total),
                   "by_session_device": {k: dict(v) for k, v in counts.items()}}
        with open(os.path.join(self.out_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        self._review_candidates(out)
        return summary

    def _review_candidates(self, recs, n=200, seed=7):
        """Frames for the human-checked test set: every hard case first, then a stratified random fill.

        The list is frozen in <data_root>/testset/candidates.json the first time: a test set that changes whenever
        the rules change could not compare labeler / model versions. Delete that file to draw a new one."""
        frozen_path = os.path.join(project.work_of(self.data_root), "testset", "candidates.json")
        if os.path.exists(frozen_path):
            by_frame = {os.path.normcase(r["frame"]): r for r in recs}
            frozen = json.load(open(frozen_path, encoding="utf-8"))
            chosen = [by_frame[os.path.normcase(f)] for f in frozen if os.path.normcase(f) in by_frame]
            self._write_candidates(chosen)
            return
        rnd = random.Random(seed)
        hard = [r for r in recs if any(f.endswith(HARD_FLAG_ENDS) for f in r["flags"])]
        rnd.shuffle(hard)
        chosen = hard[: n // 2]
        strata = collections.defaultdict(list)
        for r in recs:
            if r not in chosen:
                strata[tuple(r[k] for k in self.rule_ids[:2])].append(r)   # spread over the first two states
        for lst in strata.values():
            rnd.shuffle(lst)
        while len(chosen) < n and any(strata.values()):
            for k in list(strata):
                if strata[k] and len(chosen) < n:
                    chosen.append(strata[k].pop())
        os.makedirs(os.path.dirname(frozen_path), exist_ok=True)
        with open(frozen_path, "w", encoding="utf-8") as f:
            json.dump([r["frame"] for r in chosen], f, ensure_ascii=False, indent=0)
        self._write_candidates(chosen)

    def _write_candidates(self, chosen):
        with open(os.path.join(self.out_dir, "review_candidates.jsonl"), "w", encoding="utf-8") as f:
            for r in chosen:
                f.write(json.dumps({k: v for k, v in r.items() if k not in CANDIDATE_SKIP}, ensure_ascii=False) + "\n")
