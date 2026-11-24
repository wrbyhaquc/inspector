"""Maps made by taking a picture (地圖:拍下來 → 標地點 → 試走): the signs are cut from the picture itself, another
part is added where the pictures overlap, places are clicked, and walk_to {"map", "place"} becomes the full walk."""
import numpy as np
import pytest

from automation import buttons, walkmap

BOX = [100, 100, 1000, 500]          # the map's part of the screen
ME = [210, 84, 50]


def _world(seed=3):
    """a big map: gray ground, dark walls / water of all shapes (what makes places tell apart)"""
    rng = np.random.default_rng(seed)
    w = np.full((900, 2000, 3), 110, np.uint8)
    for _k in range(140):
        x, y = int(rng.integers(0, 1950)), int(rng.integers(0, 860))
        w[y:y + int(rng.integers(8, 40)), x:x + int(rng.integers(8, 60))] = int(rng.integers(0, 30))
    return w


def _screen(world, at, me=None):
    """the screen with the big map open, its part from at (x, y) of the world in BOX; "me" drawn where given"""
    f = np.full((720, 1280, 3), 20, np.uint8)
    x, y, w, h = BOX
    f[y:y + h, x:x + w] = world[at[1]:at[1] + h, at[0]:at[0] + w]
    if me:
        f[me[1] - 4:me[1] + 4, me[0] - 4:me[0] + 4] = ME
    return f


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(buttons, "_here", lambda: None)   # a studio (a runtime cannot make buttons)
    r = str(tmp_path)
    walkmap.save_settings(r, {"open": {"button": "open_map"}, "close": {"button": "close_map"},
                              "me": {"color": ME, "tol": 30, "min_px": 6, "box": BOX},
                              "stick": {"x": 190, "y": 570, "r": 60}, "near": 10, "before": "prepare"})
    return r


def test_signs_are_parts_like_nothing_else():
    flat = np.full((500, 1000, 3), 110, np.uint8)
    assert walkmap.pick_signs(flat) == []                          # nothing on it to tell where it is
    crop = _world()[100:600, 200:1200]
    got = walkmap.pick_signs(crop)
    assert len(got) >= 4                                           # spread over the map
    me = np.zeros(crop.shape[:2], np.uint8)
    me[200:300, 400:500] = 1
    for x, y, w, h in walkmap.pick_signs(crop, me):                # none where "me" is (it moves)
        assert x + w <= 400 or x >= 500 or y + h <= 200 or y >= 300


