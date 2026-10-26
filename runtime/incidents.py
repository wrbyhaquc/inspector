"""Urgent incidents (緊急事件): when an urgent rule matches, follow that emulator closely until things settle.

An urgent rule is the important case (an alarm, an error screen, a fish fell out of the pond...), so its whole story is kept,
apart from the everyday log: what was on screen, whether the rule really acted (or why not), what every script did
next, the sub-script steps, situation changes, how the watched states changed, and when it was over.

  <shadow dir>/incidents/<id>/incident.json   {"id", "device", "start", "end", "status", "triggers", "watch",
                                               "entries": [{"t", "kind", "text", "frame"?, ...}]}
  <shadow dir>/incidents/<id>/<ms>.jpg         frames: the trigger, every input, every FRAME_EVERY seconds, the end
  <shadow dir>/incidents/<id>/clip/<ms>.jpg    the clip (事件影片): a frame a second from PRE_S seconds before the
                                               trigger (the runner keeps them in memory, small) to CLIP_AFTER seconds
                                               after; "clip": [[t, name]] in incident.json; the pages play it back

An incident stays open while any urgent rule on that emulator matches, and TAIL seconds after the last one stopped
(so the follow-up shows); another urgent rule matching meanwhile joins the same incident. status: open / resolved /
timeout (still matching after MAX_SECONDS) / stopped (the runner stopped)."""
import collections
import datetime
import json
import os
import threading

from PIL import Image
from i18n import _

TAIL = 60
MAX_SECONDS = 1800
MAX_FRAMES = 60
FRAME_EVERY = 10         # a frame at least this often while it is open
FRAME_GAP = 2            # ... and at most this often for inputs (the trigger, the resolution and the end always get one)
RESOLVE_AFTER = 3        # not matching this long = over (an icon that blinks is still the same incident)
SAVE_EVERY = 3
PRE_S = 15               # the clip: seconds before the trigger (kept in memory, CLIP_EVERY apart) ...
CLIP_AFTER = 45          # ... and after it
CLIP_EVERY = 1.0
CLIP_W = 640             # the clip's frames are about this wide (every k-th pixel: no resampling while the runner looks)


