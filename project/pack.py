"""方案包 (pack): a whole use of the platform - a plugin and a design - made into a release others install.

The folder a pack is developed in and the folder it is installed in look the same (<data>/packs/<id>/):
      pack.json        what the pack is and what it needs (project/manifest.py)
      README.md
      plugin/          the plugin (code, reference images, requirements.txt)
      design/          project.json + meta/: states, reference images, buttons, lists, scripts, sub-scripts,
                       variables, schedules, panel, user settings, templates, name galleries
      models/<run>/    the trained model it comes with, as ONNX (model.onnx, model.json) and its test report, so the
                       runtime can run it without PyTorch
The pack being developed is usually a git working folder; a release is what export makes of it: one zip,
<id>-<version>.zip, without the history, backups, logs or older versions of scripts. Nothing that belongs to one
computer is ever in either (recordings, labels, values people changed, PINs, chat bots, output secrets: they live in
the work and runtime folders), so installing a newer release keeps all of it.

    python -m project.pack export [--out <folder>] [--version 1.2.0] [--model latest] [--folder]
    python -m project.pack install <zip or folder> [--data <data folder>] [--activate] [--force]
    python -m project.pack list [--data <data folder>]
    python -m project.pack use <id> [--data <data folder>]

export takes the active pack (data folder layout); in the single-folder layout, --plugin <name> and the project.
install puts a new pack in <data>/packs/<id>/, or upgrades the one there to a newer version (the previous one is kept
in <data>/packs/.previous/); it never overwrites a pack that is being developed (a git working folder)."""
import atomic
import argparse
import fnmatch
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

from . import FILE, active_pack, data_home, data_root, load, manifest, models_of, pack_dir
from .plugins import plugin_dir
from i18n import _

SKIP = ["*.before_*", "*.tmp", "*_log.jsonl", "__pycache__", "*.pyc", ".git", ".gitignore", ".gitattributes",
        ".deleted",                                    # deleted scripts / sub-scripts: the designer's bin, not shipped
        "access.json"]                                 # PINs of an older layout (they live in the runtime folder now)
MODEL_FILES = ("model.onnx", "model.json", "eval.json", "predictions.jsonl", "config.json", "metrics.jsonl", "status.json")


def _skip(name):
    return any(fnmatch.fnmatch(name, p) for p in SKIP)


def _copy_tree(src, dst):
    """Copy a folder; a folder with current.json = {"version": N} keeps only current.json and v<N>.json."""
    os.makedirs(dst, exist_ok=True)
    names = os.listdir(src)
    keep = None
    if "current.json" in names:
        try:
            with open(os.path.join(src, "current.json"), encoding="utf-8") as f:
                v = json.load(f).get("version")
            keep = {"current.json", f"v{v}.json", "settings.json"}
        except (OSError, ValueError, AttributeError):
            keep = None
    n = 0
    for name in names:
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if _skip(name):
            continue
        if os.path.isdir(s):
            n += _copy_tree(s, d)
        elif keep is None or name in keep or not (name.startswith("v") and name.endswith(".json")):
            shutil.copy2(s, d)
            n += 1
    return n


def _model_run(root, model):
    from runtime import judge
    run = judge.latest_run(root) if model == "latest" else os.path.join(models_of(root), model)
    if not run or not os.path.exists(os.path.join(run, "model.onnx")):
        raise SystemExit(_("找不到這次訓練的 ONNX 模型({run});先執行 python -m trainer.onnx_export --all", run=run))
    return run


def _strip_output_secrets(path):
    """An outputs.json saved before secrets moved out may still hold some: the release gets it without them."""
    if not os.path.exists(path):
        return
    from automation import outputs
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d["outputs"], _secret = outputs.strip_secrets(d.get("outputs") or [])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


# ---------------- export ----------------

