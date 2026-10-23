"""Commands from chat (雙向指令): what people may type to a bot channel (notify/bots.py), or press under a
notification, and who may.

Runs inside the web server (it does what the pages do, through the same functions: Actions). For every enabled bot
channel in notify.json a listener thread keeps a connection out to the chat service and reconnects on its own.

Who may: only people who paired. The page shows a pairing code (6 digits, 10 minutes); whoever sends it in a chat
the bot is in is added to that channel's allowed list, and that chat becomes where its notifications go.
Everything from anyone else is ignored. <runtime dir>/notify_access.json {channel id: {"allowed": [{"id", "name"}],
"chat", "chat_name"}}; every command is written to <runtime dir>/commands.jsonl.

Commands: a few built in, for safety and to look (Chinese or English; device names may be shortened, e.g. A01):
  說明 help · 狀態 status · 畫面 <裝置> screen · 停下來 [裝置|#標籤|全部] stop (cancel what it does, nothing acts)
  暫停 [裝置|#標籤|全部] pause (hold it where it is) · 繼續 [裝置|#標籤|全部] resume
Everything else comes from the operation panel (server/panel_chat.py through Actions.panel_command): what end users
may change or press there, and nothing more. Stopping never asks; the rest asks 確認 / 取消 first.
Button payloads too long for a chat service (Telegram: 64 bytes) are kept here and sent as a short token."""
import atomic
import json
import os
import random
import re
import threading
import time
from i18n import N_, _

ACCESS = "notify_access.json"
LOG = "commands.jsonl"
PAIR_SECONDS = 600
CONFIRM_SECONDS = 120
HELP = (N_("隨時可以傳(機台名稱可以只打一部分,例如 A01):\n選單 · 狀態 · 畫面 <機台> · 停下來 [機台|#標籤|全部] · 暫停 [機台|#標籤|全部] · 繼續 [機台|#標籤|全部]"))
TOKEN_BYTES = 60
VERBS = {"help": "help", "說明": "help", "幫助": "help", "?": "help", "指令": "help",
         "status": "status", "狀態": "status",
         "stop": "hold", "停下來": "hold", "停止": "hold", "pause": "pause", "暫停": "pause",
         "resume": "resume", "繼續": "resume", "恢復": "resume",
         "畫面": "screen", "看畫面": "screen", "screen": "screen",
         # 简体中文
         "说明": "help", "帮助": "help", "状态": "status", "停下来": "hold", "暂停": "pause", "继续": "resume",
         "恢复": "resume", "画面": "screen", "看画面": "screen"}


def match_devices(names, arg):
    """The devices (ids) a (shortened) id or name means; 全部 = every one."""
    from drivers.sources import expand, label
    if not arg or arg in ("全部", "all", "*", _("全部")):
        return list(names)
    if arg.startswith("#"):                               # every source with that tag
        hit = [n for n in expand([arg]) if n in names]
        if not hit:
            raise ValueError(_("沒有標籤「{p1}」的機台", p1=arg[1:]))
        return hit
    a = arg.lower()
    exact = [n for n in names if a in (n.lower(), label(n).lower())]
    if exact:
        return exact
    part = [n for n in names if a in n.lower() or a in label(n).lower()]
    if len(part) == 1:
        return part
    if part:
        raise Ambiguous(_("「{arg}」符合好幾台:{p2},請打完整一點", arg=arg, p2=_("、").join(label(p) for p in part)))
    raise ValueError(_("找不到「{arg}」", arg=arg))