def test_shoot_add_a_part_places_and_the_walk(root):
    world = _world()
    a = walkmap.shoot(root, "map1", _screen(world, (200, 150), me=(500, 300)), "村莊")
    assert a["label"] == "村莊" and a["size"] == [1000, 500] and a["has_bg"] and len(a["signs"]) >= 4
    s0 = a["signs"][0]
    assert (s0["x"], s0["y"]) == (0, 0)                             # the first sign is where everything is measured from
    lib = buttons.load(root)
    assert all(lib[s["button"]]["find"] and lib[s["button"]]["min_score"] == walkmap.SIGN_SCORE for s in a["signs"])
    # the map scrolled 300 px: the same signs, 300 px further left on the screen -> it knows where it is
    f2 = _screen(world, (500, 150))
    found = [s for s in a["signs"] if buttons.locate(lib[s["button"]], f2, root)[0][0] is not None]
    assert found
    (px, py), _sc = buttons.locate(lib[found[0]["button"]], f2, root)
    assert abs((px - found[0]["x"]) - (BOX[0] + (a["signs"][0]["x"] - a["origin"][0]) - 300)) <= 1
    # another part added: the map grows to the right, the old signs kept and new ones from the new part
    b = walkmap.shoot(root, "map1", f2, merge=True)
    assert b["size"] == [1300, 500] and b["origin"] == a["origin"] and len(b["signs"]) > len(a["signs"])
    assert b["added_signs"] >= 1
    # a picture of somewhere else: not taken in
    with pytest.raises(ValueError):
        walkmap.shoot(root, "map1", _screen(_world(9), (0, 0)), merge=True)
    # places: clicked and named; a new one gets an id; names must differ
    ps = walkmap.set_places(root, "map1", [{"name": "商店", "x": 120, "y": 40}, {"name": "倉庫", "x": 600.4, "y": -20}])
    assert [p["id"] for p in ps] == ["p1", "p2"] and ps[1]["x"] == 600.4
    with pytest.raises(ValueError):
        walkmap.set_places(root, "map1", [{"name": "商店", "x": 0, "y": 0}, {"name": "商店", "x": 1, "y": 1}])
    # walk_to {"map", "place"}: the walk settings, the map's signs, its walk map, the place
    st = walkmap.walk_step(root, {"type": "walk_to", "map": "map1", "place": "p2", "on_fail": "continue"})
    assert st["anchor"] == {"button": b["signs"][0]["button"]} and len(st["anchors"]) == len(b["signs"]) - 1
    assert st["area"] == "map1" and st["open"] == {"button": "open_map"} and st["me"]["box"] == BOX
    assert st["points"] == [{"x": 600.4, "y": -20.0, "label": "倉庫", "near": walkmap.PLACE_NEAR}] and st["on_fail"] == "continue"
    sub = walkmap.walk_sub(root, {"type": "walk_to", "map": "map1", "place": "p1"})
    assert [x["type"] for x in sub["steps"]] == ["call", "walk_to"] and sub["steps"][0]["sub"] == "prepare"
    with pytest.raises(ValueError):
        walkmap.walk_step(root, {"type": "walk_to", "map": "map1", "place": "p9"})
    # the map made again from scratch: its old signs go
    walkmap.shoot(root, "map1", _screen(world, (200, 150)), "村莊")
    assert not [b for b in buttons.load(root) if b.startswith("map1_sign") and b not in {s["button"] for s in walkmap.summary(root, "map1")["signs"]}]


def test_settings_must_say_how_to_walk(tmp_path):
    with pytest.raises(ValueError):
        walkmap.save_settings(str(tmp_path), {"me": {"color": ME, "box": BOX}})          # no control, no open / close
    assert walkmap.list_ids(str(tmp_path)) == []


def test_me_is_the_patch_of_its_size_not_an_icon_of_its_colour():
    from automation import mapnav
    f = np.full((300, 400, 3), 60, np.uint8)
    f[200:215, 40:55] = ME                                         # an icon on the map in the same colour (225 px)
    f[100:104, 300:310] = ME                                       # "me": an arrow drawn in pieces (40 + 30 px)
    f[106:109, 300:310] = ME
    box = [0, 0, 400, 300]
    assert mapnav.find_me(f, box, ME, 30, 6) == [47, 207]          # the biggest patch: the icon
    assert mapnav.find_me(f, box, ME, 30, 6, size=70) == [304, 104]   # its size: "me"
    assert mapnav.find_me(f, box, ME, 30, 6, size=2000) is None    # nothing near that size
    fixed = np.zeros((300, 400), np.uint8)
    fixed[100:115, 295:315] = 1                                    # the map's picture has this colour where "me" is
    assert mapnav.find_me(f, box, ME, 30, 6, size=70, fixed=fixed) == [304, 104]   # but nothing else fits: still it
    f[50:58, 100:110] = ME                                         # an icon drawn on the map, about the size of "me" ...
    fixed[:] = 0
    fixed[48:60, 98:112] = 1                                       # ... and in the map's picture there
    assert mapnav.find_me(f, box, ME, 30, 6, size=70, fixed=fixed) == [304, 104]


def test_a_sign_matched_in_the_wrong_place_is_outvoted():
    from automation.runner import _agreeing
    right = [(((100 + x, 200 + y), (5, 5)), (x, y)) for x, y in [(0, 0), (50, 10), (90, -20)]]
    wrong = (((700, 40), (5, 5)), (30, 30))
    best, n = _agreeing([wrong] + right)
    assert n == 3 and best in right
