"""Thinning the recordings (錄影瘦身): a recorded frame that adds nothing is deleted - one that looks like the frame
kept just before it on the same device (within GAP seconds) AND got the same automatic labels. Training learns the
same answer from it twice; the screen it shows is still there in the kept one.

Never thinned: a frame a person answered or labelled, one a question, the test set or the review queue points at
(and NEIGHBOR seconds around it), a recording and device a script test replays, the runner's saved questions
(shadow_<date>), a recording still being made or changed in the last hour, and a frame with no labels yet.

Looks like = a small grey copy (THUMB) differs from the kept one by at most MEAN on average and no cell of a
CELLS grid by more than CELL (a changed number or a popup in one corner still counts as different).

Two steps, both a job (python -m project.thin): the plan (nothing is deleted; written to <work>/.thin/plan.json),
then --apply, which checks every frame again and deletes it, takes its line out of samples.jsonl (kept in
thinned.jsonl next to it) and writes the cleaning down (runtime/retention.py)."""
import argparse
import collections
import json
import os
import re
import time

import project
from i18n import _

THUMB = (96, 54)
CELLS = (6, 8)                     # rows, columns: 9 x 12 pixels each
MEAN, CELL = 5, 30                 # out of 255
GAP = 60
NEIGHBOR = 3.0
QUIET = 3600
META = {"frame", "session", "device", "id", "t", "trigger", "group", "scores", "sources", "labeler_version",
        "schema_version", "mtime", "auto"}
REF = re.compile(r"sessions[\\/]+([^\\/\"]+)[\\/]+devices[\\/]+([^\\/\"]+)[\\/]+frames[\\/]+(\d+)\.\w+")


def _dir(work):
    return os.path.join(work, ".thin")


def plan_path(work):
    return os.path.join(_dir(work), "plan.json")


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


def _labels(work):
    d = os.path.join(work, "labels")
    vs = sorted((v for v in os.listdir(d) if v.startswith("v") and v[1:].isdigit()), key=lambda v: int(v[1:])) if os.path.isdir(d) else []
    return os.path.join(d, vs[-1]) if vs else None


def _same(a, b):
    """the automatic labels of two frames, as training sees them (numbers to 2 places)"""
    def norm(v):
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    keys = (set(a) | set(b)) - META
    return all(norm(a.get(k)) == norm(b.get(k)) for k in keys)


def protected(work, data_root):
    """-> (frames {(session, device, id)}, replayed {(session, device)}) that must stay"""
    frames = set()
    lab = _labels(work)
    if lab:
        for r in _jsonl(os.path.join(lab, "labels.jsonl")):
            if r.get("auto") == 0:                        # a person labelled it
                frames.add((r["session"], r["device"], str(r["id"])))
    texts = [os.path.join(work, "testset", f) for f in (os.listdir(os.path.join(work, "testset")) if os.path.isdir(os.path.join(work, "testset")) else [])]
    texts += [os.path.join(work, "shadow", f) for f in (os.listdir(os.path.join(work, "shadow")) if os.path.isdir(os.path.join(work, "shadow")) else []) if f.endswith(".jsonl")]
    if lab:
        texts.append(os.path.join(lab, "review_candidates.jsonl"))
    for p in texts:
        try:
            with open(p, encoding="utf-8") as f:
                frames |= set(REF.findall(f.read()))
        except (OSError, UnicodeDecodeError):
            pass
    replayed = set()
    try:
        with open(os.path.join(data_root, "meta", "tests.json"), encoding="utf-8") as f:
            replayed = {(t.get("session"), t.get("device")) for t in json.load(f).get("tests") or []}
    except (OSError, ValueError):
        pass
    return frames, replayed


def _kept(work, data_root):
    """-> function (session, device, id, t) -> must it stay?"""
    frames, replayed = protected(work, data_root)
    times = collections.defaultdict(list)
    for s, d, i in frames:
        times[(s, d)].append(int(i) / 1000)
    return lambda s, d, i, t: ((s, d) in replayed or (s, d, i) in frames
                               or any(abs(t - x) <= NEIGHBOR for x in times.get((s, d), ())))


def _recordings(work):
    """(session, device, device dir) of the finished recordings that may be thinned"""
    root = os.path.join(work, "sessions")
    for s in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        sp = os.path.join(root, s, "session.json")
        if s.startswith("shadow_") or not os.path.exists(sp):
            continue
        try:
            with open(sp, encoding="utf-8") as f:
                if not json.load(f).get("ended"):
                    continue
        except (OSError, ValueError):
            continue
        dd = os.path.join(root, s, "devices")
        for d in sorted(os.listdir(dd)) if os.path.isdir(dd) else []:
            p = os.path.join(dd, d)
            if os.path.exists(os.path.join(p, "samples.jsonl")) and time.time() - os.path.getmtime(os.path.join(p, "samples.jsonl")) > QUIET:
                yield s, d, p


def _low():
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:
        pass


def _thumb(path):
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("L").resize(THUMB, Image.BILINEAR), dtype=np.int16)
    except OSError:
        return None


