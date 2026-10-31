"""What an AI connected over MCP (mcp_server/) needs beyond the pages' own API:

  POST /api/ai/check {kind, doc}     check a design document without saving it -> {"ok", "errors": [{path, message}]}
       kinds: script, sub, states (the whole list), schedules (the whole list), settings (user setting declarations),
              variables, outputs, panel
  POST /api/ai/log {tool, target, reason, before, after, result}    one change an AI made, written down
  GET  /api/ai/log?limit=            the changes, newest first (<runtime dir>/ai_log.jsonl)
  POST /api/ai/requests {script, device, reason}    an AI asks for a main script to run live on a device
  GET  /api/ai/requests              the requests (open ones first)
  POST /api/ai/requests/{id}/answer {approve}       a person says yes (the script goes live there) or no; an AI
                                                    cannot (its calls say X-Actor: ai)
The changes themselves go through the same endpoints the pages use, so the same checks hold."""
import json
import os
import time
import urllib.parse
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import atomic
from . import DATA_ROOT, RUNTIME_DIR
from i18n import _

router = APIRouter()
LOG = "ai_log.jsonl"
REQUESTS = "ai_requests.json"
KINDS = ("script", "sub", "states", "schedules", "settings", "variables", "outputs", "panel")


class Check(BaseModel):
    kind: str
    doc: object = None


@router.post("/api/ai/check")
def check(req: Check):
    """Would this be saved? The same checks the save runs, nothing written."""
    from automation import spec_schema
    if req.kind not in KINDS:
        raise HTTPException(400, _("可以檢查:{kinds}", kinds=", ".join(KINDS)))
    try:
        if req.kind in ("script", "sub", "panel"):
            if not isinstance(req.doc, dict):
                return {"ok": False, "errors": [{"path": _("(整份)"), "message": _("最外層要是一個物件 { … }")}]}
            errs = spec_schema.check(req.kind, req.doc, DATA_ROOT)
            return {"ok": not errs, "errors": errs}
        if not isinstance(req.doc, list):
            return {"ok": False, "errors": [{"path": _("(整份)"), "message": _("要是一個清單 [ … ]")}]}
        if req.kind == "states":
            import schema as schema_mod
            schema_mod.validate({"states": req.doc})
        elif req.kind == "schedules":
            from automation import schedules, subs
            schedules.validate(req.doc, subs.load_all(DATA_ROOT))
        elif req.kind == "settings":
            from automation import settings
            settings.validate(DATA_ROOT, req.doc)
        elif req.kind == "variables":
            import automation
            automation.check_variables(req.doc)
        elif req.kind == "outputs":
            from automation import outputs
            outputs.validate(req.doc)
    except ValueError as e:
        return {"ok": False, "errors": [{"path": _("(內容)"), "message": str(e)}]}
    except (KeyError, TypeError, AttributeError) as e:
        return {"ok": False, "errors": [{"path": _("(內容)"), "message": _("格式不對:{e}", e=e)}]}
    return {"ok": True, "errors": []}


class LogEntry(BaseModel):
    tool: str
    target: str = ""
    reason: str = ""
    before: object = None
    after: object = None
    result: object = None
    client: str = ""


