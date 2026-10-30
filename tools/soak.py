"""Soak test (長時間運轉): does the runner keep running for hours without growing?

    python -m tools.soak --minutes 30            (a report at the end; exit code 1 if something keeps growing)

On a throwaway home: a made-up recording (a red box that comes and goes on a noisy picture) played back by the
recording-replay source, a colour-ratio state, a main script whose rules notify and call a sub-script (a wait and a
counter). The Studio and the runner run as they do on site; a page asks for the runner's status every few seconds.
Every minute: each process's memory (and handles / open files, and threads where the system says), the files and
bytes under the home. After a warm-up (the first third), what keeps growing is measured per hour:

  memory      the runner's and the server's: MAX_MB_H
  files       the number of files under the home: MAX_FILES_H (a log is one file however long it gets); the dated
              folders the runner cleans after keep_days days (action pictures, incidents, schedule runs) are counted
              apart ("kept_files_day": they grow every day by design, until keep_days)
  bytes       MAX_MB_DAY a day: kept keep_days days, this is about what a site needs on disk
  handles     MAX_HANDLES_H (a leaked file / socket shows here first)

The numbers (and each minute's samples, --out) are the report; GitHub runs it every night (.github/workflows/soak.yml)."""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_MB_H = 40
MAX_FILES_H = 30
MAX_MB_DAY = 600          # this site acts every 20 s and keeps a picture of each: a busy site
MAX_HANDLES_H = 60


