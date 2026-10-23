"""When a newer version of a pack renames things: carry the values its people set over to the new names, and say which
ones no longer belong to anything.

The runtime folder (project/runtime_data.py) keeps values by the ids of the design: a script's settings by script,
situation and rule id, panel overrides by schedule id, user settings by setting id, the names of a list by list id,
variables by name. A pack.json may say what it renamed since its last version:

    "renamed": {"scripts":    {"old": "new"},
                "situations": {"<script>/old": "new"},       <script> = the script's id in the new version
                "rules":      {"<script>/old": "new"},
                "schedules":  {"old": "new"}, "settings": {"old": "new"}, "lists": {"old": "new"}, "vars": {"old": "new"}}

install (project/pack.py) applies them to the runtime folder after a backup; orphans() then lists the values that
still point at something the design no longer has (they do nothing; the Packs page and "next steps" show them)."""
import atomic
import json
import os
import re
import shutil

KINDS = ("scripts", "situations", "rules", "schedules", "settings", "lists", "vars")


def _json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _dump(p, obj):
    atomic.write_json(p, obj, ensure_ascii=False, indent=1)


def design_ids(design):
    """{kind: set of ids} a pack's design has (read from the files: works for any pack folder, active or not)."""
    meta = os.path.join(design, "meta")
    out = {k: set() for k in KINDS}
    sdir = os.path.join(meta, "scripts")
    for sid in os.listdir(sdir) if os.path.isdir(sdir) else []:
        cur = _json(os.path.join(sdir, sid, "current.json"))
        if not cur:
            continue
        out["scripts"].add(sid)
        doc = _json(os.path.join(sdir, sid, f"v{cur.get('version')}.json"), {})
        for sit in doc.get("situations") or []:
            out["situations"].add(f"{sid}/{sit.get('id')}")
            for r in sit.get("rules") or []:
                out["rules"].add(f"{sid}/{r.get('id')}")
    for kind, f, field, key in (("schedules", "schedules.json", "schedules", "id"),
                                ("settings", "user_settings.json", "settings", "id"),
                                ("lists", "lists.json", "lists", "id"), ("vars", "variables.json", "vars", "name")):
        out[kind] = {x.get(key) for x in (_json(os.path.join(meta, f), {}) or {}).get(field) or []}
    return out


# ---------------- what the runtime folder refers to ----------------
_ADDR = re.compile(r'situations/"([^"]+)"(?:/rules/"([^"]+)")?')


def _layers(rt):
    """(script id, settings.json path) of the script settings changed here (project/overlay.py)."""
    d = os.path.join(rt, "settings", "meta", "scripts")
    return [(sid, os.path.join(d, sid, "settings.json")) for sid in (os.listdir(d) if os.path.isdir(d) else [])
            if os.path.isfile(os.path.join(d, sid, "settings.json"))]


def used(rt):
    """{kind: {id: what refers to it}} - the values this computer keeps, by the design ids they belong to."""
    out = {k: {} for k in KINDS}
    for sid, p in _layers(rt):
        out["scripts"].setdefault(sid, "settings")
        for addr in list(((_json(p, {}) or {}).get("values") or {})) + list((_json(p, {}) or {}).get("removed") or []):
            m = _ADDR.match(addr)
            if m:
                out["situations"].setdefault(f"{sid}/{m.group(1)}", "settings")
                if m.group(2):
                    out["rules"].setdefault(f"{sid}/{m.group(2)}", "settings")
    for sid, sits in (_json(os.path.join(rt, "entry_args.json"), {}) or {}).items():
        out["scripts"].setdefault(sid, "entry_args")
        for sit in sits:
            out["situations"].setdefault(f"{sid}/{sit}", "entry_args")
    for k in ((_json(os.path.join(rt, "schedule_overrides.json"), {}) or {}).get("schedules") or {}):
        out["schedules"].setdefault(k, "schedule_overrides")
    for k in ((_json(os.path.join(rt, "user_settings_values.json"), {}) or {}).get("values") or {}):
        out["settings"].setdefault(k, "user_settings_values")
    for b in ((_json(os.path.join(rt, "buttons.json"), {}) or {}).get("buttons") or []):
        if b.get("list"):
            out["lists"].setdefault(b["list"], "buttons")
    return out


