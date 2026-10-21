"""Notification channel types. Each is a class with:
  LABEL     what people call it
  HELP      how to get what it needs, in plain words
  FIELDS    [{"name", "label", "secret": bool, "placeholder"}]   what to fill in (secret ones are never shown again)
  check(config, name)                 raise ValueError if the fields are not usable
  send(config, head, text, image)     send one message (image: JPEG bytes or None); raise on failure
Adding a channel = adding a class here and to TYPES; the routing, merging and the page need nothing else."""
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from i18n import N_, _

TIMEOUT = 15


def _post(url, body, content_type, tries=3):
    """POST with a retry on rate limits (429: wait as told) and server errors."""
    for attempt in range(tries):
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type, "User-Agent": "Inspector"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and attempt < tries - 1:
                try:
                    wait = float(json.loads(detail).get("retry_after", 2))
                except ValueError:
                    wait = 2
                time.sleep(min(wait, 30))
                continue
            if e.code >= 500 and attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}:{detail}") from None
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(_("連不上:{reason}", reason=e.reason)) from None


def _multipart(fields, files):
    """multipart/form-data: fields {name: text}, files [(field name, file name, content type, bytes)]."""
    b = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode() + v.encode("utf-8") + b"\r\n"
    for k, fn, ct, data in files:
        out += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\nContent-Type: {ct}\r\n\r\n".encode() + data + b"\r\n"
    return out + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


class Discord:
    LABEL = "Discord"
    HELP = (N_("在 Discord 要接收通知的頻道:編輯頻道 › 整合 › Webhook › 新 Webhook › 複製 Webhook 網址,貼到下面。不需要自己架伺服器;網址等同密碼,不要給別人。"))
    FIELDS = [{"name": "url", "label": N_("Webhook 網址"), "secret": True, "placeholder": "https://discord.com/api/webhooks/…"},
              {"name": "mention", "label": N_("緊急時提醒誰(可不填)"), "secret": False, "placeholder": N_("@here 或 @everyone")}]
    URL = re.compile(r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+")

    @classmethod
    def check(cls, config, name):
        if not cls.URL.fullmatch(config.get("url") or ""):
            raise ValueError(_("「{name}」:Webhook 網址要像 https://discord.com/api/webhooks/數字/一串英數字", name=name))
        if config.get("mention") and config["mention"] not in ("@here", "@everyone"):
            raise ValueError(_("「{name}」:提醒只能填 @here 或 @everyone", name=name))

    @classmethod
    def send(cls, config, head, text, image=None):
        content = f"**{head}**\n{text}"
        if config.get("mention") and head.startswith("🚨"):            # an urgent event
            content = f"{config['mention']} {content}"
        content = content[:1990]
        payload = {"content": content, "username": "Inspector",
                   "allowed_mentions": {"parse": ["everyone"] if config.get("mention") else []}}
        if image:
            body, ct = _multipart({"payload_json": json.dumps(payload, ensure_ascii=False)}, [("files[0]", "screen.jpg", "image/jpeg", image)])
        else:
            body, ct = json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"
        _post(config["url"], body, ct)


TYPES = {"discord": Discord}             # built in; a project's plugins can add more (kind "notify")


def types():
    """Every channel type there is: the built-in ones and the current project's plugins'."""
    from project.plugins import registry
    from .bots import TYPES as BOTS
    return {**TYPES, **BOTS, **registry().all("notify")}
