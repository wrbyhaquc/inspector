"""Behaviour of the platform that has broken before: each test names what it keeps fixed."""
import collections
import json
import os
import types

import pytest

import project


# ---------------------------------------------------------------- panel controls for some sources (spec 9)
def test_a_control_for_some_sources_acts_only_on_them():
    from server import panel
    c = {"id": "vents", "type": "action", "scope": "device", "devices": ["GH-CAM"], "bind": {"kind": "act_sub", "sub": "x"}}
    assert panel.applies(c, "GH-CAM") and not panel.applies(c, "COOP-CAM")
    assert panel.act_targets(None, c, "COOP-CAM", ["GH-CAM", "COOP-CAM"]) == []
    assert panel.act_targets(None, c, "GH-CAM", ["GH-CAM", "COOP-CAM"]) == ["GH-CAM"]
    every = {**c, "devices": []}
    assert panel.applies(every, "COOP-CAM")
    shared = {**c, "scope": "global"}
    assert panel.act_targets(None, shared, None, ["GH-CAM", "COOP-CAM"]) == ["GH-CAM", "COOP-CAM"] or \
        panel.act_targets(None, shared, None, ["GH-CAM", "COOP-CAM"]) == ["GH-CAM"]


def test_a_value_for_a_source_the_control_is_not_for_is_refused():
    from server import panel
    c = {"id": "t", "label": "T", "type": "toggle", "scope": "device", "devices": ["A"], "bind": {"kind": "setting", "setting": "s"}}
    with pytest.raises(ValueError):
        panel._check(None, c, "B", True)
    assert panel._check(None, c, "A", True) is True


# ---------------------------------------------------------------- pack export
def test_export_leaves_out_deleted_scripts(tmp_path):
    from project import pack
    src = tmp_path / "design" / "meta" / "scripts"
    (src / "keeper").mkdir(parents=True)
    (src / "keeper" / "current.json").write_text('{"version": 2}', encoding="utf-8")
    (src / "keeper" / "v1.json").write_text("{}", encoding="utf-8")
    (src / "keeper" / "v2.json").write_text("{}", encoding="utf-8")
    (src / ".deleted" / "main_1").mkdir(parents=True)
    (src / ".deleted" / "main_1" / "current.json").write_text('{"version": 1}', encoding="utf-8")
    out = tmp_path / "out"
    pack._copy_tree(str(tmp_path / "design"), str(out))
    files = sorted(os.path.relpath(os.path.join(d, f), out).replace("\\", "/") for d, _s, fs in os.walk(out) for f in fs)
    assert files == ["meta/scripts/keeper/current.json", "meta/scripts/keeper/v2.json"]


# ---------------------------------------------------------------- how a design is meant to run (project.json "run")
_n = [0]


def _design(tmp_path, **extra):
    _n[0] += 1                                        # a folder of its own each time: no cache to outwit
    d = tmp_path / f"design{_n[0]}"
    d.mkdir()
    (d / "project.json").write_text(json.dumps({"id": "t", "screen": {"width": 1280, "height": 720}, **extra}), encoding="utf-8")
    return str(d)


def test_run_defaults_stay_within_the_platforms_limits(tmp_path):
    assert project.run_defaults(_design(tmp_path)) == {}
    assert project.run_defaults(_design(tmp_path, run={"interval": 0.3, "max_per_min": 60})) == {"interval": 0.3, "max_per_min": 60}
    assert project.run_defaults(_design(tmp_path, run={"interval": 0.01, "max_per_min": 500})) == {"interval": 0.3, "max_per_min": 60}
    assert project.run_defaults(_design(tmp_path, run={"interval": "fast"})) == {}


# ---------------------------------------------------------------- first start: which sources are used
def test_first_start_takes_declared_and_referenced_sources_only(tmp_path, monkeypatch):
    from drivers import sources
    design = _design(tmp_path, sources={"CAM-1": {"kind": "stream/http", "name": "Camera",
                                                  "params": {"url": "http://127.0.0.1:1/x.mjpg"}}})
    os.makedirs(os.path.join(design, "meta"), exist_ok=True)
    with open(os.path.join(design, "meta", "panel.json"), "w", encoding="utf-8") as f:
        json.dump({"devices": ["EMU-7"], "blocks": [], "controls": []}, f)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("INSPECTOR_RUNTIME", str(runtime))
    import drivers
    real = drivers.kinds

    class Found:                                      # what a scan of this computer would find: never asked for now
        caps = {"screen", "tap"}

        def __init__(self, *_a, **_k):
            raise AssertionError("the first start must not take every device found")
    monkeypatch.setattr(drivers, "kinds", lambda: {**real(), "android/ldplayer": Found})
    cfg = sources.load(design)
    items = {it["id"]: it for it in cfg["items"]}
    assert set(items) == {"CAM-1", "EMU-7"}
    assert items["CAM-1"]["hand"] == {"to": "none"}   # a stream only watches
    assert items["CAM-1"]["params"]["url"].endswith("x.mjpg")