def orphans(design, rt):
    """{kind: [ids]}: values kept here that belong to nothing in the design any more."""
    have = design_ids(design)
    out = {}
    for kind, refs in used(rt).items():
        gone = sorted(k for k in refs if k not in have[kind])
        if gone:
            out[kind] = gone
    return out


# ---------------- renaming ----------------
def apply(rt, renamed):
    """Rewrite the runtime folder for a pack's "renamed" -> how many things were renamed."""
    renamed = {k: dict(v) for k, v in (renamed or {}).items() if k in KINDS and isinstance(v, dict)}
    n = 0
    scripts = renamed.get("scripts") or {}

    # scripts: their settings folder, their entry arguments
    base = os.path.join(rt, "settings", "meta", "scripts")
    for old, new in scripts.items():
        if os.path.isdir(os.path.join(base, old)) and not os.path.exists(os.path.join(base, new)):
            shutil.move(os.path.join(base, old), os.path.join(base, new))
            n += 1
    ep = os.path.join(rt, "entry_args.json")
    ea = _json(ep)
    if ea:
        ea2 = {scripts.get(sid, sid): {(renamed.get("situations") or {}).get(f"{scripts.get(sid, sid)}/{sit}", sit): v
                                       for sit, v in sits.items()} for sid, sits in ea.items()}
        if ea2 != ea:
            _dump(ep, ea2)
            n += 1

    # situations and rules inside the settings of each script
    sits = renamed.get("situations") or {}
    rules = renamed.get("rules") or {}

    def addr(sid, a):
        def sub(m):
            s = sits.get(f"{sid}/{m.group(1)}", m.group(1))
            r = m.group(2) and rules.get(f"{sid}/{m.group(2)}", m.group(2))
            return f'situations/"{s}"' + (f'/rules/"{r}"' if r else "")
        return _ADDR.sub(sub, a)

    for sid, p in _layers(rt):
        d = _json(p, {})
        d2 = {**d, "values": {addr(sid, a): v for a, v in (d.get("values") or {}).items()},
              "removed": [addr(sid, a) for a in d.get("removed") or []],
              "items": [addr(sid, a) for a in d.get("items") or []]}
        if d2 != d:
            _dump(p, d2)
            n += 1

    # keys of files kept by id
    for kind, f, path in (("schedules", "schedule_overrides.json", ("schedules",)),
                          ("settings", "user_settings_values.json", ("values",)),
                          ("vars", "vars.json", ("global",))):
        m = renamed.get(kind) or {}
        p = os.path.join(rt, f)
        d = _json(p)
        if not m or not d:
            continue
        box = d
        for k in path[:-1]:
            box = box.get(k) or {}
        inner = box.get(path[-1]) or {}
        new_inner = {m.get(k, k): v for k, v in inner.items()}
        if new_inner != inner:
            box[path[-1]] = new_inner
            if kind == "vars":                       # per-device variables too
                d["device"] = {dev: {m.get(k, k): v for k, v in vs.items()} for dev, vs in (d.get("device") or {}).items()}
            _dump(p, d)
            n += 1
    lists = renamed.get("lists") or {}
    if lists:
        p = os.path.join(rt, "buttons.json")
        d = _json(p)
        if d:
            d["buttons"] = [{**b, "list": lists.get(b.get("list"), b.get("list"))} if b.get("list") else b
                            for b in d.get("buttons") or []]
            _dump(p, d)
            n += 1
        p = os.path.join(rt, "list_scans.json")
        d = _json(p)
        if d:
            _dump(p, {lists.get(k, k): v for k, v in d.items()})
            n += 1
    return n
