"""Stage 2: the AI changes the design, and checks its work before anyone relies on it.

Every change
  - says why (reason: kept in the version note and the AI log), and can be checked first (dry_run: nothing saved)
  - goes through the endpoints the pages use (the same checks; a runtime refuses design changes as for a person)
  - is written down with what was there before (/api/ai/log), so undo_change puts it back
  - never makes anything live: a main script the AI saves runs at most as a dry run ("shadow") on a device where it
    was not live already - going live is a person's decision on the Run page
Secrets stay out: an output's secret fields come back masked, and a masked or missing one is kept as it was."""
import copy
import time
import urllib.parse

from .protocol import ToolError
from .tools import SECRET_KEY, _arg, _schema, text

MASK = "•••"


def make(api):
    # ---------------------------------------------------------------- reading the current design
    def scripts():
        s = api.get("/api/scripts")
        return {x["id"]: x for x in s["scripts"]}, {x["id"]: {k: v for k, v in x.items() if k != "outline"} for x in s["subs"]}, s

    def states():
        return api.get("/api/states")["schema"]["states"]

    def need_reason(a):
        r = (a.get("reason") or "").strip()
        if not r:
            raise ToolError("reason is required: one sentence on why (it is kept with the change)")
        return r

    def log(tool, target, reason, before, after, result=None):
        try:
            return api.send("POST", "/api/ai/log", {"tool": tool, "target": target, "reason": reason, "before": before,
                                                    "after": after, "result": result})["id"]
        except ToolError:
            return None

    def checked(kind, doc):
        r = api.send("POST", "/api/ai/check", {"kind": kind, "doc": doc})
        if not r["ok"]:
            raise ToolError("not saved - the platform found:\n" + "\n".join(f"- {e['path']}: {e['message']}" for e in r["errors"]))

    def done(what, log_id, extra=None, notes=()):
        out = {"saved": what, "log_id": log_id, **(extra or {})}
        if notes:
            out["notes"] = list(notes)
        return text(out)

    # ---------------------------------------------------------------- main scripts
    def no_live(script, before):
        """A device may be live only where it was live already (before); else a dry run. -> notes"""
        notes, was = [], (before or {}).get("devices") or {}
        for k, m in list((script.get("devices") or {}).items()):
            if m == "live" and was.get(k) != "live":
                script["devices"][k] = "shadow"
                notes.append(f"{k}: set to shadow (dry run). Going live is a person's choice on the Run page.")
        return notes

    def save_script(a):
        doc = copy.deepcopy(a.get("script") or {})
        if not isinstance(doc, dict) or not doc.get("id"):
            raise ToolError("script must be an object with an id (see platform_guide topic=schema:script)")
        reason, (main, subs, _all) = need_reason(a), scripts()
        before = main.get(doc["id"])
        notes = no_live(doc, before)
        checked("script", doc)
        if a.get("dry_run"):
            return done("nothing (dry run): it would be saved", None, notes=notes)
        r = api.send("POST", "/api/scripts", {"script": doc, "note": f"AI: {reason}"})
        return done(f"main script {doc['id']} v{r.get('version')}", log("save_script", f"script:{doc['id']}", reason, before, r), notes=notes)

    def delete_script(a):
        reason, (main, _subs, _all) = need_reason(a), scripts()
        sid = a["id"]
        if sid not in main:
            raise ToolError(f"no main script {sid!r}")
        api.send("DELETE", f"/api/scripts/{urllib.parse.quote(sid)}")
        return done(f"main script {sid} deleted", log("delete_script", f"script:{sid}", reason, main[sid], None))

    # ---------------------------------------------------------------- sub-scripts
    def save_sub(a):
        doc = copy.deepcopy(a.get("sub") or {})
        if not isinstance(doc, dict) or not doc.get("id"):
            raise ToolError("sub must be an object with an id (see platform_guide topic=schema:sub)")
        reason, (_main, subs, _all) = need_reason(a), scripts()
        checked("sub", doc)
        if a.get("dry_run"):
            return done("nothing (dry run): it would be saved", None)
        r = api.send("POST", "/api/subscripts", {"sub": doc, "note": f"AI: {reason}"})
        return done(f"sub-script {doc['id']} v{r.get('version')}", log("save_subscript", f"sub:{doc['id']}", reason, subs.get(doc["id"]), r))

    def delete_sub(a):
        reason, (_main, subs, _all) = need_reason(a), scripts()
        sid = a["id"]
        if sid not in subs:
            raise ToolError(f"no sub-script {sid!r}")
        api.send("DELETE", f"/api/subscripts/{urllib.parse.quote(sid)}")
        return done(f"sub-script {sid} deleted", log("delete_subscript", f"sub:{sid}", reason, subs[sid], None))

    # ---------------------------------------------------------------- lists kept whole (one item changed at a time)
    def upsert(items, item, key="id"):
        out = [x for x in items if x.get(key) != item.get(key)]
        i = next((k for k, x in enumerate(items) if x.get(key) == item.get(key)), None)
        out.insert(i if i is not None else len(out), item)
        return out

    def list_change(kind, a, tool, item_key, read, write, key="id"):
        """Add / replace one item (a[item_key]) or delete one (a["delete"] = its id) in a list saved whole."""
        reason = need_reason(a)
        items = read()
        if a.get("delete"):
            gone = [x for x in items if x.get(key) == a["delete"]]
            if not gone:
                raise ToolError(f"no {kind} {a['delete']!r}; there are: " + ", ".join(str(x.get(key)) for x in items))
            new, target, before, after = [x for x in items if x.get(key) != a["delete"]], a["delete"], gone[0], None
        else:
            item = a.get(item_key)
            if not isinstance(item, dict) or not item.get(key):
                raise ToolError(f"{item_key} must be an object with its {key}")
            before = next((x for x in items if x.get(key) == item[key]), None)
            new, target, after = upsert(items, item, key), item[key], item
        checked(kind, new)
        if a.get("dry_run"):
            return done("nothing (dry run): it would be saved", None)
        write(new, reason)
        return done(f"{kind}: {target} {'deleted' if a.get('delete') else 'saved'}", log(tool, f"{kind}:{target}", reason, before, after))

    def save_state(a):
        return list_change("states", a, "save_state", "state", states,
                           lambda new, why: api.send("POST", "/api/states", {"states": new, "note": f"AI: {why}"}))

    def save_schedule(a):
        cur = api.get("/api/schedules")
        return list_change("schedules", a, "save_schedule", "schedule", lambda: cur["items"],
                           lambda new, why: api.send("POST", "/api/schedules", {"items": new, "day_start": cur.get("day_start")}))

    def save_setting(a):
        return list_change("settings", a, "save_user_setting", "setting", lambda: api.get("/api/settings")["settings"],
                           lambda new, why: api.send("POST", "/api/settings", {"settings": new}))

    def save_variable(a):
        return list_change("variables", a, "save_variable", "variable", lambda: api.get("/api/scripts")["variables"],
                           lambda new, why: api.send("POST", "/api/variables", {"vars": new}), key="name")

    def save_output(a):
        current = {o["id"]: o for o in api.get("/api/outputs")["outputs"]}
        o = a.get("output")
        if isinstance(o, dict) and o.get("id") in current:                 # secrets: masked or missing = as they were
            for k, v in current[o["id"]].items():
                if SECRET_KEY.search(k) and (k not in o or o[k] == MASK or (isinstance(o[k], dict) and MASK in o[k].values())):
                    o[k] = v
        return list_change("outputs", a, "save_output", "output", lambda: list(current.values()),
                           lambda new, why: api.send("PUT", "/api/outputs", {"outputs": new}))

    def save_panel(a):
        doc = a.get("panel")
        if not isinstance(doc, dict):
            raise ToolError("panel must be the whole panel object (get_design part=panel shows it)")
        reason = need_reason(a)
        checked("panel", doc)
        if a.get("dry_run"):
            return done("nothing (dry run): it would be saved", None)
        before = api.get("/api/panel/definition")["panel"]
        api.send("POST", "/api/panel/definition", {"panel": doc})
        return done("operation panel", log("save_panel", "panel", reason, before, doc))

    # ---------------------------------------------------------------- versions and undo
    VERSIONED = {"script": "/api/scripts/{id}", "sub": "/api/subscripts/{id}"}

    def versions(a):
        kind = a["kind"]
        if kind == "states":
            return text(api.get("/api/states").get("history"))
        if kind not in VERSIONED:
            raise ToolError("kind: script | sub | states")
        return text(api.get(VERSIONED[kind].format(id=urllib.parse.quote(a["id"])) + "/history"))

    def restore(a):
        reason, kind, v = need_reason(a), a["kind"], _arg(a, "version", int)
        if kind == "states":
            before = states()
            r = api.send("POST", "/api/states/restore", {"version": v, "note": f"AI: {reason}"})
            return done(f"states restored from v{v} as v{r.get('version')}", log("restore_version", "states", reason, before, r.get("states")))
        if kind not in VERSIONED:
            raise ToolError("kind: script | sub | states")
        old = api.get(VERSIONED[kind].format(id=urllib.parse.quote(a["id"])) + f"/v/{v}")
        old = {k: x for k, x in old.items() if k not in ("version", "created", "note", "format")}
        return (save_script if kind == "script" else save_sub)({"script" if kind == "script" else "sub": old,
                                                               "reason": f"{reason} (back to v{v})"})

    def undo(a):
        reason = need_reason(a)
        e = api.get("/api/ai/log", id=a["log_id"])
        kind, _sep, target = e["target"].partition(":")
        before = e.get("before")
        if e["tool"] in ("save_script", "delete_script"):
            if before is None:                                  # it was new: undoing is deleting it
                return delete_script({"id": target, "reason": f"undo {a['log_id']}: {reason}"})
            doc = {k: x for k, x in before.items() if k not in ("version", "created", "note", "format")}
            cur = scripts()[0].get(target)
            notes = no_live(doc, {"devices": {**((cur or {}).get("devices") or {}), **{k: m for k, m in (before.get("devices") or {}).items() if m == "live"}}})
            r = api.send("POST", "/api/scripts", {"script": doc, "note": f"AI undo: {reason}"})
            return done(f"main script {target} back as before (v{r.get('version')})", log("undo_change", e["target"], reason, cur, r), notes=notes)
        if e["tool"] in ("save_subscript", "delete_subscript"):
            if before is None:
                return delete_sub({"id": target, "reason": f"undo {a['log_id']}: {reason}"})
            doc = {k: x for k, x in before.items() if k not in ("version", "created", "note", "format", "outline")}
            return save_sub({"sub": doc, "reason": f"undo {a['log_id']}: {reason}"})
        if e["tool"] == "save_panel":
            return save_panel({"panel": before, "reason": f"undo {a['log_id']}: {reason}"})
        lists = {"save_state": (save_state, "state", "id"), "save_schedule": (save_schedule, "schedule", "id"),
                 "save_user_setting": (save_setting, "setting", "id"), "save_variable": (save_variable, "variable", "name"),
                 "save_output": (save_output, "output", "id")}
        if e["tool"] in lists:
            fn, key, _k = lists[e["tool"]]
            why = f"undo {a['log_id']}: {reason}"
            return fn({"delete": target, "reason": why} if before is None else {key: before, "reason": why})
        if e["tool"] == "restore_version" and kind == "states":
            return text({"note": "states are versioned: use restore_version kind=states with the version before"})
        raise ToolError(f"cannot undo a {e['tool']}")

    def ai_log(a):
        return text(api.get("/api/ai/log", limit=_arg(a, "limit", int, 30, 1, 500)))

    # ---------------------------------------------------------------- checking the work
    def try_rule(a):
        st = a.get("state")
        if isinstance(st, str):
            hit = [s for s in states() if s["id"] == st]
            if not hit:
                raise ToolError(f"no state {st!r}")
            st = hit[0]
        if not isinstance(st, dict):
            raise ToolError("state: a state id, or a whole state definition (saved or not)")
        n = _arg(a, "frames", int, 200, 1, 400)
        r = api.send("POST", "/api/rules/preview", {"state": st, "n": n, "seed": _arg(a, "seed", int, 0)})
        items = r.get("items") or []
        by = {}
        for i in items:
            by.setdefault(str(i.get("value")), []).append(i)
        out = {"frames": len(items), "answers": {k: len(v) for k, v in by.items()},
               "examples": {k: [i["frame"] for i in v[:3]] for k, v in by.items()},
               "gated": sum(1 for i in items if i.get("gated"))}
        if r.get("suggest") is not None:
            out["suggested_thresholds"] = r["suggest"]
        ans = [i for i in items if i.get("answer") is not None]
        if ans:
            out["against_answers"] = {"answered": len(ans), "agree": sum(1 for i in ans if i.get("value") == i["answer"]),
                                      "undecided": sum(1 for i in ans if i.get("value") is None)}
        ratios = [i["ratio"] for i in items if i.get("ratio") is not None]
        if ratios:
            out["ratio"] = {"min": min(ratios), "max": max(ratios)}
        return text(out, "None = the rule cannot tell. view_frame shows an example.")

    def replay(a):
        body = {"session": a["session"], "device": a["device"], "start": _arg(a, "start", float, 0, 0),
                "minutes": _arg(a, "minutes", float, 10, 0.1, 240), "sub_result": a.get("sub_result") or "success"}
        if a.get("script"):
            body["script"] = a["script"]                    # an unsaved draft instead of the saved one with its id
        rid = api.send("POST", "/api/replay", body)["id"]
        t0 = time.time()
        while time.time() - t0 < 600:
            r = api.get(f"/api/replay/{urllib.parse.quote(rid)}")
            if r.get("status") == "done":
                res = r["result"]
                events = [{"t": round(ev["t"] - res["ticks"][0]["t"], 1), "kind": ev["kind"], "text": ev.get("text")}
                          for tk in res["ticks"] for ev in tk.get("events") or []][:_arg(a, "limit", int, 150, 1, 1000)]
                changes, last = [], None
                for tk in res["ticks"]:                     # when the decisions changed (not every tick)
                    d = [(x.get("script"), x.get("rule_name"), x.get("action")) for x in tk.get("decisions") or []]
                    if d != last:
                        changes.append({"t": round(tk["t"] - res["ticks"][0]["t"], 1), "frame": tk["frame"],
                                        "decisions": [{"script": s, "rule": rn, "action": ac} for s, rn, ac in d]})
                        last = d
                return text({"replay": rid, "summary": res["summary"], "events": events, "decision_changes": changes[:100]},
                            "Nothing was tapped or sent: a replay only writes down what would happen.")
            if r.get("status") in ("failed", "stopped"):
                raise ToolError("the replay failed: " + " ".join(r.get("log") or []))
            time.sleep(1)
        raise ToolError(f"the replay {rid} is still running; get it later with get_design or try a shorter stretch")

    def run_tests(a):
        api.send("POST", "/api/tests/run", {"ids": a.get("ids") or []})
        t0 = time.time()
        while time.time() - t0 < 900:
            time.sleep(1.5)
            r = api.get("/api/tests")
            if (r.get("job") or {}).get("status") != "running":
                return text({"job": {k: (r.get("job") or {}).get(k) for k in ("status", "log")},
                             "tests": [{k: t.get(k) for k in ("id", "name", "last")} for t in r.get("tests") or []]})
        raise ToolError("the tests are still running")

    def check_design(a):
        r = api.send("POST", "/api/ai/check", {"kind": a["kind"], "doc": a.get("doc")})
        return text(r)

    # ---------------------------------------------------------------- the tool list
    ch = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
    rm = {**ch, "destructiveHint": True}
    ro = {"readOnlyHint": True, "openWorldHint": False}
    why = {"reason": {"type": "string", "description": "one sentence on why - kept with the change"},
           "dry_run": {"type": "boolean", "description": "only check: nothing is saved"}}
    one = lambda name, what: _schema({name: {"type": "object", "description": what}, "delete": {"type": "string", "description": "instead: the id to delete"}, **why}, ["reason"])
    return [
        {"name": "check_design", "title": "Check a design", "handler": check_design, "annotations": ro,
         "description": "Check a design document without saving it: kind script | sub | panel (an object), states | schedules | settings | variables | outputs (the whole list).",
         "inputSchema": _schema({"kind": {"type": "string", "enum": ["script", "sub", "states", "schedules", "settings", "variables", "outputs", "panel"]}, "doc": {}}, ["kind", "doc"])},
        {"name": "save_script", "title": "Save a main script", "handler": save_script, "annotations": ch,
         "description": "Add or replace a main script (the whole object, by id; platform_guide topic=schema:script). A new version is kept. It never goes live: devices not live before run it as a dry run (shadow).",
         "inputSchema": _schema({"script": {"type": "object"}, **why}, ["script", "reason"])},
        {"name": "delete_script", "title": "Delete a main script", "handler": delete_script, "annotations": rm,
         "description": "Delete a main script (undo_change brings it back).",
         "inputSchema": _schema({"id": {"type": "string"}, "reason": why["reason"]}, ["id", "reason"])},
        {"name": "save_subscript", "title": "Save a sub-script", "handler": save_sub, "annotations": ch,
         "description": "Add or replace a sub-script (the whole object, by id; platform_guide topic=schema:sub). A new version is kept.",
         "inputSchema": _schema({"sub": {"type": "object"}, **why}, ["sub", "reason"])},
        {"name": "delete_subscript", "title": "Delete a sub-script", "handler": delete_sub, "annotations": rm,
         "description": "Delete a sub-script nothing calls (undo_change brings it back).",
         "inputSchema": _schema({"id": {"type": "string"}, "reason": why["reason"]}, ["id", "reason"])},
        {"name": "save_state", "title": "Save a state", "handler": save_state, "annotations": ch,
         "description": "Add or replace one state definition (by id), or delete one (delete=id). Try its rule first with try_state_rule.",
         "inputSchema": one("state", "a whole state definition (get_design part=states shows their shape)")},
        {"name": "save_schedule", "title": "Save a schedule", "handler": save_schedule, "annotations": ch,
         "description": "Add or replace one schedule (by id), or delete one (delete=id).",
         "inputSchema": one("schedule", "a whole schedule (get_design part=schedules shows their shape)")},
        {"name": "save_user_setting", "title": "Save a user setting", "handler": save_setting, "annotations": ch,
         "description": "Add or replace one user setting declaration (a value people on site may change), or delete one.",
         "inputSchema": one("setting", "a whole setting declaration (get_design part=settings)")},
        {"name": "save_variable", "title": "Save a variable", "handler": save_variable, "annotations": ch,
         "description": "Add or replace one variable (by name), or delete one (delete=name).",
         "inputSchema": one("variable", "{name, label, scope: global|device, reset, initial}")},
        {"name": "save_output", "title": "Save an output", "handler": save_output, "annotations": ch,
         "description": "Add or replace one output (where scripts send things: HTTP, MQTT, Home Assistant), or delete one. Secret fields shown as ••• are kept as they are.",
         "inputSchema": one("output", "a whole output (get_design part=outputs)")},
        {"name": "save_panel", "title": "Save the operation panel", "handler": save_panel, "annotations": ch,
         "description": "Replace the operation panel (the whole object from get_design part=panel, changed).",
         "inputSchema": _schema({"panel": {"type": "object"}, **why}, ["panel", "reason"])},
        {"name": "list_versions", "title": "Versions", "handler": versions, "annotations": ro,
         "description": "The saved versions of a main script, a sub-script or the states.",
         "inputSchema": _schema({"kind": {"type": "string", "enum": ["script", "sub", "states"]}, "id": {"type": "string"}}, ["kind"])},
        {"name": "restore_version", "title": "Restore a version", "handler": restore, "annotations": ch,
         "description": "Save an older version of a main script, a sub-script or the states again as the newest.",
         "inputSchema": _schema({"kind": {"type": "string", "enum": ["script", "sub", "states"]}, "id": {"type": "string"},
                                 "version": {"type": "integer"}, "reason": why["reason"]}, ["kind", "version", "reason"])},
        {"name": "get_ai_log", "title": "AI changes", "handler": ai_log, "annotations": ro,
         "description": "The changes AI clients made (newest first), each with its reason, what was before and after, and the log_id undo_change takes.",
         "inputSchema": _schema({"limit": {"type": "integer"}})},
        {"name": "undo_change", "title": "Undo a change", "handler": undo, "annotations": ch,
         "description": "Put back what was there before one change in the AI log (a new one is deleted, a deleted one comes back).",
         "inputSchema": _schema({"log_id": {"type": "string"}, "reason": why["reason"]}, ["log_id", "reason"])},
        {"name": "try_state_rule", "title": "Try a state's rule", "handler": try_rule, "annotations": ro,
         "description": "Run a state's screen rule (saved, or a draft definition) on recorded frames: how many frames get each answer, examples, how it agrees with a person's answers, and for colour ratios suggested thresholds.",
         "inputSchema": _schema({"state": {"description": "a state id or a whole (draft) state definition"}, "frames": {"type": "integer", "description": "1-400, default 200"},
                                 "seed": {"type": "integer"}}, ["state"])},
        {"name": "replay_script", "title": "Replay the scripts on a recording", "handler": replay, "annotations": ro,
         "description": "Run the scripts over a recorded stretch (list_recordings) and say what they would have done, when the decisions changed and why. Nothing is tapped or sent. script= replays an unsaved draft instead of the saved one with its id.",
         "inputSchema": _schema({"session": {"type": "string"}, "device": {"type": "string"}, "start": {"type": "number", "description": "seconds from the recording's start"},
                                 "minutes": {"type": "number"}, "script": {"type": "object"}, "sub_result": {"type": "string", "enum": ["success", "fail"]},
                                 "limit": {"type": "integer"}}, ["session", "device"])},
        {"name": "run_tests", "title": "Run the script tests", "handler": run_tests, "annotations": ro,
         "description": "Run the script tests (all, or ids=) and give their results: a change that broke something shows here.",
         "inputSchema": _schema({"ids": {"type": "array", "items": {"type": "string"}}})},
    ]
