"""The operation panel in a chat (聊天指令): what a paired person may do from a bot is exactly what the panel lets end
users do - the consultant designs it once (操作面板設計), the page and the chat follow the same design and the same
server checks (server/panel.py). Nothing here is about one project.

Command names: a control's "chat" name if the consultant set one, else its label - or "<block title> <label>" when two
controls share a label. A control with "chat_off": true is only on the page; a stop button needs none (停下來 /
繼續 are always there).
  <name>                         show the value (every emulator's, for a per-emulator control) / a button: ask which one
  <name> [emulator] <value>      change it (asks 確認 first, showing old -> new)
  <name> [emulator | 全部]        a button: press it (asks 確認 first; a stop button does not ask)
  選單 [block]                    the panel's blocks as buttons; a block: its values and its buttons
Watch widgets become read-only commands: 排程 (today's schedules), 緊急事件, 紀錄, 部署 (and 部署 <script> <emulator>
<mode>, as far as the widget allows)."""
import json
import re

import automation
from drivers.sources import label as L

from . import panel as pm
from i18n import N_, _

TRUE = {N_("開"), "on", N_("是"), N_("要"), "true", "1", N_("啟用"), N_("打開")}
FALSE = {N_("關"), "off", N_("否"), N_("不要"), "false", "0", N_("停用"), N_("關閉")}
WIDGET_CMDS = {"schedules": N_("排程"), "incidents": N_("緊急事件"), "log": N_("紀錄"), "deploy": N_("部署")}


def entries(panel):
    """[{"name", "control", "block"}] - every chat command the panel gives, in the panel's order."""
    ctl = {c["id"]: c for c in panel.get("controls") or []}
    order = []
    for b in panel.get("blocks") or []:
        if b.get("widget"):
            continue
        for i in ([b["toggle"]] if b.get("toggle") else []) + list(b.get("items") or []):
            if i in ctl and not ctl[i].get("chat_off") and ctl[i]["bind"].get("kind") != "act_stop":   # 停下來 is built in
                order.append((ctl[i], b))
    count = {}
    for c, _x in order:
        count[c["label"]] = count.get(c["label"], 0) + 1
    out = []
    for c, b in order:
        name = (c.get("chat") or "").strip() or (c["label"] if count[c["label"]] == 1 or c.get("id") == b.get("toggle")
                                                 else f"{b['title']} {c['label']}")
        out.append({"name": name, "control": c, "block": b, "also": [f"{b['title']} {c['label']}"]})
    return out


def widget_names(panel):
    """The widget commands to show (in the current language)."""
    return [_(WIDGET_CMDS[k]) for k in WIDGET_CMDS if pm.widget_blocks(panel, k)]


def widget_cmds(panel):
    on = [k for k in WIDGET_CMDS if pm.widget_blocks(panel, k)]
    return {**{WIDGET_CMDS[k]: k for k in on}, **{_(WIDGET_CMDS[k]).lower(): k for k in on}}   # typed in any case


def check(panel):
    """Chat names must not clash with each other or with the built-in commands (server/panel.py save calls this)."""
    from notify.commands import VERBS
    seen = {}
    builtin = set(VERBS) | set(WIDGET_CMDS.values()) | {_(v) for v in WIDGET_CMDS.values()} | {"選單", "面板", _("選單"), _("面板"), "menu"}   # i18n: keep
    for e in entries(panel):
        n = e["name"]
        if n.split()[0].lower() in builtin:
            raise ValueError(_("「{label}」在聊天裡的名稱「{n}」跟內建指令重複,請在「聊天名稱」改一個", label=e['control']['label'], n=n))
        if n in seen:
            raise ValueError(_("「{label}」和「{p2}」在聊天裡都叫「{n}」,請改其中一個的聊天名稱", label=e['control']['label'], p2=seen[n], n=n))
        seen[n] = e["control"]["label"]


def help_lines(panel):
    lines = []
    for e in entries(panel):
        c = e["control"]
        dev = (_(" [機台|全部]") if c["type"] == "action" else _(" [機台]")) if c.get("scope") == "device" else ""
        what = {"toggle": _(" 開/關"), "time": _(" 時間"), "number": _(" 數字{p1}", p1=c.get('unit') or ''), "single": _(" 選項"), "multi": _(" 選項、選項")}
        lines.append(f"{e['name']}{dev}" + ("" if c["type"] == "action" else what.get(c["type"], "")))
    return lines


