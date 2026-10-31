"""The live workbench's draft (草稿): new and changed things over the design, judged on the screen before anything is saved.

Nothing here changes the design until it is applied: <runtime>/wb/_draft/draft.json with the pictures it was made on

  {"buttons": [{"button": {...}, "frame": picture}], "states": [a whole state, new or changed],
   "refs": [{"state", "value", "frame", "box"}],    a new reference picture for a state's rule
   "answers": [{"state", "value", "frame"}],        "this picture is really ...": a test question
   "subs": [a whole sub-script, new or changed], "rules": [{"script", "situation", "rule", "first"}]}

Applying goes through the same saves as the other pages (same checks, new versions), in the order things depend on each
other; anything refused and all of it goes back. What an apply did is kept (<runtime>/wb/_applied/<id>.json) to undo it."""
import base64
import datetime
import json
import os
import re
import shutil
import threading
import time

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

import atomic
import project
import schema as schema_mod
from automation import buttons as buttons_mod
from i18n import _
from labeler import generic

from . import DATA_ROOT, RUNTIME_DIR
from .workbench import _dir, _frame_path, _grab, _runner_sees, find_buttons, load_frame

router = APIRouter()
NEAR = 28                       # a point this close to a button is that button
EMPTY = {"buttons": [], "states": [], "refs": [], "answers": [], "subs": [], "rules": []}
_lock = threading.RLock()


# ---------------------------------------------------------------- what is at this spot already
class At(BaseModel):
    device: str
    frame: str
    box: list[int]              # [x, y, w, h]; w = h = 0: a point


def _overlap(a, b):
    """How much of the smaller of two boxes the other covers (0..1)."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h) / max(1, min(a[2] * a[3], b[2] * b[3]))


def dominant_color(crop):
    """The colour that stands out in a picture as a rule's HSV range, and how much of it is that colour."""
    hsv = np.asarray(Image.fromarray(crop).convert("HSV"), dtype=np.int16)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vivid = (s >= 60) & (v >= 60)
    if vivid.mean() < 0.02:                              # no colour to speak of: bright (white text) or nothing
        if (v >= 170).mean() < 0.02:
            return None, 0.0
        c = {"h": [0, 255], "s": [0, 80], "v": [150, 255]}
    else:
        hist = np.bincount(h[vivid].ravel().astype(int), minlength=256).astype(float)
        hist = np.convolve(np.r_[hist[-8:], hist, hist[:8]], np.ones(17), "valid")[:256]
        mid = int(hist.argmax())
        c = {"h": [(mid - 14) % 256, (mid + 14) % 256], "s": [60, 255], "v": [60, 255]}
    return c, float(generic.color_mask(hsv, [c]).mean())


