"""FastAPI routes. The built web UI (web/dist) is served from the same port."""
import bisect
import glob
import collections
import json
import re
import os
import tempfile
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
from PIL import Image
from pydantic import BaseModel

import project
from i18n import N_, _, tr
from . import DATA_ROOT, PROJECT_ROOT, RUNTIME_DIR, WORK_ROOT, data, review
from .jobs import JobManager

app = FastAPI(title="Inspector")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
jobs = JobManager()


@app.middleware("http")
async def _access(request: Request, call_next):
    """Other devices (phones on the LAN) sign in with a PIN; end users only reach the operation panel."""
    from . import access
    role = access.role_of(request.client.host if request.client else "", request.cookies.get(access.COOKIE))
    if not access.allowed(role, request.method, request.url.path):
        return JSONResponse({"detail": _("請先登入") if not role else _("沒有權限")}, status_code=401 if not role else 403)
    if access.design_locked(request.method, request.url.path):
        return JSONResponse({"detail": _("這是執行版:設計只能在 Studio 修改,再匯出新版的方案包安裝到這裡")}, status_code=403)
    request.state.role = role
    return await call_next(request)


@app.middleware("http")
async def _language(request: Request, call_next):
    """The sentences this request's answer builds come in the page's language (X-Lang; i18n/__init__.py)."""
    import i18n
    token = i18n.use(request.headers.get("x-lang"))
    try:
        return await call_next(request)
    finally:
        i18n.reset(token)




def _bad(e, code=400):
    raise HTTPException(code, str(e))


# ---------------- collector ----------------
def _collector_live():
    path = os.path.join(WORK_ROOT, "collector_status.json")
    if not os.path.exists(path):
        return None
    try:
        st = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    st["stale"] = st.get("running") and time.time() - st.get("updated", 0) > 10   # process died without cleanup
    return st


# ---------------- sources (來源: drivers/sources.py, server/sources_view.py) ----------------
@app.get("/api/sources")
def sources_get():
    from . import sources_view
    return sources_view.view(DATA_ROOT, RUNTIME_DIR, _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {})


@app.get("/api/sources/names")
def sources_names():
    """id -> the name people read (every page that shows a device uses it)."""
    from drivers import sources
    cfg = sources.load(DATA_ROOT)
    return {"names": sources.names(DATA_ROOT), "enabled": [it["id"] for it in cfg["items"] if it.get("enabled")],
            "hands": {it["id"]: sources.hand_text(it, DATA_ROOT) for it in cfg["items"] if (it.get("hand") or {}).get("to", "self") != "self"},
            "tags": sources.tags(DATA_ROOT)}


class SourceScan(BaseModel):
    kinds: list[str] = []
    q: str = ""


@app.post("/api/sources/scan")
def sources_scan(req: SourceScan):
    from . import sources_view
    import drivers
    bad = [k for k in req.kinds if k not in drivers.kinds()]
    if bad:
        _bad(_("沒有這種來源:{p1}", p1=_("、").join(bad)))
    return sources_view.scan(DATA_ROOT, req.kinds, req.q)


class SourceAdd(BaseModel):
    kind: str
    match: str
    id: str | None = None
    name: str = ""
    params: dict = {}                       # its own settings (a window: title, program ...)


@app.post("/api/sources/add")
def sources_add(req: SourceAdd, start_mode: str = "shadow"):
    """Use a source that was found: it gets an id for good (its own name unless taken) and is on right away.
    start_mode shadow: a main script running live everywhere starts it as a trial (試跑); live: as it runs elsewhere."""
    from drivers import sources
    cfg = sources.load(DATA_ROOT)
    import drivers
    per = drivers.kinds().get(req.kind) and drivers.kinds()[req.kind].per_source
    if not per and any(it["kind"] == req.kind and it["match"] == req.match for it in cfg["items"]):
        _bad(_("這個來源已經在用了"))
    sid = (req.id or "").strip() or sources.new_id(cfg, req.match)
    if any(it["id"] == sid for it in cfg["items"]):
        _bad(_("代號「{sid}」已經有別的來源用了(代號不能重複用,舊的設定會接錯)", sid=sid))
    kd = drivers.kinds().get(req.kind)
    own_hand = bool(kd and kd.caps & {"tap", "swipe", "back", "text"})
    cfg["items"].append({"id": sid, "kind": req.kind, "match": req.match, "name": req.name, "enabled": True, "added": time.time(),
                         "hand": {"to": "self" if own_hand else "none"}, "params": req.params or {}})
    cfg["kinds"].setdefault(req.kind, {"params": {}})
    cfg["seen"].pop(f"{req.kind}|{req.match}", None)
    try:
        sources.save(cfg, DATA_ROOT)
    except ValueError as e:
        _bad(e)
    print(_("{p1} 來源:加入 {sid}({kind} {match})", p1=time.strftime('%H:%M:%S'), sid=sid, kind=req.kind, match=req.match), flush=True)
    # a new source starts as a trial everywhere: a main script that runs "live" on every device gets "試跑" here
    import automation
    trial = []
    for sc in automation.load_all(DATA_ROOT) if start_mode != "live" else []:
        if automation.is_guard(sc) or sid in (sc.get("devices") or {}) or automation.mode_for(sc, sid) != "live":
            continue
        sc = {k: v for k, v in sc.items() if k not in ("version", "created", "note")}
        sc["devices"][sid] = "shadow"
        try:
            automation.save(DATA_ROOT, sc, _("新來源 {sid} 先試跑", sid=sid))
            trial.append(sc["name"])
        except ValueError:
            pass
    return {"id": sid, "trial": trial}


class SourceUpdate(BaseModel):
    id: str
    name: str | None = None
    enabled: bool | None = None
    hand: dict | None = None                # where its actions go: {"to": self | source | output | none, "id"}
    params: dict | None = None              # its own settings (a window's title, a screen rectangle)
    tags: list[str] | None = None           # the groups it belongs to (#北棟 ...)
    match: str | None = None                # re-bind: the driver's name for it changed (e.g. the emulator was renamed)
    kind: str | None = None


@app.post("/api/sources/update")
def sources_update(req: SourceUpdate):
    from drivers import sources
    cfg = sources.load(DATA_ROOT)
    it = next((x for x in cfg["items"] if x["id"] == req.id), None)
    if not it:
        _bad(_("找不到這個來源"))
    if req.name is not None:
        it["name"] = req.name
    if req.enabled is not None:
        it["enabled"] = req.enabled
    if req.match:
        it["match"], it["kind"] = req.match, req.kind or it["kind"]
        cfg["seen"].pop(f"{it['kind']}|{req.match}", None)
    old_hand = dict(it.get("hand") or {"to": "self"})
    old_tags = list(it.get("tags") or [])
    import automation
    before = {sc["id"]: automation.mode_for(sc, req.id) for sc in automation.load_all(DATA_ROOT)}
    if req.tags is not None:
        it["tags"] = req.tags
    if req.hand is not None:
        it["hand"] = req.hand
    if req.params is not None:
        it["params"] = req.params
    try:
        sources.save(cfg, DATA_ROOT)
    except ValueError as e:
        _bad(e)
    if (req.hand is not None and req.hand != old_hand) or (req.tags is not None and req.tags != old_tags):
        import drivers                                     # the scripts deployed here must still be able to act
        for sc in automation.load_all(DATA_ROOT):
            try:
                drivers.check_script(sc, _("主腳本「{name}」", name=sc['name']), DATA_ROOT)
            except ValueError as e:
                it["hand"], it["tags"] = old_hand, old_tags
                sources.save(cfg, DATA_ROOT)
                _bad(_("{e}。沒有改。", e=e))
    out = sources_get()
    now_live = [sc["name"] for sc in automation.load_all(DATA_ROOT)
                if automation.mode_for(sc, req.id) == "live" and before.get(sc["id"]) != "live"]
    return {**out, "now_live": now_live}


class SourceRemove(BaseModel):
    id: str
    force: bool = False


@app.post("/api/sources/remove")
def sources_remove(req: SourceRemove):
    """Stop knowing a source. Its id is not given to another one (what refers to it would point at the wrong device)."""
    from drivers import sources
    from . import sources_view
    refs = sources_view.references(DATA_ROOT, RUNTIME_DIR, req.id)
    if refs and not req.force:
        return {"refs": refs, "removed": False}
    cfg = sources.load(DATA_ROOT)
    it = next((x for x in cfg["items"] if x["id"] == req.id), None)
    if not it:
        _bad(_("找不到這個來源"))
    cfg["items"] = [x for x in cfg["items"] if x["id"] != req.id]
    cfg.setdefault("retired", []).append(req.id)
    sources.save(cfg, DATA_ROOT)
    return {"refs": refs, "removed": True}


class SourceKind(BaseModel):
    kind: str
    on: bool
    params: dict[str, Any] = {}


@app.post("/api/sources/kind")
def sources_kind(req: SourceKind):
    from drivers import sources
    cfg = sources.load(DATA_ROOT)
    cfg["kinds"][req.kind] = {"params": req.params}       # (on: kept for older pages; in use decides now)
    try:
        sources.save(cfg, DATA_ROOT)
    except ValueError as e:
        _bad(e)
    return sources_get()


class SourceIgnore(BaseModel):
    kind: str
    match: str
    ignore: bool = True


@app.post("/api/sources/ignore")
def sources_ignore(req: SourceIgnore):
    """Found but not wanted (someone's own emulator): no longer announced as new."""
    from drivers import sources
    cfg = sources.load(DATA_ROOT)
    key = f"{req.kind}|{req.match}"
    ig = [x for x in cfg.get("ignored") or [] if x != key]
    cfg["ignored"] = ig + ([key] if req.ignore else [])
    sources.save(cfg, DATA_ROOT)
    return {"ok": True}


@app.get("/api/devices")
def devices_list():
    import drivers
    try:
        drv = drivers.current(DATA_ROOT)
        insts = drv.list()
    except Exception as e:
        _bad(_("裝置來源無法使用:{e}", e=e))
    return [{"name": i.name, "label": (i.info or {}).get("name") or i.name, "ok": i.ok, "detail": i.detail,
             "size": f"{i.size[0]}x{i.size[1]}" if i.size else ""} for i in insts]


@app.get("/api/drivers")
def drivers_info():
    """The device sources there are, which one the project uses, and what it can do."""
    import drivers
    kind, params = drivers.config(DATA_ROOT)
    return {"kinds": drivers.describe(), "current": {"driver": kind, "params": params}, "caps": tr(drivers.CAPS)}


class DriverSet(BaseModel):
    driver: str
    params: dict[str, Any] = {}


@app.put("/api/drivers")
def drivers_set(req: DriverSet):
    import drivers
    if req.driver not in drivers.kinds():
        _bad(_("沒有這種裝置來源"))
    from drivers import sources                     # older pages: "use this kind" = turn it on (sources.json)
    cfg = sources.load(DATA_ROOT)
    cfg["kinds"][req.driver] = {"params": req.params}
    try:
        sources.save(cfg, DATA_ROOT)
    except ValueError as e:
        _bad(e)
    return drivers_info()


class CollectorStart(BaseModel):
    interval: float = 3.0
    minutes: float = 0
    only: list[str] = []
    touch: bool = True
    label_after: bool = True       # produce labels as soon as the collection ends
    capture: str = "window"        # the source kind's capture modes (e.g. android: window / adb)


@app.post("/api/collector/start")
def collector_start(req: CollectorStart):
    live = _collector_live()
    if live and live.get("running") and not live.get("stale"):
        _bad(_("收集器已經在執行(可能是從指令列啟動的)"))
    args = ["collector", "--data", DATA_ROOT, "--interval", str(req.interval), "--minutes", str(req.minutes)]
    for n in req.only:
        args += ["--only", n]
    if not req.touch:
        args.append("--no-touch")
    import re
    if not re.fullmatch(r"[a-z_]+", req.capture or ""):
        _bad(_("截圖方式不正確"))
    args += ["--capture", req.capture]
    def after(job):
        if req.label_after and job.status in ("done", "stopped"):      # stopped = the user pressed stop: data is fine
            job.lines.append(_("收集結束,自動開始產生標籤…"))
            jobs.start("labeler", ["labeler", "--data", DATA_ROOT], _("產生標籤(收集後自動)"))

    try:
        j = jobs.start("collector", args, _("資料收集"), on_exit=after)
    except RuntimeError as e:
        _bad(e)
    return j.info()


@app.post("/api/collector/stop")
def collector_stop():
    j = jobs.running("collector")
    if j:
        j.stop()
        return {"stopped": True, "job": j.info()}
    live = _collector_live()
    if live and live.get("running") and not live.get("stale"):     # started from the command line
        open(os.path.join(WORK_ROOT, "collector.stop"), "w").close()
        return {"stopped": True, "via": "stop_file"}
    return {"stopped": False}


def _recorders():
    """The project's recorder plugins (classes; the collector makes them, the server only asks their static hooks)."""
    from project.plugins import registry
    return registry(DATA_ROOT).all("recorder")


@app.get("/api/collector")
def collector_status():
    j = jobs.latest("collector")
    live = _collector_live()
    if live and live.get("devices"):
        for r in _recorders().values():
            if hasattr(r, "annotate_live"):          # e.g. turn a device's own codes into names the user gave
                try:
                    r.annotate_live(live["devices"], DATA_ROOT)
                except Exception as e:
                    print(_("annotate_live 失敗:{e}", e=e), flush=True)
    return {"live": live, "job": j.info(tail=150) if j else None}


# ---------------- jobs ----------------
@app.get("/api/jobs")
def jobs_list():
    return jobs.list(tail=0)


@app.get("/api/jobs/{job_id}")
def job_get(job_id: str):
    j = jobs.get(job_id)
    if not j:
        _bad(_("找不到這個工作"), 404)
    return j.info(tail=400)


@app.post("/api/jobs/{job_id}/stop")
def job_stop(job_id: str):
    j = jobs.get(job_id)
    if not j:
        _bad(_("找不到這個工作"), 404)
    j.stop()
    return j.info()


# ---------------- overview ----------------
@app.get("/api/overview")
def overview():
    sess = data.sessions()
    versions = data.label_versions()
    return {
        "data_root": DATA_ROOT, "disk": data.disk(),
        "sessions": len(sess), "samples": sum(s["samples"] for s in sess), "touches": sum(s["touches"] for s in sess),
        "bytes": sum(s["bytes"] for s in sess), "recent_sessions": sess[:5],
        "collector": _collector_live(),
        "labels": versions[-1] if versions else None,
        "testset": {"reviewed": len(review.test_decisions())},
        "jobs": jobs.list(tail=0)[:8],
    }


from runtime import judge   # noqa: E402
from automation import outputs as outputs_mod   # noqa: E402
from runtime.judge import MIN_ANSWERS, MIN_PER_CLASS   # noqa: E402  (same bar as the model test)


@app.get("/api/next_steps")
def next_steps():
    """The home page's to-do list: what a user should do next, in plain words, each with a link.
    level: todo (something to do) / warn (needs attention) / info (going on, nothing to do) / ok"""
    from runtime import judge
    import automation
    steps = []

    def add(group, level, title, detail="", link="", cta=""):
        steps.append({"group": group, "level": level, "title": title, "detail": detail, "link": link, "cta": cta})

    sch = schema_mod.load(DATA_ROOT)
    sess = data.sessions()
    live = _collector_live()
    disk = data.disk()

    # ---- ① what to watch
    pk = _pack_status()                          # the pack and its plugin: can they run on this Inspector?
    for pr in (pk or {}).get("problems") or []:
        add("watch", "warn", _("方案包「{name}」:{text}", name=pk.get("name") or pk.get("id"), text=pr["text"]),
            _("方案包不能執行時,它的外掛不會載入;請更新 Inspector 或換一個相容的方案包版本。") if pr["level"] == "error" else "")
    from project.plugins import registry
    for pl in registry(DATA_ROOT).loaded:
        if not pl["ok"] and not (pk and any(pr["level"] == "error" for pr in pk["problems"])):
            add("watch", "warn", _("外掛「{name}」載入失敗", name=pl["name"]), str(pl.get("error") or ""))
    try:                                         # sources (來源): the last scan the runner / collector made
        import drivers
        from drivers import sources
        cfg = sources.load(DATA_ROOT)
        drv = drivers.current(DATA_ROOT)
        if not drv.last:
            drv.list()
        natives = {(k, d.name): d for k, ds in drv.last.items() for d in ds}
        bound = {(it["kind"], it["match"]) for it in cfg["items"]}
        have = drivers.kinds()
        fresh = [n for (k, n) in natives if (k, n) not in bound and f"{k}|{n}" not in (cfg.get("ignored") or [])
                 and not (k in have and have[k].per_source) and k in sources.in_use(cfg)]
        if not cfg["items"]:
            add("watch", "todo", _("還沒有使用任何來源"), _("到「來源」掃描這台電腦上的{p1},勾選要用的。", p1=project.word('device')), "/sources", _("去設定"))
        if fresh:
            add("watch", "todo", _("發現 {p1} 個新來源:", p1=len(fresh)) + _("、").join(fresh[:4]), _("新的來源預設不使用;要用的話到「來源」按「使用」,不用的可以忽略。"), "/sources", _("去看看"))
        gone = [sources.label(it["id"], DATA_ROOT) for it in cfg["items"] if it.get("enabled") and (
                    (it["id"] not in drv.found) if (it["kind"] in have and have[it["kind"]].per_source)
                    else ((it["kind"], it["match"]) not in natives and it["kind"] in drv.last))]
        if gone:
            add("watch", "warn", _("找不到:") + _("、").join(gone[:4]), _("沒開,或改了名稱;改名的話到「來源」把它接回,設定都會保留。"), "/sources", _("去看看"))
        bad = [(sources.label(it["id"], DATA_ROOT), sources.check_size(natives[(it["kind"], it["match"])], DATA_ROOT))
               for it in cfg["items"] if it.get("enabled") and (it["kind"], it["match"]) in natives and not have.get(it["kind"], None).per_source] +               [(sources.label(i, DATA_ROOT), sources.check_size(d, DATA_ROOT, True)) for i, d in drv.found.items()]
        for nm, w in [x for x in bad if x[1]][:3]:
            add("watch", "warn", _("「{nm}」的畫面大小不對", nm=nm), w, "/sources", _("去看看"))
        stl = _runner_live() or {}
        for dv in stl.get("devices") or []:
            hl = dv.get("health") or {}
            if hl.get("state") in ("lost", "frozen"):
                add("watch", "warn", _("「{x}」", x=sources.label(dv["name"], DATA_ROOT)) + " " + str(hl.get("text") or ""), _("看一下那台:程式還開著嗎、網路通嗎、畫面是不是停住了。"), "/sources", _("去看看"))
    except Exception as e:
        add("watch", "warn", _("來源讀不到"), str(e), "/sources", _("去看看"))
    if not sess:
        add("watch", "todo", _("還沒有任何影像"), _("先接上影像來源並開始錄製,平台才有畫面可以學。"), "/collect", _("開始錄製"))
    if live and live.get("running") and not live.get("stale"):
        mins = (time.time() - (live.get("started") or time.time())) / 60
        add("watch", "info", _("正在錄製({p1} 個畫面來源)", p1=len(live.get('devices') or [])), _("已錄 {mins} 分鐘", mins=format(mins, '.0f')), "/collect", _("查看"))
    if disk["free"] < 50e9:
        add("watch", "warn", _("磁碟只剩 {p1} GB", p1=format(disk['free'] / 1e9, '.0f')), _("錄製會用掉大量空間,請清理或換一顆磁碟。"), "/collect", _("查看"))

    # ---- ② teach it
    st = review.stats()
    if st["needs_human"]:
        add("teach", "todo", _("有 {needs_human} 題等你確認", needs_human=st['needs_human']), _("這些題目答案還沒確定,確認後成績才準。"), "/review", _("去回答"))
    for s in sch["states"]:
        if s["type"] != "class" or not (s.get("review") or {}).get("enabled"):
            continue
        dist = (st["states"].get(s["id"]) or {}).get("distribution", {})
        n = sum(dist.values())
        from . import progress
        askable, unseen = progress.short_answers(s, dist)
        if n < MIN_ANSWERS:
            add("teach", "todo", _("「{name}」只有 {n} 題考題", name=s['name'], n=n),
                _("至少要 {MIN_ANSWERS} 題,才知道它判斷得準不準。", MIN_ANSWERS=MIN_ANSWERS), f"/review?state={s['id']}", _("去回答"))
        elif askable:
            add("teach", "todo", _("「{name}」有些答案太少考到", name=s['name']), _("、").join(_("「{nm}」{k} 題", nm=nm, k=k) for nm, k in askable)
                + _("。每種答案至少要 {MIN_PER_CLASS} 題;在「回答問題」只問這一題,不夠的話按「補 30 題」。", MIN_PER_CLASS=MIN_PER_CLASS), f"/review?state={s['id']}", _("去回答"))
        if n >= MIN_ANSWERS and unseen:
            add("teach", "info", _("「{name}」的「{answers}」還沒錄到過", name=s["name"], answers=_("」、「").join(nm for nm, _x in unseen)),
                _(progress.UNSEEN_HINT), "/collect", _("去錄製"))
    tj = jobs.running("train")
    run_dir = judge.latest_run(DATA_ROOT)
    if tj:
        add("teach", "info", _("正在學習(訓練模型)"), _("完成後腳本就會用新的模型判斷。"), "/train", _("看進度"))
    elif not run_dir:
        add("teach", "todo", _("還沒有學過"), _("有了影像和一些考題之後,就可以開始第一次學習。"), "/train", _("開始學習"))
    else:
        created = (_read_json(os.path.join(run_dir, "config.json"), {}) or {}).get("created", 0)
        new = [x for x in sess if x.get("ended") and (x.get("started") or 0) > created and x["samples"]]
        if new:
            hours = sum(x["minutes"] or 0 for x in new) / 60
            add("teach", "todo", _("有 {hours} 小時的新畫面還沒學過", hours=format(hours, '.1f')), _("{p1} 次錄製是上次學習之後才錄的,學過之後判斷會更穩。", p1=len(new)),
                "/train", _("開始學習"))
    jd = judge.sources(sch, run_dir)
    rule = [s["name"] for s in sch["states"] if jd["states"].get(s["id"], {}).get("source") == "rule"]
    if rule:
        add("teach", "info", _("「{states}」還沒學過,先用參考圖判斷", states=_("」、「").join(rule)),
            _("現在就能用在腳本裡;下次學習時會一起學。"), "/states", _("查看"))

    # ---- ③ automation
    scripts = [s for s in automation.load_all(DATA_ROOT) if s.get("enabled", True)]
    rs = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    running = rs.get("running") and time.time() - rs.get("updated", 0) < 10
    if not scripts:
        add("auto", "todo", _("還沒有腳本"), _("用「如果…就…」設計第一個腳本,先用試跑看它會怎麼做。"), "/scripts", _("去設計腳本"))
    elif running:
        n_live = sum(1 for s in scripts for m in (s.get("devices") or {}).values() if m == "live")
        held = [d["name"] for d in rs.get("devices") or [] if d.get("hold")]
        add("auto", "info", _("腳本執行中({p1} 個畫面來源)", p1=len(rs.get('devices') or [])),
            (_("全部停下來中,只看不點(按「全部繼續」恢復)") if rs.get("hold_all") and (rs["hold_all"] or {}).get("mode") != "run"
             else _("正式執行的腳本會真的動作") + (_(";{p1} 台停下來或暫停中", p1=len(held)) if held else "")) if n_live else _("全部都是試跑(只看不點)"),
            "/script", _("監看"))
        if rs.get("hold_all"):
            add("auto", "warn", _("全部暫停中") if rs["hold_all"].get("mode") == "pause" else _("全部停下來中"),
                _("{p1}:正式執行的腳本、守門規則、排程都不會動作,到「執行」按「全部繼續」恢復。", p1=rs['hold_all'].get('by') or ''), "/script", _("去看看"))
        for d in rs.get("devices") or []:
            h = d.get("hold") or {}
            if h.get("cause"):                     # a rule / a script stopped it
                add("auto", "warn", _("{name} 停下來了:{by}", name=d['name'], by=h.get('by', '')), h.get("why") or "",
                    "/script", _("處理"))
        for b in rs.get("blocked") or []:
            add("auto", "warn", _("{device} 有規則暫停了", device=b['device']), b["reason"], "/script", _("處理"))
    else:
        add("auto", "info", _("腳本沒有在執行"), _("已設計 {p1} 個腳本。", p1=len(scripts)), "/script", _("開始執行"))
    from automation import tests as tests_mod
    tres = _read_json(os.path.join(RUNTIME_DIR, "tests", "results.json"), {}) or {}
    tlist = tests_mod.load(DATA_ROOT)
    failed = [t["name"] for t in tlist if (tres.get(t["id"]) or {}).get("status") in ("fail", "error")]
    if failed:
        add("auto", "warn", _("{p1} 個腳本測試沒通過", p1=len(failed)), _("、").join(failed[:3]) + ("…" if len(failed) > 3 else ""), "/tests", _("查看"))
    dec = review.decisions()
    saved = _runtime_saved()
    open_flags = [r for r in saved if r["origin"] == "flag" and not (dec.get(r["frame"]) or {}).get("answers")]
    open_unsure = [r for r in saved if r["origin"] == "uncertain" and r["frame"] not in dec]
    if open_flags:
        add("auto", "todo", _("有 {p1} 張「判斷錯了」的畫面還沒回答", p1=len(open_flags)),
            _("回答後會變成考題,下次學習時也能檢查有沒有改善。"), "/review?origin=runtime", _("去回答"))
    if open_unsure:
        add("teach", "todo", _("腳本執行時存下 {p1} 張拿不準的畫面", p1=len(open_unsure)),
            _("模型在這些畫面上沒把握。回答後大部分拿去學習、少部分當考題,比每天錄影更有效。"), "/review?origin=runtime", _("去回答"))

    order = {"warn": 0, "todo": 1, "info": 2}
    steps.sort(key=lambda x: order.get(x["level"], 3))
    if project.edition() == "runtime":            # a runtime has no design pages: only what can be done here
        steps = [x for x in steps if (x["link"] or "").split("?")[0] in ("", "/", "/script", "/sources", "/panel", "/packs")]
    return {"steps": steps, "todo": sum(1 for x in steps if x["level"] in ("todo", "warn"))}


