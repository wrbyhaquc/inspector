"""Device cards of the operation panel show chosen states' values as people read them."""
import pytest

from server import app as appmod
from server import panel as pm


@pytest.mark.parametrize("s,v,text", [
    ({"type": "number", "unit": "枚"}, 361191225, "361,191,225 枚"),
    ({"type": "number"}, 12.5, "12.50"),
    ({"type": "ratio"}, 0.3254, "32.5%"),
    ({"type": "class", "classes": [{"value": 1, "name": "開"}, {"value": 0, "name": "關"}]}, 0, "關"),
    ({"type": "number"}, None, None),
])
def test_a_state_value_as_people_read_it(s, v, text):
    assert appmod._state_text(s, {"value": v}) == text


def test_a_card_shows_only_states_that_exist(tmp_path, monkeypatch):
    import schema as schema_mod
    monkeypatch.setattr(schema_mod, "load", lambda root: {"states": [{"id": "level", "name": "Level", "type": "number"}]})
    pm.check_widget(str(tmp_path), {"kind": "devices", "states": ["level"]})
    with pytest.raises(ValueError):
        pm.check_widget(str(tmp_path), {"kind": "devices", "states": ["gone"]})
