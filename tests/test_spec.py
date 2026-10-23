"""The script spec: the published schemas match the code, older files are upgraded, newer ones refused."""
import json
import os

import pytest

from automation import spec, spec_schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("kind", spec_schema.KINDS)
def test_published_schema_matches_the_code(kind):
    """docs/spec/v<FORMAT>/ is the contract: regenerate it (python -m automation.spec_schema --write ...) when the
    spec changes."""
    path = os.path.join(ROOT, "docs", "spec", f"v{spec.FORMAT}", f"{kind}.schema.json")
    assert os.path.exists(path), f"docs/spec/v{spec.FORMAT} is missing {kind}.schema.json"
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == json.loads(json.dumps(spec_schema.schema(kind)))


def test_only_the_current_schemas_are_published():
    assert os.listdir(os.path.join(ROOT, "docs", "spec")) == [f"v{spec.FORMAT}"]


def test_a_version_7_rule_action_becomes_steps():
    old = {"format": 7, "id": "m", "name": "M", "situations": [{"id": "s", "name": "S", "on_enter": {"type": "tap", "target": {"x": 1, "y": 2}},
                                                                 "rules": [{"id": "r", "when": [], "action": {"type": "back"}}]}]}
    new = spec.upgrade(old)
    assert new["format"] == spec.FORMAT
    rule = new["situations"][0]["rules"][0]
    assert "action" not in rule and isinstance(rule["do"], list) and rule["do"]
    assert isinstance(new["situations"][0]["on_enter"], list)
    assert old["format"] == 7                          # the original is left alone


def test_a_version_0_wait_parameter_becomes_a_value():
    new = spec.upgrade({"steps": [{"type": "wait", "seconds_param": "t"}]})
    assert new["steps"][0]["seconds"] == {"param": "t"}


def test_a_newer_file_is_refused():
    with pytest.raises(ValueError):
        spec.check({"format": spec.FORMAT + 1}, "x")
    spec.check({"format": spec.FORMAT}, "x")


def test_a_panel_control_may_name_its_sources():
    errs = spec_schema.schema_errors("panel", spec.stamp({
        "blocks": [{"id": "b", "title": "B", "items": ["c"]}],
        "controls": [{"id": "c", "label": "C", "type": "action", "scope": "device", "devices": ["CAM-1", "#north"],
                      "bind": {"kind": "act_stop"}}]}))
    assert errs == []
