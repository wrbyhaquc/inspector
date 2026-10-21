import argparse
import json
import os

from . import LABELER_VERSION
from .build import Builder
from i18n import _


def main():
    ap = argparse.ArgumentParser(prog="python -m labeler", description=_("從收集的資料產生訓練標籤"))
    ap.add_argument("--data", default=__import__("project").data_root(), help=_("專案資料夾(預設 %(default)s)"))
    ap.add_argument("--out", default=None, help=_("輸出目錄(預設 <data>\\labels\\v{LABELER_VERSION})", LABELER_VERSION=LABELER_VERSION))
    ap.add_argument("--session", action="append", default=[], help=_("只處理指定場次,可重複"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = ap.parse_args()
    out = a.out or os.path.join(__import__("project").work_of(a.data), "labels", f"v{LABELER_VERSION}")
    summary = Builder(a.data, out, a.workers, a.session or None).run()
    t = summary["total"]
    print(_("\n完成,輸出在 {out}", out=out))
    print(_("  畫面 {frames} 張", frames=t.get('frames', 0)))
    per_state = {}
    for k, v in t.items():
        if "=" in k and not k.startswith("flag:"):
            sid, val = k.split("=", 1)
            per_state.setdefault(sid, {})[val] = v
    for sid, vals in per_state.items():
        print(f"  {sid}:{json.dumps(vals, ensure_ascii=False)}")
    others = {k: v for k, v in t.items() if "=" not in k and not k.startswith("flag:") and k != "frames"}
    if others:
        print(_("  其他:{p1}", p1=json.dumps(others, ensure_ascii=False)))
    flags = {k[5:]: v for k, v in t.items() if k.startswith("flag:")}
    print(_("  旗標:{p1}", p1=json.dumps(flags, ensure_ascii=False)))


if __name__ == "__main__":
    main()
