"""pack.json (方案包資訊): what a pack is and what it needs to run.

    {"format": 1,                          the version of this file's format (FORMAT)
     "id": "my_pack",                      lowercase letters, digits, _ and -; the folder name under <data>/packs/
     "name": "...", "description": "...",
     "version": "1.2.0",                   the pack's own version: MAJOR.MINOR.PATCH (a newer one replaces an older one)
     "author": "...", "license": "...", "homepage": "...",     (optional)
     "plugin": "my_plugin" | null,         the plugin in plugin/ (a Python package name), null for a design only
     "requires": {"platform": ">=0.1.0",   which Inspector versions can run it: comparisons joined by ","
                  "spec": 8},              the script spec the design is written in (automation/spec.py FORMAT)
     "requirements": "plugin/requirements.txt" | null,          Python packages the plugin needs (pip)
     "model": "<run>" | null,              the trained model in models/<run>/ it comes with
     "renamed": {"scripts": {"old": "new"}, ...},    what this version renamed, so the values people set for the old
                                           names come along when it is installed over an older one (project/renames.py)
     "created": epoch, "updated": epoch}

A pack folder: pack.json, plugin/, design/ (project.json + meta/), models/. Nothing in it belongs to one computer:
values the people running it change, PINs, chat bots and output secrets stay in the runtime folder.

check() says what keeps a pack from running here (errors) or what looks wrong (warnings); a pack with errors is not
loaded. An older pack.json (no "format") is read as format 1 with what it has.

    python -m project.manifest check <pack folder>
    python -m project.manifest upgrade <pack folder>       rewrite pack.json in the current format"""
import atomic
import argparse
import glob
import json
import os
import re
import sys
import time

from i18n import _

PLATFORM_VERSION = "0.2.0"          # this Inspector; raised with every release that changes what packs may rely on
FORMAT = 1
FILE = "pack.json"
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
PLUGIN = re.compile(r"[a-z][a-z0-9_]{0,63}")
VERSION = re.compile(r"\d+(\.\d+){0,2}")
FIELDS = ("format", "id", "name", "description", "version", "author", "license", "homepage", "plugin", "requires",
          "requirements", "model", "renamed", "created", "updated")


def parse_version(v):
    """'1.2' -> (1, 2, 0); None if it is not a version."""
    v = str(v or "").strip()
    if not VERSION.fullmatch(v):
        return None
    parts = [int(x) for x in v.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def satisfies(version, spec):
    """Does version meet spec (">=0.1, <1", "==0.2.1", "0.2" = "==0.2")? An empty spec allows any."""
    have = parse_version(version)
    for part in [p.strip() for p in str(spec or "").split(",") if p.strip()]:
        m = re.fullmatch(r"(>=|<=|==|!=|>|<)?\s*(\S+)", part)
        want = parse_version(m.group(2)) if m else None
        if have is None or want is None:
            return False
        op = m.group(1) or "=="
        if not {">=": have >= want, "<=": have <= want, "==": have == want, "!=": have != want,
                ">": have > want, "<": have < want}[op]:
            return False
    return True


def normalize(d):
    """pack.json in the current format, every field present (what an older file lacks gets its default)."""
    d = dict(d or {})
    out = {k: d.get(k) for k in FIELDS}
    out["format"] = d.get("format") or FORMAT
    out["name"] = d.get("name") or d.get("id") or ""
    out["description"] = d.get("description") or ""
    v = parse_version(d.get("version"))
    out["version"] = ".".join(map(str, v)) if v else (str(d["version"]) if d.get("version") else "0.1.0")
    req = dict(d.get("requires") or {})
    out["requires"] = {"platform": req.get("platform") or "", "spec": req.get("spec")}
    for k in ("author", "license", "homepage", "renamed"):
        if not out[k]:
            out.pop(k)
    return out


def design_spec(design):
    """The newest script spec any design file in <design>/meta is written in (0 if none says)."""
    top = 0
    for p in glob.glob(os.path.join(design, "meta", "**", "*.json"), recursive=True):
        if ".before_" in p:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("format"), int):
            top = max(top, d["format"])
    return top


