"""This computer's storage settings (儲存空間設定), <runtime dir>/storage.json - not the design: they stay with the
machine, never in a pack.

  {"record_format": "png" | "jpg", "jpeg_quality": 50-100,      how new recordings keep their frames
   "keep": {"actions", "incidents", "schedules", "logs": days},   the run's records (runtime/retention.py; 0 = all)
   "keep_models": n,                                               the newest n training runs (0 = all; the one in
                                                                   use and the newest finished one always stay)
   "min_free_gb": n,                                               free space to keep on the work folder's disk
   "when_full": "stop" | "cycle"}                                  then: stop recording, or make room by deleting the
                                                                   oldest recordings no answer or script test uses
An older run setting "keep_days" (control.json) counts until the storage page saves "keep"."""
import json
import os
import shutil

import atomic

FILE = "storage.json"
DEFAULT = {"record_format": "png", "jpeg_quality": 90, "keep_models": 0, "min_free_gb": 20, "when_full": "stop"}


def load(runtime_dir):
    from runtime import retention
    try:
        with open(os.path.join(runtime_dir, FILE), encoding="utf-8") as f:
            s = {**DEFAULT, **json.load(f)}
    except (OSError, ValueError):
        s = dict(DEFAULT)
    if "keep" not in s:                                   # the older single number, set on the run page
        try:
            with open(os.path.join(runtime_dir, "control.json"), encoding="utf-8") as f:
                old = json.load(f).get("keep_days")
            if isinstance(old, (int, float)):
                s["keep_days"] = old
        except (OSError, ValueError):
            pass
    s["keep"] = retention.keep_of(s)
    s.pop("keep_days", None)
    if s["record_format"] not in ("png", "jpg"):
        s["record_format"] = "png"
    s["jpeg_quality"] = max(50, min(100, int(s.get("jpeg_quality") or 90)))
    if s["when_full"] not in ("stop", "cycle"):
        s["when_full"] = "stop"
    try:
        s["keep_models"] = max(0, int(s.get("keep_models") or 0))
    except (TypeError, ValueError):
        s["keep_models"] = 0
    try:
        s["min_free_gb"] = max(0.0, float(s.get("min_free_gb") or 0))
    except (TypeError, ValueError):
        s["min_free_gb"] = DEFAULT["min_free_gb"]
    return s


def save(runtime_dir, s):
    os.makedirs(runtime_dir, exist_ok=True)
    atomic.write_json(os.path.join(runtime_dir, FILE), {k: s[k] for k in (*DEFAULT, "keep")}, indent=1)
    return load(runtime_dir)


def free(folder):
    """bytes free on the disk of folder (its nearest existing parent)"""
    p = os.path.abspath(folder)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return shutil.disk_usage(p).free


def low(folder, s):
    """Is the disk under the free space to keep?"""
    return s["min_free_gb"] > 0 and free(folder) < s["min_free_gb"] * 2 ** 30


def protected(work_root, data_root):
    """Recordings that must stay: a person answered frames of them, or a script test replays them."""
    keep = set()
    try:
        with open(os.path.join(work_root, "testset", "testset.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    keep.add(json.loads(line).get("session"))
                except ValueError:
                    pass
    except OSError:
        pass
    try:
        with open(os.path.join(data_root, "meta", "tests.json"), encoding="utf-8") as f:
            keep |= {t.get("session") for t in json.load(f).get("tests") or []}
    except (OSError, ValueError):
        pass
    keep.discard(None)
    return keep


def make_room(work_root, data_root, runtime_dir, s, current=None):
    """Delete the oldest recordings nothing needs (not protected(), not the one being made) until the disk has
    the free space to keep again (and a little more, so it is not at it every minute).
    -> {"sessions": [ids], "files", "bytes", "ok": the free space is back}"""
    from runtime import retention
    want = s["min_free_gb"] * 2 ** 30 * 1.1
    keep = protected(work_root, data_root) | {current}
    root = os.path.join(work_root, "sessions")
    out = {"sessions": [], "files": 0, "bytes": 0, "ok": free(work_root) >= want}
    try:
        names = sorted(os.listdir(root))                 # session ids start with their date: the oldest first
    except OSError:
        names = []
    for sid in names:
        if out["ok"]:
            break
        p = os.path.join(root, sid)
        if sid in keep or not os.path.isdir(p) or sid.startswith("shadow_"):    # the runner's saved questions stay too
            continue
        n, b = retention._size(p)
        shutil.rmtree(p, ignore_errors=True)
        out["sessions"].append(sid)
        out["files"] += n
        out["bytes"] += b
        out["ok"] = free(work_root) >= want
    if out["sessions"]:
        retention.note(runtime_dir, "room", "recordings", out["files"], out["bytes"], {"sessions": out["sessions"]})
    return out


def old_models(models_dir, n, keep=()):
    """Training runs beyond the newest n (by their folder names, which start with the date), but never those in keep
    (the one in use, the newest finished one, one still training). -> [(run id, bytes)]; n 0 = none."""
    from runtime import retention
    if not n or not os.path.isdir(models_dir):
        return []
    runs = sorted((d for d in os.listdir(models_dir) if os.path.isdir(os.path.join(models_dir, d))), reverse=True)
    return [(r, retention._size(os.path.join(models_dir, r))[1]) for r in runs[n:] if r not in keep]
