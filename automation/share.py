"""Share sub-scripts (分享子腳本): export some sub-scripts as one JSON bundle, import a bundle into this project.

Bundle (one JSON text - a file, or pasted):
  {"kind": "inspector.subscripts", "format": spec.FORMAT, "exported", "from": project name, "screen": [w, h],
   "subs":      [sub-script, ...]                      as stored (without version / created / note)
   "buttons":   {id: {"label", "x", "y", "find", "box", "search", "min_score", "feature", "scales", ...,
                      "image": PNG as base64 (find buttons)}}
   "states":    {id: {"name", "type", "classes": [values]}}   the states the conditions read
   "variables": [variable definitions], "settings": [user setting declarations],
   "lists":     {id: {"title"}}, "outputs": {id: {"name", "type"}}   (an output's address is never exported)}

Import = analyze(bundle) -> what it needs and what matches here (by id, then by name); the user picks per item:
  sub-script  "new" (its id) | "rename" (a new id) | "overwrite" | "skip"
  button      an existing button id | "create" (from the bundle's position / picture)
  state       an existing state id                list / output: an existing id
then apply(bundle, plan) rewrites every reference, checks each sub-script against the spec (spec_schema.check) and
saves them; missing variables and user settings are added as they were declared. Nothing is saved when one fails."""
import base64
import copy
import json
import os
import re
import time

from . import spec
from i18n import _

KIND = "inspector.subscripts"
ID = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------- what a sub-script refers to
def refs(doc):
    """{"buttons", "states", "vars", "settings", "lists", "subs", "outputs"}: ids a sub-script (or a list of them) uses."""
    out = {k: set() for k in ("buttons", "states", "vars", "settings", "lists", "subs", "outputs")}

    def walk(x, parent_key=None):
        if isinstance(x, list):
            for v in x:
                walk(v, parent_key)
            return
        if not isinstance(x, dict):
            return
        if len(x) == 1:
            (k, v), = x.items()
            if k == "button":
                out["buttons"].add(v)
            elif k == "setting":
                out["settings"].add(v)
            elif k == "var":
                out["vars"].add(v)
        t = x.get("type")
        if x.get("state") and isinstance(x.get("state"), str):
            out["states"].add(x["state"])
        if t == "set_var" or (x.get("kind") in ("var", "elapsed")):
            if isinstance(x.get("var"), str):
                out["vars"].add(x["var"])
        if t == "call" and x.get("sub"):
            out["subs"].add(x["sub"])
        if t == "capture_list" and x.get("list"):
            out["lists"].add(x["list"])
        if t == "output" and x.get("output"):
            out["outputs"].add(x["output"])
        if x.get("from_list"):
            out["lists"].add(x["from_list"])
        for k, v in x.items():
            walk(v, k)
    walk(doc)
    return out


def _rewrite(doc, maps):
    """A copy of doc with references renamed: maps {"buttons": {old: new}, "states", "lists", "subs", "outputs"}."""
    doc = copy.deepcopy(doc)

    def walk(x):
        if isinstance(x, list):
            for v in x:
                walk(v)
            return
        if not isinstance(x, dict):
            return
        if len(x) == 1 and "button" in x and x["button"] in maps.get("buttons", {}):
            x["button"] = maps["buttons"][x["button"]]
        if isinstance(x.get("state"), str) and x["state"] in maps.get("states", {}):
            x["state"] = maps["states"][x["state"]]
        if x.get("type") == "call" and x.get("sub") in maps.get("subs", {}):
            x["sub"] = maps["subs"][x["sub"]]
        if x.get("type") == "capture_list" and x.get("list") in maps.get("lists", {}):
            x["list"] = maps["lists"][x["list"]]
        if x.get("from_list") in maps.get("lists", {}):
            x["from_list"] = maps["lists"][x["from_list"]]
        if x.get("type") == "output" and x.get("output") in maps.get("outputs", {}):
            x["output"] = maps["outputs"][x["output"]]
        for v in x.values():
            walk(v)
    walk(doc)
    return doc


