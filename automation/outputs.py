"""Outputs (輸出): where a script sends something besides the device's screen - a web hook, a home-automation
server, a relay. A rule action or a sub-script step {"type": "output", "output": id, "command": text, "value": value}
sends one message there:
  {"device", "script", "command" (text; {variable} placeholders filled in), "value" (a number or text, may come from
   a parameter / setting / variable), "time"}

<project>/meta/outputs.json  {"format", "outputs": [{"id", "name", "type", ...settings of that type}]}
Types: http (built in)          {"url", "method": "POST" | "GET", "headers": {name: value}}
                                POST sends the message as JSON; GET puts it in the query string
       mqtt (built in)          {"host", "port", "topic" ({device} {command}), "payload": json | value | command,
                                 "username", "password", "retain", "qos"}: one PUBLISH per message
       homeassistant (built in) {"url", "token", "entity_id", "service"}: calls a service - command "on" / "off" /
                                 "toggle" / "<domain>.<service>", else the default service
       a plugin's (registry kind "output"): a class with label, fields {name: label} and send(settings, message);
                                 secrets (a tuple of field names) says which fields are secret
The secret fields (http headers, mqtt password, Home Assistant token) are kept apart from the design, in
<runtime dir>/output_secrets.json {output id: {field: value}}: a pack carries where an output goes, never the key to
it. load() puts them back together; an older outputs.json with secrets inside still works, save() moves them out.
Sending runs in the background (it never holds up the watch loop); a failure is reported like a failed tap."""
import atomic
import concurrent.futures
import json
import os
import re
import time
import urllib.parse
import urllib.request

import project
from . import spec
from i18n import N_, _

FILE = os.path.join("meta", "outputs.json")
SECRETS = "output_secrets.json"
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="output")


class Http:
    label = N_("網址(HTTP / Webhook)")
    fields = {"url": N_("網址"), "method": N_("方法(POST 或 GET)"), "headers": N_("標頭(JSON,可不填)")}
    secrets = ("headers",)

    @staticmethod
    def check(o):
        if not re.match(r"https?://", o.get("url") or ""):
            raise ValueError(_("輸出「{name}」:網址要以 http:// 或 https:// 開頭", name=o.get('name')))
        if (o.get("method") or "POST").upper() not in ("POST", "GET"):
            raise ValueError(_("輸出「{name}」:方法只能是 POST 或 GET", name=o.get('name')))
        if not isinstance(o.get("headers") or {}, dict):
            raise ValueError(_("輸出「{name}」:標頭要是 JSON 物件", name=o.get('name')))

    @staticmethod
    def send(o, msg):
        method = (o.get("method") or "POST").upper()
        url = o["url"]
        headers = {"User-Agent": "Inspector", **(o.get("headers") or {})}
        if method == "GET":
            q = urllib.parse.urlencode({k: v for k, v in msg.items() if v is not None})
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + q, headers=headers, method="GET")
        else:
            req = urllib.request.Request(url, data=json.dumps(msg, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json", **headers}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status >= 300:
                raise RuntimeError(f"HTTP {r.status}")
            return r.status


def _fill(text, msg):
    """{device} {command} {script} {value} in a topic / entity from the message."""
    out = str(text or "")
    for k in ("device", "command", "script", "value"):
        v = msg.get(k)
        out = out.replace("{" + k + "}", "" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)))
    return out


