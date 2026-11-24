"""Each device's own plan (automation/plans.py): entries on a week, run as schedules of that device alone; a kept
entry stands for its task's settings until the next kept one (or a RESET)."""
import datetime
import json
import os

import pytest

from automation import catalogs, plans, schedules, settings as settings_mod, subs as subs_mod

SPOTS = [{"label": "甲地", "value": {"item": "a"}}, {"label": "乙地", "value": {"item": "b"}}]
TASK = {"id": "go", "name": "去練習", "sub": "go_sub", "params": {"spot": {"label": "地點", "from": "catalog:spots", "sets": ["place"]}}}
ONCE = {"id": "feed", "name": "餵食", "sub": "feed_sub", "params": {}}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    data, run = tmp_path / "data", tmp_path / "run"
    (data / "meta").mkdir(parents=True)
    run.mkdir()
    monkeypatch.setattr(subs_mod, "load_all", lambda root: {"go_sub": {"id": "go_sub", "params": [{"name": "spot", "type": "text"}]},
                                                            "feed_sub": {"id": "feed_sub", "params": []}})
    monkeypatch.setattr(settings_mod, "load", lambda root=None: {"place": {"id": "place", "type": "item", "scope": "device", "default": {"item": "home"}}})
    monkeypatch.setattr(catalogs, "choices", lambda root, cid: SPOTS if cid == "spots" else [])
    monkeypatch.setattr(plans, "device_tags", lambda device: ["coop"] if device == "dev1" else [])
    plans.save_tasks(str(data), [TASK, ONCE])
    return str(data), str(run)


def at(day, hhmm):
    """a time in the week of 2026-11-23 (a Monday): day 0 = Monday"""
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime(2026, 11, 23 + day, h, m).timestamp()


def test_a_kept_entry_stands_until_the_next_and_a_reset_ends_it(roots, monkeypatch):
    data, run = roots
    import time as time_mod
    monkeypatch.setattr(time_mod, "time", lambda: at(-7, "00:00"))                    # planned the week before
    plans.save_plan(data, run, "dev1", [
        {"task": "go", "days": [0], "at": "10:00", "keep": True, "args": {"spot": {"item": "a"}}},
        {"task": "go", "days": [0], "at": "15:00", "keep": True, "args": {"spot": {"item": "b"}}},
        {"task": "feed", "days": [0], "at": "12:00", "keep": False},
        {"task": plans.RESET, "days": [2], "at": "08:00"}])
    ov = lambda t: plans.overlay(data, run, "dev1", t, ["coop"])                     # noqa: E731
    assert ov(at(0, "09:59")) == {}                                                   # last week ended with the reset
    assert ov(at(0, "10:00")) == {"place": {"item": "a"}}
    assert ov(at(0, "12:30")) == {"place": {"item": "a"}}                             # a "once" entry changes nothing
    assert ov(at(1, "23:00")) == {"place": {"item": "b"}}                             # kept over the night
    assert ov(at(2, "08:00")) == {}                                                   # back to the users' own


def test_the_kept_pick_is_what_a_run_reads_and_the_users_value_stays(roots, monkeypatch):
    data, run = roots
    import time as time_mod
    real = time_mod.time()
    monkeypatch.setattr(time_mod, "time", lambda: real - 8 * 86400)                   # planned more than a week ago
    plans.save_plan(data, run, "dev1", [{"task": "go", "days": list(range(7)), "at": "00:00", "keep": True, "args": {"spot": {"item": "b"}}}])
    monkeypatch.setattr(time_mod, "time", lambda: real)
    assert settings_mod.run_value(data, run, "place", "dev1") == {"item": "b"}
    assert settings_mod.value(data, run, "place", "dev1") == {"item": "home"}         # the panel's own value
    assert settings_mod.run_value(data, run, "place", "dev2") == {"item": "home"}     # another device: untouched