def _read(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(p, obj):
    atomic.write_json(p, obj, ensure_ascii=False, indent=1)


def access(runtime_dir):
    return _read(os.path.join(runtime_dir, ACCESS), {})


def chat_of(runtime_dir, cid):
    return (access(runtime_dir).get(cid) or {}).get("chat")


def notify_buttons(ev):
    """Buttons under a notification: stop that device / see its screen; an urgent one also stop everything."""
    rows = []
    if ev.get("device"):
        rows.append([(_("🛑 停下來"), f"cmd:停下來 {ev['device']}"), (_("看畫面"), f"cmd:畫面 {ev['device']}")])   # i18n: keep (button commands)
    if ev.get("kind") == "urgent":
        rows.append([(_("🛑 全部停下來"), "cmd:停下來 全部")])   # i18n: keep (button commands)
    return rows


class Ambiguous(ValueError):
    """A name that fits several devices."""


class Commander:
    def __init__(self, runtime_dir, actions):
        self.dir, self.a = runtime_dir, actions
        self.listeners = {}               # channel id -> {"stop", "thread", "state", "error", "since", "sig"}
        self.pairing = {}                 # channel id -> (code, expires)
        self.confirms = {}                # token -> (channel id, user, command, expires)
        self.tokens = {}                  # token -> a button's long payload (see _short)
        self.lock = threading.RLock()
        self._stop = threading.Event()

    # ---------- listeners ----------
    def start(self):
        threading.Thread(target=self._watch, daemon=True, name="commands").start()
        threading.Thread(target=self._watch_asks, daemon=True, name="asks").start()

    # ---------- questions from scripts (notify/asks.py) ----------
    def _watch_asks(self):
        while not self._stop.wait(1.5):
            try:
                self._post_asks()
            except Exception as e:
                print(_("問使用者:{e}", e=e), flush=True)

    def _post_asks(self):
        """Send every open question to each paired bot chat that watches its device (once)."""
        from drivers.sources import label
        from . import asks
        qs = asks.pending(self.dir)
        if not qs:
            return
        import notify
        from .channels import types
        acc = access(self.dir)
        for c in notify.load(self.dir).get("channels", []):
            t = types().get(c.get("type"))
            chat = (acc.get(c["id"]) or {}).get("chat")
            if not (c.get("enabled") and t is not None and getattr(t, "LISTENS", False) and chat):
                continue
            for q in qs:
                from drivers.sources import expand
                if c.get("devices") and q["device"] not in expand(c["devices"]):
                    continue
                if c["id"] in asks.posted(self.dir, q["id"]):
                    continue
                asks.mark_posted(self.dir, q["id"], c["id"])        # once, even if sending fails
                left = max(1, round((q["expires"] - time.time()) / 60))
                d = q.get("default")
                tail = _("{left} 分鐘內沒人回答就選「{p2}」", left=left, p2=q['options'][d - 1]) if d else _("{left} 分鐘內沒人回答,腳本就停在失敗", left=left)
                rows = [[(o, f"ans:{q['id']}:{k}") for k, o in enumerate(q["options"], 1)][i:i + 3] for i in range(0, len(q["options"]), 3)]
                try:
                    t.reply(c["config"], chat, f"❓ {label(q['device'])}" + (f" · {q['script_name']}" if q.get("script_name") else "")
                            + f"\n{q['text']}\n({tail})", rows)
                except Exception as e:
                    print(_("問使用者:送到「{name}」失敗:{e}", name=c.get('name'), e=e), flush=True)

    def _watch(self):
        while not self._stop.is_set():
            try:
                self._sync()
            except Exception as e:
                print(_("雙向指令:{e}", e=e), flush=True)
            self._stop.wait(5)

    def _sync(self):
        import notify
        from .channels import types
        cfg = notify.load(self.dir)
        want = {}
        for c in cfg.get("channels", []):
            t = types().get(c.get("type"))
            if c.get("enabled") and t is not None and getattr(t, "LISTENS", False):
                want[c["id"]] = (c, t, json.dumps(c["config"], sort_keys=True))
        with self.lock:
            for cid in list(self.listeners):
                if cid not in want or self.listeners[cid]["sig"] != want[cid][2]:
                    self.listeners.pop(cid)["stop"].set()
            for cid, (c, t, sig) in want.items():
                if cid not in self.listeners:
                    st = {"stop": threading.Event(), "state": "connecting", "error": None, "since": time.time(), "sig": sig}
                    st["thread"] = threading.Thread(target=self._listen, args=(c, t, st), daemon=True, name=f"listen-{cid}")
                    self.listeners[cid] = st
                    st["thread"].start()

    def _listen(self, c, t, st):
        wait = 5
        while not st["stop"].is_set():
            try:
                st.update(state="ok", error=None, since=time.time())
                t.listen(c["config"], lambda ev: self._on_event(c, t, ev), st["stop"])
            except Exception as e:
                st.update(state="error", error=str(e), since=time.time())
                st["stop"].wait(wait)
                wait = min(wait * 2, 300)                 # keep trying, less often (the service may be down)
            else:
                wait = 5

    def states(self):
        with self.lock:
            return {cid: {"state": st["state"], "error": st["error"], "since": st["since"]} for cid, st in self.listeners.items()}

    # ---------- pairing ----------
    def pair_code(self, cid):
        code = f"{random.SystemRandom().randint(0, 999999):06d}"
        with self.lock:
            self.pairing[cid] = (code, time.time() + PAIR_SECONDS)
        return code, PAIR_SECONDS

    def unpair(self, cid, user):
        acc = access(self.dir)
        ch = acc.get(cid) or {}
        ch["allowed"] = [u for u in ch.get("allowed") or [] if u["id"] != user]
        acc[cid] = ch
        _write(os.path.join(self.dir, ACCESS), acc)

    def _allowed(self, cid, user):
        return any(u["id"] == user for u in (access(self.dir).get(cid) or {}).get("allowed") or [])

    def _log(self, c, ev, text, result):
        try:
            with open(os.path.join(self.dir, LOG), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "channel": c["id"], "user": ev.get("user"), "user_name": ev.get("user_name"),
                                    "command": text, "result": result}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- one message or button ----------
    def _on_event(self, c, t, ev):
        cid = c["id"]
        reply = lambda text, buttons=None, image=None: t.reply(c["config"], ev["chat"], text, self._short(buttons), image)
        if ev.get("ack"):
            ev["ack"]()
        text = (ev.get("text") or "").strip()
        text = re.sub(r"<@!?\d+>", "", text).strip().lstrip("/")      # a Discord mention / a Telegram /command
        with self.lock:
            code = self.pairing.get(cid)
        if text and code and time.time() < code[1] and text == code[0]:
            acc = access(self.dir)
            ch = acc.get(cid) or {}
            ch["allowed"] = [u for u in ch.get("allowed") or [] if u["id"] != ev["user"]] + [{"id": ev["user"], "name": ev.get("user_name")}]
            name = ev.get("chat_name")
            if hasattr(t, "chat_title") and (not name or name == ev["chat"]):
                name = t.chat_title(c["config"], ev["chat"]) or name
            ch.update(chat=ev["chat"], chat_name=name)
            acc[cid] = ch
            _write(os.path.join(self.dir, ACCESS), acc)
            with self.lock:
                self.pairing.pop(cid, None)
            self._log(c, ev, _("(配對)"), "ok")
            reply(_("配對成功:{p1} 可以下指令了,之後的通知也會送到這裡。\n{HELP}", p1=ev.get('user_name') or ev['user'], HELP=_(HELP)))
            return
        if not self._allowed(cid, ev["user"]):
            return                                             # not paired: say nothing
        button = ev.get("button") or ""
        if button.startswith("ans:"):
            from . import asks
            from drivers.sources import label
            _x, qid, k = button.split(":", 2)
            ok, msg = asks.answer(self.dir, qid, int(k), ev.get("user_name") or ev["user"])
            q = asks.get(self.dir, qid) or {}
            self._log(c, ev, _("(回答)「{p1}」", p1=q.get('text', '')[:30]), msg)
            reply(f"{label(q.get('device', ''))}:{msg}")
            return
        if button.startswith(("ok:", "no:")):
            self._confirm(c, ev, button, reply)
            return
        if button.startswith("c:"):
            with self.lock:
                button = self.tokens.get(button[2:], "")
            if not button:
                reply(_("這個按鈕已經過期,請重新下指令"))
                return
        if button.startswith("cmd:"):
            text = button[4:]
        if not text:
            return
        try:
            out = self._run(c, ev, text, reply)
        except Exception as e:
            out = _("做不到:{e}", e=e)
        if out:
            self._log(c, ev, text, out)
            reply(out)

    def _confirm(self, c, ev, button, reply):
        token = button[3:]
        with self.lock:
            item = self.confirms.pop(token, None)
        if not item or item[0] != c["id"] or item[1] != ev["user"] or time.time() > item[3]:
            reply(_("這個確認已經過期,請重新下指令"))
            return
        if button.startswith("no:"):
            reply(_("已取消"))
            return
        try:
            out = item[2]()
        except Exception as e:
            out = _("做不到:{e}", e=e)
        self._log(c, ev, _("(確認)"), out)
        reply(out)

    def _ask(self, c, ev, question, do, reply):
        token = f"{random.SystemRandom().randint(0, 2 ** 40):x}"
        with self.lock:
            self.confirms[token] = (c["id"], ev["user"], do, time.time() + CONFIRM_SECONDS)
        reply(question, [[(_("確認"), f"ok:{token}"), (_("取消"), f"no:{token}")]])
        return None

    def _short(self, buttons):
        """Payloads too long for the chat service -> a short token kept here (the newest 2000)."""
        if not buttons:
            return buttons
        out = []
        for row in buttons:
            r = []
            for label, payload in row:
                if len(payload.encode("utf-8")) > TOKEN_BYTES:
                    token = f"{random.SystemRandom().randint(0, 2 ** 40):x}"
                    with self.lock:
                        self.tokens[token] = payload
                        while len(self.tokens) > 2000:
                            self.tokens.pop(next(iter(self.tokens)))
                    payload = f"c:{token}"
                r.append((label, payload))
            out.append(r)
        return out

    def _devices(self, arg):
        return match_devices(self.a.devices(), arg)

    def _run(self, c, ev, text, reply):
        from drivers.sources import label
        parts = text.split(None, 1)
        verb = VERBS.get(parts[0].lower()) if parts else None
        arg = parts[1].strip() if len(parts) > 1 else ""
        by = f"{ev.get('user_name') or ev['user']}({c['name']})"
        if verb is None:
            r = self.a.panel_command(text, by)
            if r is None:
                return _("看不懂「{text}」。\n{p2}", text=text, p2=self.a.help_text(_(HELP)))
            if r.get("ask"):
                return self._ask(c, ev, r["ask"][0], r["ask"][1], reply)
            reply(r["text"], r.get("buttons"))
            self._log(c, ev, text, r["text"].split("\n")[0][:80])
            return None
        if verb == "help":
            return self.a.help_text(_(HELP))
        if verb == "status":
            return self.a.status_text()
        if verb in ("hold", "pause", "resume"):
            kind = {"hold": "stop", "pause": "pause", "resume": "resume"}[verb]
            if arg in ("全部", "all", "*", _("全部")) or not arg and verb != "resume":
                if not arg:
                    return _("要停下來哪一台?例如「停下來 A01」或「停下來 全部」") if verb == "hold" else _("要暫停哪一台?例如「暫停 A01」或「暫停 全部」")
                return self.a.hold_all(kind, by)
            devs = self._devices(arg)
            res = [f"{label(d)}:{self.a.act(d, kind, by, mode='stop' if kind == 'stop' else None)}" for d in devs]
            return {"hold": _("停下來"), "pause": _("暫停"), "resume": _("繼續")}[verb] + "\n" + "\n".join(res)
        if verb == "screen":
            devs = self._devices(arg) if arg else []
            if len(devs) != 1:
                return _("要看哪一台?例如「畫面 A01」")
            jpg = self.a.screen(devs[0])
            if not jpg:
                return _("{p1} 現在沒有畫面(腳本沒有在執行,或視窗被縮到最小)", p1=label(devs[0]))
            reply(_("{p1} 現在的畫面", p1=label(devs[0])), [[(_("🛑 停下來"), f"cmd:停下來 {devs[0]}"), (_("重新整理"), f"cmd:畫面 {devs[0]}")]], jpg)   # i18n: keep (button commands)
            self._log(c, ev, text, _("(畫面)"))
            return None
        return _(HELP)