class Mqtt:
    """MQTT (sensors, relays, Home Assistant, Node-RED ...): one PUBLISH per message (MQTT 3.1.1, no library needed)."""
    label = "MQTT"
    fields = {"host": N_("伺服器(broker)位址"), "port": N_("埠號(預設 1883;8883 = 加密)"), "topic": N_("主題(可用 {device} {command})"),
              "payload": N_("內容:json(整則訊息)/ value(只有值)/ command(只有指令)"), "username": N_("帳號(可不填)"),
              "password": N_("密碼(可不填)"), "retain": N_("保留最後一則(yes / no)"), "qos": N_("送達保證 0 或 1")}
    secrets = ("password",)

    @staticmethod
    def check(o):
        if not (o.get("host") or "").strip():
            raise ValueError(_("輸出「{name}」:請填 MQTT 伺服器位址", name=o.get('name')))
        if not (o.get("topic") or "").strip():
            raise ValueError(_("輸出「{name}」:請填主題,例如 farm/{device}/{command}", name=o.get('name')))
        if not str(o.get("port") or "1883").strip().isdigit():
            raise ValueError(_("輸出「{name}」:埠號要是數字", name=o.get('name')))
        if (o.get("payload") or "json") not in ("json", "value", "command"):
            raise ValueError(_("輸出「{name}」:內容只能是 json、value 或 command", name=o.get('name')))
        if str(o.get("qos") or "0") not in ("0", "1"):
            raise ValueError(_("輸出「{name}」:送達保證只能是 0 或 1", name=o.get('name')))

    @staticmethod
    def _str(t):
        b = t.encode("utf-8")
        return len(b).to_bytes(2, "big") + b

    @staticmethod
    def _len(n):
        out = b""
        while True:
            d, n = n % 128, n // 128
            out += bytes([d | (0x80 if n else 0)])
            if not n:
                return out

    @classmethod
    def send(cls, o, msg):
        import random
        import socket
        import ssl
        port = int(str(o.get("port") or "1883").strip() or 1883)
        sock = socket.create_connection((o["host"].strip(), port), timeout=10)
        if port == 8883:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=o["host"].strip())
        try:
            user, pw = (o.get("username") or "").strip(), o.get("password") or ""
            flags = 0x02 | (0x80 if user else 0) | (0x40 if user and pw else 0)
            body = cls._str("MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + cls._str(f"inspector-{random.randrange(1 << 30):x}")
            if user:
                body += cls._str(user) + (cls._str(pw) if pw else b"")
            sock.sendall(bytes([0x10]) + cls._len(len(body)) + body)
            ack = sock.recv(4)
            if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
                raise RuntimeError(_("MQTT 伺服器不接受連線(帳號密碼?)") if len(ack) >= 4 else _("MQTT 伺服器沒有回應"))
            kind = o.get("payload") or "json"
            if kind == "value":
                v = msg.get("value")
                data = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else str(v))
            elif kind == "command":
                data = str(msg.get("command") or "")
            else:
                data = json.dumps(msg, ensure_ascii=False)
            qos = 1 if str(o.get("qos") or "0") == "1" else 0
            retain = str(o.get("retain") or "no").lower() in ("yes", "true", "1", "是")
            pub = cls._str(_fill(o["topic"], msg)) + ((1).to_bytes(2, "big") if qos else b"") + data.encode("utf-8")
            sock.sendall(bytes([0x30 | (qos << 1) | (1 if retain else 0)]) + cls._len(len(pub)) + pub)
            if qos:
                ack = sock.recv(4)
                if len(ack) < 2 or ack[0] != 0x40:
                    raise RuntimeError(_("MQTT 伺服器沒有確認收到"))
            sock.sendall(b"\xe0\x00")                       # DISCONNECT
            return True
        finally:
            sock.close()


