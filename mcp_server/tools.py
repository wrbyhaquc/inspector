"""The tools an AI gets (stage 1: reading only). Each one asks the running Inspector's own API, so what the pages
may see is what the AI may see; secrets (passwords, tokens, PINs, webhook addresses) are masked before anything
leaves. Pictures come back as images the AI can look at."""
import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .protocol import ToolError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TEXT = 60000                  # characters of one answer; the rest is cut (the AI is told)
SECRET_KEY = re.compile(r"token|password|passwd|secret|(^|_)pin($|_)|api_?key|authorization|cookie|webhook|^headers$", re.I)
SECRET_TEXT = re.compile(r"https://(discord(app)?\.com/api/webhooks|hooks\.slack\.com)/\S+|bot\d+:[\w-]{20,}", re.I)


class Api:
    """The running Inspector's HTTP API (as the pages use it), from this computer."""

    def __init__(self, base, lang=None, client=""):
        self.base, self.lang, self.client = base.rstrip("/"), lang, client      # client: whose changes these are (the AI log)

    def _open(self, route, params=None, timeout=60, method="GET", body=None):
        url = self.base + route + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else "")
        headers = {"X-Lang": self.lang} if self.lang else {}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json"
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={**headers, "X-Actor": "ai", **({"X-AI-Client": urllib.parse.quote(self.client)} if self.client else {})})
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}").get("detail")
            except ValueError:
                detail = None
            raise ToolError(f"Inspector answered {e.code}: {detail or e.reason}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ToolError(f"Inspector is not reachable at {self.base} ({e}). Is it running?") from None

    def get(self, route, **params):
        with self._open(route, params) as r:
            return json.loads(r.read() or b"null")

    def image(self, route, **params):
        with self._open(route, params) as r:
            return r.read(), r.headers.get("Content-Type", "image/jpeg")

    def send(self, method, route, body=None, timeout=120):
        """POST / PUT / DELETE, as the pages do; the answer (JSON)."""
        with self._open(route, None, timeout, method, body if body is not None else ({} if method != "DELETE" else None)) as r:
            return json.loads(r.read() or b"null")


# ---------------------------------------------------------------- what goes back
def redact(x):
    """Secrets out, recursively: a value under a secret-looking key, or text that is a webhook / bot token."""
    if isinstance(x, dict):
        return {k: ("•••" if SECRET_KEY.search(str(k)) and v not in (None, "", [], {}) and not isinstance(v, bool) else redact(v))
                for k, v in x.items()}
    if isinstance(x, list):
        return [redact(v) for v in x]
    if isinstance(x, str):
        return SECRET_TEXT.sub("•••", x)
    return x


def text(obj, note=None):
    s = obj if isinstance(obj, str) else json.dumps(redact(obj), ensure_ascii=False, indent=1, default=str)
    if len(s) > MAX_TEXT:
        s = s[:MAX_TEXT] + f"\n… (cut: {len(s) - MAX_TEXT} more characters; ask for less, e.g. one id)"
    return [{"type": "text", "text": (note + "\n\n" if note else "") + s}]


def picture(data, mime, width=None):
    """An image item, made smaller when asked (fewer tokens for the AI)."""
    if width:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=85)
            data, mime = b.getvalue(), "image/jpeg"
        except Exception:                                  # noqa: BLE001 - the full one then
            pass
    return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime}


def _arg(a, k, kind, default=None, lo=None, hi=None):
    v = a.get(k, default)
    if v is None:
        return None
    try:
        v = kind(v)
    except (TypeError, ValueError):
        raise ToolError(f"{k} must be a {kind.__name__}") from None
    if kind in (int, float):
        v = max(lo, v) if lo is not None else v
        v = min(hi, v) if hi is not None else v
    return v


def _schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


