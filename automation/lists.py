"""Lists (清單): any scrolling list of names on the screen (accounts, places, cameras or devices),
captured once into the button library so a script can find an item by its name wherever it is in the list.

<data_root>/meta/lists.json  {"lists": [{
    "id", "title",                      e.g. "places_north", "北棟的地點"
    "group": "account" | "place" ...,    the buttons' group (what the item is)
    "per_device": bool,                 accounts differ per device; places are the same everywhere
    "anchor": {"file", "feature", "area": [x, y, w, h], "min", "gap"},
                                        a small picture every row has (an icon at the start of every row):
                                        found in "area", rows at least "gap" px apart
    "name": [dx, dy, w, h],             the name, from the anchor's top-left corner
    "swipe": {"x", "top": [from_y, to_y, times], "page": [from_y, to_y]},
                                        back to the top of the list; one step down (a little over a row: no fling)
    "ready": button id,                 must be on screen to start (the right screen / mode), with "ready_text" telling how
    "open_sub": sub-script id,          what brings the list onto the screen (run from 素材庫 before capturing)
    "select_first": bool,               the chosen row looks different (e.g. the account in use): choose two rows in turn while capturing
    "skip_red": fraction,               leave out rows with this much strong red on the name (a lock over a place not open yet)
    "match": "run"}]}                   scripts find its names by the run of rows (which()), not one picture each (lists
                                        whose chosen row is drawn smaller keep the picture)

Every name is saved as a "find" button (text-stroke comparison, also a bit smaller: a highlighted row), group / list /
device set; names already in the library are skipped. A walk that reached the end of the list also marks the names it
did not see ("missing_since": deleted or renamed in the app, or just not found) and clears the mark of those it saw:
user settings leave missing names out of what a run goes through (settings.value) until someone removes or keeps them.
Each walk is kept in <runtime dir>/list_scans.json {list id: {device or "*": {"t", "total", "new", "missing",
"complete"}}} for the pages (the operation panel's 清單 widget).

Names in a list can differ by one character only (北棟一號入口 / 北棟二號入口): one row alone can look almost as much like
another name as like its own. So rows are never told one by one: the 5~6 rows on the screen are laid over the list (the
library in list order, "pos") together, and the place where the whole run fits best wins (which()). The same is done while
capturing: a new page is laid over the end of the last one, the rows that fit are the ones already walked."""
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
except ImportError:
    cv2 = None

from . import buttons
import project

FILE = os.path.join("meta", "lists.json")
SEARCH = 520
MIN_SCORE = 0.62
SCALES = [1.0, 0.75, 0.7]
MATCH = 0.5                # a row "fits" a name above this (whole-name comparison): one place ~0.8-0.97, two ~0.1-0.5,
                           # but two names one character apart up to ~0.87: only a run of rows tells them apart
ROW_OK = 0.6               # a row laid on a name must still look like it at least this much
PAD = 8                    # names may sit a few pixels off (the anchor found a little higher or lower)
ALONE_MARGIN = 0.05        # a row matched by itself (lists whose order changes) must beat the next best name by this


def load(data_root):
    p = os.path.join(data_root, FILE)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return {x["id"]: x for x in json.load(f).get("lists", [])}


def _strokes(a):
    m = a.astype(np.float32).min(axis=2)
    return m - cv2.GaussianBlur(m, (0, 0), 3)


def _ncc(a, b):
    """Two name pictures (_strokes, same size), a few pixels of give."""
    if a.shape != b.shape:
        return 0.0
    return float(cv2.matchTemplate(np.pad(b, PAD, mode="edge"), a[2:-2, 2:-2], cv2.TM_CCOEFF_NORMED).max())


def _fit(lib, pics):
    """Lay the rows (pics, top to bottom) over the list (lib pictures in list order).
    -> (k, scores): row j sits on lib[k + j]; scores[j] its own score (None: past the list's ends)."""
    if not lib or not pics:
        return 0, [None] * len(pics)
    m = np.array([[_ncc(q, p) for q in lib] for p in pics])
    best, bk = None, 0
    for k in range(-len(pics) + 1, len(lib)):
        s = sum(m[j, k + j] - MATCH for j in range(len(pics)) if 0 <= k + j < len(lib))
        if best is None or s > best:
            best, bk = s, k
    return bk, [float(m[j, bk + j]) if 0 <= bk + j < len(lib) else None for j in range(len(pics))]


