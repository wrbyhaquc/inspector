"""Settings kept beside a versioned document (scripts, the state definitions).

A versioned folder holds v<N>.json (every saved version, never modified) and current.json. Some fields only adjust
how the document is used or shown - where a script runs, a rule's limits, a state's name or shortcut keys - and are
not its design: changing them should not make a new version. They live in settings.json next to the versions:

  - reading (any version) puts the settings on top: the current settings stay when an old version is loaded,
  - saving writes the settings, and a new version only when something else (the design) changed.

A document type says which fields are settings with a list of paths ("devices", "situations[].rules[].cooldown",
"classes[].key", ...); list items are matched by their key field (KEYS) so a setting stays with its rule / class /
region when others are added or moved.

In a runtime (project.edition()) the design is read-only: changed settings go to a layer in the runtime folder
(_layer), read on top of the pack's own."""
import copy
import json
import os

FILE = "settings.json"
KEYS = ("id", "value")          # how a list item is known across versions (the first of these it has)


def _key(item):
    for k in KEYS:
        if isinstance(item, dict) and k in item:
            return json.dumps(item[k], ensure_ascii=False)
    return None


def _walk(doc, path):
    """[(container, field, address)] for one path; address = the item keys on the way (stable across versions)."""
    parts = path.split(".")
    out = [(doc, ())]
    for part in parts[:-1]:
        nxt = []
        many = part.endswith("[]")
        name = part[:-2] if many else part
        for obj, addr in out:
            v = obj.get(name) if isinstance(obj, dict) else None
            if many:
                for it in v or []:
                    k = _key(it)
                    if k is not None:
                        nxt.append((it, addr + (name, k)))
            elif isinstance(v, dict):
                nxt.append((v, addr + (name,)))
        out = nxt
    last = parts[-1]
    return [(obj, last, "/".join(addr + (last,))) for obj, addr in out if isinstance(obj, dict)]


def extract(doc, paths):
    """{"values": {address: value}, "items": [item address]} - every setting the document has, and every item
    (rule, class ...) that can carry settings (so a setting removed from an item is told from a new item)."""
    values, items = {}, set()
    for p in paths:
        for obj, field, addr in _walk(doc, p):
            parent = addr.rsplit("/", 1)[0] if "/" in addr else ""
            items.add(parent)
            if field in obj:
                values[addr] = copy.deepcopy(obj[field])
    return {"values": values, "items": sorted(items)}


def apply(doc, settings, paths):
    """The document with the settings on top. An item the settings know takes every setting field from them (one
    they do not have is removed); an item they do not know (added in a version since) keeps its own."""
    doc = copy.deepcopy(doc)
    values, items = (settings or {}).get("values") or {}, set((settings or {}).get("items") or [])
    for p in paths:
        for obj, field, addr in _walk(doc, p):
            parent = addr.rsplit("/", 1)[0] if "/" in addr else ""
            if addr in values:
                obj[field] = copy.deepcopy(values[addr])
            elif parent in items:
                obj.pop(field, None)
    return doc


def strip(doc, paths, meta=("version", "created", "note", "spec", "format")):
    """The design only: no settings, no version info - two documents with the same design compare equal."""
    doc = copy.deepcopy({k: v for k, v in doc.items() if k not in meta})
    for p in paths:
        for obj, field, _ in _walk(doc, p):
            obj.pop(field, None)
    return json.dumps(doc, ensure_ascii=False, sort_keys=True)


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _layer(folder):
    """A runtime (project.edition()) does not write the design: what its people change is kept on top of the pack's
    settings in <runtime>/settings/<the folder, relative to the design>/settings.json, as the differences only
    ({"values": {address: value}, "removed": [address]}), so a newer pack's defaults still come through for the
    rest. None in a studio."""
    import project
    if project.edition() != "runtime":
        return None
    design = project.data_root()
    if not project.inside(folder, design):
        return None
    return os.path.join(project.runtime_dir(), "settings", os.path.relpath(folder, design), FILE)


def read(folder):
    base = _load(os.path.join(folder, FILE))
    lp = _layer(folder)
    mine = _load(lp) if lp else {}
    if not mine:
        return base
    values = {**(base.get("values") or {}), **(mine.get("values") or {})}
    for addr in mine.get("removed") or []:
        values.pop(addr, None)
    return {"values": values, "items": sorted(set(base.get("items") or []) | set(mine.get("items") or []))}


def _dump(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def write(folder, settings):
    lp = _layer(folder)
    if lp:                                            # a runtime: only what differs from the pack's settings
        base = _load(os.path.join(folder, FILE))
        bv, nv = base.get("values") or {}, settings.get("values") or {}
        _dump(lp, {"values": {a: v for a, v in nv.items() if a not in bv or bv[a] != v},
                   "removed": sorted(a for a in bv if a not in nv),
                   "items": sorted(set(settings.get("items") or []) - set(base.get("items") or []))})
        return
    _dump(os.path.join(folder, FILE), settings)


def mtime(folder):
    ps = [os.path.join(folder, FILE), _layer(folder)]
    return max((os.path.getmtime(p) for p in ps if p and os.path.exists(p)), default=0)
