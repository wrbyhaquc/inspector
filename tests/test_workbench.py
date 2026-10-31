"""The live workbench: what is at a spot, a state made from a box, what a teaching session writes down."""
import numpy as np
import pytest

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


def digits_picture():
    """two "characters" on a textured brown background"""
    img = np.full((720, 1280, 3), (92, 70, 48), np.uint8)
    img[::2, ::2] = (110, 84, 58)
    img[100:120, 200:208] = (225, 225, 225)              # a "1"
    img[100:120, 214:226] = (225, 225, 225)              # a "0"
    img[105:115, 217:223] = (92, 70, 48)
    return img


def test_a_number_is_read_by_the_colour_of_what_is_written_not_of_the_background():
    from labeler import generic
    img = digits_picture()
    req = wb_draft.NewState(device="d", frame="1", box=[195, 95, 40, 30], name="n", kind="digits")
    s = wb_draft.make_state(req, img, set())
    assert s["source"]["params"]["colors"][0]["s"][0] == 0   # white text on brown
    assert len(generic.glyphs(img, (195, 95, 40, 30), s["source"]["params"]["colors"])) == 2


def test_text_on_a_bar_is_told_from_the_bar_even_if_the_box_reaches_past_it():
    img = np.full((30, 80, 3), (60, 50, 40), np.uint8)
    img[4:30] = (200, 30, 30)                            # the bar, with the box's top edge above it
    img[10:22, 10:14] = (240, 240, 240)
    img[10:22, 20:24] = (240, 240, 240)
    assert wb_draft.text_color(img)["s"][0] == 0         # the white, not the red


def test_a_picture_with_nothing_written_has_no_text_colour():
    assert wb_draft.text_color(np.full((30, 40, 3), 90, np.uint8)) is None


def test_a_number_learns_its_characters_from_what_a_person_reads_there(monkeypatch):
    from labeler import generic
    img = digits_picture()
    monkeypatch.setattr(wb_draft, "draft_image", lambda name: img)
    monkeypatch.setattr(generic, "load_templates", lambda root, state: [])
    req = wb_draft.NewState(device="d", frame="1", box=[195, 95, 40, 30], name="n", kind="digits")
    s = wb_draft.make_state(req, img, set())
    doc = {**wb_draft.EMPTY, "states": [s], "refs": []}
    assert wb_draft.glyph_view(s, img, doc)["value"] is None
    with pytest.raises(wb_draft.HTTPException):
        wb_draft.teach_glyphs(doc, s, img, "101", "kept")      # three said, two there
    doc = wb_draft.teach_glyphs(doc, s, img, "1 0", "kept")
    assert [(r["value"], r["glyph"]) for r in doc["refs"]] == [("1", True), ("0", True)]
    got = wb_draft.glyph_view(s, img, doc)
    assert got["value"] == 10 and got["taught"] == ["0", "1"]
    assert wb_draft.teach_glyphs(doc, s, img, "10", "kept2")["refs"] == doc["refs"]    # already read right: nothing more


def test_two_numbers_with_a_slash_read_the_first_until_a_person_says(monkeypatch):
    from labeler import generic
    img = np.full((720, 1280, 3), 30, np.uint8)
    img[100:120, 200:208] = 230
    for x, x2 in ((212, 216), (216, 220), (220, 224)):   # a "/" made of a stair
        img[100 + (224 - x2):120 - (x - 212), x:x2] = 230
    img[100:120, 228:236] = 230
    monkeypatch.setattr(wb_draft, "draft_image", lambda name: img)
    monkeypatch.setattr(generic, "load_templates", lambda root, state: [])
    s = wb_draft.make_state(wb_draft.NewState(device="d", frame="1", box=[195, 95, 50, 30], name="n", kind="digits"), img, set())
    doc = wb_draft.teach_glyphs({**wb_draft.EMPTY, "states": [s], "refs": []}, s, img, "1/1", "kept")
    assert doc["states"][0]["source"]["params"]["part"] == "left"


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


def test_what_really_happened_comes_before_what_only_follows_it(monkeypatch):
    defs = [{"id": "auto", "name": "Auto", "type": "class", "classes": [{"value": 1, "name": "On"}]},
            {"id": "map", "name": "Map", "type": "class", "classes": [{"value": "no", "name": "Closed"}]}]
    monkeypatch.setattr(wb_draft, "merged_states", lambda doc=None: defs)
    got = wb_teach.changes({"auto": "hidden", "map": "yes"}, {"auto": 1, "map": "no"})     # closing a map: the rest can be seen again
    assert [c["state"] for c in got] == ["map", "auto"]


