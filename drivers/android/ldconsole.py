"""LDPlayer's console (ldconsole.exe): its running instances (with their names) and their adb serials.
Used by the Android category when the LDPlayer preset's discovery is "ldconsole"."""
import re
import subprocess
from dataclasses import dataclass
from i18n import _


@dataclass
class Instance:
    index: int
    name: str
    vbox_pid: int
    width: int
    height: int
    adb_serial: str = None                       # None = no adb (no screenshots)


def _run(args, timeout=15):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace")


def list_instances(ldconsole):
    """Running instances from `ldconsole list2`: index,title,top_hwnd,bind_hwnd,running,pid,vbox_pid,w,h,dpi"""
    out = []
    for line in _run([ldconsole, "list2"]).splitlines():
        p = line.strip().split(",")
        if len(p) >= 10 and p[4] == "1" and p[6].lstrip("-").isdigit() and int(p[6]) > 0:
            out.append(Instance(int(p[0]), p[1], int(p[6]), int(p[7]), int(p[8])))
    return out


def adb_devices(adb):
    return {m.group(1) for m in re.finditer(r"^(\S+)\s+device\b", _run([adb, "devices"]), re.M)}


def attach_adb(instances, adb):
    """LDPlayer instance N listens on console port 5554+2N (serial emulator-XXXX) / adb port 5555+2N."""
    online = adb_devices(adb)
    for inst in instances:
        serial = f"emulator-{5554 + 2 * inst.index}"
        if serial not in online:
            _run([adb, "connect", f"127.0.0.1:{5555 + 2 * inst.index}"], timeout=5)
            online = adb_devices(adb)
            if serial not in online and f"127.0.0.1:{5555 + 2 * inst.index}" in online:
                serial = f"127.0.0.1:{5555 + 2 * inst.index}"
        inst.adb_serial = serial if serial in online else None


def text_input(ldconsole, name, text):
    """Type any text (Chinese too) into the focused text box of instance `name`, through LDPlayer itself."""
    r = subprocess.run([ldconsole, "action", "--name", name, "--key", "call.input", "--value", text], capture_output=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(r.stdout.decode("utf-8", "replace").strip() or _("輸入文字失敗"))
