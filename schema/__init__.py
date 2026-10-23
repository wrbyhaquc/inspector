"""State definitions (label schema): the single source of truth for what the models learn.

Stored in <data_root>\\meta\\states\\ :
  v<N>.json      every saved version (never modified)
  current.json   {"version": N}

Every consumer (labeler rules, review questions, UI crops/overlays, later training heads) reads the
current version, and every labels/model output records which version it was made with.

A state may be for some sources only: "sources": [source id | "#tag"] (a greenhouse's states on the greenhouse
camera). On any other source it is not looked at: "hidden" if it has that class, else no value (not_here())."""
import hashlib
import json
import os
import re
import time
from i18n import _


TYPES = {"class", "ratio", "number", "gallery"}   # number: a value read from the screen (unit, min, max)
SOURCES = {"rule", "gallery", "manual"}      # the platform's own; any other kind = a plugin's label source (checked below)


def _dir(data_root):
    return os.path.join(data_root, "meta", "states")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def history(data_root):
    d = _dir(data_root)
    if not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        m = re.fullmatch(r"v(\d+)\.json", f)
        if m:
            s = _read(os.path.join(d, f))
            out.append({"version": s["version"], "created": s.get("created"), "note": s.get("note", ""),
                        "states": len(s.get("states", []))})
    return sorted(out, key=lambda x: x["version"])


# not the design (what the labels and the model depend on): changing only these saves no new version
SETTINGS = ("states[].name", "states[].description", "states[].review", "states[].judge", "states[].sources",
            "states[].classes[].name",
            "states[].classes[].color", "states[].classes[].key", "states[].rois[].name")


def load(data_root, version=None):
    """Current (or a given) schema version, with the current settings on top (meta/states/settings.json). A new
    project starts with no states (version 1, empty)."""
    from project import overlay
    d = _dir(data_root)
    cur = os.path.join(d, "current.json")
    if not os.path.exists(cur):
        return save(data_root, {"states": []}, note=_("新專案"))
    if version is None:
        version = _read(cur)["version"]
    return overlay.apply(_read(os.path.join(d, f"v{int(version)}.json")), overlay.read(d), SETTINGS)


def settings_mtime(data_root):
    from project import overlay
    return overlay.mtime(_dir(data_root))


