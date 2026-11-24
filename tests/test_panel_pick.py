"""A panel button with a pick beside it (act_sub + "arg"): what is picked goes to the sub-script for that run only."""
import pytest

from server import panel as pm


def button(**kw):
    return {"id": "go", "label": "前往", "type": "action", "scope": "device",
            "bind": {"kind": "act_sub", "sub": "go_to", "arg": "spot"},
            "options": [{"label": "甲地", "value": {"item": "a"}}, {"label": "乙地", "value": {"item": "b"}}], **kw}


def test_the_pick_is_the_runs_argument(tmp_path):
    c = button()
    assert pm.pick_value(str(tmp_path), c, "dev1", {"item": "b"}) == {"spot": {"item": "b"}}
    assert pm.pick_label(str(tmp_path), c, "dev1", {"item": "b"}) == "乙地"
    with pytest.raises(ValueError):
        pm.pick_value(str(tmp_path), c, "dev1", None)                      # nothing picked
    with pytest.raises(ValueError):
        pm.pick_value(str(tmp_path), c, "dev1", {"item": "zzz"})           # not one of its options
    plain = {**c, "bind": {"kind": "act_sub", "sub": "go_to"}}
    assert pm.pick_value(str(tmp_path), plain, "dev1", None) == {}         # a button without a pick: as before


def test_a_sub_with_one_argument_can_be_a_button_when_it_is_picked(tmp_path, monkeypatch):
    sub = {"id": "go_to", "name": "前往", "params": [{"name": "spot", "type": "text"}], "steps": []}
    monkeypatch.setattr(pm.subs_mod, "load_all", lambda root: {"go_to": sub})
    assert pm.value(str(tmp_path), button()) is None                        # fine
    with pytest.raises(ValueError):
        pm.value(str(tmp_path), {**button(), "bind": {"kind": "act_sub", "sub": "go_to"}})   # its argument not given
    with pytest.raises(ValueError):
        pm.value(str(tmp_path), {**button(), "options": None})               # nothing to pick from
    with pytest.raises(ValueError):
        pm.value(str(tmp_path), {**button(), "bind": {"kind": "act_sub", "sub": "go_to", "arg": "nope"}})


def test_where_the_pick_comes_from_is_found_in_the_sub():
    from server.panel_start import _pick_from
    sub = {"steps": [{"type": "retry", "times": 2, "steps": [{"type": "call_item", "catalog": "spots", "item": {"param": "spot"}}]}]}
    assert _pick_from(sub, {"name": "spot"}) == "catalog:spots"
    assert _pick_from(sub, {"name": "other"}) is None
    assert _pick_from({"steps": []}, {"name": "who", "from_list": "people"}) == "list:people"
