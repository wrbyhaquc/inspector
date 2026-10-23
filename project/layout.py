"""Move a single project folder into the data folder layout (project/__init__.py), without touching the original.

    python -m project.layout migrate --project <old project folder> --data <data folder> [--work <work folder>]
                                     [--runtime <old runtime folder>] [--pack <pack folder> | --plugin <folder>]
                                     [--id <pack id>] [--link] [--activate]

What goes where:
  <project>/project.json, meta/     -> <data>/packs/<id>/design/   (PINs and output secrets go to the runtime instead)
  the plugin (--pack's plugin/, --plugin, or <app folder>/packs/<name>/)  -> <data>/packs/<id>/plugin/
  --pack's pack.json (or a new one) -> <data>/packs/<id>/pack.json
  everything else in <project>      -> <work>/<id>/                (sessions, labels, testset, models, shadow ...)
  <runtime> (or <project>/.runtime) -> <data>/runtime/<id>/

It only reads the old folders. Run it again to bring the copy up to date: files that did not change are skipped.
--link hard-links pictures and model files instead of copying them (same disk only: no extra space, and those files
are never rewritten in place); text files are always copied, so nothing written later reaches the original.
Absolute paths of the old folders inside json / jsonl files are rewritten to the new ones.
--activate makes this machine use the new layout (inspector.json "data" / "work", <data>/active.json); taking "data"
out of inspector.json again goes back to the old folder."""
import atomic
import argparse
import json
import os
import shutil
import sys

from . import APP_DIR, FILE, inside, manifest, set_machine
from i18n import _

LINK = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".npy", ".npz", ".pt", ".pth", ".onnx", ".bin", ".mp4", ".avi"}
TEXT = {".json", ".jsonl"}
SKIP_NAMES = {"inspector.lock", "__pycache__", ".git"}
SECRET_META = {"access.json"}


class Copier:
    def __init__(self, link, rewrite):
        self.link, self.rewrite = link, rewrite          # rewrite: [(old text, new text)]
        self.n = {"copied": 0, "linked": 0, "rewritten": 0, "skipped": 0}
        self.bytes = 0

    def _fresh(self, src, dst):
        return os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src)

    def file(self, src, dst):
        if self._fresh(src, dst):
            self.n["skipped"] += 1
            return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        ext = os.path.splitext(src)[1].lower()
        if ext in TEXT and self.rewrite:
            with open(src, encoding="utf-8", errors="surrogateescape") as f:
                s = f.read()
            t = s
            for a, b in self.rewrite:
                t = t.replace(a, b)
            if t != s:
                atomic.write_text(dst, t, errors="surrogateescape")
                self.n["rewritten"] += 1
                return
        if self.link and ext in LINK:
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                os.link(src, dst)
                self.n["linked"] += 1
                return
            except OSError:
                pass                                     # another disk: copy instead
        shutil.copy2(src, dst)
        self.n["copied"] += 1
        self.bytes += os.path.getsize(src)

    def tree(self, src, dst, skip=()):
        if not os.path.isdir(src):
            return
        for dirpath, dirs, files in os.walk(src):
            rel = os.path.relpath(dirpath, src)
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES and not (rel == "." and d in skip)]
            for f in files:
                if f in SKIP_NAMES or f.endswith(".tmp") or (rel == "." and f in skip):
                    continue
                self.file(os.path.join(dirpath, f), os.path.normpath(os.path.join(dst, rel, f)))


def _forms(path):
    """How a folder path can appear inside json text: escaped backslashes and forward slashes."""
    p = os.path.normpath(os.path.abspath(path))
    return [json.dumps(p)[1:-1], p.replace("\\", "/")]


