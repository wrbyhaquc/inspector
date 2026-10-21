import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback

from . import data
from .train import Run
from i18n import _


def relabel_if_stale(data_root, run):
    """Run the labeler first when the labels are older than the data / definitions they come from."""
    st = data.labels_status(data_root)
    if not st["stale"]:
        print(_("標籤 {version} 是最新的,直接訓練", version=st['version']), flush=True)
        return
    reason = _(";").join(st["reasons"])
    print(_("標籤不是最新的:") + reason + _("。先產生標籤…"), flush=True)
    run.progress("labels", message=reason)
    p = subprocess.Popen([sys.executable, "-u", "-m", "labeler", "--data", data_root], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    t0 = time.time()
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        print(line, flush=True)
        m = re.match(r"\s*(\d+)/(\d+)$", line)             # the labeler prints "  500/2000" while computing rules
        if m:
            d, t = int(m.group(1)), int(m.group(2))
            run.progress("labels", d, t, rate=d / max(1e-6, time.time() - t0), message=reason)
    if p.wait() != 0:
        raise RuntimeError(_("產生標籤失敗,訓練取消"))
    print(_("標籤更新完成,開始訓練"), flush=True)


def main():
    ap = argparse.ArgumentParser(description=_("訓練多頭畫面模型"))
    ap.add_argument("--data", default=__import__("project").data_root())
    ap.add_argument("--config-json", default="{}", help=_("設定,例如 {\"epochs\": 20, \"pretrained\": true}"))
    args = ap.parse_args()
    cfg = json.loads(args.config_json)
    relabel = cfg.pop("relabel", True)
    run = Run(args.data, cfg)
    print(_("訓練編號 {id}", id=run.id), flush=True)
    try:
        if relabel:
            relabel_if_stale(args.data, run)
        run.train()
    except Exception as e:
        traceback.print_exc()
        run.status(state="failed", message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
