"""Two-way channels (雙向指令): a bot that both sends the notifications (with buttons under them) and listens for
commands. Both connect out from this computer - no open port, no server of one's own.

A bot channel type is a notification channel type (notify/channels.py) plus:
  LISTENS = True
  send(config, head, text, image, buttons)   config["_chat"] = where to send (set when someone pairs, kept in
                                             <runtime dir>/notify_access.json); buttons = [[label, payload], ...]
  listen(config, on_event, stop)             blocking: calls on_event({"user", "user_name", "chat", "chat_name",
                                             "text" | "button", "ack"}) until stop is set; raises with a readable
                                             message when it cannot connect (the caller retries)
  reply(config, chat, text, buttons=None, image=None)
  invite(config) -> a link that adds the bot (or None)
The commands themselves (what a text or a button does, who may) are in notify/commands.py."""
import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .channels import _multipart
from i18n import N_, _

TIMEOUT = 20


def _http(method, url, body=None, headers=None, timeout=TIMEOUT):
    data, ct = body if isinstance(body, tuple) else ((json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json")
                                                      if body is not None else (None, None))
    h = {"User-Agent": "Inspector (https://github.com, 1.0)", **(headers or {})}
    if ct:
        h["Content-Type"] = ct
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}:{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(_("連不上:{reason}", reason=e.reason)) from None


# ---------------------------------------------------------------- Telegram
class Telegram:
    LABEL = N_("Telegram(可下指令)")
    HELP = (N_("在 Telegram 搜尋 @BotFather,傳 /newbot,照它問的取名字,最後它會給一串 Token(像 123456:ABC-DEF…),貼到下面並儲存。接著按「配對」,把顯示的配對碼傳給你的 Bot,就能收通知、下指令。"))
    FIELDS = [{"name": "token", "label": "Bot Token", "secret": True, "placeholder": "123456789:AA…"}]
    LISTENS = True
    API = "https://api.telegram.org/bot{token}/{method}"

    @classmethod
    def check(cls, config, name):
        if not (config.get("token") or "").count(":") == 1 or len(config["token"]) < 30:
            raise ValueError(_("「{name}」:Token 要像 123456789:AA… (向 @BotFather 拿)", name=name))

    @classmethod
    def _call(cls, config, method, body=None, timeout=TIMEOUT):
        try:
            r = _http("POST", cls.API.format(token=config["token"], method=method), body, timeout=timeout)
        except RuntimeError as e:
            if "HTTP 401" in str(e) or "HTTP 404" in str(e):
                raise RuntimeError(_("Token 不正確(向 @BotFather 重新拿)")) from None
            raise
        if not r.get("ok", True):
            raise RuntimeError(r.get("description") or _("Telegram 回傳錯誤"))
        return r.get("result")

    @staticmethod
    def _markup(buttons):
        if not buttons:
            return None
        return {"inline_keyboard": [[{"text": label, "callback_data": payload[:64]} for label, payload in row] for row in buttons]}

    @classmethod
    def reply(cls, config, chat, text, buttons=None, image=None):
        markup = cls._markup(buttons)
        if image:
            fields = {"chat_id": str(chat), "caption": text[:1000]}
            if markup:
                fields["reply_markup"] = json.dumps(markup, ensure_ascii=False)
            cls._call(config, "sendPhoto", _multipart(fields, [("photo", "screen.jpg", "image/jpeg", image)]))
        else:
            body = {"chat_id": chat, "text": text[:4000]}
            if markup:
                body["reply_markup"] = markup
            cls._call(config, "sendMessage", body)

    @classmethod
    def send(cls, config, head, text, image=None, buttons=None):
        if not config.get("_chat"):
            raise RuntimeError(_("還沒配對:到「通知」頁按「配對」"))
        cls.reply(config, config["_chat"], f"{head}\n{text}", buttons, image)

    @classmethod
    def invite(cls, config):
        try:
            me = cls._call(config, "getMe")
            return f"https://t.me/{me['username']}"
        except Exception:
            return None

    @classmethod
    def listen(cls, config, on_event, stop):
        me = cls._call(config, "getMe")                          # a wrong token fails here, with Telegram's reason
        offset = None
        while not stop.is_set():
            body = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                body["offset"] = offset
            ups = cls._call(config, "getUpdates", body, timeout=35) or []
            for u in ups:
                offset = u["update_id"] + 1
                if "message" in u and u["message"].get("text"):
                    m = u["message"]
                    who = m.get("from") or {}
                    if who.get("is_bot"):
                        continue
                    chat = m["chat"]
                    on_event({"user": str(who.get("id")), "user_name": who.get("username") or who.get("first_name") or "",
                              "chat": chat["id"], "chat_name": chat.get("title") or chat.get("username") or chat.get("first_name") or "",
                              "text": m["text"], "ack": None, "bot": me.get("username")})
                elif "callback_query" in u:
                    q = u["callback_query"]
                    who = q.get("from") or {}
                    chat = (q.get("message") or {}).get("chat") or {}

                    def ack(text=None, qid=q["id"]):
                        try:
                            cls._call(config, "answerCallbackQuery", {"callback_query_id": qid, **({"text": text} if text else {})})
                        except Exception:
                            pass
                    on_event({"user": str(who.get("id")), "user_name": who.get("username") or who.get("first_name") or "",
                              "chat": chat.get("id"), "chat_name": chat.get("title") or chat.get("username") or "",
                              "button": q.get("data") or "", "ack": ack, "bot": me.get("username")})


# ---------------------------------------------------------------- Discord
class DiscordBot:
    LABEL = N_("Discord Bot(可下指令)")
    HELP = (N_("到 https://discord.com/developers/applications 按 New Application 取名 → 左邊 Bot → Reset Token 複製 Token 貼到下面;同一頁往下打開「Message Content Intent」並儲存。存好後按「邀請 Bot」把它加進你的伺服器,再按「配對」,在要收通知的頻道傳配對碼。"))
    FIELDS = [{"name": "token", "label": "Bot Token", "secret": True, "placeholder": "MTA…"}]
    LISTENS = True
    API = "https://discord.com/api/v10"
    GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
    INTENTS = 1 | (1 << 9) | (1 << 12) | (1 << 15)      # guilds, guild messages, direct messages, message content
    PERMISSIONS = 1024 | 2048 | 32768 | 65536           # view channel, send messages, attach files, read history

    @classmethod
    def check(cls, config, name):
        if (config.get("token") or "").count(".") != 2:
            raise ValueError(_("「{name}」:Token 要像 MTA….….…(在開發者網站的 Bot 頁按 Reset Token)", name=name))

    @classmethod
    def _auth(cls, config):
        return {"Authorization": f"Bot {config['token']}"}

    @staticmethod
    def _components(buttons):
        if not buttons:
            return []
        return [{"type": 1, "components": [{"type": 2, "style": 2 if not label.startswith(("確認", _("確認"), "🛑")) else 4,
                                            "label": label[:80], "custom_id": payload[:100]} for label, payload in row[:5]]}
                for row in buttons[:5]]

    @classmethod
    def reply(cls, config, chat, text, buttons=None, image=None):
        payload = {"content": text[:1990], "components": cls._components(buttons), "allowed_mentions": {"parse": []}}
        url = f"{cls.API}/channels/{chat}/messages"
        if image:
            body = _multipart({"payload_json": json.dumps(payload, ensure_ascii=False)}, [("files[0]", "screen.jpg", "image/jpeg", image)])
            _http("POST", url, body, cls._auth(config))
        else:
            _http("POST", url, payload, cls._auth(config))

    @classmethod
    def send(cls, config, head, text, image=None, buttons=None):
        if not config.get("_chat"):
            raise RuntimeError(_("還沒配對:到「通知」頁按「配對」"))
        cls.reply(config, config["_chat"], f"**{head}**\n{text}", buttons, image)

    @classmethod
    def chat_title(cls, config, chat):
        """'#channel' for a channel id (the gateway message only carries the id)."""
        try:
            name = _http("GET", f"{cls.API}/channels/{chat}", None, cls._auth(config)).get("name")
            return f"#{name}" if name else None
        except RuntimeError:
            return None

    @classmethod
    def app_id(cls, config):
        try:                                             # the token starts with the bot's id (base64)
            first = config["token"].split(".")[0]
            return base64.b64decode(first + "=" * (-len(first) % 4)).decode()
        except Exception:
            return None

    @classmethod
    def invite(cls, config):
        aid = cls.app_id(config)
        return f"https://discord.com/oauth2/authorize?client_id={aid}&scope=bot&permissions={cls.PERMISSIONS}" if aid else None

    @classmethod
    def listen(cls, config, on_event, stop):
        import websocket                                  # websocket-client
        ws = websocket.create_connection(cls.GATEWAY, timeout=30)
        seq = [None]
        try:
            hello = json.loads(ws.recv())
            interval = hello["d"]["heartbeat_interval"] / 1000.0
            ws.send(json.dumps({"op": 2, "d": {"token": config["token"], "intents": cls.INTENTS,
                                               "properties": {"os": "windows", "browser": "inspector", "device": "inspector"}}}))
            lock = threading.Lock()

            def beat():
                while not stop.wait(interval):
                    try:
                        with lock:
                            ws.send(json.dumps({"op": 1, "d": seq[0]}))
                    except Exception:
                        return
            threading.Thread(target=beat, daemon=True, name="discord-beat").start()
            ws.settimeout(interval * 2)
            me = {}
            while not stop.is_set():
                try:
                    opcode, raw = ws.recv_data(control_frame=True)
                except websocket.WebSocketTimeoutException:
                    raise RuntimeError(_("Discord 太久沒有回應,重新連線"))
                if opcode == websocket.ABNF.OPCODE_CLOSE:
                    code = int.from_bytes(raw[:2], "big") if len(raw) >= 2 else 0
                    raise RuntimeError(_(CLOSE[code]) if code in CLOSE else _("Discord 關閉了連線({code})", code=code))
                if opcode != websocket.ABNF.OPCODE_TEXT:
                    continue
                msg = json.loads(raw)
                if msg.get("s") is not None:
                    seq[0] = msg["s"]
                op, t, d = msg.get("op"), msg.get("t"), msg.get("d") or {}
                if op in (7, 9):
                    raise RuntimeError(_("Discord 要求重新連線"))
                if op != 0:
                    continue
                if t == "READY":
                    me = d.get("user") or {}
                elif t == "MESSAGE_CREATE":
                    a = d.get("author") or {}
                    if a.get("bot") or not d.get("content"):
                        continue
                    on_event({"user": str(a.get("id")), "user_name": a.get("global_name") or a.get("username") or "",
                              "chat": d.get("channel_id"), "chat_name": d.get("channel_id"), "text": d["content"],
                              "ack": None, "bot": me.get("username")})
                elif t == "INTERACTION_CREATE" and d.get("type") == 3:
                    who = (d.get("member") or {}).get("user") or d.get("user") or {}

                    def ack(text=None, iid=d["id"], tok=d["token"]):
                        try:                                  # within 3 s, or Discord shows "interaction failed"
                            _http("POST", f"{cls.API}/interactions/{iid}/{tok}/callback", {"type": 6})
                        except Exception:
                            pass
                    on_event({"user": str(who.get("id")), "user_name": who.get("global_name") or who.get("username") or "",
                              "chat": d.get("channel_id"), "chat_name": d.get("channel_id"),
                              "button": (d.get("data") or {}).get("custom_id") or "", "ack": ack, "bot": me.get("username")})
        except websocket.WebSocketBadStatusException as e:
            raise RuntimeError(_("Discord 拒絕連線:{e}", e=e)) from None
        except websocket.WebSocketConnectionClosedException:
            raise RuntimeError(_("Discord 關閉了連線")) from None
        finally:
            try:
                ws.close()
            except Exception:
                pass


CLOSE = {4004: N_("Token 不正確(到開發者網站的 Bot 頁重新產生)"),
         4014: N_("請在 Discord 開發者網站的 Bot 頁打開「Message Content Intent」並儲存"),
         4013: N_("連線設定不正確(intents)"), 4011: N_("Bot 加入的伺服器太多,需要分片")}

TYPES = {"telegram": Telegram, "discord_bot": DiscordBot}