def _alone(lib, pic, taken):
    """A list whose order changes (accounts: the one used last comes first): the best name for one row by
    itself -> library index, or None. It must look like the row, clearly more than any other name, and not be one
    already walked."""
    sc = sorted(((_ncc(q, pic), i) for i, q in enumerate(lib)), reverse=True)
    if not sc or sc[0][0] < ROW_OK or (len(sc) > 1 and sc[0][0] - sc[1][0] < ALONE_MARGIN) or sc[0][1] in taken:
        return None
    return sc[0][1]


def _overlap(prev, cur):
    """How many of the first rows of this page are the last rows walked (scrolled less than a page)."""
    best, bt = 0.0, 0
    for t in range(1, min(len(prev), len(cur)) + 1):
        s = sum(_ncc(prev[len(prev) - t + j], cur[j]) - MATCH for j in range(t))
        if s > best:
            best, bt = s, t
    return bt


def _locked(spec, crop):
    f = spec.get("skip_red")
    if not f:
        return False
    a = crop.astype(np.int32)
    return float(((a[..., 0] > 90) & (a[..., 0] > 2 * a[..., 1]) & (a[..., 0] > 2 * a[..., 2])).mean()) >= float(f)


def rows(spec, frame, anchor):
    """Top-left corners of the anchors (one per row), top to bottom."""
    x, y, w, h = spec["anchor"]["area"]
    reg = buttons._feature(Image.fromarray(frame[y:y + h, x:x + w]), spec["anchor"].get("feature", "gray"))
    r = cv2.matchTemplate(reg, anchor, cv2.TM_CCOEFF_NORMED)
    gap = int(spec["anchor"].get("gap", 40))
    out = []
    while True:
        _x, s, _x, (bx, by) = cv2.minMaxLoc(r)
        if s < float(spec["anchor"].get("min", 0.6)):
            break
        out.append((bx + x, by + y))
        r[max(0, by - gap):by + gap, :] = -1
    return sorted(out, key=lambda p: p[1])


def names(spec, frame, anchor):
    dx, dy, w, h = spec["name"]
    ax, ay, aw, ah = spec["anchor"]["area"]
    out = []
    for x0, y0 in rows(spec, frame, anchor):
        x, y = x0 + dx, y0 + dy
        if x < 0 or y < 0 or y + h > frame.shape[0] or x + w > frame.shape[1] or y < ay or y + h > ay + ah:
            continue                                      # cut off at the top / bottom of the list
        crop = frame[y:y + h, x:x + w]
        if _locked(spec, crop):
            continue
        out.append(([x, y, w, h], _strokes(crop)))
    return out


def items(data_root, spec, device=None):
    return [b for b in buttons.load(data_root).values()
            if b.get("list") == spec["id"] and (not spec.get("per_device") or b.get("device") == device)]


def _anchor(data_root, spec):
    a = Image.open(project.resolve(spec["anchor"]["file"], data_root)).convert("RGB")
    return buttons._feature(a, spec["anchor"].get("feature", "gray"))


def _pos(b):
    if b.get("pos") is not None:
        return float(b["pos"])
    m = re.search(r"_(\d+)$", b["id"])
    return float(m.group(1)) if m else 1e9


def ordered(data_root, spec, device=None):
    """The list's names (buttons) in list order."""
    return sorted(items(data_root, spec, device), key=_pos)


_pics = {}


def _library(data_root, spec, device=None):
    """[(button, picture)] in list order."""
    out = []
    for b in ordered(data_root, spec, device):
        p = buttons.image_path(data_root, b["id"])
        key = (p, b.get("updated"))
        if key not in _pics and os.path.exists(p):
            _pics[key] = _strokes(np.asarray(Image.open(p).convert("RGB")))
        if key in _pics:
            out.append((b, _pics[key]))
    return out


