"""Every text in the code has a translation in every language, and every text written out can be read by the tools."""
import json
import os

import pytest

from tools import i18n as tool

LANGS = ["en", "ja", "ko", "zh-CN"]


@pytest.mark.parametrize("side", list(tool.SIDES))
def test_every_text_can_be_read(side):
    _found, bad = tool.texts(side)
    assert bad == [], "write the text out in t() / _() (not a variable or a template): " + ", ".join(bad[:5])


@pytest.mark.parametrize("side", list(tool.SIDES))
@pytest.mark.parametrize("lang", LANGS)
def test_every_text_is_translated(side, lang):
    found, _bad = tool.texts(side)
    with open(os.path.join(tool.ROOT, tool.SIDES[side]["locales"], f"{lang}.json"), encoding="utf-8") as f:
        cat = json.load(f)
    missing = [k for k in found if not cat.get(k)]
    assert missing == [], f"{side} {lang} lacks {len(missing)}: {missing[:5]} (python -m tools.i18n check)"
