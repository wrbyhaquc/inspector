"""The operation panel's grid (spec v11): an older panel is placed from its order and widths, a place is checked."""
import pytest

from automation import spec, spec_schema
from server import panel as pm


def old_panel():
    return {"title": "P", "pages": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            "controls": [{"id": "per", "label": "Per", "type": "number", "scope": "device", "bind": {"kind": "setting", "setting": "x"}}],
            "blocks": [{"id": "b1", "title": "1", "items": [], "width": "third"},
                       {"id": "b2", "title": "2", "items": [], "width": "two_thirds"},
                       {"id": "b3", "title": "3", "items": [], "width": "narrow"},
                       {"id": "b4", "title": "4", "items": ["per"]},                        # auto, asked per device: a whole row
                       {"id": "b5", "title": "5", "items": []},                             # auto: half
                       {"id": "b6", "title": "6", "items": [], "page": "b", "widget": {"kind": "log"}}]}


def test_an_older_panel_is_placed_row_by_row_from_its_widths():
    p = pm.normalize(old_panel())
    places = {b["id"]: b["place"] for b in p["blocks"]}
    assert places == {"b1": {"x": 0, "y": 0, "w": 4}, "b2": {"x": 4, "y": 0, "w": 8}, "b3": {"x": 0, "y": 1, "w": 6},
                      "b4": {"x": 0, "y": 2, "w": 12}, "b5": {"x": 0, "y": 3, "w": 6},
                      "b6": {"x": 0, "y": 0, "w": 12}}                                 # its own page starts at the top


def test_a_new_block_goes_under_the_placed_ones():
    p = old_panel()
    p["blocks"] = [{"id": "a", "title": "A", "items": [], "place": {"x": 6, "y": 2, "w": 6, "h": 3}},
                   {"id": "n", "title": "N", "items": [], "width": "wide"}]
    p = pm.normalize(p)
    assert p["blocks"][0]["place"] == {"x": 6, "y": 2, "w": 6, "h": 3}
    assert p["blocks"][1]["place"] == {"x": 0, "y": 5, "w": 12}


@pytest.mark.parametrize("place", [{"x": 12, "y": 0, "w": 1}, {"x": 8, "y": 0, "w": 6}, {"x": 0, "y": -1, "w": 3},
                                   {"x": 0, "y": 0, "w": 0}, {"x": 0, "y": 0}, {"x": "0", "y": 0, "w": 3}, {"x": 0, "y": 0, "w": 3, "z": 1}])
def test_a_wrong_place_is_refused(place):
    with pytest.raises(ValueError):
        pm.check_place({"title": "B", "place": place})


def test_phone_order_and_hiding_are_checked():
    pm.check_place({"title": "B", "place": {"x": 0, "y": 0, "w": 6}, "phone": {"order": 2, "hide": True}})
    with pytest.raises(ValueError):
        pm.check_place({"title": "B", "place": {"x": 0, "y": 0, "w": 6}, "phone": {"hide": "yes"}})


def test_the_schema_takes_places_and_a_theme():
    doc = spec.stamp({"theme": {"accent": "#0369a1", "big_text": True}, "controls": [],
                      "blocks": [{"id": "b", "title": "B", "place": {"x": 0, "y": 0, "w": 12}, "phone": {"order": 1}}]})
    assert spec_schema.schema_errors("panel", doc) == []
    assert spec_schema.schema_errors("panel", {**doc, "theme": {"accent": "blue"}})


def test_save_checks_the_theme(tmp_path):
    base = {"title": "P", "controls": [], "blocks": []}
    with pytest.raises(ValueError):
        pm.save(str(tmp_path), {**base, "theme": {"accent": "red"}})
    pm.save(str(tmp_path), {**base, "theme": {"accent": "#112233", "big_text": False}})
    assert pm.load(str(tmp_path))["theme"] == {"accent": "#112233"}         # off is the same as not set
