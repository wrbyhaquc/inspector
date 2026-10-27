"""Stage 3: the AI looks after the run - explains, reports, and (at the "run" level) starts, stops, holds and deploys.

What it never does: make a script live (it asks, a person says yes or no on the Run page), run a schedule or a
sub-script now (that acts on the site), delete recordings or models, move the data, restart Inspector. Every action
says why and is in the AI log."""
import collections
import time
import urllib.parse

from .protocol import ToolError
from .tools import _arg, _schema, text


def make(api):
    def need_reason(a):
        r = (a.get("reason") or "").strip()
        if not r:
            raise ToolError("reason is required: one sentence on why (it is kept with the action)")
        return r

    def log(tool, target, reason, before=None, after=None, result=None):
        try:
            return api.send("POST", "/api/ai/log", {"tool": tool, "target": target, "reason": reason, "before": before,
                                                    "after": after, "result": result})["id"]
        except ToolError:
            return None

    # ---------------------------------------------------------------- explaining and reporting (read)
    def explain(a):
        return text(api.send("POST", "/api/ai/explain", {"script": a.get("script"), "device": a.get("device") or ""}))

    def report(a):
        hours = _arg(a, "hours", float, 24, 1, 24 * 14)
        since = time.time() - hours * 3600
        rows = [r for r in api.get("/api/shadow/log", limit=1000) or [] if (r.get("t") or 0) >= since]
        per = collections.defaultdict(lambda: collections.Counter())
        alerts = []
        for r in rows:
            dev = r.get("device") or "-"
            act = r.get("action") or "?"
            per[dev][act if act != "alert" else f"alert_{r.get('reason') or 'info'}"] += 1
            if r.get("executed"):
                per[dev]["acted"] += 1
            if act == "alert" and r.get("reason") == "warn":
                alerts.append({"t": r.get("t"), "device": dev, "text": r.get("text")})
        incidents = [i for i in (api.get("/api/incidents", limit=200) or {}).get("items") or [] if (i.get("start") or 0) >= since]
        st = (api.get("/api/shadow/status") or {}).get("status") or {}
        ai = [e for e in (api.get("/api/ai/log", limit=200) or {}).get("items") or [] if e.get("t", 0) >= since]
        return text({"hours": hours, "runner_running_now": st.get("running"),
                     "per_device": {d: dict(c) for d, c in per.items()},
                     "warnings": alerts[-30:],
                     "incidents": [{k: i.get(k) for k in ("id", "device", "start", "end", "status", "not_done")} | {"rules": [t.get("rule_name") for t in i.get("triggers") or []]} for i in incidents],
                     "devices_now": [{"name": d.get("name"), "health": (d.get("health") or {}).get("state"), "held": d.get("hold")} for d in st.get("devices") or []],
                     "hold_all": st.get("hold_all"),
                     "ai_changes": [{k: e.get(k) for k in ("t", "tool", "target", "reason")} for e in ai],
                     "open_requests": [r for r in (api.get("/api/ai/requests") or {}).get("items") or [] if r["status"] == "open"],
                     "next_steps": [s for s in (api.get("/api/next_steps") or {}).get("steps") or [] if s.get("level") in ("todo", "warn")]},
                    f"The last {hours:g} hours (the log reaches back at most 1000 entries). Write it for a person: what happened, what needs them.")

    def requests(a):
        return text(api.get("/api/ai/requests"))

    # ---------------------------------------------------------------- running (run level)
    def start(a):
        reason = need_reason(a)
        iv = a.get("interval")
        if iv is None:
            iv = ((api.get("/api/project") or {}).get("run") or {}).get("interval") or 1.0
        r = api.send("POST", "/api/shadow/start", {"interval": float(iv)})
        return text({"started": r.get("id"), "interval": iv, "log_id": log("start_runner", "runner", reason, after={"interval": iv})},
                    "Stopped / paused devices stay so; live scripts act a few seconds after each picture is healthy.")

    def stop(a):
        reason = need_reason(a)
        api.send("POST", "/api/shadow/stop")
        return text({"stopping": True, "log_id": log("stop_runner", "runner", reason)})

    def hold(a):
        reason, action, dev = need_reason(a), a["action"], a.get("device") or "*"
        if action not in ("stop", "pause", "resume"):
            raise ToolError("action: stop | pause | resume")
        body = {"device": dev, "kind": action, **({"mode": "stop"} if action == "stop" else {})}
        r = api.send("POST", "/api/shadow/act", body)
        return text({**r, "log_id": log("hold", f"device:{dev}", reason, after=body)},
                    {"stop": "Stopped: what it was doing is ended (cleanup first); scripts and situations hold until resumed.",
                     "pause": "Paused where it is: resume carries on from the same step.",
                     "resume": "Resumed: live scripts act again (a stopped device starts its scripts over)."}[action])

    def deploy(a):
        reason, mode = need_reason(a), a["mode"]
        if mode == "live":
            raise ToolError("going live is a person's choice: use request_live (they answer on the Run page)")
        if mode not in ("off", "shadow"):
            raise ToolError("mode: off | shadow")
        sc = next((s for s in api.get("/api/scripts")["scripts"] if s["id"] == a["script"]), None)
        if not sc:
            raise ToolError(f"no main script {a['script']!r}")
        before = dict(sc.get("devices") or {})
        doc = {k: v for k, v in sc.items() if k not in ("version", "created", "note", "format")}
        doc["devices"] = {**before, a["device"]: mode}
        r = api.send("POST", "/api/scripts", {"script": doc, "note": f"AI: {reason}"})
        return text({"devices": r.get("devices"), "log_id": log("save_script", f"script:{sc['id']}", reason, sc, r)})

    def request_live(a):
        reason = need_reason(a)
        r = api.send("POST", "/api/ai/requests", {"script": a["script"], "device": a["device"], "reason": reason})
        if r.get("already"):
            return text({"already_live": True})
        log("request_live", f"script:{a['script']}", reason, after={"device": a["device"]}, result={"request": r.get("id")})
        return text(r, "Asked. A person sees it on the Run page and Home (and in notifications) and says yes or no; "
                       "nothing changes until then. Tell them what to look at before saying yes.")

    RUN_KEYS = ("max_per_min", "max_strikes", "manual_pause_s", "auto_save", "auto_save_per_hour", "live_view",
                "freeze_seconds", "blank_seconds", "start_wait_s")

    def run_setting(a):
        reason, key = need_reason(a), a["key"]
        if key not in RUN_KEYS:
            raise ToolError("key: " + ", ".join(RUN_KEYS))
        before = ((api.get("/api/shadow/control") or {}) or {}).get(key)
        r = api.send("POST", "/api/shadow/control", {key: a["value"]})
        return text({key: (r or {}).get(key, a["value"]), "before": before if before is not None else "(the default)",
                     "log_id": log("run_setting", f"control:{key}", reason, {key: before}, {key: a["value"]})})

    def setting_value(a):
        reason = need_reason(a)
        r = api.send("POST", "/api/settings/value", {"id": a["id"], "device": a.get("device"), "value": a.get("value")})
        return text({**r, "log_id": log("setting_value", f"setting:{a['id']}:{a.get('device') or '*'}", reason, r.get("old"), r.get("new"))})

    # ---------------------------------------------------------------- the tool list
    ro = {"readOnlyHint": True, "openWorldHint": False}
    act = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
    why = {"reason": {"type": "string", "description": "one sentence on why - kept with the action"}}
    dev = {"device": {"type": "string", "description": "a source id"}}
    return [
        {"name": "explain_rules", "title": "Why does a rule act or not", "handler": explain, "annotations": ro, "level": "read",
         "description": "Each rule of a main script in the device's current situation, each condition checked on what the runner sees now (holds / does not hold / unsure, the state's value), what it would decide, and whether the device is held. For 'why did it not act'.",
         "inputSchema": _schema({"script": {"description": "a main script id, or a whole draft"}, **dev}, ["script"])},
        {"name": "report", "title": "What happened", "handler": report, "annotations": ro, "level": "read",
         "description": "What happened in the last hours, per device: decisions and actions, warnings, incidents, health now, held devices, the AI's own changes, open requests, what needs doing. For a daily report.",
         "inputSchema": _schema({"hours": {"type": "number", "description": "default 24"}})},
        {"name": "list_requests", "title": "Requests to a person", "handler": requests, "annotations": ro, "level": "read",
         "description": "What an AI asked a person to decide (going live) and their answers.",
         "inputSchema": _schema()},
        {"name": "start_runner", "title": "Start the script runner", "handler": start, "annotations": act, "level": "run",
         "description": "Start the script runner (interval in seconds, default the project's). Held devices stay held.",
         "inputSchema": _schema({"interval": {"type": "number"}, **why}, ["reason"])},
        {"name": "stop_runner", "title": "Stop the script runner", "handler": stop, "annotations": act, "level": "run",
         "description": "Stop the script runner: nothing is watched or done until it starts again.",
         "inputSchema": _schema(why, ["reason"])},
        {"name": "hold_device", "title": "Stop / pause / resume", "handler": hold, "annotations": act, "level": "run",
         "description": "Stop (end what it does, hold its scripts), pause (hold where it is) or resume one device, or every one (device='*').",
         "inputSchema": _schema({**dev, "action": {"type": "string", "enum": ["stop", "pause", "resume"]}, **why}, ["action", "reason"])},
        {"name": "deploy", "title": "Deploy a script", "handler": deploy, "annotations": act, "level": "run",
         "description": "Set how a main script runs on one device: off or shadow (a dry run that only writes down what it would do). Live: request_live.",
         "inputSchema": _schema({"script": {"type": "string"}, **dev, "mode": {"type": "string", "enum": ["off", "shadow"]}, **why}, ["script", "device", "mode", "reason"])},
        {"name": "request_live", "title": "Ask to go live", "handler": request_live, "annotations": act, "level": "run",
         "description": "Ask a person to let a main script act for real on a device. They answer on the Run page (and are notified); nothing changes until they say yes.",
         "inputSchema": _schema({"script": {"type": "string"}, **dev, **why}, ["script", "device", "reason"])},
        {"name": "set_run_setting", "title": "A run setting", "handler": run_setting, "annotations": act, "level": "run",
         "description": "Change one run setting: " + ", ".join(RUN_KEYS) + " (get_run_status full=true shows them under control).",
         "inputSchema": _schema({"key": {"type": "string", "enum": list(RUN_KEYS)}, "value": {}, **why}, ["key", "value", "reason"])},
        {"name": "set_setting_value", "title": "A user setting's value", "handler": setting_value, "annotations": act, "level": "run",
         "description": "Set the value of a user setting (as people on site do on the operation panel), for one device or all; value null = back to the default.",
         "inputSchema": _schema({"id": {"type": "string"}, "device": {"type": "string"}, "value": {}, **why}, ["id", "reason"])},
    ]
