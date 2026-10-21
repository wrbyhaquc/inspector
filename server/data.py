"""Read-only access to the dataset on disk, with small mtime-based caches."""
import glob
import json
import os
import re
import shutil
import threading

from PIL import Image

import project
from . import DATA_ROOT, WORK_ROOT

_lock = threading.Lock()
_cache = {}          # key -> (mtime, value)


def _cached(key, path, loader):
    try:
        m = os.path.getmtime(path)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == m:
            return hit[1]
    v = loader(path)
    with _lock:
        _cache[key] = (m, v)
    return v


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def rel(path):
    return project.rel_of(path, DATA_ROOT)


def abs_path(relpath):
    """Resolve a data-root relative path and refuse anything outside the data root."""
    p = os.path.abspath(project.resolve(relpath, DATA_ROOT))
    if not any(project.inside(p, r) for r in (DATA_ROOT, WORK_ROOT)):
        raise ValueError("path outside data root")
    return p


# ---------------- disk ----------------
def disk():
    u = shutil.disk_usage(WORK_ROOT)
    return {"total": u.total, "used": u.used, "free": u.free}


# ---------------- sessions ----------------
def _dir_bytes(d):
    total = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


_size_cache = {}     # finished session id -> bytes (sessions do not change after they end)


def sessions():
    out = []
    for d in sorted(glob.glob(os.path.join(WORK_ROOT, "sessions", "*")), reverse=True):
        sid = os.path.basename(d)
        meta = _cached(("session", sid), os.path.join(d, "session.json"),
                       lambda p: json.load(open(p, encoding="utf-8"))) or {}
        ended = meta.get("ended")
        if ended and sid in _size_cache:
            size = _size_cache[sid]
        else:
            size = _dir_bytes(d)
            if ended:
                _size_cache[sid] = size
        devs = [{"name": n, **v} for n, v in (meta.get("devices") or {}).items()]
        out.append({"id": sid, "started": meta.get("started"), "ended": ended,
                    "minutes": round((ended - meta["started"]) / 60, 1) if ended and meta.get("started") else None,
                    "devices": devs, "samples": sum(v.get("samples", 0) for v in devs),
                    "touches": sum(v.get("touches", 0) for v in devs), "bytes": size})
    return out


def device_dir(session, device):
    if not re.fullmatch(r"[\w\-]+", session) or not re.fullmatch(r"[\w\-]+", device):
        raise ValueError("bad name")
    return os.path.join(WORK_ROOT, "sessions", session, "devices", device)


def samples(session, device):
    d = device_dir(session, device)
    return _cached(("samples", session, device), os.path.join(d, "samples.jsonl"), read_jsonl) or []


def events(session, device):
    d = device_dir(session, device)
    return _cached(("events", session, device), os.path.join(d, "events.jsonl"), read_jsonl) or []


def touches(session, device):
    d = device_dir(session, device)
    return _cached(("touches", session, device), os.path.join(d, "touches.jsonl"), read_jsonl) or []


# ---------------- labels ----------------
def label_versions():
    out = []
    for d in sorted(glob.glob(os.path.join(WORK_ROOT, "labels", "v*")), key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        s = os.path.join(d, "summary.json")
        if os.path.exists(s):
            out.append({"version": os.path.basename(d), "updated": os.path.getmtime(s),
                        "summary": json.load(open(s, encoding="utf-8"))})
    return out


def latest_label_version():
    v = label_versions()
    return v[-1]["version"] if v else None


def labels(version=None):
    """-> {(session, device, id): label record}"""
    version = version or latest_label_version()
    if not version:
        return {}
    path = os.path.join(WORK_ROOT, "labels", version, "labels.jsonl")

    def load(p):
        return {(r["session"], r["device"], r["id"]): r for r in read_jsonl(p)}
    return _cached(("labels", version), path, load) or {}


def review_candidates(version=None):
    version = version or latest_label_version()
    if not version:
        return []
    path = os.path.join(WORK_ROOT, "labels", version, "review_candidates.jsonl")
    return _cached(("cands", version), path, read_jsonl) or []


# ---------------- images ----------------
def view_image(relpath):
    """Full-size JPEG copy of a frame for answering questions (~1/7 of the PNG; read and decoded much faster).
    Kept on the fast runtime disk, not next to the PNGs on the data disk."""
    from . import RUNTIME_DIR
    src = abs_path(relpath)
    out = os.path.join(RUNTIME_DIR, "view_cache", os.path.splitext(relpath)[0] + ".jpg")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".tmp"
        Image.open(src).convert("RGB").save(tmp, "JPEG", quality=92)
        os.replace(tmp, out)
    return out


def thumbnail(relpath, width=320):
    src = abs_path(relpath)
    thumb = os.path.join(WORK_ROOT, ".cache", "thumbs", os.path.splitext(relpath)[0] + f"_{width}.jpg")
    if not os.path.exists(thumb):
        os.makedirs(os.path.dirname(thumb), exist_ok=True)
        im = Image.open(src).convert("RGB")
        im.thumbnail((width, width))
        im.save(thumb, quality=82)
    return thumb
