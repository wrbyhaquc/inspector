"""Who may use the system from another device (a phone on the LAN).

This computer (127.0.0.1) is trusted as the consultant: nothing changes for the people working at the machine.
Anyone else signs in with a PIN:
  user   (使用者)  only the operation panel (look, change its settings, pause / continue)
  admin  (顧問)    everything

<runtime dir>/access.json  {"user_pin": sha256, "admin_pin": sha256, "salt"}  (no PINs = nobody else gets in)
It belongs to this machine, not to the design: a pack never carries it. An older <data_root>/meta/access.json is
still read, and moved here the next time the PINs are set.
Sessions live in memory (a restart signs everybody out)."""
import hashlib
import json
import os
import secrets
import time

import project
from i18n import _

FILE = "access.json"
OLD_FILE = os.path.join("meta", "access.json")
LOCAL = {"127.0.0.1", "::1", "localhost"}
USER_API = {("GET", "/api/panel"), ("GET", "/api/sources/names"), ("POST", "/api/panel/set"), ("POST", "/api/panel/pause"), ("POST", "/api/panel/resume"),
            ("POST", "/api/panel/act"), ("POST", "/api/panel/deploy"), ("POST", "/api/panel/answer"),
            ("POST", "/api/panel/chat/save"), ("POST", "/api/panel/chat/remove"), ("POST", "/api/panel/chat/pair"),
            ("POST", "/api/panel/chat/unpair")}
# pictures the panel's widgets show (each endpoint also checks the panel really has a widget that allows it)
USER_GET_PREFIX = ("/api/panel/live/", "/api/panel/incident/")
OPEN_API = {"/api/auth/me", "/api/auth/login", "/api/auth/logout", "/api/project"}
COOKIE = "inspector_session"
# what a runtime (project.edition()) may still change: running, the operation panel, its own sources, notifications,
# sign-in, packs. Everything else that writes belongs to the design, which a runtime only gets from a pack.
RUNTIME_WRITE = ("/api/auth/", "/api/language", "/api/panel/", "/api/shadow/", "/api/sources/", "/api/drivers",
                 "/api/notify", "/api/settings/value", "/api/schedules/override", "/api/schedules/request",
                 "/api/outputs/test", "/api/image/warm", "/api/jobs", "/api/spec/check", "/api/packs", "/api/system/",
                 "/api/storage/")
RUNTIME_WRITE_EXACT = ("/api/scripts",)        # saving a script: only its settings (where it runs ...), automation.save
RUNTIME_DESIGN_ONLY = ("/api/panel/definition",)
_sessions = {}                     # token -> (role, expires)


def _path():
    return os.path.join(project.runtime_dir(), FILE)


def _read(data_root):
    p = _path()
    if not os.path.exists(p):
        p = os.path.join(data_root, OLD_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _hash(pin, salt):
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def configured(data_root):
    d = _read(data_root)
    return {"user": bool(d.get("user_pin")), "admin": bool(d.get("admin_pin"))}


def set_pins(data_root, user_pin=None, admin_pin=None):
    d = _read(data_root)
    d.setdefault("salt", secrets.token_hex(8))
    for key, pin in (("user_pin", user_pin), ("admin_pin", admin_pin)):
        if pin is None:
            continue
        pin = str(pin).strip()
        if pin == "":
            d.pop(key, None)                           # cleared: that kind of sign-in is off
            continue
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise ValueError(_("PIN 碼要是 4~8 位數字"))
        d[key] = _hash(pin, d["salt"])
    if d.get("user_pin") and d.get("user_pin") == d.get("admin_pin"):
        raise ValueError(_("使用者和顧問的 PIN 碼不能一樣"))
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(p + ".tmp", p)
    old = os.path.join(data_root, OLD_FILE)
    if os.path.exists(old):
        os.remove(old)                                 # moved: the design must not keep the PINs


def login(data_root, pin):
    d = _read(data_root)
    h = _hash(str(pin).strip(), d.get("salt", ""))
    role = "admin" if d.get("admin_pin") == h else "user" if d.get("user_pin") == h else None
    if not role:
        time.sleep(1)                                  # slow down guessing
        return None, None
    token = secrets.token_urlsafe(24)
    _sessions[token] = (role, time.time() + 30 * 86400)
    return token, role


def logout(token):
    _sessions.pop(token, None)


def role_of(host, token):
    """-> "admin" | "user" | None for a request."""
    if host in LOCAL:
        return "admin"
    s = _sessions.get(token or "")
    if s and s[1] > time.time():
        return s[0]
    return None


def design_locked(method, path):
    """A runtime does not change the design: is this a design change it must refuse?"""
    if method in ("GET", "HEAD", "OPTIONS") or not path.startswith("/api/") or project.edition() != "runtime":
        return False
    if path in RUNTIME_WRITE_EXACT and method == "POST":
        return False
    return path.startswith(RUNTIME_DESIGN_ONLY) or not path.startswith(RUNTIME_WRITE)


def allowed(role, method, path):
    if not path.startswith("/api/") or path in OPEN_API:
        return True                                    # the page itself; the sign-in calls
    if role == "admin":
        return True
    return role == "user" and ((method, path) in USER_API or method == "GET" and path.startswith(USER_GET_PREFIX))
