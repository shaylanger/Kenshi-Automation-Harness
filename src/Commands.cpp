// Built-in harness commands (TEST ONLY): load/save games, spawn characters,
// move, hurt or knock out anyone, set hunger, stats, money, items, game
// speed and faction relations. See docs/COMMANDS.md.
#ifndef NOMINMAX
#define NOMINMAX // OgreRoot.h uses std::min/max
#endif
#include "Harness.h"
#include "SearchRadius.h"
#include "BuildArgs.h"

#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/Character.h>
#include <kenshi/CharStats.h>
#include <kenshi/Building/CraftingBuilding.h>
#include <kenshi/Research.h>
#include <kenshi/Building/Building.h>
#include <kenshi/Building/FarmBuilding.h>
#include <kenshi/Building/ProductionBuilding.h>
#include <kenshi/Building/StorageBuilding.h>
#include <kenshi/Building/UseableStuff.h>
#include <kenshi/util/TimeOfDay.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Widget.h>
#include <kenshi/Damages.h>
#include <kenshi/Faction.h>
#include <kenshi/FactionRelations.h>
#include <kenshi/GameData.h>
#include <kenshi/GameWorld.h>
#include <kenshi/Globals.h> // ou
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>
#include <kenshi/Kenshi.h>
#include <kenshi/MedicalSystem.h>
#include <kenshi/Platoon.h>
#include <kenshi/PlayerInterface.h>
#include <kenshi/RootObjectFactory.h>
#include <kenshi/SaveManager.h>
#include <kenshi/util/hand.h>
#include <kenshi/util/UtilityT.h>

#include <windows.h>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

bool Valid(const void *p) { return p && (uintptr_t)p > 0x10000; }

PlayerInterface *Player(GameWorld *world) {
  return (Valid(world) && Valid(world->player)) ? world->player : nullptr;
}

bool InWorld(GameWorld *world) {
  PlayerInterface *player = Player(world);
  return player && player->playerCharacters.size() > 0;
}

Character *FirstPlayerCharacter(GameWorld *world) {
  PlayerInterface *player = Player(world);
  if (!player || player->playerCharacters.size() == 0)
    return nullptr;
  return player->playerCharacters[0];
}

// Every live character, plus characters (incl. dead bodies, which drop out of
// the update list) within `radius` of `origin`.
void CollectCharacters(GameWorld *world, const Ogre::Vector3 &origin, float radius,
                       std::vector<Character *> &out) {
  const ogre_unordered_set<Character *>::type &chars = world->getCharacterUpdateList();
  for (ogre_unordered_set<Character *>::type::const_iterator it = chars.begin();
       it != chars.end(); ++it)
    if (Valid(*it))
      out.push_back(*it);
  lektor<RootObject *> nearby;
  try {
    world->getObjectsWithinSphere(nearby, origin, radius, CHARACTER, 256, nullptr);
  } catch (...) {
    return;
  }
  for (uint32_t i = 0; i < nearby.size(); ++i) {
    Character *c = dynamic_cast<Character *>(nearby.stuff[i]);
    if (Valid(c) && std::find(out.begin(), out.end(), c) == out.end())
      out.push_back(c);
  }
}

// "@player" (first squad member), "@selected", or a name: exact
// (case-insensitive) match nearest the player wins, else nearest substring.
Character *FindCharacter(GameWorld *world, const std::string &name) {
  if (!InWorld(world))
    return nullptr;
  Character *player = FirstPlayerCharacter(world);
  if (name == "@player")
    return player;
  if (name == "@selected") {
    Character *sel = nullptr;
    try {
      sel = dynamic_cast<Character *>(world->player->selectedCharacter.getRootObject());
    } catch (...) {
      sel = nullptr;
    }
    return sel;
  }
  Ogre::Vector3 origin(0, 0, 0);
  if (Valid(player)) {
    try {
      origin = player->getPosition();
    } catch (...) {
    }
  }
  const std::string wanted = Lower(name);
  const bool bySerial = !name.empty() && name[0] == '#';
  const unsigned long serial = bySerial ? strtoul(name.c_str() + 1, nullptr, 10) : 0;
  Character *exact = nullptr, *partial = nullptr;
  float exactDist = 0, partialDist = 0;
  std::vector<Character *> chars;
  CollectCharacters(world, origin, 500.0f, chars);
  for (size_t i = 0; i < chars.size(); ++i) {
    Character *c = chars[i];
    if (bySerial) {
      try {
        if ((unsigned long)c->getHandle().serial == serial)
          return c;
      } catch (...) {
      }
      continue;
    }
    std::string cname;
    float dist = 0;
    try {
      cname = Lower(c->getName());
      dist = c->getPosition().distance(origin);
    } catch (...) {
      continue;
    }
    if (cname == wanted) {
      if (!exact || dist < exactDist) {
        exact = c;
        exactDist = dist;
      }
    } else if (cname.find(wanted) != std::string::npos) {
      if (!partial || dist < partialDist) {
        partial = c;
        partialDist = dist;
      }
    }
  }
  return exact ? exact : partial;
}

bool ParseStatName(const std::string &name, StatsEnumerated &out) {
  const std::string n = Lower(name);
  if (n == "labouring" || n == "laboring" || n == "mining") out = STAT_LABOURING;
  else if (n == "science" || n == "research") out = STAT_SCIENCE;
  else if (n == "engineering") out = STAT_ENGINEERING;
  else if (n == "robotics") out = STAT_ROBOTICS;
  else if (n == "weapon_smith" || n == "weaponsmith") out = STAT_SMITHING_WEAPON;
  else if (n == "armour_smith" || n == "armor_smith" || n == "armoursmith") out = STAT_SMITHING_ARMOUR;
  else if (n == "crossbow_smith" || n == "crossbowsmith") out = STAT_SMITHING_BOW;
  else if (n == "medic" || n == "medicine") out = STAT_MEDIC;
  else if (n == "turrets" || n == "turret") out = STAT_TURRETS;
  else if (n == "farming") out = STAT_FARMING;
  else if (n == "cooking") out = STAT_COOKING;
  else if (n == "stealth") out = STAT_STEALTH;
  else if (n == "athletics") out = STAT_ATHLETICS;
  else if (n == "assassination") out = STAT_ASSASSINATION;
  else if (n == "swimming") out = STAT_SWIMMING;
  else if (n == "perception") out = STAT_PERCEPTION;
  else if (n == "lockpicking") out = STAT_LOCKPICKING;
  else if (n == "thievery" || n == "thieving") out = STAT_THIEVING;
  else if (n == "maxcarry" || n == "maxcarryweight") out = _MaxCarryWeight;
  else if (n == "maxrunspeed") out = _MaxRunSpeed;
  else if (n == "currentrunspeed") out = _CurrentRunSpeed;
  else if (n == "encumbrance") out = _encumbrance;
  else return false;
  return true;
}

Item *FindInventoryItem(Character *c, const std::string &wanted, bool &ambiguous) {
  ambiguous = false;
  if (!Valid(c))
    return nullptr;
  Inventory *inv = c->getInventory();
  if (!Valid(inv))
    return nullptr;
  const std::string needle = Lower(wanted);
  Item *partial = nullptr;
  lektor<InventorySection *> &sections = inv->getAllSections();
  for (uint32_t si = 0; si < sections.size(); ++si) {
    InventorySection *section = sections.stuff[si];
    if (!Valid(section))
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
    for (size_t i = 0; i < items.size(); ++i) {
      Item *item = items[i].item;
      if (!Valid(item))
        continue;
      std::string name, dataId;
      try {
        name = Lower(item->getName());
        if (item->data) dataId = Lower(item->data->stringID);
      } catch (...) { continue; }
      if (!dataId.empty() && dataId == needle)
        return item;
      if (name == needle)
        return item;
      if (name.find(needle) != std::string::npos) {
        if (partial && partial != item) ambiguous = true;
        else partial = item;
      }
    }
  }
  return ambiguous ? nullptr : partial;
}

