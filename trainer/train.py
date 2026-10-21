"""One training run -> <project>\\models\\<run id>\\

  config.json      the settings used (+ dataset summary)
  status.json      progress for the web page
  metrics.jsonl    one line per epoch: training loss, hold-out (val) and test-set scores per head
  model_best.pt    checkpoint with the best hold-out score (the test set is never used to choose)
  model_last.pt    checkpoint after the last epoch
  eval.json        final test-set report for model_best: per state accuracy vs the screen rules, confusion, mistakes
  predictions.jsonl  model_best's answers for every test frame"""
import collections
import datetime
import json
import math
import os
import random
import time
import warnings

import numpy as np
import torch
import torch.nn.functional as F

from . import TRAINER_VERSION, data, resize
from .model import ScreenModel
from i18n import N_, _
import project

# GradScaler skips the very first step (inf check), which makes the scheduler warn; harmless
warnings.filterwarnings("ignore", message=r"Detected call of `lr_scheduler.step\(\)` before")

DEFAULTS = {
    "name": "", "epochs": 20, "width": 640, "height": 360, "batch": 16, "lr": 1e-3, "weight_decay": 1e-4,
    "pretrained": False, "backbone": "resnet18", "holdout": [], "neighbor_seconds": 1.0,
    "augment": True, "seed": 0, "ratio_weight": 5.0, "warmup_epochs": 1,
}


def cache_dir(data_root, size):
    """Resized frames are cached per session/device, so new recordings only resize their own frames. Written once
    and read every epoch, so it belongs on a fast disk: INSPECTOR_TRAIN_CACHE, else inspector.json "train_cache",
    else <runtime folder>/train_cache."""
    import project
    root = os.environ.get("INSPECTOR_TRAIN_CACHE") or project.machine().get("train_cache") \
        or os.path.join(project.runtime_dir(), "train_cache")
    return os.path.join(root, f"{size[0]}x{size[1]}")


def _group(frame):
    p = frame.replace("\\", "/").split("/")          # sessions/<session>/devices/<device>/frames/<id>.png
    return f"{p[1]}__{p[3]}"



LABEL_SMOOTHING = 0.05


def smooth_ce(logits, y, w, eps=LABEL_SMOOTHING):
    """Cross entropy with class weights and label smoothing, the smoothing NOT weighted by class.
    F.cross_entropy(weight=, label_smoothing=) also weights the smoothing part per class: every frame of a common
    answer is pushed to keep a share for the rare one, the more the rarer it is - a "map closed" frame came out at
    0.63 with the model right every time (map open: 167 of 62 852 frames). Here a frame counts by its own answer's
    weight, and its smoothing is spread evenly: a clear frame of any answer reaches 1 - eps + eps / classes."""
    logp = F.log_softmax(logits, dim=1)
    nll = -logp.gather(1, y[:, None])[:, 0]
    loss = (1 - eps) * nll + eps * (-logp.mean(dim=1))
    wy = w[y]
    return (wy * loss).sum() / wy.sum().clamp(min=1e-8)

class FrameStore:
    """Frames of one split, read on demand from the memory-mapped cache files (on the SSD) instead of all held in RAM:
    50k frames at 640x360 are ~37 GB, more than the free memory while the emulators run.
    store[idx] (a list/tensor of positions) -> uint8 tensor len(idx) x H x W x 3; store.shape like an array."""

    def __init__(self, arrays, grp, row):
        self.arrays, self.grp, self.row = arrays, np.asarray(grp, np.int64), np.asarray(row, np.int64)
        self.shape = (len(self.grp),) + (arrays[0].shape[1:] if arrays else (0, 0, 3))

    def __len__(self):
        return len(self.grp)

    def slice(self, a, b):
        return FrameStore(self.arrays, self.grp[a:b], self.row[a:b])

    def __getitem__(self, idx):
        idx = idx.numpy() if isinstance(idx, torch.Tensor) else np.asarray(idx)
        out = np.empty((len(idx),) + self.shape[1:], np.uint8)
        for k, (g, r) in enumerate(zip(self.grp[idx], self.row[idx])):
            out[k] = self.arrays[g][r]
        return torch.from_numpy(out)


