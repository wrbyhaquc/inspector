"""Atomic JSON writes (atomic/): writers at the same time do not share one temp file."""
import json
import os
import threading

import atomic


def test_threads_writing_one_file_at_once_all_succeed(tmp_path):
    p = str(tmp_path / "x.json")
    errors = []
    start = threading.Barrier(8)

    def write(n):
        start.wait()
        try:
            for i in range(20):
                atomic.write_json(p, {"n": n, "i": i}, indent=1)
        except Exception as e:      # noqa: BLE001 - any failure fails the test
            errors.append(e)

    ts = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    with open(p, encoding="utf-8") as f:
        assert set(json.load(f)) == {"n", "i"}
    assert os.listdir(tmp_path) == ["x.json"]          # no temp file left behind


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(tmp_path):
    p = str(tmp_path / "x.json")
    atomic.write_json(p, {"a": 1})
    try:
        atomic.write_json(p, {"a": object()})
    except TypeError:
        pass
    with open(p, encoding="utf-8") as f:
        assert json.load(f) == {"a": 1}
    assert os.listdir(tmp_path) == ["x.json"]