# ---------------------------------------------------------------- the runner's notices
def test_a_notice_not_about_one_device_does_not_stop_the_runner(capsys):
    from runtime.shadow import Shadow
    told = []
    fake = types.SimpleNamespace(clock=lambda: 1.0, alerts=collections.deque(maxlen=10),
                                 notifier=types.SimpleNamespace(emit=lambda *a, **k: told.append(a)),
                                 incidents=types.SimpleNamespace(note=lambda *a, **k: None), _append_log=lambda rec: None)
    Shadow.alert(fake, None, "found a new source", "info")
    assert fake.alerts[0]["device"] is None and told
    assert "found a new source" in capsys.readouterr().out


def test_first_start_of_a_blank_project_uses_no_device_found(tmp_path, monkeypatch):
    """A new computer with emulators running: they are only found (the Sources page lists them to pick)."""
    from drivers import sources, Device
    design = _design(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("INSPECTOR_RUNTIME", str(runtime))
    import drivers
    real = drivers.kinds

    class Found:
        caps = {"screen", "tap"}

        def __init__(self, *_a, **_k):
            pass

        def list(self):
            return [Device("EMU-1"), Device("EMU-2")]
    monkeypatch.setattr(drivers, "kinds", lambda: {**real(), "android/ldplayer": Found})
    assert sources.load(design)["items"] == []


# ---------------------------------------------------------------- states for some sources only
def test_a_state_for_some_sources_is_not_looked_at_on_others():
    import schema
    tags = {"#greenhouse": ["GH-1", "GH-2"]}
    expand = lambda keys: [i for k in keys for i in (tags.get(k, [k]))]
    states = [{"id": "vents", "sources": ["#greenhouse"], "classes": [{"value": "open"}, {"value": "closed"}, {"value": "hidden"}]},
              {"id": "temp", "sources": ["GH-1"]},
              {"id": "daylight"}]
    assert schema.not_here(states, "GH-1", expand) == {}
    assert schema.not_here(states, "GH-2", expand) == {"temp": None}
    assert schema.not_here(states, "COOP", expand) == {"vents": "hidden", "temp": None}


def test_only_on_these_sources_is_checked_and_is_a_setting():
    import schema
    base = {"id": "s", "name": "S", "type": "class", "classes": [{"value": "a"}, {"value": "b"}],
            "rois": [], "source": {"kind": "manual"}}
    schema.validate({"states": [{**base, "sources": ["CAM-1", "#north"]}]})
    for bad in ([], "CAM-1", ["has space"]):
        with pytest.raises(ValueError):
            schema.validate({"states": [{**base, "sources": bad}]})
    assert "states[].sources" in schema.SETTINGS             # changing it makes no new version: nothing to relabel


def test_confirm_one_or_two_looks(tmp_path):
    assert project.run_defaults(_design(tmp_path, run={"confirm": 1})) == {"confirm": 1}
    assert project.run_defaults(_design(tmp_path, run={"confirm": 5})) == {"confirm": 2}
    assert project.run_defaults(_design(tmp_path, run={"confirm": 0})) == {"confirm": 1}


# ---------------------------------------------------------------- exporting from the page
def test_export_check_compares_with_the_last_release(tmp_path):
    from project import pack
    out = str(tmp_path / "releases")
    first = pack.export_check(out=out)
    assert first["last"] is None and first["changes"] is None
    assert not [c for c in first["checks"] if c["level"] == "error"]
    pack.export(out=out, version="0.1.0", say=lambda *_a: None)
    same = pack.export_check(out=out)
    assert same["last"]["version"] == "0.1.0" and same["next"] == "0.1.1"
    assert same["changes"] == {"added": [], "removed": [], "changed": []}
    p = project.load()
    project.save({**p, "description": "changed"})
    moved = pack.export_check(out=out)
    assert "design/project.json" in moved["changes"]["changed"] and not moved["changes"]["added"]