# ---------------------------------------------------------------- the platform guide
GUIDE = """# Inspector for an AI: what the platform is

Inspector watches screens or cameras (sources), judges states on them (screen rules or a trained model), and runs
scripts that act (taps, keys, outputs to equipment) - designed in its web pages, no code. You are connected to one
running Inspector on this computer: you can look at everything, and change the design (scripts, sub-scripts, states,
schedules, user settings, variables, outputs, the operation panel) - never what runs live (see "Changing the design").

## The parts (and the tool that shows them)
- project: name, what a source / an item is called, the screen coordinate space          get_overview
- sources: the pictures watched (emulators, windows, screens, cameras, video files,      get_design part=sources
  recordings replayed); each has an id (used everywhere) and a name (shown to people)
- states: what is judged on the picture - classes (yes/no, day/night...) or numbers     get_design part=states
  (a bar's fill, digits). Each has an area (roi) and a source: a screen rule
  (color_ratio, bar, template, digits) or the model
- recordings, answers (a person's answers per frame = the test set), training runs       list_recordings, get_models
- scripts: main scripts run all the time; a script has situations, each with rules        get_design part=scripts
  "when <conditions> do <steps>"; the first rule that holds acts. Priority order decides
  which main script acts on a device. Guard rules hold the others. Sub-scripts are
  reusable step lists (tap a button, wait until a state, call another, send to an output)
- buttons (named tap positions or pictures to find), variables, lists, outputs            get_design part=library
  (HTTP / MQTT / Home Assistant ...), user settings (values people on site change)
- schedules: a sub-script at a time on chosen devices                                     get_design part=schedules
- operation panel: the page for people on site (blocks of switches, settings, widgets)    get_design part=panel
- script tests: a recorded stretch replayed with what the scripts are expected to do      get_tests

## Running (get_run_status, get_timeline, get_log, list_incidents, view_screen)
The script runner looks at every source every interval, judges the states, and decides per script. Each script
runs per device in a mode: off, shadow (dry run: only writes down what it would do) or live (acts). A device can be
stopped (scripts and situations held) or paused; "hold_all" is everyone. Health per source: ok / slow / lost /
blank (one colour) / frozen. Urgent rules open an incident with its story and a clip (view_incident).

## Words
Inspector's pages speak the machine's language (often Chinese); ids are stable, names are for people.
When you explain to a person, use names; when you refer to data, give ids too.

## Changing the design
1. Read first: get_design (and platform_guide topic=schema:<kind> for the exact fields), list_recordings.
2. Draft, then check without saving: dry_run=true on any save_* tool, or check_design.
3. Prove it on what was recorded: try_state_rule for a state (and its suggested thresholds), replay_script for a
   script (a draft can be replayed before it is saved), run_tests after a change.
4. Save with a reason (one sentence; it is kept). Every change is a new version and is in get_ai_log; undo_change
   puts one back, restore_version goes back to any version.
A main script you save never goes live: devices that were not live run it as a dry run (shadow), and a person
decides on the Run page when it acts for real. Tell the person what you changed and what to check.

## Looking after the run
- "Why did it (not) act?": explain_rules - each condition of each rule on what the runner sees now.
- A daily report: report hours=24 - per device, warnings, incidents, health, held devices, your own changes.
- At the "run" level (the person chose it when connecting you): start_runner / stop_runner, hold_device (stop,
  pause, resume one device or all), deploy (off or shadow), set_run_setting, set_setting_value.
- Going live is never yours: request_live asks the person, who answers on the Run page; tell them what to check.
- Not for you at all: running a schedule or a sub-script now, deleting recordings or models, moving the data,
  restarting Inspector - say what you would do and let the person do it.

## Good habits
- Start with get_overview (it lists what needs doing), then narrow down.
- To answer "why did X (not) happen": get_run_status (the decisions now), get_timeline for that device,
  view_screen to see it, get_design part=scripts for the rule.
- Recorded frames are referred to by their path (e.g. sessions/<id>/devices/<src>/frames/<n>.png): view_frame shows one.
- Topics for more: platform_guide topic=scripts | tutorial | readme:<section> | schema:<kind>.
"""

README_SECTIONS = ["States (state definitions)", "Sources and recording", "Answer questions (the test set)",
                   "Training (trainer)", "What scripts are made of", "Run and monitor (runtime)",
                   "Notifications and chat commands (`notify/`)", "Script tests (runtime/replaytest.py)", "Packs"]


