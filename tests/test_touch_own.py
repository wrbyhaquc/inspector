"""A finger the program holds itself (drivers/android hold) is not taken for a person operating the device."""
from drivers.android.touch import OWN_IDS, TouchRecorder


def _feed(r, events):
    for t, typ, code, val in events:
        r._line(f"[ {t:.6f}] /dev/input/event2: {typ} {code} {val}\n", 1000 + t)


def test_the_programs_own_held_finger_is_no_person_but_a_person_is():
    got = []
    r = TouchRecorder("x", got.append, "t", "adb")
    own = f"{OWN_IDS[3]:08x}"
    _feed(r, [(1, "EV_ABS", "ABS_MT_TRACKING_ID", own),          # (the first event seen from this device)
              (1, "EV_KEY", "BTN_TOUCH", "DOWN"), (1, "EV_ABS", "ABS_MT_POSITION_X", "000000c0"),
              (1, "EV_ABS", "ABS_MT_POSITION_Y", "0000023a"), (1, "EV_SYN", "SYN_REPORT", "00000000"),
              (2, "EV_ABS", "ABS_MT_POSITION_X", "000000fc"), (2, "EV_SYN", "SYN_REPORT", "00000000"),
              (3, "EV_ABS", "ABS_MT_TRACKING_ID", "ffffffff"), (3, "EV_KEY", "BTN_TOUCH", "UP"),
              (3, "EV_SYN", "SYN_REPORT", "00000000")])
    assert r.last_event == 0 and r.last_touch == 0 and not got
    _feed(r, [(5, "EV_ABS", "ABS_MT_TRACKING_ID", "00000005"), (5, "EV_ABS", "ABS_MT_POSITION_X", "00000100"),
              (5, "EV_ABS", "ABS_MT_POSITION_Y", "00000100"), (5, "EV_SYN", "SYN_REPORT", "00000000"),
              (5.1, "EV_ABS", "ABS_MT_TRACKING_ID", "ffffffff"), (5.1, "EV_SYN", "SYN_REPORT", "00000000")])
    assert r.last_event > 1000 and len(got) == 1
