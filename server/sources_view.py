"""The 來源 page's view of the sources (drivers/sources.py): what is found, what is used, where each one is referred to.

references(id) answers "what depends on this source" - before it is removed or re-bound, and on its row: the main
scripts deployed on it, schedules it takes part in, the operation panel, notification channels that watch it, the
values users chose for it (user settings), its own names in per-device lists, its variables, script tests, recordings.
Ids never change, so renaming (the name people read) or re-binding (the driver's own name) keeps all of these."""
import json
import os

import drivers
from drivers import sources
from i18n import _, tr
import project


def _read(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def references(root, runtime_dir, dev_id):
    """[{"kind", "what", "text"}] - everything that refers to this source by its id."""
    import automation
    from automation import buttons, lists, schedules, settings, tests
    out = []
    for x in sources.load(root)["items"]:
        if (x.get("hand") or {}).get("to") == "source" and x["hand"].get("id") == dev_id:
            out.append({"kind": "hand", "what": x["id"], "text": _("來源「{p1}」的動作交給它", p1=sources.label(x['id'], root))})
    for s in automation.load_all(root):
        devs = s.get("devices") or {}
        m = devs.get(dev_id) or (sources.mode_of(devs, dev_id, root) if any(str(k).startswith("#") for k in devs) else None)
        if m and m != "off":
            out.append({"kind": "script", "what": s["id"], "text": _("主腳本「{name}」:{p2}", name=s['name'], p2=automation.mode_label(m))
                        + ("" if dev_id in devs else _("(因為標籤)"))})
    for s in schedules.load(root):
        if dev_id in sources.expand(s.get("devices")):
            out.append({"kind": "schedule", "what": s["id"], "text": _("排程「{name}」", name=s['name']) + ("" if dev_id in (s.get("devices") or []) else _("(因為標籤)"))})
    pnl = _read(os.path.join(root, "meta", "panel.json"), {})
    if dev_id in sources.expand(pnl.get("devices")):
        out.append({"kind": "panel", "what": "panel", "text": _("操作面板顯示這台") + ("" if dev_id in (pnl.get("devices") or []) else _("(因為標籤)"))})
    for c in (_read(os.path.join(runtime_dir, "notify.json"), {}) or {}).get("channels", []):
        if dev_id in sources.expand(c.get("devices")):
            out.append({"kind": "notify", "what": c["id"], "text": _("通知「{name}」只看這幾台(包含它)", name=c.get('name'))})
    decl = settings.load(root)
    for sid, per in (settings.values(runtime_dir) or {}).items():
        if isinstance(per, dict) and dev_id in per:
            out.append({"kind": "setting", "what": sid, "text": _("使用者設定「{label}」有這台自己的值", label=(decl.get(sid) or {}).get('label', sid))})
    try:
        specs = lists.load(root)
        n = {}
        for b in buttons.load(root).values():
            if b.get("device") == dev_id and b.get("list") in specs:
                n[b["list"]] = n.get(b["list"], 0) + 1
        for lid, k in n.items():
            out.append({"kind": "list", "what": lid, "text": _("清單「{title}」有這台的 {k} 個項目", title=specs[lid].get('title', lid), k=k)})
    except Exception:
        pass
    vs = (_read(os.path.join(runtime_dir, "vars.json"), {}) or {}).get("device", {}).get(dev_id)
    if vs:
        out.append({"kind": "vars", "what": "vars", "text": _("變數:這台自己的值 {p1} 個", p1=len(vs))})
    for t in tests.load(root):
        if t.get("device") == dev_id:
            out.append({"kind": "test", "what": t["id"], "text": _("腳本測試「{name}」用這台的錄影", name=t.get('name'))})
    sess = os.path.join(project.work_of(root), "sessions")
    k = sum(1 for s in (os.listdir(sess) if os.path.isdir(sess) else []) if os.path.isdir(os.path.join(sess, s, dev_id)))
    if k:
        out.append({"kind": "recording", "what": "sessions", "text": _("錄影:{k} 次收集有這台的畫面", k=k)})
    return out


def view(root, runtime_dir, status=None):
    """The page: kinds, the sources (with how they are now) and the ones found but not used."""
    cfg = sources.load(root)
    have = drivers.describe()
    live = {d["name"]: d for d in (status or {}).get("devices") or []}
    drv = drivers.current(root)
    if not drv.last or any((have.get(it["kind"]) or {}).get("per_source") for it in cfg["items"]):
        drv.list()                               # windows / screens: looked for by their own settings each time
    found = drv.last or {}
    natives = {(k, d.name): d for k, devs in found.items() for d in devs}
    items = []
    for it in cfg["items"]:
        d = drv.found.get(it["id"]) if (have.get(it["kind"]) or {}).get("per_source") else natives.get((it["kind"], it["match"]))
        items.append({**it, "label": it.get("name") or it["id"], "kind_label": (have.get(it["kind"]) or {}).get("label", it["kind"]),
                      "present": d is not None, "detail": d.detail if d else "", "size": list(d.size) if d and d.size else None,
                      "size_warn": sources.check_size(d, root, bool((have.get(it["kind"]) or {}).get("per_source"))) if d else None,
                      "watching": it["id"] in live, "window": bool((live.get(it["id"]) or {}).get("window")),
                      "health": (live.get(it["id"]) or {}).get("health"),
                      "caps": sorted(sources.caps_of(it["id"], root)), "hand_text": sources.hand_text(it, root),
                      "per_source": (have.get(it["kind"]) or {}).get("per_source") or {},
                      "used_as_hand_by": [x["id"] for x in cfg["items"] if (x.get("hand") or {}).get("to") == "source"
                                          and x["hand"].get("id") == it["id"]],
                      "refs": references(root, runtime_dir, it["id"])})
    bound = {(it["kind"], it["match"]) for it in cfg["items"]}
    new = [_native(k, d, root, have, cfg) for (k, n), d in natives.items() if (k, n) not in bound]
    missing = [it["id"] for it in items if not it["present"] and it["kind"] in found]
    new = [n for n in new if not (have.get(n["kind"]) or {}).get("per_source")]     # windows: candidates, not news
    from automation import outputs
    used = {}
    for it in cfg["items"]:
        if it.get("enabled"):
            used[it["kind"]] = used.get(it["kind"], 0) + 1
    return {"kinds": {k: {**v, "on": k in used, "in_use": used.get(k, 0),
                          "params_set": (cfg["kinds"].get(k) or {}).get("params") or {}} for k, v in have.items()},
            "items": items, "new": new, "missing": missing, "hands": tr(sources.HANDS),
            "outputs": [{"id": o["id"], "name": o.get("name") or o["id"]} for o in outputs.load(root).values()]}


def _native(k, d, root, have, cfg):
    kd = have.get(k) or {}
    return {"kind": k, "kind_label": kd.get("label", k), "category_label": kd.get("category_label", ""), "match": d.name, "detail": d.detail, "ok": d.ok,
            "size": list(d.size) if d.size else None, "size_warn": sources.check_size(d, root, bool(kd.get("per_source"))),
            "opts": (d.info or {}).get("opts"), "per_source": bool(kd.get("per_source")),
            "seen": cfg["seen"].get(f"{k}|{d.name}"), "ignored": f"{k}|{d.name}" in (cfg.get("ignored") or [])}


def _spec_hit(spec, title, cls):
    """Does a window (title, class) fit a window spec (drivers/windows.py)?"""
    t = spec.get("title") or ""
    if t and not ((t.lower() in title.lower()) if spec.get("title_mode") == "contains" else t == title):
        return False
    return not spec.get("class") or spec["class"] == cls


def scan(root, kinds=None, q=""):
    """Look now (any kinds, even ones that are off - with their saved or default params), filtered by text.
    Every row says its category; one already in use says by which source - also when it is the same device seen another
    way (an emulator's window is that emulator: its kind says which window shows it) -; a window that looks like a
    product another kind knows better says so (suggest)."""
    drv = drivers.current(root)
    if not drv.last:
        drv.list()                               # what the kinds in use own (another kind does not list it again)
    found, errors = drv.scan(kinds or None)
    cfg = sources.load(root)
    have = drivers.describe()
    kinds_all = drivers.kinds()
    per = lambda k: bool((have.get(k) or {}).get("per_source"))
    bound = {(it["kind"], it["match"]): it["id"] for it in cfg["items"] if not per(it["kind"])}
    windowed = []                                # (window spec, source id): sources whose picture is a window
    for it in cfg["items"]:
        if per(it["kind"]) or it["kind"] not in kinds_all:
            continue
        try:
            d = drv._driver(it["kind"], (cfg["kinds"].get(it["kind"]) or {}).get("params"))
            spec = d.window_spec(it["match"]) if hasattr(d, "window_spec") else None
        except Exception:
            spec = None
        if spec:
            windowed.append((spec, it["id"]))
    own = [(it["kind"], it.get("params") or {}, it["id"]) for it in cfg["items"] if per(it["kind"])]
    q = (q or "").strip().lower()
    out = []
    for k, devs in found.items():
        for d in devs:
            row = {**_native(k, d, root, have, cfg), "bound": bound.get((k, d.name)), "same_as": None, "suggest": None,
                   "category": (have.get(k) or {}).get("category", k)}
            if row["per_source"]:
                o = (d.info or {}).get("opts") or {}
                title, cls, proc = o.get("title", ""), o.get("class", ""), o.get("process", "")
                for kk, ps, sid in own:              # a window / screen source already pointing at it
                    if kk.split("/")[0] != k.split("/")[0]:
                        continue
                    if ("monitor" in ps and ps.get("monitor") == o.get("monitor")) or (
                            ps.get("title") and _spec_hit({"title": ps["title"], "title_mode": ps.get("title_mode"), "class": ps.get("class")}, title, cls)
                            and (not ps.get("process") or ps["process"].lower() == proc.lower())):
                        row["bound"] = sid
                for spec, sid in windowed:           # the window of a source used another way: the same device
                    if title and _spec_hit(spec, title, cls):
                        row["bound"], row["same_as"] = sid, (have.get(next(i["kind"] for i in cfg["items"] if i["id"] == sid)) or {}).get("label")
                if not row["bound"]:
                    for kid, kd in kinds_all.items():
                        sig = kd.signature
                        if sig and (proc.lower() in {x.lower() for x in sig.get("process", [])} or cls in sig.get("class", [])):
                            row["suggest"] = {"kind": kid, "label": kd.label, "category_label": kd.category_label}
                            break
            text = " ".join([k, row["kind_label"], row["category_label"], d.name, d.detail or "",
                             str((d.info or {}).get("model") or "")]).lower()
            if q and not all(w in text for w in q.split()):
                continue
            out.append(row)
    return {"found": out, "errors": errors}