def _small(frame):
    k = max(1, frame.shape[1] // CLIP_W)
    return frame[::k, ::k].copy()


def _urgent(decisions):
    return [d for d in decisions if d.get("urgent") and d.get("rule") and d.get("action") not in ("none", "uncertain", None)]


class Incidents:
    def __init__(self):
        self.open = {}                                   # device -> incident (with private "_" fields)
        self.on_event = None                             # (kind, device, text, frame, now) -> None: tell people (notify)
        self.pre = {}                                    # device -> deque of (t, small frame): the clip before a trigger

    def keep(self, n, frame, now):
        """Every tick: the last PRE_S seconds of each source, a small frame every CLIP_EVERY seconds."""
        if frame is None:
            return
        q = self.pre.setdefault(n, collections.deque())
        if q and now - q[-1][0] < CLIP_EVERY:
            return
        q.append((now, _small(frame)))
        while q and now - q[0][0] > PRE_S:
            q.popleft()

    # ---------- before the tick's actions: open an incident when an urgent rule matches ----------
    def begin(self, root, n, now, st, decisions, frame):
        urg = _urgent(decisions)
        inc = self.open.get(n)
        if not urg:
            return
        if not inc:
            t = datetime.datetime.fromtimestamp(now)
            iid = f"{t:%Y%m%d_%H%M%S}_{n}"
            inc = {"id": iid, "device": n, "start": round(now, 3), "end": None, "status": "open", "triggers": [],
                   "watch": [], "entries": [], "frames": 0,
                   "_dir": os.path.join(root, iid), "_exec": {}, "_last": {}, "_snap": {}, "_resolved": None,
                   "_saved": 0.0, "_frame_t": 0.0, "_miss": None, "clip": [], "_clip_t": 0.0}
            os.makedirs(os.path.join(inc["_dir"], "clip"), exist_ok=True)
            self.open[n] = inc
            before = list(self.pre.get(n) or [])         # the seconds before: written in the background
            inc["clip"] = [[round(t, 3), f"{int(t * 1000)}.jpg"] for t, _f in before]
            inc["_clip_t"] = before[-1][0] if before else 0.0
            threading.Thread(target=_write_clip, args=(inc["_dir"], before), daemon=True, name="clip").start()
        for d in urg:
            key = f"{d['script']}/{d['rule']}"
            if key in (x["key"] for x in inc["triggers"]):
                continue
            inc["triggers"].append({"key": key, "script": d["script"], "script_name": d.get("script_name"), "rule": d["rule"],
                                    "rule_name": d.get("rule_name"), "text": d.get("text"), "reason": d.get("reason"),
                                    "t": round(now, 3), "mode": d.get("mode")})
            for sid in d.get("watch") or []:
                if sid not in inc["watch"]:
                    inc["watch"].append(sid)
            self._add(inc, now, "trigger", _("[{script_name}] 緊急規則「{rule_name}」成立:{reason}", script_name=d.get('script_name'), rule_name=d.get('rule_name'), reason=d.get('reason')),
                      frame=frame, force=True, state={k: v.get("value") for k, v in (st or {}).items()})
            if self.on_event:
                self.on_event("urgent", n, _("緊急規則「{rule_name}」成立,處理方式:{text}\n原因:{reason}", rule_name=d.get('rule_name'), text=d.get('text'), reason=d.get('reason')), frame, now)
        inc["_miss"] = None
        if inc["_resolved"] is not None:
            inc["_resolved"] = None
            self._add(inc, now, "again", _("緊急規則又成立了"))

    # ---------- notes from the runner while an incident is open ----------
    def note(self, n, now, kind, text, frame=None, **extra):
        inc = self.open.get(n)
        if inc:
            self._add(inc, now, kind, text, frame=frame, **extra)

    # ---------- after the tick: follow-up, resolution, closing ----------
    def tick(self, n, now, st, decisions, frame, proc=None, held=None, situations=None):
        inc = self.open.get(n)
        if not inc:
            return
        urg = _urgent(decisions)
        for d in urg:                                    # did it act? (or why not)
            key = f"{d['script']}/{d['rule']}"
            ex = d.get("exec") or (_("試跑(只記錄)") if d.get("mode") != "live" else "")
            if inc["_exec"].get(key) != ex and not d.get("done"):
                inc["_exec"][key] = ex
                if ex:
                    self._add(inc, now, "exec", _("[{script_name}] 「{rule_name}」沒有執行:{ex}", script_name=d.get('script_name'), rule_name=d.get('rule_name'), ex=ex), why=ex)
            elif d.get("done"):
                inc["_exec"][key] = ex
        for sid in inc["watch"]:                          # the states the urgent rules read
            v = ((st or {}).get(sid) or {}).get("value") if st else _("(沒有畫面)")
            if sid not in inc["_last"] or inc["_last"][sid] != v:
                if sid in inc["_last"]:
                    self._add(inc, now, "state", "", sid=sid, value=v)
                inc["_last"][sid] = v
        snap = {"proc": " › ".join(c["sub"] for c in (proc or {}).get("chain", [])) or None, "held": held,
                "situations": {k: v.get("name") for k, v in (situations or {}).items()}}
        old = inc["_snap"]
        if old:
            if old.get("proc") != snap["proc"]:
                self._add(inc, now, "proc", _("子腳本開始:{proc}", proc=snap['proc']) if snap["proc"] else _("子腳本結束:{proc}", proc=old.get('proc')))
            if old.get("held") != snap["held"]:
                self._add(inc, now, "hold", _("守門規則「{held}」暫停其他腳本", held=snap['held']) if snap["held"] else _("其他腳本恢復"))
            for k, v in snap["situations"].items():
                if old.get("situations", {}).get(k) not in (None, v):
                    self._add(inc, now, "situation", _("情境:{p1} → {v}", p1=old['situations'][k], v=v))
        inc["_snap"] = snap
        if frame is not None and now - inc["start"] <= CLIP_AFTER and now - inc["_clip_t"] >= CLIP_EVERY:
            name = f"{int(now * 1000)}.jpg"
            if _write_clip(inc["_dir"], [(now, _small(frame))]):
                inc["clip"].append([round(now, 3), name])
            inc["_clip_t"] = now
        if frame is not None and now - inc["_frame_t"] >= FRAME_EVERY:
            self._add(inc, now, "frame", "", frame=frame)
        if urg:
            inc["_miss"] = None
        elif inc["_miss"] is None:
            inc["_miss"] = now
        elif inc["_resolved"] is None and now - inc["_miss"] >= RESOLVE_AFTER:
            inc["_resolved"] = now
            self._add(inc, now, "resolved", _("緊急規則不再成立,繼續觀察 {TAIL} 秒", TAIL=TAIL), frame=frame, force=True)
        elif inc["_resolved"] is not None and now - inc["_resolved"] >= TAIL:
            self.close(n, now, "resolved", frame)
            return
        if now - inc["start"] >= MAX_SECONDS:
            self.close(n, now, "timeout", frame)
            return
        if now - inc["_saved"] >= SAVE_EVERY:
            self._save(inc, now)

    def close(self, n, now, status, frame=None):
        inc = self.open.pop(n, None)
        if not inc:
            return
        inc["status"], inc["end"] = status, round(now, 3)
        why = {"resolved": _("緊急規則已經 {TAIL} 秒沒有成立", TAIL=TAIL), "timeout": _("超過 {p1} 分鐘還在成立,停止追蹤", p1=MAX_SECONDS // 60),
               "stopped": _("腳本執行停止了")}.get(status, status)
        self._add(inc, now, "end", _("結束:{why}", why=why), frame=frame, force=True)
        self._save(inc, now)
        if self.on_event and status != "stopped":
            names = _("、").join(dict.fromkeys(t.get("rule_name") or "" for t in inc["triggers"]))
            self.on_event("urgent_end", n, _("「{names}」{why}(共 {p3} 分鐘)", names=names, why=why, p3=round((now - inc['start']) / 60)), None, now)

    def close_all(self, now):
        for n in list(self.open):
            self.close(n, now, "stopped")

    # ---------- storage ----------
    def _add(self, inc, now, kind, text, frame=None, force=False, **extra):
        e = {"t": round(now, 3), "kind": kind, "text": text, **extra}
        if frame is not None and inc["frames"] < MAX_FRAMES and (force or now - inc["_frame_t"] >= FRAME_GAP):
            name = f"{int(now * 1000)}.jpg"
            try:
                Image.fromarray(frame).resize((960, 540), Image.BILINEAR).save(os.path.join(inc["_dir"], name), quality=85)
                e["frame"] = name
                inc["frames"] += 1
                inc["_frame_t"] = now
            except (OSError, ValueError):
                pass
        if kind == "frame" and "frame" not in e:
            return
        inc["entries"].append(e)

    def _save(self, inc, now):
        inc["_saved"] = now
        out = {k: v for k, v in inc.items() if not k.startswith("_")}
        p = os.path.join(inc["_dir"], "incident.json")
        try:
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, default=str)
            os.replace(p + ".tmp", p)
        except OSError:
            pass

    def status(self):
        return [{"id": i["id"], "device": n, "start": i["start"], "triggers": [t["rule_name"] for t in i["triggers"]],
                 "resolved": i["_resolved"]} for n, i in self.open.items()]


def _write_clip(folder, frames):
    """[(t, small frame)] -> clip/<ms>.jpg; True if all were written"""
    ok = True
    for t, f in frames:
        try:
            Image.fromarray(f).save(os.path.join(folder, "clip", f"{int(t * 1000)}.jpg"), quality=75)
        except (OSError, ValueError):
            ok = False
    return ok