def _looks_like(a, b):
    import numpy as np
    d = np.abs(a - b)
    r, c = CELLS
    return d.mean() <= MEAN and d.reshape(r, THUMB[1] // r, c, THUMB[0] // c).mean(axis=(1, 3)).max() <= CELL


def plan(data_root, workers=4):
    """Find what thinning would delete; written to plan_path(). -> the plan without its list of frames"""
    from multiprocessing import Pool
    work = project.work_of(data_root)
    lab = _labels(work)
    if not lab:
        raise RuntimeError(_("還沒有標籤,無法判斷哪些畫面重複;請先產生標籤"))
    labels = {(r["session"], r["device"], str(r["id"])): r for r in _jsonl(os.path.join(lab, "labels.jsonl"))}
    kept = _kept(work, data_root)
    recs = list(_recordings(work))
    frames = total = 0
    drop, per = [], []
    with Pool(workers, initializer=_low) as pool:
        for n, (s, d, p) in enumerate(recs, 1):
            samples = [x for x in _jsonl(os.path.join(p, "samples.jsonl")) if x.get("frame") or x.get("id")]
            paths = [os.path.join(p, x.get("frame") or f"frames/{x['id']}.png") for x in samples]
            have = [(x, fp) for x, fp in zip(samples, paths) if os.path.exists(fp)]
            thumbs = pool.map(_thumb, [fp for _x, fp in have], chunksize=16)
            last, gone, size = None, 0, 0
            for (x, fp), g in sorted(zip(have, thumbs), key=lambda z: z[0][0].get("t_req") or 0):
                b = os.path.getsize(fp)
                frames += 1
                total += b
                i, t = str(x["id"]), x.get("t_req") or int(x["id"]) / 1000
                lb = labels.get((s, d, i))
                if (g is not None and lb is not None and last is not None and not kept(s, d, i, t)
                        and t - last[0] < GAP and _same(lb, last[2]) and _looks_like(g, last[1])):
                    drop.append({"session": s, "device": d, "id": i, "frame": project.rel_of(fp, data_root), "bytes": b,
                                 "like": last[3]})
                    gone += 1
                    size += b
                    continue
                if g is not None and lb is not None:
                    last = (t, g, lb, project.rel_of(fp, data_root))
                else:
                    last = None                           # nothing to compare with: the next one is kept
            per.append({"session": s, "device": d, "frames": len(have), "drop": gone, "bytes": size})
            print(_("{n}/{all} {s} {d}:{k} 張裡 {gone} 張重複", n=n, all=len(recs), s=s, d=d, k=len(have), gone=gone), flush=True)
    out = {"t": time.time(), "labels": os.path.basename(lab), "frames": frames, "bytes": total,
           "drop_frames": len(drop), "drop_bytes": sum(x["bytes"] for x in drop), "recordings": per, "drop": drop}
    os.makedirs(_dir(work), exist_ok=True)
    with open(plan_path(work) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(plan_path(work) + ".tmp", plan_path(work))
    print(_("重複 {n} 張,可省 {gb} GB(全部 {all} 張)", n=len(drop), gb=f"{out['drop_bytes'] / 1e9:.1f}", all=frames), flush=True)
    return summary(data_root)


def summary(data_root, samples=6):
    """The plan without its list of frames, plus a few pairs to look at; None without a plan"""
    try:
        with open(plan_path(project.work_of(data_root)), encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError):
        return None
    d = p.pop("drop")
    step = max(1, len(d) // samples) if d else 1
    p["samples"] = [{"frame": x["frame"], "like": x["like"]} for x in d[::step][:samples]]
    p["recordings"] = sorted(p["recordings"], key=lambda r: -r["bytes"])[:20]
    return p


def apply(data_root, runtime_dir, by="user"):
    """Delete what the plan found, checking every frame again. -> {"files", "bytes"}"""
    from runtime import retention
    work = project.work_of(data_root)
    with open(plan_path(work), encoding="utf-8") as f:
        p = json.load(f)
    kept = _kept(work, data_root)
    sessions = os.path.join(work, "sessions")
    by_dir = collections.defaultdict(set)
    files = size = 0
    for x in p["drop"]:
        fp = os.path.join(work, x["frame"])
        if kept(x["session"], x["device"], x["id"], int(x["id"]) / 1000) or not os.path.exists(os.path.join(work, x["like"])):
            continue                                       # answered since, or the frame it looks like is gone
        try:
            b = os.path.getsize(fp)
            os.remove(fp)
        except OSError:
            continue
        by_dir[os.path.join(sessions, x["session"], "devices", x["device"])].add(x["id"])
        files += 1
        size += b
    for d, ids in by_dir.items():
        sp = os.path.join(d, "samples.jsonl")
        st = os.stat(sp)
        with open(sp, encoding="utf-8") as f:
            lines = f.readlines()
        keep, out = [], []
        for line in lines:
            try:
                (out if str(json.loads(line).get("id")) in ids else keep).append(line)
            except ValueError:
                keep.append(line)
        with open(os.path.join(d, "thinned.jsonl"), "a", encoding="utf-8") as f:
            f.writelines(out)
        with open(sp + ".tmp", "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.replace(sp + ".tmp", sp)
        os.utime(sp, (st.st_atime, st.st_mtime))           # nothing new was recorded: the labels are not out of date
        print(_("{d}:刪掉 {n} 張", d=os.path.relpath(d, sessions), n=len(out)), flush=True)
    os.remove(plan_path(work))
    retention.note(runtime_dir, by, "thinned", files, size, {"recordings": len(by_dir)})
    print(_("刪掉 {n} 張重複的畫面,省下 {gb} GB", n=files, gb=f"{size / 1e9:.1f}"), flush=True)
    return {"files": files, "bytes": size}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--runtime")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        apply(a.data, a.runtime)
    else:
        plan(a.data)
