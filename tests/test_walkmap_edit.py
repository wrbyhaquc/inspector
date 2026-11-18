"""Walk maps made and edited from the page (可走區域圖編輯器): from a big-map picture, another part merged in, painted."""
import numpy as np

from automation import walkmap


def _map(dark_cols=(), w=200, h=120):
    f = np.full((360, 640, 3), 120, np.uint8)              # a light map ...
    for c in dark_cols:
        f[:, c:c + 10] = 10                                 # ... with dark walls
    return f


def test_make_merge_paint_and_remove(tmp_path):
    root = str(tmp_path)
    m = walkmap.make(root, "plaza", _map([150]), [100, 50, 200, 120], (100, 50), label="廣場")
    s = walkmap.summary(root, "plaza")
    assert s["label"] == "廣場" and s["origin"] == [0, 0] and s["size"] == [200, 120] and s["has_bg"]
    wm = walkmap.load(root, "plaza")
    assert not wm["free"][10, 55] and wm["free"][10, 20]   # the wall (x 150 on screen = 50 in the box) is blocked
    walkmap.add_marks(root, "plaza", [(30, 30)])
    # another part of the same map: the anchor seen 50 px further right (the map scrolled) - merged, marks kept
    walkmap.make(root, "plaza", _map(), [100, 50, 200, 120], (150, 50), merge_in=True)
    s = walkmap.summary(root, "plaza")
    assert s["origin"] == [-50, 0] and s["size"] == [250, 120] and len(s["marks"]) == 1
    wm = walkmap.load(root, "plaza")
    assert wm["free"][10, 55 + 50]                          # seen walkable from the second spot: walkable
    # painted: a block made walkable / blocked, the marks and the ways walked through dropped
    free = wm["free"].copy()
    free[:, 200:210] = False
    walkmap.add_walk(root, "plaza", [(10, 10), (40, 10)])
    walkmap.paint(root, "plaza", free, marks=[], clear_ways=True)
    s = walkmap.summary(root, "plaza")
    assert s["marks"] == [] and s["proven"] == 0 and not walkmap.load(root, "plaza")["free"][5, 205]
    # made again (not merged): nothing learnt on the old one is kept
    walkmap.add_marks(root, "plaza", [(30, 30)])
    walkmap.make(root, "plaza", _map(), [100, 50, 200, 120], (100, 50))
    assert walkmap.summary(root, "plaza")["marks"] == []
    walkmap.remove(root, "plaza")
    assert walkmap.list_ids(root) == []
