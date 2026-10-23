# Inspector

**Watch a screen, act on it.** Connect a picture source → teach Inspector to read the states on that screen → automate with scripts you build without writing code.

English · [繁體中文](README.zh-TW.md)

**What it does**

- **Watches any screen**: Android devices and emulators (adb), app windows, parts of the desktop, RTSP/HTTP cameras, video files.
- **Learns to read it**: you define the states that matter (a button visible, a bar's level, a number, a zone) and teach it with a few answers; it trains its own model, no code.
- **Acts on it with no-code scripts**: rules, situations, sub-scripts, schedules, lists and variables; taps and swipes, or HTTP / MQTT / Home Assistant outputs for things off the screen.
- **Lets people run it**: a simple operation panel for phones, Discord / Telegram notifications and chat commands, every action logged.
- **Ships as packs**: export a whole setup as a versioned release and install or upgrade it on another computer (Studio to design, Runtime to run).

**See it work**: three demos, each tried in 10 minutes with no model to train. Nobody touches anything in these clips.

- [Whack-a-mole](https://github.com/wrbyhaquc/inspector-demo-whack-a-mole), a game in a window: Inspector watches the screen and clicks every mole that pops up, never a bomb, in the background while the mouse stays free.
- [A fish pond](https://github.com/wrbyhaquc/inspector-demo-pond), one camera: at night the fish come up gasping and Inspector turns the aerator on; in the morning a heron lands and it is scared away.
- [A small farm](https://github.com/wrbyhaquc/inspector-demo-farm), two cameras: it reads the greenhouse thermometer and opens the roof vents, waters only the bed that dried out, sounds the alarm at a fox, and shuts the hen house door once every hen is in.

![Inspector playing whack-a-mole: it clicks every mole and never a bomb](https://raw.githubusercontent.com/wrbyhaquc/inspector-demo-whack-a-mole/main/docs/demo.gif)

![Inspector looking after a simulated fish pond](https://raw.githubusercontent.com/wrbyhaquc/inspector-demo-pond/main/docs/demo.gif)

![Inspector looking after a simulated farm: a greenhouse and a hen house](https://raw.githubusercontent.com/wrbyhaquc/inspector-demo-farm/main/docs/demo.gif)

<img src="https://raw.githubusercontent.com/wrbyhaquc/inspector-demo-farm/main/docs/panel.png" alt="The farm's operation panel: each camera with its own buttons" width="640">

The platform knows nothing about any particular app, device or scene. What to watch, how to judge it and what to do are all settings of a **project**.
Abilities a scene needs beyond that (its own screen rules, extra data sources, other kinds of devices) come from the project's **plugins**, and the two are bundled together as a **pack**.

**Principles**

- At run time Inspector only looks at the screen: it takes pictures from a picture source and sends input such as taps. It does not modify or forge network packets and does not read or write other programs' memory.
- Adding or changing a state to watch, or a script, is done in the interface; no code changes.
- The platform code is never specialized for one scene; scene-specific things live in plugins, inside packs (`<data>/packs/<id>/`, each pack in its own repository).
- The interface comes in 繁體中文, English, 简体中文, 日本語 and 한국어 (see [docs/i18n.md](docs/i18n.md)).

---

## Requirements

- **Windows 10 / 11** is the main platform. Window capture, screen capture and mouse / keyboard input (`drivers/window.py`, `desktop.py`, `winput.py`) work on Windows only; Android devices (through adb), cameras / streams and video files work elsewhere too.
- **Python 3.12** and **Node.js 20.19 or later** (to build the web interface once).
- For Android devices: **adb** on `PATH` (Android platform-tools), or the one an emulator brings (LDPlayer's is found by itself).
- A graphics card is optional: training is much faster with an NVIDIA card (CUDA); running uses ONNX, which on Windows accelerates any card through DirectML and otherwise uses the CPU.
- Disk: the Studio with PyTorch takes several GB; recordings take space too (a frame is a PNG of the project's screen size).

## Install and start

**Studio** (design, labeling, training, running, making packs):

```bash
# install torch / torchvision first, the CUDA build from https://pytorch.org (or the CPU build)
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
start.bat                           # or: python -m server  → opens http://127.0.0.1:8765
```

**Runtime** (install packs and run them: the monitor, the operation panel, notifications; no design pages, no training, no PyTorch, about 370 MB):

```bash
pip install -r requirements-runtime.txt
cd web && npm install && npm run build && cd ..
start.bat
```

Models run as ONNX there, with the same answers as PyTorch; training a model needs the Studio (on this or another computer).

Both are the same program. An installation with PyTorch starts as a Studio, one without as a Runtime; `"edition": "studio"` or `"runtime"` in `inspector.json` (or `INSPECTOR_EDITION`) chooses explicitly. In a Runtime the pack's design is read-only: what the people running it change - where each script runs, a rule's limits, schedule times and arguments, the names a list walk captured, the operation panel's values - is kept in the runtime folder on top of the pack, so installing a newer version of the pack keeps all of it. Design changes are made in a Studio and arrive as a new release ("Packs").

**Start options** (`python -m server …`):

| Option | |
|---|---|
| `--port 8765` | The port of the interface |
| `--no-browser` | Do not open a browser |
| `--lan` | Let phones and other computers on the same network connect (set the sign-in PINs first: "Operation panel design › Phone connection and sign-in") |
| `--start-runner` | Start the script runner too, with the settings it last ran with |

`run_service.bat` keeps Inspector running in the background (a second start is refused, and it restarts by itself if it stops); `restart_inspector.bat` restarts it.

**This computer's settings**: `inspector.json` in `%USERPROFILE%\.inspector\` (`~/.config/inspector/` outside Windows; `INSPECTOR_CONFIG` names another file). It is never in the program folder, so replacing or updating the program keeps it; one left there by an older version is moved on the first start. Created as needed:

```json
{"data": "D:\\InspectorData", "work": "E:\\InspectorWork", "language": "en", "train_cache": "D:\\InspectorCache\\train"}
```

| Key | |
|---|---|
| `data` | The data folder (below). Default: `data` beside the settings, so a new computer needs no setting at all |
| `work` | Where the work data goes (recordings, labels, models; large): `<work>/<pack id>/`. Default `<data>/work` |
| `language` | The language of run logs, notifications and chat bot replies (also under "Run › ⚙ Run settings") |
| `edition` | `studio` or `runtime` (see above). Default: `studio` with PyTorch installed, else `runtime` |
| `train_cache` | Resized frames for training, written once and read every epoch; on an SSD. Default `<data>/runtime/<id>/train_cache` |
| `project`, `runtime` | Only for an older single project folder (used when `data` is not set) |

The environment variables `INSPECTOR_DATA`, `INSPECTOR_WORK`, `INSPECTOR_PACK`, `INSPECTOR_EDITION` and `INSPECTOR_TRAIN_CACHE` take precedence. `python -m project where` shows where everything is on this computer.

**Data folder**: the program folder holds code only, and every pack is kept apart, so updating the platform or swapping a pack never touches the rest:

```
<data>/active.json          {"pack": "<id>"}: the pack that runs
<data>/packs/<id>/          what the pack ships: pack.json, plugin/, design/ (project.json + meta/), models/
<work>/<id>/                what working on it makes: sessions, labels, testset, models, shadow (may be another disk)
<data>/runtime/<id>/        this computer only: the users' values, live state, PINs, chat bots, output secrets
<data>/logs/                the service's logs (run_service.bat)
```

To move an older single project folder there (the original is only read; run it again to bring over newer changes):

```bat
python -m project.layout migrate --project D:\inspector\myproject --runtime D:\inspector\runtime --data D:\InspectorData --work E:\InspectorWork --link
```

`--link` hard-links pictures and model files on the same disk instead of copying them; `--activate` switches this computer to the new layout. Taking `"data"` out of `inspector.json` goes back to the old folder.

**Languages**: each browser picks its own (bottom of the sidebar, top right of the operation panel).

## First steps with an empty project

Inspector comes with no project or pack; you build your own. A new computer starts with an empty pack, `default` (`<data>/packs/default/`): its design is your project. "Home: next steps" always shows what to do next; this is the whole path once:

1. **Sources**: "+ Add source", scan this computer (emulators, phones, windows, screens, cameras, video files), tick the ones to use. Check that the screen size matches the project's coordinate space (`screen` in `project.json`, 1280×720 by default); a different aspect ratio is reported on the page.
2. **States**: "+ Add state" for the first thing to recognize, e.g. "is the start button visible" (class: yes / no). Draw its area on a sample frame, choose a screen rule (reference image match is the easiest: pick a few frames for each answer).
3. **Recording**: record a while, going through the screens you care about (each answer of each state should appear).
4. **Auto-labeling**: "Generate labels" (it also runs after a recording by default).
5. **Answer questions**: answer about 20–30 test questions per state (at least 3 per answer). These only score the model.
6. **Training**: start a training run (Studio). Until a state passes the test, scripts judge it with its screen rule, so you can go on meanwhile.
7. **Scripts**: a main script with one rule: *if* the start button is visible, *then* tap it. Buttons to tap are named in "Library › Buttons".
8. **Run**: "Start the runner". New scripts and sources start in **dry run**: watch the timeline to see what it *would* do.
9. When it looks right, switch it to **live** in "Run › Deploy". Stop / pause / resume any time, per device or for all.
10. Optional: an **operation panel** for the people using it, **schedules**, **notifications** and chat commands, **script tests**.

To hand the result to another computer, export it as a pack and install it there ("Packs"; the page is under "④ Deliver").

The menu follows the order of use:

| Part | Page | What it does |
|---|---|---|
| | **Home: next steps** | What to do now (too few test questions, new screens not learned yet, uncertain frames saved by scripts…), with a button to go there |
| ① What to watch | **States** | Which states on the screen to watch, which area each looks at, which answers it has; each state's training progress |
| | **Sources**, **Recording** | Choose picture sources; start / stop recording (the collector) |
| ② Teach it to see | **Answer questions** | Answer test questions by hand; ask one question only, add questions, answer frames saved while running; name the entries of name libraries |
| | **Training** | Train the model |
| | **Scores & mistakes** | Test scores of each training run, frames answered wrong |
| ③ Automate | **Scripts**, **Script tests**, **Schedules**, **Library** | Guard rules, main scripts, sub-scripts, variables, buttons, lists, templates, outputs, user settings, replay |
| | **Run** | Start the runner; deploy scripts to devices; stop / pause / resume; each device's live state and timeline |
| | **Operation panel design**, **Operation panel** | A simple page for the people using it (settings, schedules, buttons), also usable from a chat bot |
| ④ Deliver | **Packs** | The installed packs and the one that runs; install or upgrade a release, switch, restart |
| Advanced tools (collapsed) | **Screen browser**, **Auto-labeling** | Look at internal details |

A Runtime shows only **Home**, **Run**, **Sources**, **Operation panel** and **Packs**.

---

## Where things are

A project is the design of a pack. `<data>`, `<work>` and the settings are described under "Install and start"; `python -m project where` prints them for this computer.

| Where | Contents |
|---|---|
| `%USERPROFILE%\.inspector\inspector.json` | This computer's settings: where the data folder is, its language, its edition |
| `<data>/active.json` | The pack that runs |
| `<data>/packs/<id>/pack.json` | What the pack is and needs ("Packs") |
| `<data>/packs/<id>/plugin/` | The pack's plugin ("Plugins") |
| `<data>/packs/<id>/design/project.json` | Project name, coordinate space (`screen`), default app, words (`words`, e.g. what a device is called), device sources (`devices`), plugins to load (`plugins`) |
| `<data>/packs/<id>/design/meta/` | The whole design: `states/` (state definitions), `rule_templates/` (reference images), `scripts/`, `subscripts/`, `variables.json`, `buttons.json` and `buttons/`, `lists.json`, `schedules.json`, `panel.json`, `user_settings.json`, `templates.json`, `tests.json`, name libraries |
| `<work>/<id>/sessions/`, `labels/`, `testset/`, `models/`, `shadow/` | Recorded data, auto-labels, the test set, trained models, what the runner kept (logs, audit frames, uncertain frames) |
| `<data>/runtime/<id>/` | This computer's own: the users' values, overrides and list names, live state, PINs, chat bots, output secrets; `runtime.json` is its format (older ones are upgraded after a backup in `.backup/`) |
| `<data>/logs/` | The service's logs |

Settings are versioned or append-only, so a bad change can be rolled back. Nothing above is in the program folder.

## Plugins

A plugin is a Python package in the pack's `plugin/` folder with `register(reg)` in `plugin.py`; `pack.json` names it (`"plugin"`) and it is imported as `packs.<name>`. A project lists the plugins to load under `plugins` in `project.json`. Plugin points (`project/plugins.py`):

| Kind | Purpose |
|---|---|
| `rule` | A kind of screen rule (answers one or more states at once; the interface is described in `labeler/rules.py`) |
| `label_source` | A source of answers for auto-labeling besides screen rules (e.g. a scene's own data; `labeler/build.py`) |
| `recorder` | Data recorded while collecting besides screenshots (`collector/collector.py`) |
| `source` | A device source: where pictures come from and where actions go (`drivers/__init__.py`) |
| `gallery_cut` | How a name library cuts out names (`labeler/gallery.py`) |
| `notify` | A notification channel (Discord and others are built in; `notify/channels.py`) |
| `api` | The plugin's own web API, mounted at `/api/plugins/<name>/` |

A plugin that fails to load (or a pack that needs a newer Inspector) does not stop the platform; "Home: next steps" says why.

## Packs

A pack = one plugin + one project design (states, reference images, buttons, lists, scripts, schedules, panel…), optionally with a trained model (ONNX and its test report only). Recorded data is never included.
Packs are made by the people who use Inspector, and deployed or published by them; this repository contains none.

The pack you are developing is a folder in the data folder layout, `<data>/packs/<id>/` (`pack.json`, `plugin/`, `design/`), and it is meant to be a git repository of its own: the recordings, labels, models, the users' values and the secrets all live outside it (`work/` and `runtime/`), so what git sees is only the pack's source. A **release** is what you give to others: export makes one zip of the pack without its history, backups, logs and older script versions. Installing a newer release upgrades the pack in place and keeps every value the people running it changed.

> Secrets stay on this machine: the sign-in PINs (`<data>/runtime/<id>/access.json`), chat bots (`<data>/runtime/<id>/notify.json`) and the secret fields of outputs (HTTP headers, MQTT password, Home Assistant token, in `<data>/runtime/<id>/output_secrets.json`) are never exported. The rest of an output (its URL, host, topic) is part of the design and goes with the pack: check it before giving a pack to anyone.

```bash
python -m project.pack export [--version 1.2.0] [--model latest] [--out <folder>]   # the active pack -> <id>-<version>.zip (default <data>/releases)
python -m project.pack install <zip or folder> [--activate]                         # install it, or upgrade to a newer version
python -m project.pack list                                                          # installed packs (● = active)
python -m project.pack use <id>                                                      # switch to another installed pack
```

`install` puts a pack in `<data>/packs/<id>/`. An existing one is replaced only by a newer version (the previous one is kept in `<data>/packs/.previous/`); a pack being developed (a git working folder) is never overwritten. Restart Inspector after installing or switching the active pack. In the single-folder layout, `export --plugin <name>` makes a release of the project and that plugin.

Every pack has a `pack.json` that says what it is and what it needs (`project/manifest.py`):

```json
{"format": 1, "id": "my_pack", "name": "My pack", "description": "", "version": "1.2.0",
 "plugin": "my_plugin", "requires": {"platform": ">=0.1.0", "spec": 8},
 "requirements": "plugin/requirements.txt", "model": null}
```

| Field | |
|---|---|
| `format` | The version of the pack.json format (1) |
| `id` | Lowercase letters, digits, `_` and `-`; the folder name under `<data>/packs/` |
| `version` | The pack's own version, `MAJOR.MINOR.PATCH` |
| `plugin` | The plugin in `plugin/` (a Python package name), or `null` for a design only |
| `requires.platform` | Which Inspector versions can run it, e.g. `>=0.1.0, <1` |
| `requires.spec` | The script spec the design is written in (`automation/spec.py`) |
| `renamed` | What this version renamed since the last one, e.g. `{"schedules": {"old": "new"}, "rules": {"<script>/old": "new"}}` (kinds: scripts, situations, rules, schedules, settings, lists, vars): installing it over an older version moves the values set for the old names along. Values left with nothing to belong to are listed on the Packs page and in "next steps" |
| `author`, `license`, `homepage` | Optional |

A pack that needs a newer Inspector or a newer script spec is not loaded, and "Home: next steps" says why. Check or upgrade one by hand:

```bash
python -m project.manifest check <pack folder>
python -m project.manifest upgrade <pack folder>
```

---

# ① What to watch

## States (state definitions)

Which states the model recognizes, which area of the screen each one looks at and which answers it has are defined in one versioned file (`meta/states/v<N>.json`).
Auto-labeling, the questions and shortcut keys of "Answer questions", the screen browser and script conditions all follow it.

| Type | Use |
|---|---|
| Class | A fixed set of answers, e.g. on / off / not visible |
| Ratio 0–1 | e.g. a bar that fills up |
| Number | A number read from the screen |
| Name library | A piece of text or an icon on the screen, recognized automatically once a person has named it (`labeler/gallery.py`) |

**A new state needs no code**: choose "screen rule" as its label source, then a kind of rule (`labeler/generic.py`) or one a plugin provides:

| Rule | How it judges | How to set it up |
|---|---|---|
| Reference image match | A few reference images per answer, compared with the screen; the answer that matches best, above the minimum similarity and ahead of the runner-up, wins; otherwise the "when nothing matches" answer | Click a frame and pick its answer |
| Color ratio | The share of pixels in the area within some HSV ranges; above / below the thresholds means one answer each | Click colors on the enlarged image, set thresholds on the distribution |
| Bar ratio | How full a bar is, even when it changes color | Frame the bar, pick its direction |
| Read digits | The number in the area | Click the color of the digits, teach each character a few times |

- A state can have a **prerequisite**: when another state is not visible, this one counts as not visible either.
- Until the model has learned a state, scripts judge it with its rule, so a new state can be used right away; the next training run learns it too.
- **Training progress**: each state shows four steps (defined → can judge → has test questions → model learned) and what to do next.

## Sources and recording

**Sources** (`drivers/`) decide where the picture comes from (the eyes) and where actions go (the hands). Sources come in categories, each with presets for common products (only suggestions, every value can be changed), and each source declares what it can do (get the screen, tap, long press, swipe, back key, launch an app, detect someone operating):

| Category | Notes |
|---|---|
| Android (`android/`) | Any device adb can reach; presets for LDPlayer, MuMu, BlueStacks, NoxPlayer, MEmu and real phones. Can copy an emulator's window (no slowdown), send input through adb, detect a person operating through `getevent` |
| Application window (`window.py`) | Any program's window (an NVR client, a browser, an office program…); mouse / keyboard input goes to the window |
| Screen area (`desktop.py`) | A screen or part of one |
| Stream (`stream.py`) | RTSP / HTTP cameras and network streams; watch only (its actions can be handed to another source or to an output) |
| Recording (`video.py`) | Each video file in a folder is a source, played live and looped; pictures only |
| From plugins | A project's plugins can add more |

A script that uses an action its source cannot do is refused when saved.

The **collector** records each device's screen and touches (plugins can record more). **The collector never taps or sends anything.**

```bash
python -m collector                 # record until Ctrl+C (normally started from the interface)
python -m collector --minutes 60 --interval 5 --only <device name>
```

- **Sampling**: one frame every N seconds per device (`base`); one per second right after touches (`active`); the last frame before a touch (`pre_touch`, from a memory buffer); 0.3 / 0.8 / 1.5 s after events reported by plugins.
- Layout:

```
<work>/<id>/sessions/<YYYYMMDD_HHMMSS>/
  session.json
  devices/<device>/
    samples.jsonl                 each sample: time, trigger, states recorded by plugins
    events.jsonl / touches.jsonl  events, touch gestures (with pre_frame)
    frames/<id>.png               full frames (in the project's coordinate space)
```

Frames saved while scripts run ("judged wrong", uncertain frames) go to the session `shadow_<date>`, in the same format.

---

# ② Teach it to see

## Auto-labeling (labeler)

Labels every frame by the state definitions (weak supervision) for training: screen rules first (plugin and generic ones), then the plugins' label sources fill in or correct, then name libraries.

```bash
python -m labeler [--session <session>]
```

Output: `<work>/<id>/labels/v<version>/labels.jsonl` (one line per frame), `summary.json`, `review_candidates.jsonl` (question candidates), `rule_cache.jsonl` (rule cache; only new frames are computed).
When a rule is unsure, the label stays empty with a flag (e.g. `<state>_uncertain`) and training skips it, or counts it as "not visible" if the rule says so.

## Answer questions (the test set)

Answers given by people are **test questions**: they score the model and are never used to train it.

- Kept in `<work>/<id>/testset/testset.jsonl` (append-only; the last answer for a frame wins). Each entry records the `reviewer`: `human` or `claude` (pre-labels); a pre-label never overwrites a person's answer.
- The question candidates are fixed in `testset/candidates.json`, so changing a rule does not change the questions and scores of different versions stay comparable.
- **Ask one question only**, **add 30 questions**, answer **frames saved while running** (once answered, 3 of every 4 go to training and 1 becomes a test question).
- Each name-library state has its own tab: identical names are grouped automatically and each group is named once.

## Training (trainer)

```bash
python -m trainer --config-json "{\"epochs\": 20, \"pretrained\": true}"
```

- **Model**: a ResNet18 backbone looks at the whole screen, with a small head per state; the heads keep spatial positions, so the model learns where to look by itself.
- **Data split**: test questions are never used for training; a "held-out device" (one the model never sees) can be ticked to pick the best epoch; frames right before and after test frames are excluded; the remaining labeled frames are used for training.
- Outdated labels are regenerated before training (new recordings, changed state definitions, reference images, name libraries or plugins).
- Output `<work>/<id>/models/<run>/`: `config.json`, `metrics.jsonl`, `model_best.pt`, `eval.json` (test report, confusion matrices, wrong answers), plus `model.onnx` + `model.json` for the runtime (exported automatically and checked against PyTorch). Convert older runs with `python -m trainer.onnx_export --all`.

## Scores & mistakes

- One score card per state: accuracy, accuracy on unseen devices, and the screen rule's score on the same questions.
- **Passing the test** (`runtime/judge.py`): at least 20 test questions, at least 3 per answer, not worse than the screen rule, and at least 90% right on unseen devices.
- **Who judges while scripts run**: the model for states it passed; the screen rule for states the model has not learned or not passed, when there is one. While the model is unsure, the screen rule helps confirm (configurable per state: auto / model only / rule only).

---

# ③ Automate

## What scripts are made of

| Part | Notes |
|---|---|
| **🛡 Global guard rules** | Checked **first**, before every main script on every device. "Stop this device" stops all of that device's scripts; "Pause other scripts" keeps every other script still while the condition holds |
| **Main scripts** | Always running, with a **priority order**, made of one or more **situations** |
| **Situations** | Each device is in one situation of a main script at a time and only that situation's rules are checked; a situation can do something on entry and have a maximum stay |
| **Rules** | "If… then… / else if / else", checked from the top; the first that matches runs; cooldown, hourly / daily limits and **urgent** can be set |
| **Sub-scripts** | Multi-step actions called like functions: parameters, success / failure, cleanup steps, an overall time limit |
| **Variables** | Counters or "last time". Per device or shared; reset daily at 00:00 or never |
| **Button library** | Named tap positions; a button with "image match" finds its picture on the screen before tapping |
| **Lists** | Items to choose from (per device or shared), which can be captured from the screen; script parameters, settings and the panel can pick from them |
| **Templates** | "+ From template": the platform's generic templates plus the project's own (`meta/templates.json`) |
| **Outputs** | HTTP / webhook, MQTT, Home Assistant: a script's "send to output" drives devices outside the screen |
| **User settings** | Values the users choose on the operation panel and scripts read at run time |
| **Schedules** | Run a sub-script on chosen devices at a time of day, once per device per day, with catch-up and time limits |

### Kinds of conditions (`automation/conds.py`)

State, just became, times within a period, change, time of day, always (with a cooldown), variable, time since, another device's state, a button visible on the screen, comparing two numbers.
When the model is not sure about a state a condition needs, the script waits at that rule instead of jumping to the rules below it.

### Actions and sub-script steps

Tap, long press, swipe, back key, type text, launch an app, find in a list and tap, capture a list, wait seconds, wait until a condition holds, if… else, retry on failure, repeat until, for each item of a list, call a sub-script, set a variable, notify, ask the user (with buttons, also in chat), send to an output, end (success / failure), stop this device, stay put, pause other scripts (global guard rules only), switch situation (main scripts only).

## Run and monitor (runtime)

```bash
python -m runtime [--run <training run id>] [--interval 1]     # normally "Start the runner" in the interface
```

- Model: a training run with `model.onnx` runs on ONNX (no PyTorch needed), otherwise `model_best.pt`; the Run page shows which.
- Every round: get each device's screen → the model judges everything at once → smoothing → screen rules fill in the states the model does not handle → every script decides for each device by its current situation → the same decision twice in a row counts (except urgent rules). Saving a design reloads it automatically.
- **Each device is independent**: its own situations, sub-script progress, timers, cooldowns, variables and command channel.
- **Modes**: off / dry run (watch only) / live, per script and per device ("Run › Deploy").
- **Safety**: stop / pause / resume per device or for all (from the Run page, the operation panel or chat); a device pauses while someone operates it; start-up checks; tap limits, cooldowns, rules with no effect are paused and reported; every real input is logged with its frame.
- **Keeps improving**: frames where the model is unsure, or disagrees with the screen rule, are saved to "Answer questions › Saved while running".

## Notifications and chat commands (`notify/`)

Notification channels include Discord webhooks, a Telegram bot and a Discord bot. Bots can also take commands in chat; Inspector connects out, so no ports or servers are needed.

- Setup: get a token from @BotFather (Telegram), or create a bot on the Discord developer site, turn on Message Content Intent and invite it with the link on the page.
- Pairing: "Pair" shows a 6-digit code (valid for 10 minutes); send it to the bot in the chat that should get notifications. Only paired people's commands are obeyed.
- Commands: `menu` · `status` · `screen <device>` · `stop` / `pause` / `resume [device|#tag|all]` (device names may be shortened), plus whatever the operation panel offers. Changing settings and pressing buttons ask to confirm first.
- Every command is logged in `<data>/runtime/<id>/commands.jsonl`.

## Replay (runtime/replay.py)

Pick a stretch of a recording and let a script (even an unsaved version) run over it: see what it would judge at each moment, which situation it would switch to and where it would tap. No device is touched.

## Script spec (automation/spec.py)

The file formats of scripts, sub-scripts, variables, outputs, the operation panel and script tests are versioned (currently version 9).
JSON Schemas are in `docs/spec/v<N>/` (written by `python -m automation.spec_schema --write docs/spec/v<N>`) and served at `/api/spec/schema/<script|sub|variables|outputs|panel|tests>`.

- Every file records its `"format"`; older files are upgraded when read, files newer than this Inspector are refused.
- Number and text fields take a value, or `{"param": …}` / `{"setting": …}` / `{"var": …}` (taken at run time); text can insert current values with `{id}`.
- Fields of a released version are never renamed, removed or given another meaning; new kinds or fields come with a new version and an upgrade.
- The editors of main scripts and sub-scripts have a "JSON" tab: view, edit or paste, checked against the schema before "Apply".

## Sharing sub-scripts (automation/share.py)

"Library › Share sub-scripts": tick sub-scripts (optionally with the sub-scripts they call) to make a share file to download or copy as text. It contains the sub-scripts, the buttons they use (with image-match pictures) and the names of the states, variables, user settings, lists and outputs they refer to; output URLs are left out.

Importing first "reads" the file and shows what each reference maps to here (by ID, then by name): buttons can map to your own or be created from theirs; states, lists and outputs must map to existing ones; missing variables and user settings are added. A sub-script whose ID exists here can overwrite it (as a new version), be saved under a new ID, or be skipped. Everything is checked against the script spec first; if anything fails, nothing is saved.

## Script tests (runtime/replaytest.py)

A stretch of recording plus "expected results" saved as a test (like a unit test): after changing scripts, state definitions or the model, "Run all" shows whether anything broke.

- Expected results: in a situation at the end / will (not) enter a situation, will (not) call a sub-script, will (not) tap (optionally by rule), will (not) stop, will (not) warn; with counts and "only look at seconds N–M".
- No need to write them: replay, and if the behavior looks right, "Save as test" turns it into the expected result, editable on the "Script tests" page.
- Replays use the saved scripts and the latest model; sub-scripts are not really run and their results are assumed (per sub-script).
- Tests live in `meta/tests.json` (they travel with packs); results in `<data>/runtime/<id>/tests/results.json`; failures show up in "Home: next steps".

```bash
python -m runtime.replaytest [--id <test id>]     # exit code 0 when all pass
```

---

## Code layout

| Where | What |
|---|---|
| `project/` | Where things are (`__init__.py`, `python -m project where`), plugin registry (`plugins.py`), packs: releases, install, upgrade (`pack.py`), pack.json (`manifest.py`), moving an older project folder (`layout.py`), settings kept beside versioned files and a runtime's own layer (`overlay.py`), the runtime folder's format (`runtime_data.py`), renamed ids (`renames.py`) |
| `drivers/` | Sources: interface and categories (`__init__.py`), sources in use (`sources.py`), Android (`android/`), windows (`window.py`), screens (`desktop.py`), streams (`stream.py`), recordings (`video.py`), picture fitting (`fit.py`) |
| `collector/` | The collector |
| `labeler/` | Auto-labeling: rule dispatch (`rules.py`), generic rules (`generic.py`), name libraries (`gallery.py`), assembly (`build.py`) |
| `schema/` | Reading, writing and checking state definitions |
| `trainer/` | Data split (`data.py`), model (`model.py`), training and testing (`train.py`) |
| `automation/` | Script format and checks, conditions, decisions, sub-scripts and running them, buttons, lists, templates, schedules, user settings, outputs, sending actions (`executor.py`) |
| `runtime/` | The script runner (`shadow.py`), who judges (`judge.py`), replay, quality monitoring |
| `notify/` | Notification channels, chat bots and commands |
| `server/` | API (`app.py`), long-running jobs, data access, test set, progress, operation panel |
| `i18n/`, `web/src/i18n/` | Interface languages (`docs/i18n.md`) |
| `web/src/` | The interface (React + Vite) |
| `packs/` | Where the active pack's plugin is mounted (`packs.<name>`); in the single-folder layout, plugins themselves (one folder each, not part of this repository) |

## Development

```bash
python -m server --no-browser     # backend on :8765
cd web && npm run dev             # frontend on :5173 (proxies /api)
cd web && npm run build           # builds web/dist, served by the backend
```


## Known limits

- Sub-scripts only really run in live mode; replays and dry runs never run them.
- Window capture cannot get a minimized window; judging gets worse when a window is very small.
- One pack runs per computer at a time (switch on the Packs page).

## Troubleshooting

| What you see | What to do |
|---|---|
| "Inspector is already running (port … is in use)" | Another Inspector (or another program) uses the port: use the one running, `restart_inspector.bat`, or `--port` |
| A page stays on "Loading…" right after a start | The first "next steps" after a start reads everything once and can take up to a minute; it is quick afterwards |
| A window source shows no picture | The window is minimized or closed; restore it. If its title changed, reconnect it on the "Sources" page |
| An Android device is not found | Check `adb devices` in a terminal; install Android platform-tools or point the source's advanced settings to the emulator's adb |
| Taps land in the wrong place | The screen's aspect ratio differs from the project's coordinate space; the "Sources" page says what to change |
| A state is often unsure while running | Answer the frames saved under "Answer questions › Saved while running", then train again ("Training" tells you when it is worth it) |

## Security and responsible use

- By default only this computer can open the interface. `--lan` opens it to your local network: set the user and consultant PINs first. Never expose the port to the internet.
- Recordings, models and settings stay on this computer; nothing is sent anywhere except the notifications and outputs you set up yourself.
- Secrets you enter (PINs, bot tokens, output passwords, tokens and headers) are stored in the runtime folder (`<data>/runtime/<id>/`), never in the design, and a pack export leaves them out. Output URLs and hosts are part of the design; keep the runtime folder out of anything you share.
- Inspector operates other software only through its screen and normal input. Automating an app or service may still be against its terms of use; you are responsible for how and where you use it.

## License

[Apache License 2.0](LICENSE).
