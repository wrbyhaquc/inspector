"""Moving the work folder (更換資料位置): what working on the packs makes - recordings, labels, answers, models, the
run's records - to another folder or disk, by the platform itself.

    python -m project.relocate --to <folder>          copy, check, then use it (inspector.json "work")
    python -m project.relocate --delete-old           after the restart: delete the old copy

The work folder is the parent of every pack's (<work>/<pack id>/). Moving it:
  1. copy every file to the new folder (one already there with the same size and time is skipped, so a move that
     stopped half way goes on from where it was)
  2. check: every file there, the same size
  3. inspector.json "work" = the new folder; the platform uses it after a restart (the server knows its folders
     from the start)
  4. the old folder stays until it is deleted on purpose (--delete-old), once the new one is seen to work
Progress is <state file> (STATE, beside inspector.json): {"phase": "copy" | "check" | "done" | "failed" | "deleting" |
"deleted", "from", "to", "files", "files_done", "bytes", "bytes_done", "error", "t"}.
What writes to the work folder (recording, the script runner, training) is stopped first by the server."""
import argparse
import json
import os
import shutil
import sys
import time

import atomic
import project
from i18n import _

STATE = os.path.join(os.path.dirname(project.MACHINE), "relocate.json")
MARGIN = 1.05                 # the new disk must have this much more free than the data (and 1 GB)
OWN_LOG = "_relocate.log"     # this job's own log (<work>/<pack>/.jobs/): it grows while the move runs


def state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    st["t"] = time.time()
    atomic.write_json(STATE, st, ensure_ascii=False, indent=1)


def current():
    """The work folder now (the parent of every pack's): inspector.json "work", else <data>/work. None: this computer
    uses a single project folder, or INSPECTOR_WORK decides (then the platform does not move it)."""
    if os.environ.get("INSPECTOR_WORK"):
        return None
    home = project.data_home()
    if not home:
        return None
    return os.path.abspath(project.machine().get("work") or os.path.join(home, "work"))


def _walk(root):
    """[(relative path, size, mtime)] of every file under root"""
    out = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, root), st.st_size, st.st_mtime))
    return out