# ---------------------------------------------------------------- what a process uses
def usage(pid):
    """{"mb": resident memory, "handles": open handles / files, "threads"} of a process, or None if it is gone."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                       [(k, ctypes.c_size_t) for k in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                       "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                                       "PrivateUsage")]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000 | 0x0010, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION | VM_READ
        if not h:
            return None
        try:
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            if not ctypes.WinDLL("psapi").GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                return None
            n = wintypes.DWORD()
            k32.GetProcessHandleCount(h, ctypes.byref(n))
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:      # STILL_ACTIVE
                return None
            return {"mb": round(pmc.PrivateUsage / 2 ** 20, 1), "handles": n.value, "threads": None}
        finally:
            k32.CloseHandle(h)
    try:
        with open(f"/proc/{pid}/status") as f:
            st = dict(line.split(":", 1) for line in f if ":" in line)
        return {"mb": round(int(st["VmRSS"].split()[0]) / 1024, 1), "handles": len(os.listdir(f"/proc/{pid}/fd")),
                "threads": int(st["Threads"])}
    except (OSError, KeyError, ValueError):
        return None


def disk(folder, skip):
    """-> (files, bytes, kept files): kept = in the folders the runner deletes after keep_days days (runtime/retention.py),
    which grow every day by design and stop growing at keep_days"""
    files = size = kept = 0
    for root, dirs, fs in os.walk(folder):
        dirs[:] = [d for d in dirs if os.path.join(root, d) != skip]
        dated = os.path.basename(os.path.dirname(root)) in ("actions", "incidents", "schedules")
        for f in fs:
            try:
                size += os.path.getsize(os.path.join(root, f))
                files += 1
                kept += dated
            except OSError:
                pass
    return files, size, kept


def slope(xs, ys):
    """least-squares change of ys per unit of xs"""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


# ---------------------------------------------------------------- the site
def recording(work, frames=120):
    """A recording of one camera: a noisy field, a red box there for 10 frames out of every 20 (one a second)."""
    import numpy as np
    from PIL import Image
    d = os.path.join(work, "sessions", "soak", "devices", "CAM")
    os.makedirs(os.path.join(d, "frames"), exist_ok=True)
    rnd = np.random.default_rng(7)
    t0 = 1_700_000_000.0
    with open(os.path.join(d, "samples.jsonl"), "w", encoding="utf-8") as f:
        for k in range(frames):
            img = np.clip(rnd.normal(90, 25, (720, 1280, 3)), 0, 255).astype(np.uint8)
            if (k // 10) % 2:
                x = 200 + (k % 10) * 60
                img[300:420, x:x + 160] = (220, 30, 30)
            Image.fromarray(img).save(os.path.join(d, "frames", f"{k}.png"), compress_level=1)
            f.write(json.dumps({"id": str(k), "t_req": t0 + k, "frame": f"frames/{k}.png"}) + "\n")
    with open(os.path.join(os.path.dirname(os.path.dirname(d)), "session.json"), "w", encoding="utf-8") as f:
        json.dump({"session": "soak", "started": t0, "ended": t0 + frames, "devices": {"CAM": {"samples": frames}}}, f)
    return os.path.dirname(os.path.dirname(os.path.dirname(d)))


def design(api):
    red = [{"h": [250, 10], "s": [150, 255], "v": [120, 255]}]
    api("POST", "/api/sources/add", {"kind": "recording/default", "match": "soak CAM", "id": "CAM", "name": "Soak camera", "params": {}})
    api("POST", "/api/states", {"note": "soak", "states": [{
        "id": "red_box", "name": "Red box", "type": "class", "description": "",
        "classes": [{"value": "yes", "name": "Yes", "color": "red", "key": "1"}, {"value": "no", "name": "No", "color": "green", "key": "2"}],
        "rois": [{"id": "all", "name": "All", "box": [0, 0, 1280, 720]}],
        "source": {"kind": "rule", "rule": "color_ratio", "params": {"roi": "all", "colors": red, "high_value": "yes",
                                                                       "high_min": 0.01, "low_value": "no", "low_max": 0.005}},
        "review": {"enabled": False, "roi": "all", "scale": 1}}]})
    api("POST", "/api/variables", {"vars": [{"name": "seen", "label": "Seen", "scope": "device", "reset": "never", "initial": 0}]})
    api("POST", "/api/subscripts", {"note": "soak", "sub": {
        "id": "count", "name": "Count", "description": "", "timeout": 30, "params": [], "cleanup": [],
        "steps": [{"type": "wait", "seconds": 1}, {"type": "set_var", "var": "seen", "mode": "add", "value": 1}]}})
    api("POST", "/api/scripts", {"note": "soak", "script": {
        "id": "soak", "name": "Soak", "enabled": True, "devices": {"*": "off", "CAM": "live"}, "description": "",
        "otherwise": {"type": "none", "text": ""}, "initial": "main",
        "situations": [{"id": "main", "name": "Main", "rules": [
            {"id": "seen", "name": "Red box: count it", "enabled": True, "cooldown": 5,
             "when": [[{"state": "red_box", "op": "is", "value": "yes", "for": 2}]],
             "do": [{"type": "call", "sub": "count", "args": {}}, {"type": "notify", "text": "red box"}]},
        ]}]}})


def main():
    ap = argparse.ArgumentParser(prog="python -m tools.soak", description="Soak test: does the runner keep running without growing?")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--interval", type=float, default=0.3, help="the runner's look interval (seconds)")
    ap.add_argument("--every", type=float, default=60, help="seconds between samples")
    ap.add_argument("--out", help="write every sample and the report here (JSON)")
    ap.add_argument("--keep", action="store_true", help="keep the throwaway home")
    a = ap.parse_args()

    home = tempfile.mkdtemp(prefix="inspector-soak-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("INSPECTOR_")}
    env.update(INSPECTOR_HOME=home, INSPECTOR_EDITION="studio", PYTHONIOENCODING="utf-8")
    work = subprocess.run([sys.executable, "-c", "import project; print(project.work_root())"], cwd=ROOT, env=env,
                          capture_output=True, text=True, check=True).stdout.strip()
    rec = recording(work)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = open(os.path.join(home, "server.log"), "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "server", "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT)

    def api(method, path, body=None):
        r = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                   data=json.dumps(body).encode() if body is not None else None)
        return json.loads(urllib.request.urlopen(r, timeout=60).read() or b"{}")

    samples, problems = [], []
    failed = None
    try:
        for _ in range(240):
            try:
                api("GET", "/api/project")
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError("the server stopped")
                time.sleep(0.25)
        design(api)
        api("POST", "/api/shadow/start", {"interval": a.interval})
        t0 = time.time()
        end = t0 + a.minutes * 60
        nxt = t0 + 20                                   # the first sample once it has started
        while time.time() < end:
            st = api("GET", "/api/shadow/status")      # a page open on the run page
            if time.time() >= nxt:
                s = st.get("status") or {}
                runner = usage(s.get("pid")) if s.get("pid") else None
                files, size, kept = disk(home, rec)
                dev = (s.get("devices") or [{}])[0]
                samples.append({"t": round(time.time() - t0), "runner": runner, "server": usage(server.pid),
                                "files": files - kept, "kept_files": kept, "mb": round(size / 2 ** 20, 2), "ticks": s.get("ticks"),
                                "decisions": s.get("decisions"), "health": (dev.get("health") or {}).get("state"),
                                "running": s.get("running")})
                print(json.dumps(samples[-1]), flush=True)
                if not runner:
                    problems.append(f"the runner stopped after {samples[-1]['t']} s")
                    break
                nxt += a.every
            time.sleep(3)
        try:
            api("POST", "/api/shadow/stop")
        except Exception:
            pass
    except Exception as e:                              # it could not even run: the report says why
        body = e.read().decode("utf-8", "replace")[:500] if isinstance(e, urllib.error.HTTPError) else ""
        failed = f"{e} {body}".strip()
    finally:
        server.terminate()
        try:
            server.wait(15)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    if failed:
        with open(os.path.join(home, "server.log"), encoding="utf-8", errors="replace") as f:
            problems.append(f"stopped early: {failed}\nthe server's log:\n{f.read()[-3000:]}")

    # ---- after the warm-up: what keeps growing
    late = [x for x in samples if x["t"] >= a.minutes * 60 / 3 and x["runner"]]
    hours = [x["t"] / 3600 for x in late]
    report = {"minutes": a.minutes, "samples": len(samples)}
    if len(late) >= 3:
        rate = {"runner_mb_h": slope(hours, [x["runner"]["mb"] for x in late]),
                "server_mb_h": slope(hours, [x["server"]["mb"] for x in late]),
                "files_h": slope(hours, [x["files"] for x in late]),
                "kept_files_day": slope(hours, [x["kept_files"] for x in late]) * 24,
                "mb_day": slope(hours, [x["mb"] for x in late]) * 24,
                "runner_handles_h": slope(hours, [x["runner"]["handles"] for x in late]),
                "server_handles_h": slope(hours, [x["server"]["handles"] for x in late])}
        report["rates"] = {k: round(v, 2) for k, v in rate.items()}
        for k, lim in (("runner_mb_h", MAX_MB_H), ("server_mb_h", MAX_MB_H), ("files_h", MAX_FILES_H), ("mb_day", MAX_MB_DAY),
                       ("runner_handles_h", MAX_HANDLES_H), ("server_handles_h", MAX_HANDLES_H)):
            if rate[k] > lim:
                problems.append(f"{k} {rate[k]:.1f} > {lim}")
        first, last = samples[0], samples[-1]
        report["start"] = {"runner_mb": first["runner"]["mb"], "server_mb": first["server"]["mb"], "files": first["files"], "mb": first["mb"]}
        report["end"] = {"runner_mb": last["runner"]["mb"], "server_mb": last["server"]["mb"], "files": last["files"], "mb": last["mb"],
                         "ticks": last["ticks"], "decisions": last["decisions"], "health": last["health"]}
        if not (last["decisions"] or {}).get("call"):
            problems.append("the script never ran (no call decisions): the soak exercised nothing")
    elif not failed:
        problems.append("too few samples to judge (run longer)")
    report["problems"] = problems
    print(json.dumps(report, indent=1), flush=True)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"report": report, "samples": samples}, f, indent=1)
    if not a.keep:
        import shutil
        shutil.rmtree(home, ignore_errors=True)
    else:
        print("home:", home)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