def test_entries_run_as_schedules_of_that_device_first_and_by_tag(roots):
    data, run = roots
    plans.save_plan(data, run, "#coop", [{"task": "feed", "days": [1], "at": "08:00"}])
    plans.save_plan(data, run, "dev1", [{"task": "go", "days": [0], "at": "02:00", "keep": True, "args": {"spot": {"item": "a"}}},
                                        {"task": plans.RESET, "days": [3], "at": "08:00"}])
    got = plans.as_schedules(data, run, "dev1", ["coop"], day_start=300)
    ids = {s["id"]: s for s in got}
    assert len(got) == 2                                                               # a reset runs nothing
    go = next(s for s in got if s["sub"] == "go_sub")
    assert go["devices"] == ["dev1"] and go["window"] == plans.WINDOW and go["args"] == {"spot": {"item": "a"}}
    assert go["days"] == [6]                     # 02:00 Monday is before the day starts at 05:00: Sunday's schedule day
    assert all(i.startswith(plans.PLAN_PREFIX) for i in ids)
    feed = next(s for s in got if s["sub"] == "feed_sub")
    st = schedules.State(os.path.join(run, "state.json"), 300)
    assert schedules.due([feed], "dev1", at(1, "08:05"), st) == [feed]
    assert schedules.due([feed], "dev1", at(1, "08:11"), st) == []                    # missed after 10 minutes


def test_what_is_checked_when_a_plan_is_saved(roots):
    data, run = roots
    bad = [[{"task": "nope", "days": [0], "at": "10:00"}],
           [{"task": "go", "days": [], "at": "10:00", "args": {"spot": {"item": "a"}}}],
           [{"task": "go", "days": [0], "at": "25:00", "args": {"spot": {"item": "a"}}}],
           [{"task": "go", "days": [0], "at": "10:00", "args": {"spot": {"item": "zzz"}}}],
           [{"task": "feed", "days": [0], "at": "10:00", "keep": True}]]                # nothing it could keep
    for entries in bad:
        with pytest.raises(ValueError):
            plans.save_plan(data, run, "dev1", entries)
    out = plans.save_plan(data, run, "dev1", [{"task": "feed", "days": [4, 0], "at": "07:30"}])
    assert out[0]["id"] and out[0]["days"] == [0, 4] and out[0]["keep"] is False
    assert json.load(open(os.path.join(run, plans.PLANS_FILE), encoding="utf-8"))["plans"]["dev1"][0]["id"] == out[0]["id"]
    plans.save_plan(data, run, "dev1", [])
    assert "dev1" not in plans.plans(run)


def test_a_thing_to_plan_must_name_what_its_sub_needs(roots):
    data, _run = roots
    with pytest.raises(ValueError):
        plans.save_tasks(data, [{"id": "go", "name": "去", "sub": "go_sub", "params": {}}])              # spot not offered
    with pytest.raises(ValueError):
        plans.save_tasks(data, [{**TASK, "params": {"spot": {**TASK["params"]["spot"], "sets": ["nope"]}}}])


def test_a_new_entry_counts_from_its_first_time_on(roots, monkeypatch):
    data, run = roots
    import time as time_mod
    monkeypatch.setattr(time_mod, "time", lambda: at(1, "15:20"))                     # made on Tuesday 15:20
    plans.save_plan(data, run, "dev1", [{"task": "go", "days": [1], "at": "15:25", "keep": True, "args": {"spot": {"item": "a"}}}])
    ov = lambda t: plans.overlay(data, run, "dev1", t, [])                            # noqa: E731
    assert ov(at(1, "15:22")) == {}                                                   # not last week's Tuesday
    assert ov(at(1, "15:25")) == {"place": {"item": "a"}}
    monkeypatch.setattr(time_mod, "time", lambda: at(2, "09:00"))
    e = plans.plans(run)["dev1"][0]
    plans.save_plan(data, run, "dev1", [{**e, "enabled": True}])                      # unchanged: still counts
    assert ov(at(2, "09:30")) == {"place": {"item": "a"}}