def spot(img, box, states, buttons):
    """What the design already has at this spot, nearest first; and what the picture there looks like."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    near = []
    for b in buttons:
        if b.get("find") and b.get("found") is False:
            continue                                     # its picture is not on this screen
        bx, by = b["at"] if b.get("at") else (b["x"], b["y"])
        inside = w and h and x <= bx <= x + w and y <= by <= y + h
        d = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
        if inside or d <= NEAR:
            near.append({"id": b["id"], "label": b["label"], "dist": round(d), "find": bool(b.get("find")), "x": bx, "y": by})
    near.sort(key=lambda r: r["dist"])
    over = []
    me = [x, y, max(w, 1), max(h, 1)]
    for s in states:
        for r in s.get("rois") or []:
            o = _overlap(me, r["box"])
            if o >= (0.5 if w and h else 1):
                over.append({"state": s["id"], "name": s.get("name"), "roi": r["id"], "box": r["box"], "overlap": round(o, 2)})
    over.sort(key=lambda r: -r["overlap"])
    out = {"buttons": near, "states": over}
    if w >= 4 and h >= 4:
        c, ratio = dominant_color(img[y:y + h, x:x + w])
        out.update(color=c, ratio=round(ratio, 3), looks="bar" if w >= 5 * h and ratio >= 0.2 else "picture")
    return out


# ---------------------------------------------------------------- the draft
def _draft_dir():
    return os.path.join(RUNTIME_DIR, "wb", "_draft")


def draft_load():
    try:
        with open(os.path.join(_draft_dir(), "draft.json"), encoding="utf-8") as f:
            return {**EMPTY, **json.load(f)}
    except (OSError, ValueError):
        return json.loads(json.dumps(EMPTY))


def draft_save(doc):
    os.makedirs(_draft_dir(), exist_ok=True)
    atomic.write_json(os.path.join(_draft_dir(), "draft.json"), doc)


def keep_frame(device, fid):
    """The draft keeps its own copy of a picture (the kept ones get replaced). -> its name"""
    name = f"{device}__{fid}.png"
    out = os.path.join(_draft_dir(), name)
    if not os.path.exists(out):
        p = _frame_path(device, fid)
        if not os.path.exists(p):
            raise HTTPException(404, _("這張畫面已經不在了,請重新凍結"))
        os.makedirs(_draft_dir(), exist_ok=True)
        shutil.copyfile(p, out)
    return name


def draft_image(name):
    p = os.path.join(_draft_dir(), os.path.basename(name))
    if not os.path.exists(p):
        raise ValueError(_("草稿用的畫面不見了:{name}", name=name))
    return np.asarray(Image.open(p).convert("RGB"))


def merged_states(doc=None):
    """The design's states with the draft's over them (a changed one in place, new ones after)."""
    doc = draft_load() if doc is None else doc
    mine = {s["id"]: s for s in doc["states"]}
    out = [mine.pop(s["id"], s) for s in schema_mod.load(DATA_ROOT)["states"]]
    return out + list(mine.values())


def _templates(state, doc):
    """A rule's reference pictures: the design's and the draft's new ones."""
    tpls = generic.load_templates(DATA_ROOT, state)
    params = state["source"].get("params") or {}
    box = next((r["box"] for r in state.get("rois") or [] if r["id"] == params.get("roi")), None)
    for r in doc["refs"]:
        if r["state"] == state["id"] and state["source"].get("rule") == "template" and box:
            x, y, w, h = r["box"]
            im = Image.fromarray(draft_image(r["frame"])[y:y + h, x:x + w]).resize((box[2], box[3]), Image.BILINEAR)
            tpls.append((r["value"], generic.feature(np.asarray(im), params.get("feature", "gray"))))
    return tpls


def read_with_draft(img, sees=None, doc=None):
    """What each state, new or changed or as it is, says on a picture. A screen rule on this very picture (later ones may
    gate on earlier ones, as when labelling); a state a model answers as the runner said."""
    doc = draft_load() if doc is None else doc
    told = (sees or {}).get("state") or {}
    ctx = {k: (v or {}).get("value") for k, v in told.items()}
    changed = {s["id"] for s in doc["states"]} | {r["state"] for r in doc["refs"]}
    out = {}
    for s in merged_states(doc):
        if generic.is_generic(s) and s.get("type") in ("class", "number", "ratio"):
            try:
                v, sc = generic.evaluate(s, img, _templates(s, doc), ctx)
                ctx[s["id"]] = v
                out[s["id"]] = {"value": v, "source": "rule", **{k: x for k, x in sc.items() if k in ("ratio", "scores", "text", "gated")}}
            except Exception as e:                        # noqa: BLE001 - an unfinished draft must not hide the others
                out[s["id"]] = {"value": None, "source": "rule", "error": str(e)}
        elif s["id"] in told:
            out[s["id"]] = {**told[s["id"]], "source": "runner"}
        else:
            out[s["id"]] = {"value": None, "source": "none"}
        if s["id"] in changed:
            out[s["id"]]["draft"] = True
    return out


def new_id(name, taken, prefix):
    """A code for something a person named (in any language)."""
    slug = re.sub(r"[^a-z0-9_]+", "_", (name or "").lower()).strip("_")
    base = slug if re.fullmatch(r"[a-z][a-z0-9_]*", slug) else prefix
    if base != prefix and base not in taken:
        return base
    n = 1
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


class NewState(BaseModel):
    device: str
    frame: str
    box: list[int]
    name: str
    kind: str                   # template | color | bar | digits


