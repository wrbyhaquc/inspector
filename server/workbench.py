"""The live workbench (即時工作台): look at a device's screen now and see what the design makes of it - the states' regions
and what they read, the buttons and where they are found, why each rule holds or not.

The pictures are taken here, one at a time and only while the page asks (the driver's capture, so it also works with the
runner off): the runner does no extra work per frame. A frozen picture is kept in <runtime>/wb/<device>/<id>.png with what
the runner saw right after it (<id>.json); the newest KEEP of each device stay.

The draft over the design and teaching a job: wb_draft.py, wb_teach.py."""
import io
import json
import os
import threading
import time

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

import atomic
import drivers
from automation import buttons as buttons_mod
from i18n import _

from . import DATA_ROOT, RUNTIME_DIR

router = APIRouter()
KEEP = 12                       # frozen pictures kept per device
LIVE_MIN_S = 0.8                # a picture is taken at most this often, however many pages ask
LIVE_WIDTH = 960
RUNNER_FRESH_S = 10             # the runner's status is newer than this: it is running
WAIT_RUNNER_S = 3               # how long a frozen picture waits for what the runner sees next

_caps, _live, _guard = {}, {}, threading.Lock()


def _lock(device):
    with _guard:
        return _caps.setdefault(device, {"lock": threading.Lock(), "cap": None})["lock"]


def _grab(device):
    """One picture of a source now, in the project's coordinate space (RGB array)."""
    with _lock(device):
        slot = _caps[device]
        try:
            if slot["cap"] is None:
                slot["cap"] = drivers.current(DATA_ROOT).capture(device, prefer="window", fallback=True)
            got = slot["cap"].grab()
        except Exception as e:                            # noqa: BLE001 - any driver: said on the page
            slot["cap"] = None
            raise HTTPException(400, _("拿不到這個來源的畫面:{e}", e=e)) from None
    if got is None:
        slot["cap"] = None
        raise HTTPException(400, _("拿不到這個來源的畫面(視窗可能縮到最小,或還沒開)"))
    return got[0]


def _status():
    try:
        with open(os.path.join(RUNTIME_DIR, "status.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _runner_sees(device, st=None):
    """What the runner says about this device now; {"running": False} when it is off."""
    st = _status() if st is None else st
    if not st.get("running") or time.time() - (st.get("updated") or 0) > RUNNER_FRESH_S:
        return {"running": False}
    d = next((x for x in st.get("devices") or [] if x.get("name") == device), None)
    if d is None:
        return {"running": True, "here": False}
    return {"running": True, "here": True, "updated": st.get("updated"), "hold_all": st.get("hold_all"),
            **{k: d.get(k) for k in ("state", "decisions", "situations", "hold", "proc", "manual")}}


def _dir(device):
    return os.path.join(RUNTIME_DIR, "wb", os.path.basename(device))


def _frame_path(device, fid):
    if not fid.isdigit():
        raise HTTPException(404, _("沒有這張畫面"))
    return os.path.join(_dir(device), f"{fid}.png")


def freeze(device, frame=None):
    """Keep one picture of a device with what the runner saw right after it. -> what the page gets."""
    img = _grab(device) if frame is None else frame
    t = time.time()
    fid = str(int(t * 1000))
    d = _dir(device)
    os.makedirs(d, exist_ok=True)
    Image.fromarray(img).save(os.path.join(d, fid + ".png"), compress_level=1)
    sees = _runner_sees(device)
    while sees.get("here") and (sees.get("updated") or 0) < t and time.time() - t < WAIT_RUNNER_S:
        time.sleep(0.1)                                   # what it judged on a picture no older than this one
        sees = _runner_sees(device)
    row = {"id": fid, "device": device, "t": t, "runner": sees}
    atomic.write_json(os.path.join(d, fid + ".json"), row)
    kept = sorted((f[:-4] for f in os.listdir(d) if f.endswith(".png")), key=int)
    for old in kept[:-KEEP]:
        for ext in (".png", ".json"):
            try:
                os.remove(os.path.join(d, old + ext))
            except OSError:
                pass
    return row


def load_frame(device, fid):
    """A kept picture as an RGB array (404 when it has been replaced by newer ones)."""
    p = _frame_path(device, fid)
    if not os.path.exists(p):
        raise HTTPException(404, _("這張畫面已經不在了,請重新凍結"))
    return np.asarray(Image.open(p).convert("RGB"))


def find_buttons(img, device=None):
    """Where the buttons are on a picture (a list's names only for the device they belong to: there can be many)."""
    out = []
    for b in buttons_mod.load(DATA_ROOT).values():
        if b.get("list"):
            continue
        row = {"id": b["id"], "label": b["label"], "x": b["x"], "y": b["y"], "find": bool(b.get("find")), "box": b.get("box"), "group": b.get("group")}
        if b.get("find"):
            (x, y), score = buttons_mod.locate(b, img, DATA_ROOT)
            row.update(found=x is not None, at=[x, y] if x is not None else None, score=score)
        out.append(row)
    return out


# ---------------------------------------------------------------- the pages
class Grab(BaseModel):
    device: str


@router.get("/api/wb/live/{device}")
def live(device: str):
    """The screen now, for the page's live view (smaller, and taken at most every LIVE_MIN_S)."""
    device = os.path.basename(device)
    hit = _live.get(device)
    if hit and time.time() - hit[0] < LIVE_MIN_S:
        return Response(hit[1], media_type="image/jpeg", headers={"Cache-Control": "no-store"})
    img = Image.fromarray(_grab(device))
    if img.width > LIVE_WIDTH:
        img = img.resize((LIVE_WIDTH, round(img.height * LIVE_WIDTH / img.width)), Image.BILINEAR)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=75)
    _live[device] = (time.time(), b.getvalue())
    return Response(b.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/api/wb/sees/{device}")
def sees(device: str):
    return _runner_sees(os.path.basename(device))


@router.post("/api/wb/freeze")
def freeze_now(req: Grab):
    return freeze(os.path.basename(req.device))


@router.get("/api/wb/frames/{device}")
def frames(device: str):
    """The kept pictures of a device, newest first."""
    d = _dir(os.path.basename(device))
    if not os.path.isdir(d):
        return {"items": []}
    ids = sorted((f[:-4] for f in os.listdir(d) if f.endswith(".png")), key=int, reverse=True)
    return {"items": [{"id": i, "t": int(i) / 1000} for i in ids]}


@router.get("/api/wb/frames/{device}/{fid}/image")
def frame_image(device: str, fid: str):
    p = _frame_path(os.path.basename(device), fid)
    if not os.path.exists(p):
        raise HTTPException(404, _("這張畫面已經不在了,請重新凍結"))
    return FileResponse(p, headers={"Cache-Control": "max-age=3600"})


@router.get("/api/wb/frames/{device}/{fid}")
def frame_read(device: str, fid: str):
    """One kept picture read through the design: what each state reads on it, where the buttons are, what the runner saw."""
    device = os.path.basename(device)
    img = load_frame(device, fid)
    try:
        with open(os.path.join(_dir(device), fid + ".json"), encoding="utf-8") as f:
            row = json.load(f)
    except (OSError, ValueError):
        row = {"id": fid, "device": device, "t": int(fid) / 1000, "runner": {"running": False}}
    from .wb_draft import read_with_draft
    return {**row, "states": read_with_draft(img, row.get("runner")), "buttons": find_buttons(img, device)}