def _write_json(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    atomic.write_json(p, d, ensure_ascii=False, indent=1)


def migrate(project, data, work=None, runtime=None, pack=None, plugin=None, pid=None, link=False, activate=False):
    project = os.path.abspath(project)
    if not os.path.exists(os.path.join(project, FILE)):
        raise SystemExit(_("{project} 不是專案資料夾(沒有 project.json)", project=project))
    with open(os.path.join(project, FILE), encoding="utf-8") as f:
        pj = json.load(f)
    info = {}
    if pack:
        with open(os.path.join(pack, "pack.json"), encoding="utf-8") as f:
            info = json.load(f)
    pid = pid or info.get("id") or pj.get("id") or "default"
    plugin_name = info.get("plugin") or (pj.get("plugins") or [None])[0]
    plugin_src = (os.path.join(pack, "plugin") if pack else plugin
                  or (os.path.realpath(os.path.join(APP_DIR, "packs", plugin_name)) if plugin_name else None))
    runtime = runtime or os.path.join(project, ".runtime")
    data = os.path.abspath(data)
    work_base = os.path.abspath(work) if work else os.path.join(data, "work")
    dst_pack, dst_work, dst_rt = (os.path.join(data, "packs", pid), os.path.join(work_base, pid),
                                  os.path.join(data, "runtime", pid))
    for d in (dst_pack, dst_work, dst_rt):
        if inside(d, project):
            raise SystemExit(_("新的位置不能在舊的專案資料夾裡面:{d}", d=d))
    rewrite = list(zip(_forms(project), _forms(dst_work))) + list(zip(_forms(runtime), _forms(dst_rt)))

    c = Copier(link, rewrite)
    print(_("設計 → {d}", d=os.path.join(dst_pack, "design")), flush=True)
    c.file(os.path.join(project, FILE), os.path.join(dst_pack, "design", FILE))
    c.tree(os.path.join(project, "meta"), os.path.join(dst_pack, "design", "meta"), skip=SECRET_META)
    if plugin_src and os.path.isdir(plugin_src):
        print(_("外掛 → {d}", d=os.path.join(dst_pack, "plugin")), flush=True)
        c.tree(plugin_src, os.path.join(dst_pack, "plugin"))
    if not os.path.exists(os.path.join(dst_pack, manifest.FILE)):
        manifest.write(dst_pack, manifest.stamp({"name": pj.get("name") or pid, "plugin": plugin_name, **info, "id": pid},
                                                os.path.join(dst_pack, "design")))
    print(_("工作資料 → {d}", d=dst_work), flush=True)
    c.tree(project, dst_work, skip={FILE, "meta", ".runtime"})
    print(_("執行資料 → {d}", d=dst_rt), flush=True)
    c.tree(runtime, dst_rt)

    # secrets the old design kept: PINs, and the secret fields of outputs
    old_access = os.path.join(project, "meta", "access.json")
    if os.path.exists(old_access) and not os.path.exists(os.path.join(dst_rt, "access.json")):
        shutil.copy2(old_access, os.path.join(dst_rt, "access.json"))
    outs_p = os.path.join(dst_pack, "design", "meta", "outputs.json")
    if os.path.exists(outs_p):
        from automation import outputs
        with open(outs_p, encoding="utf-8") as f:
            d = json.load(f)
        d["outputs"], secret = outputs.strip_secrets(d.get("outputs") or [])
        if secret:
            sp = os.path.join(dst_rt, outputs.SECRETS)
            old = {}
            if os.path.exists(sp):
                with open(sp, encoding="utf-8") as f:
                    old = json.load(f)
            _write_json(sp, {**old, **secret})
            _write_json(outs_p, d)

    if activate:
        _write_json(os.path.join(data, "active.json"), {"pack": pid})
        set_machine(data=data, work=work_base if work else None)
    print(_("完成:複製 {copied} 個、連結 {linked} 個、改寫路徑 {rewritten} 個、沒變略過 {skipped} 個檔案(複製了 {mb} MB)",
            mb=round(c.bytes / 1e6), **c.n), flush=True)
    if activate:
        print(_("這台電腦已改用新的資料位置;重新啟動 Inspector 後生效"), flush=True)
    return {"pack": dst_pack, "work": dst_work, "runtime": dst_rt, **c.n}


def main():
    ap = argparse.ArgumentParser(prog="python -m project.layout",
                                 description=_("資料位置:把一個專案資料夾搬成「方案包 / 工作資料 / 執行資料」分開的結構"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help=_("複製舊的專案資料夾到新的結構(不動原檔;再執行一次會補上新的變更)"))
    m.add_argument("--project", required=True, help=_("舊的專案資料夾"))
    m.add_argument("--data", required=True, help=_("新的資料根目錄"))
    m.add_argument("--work", default=None, help=_("工作資料放的位置(預設 <data>/work;可放別顆磁碟)"))
    m.add_argument("--runtime", default=None, help=_("舊的執行資料夾(預設 <project>/.runtime)"))
    m.add_argument("--pack", default=None, help=_("方案包資料夾(有 pack.json 與 plugin/)"))
    m.add_argument("--plugin", default=None, help=_("外掛資料夾(沒有方案包時)"))
    m.add_argument("--id", default=None, help=_("方案包代號(預設 pack.json 或 project.json 的 id)"))
    m.add_argument("--link", action="store_true", help=_("圖片與模型檔用硬連結,不另外佔空間(同一顆磁碟)"))
    m.add_argument("--activate", action="store_true", help=_("完成後讓這台電腦改用新的位置"))
    a = ap.parse_args()
    migrate(a.project, a.data, a.work, a.runtime, a.pack, a.plugin, a.id, a.link, a.activate)


if __name__ == "__main__":
    sys.exit(main())