def make_state(req, img, taken):
    """A new state from a box on a picture: enough to judge that very picture."""
    x, y, w, h = req.box
    state = {"id": new_id(req.name, taken, "state"), "name": req.name.strip(), "type": "class", "description": "",
             "rois": [{"id": "main", "name": _("範圍"), "box": [int(v) for v in req.box]}],
             "source": {"kind": "rule"}, "review": {"enabled": False, "roi": "main", "scale": 1}}
    yes_no = [{"value": "yes", "name": _("有"), "color": "green", "key": "1"}, {"value": "no", "name": _("沒有"), "color": "stone", "key": "2"}]
    color, ratio = dominant_color(img[y:y + h, x:x + w])
    if req.kind == "template":
        state["classes"] = yes_no
        state["source"].update(rule="template", params={"roi": "main", "feature": "gray", "match_min": 0.7, "margin": 0.05, "search": 3, "fallback": "no"})
    elif req.kind == "color":
        if not color:
            raise HTTPException(400, _("這塊看不出明顯的顏色,換一塊框,或改用「圖片比對」"))
        state["classes"] = yes_no
        state["source"].update(rule="color_ratio", params={"roi": "main", "colors": [color], "high_value": "yes", "high_min": round(max(0.02, ratio * 0.6), 3),
                                                           "low_value": "no", "low_max": round(ratio * 0.2, 3)})
    elif req.kind == "bar":
        state["type"] = "ratio"
        state["source"].update(rule="bar", params={"roi": "main", "dir": "right", "fill": "auto", "slant": 0})
    elif req.kind == "digits":
        if not color:
            raise HTTPException(400, _("這塊看不出數字的顏色,換一塊框"))
        state["type"] = "number"
        state["source"].update(rule="digits", params={"roi": "main", "colors": [color], "part": "all", "match_min": 0.6})
    else:
        raise HTTPException(400, _("不支援的狀態種類"))
    return state


def _uses(doc, key, value):
    """Does this document (a script, a sub-script) use this value under this key, anywhere?"""
    if isinstance(doc, dict):
        return doc.get(key) == value or any(_uses(v, key, value) for v in doc.values())
    if isinstance(doc, list):
        return any(_uses(v, key, value) for v in doc)
    return False


def impact(doc):
    """What already uses what this draft changes: [{"what", "users": [...]}]. New things have no users."""
    import automation
    from automation import subs as subs_mod
    scripts = automation.load_all(DATA_ROOT)
    lib = subs_mod.load_all(DATA_ROOT)
    have_states = {s["id"] for s in schema_mod.load(DATA_ROOT)["states"]}
    have_buttons = buttons_mod.load(DATA_ROOT)

    def users(key, value):
        return [_("主腳本「{name}」", name=s.get("name")) for s in scripts if _uses(s, key, value)] + \
               [_("子腳本「{name}」", name=s.get("name")) for s in lib.values() if _uses(s, key, value)]
    out = []
    for s in doc["states"]:
        if s["id"] in have_states:
            out.append({"what": _("狀態「{name}」", name=s.get("name")), "users": users("state", s["id"])})
    for sid in sorted({r["state"] for r in doc["refs"]} - {s["id"] for s in doc["states"]}):
        if sid in have_states:
            name = next((x["name"] for x in merged_states(doc) if x["id"] == sid), sid)
            out.append({"what": _("狀態「{name}」的參考圖", name=name), "users": users("state", sid)})
    for row in doc["buttons"]:
        b = row["button"]
        if b["id"] in have_buttons:
            out.append({"what": _("按鈕「{name}」", name=b.get("label")), "users": users("button", b["id"])})
    for sub in doc["subs"]:
        if sub["id"] in lib:
            out.append({"what": _("子腳本「{name}」", name=sub.get("name")), "users": users("sub", sub["id"])})
    return out


def problems(doc):
    """What can be told before applying (the rest shows when it is applied, and then nothing is left changed)."""
    out = []
    try:
        schema_mod.validate({"states": merged_states(doc)})
    except ValueError as e:
        out.append(str(e))
    for s in doc["states"]:
        if generic.is_generic(s):
            try:
                generic.validate(s)
            except ValueError as e:
                out.append(str(e))
    return out


def live_devices(script):
    """Where this main script really acts."""
    import automation
    return sorted(d for d in (script.get("devices") or {}) if d != "*" and not d.startswith("#") and automation.mode_for(script, d) == "live")


class DraftDoc(BaseModel):
    doc: dict


class KeepFrame(BaseModel):
    device: str
    frame: str


@router.get("/api/wb/draft")
def draft_read():
    import automation
    doc = draft_load()
    scripts = {s["id"]: s for s in automation.load_all(DATA_ROOT)}
    return {"doc": doc, "problems": problems(doc), "impact": impact(doc),
            "live": {r["script"]: live_devices(scripts[r["script"]]) for r in doc["rules"] if r["script"] in scripts}}


@router.post("/api/wb/draft")
def draft_write(req: DraftDoc):
    with _lock:
        doc = {**EMPTY, **req.doc}
        draft_save(doc)
    return {"problems": problems(doc), "impact": impact(doc)}


