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


def test_naming_the_project_is_the_first_stop_of_the_route(monkeypatch):
    from fastapi.testclient import TestClient
    import server.app as app
    c = TestClient(app.app, client=("127.0.0.1", 50000))
    assert c.get("/api/project", headers={"X-Lang": "en"}).json()["name"] == "New project"   # not named yet: in the page's language
    assert c.get("/api/getting_started").json()["done"]["project"] is False
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")                                       # the design is changed in Studio only
    assert c.post("/api/project/settings", json={"name": " ", "description": "", "words": {}}).status_code == 400
    assert c.post("/api/project/settings", json={"name": "Pond", "description": "", "words": {"device": "x" * 21}}).status_code == 400
    r = c.post("/api/project/settings", json={"name": "Pond", "description": "One camera", "words": {"device": "camera"}})
    assert r.status_code == 200 and r.json()["name"] == "Pond" and r.json()["words"]["device"] == "camera"
    done = c.get("/api/getting_started").json()["done"]
    assert done["project"] is True and not any(v for k, v in done.items() if k != "project")


def test_a_new_pack_does_not_warn_about_its_own_spec(tmp_path):
    from automation import spec
    from project import manifest
    design = tmp_path / "design" / "meta"
    design.mkdir(parents=True)
    (design / "order.json").write_text(json.dumps(spec.stamp({"order": []})), encoding="utf-8")
    new = manifest.stamp({"id": "pond", "name": "Pond"})
    assert new["requires"]["spec"] == spec.FORMAT
    assert not [x for x in manifest.check(new, str(tmp_path)) if "pack.json" in x[1]]
    made_by_0_2_0 = {**new, "requires": {**new["requires"], "spec": 0}}           # 0.2.0 recorded 0 for an empty design
    assert not [x for x in manifest.check(made_by_0_2_0, str(tmp_path)) if "pack.json" in x[1]]


# ---------------------------------------------------------------- recording replay

def _recording(root, sid, dev, times, ended=True):
    from PIL import Image
    d = root / "sessions" / sid / "devices" / dev
    (d / "frames").mkdir(parents=True)
    with open(d / "samples.jsonl", "w", encoding="utf-8") as f:
        for k, t in enumerate(times):
            Image.new("RGB", (64, 36), (k * 40 % 255, 0, 0)).save(d / "frames" / f"{k}.png")
            f.write(json.dumps({"id": str(k), "t_req": t, "frame": f"frames/{k}.png"}) + "\n")
    meta = {"started": times[0], "devices": {dev: {"samples": len(times)}}}
    if ended:
        meta["ended"] = times[-1]
    (root / "sessions" / sid / "session.json").write_text(json.dumps(meta), encoding="utf-8")


def test_a_recording_replays_in_its_timing_with_long_pauses_shortened(tmp_path, monkeypatch):
    from drivers import recording
    monkeypatch.setattr(project, "work_root", lambda: str(tmp_path))
    monkeypatch.setattr(project, "screen", lambda: (64, 36))
    _recording(tmp_path, "s1", "CAM", [100.0, 101.0, 161.0, 162.0])          # a minute's pause in the middle
    _recording(tmp_path, "s2", "CAM", [200.0, 201.0], ended=False)              # still recording: not offered
    rec = recording.Recording({"max_gap": "5", "speed": "1"})
    assert [d.name for d in rec.list()] == ["s1 CAM"]
    p = rec.capture("s1 CAM")
    assert p.at == [0.0, 1.0, 6.0, 7.0]
    clock = [1000.0]
    monkeypatch.setattr(recording.time, "time", lambda: clock[0])
    p.t0 = 1000.0
    for t, k in ((0.5, 0), (3.0, 1), (6.5, 2), (7.5, 3), (8.2, 0)):                # ... and starts over
        clock[0] = 1000.0 + t
        img, how, size = p.grab()
        assert p.shown == k and img.shape == (36, 64, 3) and how == "recording"
    assert recording.Recording({"speed": "2"}).capture("s1 CAM").at == [0.0, 0.5, 3.0, 3.5]