std::string DescribeItem(Item *item) {
  if (!Valid(item))
    return "invalid item";
  std::ostringstream s;
  try {
    const hand h = item->getHandle();
    s << item->getName()
      << " handle=" << h.toString()
      << " h.index=" << h.index
      << " h.serial=" << h.serial
      << " h.type=" << (int)h.type
      << " h.container=" << h.container
      << " h.containerSerial=" << h.containerSerial
      << " persistent=" << item->persistant.toString()
      << " properOwner=" << item->properOwner.toString()
      << " inventoryOwner=" << item->getInventoryWeAreIn().toString()
      << " invPos=" << item->inventoryPos.x << "," << item->inventoryPos.y
      << " slotType=" << (int)item->slotType
      << " objectType=" << (int)item->objectType
      << " base=" << (item->data ? item->data->stringID : "")
      << " section=" << item->inventorySection
      << " equipped=" << (item->isEquipped ? 1 : 0)
      << " qty=" << item->quantity
      << " quality=" << item->quality;
  } catch (...) {
    s << "unreadable item";
  }
  return s.str();
}

std::string Describe(Character *c, const Ogre::Vector3 *origin) {
  std::string out;
  try {
    out = c->getName();
    out += " #" + Int(c->getHandle().serial);
    Faction *f = c->getFaction();
    out += " [" + std::string(Valid(f) ? f->getName() : "?") + "]";
    Ogre::Vector3 p = c->getPosition();
    out += " pos=" + Num(p.x) + "," + Num(p.y) + "," + Num(p.z);
    if (origin)
      out += " dist=" + Num(p.distance(*origin));
    if (c->isDead())
      out += " DEAD";
    else if (c->isUnconcious())
      out += " KO";
  } catch (...) {
    out += " (unreadable)";
  }
  return out;
}

GameData *FindData(GameWorld *world, itemType type, const std::string &name,
                   std::string &error) {
  const std::string wanted = Lower(name);
  std::vector<GameData *> partial;
  const auto categoryIt = world->gamedata.gamedataCatSID.find((int)type);
  if (categoryIt != world->gamedata.gamedataCatSID.end()) {
    const auto &entries = categoryIt->second;
    for (auto it = entries.begin(); it != entries.end(); ++it) {
      GameData *data = it->second;
      if (!Valid(data))
        continue;
      const std::string dataId = Lower(data->stringID);
      if (!dataId.empty() && dataId == wanted)
        return data;
      std::string dataName = Lower(data->name);
      if (dataName == wanted)
        return data;
      if (dataName.find(wanted) != std::string::npos)
        partial.push_back(data);
    }
  }
  if (partial.size() == 1)
    return partial[0];
  if (partial.empty()) {
    error = "no data named: " + name;
  } else {
    error = "ambiguous name, candidates:";
    for (size_t i = 0; i < partial.size() && i < 15; ++i)
      error += " [" + partial[i]->name + "]";
  }
  return nullptr;
}

Faction *FindFaction(GameWorld *world, const std::string &name) {
  if (!Valid(world->factionMgr))
    return nullptr;
  Faction *f = nullptr;
  try {
    f = world->factionMgr->getFactionByName(name);
  } catch (...) {
    f = nullptr;
  }
  return Valid(f) ? f : nullptr;
}

// Parses "x y z" or a character name into a position.
bool ResolvePosition(GameWorld *world, const std::vector<std::string> &f, size_t at,
                     Ogre::Vector3 &pos, std::string &error) {
  if (f.size() >= at + 3) {
    char *e1, *e2, *e3;
    double x = strtod(f[at].c_str(), &e1), y = strtod(f[at + 1].c_str(), &e2),
           z = strtod(f[at + 2].c_str(), &e3);
    if (!*e1 && !*e2 && !*e3) {
      pos = Ogre::Vector3((float)x, (float)y, (float)z);
      return true;
    }
  }
  if (f.size() <= at) {
    error = "missing position (<npc> or x y z)";
    return false;
  }
  Character *c = FindCharacter(world, f[at]);
  if (!c) {
    error = "no character named: " + f[at];
    return false;
  }
  pos = c->getPosition();
  return true;
}

// Reads "key value" options after the positional arguments.
std::string Option(const std::vector<std::string> &f, size_t from, const std::string &key,
                   const std::string &fallback) {
  for (size_t i = from; i + 1 < f.size(); ++i)
    if (Lower(f[i]) == key)
      return f[i + 1];
  return fallback;
}

// Items of one kind in every section, the worn backpack slot included
// (Inventory::countItems skips that slot, so a given backpack that was put
// on straight away looked like it never arrived).
int CountAllSections(Inventory *inv, GameData *data) {
  int total = 0;
  if (!Valid(inv))
    return 0;
  lektor<InventorySection *> &sections = inv->getAllSections();
  for (uint32_t si = 0; si < sections.size(); ++si) {
    InventorySection *section = sections.stuff[si];
    if (!Valid(section))
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
    for (size_t i = 0; i < items.size(); ++i) {
      Item *item = items[i].item;
      if (Valid(item) && item->data == data)
        total += item->quantity > 0 ? item->quantity : 1;
    }
  }
  return total;
}

// Creates one item. The game's factory returns nothing for weapons (with or
// without a maker and quality grade, tried 2026-10-02), so they are refused
// with a clear message instead of a silent "0/1".
Item *MakeItem(GameWorld *world, GameData *data, const std::vector<std::string> &, size_t,
               GameData *defaultMaker, std::string &error) {
  if (data->type == WEAPON) {
    error = "weapons can't be created by the harness (the game's item factory refuses them): " +
            data->name;
    return nullptr;
  }
  Item *item = world->theFactory->createItem(data, hand(), defaultMaker, nullptr, -1, nullptr);
  if (!Valid(item))
    error = "the game could not create " + data->name;
  return Valid(item) ? item : nullptr;
}

// Nearest crafting bench to c within 300 whose name contains `wanted` (any if empty).
CraftingBuilding *FindBench(GameWorld *world, Character *c, const std::string &wanted, float &dist) {
  lektor<RootObject *> nearby;
  world->getObjectsWithinSphere(nearby, c->getPosition(), 300.0f, BUILDING, 512, nullptr);
  CraftingBuilding *best = nullptr;
  for (uint32_t i = 0; i < nearby.size(); ++i) {
    CraftingBuilding *b = dynamic_cast<CraftingBuilding *>(nearby.stuff[i]);
    if (!Valid(b))
      continue;
    if (!wanted.empty() && Lower(b->getName()).find(Lower(wanted)) == std::string::npos)
      continue;
    float d = b->getPosition().distance(c->getPosition());
    if (!best || d < dist) {
      best = b;
      dist = d;
    }
  }
  return best;
}

// "item (material)" for a bench's available craft.
std::string CraftName(const GameDataGroup &g) {
  std::string out = Valid(g.g1) ? g.g1->name : std::string("?");
  if (Valid(g.g2))
    out += " (" + g.g2->name + ")";
  return out;
}

Research *Tech(GameWorld *world) {
  return Valid(world->player) && Valid(world->player->technology) ? world->player->technology
                                                                  : nullptr;
}

// A count argument at f[at], unless that field is already an option name.
int CountArg(const std::vector<std::string> &f, size_t at) {
  if (f.size() <= at)
    return 1;
  const std::string v = Lower(f[at]);
  if (v == "at" || v == "near" || v == "section" || v == "radius")
    return 1;
  return atoi(f[at].c_str());
}

