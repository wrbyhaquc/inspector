"""Generic screen rules on pictures drawn here: colour ratio, bar, reference pictures, read digits, gates."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from labeler import generic

W, H = 320, 120
RED = [{"h": [245, 10], "s": [150, 255], "v": [150, 255]}]


def state(rule, params, typ="class", classes=("yes", "no"), box=(0, 0, W, H), **kw):
    s = {"id": "s", "type": typ, "rois": [{"id": "r", "box": list(box)}],
         "source": {"kind": "rule", "rule": rule, "params": {"roi": "r", **params}}, **kw}
    if typ == "class":
        s["classes"] = [{"value": c} for c in classes]
    return s


def picture(draw=None, bg=(20, 20, 24)):
    im = Image.new("RGB", (W, H), bg)
    if draw:
        draw(ImageDraw.Draw(im))
    return np.asarray(im)


# ---------------------------------------------------------------- colour ratio
def test_color_ratio_high_low_and_between():
    s = state("color_ratio", {"colors": RED, "high_value": "yes", "high_min": 0.2, "low_value": "no", "low_max": 0.05})
    assert generic.evaluate(s, picture(lambda d: d.rectangle((0, 0, 159, H), fill=(230, 30, 30))))[0] == "yes"
    assert generic.evaluate(s, picture())[0] == "no"
    assert generic.evaluate(s, picture(lambda d: d.rectangle((0, 0, 31, H), fill=(230, 30, 30))))[0] is None   # 10%


def test_a_gated_state_is_hidden_when_its_gate_is():
    s = state("color_ratio", {"colors": RED, "high_value": "yes", "high_min": 0.2, "low_value": "no", "low_max": 0.05,
                              "gate_state": "g"}, classes=("yes", "no", "hidden"))
    img = picture(lambda d: d.rectangle((0, 0, 159, H), fill=(230, 30, 30)))
    assert generic.evaluate(s, img, context={"g": "hidden"})[0] == "hidden"
    assert generic.evaluate(s, img, context={"g": None})[0] == "hidden"
    assert generic.evaluate(s, img, context={"g": "yes"})[0] == "yes"


# ---------------------------------------------------------------- bar
@pytest.mark.parametrize("level", [0.25, 0.6, 0.9])
def test_bar_reads_how_full(level):
    s = state("bar", {"dir": "right", "fill": "auto"}, typ="ratio", box=(20, 50, 280, 20))
    img = picture(lambda d: (d.rectangle((20, 50, 299, 69), fill=(60, 60, 66)),
                             d.rectangle((20, 50, 20 + int(280 * level) - 1, 69), fill=(40, 120, 230))))
    v, _info = generic.evaluate(s, img)
    assert v == pytest.approx(level, abs=0.03)


# ---------------------------------------------------------------- reference pictures
def test_template_picks_the_closest_reference(tmp_path):
    box = (40, 30, 120, 60)
    on = picture(lambda d: (d.rounded_rectangle((40, 30, 159, 89), 12, fill=(40, 160, 80)), d.ellipse((120, 45, 150, 75), fill=(255, 255, 255))))
    off = picture(lambda d: (d.rounded_rectangle((40, 30, 159, 89), 12, fill=(90, 90, 90)), d.ellipse((50, 45, 80, 75), fill=(255, 255, 255))))
    s = state("template", {"search": 3, "match_min": 0.6, "margin": 0.05}, classes=("on", "off"), box=box)
    generic.tpl_add(str(tmp_path), "s", "on", on, box, "a")
    generic.tpl_add(str(tmp_path), "s", "off", off, box, "b")
    tpls = generic.load_templates(str(tmp_path), s)
    assert len(tpls) == 2
    assert generic.evaluate(s, on, tpls)[0] == "on"
    assert generic.evaluate(s, off, tpls)[0] == "off"


def test_references_made_within_one_millisecond_are_all_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(generic.time, "time", lambda: 1000.0)
    box = (0, 0, 10, 10)
    a = generic.tpl_add(str(tmp_path), "s", "on", picture(), box, "a")
    b = generic.tpl_add(str(tmp_path), "s", "off", picture(), box, "b")
    c = generic.glyph_add(str(tmp_path), "s", "1", picture(), (0, 10, 0, 10), "c")
    assert len({a, b, c}) == 3 and len(generic.tpl_index(str(tmp_path), "s")) == 3


def test_template_falls_back_when_nothing_looks_alike(tmp_path):
    box = (40, 30, 120, 60)
    btn = picture(lambda d: (d.rounded_rectangle((40, 30, 159, 89), 12, fill=(40, 160, 80)), d.text((60, 50), "OK", fill=(255, 255, 255))))
    s = state("template", {"search": 3, "match_min": 0.75, "fallback": "none"}, classes=("button", "none"), box=box)
    generic.tpl_add(str(tmp_path), "s", "button", btn, box, "a")
    tpls = generic.load_templates(str(tmp_path), s)
    assert generic.evaluate(s, btn, tpls)[0] == "button"
    noise = (np.random.default_rng(1).random((H, W, 3)) * 255).astype(np.uint8)
    assert generic.evaluate(s, noise, tpls)[0] == "none"


# ---------------------------------------------------------------- read digits
def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    pytest.skip("no TrueType font on this machine")


def _digits(text, size=52, gap=5, speck=False):
    f = _font(size)
    im = Image.new("RGB", (W, H), (10, 10, 12))
    d = ImageDraw.Draw(im)
    x = 10
    for ch in text:                                   # one at a time: a gap between every two characters
        d.text((x, 20), ch, font=f, fill=(255, 55, 40))
        x += int(f.getlength(ch)) + gap
    if speck:
        d.rectangle((280, 30, 282, 32), fill=(255, 55, 40))
    return np.asarray(im)


@pytest.fixture(scope="module")
def refs():
    """The ten digits, taught once from one picture."""
    f = _font(52)
    im = Image.new("RGB", (700, H), (10, 10, 12))
    d = ImageDraw.Draw(im)
    x = 10
    for ch in "0123456789":
        d.text((x, 20), ch, font=f, fill=(255, 55, 40))
        x += int(f.getlength(ch)) + 9
    img = np.asarray(im)
    gs = generic.glyphs(img, (0, 0, 700, H), RED)
    assert len(gs) == 10
    out = []
    for (b, _m), ch in zip(gs, "0123456789"):
        rgb = generic._glyph_rgb(img, b)
        out.append((ch, generic._glyph_feat(rgb), rgb.shape[1] / max(1, rgb.shape[0])))
    return out


@pytest.mark.parametrize("text,value", [("42", 42), ("7", 7), ("10.2", 10.2), ("0.75", 0.75), ("-3.5", -3.5),
                                        ("-12", -12), ("1,250", 1250)])
def test_digits_read_points_minus_and_commas(refs, text, value):
    s = state("digits", {"colors": RED, "part": "all"}, typ="number")
    v, info = generic.eval_digits(s, _digits(text), refs)
    assert v == value, info


def test_digits_ignore_a_speck(refs):
    s = state("digits", {"colors": RED, "part": "all"}, typ="number")
    assert generic.eval_digits(s, _digits("42", speck=True), refs)[0] == 42


def test_digits_outside_the_states_range_are_undecided(refs):
    s = state("digits", {"colors": RED, "part": "all"}, typ="number", min=0, max=50)
    assert generic.eval_digits(s, _digits("75"), refs)[0] is None


def test_small_marks_by_place_and_shape():
    line = (20, 60)                                   # a 40 px line of text
    assert generic.small_char((10, 18, 52, 60), line) == "."
    assert generic.small_char((10, 18, 52, 68), line) == ","
    assert generic.small_char((10, 34, 38, 44), line) == "-"
    assert generic.small_char((10, 13, 22, 25), line) is None         # a speck near the top
    assert generic.small_char((10, 30, 20, 60), line) is None         # full height: a digit, not a mark


# ---------------------------------------------------------------- suggested thresholds (colour ratio)

def test_thresholds_are_suggested_in_the_empty_stretch_between_two_groups():
    import random
    from labeler.generic import suggest_ratio
    rnd = random.Random(3)
    no, yes = [rnd.uniform(0, 0.003) for _ in range(120)], [rnd.uniform(0.009, 0.03) for _ in range(15)]
    s = suggest_ratio(no + yes)
    assert s["basis"] == "gap" and 0.003 < s["low_max"] < s["high_min"] < 0.009
    assert (s["high"], s["low"], s["unsure"]) == (15, 120, 0)
    assert suggest_ratio(no)["none"] == "one_group"                                # nothing to split yet
    assert suggest_ratio([0.0, 0.5])["none"] == "few_frames"


def test_answers_decide_the_thresholds_and_none_of_them_comes_out_wrong():
    from labeler.generic import suggest_ratio
    answers = [(0.001, "low"), (0.002, "low"), (0.004, "low"), (0.003, "high"), (0.006, "high"), (0.008, "high")]
    s = suggest_ratio([r for r, _a in answers] * 3, answers)
    assert s["basis"] == "answers" and s["wrong"] == 0
    assert s["low_max"] < 0.003 and s["high_min"] > 0.004          # the two answers on each other's side: undecided
    assert s["unsure_answers"] == 2