# ---------------- sessions / samples ----------------
@app.get("/api/sessions")
def sessions_list():
    return data.sessions()


def _label_value(lab, sid):
    """A state's automatic label (a ratio state's may be stored as <id>_ratio)."""
    return lab.get(sid, lab.get(f"{sid}_ratio")) if lab else None


def _label_brief(lab):
    if not lab:
        return None
    ids = [s["id"] for s in schema_mod.load(DATA_ROOT)["states"]]
    return {"values": {sid: _label_value(lab, sid) for sid in ids}, "flags": lab.get("flags", []), "scores": lab.get("scores")}


@app.get("/api/samples")
def samples_list(session: str, device: str, offset: int = 0, limit: int = Query(120, le=500),
                 state: str = "", value: str = "", flag: str = "", trigger: str = "", reviewed: str = ""):
    try:
        items = sorted(data.samples(session, device), key=lambda s: s["t_req"])   # pre_touch frames are appended late
    except ValueError as e:
        _bad(e)
    labels = data.labels()
    dec = review.decisions()
    out = []
    for s in items:
        lab = labels.get((session, device, s["id"]))
        frame = data.rel(os.path.join(data.device_dir(session, device), s.get("frame") or f"frames/{s['id']}.png"))
        if state and value and str(_label_value(lab, state)) != value:     # one state's automatic label
            continue
        if flag and (not lab or flag not in lab.get("flags", [])):
            continue
        if trigger and not s.get("trigger", "").startswith(trigger):
            continue
        if reviewed and (frame in dec) != (reviewed == "1"):
            continue
        out.append({"id": s["id"], "t": s["t_req"], "trigger": s.get("trigger"), "frame": frame,
                    "label": _label_brief(lab), "reviewed": frame in dec})
    return {"total": len(out), "offset": offset, "items": out[offset:offset + limit]}


@app.get("/api/find")
def find_frame(q: str):
    """Find frames by id (full or partial, also accepts a pasted file name / path)."""
    import re
    m = re.search(r"\d{6,}", q)
    if not m:
        _bad(_("請輸入畫面編號(一串數字),例如 1760000000000"))
    key = m.group(0)
    out = []
    for s in data.sessions():
        for dv in s["devices"]:
            try:
                for smp in data.samples(s["id"], dv["name"]):
                    if key in smp["id"]:
                        out.append({"session": s["id"], "device": dv["name"], "id": smp["id"], "t": smp["t_req"]})
            except ValueError:
                continue
            if len(out) >= 20:
                return out
    return out


@app.get("/api/sample")
def sample_detail(session: str, device: str, id: str):
    try:
        items = sorted(data.samples(session, device), key=lambda s: s["t_req"])
    except ValueError as e:
        _bad(e)
    ids = [s["id"] for s in items]
    if id not in ids:
        _bad(_("找不到這個樣本"), 404)
    i = ids.index(id)
    s = items[i]
    t = s["t_req"]
    frame = data.rel(os.path.join(data.device_dir(session, device), s.get("frame") or f"frames/{s['id']}.png"))
    ev = data.events(session, device)
    et = [e["t"] for e in ev]
    near_ev = ev[bisect.bisect_left(et, t - 5):bisect.bisect_right(et, t + 5)]
    near_touch = [x for x in data.touches(session, device) if abs(x["t_down"] - t) <= 5]
    recs = _recorders().values()
    shown = [e for e in near_ev if not any(hasattr(r, "hide_event") and r.hide_event(e) for r in recs)]
    recorded = [d for r in recs if hasattr(r, "describe_sample") for d in [r.describe_sample(s)] if d]
    return {"sample": s, "recorded": recorded, "frame": frame, "label": data.labels().get((session, device, id)),
            "review": review.decisions().get(frame),
            "prev": ids[i - 1] if i > 0 else None, "next": ids[i + 1] if i + 1 < len(ids) else None,
            "index": i, "count": len(ids),
            "events": shown[:80],
            "touches": [{k: x.get(k) for k in ("t_down", "t_up", "kind", "action", "x0", "y0", "x1", "y1", "duration")}
                        for x in near_touch]}