def test_among_equals_the_state_at_the_touch_comes_first(monkeypatch):
    defs = [{"id": "far", "name": "Far", "type": "class", "rois": [{"box": [900, 600, 50, 50]}]},
            {"id": "here", "name": "Here", "type": "class", "rois": [{"box": [100, 100, 50, 50]}]}]
    monkeypatch.setattr(wb_draft, "merged_states", lambda doc=None: defs)
    got = wb_teach.changes({"far": "a", "here": "a"}, {"far": "b", "here": "b"}, at=(120, 120))
    assert [c["state"] for c in got] == ["here", "far"]


def test_a_state_that_moves_by_itself_comes_last_and_says_so(monkeypatch):
    defs = [{"id": "blink", "name": "Blink", "type": "class"}, {"id": "map", "name": "Map", "type": "class"}]
    monkeypatch.setattr(wb_draft, "merged_states", lambda doc=None: defs)
    own = wb_teach.on_its_own([(t, {"blink": "on" if t % 2 else "off", "map": "no"}) for t in range(6)], [10])
    assert own == {"blink"}
    got = wb_teach.changes({"blink": "off", "map": "no"}, {"blink": "on", "map": "yes"}, own=own)
    assert [(c["state"], c["own"]) for c in got] == [("map", False), ("blink", True)]


def test_what_a_step_causes_is_not_taken_for_moving_by_itself():
    samples = [(0, {"map": "no"}), (1, {"map": "no"}), (2.5, {"map": "yes"}), (3, {"map": "no"}), (5, {"map": "no"}), (9, {"map": "yes"}), (10, {"map": "yes"})]
    assert wb_teach.on_its_own(samples, [2, 3]) == set()           # opened, closed at once, and once much later: a slow screen
    assert wb_teach.on_its_own(samples, []) == {"map"}             # the same with nobody touching


def test_a_touch_that_became_no_step_is_no_movement_by_itself():
    samples = [(t, {"map": "yes" if 2 < t < 6 else "no"}) for t in range(9)]
    assert wb_teach.on_its_own(samples, []) == {"map"}
    assert wb_teach.on_its_own(samples, [2.5, 5.5]) == set()


def test_a_touch_lands_where_it_is_on_a_screen_shown_sideways():
    from drivers.android import touch
    rng = (1279, 719)                                    # seen on an emulator: the range is turned, the app is shown sideways
    x, y = touch.to_fraction(918, 653, rng, 1)
    assert (round(x * 1279), round(y * 719)) == (1162, 203)   # the spot pressed on the 1280 x 720 picture
    assert touch.to_fraction(0, 0, rng, 0) == (0, 0)
    assert touch.to_fraction(rng[0], 0, rng, 3) == (1, 1)


def test_what_a_device_says_about_its_touch_screen_is_read():
    from drivers.android import touch
    lp = """add device 1: /dev/input/event4
  name:     "mouse"
add device 3: /dev/input/event2
  name:     "input"
  events:
    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 15, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 1279, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 719, fuzz 0, flat 0, resolution 0
"""
    assert touch.parse_ranges(lp) == {"/dev/input/event2": (1279, 719)}
    view = "mDefaultViewport=DisplayViewport{valid=true, displayId=0, orientation=1, logicalFrame=Rect(0, 0 - 1280, 720)}\n" \
           "mExternalTouchViewport=DisplayViewport{valid=false, displayId=0, orientation=0}"
    assert touch.parse_rotation(view) == 1
    assert touch.parse_rotation("nothing") is None


def test_a_run_of_taps_an_existing_sub_script_does_is_recognised(monkeypatch):
    lib = {"open": {"name": "Open", "steps": [{"type": "tap", "target": {"button": "a"}}, {"type": "wait", "seconds": 1}, {"type": "tap", "target": {"button": "b"}}]},
           "other": {"name": "Other", "steps": [{"type": "tap", "target": {"x": 1, "y": 2}}]},
           "takes": {"name": "Takes", "params": [{"name": "p"}], "steps": [{"type": "tap", "target": {"button": "a"}}]}}
    monkeypatch.setattr(wb_teach.subs_mod, "load_all", lambda root: lib)
    steps = [{"op": "back"}, {"op": "tap", "buttons": [{"id": "x"}, {"id": "a"}]}, {"op": "tap", "buttons": [{"id": "b"}]}]
    assert wb_teach.known_subs(steps) == [{"sub": "open", "name": "Open", "from": 1, "to": 2}]