def check(d, folder=None):
    """[(level, text)]: "error" = cannot run here, "warn" = runs, but something looks wrong."""
    from automation import spec
    out = []
    raw = d or {}
    d = normalize(raw)
    if d["format"] > FORMAT:
        out.append(("error", _("pack.json 是較新的格式 {f}(這個 Inspector 只懂到 {mine});請更新 Inspector", f=d["format"], mine=FORMAT)))
    if not ID.fullmatch(d["id"] or ""):
        out.append(("error", _("方案包代號「{id}」只能用小寫英文、數字、_ 和 -,並以英文字母開頭", id=d["id"])))
    if not parse_version(raw.get("version")):
        out.append(("warn", _("版本「{v}」不是 主.次.修 的格式(例如 1.2.0)", v=raw.get("version"))))
    if d["plugin"] and not PLUGIN.fullmatch(d["plugin"]):
        out.append(("error", _("外掛名稱「{p}」只能用小寫英文、數字和 _", p=d["plugin"])))
    from .renames import KINDS
    ren = raw.get("renamed")
    if ren is not None and not (isinstance(ren, dict) and all(k in KINDS and isinstance(v, dict) and all(
            isinstance(a, str) and isinstance(b, str) for a, b in v.items()) for k, v in ren.items())):
        out.append(("error", _("renamed 要像 {\"scripts\": {\"舊代號\": \"新代號\"}},種類只能是 {kinds}", kinds=", ".join(KINDS))))
    want = d["requires"]["platform"]
    if want and not satisfies(PLATFORM_VERSION, want):
        out.append(("error", _("這個方案包需要 Inspector {want},目前是 {mine}", want=want, mine=PLATFORM_VERSION)))
    s = d["requires"]["spec"]
    if isinstance(s, int) and s > spec.FORMAT:
        out.append(("error", _("設計用的是較新的腳本規範 v{s}(這個 Inspector 只懂到 v{mine});請更新 Inspector", s=s, mine=spec.FORMAT)))
    if folder:
        if d["id"] and os.path.basename(os.path.normpath(folder)) not in (d["id"], "."):
            out.append(("warn", _("資料夾名稱「{name}」和方案包代號「{id}」不同", name=os.path.basename(os.path.normpath(folder)), id=d["id"])))
        if d["plugin"] and not os.path.exists(os.path.join(folder, "plugin", "plugin.py")):
            out.append(("error", _("找不到外掛 {p}", p=os.path.join(folder, "plugin", "plugin.py"))))
        design = os.path.join(folder, "design")
        if os.path.isdir(design):
            top = design_spec(design)
            if isinstance(s, int) and 0 < s < top:                     # 0: a new pack's, before its design had files
                out.append(("warn", _("設計裡有用腳本規範 v{top} 寫的檔案,pack.json 寫的是 v{s}", top=top, s=s)))
    return out


def read(folder):
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return None


def write(folder, d):
    d = normalize(d)
    d["updated"] = time.time()
    d["created"] = d.get("created") or d["updated"]
    p = os.path.join(folder, FILE)
    os.makedirs(folder, exist_ok=True)
    atomic.write_json(p, d, ensure_ascii=False, indent=1)
    return d


def stamp(d, design=None):
    """What a pack written now says it needs: this Inspector's major.minor or newer, and the design's spec."""
    from automation import spec
    d = normalize(d)
    major, minor, _patch = parse_version(PLATFORM_VERSION)
    d["requires"] = {"platform": d["requires"]["platform"] or f">={major}.{minor}.0",
                     "spec": design_spec(design) if design else spec.FORMAT}
    if design and not d["description"]:
        try:
            with open(os.path.join(design, "project.json"), encoding="utf-8") as f:
                d["description"] = json.load(f).get("description") or ""
        except (OSError, ValueError):
            pass
    return d


def main():
    ap = argparse.ArgumentParser(prog="python -m project.manifest", description=_("方案包資訊(pack.json):檢查 / 升級"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("check", _("檢查方案包能不能在這個 Inspector 執行")), ("upgrade", _("把 pack.json 改寫成目前的格式"))):
        sub.add_parser(name, help=text).add_argument("folder")
    a = ap.parse_args()
    try:
        with open(os.path.join(a.folder, FILE), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(_("讀不到 {p}:{e}", p=os.path.join(a.folder, FILE), e=e))
    if a.cmd == "upgrade":
        d = write(a.folder, stamp(raw, os.path.join(a.folder, "design")))
        print(json.dumps(d, ensure_ascii=False, indent=1))
        raw = d
    problems = check(raw, a.folder)
    for level, text in problems:
        print(("✗ " if level == "error" else "! ") + text)
    if not problems:
        print(_("沒有問題:可以在 Inspector {v} 執行", v=PLATFORM_VERSION))
    return 1 if any(lv == "error" for lv, _t in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
