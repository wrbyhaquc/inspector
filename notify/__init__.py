"""Notifications (通知): tell people what happened, through whatever channels they use (Discord first).

The runtime emits events; this module decides per channel whether to send them, merges repeats, and sends in a
background thread (a slow or failing channel never holds up the watch loop).

  <runtime dir>/notify.json         where to send (it holds secrets such as webhook addresses: kept where it runs,
                                    never in the design or a pack)
     {"channels": [{"id", "name", "type", "enabled", "config": {...the type's fields},
                    "kinds": [event kinds to send], "devices": [only these; empty = all],
                    "quiet": {"from": "HH:MM", "to": "HH:MM"} | null   (only urgent ones then),
                    "image": bool  (attach the screen with urgent events)}],
      "merge_minutes": 10}
  <runtime dir>/notify_status.json  per channel: last sent / last error (for the page)

Event kinds (KINDS): urgent (an urgent rule matched: an incident began), urgent_end (it is over), warn (something
failed or needs a look), notify (a script's 通知 step / action), info (schedules started / finished and the like).

Channel types live in notify/channels.py: each declares its fields (with which are secret) and how to send."""
import datetime
import json
import os
import queue
import re
import threading
import time

from . import channels as channel_types
from i18n import N_, _

FILE = "notify.json"
STATUS = "notify_status.json"
KINDS = {"urgent": N_("緊急事件發生"), "urgent_end": N_("緊急事件結束"), "warn": N_("失敗或需要注意"), "notify": N_("腳本的「通知」"),
         "ask": N_("腳本問問題(要回答)"), "info": N_("一般訊息(排程開始、完成…)")}
KIND_MARK = {"urgent": "🚨", "urgent_end": "✅", "warn": "⚠️", "notify": "🔔", "ask": "❓", "info": "ℹ️"}
DEFAULT_KINDS = ["urgent", "urgent_end", "warn", "notify", "ask"]
MASK = "••••••"


def _read(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def load(runtime_dir):
    return _read(os.path.join(runtime_dir, FILE), {"channels": [], "merge_minutes": 10})


def masked(runtime_dir):
    """The settings for the page: secret fields hidden."""
    cfg = load(runtime_dir)
    out = []
    for c in cfg.get("channels", []):
        t = channel_types.types().get(c.get("type"))
        conf = dict(c.get("config") or {})
        for f in (t.FIELDS if t else []):
            if f.get("secret") and conf.get(f["name"]):
                conf[f["name"]] = MASK + conf[f["name"]][-4:]
        out.append({**c, "config": conf})
    return {**cfg, "channels": out}


def save(runtime_dir, cfg):
    """Validate and store; a secret field sent back masked keeps its stored value."""
    old = {c["id"]: c for c in load(runtime_dir).get("channels", [])}
    seen, out = set(), []
    for c in cfg.get("channels") or []:
        cid, name = str(c.get("id") or ""), str(c.get("name") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", cid) or cid in seen:
            raise ValueError(_("通知管道的代號不正確或重複"))
        seen.add(cid)
        if not name:
            raise ValueError(_("請替通知管道取個名稱"))
        t = channel_types.types().get(c.get("type"))
        if not t:
            raise ValueError(_("「{name}」:不支援這種通知管道", name=name))
        conf = {}
        for f in t.FIELDS:
            v = (c.get("config") or {}).get(f["name"], "")
            if f.get("secret") and isinstance(v, str) and v.startswith(MASK):
                v = ((old.get(cid) or {}).get("config") or {}).get(f["name"], "")
            conf[f["name"]] = v.strip() if isinstance(v, str) else v
        t.check(conf, name)
        kinds = [k for k in c.get("kinds") or [] if k in KINDS]
        quiet = c.get("quiet") or None
        if quiet and not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(quiet.get(k, ""))) for k in ("from", "to")):
            raise ValueError(_("「{name}」:勿擾時段要像 23:00", name=name))
        out.append({"id": cid, "name": name, "type": c["type"], "enabled": bool(c.get("enabled", True)), "config": conf,
                    "kinds": kinds, "devices": [str(d) for d in c.get("devices") or []], "quiet": quiet,
                    "image": bool(c.get("image", True))})
    merge = int(cfg.get("merge_minutes", 10))
    if not 0 <= merge <= 240:
        raise ValueError(_("合併時間要在 0~240 分鐘"))
    _write(os.path.join(runtime_dir, FILE), {"channels": out, "merge_minutes": merge})
    return masked(runtime_dir)


def _expand(keys):
    from drivers.sources import expand
    return expand(keys)


def _in_quiet(quiet, now):
    if not quiet:
        return False
    hm = datetime.datetime.fromtimestamp(now).strftime("%H:%M")
    a, b = quiet["from"], quiet["to"]
    return a <= hm < b if a <= b else hm >= a or hm < b