def which(data_root, spec, frame, device=None):
    """The rows on the screen -> {"rows": [{"id", "label", "score", "box"}] (id None: not a name in the list),
    "top": where the first row is in the list (0 = its first name; can be off by the rows not known), "size"}."""
    lib = _library(data_root, spec, device)
    found = names(spec, frame, _anchor(data_root, spec))
    k, scores = _fit([p for _x, p in lib], [p for _x, p in found])
    out = []
    for j, ((box, _x), sc) in enumerate(zip(found, scores)):
        b = lib[k + j][0] if sc is not None and sc >= ROW_OK else None
        out.append({"id": b and b["id"], "label": b and b["label"], "score": round(sc or 0.0, 3), "box": box})
    return {"rows": out, "top": k, "size": len(lib)}


def order(b):
    """The number in front of a name ("12. 北棟水池" -> 12): where it is in the list."""
    m = re.match(r"\s*(\d+)", b.get("label") or "")
    return int(m.group(1)) if m else None


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _to_top(spec, anchor, snap, swipe, most=30):
    sw = spec["swipe"]
    last = None
    for _x in range(most):
        swipe(sw["x"], sw["top"][0], sw["top"][1])
        time.sleep(0.8)
        cur = [p for _x, p in names(spec, snap(), anchor)]
        if last and len(cur) == len(last) and _overlap(last, cur) == len(cur):
            return                                        # did not move: the top
        last = cur