def show(data_root, c, v, device=None):
    """A control's value as the user reads it."""
    t = c["type"]
    if v is None:
        return _("(未設定)")
    if t == "toggle":
        return _("開") if v else _("關")
    if t == "number":
        return f"{v:g}{c.get('unit') or ''}" if isinstance(v, (int, float)) else str(v)
    if t in ("single", "multi"):
        opts = pm.options(data_root, c, device)
        lab = {json.dumps(o["value"], sort_keys=True): o["label"] for o in opts}
        vs = v if isinstance(v, list) else [v]
        names = [lab.get(json.dumps(x, sort_keys=True), str(x)) for x in vs]
        return _("、").join(names) if names else _("(都沒選)")
    return str(v)


def parse(data_root, c, device, text):
    """What the user typed -> the value the panel takes."""
    t, s = c["type"], text.strip()
    if t == "toggle":
        if s.lower() in TRUE or s.lower() in {_(x).lower() for x in TRUE}:
            return True
        if s.lower() in FALSE or s.lower() in {_(x).lower() for x in FALSE}:
            return False
        raise ValueError(_("請打「開」或「關」"))
    if t == "time":
        m = re.fullmatch(r"(\d{1,2})[:：](\d{2})", s)
        if not m:
            raise ValueError(_("時間要像 20:00"))
        return f"{int(m[1]):02d}:{m[2]}"
    if t == "number":
        try:
            return float(s)
        except ValueError:
            raise ValueError(_("請打數字")) from None
    if t in ("single", "multi"):
        opts = pm.options(data_root, c, device)

        def one(x):
            hit = [o for o in opts if o["label"] == x] or [o for o in opts if x and x.lower() in o["label"].lower()]
            if len(hit) != 1:
                names = _("、").join(o["label"] for o in opts[:20])
                raise ValueError((_("找不到「{x}」", x=x) if not hit else _("「{x}」符合好幾個", x=x)) + _("。可以選:{names}", names=names))
            return hit[0]["value"]
        if t == "single":
            return one(s)
        return [one(x) for x in re.split(r"[、,，\s]+", s) if x]
    raise ValueError(_("這個項目不能在聊天裡改"))


