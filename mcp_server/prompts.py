"""Ready-made ways of working (MCP prompts): the person picks one in their AI client (Claude Desktop: the + menu;
Claude Code: /mcp__inspector__<name>) and the AI goes through it step by step with the tools. Each needs a level:
a client sees only what its level can carry out."""


LANG = "Answer in the person's language (the language they write in; Inspector's own words are often Chinese)."


def build_solution(a):
    goal = a.get("goal") or "(ask the person)"
    return f"""Help me make a solution on this Inspector: {goal}

Work step by step and show me each step before the next. {LANG}
1. Look first: get_overview, get_design part=sources and part=states, list_recordings. Tell me what is already there.
2. Ask me what to watch for and what should happen (who / what acts: a tap, an output to equipment, a notification),
   and when it must not act. Keep the questions few and plain.
3. If the picture needed is not recorded yet, tell me what to record (Recording page) and wait.
4. States: for each thing to judge, draft a state (platform_guide topic=readme:States (state definitions)), prove it
   with try_state_rule on the recordings (use the suggested thresholds when they fit), show me example frames
   (view_frame) of each answer, then save_state.
5. Actions: sub-scripts for multi-step actions, outputs for equipment (save_subscript, save_output).
6. The main script: rules "when ... do ..." in priority order (platform_guide topic=schema:script). Replay it on
   the recordings with replay_script (a draft can be replayed before saving) and tell me what it would have done
   and when; fix what is wrong; then save_script (it runs as a dry run).
7. Tell me how to watch the dry run (Run page, Details) and what to check before it goes live. Do not ask to go
   live yourself unless I say so."""


def diagnose(a):
    dev = a.get("device") or "(ask which one)"
    problem = a.get("problem") or "(ask what was expected and what happened)"
    return f"""Something is not right on device {dev}: {problem}

Find out why before changing anything. {LANG}
1. get_run_status device={dev}: is the runner running, the source healthy, the device held or paused, which mode
   each script runs in (off / dry run / live)?
2. view_screen device={dev}: look at what it sees now.
3. explain_rules for the script concerned: which condition does not hold, with the state's value.
4. get_timeline for that device (and list_incidents if it was urgent): what happened and when.
5. If a state judges wrongly, prove it: try_state_rule on the recordings, view_frame on examples.
Then tell me plainly: what happened, why, and what you suggest - as a change I can check first (dry_run=true,
replay_script). Make the change only when I agree."""


def daily_report(a):
    hours = a.get("hours") or "24"
    return f"""Give me a report of the last {hours} hours on this Inspector, for a person who has no time. {LANG}
Use report hours={hours}; for each incident in it, view_incident (a few frames). Then write, short:
- the headline: is everything all right?
- what needs me (warnings, held devices, sources with no or a blank picture, requests waiting for my yes, the next
  steps the platform lists)
- what happened per device (in plain words, not counts alone)
- what AIs changed (get_ai_log) and anything that looks off
End with what you would do next, if anything."""


def check_before_live(a):
    script = a.get("script") or "(ask which main script)"
    dev = a.get("device") or "(ask which device)"
    return f"""Check whether main script {script} is ready to act for real on device {dev}. {LANG}
1. get_design part=scripts id={script}: say in plain words what it does and when.
2. Replay it on the recordings of that device (list_recordings, replay_script): the moments it would act and why;
   also stretches where it must NOT act. Look at a few frames (view_frame) where it decides.
3. run_tests: all script tests pass?
4. get_timeline for {dev}: what its dry run did lately (decisions it wrote down).
Tell me what you found, any doubt, and your recommendation. If it is ready and I agree, use request_live with a
reason that says what was checked - a person still answers it on the Run page."""


PROMPTS = [
    {"name": "build_solution", "level": "design", "title": "Make a solution", "text": build_solution,
     "description": "From what you want watched and done to a script running as a dry run: states proven on recordings, actions, the main script replayed.",
     "arguments": [{"name": "goal", "description": "what it should do, in your words (optional)", "required": False}]},
    {"name": "diagnose", "level": "read", "title": "Find out why", "text": diagnose,
     "description": "Why a device did (or did not) do something: status, the screen, each rule's conditions, the timeline - then a suggested fix.",
     "arguments": [{"name": "device", "description": "the device (source id or name)", "required": False},
                   {"name": "problem", "description": "what was expected and what happened", "required": False}]},
    {"name": "daily_report", "level": "read", "title": "Daily report", "text": daily_report,
     "description": "What happened lately and what needs you, short and plain.",
     "arguments": [{"name": "hours", "description": "how far back (default 24)", "required": False}]},
    {"name": "check_before_live", "level": "run", "title": "Check before going live", "text": check_before_live,
     "description": "Prove a main script on the recordings and the tests before asking you to let it act for real.",
     "arguments": [{"name": "script", "description": "the main script id", "required": False},
                   {"name": "device", "description": "the device", "required": False}]},
]
