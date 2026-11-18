"""A still screen (a message waiting to be answered) is "frozen", but a device may still start: the frames arrive."""
import numpy as np

from runtime.health import Health


def _still(seconds, freeze_s=300):
    h = Health()
    img = np.full((720, 1280, 3), 80, np.uint8)
    img[300:420, 400:880] = 200                       # a dialog: not one colour, so not "blank"
    for t in range(0, seconds + 1, 5):
        h.frame("dev", img, 50, 1000.0 + t)
    return h.check("dev", 1000.0 + seconds, freeze_s=freeze_s)[0]


def test_a_screen_still_for_long_is_frozen_but_ready():
    state = _still(900)
    assert state == "frozen"
    assert Health.ready(state)


def test_a_moving_screen_is_ready():
    assert Health.ready(_still(60))


def test_no_picture_or_a_blank_one_is_not_ready():
    assert not Health.ready("lost")
    assert not Health.ready("blank")
