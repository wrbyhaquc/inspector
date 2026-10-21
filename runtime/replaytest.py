"""Run the script tests (automation/tests.py): replay each test's recording with the saved scripts and the newest
model, check its expectations, keep the results.

    python -m runtime.replaytest [--id <test id> ...]
results: <runtime dir>/tests/results.json  {test id: {"run_at", "status": pass | fail | error, "checks", "frames",
                                                    "seconds", "error", "replay": the replay's file name}}
The replay of every test is kept as <runtime dir>/replays/test_<id>.json (the page can show what happened)."""
import argparse
import json
import os
import sys
import time

from automation import tests as tests_mod

from . import shadow as S
from .replay import replay
from i18n import _


def _write(path, obj):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str)
    os.replace(path + ".tmp", path)


def run(data_root, runtime_dir, ids=None):
    tests = [t for t in tests_mod.load(data_root) if not ids or t["id"] in ids]
    if not tests:
        print(_("沒有要執行的測試"), flush=True)
        return {}
    out_dir = os.path.join(runtime_dir, "tests")
    rep_dir = os.path.join(runtime_dir, "replays")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(rep_dir, exist_ok=True)
    res_path = os.path.join(out_dir, "results.json")
    try:
        results = json.load(open(res_path, encoding="utf-8"))
    except (OSError, ValueError):
        results = {}
    names = tests_mod.Names(data_root)
    model = S.latest_model(data_root)
    passed = 0
    for i, t in enumerate(tests, 1):
        print(f"[{i}/{len(tests)}] {t['name']}", flush=True)
        t0 = time.time()
        rec = {"run_at": t0, "model": os.path.basename(os.path.dirname(model))}
        try:
            r = replay(data_root, {"id": f"test_{t['id']}", **{k: t.get(k) for k in ("session", "device", "start", "minutes",
                                                                                   "sub_result", "sub_results")}},
                       model=model, progress=False)
            _write(os.path.join(rep_dir, f"test_{t['id']}.json"), r)
            checks = tests_mod.check(t, r, names)
            ok = all(c["ok"] for c in checks)
            rec.update(status="pass" if ok else "fail", checks=checks, frames=r["summary"]["frames"],
                       replay=f"test_{t['id']}")
            passed += ok
            for c in checks:
                print(f"    {'✓' if c['ok'] else '✗'} {c['text']}{'' if c['ok'] else ':' + c['detail']}", flush=True)
        except Exception as e:                        # e.g. the recording was deleted
            rec.update(status="error", error=str(e), checks=[])
            print(_("    無法執行:{e}", e=e), flush=True)
        rec["seconds"] = round(time.time() - t0, 1)
        results[t["id"]] = rec
        _write(res_path, results)
    print(_("完成:{passed}/{p2} 個測試通過", passed=passed, p2=len(tests)), flush=True)
    return {t["id"]: results[t["id"]] for t in tests}


def main():
    ap = argparse.ArgumentParser(prog="python -m runtime.replaytest", description=_("執行腳本測試(用錄影重播,檢查預期結果)"))
    ap.add_argument("--id", action="append", default=[], help=_("只執行這個測試,可重複"))
    ap.add_argument("--data", default=__import__("project").data_root())
    ap.add_argument("--fast-dir", default=__import__("project").runtime_dir())
    a = ap.parse_args()
    res = run(a.data, a.fast_dir, a.id or None)
    sys.exit(0 if all(r["status"] == "pass" for r in res.values()) else 1)


if __name__ == "__main__":
    main()