def check(to):
    """-> {"ok", "problems": [text], "from", "to", "bytes", "files", "free"}: can the work folder move there?"""
    old = current()
    out = {"ok": False, "problems": [], "from": old, "to": None, "bytes": 0, "files": 0, "free": None}
    if not old:
        out["problems"].append(_("這台的資料位置由環境變數 INSPECTOR_WORK 或舊的單一專案資料夾決定,不能在這裡搬"))
        return out
    to = (to or "").strip().strip('"')
    if not to or not os.path.isabs(to):
        out["problems"].append(_("請填完整的資料夾路徑,例如 E:\\InspectorWork"))
        return out
    to = os.path.abspath(to)
    out["to"] = to
    if os.path.normcase(to) == os.path.normcase(old):
        out["problems"].append(_("這就是現在的位置"))
        return out
    if project.inside(to, old) or project.inside(old, to):
        out["problems"].append(_("新位置不能在現在的位置裡面,也不能包含它"))
        return out
    if project.inside(to, project.APP_DIR):
        out["problems"].append(_("不能放在程式資料夾裡(更新程式時會被換掉)"))
        return out
    files = _walk(old) if os.path.isdir(old) else []
    out["files"], out["bytes"] = len(files), sum(s for _p, s, _m in files)
    try:
        os.makedirs(to, exist_ok=True)
        probe = os.path.join(to, ".inspector_write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        out["problems"].append(_("新位置不能寫入:{e}", e=e))
        return out
    st = state()
    ours = bool(st.get("to")) and os.path.normcase(st["to"]) == os.path.normcase(to) and st.get("from") == old
    if not ours and any(True for _e in os.scandir(to)):
        out["problems"].append(_("新位置已經有別的檔案;請選一個空的資料夾"))
    have = {p: s for p, s, _m in _walk(to)} if ours else {}               # a move that stopped half way: what is there
    need = out["bytes"] - sum(have.get(p, 0) for p, _s, _m in files)          # a move that stopped: the rest only
    out["free"] = shutil.disk_usage(to).free
    if out["free"] < need * MARGIN + 2 ** 30:
        out["problems"].append(_("新位置的磁碟空間不夠:要 {need} GB,只剩 {free} GB", need=round(need * MARGIN / 2 ** 30 + 1, 1),
                                 free=round(out["free"] / 2 ** 30, 1)))
    out["ok"] = not out["problems"]
    return out


def move(to):
    c = check(to)
    if not c["ok"]:
        raise SystemExit("\n".join(c["problems"]))
    old, to = c["from"], c["to"]
    files = _walk(old)
    st = {"phase": "copy", "from": old, "to": to, "files": len(files), "files_done": 0, "bytes": c["bytes"], "bytes_done": 0,
          "error": None, "started": time.time()}
    _save(st)
    print(_("搬移 {old} → {to}:{n} 個檔案、{gb} GB", old=old, to=to, n=len(files), gb=round(c["bytes"] / 2 ** 30, 2)), flush=True)
    try:
        last = 0.0
        for rel, size, mtime in files:
            src, dst = os.path.join(old, rel), os.path.join(to, rel)
            try:
                d = os.stat(dst)
                same = d.st_size == size and abs(d.st_mtime - mtime) < 2
            except OSError:
                same = False
            if not same:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            st["files_done"] += 1
            st["bytes_done"] += size
            if time.time() - last > 1:
                _save(st)
                last = time.time()
        st["phase"] = "check"
        _save(st)
        for _pass in range(3):                          # a file written to meanwhile (a cache, a log): copied again
            now = {p: s for p, s, _m in _walk(old) if not p.endswith(OWN_LOG)}
            there = {p: s for p, s, _m in _walk(to)}
            bad = [p for p, s in now.items() if there.get(p) != s]
            if not bad:
                break
            for p in bad:
                os.makedirs(os.path.dirname(os.path.join(to, p)), exist_ok=True)
                shutil.copy2(os.path.join(old, p), os.path.join(to, p))
        if bad:
            raise RuntimeError(_("新位置有 {n} 個檔案不對(例如 {p}),沒有改用新位置", n=len(bad), p=bad[0]))
        project.set_machine(work=to)
        st["phase"] = "done"
        _save(st)
        print(_("搬好了:{n} 個檔案都核對過;重新啟動後改用 {to}(舊位置的資料還在,確認沒問題再刪)", n=len(files), to=to), flush=True)
    except BaseException as e:                           # noqa: BLE001 - said, then stopped; the old folder is untouched
        st["phase"], st["error"] = "failed", str(e)
        _save(st)
        raise


def delete_old():
    st = state()
    old, to = st.get("from"), st.get("to")
    now = current()
    if st.get("phase") not in ("done", "deleting") or not old or not now or os.path.normcase(now) != os.path.normcase(to or ""):
        raise SystemExit(_("沒有可以刪的舊位置(還沒搬好,或已經不是用新位置)"))
    if os.environ.get("INSPECTOR_RUNNING_WORK") and os.path.normcase(os.environ["INSPECTOR_RUNNING_WORK"]) == os.path.normcase(old):
        raise SystemExit(_("Inspector 還在用舊位置;請先重新啟動"))
    st["phase"] = "deleting"
    _save(st)
    shutil.rmtree(old, ignore_errors=True)
    st["phase"] = "deleted" if not os.path.exists(old) else "done"
    if os.path.exists(old):
        st["error"] = _("有些檔案刪不掉(可能還開著),舊位置還在:{old}", old=old)
    _save(st)
    print(_("舊位置已刪除:{old}", old=old) if st["phase"] == "deleted" else st["error"], flush=True)


def main():
    ap = argparse.ArgumentParser(prog="python -m project.relocate", description=_("更換資料位置"))
    ap.add_argument("--to", help=_("新的資料位置(資料夾)"))
    ap.add_argument("--delete-old", action="store_true", help=_("刪除搬移前的舊位置"))
    a = ap.parse_args()
    if a.delete_old:
        delete_old()
    elif a.to:
        move(a.to)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
