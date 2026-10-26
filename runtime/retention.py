"""Keeping the run's records for a while (保留天數): what the runner writes every day is deleted after keep_days days
(run setting "keep_days", default KEEP_DAYS; 0 = keep everything). Without it a site that runs for months only grows
(a month of one test site: about 2 GB).

Deleted when its date (the name starts with YYYYMMDD) is more than keep_days days ago:
  <shadow dir>/actions/<day>/              the picture of every real input
  <shadow dir>/incidents/<day>_.../         urgent incidents (one still open is kept)
  <shadow dir>/schedules/<day>_.../         schedule runs
  <shadow dir>/log/<day>.jsonl              the day's log
  <runtime dir>/quality/<day>.jsonl         how sure the model was, by the hour
  <work>/.jobs/<day>_....log                background jobs' output
Never: recordings (sessions), answers, labels, models, the design - they are what the platform learns from.
The runner cleans when it starts and every CHECK_EVERY seconds after."""
import datetime
import json
import os
import re
import shutil

KEEP_DAYS = 30
CHECK_EVERY = 6 * 3600
DAY = re.compile(r"^(\d{8})")


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


def clean(shadow_dir, runtime_dir, work_dir, keep_days=KEEP_DAYS, today=None):
    """Delete what is older than keep_days days. -> {"files": n, "bytes": n} removed (nothing when keep_days is 0)."""
    out = {"files": 0, "bytes": 0}
    if not keep_days or keep_days <= 0:
        return out
    cutoff = (today or datetime.date.today()) - datetime.timedelta(days=int(keep_days))
    places = [(os.path.join(shadow_dir, "actions"), None), (os.path.join(shadow_dir, "incidents"), _open_incident),
              (os.path.join(shadow_dir, "schedules"), None), (os.path.join(shadow_dir, "log"), None),
              (os.path.join(runtime_dir, "quality"), None), (os.path.join(work_dir, ".jobs"), None)]
    for folder, keep in places:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            d = _day(name)
            if d is None or d >= cutoff:
                continue
            p = os.path.join(folder, name)
            if keep and keep(p):
                continue
            if os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        try:
                            out["bytes"] += os.path.getsize(os.path.join(root, f))
                            out["files"] += 1
                        except OSError:
                            pass
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    out["bytes"] += os.path.getsize(p)
                    os.remove(p)
                    out["files"] += 1
                except OSError:
                    pass
    return out
