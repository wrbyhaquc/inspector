"""Inspector for an AI (mcp_server/): the protocol as clients speak it, secrets kept out, tools answering from the API."""
import io
import json

from mcp_server import protocol, tools


class FakeApi:
    """The running Inspector's API, as the tools ask it."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, route, **params):
        self.asked.append(route)
        if route not in self.answers:
            raise protocol.ToolError(f"Inspector answered 404: {route}")
        return self.answers[route]

    def image(self, route, **params):
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (1280, 720), (20, 40, 60)).save(b, "JPEG")
        return b.getvalue(), "image/jpeg"


def talk(server, *msgs):
    out = io.BytesIO()
    server.serve(io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in msgs)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def server(answers):
    return protocol.Server("inspector", "0.0.0", "hi", tools.make(FakeApi(answers)))


def test_a_client_starts_lists_and_calls_like_the_protocol_says():
    s = server({"/api/project": {"name": "Pond"}, "/api/next_steps": {"steps": []}, "/api/getting_started": {"done": {}},
                "/api/shadow/status": {"status": {"running": False}}, "/api/storage": {"free": 1}})
    init, lst, call, ping, bad = talk(s,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},                       # a notification: no answer
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_overview", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    names = [t["name"] for t in lst["result"]["tools"]]
    assert "get_overview" in names and all(t["annotations"]["readOnlyHint"] for t in lst["result"]["tools"])
    assert all(t["inputSchema"]["type"] == "object" for t in lst["result"]["tools"])
    assert json.loads(call["result"]["content"][0]["text"])["project"] == {"name": "Pond"}
    assert ping["result"] == {} and bad["error"]["code"] == -32601
    assert talk(s, {"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})[0]["result"]["protocolVersion"] == protocol.VERSIONS[0]


def test_a_failing_tool_tells_the_ai_why_instead_of_breaking():
    s = server({})
    r = talk(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_design", "arguments": {"part": "states"}}})[0]
    assert r["result"]["isError"] and "404" in r["result"]["content"][0]["text"]
    r = talk(s, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})[0]
    assert r["error"]["code"] == -32602
    assert talk(s, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "get_design", "arguments": {"part": "x"}}})[0]["result"]["isError"]
    out = io.BytesIO()
    s.serve(io.BytesIO(b"{not json\n"), out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


def test_secrets_never_leave():
    outputs = {"outputs": [{"id": "hook", "type": "http", "url": "https://discord.com/api/webhooks/123/abcdef",
                            "headers": {"Authorization": "Bearer xyz", "Accept": "json"}, "password": "pw", "pin": "1234",
                            "token_ttl": None, "enabled": True}],
               "note": "bot123456789:AAAbbbCCCdddEEEfffGGGhhh in the text"}
    s = server({"/api/outputs": outputs})
    r = talk(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_design", "arguments": {"part": "outputs"}}})[0]
    t = r["result"]["content"][0]["text"]
    for secret in ("abcdef", "Bearer", "pw\"", "1234", "AAAbbb"):
        assert secret not in t, secret
    o = json.loads(t)["outputs"][0]
    assert o["headers"] == "•••" and o["enabled"] is True and o["token_ttl"] is None      # headers carry keys: all masked


def test_pictures_come_back_as_images_the_size_asked():
    import base64
    from PIL import Image
    s = server({"/api/shadow/status": {"status": {"running": True}}})
    r = talk(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "view_screen", "arguments": {"device": "CAM", "width": 320}}})[0]
    img = [c for c in r["result"]["content"] if c["type"] == "image"][0]
    assert img["mimeType"] == "image/jpeg" and Image.open(io.BytesIO(base64.b64decode(img["data"]))).size == (320, 180)


def test_the_guide_reads_the_platforms_own_docs():
    s = server({"/api/spec": {"kinds": {"script": "x"}}})
    ask = lambda topic: talk(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "platform_guide", "arguments": {"topic": topic}}})[0]["result"]
    assert "Inspector for an AI" in ask("overview")["content"][0]["text"]
    assert "## Run and monitor" in ask("readme:Run and monitor (runtime)")["content"][0]["text"]
    assert ask("nonsense")["isError"]


# ---------------------------------------------------------------- stage 2: changing the design

class DesignApi(FakeApi):
    """A small design held in memory, changed through the same calls the pages make."""

    def __init__(self):
        super().__init__({})
        self.scripts = {"keeper": {"id": "keeper", "name": "Keeper", "devices": {"*": "off", "CAM": "live"}}}
        self.outputs = [{"id": "siren", "name": "Siren", "type": "http", "url": "http://x", "headers": {"X-Key": "REAL"}}]
        self.log, self.saved = [], []

    def get(self, route, **params):
        if route == "/api/scripts":
            return {"scripts": list(self.scripts.values()), "subs": [], "variables": []}
        if route == "/api/outputs":
            return {"outputs": json.loads(json.dumps(self.outputs))}
        if route == "/api/ai/log":
            return [e for e in self.log if e["id"] == params["id"]][0]
        return super().get(route, **params)

    def send(self, method, route, body=None, timeout=120):
        if route == "/api/ai/check":
            bad = body["kind"] == "script" and not body["doc"].get("name")
            return {"ok": not bad, "errors": [{"path": "name", "message": "missing"}] if bad else []}
        if route == "/api/ai/log":
            self.log.append({**body, "id": f"L{len(self.log)}"})
            return {"id": f"L{len(self.log) - 1}"}
        self.saved.append((method, route))
        if route == "/api/scripts":
            self.scripts[body["script"]["id"]] = body["script"]
            return {**body["script"], "version": 2}
        if method == "DELETE" and route.startswith("/api/scripts/"):
            self.scripts.pop(route.rsplit("/", 1)[1])
            return {}
        if route == "/api/outputs":
            self.outputs = body["outputs"]
            return {}
        raise AssertionError(route)


def call(s, name, **args):
    r = talk(s, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})[0]["result"]
    return r, "".join(c.get("text", "") for c in r["content"])


def test_an_ai_never_makes_a_script_live_and_must_say_why():
    from mcp_server import design
    api = DesignApi()
    s = protocol.Server("inspector", "0", "", design.make(api))
    new = {"id": "night", "name": "Night", "devices": {"*": "live", "CAM": "live"}}
    r, t = call(s, "save_script", script=new)
    assert r["isError"] and "reason" in t                                        # no reason, nothing saved
    r, t = call(s, "save_script", script={**new, "name": ""}, reason="x")
    assert r["isError"] and "missing" in t                                       # the platform's own check
    r, t = call(s, "save_script", script=new, reason="x", dry_run=True)
    assert not r.get("isError") and "night" not in api.scripts                   # only checked
    call(s, "save_script", script=new, reason="say when night falls")
    assert api.scripts["night"]["devices"] == {"*": "shadow", "CAM": "shadow"}   # a dry run, not live
    call(s, "save_script", script={**api.scripts["keeper"], "name": "Keeper 2"}, reason="rename")
    assert api.scripts["keeper"]["devices"]["CAM"] == "live"                     # live already: stays live


def test_a_deleted_script_comes_back_with_undo_and_secrets_survive_a_save():
    from mcp_server import design
    api = DesignApi()
    s = protocol.Server("inspector", "0", "", design.make(api))
    r, t = call(s, "delete_script", id="keeper", reason="test")
    assert "keeper" not in api.scripts
    call(s, "undo_change", log_id=json.loads(t)["log_id"], reason="back")
    assert api.scripts["keeper"]["devices"] == {"*": "off", "CAM": "live"}       # as a person had it, live included
    call(s, "save_output", output={"id": "siren", "name": "Siren (yard)", "type": "http", "url": "http://x", "headers": "•••"}, reason="where")
    assert api.outputs[0]["name"] == "Siren (yard)" and api.outputs[0]["headers"] == {"X-Key": "REAL"}
    call(s, "save_output", output={"id": "siren", "name": "Siren", "type": "http", "url": "http://x"}, reason="left out")
    assert api.outputs[0]["headers"] == {"X-Key": "REAL"}                        # left out = kept, not dropped


def test_a_path_written_before_the_work_folder_moved_is_found_again():
    import project
    assert project.rel_of(r"D:\old\work\pond\sessions\s1\devices\CAM\frames\1.png", r"C:\new\data\packs\pond\design") \
        == "sessions/s1/devices/CAM/frames/1.png"
    assert project.rel_of("sessions/a/b.png", r"C:\new\design") == "sessions/a/b.png"


def test_the_check_endpoint_says_what_is_wrong_without_saving(monkeypatch):
    from fastapi.testclient import TestClient
    import server.app as app
    c = TestClient(app.app, client=("127.0.0.1", 50000))
    r = c.post("/api/ai/check", json={"kind": "states", "doc": [{"id": "Bad Id", "type": "class"}]}).json()
    assert not r["ok"] and r["errors"]
    assert c.post("/api/ai/check", json={"kind": "variables", "doc": []}).json()["ok"]
    assert c.post("/api/ai/check", json={"kind": "nope", "doc": []}).status_code == 400
    lid = c.post("/api/ai/log", json={"tool": "save_state", "target": "states:x", "reason": "why", "before": None, "after": {"id": "x"}}).json()["id"]
    assert c.get("/api/ai/log", params={"id": lid}).json()["reason"] == "why"
    assert c.get("/api/ai/log").json()["items"][0]["id"] == lid


# ---------------------------------------------------------------- stage 3: looking after the run

def test_each_level_sees_only_its_tools_and_changes_are_limited():
    from mcp_server import build as m, design, run
    every = tools.make(FakeApi({})) + design.make(DesignApi()) + run.make(FakeApi({}))
    by = {lv: {t["name"] for t in every if m.level_of(t) in m.LEVELS[:m.LEVELS.index(lv) + 1]} for lv in m.LEVELS}
    assert "get_overview" in by["read"] and "save_script" not in by["read"] and "explain_rules" in by["read"]
    assert "save_script" in by["design"] and "hold_device" not in by["design"]
    assert {"hold_device", "deploy", "request_live", "start_runner"} <= by["run"]
    assert not any(n in by["run"] for n in ("approve", "run_schedule", "delete_recording", "move_data", "restart"))
    calls = __import__("collections").deque()
    f = m.limited(lambda a: "ok", calls)
    for _i in range(m.MAX_CHANGES):
        f({})
    try:
        f({})
        raise AssertionError("not limited")
    except protocol.ToolError as e:
        assert "changes in a minute" in str(e)


def test_deploy_never_goes_live_and_asking_is_the_way():
    from mcp_server import run
    api = DesignApi()
    s = protocol.Server("inspector", "0", "", run.make(api))
    r, t = call(s, "deploy", script="keeper", device="CAM", mode="live", reason="x")
    assert r["isError"] and "request_live" in t and api.scripts["keeper"]["devices"]["CAM"] == "live"
    call(s, "deploy", script="keeper", device="CAM", mode="shadow", reason="dry run first")
    assert api.scripts["keeper"]["devices"]["CAM"] == "shadow"


def test_only_a_person_can_say_yes_to_going_live(monkeypatch):
    from fastapi.testclient import TestClient
    import automation
    import server.app as app
    monkeypatch.setenv("INSPECTOR_EDITION", "studio")
    automation.save(app.DATA_ROOT, {"id": "keeper", "name": "Keeper", "enabled": True, "devices": {"*": "off", "CAM": "shadow"},
                                    "otherwise": {"type": "none", "text": ""}, "initial": "main",
                                    "situations": [{"id": "main", "name": "Main", "rules": []}]}, "test")
    c = TestClient(app.app, client=("127.0.0.1", 50000))
    assert c.post("/api/ai/requests", json={"script": "keeper", "device": "CAM", "reason": ""}).status_code == 400
    rid = c.post("/api/ai/requests", json={"script": "keeper", "device": "CAM", "reason": "it did right"}).json()["id"]
    assert any("AI" in s["title"] for s in c.get("/api/next_steps").json()["steps"])
    r = c.post(f"/api/ai/requests/{rid}/answer", json={"approve": True}, headers={"X-Actor": "ai"})
    assert r.status_code == 403 and automation.mode_for(next(s for s in automation.load_all(app.DATA_ROOT) if s["id"] == "keeper"), "CAM") == "shadow"
    assert c.post(f"/api/ai/requests/{rid}/answer", json={"approve": True}).json()["status"] == "approved"
    assert automation.mode_for(next(s for s in automation.load_all(app.DATA_ROOT) if s["id"] == "keeper"), "CAM") == "live"
    assert c.post(f"/api/ai/requests/{rid}/answer", json={"approve": False}).status_code == 400          # once


# ---------------------------------------------------------------- stage 4: over the network, a token per client

def test_mcp_over_http_needs_a_live_token_and_shows_its_levels_tools(monkeypatch):
    from fastapi.testclient import TestClient
    import server.app as app
    c = TestClient(app.app, client=("192.168.1.20", 50000))                      # another computer on the LAN
    local = TestClient(app.app, client=("127.0.0.1", 50000))
    rpc = lambda tok, m, i=1: c.post("/mcp", json={"jsonrpc": "2.0", "id": i, "method": m, "params": {"protocolVersion": "2025-06-18"}},
                                     headers={"Authorization": f"Bearer {tok}"} if tok else {})
    assert rpc(None, "tools/list").status_code == 401
    assert local.post("/api/ai/tokens", json={"name": "x"}, headers={"X-Actor": "ai"}).status_code == 403      # a person makes them
    assert c.post("/api/ai/tokens", json={"name": "x"}).status_code == 401                                    # not from the LAN without a PIN
    t = local.post("/api/ai/tokens", json={"name": "Office", "level": "read"}).json()
    assert "hash" not in t and t["token"].startswith("insp_")
    assert all("token" not in r and "hash" not in r for r in local.get("/api/ai/tokens").json()["items"])
    r = rpc(t["token"], "initialize")
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "inspector" and r.headers.get("mcp-session-id")
    names = {x["name"] for x in rpc(t["token"], "tools/list").json()["result"]["tools"]}
    assert "get_overview" in names and "save_script" not in names                                            # read level
    assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": f"Bearer {t['token']}"}).status_code == 202
    local.post(f"/api/ai/tokens/{t['id']}/revoke")
    assert rpc(t["token"], "tools/list").status_code == 401
    assert rpc("insp_made_up", "tools/list").status_code == 401


# ---------------------------------------------------------------- stage 5: ready-made ways of working

def test_prompts_are_listed_for_the_level_and_start_with_their_arguments():
    from mcp_server import build
    s = build.server(FakeApi({}), "read", "0")
    init, lst, get, missing = talk(s,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "prompts/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "daily_report", "arguments": {"hours": "12"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/get", "params": {"name": "build_solution"}})
    assert init["result"]["capabilities"]["prompts"] == {"listChanged": False}
    names = [p["name"] for p in lst["result"]["prompts"]]
    assert "daily_report" in names and "diagnose" in names and "build_solution" not in names and "check_before_live" not in names
    msg = get["result"]["messages"][0]
    assert msg["role"] == "user" and "12 hours" in msg["content"]["text"] and "report hours=12" in msg["content"]["text"]
    assert missing["error"]["code"] == -32602                                    # not at the read level
    names = [p["name"] for p in talk(build.server(FakeApi({}), "run", "0"), {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})[0]["result"]["prompts"]]
    assert {"build_solution", "check_before_live"} <= set(names)