void SetAllParts(Character *c, float fraction) {
  MedicalSystem &med = c->medical;
  int count = med.getPartCount();
  for (int i = 0; i < count; ++i) {
    MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)i);
    if (!Valid(part))
      continue;
    float maxHp = part->maxHealth();
    part->flesh = maxHp * fraction;
    part->fleshStun = maxHp * fraction;
  }
}

// After a load command the old world stays "in world" for a few frames, so a
// pending load only ends once the squad list emptied and filled again (or
// after 120 s).
bool g_loadPending = false;
bool g_loadSawEmpty = false;
DWORD g_loadStarted = 0;
Character *g_loadOldLeader = nullptr; // squad leader object before the load

// getCurrentGame() is the last name *saved* (Kenshi doesn't update it on a
// load), so the harness remembers what was loaded: its own "load", and any
// load the game signals (the load menu too), seen by WatchLoads() each frame.
std::string g_loadedSave;
int g_lastSignal = 0;

std::string CurrentSave() {
  try {
    SaveManager *sm = SaveManager::getSingleton();
    if (Valid(sm))
      return sm->getCurrentGame();
  } catch (...) {
  }
  return "";
}

#include "WorldCommands.inc"

const char *const kBuiltins[] = {
    "help",  "status", "load",     "save",    "speed",  "chars",   "find",  "spawn",
    "stash", "stat",   "setstat",  "weight",  "iteminfo", "equip", "unequip",
    "where", "hp",     "inv",      "teleport", "ko",    "health",  "kill",  "hunger",
    "attack", "money", "buy",      "select",  "recruit", "give",   "relation",
    "traders", "transfer", "packput", "packweight", "craftfinish", "sections",
    "benches", "craft", "research", "blueprint",
    "tasks", "ui", "click", "messages", "screenshot", "time", "building", "production",
    "buildings", "power", "fill", "order", "fight", "job", "jobs", "clearjobs", "setname",
    "faction", "sleep", "wake", "damage", "shackle", "unshackle", "cage", "uncage", "shopstock",
    "trade", "eat", "blood", "build", "unbuild"};

const char *const kHelp =
    "built-in: help | status | load <save> | save <name> | speed <0|0.5..50> | "
    "chars [radius] | traders [radius] | benches [radius] [crafts] | research <name> | "
    "blueprint <item> | craft <npc> <item> [at <bench>] [count n] | find <character|squad|item|weapon|armour|container> <text> | "
    "spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] "
    "[size <mult>] | stash <item> <n> [near <npc>] | stat <npc> <stat> | "
    "setstat <npc> <stat> <value> | weight <npc> | iteminfo|equip|unequip <npc> <item> | "
    "where|hp|inv|sections|select|recruit|kill <npc> | teleport <npc> <npc2 | x y z | building <name>> [dist m] | "
    "ko <npc> [seconds] | health <npc> <percent> | hunger <npc> [0..300] | "
    "attack <attacker> <target> | money <npc> <delta> | buy <buyer> <seller> <item> <price> | "
    "give <npc> <item> [n] | relation <npc> <-100..100> | "
    "order <npc> <task> [target <npc>] [building <name>] [keep] | tasks [filter] | fight <a> <b> | "
    "job <npc> <building> [task <name>] [radius <m>] | jobs|clearjobs <npc> | setname <npc> <name> | "
    "faction <npc> <faction> | sleep <npc> [bed <name>] | wake <npc> | "
    "damage <npc> <part> <cut> [blunt] [pierce] | blood <npc> <value|pct%> | shackle <npc> [owner <npc>] | unshackle <npc> | "
    "cage|uncage <npc> [cage] | shopstock <trader> [radius <m>] | trade <buyer> <trader> <item> [radius <m>] | "
    "eat <npc> <food> | build <building|sid> [near <npc> [dist m] | at x y z] [faction <f>] | "
    "unbuild <name> [radius] | time | buildings [radius] [filter] [near <npc>] | building <name> [radius] | "
    "power <building> on|off|charge [radius <m>] | fill <building> <item> [n] [section <s>] [radius <m>] | "
    "ui [filter] [all] | click <widget> | messages [n] | screenshot [name] | "
    "transfer <from npc> <to npc> <item> | packput <npc> <pack> <item> [n] | "
    "packweight <npc> <pack> | craftfinish <npc> <item> [at <bench>]. "
    "<npc> = name (exact match nearest the player wins, else nearest substring), "
    "#serial, @player or @selected.";

} // namespace

void WatchLoads() {
  try {
    SaveManager *sm = SaveManager::getSingleton();
    if (!Valid(sm))
      return;
    int signal = sm->signal;
    if (signal == SaveManager::LOADGAME && g_lastSignal != SaveManager::LOADGAME &&
        !sm->name.empty()) {
      g_loadedSave = sm->name;
      Log("KAH: game load signalled save=" + g_loadedSave);
    }
    g_lastSignal = signal;
  } catch (...) {
  }
}

bool IsBuiltinCommand(const std::string &name) {
  const std::string n = Lower(name);
  for (size_t i = 0; i < sizeof(kBuiltins) / sizeof(kBuiltins[0]); ++i)
    if (n == kBuiltins[i])
      return true;
  return false;
}

bool LoadPending() {
  if (g_loadPending)
    Phase(ou);
  return g_loadPending;
}


std::string Phase(GameWorld *world) {
  if (!Valid(world))
    return "starting";
  bool loading = false;
  try {
    loading = world->isLoadingFromASaveGame();
  } catch (...) {
  }
  const bool inWorld = InWorld(world);
  if (g_loadPending) {
    if (!inWorld || loading)
      g_loadSawEmpty = true;
    else if (g_loadSawEmpty || FirstPlayerCharacter(world) != g_loadOldLeader ||
             GetTickCount() - g_loadStarted > 120000)
      g_loadPending = false;
    if (g_loadPending)
      return "loading";
  }
  if (loading)
    return "loading";
  return inWorld ? "world" : "menu";
}


