"""Operation panel (操作面板): the few settings an end user understands, wired to the real settings underneath.

Consultants define the panel when deploying (<data_root>/meta/panel.json); end users only see and change these
controls, never scripts, states or buttons.

panel.json  {"title", "devices": [emulators shown, in order] (empty = all),
             "blocks": [{"id", "title", "help", "toggle": a toggle control shown in the block's header (optional),
                         "items": [control ids, in order]}],      one block per thing the user thinks about
             "controls": [{"id", "label", "help", "type", "scope": "global" | "device", "bind": {...},
                           "min", "max", "unit", "scale", "options": [{"label", "value"}],
                           "chat": its name in a chat (optional), "chat_off": true = only on the page}]}
The same design is what a paired person may do from a chat bot (server/panel_chat.py).

types:  toggle   on / off
        time     HH:MM
        number   a number (shown in "unit"; stored as value * scale, e.g. minutes -> seconds)
        multi    tick several (options; or "list:<list id>" = the names of a list - that device's if the list is
                 per device -, in the order ticked)
        single   pick one (options; or "list:<list id>"); a number / text setting may also be picked from given options
        action   a big button that does something now (no value): run a schedule, switch a situation, stop

bind kinds:
  {"kind": "schedule", "schedule", "field": "enabled" | "at"}               a schedule's switch or start time (global)
  {"kind": "schedule_device", "schedule"}                                   does this emulator take part (device)
  {"kind": "schedule_arg", "schedule", "param"}                              a parameter of the schedule's sub-script:
                                                                            per emulator (device) or for all (global)
  {"kind": "entry_arg", "script", "situation", "param"}                     a parameter of a situation's entry call
  {"kind": "setting", "setting"}                                            a user setting (automation/settings.py): the
                                                                            design declares it, the value is kept where
                                                                            it runs; the control's type follows it
  action buttons (type "action"; scope "device" = one button per emulator, "global" = one for every emulator):
  {"kind": "act_schedule", "schedule"}                                      run this schedule now
  {"kind": "act_situation", "script", "situation"}                         switch a main script to a situation (and do
                                                                            its entry action, e.g. back to the spot)
  {"kind": "act_stop"}                                                      stop what the emulator is doing now
  {"kind": "act_sub", "sub"}                                                run a sub-script now (one that needs no
                                                                            arguments, e.g. 掃描帳號清單)

A block may instead be a watch widget (監看元件): {"id", "title", "help", "widget": {"kind", ...options}, "items": []}
  devices     how each emulator is doing          options: show_step (the step it is on), show_alerts (its last alerts),
                                                           show_image (a small live picture)
  incidents   the urgent incidents                options: limit, show_frames (the picture of the moment)
  deploy      which main script runs where        options: scripts [ids the users may switch], modes [the modes they
                                                           may choose: off / shadow / live]
  schedules   today's schedules on each emulator  options: schedules [ids; empty = every enabled one]
  list        a list's names on each emulator     options: list [a list id], scan_sub [the sub-script that walks it,
              (characters, places ...)                     "" = no scan button], rename / remove [users may name /
                                                           take out names]; shows the last walk (new / not seen)
  log         what happened lately                options: limit, panel_changes (also the users' own changes)
  chat        通知與指令: the chat bots of this site    options: setup (add a bot / change its token / remove it),
                                                           pair (pair a chat, remove who may give commands)
              (the bots kept where it runs, notify.json; what they may do follows this panel - server/panel_chat.py)
The consultant decides what users see and may change; the server checks every request against the widget.

Every change is logged (<runtime dir>/panel_log.jsonl) with the old and the new value."""
import copy
import json
import os
import re
import time

import automation
import project
from automation import buttons as buttons_mod, schedules, settings as settings_mod, subs as subs_mod

from . import RUNTIME_DIR
from automation import spec
from i18n import N_, _

FILE = os.path.join("meta", "panel.json")
LOG = "panel_log.jsonl"
OLD_LOG = os.path.join("meta", "panel_log.jsonl")     # before it moved to the runtime folder


def log_path():
    """What the people running it changed and did: this computer's, in the runtime folder (never in the design)."""
    return os.path.join(RUNTIME_DIR, LOG)
TYPES = ("toggle", "time", "number", "multi", "single", "action")
ACTS = {"act_schedule": N_("立即執行排程"), "act_sub": N_("立即執行子腳本"), "act_situation": N_("切到主腳本的情境"), "act_stop": N_("停止目前動作")}