@router.post("/api/ai/log")
def log_add(e: LogEntry, request: Request):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    row = {"id": uuid.uuid4().hex[:12], "t": time.time(), **e.model_dump()}
    row["client"] = row["client"] or urllib.parse.unquote(request.headers.get("X-AI-Client") or "")   # which token made it
    with open(os.path.join(RUNTIME_DIR, LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return {"id": row["id"]}


def entries():
    try:
        with open(os.path.join(RUNTIME_DIR, LOG), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


@router.get("/api/ai/log")
def log_list(limit: int = Query(50, le=1000), id: str = ""):
    rows = entries()
    if id:
        hit = [r for r in rows if r["id"] == id]
        if not hit:
            raise HTTPException(404, _("找不到這筆 AI 修改"))
        return hit[0]
    return {"items": rows[-limit:][::-1]}


# ---------------------------------------------------------------- going live: an AI asks, a person decides
def _requests():
    try:
        with open(os.path.join(RUNTIME_DIR, REQUESTS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_requests(rows):
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    atomic.write_json(os.path.join(RUNTIME_DIR, REQUESTS), rows[-200:], ensure_ascii=False, indent=1)


def open_requests():
    return [r for r in _requests() if r["status"] == "open"]


class LiveRequest(BaseModel):
    script: str
    device: str
    reason: str = ""


@router.post("/api/ai/requests")
def request_live(req: LiveRequest):
    """An AI asks for a main script to act for real on a device; nothing changes until a person says yes."""
    import automation
    from drivers.sources import label
    sc = next((s for s in automation.load_all(DATA_ROOT) if s["id"] == req.script), None)
    if not sc:
        raise HTTPException(404, _("沒有這個主腳本:{id}", id=req.script))
    if not req.reason.strip():
        raise HTTPException(400, _("請說明為什麼要正式執行"))
    if automation.mode_for(sc, req.device) == "live":
        return {"already": True}
    rows = _requests()
    same = next((r for r in rows if r["status"] == "open" and r["script"] == req.script and r["device"] == req.device), None)
    if same:
        same["reason"] = req.reason
        _save_requests(rows)
        return same
    row = {"id": uuid.uuid4().hex[:10], "t": time.time(), "kind": "live", "script": req.script, "script_name": sc.get("name"),
           "device": req.device, "device_name": label(req.device, DATA_ROOT), "reason": req.reason.strip(), "status": "open"}
    _save_requests(rows + [row])
    try:                                                     # tell people (Discord / Telegram ...) as with any warning
        from notify import Notifier
        Notifier(RUNTIME_DIR).emit("warn", req.device, _("AI 要求讓「{script}」在「{device}」正式執行:{reason}。到「執行」頁同意或拒絕。",
                                                         script=row["script_name"], device=row["device_name"], reason=row["reason"]))
    except Exception:                                        # noqa: BLE001 - the request stands even if no one is told
        pass
    return row


@router.get("/api/ai/requests")
def requests_list():
    rows = _requests()
    return {"items": sorted(rows, key=lambda r: (r["status"] != "open", -r["t"]))[:50]}


class Answer(BaseModel):
    approve: bool


@router.post("/api/ai/requests/{rid}/answer")
def request_answer(rid: str, a: Answer, request: Request):
    """A person's answer: yes makes the script live on that device (a new version), no leaves it as it is."""
    import automation
    if request.headers.get("X-Actor") == "ai":
        raise HTTPException(403, _("要由人來同意,AI 不能自己同意"))
    rows = _requests()
    row = next((r for r in rows if r["id"] == rid), None)
    if not row:
        raise HTTPException(404, _("找不到這個要求"))
    if row["status"] != "open":
        raise HTTPException(400, _("這個要求已經處理過了"))
    if a.approve:
        sc = next((s for s in automation.load_all(DATA_ROOT) if s["id"] == row["script"]), None)
        if not sc:
            raise HTTPException(404, _("這個主腳本已經不在了"))
        sc = {k: v for k, v in sc.items() if k not in ("version", "created", "note", "format")}
        sc["devices"] = {**(sc.get("devices") or {}), row["device"]: "live"}
        try:
            automation.save(DATA_ROOT, sc, _("同意 AI 的要求:{reason}", reason=row["reason"]))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    row.update(status="approved" if a.approve else "declined", answered=time.time())
    _save_requests(rows)
    return row


# ---------------------------------------------------------------- why a rule did or did not act
class Explain(BaseModel):
    script: object = None        # an id (the saved one) or a whole draft
    device: str = ""
    state: dict | None = None    # judge on these state values instead of what the runner sees now (a frozen picture)


@router.post("/api/ai/explain")
def explain(req: Explain):
    """Each rule of the device's current situation, each condition checked on what the runner sees now:
    holds / does not hold / unsure ("for N seconds" is not waited for: shown apart)."""
    import copy
    import automation
    import schema as schema_mod
    from automation import conds, engine, subs
    from .app import _read_json
    if isinstance(req.script, str):
        sc = next((s for s in automation.load_all(DATA_ROOT) if s["id"] == req.script), None)
        if not sc:
            raise HTTPException(404, _("沒有這個主腳本:{id}", id=req.script))
    elif isinstance(req.script, dict):
        sc = req.script
    else:
        raise HTTPException(400, _("請給主腳本的代號,或整份草稿"))
    sc = automation.normalize(copy.deepcopy(sc))
    st = _read_json(os.path.join(RUNTIME_DIR, "status.json"), {}) or {}
    devs = [d for d in st.get("devices") or [] if not req.device or d["name"] == req.device]
    if req.state is not None and req.device:
        devs = [{**(devs[0] if devs else {"name": req.device}), "state": req.state}]
    if not devs:
        raise HTTPException(400, _("腳本執行沒有在跑,或沒有這台;要有現在的畫面狀態才能說明"))
    names = engine.names_from_schema(schema_mod.load(DATA_ROOT))
    word = {conds.MATCH: "holds", conds.NO: "does not hold", conds.UNSURE: "unsure"}
    out = []
    for d in devs:
        sit_id = ((d.get("situations") or {}).get(sc["id"]) or {}).get("id")
        sit = automation.situation(sc, sit_id or sc.get("initial"))
        tracker, now = engine.Tracker(), time.time()
        rules = []
        for r in sit.get("rules") or []:
            groups = []
            for gi, g in enumerate(r.get("when") or []):
                cs = []
                for ci, c in enumerate(g):
                    plain = {k: v for k, v in c.items() if k != "for"}
                    res = conds.evaluate(plain, d.get("state"), tracker, f"x:{gi}:{ci}", now, {})
                    cs.append({"condition": engine.describe(c, names), "now": word.get(res, res),
                               **({"for_seconds": c["for"]} if c.get("for") else {}),
                               **({"state_now": (d.get("state") or {}).get(c["state"])} if c.get("state") else {})})
                groups.append({"all_of": cs, "group": "holds" if all(x["now"] == "holds" for x in cs) else
                               "unsure" if not any(x["now"] == "does not hold" for x in cs) else "does not hold"})
            rules.append({"rule": r.get("id"), "name": r.get("name"), "enabled": r.get("enabled", True), "any_of": groups,
                          "do": r.get("do"), "cooldown": r.get("cooldown"), "urgent": bool(r.get("urgent"))})
        decision = engine.evaluate(sc, d.get("state"), engine.Tracker(), names, device=d["name"], subs=subs.load_all(DATA_ROOT),
                                   situation=sit_id)
        held = next((x for x in [d.get("hold"), st.get("hold_all")] if x), None)
        out.append({"device": d["name"], "mode": automation.mode_for(sc, d["name"]), "situation": sit.get("name"),
                    "held": held, "decision_now": {k: decision.get(k) for k in ("action", "text", "reason", "rule_name")},
                    "rules_in_order": rules,
                    "runner_decision": next((x for x in d.get("decisions") or [] if x.get("script") == sc["id"]), None)})
    live = st.get("running") and time.time() - (st.get("updated") or 0) < 10
    return {"updated": st.get("updated"), "running": bool(live), "devices": out,
            **({} if live else {"warning": "the script runner is not running: these are the states it saw last (not now)"}),
            "note": "the first enabled rule whose any_of has a group that holds acts; 'for N seconds' must also have held that long; cooldown / limits / held devices can still stop it"}


# ---------------------------------------------------------------- tokens for AI clients over the network (/mcp)
TOKENS = "ai_tokens.json"            # [{id, name, level, hash, created, last_used, revoked}]: the token itself is never kept
LEVELS = ("read", "design", "run")


def _tokens():
    try:
        with open(os.path.join(RUNTIME_DIR, TOKENS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _hash(token):
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_of(header):
    """The token row an "Authorization: Bearer <token>" header names (not revoked), or None; its last use is noted."""
    import hmac
    if not header or not header.lower().startswith("bearer "):
        return None
    h = _hash(header.split(None, 1)[1].strip())
    rows = _tokens()
    for r in rows:
        if not r.get("revoked") and hmac.compare_digest(r["hash"], h):
            if time.time() - (r.get("last_used") or 0) > 60:
                r["last_used"] = time.time()
                atomic.write_json(os.path.join(RUNTIME_DIR, TOKENS), rows, indent=1)
            return r
    return None


class NewToken(BaseModel):
    name: str
    level: str = "design"


@router.post("/api/ai/tokens")
def token_new(req: NewToken, request: Request):
    """A token for one AI client; shown once, only its hash is kept."""
    import secrets
    if request.headers.get("X-Actor") == "ai":
        raise HTTPException(403, _("權杖要由人來建立"))
    if req.level not in LEVELS:
        raise HTTPException(400, _("權限只能是 {levels}", levels=" / ".join(LEVELS)))
    name = req.name.strip()[:60]
    if not name:
        raise HTTPException(400, _("請替權杖取個名字(例如:辦公室的 Claude)"))
    token = "insp_" + secrets.token_urlsafe(32)
    row = {"id": uuid.uuid4().hex[:10], "name": name, "level": req.level, "hash": _hash(token), "created": time.time(),
           "last_used": None, "revoked": None}
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    atomic.write_json(os.path.join(RUNTIME_DIR, TOKENS), _tokens() + [row], indent=1)
    return {**{k: v for k, v in row.items() if k != "hash"}, "token": token}


@router.get("/api/ai/tokens")
def tokens_list():
    return {"items": [{k: v for k, v in r.items() if k != "hash"} for r in _tokens()][::-1]}


@router.post("/api/ai/tokens/{tid}/revoke")
def token_revoke(tid: str, request: Request):
    if request.headers.get("X-Actor") == "ai":
        raise HTTPException(403, _("權杖要由人來撤銷"))
    rows = _tokens()
    row = next((r for r in rows if r["id"] == tid), None)
    if not row:
        raise HTTPException(404, _("找不到這個權杖"))
    row["revoked"] = time.time()
    atomic.write_json(os.path.join(RUNTIME_DIR, TOKENS), rows, indent=1)
    return {k: v for k, v in row.items() if k != "hash"}


@router.get("/api/ai/connect")
def connect_info(request: Request):
    """What an AI client needs to connect: the local command (stdio) and, when Inspector listens on the LAN, the
    address of /mcp (with a token)."""
    import sys
    from . import PROJECT_ROOT
    lan = os.environ.get("INSPECTOR_LAN_URL")
    return {"folder": PROJECT_ROOT, "python": sys.executable, "port": request.url.port,
            "lan_mcp": lan.rsplit("/panel", 1)[0] + "/mcp" if lan else None,
            "local_mcp": f"http://127.0.0.1:{request.url.port}/mcp", "tokens": sum(1 for r in _tokens() if not r.get("revoked"))}


@router.post("/api/ai/undo/{log_id}")
def undo_by_person(log_id: str, request: Request):
    """A person puts back what was there before one AI change (the same as the AI's undo_change)."""
    from mcp_server import design, tools
    api = tools.Api(f"http://127.0.0.1:{request.url.port}", request.headers.get("x-lang"), client=_("人(AI 接入頁)"))
    tool = next(t for t in design.make(api) if t["name"] == "undo_change")
    try:
        out = tool["handler"]({"log_id": log_id, "reason": _("由人在「AI 接入」頁退回")})
    except Exception as e:                                        # noqa: BLE001 - said on the page
        raise HTTPException(400, str(e)) from None
    return {"done": "".join(c.get("text", "") for c in out)}
