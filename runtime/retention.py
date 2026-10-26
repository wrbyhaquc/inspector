"""Keeping the run's records for a while (保留天數): what the runner writes every day is deleted after a number of days
per kind (this computer's storage settings, "keep": {kind: days}; 0 = keep everything of that kind). Without it a
site that runs for months only grows (a month of one test site: about 2 GB).

  actions     <shadow dir>/actions/<day>/              the picture of every real input                 KEEP["actions"]
  incidents   <shadow dir>/incidents/<day>_.../         urgent incidents with their clips (an open one stays)
  schedules   <shadow dir>/schedules/<day>_.../         schedule runs
  logs        <shadow dir>/log/<day>.jsonl, <runtime dir>/quality/<day>.jsonl, <work>/.jobs/<day>_....log
Deleted when its date (the name starts with YYYYMMDD) is more than that many days ago. Never: recordings (sessions),
answers, labels, models, the design - they are what the platform learns from.
The runner cleans when it starts and every CHECK_EVERY seconds after; every cleaning is written down (CLEAN_LOG in
the runtime folder): when, by whom (the runner / a person / making room), what and how much."""
import datetime
import json
import os
import re
import shutil
import time

KEEP = {"actions": 30, "incidents": 90, "schedules": 30, "logs": 30}
KEEP_DAYS = 30                     # older settings had one number for all (run setting "keep_days")
CHECK_EVERY = 6 * 3600
CLEAN_LOG = "cleanup_log.jsonl"
DAY = re.compile(r"^(\d{8})")


def keep_of(settings):
    """{kind: days} from this computer's storage settings (an older single "keep_days" counts for all but incidents)."""
    out = dict(KEEP)
    old = settings.get("keep_days")
    if isinstance(old, (int, float)):
        out.update({k: int(old) for k in out if k != "incidents"})
    for k, v in (settings.get("keep") or {}).items():
        if k in out and isinstance(v, (int, float)) and v >= 0:
            out[k] = int(v)
    return out


def _day(name):
    m = DAY.match(name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _open_incident(path):
    try:
        with open(os.path.join(path, "incident.json"), encoding="utf-8") as f:
            return json.load(f).get("status") == "open"
    except (OSError, ValueError):
        return False


def _places(shadow_dir, runtime_dir, work_dir):
    return [("actions", os.path.join(shadow_dir, "actions"), None), ("incidents", os.path.join(shadow_dir, "incidents"), _open_incident),
            ("schedules", os.path.join(shadow_dir, "schedules"), None), ("logs", os.path.join(shadow_dir, "log"), None),
            ("logs", os.path.join(runtime_dir, "quality"), None), ("logs", os.path.join(work_dir, ".jobs"), None)]


def _size(p):
    if not os.path.isdir(p):
        try:
            return 1, os.path.getsize(p)
        except OSError:
            return 0, 0
    n = b = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                b += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return n, b


def clean(shadow_dir, runtime_dir, work_dir, keep=None, today=None, dry=False, by="runner"):
    """Delete what is older than its kind's days (keep: {kind: days}, or one number for all; 0 = keep).
    -> {"files", "bytes", "kinds": {kind: {"files", "bytes"}}}; dry = only say what would go."""
    if not isinstance(keep, dict):
        keep = {k: (keep if keep is not None else v) for k, v in KEEP.items()}
    today = today or datetime.date.today()
    out = {"files": 0, "bytes": 0, "kinds": {}}
    for kind, folder, stays in _places(shadow_dir, runtime_dir, work_dir):
        days = int(keep.get(kind) or 0)
        if days <= 0:
            continue
        cutoff = today - datetime.timedelta(days=days)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            d = _day(name)
            if d is None or d >= cutoff:
                continue
            p = os.path.join(folder, name)
            if stays and stays(p):
                continue
            n, b = _size(p)
            k = out["kinds"].setdefault(kind, {"files": 0, "bytes": 0})
            k["files"] += n
            k["bytes"] += b
            out["files"] += n
            out["bytes"] += b
            if dry:
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
    if not dry and out["files"]:
        note(runtime_dir, by, "records", out["files"], out["bytes"], {"kinds": out["kinds"], "keep": keep})
    return out


def note(runtime_dir, by, what, files, size, detail=None):
    """One cleaning, written down: by "runner" | "user" | "room" (making room on a full disk), what "records" |
    "recordings"."""
    try:
        os.makedirs(runtime_dir, exist_ok=True)
        with open(os.path.join(runtime_dir, CLEAN_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "by": by, "what": what, "files": files, "bytes": size, **(detail or {})},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def history(runtime_dir, limit=50):
    try:
        with open(os.path.join(runtime_dir, CLEAN_LOG), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:][::-1]
