import argparse
import os
import sys

from . import build, tools


def main():
    ap = argparse.ArgumentParser(prog="python -m mcp_server", description="Inspector for an AI (Model Context Protocol, stdio)")
    ap.add_argument("--url", default=os.environ.get("INSPECTOR_URL", "http://127.0.0.1:8765"), help="the running Inspector")
    ap.add_argument("--lang", default=os.environ.get("INSPECTOR_MCP_LANG"), help="the language Inspector answers in (default: the machine's)")
    ap.add_argument("--level", choices=build.LEVELS, default=os.environ.get("INSPECTOR_MCP_LEVEL", "design"),
                    help="read: look only; design: also change the design (never live); run: also start / stop / hold / deploy (default design)")
    ap.add_argument("--name", default=os.environ.get("INSPECTOR_MCP_NAME", "local"), help="what the AI log calls this client")
    a = ap.parse_args()
    from project.manifest import PLATFORM_VERSION
    s = build.server(tools.Api(a.url, a.lang, client=a.name), a.level, PLATFORM_VERSION)
    print(f"Inspector MCP: {a.url} ({a.level}, {len(s.tools)} tools)", file=sys.stderr, flush=True)
    s.serve()


if __name__ == "__main__":
    main()
