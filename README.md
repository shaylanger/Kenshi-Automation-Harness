# Kenshi Automation Harness

In-game test automation for Kenshi mods: drive a running game from scripts.
Load saves, spawn characters and squads, teleport, set health, hunger, stats
and money, give items, give any AI order (first aid, carry, cage, sleep...),
start NPC-vs-NPC fights, assign jobs, fill and power buildings, measure
production against game time, craft for real (research + bench + worker),
trade through the game's purchase path, inspect and click the UI, take
screenshots with the HUD, and run whole test scenarios with checks, all from
a command line or a test script. It's an RE_Kenshi plugin built on KenshiLib.

Made for mod development and automated testing. It does nothing unless you
switch it on, and it's not meant for normal play.

## Requirements

- Kenshi x64 in a version KenshiLib supports (tested on 1.0.65)
- RE_Kenshi, which brings KenshiLib
- Python 3 for the `kah` client (Windows or WSL); PowerShell for `kenshi-ctl.ps1`

## Install

1. Copy `mod/AutomationHarness/` into `Kenshi\mods\` and put
   `AutomationHarness.dll` (from a release, or built from source, see below)
   in it.
2. Enable "AutomationHarness" in the Kenshi launcher's mod list.
3. Switch it on before launching the game: `python client/kah.py on`
   (creates `Kenshi\mods\AutomationHarness\enabled.flag`; `kah off` removes it).

Point the client at the mod folder with `KAH_DIR` (or `--dir`) if Kenshi isn't
in a default Steam folder.

## Use

```bash
python client/kah.py on
powershell -File tools/kenshi-ctl.ps1 launch -Save my-test-save -Kenshi "D:\Steam\steamapps\common\Kenshi"
python client/kah.py wait-world
python client/kah.py spawn "Hungry Bandit" Drifters near @player
python client/kah.py chars 50
python client/kah.py give @player "Dried Meat" 5
python client/kah.py speed 10
```

`kah help` lists every command the running game knows, including commands
added by other mods. See [docs/COMMANDS.md](docs/COMMANDS.md).

While the harness is on:
- autosave is off, so test runs never overwrite your autosave slots;
- the game keeps running when its window is in the background;
- `autoload.txt` (written by `kah autoload <save>` or `kenshi-ctl.ps1 launch -Save`)
  loads a save as soon as the main menu is up.

**Use test saves.** Commands change the loaded game (kill, teleport, give,
relations...); copy a save and test on the copy.

## Using it with an AI agent

The harness was built to let a coding agent (Claude Code, Codex, etc.) run a
full test loop alone: launch the game, load a test save, set up a situation,
exercise a mod, read the game state back, log bugs, close the game, fix,
rebuild, relaunch. Point the agent at [AGENTS.md](AGENTS.md) (Claude Code
picks it up through `CLAUDE.md`): it covers pre-flight checks, the loop,
how to verify results against game state instead of replies, and the traps
that waste the most time.

Give the agent the paths (`KAH_DIR`, `-Kenshi`), the name of a test save it
may load, and the rule that only one session drives the game at a time.

## How it works

The DLL adds an Ogre frame listener, so commands run on the game thread and
also work at the main menu. Tools write `inbox.txt` (one command per line,
`id<TAB>command<TAB>args...`); the harness consumes it and appends
`id<TAB>ok|error<TAB>detail` to `outbox.txt`. Anything that can write a file
can drive it; `client/kah.py` is a small reference client.

`tools/kenshi-ctl.ps1` starts Kenshi unattended (presses the launcher's OK,
follows RE_Kenshi's restart, waits for the harness), stops it, checks health
(ok / hung / crashed) and takes window screenshots.

## Adding your own commands

Other RE_Kenshi plugins can register commands and hooks at run time, with no
link-time dependency: include `include/KenshiAutomationHarness.h` and call
`KAH_Connect()`. See [docs/EXTENDING.md](docs/EXTENDING.md).

## Build

Needs the VS2010 x64 compiler (KenshiLib plugins use the VS2010 runtime),
Windows SDK 7.1, the KenshiLib SDK (headers + `KenshiLib.lib`, Ogre and
MyGUI libs) and Boost headers. Set `KAH_TOOLS`, `KAH_SDK` and `KAH_BOOST`
(see the top of `build.bat`), or run it from a VS2010 x64 prompt, then:

```bat
build.bat
```

Output: `out\AutomationHarness.dll`. `tests\run_tests.bat` runs the offline
tests (extension registry and replies; no game needed).

## Licence

MIT, see [LICENSE](LICENSE).
