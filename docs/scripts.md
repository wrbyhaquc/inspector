# Designing scripts

English · [繁體中文](scripts.zh-TW.md)

Inspector automates in one way only: **"if … then do … in order" cards**, plus one shared set of **steps**.
Main scripts, global guard rules and sub-scripts all use the same cards and the same steps; they differ only in **when the "if" is checked**.

## Three kinds of scripts

| | What it is | When the "if" is checked |
|---|---|---|
| **Global guard rules** | One list of rules looked at before every main script on every device | Every second, from the top; the first that holds runs |
| **Main script** | The everyday main flow, split into "situations" (e.g. working, back to start) | Every second, the rules of the **current situation**, from the top; the first that holds runs |
| **Sub-script** | A flow done from start to end (back to start, switch account, recover from an error…) | In order; **checked once when that step is reached**, then it moves on |

### Checked every second (main scripts, guard rules)

- Every second the rules are read from the top; the first rule that holds does its steps in order, and the rules below it are not looked at this time.
- So **order is priority**: higher up wins. Guard rules always come before every main script.
- No "repeat" is needed: as soon as a condition holds, it is caught the next second (e.g. a water level dropping below 30% halfway through).
- Each rule can have:
  - **Cooldown**: how long after running it does not run again.
  - **At most N times per hour / per day**.
  - **Urgent**: acts the first time it is seen (no second confirmation) and can interrupt the sub-script this device is running.
- When a rule's condition cannot be told (the model is not sure), it does not fall through to the next rule; it does nothing this time.

### Checked when reached (sub-scripts)

- Steps run one by one from the top. "If / else if / else" is looked at once when that step is reached; one branch runs, then it moves on and never looks back.
- To wait for a screen, use "wait until a condition holds", or set "after it: wait until …" on a tap.
- To do something over and over until something happens, use "repeat until"; to start over on failure, "retry on failure".

## Shared steps

A rule's "then do in order", a situation's "on entry" and a sub-script's steps all use the same steps:

- **Operate the screen**: tap, long press, swipe, back key, type text, find in a list and tap, walk to a place on the map, launch an app, capture a list.
  Tap-like steps can set "after it": wait some seconds, or until the screen / a number meets a condition.
- **Wait**: wait seconds, wait until a condition holds.
- **Decide and repeat**: if… else, repeat until, for each…, retry on failure.
- **Call and end**: call a sub-script (when it fails: fail entirely / go on / stop this device), do an item of a catalog, end (success), end (failure), stop this device, switch situation.
- **Communicate**: notify, ask the user, send to an output.
- **Record**: set a variable.
- **Rules only**: stay put (do nothing, and keep the rules below from acting), pause other scripts (guard rules only).

Some steps only make sense in certain places:

- **Switch situation**: only in main-script rules and situation entries (sub-scripts and guard rules have no situations).
- **Stay put / pause other scripts**: only as the single step of a rule.

## Catalogs: choosing one of many, each done its own way

A **catalog** (Library › Catalogs) is a list of named items to choose from, filed in folders. Each item says what doing
it means: which sub-scripts to call, in order, and with what (go in, choose the area, walk on). Items of one catalog may use different sub-scripts - e.g. the places
to go, some reached through the map and some only after entering somewhere and walking on; or the rooms to clean, each
with its own route.

- Let the people running it choose: add a user setting of the kind "an item of a catalog". It shows on the operation
  panel and in the chat bot like any other choice, with the catalog's folders.
- In a script, the step **do an item of a catalog** runs the chosen item (the setting's value, a text parameter, or a
  fixed item): it calls that item's sub-scripts in order, each with its arguments.
- An item may also say **how to tell it is already there** (conditions, like an "if"). Then it is checked first:
  already there means nothing to do (no second trip, no second fee); after the steps it waits until it holds, and not
  seeing it means the item failed - so the caller can try another one.
- Adding a new item is only filling in the catalog; no script changes.

## Walking to a place on a map

**Walk to a place on the map** is for screens that show "me" on a map and move "me" with a joystick (a game, a robot's
floor plan). It goes in stretches: open the map, see where the "me" mark is, close the map, push the joystick towards the
next point for a moment, again.

- **The anchor sign**: a fixed sign on the map (a find button). The points count from it, so a map that opens centred on
  "me" still works.
- **"Me"**: the colour of the mark, and the area of the screen where the map is (the biggest patch of that colour).
- **The points**, in order: e.g. the start of a bridge, its end, the field behind it. Each may say how close counts.
- **The joystick**: its centre and how far to push; "hold it at the edge" is faster where the game allows it.
- Optional **done when**: a condition, e.g. "the place name says I am out of the safe area".

Which way a push really goes on the map, and how far, is learnt while walking: nothing to calibrate. When pushes hardly
move "me" (something in the way), it tries to the sides with short pushes; still stuck = the step fails.

## Conditions

- A card's conditions form one or more groups: **everything in a group** must hold (and), **any group** holding is enough (or).
- Kinds: state (the value the model or a rule judged), just became, times within a period, change, time of day, always, variable, time since, another device, button visible, **compare two numbers**.
- Both sides of "compare two numbers" can be a number, a number read from the screen, a user setting, a variable, or several of them added together, e.g.
  `stock ≥ today's orders + setting "safety stock"`.
- Texts such as notifications and failure messages can contain `{id}`, filled in at run time with the value of a parameter, variable, number read from the screen or user setting.

## Stop and pause

- **Stop (this device)**: all of the device's scripts and situations stop; "Resume" starts from the beginning (situations back to the start, conditions counted again).
- **Pause**: holds where it is; "Resume" carries on from the same situation and the same step.
- One device, a tag (#tag), all devices, or a rule: all use the same mechanism.
- **Someone operating**: when someone touches the device's screen it **pauses** automatically, and **resumes** by itself after the set number of seconds without touches (same situation; the paused time does not count toward the situation's stay).
  A running schedule waits and carries on from the same step; a sub-script started by a rule is cancelled (the person has changed the screen), and the rules decide again and call it again if needed.

The spec (JSON format) is in [spec/](spec/); the current version is 9.
