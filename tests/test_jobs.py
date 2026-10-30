"""Background jobs (the runner, the collector, training) start on every system."""
import subprocess
import time


def test_a_job_starts_without_the_windows_only_flags(tmp_path, monkeypatch):
    from server import jobs
    monkeypatch.setattr(jobs, "WORK_ROOT", str(tmp_path))
    for flag in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):      # as on Linux and macOS
        monkeypatch.delattr(subprocess, flag, raising=False)
    j = jobs.JobManager().start("test", ["json.tool", "--help"], "test")
    end = time.time() + 30
    while j.status == "running" and time.time() < end:
        time.sleep(0.05)
    assert j.status == "done"