def _append_cache(cdir, g, index, items, w, h):
    """Add newly resized frames to one session/device's cache file (written next to it, then swapped in)."""
    ap, ip = os.path.join(cdir, g + ".npy"), os.path.join(cdir, g + ".json")
    old = np.load(ap) if index[g] else np.empty((0, h, w, 3), np.uint8)
    arr = np.concatenate([old, np.stack([a for _x, a in items])])
    del old
    np.save(ap + ".tmp.npy", arr)
    os.replace(ap + ".tmp.npy", ap)
    for f, _x in items:
        index[g][f] = len(index[g])
    with open(ip + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(index[g], fh)
    os.replace(ip + ".tmp", ip)


def load_images(data_root, frames, size, log, progress=None):
    """All frames resized to size, as a FrameStore in the order of `frames`. New frames are resized and added to the
    cache one session/device at a time, so a stopped run keeps what it already did and memory stays small."""
    w, h = size
    cdir = cache_dir(data_root, size)
    os.makedirs(cdir, exist_ok=True)
    groups = collections.defaultdict(list)
    for f in frames:
        groups[_group(f)].append(f)
    index = {}
    todo = []
    for g, fs in groups.items():
        ip, ap = os.path.join(cdir, g + ".json"), os.path.join(cdir, g + ".npy")
        idx = json.load(open(ip, encoding="utf-8")) if os.path.exists(ip) and os.path.exists(ap) else {}
        index[g] = idx
        todo += [f for f in fs if f not in idx]
    if todo:
        log(_("縮小 {p1} 張新畫面到 {w}x{h}(已快取 {p4} 張)…", p1=len(todo), w=w, h=h, p4=len(frames) - len(todo)))
        done = 0
        todo.sort()                                   # one reader in file order: a hard disk hates parallel readers
        cur, items = None, []                         # sorted -> each session/device comes in one stretch
        for i, a in resize.shrink_all([project.resolve(f, data_root) for f in todo], w, h):
            f = todo[i]
            if _group(f) != cur and items:
                _append_cache(cdir, cur, index, items, w, h)
                items = []
            cur = _group(f)
            items.append((f, a))
            done += 1
            if done % 2000 == 0:
                log(f"  {done}/{len(todo)}")
            if progress and done % 100 == 0:
                progress(done, len(todo))
        if items:
            _append_cache(cdir, cur, index, items, w, h)
    else:
        log(_("影像快取:{p1} 張都已快取", p1=len(frames)))
    names = sorted(groups)
    arrays = [np.load(os.path.join(cdir, g + ".npy"), mmap_mode="r") for g in names]
    gi = {g: k for k, g in enumerate(names)}
    return FrameStore(arrays, [gi[_group(f)] for f in frames], [index[_group(f)][f] for f in frames])


class Run:
    def __init__(self, data_root, cfg):
        self.data_root = data_root
        self.cfg = {**DEFAULTS, **cfg}
        c = self.cfg
        stamp = f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
        safe = "".join(ch for ch in c["name"] if ch.isalnum() or ch in "-_")[:40]
        self.id = f"{stamp}_{safe}" if safe else stamp
        self.dir = os.path.join(project.work_of(data_root), "models", self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.size = (int(c["width"]), int(c["height"]))
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.t0 = time.time()

    # ---------- bookkeeping ----------
    def log(self, msg):
        print(msg, flush=True)

    PHASES = {"labels": N_("更新標籤"), "cache": N_("縮小畫面"), "train": N_("訓練"), "val": N_("保留裝置評分"), "test": N_("測試集評分"),
              "report": N_("最終報告")}

    def progress(self, phase, done=None, total=None, rate=None, **kw):
        """Status with what is happening now, how far it is, and estimated time left (this step and whole run)."""
        now = time.time()
        if phase != getattr(self, "_phase", None):
            self._phase, self._phase_t0 = phase, now
        eta = None
        if rate and done is not None and total:
            eta = (total - done) / rate
        state = {"labels": "loading", "cache": "loading", "train": "training"}.get(phase, "evaluating")
        self.status(state=state, phase=phase, phase_name=_(self.PHASES.get(phase, phase)), done=done, total=total,
                    img_per_s=round(rate, 1) if rate else None, eta_phase=round(eta) if eta is not None else None,
                    eta_total=self._eta_total(phase, done or 0), **kw)

    def _eta_total(self, phase, done):
        """Seconds left for the whole run, from the measured training and scoring speeds."""
        rt, re_ = getattr(self, "rate_train", None), getattr(self, "rate_eval", None)
        if not rt or not hasattr(self, "n_train"):
            return None
        re_ = re_ or rt * 3                       # scoring is roughly 3x faster than training until measured
        ep = getattr(self, "cur_epoch", 1)
        epochs = self.cfg["epochs"]
        n_eval = self.n_val + self.n_test
        if phase == "train":
            left_train, left_eval = (epochs - ep + 1) * self.n_train - done, (epochs - ep + 1) * n_eval + self.n_test
        elif phase == "val":
            left_train, left_eval = (epochs - ep) * self.n_train, (epochs - ep + 1) * n_eval - done + self.n_test
        elif phase == "test":
            left_train, left_eval = (epochs - ep) * self.n_train, (epochs - ep) * n_eval + self.n_test * 2 - done
        elif phase == "report":
            left_train, left_eval = 0, self.n_test - done
        else:
            return None
        return round(left_train / rt + left_eval / re_)

    def status(self, **kw):
        s = {"id": self.id, "updated": time.time(), "started": self.t0, "trainer_version": TRAINER_VERSION, **kw}
        # best effort: the web page may be reading the file at this moment (Windows then refuses the replace);
        # a missed progress update must never stop the training
        tmp = os.path.join(self.dir, "status.json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False)
            for attempt in range(5):
                try:
                    os.replace(tmp, os.path.join(self.dir, "status.json"))
                    return
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))
        except OSError:
            pass

    def _json(self, name, obj):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)

    # ---------- data ----------
    def prepare(self):
        c = self.cfg
        random.seed(c["seed"]); np.random.seed(c["seed"]); torch.manual_seed(c["seed"])
        data.NEIGHBOR_SECONDS = float(c["neighbor_seconds"])
        ds = data.build(self.data_root, c["holdout"])
        self.heads = ds["heads"]
        summ = data.summary(ds)
        self._json("config.json", {"id": self.id, "config": c, "created": self.t0, "trainer_version": TRAINER_VERSION,
                                   "device": torch.cuda.get_device_name(0) if self.dev == "cuda" else "cpu",
                                   "dataset": summ, "heads": self.heads})
        self.splits = {sp: [i for i in ds["items"] if i["split"] == sp] for sp in ("train", "val", "test")}
        for sp, its in self.splits.items():
            self.log(_("{sp}: {p2} 張", sp=sp, p2=len(its)))
        if not self.splits["train"]:
            raise RuntimeError(_("沒有可以訓練的畫面"))
        frames = [i["frame"] for sp in ("train", "val", "test") for i in self.splits[sp]]
        self.progress("cache", 0, None, message=_("準備影像"))
        t_cache = time.time()
        imgs = load_images(self.data_root, frames, self.size, self.log,
                           progress=lambda d, t: self.progress("cache", d, t, rate=d / max(1e-6, time.time() - t_cache)))
        pos = 0
        self.X = {}
        for sp in ("train", "val", "test"):
            n = len(self.splits[sp])
            self.X[sp] = imgs.slice(pos, pos + n)                 # read from the SSD cache per batch
            pos += n
        self.Y = {sp: self._targets(self.splits[sp]) for sp in self.X}
        self.n_train, self.n_val, self.n_test = (len(self.splits[sp]) for sp in ("train", "val", "test"))

        # class weights: rarer classes count more (square-root balancing, so rare ones don't dominate)
        self.class_w = {}
        for h in self.heads:
            if h["kind"] != "class":
                continue
            y = self.Y["train"][h["id"]]
            cnt = torch.bincount(y[y >= 0], minlength=len(h["classes"])).float()
            w = torch.where(cnt > 0, (cnt.sum() / cnt.clamp(min=1)).sqrt(), torch.zeros_like(cnt))
            self.class_w[h["id"]] = (w / w[cnt > 0].mean()).to(self.dev)

    def _targets(self, items):
        out = {}
        for h in self.heads:
            v = [i["targets"][h["id"]] for i in items]
            if h["kind"] == "class":
                out[h["id"]] = torch.tensor([-1 if x is None else x for x in v], dtype=torch.long)
            else:
                out[h["id"]] = torch.tensor([math.nan if x is None else x for x in v], dtype=torch.float32)
        return out

    # ---------- model ----------
    def _batch(self, X, idx, augment=False):
        x = X[idx].to(self.dev, non_blocking=True).permute(0, 3, 1, 2).float()
        if augment:
            n = x.shape[0]
            b = torch.empty(n, 1, 1, 1, device=self.dev).uniform_(0.8, 1.2)       # brightness
            cst = torch.empty(n, 1, 1, 1, device=self.dev).uniform_(0.8, 1.2)     # contrast
            m = x.mean(dim=(1, 2, 3), keepdim=True)
            x = ((x - m) * cst + m) * b
            dx, dy = random.randint(-6, 6), random.randint(-4, 4)                 # small shift: the screen layout stays in place
            x = torch.roll(x, shifts=(dy, dx), dims=(2, 3))
            x = x.clamp(0, 255)
        return x.contiguous()        # plain NCHW: channels_last was 10x slower on the RTX 2060 (measured)

    def _loss(self, out, idx, split="train"):
        total, parts = 0.0, {}
        for h in self.heads:
            y = self.Y[split][h["id"]][idx].to(self.dev)
            if h["kind"] == "class":
                ok = y >= 0
                if not ok.any():
                    continue
                l = smooth_ce(out[h["id"]][ok].float(), y[ok], self.class_w[h["id"]], LABEL_SMOOTHING)
            else:
                ok = ~torch.isnan(y)
                if not ok.any():
                    continue
                l = F.smooth_l1_loss(out[h["id"]][ok].float(), y[ok], beta=0.05) * self.cfg["ratio_weight"]
            parts[h["id"]] = l.detach()          # kept on the GPU: reading it every step would stall the pipeline
            total = total + l
        return total, parts

    @torch.no_grad()
    def predict(self, model, X, bs=64, phase=None):
        model.eval()
        res = {h["id"]: [] for h in self.heads}
        t0 = time.time()
        for s in range(0, X.shape[0], bs):
            if phase and s and (s // bs) % 10 == 0:
                self.rate_eval = s / (time.time() - t0)
                self.progress(phase, s, X.shape[0], rate=self.rate_eval, epoch=getattr(self, "cur_epoch", None),
                              epochs=self.cfg["epochs"], best_epoch=getattr(self, "best_epoch", None))
            idx = torch.arange(s, min(s + bs, X.shape[0]))
            with torch.autocast(self.dev, dtype=torch.float16, enabled=self.dev == "cuda"):
                out = model(self._batch(X, idx))
            for h in self.heads:
                o = out[h["id"]].float()
                res[h["id"]].append(torch.softmax(o, 1).cpu() if h["kind"] == "class" else o.cpu())
        return {k: torch.cat(v) for k, v in res.items()}

    def score(self, pred, split):
        """Per head: accuracy (class) or mean absolute error (ratio). Test uses the checked answers."""
        items, out = self.splits[split], {}
        for h in self.heads:
            p = pred[h["id"]]
            if h["kind"] == "class":
                if split == "test":
                    pairs = [(h["classes"].index(i["answers"][h["id"]]), int(p[k].argmax())) for k, i in enumerate(items)
                             if i["answers"].get(h["id"]) in h["classes"]]
                else:
                    y = self.Y[split][h["id"]]
                    pairs = [(int(y[k]), int(p[k].argmax())) for k in range(len(items)) if y[k] >= 0]
                out[h["id"]] = round(sum(a == b for a, b in pairs) / len(pairs), 4) if pairs else None
            else:
                y = self.Y[split][h["id"]]
                ok = ~torch.isnan(y)
                out[h["id"]] = round(float((p[ok] - y[ok]).abs().mean()), 4) if ok.any() else None
        return out

    def _val_key(self, s):
        """Single number to choose the best epoch: mean hold-out accuracy of the class heads, minus ratio error."""
        cls = [s[h["id"]] for h in self.heads if h["kind"] == "class" and s.get(h["id"]) is not None]
        rat = [s[h["id"]] for h in self.heads if h["kind"] == "ratio" and s.get(h["id"]) is not None]
        return (sum(cls) / len(cls) if cls else 0) - (sum(rat) / len(rat) if rat else 0)

    def _save(self, model, name, extra=None):
        torch.save({"state_dict": model.state_dict(), "heads": self.heads, "size": list(self.size),
                    "backbone": self.cfg["backbone"], "config": self.cfg, "run": self.id,
                    "trainer_version": TRAINER_VERSION, **(extra or {})}, os.path.join(self.dir, name))

    # ---------- main loop ----------
    def train(self):
        c = self.cfg
        self.prepare()
        model = ScreenModel(self.heads, self.size, pretrained=c["pretrained"], backbone=c["backbone"])
        torch.backends.cudnn.benchmark = True          # fixed input size: let cuDNN pick the fastest kernels
        model = model.to(self.dev)
        opt = torch.optim.AdamW(model.parameters(), lr=c["lr"], weight_decay=c["weight_decay"])
        n = self.X["train"].shape[0]
        steps_per_epoch = max(1, math.ceil(n / c["batch"]))
        total, warm = c["epochs"] * steps_per_epoch, c["warmup_epochs"] * steps_per_epoch
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: (s + 1) / warm if s < warm else 0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, total - warm))))
        scaler = torch.amp.GradScaler(enabled=self.dev == "cuda")
        best, best_epoch = -1e9, None
        self.log(_("開始訓練:{epochs} 輪,每輪 {steps_per_epoch} 批,裝置 {dev}", epochs=c['epochs'], steps_per_epoch=steps_per_epoch, dev=self.dev))
        for ep in range(1, c["epochs"] + 1):
            model.train()
            self.cur_epoch = ep
            perm = torch.randperm(n)
            sums, cnt, te = {}, 0, time.time()
            for s in range(0, n, c["batch"]):
                idx = perm[s:s + c["batch"]]
                if len(idx) < 2:
                    continue
                x = self._batch(self.X["train"], idx, augment=c["augment"])
                with torch.autocast(self.dev, dtype=torch.float16, enabled=self.dev == "cuda"):
                    out = model(x)
                loss, parts = self._loss(out, idx)
                opt.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
                sched.step()
                for k, v in parts.items():
                    sums[k] = sums.get(k, 0) + v
                sums["total"] = sums.get("total", 0) + loss.detach(); cnt += 1
                if cnt % 10 == 0:
                    self.rate_train = cnt * c["batch"] / (time.time() - te)
                    self.progress("train", min(n, cnt * c["batch"]), n, rate=self.rate_train, epoch=ep, epochs=c["epochs"],
                                  step=cnt, steps=steps_per_epoch, best_epoch=best_epoch)
            train_loss = {k: round(float(v) / cnt, 4) for k, v in sums.items()}
            self.best_epoch = best_epoch
            val = self.score(self.predict(model, self.X["val"], phase="val"), "val") if len(self.splits["val"]) else {}
            test = self.score(self.predict(model, self.X["test"], phase="test"), "test") if len(self.splits["test"]) else {}
            key = self._val_key(val) if val else -train_loss["total"]
            is_best = key > best
            if is_best:
                best, best_epoch = key, ep
                self._save(model, "model_best.pt", {"epoch": ep})
            rec = {"epoch": ep, "lr": round(sched.get_last_lr()[0], 7), "seconds": round(time.time() - te, 1),
                   "train_loss": train_loss, "val": val, "test": test, "best": is_best}
            with open(os.path.join(self.dir, "metrics.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fmt = lambda d: " ".join(f"{k}={v}" for k, v in d.items() if v is not None)
            self.log(_("第 {ep}/{epochs} 輪 ({seconds}s) loss {total} | 保留裝置 {p5} | 測試集 {p6}{p7}", ep=ep, epochs=c['epochs'], seconds=rec['seconds'], total=train_loss['total'], p5=fmt(val), p6=fmt(test), p7=' ★' if is_best else ''))
            self.progress("train", 0, n, rate=getattr(self, "rate_train", None), epoch=min(ep + 1, c["epochs"]),
                          epochs=c["epochs"], best_epoch=best_epoch, epoch_seconds=rec["seconds"])
        self._save(model, "model_last.pt", {"epoch": c["epochs"]})

        self.progress("report", 0, self.n_test, epoch=c["epochs"], epochs=c["epochs"], best_epoch=best_epoch)
        from .model import load
        best_model, _x = load(os.path.join(self.dir, "model_best.pt"), self.dev)
        report = self.report(best_model, best_epoch)
        try:                                          # the runtime runs this one without PyTorch
            from .onnx_export import export
            path, diff = export(os.path.join(self.dir, "model_best.pt"))
            self.log(_("已轉成 ONNX(和 PyTorch 的最大差異 {diff})", diff=format(diff, '.1e')))
        except Exception as e:                        # the runtime falls back to model_best.pt
            self.log(_("轉成 ONNX 失敗(執行時改用 PyTorch):{e}", e=e))
        self._json("eval.json", report)
        self.status(state="done", epoch=c["epochs"], epochs=c["epochs"], best_epoch=best_epoch,
                    summary={k: v.get("model_acc") if "model_acc" in v else v.get("test_mae") for k, v in report["heads"].items()})
        self.log(_("完成,最佳是第 {best_epoch} 輪。結果在 {dir}", best_epoch=best_epoch, dir=self.dir))

    # ---------- final report ----------
    def report(self, model, best_epoch):
        items = self.splits["test"]
        pred = self.predict(model, self.X["test"])
        holdout = set(self.cfg["holdout"])
        heads, mistakes = {}, []
        with open(os.path.join(self.dir, "predictions.jsonl"), "w", encoding="utf-8") as f:
            for k, it in enumerate(items):
                row = {"frame": it["frame"], "device": it["device"], "answers": it["answers"], "reviewer": it["reviewer"],
                       "rule": it["rule"], "pred": {}}
                for h in self.heads:
                    p = pred[h["id"]][k]
                    if h["kind"] == "class":
                        j = int(p.argmax())
                        row["pred"][h["id"]] = {"value": h["classes"][j], "conf": round(float(p[j]), 3)}
                    else:
                        row["pred"][h["id"]] = {"value": round(float(p), 4)}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                for h in self.heads:
                    if h["kind"] != "class":
                        continue
                    ans = it["answers"].get(h["id"])
                    pv = row["pred"][h["id"]]
                    if ans in h["classes"] and pv["value"] != ans:
                        mistakes.append({"frame": it["frame"], "device": it["device"], "state": h["id"], "answer": ans,
                                         "pred": pv["value"], "conf": pv["conf"], "rule": it["rule"].get(h["id"])})
        for h in self.heads:
            if h["kind"] == "ratio":
                y = self.Y["test"][h["id"]]
                ok = ~torch.isnan(y)
                heads[h["id"]] = {"name": h["name"], "kind": "ratio",
                                  "test_mae": round(float((pred[h["id"]][ok] - y[ok]).abs().mean()), 4) if ok.any() else None,
                                  "n": int(ok.sum())}
                continue
            C = len(h["classes"])
            conf = [[0] * C for _x in range(C)]
            groups = collections.defaultdict(lambda: [0, 0])
            rule = collections.Counter()
            for k, it in enumerate(items):
                ans = it["answers"].get(h["id"])
                if ans not in h["classes"]:
                    continue
                a, p = h["classes"].index(ans), int(pred[h["id"]][k].argmax())
                conf[a][p] += 1
                g = "holdout" if it["device"] in holdout else "seen"
                groups[g][0] += a == p; groups[g][1] += 1
                groups["all"][0] += a == p; groups["all"][1] += 1
                r = it["rule"].get(h["id"])
                if r is None:
                    rule["abstain_ok" if ans == "hidden" else "abstain_missed"] += 1
                else:
                    rule["correct" if r == ans else "wrong"] += 1
            judged = rule["correct"] + rule["wrong"]
            n_all = judged + rule["abstain_ok"] + rule["abstain_missed"]
            heads[h["id"]] = {
                "name": h["name"], "kind": "class", "classes": [str(x) for x in h["classes"]], "class_names": h["class_names"],
                "n": groups["all"][1],
                "model_acc": round(groups["all"][0] / groups["all"][1], 4) if groups["all"][1] else None,
                "by_group": {g: {"acc": round(v[0] / v[1], 4) if v[1] else None, "n": v[1]} for g, v in groups.items() if g != "all"},
                "confusion": conf,
                # the rule may say "don't know"; counting that as right only when the answer is "hidden" makes it comparable
                "rule": {**dict(rule), "acc_when_answered": round(rule["correct"] / judged, 4) if judged else None,
                         "coverage": round(judged / n_all, 4) if n_all else None,
                         "acc_overall": round((rule["correct"] + rule["abstain_ok"]) / n_all, 4) if n_all else None},
            }
        return {"run": self.id, "best_epoch": best_epoch, "test_frames": len(items), "holdout": sorted(holdout),
                "heads": heads, "mistakes": mistakes}