BINDS = {"setting": N_("使用者設定"), "schedule": N_("排程的開關或開始時間"), "schedule_device": N_("這台要不要參加排程"),
         "schedule_arg": N_("排程子腳本的參數(舊接法)"), "entry_arg": N_("主腳本情境進入時的參數(舊接法)"), **ACTS}
# the panel control a user setting shows as (a list of free text / numbers has no panel control yet)
SETTING_CONTROL = {"number": "number", "bool": "toggle", "time": "time", "point": "single", "list": "multi"}


def setting_of(c):
    """The user setting a control is wired to (None if it is wired to something else)."""
    b = c.get("bind") or {}
    if b.get("kind") != "setting":
        return None
    s = settings_mod.load().get(b.get("setting"))
    if not s:
        raise ValueError(_("這個控制項接的使用者設定已經不存在,請聯絡導入顧問"))
    return s


WIDGETS = {"devices": N_("裝置狀態"), "incidents": N_("緊急事件"), "deploy": N_("部署開關"), "schedules": N_("排程表"), "log": N_("紀錄"),
           "chat": N_("通知與指令(聊天 Bot)"), "list": N_("清單(帳號、地點…)")}
WIDGET_DEFAULTS = {"devices": {"show_step": True, "show_alerts": False, "show_image": False},
                   "incidents": {"limit": 10, "show_frames": True},
                   "deploy": {"scripts": [], "modes": ["off", "live"]},
                   "schedules": {"schedules": []},
                   "log": {"limit": 20, "panel_changes": True},
                   "chat": {"setup": True, "pair": True},
                   "list": {"list": "", "scan_sub": "", "rename": True, "remove": True}}


def widget_blocks(panel, kind):
    return [b for b in panel.get("blocks") or [] if (b.get("widget") or {}).get("kind") == kind]


def check_widget(data_root, w):
    kind = (w or {}).get("kind")
    if kind not in WIDGETS:
        raise ValueError(_("監看元件的種類不正確"))
    if kind in ("incidents", "log") and not 1 <= int(w.get("limit", 10)) <= 200:
        raise ValueError(_("「{p1}」顯示筆數要在 1~200", p1=_(WIDGETS[kind])))
    if kind == "deploy":
        have = {s["id"] for s in automation.load_all(data_root) if not automation.is_guard(s)}
        if not w.get("scripts") or any(s not in have for s in w["scripts"]):
            raise ValueError(_("「部署開關」請選擇要開放的主腳本"))
        if not w.get("modes") or any(m not in automation.MODES for m in w["modes"]):
            raise ValueError(_("「部署開關」請選擇使用者可以切換的模式"))
    if kind == "list":
        from automation import lists
        if w.get("list") not in lists.load(data_root):
            raise ValueError(_("「清單」請選擇要顯示哪一份清單"))
        if w.get("scan_sub") and w["scan_sub"] not in subs_mod.load_all(data_root):
            raise ValueError(_("「清單」選的掃描子腳本已經不存在"))
    if kind == "schedules":
        have = {s["id"] for s in schedules.load(data_root)}
        if any(s not in have for s in w.get("schedules") or []):
            raise ValueError(_("「排程表」選的排程已經不存在"))


def load(data_root):
    p = os.path.join(data_root, FILE)
    if not os.path.exists(p):
        return {"title": _("操作面板"), "devices": [], "blocks": [], "controls": []}
    with open(p, encoding="utf-8") as f:
        return normalize(json.load(f))


def normalize(panel):
    """Every control sits in exactly one block (an old panel without blocks gets one per schedule); a block on a page
    that is not there goes to the first page."""
    panel.setdefault("devices", [])
    pages = [p for p in panel.get("pages") or [] if isinstance(p, dict) and p.get("id")]
    if pages:
        panel["pages"] = pages
    else:
        panel.pop("pages", None)
    for b in panel.get("blocks") or []:
        if not pages or b.get("page") not in {p["id"] for p in pages}:
            b.pop("page", None)
        if b.get("width") in (None, "", "auto"):
            b.pop("width", None)
    panel.setdefault("controls", [])
    blocks = panel.setdefault("blocks", [])
    ids = {c["id"] for c in panel["controls"]}
    for b in blocks:
        b["items"] = [i for i in b.get("items") or [] if i in ids]
        if b.get("toggle") not in ids:
            b.pop("toggle", None)
    placed = {i for b in blocks for i in b["items"]} | {b.get("toggle") for b in blocks}
    rest = [c for c in panel["controls"] if c["id"] not in placed]
    for c in rest:
        key = c["bind"].get("schedule") or c["bind"].get("script") or "other"
        b = next((x for x in blocks if x.get("_key") == key), None)
        if not b:
            b = {"id": f"b{len(blocks) + 1}", "title": c["label"], "items": [], "_key": key}
            blocks.append(b)
        if c["type"] == "toggle" and c["bind"]["kind"] == "schedule" and not b.get("toggle"):
            b["toggle"], b["title"] = c["id"], c["label"]
        else:
            b["items"].append(c["id"])
    for b in blocks:
        b.pop("_key", None)
    return panel


