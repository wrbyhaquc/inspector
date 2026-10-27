# Inspector for an AI (MCP)

An AI client that speaks the [Model Context Protocol](https://modelcontextprotocol.io) - Claude Desktop, Claude Code
and others - connects to the Inspector running on a computer and works with it in plain words: it reads the design
and the run, changes the design for you, and looks after the run. You do not open the source code; the AI uses
Inspector the way its pages do, with the same checks.

## What it can do, by level

| Level | What the AI may do | Tools |
|---|---|---|
| `read` | Look at everything: the project, sources, states, scripts, schedules, panel, settings, outputs (secrets masked); what each device sees and decides now, the timeline, the log, incidents with their clips, the live screen, recorded frames, recordings, training runs, tests, storage. Explain why a rule acts or not. Report what happened. Check a design without saving, try a state's rule on recordings, replay scripts, run the tests. | 23 |
| `design` (default) | Also change the design: main scripts, sub-scripts, states, schedules, user settings, variables, outputs, the operation panel. Every change needs a reason, is a new version, is in the AI log, and can be undone. | 35 |
| `run` | Also start / stop the script runner, stop / pause / resume devices, deploy a script off or as a dry run, change run settings and user setting values, and ask a person to let a script go live. | 42 |

### What it never does, at any level

- **Make anything live.** A main script it saves runs as a dry run on every device where it was not live already.
  It can only *ask* (`request_live`): the request shows on the Run page and Home, and in notifications; a person
  answers Yes or No. An AI cannot answer it.
- Run a schedule or a sub-script right now, delete recordings or models, move the data, restart Inspector.
- See secrets: passwords, tokens, PINs, webhook addresses and HTTP headers are masked; when it saves an output, a
  masked or left-out secret stays as it was.
- More than 30 changes a minute.

## Connecting

The **AI access** page (This computer › AI access) writes all of this for you.

### On the same computer (suggested)

The AI client starts `python -m mcp_server` itself (stdio); no token is needed.

```bash
cd <the Inspector folder>
claude mcp add inspector -- python -m mcp_server --level design
```

Claude Desktop, in `claude_desktop_config.json` (then reopen Claude):

```json
{"mcpServers": {"inspector": {"command": "python", "args": ["-m", "mcp_server", "--level", "design"], "cwd": "<the Inspector folder>"}}}
```

Options: `--url` (the running Inspector, default `http://127.0.0.1:8765`), `--level read|design|run`, `--lang`
(the language Inspector answers in), `--name` (what the AI log calls this client).

### From another computer

Make a **token** on the AI access page (a name and a level; it is shown once, only its hash is kept, it can be
revoked). The AI client connects to Inspector's own `/mcp` address with it:

```bash
claude mcp add --transport http inspector http://<the Inspector computer>:8765/mcp --header "Authorization: Bearer <token>"
```

Inspector takes connections from its own computer only unless started with `--lan`. On a LAN the token is not
encrypted; from outside, go through an encrypted tunnel (Tailscale, a VPN). Without a token nothing gets in.

## Ready-made ways of working (prompts)

Pick one in the AI client (Claude Desktop: the + menu; Claude Code: `/mcp__inspector__<name>`):

| Prompt | Level | What the AI does |
|---|---|---|
| `daily_report` | read | What happened lately and what needs you, short and plain |
| `diagnose` | read | Why a device did (or did not) do something - status, the screen, each rule's conditions, the timeline - then a fix to check |
| `build_solution` | design | From what you want watched and done to a script running as a dry run: states proven on recordings, actions, the main script replayed |
| `check_before_live` | run | Proves a script on the recordings and the tests, then asks you to let it act for real |

Or just ask: "How are things now?", "Why did the aerator not start last night?", "Make the heron rule wait 5
seconds and show me what it would have done yesterday."

## Keeping track

- **AI log** (AI access page, or `get_ai_log`): every change and action with its time, the client (token name), the
  reason, and what was there before. **Undo** puts a design change back.
- **Versions**: scripts, sub-scripts and states keep every version (`list_versions`, `restore_version`); an AI's
  version notes start with "AI:".
- **Requests**: what an AI asked a person to decide, on the Run page and the AI access page.

## Troubleshooting

- *"Inspector is not reachable"*: Inspector must be running (the AI talks to it); check `--url` and the port.
- *401 from /mcp*: no token, a wrong one, or a revoked one - make a new one on the AI access page.
- *A tool is missing*: the client's level does not include it (`--level`, or the token's level).
- *"the script runner is not running"* from explain / view_screen: start it on the Run page (or `start_runner` at
  the run level).
- A Runtime (the run-only edition) refuses design changes, as it does for a person.
