r"""Programs the Android category may use on this computer.

  adb        params "adb", else adb on PATH, else the one LDPlayer brings
  ldconsole  LDPlayer's console (the LDPlayer preset's "ldconsole" discovery / text input): params "ldplayer_dir",
             else inspector.json "ldplayer_dir", else C:\LDPlayer\LDPlayer9"""
import os
import shutil

import project


def ldplayer_dir(params=None):
    return (params or {}).get("ldplayer_dir") or project.machine().get("ldplayer_dir") or r"C:\LDPlayer\LDPlayer9"


def ldconsole(params=None):
    return os.path.join(ldplayer_dir(params), "ldconsole.exe")


def adb(params=None):
    p = (params or {}).get("adb") or ""
    if p and os.path.exists(p):
        return p
    ld = os.path.join(ldplayer_dir(params), "adb.exe")
    if (params or {}).get("discovery") == "ldconsole" and os.path.exists(ld):
        return ld                                   # LDPlayer's own adb matches its emulators best
    return shutil.which("adb") or ld
