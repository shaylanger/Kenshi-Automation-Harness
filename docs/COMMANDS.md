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
| `status` | `phase=menu|loading|world save=... paused=... speed=... squad=N player=...` |
| `load <save>` | load a save (phase stays `loading` until the new squad is in) |
| `save <name>` | save the game |
| `speed <0\|0.5..50>` | game speed; 0 pauses |
| `chars [radius]` | characters within radius (default 100) of the player |
| `traders [radius]` | characters the game itself treats as traders (`isATrader`), default radius 300 |
| `find <character\|squad\|item\|weapon\|armour\|container> <text>` | look up game data by name |
| `spawn <template> <faction> [near <npc> \| at x y z] [count n] [dist m] [target <npc>] [size <mult>]` | spawn characters, or a squad template (`target`: the squad's AI goes for that character; `size`: scale the squad) |
| `stash <item> <n> [near <npc>]` | put items into the nearest storage chest |
| `where <npc>` | name, serial, faction, position, distance, KO/DEAD |
| `hp <npc>` | flesh/max per body part, worst part %, blood, KO |
| `inv <npc>` | inventory incl. worn items and backpack as JSON (works on bodies) |
| `stat <npc> <stat>` / `setstat <npc> <stat> <value>` | read/set a skill (base and effective) |
| `weight <npc>` | inventory weight |
| `iteminfo\|equip\|unequip <npc> <item>` | an inventory item by name |
| `teleport <npc> <npc2 \| x y z> [dist m]` | move a character |
| `ko <npc> [seconds]` | knock out (default 30 s) |
| `health <npc> <percent>` | set every body part to a percentage of its max (negative values too) |
| `kill <npc>` | every body part to -200% |
| `hunger <npc> <0..300>` | hunger as the game UI shows it (300 = full) |
| `attack <attacker> <target>` | a real attack order, as a player click gives it |
| `money <npc> <delta>` | add (or with a minus, take) cats |
| `buy <buyer> <seller> <item> <price>` | one atomic purchase: item + cats in the same frame |
| `select <npc>` | select the character |
| `recruit <npc>` | recruit into the player's squad (changes the selection) |
| `give <npc> <item> [n]` | create items in the inventory (reports how many really arrived) |
| `relation <npc> <-100..100>` | set the relation between the npc's faction and the player's |
| `transfer <from npc> <to npc> <item>` | move the same (unequipped) item instance between inventories |
| `packput <npc> <pack> <item> [n]` | create items directly inside a backpack the npc owns |
| `packweight <npc> <pack>` | a backpack's equipped state, raw content weight and total weight |
| `craftfinish <npc> <item>` | finish a craft of the item at the nearest real crafting building (within 300), with the npc as crafter |

Stats: labouring, science, engineering, robotics, weapon_smith, armour_smith,
crossbow_smith, medic, turrets, farming, cooking, stealth, athletics,
assassination, swimming, perception, lockpicking, thievery, plus maxcarry,
maxrunspeed, currentrunspeed, encumbrance.

## Notes

- `give` and `stash` can't create weapons; `find` shows exact names. Items can
  be named by game-data string ID too (`find` prints `sid=`).
- `give` of a backpack fails while the character already wears one.
- `unequip` leaves the item in its equipment section, so `equip` of the same item
  then fails.
- Same-faction NPCs ignore `attack` orders against each other.
- Characters teleported next to a hostile squad get attacked.