def export(out=None, version=None, model=None, folder=False, plugin=None, root=None, say=print):
    """Make a release of the active pack (or, in the single-folder layout, of --plugin and the project)."""
    src = pack_dir()
    if src:
        design = os.path.join(src, "design")
        info = manifest.read(src) or manifest.normalize({"id": active_pack()})
        plugin = info["plugin"]
        src_plugin = os.path.join(src, "plugin") if plugin else None
    else:
        design = root or data_root()
        p = load(design)
        if not plugin:
            raise SystemExit(_("請用 --plugin 指定要放進方案包的外掛"))
        if plugin not in (p.get("plugins") or []):
            raise SystemExit(_("目前的專案({root})沒有使用外掛 {plugin}", root=design, plugin=plugin))
        info = manifest.normalize({"id": p.get("id") or plugin, "name": p.get("name"), "plugin": plugin})
        src_plugin = plugin_dir(plugin)
    if src_plugin and not os.path.isfile(os.path.join(src_plugin, "plugin.py")):
        raise SystemExit(_("找不到外掛 {src_plugin}", src_plugin=src_plugin))
    if version:
        if not manifest.parse_version(version):
            raise SystemExit(_("版本「{v}」不是 主.次.修 的格式(例如 1.2.0)", v=version))
        info["version"] = version
        if src:                                       # the pack being developed records the version it released
            manifest.write(src, {**info})
    run = _model_run(design, model) if model else None
    info = manifest.stamp({**info, "model": os.path.basename(run) if run else None,
                           "requirements": "plugin/requirements.txt" if src_plugin and os.path.exists(
                               os.path.join(src_plugin, "requirements.txt")) else None}, design)
    errors = [t for lv, t in manifest.check(info) if lv == "error"]
    if errors:
        raise SystemExit(_("這個方案包不能匯出:") + "; ".join(errors))

    out = os.path.abspath(out or os.path.join(data_home() or os.path.dirname(design), "releases"))
    name = f"{info['id']}-{info['version']}"
    with tempfile.TemporaryDirectory(dir=out if os.path.isdir(out) else None) as tmp:
        stage = os.path.join(tmp, name)
        n_plugin = _copy_tree(src_plugin, os.path.join(stage, "plugin")) if src_plugin else 0
        os.makedirs(os.path.join(stage, "design"), exist_ok=True)
        shutil.copy2(os.path.join(design, FILE), os.path.join(stage, "design", FILE))
        meta = os.path.join(design, "meta")               # (a pack only just begun has none yet)
        n_design = _copy_tree(meta, os.path.join(stage, "design", "meta")) if os.path.isdir(meta) else 0
        _strip_output_secrets(os.path.join(stage, "design", "meta", "outputs.json"))
        if run:
            dst = os.path.join(stage, "models", os.path.basename(run))
            os.makedirs(dst, exist_ok=True)
            for f in MODEL_FILES:
                if os.path.exists(os.path.join(run, f)):
                    shutil.copy2(os.path.join(run, f), dst)
        readme = next((os.path.join(d, "README.md") for d in (src, src_plugin)
                       if d and os.path.isfile(os.path.join(d, "README.md"))), None)
        if readme:
            shutil.copy2(readme, os.path.join(stage, "README.md"))
        manifest.write(stage, {**info, "created": info.get("created") or time.time()})
        os.makedirs(out, exist_ok=True)
        if folder:
            target = os.path.join(out, name)
            if os.path.exists(target):
                shutil.rmtree(target)
            shutil.move(stage, target)
        else:
            target = os.path.join(out, name + ".zip")
            with zipfile.ZipFile(target + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
                for dirpath, _dirs, files in os.walk(stage):
                    for f in files:
                        p = os.path.join(dirpath, f)
                        z.write(p, os.path.relpath(p, stage).replace("\\", "/"))
            os.replace(target + ".tmp", target)
    say(_("已匯出方案包 {name} {version} 到 {out}:外掛 {n_plugin} 個檔案,設計 {n_design} 個檔案",
            name=info["name"], version=info["version"], out=target, n_plugin=n_plugin, n_design=n_design)
          + (_(",模型 {model}", model=info["model"]) if run else ""))
    return target


def releases(out, pid):
    """[(version, path)] of pid's releases (.zip) in out, oldest first."""
    found = []
    for f in os.listdir(out) if out and os.path.isdir(out) else []:
        if f.startswith(pid + "-") and f.endswith(".zip"):
            v = manifest.parse_version(f[len(pid) + 1:-4])
            if v:
                found.append((v, os.path.join(out, f)))
    return sorted(found)


def _hashes(entries):
    """{path: sha1} of a release's files; pack.json without what changes every time (its times, the version)."""
    import hashlib
    out = {}
    for name, data in entries:
        if name == "pack.json":
            d = json.loads(data)
            data = json.dumps({k: v for k, v in d.items() if k not in ("created", "updated", "version")}, sort_keys=True).encode()
        out[name] = hashlib.sha1(data).hexdigest()
    return out


def _tree(folder):
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                yield os.path.relpath(p, folder).replace("\\", "/"), fh.read()


def _zip(path):
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not n.endswith("/"):
                yield n, z.read(n)


def export_check(model=None, out=None):
    """Before exporting the active pack from the page: what it is, its last release and what changed since, and what
    to look at first - [{"level": "error" | "warn" | "ok" | "info", "text"}] (an error keeps it from exporting)."""
    import automation
    from automation import outputs, spec_schema, subs as subs_mod, tests as tests_mod
    from . import runtime_dir
    src = pack_dir()
    if not src:
        raise ValueError(_("只有資料目錄結構的方案包能在這裡匯出"))
    design = os.path.join(src, "design")
    info = manifest.read(src) or manifest.normalize({"id": active_pack()})
    out = os.path.abspath(out or os.path.join(data_home(), "releases"))
    checks = []

    def add(level, text):
        checks.append({"level": level, "text": text})

    for lv, t in manifest.check(info):
        add(lv, t)
    scripts = automation.load_all(design)
    bad = []
    for sc in scripts:
        bad += [_("主腳本「{name}」:{msg}", name=sc.get("name") or sc["id"], msg=e["message"])
                for e in spec_schema.check("script", sc, design)[:1]]
    for sid, sub in subs_mod.load_all(design).items():
        bad += [_("子腳本「{name}」:{msg}", name=sub.get("name") or sid, msg=e["message"])
                for e in spec_schema.check("sub", sub, design)[:1]]
    panel_file = os.path.join(design, "meta", "panel.json")
    if os.path.exists(panel_file):
        with open(panel_file, encoding="utf-8") as f:
            bad += [_("操作面板:{msg}", msg=e["message"]) for e in spec_schema.check("panel", json.load(f), design)[:1]]
    for b in bad:
        add("error", b)
    if not bad:
        add("ok", _("腳本、子腳本和操作面板都符合腳本規範 v{v}", v=__import__("automation.spec", fromlist=["FORMAT"]).FORMAT))
    for sc in scripts:
        if not any(sit.get("rules") for sit in sc.get("situations") or []):
            add("warn", _("主腳本「{name}」沒有任何規則,也會一起匯出(用不到就先刪掉)", name=sc.get("name") or sc["id"]))
    tests = tests_mod.load(design)
    if not tests:
        add("info", _("沒有腳本測試:建議從重播存幾個,匯出前先跑一次"))
    else:
        try:
            with open(os.path.join(runtime_dir(), "tests", "results.json"), encoding="utf-8") as f:
                res = json.load(f)
        except (OSError, ValueError):
            res = {}
        changed = max((os.path.getmtime(os.path.join(d, f)) for d, _x, fs in os.walk(os.path.join(design, "meta"))
                       for f in fs), default=0)
        failed = [t["name"] for t in tests if (res.get(t["id"]) or {}).get("status") in ("fail", "error")]
        stale = [t["name"] for t in tests if (res.get(t["id"]) or {}).get("run_at", 0) < changed]
        if failed:
            add("warn", _("{n} 個腳本測試沒通過:{names}", n=len(failed), names=_("、").join(failed[:5])))
        elif stale:
            add("warn", _("{n} 個腳本測試在設計改過之後還沒重跑(「腳本測試」頁)", n=len(stale)))
        else:
            add("ok", _("{n} 個腳本測試都通過", n=len(tests)))
    if model:
        run = _model_run(design, model)
        if not run:
            add("error", _("找不到要放進去的模型(還沒學習過?)"))
        else:
            from runtime import judge
            import schema as schema_mod
            st = judge.sources(schema_mod.load(design), run)["states"]
            fails = [s for s, v in st.items() if v.get("test") == "fail"]
            add("warn" if fails else "ok", _("模型「{run}」有 {n} 個狀態沒通過考試", run=os.path.basename(run), n=len(fails)) if fails
                else _("模型「{run}」每個學過的狀態都通過考試", run=os.path.basename(run)))
    for o in outputs.load(design).values():           # {id: output}
        if any(o.get(k) not in (None, "", {}) for k in outputs._secret_fields(o)):   # one filled in here
            add("info", _("輸出「{name}」的密碼或權杖不會放進方案包:安裝後要在那台電腦填", name=o.get("name") or o["id"]))
    rels = releases(out, info["id"])
    last = rels[-1] if rels else None
    with tempfile.TemporaryDirectory() as tmp:            # the very release export() would make, to compare
        target = export(out=tmp, model=model, folder=True, say=lambda *_a: None)
        now = _hashes(_tree(target))
    changes = None
    if last:
        before = _hashes(_zip(last[1]))
        changes = {"added": sorted(set(now) - set(before)), "removed": sorted(set(before) - set(now)),
                   "changed": sorted(k for k in set(now) & set(before) if now[k] != before[k])}
        if not any(changes.values()):
            add("info", _("和上一版 {v} 一模一樣", v=".".join(map(str, last[0]))))
    base = max([manifest.parse_version(info.get("version")) or (0, 1, 0)] + [v for v, _p in rels])
    nxt = f"{base[0]}.{base[1]}.{base[2] + 1}" if rels else ".".join(map(str, base))
    return {"pack": {k: info.get(k) for k in ("id", "name", "version", "description", "license", "homepage")},
            "next": nxt, "last": {"version": ".".join(map(str, last[0])), "file": os.path.basename(last[1])} if last else None,
            "checks": checks, "changes": changes, "files": len(now), "out": out}


# ---------------- install / upgrade ----------------

def _data(data=None):
    d = data or data_home()
    if not d:
        raise SystemExit(_("請用 --data 指定資料根目錄,或在 inspector.json 設定 \"data\"(見 README 的資料目錄結構)"))
    return os.path.abspath(d)


def _is_workspace(folder):
    return os.path.exists(os.path.join(folder, ".git"))


def install(src, data=None, activate=False, force=False, say=print):
    """Install a release (zip or folder) into <data>/packs/<id>/, or upgrade the one there."""
    data = _data(data)
    packs = os.path.join(data, "packs")
    os.makedirs(packs, exist_ok=True)
    incoming = tempfile.mkdtemp(prefix=".incoming-", dir=packs)
    try:
        stage = os.path.join(incoming, "pack")
        if os.path.isfile(src) and zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as z:
                for m in z.namelist():                   # nothing may land outside the folder
                    if os.path.isabs(m) or ".." in m.replace("\\", "/").split("/"):
                        raise SystemExit(_("方案包裡有不安全的路徑:{m}", m=m))
                z.extractall(stage)
        elif os.path.isdir(src):
            shutil.copytree(src, stage, ignore=shutil.ignore_patterns(".git"))
        else:
            raise SystemExit(_("找不到方案包 {src}", src=src))
        info = manifest.read(stage)
        if info is None:
            raise SystemExit(_("讀不到 {p}", p=os.path.join(src, manifest.FILE)))
        errors = [t for lv, t in manifest.check(info, None) if lv == "error"]
        if info["plugin"] and not os.path.isfile(os.path.join(stage, "plugin", "plugin.py")):
            errors.append(_("找不到外掛 {p}", p="plugin/plugin.py"))
        if not os.path.isfile(os.path.join(stage, "design", FILE)):
            errors.append(_("找不到設計 {p}", p="design/project.json"))
        if errors:
            raise SystemExit(_("這個方案包不能在這裡執行:") + "; ".join(errors))

        target = os.path.join(packs, info["id"])
        old = manifest.read(target) if os.path.isdir(target) else None
        if os.path.isdir(target):
            if _is_workspace(target) and not force:
                raise SystemExit(_("{target} 是開發中的方案包(git 工作資料夾),不會用安裝蓋過;要蓋過請加 --force", target=target))
            if old and not force and manifest.parse_version(info["version"]) <= (manifest.parse_version(old["version"]) or (0, 0, 0)):
                raise SystemExit(_("已經裝了 {id} {old} 版,這個是 {new} 版;要換成它請加 --force", id=info["id"], old=old["version"], new=info["version"]))
            prev = os.path.join(packs, ".previous", f"{info['id']}-{(old or {}).get('version') or 'old'}")
            if os.path.exists(prev):
                shutil.rmtree(prev)
            os.makedirs(os.path.dirname(prev), exist_ok=True)
            os.replace(target, prev)
        os.replace(stage, target)
    finally:
        shutil.rmtree(incoming, ignore_errors=True)

    if old:
        say(_("已把 {name} 從 {old} 版升級到 {new} 版(舊版留在 {prev});使用者的值、錄影與執行資料都保留",
                name=info["name"], old=old["version"], new=info["version"], prev=prev))
    else:
        say(_("已安裝 {name} {version} 到 {target}", name=info["name"], version=info["version"], target=target))
    left = {}
    rt = os.path.join(data, "runtime", info["id"])
    if old and os.path.isdir(rt):                       # the values set here follow what the new version renamed
        from . import renames, runtime_data
        if info.get("renamed"):
            runtime_data.backup(rt, runtime_data.read(rt).get("format", 0))
            n = renames.apply(rt, info["renamed"])
            if n:
                say(_("已依新版本的改名,把這台電腦設定過的值搬到新的代號({n} 處)", n=n))
        left = renames.orphans(os.path.join(target, "design"), rt)
        if left:
            say(_("這些設定過的值在新版本找不到對應的項目(不會再有作用):") + "; ".join(
                f"{k} {', '.join(v)}" for k, v in left.items()))
    if info.get("model"):
        say(_("已放入模型 {model}(ONNX,執行時不需要 PyTorch)", model=info["model"]))
    if info.get("requirements"):
        say(_("記得安裝外掛需要的套件:pip install -r {p1}", p1=os.path.normpath(os.path.join(target, info["requirements"]))))
    if activate:
        use(info["id"], data, say)
    elif _active(data) == info["id"]:
        say(_("它是目前執行中的方案包:重新啟動 Inspector 後生效"))
    elif say is print:
        say(_("要使用它:python -m project.pack use {id}", id=info["id"]))
    return {"id": info["id"], "version": info["version"], "old": (old or {}).get("version"), "target": target,
            "active": _active(data) == info["id"], "orphans": left}


def _active(data):
    try:
        with open(os.path.join(data, "active.json"), encoding="utf-8") as f:
            return json.load(f).get("pack")
    except (OSError, ValueError):
        return None


def installed(data=None):
    """[{id, name, version, active, workspace, problems}] for every pack in <data>/packs."""
    data = _data(data)
    packs = os.path.join(data, "packs")
    act = _active(data)
    out = []
    for name in sorted(os.listdir(packs)) if os.path.isdir(packs) else []:
        d = os.path.join(packs, name)
        if name.startswith(".") or not os.path.isdir(d):
            continue
        info = manifest.read(d) or manifest.normalize({"id": name})
        out.append({"id": name, "name": info["name"], "version": info["version"], "active": name == act,
                    "workspace": _is_workspace(d), "problems": manifest.check(info, d)})
    return out


def use(pid, data=None, say=print):
    data = _data(data)
    if not os.path.isdir(os.path.join(data, "packs", pid)):
        raise SystemExit(_("沒有裝 {id} 這個方案包", id=pid))
    p = os.path.join(data, "active.json")
    atomic.write_json(p, {"pack": pid})
    say(_("已改用方案包 {id};重新啟動 Inspector 後生效", id=pid))


def main():
    ap = argparse.ArgumentParser(prog="python -m project.pack", description=_("方案包:匯出 / 安裝 / 升級"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help=_("把目前的方案包匯出成一個發行版(zip)"))
    e.add_argument("--out", default=None, help=_("放到哪個資料夾(預設 <data>/releases)"))
    e.add_argument("--version", default=None, help=_("這次的版本(主.次.修);也會記在方案包的 pack.json"))
    e.add_argument("--model", default=None, help=_("一起放入的模型:latest(最新一次訓練)或訓練編號;只放 ONNX"))
    e.add_argument("--folder", action="store_true", help=_("輸出資料夾,不壓縮"))
    e.add_argument("--plugin", default=None, help=_("單一專案資料夾時:要放進去的外掛"))
    e.add_argument("--project", default=None, help=_("單一專案資料夾時:要匯出的專案(預設:目前的專案)"))
    i = sub.add_parser("install", help=_("安裝方案包,或升級成較新的版本"))
    i.add_argument("pack", help=_("方案包的 zip 或資料夾"))
    i.add_argument("--data", default=None, help=_("資料根目錄(預設 inspector.json 的 \"data\")"))
    i.add_argument("--activate", action="store_true", help=_("裝好後改用它"))
    i.add_argument("--force", action="store_true", help=_("同版或較舊的版本也裝,或蓋過開發中的方案包"))
    ls = sub.add_parser("list", help=_("列出裝了哪些方案包"))
    ls.add_argument("--data", default=None)
    u = sub.add_parser("use", help=_("改用另一個已安裝的方案包"))
    u.add_argument("id")
    u.add_argument("--data", default=None)
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.out, a.version, a.model, a.folder, a.plugin, a.project)
    elif a.cmd == "install":
        install(a.pack, a.data, a.activate, a.force)
    elif a.cmd == "use":
        use(a.id, a.data)
    else:
        for p in installed(a.data):
            marks = ("● " if p["active"] else "  ") + (_("[開發中] ") if p["workspace"] else "")
            print(f"{marks}{p['id']}  {p['version']}  {p['name']}")
            for lv, t in p["problems"]:
                print(("    ✗ " if lv == "error" else "    ! ") + t)


if __name__ == "__main__":
    sys.exit(main())