def render(ev, channel=None):
    """The message text of an event (the same for every channel type; a type may format it further)."""
    t = datetime.datetime.fromtimestamp(ev["t"]).strftime("%m/%d %H:%M")
    from drivers.sources import label
    head = _("{p1} {p2} · {p3} · {t}", p1=KIND_MARK.get(ev['kind'], ''), p2=label(ev.get('device')) or _("全部"), p3=_(KINDS.get(ev['kind'], ev['kind'])), t=t)
    text = ev["text"]
    if ev.get("repeats"):
        text += _("\n(前 {merge_minutes} 分鐘內同樣的事另外發生了 {repeats} 次)", merge_minutes=ev['merge_minutes'], repeats=ev['repeats'])
    return head, text


def send_now(channel, ev, image_jpeg=None):
    """Send one event through one channel right away (raises on failure). Used by the test button too."""
    t = channel_types.types()[channel["type"]]
    head, text = render(ev, channel)
    if getattr(t, "LISTENS", False):                  # a bot: to the chat it was paired in, with buttons
        from . import commands
        rd = channel.get("_runtime_dir") or ""
        t.send({**channel["config"], "_chat": commands.chat_of(rd, channel["id"])}, head, text, image_jpeg,
               commands.notify_buttons(ev))
    else:
        t.send(channel["config"], head, text, image_jpeg)


class Notifier:
    """Owned by the runtime: emit() is cheap and never blocks; a worker thread sends."""

    def __init__(self, runtime_dir):
        self.dir = runtime_dir
        self.q = queue.Queue(maxsize=500)
        self.last = {}                     # (channel, device, kind, text) -> (time sent, repeats since)
        self.status = _read(os.path.join(runtime_dir, STATUS), {})
        threading.Thread(target=self._work, daemon=True, name="notify").start()

    def emit(self, kind, device, text, frame=None, now=None):
        try:
            self.q.put_nowait({"kind": kind, "device": device, "text": text, "t": now or time.time(), "frame": frame})
        except queue.Full:
            pass                           # far too much at once: drop rather than slow the runtime down

    def _work(self):
        while True:
            ev = self.q.get()
            try:
                self._route(ev)
            except Exception as e:         # never let the worker die
                print(_("通知:處理失敗 {e}", e=e), flush=True)

    def _route(self, ev):
        cfg = load(self.dir)
        merge = float(cfg.get("merge_minutes", 10)) * 60
        jpeg = None
        for c in cfg.get("channels", []):
            kinds = c.get("kinds") or DEFAULT_KINDS
            if not c.get("enabled") or (ev["kind"] not in kinds and not (ev["kind"] == "ask" and "notify" in kinds)):
                continue                           # (a channel set up before questions existed gets them with 通知)
            if ev["kind"] == "ask" and getattr(channel_types.types().get(c.get("type")), "LISTENS", False):
                continue                           # a bot gets the question itself, with a button per option
            if c.get("devices") and ev["device"] and ev["device"] not in _expand(c["devices"]):
                continue
            if ev["kind"] != "urgent" and _in_quiet(c.get("quiet"), ev["t"]):
                continue
            # the same thing on the same device within a few minutes: count it, say so with the next one
            key = (c["id"], ev["device"], ev["kind"], re.sub(r"\d+", "#", ev["text"]))
            seen = self.last.get(key)
            if merge and seen and ev["t"] - seen[0] < merge:
                self.last[key] = (seen[0], seen[1] + 1)
                continue
            out = {**ev, "repeats": seen[1] if seen else 0, "merge_minutes": int(merge // 60)}
            self.last[key] = (ev["t"], 0)
            if ev.get("frame") is not None and c.get("image", True) and ev["kind"] == "urgent" and jpeg is None:
                jpeg = _jpeg(ev["frame"])
            try:
                send_now({**c, "_runtime_dir": self.dir}, out, jpeg if c.get("image", True) and ev["kind"] == "urgent" else None)
                self._mark(c["id"], ok=True)
            except Exception as e:
                self._mark(c["id"], ok=False, error=str(e))

    def _mark(self, cid, ok, error=None):
        s = self.status.setdefault(cid, {})
        if ok:
            s.update(last_ok=time.time(), sent=s.get("sent", 0) + 1)
        else:
            s.update(last_error=time.time(), error=error, failed=s.get("failed", 0) + 1)
        _write(os.path.join(self.dir, STATUS), self.status)


def _jpeg(frame):
    import io
    from PIL import Image
    im = Image.fromarray(frame)
    im.thumbnail((960, 540))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=80)
    return b.getvalue()


def status(runtime_dir):
    return _read(os.path.join(runtime_dir, STATUS), {})
