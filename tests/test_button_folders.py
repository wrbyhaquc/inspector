"""Buttons filed in folders (only how people find them; scripts use the id)."""
import json

import pytest

from automation import buttons
import project


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "screen", lambda root=None: (1280, 720))
    monkeypatch.setattr(buttons, "_here", lambda: None)
    return str(tmp_path)


def _saved(root):
    with open(buttons._path(root), encoding="utf-8") as f:
        return {b["id"]: b for b in json.load(f)["buttons"]}


def test_a_folder_is_kept_tidy_and_dropped_when_emptied(root):
    buttons.save(root, {"id": "map_move", "label": "選單:設定", "x": 10, "y": 10, "folder": " 選單 / 設定/ "})
    assert _saved(root)["map_move"]["folder"] == "選單/設定"
    buttons.save(root, {"id": "map_move", "label": "選單:設定", "x": 10, "y": 10, "folder": ""})
    assert "folder" not in _saved(root)["map_move"]


def test_moving_many_at_once_leaves_the_rest_as_it_was(root):
    for i in ("a", "b", "c"):
        buttons.save(root, {"id": i, "label": i, "x": 1, "y": 1, "find": False})
    assert buttons.set_folders(root, {"a": "選單/設定", "b": "選單"}) == 2
    assert buttons.set_folders(root, {"a": "選單/設定"}) == 0          # already there
    s = _saved(root)
    assert s["a"]["folder"] == "選單/設定" and s["b"]["folder"] == "選單" and "folder" not in s["c"]
    assert (s["a"]["x"], s["a"]["label"]) == (1, "a")
    buttons.set_folders(root, {"b": ""})
    assert "folder" not in _saved(root)["b"]
    with pytest.raises(ValueError):
        buttons.set_folders(root, {"nope": "x"})
