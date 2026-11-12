"""Catalogs (目錄): named ways of getting something done, for people to choose one by name - the places to go and
how each is reached, the rooms to clean and how, the cameras to check and how. Each item is a few sub-script calls
done in order (go into the building, take the lift, walk to the room), under a name and filed in folders; items of
one catalog may use different sub-scripts.

<data_root>/meta/catalogs.json
  {"catalogs": [{"id", "name", "description",
                 "items": [{"id", "name", "folder": "a/b",
                            "calls": [{"sub": sub-script id, "args": {param: value}}, ...],   done in order
                            "here": when,         optional: how to tell it is already there (conditions, like an if)
                            "here_wait": seconds, how long to wait for "here" after the calls (default 15)
                            "note"}]}]}

With "here", call_item first checks it: already there = nothing to do (no second trip, no second fee); after the
calls it waits until it holds - not seen = the item failed (so a caller can try another one).
An old item {"sub", "args"} reads as one call.

The people running it choose one with a user setting of type "item" (pick_from "catalog:<id>", value {"item": id});
the step call_item {"catalog", "item": "<item id>" | {"setting"} | {"param"}} runs the chosen item's call.
An item's arguments are fixed values (a button, x / y, a number, a text, a list) or a user setting - not a parameter:
an item is not inside a sub-script."""
import json
import os
import re
import time

import atomic
from . import spec
from i18n import _

FILE = os.path.join("meta", "catalogs.json")
ID = r"[a-z][a-z0-9_]{0,39}"
MAX_ITEMS = 1000
_cache = {}


def _root(data_root):
    import project
    return data_root or project.data_root()


def load(data_root=None):
    """id -> catalog, in their order (re-read when the file changes)."""
    p = os.path.join(_root(data_root), FILE)
    m = os.path.getmtime(p) if os.path.exists(p) else 0
    hit = _cache.get(p)
    if hit and hit[0] == m:
        return hit[1]
    d = {}
    if m:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        spec.check(raw, _("目錄"))
        d = {c["id"]: {**c, "items": [_norm_item(x) for x in c.get("items") or []]}
             for c in raw.get("catalogs", []) if isinstance(c, dict) and c.get("id")}
    _cache[p] = (m, d)
    return d


HERE_WAIT = 15
MAX_CALLS = 10


def _loops_back(lib, sid, cid, cats):
    """Does sub-script sid (or anything it calls) do an item of catalog cid? (an item calling it would never end)"""
    from . import subs as subs_mod
    seen, todo = set(), [sid]
    while todo:
        s = todo.pop()
        if s in seen or s not in lib:
            continue
        seen.add(s)
        for st in subs_mod.walk(lib[s].get("steps")):
            if st.get("type") == "call":
                todo.append(st.get("sub"))
            elif st.get("type") == "call_item":
                if st.get("catalog") == cid:
                    return True
                todo += [c.get("sub") for x in (cats.get(st.get("catalog")) or {}).get("items") or [] for c in x.get("calls") or []]
    return False


def _norm_item(x):
    """An old item {"sub", "args"} reads as calls: [{"sub", "args"}]."""
    if isinstance(x, dict) and "calls" not in x and x.get("sub"):
        x = {**{k: v for k, v in x.items() if k not in ("sub", "args")}, "calls": [{"sub": x["sub"], "args": x.get("args") or {}}]}
    return x


def item(data_root, cid, iid):
    """One item of a catalog, or None."""
    return next((x for x in (load(data_root).get(cid) or {}).get("items") or [] if x.get("id") == iid), None)


def item_id(v):
    """The item id a value names: "id" or {"item": id} (a user setting's value)."""
    if isinstance(v, dict) and set(v) == {"item"}:
        v = v["item"]
    return v if isinstance(v, str) else None


def subs_of(cat):
    return {c.get("sub") for x in (cat or {}).get("items") or [] for c in x.get("calls") or [] if c.get("sub")}


def sub_id(cid, iid):
    """The id of the sub-script call_item runs for an item (made up from the item, see as_sub)."""
    return f"@{cid}/{iid}"