def source_kinds(panel):
    """The kinds the panel's users may scan for ("<category>/*" = every kind of it); [] = they may not pick sources."""
    import drivers
    have = drivers.kinds()
    out = []
    for k in ((panel.get("sources") or {}).get("kinds") or []):
        out += [x for x in have if x.startswith(k[:-1])] if k.endswith("/*") else [k] if k in have else []
    return list(dict.fromkeys(out))


def save(data_root, panel, check=True):
    src = panel.get("sources")
    if src:
        import drivers
        have = drivers.kinds()
        for k in src.get("kinds") or []:
            if not (k in have or (k.endswith("/*") and any(x.startswith(k[:-1]) for x in have))):
                raise ValueError(_("「使用者可以加入的來源」沒有這種:{k}", k=k))
        if src.get("new_mode", "shadow") not in ("shadow", "live"):
            raise ValueError(_("「使用者可以加入的來源」的開始方式不正確"))
        if not src.get("kinds"):
            panel.pop("sources", None)
    seen_pages = set()
    for pg in panel.get("pages") or []:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(pg.get("id") or "")) or pg["id"] in seen_pages:
            raise ValueError(_("分頁的代號不正確或重複"))
        if not str(pg.get("title") or "").strip():
            raise ValueError(_("每個分頁都要有名稱"))
        seen_pages.add(pg["id"])
    for b in panel.get("blocks") or []:
        if b.get("width") not in (None, "", "auto", "narrow", "wide"):
            raise ValueError(_("區塊「{title}」的寬度不正確", title=b.get('title')))
    panel = normalize(panel)
    for b in panel["blocks"]:
        if b.get("widget"):
            check_widget(data_root, b["widget"])
            b["items"] = []                        # a widget has no controls of its own
            b.pop("toggle", None)
    seen = set()
    for c in panel.get("controls", []):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", c.get("id") or ""):
            raise ValueError(_("控制項「{label}」的代號只能用小寫英文、數字、底線", label=c.get('label')))
        if c["id"] in seen:
            raise ValueError(_("控制項代號「{id}」重複", id=c['id']))
        seen.add(c["id"])
        if not c.get("label"):
            raise ValueError(_("每個控制項都要有名稱"))
        if c.get("type") not in TYPES:
            raise ValueError(_("控制項「{label}」的種類不正確", label=c.get('label')))
        if (c.get("bind") or {}).get("kind") not in BINDS:
            raise ValueError(_("控制項「{label}」還沒設定要接到哪裡", label=c['label']))
        if (c["type"] == "action") != (c["bind"]["kind"] in ACTS):
            raise ValueError(_("「{label}」:動作按鈕要接「{p2}」其中一種,其他種類不能接這些", label=c['label'], p2=_("、").join(_(v) for v in ACTS.values())))
        if c["bind"]["kind"] == "schedule_device" and c.get("scope") != "device":
            raise ValueError(_("「{label}」(這台要不要參加)必須是每台各自的設定", label=c['label']))
        if c["bind"]["kind"] == "setting":
            s = settings_mod.load(data_root).get(c["bind"].get("setting"))
            if not s:
                raise ValueError(_("「{label}」:請選擇要接的使用者設定", label=c['label']))
            want = SETTING_CONTROL.get(s["type"])
            if s["type"] == "list" and (s.get("item", "point") != "point" or not s.get("pick_from")):
                want = None
            if not want:
                raise ValueError(_("「{label}」:使用者設定「{label2}」的種類還不能放在面板上", label=c['label'], label2=s['label']))
            if c.get("type") == "single" and isinstance(c.get("options"), list) and c["options"] and s["type"] in ("number", "text"):
                want = "single"                    # a number / text picked from given choices ("不動作 / 只通知 / ...")
            c["type"] = want                       # the control follows the setting
            c["scope"] = "device" if s.get("scope") == "device" else "global"
            if s.get("pick_from"):
                c["options"] = s["pick_from"]
        if check:                                  # the target must exist (read its value once)
            from drivers.sources import expand
            dev = (expand(panel.get("devices")) or [None])[0] if c.get("scope") == "device" else None
            try:
                value(data_root, c, dev)
            except (ValueError, KeyError, OSError) as e:
                raise ValueError(_("「{label}」接的設定讀不到:{e}", label=c['label'], e=e))
    for c in panel.get("controls", []):
        if not c.get("chat"):
            c.pop("chat", None)
        if not c.get("chat_off"):
            c.pop("chat_off", None)
    from .panel_chat import check as check_chat
    check_chat(panel)
    p = os.path.join(data_root, FILE)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(spec.stamp(panel), f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def _schedule(data_root, sid):
    s = next((x for x in schedules.effective(data_root, RUNTIME_DIR) if x["id"] == sid), None)
    if not s:
        raise ValueError(_("這個控制項接的排程已經不存在,請聯絡導入顧問"))
    return s


def _sub_default(data_root, sub_id, param):
    sub = subs_mod.load_all(data_root).get(sub_id) or {}
    return next((p.get("default") for p in sub.get("params") or [] if p["name"] == param), None)


def list_options(data_root, list_id, device=None):
    from automation import lists
    spec = lists.load(data_root).get(list_id)
    return [{"label": b["label"], "value": {"button": b["id"]}} for b in lists.ordered(data_root, spec, device)] if spec else []


def options(data_root, c, device):
    s = setting_of(c)
    if s is not None:
        return settings_mod.choices(data_root, s, device) or []
    o = c.get("options")
    if isinstance(o, str) and o.startswith("list:"):     # every name of a list (lists.py), in list order
        return list_options(data_root, o[5:], device)
    return o or []


def value(data_root, c, device=None):
    """The current value of a control (for one emulator if it is a device control), as the user sees it."""
    b = c["bind"]
    kind = b["kind"]
    if kind in ACTS:                                 # a button has no value; only check what it points at exists
        if kind == "act_schedule":
            _schedule(data_root, b["schedule"])
        elif kind == "act_sub":
            sub = subs_mod.load_all(data_root).get(b.get("sub"))
            if not sub:
                raise ValueError(_("這個按鈕要執行的子腳本已經不存在,請聯絡導入顧問"))
            if any(p.get("default") is None for p in sub.get("params") or []):
                raise ValueError(_("子腳本「{name}」要填參數,不能直接放在面板上", name=sub['name']))
        elif kind == "act_situation":
            automation.situation(automation.load(data_root, b["script"]), b["situation"])
        return None
    if kind == "setting":
        setting_of(c)
        v = settings_mod.value(data_root, RUNTIME_DIR, b["setting"], device)
        if c["type"] == "number" and v is not None:
            return round(float(v) / float(c.get("scale", 1)), 2)
        return v
    if kind == "schedule":
        return _schedule(data_root, b["schedule"]).get(b["field"])
    if kind == "schedule_device":
        return device in (_schedule(data_root, b["schedule"]).get("devices") or [])
    if kind == "schedule_arg":
        s = _schedule(data_root, b["schedule"])
        v = ((s.get("device_args") or {}).get(device) or {}).get(b["param"]) if c.get("scope") == "device" else None
        if v is None:
            v = (s.get("args") or {}).get(b["param"], _sub_default(data_root, s["sub"], b["param"]))
    elif kind == "entry_arg":
        sc = automation.load(data_root, b["script"])
        sit = automation.situation(sc, b["situation"])
        v = ((automation.enter_call(sit) or {}).get("args") or {}).get(b["param"])
    else:
        raise ValueError(_("不支援的接法「{kind}」", kind=kind))
    if c["type"] == "number" and v is not None:
        return round(float(v) / float(c.get("scale", 1)), 2)
    return v


def _check(data_root, c, device, v):
    t = c["type"]
    if t == "toggle" and not isinstance(v, bool):
        raise ValueError(_("請選擇開或關"))
    if t == "time" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(v)):
        raise ValueError(_("時間要像 20:00"))
    if t == "number":
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(_("請填數字"))
        if c.get("min") is not None and v < float(c["min"]) or c.get("max") is not None and v > float(c["max"]):
            raise ValueError(_("「{label}」要在 {min}~{max} {unit}之間", label=c['label'], min=c.get('min'), max=c.get('max'), unit=c.get('unit', '')))
        return v * float(c.get("scale", 1))
    if t in ("single", "multi"):
        allowed = [json.dumps(o["value"], sort_keys=True) for o in options(data_root, c, device)]
        vs = v if t == "multi" else [v]
        if not isinstance(vs, list) or any(json.dumps(x, sort_keys=True) not in allowed for x in vs):
            raise ValueError(_("選項不正確,請重新整理頁面"))
        if t == "multi" and c.get("min") and len(vs) < int(c["min"]):
            raise ValueError(_("「{label}」至少要選 {min} 個", label=c['label'], min=c['min']))
    return v


