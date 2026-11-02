"""The touch listener's adb client ends with the process that started it, however that process ends."""
import os
import subprocess
import sys
import time

import pytest

from drivers.android import touch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLEEP = "import time; time.sleep(60)"
# Started inside the job, as adb starts the adb server: told to go once it is in the job, says the pid of what it started.
CHILD = ("import subprocess, sys; sys.stdin.readline(); "
         f"print(subprocess.Popen([sys.executable, '-c', {SLEEP!r}], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
         "stderr=subprocess.DEVNULL).pid, flush=True); " + SLEEP)
PARENT = ("import subprocess, sys, time; from drivers.android.touch import _end_with_parent; "
          f"c = subprocess.Popen([sys.executable, '-c', {CHILD!r}], stdin=subprocess.PIPE); "
          "_end_with_parent(c); print(c.pid, flush=True); c.stdin.write(b'go\\n'); c.stdin.flush(); time.sleep(60)")


def _alive(pid):
    return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job objects")
def test_a_force_ended_parent_takes_the_child_but_not_what_the_child_started():
    parent = subprocess.Popen([sys.executable, "-c", PARENT], cwd=ROOT, stdout=subprocess.PIPE)
    child = helper = None
    try:
        child = int(parent.stdout.readline())
        helper = int(parent.stdout.readline())
        assert _alive(child) and _alive(helper)
        parent.kill()
        end = time.time() + 10
        while _alive(child) and time.time() < end:
            time.sleep(0.1)
        assert not _alive(child)
        assert _alive(helper)
    finally:
        parent.kill()
        for pid in (child, helper):
            if pid:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def test_it_does_nothing_on_other_systems(monkeypatch):
    monkeypatch.setattr(touch, "_k", None)
    touch._end_with_parent(object())


class _Adb:
    stdout = [b"a line\n"]

    def poll(self):
        return None


def test_listening_goes_on_when_the_child_cannot_be_tied_to_the_parent(monkeypatch, capsys):
    def refuse(proc):
        raise OSError("refused")

    rec = touch.TouchRecorder("serial", None, "device", "adb")
    lines = []
    monkeypatch.setattr(touch, "_end_with_parent", refuse)
    monkeypatch.setattr(touch.subprocess, "Popen", lambda *a, **k: _Adb())
    monkeypatch.setattr(rec, "_line", lambda s, now: (lines.append(s), rec.stop.set()))
    rec._run()
    assert lines == ["a line\n"]
    assert "refused" in capsys.readouterr().out
