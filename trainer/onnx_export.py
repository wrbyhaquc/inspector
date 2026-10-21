"""Export a trained model to ONNX, so the runtime can run it without PyTorch (onnxruntime).

Writes next to the checkpoint:
  model.onnx   input "frames": float32 N x 3 x H x W in [0, 255] (RGB, resized to the training size); one output
               per head, in the order of model.json: class heads -> logits N x classes, ratio heads -> N values in [0, 1]
  model.json   {"format": 1, "size", "heads", "schema_version", "backbone", "checkpoint"} (readable without torch)

    python -m trainer.onnx_export <training run folder or model_best.pt> [--all]"""
import argparse
import glob
import json
import os

import numpy as np
from i18n import _

OPSET = 17


def export(ckpt, check=True):
    import torch
    from .model import load
    run = os.path.dirname(ckpt)
    model, ck = load(ckpt, "cpu")
    heads, size = ck["heads"], tuple(ck["size"])

    class Flat(torch.nn.Module):                      # dict outputs -> a tuple in head order
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            out = self.m(x)
            return tuple(out[h["id"]] for h in heads)

    flat = Flat(model).eval()
    dummy = torch.zeros(1, 3, size[1], size[0])
    names = [h["id"] for h in heads]
    path = os.path.join(run, "model.onnx")
    torch.onnx.export(flat, dummy, path + ".tmp", input_names=["frames"], output_names=names, opset_version=OPSET,
                      dynamic_axes={"frames": {0: "n"}, **{n: {0: "n"} for n in names}}, dynamo=False)
    os.replace(path + ".tmp", path)
    meta = {"format": 1, "size": list(size), "heads": heads, "schema_version": ck.get("schema_version"),
            "backbone": ck.get("backbone", "resnet18"), "checkpoint": os.path.basename(ckpt), "opset": OPSET}
    with open(os.path.join(run, "model.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    diff = None
    if check:                                         # the same frames through both: the answers must match
        import onnxruntime as ort
        x = np.random.default_rng(0).integers(0, 256, (2, 3, size[1], size[0])).astype(np.float32)
        with torch.no_grad():
            ref = flat(torch.from_numpy(x))
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        got = sess.run(None, {"frames": x})
        diff = max(float(np.abs(r.numpy() - g).max()) for r, g in zip(ref, got))
    return path, diff


def main():
    ap = argparse.ArgumentParser(prog="python -m trainer.onnx_export", description=_("把訓練好的模型轉成 ONNX(執行端不需要 PyTorch)"))
    ap.add_argument("target", nargs="?", help=_("訓練結果資料夾或 model_best.pt"))
    ap.add_argument("--all", action="store_true", help=_("專案裡所有還沒有 ONNX 的訓練結果"))
    a = ap.parse_args()
    if a.all:
        import project
        todo = [p for p in sorted(glob.glob(os.path.join(project.work_root(), "models", "*", "model_best.pt")))
                if not os.path.exists(os.path.join(os.path.dirname(p), "model.onnx"))]
    elif a.target:
        todo = [a.target if a.target.endswith(".pt") else os.path.join(a.target, "model_best.pt")]
    else:
        ap.error(_("請指定訓練結果,或用 --all"))
    for ck in todo:
        path, diff = export(ck)
        print(_("{path}  (和 PyTorch 的最大差異 {diff})", path=path, diff=format(diff, '.2e')), flush=True)


if __name__ == "__main__":
    main()
