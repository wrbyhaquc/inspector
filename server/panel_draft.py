"""The operation panel's draft, its published versions and what is wrong with it (面板改造 E6).

Editing changes a draft (<runtime dir>/panel_draft.json {"panel", "base", "t"}): the people using the panel keep
seeing the published one (<data_root>/meta/panel.json) until it is published. "base" is the published panel the draft
started from, so the editor can say when someone else published since (an AI over MCP, another tab).
Every publish keeps a copy (<runtime dir>/panel_versions/<id>.json {"id", "t", "note", "panel"}, the newest
KEEP); an older one comes back as a draft, to look at and publish again.
problems() lists what is wrong (level "error": it cannot be published) or worth a look ("warn"), with the block."""
import copy
import hashlib
import json
import os
import time

import atomic
from i18n import _

from . import RUNTIME_DIR, panel as pm

DRAFT = "panel_draft.json"
VERSIONS = "panel_versions"
KEEP = 50


def _key(panel):
    """What a panel is, without its stamp: two panels with the same key are the same."""
    p = {k: v for k, v in (panel or {}).items() if k != "format"}
    return hashlib.sha1(json.dumps(p, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_draft(data_root):
    """{"panel", "stale": someone published since it started, "t"} or None."""
    p = os.path.join(RUNTIME_DIR, DRAFT)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    return {"panel": pm.normalize(d["panel"]), "t": d.get("t"), "stale": d.get("base") != _key(pm.load(data_root))}


def save_draft(data_root, panel, base=None):
    """Keep the draft (nothing is checked: a draft may be half done). base: the published panel it started from
    (None = keep the one it had)."""
    p = os.path.join(RUNTIME_DIR, DRAFT)
    old = None
    if base is None and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            old = json.load(f).get("base")
    atomic.write_json(p, {"panel": panel, "base": base or old or _key(pm.load(data_root)), "t": time.time()},
                      ensure_ascii=False, indent=1)


def drop_draft():
    p = os.path.join(RUNTIME_DIR, DRAFT)
    if os.path.exists(p):
        os.remove(p)


def _vdir():
    return os.path.join(RUNTIME_DIR, VERSIONS)


def versions():
    """The kept versions, newest first: [{"id", "t", "note", "blocks"}]."""
    d = _vdir()
    out = []
    for n in sorted(os.listdir(d), reverse=True) if os.path.isdir(d) else []:
        if n.endswith(".json"):
            with open(os.path.join(d, n), encoding="utf-8") as f:
                v = json.load(f)
            out.append({"id": v["id"], "t": v["t"], "note": v.get("note") or "", "blocks": len(v["panel"].get("blocks") or [])})
    return out


def version(vid):
    p = os.path.join(_vdir(), f"{vid}.json")
    if not vid.replace("-", "").isdigit() or not os.path.exists(p):
        raise ValueError(_("找不到這個版本"))
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def keep(panel, note):
    """Keep a copy of a published panel (not when it is the same as the newest one)."""
    vs = versions()
    if vs and _key(version(vs[0]["id"])["panel"]) == _key(panel):
        return
    os.makedirs(_vdir(), exist_ok=True)
    now = time.time()

    def vid_at(t):                                  # one clock reading: date-time and its milliseconds
        return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + f"{int(t * 1000) % 1000:03d}"
    vid = vid_at(now)
    # two keeps in the same millisecond (a fast machine) must not share an id, and the new one sorts newest
    while os.path.exists(os.path.join(_vdir(), f"{vid}.json")) or (vs and vid <= vs[0]["id"]):
        now += 0.001
        vid = vid_at(now)
    atomic.write_json(os.path.join(_vdir(), f"{vid}.json"), {"id": vid, "t": now, "note": note, "panel": panel},
                      ensure_ascii=False, indent=1)
    for old in versions()[KEEP:]:
        os.remove(os.path.join(_vdir(), f"{old['id']}.json"))


def publish(data_root, panel, note, drop=True):
    """Make the panel what its users see (pm.save checks it), keep it as a version and (drop) end the draft. The one
    it replaces is kept first, so the very first publish can be taken back too."""
    if not versions() and os.path.exists(os.path.join(data_root, pm.FILE)):
        keep(pm.load(data_root), _("發佈前的面板"))
    pm.save(data_root, panel)
    keep(pm.load(data_root), note)
    if drop:
        drop_draft()


def problems(data_root, panel):
    """[{"level": "error" | "warn", "text", "block"?}] - errors keep it from being published."""
    out = []
    panel = pm.normalize(copy.deepcopy(panel))
    ctl = {c["id"]: c for c in panel.get("controls") or []}
    on_page = {}
    for b in panel["blocks"]:
        on_page.setdefault(b.get("page") or (panel.get("pages") or [{"id": None}])[0]["id"], []).append(b)
        name = b.get("title") or b["id"]
        if not str(b.get("title") or "").strip():
            out.append({"level": "warn", "text": _("有一個區塊沒有標題"), "block": b["id"]})
        if b.get("widget"):
            try:
                pm.check_widget(data_root, b["widget"])
            except ValueError as e:
                out.append({"level": "error", "text": _("「{name}」:{e}", name=name, e=e), "block": b["id"]})
            continue
        ids = ([b["toggle"]] if b.get("toggle") else []) + list(b.get("items") or [])
        if not ids:
            out.append({"level": "warn", "text": _("「{name}」裡面還沒有設定或按鈕", name=name), "block": b["id"]})
        for i in ids:
            c = ctl[i]
            try:
                pm.save_check_control(data_root, panel, c)
            except ValueError as e:
                out.append({"level": "error", "text": _("「{name}」:{e}", name=name, e=e), "block": b["id"]})
    for pg in panel.get("pages") or []:
        if not on_page.get(pg["id"]):
            out.append({"level": "warn", "text": _("分頁「{title}」是空的", title=pg.get("title") or pg["id"])})
    if panel["blocks"] and all((b.get("phone") or {}).get("hide") for b in panel["blocks"]):
        out.append({"level": "warn", "text": _("每個區塊都設成手機上不顯示,手機上會是空的")})
    if not out or all(x["level"] == "warn" for x in out):        # the rest of what saving checks (names, pages, look ...)
        try:
            pm.save(data_root, copy.deepcopy(panel), write=False)
        except ValueError as e:
            out.insert(0, {"level": "error", "text": str(e)})
    return out