# ---------------------------------------------------------------- export
def export(data_root, sub_ids, with_calls=True):
    """-> the bundle (dict) of these sub-scripts (and, with_calls, every sub-script they call)."""
    import automation
    import project
    import schema as schema_mod
    from . import buttons, lists, outputs, settings, subs
    lib = subs.load_all(data_root)
    todo, chosen = list(sub_ids), []
    while todo:
        sid = todo.pop(0)
        if sid in chosen:
            continue
        if sid not in lib:
            raise ValueError(_("找不到子腳本「{sid}」", sid=sid))
        chosen.append(sid)
        if with_calls:
            todo += sorted(refs(lib[sid])["subs"] - set(chosen))
    docs = [{k: v for k, v in lib[s].items() if k not in ("version", "created", "note", "outline")} for s in chosen]
    r = refs(docs)
    bs = buttons.load(data_root)
    out_buttons = {}
    for bid in sorted(r["buttons"]):
        b = bs.get(bid)
        if not b:
            continue
        item = {k: v for k, v in b.items() if k not in ("updated", "group")}
        img = buttons.image_path(data_root, bid)
        if b.get("find") and os.path.exists(img):
            item["image"] = base64.b64encode(open(img, "rb").read()).decode("ascii")
        out_buttons[bid] = item
    sch = schema_mod.load(data_root)
    states = {s["id"]: {"name": s["name"], "type": s["type"], "classes": [c["value"] for c in s.get("classes") or []]}
              for s in sch["states"] if s["id"] in r["states"]}
    var_defs = [v for v in automation.variables(data_root) if v["name"] in r["vars"]]
    decls = settings.load(data_root)
    p = project.load(data_root)
    return {"kind": KIND, "format": spec.FORMAT, "exported": time.time(), "from": p.get("name"),
            "screen": list(project.screen(data_root)), "subs": docs, "buttons": out_buttons, "states": states,
            "variables": var_defs, "settings": [decls[k] for k in sorted(r["settings"]) if k in decls],
            "lists": {k: {"title": (lists.load(data_root).get(k) or {}).get("title", k)} for k in sorted(r["lists"])},
            "outputs": {k: {"name": (outputs.load(data_root).get(k) or {}).get("name", k),
                            "type": (outputs.load(data_root).get(k) or {}).get("type")} for k in sorted(r["outputs"])}}


# ---------------------------------------------------------------- import
def _read(bundle):
    if isinstance(bundle, str):
        try:
            bundle = json.loads(bundle)
        except ValueError as e:
            raise ValueError(_("不是正確的 JSON:{e}", e=e)) from None
    if not isinstance(bundle, dict) or bundle.get("kind") != KIND:
        raise ValueError(_("這不是 Inspector 的子腳本分享檔"))
    if spec.version(bundle) > spec.FORMAT:
        raise ValueError(_("分享檔是較新的腳本規範(第 {p1} 版)做的,請先更新 Inspector", p1=spec.version(bundle)))
    bundle = dict(bundle)
    bundle["subs"] = [spec.upgrade({"format": bundle.get("format"), **s}) for s in bundle.get("subs") or []]
    return bundle


def _by_name(items, name, key="name"):
    hits = [k for k, v in items.items() if (v.get(key) or "").strip() == (name or "").strip()]
    return hits[0] if len(hits) == 1 else None


