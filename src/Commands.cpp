// Built-in harness commands (TEST ONLY): load/save games, spawn characters,
// move, hurt or knock out anyone, set hunger, stats, money, items, game
// speed and faction relations. See docs/COMMANDS.md.
#ifndef NOMINMAX
#define NOMINMAX // OgreRoot.h uses std::min/max
#endif
#include "Harness.h"

#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/Character.h>
#include <kenshi/CharStats.h>
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
      std::string name;
      try { name = Lower(item->getName()); } catch (...) { continue; }
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
    s << item->getName()
      << " handle=" << item->getHandle().toString()
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

std::string CurrentSave() {
  try {
    SaveManager *sm = SaveManager::getSingleton();
    if (Valid(sm))
      return sm->getCurrentGame();
  } catch (...) {
  }
  return "";
}

const char *const kBuiltins[] = {
    "help",  "status", "load",     "save",    "speed",  "chars",   "find",  "spawn",
    "stash", "stat",   "setstat",  "weight",  "iteminfo", "equip", "unequip",
    "where", "hp",     "inv",      "teleport", "ko",    "health",  "kill",  "hunger",
    "attack", "money", "buy",      "select",  "recruit", "give",   "relation"};

const char *const kHelp =
    "built-in: help | status | load <save> | save <name> | speed <0|0.5..50> | "
    "chars [radius] | find <character|squad|item|weapon|armour> <text> | "
    "spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] "
    "[size <mult>] | stash <item> <n> [near <npc>] | stat <npc> <stat> | "
    "setstat <npc> <stat> <value> | weight <npc> | iteminfo|equip|unequip <npc> <item> | "
    "where|hp|inv|select|recruit|kill <npc> | teleport <npc> <npc2 | x y z> [dist m] | "
    "ko <npc> [seconds] | health <npc> <percent> | hunger <npc> <0..300> | "
    "attack <attacker> <target> | money <npc> <delta> | buy <buyer> <seller> <item> <price> | "
    "give <npc> <item> [n] | relation <npc> <-100..100>. "
    "<npc> = name (exact match nearest the player wins, else nearest substring), "
    "#serial, @player or @selected.";

} // namespace

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

  if (cmd == "help") {
    ok = true;
    return std::string(kHelp) + ExtensionCommandList();
  }

  if (cmd == "status") {
    ok = true;
    std::string out = "phase=" + Phase(world) + " save=" + CurrentSave();
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
  Ogre::Vector3 origin = player->getPosition();

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

  if (cmd == "find") { // find <character|squad|item|faction> <substring>
    if (f.size() < 4)
      return "usage: find <character|squad|item|weapon|armour> <text>";
    const std::string kind = Lower(f[2]);
    itemType type = kind == "squad" ? SQUAD_TEMPLATE
                    : kind == "item" ? ITEM
                    : kind == "weapon" ? WEAPON
                    : kind == "armour" ? ARMOUR
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
    const itemType types[] = {ITEM, WEAPON, ARMOUR};
    for (int t = 0; t < 3 && !data; ++t)
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
      Item *item = world->theFactory->createItem(data, hand(), nullptr, nullptr, -1, nullptr);
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
      std::string section = item->inventorySection;
      c->unequipItem(section, item);
      ok = !item->isEquipped;
      Log("KAH: unequip " + c->getName() + " " + DescribeItem(item) + " ok=" + (ok ? "1" : "0"));
      return std::string(ok ? "unequipped " : "unequip failed ") + DescribeItem(item);
    }

    ok = true;
    return DescribeItem(item);
  }

  if (cmd == "where") {
    ok = true;
    return Describe(c, &origin);
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

  if (cmd == "teleport") { // teleport <npc> <npc2 | x y z> [dist m]
    Ogre::Vector3 to;
    std::string error;
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

  if (cmd == "hunger") { // hunger <npc> <game UI value, 0..300>
    if (f.size() < 4)
      return "usage: hunger <npc> <value as shown in game, 0..300>";
    float before = c->medical.hunger * 100.0f;
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
    const itemType types[] = {ITEM, WEAPON, ARMOUR};
    for (int t = 0; t < 3 && !data; ++t)
      data = FindData(world, types[t], f[4], error);
    if (!data)
      return error;
    Item *item = world->theFactory->createItem(data, hand(), nullptr, nullptr, -1, nullptr);
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
    int count = f.size() >= 5 ? atoi(f[4].c_str()) : 1;
    if (count < 1 || count > 50)
      return "count must be 1..50";
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR};
    for (int t = 0; t < 3 && !data; ++t)
      data = FindData(world, types[t], f[3], error);
    if (!data)
      return error;
    Inventory *inv = c->getInventory();
    if (!Valid(inv))
      return "no inventory";
    int added = 0;
    int countBefore = inv->countItems(data);
    for (int i = 0; i < count; ++i) {
      Item *item = world->theFactory->createItem(data, hand(), nullptr, nullptr, -1, nullptr);
      if (!Valid(item) || !inv->addItem(item, 1, false, true))
        break;
      ++added;
    }
    // addItem can report success for items that don't stay: report what really arrived.
    int real = inv->countItems(data) - countBefore;
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
