"""The Model Context Protocol over stdio, by hand: JSON-RPC 2.0, one message per line on stdin / stdout (logs go to
stderr). Only what this server needs: initialize, ping, tools/list, tools/call, prompts/list, prompts/get. No SDK: the
official one pulls in a newer Starlette / Pydantic than the platform's FastAPI runs with, and this much is small.
A prompt (a ready-made way of working the person picks in their AI client): {"name", "title", "description",
"arguments": [{"name", "description", "required"}], "text": fn(arguments) -> the message it starts with}.

A tool: {"name", "title", "description", "inputSchema" (JSON Schema), "annotations"} and a handler(arguments) ->
a list of content items ({"type": "text", "text"} / {"type": "image", "data": base64, "mimeType"}); raising ToolError
(or anything else) answers with isError and the reason, so the AI can read it and try again."""
import json
import sys
import traceback

VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]       # newest first


class ToolError(Exception):
    pass


class Server:
    def __init__(self, name, version, instructions, tools, prompts=()):
        self.name, self.version, self.instructions = name, version, instructions
        self.tools = {t["name"]: t for t in tools}
        self.prompts = {p["name"]: p for p in prompts}           # {"name", "title", "description", "arguments", "text"(args)}

    # ---------- the requests ----------
    def _initialize(self, p):
        asked = (p or {}).get("protocolVersion")
        caps = {"tools": {"listChanged": False}, **({"prompts": {"listChanged": False}} if self.prompts else {})}
        return {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0], "capabilities": caps,
                "serverInfo": {"name": self.name, "version": self.version},
                "instructions": self.instructions}

    def _prompts(self, p):
        return {"prompts": [{k: x[k] for k in ("name", "title", "description", "arguments") if k in x} for x in self.prompts.values()]}

    def _prompt(self, p):
        x = self.prompts.get((p or {}).get("name"))
        if not x:
            raise _RpcError(-32602, f"unknown prompt: {(p or {}).get('name')}")
        args = {k: str(v) for k, v in ((p or {}).get("arguments") or {}).items()}
        missing = [a["name"] for a in x.get("arguments") or [] if a.get("required") and not args.get(a["name"])]
        if missing:
            raise _RpcError(-32602, "missing: " + ", ".join(missing))
        return {"description": x["description"], "messages": [{"role": "user", "content": {"type": "text", "text": x["text"](args)}}]}

    def _list(self, p):
        return {"tools": [{k: t[k] for k in ("name", "title", "description", "inputSchema", "annotations") if k in t}
                          for t in self.tools.values()]}

    def _call(self, p):
        t = self.tools.get((p or {}).get("name"))
        if not t:
            raise _RpcError(-32602, f"unknown tool: {(p or {}).get('name')}")
        try:
            return {"content": t["handler"]((p or {}).get("arguments") or {})}
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:                                   # noqa: BLE001 - said to the AI, never a crash
            traceback.print_exc(file=sys.stderr)
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}

    def handle(self, msg):
        """One message -> the answer (None for a notification)."""
        method, mid = msg.get("method"), msg.get("id")
        if method is None or "id" not in msg:                    # a notification (initialized, cancelled ...) or an answer
            return None
        try:
            fn = {"initialize": self._initialize, "ping": lambda p: {}, "tools/list": self._list,
                  "tools/call": self._call, "prompts/list": self._prompts, "prompts/get": self._prompt}.get(method)
            if not fn:
                raise _RpcError(-32601, f"method not found: {method}")
            return {"jsonrpc": "2.0", "id": mid, "result": fn(msg.get("params"))}
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": e.message}}

    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            else:
                out = [self.handle(m) for m in msg] if isinstance(msg, list) else self.handle(msg)
                if isinstance(out, list):
                    out = [o for o in out if o] or None
            if out:
                stdout.write(json.dumps(out, ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message