def test_the_recorder_does_not_record_a_replay(monkeypatch):
    import types
    from collector import collector as col
    from drivers import Device
    found = [Device("CAM", info={"kind": "stream/http"}), Device("s1 CAM", info={"kind": "recording/default"})]
    told = []
    c = types.SimpleNamespace(driver=types.SimpleNamespace(list=lambda: found), s=types.SimpleNamespace(only=None),
                              _ask=lambda what, insts: told.append([i.name for i in insts]), lock=__import__("threading").RLock(),
                              devs={})
    monkeypatch.setattr(col, "DeviceCtx", lambda owner, inst: types.SimpleNamespace(start=lambda: None, inst=inst, thread=None))
    col.Collector.rescan(c)
    assert told == [["CAM"]] and list(c.devs) == ["CAM"]


# ---------------------------------------------------------------- source health

def test_a_black_or_one_colour_picture_is_told_a_dark_scene_is_not():
    import numpy as np
    from runtime.health import Health
    h = Health()
    rnd = np.random.default_rng(1)
    night = np.clip(rnd.normal(35, 15, (360, 640, 3)), 0, 255).astype(np.uint8)       # a pond at night: dark, but a picture
    for t in range(0, 200, 2):
        h.frame("POND", night if t % 4 else night[::-1], 20, 1000.0 + t)
        h.frame("CAM", np.zeros((360, 640, 3), np.uint8), 20, 1000.0 + t)             # a covered lens
        h.frame("NVR", np.full((360, 640, 3), (20, 40, 160), np.uint8), 20, 1000.0 + t)  # a recorder's "no signal" blue
    assert h.check("POND", 1198.0)[0] == "ok"
    state, text, changed, _info = h.check("CAM", 1198.0)
    assert state == "blank" and changed and "全黑" in text
    assert h.check("NVR", 1198.0)[0] == "blank" and "單色" in h.check("NVR", 1198.0)[1]
    assert h.check("CAM", 1198.0, blank_s=0)[0] != "blank"                            # 0 = not looked for
    h.frame("CAM", night, 20, 1199.0)                                                  # the lens uncovered
    assert h.check("CAM", 1199.5)[0] == "ok"


# ---------------------------------------------------------------- keeping the run's records for a while

def test_old_run_records_are_deleted_and_recordings_open_incidents_and_recent_days_are_kept(tmp_path):
    import datetime
    from runtime import retention
    shadow, rt, work = tmp_path / "work" / "shadow", tmp_path / "rt", tmp_path / "work"

    def put(path, text="x"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    put(shadow / "actions" / "20260901" / "1_CAM.jpg")
    put(shadow / "actions" / "20261020" / "2_CAM.jpg")
    put(shadow / "incidents" / "20260901_120000_CAM" / "incident.json", json.dumps({"status": "resolved"}))
    put(shadow / "incidents" / "20260902_120000_CAM" / "incident.json", json.dumps({"status": "open"}))
    put(shadow / "schedules" / "20260901_080000_feed_CAM" / "job.json")
    put(shadow / "log" / "20260901.jsonl")
    put(shadow / "log" / "20261025.jsonl")
    put(rt / "quality" / "20260901.jsonl")
    put(work / ".jobs" / "20260901_101010_1_shadow.log")
    put(work / "sessions" / "20260901_090000" / "session.json")                 # a recording: never
    put(shadow / "actions" / "notes.txt")                                          # no date: never
    today = datetime.date(2026, 10, 26)
    assert retention.clean(str(shadow), str(rt), str(work), 0, today)["files"] == 0                # 0 = keep all
    gone = retention.clean(str(shadow), str(rt), str(work), 30, today)
    assert gone["files"] == 6
    left = sorted(str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file())
    assert left == ["rt/cleanup_log.jsonl", "work/sessions/20260901_090000/session.json", "work/shadow/actions/20261020/2_CAM.jpg",
                    "work/shadow/actions/notes.txt", "work/shadow/incidents/20260902_120000_CAM/incident.json",
                    "work/shadow/log/20261025.jsonl"]


def test_storage_says_what_each_kind_takes_and_how_long_the_disk_lasts(tmp_path):
    import datetime
    from server import storage
    work, rt = tmp_path / "work", tmp_path / "rt"
    today = datetime.date(2026, 10, 26)

    def put(path, n):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * n)
    for k in range(1, 8):                                                   # a week: 1000 bytes of recording a day
        day = (today - datetime.timedelta(days=k)).strftime("%Y%m%d")
        put(work / "sessions" / f"{day}_090000" / "devices" / "CAM" / "frames" / "1.png", 1000)
        put(work / "shadow" / "actions" / day / "1_CAM.jpg", 100)
    put(work / "models" / "run1" / "model.onnx", 5000)
    put(work / "testset" / "testset.jsonl", 70)
    put(rt / "status.json", 30)
    s = storage.measure(str(work), str(rt), keep_days=30, today=today)
    assert s["sizes"] == {"recordings": 7000, "records": 700, "models": 5000, "answers": 70, "other": 30}
    assert s["per_day"] == {"recordings": 1000, "records": 100}
    assert s["growing"] == 1100                                               # the records are not 30 days old yet
    assert storage.measure(str(work), str(rt), keep_days=7, today=today)["growing"] == 1000   # kept 7 days: full