@app.get("/api/image")
def image(path: str, thumb: int = 0, view: int = 0):
    """view=1: full-size JPEG copy (fast, for answering questions); thumb=<width>: small JPEG; else the PNG."""
    try:
        p = data.view_image(path) if view else data.thumbnail(path, thumb) if thumb else data.abs_path(path)
    except ValueError as e:
        _bad(e)
    except FileNotFoundError:
        _bad(_("找不到圖片"), 404)
    if not os.path.exists(p):
        _bad(_("找不到圖片"), 404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


class WarmImages(BaseModel):
    paths: list[str]


_warm_pool = None


@app.post("/api/image/warm")
def image_warm(req: WarmImages):
    """Make the JPEG copies of the next questions in the background, so they are ready when asked."""
    global _warm_pool
    from concurrent.futures import ThreadPoolExecutor
    if _warm_pool is None:
        _warm_pool = ThreadPoolExecutor(2, thread_name_prefix="warm")
    for p in req.paths[:50]:
        try:
            data.abs_path(p)
        except ValueError:
            continue
        _warm_pool.submit(data.view_image, p)
    return {"queued": min(len(req.paths), 50)}


# ---------------- labels ----------------
@app.get("/api/labels")
def labels_versions():
    return data.label_versions()


class LabelRun(BaseModel):
    sessions: list[str] = []


@app.post("/api/labels/run")
def labels_run(req: LabelRun):
    args = ["labeler", "--data", DATA_ROOT]
    for s in req.sessions:
        args += ["--session", s]
    try:
        j = jobs.start("labeler", args, _("產生標籤"))
    except RuntimeError as e:
        _bad(e)
    return j.info()


# ---------------- state definitions (label schema) ----------------
import schema as schema_mod


def _state_ids():
    return {s["id"] for s in schema_mod.load(DATA_ROOT)["states"]}


@app.get("/api/states")
def states_current():
    return {"schema": schema_mod.load(DATA_ROOT), "history": schema_mod.history(DATA_ROOT)}


@app.get("/api/states/judge")
def states_judge(run: str = ""):
    """How each state is judged while scripts run: by the model or by its screen rule. Uses the model the running
    script runner loaded, else the given training run, else the newest finished one (the runner's default)."""
    from runtime import judge
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    live = None
    if st.get("running") and time.time() - st.get("updated", 0) < 10 and st.get("model"):
        live = os.path.dirname(st["model"])
    d = live or (_run_dir(run) if run else judge.latest_run(DATA_ROOT))
    out = judge.sources(schema_mod.load(DATA_ROOT), d)
    out["running"] = bool(live)
    return out


# ---------------- how the model does while it runs, and whether to train again ----------------
RETRAIN_ANSWERS = 50          # new answers since the last training: worth training again
RETRAIN_DAYS = 7              # ... or this old with at least RETRAIN_MIN_ANSWERS new ones
RETRAIN_MIN_ANSWERS = 15


def _questions_since(t0):
    """Frames the runner saved as questions (unsure / disagreeing) since t0, and how many are still unanswered."""
    answered = set(review.decisions())
    saved = []
    for d in glob.glob(os.path.join(WORK_ROOT, "sessions", "shadow_*")):
        day = os.path.basename(d)[7:]
        if day < time.strftime("%Y%m%d", time.localtime(t0)):
            continue
        for f in glob.glob(os.path.join(d, "devices", "*", "frames", "*.png")):
            try:
                if int(os.path.basename(f)[:-4]) / 1000 >= t0:
                    saved.append(project.rel_of(f, DATA_ROOT))
            except ValueError:
                pass
    return len(saved), sum(1 for f in saved if f not in answered)


@app.get("/api/quality")
def quality_get(hours: int = Query(24, ge=1, le=24 * 14)):
    """Per state: how sure the running model has been (last `hours`, per hour and per emulator) next to what this
    model usually does; and whether it is time to train again."""
    from runtime import judge, quality as q
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    run_dir = os.path.dirname(st["model"]) if st.get("model") else judge.latest_run(DATA_ROOT)
    model = os.path.basename(run_dir) if run_dir else None
    qdir = os.path.join(RUNTIME_DIR, "quality")
    rows = q.read(qdir, max(q.BASELINE_DAYS, hours // 24 + 1), model) if model else []
    cut = time.time() - hours * 3600
    names = {x["id"]: x["name"] for x in schema_mod.load(DATA_ROOT)["states"]}
    by = {}
    for r in rows:
        by.setdefault(r["state"], []).append(r)
    states = []
    for sid, rs in sorted(by.items(), key=lambda kv: names.get(kv[0], kv[0])):
        recent = [r for r in rs if r["t"] >= cut]
        usual = [r for r in rs if r["t"] < cut - q.RECENT * q.BUCKET] or rs
        hourly = {}
        for r in recent:
            hourly.setdefault(int(r["t"] // 3600) * 3600, []).append(r)
        devs = {}
        for r in recent:
            devs.setdefault(r["device"], []).append(r)
        states.append({"id": sid, "name": names.get(sid, sid), "recent": q.rates(recent), "usual": q.rates(usual),
                       "hours": [{"t": t, **q.rates(v)} for t, v in sorted(hourly.items())],
                       "devices": {d: q.rates(v) for d, v in sorted(devs.items())}})
    # train again?
    run = os.path.basename(run_dir) if run_dir else None
    run_st = _read_json(os.path.join(run_dir, "status.json"), {}) if run_dir else {}
    started = run_st.get("started") or 0
    answers = sum(1 for e in review.decisions().values() if (e.get("reviewed_at") or 0) > started) if started else 0
    saved, unanswered = _questions_since(started) if started else (0, 0)
    days = (time.time() - started) / 86400 if started else None
    worse = [s["name"] for s in states if s["recent"]["n"] and s["usual"]["n"] >= q.BASELINE_MIN_N and s["recent"]["low"] is not None
             and s["recent"]["low"] >= max(q.LOW_ABS, (s["usual"]["low"] or 0) * q.LOW_FACTOR + 0.05)]
    reasons = []
    if answers >= RETRAIN_ANSWERS:
        reasons.append(_("上次訓練後又答了 {answers} 題", answers=answers))
    elif days is not None and days >= RETRAIN_DAYS and answers >= RETRAIN_MIN_ANSWERS:
        reasons.append(_("上次訓練已經 {days} 天,這段時間答了 {answers} 題", days=format(days, '.0f'), answers=answers))
    if worse:
        reasons.append(_("執行中信心變差的狀態:") + _("、").join(worse) + _("(先補答再訓練)"))
    return {"model": run, "hours": hours, "conf_low": q.CONF_LOW, "states": states,
            "retrain": {"run": run, "started": started, "days": days, "answers": answers, "saved": saved, "unanswered": unanswered,
                        "suggest": bool(reasons), "reasons": reasons,
                        "rule": _("答了 {RETRAIN_ANSWERS} 題以上,或超過 {RETRAIN_DAYS} 天且答了 {RETRAIN_MIN_ANSWERS} 題以上,或有狀態信心變差", RETRAIN_ANSWERS=RETRAIN_ANSWERS, RETRAIN_DAYS=RETRAIN_DAYS, RETRAIN_MIN_ANSWERS=RETRAIN_MIN_ANSWERS)}}


@app.get("/api/states/urgent_check")
def states_urgent_check(ids: str = ""):
    """Are the states read by urgent rules (or the given ones, comma separated) judged reliably enough?"""
    from . import urgent
    j = states_judge()
    sids = [x for x in ids.split(",") if x] if ids else None
    return {"min_acc": urgent.MIN_ACC, "min_n": urgent.MIN_N, "states": urgent.check(DATA_ROOT, j.get("states") or {}, sids)}


@app.get("/api/states/progress")
def states_progress():
    """Each state's learning rail: defined -> judged automatically -> enough test questions -> model passed."""
    from . import progress
    return progress.progress()


@app.get("/api/states/v/{version}")
def states_version(version: int):
    try:
        return schema_mod.load(DATA_ROOT, version)
    except FileNotFoundError:
        _bad(_("沒有這個版本"), 404)


class SchemaSave(BaseModel):
    states: list[dict]
    note: str = ""


@app.post("/api/states")
def states_save(req: SchemaSave):
    try:
        return schema_mod.save(DATA_ROOT, {"states": req.states}, note=req.note)
    except ValueError as e:
        _bad(e)


class SchemaRestore(BaseModel):
    version: int
    note: str = ""


@app.post("/api/states/restore")
def states_restore(req: SchemaRestore):
    old = schema_mod.load(DATA_ROOT, req.version)
    return schema_mod.save(DATA_ROOT, {"states": old["states"]}, note=req.note or _("還原為 v{version}", version=req.version))


def _all_frames():
    """(session, device) -> [relative frame path] in time order, for every recorded frame (labelled or not)."""
    groups = {}
    for sp in glob.glob(os.path.join(WORK_ROOT, "sessions", "*", "devices", "*", "samples.jsonl")):
        d = os.path.dirname(sp)
        session, device = os.path.basename(os.path.dirname(os.path.dirname(d))), os.path.basename(d)
        fr = []
        for smp in sorted(data.samples(session, device), key=lambda x: x["t_req"]):
            rel = data.rel(os.path.join(d, smp.get("frame") or f"frames/{smp['id']}.png"))
            if os.path.exists(project.resolve(rel, DATA_ROOT)):
                fr.append(rel)
        if fr:
            groups[(session, device)] = fr
    return groups


@app.get("/api/frames/browse")
def frames_browse(session: str, device: str, offset: int = 0, limit: int = Query(24, le=96)):
    """Frames of one session/device in time order (to find a rare moment, e.g. while a side panel was collapsed)."""
    fr = _all_frames().get((session, device), [])
    return {"total": len(fr), "offset": offset, "items": fr[offset:offset + limit]}


@app.get("/api/frames/random")
def frames_random(n: int = Query(12, le=48), seed: int = 0):
    """Random frames for previewing crop regions, spread over sessions and devices (including unlabelled ones)."""
    import random
    groups = {k: list(v) for k, v in _all_frames().items()}
    rnd = random.Random(seed)
    keys = list(groups)
    rnd.shuffle(keys)
    out = []
    while len(out) < n and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop(rnd.randrange(len(groups[k]))))
    return out


# ---------------- name galleries (labeler/gallery.py) ----------------
def _matcher(sid):
    from labeler import gallery
    st = schema_mod.state(schema_mod.load(DATA_ROOT), sid)
    if not st or st.get("source", {}).get("kind") != "gallery":
        _bad(_("找不到這個名稱庫"), 404)
    return gallery.Matcher(DATA_ROOT, st)


@app.get("/api/galleries")
def galleries_list():
    from labeler import gallery
    return {"galleries": [{"id": s["id"], "name": s["name"]} for s in gallery.states(schema_mod.load(DATA_ROOT))],
            "cuts": tr(gallery.cuts())}


@app.get("/api/galleries/{sid}")
def gallery_info(sid: str):
    from labeler import gallery
    m, v = _matcher(sid), data.latest_label_version()
    clusters = []
    path = gallery.clusters_path(os.path.join(WORK_ROOT, "labels", v), sid) if v else None
    if path and os.path.exists(path):
        for c in json.load(open(path, encoding="utf-8")):
            clusters.append({**c, "rep": data.rel(c["rep"]), "examples": [data.rel(p) for p in c["examples"]]})
    counts = {}                                       # frames per name in the latest labels
    for r in data.labels().values():
        if r.get(sid):
            counts[r[sid]] = counts.get(r[sid], 0) + 1
    items = [{"file": f, **meta} for f, meta in sorted(m.index.items(), key=lambda kv: kv[1]["name"])]
    names = sorted({e["name"] for e in m.index.values() if e["name"] != gallery.NOT_A_NAME})
    return {"id": sid, "name": m.name, "version": v, "gallery": items, "clusters": clusters, "names": names,
            "counts": counts, "not_a_name": gallery.NOT_A_NAME, "row": [m.y0, m.y1]}


class GalleryName(BaseModel):
    frame: str
    ext: list[int]
    name: str


@app.post("/api/galleries/{sid}/name")
def gallery_name(sid: str, req: GalleryName):
    m, name = _matcher(sid), req.name.strip()
    if not name or len(req.ext) != 2 or not (0 <= req.ext[0] < req.ext[1] <= project.screen()[0]):
        _bad(_("名稱不可空白,範圍要正確"))
    img = np.array(Image.open(data.abs_path(req.frame)).convert("RGB"))
    return {"file": m.add(img, tuple(req.ext), name)}


class GalleryEdit(BaseModel):
    file: str
    name: str | None = None


@app.post("/api/galleries/{sid}/rename")
def gallery_rename(sid: str, req: GalleryEdit):
    m = _matcher(sid)
    if req.file not in m.index or not (req.name or "").strip():
        _bad(_("找不到這筆或名稱空白"))
    m.rename(req.file, req.name.strip())
    return {"ok": True}


@app.post("/api/galleries/{sid}/delete")
def gallery_delete(sid: str, req: GalleryEdit):
    m = _matcher(sid)
    if req.file not in m.index:
        _bad(_("找不到這筆"))
    m.remove(req.file)
    return {"ok": True}


@app.get("/api/galleries/{sid}/image/{name}")
def gallery_image(sid: str, name: str):
    p = os.path.join(_matcher(sid).dir, os.path.basename(name))
    if not os.path.exists(p):
        _bad(_("找不到圖片"), 404)
    return FileResponse(p)


# ---------------- review / test set ----------------
def _runtime_saved():
    """Frames saved while scripts ran: automatically (the model was unsure) and "judged wrong" flags."""
    out = []
    for name, origin in (("uncertain.jsonl", "uncertain"), ("flags.jsonl", "flag")):
        p = os.path.join(SHADOW_DIR, name)
        if os.path.exists(p):
            for r in data.read_jsonl(p):
                out.append({**r, "origin": origin})
    return out


def _tidy_now():
    """The last tidy result, only when made with the model in use now (else None: the saved reasons count)."""
    from runtime import judge, tidy
    run = judge.latest_run(DATA_ROOT)
    return tidy.load(DATA_ROOT, os.path.basename(run)) if run else None


def _start_tidy(note=""):
    """Look at the unanswered saved frames again with the current model (runtime/tidy.py), in the background."""
    if jobs.running("tidy"):
        return jobs.running("tidy")
    return jobs.start("tidy", ["runtime.tidy", "--data", DATA_ROOT], _("整理題目") + note)


@app.get("/api/review/queue")
def review_queue():
    dec = review.decisions()
    cands = data.review_candidates()
    labels = data.labels()
    ids = _state_ids()
    items = []
    for c in cands:
        lab = labels.get((c["session"], c["device"], c["id"])) or c
        items.append({"frame": data.rel(c["frame"]), "session": c["session"], "device": c["device"], "id": c["id"],
                      "origin": "testset", "use": "test",
                      "rule": {**{k: v for k, v in lab.items() if k in ids}, "flags": lab.get("flags", [])}})
    seen = {it["frame"] for it in items}
    put_aside = review.dismissed()
    from runtime import tidy as tidy_mod
    tidy = _tidy_now()
    for r in _runtime_saved():
        if r["frame"] in seen or (r["frame"] in put_aside and not dec.get(r["frame"])):
            continue
        seen.add(r["frame"])
        lab = labels.get((r["session"], r["device"], r["id"]))
        items.append({"frame": r["frame"], "session": r["session"], "device": r["device"], "id": r["id"],
                      "origin": r["origin"], "t": r.get("t"), "reasons": r.get("reasons", []),
                      "ask": tidy_mod.asks(r, tidy) if r["origin"] == "uncertain" else None,
                      "use": review.use_for(r["id"]) if r["origin"] == "uncertain" else "test",
                      "auto_from": "label" if lab else "model", "conf": r.get("conf") or {},
                      "rule": {**{k: v for k, v in (lab or r.get("pred") or {}).items() if k in ids},
                               "flags": (lab or {}).get("flags", [])}})
    from . import urgent
    hot = urgent.urgent_states(DATA_ROOT)
    for it in items:
        it["decision"] = dec.get(it["frame"])
        it["needs_human"] = review.needs_human(it["decision"])
        it["urgent_states"] = sorted({r["state"] for r in it.get("reasons") or [] if r.get("state") in hot})
    # frames about states that urgent rules read come first: their mistakes cost the most
    items.sort(key=lambda it: it["origin"] != "testset" and not it["urgent_states"])
    runtime = [it for it in items if it["origin"] != "testset"]
    return {"version": data.latest_label_version(), "total": len(items),
            "done": sum(1 for it in items if it["decision"]),
            "needs_human": sum(1 for it in items if it["needs_human"]),
            "runtime_todo": sum(1 for it in runtime if not it["decision"] and (it["ask"] is None or it["ask"])),
            "put_aside": len(put_aside), "items": items}


# which questions are worth answering now (the ones the model is weakest on first)
PRIO_LEVELS = ("suggest", "ok", "later")
PRIO_WORDS = {"suggest": N_("建議"), "ok": N_("可以"), "later": N_("不急")}
THIN = 15                 # fewer answers of one kind than this: a 100% test says little
LOW_CONF = 0.8            # below this the screen rule backs the model up at run time: worth an answer
ROUND = 20                # questions picked for one round (answer them, retrain, look again)
ROUND_GAP = 60.0          # picked frames of one emulator at least this many seconds apart (near frames teach nothing new)


def _needed_conf():
    from runtime import tidy
    return tidy.needed_conf(DATA_ROOT)


def _pick_round(todo, sid, need):
    """The frames worth answering this round for one state: the model below what the scripts need, least sure first,
    spread out (one emulator: >= ROUND_GAP s apart) and over the values the model guessed (so not all one answer)."""
    import collections
    def disagreed(r):        # model and screen rule said different things: the answer decides whom to believe next time
        return any(x.get("state") == sid and x.get("kind") == "disagree" for x in r.get("reasons") or [])
    hard = [r for r in todo if r.get("_looked") or disagreed(r)
            or (isinstance((r.get("conf") or {}).get(sid), (int, float)) and r["conf"][sid] < need)]
    by_guess = collections.defaultdict(list)
    for r in sorted(hard, key=lambda r: (not disagreed(r), (r.get("conf") or {}).get(sid, 1))):
        by_guess[json.dumps((r.get("pred") or {}).get(sid))].append(r)
    picked, last = [], collections.defaultdict(list)
    lists = list(by_guess.values())
    while len(picked) < ROUND and any(lists):
        for lst in lists:                                  # round robin over the guessed values
            while lst:
                r = lst.pop(0)
                if all(abs(r.get("t", 0) - t) >= ROUND_GAP for t in last[r["device"]]):
                    picked.append(r)
                    last[r["device"]].append(r.get("t", 0))
                    break
            if len(picked) >= ROUND:
                break
    return [r["frame"] for r in picked], len(hard)


def _priorities():
    """Per review state: how much answering it helps now. -> [{"state", "name", "level", "why", "answers",
    "per_class", "acc", "holdout_acc", "source", "unsure_todo", "todo"}] most useful first."""
    import collections
    import schema as schema_mod
    from runtime import judge
    sch = schema_mod.load(DATA_ROOT)
    src = judge.sources(sch, judge.latest_run(DATA_ROOT))["states"]
    dec = review.test_decisions()
    alld = review.decisions()
    put_aside = review.dismissed()
    runtime = [r for r in _runtime_saved() if r["origin"] == "uncertain"]
    from runtime import tidy as tidy_mod
    tidy = _tidy_now()
    if tidy:            # what the current model says now (the saved confidence is the old model's)
        tf = tidy["frames"]
        runtime = [{**r, "conf": {**(r.get("conf") or {}), **tf[r["frame"]]["conf"]},
                    "pred": {**(r.get("pred") or {}), **tf[r["frame"]]["pred"]}, "_looked": True} if r["frame"] in tf else r
                   for r in runtime]
    needs = _needed_conf()
    # a frame's confidence is that of the model running when it was saved: only frames saved since the current model
    # tell what it is weak at now (older ones may well be known by now)
    run = judge.latest_run(DATA_ROOT)
    since = (judge.model_time(run) or 0) if run else 0
    out = []
    for st in sch["states"]:
        if st["type"] != "class" or not (st.get("review") or {}).get("enabled"):
            continue
        sid = st["id"]
        values = [c["value"] for c in st.get("classes") or [] if c["value"] != "hidden"]
        per = collections.Counter(str(d["answers"][sid]) for d in dec.values() if sid in d.get("answers", {}))
        n = sum(per.values())
        low = [c["name"] for c in st["classes"] if c["value"] in values and per.get(str(c["value"]), 0) < judge.MIN_PER_CLASS]
        s = src.get(sid) or {}
        acc, hold = s.get("acc"), s.get("holdout_acc")
        # the frames that still ask this state, unanswered and not put aside
        todo = [r for r in runtime if not alld.get(r["frame"]) and r["frame"] not in put_aside and sid in tidy_mod.asks(r, tidy)]
        # looked at again with the current model (tidied), or saved while it ran
        cur = [r for r in todo if r.get("_looked") or r.get("t", 0) >= since]
        unsure = sum(1 for r in cur if any(x.get("state") == sid for x in r.get("reasons") or []))
        confs = sorted(float(r["conf"][sid]) for r in cur if isinstance((r.get("conf") or {}).get(sid), (int, float)))
        low_conf = sum(1 for c in confs if c < LOW_CONF)          # frames the model was not really sure about
        need = needs.get(sid)                                     # what the scripts ask for (None: no script reads it)
        best, stuck = _pick_round(cur, sid, need) if need else ([], 0)
        why = []
        if s.get("source") == "rule":
            why.append(_("模型還沒學會(執行時用畫面規則)") if s.get("test") is None else _("模型還沒通過考試"))
        if n < judge.MIN_ANSWERS:
            why.append(_("考題只有 {n} 題(要 {MIN_ANSWERS})", n=n, MIN_ANSWERS=judge.MIN_ANSWERS))
        if low:
            why.append(_("「{names}」不到 {MIN_PER_CLASS} 題", names=_("」、「").join(low), MIN_PER_CLASS=judge.MIN_PER_CLASS))
        if acc is not None and acc < 0.95:
            why.append(_("模型考試 {acc}", acc=format(acc, '.0%')))
        if hold is not None and hold < 0.95:
            why.append(_("沒看過的{p1} {hold}", p1=project.word("device"), hold=format(hold, '.0%')))
        thin = [_("「{name}」只有 {p2} 題", name=c['name'], p2=per.get(str(c['value']), 0)) for c in st["classes"]
                if c["value"] in values and judge.MIN_PER_CLASS <= per.get(str(c["value"]), 0) < THIN]
        if need and stuck >= ROUND:
            why.append(_("{stuck} 張低於腳本要的信心 {need}", stuck=stuck, need=format(need, '.2f')))
        disagreed = sum(1 for r in cur if any(x.get("state") == sid and x.get("kind") == "disagree" for x in r.get("reasons") or []))
        if disagreed >= 3:                  # answering these decides whether the model or the rule is believed when they differ
            why.insert(0, _("{disagreed} 張模型和畫面規則意見不同(答了才知道該信誰)", disagreed=disagreed))
        level = "suggest" if why else "ok" if (acc is not None and acc < 0.98) or unsure >= 20 or low_conf >= 20 or thin else "later"
        if level == "ok" and not why:
            why.append(_("模型考試 {acc}", acc=format(acc, '.0%')) if acc is not None and acc < 0.98 else _("、").join(thin) + _(",考試看不太出來") if thin
                       else _("{p1} 張模型沒把握", p1=max(unsure, low_conf)))
        if level == "later":
            why.append(_("模型考試 {acc},考題 {n} 題", acc=format(acc, '.0%'), n=n) if acc is not None else _("考題 {n} 題", n=n))
        out.append({"state": sid, "name": st["name"], "level": level, "level_text": _(PRIO_WORDS[level]), "why": _(";").join(why),
                    "disagree": disagreed >= 3, "answers": n,
                    "per_class": dict(per), "acc": acc, "holdout_acc": hold, "source": s.get("source"),
                    "unsure_todo": unsure, "todo": len(todo), "low_conf": low_conf,
                    "median_conf": round(confs[len(confs) // 2], 2) if confs else None,
                    "need": need, "stuck": stuck, "best": best})
    out.sort(key=lambda x: (PRIO_LEVELS.index(x["level"]), not x["disagree"], -x["stuck"], -max(x["unsure_todo"], x["low_conf"]), x["answers"]))
    return out


@app.get("/api/review/priorities")
def review_priorities():
    from runtime import judge
    run = judge.latest_run(DATA_ROOT)
    t = _tidy_now()
    aside = review.dismissed()
    why = collections.Counter(v.get("why") if isinstance(v, dict) else "user" for v in aside.values())
    tj = jobs.latest("tidy")
    return {"states": _priorities(), "put_aside": len(aside), "round": ROUND,
            "tidy": {"current": bool(t), "t": t.get("t") if t else None, "learned": why.get("learned", 0),
                     "dupes": why.get("dupe", 0), "user": why.get("user", 0),
                     "job": tj.info(tail=3) if tj else None},
            "model": os.path.basename(run) if run else None,
            "since": judge.model_time(run) if run else None}


class PutAside(BaseModel):
    restore: bool = False


@app.post("/api/review/put_aside")
def review_put_aside(req: PutAside):
    """Tidy the questions (look at the unanswered saved frames again with the current model and put aside the ones
    it has learned and the repeats; runs in the background), or restore = bring every put-aside frame back."""
    if req.restore:
        review.set_dismissed([], on=False)
        return {"put_aside": 0, "job": None}
    try:
        return {"put_aside": len(review.dismissed()), "job": _start_tidy().info(tail=0)}
    except RuntimeError as e:
        _bad(e)


class Decision(BaseModel):
    frame: str
    session: str | None = None
    device: str | None = None
    id: str | None = None
    answers: dict[str, int | str | None] = {}
    skipped: list[str] = []          # questions this frame cannot answer (e.g. covered): asked no more
    use: str | None = None           # "train": a frame saved while scripts ran, answered as training data
    note: str = ""
    deleted: bool = False
    reviewer: str = "human"
    unsure: bool = False
    spot_check: bool = False


@app.post("/api/review/decision")
def review_decide(d: Decision):
    try:
        return review.save(d.model_dump())
    except ValueError as e:
        _bad(e)


class AddQuestions(BaseModel):
    state: str
    n: int = 30
    session: str | None = None
    device: str | None = None


class AnswerOne(BaseModel):
    frame: str
    state: str
    value: int | str | None = None


@app.post("/api/review/answer_one")
def review_answer_one(req: AnswerOne):
    """One state's answer on one frame (the quick answering in a state's page); the frame's other answers stay."""
    try:
        return review.answer_one(req.frame, req.state, req.value)
    except ValueError as e:
        _bad(e)


@app.get("/api/review/answers/{state}")
def review_answers(state: str):
    return review.answers_for(state)


@app.post("/api/review/add_questions")
def review_add_questions(req: AddQuestions):
    """Extra test questions aimed at one state (e.g. a new state the frozen test set never shows)."""
    from . import progress
    try:
        return progress.add_questions(req.state, max(5, min(req.n, 100)), session=req.session or None, device=req.device or None)
    except ValueError as e:
        _bad(e)


@app.get("/api/review/stats")
def review_stats():
    return review.stats()


# ---------------- generic rules (configured on the state-definition page) ----------------
def _load_rgb(rel_frame):
    return np.asarray(Image.open(data.abs_path(rel_frame)).convert("RGB"))


class RulePreview(BaseModel):
    state: dict
    n: int = 24
    seed: int = 0
    context: bool = True       # evaluate the gate state from the latest labels


@app.post("/api/rules/preview")
def rules_preview(req: RulePreview):
    """Run one (possibly unsaved) generic rule on random frames -> value and score per frame."""
    import concurrent.futures
    from labeler import generic
    st = req.state
    if not generic.is_generic(st):
        _bad(_("這個狀態沒有使用通用規則"))
    try:
        generic.validate(st)
    except ValueError as e:
        if st["source"]["rule"] != "color_ratio" or not isinstance(e, generic.Unfinished):
            _bad(e)                                     # allow previewing before thresholds / classes are set
    frames = frames_random(min(req.n, 400), req.seed) if req.n <= 48 else _random_frames(min(req.n, 400), req.seed)
    tpls = generic.load_templates(DATA_ROOT, st) if st["source"]["rule"] in ("template", "digits") else None
    labels = {data.rel(r["frame"]): r for r in data.labels().values()}
    gate = st["source"].get("params", {}).get("gate_state")

    def one(f):
        ctx = {gate: labels.get(f, {}).get(gate)} if gate else None
        v, sc = generic.evaluate(st, _load_rgb(f), tpls, ctx)
        return {"frame": f, "value": v, **sc}

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        return {"items": list(ex.map(one, frames)), "templates": len(tpls or [])}


class GlyphsReq(BaseModel):
    state: dict                # the (possibly unsaved) number state with a digits rule
    frame: str


def _glyphs_of(st, frame):
    from labeler import generic
    if st.get("source", {}).get("rule") != "digits":
        _bad(_("這個狀態不是「讀數字」規則"))
    p = st["source"].get("params") or {}
    box = generic._box(st, p.get("roi"))
    img = _load_rgb(frame)
    return img, generic.glyphs(img, box, p.get("colors"))


@app.post("/api/rules/glyphs")
def rule_glyphs(req: GlyphsReq):
    """The characters a digits rule finds on one frame, and what it reads each as (to teach the wrong ones)."""
    from labeler import generic
    img, gs = _glyphs_of(req.state, req.frame)
    refs = generic.load_templates(DATA_ROOT, req.state)
    out = [{"box": [int(v) for v in b], "char": c, "score": sc} for (b, _x), (c, sc) in zip(gs, generic.read_chars(img, gs, refs))]
    v, info = generic.eval_digits(req.state, img, refs)
    return {"glyphs": out, "text": info["text"], "value": v, "taught": len(refs)}


class GlyphTeach(GlyphsReq):
    index: int
    char: str


@app.post("/api/rules/glyph")
def rule_glyph_teach(req: GlyphTeach):
    import re
    from labeler import generic
    sid = req.state.get("id") or ""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", sid):
        _bad(_("狀態代號不正確"))
    if len(req.char) != 1 or req.char not in generic.CHARS:
        _bad(_("只能教這些字元:{CHARS}", CHARS=generic.CHARS))
    img, gs = _glyphs_of(req.state, req.frame)
    if not 0 <= req.index < len(gs):
        _bad(_("找不到這個字元,請重新整理"))
    name = generic.glyph_add(DATA_ROOT, sid, req.char, img, gs[req.index][0], req.frame)
    return rule_glyphs(GlyphsReq(state=req.state, frame=req.frame)) | {"file": name}


def _random_frames(n, seed):
    import random
    all_frames = sorted(f for fr in _all_frames().values() for f in fr)
    return random.Random(seed).sample(all_frames, min(n, len(all_frames)))


@app.get("/api/rules/templates/{state_id}")
def rule_templates(state_id: str):
    from labeler import generic
    idx = generic.tpl_index(DATA_ROOT, os.path.basename(state_id))
    return [{"file": k, **v} for k, v in sorted(idx.items(), key=lambda kv: kv[1]["created"])]


@app.get("/api/rules/templates/{state_id}/{name}")
def rule_template_image(state_id: str, name: str):
    from labeler import generic
    p = os.path.join(generic.tpl_dir(DATA_ROOT, os.path.basename(state_id)), os.path.basename(name))
    if not os.path.exists(p):
        _bad(_("找不到參考圖"), 404)
    return FileResponse(p)


class RuleTemplateNew(BaseModel):
    state_id: str
    value: int | str
    frame: str
    box: list[int]


@app.post("/api/rules/templates")
def rule_template_add(req: RuleTemplateNew):
    import re
    from labeler import generic
    if not re.fullmatch(r"[a-z][a-z0-9_]*", req.state_id):
        _bad(_("狀態代號不正確"))
    x, y, w, h = req.box
    W, H = project.screen()
    if not (len(req.box) == 4 and w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= W and y + h <= H):
        _bad(_("範圍不正確"))
    name = generic.tpl_add(DATA_ROOT, req.state_id, req.value, _load_rgb(req.frame), req.box, req.frame)
    return {"file": name}


@app.delete("/api/rules/templates/{state_id}/{name}")
def rule_template_delete(state_id: str, name: str):
    from labeler import generic
    try:
        generic.tpl_delete(DATA_ROOT, os.path.basename(state_id), os.path.basename(name))
    except ValueError as e:
        _bad(e, 404)
    return {"deleted": name}


# ---------------- training ----------------
MODELS_DIR = project.models_dir()


def _valid_run_id(run_id):
    """<date>_<time>[_<name>]; the name may be Chinese, but never a path"""
    import re
    return bool(re.fullmatch(r"[0-9]{8}_[0-9]{6}(_.+)?", run_id)) and os.path.basename(run_id) == run_id \
        and "/" not in run_id and ".." not in run_id


def _run_dir(run_id):
    if not _valid_run_id(run_id):
        _bad(_("訓練編號格式不對"))
    d = os.path.join(MODELS_DIR, run_id)
    if not os.path.isdir(d):
        _bad(_("找不到這次訓練"), 404)
    return d


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _run_brief(run_id):
    d = os.path.join(MODELS_DIR, run_id)
    cfg = _read_json(os.path.join(d, "config.json"), {})
    st = _read_json(os.path.join(d, "status.json"), {})
    ev = _read_json(os.path.join(d, "eval.json"))
    job = jobs.running("train")
    if st.get("state") in ("loading", "training", "evaluating") and not (job and st.get("updated", 0) >= job.started - 5):
        st["state"] = "stopped"                        # the process ended without finishing (stopped or crashed)
    return {"id": run_id, "config": cfg.get("config"), "created": cfg.get("created"), "device": cfg.get("device"),
            "splits": {k: v["frames"] for k, v in (cfg.get("dataset") or {}).get("splits", {}).items()},
            "labels_version": (cfg.get("dataset") or {}).get("labels_version"),
            "schema_version": (cfg.get("dataset") or {}).get("schema_version"),
            "status": st,
            "result": {k: {"model_acc": v.get("model_acc"), "rule_acc": (v.get("rule") or {}).get("acc_overall"),
                           "test_mae": v.get("test_mae"), "holdout_acc": ((v.get("by_group") or {}).get("holdout") or {}).get("acc")}
                       for k, v in (ev or {}).get("heads", {}).items()} if ev else None}


@app.get("/api/train/preview")
def train_preview(holdout: str = "", neighbor: float = 1.0):
    from trainer import data as tdata
    tdata.NEIGHBOR_SECONDS = neighbor
    try:
        ds = tdata.build(DATA_ROOT, [h for h in holdout.split(",") if h])
    except RuntimeError as e:
        _bad(e)
    out = tdata.summary(ds)
    out["all_devices"] = sorted({i["device"] for i in ds["items"]})
    out["labels_status"] = tdata.labels_status(DATA_ROOT)
    lj = jobs.running("labeler")
    out["labeling"] = lj.info(tail=0) if lj else None
    labeled = {i["session"] for i in ds["items"]}
    sess_dir = os.path.join(WORK_ROOT, "sessions")
    out["unlabeled_sessions"] = sorted(d for d in os.listdir(sess_dir)
                                       if d not in labeled and glob.glob(os.path.join(sess_dir, d, "devices", "*", "frames", "*.png")))
    return out


class TrainConfig(BaseModel):
    name: str = ""
    epochs: int = 20
    width: int = 640
    height: int = 360
    batch: int = 16
    lr: float = 1e-3
    pretrained: bool = False
    holdout: list[str] = []
    neighbor_seconds: float = 1.0
    augment: bool = True
    seed: int = 0
    relabel: bool = True           # update the labels first when they are out of date


def _can_train():
    """The full edition has PyTorch; the runtime-only one (requirements-runtime.txt) runs ONNX models only."""
    import importlib.util
    return importlib.util.find_spec("torch") is not None


@app.post("/api/train/start")
def train_start(c: TrainConfig):
    if not _can_train():
        _bad(_("這是純執行版,沒有安裝訓練需要的 PyTorch(pip install -r requirements.txt)"))
    if not (1 <= c.epochs <= 200 and 64 <= c.width <= project.screen()[0] and 36 <= c.height <= project.screen()[1] and 1 <= c.batch <= 128):
        _bad(_("設定超出範圍"))
    if jobs.running("labeler"):
        _bad(_("標籤正在產生中,完成後再開始訓練"))
    try:
        def after(job):
            if job.status == "done":            # the new model may know some of the questions now
                job.lines.append(_("訓練完成,用新模型重新整理題目…"))
                _start_tidy(_("(訓練後自動)"))
        j = jobs.start("train", ["trainer", "--data", DATA_ROOT, "--config-json", json.dumps(c.model_dump(), ensure_ascii=False)],
                       _("訓練模型"), on_exit=after)
    except RuntimeError as e:
        _bad(e)
    return j.info()


@app.post("/api/train/stop")
def train_stop():
    j = jobs.running("train")
    if j:
        j.stop()
    return {"stopped": bool(j)}


@app.get("/api/train/runs")
def train_runs():
    if not os.path.isdir(MODELS_DIR):
        return {"runs": [], "job": None}
    ids = sorted((d for d in os.listdir(MODELS_DIR) if os.path.isdir(os.path.join(MODELS_DIR, d))), reverse=True)
    j = jobs.latest("train")
    return {"runs": [_run_brief(i) for i in ids], "job": j.info(tail=60) if j else None}


@app.get("/api/train/runs/{run_id}")
def train_run(run_id: str):
    d = _run_dir(run_id)
    metrics = data.read_jsonl(os.path.join(d, "metrics.jsonl")) if os.path.exists(os.path.join(d, "metrics.jsonl")) else []
    cfg = _read_json(os.path.join(d, "config.json"), {})
    ev = _read_json(os.path.join(d, "eval.json"))
    from runtime import judge
    tests = {k: dict(zip(("result", "reason"), judge.model_test(h))) for k, h in ((ev or {}).get("heads") or {}).items()}
    return {**_run_brief(run_id), "dataset": cfg.get("dataset"), "heads": cfg.get("heads"), "metrics": metrics,
            "eval": ev, "tests": tests}


@app.delete("/api/train/runs/{run_id}")
def train_delete(run_id: str):
    import shutil
    d = _run_dir(run_id)
    j = jobs.running("train")
    if j and _run_brief(run_id)["status"].get("state") in ("loading", "training", "evaluating"):
        _bad(_("這次訓練還在進行,請先停止"))
    shutil.rmtree(d)
    return {"deleted": run_id}


# ---------------- scripts (no-code automation) ----------------
@app.get("/api/scripts")
def scripts_list():
    """Main scripts (in priority order), the sub-script library and everything the editor needs."""
    import automation
    from automation import buttons, conds, engine, lists, settings as user_settings, subs, templates
    names = engine.names_from_schema(schema_mod.load(DATA_ROOT))
    scripts, lib = automation.load_all(DATA_ROOT), subs.load_all(DATA_ROOT)
    return {"scripts": scripts, "order": [s["id"] for s in scripts],
            "subs": [{**s, "outline": subs.outline(s.get("steps"), names, lib, s.get("params"))} for s in lib.values()],
            "sub_layout": subs.layout(DATA_ROOT),
            "settings": list(user_settings.load(DATA_ROOT).values()),
            "lists": [{"id": x["id"], "title": x.get("title") or x["id"], "per_device": bool(x.get("per_device")),
                       "open_sub": x.get("open_sub"), "ready_text": x.get("ready_text")} for x in lists.load(DATA_ROOT).values()],
            "used_by": subs.used_by(DATA_ROOT, scripts, lib),
            "modes": tr(automation.MODES), "actions": tr(automation.ACTIONS), "ops": conds.op_labels(),
            "cond_kinds": conds.kind_labels(), "variables": automation.variables(DATA_ROOT),
            "buttons": list(buttons.load(DATA_ROOT).values()), "templates": templates.templates(DATA_ROOT),
            "var_modes": tr(automation.VAR_MODES), "var_scopes": tr(automation.VAR_SCOPES, device=project.word("device")), "var_resets": tr(automation.VAR_RESETS),
            "step_types": tr(subs.STEP_TYPES), "param_types": tr(subs.PARAM_TYPES), "cleanup_steps": sorted(subs.CLEANUP_STEPS),
            "step_groups": [(_(g), ids) for g, ids in subs.STEP_GROUPS], "after_steps": sorted(subs.AFTER_STEPS), "on_fail": tr(subs.ON_FAIL),
            "outputs": [{"id": o["id"], "name": o["name"]} for o in outputs_mod.load(DATA_ROOT).values()]}


# ---------------- button library ----------------
def _button_users(bid):
    """Where a button is used (scripts and sub-scripts)."""
    import automation
    from automation import subs
    needle = f'"button": "{bid}"'
    out = [_("主腳本「{name}」", name=s['name']) for s in automation.load_all(DATA_ROOT) if needle in json.dumps(s, ensure_ascii=False)]
    out += [_("子腳本「{name}」", name=s['name']) for s in subs.load_all(DATA_ROOT).values() if needle in json.dumps(s, ensure_ascii=False)]
    from automation import schedules
    out += [_("排程「{name}」", name=s['name']) for s in schedules.load(DATA_ROOT) if needle in json.dumps(s, ensure_ascii=False)]
    return out


class ButtonSave(BaseModel):
    button: dict
    snap: str | None = None          # cut a find button's picture from this device's snapshot
    frame: str | None = None         # ... or from this recorded frame


@app.post("/api/buttons")
def buttons_save(req: ButtonSave):
    from automation import buttons
    img = None
    if req.snap:
        p = os.path.join(RUNTIME_DIR, "snaps", os.path.basename(req.snap) + ".png")
        if not os.path.exists(p):
            _bad(_("沒有這台{p1}的畫面,請重新擷取", p1=project.word("device")))
        img = np.asarray(Image.open(p).convert("RGB"))
    elif req.frame:
        try:
            img = np.asarray(Image.open(data.abs_path(req.frame)).convert("RGB").resize(project.screen()))
        except (ValueError, OSError):
            _bad(_("讀不到這張畫面"))
    try:
        return buttons.save(DATA_ROOT, req.button, img)
    except ValueError as e:
        _bad(e)


@app.delete("/api/buttons/{bid}")
def buttons_delete(bid: str):
    from automation import buttons
    try:
        buttons.delete(DATA_ROOT, os.path.basename(bid), _button_users(bid))
    except ValueError as e:
        _bad(e)
    return {"deleted": bid}


@app.get("/api/buttons/{bid}/image")
def buttons_image(bid: str):
    from automation import buttons as buttons_mod
    p = buttons_mod.image_path(DATA_ROOT, os.path.basename(bid))
    if not os.path.exists(p):
        _bad(_("這個按鈕沒有圖片"), 404)
    return FileResponse(p, headers={"Cache-Control": "no-store"})


class SnapReq(BaseModel):
    device: str


def _snap_frame(name):
    """One device's frame now, in full size (through the running loop)."""
    out = os.path.join(RUNTIME_DIR, "snaps", name + ".png")
    before = os.path.getmtime(out) if os.path.exists(out) else 0
    os.makedirs(os.path.join(RUNTIME_DIR, "snap_requests"), exist_ok=True)
    open(os.path.join(RUNTIME_DIR, "snap_requests", name + ".json"), "w").close()
    for _x in range(50):
        if os.path.exists(out) and os.path.getmtime(out) > before:
            time.sleep(0.05)
            return np.asarray(Image.open(out).convert("RGB"))
        time.sleep(0.1)
    raise ValueError(_("等不到這台{p1}的畫面(視窗可能縮到最小)", p1=project.word("device")))


class ListCapture(BaseModel):
    list: str
    device: str


@app.get("/api/lists")
def lists_get():
    """The scrolling lists that can be captured (accounts, places...) and what is in them."""
    from automation import lists
    out = []
    for spec in lists.load(DATA_ROOT).values():
        out.append({k: spec.get(k) for k in ("id", "title", "group", "per_device", "ready_text", "open_sub")})
    return {"lists": out}


@app.post("/api/lists/capture")
def lists_capture(req: ListCapture):
    """Walk one list on one emulator's screen and save every new name as a button."""
    from automation import lists
    from automation.executor import Executor
    spec = lists.load(DATA_ROOT).get(req.list)
    if not spec:
        _bad(_("沒有這個清單"))
    if not _runner_live():
        _bad(_("腳本執行沒有在跑,沒辦法擷取{p1}的畫面(到「執行」開始)", p1=project.word("device")))
    name = os.path.basename(req.device)
    ex = Executor()

    def swipe(x, y1, y2):
        ex.submit(name, "swipe", x1=x, y1=y1, x2=x, y2=y2, ms=900).result(timeout=15)
        time.sleep(0.3)
    try:
        r = lists.capture(DATA_ROOT, spec, name, lambda: _snap_frame(name), swipe,
                          lambda x, y: ex.submit(name, "tap", x=x, y=y).result(timeout=15))
    except ValueError as e:
        _bad(e)
    return {"new": [b["id"] for b in r["new"]], "known": r["known"]}


@app.post("/api/buttons/snap")
def buttons_snap(req: SnapReq):
    """Ask the running loop for one device's frame in full size (to pick a button on it); waits for it."""
    name = os.path.basename(req.device)
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    if not st.get("running") or time.time() - st.get("updated", 0) > 10:
        _bad(_("腳本執行沒有在跑,沒辦法擷取{p1}現在的畫面(可以改用錄過的畫面)", p1=project.word("device")))
    out = os.path.join(RUNTIME_DIR, "snaps", name + ".png")
    before = os.path.getmtime(out) if os.path.exists(out) else 0
    os.makedirs(os.path.join(RUNTIME_DIR, "snap_requests"), exist_ok=True)
    open(os.path.join(RUNTIME_DIR, "snap_requests", name + ".json"), "w").close()
    for _x in range(50):
        if os.path.exists(out) and os.path.getmtime(out) > before:
            return {"device": name, "updated": os.path.getmtime(out)}
        time.sleep(0.1)
    _bad(_("等不到這台{p1}的畫面(視窗可能縮到最小)", p1=project.word("device")))


@app.get("/api/buttons/snap/{device}")
def buttons_snap_image(device: str):
    p = os.path.join(RUNTIME_DIR, "snaps", os.path.basename(device) + ".png")
    if not os.path.exists(p):
        _bad(_("沒有畫面"), 404)
    return FileResponse(p, headers={"Cache-Control": "no-store"})


class RunSub(BaseModel):
    device: str
    sub: str
    args: dict = {}


@app.post("/api/shadow/run_sub")
def shadow_run_sub(req: RunSub):
    """Run one sub-script once on one device now (testing). Real input: the device must not be stopped or paused."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]*", req.sub):
        _bad(_("子腳本代號不正確"))
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    if not st.get("running") or time.time() - st.get("updated", 0) > 10:
        _bad(_("腳本執行沒有在跑,請先到「執行」開始執行"))
    dv = next((x for x in st.get("devices") or [] if x["name"] == req.device), None)
    if dv and dv.get("hold"):
        _bad(_("這台") + (_("暫停中") if dv["hold"].get("mode") == "pause" else _("停下來中")) + _(",先按「繼續」"))
    d = os.path.join(RUNTIME_DIR, "sub_requests")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, os.path.basename(req.device) + ".json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"sub": req.sub, "args": req.args}, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    return {"queued": True}


class Act(BaseModel):
    device: str
    kind: str                               # schedule | sub | situation | stop | pause | resume  (device "*" = all for
                                            # stop / pause / resume)
    id: str | None = None                   # schedule
    sub: str | None = None                  # sub
    args: dict = {}
    script: str | None = None               # situation
    situation: str | None = None
    mode: str | None = None                 # stop: "stop" / "hold" (停下來: cancel, nothing acts until 繼續) | "pause"
                                            # (暫停: hold what it does where it is) | "abort" (only end what it does now)
    if_busy: str = "ask"                    # the device is running something: "ask" (just say so) | "interrupt" | "queue"


def _act_check(req: Act):
    """What is wrong with a page action, or None. Shared by the monitor and the operation panel."""
    import re
    from automation import schedules as sm, subs as subm
    import automation
    if req.kind not in ("schedule", "sub", "situation", "stop", "pause", "resume"):
        return _("不支援的操作")
    if req.if_busy not in ("ask", "interrupt", "queue"):
        return _("if_busy 要是 ask / interrupt / queue")
    if not _runner_live():
        return _("腳本執行沒有在跑,請先到「執行」開始執行")
    if req.kind in ("stop", "pause", "resume"):
        return None
    if req.device == "*":
        return _("請選擇是哪一台")
    if req.kind == "schedule":
        s = next((x for x in sm.effective(DATA_ROOT, RUNTIME_DIR) if x["id"] == req.id), None)
        if not s:
            return _("找不到這個排程(先儲存)")
        if req.device not in (s.get("devices") or []):
            return _("排程「{name}」沒有包含 {device}", name=s['name'], device=req.device)
    if req.kind == "sub" and (not re.fullmatch(r"[a-z][a-z0-9_]*", req.sub or "") or req.sub not in subm.load_all(DATA_ROOT)):
        return _("找不到這個子腳本")
    if req.kind == "situation":
        sc = next((x for x in automation.load_all(DATA_ROOT) if x["id"] == req.script), None)
        if not sc or not any(x["id"] == req.situation for x in sc.get("situations") or []):
            return _("找不到這個腳本或情境")
    return None


def _act_send(req: Act, by: str):
    """-> {"queued": True} or {"busy": what the device is doing} (if_busy = ask)."""
    err = _act_check(req)
    if err:
        _bad(err)
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    dev = next((d for d in st.get("devices") or [] if d["name"] == req.device), None) if req.device != "*" else {}
    if dev is None:
        _bad(_("找不到 {device}", device=req.device))
    proc = dev.get("proc")
    if proc and req.if_busy == "ask" and req.kind not in ("stop", "pause", "resume", "situation"):
        return {"queued": False, "busy": {"name": proc.get("script_name"), "sub": proc.get("sub_name"), "now": proc.get("now"),
                                          "loop": proc.get("loop"), "schedule": (proc.get("script") or "").startswith("schedule:")}}
    d = os.path.join(RUNTIME_DIR, "act_requests")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{time.time_ns()}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({**req.model_dump(), "if_busy": "queue" if req.if_busy == "ask" else req.if_busy, "by": by, "t": time.time()},
                  f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    return {"queued": True}


@app.post("/api/shadow/act")
def shadow_act(req: Act):
    """Do something on one emulator now, from the monitor: run a schedule / a sub-script, switch a main script to a
    situation, stop or pause what it is doing, carry on a paused schedule."""
    return _act_send(req, _("監看"))


@app.get("/api/shadow/actions/{device}")
def shadow_actions(device: str):
    """What can be started on this emulator: its schedules (with today's status), its main scripts' situations."""
    import automation
    from automation import schedules as sm
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    today = {x["id"]: x["devices"].get(device) for x in st.get("schedules") or []}
    scheds = [{"id": s["id"], "name": s["name"], "enabled": s.get("enabled", True), "at": s.get("at"),
               "status": today.get(s["id"])} for s in sm.effective(DATA_ROOT, RUNTIME_DIR) if device in (s.get("devices") or [])]
    scripts = []
    for sc in automation.load_all(DATA_ROOT):
        if automation.is_guard(sc) or automation.mode_for(sc, device) == "off" or len(sc.get("situations") or []) < 2:
            continue
        scripts.append({"id": sc["id"], "name": sc["name"],
                        "situations": [{"id": x["id"], "name": x["name"], "enter": bool(x.get("on_enter"))} for x in sc["situations"]]})
    return {"device": device, "schedules": scheds, "scripts": scripts}


class TemplateReq(BaseModel):
    template: str


@app.post("/api/scripts/template")
def scripts_from_template(req: TemplateReq):
    """A fresh copy of a template to edit (not saved)."""
    import automation
    from automation import subs, templates
    lib = subs.load_all(DATA_ROOT)
    try:
        return templates.make(req.template, automation.ids(DATA_ROOT) + list(lib), lib,
                              schema_mod.load(DATA_ROOT)["states"], DATA_ROOT)
    except ValueError as e:
        _bad(e)


class Variables(BaseModel):
    vars: list[dict]


@app.post("/api/variables")
def variables_save(req: Variables):
    """Variable definitions (counters, "last time ..."), used by conditions and the "設定變數" action."""
    import automation
    try:
        return {"vars": automation.save_variables(DATA_ROOT, req.vars)}
    except ValueError as e:
        _bad(e)


class VarSet(BaseModel):
    var: str
    value: float
    device: str | None = None        # for a variable kept per emulator


@app.post("/api/shadow/vars")
def shadow_var_set(req: VarSet):
    """Change a variable's current value; the running loop picks it up within a tick."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]*", req.var):
        _bad(_("變數代號不正確"))
    d = os.path.join(RUNTIME_DIR, "var_requests")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{time.time_ns()}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"var": req.var, "value": req.value, "device": req.device}, f)
    os.replace(p + ".tmp", p)
    return {"queued": True}


# ---------------- replay: run the scripts over a recording ----------------
class ReplayStart(BaseModel):
    session: str
    device: str
    start: float = 0                 # seconds from the start of the recording
    minutes: float = 30
    script: dict | None = None       # an unsaved script to use instead of the saved one with the same id
    sub_result: str = "success"


@app.post("/api/replay")
def replay_start(req: ReplayStart):
    import re
    if not re.fullmatch(r"[\w\-]+", req.session) or not re.fullmatch(r"[\w\-]+", req.device):
        _bad(_("錄製或{p1}名稱不正確", p1=project.word("device")))
    if req.sub_result not in ("success", "fail") or not 0 < req.minutes <= 240:
        _bad(_("設定不正確(最多重播 240 分鐘)"))
    rid = f"{time.strftime('%Y%m%d_%H%M%S')}_{req.device}"
    d = os.path.join(RUNTIME_DIR, "replays")
    os.makedirs(d, exist_ok=True)
    inp = os.path.join(d, f"{rid}.input.json")
    with open(inp, "w", encoding="utf-8") as f:
        json.dump({"id": rid, **req.model_dump()}, f, ensure_ascii=False)
    try:
        j = jobs.start("replay", ["runtime.replay", "--input", inp, "--data", DATA_ROOT, "--fast-dir", RUNTIME_DIR], _("腳本重播"))
    except RuntimeError as e:
        _bad(e)
    return {"id": rid, "job": j.id}


@app.get("/api/replay/{rid}")
def replay_result(rid: str):
    """The replay's result, or how far the job is."""
    p = os.path.join(RUNTIME_DIR, "replays", os.path.basename(rid) + ".json")
    if os.path.exists(p):
        return {"status": "done", "result": _read_json(p)}
    j = jobs.latest("replay")
    if j and rid in " ".join(j.args):
        return {"status": j.status, "log": list(j.lines)[-3:]}
    _bad(_("找不到這次重播"), 404)


# ---------------- the script spec (JSON view / edit) ----------------
@app.get("/api/spec")
def spec_info():
    from automation import spec, spec_schema
    return {"format": spec.FORMAT, "kinds": tr(spec_schema.KINDS)}


@app.get("/api/spec/schema/{kind}")
def spec_schema_get(kind: str):
    from automation import spec_schema
    try:
        return spec_schema.schema(kind)
    except KeyError:
        _bad(_("沒有這種文件"), 404)


class SpecCheck(BaseModel):
    kind: str
    doc: Any


@app.post("/api/spec/check")
def spec_check(req: SpecCheck):
    """Check one document (e.g. edited as JSON) against the script spec and the platform's own checks."""
    from automation import spec_schema
    if req.kind not in ("script", "sub"):
        _bad(_("目前可以檢查主腳本和子腳本"))
    if not isinstance(req.doc, dict):
        return {"ok": False, "errors": [{"path": _("(整份)"), "message": _("最外層要是一個物件 { … }")}]}
    errs = spec_schema.check(req.kind, req.doc, DATA_ROOT)
    return {"ok": not errs, "errors": errs}


# ---------------- share sub-scripts (automation/share.py) ----------------
class ShareExport(BaseModel):
    subs: list[str]
    with_calls: bool = True


@app.post("/api/share/export")
def share_export(req: ShareExport):
    from automation import share
    if not req.subs:
        _bad(_("請選擇要分享的子腳本"))
    try:
        return share.export(DATA_ROOT, req.subs, req.with_calls)
    except ValueError as e:
        _bad(e)


class ShareBundle(BaseModel):
    bundle: Any
    plan: dict = {}


@app.post("/api/share/analyze")
def share_analyze(req: ShareBundle):
    from automation import share
    try:
        return share.analyze(DATA_ROOT, req.bundle)
    except ValueError as e:
        _bad(e)


@app.post("/api/share/import")
def share_import(req: ShareBundle):
    from automation import share
    try:
        return share.apply(DATA_ROOT, req.bundle, req.plan)
    except ValueError as e:
        _bad(e)


# ---------------- outputs: where scripts send things besides the screen ----------------
def _outputs_info():
    return {"outputs": list(outputs_mod.load(DATA_ROOT).values()),
            "types": {k: {"label": _(getattr(t, "label", k)), "fields": tr(getattr(t, "fields", {}))} for k, t in outputs_mod.types().items()}}


@app.get("/api/outputs")
def outputs_list():
    return _outputs_info()


class OutputsSave(BaseModel):
    outputs: list[dict]


@app.put("/api/outputs")
def outputs_save(req: OutputsSave):
    from drivers import sources
    keep = {o.get("id") for o in req.outputs}
    used = [sources.label(it["id"], DATA_ROOT) for it in sources.load(DATA_ROOT)["items"]
            if (it.get("hand") or {}).get("to") == "output" and it["hand"].get("id") not in keep]
    if used:
        _bad(_("這個輸出是「{p1}」的動作要送去的地方,先到「來源」改掉再刪", p1=_("、").join(used)))
    try:
        outputs_mod.save(DATA_ROOT, req.outputs)
    except ValueError as e:
        _bad(e)
    return _outputs_info()


class OutputTest(BaseModel):
    id: str


@app.post("/api/outputs/test")
def outputs_test(req: OutputTest):
    """Send one test message to an output (the user pressed 測試)."""
    try:
        status = outputs_mod.send(DATA_ROOT, req.id, {"device": "test", "script": _("測試"), "command": "test", "value": None}).result(timeout=15)
    except Exception as e:
        _bad(_("送不出去:{e}", e=e))
    return {"ok": True, "status": status}


# ---------------- script tests: a recording + what the scripts should do on it ----------------
def _tests_info():
    from automation import tests as tm
    names = tm.Names(DATA_ROOT)
    results = _read_json(os.path.join(RUNTIME_DIR, "tests", "results.json"), {}) or {}
    tests = [{**t, "expect_text": [tm.describe(e, names) for e in t.get("expect") or []], "last": results.get(t["id"])}
             for t in tm.load(DATA_ROOT)]
    j = jobs.latest("tests")
    return {"tests": tests, "job": j.info(tail=40) if j else None, "kinds": tr(tm.KINDS),
            "scripts": [{"id": sc["id"], "name": sc["name"],
                         "situations": [{"id": x["id"], "name": x["name"]} for x in sc.get("situations") or []],
                         "rules": [{"id": r["id"], "name": r.get("name") or r["id"]} for x in sc.get("situations") or []
                                   for r in x.get("rules") or []]} for sc in names.scripts.values()],
            "subs": [{"id": k, "name": v.get("name", k)} for k, v in names.subs.items()]}


@app.get("/api/tests")
def tests_list():
    return _tests_info()


class TestsSave(BaseModel):
    tests: list[dict]


@app.put("/api/tests")
def tests_save(req: TestsSave):
    from automation import tests as tm
    keep = ("id", "name", "description", "session", "device", "start", "minutes", "sub_result", "sub_results", "expect")
    try:
        tm.save(DATA_ROOT, [{k: t[k] for k in keep if k in t} for t in req.tests])
    except (ValueError, TypeError) as e:
        _bad(e)
    return _tests_info()


class TestFromReplay(BaseModel):
    replay: str
    name: str


@app.post("/api/tests/from_replay")
def tests_from_replay(req: TestFromReplay):
    """A new test from a replay the user looked at: its recording, and what happened as the expectations."""
    from automation import tests as tm
    res = _read_json(os.path.join(RUNTIME_DIR, "replays", os.path.basename(req.replay) + ".json"), None)
    if not res:
        _bad(_("找不到這次重播"), 404)
    if res.get("draft"):
        _bad(_("這次重播用的是還沒儲存的腳本;請先儲存腳本、再重播一次,才能存成測試"))
    inp = _read_json(os.path.join(RUNTIME_DIR, "replays", os.path.basename(req.replay) + ".input.json"), {}) or {}
    tests = tm.load(DATA_ROOT)
    taken = {t["id"] for t in tests}
    tid = next(f"test_{i}" for i in range(1, 10000) if f"test_{i}" not in taken)
    t = {"id": tid, "name": req.name.strip() or tid, "description": "",
         "session": res["session"], "device": res["device"],
         "start": res.get("start", inp.get("start", 0)), "minutes": res.get("minutes", inp.get("minutes", 30)),
         "sub_result": res.get("sub_result", "success"), "sub_results": res.get("sub_results") or {},
         "expect": tm.suggest(res, tm.Names(DATA_ROOT))}
    try:
        tm.save(DATA_ROOT, tests + [t])
    except ValueError as e:
        _bad(e)
    return {"id": tid, **_tests_info()}


class TestsRun(BaseModel):
    ids: list[str] = []


@app.post("/api/tests/run")
def tests_run(req: TestsRun):
    args = ["runtime.replaytest", "--data", DATA_ROOT, "--fast-dir", RUNTIME_DIR]
    for i in req.ids:
        args += ["--id", i]
    try:
        j = jobs.start("tests", args, _("腳本測試"))
    except RuntimeError as e:
        _bad(e)
    return j.info()


# ---------------- timeline of what the runner did on one device ----------------
@app.get("/api/shadow/timeline")
def shadow_timeline(device: str, minutes: float = 60):
    """Situation switches, inputs, sub-script steps, alerts and decision changes of one device (newest first)."""
    import datetime
    since = time.time() - minutes * 60
    out = []
    for day in sorted({datetime.date.fromtimestamp(since), datetime.date.today()}):
        p = os.path.join(SHADOW_DIR, "log", f"{day:%Y%m%d}.jsonl")
        if os.path.exists(p):
            for r in data.read_jsonl(p):
                if r.get("t", 0) >= since and (r.get("device") == device or (r.get("action") == "alert" and not r.get("device"))):
                    out.append({k: r.get(k) for k in ("t", "action", "executed", "script_name", "rule_name", "text", "reason",
                                                      "level", "mode", "var", "old", "new")})
    return out[::-1][:2000]


class ScriptOrder(BaseModel):
    order: list[str]


@app.post("/api/scripts/order")
def scripts_order(req: ScriptOrder):
    """Priority of the main scripts (first = highest): on a device only one acts at a time."""
    import automation
    try:
        automation.set_order(DATA_ROOT, req.order)
    except ValueError as e:
        _bad(e)
    return {"order": automation.order(DATA_ROOT)}


# ---------------- notifications (Discord ...): where to tell people what happened ----------------
@app.get("/api/notify")
def notify_get():
    import notify
    from notify import channels
    return {**notify.masked(RUNTIME_DIR), "kinds": tr(notify.KINDS), "default_kinds": notify.DEFAULT_KINDS, "status": notify.status(RUNTIME_DIR),
            "types": {k: {"label": _(t.LABEL), "help": _(t.HELP), "fields": [{**f, "label": _(f.get("label", "")), "placeholder": _(f.get("placeholder", ""))} for f in t.FIELDS], "listens": bool(getattr(t, "LISTENS", False))}
                      for k, t in channels.types().items()}}


class NotifySave(BaseModel):
    channels: list[dict]
    merge_minutes: int = 10


@app.post("/api/notify")
def notify_save(req: NotifySave):
    import notify
    try:
        return notify.save(RUNTIME_DIR, req.model_dump())
    except ValueError as e:
        _bad(e)


# ---------------- commands from chat (notify/commands.py) ----------------
class _ChatActions:
    """What a chat command may do: the operation panel's design decides (server/panel_chat.py), through the same
    functions the panel's page uses; plus the few safety commands of notify/commands.py."""

    def _status(self):
        return _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}

    def devices(self):
        from . import panel as pm
        from drivers.sources import expand
        return expand(pm.load(DATA_ROOT).get("devices")) or [d["name"] for d in self._status().get("devices") or []]

    def find_devices(self, arg):
        from notify.commands import match_devices
        return match_devices(self.devices(), arg)

    def status_text(self):
        st = self._status()
        if not (st.get("running") and time.time() - st.get("updated", 0) < 10):
            return _("系統沒有在運作")
        ha = st.get("hold_all")
        lines = [(_("🛑 全部暫停中(傳「繼續 全部」恢復)") if ha.get("mode") == "pause" else _("🛑 全部停下來中(傳「繼續 全部」恢復)"))
                 if ha else _("運作中")]
        names = self.devices()
        from drivers.sources import label
        for n in names:
            lines.append(f"{label(n)}:{_device_status(n, st, {})['now']}")
        return "\n".join(lines)

    def act(self, device, kind, by, mode=None, id=None):
        try:
            r = _act_send(Act(device=device, kind=kind, mode=mode, id=id, if_busy="queue"), by)
        except HTTPException as e:
            return str(e.detail)
        return _("已送出") if r.get("queued") else _("正在忙:{name}", name=(r.get('busy') or {}).get('name'))

    def _say(self, by, what):
        print(_("{p1} 聊天指令({by}):{what}", p1=time.strftime('%H:%M:%S'), by=by, what=what), flush=True)

    def hold_all(self, kind, by):
        """停下來 / 暫停 / 繼續 for every source."""
        try:
            _act_send(Act(device="*", kind=kind), by)
        except HTTPException as e:
            return str(e.detail)
        self._say(by, {"stop": _("全部停下來"), "pause": _("全部暫停"), "resume": _("全部繼續")}[kind])
        return {"stop": _("🛑 全部停下來了:正在做的事已取消,不會動作(守門規則也是)。傳「繼續 全部」恢復"),
                "pause": _("⏸ 全部暫停了:正在做的事停在原地。傳「繼續 全部」從同一步接著做"),
                "resume": _("▶ 全部繼續")}[kind]

    def screen(self, device):
        d = os.path.join(RUNTIME_DIR, "live")
        p = os.path.join(d, os.path.basename(device) + ".jpg")
        t0 = time.time()
        try:
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "_asked"), "w").close()    # the runner writes frames for a while (even with live view off)
        except OSError:
            return None
        for _x in range(30):
            if os.path.exists(p) and os.path.getmtime(p) >= t0 - 0.5:
                break
            time.sleep(0.2)
        if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 10:
            return None
        with open(p, "rb") as f:
            return f.read()

    # ---- the operation panel (server/panel_chat.py) ----
    def panel_command(self, text, by):
        from .panel_chat import PanelChat
        return PanelChat(DATA_ROOT, self).run(text, by)

    def help_text(self, builtin):
        from . import panel as pm
        from .panel_chat import help_lines, widget_names
        pnl = pm.load(DATA_ROOT)
        lines = help_lines(pnl)
        w = widget_names(pnl)
        out = builtin
        if w:
            out += _("\n看:") + " · ".join(w)
        if lines:
            out += _("\n操作面板上的(打名稱看現在的值,後面加新的值就是改):\n") + "\n".join(lines)
        return out

    def panel_act(self, c, device, by):
        r = _panel_press(c, device, "queue", False, _("聊天:{by}", by=by))
        from drivers.sources import label
        return "\n".join(f"{label(n)}:{v}" for n, v in r["done"].items()) or _("沒有要做這件事的機台")

    def panel_deploy(self, block, script, device, mode):
        try:
            r = panel_deploy(PanelDeploy(block=block, script=script, device=device, mode=mode))
        except HTTPException as e:
            return str(e.detail)
        import automation
        from drivers.sources import label
        return _("已改好:{p1} {p2} → {p3}", p1=label(device), p2=automation.mode_label(r['old']), p3=automation.mode_label(r['new']))

    def widget_data(self, kind):
        from . import panel as pm
        pnl = pm.load(DATA_ROOT)
        b = pm.widget_blocks(pnl, kind)
        if not b:
            raise ValueError(_("操作面板沒有開放這個"))
        st = _runner_live() or {}
        devices = self.devices()
        cards = [{"device": n, **_device_status(n, st, {}), "today": [], "alerts": []} for n in devices]
        return _widget_data(b[0]["widget"], st, devices, cards, pm)

    def when(self, t):
        return time.strftime("%m/%d %H:%M", time.localtime(t)) if t else ""

    def log_panel(self, c, device, by):
        pass                                             # panel.apply already logs the change (old -> new)


_commander = None


@app.on_event("startup")
def _start_commander():
    global _commander
    from notify.commands import Commander
    _commander = Commander(RUNTIME_DIR, _ChatActions())
    _commander.start()


@app.get("/api/notify/bots")
def notify_bots():
    """Bot channels: connected?, who may give commands, the invite link; the latest commands."""
    import notify
    from notify import channels, commands
    acc = commands.access(RUNTIME_DIR)
    states = _commander.states() if _commander else {}
    out = {}
    for c in notify.load(RUNTIME_DIR).get("channels", []):
        t = channels.types().get(c.get("type"))
        if t is None or not getattr(t, "LISTENS", False):
            continue
        a = acc.get(c["id"]) or {}
        if a.get("chat") and a.get("chat_name") in (None, "", a["chat"]) and hasattr(t, "chat_title") and c.get("enabled"):
            name = t.chat_title(c["config"], a["chat"])  # paired before names were looked up: once
            if name:
                a["chat_name"] = name
                acc[c["id"]] = a
                commands._write(os.path.join(RUNTIME_DIR, commands.ACCESS), acc)
        out[c["id"]] = {"state": states.get(c["id"]), "allowed": a.get("allowed") or [], "chat_name": a.get("chat_name"),
                        "paired": bool(a.get("chat")), "invite": t.invite(c["config"]) if c.get("enabled") else None}
    log = []
    p = os.path.join(RUNTIME_DIR, commands.LOG)
    if os.path.exists(p):
        log = data.read_jsonl(p)[-30:][::-1]
    return {"bots": out, "log": log}


class NotifyPair(BaseModel):
    id: str
    user: str | None = None


@app.post("/api/notify/pair")
def notify_pair(req: NotifyPair):
    if not _commander:
        _bad(_("指令服務還沒啟動"))
    code, secs = _commander.pair_code(req.id)
    return {"code": code, "seconds": secs}


@app.post("/api/notify/unpair")
def notify_unpair(req: NotifyPair):
    if not _commander or not req.user:
        _bad(_("請指定要移除的人"))
    _commander.unpair(req.id, req.user)
    return notify_bots()


class NotifyTest(BaseModel):
    id: str


@app.post("/api/notify/test")
def notify_test(req: NotifyTest):
    """Send a test message through one saved channel now (with a small picture, as an urgent event would)."""
    import notify
    c = next((x for x in notify.load(RUNTIME_DIR).get("channels", []) if x["id"] == req.id), None)
    if not c:
        _bad(_("請先儲存這個通知管道"))
    img = None
    st = _runner_live() or {}
    for d in st.get("devices") or []:
        p = os.path.join(RUNTIME_DIR, "live", d["name"] + ".jpg")
        if os.path.exists(p):
            with open(p, "rb") as f:
                img = f.read()
            break
    try:
        notify.send_now(c, {"kind": "info", "device": None, "t": time.time(),
                            "text": _("這是測試訊息:之後緊急事件、失敗、腳本的「通知」都會送到這裡。") + (_("(附上一台{p1}現在的畫面)", p1=project.word("device")) if img else "")}, img)
    except Exception as e:
        _bad(_("送出失敗:{e}", e=e))
    return {"sent": True}


# ---------------- user settings (the parameters a design opens to its users) ----------------
@app.get("/api/settings")
def settings_get():
    """Declarations, where each is passed, and the values chosen so far (per emulator)."""
    from automation import settings as us
    from . import panel as pm
    st = _runner_live() or {}
    decls = list(us.load(DATA_ROOT).values())
    # the emulators: as the runner sees them, else the panel's, else the ones the defaults name
    devices = [d["name"] for d in st.get("devices") or []] or pm.load(DATA_ROOT).get("devices")         or sorted({d for s in decls for d in s.get("device_default") or {}})
    cur = {s["id"]: ({n: us.value(DATA_ROOT, RUNTIME_DIR, s["id"], n) for n in devices} if s.get("scope") == "device"
                     else {"*": us.value(DATA_ROOT, RUNTIME_DIR, s["id"])}) for s in decls}
    chosen = us.values(RUNTIME_DIR)
    choices = {s["id"]: ({n: us.choices(DATA_ROOT, s, n) for n in devices} if s.get("scope") == "device" else {"*": us.choices(DATA_ROOT, s)})
               for s in decls if s.get("pick_from")}
    from automation import lists
    return {"settings": decls, "types": tr(us.TYPES), "items": tr(us.ITEMS), "scopes": tr(us.SCOPES), "used_by": us.used_by(DATA_ROOT),
            "current": cur, "chosen": {k: sorted(v) for k, v in chosen.items()}, "devices": devices, "choices": choices,
            "lists": [{"id": x["id"], "title": x.get("title") or x["id"], "per_device": bool(x.get("per_device"))} for x in lists.load(DATA_ROOT).values()]}


@app.get("/api/settings/choices")
def settings_choices(pick_from: str, device: str | None = None):
    """What a setting with this source may take (for a declaration not saved yet)."""
    from automation import settings as us
    return {"choices": us.choices(DATA_ROOT, {"pick_from": pick_from}, device) or []}


class SettingsSave(BaseModel):
    settings: list[dict]


@app.post("/api/settings")
def settings_save(req: SettingsSave):
    from automation import settings as us
    try:
        return {"settings": us.save(DATA_ROOT, req.settings)}
    except ValueError as e:
        _bad(e)


class SettingValue(BaseModel):
    id: str
    device: str | None = None
    value: Any = None                       # None = back to the default


@app.post("/api/settings/value")
def settings_value(req: SettingValue):
    from automation import settings as us
    try:
        old, new = us.set_value(DATA_ROOT, RUNTIME_DIR, req.id, req.device, req.value)
    except ValueError as e:
        _bad(e)
    return {"old": old, "new": new}


# ---------------- sub-scripts (called by main scripts, like functions) ----------------
class SubLayout(BaseModel):
    groups: list[dict] = []
    of: dict[str, str] = {}
    order: list[str] = []


@app.post("/api/subscripts/layout")
def subs_layout(req: SubLayout):
    """Groups of the sub-script library and the order inside them (only how the page shows them)."""
    from automation import subs
    try:
        return subs.set_layout(DATA_ROOT, req.model_dump())
    except ValueError as e:
        _bad(e)


class SubSave(BaseModel):
    sub: dict
    note: str = ""


@app.post("/api/subscripts")
def subs_save(req: SubSave):
    from automation import subs
    try:
        return subs.save(DATA_ROOT, req.sub, req.note)
    except ValueError as e:
        _bad(e)


@app.get("/api/subscripts/{sid}/history")
def subs_history(sid: str):
    from automation import subs
    try:
        return subs.history(DATA_ROOT, os.path.basename(sid))
    except FileNotFoundError:
        _bad(_("找不到這個子腳本"), 404)


@app.get("/api/subscripts/{sid}/v/{version}")
def subs_version(sid: str, version: int):
    from automation import subs
    try:
        return subs.load(DATA_ROOT, os.path.basename(sid), version)
    except FileNotFoundError:
        _bad(_("沒有這個版本"), 404)


@app.delete("/api/subscripts/{sid}")
def subs_delete(sid: str):
    from automation import subs
    try:
        subs.delete(DATA_ROOT, os.path.basename(sid))
    except ValueError as e:
        _bad(e)
    return {"deleted": sid}


@app.get("/api/scripts/{sid}/history")
def scripts_history(sid: str):
    import automation
    try:
        return automation.history(DATA_ROOT, os.path.basename(sid))
    except FileNotFoundError:
        _bad(_("找不到這個腳本"), 404)


@app.get("/api/scripts/{sid}/v/{version}")
def scripts_version(sid: str, version: int):
    import automation
    try:
        return automation.load(DATA_ROOT, os.path.basename(sid), version)
    except FileNotFoundError:
        _bad(_("沒有這個版本"), 404)


class ScriptSave(BaseModel):
    script: dict
    note: str = ""


@app.post("/api/scripts")
def scripts_save(req: ScriptSave):
    import automation
    try:
        return automation.save(DATA_ROOT, req.script, req.note)
    except ValueError as e:
        _bad(e)


@app.delete("/api/scripts/{sid}")
def scripts_delete(sid: str):
    import automation
    try:
        automation.delete(DATA_ROOT, os.path.basename(sid))
    except ValueError as e:
        _bad(e, 404)
    return {"deleted": sid}


class ScriptTest(BaseModel):
    script: dict


@app.post("/api/scripts/test")
def scripts_test(req: ScriptTest):
    """Run a (possibly unsaved) script once on the states shadow mode sees right now. "For N seconds" is ignored."""
    import copy
    import automation
    from automation import engine, subs
    sc = automation.normalize(copy.deepcopy(req.script))
    lib = subs.load_all(DATA_ROOT)
    for r in automation.all_rules(sc):
        for g in r.get("when", []):
            for c in g:
                c.pop("for", None)
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    if not st.get("devices"):
        _bad(_("腳本還沒有執行過,沒有現在的畫面狀態可以用"))
    names = engine.names_from_schema(schema_mod.load(DATA_ROOT))
    out = []
    for d in st["devices"]:
        sit = ((d.get("situations") or {}).get(sc["id"]) or {}).get("id")     # the device's situation right now
        dec = engine.evaluate(sc, d.get("state"), engine.Tracker(), names, device=d["name"], subs=lib, situation=sit)
        out.append({"device": d["name"], "state": d.get("state"), **dec})
    return {"updated": st.get("updated"), "running": st.get("running"), "results": out}


# ---------------- shadow mode (runtime) ----------------
SHADOW_DIR = os.path.join(WORK_ROOT, "shadow")


class ShadowStart(BaseModel):
    run: str = ""                  # training run id; empty = newest finished run
    interval: float = 1.0


@app.post("/api/shadow/start")
def shadow_start(req: ShadowStart):
    if req.run and not _valid_run_id(req.run):
        _bad(_("訓練編號格式不對"))
    if req.run and not judge.model_file(os.path.join(MODELS_DIR, req.run)):
        _bad(_("這次訓練沒有模型檔"))
    if not 0.3 <= req.interval <= 10:
        _bad(_("間隔要在 0.3 ~ 10 秒之間"))
    # (a start keeps how it was: stopped / paused devices stay so; the runner waits for a healthy picture first)
    args = ["runtime", "--data", DATA_ROOT, "--interval", str(req.interval), "--fast-dir", RUNTIME_DIR]
    if req.run:
        args += ["--run", req.run]
    try:
        j = jobs.start("shadow", args, _("腳本執行"))
    except RuntimeError as e:
        _bad(e)
    try:                                    # remembered: starting the server with --start-runner starts it the same way
        with open(os.path.join(RUNTIME_DIR, RUNNER_LAST), "w", encoding="utf-8") as f:
            json.dump({"interval": req.interval, "run": req.run, "t": time.time()}, f)
    except OSError:
        pass
    return j.info()


RUNNER_LAST = "runner_last.json"


@app.on_event("startup")
def _start_runner_with_server():
    """python -m server --start-runner (the Windows task does this): the script runner comes back with the server,
    started as it was last time (interval; the model: the one chosen then, or the newest)."""
    if os.environ.get("INSPECTOR_START_RUNNER") != "1":
        return
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    if st.get("running") and time.time() - st.get("updated", 0) < 10:
        print(_("腳本執行已經在跑(可能是另一個 Inspector),這次不再啟動一個"), flush=True)
        return
    last = _read_json(os.path.join(RUNTIME_DIR, RUNNER_LAST), {}) or {}
    try:
        interval = float(last.get("interval") or project.run_defaults(DATA_ROOT).get("interval") or 1.0)
        shadow_start(ShadowStart(interval=interval, run=last.get("run") or ""))
        print(_("腳本執行已啟動(每 {p1} 秒,模型 {p2})", p1=format(interval, 'g'), p2=last.get('run') or _("最新的")), flush=True)
    except HTTPException as e:
        print(_("腳本執行沒有啟動:{detail}", detail=e.detail), flush=True)


class ShadowControl(BaseModel):

    max_per_min: int | None = None
    max_strikes: int | None = None
    manual_pause_s: int | None = None  # after a real touch, don't act on that device for this long (0 = off)
    auto_save: bool | None = None      # save frames the model is unsure about as questions
    auto_save_per_hour: int | None = None
    live_view: bool | None = None      # show the devices' screens on the page
    freeze_seconds: int | None = None  # a source whose picture does not change this long is "frozen" (0 = never)
    start_wait_s: float | None = None  # after a start / a source coming back: seconds with a healthy picture before acting
    unblock: bool = False              # clear paused rules
    resume: dict | None = None         # clear one: {"device", "script", "rule"} (rule None / "(整個腳本)" = a stopped script)


@app.post("/api/shadow/control")
def shadow_control(req: ShadowControl):
    """Settings the running loop reads every tick (limits, pauses, what to save); 停下來 / 暫停 / 繼續 go by /api/shadow/act."""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    p = os.path.join(RUNTIME_DIR, "control.json")
    c = _read_json(p, {}) or {}
    for k in ("max_per_min", "max_strikes", "manual_pause_s", "auto_save", "auto_save_per_hour", "live_view",
              "freeze_seconds", "start_wait_s"):
        v = getattr(req, k)
        if v is not None:
            c[k] = v
    if req.unblock:
        c["unblock"] = time.time()
    if req.resume:
        r = {k: req.resume.get(k) for k in ("device", "script", "rule")}
        c["resume"] = [x for x in (c.get("resume") or []) if time.time() - x.get("t", 0) < 600][-20:] + [{**r, "t": time.time()}]
    if not 1 <= int(c.get("max_per_min", 12)) <= 60 or not 1 <= int(c.get("max_strikes", 3)) <= 10:
        _bad(_("上限設定超出範圍"))
    if not 0 <= int(c.get("manual_pause_s", 60)) <= 3600 or not 1 <= int(c.get("auto_save_per_hour", 20)) <= 200:
        _bad(_("手動暫停秒數要在 0~3600、每小時存檔上限要在 1~200"))
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.replace(tmp, p)
    return c


@app.get("/api/shadow/control")
def shadow_control_get():
    """This computer's settings, over the ones the design recommends (project.json "run")."""
    run = {k: v for k, v in project.run_defaults(DATA_ROOT).items() if k != "interval"}
    return {**run, **(_read_json(os.path.join(RUNTIME_DIR, "control.json"), {}) or {})}


@app.post("/api/shadow/stop")
def shadow_stop():
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    open(os.path.join(RUNTIME_DIR, "stop"), "w").close()     # graceful: the loop checks it every tick
    return {"stopping": True}


def _relang_status(st):
    """The runner writes its fixed words (stopped, paused, who stopped it…) in this machine's language: show them in
    this page's language."""
    import i18n

    def words(d, keys):
        for k in keys:
            if isinstance(d, dict) and isinstance(d.get(k), str):
                d[k] = i18n.relang(d[k])
    devs = st.get("devices") or []
    for dev in devs.values() if isinstance(devs, dict) else devs:
        if not isinstance(dev, dict):
            continue
        for d in dev.get("decisions") or []:
            words(d, ("text", "reason", "exec", "script_name"))
        words(dev.get("health"), ("text",))
        words(dev.get("hold"), ("by",))
    for d in st.get("decisions") or []:
        words(d, ("text", "reason", "exec", "script_name"))
    words(st.get("hold_all"), ("by",))


@app.get("/api/shadow/status")
def shadow_status():
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    j = jobs.latest("shadow")
    if st.get("running") and (not j or j.status != "running") and time.time() - st.get("updated", 0) > 10:
        st["running"] = False                                  # the process ended without cleaning up
    _relang_status(st)
    return {"status": st, "job": j.info(tail=80) if j else None}


@app.get("/api/shadow/live/{name}")
def shadow_live(name: str):
    d = os.path.join(RUNTIME_DIR, "live")
    try:                                    # tells the runner someone is watching (it stops writing frames otherwise)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "_viewed"), "w").close()
    except OSError:
        pass
    p = os.path.join(d, os.path.basename(name) + ".jpg")
    if not os.path.exists(p):
        _bad(_("沒有畫面"), 404)
    return FileResponse(p, headers={"Cache-Control": "no-store"})


# ---------------- schedules ----------------
def _runner_live():
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    return st if st.get("running") and time.time() - st.get("updated", 0) < 10 else None


# ---------------- sign-in (phones on the LAN) ----------------
def _mount_plugin_apis():
    """Each plugin's own API (registry kind "api") at /api/plugins/<name>/."""
    from project.plugins import registry
    for name, router in registry(DATA_ROOT).all("api").items():
        app.include_router(router, prefix=f"/api/plugins/{name}")


_mount_plugin_apis()


class LanguageSet(BaseModel):
    machine: str


@app.get("/api/language")
def language_get():
    """This machine's language (the runtime's log lines and notices) and the languages there are."""
    import i18n
    return {"machine": i18n.default(), "available": i18n.available(), "names": i18n.NAMES}


@app.post("/api/language")
def language_set(req: LanguageSet):
    import i18n
    if req.machine not in i18n.available():
        _bad(_("沒有這個語言"))
    project.set_machine(language=None if req.machine == i18n.BASE else req.machine)
    i18n._machine[0] = 0                               # read it again now
    return language_get()


# ---------------- packs (方案包) and the edition ----------------
def _pack_call(fn, *args, **kw):
    """Run a project.pack function for the page: what it says comes back as lines, a refusal as a 400."""
    lines = []
    try:
        out = fn(*args, say=lambda t: lines.append(str(t)), **kw)
    except SystemExit as e:
        _bad(str(e))
    return out, lines


@app.get("/api/packs")
def packs_list():
    """The installed packs (data folder layout), which one runs, and what this installation is."""
    from project import manifest, pack
    if not project.data_home():
        return {"layout": False, "packs": [], "edition": project.edition(), "platform": manifest.PLATFORM_VERSION}
    items = [{**p, "problems": [{"level": lv, "text": t} for lv, t in p["problems"]]} for p in pack.installed()]
    return {"layout": True, "packs": items, "active": project.active_pack(), "edition": project.edition(),
            "platform": manifest.PLATFORM_VERSION}


@app.post("/api/packs/install")
async def packs_install(request: Request, force: int = 0, activate: int = 0):
    """Install a release the page uploads (the zip itself is the request body), or upgrade to it."""
    from project import pack
    if not project.data_home():
        _bad(_("要先改用資料目錄結構(inspector.json 的 \"data\")才能安裝方案包"))
    body = await request.body()
    if not body or len(body) > 2 * 1024 ** 3:
        _bad(_("請選一個方案包 zip 檔"))
    fd, path = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        out, lines = _pack_call(pack.install, path, None, bool(activate), bool(force))
    finally:
        os.remove(path)
    return {**out, "messages": lines, "restart": out["active"]}


class PackUse(BaseModel):
    id: str


@app.post("/api/packs/use")
def packs_use(req: PackUse):
    from project import pack
    _out, lines = _pack_call(pack.use, req.id)
    return {"messages": lines, "restart": True}


@app.post("/api/system/restart")
def system_restart():
    """Restart Inspector (to load another pack or a newer version): restart_inspector.bat, outside this process."""
    bat = os.path.join(PROJECT_ROOT, "restart_inspector.bat")
    if os.name != "nt" or not os.path.exists(bat):
        _bad(_("這台電腦不能從網頁重新啟動,請自己重新啟動 Inspector"))
    import subprocess
    si = subprocess.STARTUPINFO()                     # its own (minimised) console: the .bat waits with timeout
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7                                # SW_SHOWMINNOACTIVE
    flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                         startupinfo=si, close_fds=True, cwd=PROJECT_ROOT)
    except OSError:
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags, startupinfo=si, close_fds=True, cwd=PROJECT_ROOT)
    return {"ok": True}


