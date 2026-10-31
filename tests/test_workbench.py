"""The live workbench: what is at a spot, a state made from a box, what a teaching session writes down."""
import numpy as np

from server import wb_draft, wb_teach


def picture():
    img = np.full((720, 1280, 3), 30, np.uint8)
    img[100:140, 200:400] = (220, 30, 30)              # a red bar
    return img


BUTTONS = [{"id": "near", "label": "Near", "x": 300, "y": 120, "find": False},
           {"id": "gone", "label": "Gone", "x": 300, "y": 120, "find": True, "found": False},
           {"id": "moved", "label": "Moved", "x": 10, "y": 10, "find": True, "found": True, "at": [305, 125]},
           {"id": "far", "label": "Far", "x": 900, "y": 600, "find": False}]
STATES = [{"id": "bar", "name": "Bar", "rois": [{"id": "main", "box": [200, 100, 200, 40]}]},
          {"id": "other", "name": "Other", "rois": [{"id": "main", "box": [800, 500, 100, 100]}]}]


def test_a_point_finds_the_buttons_there_and_not_those_not_on_this_picture():
    got = wb_draft.spot(picture(), [302, 122, 0, 0], STATES, BUTTONS)
    assert [b["id"] for b in got["buttons"]] == ["near", "moved"]    # where a find button was found counts, not where it was made
    assert [s["state"] for s in got["states"]] == ["bar"]


def test_a_box_says_what_it_looks_like():
    got = wb_draft.spot(picture(), [200, 100, 200, 40], STATES, BUTTONS)
    assert got["looks"] == "bar" and got["ratio"] > 0.9 and got["color"]
    assert [s["state"] for s in got["states"]] == ["bar"]


def test_a_state_made_from_a_box_judges_that_very_picture():
    from labeler import generic
    img = picture()
    req = wb_draft.NewState(device="d", frame="1", box=[200, 100, 200, 40], name="紅色長條", kind="color")
    s = wb_draft.make_state(req, img, set())
    assert s["id"] == "state_1"                          # a name in any language still gets a code
    generic.validate(s)
    assert generic.evaluate(s, img)[0] == "yes"
    assert generic.evaluate(s, np.full((720, 1280, 3), 30, np.uint8))[0] == "no"


def test_codes_do_not_clash():
    assert wb_draft.new_id("Map open", set(), "state") == "map_open"
    assert wb_draft.new_id("Map open", {"map_open"}, "state") == "map_open_1"
    assert wb_draft.new_id("地圖", {"state_1"}, "state") == "state_2"


def test_what_uses_a_thing_is_found_anywhere_in_a_script():
    doc = {"situations": [{"rules": [{"when": [[{"state": "hp"}]], "do": [{"type": "if", "then": [{"target": {"button": "ok"}}]}]}]}]}
    assert wb_draft._uses(doc, "state", "hp") and wb_draft._uses(doc, "button", "ok")
    assert not wb_draft._uses(doc, "button", "hp")


def test_a_step_can_wait_for_what_changed(monkeypatch):
    defs = [{"id": "map", "name": "Map", "type": "class", "classes": [{"value": "yes", "name": "Open"}]},
            {"id": "auto", "name": "Auto", "type": "class", "classes": [{"value": "hidden", "name": "Hidden"}]},
            {"id": "hp", "name": "HP", "type": "ratio"}]
    monkeypatch.setattr(wb_draft, "merged_states", lambda doc=None: defs)
    got = wb_teach.changes({"map": "no", "auto": 1, "hp": 0.5}, {"map": "yes", "auto": "hidden", "hp": 0.4})
    assert [c["state"] for c in got] == ["map", "auto"]  # something appearing says more; a number running on says nothing
    assert got[0]["value_name"] == "Open"
    assert wb_teach.changes({"map": None}, {"map": "yes"}) == []      # not known before: no change seen


def test_a_run_of_taps_an_existing_sub_script_does_is_recognised(monkeypatch):
    lib = {"open": {"name": "Open", "steps": [{"type": "tap", "target": {"button": "a"}}, {"type": "wait", "seconds": 1}, {"type": "tap", "target": {"button": "b"}}]},
           "other": {"name": "Other", "steps": [{"type": "tap", "target": {"x": 1, "y": 2}}]},
           "takes": {"name": "Takes", "params": [{"name": "p"}], "steps": [{"type": "tap", "target": {"button": "a"}}]}}
    monkeypatch.setattr(wb_teach.subs_mod, "load_all", lambda root: lib)
    steps = [{"op": "back"}, {"op": "tap", "buttons": [{"id": "x"}, {"id": "a"}]}, {"op": "tap", "buttons": [{"id": "b"}]}]
    assert wb_teach.known_subs(steps) == [{"sub": "open", "name": "Open", "from": 1, "to": 2}]