# ---------------------------------------------------------------- an incident's clip

def test_an_incident_keeps_a_clip_from_before_the_trigger_to_after_it(tmp_path):
    import time as _t
    import numpy as np
    from runtime import incidents as inc_mod
    inc = inc_mod.Incidents()
    frame = lambda k: np.full((720, 1280, 3), k % 255, np.uint8)
    urgent = [{"urgent": True, "rule": "fox", "rule_name": "Fox", "script": "farm", "script_name": "Farm", "action": "run",
               "text": "alarm", "reason": "fox = yes", "mode": "live"}]
    for k in range(40):                                                    # 20 s before, a frame every half second
        inc.keep("CAM", frame(k), 1000.0 + k * 0.5)
    assert len(inc.pre["CAM"]) == inc_mod.PRE_S + 1                         # the last 15 s, a frame a second
    assert inc.pre["CAM"][0][1].shape == (360, 640, 3)
    inc.begin(str(tmp_path), "CAM", 1020.0, {}, urgent, frame(40))
    for k in range(1, 60):                                                 # a minute after, still matching
        now = 1020.0 + k
        inc.keep("CAM", frame(40 + k), now)
        inc.tick("CAM", now, {}, urgent, frame(40 + k))
    _t.sleep(0.5)                                                          # the seconds before are written in the background
    i = inc.open["CAM"]
    times = [t for t, _n in i["clip"]]
    assert times[0] <= 1020.0 - inc_mod.PRE_S + 1 and 1020.0 + inc_mod.CLIP_AFTER - 1 <= times[-1] <= 1020.0 + inc_mod.CLIP_AFTER
    assert times == sorted(times)
    files = sorted(p.name for p in (tmp_path / i["id"] / "clip").iterdir())
    assert files == sorted(n for _t2, n in i["clip"])


def test_an_incident_becomes_a_recording_and_its_test_names_the_rule(tmp_path, monkeypatch):
    from automation import tests as tm
    names = types.SimpleNamespace(scripts={"pond": {"name": "Pond keeper", "situations": [{"id": "w", "rules": [{"id": "fish", "name": "Fish up"}]}]}},
                                  subs={})
    assert tm.Names.sub(types.SimpleNamespace(**names.__dict__, script=lambda s: tm.Names.script(names, s),
                                              rule=lambda s, r: tm.Names.rule(names, s, r)), "~pond.fish") == "Pond keeper:Fish up"
    ticks = [{"situation_ids": {}, "data": [{"kind": "call", "sub": "~pond.fish"}, {"kind": "output", "output": "pond"}], "events": []}]
    exp = tm.suggest({"ticks": ticks}, names)
    assert {"kind": "call", "sub": "~pond.fish", "when": "ever"} in exp and {"kind": "output", "output": "pond", "when": "ever"} in exp