def analyze(data_root, bundle):
    """What the bundle brings and what each reference matches here (to show the user before importing)."""
    import project
    import schema as schema_mod
    from . import buttons, lists, outputs, subs
    b = _read(bundle)
    lib = subs.load_all(data_root)
    bs = {k: v for k, v in buttons.load(data_root).items() if not v.get("list")}
    states = {s["id"]: s for s in schema_mod.load(data_root)["states"]}
    lst = lists.load(data_root)
    outs = outputs.load(data_root)
    r = refs(b["subs"])
    inside = {s["id"] for s in b["subs"]}
    out = {"from": b.get("from"), "exported": b.get("exported"), "screen": b.get("screen"),
           "here_screen": list(project.screen(data_root)), "subs": [], "buttons": [], "states": [], "lists": [],
           "outputs": [], "variables": [], "settings": [], "missing_subs": sorted(r["subs"] - inside - set(lib))}
    for s in b["subs"]:
        out["subs"].append({"id": s["id"], "name": s.get("name"), "exists": s["id"] in lib,
                            "here_name": (lib.get(s["id"]) or {}).get("name")})
    for bid in sorted(r["buttons"]):
        info = (b.get("buttons") or {}).get(bid) or {}
        match = bid if bid in bs and bs[bid].get("label") == info.get("label") else _by_name(bs, info.get("label"), "label")
        out["buttons"].append({"id": bid, "label": info.get("label", bid), "find": bool(info.get("find")),
                               "has_image": bool(info.get("image")), "match": match or ("" if bid not in bs else bid),
                               "exists": bid in bs, "can_create": bool(info.get("label")) and "x" in info})
    for sid in sorted(r["states"]):
        info = (b.get("states") or {}).get(sid) or {}
        match = sid if sid in states else _by_name(states, info.get("name"))
        out["states"].append({"id": sid, "name": info.get("name", sid), "match": match or ""})
    for lid in sorted(r["lists"]):
        info = (b.get("lists") or {}).get(lid) or {}
        match = lid if lid in lst else _by_name(lst, info.get("title"), "title")
        out["lists"].append({"id": lid, "title": info.get("title", lid), "match": match or ""})
    for oid in sorted(r["outputs"]):
        info = (b.get("outputs") or {}).get(oid) or {}
        match = oid if oid in outs else _by_name(outs, info.get("name"))
        out["outputs"].append({"id": oid, "name": info.get("name", oid), "match": match or ""})
    import automation
    from . import settings
    have_vars = {v["name"] for v in automation.variables(data_root)}
    out["variables"] = [{"name": v["name"], "label": v.get("label"), "exists": v["name"] in have_vars} for v in b.get("variables") or []]
    have_set = settings.load(data_root)
    out["settings"] = [{"id": s["id"], "label": s.get("label"), "exists": s["id"] in have_set} for s in b.get("settings") or []]
    return out


