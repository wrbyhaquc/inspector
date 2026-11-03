"""Starting the operation panel from what the design already has (面板改造 E5).

catalog() lists what a panel can show or change - the user settings, the schedules, the main scripts' situations,
the sub-scripts a button can run, the variables and the lists - each with what it is now and the block it becomes
on the panel ("add": {"block", "controls"}; the editor gives them fresh ids). drafts() builds whole first versions
from the same things, one per template (TEMPLATES), for an empty panel or a new start."""
import time

import automation
from automation import buttons as buttons_mod, lists as lists_mod, schedules, settings as settings_mod, subs as subs_mod
from i18n import N_, _
from project import word

from . import panel as pm

GROUPS = {"setting": N_("使用者設定"), "schedule": N_("排程"), "situation": N_("情境"), "sub": N_("子腳本"),
          "variable": N_("數值"), "list": N_("清單")}
TEMPLATES = {"full": (N_("完整"), N_("每個排程、使用者設定和情境都放上去,分成總覽、排程、設定、紀錄幾頁")),
             "simple": (N_("精簡"), N_("只有排程的開關、切換情境的按鈕和緊急事件,給現場的人用")),
             "watch": (N_("只看"), N_("每台的狀態、數值、排程表和紀錄,沒有可以改的東西"))}
MANY = 3                                    # how many names a "now" shows before it only counts the rest
EPOCH = (1e9, 4.1e9)                        # a number in here is a moment ("last time" variables), 2001 - 2099


def _show(v, choices=None, data_root=None):
    """A value as the panel's user reads it (a place by its name, a time in seconds since 1970 as a time)."""
    if v is None or v == "" or v == []:
        return "—"
    if isinstance(v, bool):
        return _("開") if v else _("關")
    if isinstance(v, (int, float)) and EPOCH[0] <= v < EPOCH[1]:
        return time.strftime("%m-%d %H:%M", time.localtime(v))
    if isinstance(v, dict) and v.get("button") and not choices:
        b = buttons_mod.load(data_root).get(v["button"]) if data_root else None
        return (b or {}).get("label") or v["button"]
    label = {str(c["value"]): c["label"] for c in choices or []}
    if isinstance(v, list):
        return _("、").join(label.get(str(x), str(x)) for x in v[:MANY]) + (_(" 等 {n} 項", n=len(v)) if len(v) > MANY else "")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return label.get(str(v), str(v))


def _by_device(vals):
    """{device: text} -> one line: the one value they share, or each device's."""
    if not vals:
        return "—"
    if len(set(vals.values())) == 1:
        return next(iter(vals.values()))
    d, v = next(iter(vals.items()))
    return _("每台不同,例如 {d}:{v}", d=d, v=v)


def setting_control(s):
    """The panel control a user setting becomes (None: this kind cannot be on the panel yet)."""
    want = pm.SETTING_CONTROL.get(s.get("type"))
    if s.get("type") == "list" and (s.get("item", "point") != "point" or not s.get("pick_from")):
        want = None
    if not want:
        return None
    c = {"id": "c1", "label": s.get("label") or s["id"], "type": want, "scope": "device" if s.get("scope") == "device" else "global",
         "bind": {"kind": "setting", "setting": s["id"]}}
    if s.get("description"):
        c["help"] = s["description"]
    if s.get("pick_from"):
        c["options"] = s["pick_from"]
    if want == "number":
        c.update({"unit": "", "scale": 1, **{k: s[k] for k in ("min", "max") if s.get(k) is not None}})
    return c


def schedule_controls(s, only_switch=False):
    """A schedule's block: its switch beside the title, then its start time, who takes part and run it now."""
    on = {"id": "c1", "label": s["name"], "type": "toggle", "scope": "global", "bind": {"kind": "schedule", "schedule": s["id"], "field": "enabled"}}
    if only_switch:
        return {"title": s["name"], "toggle": "c1", "items": []}, [on]
    rest = [{"id": "c2", "label": _("開始時間"), "type": "time", "scope": "global", "bind": {"kind": "schedule", "schedule": s["id"], "field": "at"}},
            {"id": "c3", "label": _("這台要參加"), "type": "toggle", "scope": "device", "bind": {"kind": "schedule_device", "schedule": s["id"]}},
            {"id": "c4", "label": _("現在就做"), "type": "action", "scope": "device", "bind": {"kind": "act_schedule", "schedule": s["id"]}}]
    return {"title": s["name"], "toggle": "c1", "items": [c["id"] for c in rest]}, [on, *rest]