def test_an_incident_clip_is_kept_as_a_recording(monkeypatch):
    import numpy as np
    from PIL import Image
    from fastapi.testclient import TestClient
    import server.app as app
    iid = "20261026_120000_CAM"
    d = os.path.join(app.SHADOW_DIR, "incidents", iid)
    os.makedirs(os.path.join(d, "clip"), exist_ok=True)
    clip = []
    for k in range(5):
        name = f"{1000 + k}000.jpg"
        Image.fromarray(np.full((36, 64, 3), k * 40, np.uint8)).save(os.path.join(d, "clip", name))
        clip.append([1000.0 + k, name])
    with open(os.path.join(d, "incident.json"), "w", encoding="utf-8") as f:
        json.dump({"id": iid, "device": "CAM", "start": 1002.0, "status": "resolved", "clip": clip}, f)
    c = TestClient(app.app, client=("127.0.0.1", 50000))
    assert c.post(f"/api/incidents/{iid}/recording").status_code == 403         # a runtime does not make tests
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")
    r = c.post(f"/api/incidents/{iid}/recording").json()
    assert (r["session"], r["device"], r["start"]) == (iid, "CAM", 0) and 0 < r["minutes"] <= 0.1
    frames = app._all_frames()[(iid, "CAM")]
    assert len(frames) == 5
    assert c.post(f"/api/incidents/{iid}/recording").json() == r                     # again: the same recording


# ---------------------------------------------------------------- moving the work folder

def test_the_work_folder_moves_checked_and_resumes_and_the_old_copy_goes_on_purpose(tmp_path, monkeypatch):
    from project import relocate
    old, new = tmp_path / "old", tmp_path / "new"
    monkeypatch.setattr(relocate, "STATE", str(tmp_path / "relocate.json"))
    monkeypatch.setattr(relocate, "current", lambda: str(old))
    machine = {}
    monkeypatch.setattr(project, "set_machine", lambda **v: machine.update(v))
    for k in range(20):
        f = old / "pond" / "sessions" / f"s{k % 2}" / f"{k}.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(os.urandom(100 + k))
    assert "完整" in relocate.check("relative")["problems"][0]
    assert relocate.check(str(old / "pond"))["problems"]                              # inside the old one
    (new / "x").mkdir(parents=True)
    assert relocate.check(str(new))["problems"]                                        # not empty
    (new / "x").rmdir()
    relocate.move(str(new))                                                            # (a half-done copy goes on: skipped)
    assert machine == {"work": str(new)} and relocate.state()["phase"] == "done"
    assert sorted(p.name for p in new.rglob("*.png")) == sorted(p.name for p in old.rglob("*.png"))
    monkeypatch.setattr(relocate, "current", lambda: str(new))
    relocate.delete_old()
    assert not old.exists() and relocate.state()["phase"] == "deleted"


