"""A picture button that is usually found and stops being found is reported once (runtime/button_health.py)."""
from runtime import button_health as bh

H = bh.BUCKET


def _monitor(tmp_path):
    said = []
    m = bh.ButtonHealth(str(tmp_path), lambda: {"ok_btn": "OK"}, said.append)
    return m, said


def _usual(found_share, n=100, t=0):
    return [{"t": t, "button": "ok_btn", "device": "A", "n": n, "found": int(n * found_share), "score": 0.9}]


def test_a_button_that_stops_being_found_is_reported_once(tmp_path):
    m, said = _monitor(tmp_path)
    now = 100 * H
    m.recent = [{"t": now - H, "button": "ok_btn", "device": "A", "n": 10, "found": 1, "score": 0.4}]
    m.check(now, history=_usual(0.95))
    assert len(said) == 1 and "OK" in said[0] and "10%" in said[0] and "95%" in said[0]
    m.check(now + 60, history=_usual(0.95))
    assert len(said) == 1                                    # not again within ALERT_EVERY


def test_a_button_that_is_often_missing_anyway_is_not_reported(tmp_path):
    m, said = _monitor(tmp_path)
    now = 100 * H
    m.recent = [{"t": now - H, "button": "ok_btn", "device": "A", "n": 10, "found": 1, "score": 0.4}]
    m.check(now, history=_usual(0.5))                        # usually found half the time (a step that waits for it)
    m.check(now, history=_usual(0.95, n=5))                  # too little history to tell
    assert said == []


def test_looks_are_counted_per_hour_and_written(tmp_path):
    m, said = _monitor(tmp_path)
    for k in range(4):
        m.add(10 * H + k, "ok_btn", "A", k % 2 == 0, 0.9)
    m.add(11 * H, "ok_btn", "A", True, 0.9)                  # the next hour: the first one is written
    rows = bh.read(m.dir, 100000, today=__import__("datetime").date.fromtimestamp(10 * H))
    assert rows and rows[0]["n"] == 4 and rows[0]["found"] == 2
