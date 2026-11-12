"""Catalogs (目錄): named items, each a sub-script call; a user setting chooses one, call_item runs it."""
import json
import os

import pytest

import project
from automation import buttons, catalogs, settings, spec, subs
from automation.runner import SubRun


def _sub(root, sid, params, steps=None):
    d = os.path.join(root, "meta", "subscripts", sid)
    os.makedirs(d, exist_ok=True)
    doc = spec.stamp({"id": sid, "name": sid.upper(), "params": params, "steps": steps or [{"type": "wait", "seconds": 0.01}]})
    with open(os.path.join(d, "v1.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    with open(os.path.join(d, "current.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1}, f)


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = str(tmp_path)
    monkeypatch.setattr(project, "data_root", lambda: r)
    monkeypatch.setattr(project, "screen", lambda root=None: (1280, 720))
    monkeypatch.setattr(buttons, "DATA_ROOT", r)
    monkeypatch.setattr(buttons, "_here", lambda: None)
    buttons.save(r, {"id": "spot_a", "label": "A", "x": 10, "y": 10})
    _sub(r, "go_map", [{"name": "place", "type": "point"}])
    _sub(r, "go_dungeon", [{"name": "card", "type": "point"}, {"name": "floor", "type": "number"}])
    return r


CATS = [{"id": "spots", "name": "地點", "items": [
    {"id": "a", "name": "A 區", "folder": " 地圖 / 北 ", "sub": "go_map", "args": {"place": {"button": "spot_a"}}},   # the old form
    {"id": "b", "name": "B 棟 3 樓", "folder": "室內", "calls": [{"sub": "go_dungeon", "args": {"card": {"x": 5, "y": 5}, "floor": 3}}]}]}]


def test_items_are_checked_like_a_call_and_filed_in_folders(root):
    out = catalogs.save(root, CATS)
    assert out[0]["items"][0]["folder"] == "地圖/北"
    assert out[0]["items"][0]["calls"] == [{"sub": "go_map", "args": {"place": {"button": "spot_a"}}}]
    assert catalogs.subs_of(catalogs.load(root)["spots"]) == {"go_map", "go_dungeon"}
    bad = json.loads(json.dumps(CATS))
    del bad[0]["items"][1]["calls"][0]["args"]["floor"]                          # a parameter left empty
    with pytest.raises(ValueError):
        catalogs.save(root, bad)
    bad = json.loads(json.dumps(CATS))
    bad[0]["items"][0]["sub"] = "nope"
    with pytest.raises(ValueError):
        catalogs.save(root, bad)
    assert "spot_a" in catalogs.buttons_used(root)
    with pytest.raises(ValueError):                                    # a sub-script an item uses stays
        subs.delete(root, "go_map")


def test_a_user_setting_picks_one_item(root):
    catalogs.save(root, CATS)
    decl = {"id": "spot", "label": "地點", "type": "item", "pick_from": "catalog:spots", "scope": "device", "default": {"item": "a"}}
    settings.save(root, [decl])
    assert [c["value"] for c in settings.choices(root, decl)] == [{"item": "a"}, {"item": "b"}]
    settings.check_value(root, decl, {"item": "b"})
    with pytest.raises(ValueError):
        settings.check_value(root, decl, {"item": "zz"})
    with pytest.raises(ValueError):                                    # an item type needs a catalog
        settings.save(root, [{**decl, "pick_from": "list:x"}])
    with pytest.raises(ValueError):                                    # the default still names it
        catalogs.save(root, [{**CATS[0], "items": CATS[0]["items"][1:]}])