def capture(data_root, spec, device, snap, swipe, tap, pages=60):
    """snap() -> RGB frame (the coordinate space); swipe(x, y1, y2); tap(x, y). Walks the whole list from the top.
    -> {"new": [...], "known": [...]}; every name walked gets its place in the list ("pos")."""
    anchor = _anchor(data_root, spec)
    ready = buttons.load(data_root).get(spec.get("ready") or "")
    frame = snap()
    if ready and buttons.locate(ready, frame, data_root)[0][0] is None:
        raise ValueError(spec.get("ready_text") or _("現在不在這個清單的畫面"))
    sw = spec["swipe"]
    _to_top(spec, anchor, snap, swipe)
    lib = _library(data_root, spec, device)
    lib_pics = [p for _x, p in lib]
    walked = []                                           # (picture, button) in list order
    new, found_known = [], set()
    taken = set(buttons.load(data_root))
    prefix = f"{spec['id']}_{_slug(device)}" if spec.get("per_device") else spec["id"]
    n, still = 1, 0
    for page in range(pages):
        frame = snap()
        found = names(spec, frame, anchor)
        rows_ = [(frame, x) for x in found]
        if page == 0 and spec.get("select_first") and found:
            # the chosen row (the account used last) looks different and may not even be found as a row:
            # choose the first row, then the one next to it (not the bottom one: choosing a half-shown row scrolls the
            # list); each row is taken from the first picture, the first row from the second
            def pick(r):
                bx = r[0]
                tap(bx[0] + bx[2] // 2, bx[1] + bx[3] // 2)
                time.sleep(1.2)
                f = snap()
                return f, names(spec, f, anchor)
            first = found[0][0]
            frame2, found2 = pick(found[0])
            others = [r for r in found2 if abs(r[0][1] - first[1]) > 20]
            rows_ = [(frame2, r) for r in others]
            if others:
                frame3, found3 = pick(min(others, key=lambda r: abs(r[0][1] - first[1])))
                rows_ += [(frame3, r) for r in found3 if abs(r[0][1] - first[1]) <= 20][:1]
            rows_.sort(key=lambda fr: fr[1][0][1])
        pics = [p for _x, (_x, p) in rows_]
        t = _overlap([p for p, _x in walked], pics) if walked else 0
        still = still + 1 if t == len(rows_) else 0
        if still >= 2:                                    # the bottom of the list (one still page can be a short swipe)
            break
        k, scores = _fit(lib_pics, pics)
        for j, (fr, (box, pic)) in enumerate(rows_):
            if j < t:
                continue
            i = k + j if scores[j] is not None and scores[j] >= ROW_OK else None
            if i is None and spec.get("match") != "run":  # the order changed since: find the row's name by itself
                done = {b["id"] for _x, b in walked}
                i = _alone(lib_pics, pic, {n_ for n_, (b, _x) in enumerate(lib) if b["id"] in done})
            if i is not None:
                b = lib[i][0]                             # already in the library
                found_known.add(b["id"])
                walked.append((pic, b))
                continue
            while f"{prefix}_{n}" in taken:
                n += 1
            bid = f"{prefix}_{n}"
            taken.add(bid)
            x, y, w, h = box
            b = {"id": bid, "label": f"{spec.get('title') or spec['id']} {len(walked) + 1}", "x": x + w // 2,
                 "y": y + h // 2, "find": True, "box": box, "search": SEARCH, "min_score": MIN_SCORE, "feature": "text",
                 "scales": SCALES, "min_score_scaled": 0.5, "group": spec["group"], "list": spec["id"]}
            if spec.get("per_device"):
                b["device"] = device
            b = buttons.save(data_root, b, fr)
            new.append(b)
            walked.append((pic, b))
        swipe(sw["x"], sw["page"][0], sw["page"][1])
        time.sleep(1.2)
    complete = still >= 2                                 # walked to the end (not stopped by the page limit)
    now = time.time()
    seen = {b["id"] for _x, b in walked}
    for i, (_x, b) in enumerate(walked):                   # list order, as walked; seen again: no longer missing
        if b.get("pos") != i or b.get("missing_since"):
            buttons.save(data_root, {**{k: v for k, v in b.items() if k != "missing_since"}, "pos": i})
    missing = []
    if complete:
        for b, _x in lib:
            if b["id"] not in seen:
                missing.append(b["id"])
                if not b.get("missing_since"):
                    buttons.save(data_root, {**b, "missing_since": now})
    return {"new": new, "known": sorted(found_known), "missing": missing, "total": len(walked), "complete": complete}


# ---------------- what the people running it do with a list (the operation panel) ----------------
SCANS = "list_scans.json"


def scans(runtime_dir):
    try:
        with open(os.path.join(runtime_dir, SCANS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def note_scan(runtime_dir, spec, device, result):
    """Keep what one walk found (the panel shows it: when, how many, which are new / missing)."""
    d = scans(runtime_dir)
    d.setdefault(spec["id"], {})[device if spec.get("per_device") else "*"] = {
        "t": time.time(), "total": result.get("total"), "new": [b["id"] for b in result.get("new") or []],
        "missing": result.get("missing") or [], "complete": result.get("complete", True)}
    os.makedirs(runtime_dir, exist_ok=True)
    p = os.path.join(runtime_dir, SCANS)
    atomic.write_json(p, d, ensure_ascii=False)


def _item(data_root, spec, device, bid):
    b = buttons.load(data_root).get(bid)
    if not b or b.get("list") != spec["id"] or (spec.get("per_device") and b.get("device") != device):
        raise ValueError(_("清單裡沒有這個項目,請重新整理頁面"))
    return b


def rename(data_root, spec, device, bid, label):
    label = (label or "").strip()
    if not label or len(label) > 40:
        raise ValueError(_("名稱要 1~40 個字"))
    b = _item(data_root, spec, device, bid)
    return buttons.save(data_root, {**b, "label": label})


def keep(data_root, spec, device, bid):
    """A missing name is still there (it was just not found): clear the mark."""
    b = _item(data_root, spec, device, bid)
    return buttons.save(data_root, {k: v for k, v in b.items() if k != "missing_since"})


def remove(data_root, runtime_dir, spec, device, bid):
    """Take a name out of the list for good (deleted in the app): its button, and the users' choices of it."""
    _item(data_root, spec, device, bid)
    from . import settings as settings_mod
    settings_mod.forget_button(data_root, runtime_dir, bid)
    buttons.delete(data_root, bid)