@app.get("/api/project")
def project_get():
    """The project: its name, coordinate space, words (the pages read it once when they open)."""
    from project.plugins import registry, ui
    p = project.load(DATA_ROOT)
    reg = registry(DATA_ROOT)
    return {**{k: p[k] for k in ("id", "name", "description", "screen", "words")}, "plugins": reg.loaded, "ui": ui(reg),
            "edition": {"name": project.edition(), "training": _can_train() and project.edition() == "studio"},
            "run": project.run_defaults(DATA_ROOT), "pack": _pack_status()}


def _pack_status():
    """The active pack (data folder layout): its pack.json and what keeps it from running here; None otherwise."""
    from project import manifest
    d = project.pack_dir()
    if not d:
        return None
    info = manifest.read(d) or manifest.normalize({"id": project.active_pack()})
    return {**{k: info.get(k) for k in ("id", "name", "version", "plugin", "requires", "model")},
            "platform": manifest.PLATFORM_VERSION,
            "problems": [{"level": lv, "text": t} for lv, t in manifest.check(info, d)] + _orphan_problems()}


def _orphan_problems():
    """Values set on this computer that point at what the pack no longer has (renamed or removed in a newer version)."""
    from project import renames
    try:
        left = renames.orphans(DATA_ROOT, RUNTIME_DIR)
    except Exception:                                   # never let a bad file hide the pack's status
        return []
    return [{"level": "warn", "text": _("這台電腦設定過的值找不到對應的項目(方案包改名或刪除了):") + "; ".join(
        f"{k} {', '.join(v)}" for k, v in left.items())}] if left else []