def apply(data_root, bundle, plan):
    """Import with the user's choices. plan = {"subs": {id: "new" | "overwrite" | "skip" | <new id>},
    "buttons": {id: existing id | "create"}, "states": {id: existing id}, "lists": {...}, "outputs": {...}}
    -> {"saved": [sub ids], "created_buttons": [...], "added_variables": [...], "added_settings": [...]}"""
    import automation
    from . import buttons, settings, spec_schema, subs
    b = _read(bundle)
    lib = subs.load_all(data_root)
    sub_plan = plan.get("subs") or {}
    sub_map, keep = {}, []
    for s in b["subs"]:
        choice = sub_plan.get(s["id"], "new")
        if choice == "skip":
            if s["id"] not in lib:
                raise ValueError(_("略過的子腳本「{name}」這裡沒有,呼叫它的步驟會失效;請改成匯入", name=s.get('name')))
            continue
        if choice in ("new", "overwrite"):
            if choice == "new" and s["id"] in lib:
                raise ValueError(_("子腳本代號「{id}」這裡已經有了:請選擇覆蓋,或填一個新代號", id=s['id']))
            new_id = s["id"]
        else:
            if not ID.match(choice) or choice in lib:
                raise ValueError(_("新代號「{choice}」不能用(只能小寫英文、數字、底線,且不能和現有的重複)", choice=choice))
            new_id = choice
        sub_map[s["id"]] = new_id
        keep.append(s)
    maps = {"subs": sub_map, "buttons": {}, "states": {}, "lists": {}, "outputs": {}}
    r = refs(keep)
    for kind in ("states", "lists", "outputs"):
        chosen = plan.get(kind) or {}
        for x in sorted(r[kind]):
            if not chosen.get(x):
                raise ValueError(_("請替「{x}」選擇這裡對應的{p2}", x=x, p2={'states': _("狀態"), 'lists': _("清單"), 'outputs': _("輸出")}[kind]))
            maps[kind][x] = chosen[x]
    to_create = []
    for bid in sorted(r["buttons"]):
        c = (plan.get("buttons") or {}).get(bid)
        if not c:
            raise ValueError(_("請替按鈕「{bid}」選擇對應的按鈕,或建立新的", bid=bid))
        if c == "create":
            info = (b.get("buttons") or {}).get(bid)
            if not info:
                raise ValueError(_("分享檔裡沒有按鈕「{bid}」的位置,請改成對應到現有的按鈕", bid=bid))
            new_id = bid if bid not in buttons.load(data_root) else next(
                f"{bid}_{i}" for i in range(2, 1000) if f"{bid}_{i}" not in buttons.load(data_root))
            maps["buttons"][bid] = new_id
            to_create.append((new_id, info))
        else:
            maps["buttons"][bid] = c
    docs = [{**_rewrite(s, maps), "id": sub_map[s["id"]]} for s in keep]

    # variables and settings the sub-scripts need: add the missing ones as declared (before the checks)
    have_vars = automation.variables(data_root)
    new_vars = [v for v in b.get("variables") or [] if v["name"] not in {x["name"] for x in have_vars}]
    decls = settings.load(data_root)
    new_sets = [s for s in b.get("settings") or [] if s["id"] not in decls]
    added = {"vars": False, "sets": False, "buttons": []}
    try:
        if new_vars:
            automation.save_variables(data_root, have_vars + new_vars)
            added["vars"] = True
        if new_sets:
            settings.save(data_root, list(decls.values()) + new_sets)
            added["sets"] = True
        for new_id, info in to_create:                # buttons first: the checks look them up
            if info.get("find") and info.get("image"):
                d = os.path.join(data_root, "meta", "buttons")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, f"{new_id}.png"), "wb") as f:
                    f.write(base64.b64decode(info["image"]))
            keepk = {k: v for k, v in info.items() if k not in ("image", "list", "device", "pos")}
            buttons.save(data_root, {**keepk, "id": new_id, "find": bool(info.get("find") and info.get("image"))})
            added["buttons"].append(new_id)
        # check every sub-script against the spec, with the others of the bundle already in the library
        lib_after = {**lib, **{d["id"]: d for d in docs}}
        for d in docs:
            errs = spec_schema.schema_errors("sub", d)
            if errs:
                raise ValueError(_("子腳本「{name}」:", name=d.get('name')) + _(";").join(f"{e['path']} {e['message']}" for e in errs[:5]))
            import schema as schema_mod
            subs.validate(d, {k: v for k, v in lib_after.items() if k != d["id"]}, schema_mod.load(data_root),
                          {v["name"] for v in automation.variables(data_root)})
    except Exception:
        for bid in added["buttons"]:                  # undo what this import added
            try:
                buttons.delete(data_root, bid)
            except ValueError:
                pass
        if added["vars"]:
            automation.save_variables(data_root, have_vars)
        if added["sets"]:
            settings.save(data_root, list(decls.values()))
        raise
    note = _("匯入自「{p1}」", p1=b.get('from') or _("分享檔"))
    ordered, left = [], list(docs)                     # the ones called first: saving checks that callees exist
    while left:
        ids_left = {d["id"] for d in left}
        ready = [d for d in left if not (refs(d)["subs"] & ids_left - {d["id"]})] or left[:1]
        ordered += ready
        left = [d for d in left if d not in ready]
    for d in ordered:
        subs.save(data_root, {k: v for k, v in d.items() if k != "format"}, note)
    return {"saved": [d["id"] for d in docs], "created_buttons": added["buttons"],
            "added_variables": [v["name"] for v in new_vars], "added_settings": [s["id"] for s in new_sets]}