def _doc(name):
    try:
        with open(os.path.join(ROOT, "docs", name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        raise ToolError(f"docs/{name} is not there") from None


def _readme(section):
    try:
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            s = f.read()
    except OSError:
        raise ToolError("README.md is not there") from None
    m = re.search(r"^## " + re.escape(section) + r"\s*$(.*?)(?=^## |\Z)", s, re.M | re.S)
    if not m:
        raise ToolError(f"no README section {section!r}; there are: " + ", ".join(README_SECTIONS))
    return f"## {section}\n{m.group(1).strip()}"


def make(api):
    """The tools, bound to one Inspector."""

    def guide(a):
        topic = (a.get("topic") or "overview").strip()
        if topic == "overview":
            return text(GUIDE)
        if topic == "scripts":
            return text(_doc("scripts.md"))
        if topic == "tutorial":
            return text(_doc("tutorial.md"))
        if topic.startswith("readme:"):
            return text(_readme(topic[7:].strip()))
        if topic.startswith("schema:"):
            return text(api.get(f"/api/spec/schema/{urllib.parse.quote(topic[7:].strip())}"))
        spec = api.get("/api/spec")
        raise ToolError("topics: overview, scripts, tutorial, readme:<" + " | ".join(README_SECTIONS) + ">, schema:<"
                        + " | ".join(spec.get("kinds") or {}) + ">")

    def overview(a):
        st = (api.get("/api/shadow/status") or {}).get("status") or {}
        return text({"project": api.get("/api/project"), "next_steps": api.get("/api/next_steps"),
                     "first_steps_done": api.get("/api/getting_started").get("done"),
                     "runner": {k: st.get(k) for k in ("running", "started", "updated", "model", "model_backend", "interval",
                                                      "decisions", "hold_all")}
                     | {"devices": [d.get("name") for d in st.get("devices") or []]},
                     "storage": {k: v for k, v in api.get("/api/storage").items() if k in ("sizes", "free", "days_left", "keep", "min_free_gb", "when_full")}})

    PARTS = ("sources", "states", "scripts", "library", "schedules", "panel", "settings", "outputs")

    def design(a):
        part = a.get("part")
        if part == "sources":                               # the ones set up (not the catalog of every kind)
            s = api.get("/api/sources")
            return text({"sources": s.get("items") if isinstance(s, dict) else s, "found_now": api.get("/api/devices")})
        if part == "states":
            return text(api.get("/api/states").get("schema"))
        if part == "scripts":
            s = api.get("/api/scripts")
            sid = a.get("id")
            out = {"order": s["order"], "scripts": s["scripts"], "subscripts": s["subs"], "used_by": s.get("used_by")}
            if sid:
                hit = [x for x in s["scripts"] + s["subs"] if x.get("id") == sid]
                if not hit:
                    raise ToolError(f"no script or sub-script {sid!r}; ids: " + ", ".join(x["id"] for x in s["scripts"] + s["subs"]))
                return text(hit[0])
            return text(out)
        if part == "library":
            s = api.get("/api/scripts")
            return text({k: s.get(k) for k in ("buttons", "variables", "lists", "settings", "outputs")})
        if part == "schedules":
            return text(api.get("/api/schedules"))
        if part == "panel":
            return text(api.get("/api/panel/definition").get("panel"))
        if part == "settings":
            return text(api.get("/api/settings"))
        if part == "outputs":
            return text(api.get("/api/outputs"))
        raise ToolError("part must be one of: " + ", ".join(PARTS))

    def run_status(a):
        st = (api.get("/api/shadow/status") or {}).get("status") or {}
        dev = a.get("device")
        devs = st.get("devices") or []
        if dev:
            devs = [d for d in devs if d.get("name") == dev]
            if not devs:
                raise ToolError(f"no device {dev!r} in the runner now; there are: " + ", ".join(d.get("name") for d in st.get("devices") or []))
        if not a.get("full"):                               # the parts that answer "what is it doing and why"
            devs = [{k: d.get(k) for k in ("name", "window", "health", "held", "hold", "situations", "proc")}
                    | {"state": {k: {"value": v.get("value"), "conf": v.get("conf"), "source": v.get("source")} for k, v in (d.get("state") or {}).items()}
                       if isinstance(d.get("state"), dict) else d.get("state"),
                       "decisions": [{k: x.get(k) for k in ("script", "script_name", "situation_name", "rule_name", "action", "text", "reason", "exec", "mode")}
                                     for x in d.get("decisions") or []]} for d in devs]
        return text({"running": st.get("running"), "updated": st.get("updated"), "interval": st.get("interval"),
                     "model_backend": st.get("model_backend"), "hold_all": st.get("hold_all"), "devices": devs})

    def timeline(a):
        return text(api.get("/api/shadow/timeline", device=a["device"], minutes=_arg(a, "minutes", float, 60, 1, 60 * 24 * 7))[:_arg(a, "limit", int, 200, 1, 2000)])

    def log(a):
        return text(api.get("/api/shadow/log", limit=_arg(a, "limit", int, 100, 1, 1000)))

    def incidents(a):
        return text(api.get("/api/incidents", limit=_arg(a, "limit", int, 20, 1, 200)))

    def incident(a):
        iid = a["id"]
        d = api.get(f"/api/incidents/{urllib.parse.quote(iid)}")
        out = text({k: v for k, v in d.items() if k != "clip"} | {"clip_frames": len(d.get("clip") or [])})
        n = _arg(a, "frames", int, 4, 0, 12)
        clip = d.get("clip") or []
        if n and clip:                                       # evenly through the clip: before, at and after the trigger
            pick = sorted({round(i * (len(clip) - 1) / max(1, n - 1)) for i in range(n)})
            for i in pick:
                t, name = clip[i]
                data, mime = api.image(f"/api/incidents/{urllib.parse.quote(iid)}/clip/{urllib.parse.quote(name)}")
                out += [{"type": "text", "text": f"clip frame {i + 1}/{len(clip)}: {t - d['start']:+.0f} s from the trigger"},
                        picture(data, mime, _arg(a, "width", int, 640, 160, 1280))]
        elif n:
            for e in [e for e in d.get("entries") or [] if e.get("frame")][:n]:
                data, mime = api.image(f"/api/incidents/{urllib.parse.quote(iid)}/frame/{urllib.parse.quote(e['frame'])}")
                out += [{"type": "text", "text": f"{e['kind']} {e['t'] - d['start']:+.0f} s: {e.get('text') or ''}"},
                        picture(data, mime, _arg(a, "width", int, 640, 160, 1280))]
        return out

    def screen(a):
        name = a["device"]
        st = (api.get("/api/shadow/status") or {}).get("status") or {}
        note = f"{name} now" if st.get("running") else \
            f"{name}: the script runner is not running, so this is the last picture it saw (not now)"
        for _i in range(6):                                  # the runner writes live frames once someone looks
            try:
                data, mime = api.image(f"/api/shadow/live/{urllib.parse.quote(name)}")
                return [{"type": "text", "text": note}, picture(data, mime, _arg(a, "width", int, 960, 160, 1920))]
            except ToolError as e:
                if "404" not in str(e):
                    raise
                time.sleep(1)
        raise ToolError(f"no live picture of {name!r}: the script runner must be running with that source (get_run_status)")

    def frame(a):
        data, mime = api.image("/api/image", path=a["path"], view=1)
        return [{"type": "text", "text": a["path"]}, picture(data, mime, _arg(a, "width", int, 960, 160, 1920))]

    def recordings(a):
        return text(api.get("/api/sessions")[:_arg(a, "limit", int, 30, 1, 500)])

    def models(a):
        return text(api.get("/api/train/runs"))

    def tests(a):
        return text(api.get("/api/tests"))

    def storage(a):
        return text({"storage": api.get("/api/storage"), "settings": api.get("/api/storage/settings"),
                     "location": api.get("/api/storage/location"), "cleanings": api.get("/api/storage/history", limit=20)})

    ro = {"readOnlyHint": True, "openWorldHint": False}
    dev = {"device": {"type": "string", "description": "a source id (get_run_status lists them)"}}
    width = {"width": {"type": "integer", "description": "make pictures this wide at most (fewer tokens)"}}
    return [
        {"name": "platform_guide", "title": "Platform guide", "handler": guide, "annotations": ro,
         "description": "What Inspector is and how its parts fit (start here), or a topic: scripts, tutorial, readme:<section>, schema:<kind> (the JSON schema scripts are written in).",
         "inputSchema": _schema({"topic": {"type": "string", "description": "overview (default) | scripts | tutorial | readme:<section> | schema:<kind>"}})},
        {"name": "get_overview", "title": "Overview", "handler": overview, "annotations": ro,
         "description": "The project, what needs doing next (the platform's own list), which first steps are done, whether the script runner runs, the disk.",
         "inputSchema": _schema()},
        {"name": "get_design", "title": "Design", "handler": design, "annotations": ro,
         "description": "One part of the design: sources, states, scripts (main scripts + sub-scripts; id= for one), library (buttons, variables, lists, user settings, outputs), schedules, panel, settings (user settings and their values), outputs.",
         "inputSchema": _schema({"part": {"type": "string", "enum": list(PARTS)}, "id": {"type": "string", "description": "scripts: one script or sub-script"}}, ["part"])},
        {"name": "get_run_status", "title": "Run status", "handler": run_status, "annotations": ro,
         "description": "What the script runner sees and decides now, per device: health, each state's value and confidence, each script's decision and why, held / paused, situations, the sub-script running.",
         "inputSchema": _schema({**dev, "full": {"type": "boolean", "description": "everything the runner writes (large)"}})},
        {"name": "get_timeline", "title": "Timeline", "handler": timeline, "annotations": ro,
         "description": "What happened on one device lately, newest first: decisions, inputs, sub-script steps, situation changes, alerts.",
         "inputSchema": _schema({**dev, "minutes": {"type": "number", "description": "how far back (default 60)"}, "limit": {"type": "integer"}}, ["device"])},
        {"name": "get_log", "title": "Run log", "handler": log, "annotations": ro,
         "description": "The runner's log of every device, newest first (inputs, calls, alerts).",
         "inputSchema": _schema({"limit": {"type": "integer", "description": "default 100"}})},
        {"name": "list_incidents", "title": "Incidents", "handler": incidents, "annotations": ro,
         "description": "Urgent incidents, newest first: when, which device, which rules, what was done or not.",
         "inputSchema": _schema({"limit": {"type": "integer", "description": "default 20"}})},
        {"name": "view_incident", "title": "One incident", "handler": incident, "annotations": ro,
         "description": "One incident's whole story, and pictures from its clip (before, at and after the trigger).",
         "inputSchema": _schema({"id": {"type": "string"}, "frames": {"type": "integer", "description": "pictures to include, 0-12 (default 4)"}, **width}, ["id"])},
        {"name": "view_screen", "title": "Screen now", "handler": screen, "annotations": ro,
         "description": "The live picture of one source, as the script runner sees it (the runner must be running).",
         "inputSchema": _schema({**dev, **width}, ["device"])},
        {"name": "view_frame", "title": "Recorded frame", "handler": frame, "annotations": ro,
         "description": "One recorded frame by its path (as other tools give it, e.g. sessions/<id>/devices/<src>/frames/<n>.png).",
         "inputSchema": _schema({"path": {"type": "string"}, **width}, ["path"])},
        {"name": "list_recordings", "title": "Recordings", "handler": recordings, "annotations": ro,
         "description": "The recordings (sessions), newest first: when, how long, which sources, how many frames.",
         "inputSchema": _schema({"limit": {"type": "integer", "description": "default 30"}})},
        {"name": "get_models", "title": "Training runs", "handler": models, "annotations": ro,
         "description": "The training runs and their test scores per state.",
         "inputSchema": _schema()},
        {"name": "get_tests", "title": "Script tests", "handler": tests, "annotations": ro,
         "description": "The script tests, what each expects, and the last results.",
         "inputSchema": _schema()},
        {"name": "get_storage", "title": "Storage", "handler": storage, "annotations": ro,
         "description": "What the data takes, how long the disk lasts, how long things are kept, where the data is, the cleanings so far.",
         "inputSchema": _schema()},
    ]
