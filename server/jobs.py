"""Long-running jobs (collector, labeler) run as child processes; logs are kept in memory and on disk."""
import collections
import datetime
import itertools
import os
import subprocess
import sys
import threading
import time

from . import PROJECT_ROOT, WORK_ROOT
from i18n import _

_ids = itertools.count(1)


class Job:
    def __init__(self, kind, args, title, on_exit=None):
        self.id = f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{next(_ids)}"
        self.kind, self.args, self.title = kind, args, title
        self.status = "running"          # running / done / failed / stopped
        self.returncode = None
        self.started, self.ended = time.time(), None
        self.lines = collections.deque(maxlen=3000)
        log_dir = os.path.join(WORK_ROOT, ".jobs")
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, f"{self.id}_{kind}.log")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)    # (Windows)
        self.proc = subprocess.Popen([sys.executable, "-u", "-m", *args], cwd=PROJECT_ROOT, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        self._stop_requested = False
        self.on_exit = on_exit          # called with this job once the process has ended (e.g. collector -> labeler)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        with open(self.log_path, "w", encoding="utf-8") as f:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                self.lines.append(line)
                f.write(line + "\n"); f.flush()
        self.returncode = self.proc.wait()
        self.ended = time.time()
        self.status = "stopped" if self._stop_requested else ("done" if self.returncode == 0 else "failed")
        if self.on_exit:
            try:
                self.on_exit(self)
            except Exception as e:                       # never let a follow-up break the job bookkeeping
                self.lines.append(_("後續工作沒有啟動:{e}", e=e))

    def stop(self, timeout=20):
        self._stop_requested = True
        if self.kind == "collector":        # graceful: the collector watches for this file
            open(os.path.join(WORK_ROOT, "collector.stop"), "w").close()
            try:
                self.proc.wait(timeout)
                return
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            if os.name == "nt":                 # the job and every process it started (worker pools)
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.terminate()

    def info(self, tail=200):
        return {"id": self.id, "kind": self.kind, "title": self.title, "args": self.args, "status": self.status,
                "returncode": self.returncode, "started": self.started, "ended": self.ended,
                "log": list(self.lines)[-tail:] if tail else None}


class JobManager:
    def __init__(self):
        self.jobs = collections.OrderedDict()
        self.lock = threading.Lock()

    def start(self, kind, args, title, on_exit=None):
        with self.lock:
            if any(j.kind == kind and j.status == "running" for j in self.jobs.values()):
                raise RuntimeError(_("已經有一個「{title}」正在執行", title=title))
            j = Job(kind, args, title, on_exit)
            self.jobs[j.id] = j
            while len(self.jobs) > 50:
                self.jobs.popitem(last=False)
            return j

    def running(self, kind):
        return next((j for j in reversed(self.jobs.values()) if j.kind == kind and j.status == "running"), None)

    def latest(self, kind):
        return next((j for j in reversed(self.jobs.values()) if j.kind == kind), None)

    def get(self, job_id):
        return self.jobs.get(job_id)

    def list(self, tail=0):
        return [j.info(tail) for j in reversed(self.jobs.values())]
