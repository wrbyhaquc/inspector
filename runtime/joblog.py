"""The record of one schedule run (排程執行紀錄): every sub-script step, notes and frames, and how it ended.

  <shadow dir>/schedules/<id>/run.json   {"id", "schedule", "schedule_name", "device", "sub", "args", "start", "end",
                                          "result", "message", "entries": [{"t", "kind", "text", "frame"?}]}
  <shadow dir>/schedules/<id>/<ms>.jpg   the start, every FRAME_EVERY seconds, failures and the end"""
import datetime
import json
import os

from PIL import Image
from i18n import _

MAX_FRAMES = 80
FRAME_EVERY = 30
SAVE_EVERY = 3


class JobLog:
    def __init__(self, root, sched, device, sub, args, now, frame=None):
        t = datetime.datetime.fromtimestamp(now)
        self.id = f"{t:%Y%m%d_%H%M%S}_{sched['id']}_{device}"
        self.dir = os.path.join(root, self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.data = {"id": self.id, "schedule": sched["id"], "schedule_name": sched.get("name"), "device": device, "sub": sub,
                     "args": args, "start": round(now, 3), "end": None, "result": None, "message": "", "frames": 0, "entries": []}
        self._frame_t, self._saved = 0.0, 0.0
        self.add(now, "start", _("排程「{name}」開始", name=sched.get('name')), frame=frame, force=True)

    @classmethod
    def reopen(cls, root, run_id, now, frame=None):
        """Carry on writing the record of a run started before the runtime restarted (None if it is gone)."""
        p = os.path.join(root, os.path.basename(run_id or ""), "run.json")
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        j = cls.__new__(cls)
        j.id, j.dir, j.data = data["id"], os.path.dirname(p), data
        j._frame_t, j._saved = 0.0, 0.0
        j.add(now, "resume", _("腳本執行重新啟動:從中斷的地方繼續"), frame=frame, force=True)
        return j

    def add(self, now, kind, text, frame=None, force=False, **extra):
        e = {"t": round(now, 3), "kind": kind, "text": text, **extra}
        if frame is not None and self.data["frames"] < MAX_FRAMES and (force or now - self._frame_t >= FRAME_EVERY):
            name = f"{int(now * 1000)}.jpg"
            try:
                Image.fromarray(frame).resize((960, 540), Image.BILINEAR).save(os.path.join(self.dir, name), quality=85)
                e["frame"] = name
                self.data["frames"] += 1
                self._frame_t = now
            except (OSError, ValueError):
                pass
        if kind == "frame" and "frame" not in e:
            return
        self.data["entries"].append(e)

    def tick(self, now, frame):
        if frame is not None and now - self._frame_t >= FRAME_EVERY:
            self.add(now, "frame", "", frame=frame)
        if now - self._saved >= SAVE_EVERY:
            self.save(now)

    def finish(self, now, result, message, frame=None):
        self.data.update(end=round(now, 3), result=result, message=message)
        text = {"success": _("完成"), "failed": _("失敗:{message}", message=message), "interrupted": _("中斷:{message}", message=message)}.get(result, result)
        self.add(now, "end", text, frame=frame, force=True)
        self.save(now)

    def save(self, now):
        self._saved = now
        p = os.path.join(self.dir, "run.json")
        try:
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, default=str)
            os.replace(p + ".tmp", p)
        except OSError:
            pass