class HomeAssistant:
    """Home Assistant: calls a service (switch.turn_on, light.toggle, input_number.set_value ...) through its REST API.
    The message's command picks the service: "on" / "off" / "toggle", or "<domain>.<service>"; else the default one.
    A value that is an object is added to the call's data (e.g. {"brightness": 120}); a single value goes as "value"
    for a *.set_value service."""
    label = "Home Assistant"
    fields = {"url": N_("位址(例如 http://homeassistant.local:8123)"), "token": N_("長期存取權杖(在 HA 的個人資料頁建立)"),
              "entity_id": N_("要控制的實體(例如 switch.water_pump)"), "service": N_("預設的服務(例如 switch.toggle)")}
    secrets = ("token",)

    @staticmethod
    def check(o):
        if not re.match(r"https?://", o.get("url") or ""):
            raise ValueError(_("輸出「{name}」:位址要以 http:// 或 https:// 開頭", name=o.get('name')))
        if not (o.get("token") or "").strip():
            raise ValueError(_("輸出「{name}」:請填 Home Assistant 的長期存取權杖", name=o.get('name')))
        if o.get("service") and not re.fullmatch(r"[a-z_]+\.[a-z_]+", o["service"]):
            raise ValueError(_("輸出「{name}」:服務要像 switch.toggle", name=o.get('name')))

    @staticmethod
    def send(o, msg):
        cmd = str(msg.get("command") or "").strip()
        if cmd in ("on", "off", "toggle"):
            service = {"on": "homeassistant.turn_on", "off": "homeassistant.turn_off", "toggle": "homeassistant.toggle"}[cmd]
        elif re.fullmatch(r"[a-z_]+\.[a-z_]+", cmd):
            service = cmd
        else:
            service = o.get("service") or "homeassistant.toggle"
        data = {}
        if o.get("entity_id"):
            data["entity_id"] = _fill(o["entity_id"], msg)
        v = msg.get("value")
        if isinstance(v, dict):
            data.update(v)
        elif v is not None and service.endswith(".set_value"):
            data["value"] = v
        domain, svc = service.split(".", 1)
        req = urllib.request.Request(o["url"].rstrip("/") + f"/api/services/{domain}/{svc}",
                                     data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                     headers={"Authorization": f"Bearer {o['token'].strip()}", "Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status >= 300:
                raise RuntimeError(_("Home Assistant 回應 {status}", status=r.status))
            return r.status


def types():
    from project.plugins import registry
    return {"http": Http, "mqtt": Mqtt, "homeassistant": HomeAssistant, **registry().all("output")}


def _secret_fields(o):
    t = types().get(o.get("type"))
    return tuple(getattr(t, "secrets", ()) or ()) if t else ()


def _secrets_path():
    return os.path.join(project.runtime_dir(), SECRETS)


def _read_secrets():
    try:
        with open(_secrets_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def strip_secrets(outputs):
    """outputs without their secret fields -> (outputs, {id: {field: value}})."""
    kept, secret = [], {}
    for o in outputs:
        fields = _secret_fields(o)
        s = {k: o[k] for k in fields if o.get(k) not in (None, "", {})}
        if s:
            secret[o["id"]] = s
        kept.append({k: v for k, v in o.items() if k not in fields})
    return kept, secret


def load(data_root):
    p = os.path.join(data_root, FILE)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not spec.readable(d):
        return {}
    sec = _read_secrets()
    return {o["id"]: {**o, **(sec.get(o["id"]) or {})} for o in d.get("outputs") or []}


def validate(outputs):
    ids = set()
    ts = types()
    for o in outputs:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", o.get("id") or "") or o["id"] in ids:
            raise ValueError(_("輸出「{p1}」:代號只能用小寫英文、數字、底線,且不能重複", p1=o.get('name') or o.get('id')))
        ids.add(o["id"])
        if not (o.get("name") or "").strip():
            raise ValueError(_("請替輸出取個名字"))
        t = ts.get(o.get("type"))
        if not t:
            raise ValueError(_("輸出「{name}」:沒有「{type}」這種輸出", name=o['name'], type=o.get('type')))
        if hasattr(t, "check"):
            t.check(o)


def save(data_root, outputs):
    validate(outputs)
    kept, secret = strip_secrets(outputs)
    sp = _secrets_path()
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    atomic.write_json(sp, secret, ensure_ascii=False, indent=1)
    p = os.path.join(data_root, FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, spec.stamp({"outputs": kept, "saved": time.time()}), ensure_ascii=False, indent=1)


def send(data_root, out_id, msg):
    """Send now (in a worker thread) -> Future; its exception says what went wrong."""
    o = load(data_root).get(out_id)
    if not o:
        f = concurrent.futures.Future()
        f.set_exception(RuntimeError(_("沒有「{out_id}」這個輸出", out_id=out_id)))
        return f
    t = types().get(o.get("type"))
    if not t:
        f = concurrent.futures.Future()
        f.set_exception(RuntimeError(_("沒有「{type}」這種輸出", type=o.get('type'))))
        return f
    return _pool.submit(t.send, o, {**msg, "time": msg.get("time") or time.time()})


def describe(a, data_root=None):
    from .buttons import DATA_ROOT
    o = load(data_root or DATA_ROOT).get(a.get("output")) or {}
    from . import values
    v = a.get("value")
    return _("送到「{name}」", name=o.get('name', a.get('output'))) + (f":{a['command']}" if a.get("command") else "") + \
        (_("(值 {p1})", p1=values.describe(v)) if v is not None else "")


def check_action(a, where, data_root=None, params=None, var_names=None, allow_params=True):
    from .buttons import DATA_ROOT
    from . import settings, values
    if a.get("output") not in load(data_root or DATA_ROOT):
        raise ValueError(_("{where}:請選擇要送到哪個輸出(在「素材庫 › 輸出」新增)", where=where))
    if a.get("value") is not None:
        kind = "text" if isinstance(a["value"], str) else "number"
        values.check(a["value"], where, kind, params=params, settings=settings.load(), var_names=var_names,
                     allow_params=allow_params)