def test_recordings_keep_their_frames_as_this_computer_says(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    from fastapi.testclient import TestClient
    import server.app as app
    from collector import collector as col
    from collector.config import Settings
    c = TestClient(app.app, client=("127.0.0.1", 50000))
    first = c.get("/api/storage/settings").json()
    assert (first["record_format"], first["jpeg_quality"]) == ("png", 90)
    assert c.post("/api/storage/settings", json={"record_format": "gif"}).status_code == 400
    assert c.post("/api/storage/settings", json={"record_format": "jpg", "jpeg_quality": 85}).json()["record_format"] == "jpg"
    assert (app._storage_settings()["record_format"], app._storage_settings()["jpeg_quality"]) == ("jpg", 85)
    c.post("/api/storage/settings", json={"record_format": "png"})
    img = np.random.default_rng(1).integers(0, 255, (72, 128, 3), dtype=np.uint8)
    for ext in ("png", "jpg"):
        p = str(tmp_path / f"f.{ext}")
        col._write_frame(p, img, Settings(frame_format=ext, jpeg_quality=80))
        assert Image.open(p).format == {"png": "PNG", "jpg": "JPEG"}[ext]


def test_each_kind_of_record_has_its_own_days_and_every_cleaning_is_written_down(tmp_path):
    import datetime
    from project import space
    from runtime import retention
    shadow, rt, work = tmp_path / "work" / "shadow", tmp_path / "rt", tmp_path / "work"
    for p in (shadow / "actions" / "20260901" / "a.jpg", shadow / "incidents" / "20260901_1_CAM" / "incident.json",
              shadow / "log" / "20260901.jsonl"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    rt.mkdir()
    (rt / "control.json").write_text(json.dumps({"keep_days": 40}), encoding="utf-8")   # the older single number
    assert space.load(str(rt))["keep"] == {"actions": 40, "incidents": 90, "schedules": 40, "logs": 40}
    keep = {"actions": 30, "incidents": 90, "schedules": 30, "logs": 0}
    today = datetime.date(2026, 10, 26)
    dry = retention.clean(str(shadow), str(rt), str(work), keep, today, dry=True)
    assert set(dry["kinds"]) == {"actions"} and (shadow / "actions" / "20260901").exists()   # only said
    gone = retention.clean(str(shadow), str(rt), str(work), keep, today, by="user")
    assert gone["files"] == 1 and not (shadow / "actions" / "20260901").exists()
    assert (shadow / "incidents" / "20260901_1_CAM").exists() and (shadow / "log" / "20260901.jsonl").exists()
    h = retention.history(str(rt))
    assert h[0]["by"] == "user" and h[0]["files"] == 1


def test_making_room_deletes_the_oldest_recordings_nothing_needs(tmp_path, monkeypatch):
    from project import space
    work, design, rt = tmp_path / "work", tmp_path / "design", tmp_path / "rt"
    for sid in ("20260901_1", "20260902_1", "20260903_1", "20260904_1", "shadow_20260905"):
        (work / "sessions" / sid / "devices" / "CAM").mkdir(parents=True)
        (work / "sessions" / sid / "devices" / "CAM" / "f.png").write_bytes(b"x" * 100)
    (work / "testset").mkdir()
    (work / "testset" / "testset.jsonl").write_text(json.dumps({"session": "20260901_1", "frame": "x"}) + "\n", encoding="utf-8")
    (design / "meta").mkdir(parents=True)
    (design / "meta" / "tests.json").write_text(json.dumps({"tests": [{"session": "20260902_1"}]}), encoding="utf-8")
    deleted = []
    monkeypatch.setattr(space, "free", lambda folder: 2 ** 30 * (5 + 10 * len(deleted)))   # each one deleted frees 10 GB
    real = space.shutil.rmtree
    monkeypatch.setattr(space.shutil, "rmtree", lambda p, **k: (deleted.append(os.path.basename(p)), real(p, **k)))
    out = space.make_room(str(work), str(design), str(rt), {"min_free_gb": 12}, current="20260904_1")
    assert out["sessions"] == ["20260903_1"] and out["ok"]                 # answered, tested and the current one stay
    assert sorted(os.listdir(work / "sessions")) == ["20260901_1", "20260902_1", "20260904_1", "shadow_20260905"]


def test_training_skips_the_labels_of_a_recording_deleted_since(tmp_path, monkeypatch):
    from trainer import data as tdata
    work = tmp_path / "w"
    (work / "sessions" / "kept").mkdir(parents=True)
    labels = [{"frame": str(work / "sessions" / s / "devices" / "CAM" / "frames" / "1.png"), "session": s, "device": "CAM", "id": "1", "t": 1.0}
              for s in ("kept", "deleted")]
    monkeypatch.setattr(tdata, "latest_labels", lambda root: ("v1", labels))
    monkeypatch.setattr(tdata, "test_answers", lambda root: {})
    monkeypatch.setattr(tdata.project, "work_of", lambda root: str(work))
    monkeypatch.setattr(tdata.schema_mod, "load", lambda root: {"version": 1, "states": []})
    ds = tdata.build(str(tmp_path / "design"))
    assert {i["session"] for i in ds["items"]} == {"kept"}


def test_only_the_newest_training_runs_stay_and_the_one_in_use_always(tmp_path):
    from project import space
    for r in ("20261001_a", "20261002_b", "20261003_c", "20261004_d", "20261005_e"):
        (tmp_path / r).mkdir()
        (tmp_path / r / "model.onnx").write_bytes(b"x" * 10)
    assert space.old_models(str(tmp_path), 0) == []                                   # 0 = keep every run
    assert [r for r, _b in space.old_models(str(tmp_path), 2)] == ["20261003_c", "20261002_b", "20261001_a"]
    assert [r for r, _b in space.old_models(str(tmp_path), 2, {"20261002_b"})] == ["20261003_c", "20261001_a"]   # in use