@app.get("/api/auth/me")
def auth_me(request: Request):
    from . import access
    host = request.client.host if request.client else ""
    return {"role": getattr(request.state, "role", None), "local": host in access.LOCAL,
            "configured": access.configured(DATA_ROOT), "lan": os.environ.get("INSPECTOR_LAN_URL")}


class Login(BaseModel):
    pin: str


@app.post("/api/auth/login")
def auth_login(req: Login, response: Response):
    from . import access
    token, role = access.login(DATA_ROOT, req.pin)
    if not token:
        _bad(_("PIN 碼不對"))
    response.set_cookie(access.COOKIE, token, max_age=30 * 86400, httponly=True, samesite="lax")
    return {"role": role}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    from . import access
    access.logout(request.cookies.get(access.COOKIE))
    response.delete_cookie(access.COOKIE)
    return {"ok": True}


class Pins(BaseModel):
    user_pin: str | None = None
    admin_pin: str | None = None


@app.post("/api/auth/pins")
def auth_pins(req: Pins):
    from . import access
    try:
        access.set_pins(DATA_ROOT, req.user_pin, req.admin_pin)
    except ValueError as e:
        _bad(e)
    return access.configured(DATA_ROOT)


# ---------------- operation panel (end users) ----------------
# one set of colours everywhere on the panel: tone -> what it means (label: the short word on the emulator's card)
TONES = {"green": N_("正常"), "blue": N_("進行中"), "amber": N_("注意"), "red": N_("要處理"), "grey": N_("已停止")}


