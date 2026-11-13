"""Name galleries read while scripts run (labeler/gallery.py live()): aligned search, no cut; conditions on them."""
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from automation import conds
from labeler import gallery


def _text(word, w=120, h=20):
    im = Image.new("RGB", (w, h), (30, 30, 30))
    ImageDraw.Draw(im).text((w - 8 * len(word) - 2, 4), word, fill=(240, 240, 240))
    return np.array(im)


@pytest.fixture
def matcher(tmp_path):
    d = tmp_path / "g"
    os.makedirs(d)
    idx = {}
    for k, word in enumerate(["NORTH-1", "NORTH-2", "SOUTH"]):
        Image.fromarray(_text(word)).save(d / f"{k}.png")
        idx[f"{k}.png"] = {"name": word}
    (d / "index.json").write_text(json.dumps(idx))
    s = {"id": "place", "name": "P", "type": "gallery", "rois": [{"id": "r", "box": [300, 100, 200, 20]}],
         "source": {"kind": "gallery", "params": {"dir": str(d)}}}
    return gallery.Matcher(str(tmp_path), s)


def _frame(word):
    f = np.full((300, 600, 3), 30, np.uint8)
    f[100:120, 380:500] = _text(word)                    # right-aligned at the region's right end (x 500)
    return f


def test_live_finds_the_name_at_the_right_end_even_one_letter_apart(matcher):
    how = {"align": "right", "min": 0.8}
    assert matcher.live(_frame("NORTH-2"), how)[0] == "NORTH-2"
    assert matcher.live(_frame("NORTH-1"), how)[0] == "NORTH-1"
    name, score = matcher.live(np.full((300, 600, 3), 30, np.uint8), how)     # nothing there
    assert name is None


def test_a_name_not_in_the_gallery_is_not_taken_for_the_closest_one(matcher):
    how = {"align": "right", "min": 0.5}
    assert matcher.live(_frame("NORTH-X"), how)[0] is None              # one character differs from NORTH-1 / NORTH-2
    assert matcher.live(_frame("NORTH-1"), how)[0] == "NORTH-1"


def test_entries_cut_for_one_kind_of_picture_are_used_only_on_it(matcher):
    matcher.index["2.png"]["picture"] = "sharp"                         # SOUTH: only on sharp pictures
    assert matcher.live(_frame("SOUTH"), {"align": "right", "min": 0.8, "picture": "sharp"})[0] == "SOUTH"
    assert matcher.live(_frame("NORTH-1"), {"align": "right", "min": 0.8, "picture": "sharp"})[0] is None
    assert matcher.live(_frame("NORTH-1"), {"align": "right", "min": 0.8})[0] == "NORTH-1"   # no "live" entries: untagged ones
    matcher.index["0.png"]["picture"] = "live"                          # live entries exist: only those on live pictures
    assert matcher.live(_frame("NORTH-2"), {"align": "right", "min": 0.8})[0] is None
    assert matcher.live(_frame("NORTH-1"), {"align": "right", "min": 0.8})[0] == "NORTH-1"


def test_a_condition_on_a_gallery_state_names_one_of_its_names():
    st = {"place": {"id": "place", "name": "地點", "type": "gallery"}}
    conds.check({"kind": "state", "state": "place", "op": "is", "value": "NORTH-1"}, st, None, "x")
    with pytest.raises(ValueError):
        conds.check({"kind": "state", "state": "place", "op": "gt", "value": "NORTH-1"}, st, None, "x")
    with pytest.raises(ValueError):
        conds.check({"kind": "state", "state": "place", "op": "is", "value": 3}, st, None, "x")
