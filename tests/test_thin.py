"""Thinning the recordings (project/thin.py): what looks the same and got the same labels goes; what a person
answered, a test replays or is still being recorded stays."""
import json
import os

import numpy as np
import pytest
from PIL import Image

import project
from project import thin


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "w"
    monkeypatch.setattr(project, "work_of", lambda root: str(w))
    return w


def record(work, session, device, frames, labels, ended=True, old=True):
    """frames: [(id, grey level, labels dict, auto)]"""
    d = work / "sessions" / session / "devices" / device
    (d / "frames").mkdir(parents=True)
    with open(d / "samples.jsonl", "w", encoding="utf-8") as f:
        for i, grey, lb, auto in frames:
            img = np.full((54, 96, 3), grey, np.uint8)
            Image.fromarray(img).resize((192, 108)).save(d / "frames" / f"{i}.png")
            f.write(json.dumps({"id": str(i), "t_req": i / 1000, "frame": f"frames/{i}.png"}) + "\n")
            labels.append({"frame": str(d / "frames" / f"{i}.png"), "session": session, "device": device, "id": str(i),
                           "t": i / 1000, "auto": auto, **lb})
    (work / "sessions" / session / "session.json").write_text(json.dumps({"session": session, **({"ended": 1} if ended else {})}))
    if old:
        os.utime(d / "samples.jsonl", (1, 1))


def labelled(work, labels):
    (work / "labels" / "v1").mkdir(parents=True)
    with open(work / "labels" / "v1" / "labels.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in labels)


def test_a_frame_that_adds_nothing_is_thinned_and_what_must_stay_stays(work, tmp_path):
    hunt, town = {"zone": "field", "hp_ratio": 0.8}, {"zone": "town", "hp_ratio": 0.8}
    labels = []
    record(work, "s1", "A", [(1000, 100, hunt, 1), (2000, 101, hunt, 1),       # the same: goes
                             (3000, 100, town, 1),                              # other labels: stays
                             (4000, 200, town, 1),                              # looks different: stays
                             (9000, 200, town, 0),                              # a person labelled it: stays
                             (100000, 200, town, 1)], labels)                   # more than GAP later: stays
    record(work, "s2", "A", [(1000, 100, hunt, 1), (2000, 100, hunt, 1)], labels)   # a script test replays it
    record(work, "s3", "A", [(1000, 100, hunt, 1), (2000, 100, hunt, 1)], labels, ended=False)   # still recording
    labelled(work, labels)
    design = tmp_path / "design"
    (design / "meta").mkdir(parents=True)
    (design / "meta" / "tests.json").write_text(json.dumps({"tests": [{"session": "s2", "device": "A"}]}))

    p = thin.plan(str(design), workers=1)
    assert p["drop_frames"] == 1 and p["frames"] == 8
    assert p["samples"] == [{"frame": "sessions/s1/devices/A/frames/2000.png", "like": "sessions/s1/devices/A/frames/1000.png"}]

    runtime = tmp_path / "run"
    got = thin.apply(str(design), str(runtime))
    d = work / "sessions" / "s1" / "devices" / "A"
    assert got["files"] == 1 and not (d / "frames" / "2000.png").exists() and (d / "frames" / "1000.png").exists()
    ids = [json.loads(line)["id"] for line in open(d / "samples.jsonl", encoding="utf-8")]
    assert ids == ["1000", "3000", "4000", "9000", "100000"]
    assert [json.loads(line)["id"] for line in open(d / "thinned.jsonl", encoding="utf-8")] == ["2000"]
    assert os.path.getmtime(d / "samples.jsonl") == 1                                # the labels are not out of date
    assert json.loads((runtime / "cleanup_log.jsonl").read_text().splitlines()[-1])["what"] == "thinned"
    assert thin.summary(str(design)) is None                                         # the plan is used up


def test_a_frame_answered_after_the_plan_is_not_deleted(work, tmp_path):
    hunt = {"zone": "field"}
    labels = []
    record(work, "s1", "A", [(1000, 100, hunt, 1), (2000, 100, hunt, 1)], labels)
    labelled(work, labels)
    thin.plan(str(tmp_path), workers=1)
    (work / "testset").mkdir()
    (work / "testset" / "testset.jsonl").write_text(json.dumps({"frame": "sessions/s1/devices/A/frames/2000.png"}) + "\n")
    assert thin.apply(str(tmp_path), str(tmp_path / "run"))["files"] == 0
    assert (work / "sessions" / "s1" / "devices" / "A" / "frames" / "2000.png").exists()
