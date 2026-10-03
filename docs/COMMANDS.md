# Commands and protocol

## Files

All in the mod folder (`Kenshi\mods\AutomationHarness\`):

| File | Written by | Meaning |
|---|---|---|
| `enabled.flag` | you | harness on (checked every poll; the background-running switch only at game start) |
| `inbox.txt` | tools | commands, one per line: `id<TAB>command<TAB>arg<TAB>arg...` |
| `outbox.txt` | harness | replies, appended: `id<TAB>ok|error<TAB>detail` |
| `autoload.txt` | tools | one save name, loaded once the main menu is up (deleted after use; reply id `autoload`) |
| `harness.log` | harness | log, recreated each game start |

Several clients may run at once (e.g. a background loop plus a scenario), so
writers follow this protocol (`client/kah.py` `write_command` does it):
create `inbox.txt.lock` exclusively (`O_CREAT|O_EXCL`; a lock older than
30 s is stale and may be removed), wait until `inbox.txt` is gone, write a
temp file unique to the call (`inbox.txt.<pid>.<n>.tmp`), rename it to
`inbox.txt`, delete the lock. Use ids unique across clients (kah.py:
`k<ms>_<pid>_<n>`). The harness polls every 250 ms, renames `inbox.txt` to
`inbox.txt.reading` before reading it, then deletes that copy, so a new
inbox written meanwhile is never lost. Arguments can't contain tabs or
newlines.

## Characters

`<npc>` is one of:
- a name: an exact (case-insensitive) match nearest the player wins, else the
  nearest substring match; bodies near the player are found too
- `#serial/index`: the character's full handle as printed by `spawn`, `chars`, `where` (`#374267584/1234`); resolves exactly. `#serial` alone still works but serials are not unique (a spawned bandit once shared one with an NPC 4.5 km away): if several characters have it, the command is refused with a candidate list. The serial comes first, so a `#(\d+)` capture still gets the serial; capture `#(\d+/\d+)` for the exact form
- `@player`: the first squad member
- `@selected`: the selected character

## Built-in commands

Work at the main menu too: `help`, `status`, `load`, `save` (save needs a game).
Everything else needs a loaded game.

| Command | Does |
|---|---|
| `help` | list all commands, including ones registered by other mods |
| `status` | `phase=menu|loading|world save=<loaded save> last_saved=<last name saved> paused=... speed=... squad=N player=...` (`save` = the save loaded this session, by `load` or the game's load menu; `?` until one is seen) |
| `load <save>` | load a save (phase stays `loading` until the new squad is in) |
| `save <name>` | save the game |
| `speed <0\|0.5..50>` | game speed; 0 pauses |
| `chars [radius]` | characters within radius (default 100) of the player |
| `traders [radius]` | characters the game itself treats as traders (`isATrader`), default radius 300; shop keepers in towns, or spawn a trader squad such as `"Skeleton Traders Animals" "Traders Guild"` (a lone "Trader" character doesn't count) |
| `find <character\|squad\|item\|weapon\|armour\|container\|research> <text>` | look up game data by name |
| `spawn <template> <faction> [near <npc> \| at x y z] [count n] [dist m] [target <npc>] [size <mult>]` | spawn characters, or a squad template (`target`: the squad's AI goes for that character; `size`: scale the squad) |
| `stash <item> <n> [near <npc>]` | put items into the nearest storage chest |
| `where <npc>` | name, serial, faction, position, distance, KO/DEAD, ` unique=1` for unique (named, non-template) NPCs (the game's `Character::isUnique`; KAH 13; also in `chars` and every character line) |
| `sections <npc>` | inventory sections (size, equip/container slot) with their items, and the worn backpack |
| `hp <npc>` | flesh/max per body part, worst part %, blood, KO |
| `inv <npc>` | inventory incl. worn items and backpack as JSON (works on bodies) |
| `stat <npc> <stat>` / `setstat <npc> <stat> <value>` / `stat <npc> all` | read/set a skill (base and effective); `all` lists every skill as `name=base(effective)`. Names (KAH 16): strength, toughness, dexterity, athletics, perception, attack (melee_attack), defence (defense, melee_defence), dodge, martial_arts, katanas, sabres, hackers, heavy_weapons, blunt, polearms, crossbows, turrets, weapons, mass_combat, friendly_fire (precision_shooting), stealth, assassination, lockpicking, thievery, swimming, survival, labouring (mining), science (research), engineering, robotics, weapon_smith, armour_smith, crossbow_smith, medic, hive_medic, vet, farming, cooking; derived values: maxcarry, maxrunspeed, currentrunspeed, encumbrance, combatspeed, damageresistance, knockouttime, primaryweapondamage, primaryweaponspeed |
| `weight <npc>` | inventory weight |
| `iteminfo\|equip\|unequip <npc> <item>` | an inventory item by name; `unequip` moves it to the main inventory (dropped next to the character if there's no room) |
| `teleport <npc> <npc2 \| x y z> [dist m]` | move a character |
| `teleport <npc> building <name> [dist m] [radius <m>]` | move a character next to the nearest matching building within 5000 of the player (`radius` changes that), `dist` (default 15) along x from its centre |
| `ko <npc> [seconds]` | knock out (default 30 s) |
| `health <npc> <percent>` | set every body part to a percentage of its max (negative values too) |
| `kill <npc>` | every body part to -200% |
| `hunger <npc> [0..300]` | set hunger as the game UI shows it (300 = full), reply `before -> after`; without a value only reads it (`Shay hunger 216.0`) |
| `attack <attacker> <target>` | a real attack order, as a player click gives it |
| `money <npc> <delta>` | add (or with a minus, take) cats |
| `buy <buyer> <seller> <item> <price>` | one atomic purchase: item + cats in the same frame |
| `select <npc>` | select the character |
| `recruit <npc>` | recruit into the player's squad (changes the selection) |
| `give <npc> <item> [n]` | create items in the inventory (reports how many really arrived, counting every section; a backpack goes on the back if that slot is free, else into the main inventory) |
| `relation <npc> <-100..100>` | set the relation between the npc's faction and the player's |
| `transfer <from npc> <to npc> <item>` | move the same (unequipped) item instance between inventories |
| `packput <npc> <pack> <item> [n]` | create items directly inside a backpack the npc owns |
| `packweight <npc> <pack>` | a backpack's equipped state, raw content weight and total weight |
| `craftfinish <npc> <item> [at <bench>]` | queue a craft of the item at the nearest crafting bench (within 300; `at` = part of the bench name) and run the bench's real finish step with the npc as crafter (mods hooking it see a real craft); reports what reached the bench output. A repeat needs room in the output |
| `benches [radius] [crafts]` | crafting benches within `radius` (default 300, max 5000; also `radius <m>`): queue (first craft and its progress), missing materials (`needs:`), number of available crafts (`crafts` lists them), inventory sections (sizes, limits, items with grid position) |
| `craft <npc> <item> [at <bench>] [count n]` | a **real** craft: queues the item from the bench's own craft menu (the game picks the material/grade) and gives the npc the bench as a job. Then supply materials (give them to the npc: workers carry them in; generic storage chests weren't used) and run the game (`speed`); `benches` shows progress. Works for weapons too |
| `research <name>` | complete a research entry (TEST ONLY cheat; `find research <text>` lists names). Weapon crafting needs e.g. `Basic Weapon Smithing`, `Basic Weapon Grades` and the weapon type (`Katanas`). `research start <name>` (KAH 14) queues it the game's way (`Research::startResearch`), so it shows in progress and advances only while researchers work at a research bench; if it doesn't start, the reply says why (`requirements`, `can_pay`, `paid`, `needs_bench_level`, `desk_level`). `research stop <name>` takes it off the queue. `research status`: `queue=<n> [<name> progress=<0..1> raw=<n> eta=<text>] rate=<research rate> researchers=<n> desk_level=<n> benches=<n> {<bench> dist=<m>}`; start and stop end with the same status |
| `blueprint <item>` | complete the research the game links to crafting that item (`getBlueprintsFor`); for weapons it finds nothing, use `research` |

### Orders, fights and jobs

| Command | Does |
|---|---|
| `order <npc> <task> [target <npc>] [building <name>] [keep]` | give a real AI order, any of the game's 291 tasks by name or number (`FIRST_AID_ORDER`, `LIFT_PERSON_PLAYER_ORDER`, `PUT_IN_CAGE`, `LOOT_TARGET`, `USE_BED_ORDER`, `CHAIN_TARGET`…); `keep` adds instead of replacing orders |
| `tasks [filter]` | list task names with their numbers |
| `fight <a> <b>` | make two characters of different factions fight (their factions go to -100, both get an attack order) |
| `job <npc> <building> [task <name>] [radius <m>]` | add a permanent job at the nearest matching building within `radius` of the npc (default 300, max 5000) (default task: the building's own job, e.g. OPERATE_MACHINERY) |
| `jobs <npc>` / `clearjobs <npc>` | list / remove permanent jobs |

### Buildings and time

| Command | Does |
|---|---|
| `buildings [radius] [filter] [near <npc>]` | buildings within `radius` (default 100, max 5000; at most 60 listed, use a filter for big radii) with distance, position (`pos=x,y,z`, for `teleport <npc> x y z`), owner faction and whether they have an inventory |
| `building <name> [radius]` (alias `production`) | the nearest matching building within `radius` of the player (default 300, max 5000; also `radius <m>`): power (on, has power, battery, output; `current_power`, `wants` = the most it draws, `battery_fed`; the town power grid it is in: `grid="<town>"`, `grid_role=consumer|generator|battery|none`, `grid_power=<now>/<max>`, `grid_needed`, `grid_battery=<charge>/<max>`, `grid_members=<n>in/<n>out/<n>bat`, `player_town`; `grid=none` = in no town, so nothing powers it; `supplied=1` after `power … supply`), production (product, quantity, state, inputs), farm state, inventory sections |
| `produced <building> [reset] [radius <m>]` | units a production building (mine, stone processor, refinery: anything with a production output) made, whether or not workers already hauled them away. The first call starts tracking (reply `tracking …`); later calls report `produced=<n> removed=<n> output_now=<n> game_hours=<h> per_game_hour=<rate> samples=<frames sampled>` (buildings are keyed by handle index/serial; harness.log `KAH: produced track key=…` when tracking starts); `reset` reports and restarts the window. How: the output quantity (`getCurrentProductionQuantity`) is sampled every frame, rises count as produced, drops as removed; only a haul and a production step in the very same frame net out (undercount). Up to 32 buildings; a load clears tracking. Farms may not report through this output |
| `power <building> on\|off\|charge\|supply\|unsupply [radius <m>]` | switch power; `charge` fills a battery (that only helps if the battery is in the same town grid as the consumers: check `grid_role`); `supply` (test cheat, KAH 10) keeps the building at full power whatever its grid has: its `current_power` is set to what it wants right after every town power-grid update (hook on `Town::updatePowerGrid`) and every frame, until `unsupply` or the game restarts (not saved; refused for buildings that use no power) |
| `fill <building> <item> [n] [section <name>] [radius <m>]` | put items into a building's inventory (inputs, storage); reports how many fitted |
| `build <building name\|sid> [near <npc> [dist m] \| at x y z] [faction <f>]` | create a **finished** building or furniture (`Bed`, `Prisoner Cage`, ...) through the game's factory (`RootObjectFactory::createBuilding`, completed). Data is looked up like `find` (exact name or string ID, else a unique partial name). Default place: `dist` 10 (max 200) along x from the npc (default the player's first squad member); height: the npc's (or the given) y, or the terrain height at x,z when that is within 20 of it; the factory adds the terrain height to the y it gets, so the harness compensates and checks the result (one rebuild if it is off by more than 5; the reply warns if it still is). Identity rotation, no town. Owner: the player's faction unless `faction`. Reply: name, serial, `pos=x,y,z`, faction. Refused with `refused: <name> (<sid>) …` (KAH 12), because the game crashes on them: a storage building (functionality `function` 2, Resource storage) whose template has `has inventory` false (it gets no inventory and the game reads it: Biofuel Distillery `43875-Newwworld.mod` crashed at `kenshi_x64.exe+0x2988b5` about 10 s after the next load), and sids on a deny list (`BuildDeniedSid` in `src/BuildArgs.h`, now just that one). In this install's load order the Distillery is the only building the template rule matches |
| `unbuild <name> [radius]` | destroy the nearest building that `build` made this session (name contains the text, within `radius` of the player measured on x,z, default 300, max 5000) via `GameWorld::destroy`; other buildings are never touched |
| `time` | game hours, day, time of day, speed |

Building names match the nearest exact name, else the nearest name containing the text. `radius` is above 0 and at most 5000; anything else is refused.

Client side: `kah wait-game <minutes> [timeout_s]` waits for game time to pass.

### Characters

| Command | Does |
|---|---|
| `setname <npc> <name>` | rename |
| `faction <npc> <faction>` | move into an own squad of that faction (prints the new `#serial/index`: the character gets a new handle) |
| `sleep <npc> [bed <name>]` / `wake <npc>` | sleep on the floor or in a bed (USE_BED_ORDER); `wake` gets up |
| `damage <npc> <part> <cut> [blunt] [pierce] [bleed <x>]` | a real wound on a body part (0-6 or head, chest, stomach, left_arm, right_arm, left_leg, right_leg); can be bandaged with first aid. Wounds made this way don't bleed: use `blood` |
| `blood <npc> <value\|pct%>` | set blood |
| `protect [<npc> on\|off]` | test cheat (KAH 11): every frame a protected character gets every body part (flesh and stun) and blood back to max, and a knockout is cleared at once (KO timer 0, "get up" flag, the game re-checks collapse), so she stands up again; harness.log gets `KAH: protect revived <name> (revive n)` per KO; factions, relations and aggro are untouched, so a fight still counts as a fight; the dead are not revived; not saved, the list is cleared when a save loads; `protect` alone lists who is protected (revives, KO/DEAD) |
| `shackle <npc> [owner <npc>]` / `unshackle <npc>` | chain mode on/off |
| `cage <npc> [cage name]` / `uncage <npc> [cage name]` | put into / release from the nearest matching cage (within 300) |
| `eat <npc> <food>` | eat a food item from the inventory (hunger rises over time, as in the game) |
| `drop <npc> <item> [count]` | puts an inventory item on the ground next to him the game's way (`Inventory::dropItem`, KAH 15); the whole stack (a `count` other than the stack size is refused), not worn items (unequip first). Reply: `dropped <item> x<n> #serial/index pos=x,y,z dist=<m> in_inventory=0 physical=0|1` (`(ground object still being built)` until the physics object exists). The harness remembers the items it dropped for `pickup` |
| `pickup <npc> <item\|#serial/index\|nearest> [radius <m>]` | takes a ground item within `radius` (default 20, max 300) of him into his inventory with `Character::giveItem`; `#serial/index` is the handle `drop` printed (exact, any distance among items seen), else the nearest item matching name or sid, or the nearest at all. The reply compares the handle before and after (`(same instance)`), unless a stackable item merged into a stack he had (then it says so). If he can't take it at once (no room), he is ordered to `PICKUP` it the game's way (`not picked up yet: … ordered PICKUP`): check `inv` after the walk |
| `unload <npc>` / `reload <name>` | stream a character out and back in the game's way (KAH 17): `unload` deactivates his whole squad (`Platoon::deactivate`, what the game does far from the player; the character objects are destroyed and later rebuilt from the squad's saved state), refused for the player's squad. `reload <name>` (the name `unload` printed; `reload` alone lists them) activates it again (`Platoon::activate`) and describes him; the game itself reloads a squad near the player on its own, then `reload` says `(the game had already reloaded him)`. Not saved; the list is per session |
| `shopstock <trader> [radius <m>]` | a trader's goods: carried plus storage of her faction within `radius` of her (default 60, max 300; traders walk around their shops) (where Kenshi keeps shop stock) |
| `trade <buyer> <trader> <item> [radius <m>]` | buy (from the same goods `shopstock` lists, same `radius`) through the game's own purchase path (`Inventory::buyItem`): first, if the buyer's inventory has no room for the item (`Inventory::hasRoomForItem`), it fails at once with `<buyer> has no room for <item>` and nothing moves (run m16: the Trader fixture's Shay is full); otherwise cats move, the game's trade event fires; an item in shop storage (counter, barrel) first moves into the trader's inventory, because the game prices and sells only from there (from storage it read value 0 and paid nobody), and goes back to the shelf if the purchase fails; when the game still prices it at 0 (run m10: armour made by `fill`/`give`), the move equipped it, or `buyItem` refuses, the harness sells it by hand: takes it out, the buyer pays the fallback price (average price, else the game data `value`) and the trader gets the cats (`steps:` says `sold by hand for <n>`; `problems:` shows level, quality, material, maker, stolen, avg_price, data_value of a 0-priced item); `buyItem` hands the item back detached, so it is placed the way `give` does (`Inventory::addItem`), else with `Character::giveItem` dropping it at her feet (its return value is false even when it drops, so the item's own state decides: in an inventory, on the ground, or its ground object still being built (`creatingPhysical`/`physicalShouldExist` newly set); last resort `dropItem`); if neither works the buyer is refunded and the item goes back where it came from (`steps:` shows room, addItem/giveItem results and the refund); anything that went wrong (price 0, payment short, nothing arrived) is listed after `problems:`; the reply shows `arrived=<n>` and `placed=inventory|ground|already|failed` |

### UI

| Command | Does |
|---|---|
| `ui [filter] [all]` | visible widgets (name, caption, position, size); `all` includes hidden ones |
| `click <widget name or caption>` | fire a widget's click (e.g. `click INV` opens the inventory) |
| `messages [n]` | the last on-screen player messages since launch |
| `screenshot [name]` | the game's own frame, HUD and windows included, to `shots/<name>.png` in the mod folder |
| `fps [reset]` | frame rate measured by the harness's own frame callback (QueryPerformanceCounter, every frame; in Kenshi that is MyGUI's frame event, Ogre's frameStarted does not fire; harness.log gets `KAH: fps frames=<n> source=… window: …` every 600 frames) since launch or the last reset: `avg=<fps> min=<fps> worst_ms=<longest frame> frames=<n> seconds=<s>`; `reset` returns the numbers and starts a new window. Works in every phase (loading screens and pauses count too, so reset after `wait-world`) |

### Scenario runner (client side)

`kah run <file> [--csv out.csv] [--stop]` runs a test file, one step per line (`kah run --help`):
a command must answer ok, `! command` must answer error, `command ~ regex` must match;
`@sleep`, `@wait-world`, `@wait-game <min>`, `@until <s> command ~ regex`,
`@set NAME command ~ (group)` (use `${NAME}` later), `@log <file> ~ regex` (new lines since the
run started), `@echo`. See `scenarios/example.txt`.

Stats: labouring, science, engineering, robotics, weapon_smith, armour_smith,
crossbow_smith, medic, turrets, farming, cooking, stealth, athletics,
assassination, swimming, perception, lockpicking, thievery, plus maxcarry,
maxrunspeed, currentrunspeed, encumbrance.

## Notes

- Weapons can't be created directly (`give`, `stash`, `buy`, `packput`, `craftfinish`): the game's
  item factory refuses them. Make them the real way: `research` + `craft` (see above). `find` shows exact names;
  items can be named by game-data string ID too (`find` prints `sid=`).
- Same-faction NPCs ignore `attack` orders against each other.
- Characters teleported next to a hostile squad get attacked.
