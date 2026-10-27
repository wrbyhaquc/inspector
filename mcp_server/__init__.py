"""Inspector for an AI (MCP): an AI client - Claude Desktop, Claude Code or any other that speaks the Model Context
Protocol - connects to the Inspector running on this computer and can read its design and its run (stage 1: only
reading). It talks to Inspector's own web API, so the same checks hold as for the pages.

    python -m mcp_server [--url http://127.0.0.1:8765] [--lang en]

Claude Desktop (claude_desktop_config.json) / Claude Code (claude mcp add):
    {"mcpServers": {"inspector": {"command": "python", "args": ["-m", "mcp_server"], "cwd": "<the Inspector folder>"}}}
    claude mcp add inspector -- python -m mcp_server        (run in the Inspector folder)"""