def _situation_control(sc, sit, cid="c1"):
    return {"id": cid, "label": sit["name"], "type": "action", "scope": "device",
            "bind": {"kind": "act_situation", "script": sc["id"], "situation": sit["id"]}}


def _widget(kind, **opts):
    return {**pm.WIDGET_DEFAULTS[kind], **opts, "kind": kind}


def _main_scripts(data_root):
    """Main scripts a user can switch: more than one situation."""
    return [sc for sc in automation.load_all(data_root) if not automation.is_guard(sc) and len(sc.get("situations") or []) > 1]


def catalog(data_root, runtime_dir, st):
    """Everything a panel can be made of, by group, with what it is now ("now") and what it becomes ("add");
    "why" says why one cannot be put on the panel (no "add" then)."""
    devices = [d["name"] for d in st.get("devices") or []]
    out = []
    for s in settings_mod.load(data_root).values():
        c = setting_control(s)
        if s.get("scope") == "device" and devices:
            now = _by_device({d: _show(settings_mod.value(data_root, runtime_dir, s["id"], d), settings_mod.choices(data_root, s, d), data_root) for d in devices})
        else:
            now = _show(settings_mod.value(data_root, runtime_dir, s["id"]), settings_mod.choices(data_root, s), data_root)
        it = {"kind": "setting", "id": s["id"], "name": s.get("label") or s["id"], "help": s.get("description"), "now": now}
        if c:
            it["add"] = {"block": {"title": c["label"], "items": ["c1"]}, "controls": [c]}
        else:
            it["why"] = _("這種使用者設定還不能放在面板上")
        out.append(it)
    for s in schedules.effective(data_root, runtime_dir):
        block, controls = schedule_controls(s)
        out.append({"kind": "schedule", "id": s["id"], "name": s["name"],
                    "now": _("{at} · {on} · {n} 台", at=s.get("at") or "—", on=_show(bool(s.get("enabled"))), n=len(s.get("devices") or [])),
                    "add": {"block": block, "controls": controls}})
    where = {}                                      # (script, situation) -> devices in it now
    for d in st.get("devices") or []:
        for sid, x in (d.get("situations") or {}).items():
            where.setdefault((sid, (x or {}).get("id")), []).append(d["name"])
    for sc in _main_scripts(data_root):
        for sit in sc["situations"]:
            here = where.get((sc["id"], sit["id"])) or []
            out.append({"kind": "situation", "id": f"{sc['id']}/{sit['id']}", "name": sit["name"], "group": sc["name"],
                        "now": (_("、").join(here[:MANY]) + (_(" 等 {n} 台", n=len(here)) if len(here) > MANY else "")) if here else _("沒有{device}在這裡", device=word("device")),
                        "add": {"block": {"title": sit["name"], "items": ["c1"]}, "controls": [_situation_control(sc, sit)]}})
    for s in subs_mod.load_all(data_root).values():
        it = {"kind": "sub", "id": s["id"], "name": s["name"], "now": ""}
        if all(p.get("default") is not None for p in s.get("params") or []):
            it["add"] = {"block": {"title": s["name"], "items": ["c1"]}, "controls": [
                {"id": "c1", "label": s["name"], "type": "action", "scope": "device", "bind": {"kind": "act_sub", "sub": s["id"]}}]}
        else:
            it["why"] = _("要填參數,不能直接做成按鈕")
        out.append(it)
    vals = st.get("vars") or {}
    for v in automation.variables(data_root):
        if v.get("scope") == "global":
            now = _show((vals.get("global") or {}).get(v["name"]))
        else:
            now = _by_device({d: _show(((vals.get("device") or {}).get(d) or {}).get(v["name"])) for d in devices})
        out.append({"kind": "variable", "id": v["name"], "name": v.get("label") or v["name"], "now": now,
                    "add": {"block": {"title": v.get("label") or v["name"], "items": [], "widget": _widget("values", vars=[v["name"]])}, "controls": []}})
    for spec in lists_mod.load(data_root).values():
        n = len(lists_mod.ordered(data_root, spec, devices[0] if spec.get("per_device") and devices else None))
        title = spec.get("title") or spec["id"]
        out.append({"kind": "list", "id": spec["id"], "name": title, "now": _("{n} 個名稱", n=n),
                    "add": {"block": {"title": title, "items": [], "widget": _widget("list", list=spec["id"])}, "controls": []}})
    return out


