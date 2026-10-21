"""Interface languages (多語系) of the server and the runtime.

The platform is written in Traditional Chinese and the Chinese text itself is the key: _("子腳本失敗") is that text in
繁體中文, and in another language what its catalog gives (i18n/locales/<lang>.json, {"子腳本失敗": "..."}); a text a
catalog lacks falls back to the Chinese. Values go in by name: _("第 {n} 步", n=3) - keep the whole sentence in one
text so a language with another word order can move the values. Only {name}s that are given are filled in, so a text
may show other braces as they are.

Which language: a web request's (the page sends X-Lang; server/app.py sets it for that request), else this machine's
(inspector.json "language"), else Traditional Chinese. The runtime writes its log lines and notices in this machine's
language. tools/i18n.py lists every text in use (i18n/zh-TW.json, the full list to translate) and what each language
still lacks."""
import contextvars
import json
import os
import re
import time

BASE = "zh-TW"
NAMES = {"zh-TW": "繁體中文", "en": "English", "zh-CN": "简体中文", "ja": "日本語", "ko": "한국어"}
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_current = contextvars.ContextVar("i18n_lang", default=None)
_catalogs = {}
_machine = [0.0, None]                                   # [read at, language]
_PLACE = re.compile(r"\{(\w+)\}")
_PLURAL = re.compile(r"\{(\w+)\|([^|{}]*)\|([^|{}]*)\}")


def _is_one(v):
    try:
        return float(v) == 1
    except (TypeError, ValueError):
        return False


def catalog(lang):
    """lang's texts {chinese: translated} (empty for the base language or a missing file)."""
    if lang == BASE:
        return {}
    got = _catalogs.get(lang)
    if got and time.time() - got[2] < 2:               # an edited catalog is picked up within 2 seconds
        return got[1]
    p = os.path.join(DIR, f"{lang}.json")
    try:
        stamp = os.path.getmtime(p)
    except OSError:
        _catalogs[lang] = (None, {}, time.time())
        return {}
    if not got or got[0] != stamp:
        try:
            with open(p, encoding="utf-8") as f:
                got = (stamp, json.load(f), time.time())
        except (OSError, ValueError):
            got = (None, {}, time.time())
    _catalogs[lang] = (got[0], got[1], time.time())
    return got[1]


def available():
    """The languages that can be used now: the base one and those with a catalog."""
    return [l for l in NAMES if l == BASE or catalog(l)]


def default():
    """This machine's language (inspector.json "language")."""
    if time.time() - _machine[0] < 2:
        return _machine[1]
    try:
        from project import machine
        lang = machine().get("language")
    except Exception:                                   # noqa: BLE001 - no project yet
        lang = None
    _machine[:] = [time.time(), lang if lang in NAMES else BASE]
    return _machine[1]


def current():
    return _current.get() or default()


def use(lang):
    """Use lang from here on in this context (a web request); -> a token for reset()."""
    return _current.set(lang if lang in NAMES else None)


def reset(token):
    _current.reset(token)


def N_(msg):
    """Mark a text for translation without translating it now (a module-level table: translate it where it is shown,
    with _(), so each request gets its own language)."""
    return msg


def tr(obj, **values):
    """A table of N_() texts in the current language: every text value in it (nested dicts / lists, not the keys)."""
    if isinstance(obj, str):
        return _(obj, **values)
    if isinstance(obj, dict):
        return {k: tr(v, **values) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(tr(v, **values) for v in obj)
    return obj


def _(msg, **values):
    """msg in the current language, with {name} filled in from values."""
    lang = current()
    s = (catalog(lang).get(msg) if lang != BASE else None) or msg
    if not values:
        return s
    # a translation may pick a word by a count: {n|frame|frames} (the first when n is 1)
    s = _PLURAL.sub(lambda m: m.group(0) if values.get(m.group(1)) is None else
                    m.group(2) if _is_one(values[m.group(1)]) else m.group(3), s)
    return _PLACE.sub(lambda m: str(values[m.group(1)]) if values.get(m.group(1)) is not None else m.group(0), s)


_reverse = {}


def relang(text):
    """A whole sentence the runtime wrote in this machine's language, in the current language instead (a value-free
    text only; anything else comes back as it is)."""
    src, dst = default(), current()
    if not isinstance(text, str) or not text or src == dst:
        return text
    msg = text
    if src != BASE:
        cat = catalog(src)
        rev = _reverse.get(src)
        if not rev or rev[0] is not cat:
            rev = _reverse[src] = (cat, {v: k for k, v in cat.items()})
        msg = rev[1].get(text)
        if msg is None:
            return text
    elif _PLACE.search(text):
        return text
    return (catalog(dst).get(msg) if dst != BASE else None) or msg
