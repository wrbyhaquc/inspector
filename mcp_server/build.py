"""One MCP server for one AI client: the tools its level allows, changes limited per minute. Used by the local command
(python -m mcp_server, stdio) and by Inspector's own /mcp address (a token per client, server/mcp_http.py)."""
import collections
import time

from . import design, protocol, run, tools

LEVELS = ("read", "design", "run")      # each includes the ones before it
MAX_CHANGES = 30                        # changes (not reads) a minute: an AI going round in circles is stopped


def level_of(t):
    return t.get("level") or ("read" if t["annotations"].get("readOnlyHint") else "design")


def limited(handler, recent):
    def call(a):
        now = time.time()
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= MAX_CHANGES:
            raise protocol.ToolError(f"more than {MAX_CHANGES} changes in a minute: stop, look at what was done (get_ai_log), and tell the person")
        recent.append(now)
        return handler(a)
    return call


def server(api, level, version):
    allowed = LEVELS[:LEVELS.index(level) + 1]
    recent = collections.deque()
    every = [t for t in tools.make(api) + design.make(api) + run.make(api) if level_of(t) in allowed]
    for t in every:
        if not t["annotations"].get("readOnlyHint"):
            t["handler"] = limited(t["handler"], recent)
    intro = tools.GUIDE.split("\n## ", 1)[0] + f"\nAllowed here: {level} ({', '.join(allowed)}). Call platform_guide first if this is new to you."
    from .prompts import PROMPTS
    return protocol.Server("inspector", version, intro, every, [p for p in PROMPTS if p["level"] in allowed])