class PanelChat:
    """One chat command against the panel. env: what the server does for it (see server/app.py _ChatActions)."""

    def __init__(self, data_root, env):
        self.root, self.env = data_root, env

    def _find(self, panel, text):
        """The command the text starts with (the longest name wins) -> (entry, the rest)."""
        best = None
        for e in entries(panel):
            for n in [e["name"]] + e["also"]:
                if (text == n or text.startswith(n + " ")) and (not best or len(n) > best[2]):
                    best = (e, text[len(n):].strip(), len(n))
        return best

    def _split_device(self, c, rest):
        """A per-emulator control: the first word may name the emulator."""
        if c.get("scope") != "device" or not rest:
            return None, rest
        word, _x, more = rest.partition(" ")
        try:
            devs = self.env.find_devices(word)
        except ValueError as e:
            from notify.commands import Ambiguous
            if isinstance(e, Ambiguous):                                   # it names emulators, but which one?
                raise
            return None, rest
        return (devs[0], more.strip()) if len(devs) == 1 else (None, rest)

    def run(self, text, by):
        """-> None (not a panel command) or {"text", "buttons"?, "ask"?: (question, do)}."""
        panel = pm.load(self.root)
        w = widget_cmds(panel)
        head, _x, arg = text.partition(" ")
        if head in ("選單", "面板", "menu", _("選單"), _("面板")):   # i18n: keep
            return self.menu(panel, arg.strip())
        if head in w or head.lower() in w:
            return self.widget(panel, w.get(head) or w[head.lower()], arg.strip(), by)
        hit = self._find(panel, text)
        if not hit:
            return None
        e, rest, _x = hit
        c = e["control"]
        device, value = self._split_device(c, rest)
        devices = self.env.devices()
        if c["type"] == "action":
            return self.press(e, device, value, devices, by)
        if not value:                                                # show it
            if c.get("scope") == "device":
                ds = [device] if device else devices
                lines = [f"{L(n)}:{show(self.root, c, pm.value(self.root, c, n), n)}" for n in ds]
                return {"text": f"{e['name']}\n" + "\n".join(lines), "buttons": self._choices(e, device) if device else None}
            return {"text": f"{e['name']}:{show(self.root, c, pm.value(self.root, c))}", "buttons": self._choices(e, None)}
        if c.get("scope") == "device" and not device:
            return {"text": _("「{name}」每台各自設定,要改哪一台?", name=e['name']),
                    "buttons": self._rows([(L(n), f"cmd:{e['name']} {n} {value}") for n in devices])}   # i18n: keep
        new = parse(self.root, c, device, value)
        old = show(self.root, c, pm.value(self.root, c, device), device)
        pm._check(self.root, c, device, new)                         # refuse a bad value now, not after 確認
        new_s = show(self.root, c, new, device)
        where = _(" {p1} 的", p1=L(device)) if device else ""

        def do():
            o, n = pm.apply(self.root, c, device, new)
            self.env.log_panel(c, device, by)
            return _("已改好:{where}{name} {p3} → {p4}", where=where, name=e['name'], p3=show(self.root, c, o, device), p4=show(self.root, c, n, device))
        return {"ask": (_("確定把{where}「{name}」從 {old} 改成 {new_s}?", where=where, name=e['name'], old=old, new_s=new_s), do)}

    def _rows(self, buttons, per=4):
        return [buttons[i:i + per] for i in range(0, min(len(buttons), 20), per)]

    def _choices(self, e, device):
        c = e["control"]
        pre = f"cmd:{e['name']} {device + ' ' if device else ''}"   # i18n: keep
        if c["type"] == "toggle":
            return [[(_("開"), pre + _("開")), (_("關"), pre + _("關"))]]
        if c["type"] == "single":
            opts = pm.options(self.root, c, device)
            return self._rows([(o["label"], pre + o["label"]) for o in opts]) if len(opts) <= 20 else None
        return None

    def press(self, e, device, extra, devices, by):
        c = e["control"]
        if c.get("scope") == "device" and not device:
            tg = [n for n in devices if pm.act_targets(self.root, c, n, devices)]
            if not tg:
                return {"text": _("沒有機台可以「{name}」", name=e['name'])}
            if extra in ("全部", "all", "*", _("全部")):                             # i18n: keep; every emulator it can act on, one 確認
                do_all = lambda: chr(10).join(self.env.panel_act(c, n, by) for n in tg)
                if c["bind"]["kind"] == "act_stop":
                    return {"text": do_all()}
                return {"ask": (_("確定現在在 {p1}「{name}」?", p1=_("、").join(map(L, tg)), name=e['name']), do_all)}
            btns = [(L(n), f"cmd:{e['name']} {n}") for n in tg] + ([(_("全部"), f"cmd:{e['name']} 全部")] if len(tg) > 1 else [])   # i18n: keep
            return {"text": _("「{name}」要做哪一台?", name=e['name']), "buttons": self._rows(btns)}
        if extra:
            return {"text": _("「{name}」是按鈕,只要打「{name2}{p3}」", name=e['name'], name2=e['name'], p3=_(" 機台") if c.get('scope') == 'device' else '')}
        targets = pm.act_targets(self.root, c, device, devices)
        if not targets:
            return {"text": _("沒有機台可以「{name}」", name=e['name'])}
        do = lambda: self.env.panel_act(c, device, by)
        if c["bind"]["kind"] == "act_stop":                           # stopping never waits for 確認
            return {"text": do()}
        return {"ask": (_("確定現在在 {p1}「{name}」?", p1=_("、").join(map(L, targets)), name=e['name']), do)}

    def menu(self, panel, which):
        blocks = [b for b in panel.get("blocks") or []]
        w = widget_cmds(panel)
        if not which:
            btns = []
            for b in blocks:
                k = (b.get("widget") or {}).get("kind")
                if k:
                    if k in WIDGET_CMDS and WIDGET_CMDS[k] in w:
                        btns.append((b["title"], f"cmd:{WIDGET_CMDS[k]}"))   # i18n: keep
                    elif k == "devices":
                        btns.append((b["title"], "cmd:狀態"))   # i18n: keep
                else:
                    btns.append((b["title"], f"cmd:選單 {b['title']}"))   # i18n: keep
            return {"text": _("{p1}:按一個看看", p1=panel.get('title') or _("操作面板")), "buttons": self._rows(btns, 3)}
        b = next((x for x in blocks if x["title"] == which and not x.get("widget")), None)
        if not b:
            return {"text": _("沒有「{which}」這個區塊。傳「選單」看有哪些", which=which)}
        lines, btns = [b["title"] + (f":{b['help']}" if b.get("help") else "")], []
        devices = self.env.devices()
        for e in entries(panel):
            if e["block"]["id"] != b["id"]:
                continue
            c = e["control"]
            try:
                if c["type"] == "action":
                    btns.append((c["label"], f"cmd:{e['name']}"))   # i18n: keep
                elif c.get("scope") == "device":
                    lines.append(f"· {c['label']}:" + _(";").join(f"{L(n)} {show(self.root, c, pm.value(self.root, c, n), n)}" for n in devices))
                else:
                    lines.append(f"· {c['label']}:{show(self.root, c, pm.value(self.root, c))}")
            except (ValueError, KeyError, OSError) as ex:
                lines.append(_("· {label}:讀不到({ex})", label=c['label'], ex=ex))
        names = [e["name"] for e in entries(panel) if e["block"]["id"] == b["id"] and e["control"]["type"] != "action"]
        if names:
            lines.append(_("要改的話打「{p1} …」,例如傳「{p2}」看怎麼改", p1=names[0], p2=names[0]))
        return {"text": "\n".join(lines), "buttons": self._rows(btns, 3) if btns else None}

    def widget(self, panel, kind, arg, by):
        if kind == "deploy":
            return self.deploy(panel, arg, by)
        data = self.env.widget_data(kind)
        if kind == "schedules":
            rows = [f"{r['name']}" + (f" {r['at']}" if r.get("at") else "") + (_("(停用)") if not r.get("enabled", True) else "") + ":"
                    + (_(";").join(f"{L(n)} {v['text']}" for n, v in r["devices"].items()) or "—") for r in data.get("rows") or []]
            return {"text": _("今天的排程\n") + ("\n".join(rows) or _("沒有"))}
        if kind == "incidents":
            rows = [f"{self.env.when(x.get('start'))} {L(x['device'])} {_("、").join(x.get('triggers') or [])}"
                    + (_(" (處理中)") if x.get("status") == "open" or not x.get("end") else "") for x in data.get("items") or []]
            return {"text": _("緊急事件\n") + ("\n".join(rows) or _("沒有"))}
        if kind == "log":
            rows = [f"{self.env.when(r['t'])} {L(r.get('device')) or ''} {r['text']}".replace("  ", " ") for r in data.get("rows") or []]
            return {"text": _("最近發生的事\n") + ("\n".join(rows) or _("沒有"))}
        return {"text": _("這個在聊天裡還看不到")}

    def deploy(self, panel, arg, by):
        w = {**pm.WIDGET_DEFAULTS["deploy"], **(pm.widget_blocks(panel, "deploy")[0]["widget"])}
        scripts = {s["id"]: s for s in automation.load_all(self.root) if s["id"] in w["scripts"]}
        devices = self.env.devices()
        if not arg:
            lines = [f"{s['name']}:" + _(";").join(f"{L(n)} {automation.mode_label(automation.mode_for(s, n))}" for n in devices)
                     for s in scripts.values()]
            modes = "/".join(automation.mode_label(m) for m in w["modes"])
            return {"text": _("部署\n") + "\n".join(lines) + _("\n要改的話打「部署 <主腳本> <機台> <{modes}>」", modes=modes)}
        parts = arg.split()
        if len(parts) < 3:
            return {"text": _("例如「部署 {script} A01 {mode}」", script=next((s["name"] for s in scripts.values()), _("主腳本")),
                                 mode=automation.mode_label("live"))}
        sname, dev, mode = " ".join(parts[:-2]), parts[-2], parts[-1]
        sc = [s for s in scripts.values() if s["name"] == sname] or [s for s in scripts.values() if sname in s["name"]]
        if len(sc) != 1:
            return {"text": _("找不到可以切換的主腳本「{sname}」:{p2}", sname=sname, p2=_("、").join(s['name'] for s in scripts.values()))}
        devs = self.env.find_devices(dev)
        m = next((k for k in w["modes"] if automation.mode_label(k) == mode or k == mode or mode in automation.mode_label(k)), None)
        if len(devs) != 1 or not m:
            return {"text": _("模式可以選:{p1}", p1='/'.join(automation.mode_label(k) for k in w['modes']))}
        block = pm.widget_blocks(panel, "deploy")[0]["id"]
        do = lambda: self.env.panel_deploy(block, sc[0]["id"], devs[0], m)
        return {"ask": (_("確定把 {p1} 的「{name}」改成「{p3}」?", p1=L(devs[0]), name=sc[0]['name'], p3=automation.mode_label(m)), do)}
