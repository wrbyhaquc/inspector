"""Name galleries (名稱庫): a state whose answer is a name the user gives to a piece of the screen once (state type
"gallery", source kind "gallery"), e.g. the name in a window's title bar or the label on a pen.

Per frame the state's region (its first ROI, a row) is cut to the part that holds the name, and that crop is compared
with the user's gallery: <project>/<params.dir or meta/galleries/<state id>>/*.png + index.json. Crops without a
name are clustered so the user names each distinct one once (回答問題, the state's tab); the labeler then recognises
it on every other frame.

How the row is cut is a cut method (params.cut):
  box     the whole region (built in)
  <name>  a method a plugin of the project registers (kind "gallery_cut"): fn(img, box, params) -> (x0, x1) or None
Other params: match_min (similarity needed to accept a name, 0.85), width_tol (px, 5; the same name renders with the
same width), skip_flags (frames with one of these rule flags are matched but never offered for naming, e.g. a panel
covering the screen)."""
import hashlib
import json
import os
import time

import numpy as np
from PIL import Image
from i18n import N_, _

NOT_A_NAME = "__none__"      # entries the user marked as "not a name" (e.g. icons under open panels)
MATCH_MIN = 0.85
WIDTH_TOL = 5
CUTS = {"box": N_("整個範圍")}


def _cut_box(img, box, params):
    return box[0], box[0] + box[2]


def cuts():
    """name -> label of every cut method (built in + the project's plugins)."""
    from project.plugins import registry
    reg = registry()
    return {**CUTS, **reg.labels["gallery_cut"]}


def cut_fn(name):
    if name in (None, "", "box"):
        return _cut_box
    from project.plugins import registry
    return registry().get("gallery_cut", name)


def states(schema):
    return [s for s in schema.get("states", []) if s.get("source", {}).get("kind") == "gallery"]


def validate(s):
    if not s.get("rois"):
        raise ValueError(_("{id}:名稱庫要設定一個範圍(名稱所在的那一列)", id=s['id']))
    if not cut_fn(s["source"].get("params", {}).get("cut")):
        raise ValueError(_("{id}:沒有「{cut}」這種切割方式", id=s['id'], cut=s['source']['params']['cut']))


def _ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