def _device_status(n, st, names):
    """What one emulator is doing, in plain words, for the operation panel: {"online", "now", "tone", "label"}.
    green 正常 (idle / its main script's situation) · blue 進行中 (a schedule / sub-script) · amber 注意 (paused,
    someone operating it, picture frozen) · red 要處理 (a rule stopped it, no picture) · grey 已停止 (stopped by a person,
    not used, the system not running)."""
    def out(online, now, tone, label=None):
        return {"online": online, "now": now, "tone": tone, "label": label or _(TONES[tone])}
    d = next((x for x in st.get("devices") or [] if x["name"] == n), None)
    if not st.get("running"):
        return out(False, _("系統沒有在運作"), "grey", _("沒運作"))
    if not d:
        from drivers import sources
        it = next((x for x in sources.load(DATA_ROOT)["items"] if x["id"] == n), None)
        if it is None:
            return out(False, _("沒有這個來源(到「來源」頁加入)"), "grey", _("不使用"))
        if not it.get("enabled"):
            return out(False, _("這台目前不使用(「來源」頁)"), "grey", _("不使用"))
        return out(False, _("看不到這台(沒有開或視窗縮到最小)"), "red", _("看不到"))
    if not d.get("window"):
        return out(False, _("看不到這台的畫面(沒有開或視窗縮到最小)"), "red", _("看不到"))
    hl = d.get("health") or {}
    if hl.get("state") == "lost":
        return out(False, _("沒有畫面(關掉了或斷線)"), "red", _("看不到"))
    if d.get("hold"):
        h = d["hold"]
        if h.get("mode") == "pause":
            return out(True, _("暫停中:按「繼續」從同一步接著做"), "amber", _("暫停中"))
        if h.get("cause"):                                   # a rule stopped it: someone must look
            return out(True, _("被規則停下來:{p1}", p1=h.get('why') or h.get('by')) + (_("(原因還在,先處理再按「繼續」)") if d.get("cause_now") else _("(可以按「繼續」)")),
                       "red", _("要處理"))
        return out(True, _("已停下來:腳本和情境都停住(按「繼續」從頭開始)"), "grey", _("已停下來"))
    if hl.get("state") == "frozen":
        return out(True, _("畫面{p1}", p1=hl.get('text') or _("沒有變化")), "amber", _("畫面卡住"))
    p = d.get("proc")
    if p:
        what = p.get("schedule_name") or p.get("script_name") or ""
        loop = f"({p['loop'].split(' ')[-1].replace('/', ' / ')})" if p.get("loop") else ""
        if p.get("paused"):
            return out(True, _("{what}{loop}暫停中:有人在操作,停手後會自動繼續", what=what, loop=loop), "amber", _("有人操作"))
        return out(True, _("正在進行:{what}{loop}", what=what, loop=loop), "blue")
    if (d.get("manual") or {}).get("paused"):
        return out(True, _("有人在操作這台"), "amber", _("有人操作"))
    sits = [v for v in (d.get("situations") or {}).values() if v.get("count", 1) > 1]
    return out(True, _("、").join(v["name"] for v in sits) if sits else _("待命中"), "green")


@app.get("/api/panel")
def panel_get():
    from . import panel as pm
    from automation import schedules as sm
    pnl = pm.load(DATA_ROOT)
    st = _runner_live() or {}
    from drivers.sources import expand
    devices = _panel_devices(pnl)
    sched_names = {x["id"]: x["name"] for x in sm.load(DATA_ROOT)}
    shown = {c["bind"].get("schedule") for c in pnl.get("controls", []) if c.get("bind", {}).get("schedule")}
    today = {x["id"]: x["devices"] for x in st.get("schedules") or [] if x["id"] in shown}   # only what the panel is about
    out_controls = []
    busy = {d["name"]: d.get("proc") for d in st.get("devices") or []}
    for c in pnl.get("controls", []):
        try:
            if c.get("type") == "action":            # a button: what each emulator is doing (to show progress / stop)
                pm.value(DATA_ROOT, c)
                # the emulators it can act on (a schedule button: only those taking part, so the others get no button)
                tg = pm.act_targets(DATA_ROOT, c, None, devices) if c.get("scope") != "device" else                     [n for n in devices if pm.act_targets(DATA_ROOT, c, n, devices)]
                held = {d["name"]: bool(d.get("hold")) for d in st.get("devices") or []}
                state = {n: ({"name": busy[n].get("schedule_name") or busy[n].get("script_name") or "",
                              "loop": busy[n].get("loop"), "paused": busy[n].get("paused"), "held": held.get(n, False)} if busy.get(n)
                             else {"held": True} if held.get(n) else None)
                         for n in devices}
                out_controls.append({**c, "value": state, "choices": [], "targets": tg})
                continue
            if c.get("scope") == "device":
                mine = [n for n in devices if pm.applies(c, n)]      # the devices it is for: a row / a cell each
                vals = {n: pm.value(DATA_ROOT, c, n) for n in mine}
                opts = {n: pm.options(DATA_ROOT, c, n) for n in mine}
                out_controls.append({**c, "value": vals, "choices": opts, "targets": mine})
                continue
            vals, opts = pm.value(DATA_ROOT, c), pm.options(DATA_ROOT, c, None)
            out_controls.append({**c, "value": vals, "choices": opts})
        except (ValueError, KeyError, OSError) as e:
            out_controls.append({**c, "error": str(e)})
    cards = []
    for n in devices:
        day = [{"name": sched_names.get(sid, sid), "text": devs[n]["text"], "code": devs[n]["code"]}
               for sid, devs in today.items() if n in devs]
        alerts = [{"t": a["t"], "text": a["text"]} for a in (st.get("alerts") or []) if a.get("device") == n][:3]
        p = (busy.get(n) or {}) if busy.get(n) else {}
        prog = {**(p.get("progress") or {}), "name": p.get("schedule_name") or p.get("script_name") or p.get("sub_name") or "",
                "paused": bool(p.get("paused")), "say": p.get("say")} if p else None
        cards.append({"device": n, **_device_status(n, st, sched_names), "today": day, "alerts": alerts, "progress": prog})
    ctrl = _read_json(os.path.join(RUNTIME_DIR, "control.json"), {}) or {}
    blocks = []
    for b in pnl.get("blocks", []):
        if b.get("widget"):
            try:
                b = {**b, "data": _widget_data(b["widget"], st, devices, cards, pm)}
            except (ValueError, KeyError, OSError) as e:
                b = {**b, "error": str(e)}
        blocks.append(b)
    from notify import asks
    todo = _panel_todo(pnl, st, devices, cards, blocks)
    return {"title": pnl.get("title", _("操作面板")), "devices": devices, "controls": out_controls, "cards": cards, "todo": todo,
            "pages": pnl.get("pages") or [], "blocks": blocks, "asks": [q for q in asks.pending(RUNTIME_DIR) if q["device"] in devices],
            "paused": bool(st.get("hold_all")), "paused_mode": (st.get("hold_all") or {}).get("mode"),
            "running": bool(st), "history": pm.history(DATA_ROOT, 20)}


