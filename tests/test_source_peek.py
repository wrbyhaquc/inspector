"""A look at a found source before it is used: a picture, all black, or none to take."""
import numpy as np

from server import sources_view


class Cap:
    def __init__(self, img):
        self.img = img

    def grab(self):
        return None if self.img is None else (self.img, "test", (self.img.shape[1], self.img.shape[0]))


class Kind:
    per_source = True
    capture_modes = {"window": "window"}

    def __init__(self, img):
        self.img, self.opts = img, None

    def capture(self, match, mode, fallback, opts=None):
        self.opts = opts
        return Cap(self.img)


class Drv:
    def __init__(self, img):
        self.kind = Kind(img)

    def _driver(self, k, params):
        return self.kind


def look(img, opts=None):
    sources_view._peeks.clear()
    return sources_view._peek_one(Drv(img), {"kinds": {}}, {"kind": "window/any", "match": "w", "opts": opts or {"title": "w"}})


def test_a_window_with_something_on_it_is_shown():
    img = (np.random.default_rng(1).random((720, 1280, 3)) * 255).astype(np.uint8)
    got = look(img)
    assert got["state"] == "ok" and got["image"].startswith("data:image/jpeg;base64,")


def test_all_black_is_told_apart():
    assert look(np.zeros((720, 1280, 3), np.uint8))["state"] == "blank"


def test_no_picture_to_take_is_none():
    assert look(None) == {"state": "none", "image": None}


def test_a_window_is_looked_at_with_its_own_settings():
    drv = Drv(np.zeros((10, 10, 3), np.uint8))
    sources_view._peeks.clear()
    sources_view._peek_one(drv, {"kinds": {}}, {"kind": "window/any", "match": "w", "opts": {"title": "Viewer", "process": "viewer.exe"}})
    assert drv.kind.opts == {"title": "Viewer", "process": "viewer.exe"}