def as_sub(cat, it):
    """The item as a sub-script: [already there? done] + its calls in order + [wait until there, or fail]."""
    here = it.get("here")
    steps = []
    if here:
        steps.append({"type": "if", "when": here, "else": [],
                      "then": [{"type": "succeed", "text": _("已經在「{name}」了,不用再去", name=it["name"])}]})
    steps += [{"type": "call", "sub": c["sub"], "args": c.get("args") or {}} for c in it.get("calls") or []]
    if here:
        steps += [{"type": "wait_until", "when": here, "timeout": it.get("here_wait", HERE_WAIT), "on_timeout": "continue"},
                  {"type": "if", "when": here, "then": [],
                   "else": [{"type": "fail", "text": _("做完了,但沒看到已經在「{name}」的樣子", name=it["name"])}]}]
    return {"id": sub_id(cat["id"], it["id"]), "name": label(cat, it), "params": [], "steps": steps, "timeout": 3600}


def label(cat, it):
    """"a/b › name" for logs and lists"""
    f = " › ".join(x for x in str(it.get("folder") or "").split("/") if x)
    return f"{f} › {it['name']}" if f else it["name"]


def choices(data_root, cid):
    """[{"label", "value": {"item": id}, "folder"}] for a user setting / a panel control."""
    cat = load(data_root).get(cid) or {}
    return [{"label": x["name"], "value": {"item": x["id"]}, "folder": x.get("folder") or ""} for x in cat.get("items") or []]


def used_by(data_root):
    """sub-script id -> ["目錄「X」項目「Y」", ...]"""
    out = {}
    for cat in load(data_root).values():
        for x in cat.get("items") or []:
            for sid in dict.fromkeys(c.get("sub") for c in x.get("calls") or []):
                out.setdefault(sid, []).append(_("目錄「{name}」項目「{item}」", name=cat["name"], item=x["name"]))
    return out


def buttons_used(data_root):
    """button id -> ["目錄「X」項目「Y」", ...]"""
    out = {}

    def scan(v, where):
        if isinstance(v, dict):
            if isinstance(v.get("button"), str):
                out.setdefault(v["button"], []).append(where)
            for x in v.values():
                scan(x, where)
        elif isinstance(v, list):
            for x in v:
                scan(x, where)
    for cat in load(data_root).values():
        for x in cat.get("items") or []:
            scan([x.get("calls"), x.get("here")], _("目錄「{name}」項目「{item}」", name=cat["name"], item=x["name"]))
    return out


def norm_folder(f):
    return "/".join(x.strip() for x in str(f or "").replace("\\", "/").split("/") if x.strip())[:200]


