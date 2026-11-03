"""Starting the operation panel from the design (server/panel_start.py): what is listed, what each thing becomes,
and first versions of a whole panel that save as they are."""
import json
import os

import automation
from server import panel as pm, panel_start as ps


def design(root):
    """A small design: two user settings (one the panel cannot show), a schedule, a main script with two situations,
    a sub-script that needs nothing, two variables."""
    meta = os.path.join(root, "meta")
    os.makedirs(meta, exist_ok=True)

    def put(name, obj):
        with open(os.path.join(meta, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    put("user_settings.json", {"settings": [
        {"id": "wait", "label": "Wait", "type": "number", "scope": "shared", "default": 30, "min": 1, "max": 99},
        {"id": "note", "label": "Note", "type": "text", "scope": "shared", "default": ""}]})
    put("schedules.json", {"schedules": [{"id": "morning", "name": "Morning", "enabled": True, "at": "08:00", "devices": ["d1"], "sub": "tidy", "args": {}}]})
    put("variables.json", {"vars": [{"name": "trips", "label": "Trips", "scope": "device", "reset": "daily", "initial": 0},
                                    {"name": "last", "label": "Last", "scope": "global", "reset": "never", "initial": 0}]})
    from automation import subs
    subs.save(root, {"id": "tidy", "name": "Tidy", "params": [], "steps": [{"type": "back"}]})
    automation.save(root, {"id": "patrol", "name": "Patrol", "situations": [{"id": "walk", "name": "Walk", "rules": []},
                                                                           {"id": "home", "name": "Home", "rules": []}]}, "test")


LIVE = {"devices": [{"name": "d1", "situations": {"patrol": {"id": "home"}}}],
        "vars": {"global": {"last": 1793659560.6}, "device": {"d1": {"trips": 2}}}}


def test_the_design_is_listed_with_what_it_is_now(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")
    root = str(tmp_path)
    design(root)
    things = {(t["kind"], t["id"]): t for t in ps.catalog(root, root, LIVE)}
    assert things[("setting", "wait")]["now"] == "30"
    assert things[("setting", "note")]["why"] and "add" not in things[("setting", "note")]   # text: not on a panel yet
    assert things[("schedule", "morning")]["now"].startswith("08:00")
    assert things[("situation", "patrol/home")]["now"] == "d1" and things[("situation", "patrol/home")]["group"] == "Patrol"
    assert things[("variable", "trips")]["now"] == "2"
    assert things[("variable", "last")]["now"][2] == "-"                    # seconds since 1970: shown as a time
    sched = things[("schedule", "morning")]["add"]
    assert sched["block"]["toggle"] == "c1" and [c["bind"]["kind"] for c in sched["controls"]] == ["schedule", "schedule", "schedule_device", "act_schedule"]
    assert things[("variable", "trips")]["add"]["block"]["widget"] == {"kind": "values", "vars": ["trips"]}


def test_every_thing_and_every_template_saves_as_it_is(tmp_path, monkeypatch):
    import project
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")
    root = str(tmp_path)
    monkeypatch.setattr(project, "data_root", lambda: root)          # a control reads its user setting from here
    design(root)
    for t in ps.catalog(root, root, LIVE):
        if "add" in t:
            b = {**t["add"]["block"], "id": "b1"}
            pm.save(root, {"title": "P", "devices": [], "blocks": [b], "controls": t["add"]["controls"]})
    drafts = ps.drafts(root, root)
    assert set(drafts) == set(ps.TEMPLATES)
    for name, d in drafts.items():
        pm.save(root, {"title": "P", "devices": [], **json.loads(json.dumps(d))})
        saved = pm.load(root)
        assert len(saved["blocks"]) == len(d["blocks"]) and all(b.get("place") for b in saved["blocks"]), name
    full = drafts["full"]
    assert [p["title"] for p in full["pages"]] == ["總覽", "排程", "設定", "紀錄"]
    assert {c["bind"].get("setting") for c in full["controls"] if c["bind"]["kind"] == "setting"} == {"wait"}
    assert not drafts["watch"]["controls"]
    assert "pages" not in drafts["simple"]
