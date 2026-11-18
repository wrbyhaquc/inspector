"""A find button with "with": it counts only where another button's picture is too (a short name next to its icon)."""
import numpy as np
import pytest

from automation import buttons
import project


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "screen", lambda root=None: (1280, 720))
    monkeypatch.setattr(buttons, "_here", lambda: None)
    return str(tmp_path)


def _scene(icon_at, labels):
    """grey noise; an icon (a bright ring) at icon_at; a label (bars) at each of labels (top-left corners)"""
    rng = np.random.default_rng(1)
    f = rng.integers(60, 90, (720, 1280, 3)).astype(np.uint8)
    for (x, y) in labels:
        for k in range(4):
            f[y + 4:y + 16, x + 4 + k * 9:x + 9 + k * 9] = 235
    if icon_at:
        cx, cy = icon_at
        f[cy - 14:cy + 14, cx - 14:cx + 14] = 230
        f[cy - 8:cy + 8, cx - 8:cx + 8] = 40
    return f


def test_the_name_counts_only_where_its_icon_is(root):
    # picked where both show: the label at (500, 300), its icon 40 px above its tap point
    pick = _scene((520, 270), [(500, 300)])
    buttons.save(root, {"id": "icon", "label": "icon", "x": 520, "y": 270, "find": True, "box": [500, 250, 40, 40],
                        "search": 900, "min_score": 0.8}, pick)
    buttons.save(root, {"id": "name", "label": "name", "x": 520, "y": 270, "find": True, "box": [500, 300, 40, 20],
                        "search": 900, "min_score": 0.8, "with": {"button": "icon", "dx": 0, "dy": 0}}, pick)
    lib = buttons.load(root)
    assert lib["name"]["with"]["button"] == "icon"
    # the same text twice: only the one under an icon is the button
    f = _scene((920, 470), [(200, 100), (900, 500)])
    (x, y), _s = buttons.locate(lib["name"], f, root)
    assert (x, y) == (920, 470)
    # text alone (no icon anywhere): not found
    (x, y), _s = buttons.locate(lib["name"], _scene(None, [(200, 100)]), root)
    assert x is None
    # without "with" the first text alike would do
    plain = {k: v for k, v in lib["name"].items() if k != "with"}
    (x, y), _s = buttons.locate(plain, _scene(None, [(200, 100)]), root)
    assert (x, y) == (220, 70)


def test_with_itself_is_refused(root):
    with pytest.raises(ValueError):
        buttons.save(root, {"id": "a", "label": "a", "x": 520, "y": 270, "find": True, "box": [500, 250, 40, 40],
                            "with": {"button": "a"}}, _scene((520, 270), []))


def test_try_on_tells_where_it_is_found_how_well_and_a_rival_there(root):
    pick = _scene((520, 270), [(500, 300)])
    buttons.save(root, {"id": "icon", "label": "icon", "x": 520, "y": 270, "find": True, "box": [500, 250, 40, 40],
                        "search": 900, "min_score": 0.8}, pick)
    lib = buttons.load(root)
    # not saved yet: its picture comes with the call (the same icon) - the saved "icon" is a rival right there
    draft = {"id": "new_icon", "label": "new", "x": 520, "y": 270, "find": True, "box": [500, 250, 40, 40], "search": 900,
             "min_score": 0.8}
    frames = [_scene((920, 470), []), _scene(None, [(200, 100)])]
    res = buttons.try_on(draft, frames, root, pick[250:290, 500:540], [lib["icon"]])
    assert res[0]["found"] and (res[0]["x"], res[0]["y"]) == (920, 470) and res[0]["rival"]["id"] == "icon"
    assert not res[1]["found"] and res[1]["score"] < 0.8


def test_a_flat_frame_matches_nothing(root):
    """a black loading screen: the formula gives 1.0 / inf on a flat part - no button may be "seen" there"""
    pick = _scene((520, 270), [(500, 300)])
    for feat in (None, "minch", "text"):
        b = {"id": "lbl", "label": "lbl", "x": 520, "y": 310, "find": True, "box": [500, 300, 40, 20], "search": 900, "min_score": 0.5}
        if feat:
            b["feature"] = feat
        buttons.save(root, b, pick)
        lib = buttons.load(root)
        black = np.zeros((720, 1280, 3), np.uint8)
        (x, _y), s = buttons.locate(lib["lbl"], black, root)
        assert x is None and (s or 0) < 0.5, (feat, s)
        (x, y), s = buttons.locate(lib["lbl"], pick, root)        # and the real one is still found as before
        assert (x, y) == (520, 310) and s > 0.99, (feat, s)