class _Draft:
    """A panel being put together: blocks in order, controls renumbered so every id is new."""

    def __init__(self):
        self.pages, self.blocks, self.controls = [], [], []

    def page(self, pid, title):
        self.pages.append({"id": pid, "title": title})
        return pid

    def add(self, block, controls=(), page=None, width=None):
        ids = {}
        for c in controls:
            ids[c["id"]] = f"c{len(self.controls) + 1}"
            self.controls.append({**c, "id": ids[c["id"]]})
        b = {**block, "id": f"b{len(self.blocks) + 1}", "items": [ids[i] for i in block.get("items") or []]}
        if block.get("toggle"):
            b["toggle"] = ids[block["toggle"]]
        if page:
            b["page"] = page
        if width:
            b["width"] = width
        self.blocks.append(b)

    def panel(self):
        used = {b.get("page") for b in self.blocks}
        pages = [p for p in self.pages if p["id"] in used]
        for b in self.blocks:                       # one page left: no tabs
            if len(pages) < 2:
                b.pop("page", None)
        p = {"blocks": self.blocks, "controls": self.controls}
        if len(pages) > 1:
            p["pages"] = pages
        return pm.pack(p)


def drafts(data_root, runtime_dir):
    """{template: {"pages"?, "blocks", "controls"}} - first versions of the panel from the design."""
    setts = [c for c in (setting_control(s) for s in settings_mod.load(data_root).values()) if c]
    scheds = schedules.load(data_root)
    scripts = _main_scripts(data_root)
    var_names = [v["name"] for v in automation.variables(data_root)]
    all_lists = list(lists_mod.load(data_root).values())

    def situations(d, page=None):
        for sc in scripts:
            cs = [_situation_control(sc, sit, f"c{i + 1}") for i, sit in enumerate(sc["situations"])]
            d.add({"title": _("切換「{name}」", name=sc["name"]), "items": [c["id"] for c in cs]}, cs, page)

    out = {}
    d = _Draft()
    main = d.page("main", _("總覽"))
    d.add({"title": _(pm.WIDGETS["incidents"]), "items": [], "widget": _widget("incidents")}, page=main, width="narrow")
    if var_names:
        d.add({"title": _(pm.WIDGETS["values"]), "items": [], "widget": _widget("values", vars=var_names)}, page=main, width="narrow")
    situations(d, main)
    sp = d.page("schedules", _("排程"))
    for s in scheds:
        d.add(*schedule_controls(s), page=sp, width="narrow")
    if setts:
        cs = [{**c, "id": f"c{i + 1}"} for i, c in enumerate(setts)]
        d.add({"title": _("設定"), "items": [c["id"] for c in cs]}, cs, d.page("settings", _("設定")))
    lp = d.page("log", _("紀錄"))
    for spec in all_lists:
        d.add({"title": spec.get("title") or spec["id"], "items": [], "widget": _widget("list", list=spec["id"])}, page=lp)
    d.add({"title": _(pm.WIDGETS["log"]), "items": [], "widget": _widget("log")}, page=lp)
    out["full"] = d.panel()

    d = _Draft()
    for s in scheds:
        d.add(*schedule_controls(s, only_switch=True), width="third")
    situations(d)
    d.add({"title": _(pm.WIDGETS["incidents"]), "items": [], "widget": _widget("incidents", limit=5)}, width="wide")
    out["simple"] = d.panel()

    d = _Draft()
    d.add({"title": _(pm.WIDGETS["devices"]), "items": [], "widget": _widget("devices", show_image=True)})
    d.add({"title": _(pm.WIDGETS["incidents"]), "items": [], "widget": _widget("incidents")}, width="narrow")
    if var_names:
        d.add({"title": _(pm.WIDGETS["values"]), "items": [], "widget": _widget("values", vars=var_names)}, width="narrow")
    if scheds:
        d.add({"title": _(pm.WIDGETS["schedules"]), "items": [], "widget": _widget("schedules")}, width="narrow")
    d.add({"title": _(pm.WIDGETS["log"]), "items": [], "widget": _widget("log", panel_changes=False)})
    out["watch"] = d.panel()
    return out


def start(data_root, runtime_dir, st):
    return {"groups": {k: _(v) for k, v in GROUPS.items()}, "things": catalog(data_root, runtime_dir, st),
            "templates": [{"id": k, "name": _(n), "desc": _(h)} for k, (n, h) in TEMPLATES.items()],
            "drafts": drafts(data_root, runtime_dir)}
