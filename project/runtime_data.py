"""This computer's runtime folder (<data>/runtime/<id>/): what is in it, in which format, and how a folder written by an
older Inspector is brought up to date.

The pack's design has the script spec (automation/spec.py) and pack.json its format (project/manifest.py); the runtime
folder has FORMAT, in <runtime>/runtime.json {"format", "platform", "updated"}. A folder without it is format 0 (made
before this existed: the same files as format 1).

  KEPT     what the people running it set and what this computer has learned: an upgrade must carry every one of
           them over (and is the only thing that may change their format)
  PASSING  rewritten all the time, or queues and caches: may be dropped and rebuilt

Every start of the server and of the runner calls ensure(): an older folder is upgraded step by step (UPGRADES), after
a copy of everything KEPT is put in <runtime>/.backup/<time>-format<N>/ (the last 5 are kept); a folder written by a
newer Inspector is refused (RuntimeTooNew) rather than misread or overwritten - update Inspector, or restore a backup.

When a release changes the format of a KEPT file: raise FORMAT, add UPGRADES[old] = a function that rewrites the files,
and list any new KEPT file here."""
import atomic
import json
import os
import shutil
import time

from i18n import _

FORMAT = 1
FILE = "runtime.json"
BACKUPS = ".backup"
KEEP_BACKUPS = 5

KEPT = {
    "access.json": "sign-in PINs (server/access.py)",
    "output_secrets.json": "the secret fields of outputs (automation/outputs.py)",
    "notify.json": "notification channels and chat bots (notify/)",
    "notify_access.json": "who may command through a chat bot (notify/commands.py)",
    "sources.json": "this computer's sources, their names and tags (drivers/sources.py)",
    "user_settings_values.json": "values of the user settings (automation/settings.py)",
    "schedule_overrides.json": "schedules changed on the operation panel (automation/schedules.py)",
    "entry_args.json": "situation-entry arguments set on the panel, runtime edition (automation/__init__.py)",
    "settings": "script / state settings changed here, runtime edition (project/overlay.py)",
    "buttons.json": "names of lists walked here, runtime edition (automation/buttons.py)",
    "buttons": "their pictures",
    "list_scans.json": "what each list walk found (automation/lists.py)",
    "vars.json": "the scripts' variables (automation/)",
    "control.json": "paused / stopped devices and rules, the master switch (runtime/shadow.py)",
    "device_hold.json": "devices held by a person (runtime/shadow.py)",
    "runner_last.json": "how the runner was started last (server/app.py)",
    "schedules_state.json": "what the schedules ran today (automation/schedules.py)",
    "panel_log.jsonl": "what was changed and done on the operation panel (server/panel.py)",
    "panel_todo_ack.json": "panel to-dos already seen (server/app.py)",
    "commands.jsonl": "commands received from chat (notify/commands.py)",
    "claude_answers.jsonl": "answers given for the people (server/app.py)",
    "asks": "questions asked from the panel and their answers",
    "tests": "script test results (automation/tests.py)",
    "quality": "daily model quality notes (runtime/quality.py)",
}
PASSING = ("status.json", "notify_status.json", "inspector.lock", "live", "snaps", "view_cache", "replays",
           "act_requests", "flag_requests", "snap_requests", "sub_requests", "var_requests", "schedule_requests",
           "schedule_jobs", "train_cache")


class RuntimeTooNew(RuntimeError):
    pass


def _from_0(runtime_dir):
    """Format 0 (before runtime.json): the files are already those of format 1."""


UPGRADES = {0: _from_0}


def read(runtime_dir):
    try:
        with open(os.path.join(runtime_dir, FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _stamp(runtime_dir, fmt):
    from .manifest import PLATFORM_VERSION
    p = os.path.join(runtime_dir, FILE)
    atomic.write_json(p, {"format": fmt, "platform": PLATFORM_VERSION, "updated": time.time()}, indent=1)


def backup(runtime_dir, fmt):
    """A copy of everything KEPT, before an upgrade touches it -> the backup folder."""
    root = os.path.join(runtime_dir, BACKUPS)
    dst = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + f"-format{fmt}")
    os.makedirs(dst, exist_ok=True)
    for name in KEPT:
        src = os.path.join(runtime_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
    old = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for d in old[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    return dst


def ensure(runtime_dir, say=print):
    """Bring the runtime folder to FORMAT (backing it up first); refuse one written by a newer Inspector."""
    os.makedirs(runtime_dir, exist_ok=True)
    info = read(runtime_dir)
    fmt = info.get("format", 0) if isinstance(info.get("format", 0), int) else 0
    if fmt > FORMAT:
        raise RuntimeTooNew(_("執行資料夾 {d} 是較新的 Inspector({v})寫的(格式 {f},這個 Inspector 只懂到 {mine});請更新 Inspector,或從 {b} 還原備份",
                              d=runtime_dir, v=info.get("platform") or "?", f=fmt, mine=FORMAT, b=os.path.join(runtime_dir, BACKUPS)))
    if fmt == FORMAT:
        return None
    first_time = not os.listdir(runtime_dir)
    saved = None if first_time else backup(runtime_dir, fmt)
    while fmt < FORMAT:
        UPGRADES[fmt](runtime_dir)
        fmt += 1
    _stamp(runtime_dir, FORMAT)
    if saved:
        say(_("執行資料夾已更新到格式 {f}(原本的備份在 {b})", f=FORMAT, b=saved))
    return saved