def validate(data_root, cats, lib=None, states=None):
    """Raise ValueError on the first thing wrong; -> the catalogs as they are stored."""
    from . import subs as subs_mod
    lib = lib if lib is not None else subs_mod.load_all(data_root)
    if states is None:
        import schema as schema_mod
        states = {s["id"]: s for s in (schema_mod.load(data_root).get("states") or [])}
    out, seen = [], set()
    drafts = {c.get("id"): {**c, "items": [_norm_item(x) for x in c.get("items") or []]} for c in cats or [] if isinstance(c, dict)}
    for c in cats or []:
        cid, name = str(c.get("id") or ""), str(c.get("name") or "").strip()
        if not re.fullmatch(ID, cid):
            raise ValueError(_("目錄代號只能用小寫英文、數字、底線,且以英文開頭"))
        if cid in seen:
            raise ValueError(_("目錄代號「{cid}」重複", cid=cid))
        seen.add(cid)
        if not name:
            raise ValueError(_("請替目錄取個名稱"))
        items, ids, names = [], set(), set()
        if len(c.get("items") or []) > MAX_ITEMS:
            raise ValueError(_("目錄「{name}」最多 {n} 項", name=name, n=MAX_ITEMS))
        for x in c.get("items") or []:
            iid, iname = str(x.get("id") or ""), str(x.get("name") or "").strip()
            where = _("目錄「{name}」項目「{item}」", name=name, item=iname or iid)
            if not re.fullmatch(ID, iid) or iid in ids:
                raise ValueError(_("{where}:代號只能用小寫英文、數字、底線,而且不能重複", where=where))
            if not iname or len(iname) > 60:
                raise ValueError(_("{where}:名稱要 1~60 個字", where=where))
            folder = norm_folder(x.get("folder"))
            if (folder, iname) in names:
                raise ValueError(_("{where}:同一個資料夾裡已經有這個名稱", where=where))
            ids.add(iid)
            names.add((folder, iname))
            x = _norm_item(x)
            calls = x.get("calls") or []
            if not isinstance(calls, list) or not calls:
                raise ValueError(_("{where}:至少要有一段做法(呼叫哪個子腳本)", where=where))
            if len(calls) > MAX_CALLS:
                raise ValueError(_("{where}:做法最多 {n} 段", where=where, n=MAX_CALLS))
            out_calls = []
            for k, c in enumerate(calls, 1):
                at = _("{where} 第 {k} 段", where=where, k=k) if len(calls) > 1 else where
                args = c.get("args") or {}
                if not isinstance(args, dict) or any(isinstance(v, dict) and "param" in v for v in args.values()):
                    raise ValueError(_("{where}:參數只能填固定的值或使用者設定", where=at))
                if c.get("sub") not in lib:
                    raise ValueError(_("{where}:請選擇要用哪個子腳本", where=at))
                if _loops_back(lib, c["sub"], cid, drafts):
                    raise ValueError(_("{where}:子腳本「{name}」會再回頭做這個目錄的項目,會一直繞下去", where=at, name=lib[c["sub"]].get("name", c["sub"])))
                # the same checks as a call step (every parameter filled, buttons and settings exist)
                subs_mod._check_steps([{"type": "call", "sub": c["sub"], "args": args}],
                                      {"name": iname, "params": [], "_place": {"label": at + " ", "kind": "catalog"}},
                                      lib, states, "")
                out_calls.append({"sub": c["sub"], "args": args})
            it = {"id": iid, "name": iname, "calls": out_calls}
            if x.get("here"):
                subs_mod._check_when(x["here"], states, _("{where}「怎麼看出已經在那裡」", where=where), None, [])
                it["here"] = x["here"]
                w = x.get("here_wait", HERE_WAIT)
                if not isinstance(w, (int, float)) or isinstance(w, bool) or not 1 <= w <= 600:
                    raise ValueError(_("{where}:等它出現的秒數要在 1~600", where=where))
                if w != HERE_WAIT:
                    it["here_wait"] = w
            if folder:
                it["folder"] = folder
            if str(x.get("note") or "").strip():
                it["note"] = str(x["note"]).strip()[:500]
            items.append(it)
        cat = {"id": cid, "name": name, "items": items}
        if str(c.get("description") or "").strip():
            cat["description"] = str(c["description"]).strip()[:500]
        out.append(cat)
    return out


def save(data_root, cats):
    """Every catalog at once (the page edits them together). Items still chosen somewhere must stay."""
    root = _root(data_root)
    out = validate(root, cats)
    from . import settings
    have = {(c["id"], x["id"]) for c in out for x in c["items"]}
    for s in settings.load(root).values():
        src = str(s.get("pick_from") or "")
        if s.get("type") == "item" and src.startswith("catalog:"):
            cid = src[8:]
            if cid not in {c["id"] for c in out}:
                raise ValueError(_("使用者設定「{label}」還在用目錄「{cid}」", label=s.get("label") or s["id"], cid=cid))
            for v in [s.get("default"), *(s.get("device_default") or {}).values()]:
                iid = item_id(v)
                if iid and (cid, iid) not in have:
                    raise ValueError(_("使用者設定「{label}」的預設值還在用這一項,先改掉預設值再刪", label=s.get("label") or s["id"]))
    doc = spec.stamp({"catalogs": out, "saved": time.time()})
    from . import spec_schema
    spec_schema.must_match("catalogs", doc)
    p = os.path.join(root, FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, doc, ensure_ascii=False, indent=1)
    _cache.pop(p, None)
    return out