@router.post("/api/wb/draft/keep")
def draft_keep(req: KeepFrame):
    return {"frame": keep_frame(os.path.basename(req.device), req.frame)}


@router.get("/api/wb/draft/image/{name}")
def draft_image_file(name: str):
    p = os.path.join(_draft_dir(), os.path.basename(name))
    if not os.path.exists(p):
        raise HTTPException(404, _("沒有這張畫面"))
    return FileResponse(p)


@router.post("/api/wb/at")
def what_is_here(req: At):
    device = os.path.basename(req.device)
    img = load_frame(device, req.frame)
    return spot(img, req.box, merged_states(), find_buttons(img, device))


@router.post("/api/wb/draft/state")
def draft_new_state(req: NewState):
    """A new state from a box on a kept picture, into the draft; a picture rule keeps this box as what "yes" looks like."""
    device = os.path.basename(req.device)
    if not req.name.strip():
        raise HTTPException(400, _("請替狀態取個名字"))
    if req.box[2] < 4 or req.box[3] < 4:
        raise HTTPException(400, _("請在畫面上框出一塊"))
    img = load_frame(device, req.frame)
    with _lock:
        doc = draft_load()
        state = make_state(req, img, {s["id"] for s in merged_states(doc)})
        doc["states"].append(state)
        if req.kind == "template":
            doc["refs"].append({"state": state["id"], "value": "yes", "frame": keep_frame(device, req.frame), "box": [int(v) for v in req.box]})
        draft_save(doc)
    return {"state": state, "doc": doc}


@router.post("/api/wb/draft/read")
def draft_read_frame(req: KeepFrame):
    """A kept picture read with the draft over the design."""
    device = os.path.basename(req.device)
    img = load_frame(device, req.frame)
    try:
        with open(os.path.join(_dir(device), req.frame + ".json"), encoding="utf-8") as f:
            sees = json.load(f).get("runner")
    except (OSError, ValueError):
        sees = None
    return {"states": read_with_draft(img, sees)}


@router.get("/api/wb/draft/live/{device}")
def draft_read_live(device: str):
    """The screen now read with the draft: asked for only while the page is open and has a draft."""
    device = os.path.basename(device)
    return {"states": read_with_draft(_grab(device), _runner_sees(device))}


@router.post("/api/wb/draft/try")
def draft_try():
    """The draft's states on pictures from the recordings: how often each says what (does it hold across many pictures?)."""
    from .app import _load_rgb, frames_random
    doc = draft_load()
    frames = frames_random(24, 0)
    out = []
    for s in doc["states"]:
        if not (generic.is_generic(s) and s.get("type") in ("class", "number", "ratio")):
            continue
        tpls = _templates(s, doc)
        counts, unsure = {}, 0
        for f in frames:
            try:
                v, _sc = generic.evaluate(s, _load_rgb(f), tpls, None)
            except Exception:                             # noqa: BLE001 - counted as unsure
                v = None
            if v is None:
                unsure += 1
            else:
                k = str(round(v, 1) if isinstance(v, float) else v)
                counts[k] = counts.get(k, 0) + 1
        out.append({"state": s["id"], "name": s.get("name"), "counts": counts, "unsure": unsure})
    return {"items": out, "frames": len(frames)}


class DraftWhy(BaseModel):
    device: str
    frame: str | None = None    # a kept picture; none = the screen now


@router.post("/api/wb/draft/why")
def draft_why(req: DraftWhy):
    """Each rule of each main script on this device with the draft over the design: new rules are judged too, but only
    judged - nothing acts."""
    import automation
    from .ai_api import Explain, explain
    device = os.path.basename(req.device)
    doc = draft_load()
    sees = _runner_sees(device)
    if req.frame:
        img = load_frame(device, req.frame)
        try:
            with open(os.path.join(_dir(device), req.frame + ".json"), encoding="utf-8") as f:
                sees = json.load(f).get("runner") or {}
        except (OSError, ValueError):
            sees = {}
    else:
        img = _grab(device)
    state = {k: v for k, v in read_with_draft(img, sees, doc).items() if v.get("source") != "none"}
    new_rules = {}
    for r in doc["rules"]:
        new_rules.setdefault(r["script"], []).append(r)
    out = []
    for sc in automation.load_all(DATA_ROOT):
        if not (sc.get("enabled", True) and automation.mode_for(sc, device) != "off") and sc["id"] not in new_rules:
            continue
        sc = json.loads(json.dumps(sc))
        ids = set()
        for r in new_rules.get(sc["id"], []):
            sit = next((x for x in sc["situations"] if x["id"] == r["situation"]), None)
            if sit:
                sit.setdefault("rules", []).insert(0, {**r["rule"], "enabled": True})
                ids.add(r["rule"]["id"])
        try:
            got = explain(Explain(script=sc, device=device, state=state))["devices"][0]
        except HTTPException:
            continue
        for row in got["rules_in_order"]:
            if row["rule"] in ids:
                row["draft"] = True
        out.append({"script": sc["id"], "name": sc.get("name"), **got})
    return {"items": out, "running": bool(sees.get("running"))}


