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

Write `inbox.txt` atomically (write `inbox.txt.tmp`, then rename) and wait
until the harness has deleted it before writing the next one. The inbox is
polled every 250 ms. Arguments can't contain tabs or newlines.

## Characters

`<npc>` is one of:
- a name: an exact (case-insensitive) match nearest the player wins, else the
  nearest substring match; bodies near the player are found too
- `#serial`: the character's handle serial (shown by `chars`, `where`)
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
| `where <npc>` | name, serial, faction, position, distance, KO/DEAD |
| `sections <npc>` | inventory sections (size, equip/container slot) with their items, and the worn backpack |
| `hp <npc>` | flesh/max per body part, worst part %, blood, KO |
| `inv <npc>` | inventory incl. worn items and backpack as JSON (works on bodies) |
| `stat <npc> <stat>` / `setstat <npc> <stat> <value>` | read/set a skill (base and effective) |
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
| `research <name>` | complete a research entry (TEST ONLY cheat; `find research <text>` lists names). Weapon crafting needs e.g. `Basic Weapon Smithing`, `Basic Weapon Grades` and the weapon type (`Katanas`) |
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
| `building <name> [radius]` (alias `production`) | the nearest matching building within `radius` of the player (default 300, max 5000; also `radius <m>`): power (on, has power, battery, output), production (product, quantity, state, inputs), farm state, inventory sections |
| `power <building> on\|off\|charge [radius <m>]` | switch power; `charge` fills a battery |
| `fill <building> <item> [n] [section <name>] [radius <m>]` | put items into a building's inventory (inputs, storage); reports how many fitted |
| `build <building name\|sid> [near <npc> [dist m] \| at x y z] [faction <f>]` | create a **finished** building or furniture (`Bed`, `Prisoner Cage`, ...) through the game's factory (`RootObjectFactory::createBuilding`, completed). Data is looked up like `find` (exact name or string ID, else a unique partial name). Default place: `dist` 10 (max 200) along x from the npc (default the player's first squad member); height: the npc's (or the given) y, or the terrain height at x,z when that is within 20 of it; the factory adds the terrain height to the y it gets, so the harness compensates and checks the result (one rebuild if it is off by more than 5; the reply warns if it still is). Identity rotation, no town. Owner: the player's faction unless `faction`. Reply: name, serial, `pos=x,y,z`, faction |
| `unbuild <name> [radius]` | destroy the nearest building that `build` made this session (name contains the text, within `radius` of the player measured on x,z, default 300, max 5000) via `GameWorld::destroy`; other buildings are never touched |
| `time` | game hours, day, time of day, speed |

Building names match the nearest exact name, else the nearest name containing the text. `radius` is above 0 and at most 5000; anything else is refused.

Client side: `kah wait-game <minutes> [timeout_s]` waits for game time to pass.

### Characters

| Command | Does |
|---|---|
| `setname <npc> <name>` | rename |
| `faction <npc> <faction>` | move into an own squad of that faction (prints the new `#serial`: the character gets a new handle) |
| `sleep <npc> [bed <name>]` / `wake <npc>` | sleep on the floor or in a bed (USE_BED_ORDER); `wake` gets up |
| `damage <npc> <part> <cut> [blunt] [pierce] [bleed <x>]` | a real wound on a body part (0-6 or head, chest, stomach, left_arm, right_arm, left_leg, right_leg); can be bandaged with first aid. Wounds made this way don't bleed: use `blood` |
| `blood <npc> <value\|pct%>` | set blood |
| `shackle <npc> [owner <npc>]` / `unshackle <npc>` | chain mode on/off |
| `cage <npc> [cage name]` / `uncage <npc> [cage name]` | put into / release from the nearest matching cage (within 300) |
| `eat <npc> <food>` | eat a food item from the inventory (hunger rises over time, as in the game) |
| `shopstock <trader> [radius <m>]` | a trader's goods: carried plus storage of her faction within `radius` of her (default 60, max 300; traders walk around their shops) (where Kenshi keeps shop stock) |
| `trade <buyer> <trader> <item> [radius <m>]` | buy (from the same goods `shopstock` lists, same `radius`) through the game's own purchase path (`Inventory::buyItem`): cats move, the game's trade event fires; an item in shop storage (counter, barrel) first moves into the trader's inventory, because the game prices and sells only from there (from storage it read value 0 and paid nobody), and goes back to the shelf if the purchase fails; when the game still prices it at 0 (run m10: armour made by `fill`/`give`), the move equipped it, or `buyItem` refuses, the harness sells it by hand: takes it out, the buyer pays the fallback price (average price, else the game data `value`) and the trader gets the cats (`steps:` says `sold by hand for <n>`; `problems:` shows level, quality, material, maker, stolen, avg_price, data_value of a 0-priced item); `buyItem` hands the item back detached, so it is placed the way `give` does (`Inventory::addItem`), else with `Character::giveItem` dropping it at her feet (its return value is false even when it drops, so the item's own state decides; last resort `dropItem`); if neither works the buyer is refunded and the item goes back where it came from (`steps:` shows room, addItem/giveItem results and the refund); anything that went wrong (price 0, payment short, nothing arrived) is listed after `problems:`; the reply shows `arrived=<n>` and `placed=inventory|ground|already|failed` |

### UI

| Command | Does |
|---|---|
| `ui [filter] [all]` | visible widgets (name, caption, position, size); `all` includes hidden ones |
| `click <widget name or caption>` | fire a widget's click (e.g. `click INV` opens the inventory) |
| `messages [n]` | the last on-screen player messages since launch |
| `screenshot [name]` | the game's own frame, HUD and windows included, to `shots/<name>.png` in the mod folder |

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
