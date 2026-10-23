"""Button library (按鈕庫): named tap positions, picked once on a frame and used by name in every script.

<data_root>/meta/buttons.json  {"buttons": [{"id", "label", "x", "y",
                                             "find": false | true,          look for the button's picture first
                                             "box": [x, y, w, h],           the picture (cut from the frame it was picked on)
                                             "search": px,                  how far around the box to look
                                             "min_score": 0..1,
                                             "feature": "gray" | "minch" | "text",  minch = darkest channel (any
                                                 background colour); text = minch minus its blur: only the strokes of
                                                 text, whatever is behind it (a name over a moving picture)
                                             "scales": [1.0, 0.75],         also look for the picture this much smaller
                                             "max_color_diff": 0..255,      also the colours must be this close (mean
                                                 difference per channel): an enabled (gold) and a disabled (grey)
                                                 button have the same shape
                                             "list": list id, "device": d}]}   a name of a list (lists.py), of one device if the list is per device
<data_root>/meta/buttons/<id>.png  the picture of a "find" button

In a runtime (project.edition()) the design is read-only: the names of lists it captures, renames or removes (each
device's accounts ...) are kept in <runtime dir>/buttons.json {"buttons": [...], "deleted": [id]} and
<runtime dir>/buttons/<id>.png, read on top of the pack's library - so a newer pack keeps them.

A target {"button": id} taps (x, y); a "find" button is first searched for in the current frame (normalised
cross-correlation, like the reference images of the states) and tapped where it is found - so it still works
when the button moved a little. Not found = the tap does not happen (a rule waits, a sub-script step fails)."""
import atomic
import json
import os
import re
import time

import numpy as np
from PIL import Image
from i18n import _

try:
    import cv2
except ImportError:                                   # the search needs OpenCV; without it a find button taps x, y
    cv2 = None

import project
from . import spec

DATA_ROOT = project.data_root()
_cache = {}


def _path(data_root):
    return os.path.join(data_root, "meta", "buttons.json")


def _img_dir(data_root):
    return os.path.join(data_root, "meta", "buttons")


def _here():
    """The runtime's own layer (folder), or None in a studio."""
    return project.runtime_dir() if project.edition() == "runtime" else None


def image_path(data_root, bid):
    """The picture of a button: the runtime's own if it has one, else the design's."""
    here = _here()
    if here:
        p = os.path.join(here, "buttons", f"{bid}.png")
        if os.path.exists(p):
            return p
    return os.path.join(_img_dir(data_root or DATA_ROOT), f"{bid}.png")


def _read_layer(here):
    try:
        with open(os.path.join(here, "buttons.json"), encoding="utf-8") as f:
            d = json.load(f)
        return {b["id"]: b for b in d.get("buttons", [])}, set(d.get("deleted") or [])
    except (OSError, ValueError):
        return {}, set()


def load(data_root=None):
    """id -> button, re-read when the file changes."""
    data_root = data_root or DATA_ROOT
    p = _path(data_root)
    here = _here()
    lp = os.path.join(here, "buttons.json") if here else None
    m = (os.path.getmtime(p) if os.path.exists(p) else 0, os.path.getmtime(lp) if lp and os.path.exists(lp) else 0)
    hit = _cache.get(data_root)
    if hit and hit[0] == m:
        return hit[1]
    bs = {}
    if m[0]:
        with open(p, encoding="utf-8") as f:
            bs = {b["id"]: b for b in json.load(f).get("buttons", [])}
    if m[1]:
        mine, gone = _read_layer(here)
        bs = {k: v for k, v in {**bs, **mine}.items() if k not in gone or k in mine}
    _cache[data_root] = (m, bs)
    return bs


def _write(data_root, buttons):
    os.makedirs(os.path.dirname(_path(data_root)), exist_ok=True)
    atomic.write_json(_path(data_root), spec.stamp({"buttons": list(buttons.values()), "saved": time.time()}),
                      ensure_ascii=False, indent=1)