class Matcher:
    """One gallery state: cut, match against the gallery, store new names."""

    def __init__(self, data_root, s):
        self.id, self.name = s["id"], s["name"]
        p = s["source"].get("params", {})
        self.params = p
        self.box = s["rois"][0]["box"]
        self.y0, self.y1 = self.box[1], self.box[1] + self.box[3]
        self.match_min = p.get("match_min", MATCH_MIN)
        self.width_tol = p.get("width_tol", WIDTH_TOL)
        self.skip_flags = set(p.get("skip_flags") or [])
        self.cut = cut_fn(p.get("cut"))
        self.dir = os.path.join(data_root, p.get("dir") or os.path.join("meta", "galleries", s["id"]))
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.json")
        self.index = json.load(open(self.index_path, encoding="utf-8")) if os.path.exists(self.index_path) else {}
        # gallery files are RGB crops of the row; compare on the same min-channel feature as frames
        self.tpl = {f: np.array(Image.open(os.path.join(self.dir, f)).convert("RGB")).min(axis=2).astype(np.float32)
                    for f in self.index if os.path.exists(os.path.join(self.dir, f))}

    @property
    def stamp(self):
        """Changes whenever the gallery changes (used to invalidate cached name matches)."""
        return hashlib.md5(json.dumps(self.index, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]

    def feat(self, img, x0, x1, dy=0):
        return img[self.y0 + dy:self.y1 + dy, x0:x1].min(axis=2).astype(np.float32)   # robust to bright backgrounds

    def similarity(self, img, ext, tpl):
        """Best NCC of a gallery crop against the frame, right-aligned at the cut, +-2 px."""
        h, w = tpl.shape
        best = -1.0
        for dx in range(-2, 3):
            x1 = ext[1] + dx
            x0 = x1 - w
            if x0 < 0:
                continue
            for dy in (-1, 0, 1):
                f = self.feat(img, x0, x1, dy)
                if f.shape == tpl.shape:
                    best = max(best, _ncc(f, tpl))
        return best

    def match(self, img, ext):
        """-> (name, score) of the best gallery entry, or (None, best score)."""
        w = ext[1] - ext[0]
        best, best_name = -1.0, None
        for f, tpl in self.tpl.items():
            if abs(tpl.shape[1] - w) <= self.width_tol:
                s = self.similarity(img, ext, tpl)
                if s > best:
                    best, best_name = s, self.index[f]["name"]
        return (best_name, round(best, 3)) if best >= self.match_min else (None, round(best, 3))

    def answer(self, img):
        """One frame -> {"ext", "name", "score"}."""
        ext = self.cut(img, self.box, self.params)
        if not ext:
            return {"ext": None, "name": None, "score": None}
        name, score = self.match(img, ext)
        return {"ext": [int(ext[0]), int(ext[1])], "name": name, "score": score}

    def add(self, img, ext, name):
        crop = img[self.y0:self.y1, ext[0]:ext[1]]
        f = f"{int(time.time() * 1000)}.png"
        Image.fromarray(crop).save(os.path.join(self.dir, f))
        self.index[f] = {"name": name, "created": time.time(), "width": int(ext[1] - ext[0])}
        self._save()
        return f

    def rename(self, f, name):
        self.index[f]["name"] = name
        self._save()

    def remove(self, f):
        self.index.pop(f, None)
        p = os.path.join(self.dir, f)
        if os.path.exists(p):
            os.remove(p)
        self._save()

    def _save(self):
        tmp = self.index_path + ".tmp"
        json.dump(self.index, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, self.index_path)

    def cluster(self, items):
        """Greedy clustering of unnamed crops. items: [(frame_path, ext, feat)] -> clusters (largest first)."""
        clusters = []
        for path, ext, feat in items:
            for c in clusters:
                if abs(c["width"] - feat.shape[1]) <= self.width_tol:
                    rep = c["feat"]
                    w = min(rep.shape[1], feat.shape[1])
                    if _ncc(rep[:, -w:], feat[:, -w:]) >= self.match_min:
                        c["members"].append(path)
                        break
            else:
                clusters.append({"width": feat.shape[1], "feat": feat, "rep": path, "ext": list(map(int, ext)), "members": [path]})
        clusters.sort(key=lambda c: -len(c["members"]))
        return clusters


# ---------------- the label source (run by build.py after the project's own sources) ----------------
_workers = {}


def _answer_path(args):
    """All gallery states for one frame (runs in worker processes)."""
    path, data_root, version, ids = args
    key = (data_root, version)
    if key not in _workers:
        import schema as schema_mod
        sch = schema_mod.load(data_root, version)
        _workers.clear()
        _workers[key] = {s["id"]: Matcher(data_root, s) for s in states(sch)}
    img = np.array(Image.open(path).convert("RGB"))
    return {sid: _workers[key][sid].answer(img) for sid in ids}


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def clusters_path(out_dir, sid):
    return os.path.join(out_dir, f"gallery_{sid}_clusters.json")


class Source:
    """Answers every gallery state of the schema: record field <id>, scores[<id>], flag <id>_unnamed."""

    def configure(self, schema, data_root=None):
        self.schema, self.data_root = schema, data_root
        self.states = states(schema)

    def inputs(self, data_root):
        return [(Matcher(data_root, s).index_path, _("「{name}」的名稱庫改過", name=s['name'])) for s in self.states]

    def prepare(self, build, jobs):
        import concurrent.futures
        import schema as schema_mod
        self.res, self.skip = {}, {}
        if not self.states:
            return
        matchers = {s["id"]: Matcher(build.data_root, s) for s in self.states}
        paths = [path for *_x, path, rule in jobs]
        stamps = {sid: f"{m.stamp}:{schema_mod.params_hash(self.schema, [sid])}" for sid, m in matchers.items()}
        cache_path = os.path.join(build.out_dir, "gallery_cache.jsonl")
        cache = {(r["state"], r["path"], r["mtime"]): r["res"] for r in _read_jsonl(cache_path)
                 if stamps.get(r.get("state")) == r.get("stamp")}
        todo = {}
        for p in paths:
            m = os.path.getmtime(p)
            miss = [sid for sid in matchers if (sid, p, m) not in cache]
            if miss:
                todo[p] = miss
        print(_("名稱庫:{p1},需要比對 {p2} 張", p1=_("、").join(_("{name} {p2} 筆", name=m.name, p2=len(m.index)) for m in matchers.values()), p2=len(todo)))
        if todo:
            with concurrent.futures.ProcessPoolExecutor(max_workers=build.workers) as ex, \
                    open(cache_path, "a", encoding="utf-8") as cf:
                args = [(p, build.data_root, self.schema["version"], ids) for p, ids in todo.items()]
                for (p, _x), r in zip(todo.items(), ex.map(_answer_path, args, chunksize=16)):
                    m = os.path.getmtime(p)
                    for sid, res in r.items():
                        cache[(sid, p, m)] = res
                        cf.write(json.dumps({"state": sid, "stamp": stamps[sid], "path": p, "mtime": m, "res": res}, ensure_ascii=False) + "\n")
        for sid, mt in matchers.items():
            skip = frozenset(path for *_x, path, rule in jobs if mt.skip_flags & set(rule.get("flags", [])))
            res = {p: dict(cache[(sid, p, os.path.getmtime(p))]) for p in paths}
            for r in res.values():
                if r["name"] == NOT_A_NAME:              # the user said this crop is not a name
                    r["name"], r["ext"] = None, None
            unnamed = []
            for p, r in res.items():
                if r["ext"] and not r["name"] and p not in skip:
                    x0, x1 = r["ext"]
                    unnamed.append((p, r["ext"], mt.feat(np.array(Image.open(p).convert("RGB")), x0, x1)))
            clusters = mt.cluster(unnamed)
            with open(clusters_path(build.out_dir, sid), "w", encoding="utf-8") as f:
                json.dump([{"id": i, "rep": c["rep"], "ext": c["ext"], "width": c["width"], "count": len(c["members"]),
                            "examples": c["members"][:: max(1, len(c["members"]) // 6)][:6]} for i, c in enumerate(clusters)],
                          f, ensure_ascii=False, indent=1)
            print(_("名稱庫「{name}」:已命名 {p2} 張,未命名 {p3} 張,分成 {p4} 群", name=mt.name, p2=sum(1 for r in res.values() if r['name']), p3=len(unnamed), p4=len(clusters)))
            self.res[sid], self.skip[sid] = res, skip

    def begin(self, session, device, d):
        pass

    def record(self, rec, s, rule):
        for sid, res in self.res.items():
            nm = res.get(rec["frame"]) or {}
            rec[sid] = nm.get("name")
            rec["scores"][sid] = nm.get("score")
            if nm.get("ext") and not nm.get("name") and rec["frame"] not in self.skip[sid]:
                rec["flags"].append(f"{sid}_unnamed")

    def finish(self, recs):
        pass

    def count(self, rec, c):
        for sid in self.res:
            c[f"{sid}_named"] += rec.get(sid) is not None