def apply(data_root, c, device, v):
    """Change what the control is wired to. -> (old, new) as the user sees them."""
    b = c["bind"]
    kind = b["kind"]
    old = value(data_root, c, device)
    stored = _check(data_root, c, device, v)
    lib = subs_mod.load_all(data_root)
    if kind == "setting":
        s = setting_of(c)
        if s["type"] == "number":
            stored = int(stored) if float(stored).is_integer() else stored
        settings_mod.set_value(data_root, RUNTIME_DIR, s["id"], device, stored)
    elif kind in ("schedule", "schedule_device"):          # kept where it runs, over the design
        s = _schedule(data_root, b["schedule"])
        if kind == "schedule":
            schedules.set_override(data_root, RUNTIME_DIR, s["id"], b["field"], stored)
        else:
            devs = [d for d in s.get("devices") or [] if d != device]
            devs = sorted(devs + [device]) if stored else devs
            if not devs:                         # nobody takes part: switch it off rather than refuse
                schedules.set_override(data_root, RUNTIME_DIR, s["id"], "enabled", False)
                devs = [device]
            schedules.set_override(data_root, RUNTIME_DIR, s["id"], "devices", devs)
    elif kind == "schedule_arg" and project.edition() == "runtime":   # the design is read-only: over it, here
        s = _schedule(data_root, b["schedule"])
        if c.get("scope") == "device":
            da = copy.deepcopy(s.get("device_args") or {})
            da.setdefault(device, {})[b["param"]] = stored
            schedules.set_override(data_root, RUNTIME_DIR, s["id"], "device_args", da)
        else:
            schedules.set_override(data_root, RUNTIME_DIR, s["id"], "args", {**(s.get("args") or {}), b["param"]: stored})
    elif kind == "schedule_arg":
        items = copy.deepcopy(schedules.load(data_root))
        s = next(x for x in items if x["id"] == b["schedule"])
        if c.get("scope") == "device":
            s.setdefault("device_args", {}).setdefault(device, {})[b["param"]] = stored
        else:
            s.setdefault("args", {})[b["param"]] = stored
        schedules.save(data_root, items, lib)
    elif kind == "entry_arg" and project.edition() == "runtime":
        automation.set_entry_arg(b["script"], b["situation"], b["param"], stored)
    elif kind == "entry_arg":
        sc = automation.load(data_root, b["script"])
        sc = {k: x for k, x in sc.items() if k not in ("version", "created", "note")}
        sit = automation.situation(sc, b["situation"])
        call = automation.enter_call(sit)
        if call is None:
            raise ValueError(_("情境「{name}」進入時沒有呼叫子腳本", name=sit.get('name')))
        call.setdefault("args", {})[b["param"]] = stored
        automation.save(data_root, sc, _("操作面板:{label}", label=c['label']))
    new = value(data_root, c, device)
    with open(log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "control": c["id"], "label": c["label"], "device": device,
                            "old": old, "new": new}, ensure_ascii=False, default=str) + "\n")
    return old, new


def act_targets(data_root, c, device, devices):
    """The emulators an action button acts on: the one pressed for, or (global button) every panel emulator - only
    those that take part, for a schedule."""
    targets = [device] if c.get("scope") == "device" else list(devices)
    if c["bind"]["kind"] == "act_schedule":
        part = _schedule(data_root, c["bind"]["schedule"]).get("devices") or []
        targets = [d for d in targets if d in part]
    return targets


def log_action(data_root, c, device, result):
    with open(log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "control": c["id"], "label": c["label"], "device": device,
                            "action": True, "result": result}, ensure_ascii=False, default=str) + "\n")


def history(data_root, limit=50):
    rows = []
    for p in (os.path.join(data_root, OLD_LOG), log_path()):      # the old place first: older entries
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows += [json.loads(x) for x in f if x.strip()]
    return rows[-limit:][::-1]