def _write_layer(here, mine, gone):
    os.makedirs(here, exist_ok=True)
    p = os.path.join(here, "buttons.json")
    atomic.write_json(p, spec.stamp({"buttons": list(mine.values()), "deleted": sorted(gone), "saved": time.time()}),
                      ensure_ascii=False, indent=1)


def save(data_root, b, frame_img=None):
    """Add or change one button. frame_img (RGB array in the project's coordinate space) is needed to (re)cut the picture of a find button."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", b.get("id") or ""):
        raise ValueError(_("按鈕代號只能用小寫英文、數字、底線,且以英文開頭"))
    if not b.get("label"):
        raise ValueError(_("請替按鈕取個名稱"))
    W, H = project.screen(data_root)
    if not (isinstance(b.get("x"), int) and isinstance(b.get("y"), int) and 0 <= b["x"] < W and 0 <= b["y"] < H):
        raise ValueError(_("請在畫面上選按鈕的位置"))
    out = {k: b[k] for k in ("id", "label", "x", "y")}
    out["find"] = bool(b.get("find"))
    for k in ("group", "device", "list"):
        if b.get(k):
            out[k] = str(b[k])
    if b.get("pos") is not None:
        out["pos"] = float(b["pos"])                    # where it is in its list (lists.py)
    if b.get("missing_since"):
        out["missing_since"] = float(b["missing_since"])  # a name of a list not seen in its last walk (lists.py)
    if b.get("scales"):
        out["scales"] = [float(x) for x in b["scales"] if 0.3 <= float(x) <= 2]
        if b.get("min_score_scaled") is not None:
            out["min_score_scaled"] = float(b["min_score_scaled"])
    if b.get("max_color_diff") is not None:
        out["max_color_diff"] = float(b["max_color_diff"])
    if b.get("feature") in ("gray", "minch", "text"):
        out["feature"] = b["feature"]
    here = _here()
    if here and not out.get("list"):                  # a runtime only keeps the names of lists it walked
        raise ValueError(_("執行版只能保存清單的項目,其他按鈕要在 Studio 修改"))
    if out["find"]:
        x, y, w, h = (int(v) for v in b.get("box") or [])
        if not (8 <= w <= W and 8 <= h <= H and 0 <= x and 0 <= y and x + w <= W and y + h <= H):
            raise ValueError(_("按鈕圖片的範圍不正確"))
        out.update(box=[x, y, w, h], search=int(b.get("search", 60)), min_score=float(b.get("min_score", 0.8)))
        if not 0 <= out["search"] <= W:
            raise ValueError(_("往外找的範圍要在 0~{W} 像素", W=W))
        img_dir = os.path.join(here, "buttons") if here else _img_dir(data_root)
        os.makedirs(img_dir, exist_ok=True)
        img_path = os.path.join(img_dir, f"{out['id']}.png")
        if frame_img is not None:
            Image.fromarray(frame_img[y:y + h, x:x + w]).save(img_path)
        elif not os.path.exists(image_path(data_root, out["id"])):
            raise ValueError(_("要找圖示的按鈕需要一張畫面來截圖"))
        elif here and not os.path.exists(img_path):   # a pack's name changed here: its picture comes along
            import shutil
            shutil.copy2(image_path(data_root, out["id"]), img_path)
    bs = dict(load(data_root))
    bs[out["id"]] = {**bs.get(out["id"], {}), **out, "updated": time.time()}
    for k in ("group", "device", "list", "pos", "missing_since", "feature", "scales", "min_score_scaled", "max_color_diff"):
        if k not in out:
            bs[out["id"]].pop(k, None)
    if not out["find"]:
        for k in ("box", "search", "min_score", "feature"):
            bs[out["id"]].pop(k, None)
    if here:
        mine, gone = _read_layer(here)
        mine[out["id"]] = bs[out["id"]]
        _write_layer(here, mine, gone - {out["id"]})
    else:
        _write(data_root, bs)
    _cache.pop(data_root, None)
    return bs[out["id"]]


def delete(data_root, bid, in_use=None):
    bs = dict(load(data_root))
    if bid not in bs:
        raise ValueError(_("找不到這個按鈕"))
    if in_use:
        raise ValueError(_("還有地方在用這個按鈕:") + _("、").join(in_use))
    here = _here()
    if here:                                          # a runtime: gone here, the pack's library is not touched
        if not bs[bid].get("list"):
            raise ValueError(_("執行版只能保存清單的項目,其他按鈕要在 Studio 修改"))
        mine, gone = _read_layer(here)
        mine.pop(bid, None)
        _write_layer(here, mine, gone | {bid})
        img = os.path.join(here, "buttons", f"{bid}.png")
    else:
        del bs[bid]
        _write(data_root, bs)
        img = os.path.join(_img_dir(data_root), f"{bid}.png")
    _cache.pop(data_root, None)
    try:
        os.remove(img)
    except OSError:
        pass


_tpls = {}


def _template(data_root, b):
    p = image_path(data_root, b["id"])
    m = os.path.getmtime(p) if os.path.exists(p) else 0
    m = (m, b.get("feature"))
    hit = _tpls.get(p)
    if hit and hit[0] == m:
        return hit[1]
    t = _feature(Image.open(p).convert("RGB"), b.get("feature")) if m[0] else None
    _tpls[p] = (m, t)
    return t


def _rgb(data_root, b):
    p = image_path(data_root, b["id"])
    try:
        return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
    except OSError:
        return None


def _feature(img, kind):
    """gray, or minch: the darkest of R, G, B (white text on a red or a dark row looks the same)."""
    if kind in ("minch", "text"):
        m = np.asarray(img, dtype=np.float32).min(axis=2)
        if kind == "text" and cv2 is not None:
            m = m - cv2.GaussianBlur(m, (0, 0), 3)
        return m
    return np.asarray(img.convert("L"), dtype=np.float32)


def locate(b, frame, data_root=None):
    """-> ((x, y) to tap, score) for a find button in an RGB frame of the coordinate space; ((None, None), score) if not found."""
    data_root = data_root or DATA_ROOT
    t = _template(data_root, b)
    if t is None or cv2 is None or frame is None:
        return (b["x"], b["y"]), None
    x, y, w, h = b["box"]
    s = int(b.get("search", 60))
    x0, y0 = max(0, x - s), max(0, y - s)
    x1, y1 = min(frame.shape[1], x + w + s), min(frame.shape[0], y + h + s)
    reg = _feature(Image.fromarray(frame[y0:y1, x0:x1]), b.get("feature"))
    if reg.shape[0] < h or reg.shape[1] < w:
        return (None, None), None
    best, found = (-1.0, 0, 0, 1.0), None
    for sc in b.get("scales") or [1.0]:            # e.g. a highlighted row shows the same name smaller
        tt = t if sc == 1.0 else cv2.resize(t, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        if reg.shape[0] < tt.shape[0] or reg.shape[1] < tt.shape[1]:
            continue
        _x, score, _x, (bx, by) = cv2.minMaxLoc(cv2.matchTemplate(reg, tt, cv2.TM_CCOEFF_NORMED))
        need = float(b.get("min_score", 0.8)) if sc == 1.0 else float(b.get("min_score_scaled", b.get("min_score", 0.8)))
        if score > best[0]:
            best = (score, bx, by, sc)
        if score >= need and (found is None or score - need > found[0] - found[4]):
            found = (score, bx, by, sc, need)
    if found is None:
        return (None, None), round(float(best[0]), 3)
    score, bx, by, sc, _x = found
    if b.get("max_color_diff") is not None and sc == 1.0:   # same shape: also the same colours?
        h, w = t.shape[:2]
        rgb = _rgb(data_root, b)
        got = frame[y0 + by:y0 + by + h, x0 + bx:x0 + bx + w].astype(np.float32)
        if rgb is not None and got.shape == rgb.shape and float(np.abs(got - rgb).mean()) > float(b["max_color_diff"]):
            return (None, None), round(float(score), 3)
    # the tap point keeps its offset inside the picture (it may not be the picture's centre)
    return (x0 + bx + round((b["x"] - x) * sc), y0 + by + round((b["y"] - y) * sc)), round(float(score), 3)
