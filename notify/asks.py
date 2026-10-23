"""Questions a running script asks people (the 問使用者 step) and their answers.

The runtime writes a question; whoever answers first wins - a paired chat (notify/commands.py posts it with one button
per option), the runner page or the operation panel. Files under <runtime dir>/asks/:
  <id>.json          {"id", "device", "text", "options": [labels], "created", "expires", "default": option no | None,
                      "script_name", "status": "open" | "answered" | "timeout" | "gone"}
  <id>.answer.json   {"option": 1-based, "label", "by", "t"}       created once (exclusive): the first answer wins
  <id>.posted.json   {channel id: time}                            which chats it was sent to
Closed questions are removed after a day."""
import atomic
import json
import os
import random
import time
from i18n import _

DIR = "asks"
KEEP = 86400


def _d(runtime_dir):
    return os.path.join(runtime_dir, DIR)


def _read(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(p, obj):
    atomic.write_json(p, obj, ensure_ascii=False)


def create(runtime_dir, device, text, options, timeout, default=None, script_name=""):
    d = _d(runtime_dir)
    os.makedirs(d, exist_ok=True)
    now = time.time()
    qid = f"{int(now)}{random.SystemRandom().randint(0, 0xffff):04x}"
    _write(os.path.join(d, qid + ".json"), {"id": qid, "device": device, "text": text, "options": list(options), "created": now,
                                            "expires": now + float(timeout), "default": default, "script_name": script_name,
                                            "status": "open"})
    _tidy(d, now)
    return qid


def get(runtime_dir, qid):
    q = _read(os.path.join(_d(runtime_dir), qid + ".json"))
    if q:
        a = _read(os.path.join(_d(runtime_dir), qid + ".answer.json"))
        if a:
            q["answer"] = a
    return q


def answer_of(runtime_dir, qid):
    return _read(os.path.join(_d(runtime_dir), qid + ".answer.json"))


def answer(runtime_dir, qid, option, by):
    """-> (ok, message). The first answer wins; a closed or expired question takes none."""
    q = _read(os.path.join(_d(runtime_dir), qid + ".json"))
    if not q:
        return False, _("找不到這個問題")
    if q.get("status") != "open" or time.time() > q["expires"]:
        return False, _("這個問題已經結束了")
    if not 1 <= int(option) <= len(q["options"]):
        return False, _("沒有這個選項")
    p = os.path.join(_d(runtime_dir), qid + ".answer.json")
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        a = _read(p) or {}
        return False, _("已經有人回答了:{label}({by})", label=a.get('label'), by=a.get('by'))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"option": int(option), "label": q["options"][int(option) - 1], "by": by, "t": time.time()}, f, ensure_ascii=False)
    return True, _("已回答:{p1}", p1=q['options'][int(option) - 1])


def close(runtime_dir, qid, status):
    p = os.path.join(_d(runtime_dir), qid + ".json")
    q = _read(p)
    if q and q.get("status") == "open":
        q["status"] = status
        q["closed"] = time.time()
        _write(p, q)


def pending(runtime_dir):
    """Open questions (not answered, not expired), oldest first."""
    d = _d(runtime_dir)
    if not os.path.isdir(d):
        return []
    out, now = [], time.time()
    for f in sorted(os.listdir(d)):
        if f.endswith(".json") and f.count(".") == 1:
            q = _read(os.path.join(d, f))
            if q and q.get("status") == "open" and now <= q["expires"] and not os.path.exists(os.path.join(d, q["id"] + ".answer.json")):
                out.append(q)
    return out


def posted(runtime_dir, qid):
    return _read(os.path.join(_d(runtime_dir), qid + ".posted.json"), {}) or {}


def mark_posted(runtime_dir, qid, channel):
    p = os.path.join(_d(runtime_dir), qid + ".posted.json")
    m = _read(p, {}) or {}
    m[channel] = time.time()
    _write(p, m)


def _tidy(d, now):
    for f in os.listdir(d):
        p = os.path.join(d, f)
        try:
            if now - os.path.getmtime(p) > KEEP:
                os.remove(p)
        except OSError:
            pass