TODO_ACK = "panel_todo_ack.json"
STUCK_HOURS = 24          # screens kept when stuck: shown as to do for this long (until someone says 知道了)


def _panel_devices(pnl):
    """The emulators the panel shows: the ones it names (or every one the runner sees), only those in use - a source
    turned off (not picked in 選擇模擬器) never shows and nothing acts on it."""
    from drivers.sources import expand, load as load_sources
    on = {it["id"] for it in load_sources(DATA_ROOT)["items"] if it.get("enabled")}
    names = expand(pnl.get("devices")) or [d["name"] for d in (_runner_live() or {}).get("devices") or []]
    return [n for n in names if n in on]


def _panel_todo(pnl, st, devices, cards, blocks):
    """What the people at the panel should look at now, the most pressing first: [{"key", "level": bad | warn,
    "device", "text", "detail", "t", "go": {"device"} | {"block"}, "ack": bool (an event: 知道了 hides it),
    "frame": bool}]. States (stopped by a rule, no picture, an open incident, names not seen) go away by themselves
    once they are over; events (a failed schedule, a stuck screen) once someone says 知道了."""
    from automation import lists
    acked = _read_json(os.path.join(RUNTIME_DIR, TODO_ACK), {}) or {}
    by_name = {d["name"]: d for d in st.get("devices") or []}
    out = []
    for c in cards:
        n = c["device"]
        d = by_name.get(n) or {}
        h = d.get("hold") or {}
        if h.get("cause"):                                   # a rule stopped it: someone must look and 繼續
            out.append({"key": f"hold:{n}", "level": "bad", "device": n, "t": h.get("t"),
                        "text": _("被規則停下來了:{p1}", p1=h.get('why') or h.get('by')),
                        "detail": _("原因還在畫面上,先處理再按「繼續」") if d.get("cause_now") else _("原因已經不在了,可以按「繼續」"),
                        "go": {"device": n}})
        hl = d.get("health") or {}
        if st and not c["online"] and n in by_name:
            out.append({"key": f"health:{n}", "level": "bad", "device": n, "text": c["now"], "detail": "", "go": {"device": n}})
        elif hl.get("state") == "frozen":
            out.append({"key": f"health:{n}", "level": "warn", "device": n, "text": _("畫面 {p1}", p1=hl.get('text') or _("沒有變化")),
                        "detail": _("可能當機或停在某個畫面"), "go": {"device": n}})
    for inc in st.get("incidents_open") or []:
        if inc.get("device") in devices:
            out.append({"key": f"incident:{inc.get('id')}", "level": "bad", "device": inc["device"], "t": inc.get("start"),
                        "text": _("緊急事件進行中:") + _("、").join(dict.fromkeys(x for x in inc.get("triggers") or [] if x)),
                        "detail": _("已經解除,等確認結束") if inc.get("resolved") else "",
                        "go": {"block": next((b["id"] for b in blocks if (b.get("widget") or {}).get("kind") == "incidents"), None),
                               "device": inc["device"]}})
    names = {}
    from automation import schedules as sm
    for s in sm.load(DATA_ROOT):
        names[s["id"]] = s["name"]
    for s in st.get("schedules") or []:                      # today's (they start over at the day's reset)
        for n, x in (s.get("devices") or {}).items():
            if n in devices and x.get("code") == "failed":
                key = f"sched:{s['id']}:{n}:{x.get('run') or x.get('text')}"
                if key in acked:
                    continue
                m = re.match(r"^(.*?\d{1,2}:\d{2})[::](.*)$", x.get("text") or "")      # "失敗 15:46:why"
                when, why = (m.group(1), m.group(2)) if m else (x.get("text") or "", "")
                out.append({"key": key, "level": "warn", "device": n, "text": f"{names.get(s['id'], s['id'])} {when}:{why}" if why else f"{names.get(s['id'], s['id'])} {when}",
                            "detail": x.get("detail") or "", "go": {"device": n}, "ack": True})
    p = os.path.join(SHADOW_DIR, "stuck.jsonl")
    if os.path.exists(p):
        since = time.time() - STUCK_HOURS * 3600
        for r in data.read_jsonl(p)[-200:]:
            key = f"stuck:{r['frame']}"
            if r.get("device") in devices and r.get("t", 0) >= since and key not in acked:
                out.append({"key": key, "level": "warn", "device": r["device"], "t": r.get("t"), "text": _("卡住了,存下了當時的畫面"),
                            "detail": r.get("why") or "", "go": {"device": r["device"]}, "ack": True, "frame": r["frame"]})
    for b in blocks:                                         # names of a list not seen in its last walk
        if (b.get("widget") or {}).get("kind") != "list" or not b.get("data"):
            continue
        for n, x in (b["data"].get("by_device") or {}).items():
            miss = [i["label"] for i in x.get("items") or [] if i.get("missing_since")]
            if miss:
                out.append({"key": f"list:{b['id']}:{n}", "level": "warn", "device": None if n == "*" else n,
                            "text": _("{p1}:{p2} 個上次掃描沒看到", p1=b['data'].get('title') or b['title'], p2=len(miss)),
                            "detail": _("、").join(miss[:5]) + ("…" if len(miss) > 5 else "") + _("(先不會輪到;確認後保留或移除)"),
                            "go": {"block": b["id"], "device": None if n == "*" else n}})
    out.sort(key=lambda x: (x["level"] != "bad", -(x.get("t") or 0)))
    return out


class TodoAck(BaseModel):
    keys: list[str]


@app.post("/api/panel/todo/ack")
def panel_todo_ack(req: TodoAck):
    """知道了: an event of the to-do list (a failed schedule, a stuck screen) is hidden for good."""
    p = os.path.join(RUNTIME_DIR, TODO_ACK)
    d = _read_json(p, {}) or {}
    now = time.time()
    d.update({k: now for k in req.keys if isinstance(k, str) and len(k) < 400})
    d = {k: v for k, v in d.items() if now - v < 14 * 86400}          # old ones are gone from the list anyway
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)
    return {"ok": True}


@app.get("/api/panel/stuck_frame")
def panel_stuck_frame(frame: str):
    """A screen kept when a device got stuck (only those in shadow/stuck.jsonl)."""
    p = os.path.join(SHADOW_DIR, "stuck.jsonl")
    if not os.path.exists(p) or not any(r.get("frame") == frame for r in data.read_jsonl(p)):
        _bad(_("沒有這張畫面"), 404)
    f = project.resolve(frame, DATA_ROOT)
    if not os.path.exists(f):
        _bad(_("沒有這張畫面"), 404)
    return FileResponse(f)


def _widget_data(w, st, devices, cards, pm):
    """What a watch widget of the operation panel shows (only what its options let users see)."""
    import automation
    from automation import schedules as sm
    w = {**pm.WIDGET_DEFAULTS[w["kind"]], **w}
    kind = w["kind"]
    by_name = {d["name"]: d for d in st.get("devices") or []}
    if kind == "devices":
        out = []
        for c in cards:
            p = (by_name.get(c["device"]) or {}).get("proc") or {}
            out.append({"device": c["device"], "now": c["now"], "tone": c["tone"], "label": c.get("label"), "online": c["online"], "today": c["today"],
                        "step": (p.get("now") if w.get("show_step") and p else None),
                        "alerts": c["alerts"] if w.get("show_alerts") else [],
                        "image": bool(w.get("show_image")) and c["online"]})
        return {"devices": out}
    if kind == "incidents":
        root = os.path.join(SHADOW_DIR, "incidents")
        items = []
        for iid in (sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []):
            d = _read_json(os.path.join(root, iid, "incident.json"), None)
            if not d or d.get("device") not in devices:
                continue
            es = d.get("entries") or []
            items.append({"id": d["id"], "device": d["device"], "start": d.get("start"), "end": d.get("end"), "status": d.get("status"),
                          "triggers": list(dict.fromkeys(t.get("rule_name") or t.get("text") or "" for t in d.get("triggers") or [])),
                          "story": [{"t": e.get("t"), "text": e["text"]} for e in es if e["kind"] in ("trigger", "action", "alert", "resolved", "end")][:12],
                          "frame": next((e["frame"] for e in es if e.get("frame")), None) if w.get("show_frames") else None})
            if len(items) >= int(w["limit"]):
                break
        return {"items": items}
    if kind == "deploy":
        scs = {s["id"]: s for s in automation.load_all(DATA_ROOT)}
        rows = [{"id": sid, "name": scs[sid]["name"], "enabled": scs[sid].get("enabled", True),
                 "modes": {n: automation.mode_for(scs[sid], n) for n in devices}}
                for sid in w["scripts"] if sid in scs]
        return {"rows": rows, "modes": {m: automation.mode_label(m) for m in w["modes"]}, "all_modes": tr(automation.MODES)}
    if kind == "list":
        from automation import lists
        spec = lists.load(DATA_ROOT).get(w["list"])
        if not spec:
            raise ValueError(_("這份清單已經不存在,請聯絡導入顧問"))
        scans = lists.scans(RUNTIME_DIR).get(spec["id"], {})
        out = {}
        for n in (devices if spec.get("per_device") else ["*"]):
            sc = scans.get(n)
            new = set((sc or {}).get("new") or [])
            out[n] = {"scan": sc, "busy": ((by_name.get(n) or {}).get("proc") or {}).get("script_name"),
                      "items": [{"id": b["id"], "label": b["label"], "new": b["id"] in new,
                                 "missing_since": b.get("missing_since")}
                                for b in lists.ordered(DATA_ROOT, spec, n if spec.get("per_device") else None)]}
        return {"title": spec.get("title") or spec["id"], "per_device": bool(spec.get("per_device")), "by_device": out,
                "scan": bool(w.get("scan_sub")), "rename": bool(w.get("rename")), "remove": bool(w.get("remove"))}
    if kind == "schedules":
        defs = {s["id"]: s for s in sm.effective(DATA_ROOT, RUNTIME_DIR)}
        want = w.get("schedules") or [s["id"] for s in defs.values() if s.get("enabled")]
        live = {x["id"]: x["devices"] for x in st.get("schedules") or []}
        rows = []
        for sid in want:
            s = defs.get(sid)
            if not s:
                continue
            rows.append({"id": sid, "name": s["name"], "at": s.get("at"), "enabled": s.get("enabled", True),
                         "devices": {n: {"text": v["text"], "code": v["code"]} for n, v in (live.get(sid) or {}).items() if n in devices}})
        return {"rows": rows}
    if kind == "chat":
        return _chat_widget(w)
    if kind == "log":
        rows = [{"t": a["t"], "device": a.get("device"), "text": a["text"], "level": a.get("level", "warn")}
                for a in st.get("alerts") or [] if not a.get("device") or a.get("device") in devices]
        if w.get("panel_changes"):
            for h in pm.history(DATA_ROOT, int(w["limit"])):
                what = _("按下「{label}」", label=h['label']) if h.get("action") else _("改了「{label}」", label=h['label'])
                rows.append({"t": h["t"], "device": h.get("device"), "text": _("操作面板:{what}", what=what), "level": "panel"})
        rows.sort(key=lambda r: -r["t"])
        return {"rows": rows[:int(w["limit"])]}
    return {}


def _chat_widget(w):
    """The 通知與指令 widget: this site's chat bots, without their secrets."""
    import notify
    from notify import channels, commands
    acc = commands.access(RUNTIME_DIR)
    states = _commander.states() if _commander else {}
    bots = []
    for c in notify.load(RUNTIME_DIR).get("channels", []):
        t = channels.types().get(c.get("type"))
        if t is None or not getattr(t, "LISTENS", False):
            continue
        a = acc.get(c["id"]) or {}
        st = states.get(c["id"]) or {}
        bots.append({"id": c["id"], "name": c["name"], "type": c["type"], "label": _(t.LABEL), "enabled": c.get("enabled", True),
                     "state": st.get("state"), "error": st.get("error"), "invite": t.invite(c["config"]) if c.get("enabled") else None,
                     "paired": bool(a.get("chat")), "chat_name": a.get("chat_name"), "allowed": a.get("allowed") or [],
                     "token_end": (c["config"].get("token") or "")[-4:]})
    types = [{"type": k, "label": _(t.LABEL), "help": _(t.HELP)} for k, t in channels.types().items() if getattr(t, "LISTENS", False)]
    return {"bots": bots, "types": types if w.get("setup") else [], "setup": bool(w.get("setup")), "pair": bool(w.get("pair"))}


def _chat_allowed(need):
    """The panel's 通知與指令 widget must allow this (setup / pair)."""
    _panel_widget("chat", need)


class PanelChatSave(BaseModel):
    id: str | None = None                   # None = a new bot
    type: str | None = None
    name: str | None = None
    token: str | None = None


@app.post("/api/panel/chat/save")
def panel_chat_save(req: PanelChatSave):
    """Add a chat bot, or change its name / token (end users, as far as the panel allows)."""
    import notify
    from notify import channels
    _chat_allowed("setup")
    cfg = notify.load(RUNTIME_DIR)
    chs = cfg.setdefault("channels", [])
    if req.id:
        c = next((x for x in chs if x["id"] == req.id), None)
        t = channels.types().get((c or {}).get("type"))
        if not c or not getattr(t, "LISTENS", False):
            _bad(_("找不到這個 Bot,請重新整理頁面"))
    else:
        t = channels.types().get(req.type or "")
        if not getattr(t, "LISTENS", False):
            _bad(_("請選擇要用哪一種 Bot"))
        k = 1
        while any(x["id"] == f"{req.type}{k}" for x in chs):
            k += 1
        c = {"id": f"{req.type}{k}", "name": req.name or _(t.LABEL), "type": req.type, "enabled": True, "config": {},
             "kinds": list(notify.DEFAULT_KINDS), "devices": [], "quiet": None, "image": True}
        chs.append(c)
    if req.name:
        c["name"] = req.name.strip()[:40]
    if req.token is not None and req.token.strip():
        c["config"] = {**(c.get("config") or {}), "token": req.token.strip()}
    if not c["config"].get("token"):
        _bad(_("請貼上 Bot Token"))
    try:
        notify.save(RUNTIME_DIR, cfg)
    except ValueError as e:
        _bad(e)
    return {"id": c["id"]}


class PanelChatId(BaseModel):
    id: str
    user: str | None = None


@app.post("/api/panel/chat/remove")
def panel_chat_remove(req: PanelChatId):
    import notify
    from notify import channels
    _chat_allowed("setup")
    cfg = notify.load(RUNTIME_DIR)
    c = next((x for x in cfg.get("channels", []) if x["id"] == req.id), None)
    if not c or not getattr(channels.types().get(c.get("type")), "LISTENS", False):
        _bad(_("找不到這個 Bot"))
    cfg["channels"] = [x for x in cfg["channels"] if x["id"] != req.id]
    notify.save(RUNTIME_DIR, cfg)
    return {"ok": True}


@app.post("/api/panel/chat/pair")
def panel_chat_pair(req: PanelChatId):
    _chat_allowed("pair")
    return notify_pair(NotifyPair(id=req.id))


@app.post("/api/panel/chat/unpair")
def panel_chat_unpair(req: PanelChatId):
    _chat_allowed("pair")
    if not _commander or not req.user:
        _bad(_("請指定要移除的人"))
    _commander.unpair(req.id, req.user)
    return {"ok": True}


class PanelDeploy(BaseModel):
    block: str
    script: str
    device: str
    mode: str


@app.post("/api/panel/deploy")
def panel_deploy(req: PanelDeploy):
    """A user switches a main script on one emulator, as far as the panel's 部署開關 widget allows."""
    from . import panel as pm
    import automation
    pnl = pm.load(DATA_ROOT)
    b = next((x for x in pnl.get("blocks", []) if x["id"] == req.block and (x.get("widget") or {}).get("kind") == "deploy"), None)
    w = {**pm.WIDGET_DEFAULTS["deploy"], **(b or {}).get("widget", {})}
    from drivers.sources import expand
    devices = _panel_devices(pnl)
    if not b or req.script not in w["scripts"] or req.mode not in w["modes"] or req.device not in devices:
        _bad(_("這個操作不在面板允許的範圍內,請重新整理頁面"))
    sc = {k: v for k, v in automation.load(DATA_ROOT, req.script).items() if k not in ("version", "created", "note")}
    old = automation.mode_for(sc, req.device)
    if old == req.mode:
        return {"old": old, "new": old}
    sc["devices"][req.device] = req.mode
    try:
        automation.save(DATA_ROOT, sc, _("操作面板:{device} {p2}", device=req.device, p2=automation.mode_label(req.mode)))
    except ValueError as e:
        _bad(e)
    with open(pm.log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "control": f"deploy:{req.script}", "label": _("{name} 的執行方式", name=sc['name']), "device": req.device,
                            "old": automation.mode_label(old), "new": automation.mode_label(req.mode)}, ensure_ascii=False) + "\n")
    return {"old": old, "new": req.mode}


def _panel_widget(kind, need=None):
    """The panel's widgets of this kind that allow `need` (an option that must be on); 403 if there is none."""
    from . import panel as pm
    ws = [{**pm.WIDGET_DEFAULTS[kind], **b["widget"]} for b in pm.widget_blocks(pm.load(DATA_ROOT), kind)]
    if not [w for w in ws if not need or w.get(need)]:
        _bad(_("操作面板沒有開放這個畫面"), 403)


def _panel_list(block):
    """The operation panel's 清單 widget `block` -> (its options, the list, the emulators of the panel); 403 if the
    panel has no such widget (users only reach what the consultant put there)."""
    from . import panel as pm
    from automation import lists
    from drivers.sources import expand
    pnl = pm.load(DATA_ROOT)
    b = next((x for x in pnl.get("blocks") or [] if x["id"] == block and (x.get("widget") or {}).get("kind") == "list"), None)
    if not b:
        _bad(_("操作面板沒有這個清單"), 403)
    w = {**pm.WIDGET_DEFAULTS["list"], **b["widget"]}
    spec = lists.load(DATA_ROOT).get(w["list"])
    if not spec:
        _bad(_("這份清單已經不存在,請聯絡導入顧問"))
    devices = _panel_devices(pnl)
    return w, spec, devices


def _panel_list_item(spec, devices, device, bid):
    from automation import buttons as bm
    if spec.get("per_device") and device not in devices:
        _bad(_("請選擇是哪一台"))
    b = bm.load(DATA_ROOT).get(bid)
    if not b or b.get("list") != spec["id"] or (spec.get("per_device") and b.get("device") != device):
        _bad(_("清單裡沒有這個項目,請重新整理頁面"), 404)
    return b


@app.get("/api/panel/list/{block}/pic/{device}/{bid}")
def panel_list_pic(block: str, device: str, bid: str):
    """The picture of one name of a panel list (what was read off the screen)."""
    w, spec, devices = _panel_list(block)
    _panel_list_item(spec, devices, device, bid)
    from automation import buttons as buttons_mod
    p = buttons_mod.image_path(DATA_ROOT, os.path.basename(bid))
    if not os.path.exists(p):
        _bad(_("沒有這張圖"), 404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


class PanelListItem(BaseModel):
    device: str = "*"
    id: str
    action: str                             # rename | keep (a name not seen is still there) | remove (for good)
    label: str = ""


@app.post("/api/panel/list/{block}/item")
def panel_list_item(block: str, req: PanelListItem):
    from . import panel as pm
    from automation import lists
    w, spec, devices = _panel_list(block)
    b = _panel_list_item(spec, devices, req.device, req.id)
    title = spec.get("title") or spec["id"]
    try:
        if req.action == "rename":
            if not w.get("rename"):
                _bad(_("這個清單不開放改名"), 403)
            lists.rename(DATA_ROOT, spec, b.get("device"), b["id"], req.label)
            old, new = b["label"], req.label.strip()
        elif req.action == "keep":
            lists.keep(DATA_ROOT, spec, b.get("device"), b["id"])
            old, new = _("{label}(沒看到)", label=b['label']), _("{label}(保留)", label=b['label'])
        elif req.action == "remove":
            if not w.get("remove"):
                _bad(_("這個清單不開放移除"), 403)
            lists.remove(DATA_ROOT, RUNTIME_DIR, spec, b.get("device"), b["id"])
            old, new = b["label"], _("(移除)")
        else:
            _bad(_("不認得的動作"))
    except ValueError as e:
        _bad(e)
    with open(pm.log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "control": f"list:{block}", "label": title, "device": None if req.device == "*" else req.device,
                            "old": old, "new": new}, ensure_ascii=False) + "\n")
    return {"ok": True}


