"""Where the disk goes (儲存空間): what each kind of data takes, how much is added a day, how long the free space lasts.

  recordings   <work>/sessions          what was recorded (kept until deleted on the Recording page)
  records      <work>/shadow, <runtime>/quality, <work>/.jobs   the run's records: kept keep_days days
               (runtime/retention.py), so they stop growing after that
  models       <work>/models            training runs
  answers      <work>/labels, <work>/testset   labels and answers
  other        the rest of the work and runtime folders

A day's growth is read from the dated names (YYYYMMDD...) of the last WEEK days: recordings, and the run's records
while they are not yet kept keep_days days. Walking a large folder takes a while: the result is kept CACHE_S."""
import datetime
import os
import re
import shutil
import threading
import time

WEEK = 7
CACHE_S = 600
DAY = re.compile(r"^(\d{8})")
_lock = threading.Lock()
_cache = {}


def _size(path):
    """bytes and files under path (a file: itself)"""
    total = files = 0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        pass
        except NotADirectoryError:
            try:
                return os.path.getsize(p), 1
            except OSError:
                return 0, 0
        except OSError:
            pass
    return total, files


def _by_day(folders):
    """{date: bytes} of the dated entries directly in these folders"""
    out = {}
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            m = DAY.match(name)
            if not m:
                continue
            try:
                d = datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            out[d] = out.get(d, 0) + _size(os.path.join(folder, name))[0]
    return out


def measure(work, runtime, keep_days, today=None):
    today = today or datetime.date.today()
    shadow = os.path.join(work, "shadow")
    parts = {"recordings": [os.path.join(work, "sessions")],
             "records": [shadow, os.path.join(runtime, "quality"), os.path.join(work, ".jobs")],
             "models": [os.path.join(work, "models")],
             "answers": [os.path.join(work, "labels"), os.path.join(work, "testset")]}
    sizes = {k: sum(_size(p)[0] for p in ps) for k, ps in parts.items()}
    counted = {os.path.normcase(os.path.abspath(p)) for ps in parts.values() for p in ps}
    other = 0
    for root in {os.path.abspath(work), os.path.abspath(runtime)}:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            p = os.path.join(root, name)
            q = os.path.normcase(p)
            if q not in counted and not any(c.startswith(q + os.sep) or q.startswith(c + os.sep) for c in counted):
                other += _size(p)[0]
    sizes["other"] = other

    week = [today - datetime.timedelta(days=k) for k in range(1, WEEK + 1)]           # whole days before today
    rec = _by_day([os.path.join(work, "sessions")])
    run = _by_day([os.path.join(shadow, x) for x in ("actions", "incidents", "schedules", "log")] + [os.path.join(runtime, "quality")])
    per_day = {"recordings": sum(rec.get(d, 0) for d in week) / WEEK, "records": sum(run.get(d, 0) for d in week) / WEEK}
    kept_days = len({d for d in run if d < today})
    growing = per_day["recordings"] + (per_day["records"] if not keep_days or kept_days < keep_days else 0)
    du = shutil.disk_usage(work if os.path.isdir(work) else os.path.dirname(work))
    return {"sizes": sizes, "total": sum(sizes.values()), "per_day": {k: round(v) for k, v in per_day.items()},
            "growing": round(growing), "free": du.free, "disk_total": du.total,
            "days_left": round(du.free / growing) if growing > 0 else None,
            "keep_days": keep_days, "record_days": kept_days, "t": time.time()}


def get(work, runtime, keep_days, fresh=False):
    key = (work, runtime, keep_days)
    with _lock:
        hit = _cache.get(key)
    if hit and not fresh and time.time() - hit["t"] < CACHE_S:
        return hit
    out = measure(work, runtime, keep_days)
    with _lock:
        _cache[key] = out
    return out