def test_call_item_runs_the_chosen_items_call(root):
    catalogs.save(root, CATS)
    settings.save(root, [{"id": "spot", "label": "地點", "type": "item", "pick_from": "catalog:spots", "scope": "shared"}])
    main = {"id": "main", "name": "M", "params": [], "steps": [{"type": "call_item", "catalog": "spots", "item": {"setting": "spot"}}]}
    lib = subs.load_all(root)
    subs.validate(main, lib, {"states": []}, set())
    assert subs.calls(main) == {"go_map", "go_dungeon"}
    assert "B 棟 3 樓" in subs.describe_step({"type": "call_item", "catalog": "spots", "item": "b"}, {}, lib)
    with pytest.raises(ValueError):
        subs.validate({**main, "steps": [{"type": "call_item", "catalog": "spots", "item": "zz"}]}, lib, {"states": []}, set())
    lib["main"] = main
    SubRun.setting_lookup = staticmethod(lambda device, sid: {"item": "b"})
    try:
        run, logs = SubRun("A", "main", {}, lib, 0.0), []
        run.advance({}, 0.0, None, {}, lambda text, level="": logs.append(text))
        frame = run.stack[-1]
        assert frame.sub["id"] == "go_dungeon" and frame.args == {"card": {"x": 5, "y": 5}, "floor": 3}
        SubRun.setting_lookup = staticmethod(lambda device, sid: None)          # nothing chosen
        run = SubRun("A", "main", {}, lib, 0.0)
        run.advance({}, 0.0, None, {}, lambda text, level="": None)
        assert run.done and run.result == "failed"
    finally:
        SubRun.setting_lookup = None


HERE = [[{"kind": "var", "var": "here", "op": "is", "value": 1}]]


class _Env:
    def __init__(self, ctx):
        self._c = ctx

    def ctx(self, device):
        return self._c


def _run(lib, main, ctx):
    run, logs = SubRun("A", "main", {}, lib, 0.0), []
    t = 0.0
    while not run.done and t < 60:
        run.advance({}, t, None, {}, lambda text, level="": logs.append(text), _Env(ctx))
        t += 0.5
    return run, logs


def test_an_item_does_several_calls_and_checks_it_is_there(root):
    item = {"id": "c", "name": "C 區", "folder": "室內", "here": HERE, "here_wait": 3,
            "calls": [{"sub": "go_map", "args": {"place": {"button": "spot_a"}}},
                      {"sub": "go_dungeon", "args": {"card": {"x": 1, "y": 1}, "floor": 2}}]}
    out = catalogs.save(root, [{**CATS[0], "items": CATS[0]["items"] + [item]}])
    assert out[0]["items"][2]["here"] == HERE and out[0]["items"][2]["here_wait"] == 3
    assert catalogs.used_by(root)["go_dungeon"] == ["目錄「地點」項目「B 棟 3 樓」", "目錄「地點」項目「C 區」"]
    with pytest.raises(ValueError):                                   # a broken condition
        catalogs.save(root, [{**CATS[0], "items": [{**item, "here": [[{"kind": "nope"}]]}]}])
    with pytest.raises(ValueError):
        catalogs.save(root, [{**CATS[0], "items": [{**item, "calls": []}]}])
    _sub(root, "go_spot", [], [{"type": "call_item", "catalog": "spots", "item": "a"}])
    with pytest.raises(ValueError, match="繞"):                         # an item that does an item of its own catalog
        catalogs.save(root, [{**CATS[0], "items": CATS[0]["items"] + [{**item, "calls": [{"sub": "go_spot"}]}]}])
    sub = catalogs.as_sub(catalogs.load(root)["spots"], catalogs.item(root, "spots", "c"))
    assert [s["type"] for s in sub["steps"]] == ["if", "call", "call", "wait_until", "if"]
    main = {"id": "main", "name": "M", "params": [], "steps": [{"type": "call_item", "catalog": "spots", "item": "c"}]}
    lib = {**subs.load_all(root), "main": main}
    # already there: nothing is called
    run, logs = _run(lib, main, {"vars": {"here": 1}})
    assert run.result == "success" and not any("GO_MAP" in x for x in logs), logs
    # not there, and never gets there: both calls run, then it fails
    run, logs = _run(lib, main, {"vars": {"here": 0}})
    assert run.result == "failed" and any("GO_MAP" in x for x in logs) and any("GO_DUNGEON" in x for x in logs), logs


def test_a_run_inside_an_item_carries_on_after_a_restart(root):
    catalogs.save(root, CATS)
    main = {"id": "main", "name": "M", "params": [], "steps": [{"type": "call_item", "catalog": "spots", "item": "b"}]}
    lib = {**subs.load_all(root), "main": main}
    run = SubRun("A", "main", {}, lib, 0.0)
    run.advance({}, 0.0, None, {}, lambda text, level="": None, _Env({}))
    assert run.stack[-1].sub["id"] == "go_dungeon"
    back = SubRun.restore("A", run.snapshot(0.5), lib, 1.0)               # lib has no "@spots/b": made up again
    assert [f.sub["id"] for f in back.stack if f.kind == "call"] == ["main", "@spots/b", "go_dungeon"]