def validate(schema):
    import project
    W, H = project.screen()
    ids = set()
    for s in schema.get("states", []):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", s.get("id", "")):
            raise ValueError(_("狀態代號「{id}」只能用小寫英文、數字、底線,且以英文開頭", id=s.get('id')))
        if s["id"] in ids:
            raise ValueError(_("狀態代號重複:{id}", id=s['id']))
        ids.add(s["id"])
        if s.get("type") not in TYPES:
            raise ValueError(_("{id}:類型必須是 {p2}", id=s['id'], p2=', '.join(sorted(TYPES))))
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(s.get("source", {}).get("kind") or "")):
            raise ValueError(_("{id}:標籤來源必須是 {p2},或專案外掛提供的來源", id=s['id'], p2=', '.join(sorted(SOURCES))))
        if s.get("judge", "auto") not in ("auto", "model", "rule"):
            raise ValueError(_("{id}:判斷方式要是 自動 / 只用模型 / 只用規則", id=s['id']))
        if "sources" in s and not (isinstance(s["sources"], list) and s["sources"]
                                   and all(isinstance(k, str) and re.fullmatch(r"#?[\w\-.]{1,40}", k) for k in s["sources"])):
            raise ValueError(_("{id}:「只用在這些來源」要是來源代號或 #標籤;都不用就拿掉這個設定", id=s['id']))
        if s["type"] == "number":
            lo, hi = s.get("min"), s.get("max")
            if any(v is not None and not isinstance(v, (int, float)) for v in (lo, hi)) or (lo is not None and hi is not None and lo > hi):
                raise ValueError(_("{id}:數值的最小值、最大值要是數字,而且最小值不能大於最大值", id=s['id']))
            if len(str(s.get("unit") or "")) > 10:
                raise ValueError(_("{id}:單位最多 10 個字", id=s['id']))
        if s["type"] == "class":
            cls = s.get("classes") or []
            if len(cls) < 2:
                raise ValueError(_("{id}:至少要有兩個類別", id=s['id']))
            keys = [c.get("key") for c in cls if c.get("key")]
            if len(keys) != len(set(keys)):
                raise ValueError(_("{id}:類別的快速鍵重複", id=s['id']))
        roi_ids = set()
        for r in s.get("rois", []):
            box = r.get("box")
            if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, int) for v in box)):
                raise ValueError(_("{id}/{id2}:範圍必須是 4 個整數 [x, y, 寬, 高]", id=s['id'], id2=r.get('id')))
            x, y, w, h = box
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
                raise ValueError(_("{id}/{id2}:範圍超出 {W}×{H} 畫面", id=s['id'], id2=r.get('id'), W=W, H=H))
            if r.get("id") in roi_ids:
                raise ValueError(_("{id}:範圍代號重複 {id2}", id=s['id'], id2=r.get('id')))
            roi_ids.add(r.get("id"))
    from labeler import generic
    from project.plugins import registry
    reg = registry()
    for s in schema.get("states", []):
        src = s.get("source", {})
        if src.get("kind") == "gallery":
            from labeler import gallery
            gallery.validate(s)
        elif src.get("kind") not in ("rule", "manual") and not reg.get("label_source", src.get("kind")):
            raise ValueError(_("{id}:「{kind}」標註來源要由專案的外掛提供,這個專案沒有", id=s['id'], kind=src.get('kind')))
        if src.get("kind") != "rule":
            continue
        if generic.is_generic(s):
            generic.validate(s)
        elif not reg.get("rule", src.get("rule")):       # a rule type a plugin of the project provides
            raise ValueError(_("{id}:請選擇規則種類(顏色比例、參考圖比對,或專案外掛提供的規則)", id=s['id']))
    keys = [c["key"] for s in schema["states"] if s.get("review", {}).get("enabled")
            for c in s.get("classes", []) if c.get("key")]
    if len(keys) != len(set(keys)):
        raise ValueError(_("人工確認的快速鍵在不同狀態之間重複了"))


def not_here(states, device, expand=None):
    """{state id: the value it has on this device} for the states that are for other sources only ("sources"):
    "hidden" when the state has that class, else None (not known here). expand: ids / "#tag" -> ids."""
    if expand is None:
        from drivers.sources import expand
    out = {}
    for s in states:
        if s.get("sources") and device not in expand(s["sources"]):
            out[s["id"]] = "hidden" if any(c.get("value") == "hidden" for c in s.get("classes") or []) else None
    return out


def save(data_root, schema, note=""):
    """A new version - unless only SETTINGS changed: then just those (same version, nothing to relabel)."""
    from project import overlay
    validate(schema)
    d = _dir(data_root)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, "current.json")):
        cur = load(data_root)
        overlay.write(d, overlay.extract({"states": schema["states"]}, SETTINGS))
        if overlay.strip(cur, SETTINGS) == overlay.strip({"states": schema["states"]}, SETTINGS):
            return {**load(data_root), "settings_only": True}
    else:
        overlay.write(d, overlay.extract({"states": schema["states"]}, SETTINGS))
    versions = [h["version"] for h in history(data_root)]
    v = (max(versions) if versions else 0) + 1
    out = {"version": v, "created": time.time(), "note": note, "states": schema["states"]}
    _write(os.path.join(d, f"v{v}.json"), out)
    _write(os.path.join(d, "current.json"), {"version": v})
    return out


def state(schema, state_id):
    return next((s for s in schema["states"] if s["id"] == state_id), None)


def roi(schema, state_id, roi_id):
    s = state(schema, state_id)
    return next((r["box"] for r in (s or {}).get("rois", []) if r["id"] == roi_id), None) if s else None


def params_hash(schema, state_ids):
    """Stable hash of what the screen rules depend on (rois + rule params) -> rule cache key."""
    parts = [{"id": s["id"], "rois": s.get("rois"), "source": s.get("source")}
             for s in schema["states"] if s["id"] in state_ids]
    return hashlib.md5(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:10]