std::string RunCommand(GameWorld *world, const std::vector<std::string> &f, bool &ok,
                       bool &pending) {
  ok = false;
  pending = false;
  const std::string cmd = Lower(f[1]);

  if (HasExtensionCommand(cmd))
    return RunExtensionCommand(f, ok, pending);
  if (!IsBuiltinCommand(cmd))
    return "unknown command: " + f[1] + " (help lists them)";

  {
    std::string reply;
    if (RunAnyPhaseCommand(f, ok, reply))
      return reply;
  }

  if (cmd == "help") {
    ok = true;
    return std::string(kHelp) + ExtensionCommandList();
  }

  if (cmd == "status") {
    ok = true;
    // save = the save loaded this session (as far as the harness saw it),
    // last_saved = Kenshi's own "current game" (the last name saved).
    std::string out = "phase=" + Phase(world) + " save=" +
                      (g_loadedSave.empty() ? std::string("?") : g_loadedSave) +
                      " last_saved=" + CurrentSave();
    if (Valid(world)) {
      out += " paused=" + std::string(world->paused ? "1" : "0");
      out += " speed=" + Num(world->frameSpeedMult);
    }
    if (InWorld(world))
      out += " squad=" + Int(world->player->playerCharacters.size()) + " player=" +
             FirstPlayerCharacter(world)->getName();
    return out;
  }

  if (cmd == "load") {
    if (f.size() < 3 || f[2].empty())
      return "usage: load <save name>";
    SaveManager *sm = SaveManager::getSingleton();
    if (!Valid(sm))
      return "no SaveManager";
    if (!sm->saveExists(sm->getSavePath(), f[2]))
      return "no save named: " + f[2] + " (in " + sm->getSavePath() + ")";
    Log("KAH: load save=" + f[2] + " phase=" + Phase(world));
    sm->load(f[2]);
    g_loadedSave = f[2];
    g_loadPending = true;
    g_loadSawEmpty = false;
    g_loadStarted = GetTickCount();
    g_loadOldLeader = FirstPlayerCharacter(world);
    ok = true;
    return "loading " + f[2];
  }

  if (cmd == "save") {
    if (f.size() < 3 || f[2].empty())
      return "usage: save <save name>";
    if (!InWorld(world))
      return "no game loaded";
    SaveManager *sm = SaveManager::getSingleton();
    if (!Valid(sm))
      return "no SaveManager";
    Log("KAH: save save=" + f[2]);
    sm->save(f[2], false);
    ok = true;
    return "saving " + f[2];
  }

  if (!InWorld(world))
    return "no game loaded (phase=" + Phase(world) + ")";
  Character *player = FirstPlayerCharacter(world);
  Ogre::Vector3 origin = player->getPosition();

  if (cmd == "speed") { // speed <0|0.5..50>: 0 pauses
    float v = f.size() >= 3 ? (float)atof(f[2].c_str()) : -1.0f;
    if (!(v == 0.0f || (v >= 0.5f && v <= 50.0f)))
      return "usage: speed <0|0.5..50>";
    float before = world->getFrameSpeedMultiplier();
    if (v == 0.0f) {
      world->userPause(true);
    } else {
      world->userPause(false);
      world->setGameSpeed(v, false);
      if (world->getFrameSpeedMultiplier() < v - 0.01f ||
          world->getFrameSpeedMultiplier() > v + 0.01f)
        world->setFrameSpeedMultiplier(v);
    }
    float after = world->getFrameSpeedMultiplier();
    bool paused = world->isPaused();
    Log("KAH: speed requested=" + f[2] + " before=" + Num(before) + " after=" + Num(after) +
        " paused=" + (paused ? "1" : "0"));
    ok = true;
    return "speed " + Num(before) + " -> " + Num(after) + " paused=" + (paused ? "1" : "0");
  }

  {
    std::string reply;
    if (RunWorldCommand(world, f, origin, ok, reply))
      return reply;
  }

  if (cmd == "chars") {
    float radius = f.size() >= 3 ? (float)atof(f[2].c_str()) : 100.0f;
    std::string out;
    int n = 0;
    std::vector<Character *> chars;
    CollectCharacters(world, origin, radius, chars);
    for (size_t i = 0; i < chars.size() && n < 40; ++i) {
      Character *c = chars[i];
      try {
        if (c->getPosition().distance(origin) > radius)
          continue;
      } catch (...) {
        continue;
      }
      out += (n ? " | " : "") + Describe(c, &origin);
      ++n;
    }
    ok = true;
    return Int(n) + " within " + Num(radius) + ": " + out;
  }

  if (cmd == "traders") {
    float radius = f.size() >= 3 ? (float)atof(f[2].c_str()) : 300.0f;
    std::string out;
    int n = 0;
    std::vector<Character *> chars;
    CollectCharacters(world, origin, radius, chars);
    for (size_t i = 0; i < chars.size() && n < 40; ++i) {
      Character *c = chars[i];
      bool trader = false;
      try {
        if (c->getPosition().distance(origin) > radius)
          continue;
        trader = c->isATrader();
      } catch (...) {
        continue;
      }
      if (!trader)
        continue;
      out += (n ? " | " : "") + Describe(c, &origin);
      ++n;
    }
    ok = true;
    return Int(n) + " traders within " + Num(radius) + ": " + out;
  }

  if (cmd == "find") { // find <character|squad|item|faction> <substring>
    if (f.size() < 4)
      return "usage: find <character|squad|item|weapon|armour|container|research> <text>";
    const std::string kind = Lower(f[2]);
    itemType type = kind == "squad" ? SQUAD_TEMPLATE
                    : kind == "item" ? ITEM
                    : kind == "weapon" ? WEAPON
                    : kind == "armour" ? ARMOUR
                    : kind == "container" ? CONTAINER
                    : kind == "research" ? RESEARCH
                                       : CHARACTER;
    std::string error;
    GameData *data = FindData(world, type, f[3], error);
    ok = data != nullptr;
    return data ? "[" + data->name + "] sid=" + data->stringID : error;
  }

  if (cmd == "spawn") {
    // spawn <character|squad template> <faction> [near <npc>|at x y z] [count n] [dist m] [target <npc>]
    if (f.size() < 4)
      return "usage: spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] "
             "[target <npc>]";
    Faction *faction = FindFaction(world, f[3]);
    if (!faction)
      return "no faction named: " + f[3];
    Ogre::Vector3 pos = origin;
    std::string error;
    for (size_t i = 4; i < f.size(); ++i) {
      if (Lower(f[i]) == "near" && !ResolvePosition(world, f, i + 1, pos, error))
        return error;
      if (Lower(f[i]) == "at" && !ResolvePosition(world, f, i + 1, pos, error))
        return error;
    }
    float dist = (float)atof(Option(f, 4, "dist", "8").c_str());
    int count = atoi(Option(f, 4, "count", "1").c_str());
    if (count < 1 || count > 10)
      return "count must be 1..10";
    pos.x += dist;
    if (!Valid(world->theFactory))
      return "no factory";
    std::string squadError;
    GameData *squad = FindData(world, SQUAD_TEMPLATE, f[2], squadError);
    if (squad && Lower(squad->name) == Lower(f[2])) {
      // "target <npc>": the squad's AI goes for that character (a raid on the
      // player); without it spawned squads walk off to their own goals.
      hand aiTarget;
      const std::string targetName = Option(f, 4, "target", "");
      if (!targetName.empty()) {
        Character *t = FindCharacter(world, targetName);
        if (!t)
          return "no character named: " + targetName;
        aiTarget = t->getHandle();
      }
      // "size <mult>": the template decides the squad size; this scales it.
      float sizeMult = (float)atof(Option(f, 4, "size", "1").c_str());
      if (sizeMult <= 0.0f || sizeMult > 3.0f)
        return "size must be 0..3";
      Platoon *p = world->theFactory->createRandomSquad(
          faction, pos, nullptr, count, nullptr, squad, nullptr, nullptr, nullptr, false,
          aiTarget, nullptr, sizeMult, SQ_ROAMING, false);
      Log("KAH: spawn squad=" + squad->name + " faction=" + faction->getName() +
          " ok=" + (Valid(p) ? "1" : "0"));
      ok = Valid(p);
      return std::string(ok ? "spawned squad " : "squad spawn failed ") + squad->name +
             " at " + Num(pos.x) + "," + Num(pos.y) + "," + Num(pos.z);
    }
    GameData *charData = FindData(world, CHARACTER, f[2], error);
    if (!charData)
      return error + (squad ? " (squad match: [" + squad->name + "])" : "");
    int made = 0;
    std::string names;
    for (int i = 0; i < count; ++i) {
      Ogre::Vector3 at = pos;
      at.z += 2.0f * i;
      RootObject *obj = world->theFactory->createRandomCharacter(faction, at, nullptr,
                                                                 charData, nullptr, -1.0f);
      Character *c = dynamic_cast<Character *>(obj);
      if (!Valid(c))
        break;
      ++made;
      names += (made > 1 ? ", " : "") + c->getName() + " #" + Int(c->getHandle().serial);
    }
    Log("KAH: spawn character=" + charData->name + " faction=" + faction->getName() +
        " made=" + Int(made) + " " + names);
    ok = made > 0;
    return "spawned " + Int(made) + "/" + Int(count) + " " + charData->name + ": " + names;
  }

  if (cmd == "benches") { // benches [radius] [crafts]: crafting benches, their queue and inventory
    float radius = 0;
    std::string radiusError;
    if (!ParseSearchRadius(f, 2, 2, kDefaultSearchRadius, radius, radiusError))
      return radiusError;
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, origin, radius, BUILDING, 512, nullptr);
    std::string out;
    int n = 0;
    for (uint32_t i = 0; i < nearby.size() && n < 30; ++i) {
      CraftingBuilding *b = dynamic_cast<CraftingBuilding *>(nearby.stuff[i]);
      if (!Valid(b))
        continue;
      ++n;
      out += " || " + b->getName() + " dist=" + Num(b->getPosition().distance(origin)) +
             " queue=" + Int((long long)b->crafting.size());
      if (!b->crafting.empty())
        out += " (first: " + b->crafting.front().name + " " +
               Int((long long)(b->crafting.front().progress01 * 100.0f)) + "%)";
      lektor<GameData *> needs;
      b->getResourcesNeededBecauseEmpty(needs);
      if (needs.size() > 0) {
        out += " needs:";
        for (uint32_t k = 0; k < needs.size() && k < 8; ++k)
          if (Valid(needs.stuff[k]))
            out += " [" + needs.stuff[k]->name + "]";
      }
      lektor<GameDataGroup> crafts;
      b->getAvailableCrafts(crafts);
      out += " crafts=" + Int(crafts.size());
      if (Option(f, 2, "crafts", "") != "" || (f.size() >= 3 && Lower(f[f.size() - 1]) == "crafts"))
        for (uint32_t k = 0; k < crafts.size() && k < 40; ++k)
          out += " [" + CraftName(crafts.stuff[k]) + "]";
      Inventory *inv = b->getInventory();
      if (!Valid(inv))
        continue;
      lektor<InventorySection *> &sections = inv->getAllSections();
      for (uint32_t si = 0; si < sections.size(); ++si) {
        InventorySection *section = sections.stuff[si];
        if (!Valid(section))
          continue;
        out += " | " + section->name + " " + Int(section->width) + "x" + Int(section->height) +
               (section->itemsLimit > 0 ? " limit=" + Int(section->itemsLimit) : std::string()) + ":";
        const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
        for (size_t k = 0; k < items.size() && k < 12; ++k)
          if (Valid(items[k].item))
            out += " [" + items[k].item->getName() + " x" + Int(items[k].item->quantity) + " @" +
                   Int(items[k].x) + "," + Int(items[k].y) + " " + Int(items[k].w) + "x" +
                   Int(items[k].h) + "]";
      }
    }
    ok = true;
    return Int(n) + " crafting benches within " + Num(radius) + ":" + out;
  }

  if (cmd == "research") { // research <name>: complete a research entry (TEST ONLY cheat)
    if (f.size() < 3)
      return "usage: research <research name> (find research <text> lists names)";
    Research *tech = Tech(world);
    if (!tech)
      return "no player research";
    std::string error;
    GameData *d = FindData(world, RESEARCH, f[2], error);
    if (!d)
      return error;
    const bool before = tech->isFinished(d);
    tech->completeResearch(d);
    ok = tech->isFinished(d);
    Log("KAH: research " + d->name + " finished " + (before ? "1" : "0") + " -> " + (ok ? "1" : "0"));
    return "research " + d->name + ": " + (before ? "already finished" : ok ? "completed" : "NOT completed");
  }

  if (cmd == "blueprint") { // blueprint <item>: complete the research that unlocks crafting it
    if (f.size() < 3)
      return "usage: blueprint <item name|stringID>";
    Research *tech = Tech(world);
    if (!tech)
      return "no player research";
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {WEAPON, ARMOUR, ITEM, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[2], error);
    if (!data)
      return error;
    GameData *bp = tech->getBlueprintsFor(data);
    if (!Valid(bp))
      return "no blueprint/research unlocks " + data->name;
    const bool before = tech->isFinished(bp);
    tech->completeResearch(bp);
    ok = tech->isFinished(bp);
    Log("KAH: blueprint " + data->name + " via " + bp->name + " finished " + (before ? "1" : "0") +
        " -> " + (ok ? "1" : "0"));
    return data->name + " unlocked by [" + bp->name + "]: " +
           (before ? "already finished" : ok ? "completed" : "NOT completed");
  }

  if (cmd == "stash") { // stash <item> <count> [near <npc>]: fill the nearest storage
    if (f.size() < 4)
      return "usage: stash <item> <count> [near <npc>]";
    int count = atoi(f[3].c_str());
    if (count < 1 || count > 50)
      return "count must be 1..50";
    Ogre::Vector3 at = origin;
    std::string error;
    if (f.size() >= 6 && Lower(f[4]) == "near" && !ResolvePosition(world, f, 5, at, error))
      return error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[2], error);
    if (!data)
      return error;
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, at, 300.0f, BUILDING, 256, nullptr);
    RootObject *best = nullptr;
    float bestDist = 0.0f;
    for (uint32_t i = 0; i < nearby.size(); ++i) {
      RootObject *b = nearby.stuff[i];
      if (!Valid(b))
        continue;
      std::string name;
      try {
        name = Lower(b->getName());
      } catch (...) {
        continue;
      }
      if (name.find("storage") == std::string::npos && name.find("chest") == std::string::npos)
        continue;
      Inventory *inv = nullptr;
      try {
        inv = b->getInventory();
      } catch (...) {
        inv = nullptr;
      }
      if (!Valid(inv))
        continue;
      float d = b->getPosition().distance(at);
      if (!best || d < bestDist) {
        best = b;
        bestDist = d;
      }
    }
    if (!best)
      return "no storage chest within 300";
    Inventory *inv = best->getInventory();
    int added = 0;
    for (int i = 0; i < count; ++i) {
      Item *item = MakeItem(world, data, f, 4, nullptr, error);
      if (!Valid(item) || !inv->addItem(item, 1, false, true))
        break;
      ++added;
    }
    ok = added > 0;
    Log("KAH: stash " + data->name + " x" + Int(added) + " in " + best->getName());
    return "stashed " + Int(added) + "/" + Int(count) + " " + data->name + " in " +
           best->getName() + " (" + Num(bestDist) + " away)";
  }

  // The remaining commands take a character first.
  if (f.size() < 3)
    return "usage: " + cmd + " <npc> ...";
  Character *c = FindCharacter(world, f[2]);
  if (!c)
    return "no character named: " + f[2];
  {
    std::string reply;
    if (RunCharacterCommand(world, f, c, origin, ok, reply))
      return reply;
  }

  if (cmd == "transfer") { // transfer <from npc> <to npc> <item name|stringID>
    if (f.size() < 5)
      return "usage: transfer <from npc> <to npc> <item name|stringID>";
    Character *to = FindCharacter(world, f[3]);
    if (!to)
      return "no target character named: " + f[3];
    bool ambiguous = false;
    Item *item = FindInventoryItem(c, f[4], ambiguous);
    if (ambiguous)
      return "ambiguous source inventory item: " + f[4];
    if (!Valid(item))
      return "no source inventory item matching: " + f[4];
    if (item->isEquipped)
      return "refusing to transfer equipped item: " + DescribeItem(item);
    Inventory *fromInv = c->getInventory();
    Inventory *toInv = to->getInventory();
    if (!Valid(fromInv) || !Valid(toInv))
      return "missing source/target inventory";
    Item *moved = fromInv->removeItemDontDestroy_returnsItem(item, 1, true);
    if (!Valid(moved))
      return "remove-without-destroy failed";
    bool added = toInv->addItem(moved, 1, false, true);
    if (!added) {
      fromInv->addItem(moved, 1, false, true);
      return "target add failed; item returned to source";
    }
    ok = true;
    Log("KAH: transfer " + c->getName() + " -> " + to->getName() + " " + DescribeItem(moved));
    return "transferred " + DescribeItem(moved) + " from " + c->getName() + " to " + to->getName();
  }

  if (cmd == "packput") { // packput <npc> <pack name|stringID> <item name|stringID> [count]
    if (f.size() < 5)
      return "usage: packput <npc> <pack name|stringID> <item name|stringID> [count]";
    bool ambiguous = false;
    Item *packItem = FindInventoryItem(c, f[3], ambiguous);
    if (ambiguous)
      return "ambiguous backpack: " + f[3];
    ContainerItem *pack = dynamic_cast<ContainerItem *>(packItem);
    if (!Valid(pack))
      return "no container item matching: " + f[3];
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[4], error);
    if (!data)
      return error;
    int count = CountArg(f, 5);
    if (count < 1 || count > 50)
      return "count must be 1..50";
    Inventory *pinv = pack->getInventory();
    if (!Valid(pinv))
      return "backpack inventory unavailable";
    int added = 0;
    for (int i = 0; i < count; ++i) {
      Item *item = MakeItem(world, data, f, 5, nullptr, error);
      if (!Valid(item) || !pinv->addItem(item, 1, false, true))
        break;
      ++added;
    }
    ok = added > 0;
    Log("KAH: packput " + c->getName() + " pack=" + pack->getName() +
        " item=" + data->name + " added=" + Int(added));
    return "packput " + Int(added) + "/" + Int(count) + " " + data->name +
           " into " + pack->getName();
  }

  if (cmd == "packweight") { // packweight <npc> <pack name|stringID>
    if (f.size() < 4)
      return "usage: packweight <npc> <pack name|stringID>";
    bool ambiguous = false;
    Item *packItem = FindInventoryItem(c, f[3], ambiguous);
    if (ambiguous)
      return "ambiguous backpack: " + f[3];
    ContainerItem *pack = dynamic_cast<ContainerItem *>(packItem);
    if (!Valid(pack))
      return "no container item matching: " + f[3];
    Inventory *pinv = pack->getInventory();
    if (!Valid(pinv))
      return "backpack inventory unavailable";
    float raw = 0.0f;
    const lektor<Item*>& contents = pinv->getAllItems();
    for (unsigned int i = 0; i < contents.size(); ++i)
      if (Valid(contents[i])) raw += contents[i]->getItemWeight();
    pinv->recalculateTotalWeight();
    float total = pinv->getTotalWeight();
    ok = true;
    return c->getName() + " pack=" + pack->getName() +
           " equipped=" + std::string(pack->isEquipped ? "1" : "0") +
           " items=" + Int(contents.size()) +
           " raw=" + Num(raw) + " total=" + Num(total);
  }

  if (cmd == "craft") { // craft <npc> <item> [at <bench>] [count n]: a real craft, worked by <npc>
    if (f.size() < 4)
      return "usage: craft <npc> <item> [at <bench name>] [count n]";
    float dist = 0.0f;
    CraftingBuilding *bench = FindBench(world, c, Option(f, 4, "at", ""), dist);
    if (!bench)
      return "no crafting bench within 300" + (Option(f, 4, "at", "").empty()
                                                   ? std::string()
                                                   : " matching '" + Option(f, 4, "at", "") + "'");
    int count = atoi(Option(f, 4, "count", "1").c_str());
    if (count < 1 || count > 10)
      return "count must be 1..10";
    // The bench's own craft menu: item + material pairs the player has unlocked.
    lektor<GameDataGroup> crafts;
    bench->getAvailableCrafts(crafts);
    const std::string wanted = Lower(f[3]);
    int exact = -1, partial = -1, partials = 0;
    for (uint32_t i = 0; i < crafts.size(); ++i) {
      if (!Valid(crafts.stuff[i].g1))
        continue;
      const std::string name = Lower(crafts.stuff[i].g1->name);
      if (name == wanted || Lower(crafts.stuff[i].g1->stringID) == wanted) {
        exact = (int)i;
        break;
      }
      if (name.find(wanted) != std::string::npos) {
        if (partial < 0)
          partial = (int)i;
        ++partials;
      }
    }
    const int pick = exact >= 0 ? exact : partials == 1 ? partial : -1;
    if (pick < 0) {
      std::string list;
      for (uint32_t i = 0; i < crafts.size() && i < 25; ++i)
        list += " [" + CraftName(crafts.stuff[i]) + "]";
      return std::string(partials > 1 ? "ambiguous craft name" : "not in the craft list") + " of " +
             bench->getName() + " (" + Int(crafts.size()) + " available, unlock with blueprint/research):" + list;
    }
    const GameDataGroup craft = crafts.stuff[pick];
    for (int i = 0; i < count; ++i)
      bench->_addCraft(craft.g1, craft.g2, 0.0f, YesNoMaybe(YesNoMaybe::MAYBE));
    // Put <npc> on the bench as a job (appended, existing jobs kept).
    const TaskType task = bench->getDefaultTask();
    c->addJob(task, bench, true, true, bench->getPosition());
    ok = !bench->crafting.empty();
    Log("KAH: craft " + CraftName(craft) + " x" + Int(count) + " at " + bench->getName() + " worker=" +
        c->getName() + " task=" + Int((int)task) + " queue=" + Int((long long)bench->crafting.size()));
    return "queued " + Int(count) + "x " + CraftName(craft) + " at " + bench->getName() + " (" +
           Num(dist) + " away, queue=" + Int((long long)bench->crafting.size()) + "), " + c->getName() +
           " has the job (task " + Int((int)task) + "). Materials go in the bench input or a nearby "
           "store; run the game (speed) and watch benches.";
  }

  if (cmd == "craftfinish") { // craftfinish <npc> <item name|stringID> [at <bench name>]
    if (f.size() < 4)
      return "usage: craftfinish <npc> <item name|stringID> [at <bench name>]";
    const std::string benchWanted = Lower(Option(f, 4, "at", ""));
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[3], error);
    if (!data)
      return error;
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, c->getPosition(), 300.0f, BUILDING, 512, nullptr);
    CraftingBuilding *best = nullptr;
    float bestDist = 0.0f;
    for (uint32_t i = 0; i < nearby.size(); ++i) {
      CraftingBuilding *b = dynamic_cast<CraftingBuilding *>(nearby.stuff[i]);
      if (!Valid(b))
        continue;
      if (!benchWanted.empty() && Lower(b->getName()).find(benchWanted) == std::string::npos)
        continue;
      float dist = b->getPosition().distance(c->getPosition());
      if (!best || dist < bestDist) {
        best = b;
        bestDist = dist;
      }
    }
    if (!best)
      return benchWanted.empty() ? "no CraftingBuilding within 300"
                                 : "no CraftingBuilding matching '" + benchWanted + "' within 300";
    error.clear();
    Item *item = MakeItem(world, data, f, 4, CraftingBuilding::playerManufacturerData(), error);
    if (!item)
      return error;
    const std::string itemName = data->name;
    const std::string buildingName = best->getName();
    // Report what really reached the bench's output (like "give").
    Inventory *out = best->getInventory();
    const int before = CountAllSections(out, data);
    // addFinishedCraftItem completes the craft at the head of the bench's
    // queue; with an empty queue the item goes nowhere. Queue this craft
    // first (as the player's "queue" button does), almost finished.
    bool queued = false;
    if (best->crafting.empty()) {
      best->_addCraft(data, nullptr, 0.99f, YesNoMaybe(YesNoMaybe::MAYBE));
      queued = !best->crafting.empty();
    }
    best->whosCrafting = c->getHandle();
    best->addFinishedCraftItem(item);
    // Take our helper craft off the queue again, or the bench would make it twice.
    if (queued && !best->crafting.empty())
      best->_removeCraft(0);
    int after = CountAllSections(out, data);
    // With something already in the output the game's finish step doesn't
    // place the item (it ran, hooks included): put it in the output section.
    std::string placedBy = "game";
    if (after <= before && Valid(out)) {
      InventorySection *outSection = out->getSection("out");
      // (Never place by hand: getValidInventoryPosition answers 0,0 even when
      // that spot is taken, which stacked items on top of each other.)
      if (Valid(outSection) && outSection->addItem(item, item->quantity > 0 ? item->quantity : 1))
        placedBy = "harness";
      else
        placedBy = "nobody: the bench output is full (as in the game, finished items must be "
                   "taken out first; see benches)";
      after = CountAllSections(out, data);
    }
    ok = after > before;
    Log("KAH: craftfinish crafter=" + c->getName() + " building=" + buildingName +
        " item=" + itemName + " output " + Int(before) + " -> " + Int(after) + " placed_by=" +
        placedBy);
    return std::string(ok ? "" : "item not in the bench output: ") + "craftfinish " + itemName +
           " via " + buildingName + " (" + Num(bestDist) + " away) crafter=" + c->getName() +
           " output " + Int(before) + " -> " + Int(after) + " placed_by=" + placedBy +
           " queue_now=" + Int((long long)best->crafting.size());
  }

  if (cmd == "stat") { // stat <npc> <stat>
    if (f.size() < 4)
      return "usage: stat <npc> <stat>";
    StatsEnumerated st = STAT_NONE;
    if (!ParseStatName(f[3], st))
      return "unknown stat: " + f[3];
    CharStats *stats = c->getStats();
    if (!Valid(stats))
      return "no stats";
    float base = stats->getStat(st, true);
    float effective = stats->getStat(st, false);
    ok = true;
    return c->getName() + " " + f[3] + " base=" + Num(base) + " effective=" + Num(effective);
  }

  if (cmd == "setstat") { // setstat <npc> <stat> <value>
    if (f.size() < 5)
      return "usage: setstat <npc> <stat> <value>";
    StatsEnumerated st = STAT_NONE;
    if (!ParseStatName(f[3], st))
      return "unknown stat: " + f[3];
    CharStats *stats = c->getStats();
    if (!Valid(stats))
      return "no stats";
    float before = stats->getStat(st, true);
    stats->getStatRef(st) = (float)atof(f[4].c_str());
    float after = stats->getStat(st, true);
    ok = true;
    Log("KAH: setstat " + c->getName() + " " + f[3] + " " + Num(before) + " -> " + Num(after));
    return c->getName() + " " + f[3] + " " + Num(before) + " -> " + Num(after);
  }

  if (cmd == "weight") { // weight <npc>
    Inventory *inv = c->getInventory();
    if (!Valid(inv))
      return "no inventory";
    inv->recalculateTotalWeight();
    ok = true;
    return c->getName() + " inventory_weight=" + Num(inv->getTotalWeight());
  }

  if (cmd == "iteminfo" || cmd == "equip" || cmd == "unequip") {
    if (f.size() < 4)
      return "usage: " + cmd + " <npc> <item name>";
    bool ambiguous = false;
    Item *item = FindInventoryItem(c, f[3], ambiguous);
    if (ambiguous)
      return "ambiguous inventory item: " + f[3];
    if (!Valid(item))
      return "no inventory item matching: " + f[3];

    if (cmd == "equip") {
      Inventory *inv = c->getInventory();
      if (!Valid(inv))
        return "no inventory";
      bool equipped = inv->equipItem(item);
      ok = equipped && item->isEquipped;
      Log("KAH: equip " + c->getName() + " " + DescribeItem(item) + " ok=" + (ok ? "1" : "0"));
      return std::string(ok ? "equipped " : "equip failed ") + DescribeItem(item);
    }

    if (cmd == "unequip") {
      // As a player drag does: take the item out of its equipment section
      // (the game runs its unequip callbacks) and put it in the main
      // inventory; if there's no room there it is dropped next to the
      // character.
      if (!item->isEquipped)
        return "not equipped: " + DescribeItem(item);
      Inventory *inv = c->getInventory();
      if (!Valid(inv))
        return "no inventory";
      const std::string from = item->inventorySection;
      const int qty = item->quantity > 0 ? item->quantity : 1;
      Item *moved = inv->removeItemDontDestroy_returnsItem(item, qty, false);
      if (!Valid(moved))
        return "unequip failed (remove): " + DescribeItem(item);
      InventorySection *main = inv->getSection("main");
      bool placed = false;
      if (Valid(main))
        placed = main->addItem(moved, qty);
      std::string where = "main";
      if (!placed) {
        inv->dropItem(moved);
        where = "ground";
      }
      ok = !moved->isEquipped;
      Log("KAH: unequip " + c->getName() + " from=" + from + " to=" + where + " " +
          DescribeItem(moved) + " ok=" + (ok ? "1" : "0"));
      return std::string(ok ? "unequipped " : "unequip failed ") + "(" + from + " -> " + where +
             ") " + DescribeItem(moved);
    }

    ok = true;
    return DescribeItem(item);
  }

  if (cmd == "where") {
    ok = true;
    return Describe(c, &origin);
  }

  if (cmd == "sections") { // sections <npc>: inventory sections, sizes and items
    Inventory *inv = c->getInventory();
    if (!Valid(inv))
      return "no inventory";
    std::string out;
    lektor<InventorySection *> &sections = inv->getAllSections();
    for (uint32_t si = 0; si < sections.size(); ++si) {
      InventorySection *section = sections.stuff[si];
      if (!Valid(section))
        continue;
      out += " | " + section->name + " " + Int(section->width) + "x" + Int(section->height) +
             (section->isAnEquippedItemSection ? " equip" : "") + (section->containerSlot ? " container" : "") +
             (section->enabled ? "" : " disabled") + ":";
      const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
      for (size_t i = 0; i < items.size(); ++i)
        if (Valid(items[i].item))
          out += " [" + items[i].item->getName() + "]";
    }
    ContainerItem *pack = c->hasABackpackOn();
    ok = true;
    return c->getName() + " backpack=" + (Valid(pack) ? pack->getName() : std::string("none")) +
           out;
  }

  if (cmd == "hp") { // per body part flesh/max, and the worst part in %
    MedicalSystem &med = c->medical;
    std::string out;
    float worst = 1.0f;
    int count = med.getPartCount();
    for (int i = 0; i < count; ++i) {
      MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)i);
      if (!Valid(part))
        continue;
      float maxHp = part->maxHealth();
      if (maxHp > 0.0f && part->flesh / maxHp < worst)
        worst = part->flesh / maxHp;
      out += " " + Int(i) + ":" + Num(part->flesh) + "/" + Num(maxHp);
      if (part->bandaging > 0.0f)
        out += "(bandaged " + Num(part->bandaging) + ")";
    }
    ok = true;
    return c->getName() + " worst=" + Int((long long)(worst * 100.0f)) + "% blood=" +
           Num(med.blood) + "/" + Num(med.getMaxBlood()) + (c->isUnconcious() ? " KO" : "") +
           " parts" + out;
  }

  if (cmd == "inv") { // inventory incl. worn items, as JSON (works on bodies)
    std::string json;
    int count = 0;
    ok = BuildInventoryJson(c, json, count);
    return Describe(c, nullptr) + " items=" + Int(count) + " " + json;
  }

  if (cmd == "teleport") { // teleport <npc> <npc2 | x y z | building <name>> [dist m]
    Ogre::Vector3 to;
    std::string error;
    if (f.size() >= 5 && Lower(f[3]) == "building") {
      // Next to the nearest matching building within 5000 of the player
      // (radius <m> to change), `dist` (default 15) along x off its centre.
      float radius = 0, dist = 0;
      if (!ParseSearchRadius(f, 5, 0, kMaxSearchRadius, radius, error))
        return error;
      Building *b = FindBuilding(world, origin, f[4], radius, dist);
      if (!b)
        return "no building matching '" + f[4] + "' within " + Num(radius) + " of the player";
      to = b->getPosition();
      to.x += (float)atof(Option(f, 5, "dist", "15").c_str());
      c->teleport(to, Ogre::Quaternion::IDENTITY);
      ok = true;
      Log("KAH: teleport " + Describe(c, nullptr) + " to " + b->getName());
      return "teleported next to " + b->getName() + " (" + Num(dist) + " from the player): " +
             Describe(c, &origin);
    }
    if (!ResolvePosition(world, f, 3, to, error))
      return error;
    to.x += (float)atof(Option(f, 3, "dist", "0").c_str());
    c->teleport(to, Ogre::Quaternion::IDENTITY);
    ok = true;
    Log("KAH: teleport " + Describe(c, nullptr));
    return "teleported: " + Describe(c, &origin);
  }

  if (cmd == "ko") { // ko <npc> [seconds]
    float seconds = f.size() >= 4 ? (float)atof(f[3].c_str()) : 30.0f;
    c->medical.knockoutForceTimer(seconds);
    ok = true;
    Log("KAH: ko " + c->getName() + " seconds=" + Num(seconds));
    return "knocked out " + c->getName() + " for " + Num(seconds) + " s";
  }

  if (cmd == "health") { // health <npc> <percent of max for every body part>
    if (f.size() < 4)
      return "usage: health <npc> <percent, e.g. 30 or -50>";
    float pct = (float)atof(f[3].c_str());
    SetAllParts(c, pct / 100.0f);
    if (pct >= 100.0f)
      c->medical.blood = c->medical.getMaxBlood();
    ok = true;
    Log("KAH: health " + c->getName() + " pct=" + Num(pct));
    return "set every body part of " + c->getName() + " to " + Num(pct) + "%";
  }

  if (cmd == "kill") {
    SetAllParts(c, -2.0f);
    ok = true;
    Log("KAH: kill " + c->getName());
    return "killed " + c->getName() + " (body parts at -200%)";
  }

  if (cmd == "hunger") { // hunger <npc> [game UI value, 0..300]; no value = read only
    float before = c->medical.hunger * 100.0f;
    if (f.size() < 4) {
      ok = true;
      return c->getName() + " hunger " + Num(before);
    }
    c->medical.hunger = (float)atof(f[3].c_str()) / 100.0f;
    ok = true;
    Log("KAH: hunger " + c->getName() + " " + Num(before) + " -> " + f[3]);
    return c->getName() + " hunger " + Num(before) + " -> " + Num(c->medical.hunger * 100.0f);
  }

  if (cmd == "attack") { // attack <attacker> <target>
    if (f.size() < 4)
      return "usage: attack <attacker> <target>";
    Character *target = FindCharacter(world, f[3]);
    if (!target)
      return "no character named: " + f[3];
    // A real order, as the player gives it: mods lift their truces first
    // (KAH_RegisterBeforeAttack), then the attack is queued.
    RunBeforeAttack(c, target);
    OrdersReceiver *orders = c->getOrdersReciever();
    if (orders && (uintptr_t)orders > 0x1000)
      orders->addOrder(UNPROVOKED_FOCUSED_MELEE_ATTACK, target->getHandle(),
                       target->getPosition(), true, false);
    c->attackTarget(target);
    ok = true;
    Log("KAH: attack " + c->getName() + " -> " + target->getName());
    return c->getName() + " attacks " + target->getName();
  }

  if (cmd == "money") { // money <npc> <delta>: add (or with a minus, take) cats
    if (f.size() < 4)
      return "usage: money <npc> <delta>";
    int delta = atoi(f[3].c_str());
    int before = c->getMoney();
    c->takeMoney(-delta);
    ok = true;
    Log("KAH: money " + c->getName() + " " + Int(before) + " -> " + Int(c->getMoney()));
    return c->getName() + " cats " + Int(before) + " -> " + Int(c->getMoney());
  }

  if (cmd == "buy") { // buy <buyer> <seller> <item> <price>: one atomic purchase
    if (f.size() < 6)
      return "usage: buy <buyer> <seller> <item> <price>";
    Character *seller = FindCharacter(world, f[3]);
    if (!seller)
      return "no character named: " + f[3];
    int price = atoi(f[5].c_str());
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[4], error);
    if (!data)
      return error;
    Item *item = MakeItem(world, data, f, 6, nullptr, error);
    Inventory *inv = c->getInventory();
    if (!Valid(item) || !Valid(inv) || !inv->addItem(item, 1, false, true))
      return "could not add the item";
    c->takeMoney(price);
    seller->takeMoney(-price);
    ok = true;
    Log("KAH: buy " + c->getName() + " <- " + seller->getName() + " " + data->name +
        " for " + Int(price));
    return c->getName() + " bought " + data->name + " from " + seller->getName() + " for " +
           Int(price);
  }

  if (cmd == "select") {
    world->player->selectObject(c, false);
    ok = true;
    return "selected " + c->getName();
  }

  if (cmd == "recruit") {
    ok = world->player->recruit(c, false);
    Log("KAH: recruit " + c->getName() + " ok=" + (ok ? "1" : "0"));
    return (ok ? "recruited " : "recruit failed: ") + c->getName();
  }

  if (cmd == "give") { // give <npc> <item> [count]
    if (f.size() < 4)
      return "usage: give <npc> <item> [count]";
    int count = CountArg(f, 4);
    if (count < 1 || count > 50)
      return "count must be 1..50";
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[3], error);
    if (!data)
      return error;
    Inventory *inv = c->getInventory();
    if (!Valid(inv))
      return "no inventory";
    int added = 0;
    int countBefore = CountAllSections(inv, data);
    error.clear();
    for (int i = 0; i < count; ++i) {
      Item *item = MakeItem(world, data, f, 4, nullptr, error);
      if (!Valid(item) || !inv->addItem(item, 1, false, true))
        break;
      ++added;
    }
    if (added == 0 && !error.empty())
      return error;
    // addItem can report success for items that don't stay: report what really arrived.
    int real = CountAllSections(inv, data) - countBefore;
    Log("KAH: give " + c->getName() + " item=" + data->name + " added=" + Int(added) +
        " real=" + Int(real) + " now=" + Int(countBefore + real));
    ok = real > 0;
    return c->getName() + " got " + Int(real) + "/" + Int(count) + " " + data->name +
           " (now " + Int(countBefore + real) + ")";
  }

  if (cmd == "relation") { // relation <npc> <value -100..100>: npc's faction <-> player faction
    if (f.size() < 4)
      return "usage: relation <npc> <value -100..100>";
    Faction *theirs = c->getFaction();
    Faction *ours = player->getFaction();
    if (!Valid(theirs) || !Valid(ours) || !Valid(theirs->relations) || !Valid(ours->relations))
      return "faction not found";
    float v = (float)atof(f[3].c_str());
    float before = theirs->relations->getFactionRelation(ours);
    theirs->relations->setRelation(ours, v);
    ours->relations->setRelation(theirs, v);
    ok = true;
    Log("KAH: relation " + theirs->getName() + " <-> " + ours->getName() + " " +
        Num(before) + " -> " + Num(v));
    return theirs->getName() + " <-> " + ours->getName() + ": " + Num(before) + " -> " +
           Num(theirs->relations->getFactionRelation(ours));
  }

  return "unknown command: " + cmd;
}
