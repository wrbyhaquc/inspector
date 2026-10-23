import argparse
import socket
import sys
import webbrowser

import uvicorn
from i18n import _


ALREADY_RUNNING = 3             # exit code: another Inspector is running (run_service.bat then stops instead of retrying)
RUNTIME_TOO_NEW = 4             # exit code: the runtime folder was written by a newer Inspector (run_service.bat stops too)
_lock = None


def _take_lock():
    """One Inspector at a time: an OS lock on a file, held as long as this process lives (released even if it is
    killed). -> True if this process has it."""
    global _lock
    import os
    from . import RUNTIME_DIR
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    f = open(os.path.join(RUNTIME_DIR, "inspector.lock"), "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:                                            # Linux / macOS
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock = f
    return True


def main():
    ap = argparse.ArgumentParser(prog="python -m server", description=_("Inspector 介面"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true", help=_("讓同一個網路的手機也能連(要先設定登入 PIN 碼)"))
    ap.add_argument("--start-runner", action="store_true", help=_("也啟動腳本執行(照上次啟動的設定)"))
    ap.add_argument("--check", action="store_true", help=_("只檢查是否已經有 Inspector 在執行(是:結束代碼 3)"))
    a = ap.parse_args()
    if not _take_lock():
        print(_("Inspector 已經在執行,這次不啟動。要重開請用 restart_inspector.bat。"), flush=True)
        sys.exit(ALREADY_RUNNING)
    if a.check:
        return
    from project import runtime_data
    from . import RUNTIME_DIR
    try:                                      # this computer's runtime folder: upgraded if older, refused if newer
        runtime_data.ensure(RUNTIME_DIR)
    except runtime_data.RuntimeTooNew as e:
        print(e, flush=True)
        sys.exit(RUNTIME_TOO_NEW)
    if a.start_runner:
        import os
        os.environ["INSPECTOR_START_RUNNER"] = "1"
    url = f"http://127.0.0.1:{a.port}"
    print(_("介面網址:{url}", url=url))
    host = "127.0.0.1"
    if a.lan:
        import os
        host = "0.0.0.0"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
        except OSError:
            ip = _("這台電腦的 IP")
        os.environ["INSPECTOR_LAN_URL"] = f"http://{ip}:{a.port}/panel"
        print(_("手機操作面板:{url}", url=os.environ['INSPECTOR_LAN_URL']))
    # one Inspector at a time: a second one would start a second script runner before finding the port taken
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, a.port))
    except OSError:
        print(_("Inspector 已經在執行(連接埠 {port} 已被使用),這次不啟動。要重開請用 restart_inspector.bat。", port=a.port), flush=True)
        sys.exit(ALREADY_RUNNING)
    finally:
        probe.close()
    if not a.no_browser:
        webbrowser.open(url)
    uvicorn.run("server.app:app", host=host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