class PanelListScan(BaseModel):
    device: str
    if_busy: str = "ask"                    # ask (say what it is doing) | interrupt | queue


@app.post("/api/panel/list/{block}/scan")
def panel_list_scan(block: str, req: PanelListScan):
    """Walk the list on one emulator now (the widget's scan sub-script)."""
    w, spec, devices = _panel_list(block)
    if not w.get("scan_sub"):
        _bad(_("這個清單沒有掃描按鈕"), 403)
    if req.if_busy not in ("ask", "interrupt", "queue"):
        _bad(_("if_busy 不正確"))
    c = {"id": f"list:{block}", "label": _("掃描{p1}", p1=spec.get('title') or spec['id']), "type": "action", "scope": "device",
         "bind": {"kind": "act_sub", "sub": w["scan_sub"]}}
    return _panel_press(c, req.device, req.if_busy, False, _("面板:{label}", label=c['label']))


# ---------------- the panel's users find and pick their sources (the pack says which kinds) ----------------
def _panel_sources_policy():
    from . import panel as pm
    pnl = pm.load(DATA_ROOT)
    kinds = pm.source_kinds(pnl)
    if not kinds:
        _bad(_("這個面板沒有開放選擇來源"), 403)
    return pnl.get("sources") or {}, kinds


@app.get("/api/panel/sources")
def panel_sources():
    """The sources in use and what the users may pick from (help text, whether they may at all)."""
    from . import panel as pm
    from drivers import sources
    import drivers
    pnl = pm.load(DATA_ROOT)
    kinds = pm.source_kinds(pnl)
    have = drivers.describe()
    cfg = sources.load(DATA_ROOT)
    return {"can": bool(kinds), "help": (pnl.get("sources") or {}).get("help") or "",
            "kinds": [{"kind": k, "label": (have.get(k) or {}).get("label", k)} for k in kinds],
            "items": [{"id": it["id"], "name": sources.label(it["id"], DATA_ROOT), "kind": it["kind"],
                       "kind_label": (have.get(it["kind"]) or {}).get("label", it["kind"]), "match": it["match"],
                       "enabled": bool(it.get("enabled"))} for it in cfg["items"] if it["kind"] in kinds]}


@app.post("/api/panel/sources/scan")
def panel_sources_scan():
    """Look for the kinds the pack allows (and its name filter) now."""
    from . import sources_view
    pol, kinds = _panel_sources_policy()
    r = sources_view.scan(DATA_ROOT, kinds, pol.get("q") or "")
    return {"found": [{"kind": x["kind"], "kind_label": x.get("kind_label"), "match": x["match"], "name": x["match"],
                       "detail": x.get("detail") or "", "warn": x.get("size_warn") or "", "bound": x.get("bound")}
                      for x in r["found"] if x["kind"] in kinds and not x.get("same_as")],
            "errors": r.get("errors") or {}}


class PanelSourceUse(BaseModel):
    kind: str
    match: str
    use: bool
    name: str = ""


@app.post("/api/panel/sources/use")
def panel_sources_use(req: PanelSourceUse):
    """Tick / untick one found source. Unticking only turns it off (its name, tags and deployment stay for later)."""
    from drivers import sources
    from . import panel as pm
    pol, kinds = _panel_sources_policy()
    if req.kind not in kinds:
        _bad(_("這種來源不在這個面板開放的範圍內"), 403)
    cfg = sources.load(DATA_ROOT)
    it = next((x for x in cfg["items"] if x["kind"] == req.kind and x["match"] == req.match), None)
    if it is not None:
        it["enabled"] = req.use
        sources.save(cfg, DATA_ROOT)
        sid = it["id"]
    elif req.use:
        sid = sources_add(SourceAdd(kind=req.kind, match=req.match, name=req.name), start_mode=pol.get("new_mode") or "shadow")["id"]
    else:
        return {"ok": True}
    with open(pm.log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "control": "sources", "label": _("使用的{p1}", p1=project.word('device')), "device": sid,
                            "old": _("不使用") if req.use else _("使用"), "new": _("使用") if req.use else _("不使用")}, ensure_ascii=False) + "\n")
    return {"ok": True, "id": sid}


@app.get("/api/panel/live/{name}")
def panel_live(name: str):
    _panel_widget("devices", "show_image")
    return shadow_live(name)


@app.get("/api/panel/incident/{iid}/frame/{name}")
def panel_incident_frame(iid: str, name: str):
    _panel_widget("incidents", "show_frames")
    return incident_frame(iid, name)


@app.get("/api/panel/definition")
def panel_definition():
    """The panel as the consultant designs it, and everything a control can be wired to."""
    from . import panel as pm
    import automation
    from automation import schedules as sm, subs as subm, buttons as bm, lists, settings as us
    lib = subm.load_all(DATA_ROOT)

    def params(sub_id):
        return [{"name": p["name"], "label": p.get("label") or p["name"], "type": p["type"], "item": p.get("item"), "from_list": p.get("from_list")}
                for p in (lib.get(sub_id) or {}).get("params") or []]
    entries = []
    for sc in automation.load_all(DATA_ROOT):
        for sit in sc["situations"]:
            e = automation.enter_call(sit) or {}
            if e.get("type") == "call" and params(e.get("sub")):
                entries.append({"script": sc["id"], "script_name": sc["name"], "situation": sit["id"], "situation_name": sit["name"],
                                "sub": e["sub"], "params": params(e["sub"])})
    st = _runner_live() or {}
    return {"panel": pm.load(DATA_ROOT), "binds": tr(pm.BINDS), "types": {t: n for t, n in zip(pm.TYPES, (_("開關"), _("時間"), _("數字"), _("多選"), _("單選"), _("動作按鈕")))},
            "acts": tr(pm.ACTS),
            "scripts": [{"id": sc["id"], "name": sc["name"], "situations": [{"id": x["id"], "name": x["name"]} for x in sc["situations"]]}
                        for sc in automation.load_all(DATA_ROOT) if not automation.is_guard(sc) and len(sc.get("situations") or []) > 1],
            "schedules": [{"id": s["id"], "name": s["name"], "sub": s["sub"], "params": params(s["sub"])} for s in sm.load(DATA_ROOT)],
            "entries": entries, "devices": [d["name"] for d in st.get("devices") or []],
            "settings": list(us.load(DATA_ROOT).values()),
            "widgets": tr(pm.WIDGETS), "widget_defaults": pm.WIDGET_DEFAULTS, "modes": tr(automation.MODES),
            "source_kinds": [{"kind": k, "label": v.get("label", k), "category": v.get("category"), "category_label": v.get("category_label")}
                             for k, v in __import__("drivers").describe().items()],
            "main_scripts": [{"id": sc["id"], "name": sc["name"]} for sc in automation.load_all(DATA_ROOT) if not automation.is_guard(sc)],
            # sub-scripts a panel button can run as they are (no argument without a default)
            "runnable_subs": [{"id": s["id"], "name": s["name"]} for s in lib.values() if all(p.get("default") is not None for p in s.get("params") or [])],
            "buttons": [{"id": b["id"], "label": b["label"], "group": b.get("group"), "device": b.get("device"), "list": b.get("list")} for b in bm.load(DATA_ROOT).values()
                        ],
            "lists": [{"id": x["id"], "title": x.get("title") or x["id"], "per_device": bool(x.get("per_device"))}
                      for x in lists.load(DATA_ROOT).values()]}


class PanelDefinition(BaseModel):
    panel: dict


@app.post("/api/panel/definition")
def panel_definition_save(req: PanelDefinition):
    from . import panel as pm
    try:
        pm.save(DATA_ROOT, req.panel)
    except ValueError as e:
        _bad(e)
    return {"ok": True}


@app.post("/api/panel/chat_preview")
def panel_chat_preview(req: PanelDefinition):
    """What the chat bot will understand with this (unsaved) panel design."""
    from . import panel as pm
    from .panel_chat import check, entries, widget_names
    pnl = pm.normalize(json.loads(json.dumps(req.panel)))
    try:
        check(pnl)
        err = None
    except ValueError as e:
        err = str(e)
    return {"error": err, "widgets": widget_names(pnl),
            "commands": [{"name": e["name"], "control": e["control"]["id"], "block": e["block"]["title"],
                          "type": e["control"]["type"], "scope": e["control"].get("scope", "global")} for e in entries(pnl)]}


@app.get("/api/notify/help")
def notify_help():
    from notify.commands import HELP
    return {"text": _ChatActions().help_text(_(HELP))}


@app.get("/api/asks")
def asks_get():
    """Questions running scripts are waiting on (the 問使用者 step)."""
    from notify import asks
    return {"items": asks.pending(RUNTIME_DIR)}


class Answer(BaseModel):
    id: str
    option: int


@app.post("/api/panel/answer")
def panel_answer(req: Answer, request: Request):
    """Answer a script's question (the runner page or the operation panel); the first answer wins."""
    from notify import asks
    from . import panel as pm
    q = asks.get(RUNTIME_DIR, req.id)
    from drivers.sources import expand
    devices = expand(pm.load(DATA_ROOT).get("devices"))
    if q and devices and q["device"] not in devices and getattr(request.state, "role", None) == "user":
        _bad(_("操作面板沒有這台"), 403)
    ok, msg = asks.answer(RUNTIME_DIR, req.id, req.option, _("操作面板") if getattr(request.state, "role", None) == "user" else _("執行頁"))
    if not ok:
        _bad(msg)
    return {"message": msg}


class PanelSet(BaseModel):
    control: str
    device: str | None = None
    value: object = None


@app.post("/api/panel/set")
def panel_set(req: PanelSet):
    from . import panel as pm
    c = next((x for x in pm.load(DATA_ROOT).get("controls", []) if x["id"] == req.control), None)
    if not c:
        _bad(_("找不到這個設定,請重新整理頁面"))
    if c.get("scope") == "device" and not req.device:
        _bad(_("請選擇是哪一台"))
    try:
        old, new = pm.apply(DATA_ROOT, c, req.device if c.get("scope") == "device" else None, req.value)
    except ValueError as e:
        _bad(e)
    return {"old": old, "new": new}


class PanelAct(BaseModel):
    control: str
    device: str | None = None
    if_busy: str = "ask"
    resume: bool = False                    # a 停下來 button pressed again: 繼續


@app.post("/api/panel/act")
def panel_act(req: PanelAct):
    """An action button of the operation panel: only the buttons the consultant put on the panel can be pressed."""
    from . import panel as pm
    pnl = pm.load(DATA_ROOT)
    c = next((x for x in pnl.get("controls", []) if x["id"] == req.control and x.get("type") == "action"), None)
    if not c:
        _bad(_("找不到這個按鈕,請重新整理頁面"))
    return _panel_press(c, req.device, req.if_busy, req.resume, _("面板:{label}", label=c['label']))


def _panel_press(c, device, if_busy, resume, by):
    """Press a panel button (the page or a chat): on the emulator it is for, or every one it acts on."""
    from . import panel as pm
    pnl = pm.load(DATA_ROOT)
    st = _runner_live() or {}
    from drivers.sources import expand
    devices = _panel_devices(pnl)
    if c.get("scope") == "device" and device not in devices:
        _bad(_("請選擇是哪一台"))
    b = c["bind"]
    targets = pm.act_targets(DATA_ROOT, c, device, devices)
    if not targets:
        _bad(_("沒有要做這件事的{p1}", p1=project.word("device")))
    kind = {"act_schedule": "schedule", "act_sub": "sub", "act_situation": "situation", "act_stop": "stop"}[b["kind"]]
    if kind == "stop" and resume:
        kind = "resume"
    if if_busy == "ask" and kind in ("schedule", "sub"):      # ask first, before anything is sent to any emulator
        busy = {d["name"]: {"name": (d["proc"].get("script_name") or ""), "loop": d["proc"].get("loop"), "now": d["proc"].get("now")}
                for d in st.get("devices") or [] if d["name"] in targets and d.get("proc")}
        if busy:
            return {"busy": busy, "done": {}, "errors": {}}
    out = {}
    held = {d["name"]: d["hold"] for d in st.get("devices") or [] if d.get("hold")}
    for n in targets:
        if kind in ("schedule", "sub", "situation") and n in held:     # it would only be refused there: say so here
            out[n] = {"error": (_("暫停中") if held[n].get("mode") == "pause" else _("已停下來")) + _(",先按「繼續」")}
            continue
        act = Act(device=n, kind=kind, sub=b.get("sub"),
                  id=b.get("schedule"), script=b.get("script"), situation=b.get("situation"), mode="hold",
                  if_busy="queue" if if_busy == "ask" else if_busy)
        try:
            out[n] = _act_send(act, by)
        except HTTPException as e:
            out[n] = {"error": e.detail}
    pm.log_action(DATA_ROOT, c, device, {n: (_("已送出") if r.get("queued") else r.get("error")) for n, r in out.items()})
    return {"busy": {}, "done": {n: r.get("error") or _("已送出") for n, r in out.items()},
            "errors": {n: r["error"] for n, r in out.items() if r.get("error")}}


def _write_control(c):
    p = os.path.join(RUNTIME_DIR, "control.json")
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.replace(p + ".tmp", p)


class PanelAll(BaseModel):
    mode: str = "stop"                      # stop | pause


@app.post("/api/panel/pause")
def panel_pause(req: PanelAll | None = None):
    """全部停下來 (or 全部暫停): every source, kept across restarts, until 全部繼續."""
    mode = (req.mode if req else "stop")
    if mode not in ("stop", "pause"):
        _bad(_("要停下來還是暫停?"))
    _act_send(Act(device="*", kind="pause" if mode == "pause" else "stop"), _("操作面板"))
    return {"paused": True}


@app.post("/api/panel/resume")
def panel_resume():
    _act_send(Act(device="*", kind="resume"), _("操作面板"))
    return {"paused": False}


@app.get("/api/schedules")
def schedules_get():
    from automation import schedules as sm
    items = sm.load(DATA_ROOT)
    live = _runner_live()
    if live:
        status = {x["id"]: x["devices"] for x in live.get("schedules") or []}
    else:                                   # the runner is off: today's record only
        state, now = sm.State(os.path.join(RUNTIME_DIR, "schedules_state.json"), sm.day_start(DATA_ROOT)), time.time()
        status = {s["id"]: {n: dict(zip(("code", "text"), sm.describe(s, n, now, state)), online=False,
                                    run=(state.done(s["id"], n, now) or {}).get("run")) for n in s.get("devices") or []}
                  for s in sm.effective(DATA_ROOT, RUNTIME_DIR)}
    ds = sm.day_start(DATA_ROOT)
    return {"items": items, "status": status, "running": bool(live), "day_start": f"{ds // 60:02d}:{ds % 60:02d}",
            "overrides": sm.overrides(RUNTIME_DIR)}       # what the users changed on the panel (over this design)


class ScheduleOverride(BaseModel):
    id: str
    field: str | None = None                # None = every field back to the design


@app.post("/api/schedules/override/clear")
def schedules_override_clear(req: ScheduleOverride):
    from automation import schedules as sm
    try:
        for f in [req.field] if req.field else list(sm.OVERRIDE_FIELDS):
            sm.set_override(DATA_ROOT, RUNTIME_DIR, req.id, f, None)
    except ValueError as e:
        _bad(e)
    return {"overrides": sm.overrides(RUNTIME_DIR)}


class SchedulesSave(BaseModel):
    items: list
    day_start: str | None = None


@app.post("/api/schedules")
def schedules_save(req: SchedulesSave):
    from automation import schedules as sm, subs
    try:
        return {"items": sm.save(DATA_ROOT, req.items, subs.load_all(DATA_ROOT), req.day_start)}
    except ValueError as e:
        _bad(e)


class ScheduleRequest(BaseModel):
    action: str                             # run_now | reset
    id: str
    device: str | None = None


@app.post("/api/schedules/request")
def schedules_request(req: ScheduleRequest):
    from automation import schedules as sm
    if req.action not in ("run_now", "reset"):
        _bad(_("不支援的操作"))
    if not any(s["id"] == req.id for s in sm.load(DATA_ROOT)):
        _bad(_("找不到這個排程(先儲存)"))
    if _runner_live():
        d = os.path.join(RUNTIME_DIR, "schedule_requests")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{time.time_ns()}.json"), "w", encoding="utf-8") as f:
            json.dump(req.model_dump(), f, ensure_ascii=False)
        return {"queued": True}
    if req.action == "run_now":
        _bad(_("腳本執行沒有在跑,請先到「執行」開始執行"))
    sm.State(os.path.join(RUNTIME_DIR, "schedules_state.json"), sm.day_start(DATA_ROOT)).reset(req.id, req.device)
    return {"queued": False}


def _sched_run_dir(rid: str):
    d = os.path.join(SHADOW_DIR, "schedules", os.path.basename(rid))
    if not os.path.exists(os.path.join(d, "run.json")):
        _bad(_("找不到這次執行紀錄"), 404)
    return d


@app.get("/api/schedules/runs")
def schedule_runs(limit: int = Query(100, le=1000)):
    root = os.path.join(SHADOW_DIR, "schedules")
    ids = sorted(os.listdir(root), reverse=True)[:limit] if os.path.isdir(root) else []
    out = []
    for rid in ids:
        d = _read_json(os.path.join(root, rid, "run.json"), None)
        if d:
            out.append({k: d.get(k) for k in ("id", "schedule", "schedule_name", "device", "start", "end", "result", "message")}
                       | {"steps": sum(1 for e in d.get("entries") or [] if e["kind"] in ("step", "notify"))})
    return {"items": out}


@app.get("/api/schedules/runs/{rid}")
def schedule_run(rid: str):
    return _read_json(os.path.join(_sched_run_dir(rid), "run.json"), {})


@app.get("/api/schedules/runs/{rid}/frame/{name}")
def schedule_run_frame(rid: str, name: str):
    p = os.path.join(_sched_run_dir(rid), os.path.basename(name))
    if not name.endswith(".jpg") or not os.path.exists(p):
        _bad(_("沒有這張畫面"), 404)
    return FileResponse(p)


def _incident_dir(iid: str):
    d = os.path.join(SHADOW_DIR, "incidents", os.path.basename(iid))
    if not os.path.exists(os.path.join(d, "incident.json")):
        _bad(_("找不到這個緊急事件"), 404)
    return d


@app.get("/api/incidents")
def incidents_list(limit: int = Query(100, le=1000)):
    """Urgent incidents, newest first (runtime/incidents.py)."""
    root = os.path.join(SHADOW_DIR, "incidents")
    ids = sorted(os.listdir(root), reverse=True)[:limit] if os.path.isdir(root) else []
    out = []
    for iid in ids:
        d = _read_json(os.path.join(root, iid, "incident.json"), None)
        if not d:
            continue
        es = d.get("entries") or []
        out.append({k: d.get(k) for k in ("id", "device", "start", "end", "status")} | {
            "triggers": d.get("triggers") or [],
            "actions": sum(1 for e in es if e["kind"] == "action"),
            "urgent_actions": sum(1 for e in es if e["kind"] == "action" and e.get("urgent")),
            "warnings": sum(1 for e in es if e["kind"] == "alert" and e.get("level") == "warn"),
            "not_done": sorted({e.get("why") or e["text"].split("沒有執行:", 1)[-1] for e in es if e["kind"] == "exec"}),
            "frame": next((e["frame"] for e in es if e.get("frame")), None)})
    return {"items": out}


@app.get("/api/incidents/{iid}")
def incident_get(iid: str):
    return _read_json(os.path.join(_incident_dir(iid), "incident.json"), {})


@app.get("/api/incidents/{iid}/frame/{name}")
def incident_frame(iid: str, name: str):
    p = os.path.join(_incident_dir(iid), os.path.basename(name))
    if not name.endswith(".jpg") or not os.path.exists(p):
        _bad(_("沒有這張畫面"), 404)
    return FileResponse(p)


@app.get("/api/shadow/log")
def shadow_log(limit: int = Query(100, le=1000)):
    d = os.path.join(SHADOW_DIR, "log")
    files = sorted(glob.glob(os.path.join(d, "*.jsonl")))[-2:]
    rows = []
    for f in files:
        rows += data.read_jsonl(f)
    return rows[-limit:][::-1]


class ShadowFlag(BaseModel):
    device: str
    note: str = ""


@app.post("/api/shadow/flag")
def shadow_flag(req: ShadowFlag):
    d = os.path.join(RUNTIME_DIR, "flag_requests")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, os.path.basename(req.device) + ".json"), "w", encoding="utf-8") as f:
        json.dump({"note": req.note, "t": time.time()}, f, ensure_ascii=False)
    return {"requested": True}


@app.get("/api/shadow/stuck")
def shadow_stuck(limit: int = 100):
    """The screens kept when a device got stuck (newest first)."""
    p = os.path.join(SHADOW_DIR, "stuck.jsonl")
    rows = data.read_jsonl(p) if os.path.exists(p) else []
    return rows[::-1][:max(1, min(limit, 500))]


@app.get("/api/shadow/flags")
def shadow_flags():
    p = os.path.join(SHADOW_DIR, "flags.jsonl")
    rows = data.read_jsonl(p) if os.path.exists(p) else []
    dec = review.decisions()
    for r in rows:
        r["answered"] = (dec.get(r["frame"]) or {}).get("answers")
    return rows[::-1]


# ---------------- static web UI ----------------
DIST = os.path.join(PROJECT_ROOT, "web", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
