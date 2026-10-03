# Kenshi Automation Harness

- Driving the game with the harness: read [AGENTS.md](AGENTS.md) first.
- Commands and files: [docs/COMMANDS.md](docs/COMMANDS.md). Extension API for other mods:
  [docs/EXTENDING.md](docs/EXTENDING.md).
- Code: `src/Plugin.cpp` (entry, inbox loop, autosave + player-message hooks, screenshot),
  `src/Commands.cpp` (built-ins), `src/WorldCommands.inc` (orders, fights, jobs, buildings, time,
  characters, trade, UI), `src/TaskNames.inc` (generated from the SDK's TaskType enum),
  `src/Extensions.cpp` (registry + exported C API), `src/Inventory.cpp` (`inv` JSON),
  `include/KenshiAutomationHarness.h` (public header).
- Build `build.bat` (VS2010 x64 + KenshiLib SDK, see its header); offline tests
  `tests\run_tests.bat` (no game needed). Batch files must stay CRLF.
- Scenario runner: `client/kah.py run <file>` (format: `kah run --help`, example `scenarios/example.txt`).