# ---------------------------------------------------------------- apply: all of it or nothing; undo: all of it
def _applied_dir():
    return os.path.join(RUNTIME_DIR, "wb", "_applied")


def keep_as_sample(frame):
    """A draft's picture as a sample of the session workbench_<date>: it can then be answered and trained on like any
    recording, and a reference picture remembers where it came from. -> its path in the work folder"""
    device, fid = os.path.basename(frame)[:-4].rsplit("__", 1)
    session = f"workbench_{datetime.datetime.now():%Y%m%d}"
    work = project.work_of(DATA_ROOT)
    ddir = os.path.join(work, "sessions", session, "devices", device)
    os.makedirs(os.path.join(ddir, "frames"), exist_ok=True)
    out = os.path.join(ddir, "frames", fid + ".png")
    if not os.path.exists(out):
        shutil.copyfile(os.path.join(_draft_dir(), os.path.basename(frame)), out)
        with open(os.path.join(ddir, "samples.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": fid, "session": session, "device": device, "trigger": "workbench", "t_req": int(fid) / 1000,
                                "t_done": int(fid) / 1000, "frame": f"frames/{fid}.png", "capture": "window"}, ensure_ascii=False) + "\n")
        sp = os.path.join(work, "sessions", session, "session.json")
        try:
            with open(sp, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {"session": session, "started": time.time(), "devices": {}}
        meta["ended"] = time.time()
        meta["devices"].setdefault(device, {"samples": 0, "touches": 0, "events": 0})["samples"] += 1
        atomic.write_json(sp, meta)
    return f"sessions/{session}/devices/{device}/frames/{fid}.png"


def _bare(doc):
    return {k: v for k, v in doc.items() if k not in ("version", "created", "note", "format", "settings_only")}


def undo_steps(did, note):
    """Put back what these steps changed, the last first. -> what could not be put back"""
    import automation
    from automation import subs as subs_mod
    from . import review
    failed = []
    for d in reversed(did):
        try:
            k = d["kind"]
            if k == "button":
                if d["before"] is None:
                    buttons_mod.delete(DATA_ROOT, d["id"])
                else:
                    buttons_mod.save(DATA_ROOT, d["before"])
                    if d.get("image"):
                        with open(buttons_mod.image_path(DATA_ROOT, d["id"]), "wb") as f:
                            f.write(base64.b64decode(d["image"]))
            elif k == "states":
                schema_mod.save(DATA_ROOT, {"states": schema_mod.load(DATA_ROOT, d["version"])["states"]}, note)
            elif k == "ref":
                generic.tpl_delete(DATA_ROOT, d["state"], d["name"])
            elif k == "answer":
                review.answer_one(d["frame"], d["state"], d["before"])
            elif k == "sub":
                if d["before"] is None:
                    subs_mod.delete(DATA_ROOT, d["id"])
                else:
                    subs_mod.save(DATA_ROOT, d["before"], note)
            elif k == "script":
                automation.save(DATA_ROOT, d["before"], note)
        except Exception as e:                            # noqa: BLE001 - the others still go back; said on the page
            failed.append(f"{d['kind']} {d.get('id', '')}: {e}")
    return failed


def apply_draft(doc, note, enable_rules=False):
    """The draft into the design. Anything refused: all of it goes back (ValueError says why)."""
    import automation
    from automation import subs as subs_mod
    from . import review
    did = []
    label = note or _("即時工作台")
    try:
        for row in doc["buttons"]:
            b = row["button"]
            before = buttons_mod.load(DATA_ROOT).get(b["id"])
            image = None
            if before and before.get("find") and os.path.exists(buttons_mod.image_path(DATA_ROOT, b["id"])):
                with open(buttons_mod.image_path(DATA_ROOT, b["id"]), "rb") as f:
                    image = base64.b64encode(f.read()).decode()
            buttons_mod.save(DATA_ROOT, b, draft_image(row["frame"]) if row.get("frame") else None)
            did.append({"kind": "button", "id": b["id"], "before": before, "image": image})
        if doc["states"]:
            version = schema_mod.load(DATA_ROOT)["version"]
            for s in doc["states"]:
                if generic.is_generic(s):
                    generic.validate(s)
            schema_mod.save(DATA_ROOT, {"states": merged_states(doc)}, label)
            did.append({"kind": "states", "version": version})
        for r in doc["refs"]:
            name = generic.tpl_add(DATA_ROOT, r["state"], r["value"], draft_image(r["frame"]), r["box"], keep_as_sample(r["frame"]))
            did.append({"kind": "ref", "state": r["state"], "name": name})
        for a in doc["answers"]:
            rel = keep_as_sample(a["frame"])
            before = ((review.decisions().get(rel) or {}).get("answers") or {}).get(a["state"])
            review.answer_one(rel, a["state"], a["value"])
            did.append({"kind": "answer", "frame": rel, "state": a["state"], "before": before})
        lib = subs_mod.load_all(DATA_ROOT)
        for sub in doc["subs"]:
            before = lib.get(sub["id"])
            subs_mod.save(DATA_ROOT, sub, label)
            did.append({"kind": "sub", "id": sub["id"], "before": _bare(before) if before else None})
        for sid in dict.fromkeys(r["script"] for r in doc["rules"]):
            sc = next((s for s in automation.load_all(DATA_ROOT) if s["id"] == sid), None)
            if not sc:
                raise ValueError(_("找不到這個主腳本:{id}", id=sid))
            before = _bare(sc)
            sc = json.loads(json.dumps(before))
            for r in doc["rules"]:
                if r["script"] != sid:
                    continue
                sit = next((x for x in sc["situations"] if x["id"] == r["situation"]), None)
                if not sit:
                    raise ValueError(_("主腳本「{name}」沒有這個情境", name=sc.get("name")))
                sit.setdefault("rules", [])
                sit["rules"].insert(0 if r.get("first") else len(sit["rules"]), {**r["rule"], "enabled": bool(enable_rules)})
            automation.save(DATA_ROOT, sc, label)
            did.append({"kind": "script", "id": sid, "before": before})
    except Exception as e:                                # noqa: BLE001 - refused or not: nothing stays half done
        failed = undo_steps(did, _("套用失敗,退回"))
        raise ValueError(str(e) + ("  " + "; ".join(failed) if failed else "")) from None
    return did


class Apply(BaseModel):
    note: str = ""
    enable_rules: bool = False  # a new rule of a main script: on at once, or saved off until a person turns it on


@router.post("/api/wb/draft/apply")
def draft_apply(req: Apply):
    with _lock:
        doc = draft_load()
        bad = problems(doc)
        if bad:
            raise HTTPException(400, bad[0])
        if not any(doc[k] for k in EMPTY):
            raise HTTPException(400, _("草稿是空的"))
        try:
            did = apply_draft(doc, req.note, req.enable_rules)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        rid = str(int(time.time() * 1000))
        counts = {k: len(doc[k]) for k in EMPTY if doc[k]}
        os.makedirs(_applied_dir(), exist_ok=True)
        atomic.write_json(os.path.join(_applied_dir(), rid + ".json"), {"id": rid, "t": time.time(), "note": req.note, "counts": counts, "did": did})
        draft_save(json.loads(json.dumps(EMPTY)))
    return {"id": rid, "counts": counts}


@router.get("/api/wb/applied")
def applied():
    d = _applied_dir()
    rows = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d), reverse=True)[:20]:
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    r = json.load(fh)
                rows.append({k: r.get(k) for k in ("id", "t", "note", "counts", "undone")})
            except (OSError, ValueError):
                pass
    return {"items": rows}


@router.post("/api/wb/applied/{rid}/undo")
def applied_undo(rid: str):
    p = os.path.join(_applied_dir(), os.path.basename(rid) + ".json")
    try:
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(404, _("找不到這次套用")) from None
    if r.get("undone"):
        raise HTTPException(400, _("這次套用已經退回過了"))
    failed = undo_steps(r["did"], _("退回工作台的套用"))
    r["undone"] = time.time()
    atomic.write_json(p, r)
    return {"failed": failed}
