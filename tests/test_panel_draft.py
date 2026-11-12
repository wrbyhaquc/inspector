"""The operation panel's draft and versions (server/panel_draft.py)."""
import os

import pytest

from server import panel as pm, panel_draft as pd


@pytest.fixture
def root(tmp_path, monkeypatch):
    import project
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")
    monkeypatch.setattr(project, "data_root", lambda: str(tmp_path))
    monkeypatch.setattr(pd, "RUNTIME_DIR", str(tmp_path / "run"))
    os.makedirs(tmp_path / "run")
    return str(tmp_path)


def panel(title, blocks=()):
    return {"title": title, "devices": [], "blocks": list(blocks), "controls": []}


def test_a_draft_is_not_what_users_see_until_it_is_published(root):
    pm.save(root, panel("old"))
    pd.save_draft(root, panel("new"))
    assert pm.load(root)["title"] == "old" and pd.load_draft(root)["panel"]["title"] == "new"
    assert not pd.load_draft(root)["stale"]
    pd.publish(root, panel("new"), "renamed")
    assert pm.load(root)["title"] == "new" and pd.load_draft(root) is None
    assert [v["note"] for v in pd.versions()] == ["renamed", "發佈前的面板"]   # the one it replaced is kept
    assert pd.version(pd.versions()[1]["id"])["panel"]["title"] == "old"
    pd.publish(root, panel("new"), "again")                                     # nothing changed: no new version
    assert len(pd.versions()) == 2


def test_a_draft_knows_when_someone_else_published_since(root):
    pm.save(root, panel("old"))
    pd.save_draft(root, panel("mine"))
    pd.publish(root, panel("theirs"), "AI", drop=False)
    assert pd.load_draft(root)["stale"]


def test_what_is_wrong_is_listed_with_its_block(root):
    bad = panel("P", [{"id": "w1", "title": "V", "items": [], "widget": {"kind": "values", "vars": []}},
                      {"id": "b1", "title": "", "items": []}])
    got = {(x["level"], x.get("block")) for x in pd.problems(root, bad)}
    assert ("error", "w1") in got and ("warn", "b1") in got
    assert pd.problems(root, panel("P", [{"id": "w1", "title": "L", "items": [], "widget": {"kind": "log"}}])) == []


def test_two_versions_in_the_same_millisecond_stay_apart(root, monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "time", lambda: 1794480000.123)              # a frozen clock: every keep at the same moment
    pd.keep(panel("a"), "first")
    pd.keep(panel("b"), "second")
    assert [v["note"] for v in pd.versions()] == ["second", "first"]
