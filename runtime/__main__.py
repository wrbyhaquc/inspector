import argparse
import os

from . import judge
from .shadow import Shadow, latest_model
from i18n import _


def main():
    ap = argparse.ArgumentParser(prog="python -m runtime", description=_("腳本執行:用模型看畫面,依腳本決定要做什麼(試跑只記錄,正式執行的會動作;停下來 / 暫停的不會)"))
    ap.add_argument("--data", default=__import__("project").data_root())
    ap.add_argument("--run", default="", help=_("訓練編號(預設用最新一次完成的訓練)"))
    ap.add_argument("--interval", type=float, default=1.0, help=_("每幾秒看一次"))
    ap.add_argument("--fast-dir", default=__import__("project").runtime_dir(),
                    help=_("每秒都會重寫的檔案(即時預覽、狀態、控制)放的位置,建議 SSD"))
    a = ap.parse_args()
    from project import runtime_data
    try:
        runtime_data.ensure(a.fast_dir)
    except runtime_data.RuntimeTooNew as e:
        raise SystemExit(str(e))
    ckpt = judge.model_file(os.path.join(__import__("project").models_of(a.data), a.run)) if a.run else latest_model(a.data)
    if a.run and not ckpt:
        raise SystemExit(_("訓練結果 {run} 沒有模型", run=a.run))
    Shadow(a.data, ckpt, a.interval, a.fast_dir).run()


if __name__ == "__main__":
    main()
