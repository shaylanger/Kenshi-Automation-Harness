# Driving Kenshi with the harness: notes for AI agents

Read this before using the Kenshi Automation Harness from an agent (Claude
Code, Codex, or any LLM with a shell). It explains how to run a test, how to
verify results, and the mistakes that cost the most time.

## What you control

- A running Kenshi game. You send one command at a time with
  `python client/kah.py <command> [args]`; it prints the reply (exit code 0 =
  ok, 1 = error). Commands act on the **real loaded game** at once.
- `tools/kenshi-ctl.ps1` (PowerShell) starts, stops and checks the game:
  `launch -Save <name>`, `stop`, `restart`, `status`, `health`, `screenshot`.
- `kah help` lists every command the running game knows, including commands
  other mods registered (often prefixed with the mod's name). Full reference:
  [docs/COMMANDS.md](docs/COMMANDS.md).

Paths: set `KAH_DIR` to `<Kenshi>\mods\AutomationHarness` (or pass
`--dir <path>` first), and pass `-Kenshi <game folder>` to `kenshi-ctl.ps1`
(or set `KENSHI_DIR`). From WSL, `kah.py` accepts Windows paths.

## What you can set up without a human

- Situations: `spawn`, `teleport`, `fight <a> <b>` (NPC vs NPC), `faction`, `relation`,
  `damage` + `order <medic> FIRST_AID_ORDER target <npc>`, `ko`, `blood`, `cage`, `shackle`,
  `sleep`, `order <npc> LIFT_PERSON_PLAYER_ORDER target <ko'd npc>` (carry), `eat`.
- Economy: `give`, `money`, `trade` (real purchase; `shopstock` shows a trader's goods), `stash`.
- Work: `job <npc> <building>`, `fill <building> <item> n`, `power`, `building` (production
  state), `time` + `kah wait-game <minutes>` for rates per game hour.
- Crafting: `research <name>` (test cheat), `craft <npc> <item> at <bench>`, `benches crafts`.
- UI: `ui <filter>` (widget text/position), `click <widget>`, `messages`, `screenshot`
  (the game's own frame with HUD; open it as an image to look).
- Mod commands: `help` lists commands other mods registered (e.g. first-person input,
  item affixes); see docs/EXTENDING.md.
- Whole tests: write a scenario file and `kah run <file> --csv out.csv` (format:
  `kah run --help`, example: scenarios/example.txt).

## Before you start (pre-flight)

1. `kenshi-ctl.ps1 status`: is the game already running, and is it yours?
   **Only one agent may drive the game at a time.** If someone else's session
   or the user is playing, stop and ask.
2. The harness must be on **before launch** (`kah on`): it also turns
   autosave off and keeps the game running unfocused.
3. Use a **test save**: copy a save (a "fixture") and keep the master copy
   elsewhere; restore it by copying it back over the save folder. Never test
   on the user's own saves; commands kill, teleport and change relations
   permanently once the game saves.
4. Replace mod DLLs only while the game is closed.

## The test loop

```
kenshi-ctl.ps1 launch -Save <fixture>   # archives logs, starts, presses launcher OK, autoloads
kah wait-world                          # until phase=world
(wait ~5-10 s: the world is still settling)
kah status                              # player, squad size, speed
build the situation                     # spawn, teleport, give, relation, hunger...
act                                     # the thing under test (often a mod command)
verify                                  # read state back (see below)
log the result                          # what you sent, what changed, pass/fail
kah load <fixture>                      # reset between tests, then wait-world again
kenshi-ctl.ps1 stop                     # when done (never saves)
```

Plan the whole run first, then run exactly that plan; don't add steps halfway
through.

## Verifying: replies are not results

An `ok` reply means the command was accepted, not that the game did what you
wanted. A test **passes only when real game state changed**:
- `where <npc>`: position, faction, `KO` / `DEAD`
- `hp <npc>`: per body part, worst %, blood
- `inv <npc>`: inventory JSON (worn items too, works on bodies)
- `chars [radius]`: who is around
- `status`: phase, speed, paused
- the mod's own logs or status files, if you're testing a mod

Check the state before and after, and compare. If a mod's NPC says something
happened, check it against the state: wrong claims are bugs.

## Time and speed

- `speed 0` pauses; `speed 1..50` runs. **Nothing advances while paused**,
  including timers in mods that run on game time.
- At high speed everything is faster: hunger, fights, wandering. Characters
  starve during long fast runs: set `hunger <npc> 250` first (300 = full; they
  pass out below ~80).
- Commands are picked up every 250 ms; a load takes 10-60 s (`wait-world`).

## Names and characters

- `<npc>`: an exact (case-insensitive) name nearest the player wins, else the
  nearest substring. Many NPCs share a name: read the `#serial/index` from
  `chars` or `spawn` and use it as printed (`#12345/678`). A bare `#serial` is
  refused when several characters share it (serials are not unique).
- `@player` is the **first squad member**, not necessarily the one you think;
  name characters explicitly. `@selected` is the selected one.
- `recruit` changes the selection: `select <your character>` again after it.
- After `load`, spawned characters may get the same serials as before; look
  them up again.

## Fights and spawns (common traps)

- Hostile or neutral NPCs teleported close (~7 m) to the squad may get
  attacked. Spawn or teleport at a distance (`dist 30`).
- Same-faction NPCs ignore `attack` orders against each other. `attack` is a
  real order, as a player click: it breaks truces.
- Killing one member of a spawned neutral squad near your characters can turn
  the rest hostile.
- Between tests, check `where <your character>` for `KO`.

## When things go wrong

- No reply: `kenshi-ctl.ps1 health` (`ok`, `hung`, `crashed`, `not-running`).
  On a crash, look for the newest `crashDump*.zip` in the Kenshi folder.
- `ERROR: harness is off`: run `kah on`; if the game is already running,
  relaunch.
- `harness.log` (in the mod folder) and other mods' logs are **recreated on
  every launch**: copy what you need before relaunching (`kenshi-ctl.ps1`
  archives `harness.log`, `outbox.txt`, RE_Kenshi's log and any `-ExtraLogs`).
- Something unexpected (a fight you didn't start, a knockout): pause
  (`speed 0`), save the logs, write down what happened, reload the fixture.

## Reporting

For each test: the commands sent, the state before and after, pass/fail, and
for failures the log lines that show why. Keep "the game did X" separate from
"the mod said X".
