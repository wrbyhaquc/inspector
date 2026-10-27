"""Inspector's own MCP address for AI clients over the network: POST /mcp (the Model Context Protocol's streamable
HTTP transport, answering with plain JSON), each client with its own token ("Authorization: Bearer <token>", made on
the AI page: server/ai_api.py). The token's level decides the tools; the tools ask this same server's API on
127.0.0.1, so every check holds as for the pages. No token, or a revoked one: refused.

Inspector listens on this computer only unless started with --lan; on a LAN the token goes in the clear, so beyond
it use an encrypted tunnel (Tailscale, a VPN)."""
import json
import secrets

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from i18n import _

router = APIRouter()
_servers = {}                    # token id -> (level, MCP server): one per client, its change limit with it


def _server(row, port, lang):
    from mcp_server import build, tools
    from project.manifest import PLATFORM_VERSION
    hit = _servers.get(row["id"])
    if not hit or hit[0] != row["level"]:
        hit = (row["level"], build.server(tools.Api(f"http://127.0.0.1:{port}", lang, client=row["name"]), row["level"], PLATFORM_VERSION))
        _servers[row["id"]] = hit
    return hit[1]


@router.post("/mcp")
async def mcp(request: Request):
    from .ai_api import token_of
    row = token_of(request.headers.get("authorization"))
    if not row:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": _("需要有效的權杖(在「AI 接入」頁建立)")}},
                            status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        msg = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
    server = _server(row, request.url.port, request.headers.get("x-lang"))
    msgs = msg if isinstance(msg, list) else [msg]
    out = [o for o in [await run_in_threadpool(server.handle, m) for m in msgs if isinstance(m, dict)] if o]
    if not out:                                          # only notifications / answers: accepted
        return Response(status_code=202)
    headers = {}
    if any(isinstance(m, dict) and m.get("method") == "initialize" for m in msgs):
        headers["Mcp-Session-Id"] = secrets.token_hex(16)
    return JSONResponse(out if isinstance(msg, list) else out[0], headers=headers)


@router.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})     # no server-sent stream: every answer comes back at once


@router.delete("/mcp")
def mcp_end():
    return Response(status_code=200)                                 # nothing kept per session
