// Built-in harness commands (TEST ONLY): load/save games, spawn characters,
// move, hurt or knock out anyone, set hunger, stats, money, items, game
// speed and faction relations. See docs/COMMANDS.md.
#ifndef NOMINMAX
#define NOMINMAX // OgreRoot.h uses std::min/max
#endif
#include "Harness.h"
#include "SearchRadius.h"
#include "BuildArgs.h"
#include "CharacterRef.h"
#include "ProductionCounter.h"
#include "ImportFlags.h"
#include "WalkArrival.h"
#include "AccelProfile.h"
#include "GroundOwner.h"
#include "HitCredit.h"
#include "RangedShots.h"
#include "ProtectRules.h"
#include "CrimeArgs.h"
#include "RaceFilter.h"
#include "HoldSpeed.h"
#include "Chatter.h"
#include "FrameStamp.h"

#include <kenshi/AI/AITaskSystem.h>
#include <kenshi/Character.h>
#include <kenshi/CharMovement.h>
#include <kenshi/CharStats.h>
#include <kenshi/Building/CraftingBuilding.h>
#include <kenshi/Research.h>
#include <set>
#include <kenshi/Building/Building.h>
#include <kenshi/Building/FarmBuilding.h>
#include <kenshi/Building/ProductionBuilding.h>
#include <kenshi/Building/StorageBuilding.h>
#include <kenshi/Building/UseableStuff.h>
#include <kenshi/Building/TurretBuilding.h>
#include <kenshi/GunClass.h>
#include <kenshi/combat/RangedCombatClass.h>
#include <map>
#include <kenshi/util/TimeOfDay.h>
#include <mygui/MyGUI_Gui.h>
#include <mygui/MyGUI_TextBox.h>
#include <mygui/MyGUI_Widget.h>
#include <mygui/MyGUI_Delegate.h>
#include <mygui/MyGUI_LayerManager.h>
#include <mygui/MyGUI_RenderManager.h>
#include <kenshi/gui/ForgottenGUI.h>      // character editor (newgame)
#include <kenshi/gui/MessageBoxManager.h> // its "are you sure" box
#include <kenshi/gui/DialogueWindow.h>    // dialog (the open conversation window)
#include <kenshi/Dialogue.h>
#include <kenshi/Damages.h>
#include <kenshi/SensoryData.h> // senses
#include <kenshi/Faction.h>
#include <kenshi/Gear.h> // LockedArmour (chance lockpick)
#include <kenshi/SharedKing.h> // shou->townList (towns)
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
#include <kenshi/CameraClass.h> // acceltime follow, camfollow
#include <kenshi/RootObjectFactory.h>
#include <kenshi/RaceData.h>
#include <kenshi/NavMesh.h> // walktime: is the target on the navmesh
#include <kenshi/SaveManager.h>
#include <kenshi/gui/LoadSaveWindow.h> // ImportGameMenu (import ... menu)
#include <mygui/MyGUI_Button.h>
#include <mygui/MyGUI_MultiListBox.h>
#include <kenshi/SaveInfo.h>
#include <kenshi/ShopTrader.h>
#include <kenshi/ShopTraderInventory.h>
#include <kenshi/Town.h>
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

// Why the last FindCharacter found nothing (ambiguous or malformed #ref);
// empty = plain "not found".
std::string g_findError;

std::string NotFound(const std::string &name) {
  return g_findError.empty() ? "no character named: " + name : g_findError;
}

// "@player" (first squad member), "@selected", "#serial/index" (exact
// handle), "#serial" (must be unique), or a name: exact (case-insensitive)
// match nearest the player wins, else nearest substring.
Character *FindCharacter(GameWorld *world, const std::string &name) {
  g_findError.clear();
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
  const CharacterRef ref = ParseCharacterRef(name);
  if (ref.isRef && !ref.valid) {
    g_findError = "bad character reference '" + name + "' (use #serial/index as printed, or #serial)";
    return nullptr;
  }
  Character *exact = nullptr, *partial = nullptr;
  float exactDist = 0, partialDist = 0;
  std::vector<Character *> chars;
  CollectCharacters(world, origin, 500.0f, chars);
  std::vector<Character *> bySerial;
  for (size_t i = 0; i < chars.size(); ++i) {
    Character *c = chars[i];
    if (ref.isRef) {
      try {
        const hand &h = c->getHandle();
        if ((unsigned long)h.serial != ref.serial)
          continue;
        if (ref.hasIndex) {
          if ((unsigned long)h.index == ref.index)
            return c;
          continue;
        }
        if (std::find(bySerial.begin(), bySerial.end(), c) == bySerial.end())
          bySerial.push_back(c);
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
  if (ref.isRef) {
    if (bySerial.size() == 1)
      return bySerial[0];
    if (bySerial.size() > 1) {
      g_findError = "ambiguous " + name + ": " + Int((long long)bySerial.size()) +
                    " characters share that serial, use #serial/index:";
      for (size_t k = 0; k < bySerial.size() && k < 8; ++k) {
        try {
          g_findError += " [" + bySerial[k]->getName() + " " +
                         FormatCharacterRef(bySerial[k]->getHandle().serial, bySerial[k]->getHandle().index) +
                         " dist=" + Num(bySerial[k]->getPosition().distance(origin)) + "]";
        } catch (...) {
        }
      }
    }
    return nullptr;
  }
  return exact ? exact : partial;
}

// Stat names for stat/setstat (KAH 16: every skill the game has, melee
// ones included; the first name of each entry is what "stat <npc> all" prints).
struct StatName {
  const char *name;
  StatsEnumerated stat;
};
const StatName kStatNames[] = {
    {"strength", STAT_STRENGTH}, {"toughness", STAT_TOUGHNESS},
    {"dexterity", STAT_DEXTERITY}, {"athletics", STAT_ATHLETICS},
    {"perception", STAT_PERCEPTION},
    {"attack", STAT_MELEE_ATTACK}, {"melee_attack", STAT_MELEE_ATTACK}, {"melee", STAT_MELEE_ATTACK},
    {"defence", STAT_MELEE_DEFENCE}, {"defense", STAT_MELEE_DEFENCE}, {"melee_defence", STAT_MELEE_DEFENCE},
    {"melee_defense", STAT_MELEE_DEFENCE}, {"dodge", STAT_DODGE}, {"martial_arts", STAT_MARTIALARTS},
    {"martialarts", STAT_MARTIALARTS}, {"katanas", STAT_KATANAS}, {"sabres", STAT_SABRES},
    {"sabers", STAT_SABRES}, {"hackers", STAT_HACKERS}, {"heavy_weapons", STAT_HEAVYWEAPONS},
    {"heavyweapons", STAT_HEAVYWEAPONS}, {"blunt", STAT_BLUNT}, {"polearms", STAT_POLEARMS},
    {"crossbows", STAT_CROSSBOWS}, {"turrets", STAT_TURRETS}, {"turret", STAT_TURRETS},
    {"weapons", STAT_WEAPONS}, {"mass_combat", STAT_MASSCOMBAT}, {"masscombat", STAT_MASSCOMBAT},
    {"friendly_fire", STAT_FRIENDLY_FIRE}, {"precision_shooting", STAT_FRIENDLY_FIRE},
    {"stealth", STAT_STEALTH}, {"assassination", STAT_ASSASSINATION},
    {"lockpicking", STAT_LOCKPICKING}, {"thievery", STAT_THIEVING}, {"thieving", STAT_THIEVING},
    {"swimming", STAT_SWIMMING}, {"survival", STAT_SURVIVAL},
    {"labouring", STAT_LABOURING}, {"laboring", STAT_LABOURING}, {"mining", STAT_LABOURING},
    {"science", STAT_SCIENCE}, {"research", STAT_SCIENCE}, {"engineering", STAT_ENGINEERING},
    {"robotics", STAT_ROBOTICS}, {"weapon_smith", STAT_SMITHING_WEAPON},
    {"weaponsmith", STAT_SMITHING_WEAPON}, {"armour_smith", STAT_SMITHING_ARMOUR},
    {"armor_smith", STAT_SMITHING_ARMOUR}, {"armoursmith", STAT_SMITHING_ARMOUR},
    {"crossbow_smith", STAT_SMITHING_BOW}, {"crossbowsmith", STAT_SMITHING_BOW},
    {"medic", STAT_MEDIC}, {"medicine", STAT_MEDIC}, {"hive_medic", STAT_HIVEMEDIC},
    {"vet", STAT_VET}, {"farming", STAT_FARMING}, {"cooking", STAT_COOKING},
    {"maxcarry", _MaxCarryWeight}, {"maxcarryweight", _MaxCarryWeight},
    {"maxrunspeed", _MaxRunSpeed}, {"currentrunspeed", _CurrentRunSpeed},
    {"encumbrance", _encumbrance}, {"combatspeed", _combatSpeed},
    {"damageresistance", _DamageResistance}, {"knockouttime", _KnockoutTime},
    {"primaryweapondamage", _PrimaryWeaponDamage}, {"primaryweaponspeed", _PrimaryWeaponSpeed},
};

bool ParseStatName(const std::string &name, StatsEnumerated &out) {
  const std::string n = Lower(name);
  for (size_t i = 0; i < sizeof(kStatNames) / sizeof(kStatNames[0]); ++i)
    if (n == kStatNames[i].name) {
      out = kStatNames[i].stat;
      return true;
    }
  return false;
}

// "stat <npc> all": every skill once (first name of each), base/effective.
std::string AllStats(CharStats *stats) {
  std::string out;
  std::vector<int> seen;
  for (size_t i = 0; i < sizeof(kStatNames) / sizeof(kStatNames[0]); ++i) {
    const StatsEnumerated st = kStatNames[i].stat;
    if ((int)st >= (int)STAT_END || std::find(seen.begin(), seen.end(), (int)st) != seen.end())
      continue;
    seen.push_back((int)st);
    out += " " + std::string(kStatNames[i].name) + "=" + Num(stats->getStat(st, true));
    const float eff = stats->getStat(st, false);
    if (eff != stats->getStat(st, true))
      out += "(" + Num(eff) + ")";
  }
  return out;
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

// The character's race name (RaceData -> GameData name), "?" when unreadable (PG 199).
std::string RaceName(Character *c) {
  try {
    RaceData *r = Valid(c) ? c->getRace() : nullptr;
    if (r && r->data)
      return r->data->name;
  } catch (...) {
  }
  return "?";
}

std::string Describe(Character *c, const Ogre::Vector3 *origin) {
  std::string out;
  try {
    out = c->getName();
    out += " " + FormatCharacterRef(c->getHandle().serial, c->getHandle().index);
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
    if (c->isUnique()) // the game's own flag: named, non-template NPC (KAH 13)
      out += " unique=1";
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

// FindData over several item types, an exact name/stringID in any of them first: otherwise a partial match in
// an earlier type wins ("Toothpick" (CROSSBOW) found "Bolts [Toothpicks]" (ITEM), m46)
GameData *FindDataTypes(GameWorld *world, const itemType *types, int n, const std::string &name,
                        std::string &error) {
  const std::string wanted = Lower(name);
  for (int t = 0; t < n; ++t) {
    const auto categoryIt = world->gamedata.gamedataCatSID.find((int)types[t]);
    if (categoryIt == world->gamedata.gamedataCatSID.end())
      continue;
    for (auto it = categoryIt->second.begin(); it != categoryIt->second.end(); ++it) {
      GameData *data = it->second;
      if (Valid(data) && (Lower(data->stringID) == wanted || Lower(data->name) == wanted))
        return data;
    }
  }
  GameData *data = nullptr;
  for (int t = 0; t < n && !data; ++t)
    data = FindData(world, types[t], name, error);
  return data;
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
    error = NotFound(f[at]);
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

// Weapons (weapon-matrix, 2026-10-10): RootObjectFactory::createItem returns null for a WEAPON GameData (its first
// check: type WEAPON or VENDOR_LIST -> null). The game builds a weapon from its MANUFACTURER: gd = the
// WEAPON_MANUFACTURER, 3rd arg ("weaponMesh") = the WEAPON type, 4th = the MATERIAL_SPECS_WEAPON model grade (null =
// the game picks from the maker's "weapon models"); reverse-engineered from kenshi_x64 Steam 1.0.65 createItem
// (RVA 0x57FCC0, GOG 0x57FFD0), branch type 0x33 = WEAPON_MANUFACTURER. Optional args after the count:
// `maker <name|sid>`, `model <name|sid>`; default maker: the player's (Homemade) if it makes this weapon, else the
// first maker that does, else Homemade / any maker (the game falls back to a default level for unlisted weapons).
bool RefListHas(GameData *d, const char *list, const std::string &sid) {
  const Ogre::vector<GameDataReference>::type *l = Valid(d) ? d->getReferenceListIfExists(list) : nullptr;
  if (!l)
    return false;
  for (size_t i = 0; i < l->size(); ++i)
    if ((*l)[i].sid == sid)
      return true;
  return false;
}

GameData *DataBySid(GameWorld *world, itemType type, const std::string &sid) {
  const auto cat = world->gamedata.gamedataCatSID.find((int)type);
  if (cat == world->gamedata.gamedataCatSID.end())
    return nullptr;
  for (auto it = cat->second.begin(); it != cat->second.end(); ++it)
    if (Valid(it->second) && it->second->stringID == sid)
      return it->second;
  return nullptr;
}

Item *MakeWeapon(GameWorld *world, GameData *data, const std::vector<std::string> &f, size_t from,
                 GameData *defaultMaker, std::string &error) {
  GameData *maker = nullptr, *model = nullptr;
  for (size_t i = from; i + 1 < f.size(); ++i) {
    if (Lower(f[i]) == "maker" && !(maker = FindData(world, WEAPON_MANUFACTURER, f[i + 1], error)))
      return nullptr;
    if (Lower(f[i]) == "model" && !(model = FindData(world, MATERIAL_SPECS_WEAPON, f[i + 1], error)))
      return nullptr;
  }
  if (!maker && Valid(defaultMaker) && RefListHas(defaultMaker, "weapon types", data->stringID))
    maker = defaultMaker;
  if (!maker) {
    const auto cat = world->gamedata.gamedataCatSID.find((int)WEAPON_MANUFACTURER);
    if (cat != world->gamedata.gamedataCatSID.end()) {
      for (auto it = cat->second.begin(); it != cat->second.end() && !maker; ++it)
        if (Valid(it->second) && it->second->stringID == "PLAYER_WEAPONS" &&
            RefListHas(it->second, "weapon types", data->stringID))
          maker = it->second;
      for (auto it = cat->second.begin(); it != cat->second.end() && !maker; ++it)
        if (Valid(it->second) && RefListHas(it->second, "weapon types", data->stringID) &&
            it->second->getReferenceListIfExists("weapon models") &&
            !it->second->getReferenceListIfExists("weapon models")->empty())
          maker = it->second;
    }
  }
  if (!maker && Valid(defaultMaker))
    maker = defaultMaker;   // modded weapons no maker lists: the game still builds them
  if (!maker) {
    const auto cat = world->gamedata.gamedataCatSID.find((int)WEAPON_MANUFACTURER);
    if (cat != world->gamedata.gamedataCatSID.end())
      for (auto it = cat->second.begin(); it != cat->second.end() && !maker; ++it)
        if (Valid(it->second) && it->second->getReferenceListIfExists("weapon models") &&
            !it->second->getReferenceListIfExists("weapon models")->empty())
          maker = it->second;
  }
  if (!maker) {
    error = "no weapon manufacturer found for " + data->name + " (" + data->stringID + "): give `maker <name>`";
    return nullptr;
  }
  if (!model) {
    const Ogre::vector<GameDataReference>::type *l = maker->getReferenceListIfExists("weapon models");
    for (size_t i = 0; l && i < l->size() && !model; ++i)
      model = DataBySid(world, MATERIAL_SPECS_WEAPON, (*l)[i].sid);
  }
  if (!model) {
    error = "manufacturer " + maker->name + " has no weapon model grade: give `model <name>`";
    return nullptr;
  }
  Item *item = world->theFactory->createItem(maker, hand(), data, model, -1, nullptr);
  if (!Valid(item))   // let the game pick the grade from the maker's list
    item = world->theFactory->createItem(maker, hand(), data, nullptr, -1, nullptr);
  if (!Valid(item))
    error = "the game could not create " + data->name + " (maker " + maker->name + ", model " + model->name + ")";
  else
    Log("KAH: weapon " + data->name + " sid=" + data->stringID + " maker=" + maker->name + " model=" + model->name);
  return Valid(item) ? item : nullptr;
}

// Creates one item (weapons through MakeWeapon).
Item *MakeItem(GameWorld *world, GameData *data, const std::vector<std::string> &f, size_t from,
               GameData *defaultMaker, std::string &error) {
  if (data->type == WEAPON)
    return MakeWeapon(world, data, f, from, Valid(defaultMaker) ? defaultMaker : CraftingBuilding::playerManufacturerData(), error);
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
// "research status": the queue (progress 0..1 as the game reports it, raw
// progress, ETA), the research rate, researchers working this frame, the
// desk level and every research bench with its distance (KAH 14).
std::string ResearchStatus(GameWorld *world, Research *tech, const Ogre::Vector3 &origin) {
  std::string out;
  try {
    std::deque<ResearchItem, Ogre::STLAllocator<ResearchItem, Ogre::GeneralAllocPolicy> > &q =
        tech->getResearchQueue();
    out = "queue=" + Int(q.size());
    for (size_t i = 0; i < q.size(); ++i) {
      ResearchItem &it = q[i];
      if (!Valid(it.data))
        continue;
      out += " [" + it.data->name + " progress=" + Num(tech->getResearchProgress(&it)) +
             " raw=" + Num(it.progress) + " eta=" + OneLine(tech->getETA(it.data, true)) + "]";
    }
    out += " rate=" + Num(tech->getCurrentResearchRate()) + " researchers=" + Int(tech->numResearchers) +
           " desk_level=" + Int(tech->getResearchDeskLevel());
    lektor<Building *> benches;
    tech->getAllResearchBenches(benches);
    out += " benches=" + Int(benches.size());
    for (uint32_t i = 0; i < benches.size() && i < 8; ++i) {
      Building *b = benches.stuff[i];
      if (Valid(b))
        out += " {" + b->getName() + " dist=" + Num(b->getPosition().distance(origin)) +
               (b->isPowerOn() ? "" : " power_off") + "}";
    }
  } catch (...) {
    out += " (unreadable)";
  }
  return out;
}

int CountArg(const std::vector<std::string> &f, size_t at) {
  if (f.size() <= at)
    return 1;
  const std::string v = Lower(f[at]);
  if (v == "at" || v == "near" || v == "section" || v == "radius" || v == "maker" || v == "model")
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
    // fleshStun is stun damage (ProtectRules.h PartHealthTarget): writing it
    // to max left every part at 0% health and the wounds factor at 0.25.
    PartHealthTarget(part->maxHealth(), fraction, part->flesh, part->fleshStun);
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
// The current world came from New Game (and nothing was loaded or imported
// since): the only state the game offers Import in (KAH 23).
bool g_freshNewGame = false;

// newgame (to-do 19): New Game opens the game's character editor once the
// world is built, and the world waits there until the player presses
// CONFIRM (m18-4080: phase=loading for 5 min, nothing to say why). The
// harness reports that as phase=chargen and, unless "newgame ... edit",
// presses CONFIRM and accepts the box like a player.
bool g_newGamePending = false; // a harness newgame not yet in the world
bool g_newGameAuto = false;    // confirm the character editor ourselves
int g_chargenStep = 0;         // 0 wait, 1 CONFIRM clicked, 2 box accepted
int g_chargenTries = 0;
DWORD g_chargenAt = 0;         // first seen / last step
DWORD g_newGameLastReport = 0;

bool CharEditorOpen(GameWorld *world) {
  bool open = false;
  try {
    if (gui)
      open = gui->isCharacterEditorMode();
  } catch (...) {
  }
  try {
    if (!open && Valid(world) && Valid(world->player))
      open = world->player->characterEditorMode;
  } catch (...) {
  }
  return open;
}

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
#include "BalanceCommands.inc"
#include "TurretCommands.inc"
#include "RangedCommands.inc"

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
    "trade", "eat", "blood", "build", "unbuild", "fps", "produced", "protect", "drop", "pickup", "unload", "reload", "runspeed", "walktime", "sever", "hit", "newgame", "import", "stealth", "crime",
    "chance", "detect", "detecttime", "senses", "face", "pin", "healtime", "water", "findwater", "swimtime", "acceltime", "camfollow", "construct", "construction", "farm", "towns", "turret", "rangedtest", "rangedinfo", "combatmode", "dialog", "input_isolation", "key_inject", "mouse_inject", "chatter", "sync_flash", "stamp", "sampler"};

const char *const kHelp =
    "built-in: help | status | load <save> | save <name> | newgame <start> [edit] | import <save> [flags] | speed <0|0.5..50> [hold] | chatter off|on|status | "
    "chars [radius] [filter] | traders [radius] | benches [radius] [crafts] | research <name> | research start|stop <name> | research status | "
    "blueprint <item> | craft <npc> <item> [at <bench>] [count n] | find <character|squad|item|weapon|armour|container> <text> | "
    "spawn <template> <faction> [near <npc> | at x y z] [count n] [dist m] [target <npc>] [race <a|b|!c>] "
    "[size <mult>] | stash <item> <n> [near <npc>] | stat <npc> <stat> | "
    "setstat <npc> <stat> <value> | stat <npc> all | weight <npc|building> | iteminfo|equip|unequip <npc> <item> | "
    "where|hp|inv|sections|select|recruit|kill <npc> | teleport <npc> <npc2 | x y z | building <name>> [dist m] | "
    "ko <npc> [seconds] | health <npc> <percent> | hunger <npc> [0..300] | "
    "attack <attacker> <target> | money <npc> <delta> | buy <buyer> <seller> <item> <price> | "
    "give <npc> <item> [n] | relation <npc> <-100..100> | "
    "order <npc> <task> [target <npc>] [building <name>] [keep] | tasks [filter] | fight <a> <b> | "
    "job <npc> <building> [task <name>] [radius <m>] | jobs|clearjobs <npc> | setname <npc> <name> | "
    "faction <npc> <faction> | sleep <npc> [bed <name>] | wake <npc> | "
    "damage <npc> <part> <cut> [blunt] [pierce] | blood <npc> <value|pct%> | protect [<npc> on|off] | shackle <npc> [owner <npc>] | unshackle <npc> | "
    "cage|uncage <npc> [cage] | shopstock <trader> [radius <m>] | trade <buyer> <trader> <item> [radius <m>] | "
    "eat <npc> <food> | stealth <npc> on|off | crime <npc> [radius <m>] | crime <npc> commit <crime> against <owner> [witnessed] | "
    "chance <npc> ko|kidnap|lockpick|steal <target> [item <name>] | detect <sneaker> | detecttime <sneaker> <observer> [timeout <s>] | senses <observer> <who> | face <npc> <who> | pin <npc> [at <npc|x y z>] [dist m] [face <who>] | pin <npc> off | "
    "healtime <medic> <patient> [wound <cut>] [timeout <s>] | water <npc> | findwater <npc> [radius <m>] [depth <m>] | "
    "swimtime <npc> <dist> [+x|-x|+z|-z] [walk|run] | construct <npc> <building> [dist <m>] | construction <building> [reset] [fill] | farm <building> [grown <0..1>] [skip <hours>] [empty] | towns [filter,...] [max <n>] | turret <building> [radius <m>] [target <npc>] [front <m>] [aim <npc>|off] | "
    "rangedtest <shooter> <target> [shots <n>] [window <s>] [timeout <s>] [noheal] [noaim] [attack] [keepranged] | rangedtest <shooter> last | rangedinfo <npc> [clearturret] | combatmode <npc> [block|ranged|taunt|hold|passive on|off] | dialog [close] | "
    "sever <npc> <limb> [noitem] [ko] | hit <attacker> <victim> <part> <damage> | runspeed <npc> | walktime <npc> <dist> [+x|-x|+z|-z] [walk|run] | acceltime <npc> <dist> [+x|-x|+z|-z] [walk|run] [stopat <d>] [halt] [follow] | camfollow <npc> [on|off] | unload <npc> | reload <name> | drop <npc> <item> [count] [owned] | pickup <npc> <item|#serial/index|nearest> [near <npc|building>] [radius <m>] [order|now] | build <building|sid> [near <npc> [dist m] | at x y z] [faction <f>] | "
    "unbuild <name> [radius] | time | buildings [radius] [filter] [near <npc>] | building <name> [radius] | "
    "produced <building> [reset] [radius <m>] | power <building> on|off|charge|supply|unsupply [radius <m>] | fill <building> <item> [n] [section <s>] [radius <m>] | "
    "ui [filter] [all] | click <widget> | messages [n] | screenshot [name] | sync_flash [ms] [n] | stamp on [cell] [flash] [log <file>]|off|status | sampler start <ms> <file> <query>... | sampler stop|status | fps [reset] | input_isolation on|off|status | key_inject <key> [down|up|tap] [ms] | mouse_inject <button> [down|up|click] [ms] | mouse_inject move <dx> <dy> | at <x> <y> | wheel <d> | "
    "transfer <from npc> <to npc> <item> | packput <npc> <pack> <item> [n] | "
    "packweight <npc|building|ground> <pack> | craftfinish <npc> <item> [at <bench>]. "
    "<npc> = name (exact match nearest the player wins, else nearest substring), "
    "#serial/index (exact, as printed) or #serial (refused if not unique), @player or @selected.";

// speed <x> hold: long unattended runs (PG balance at 20-50x on Full-Base) were stopped for good by the game's own
// pauses (m19-4080: "Bandit Demands has arrived at Your Outpost" paused the game and the scenario waited on).
// While a hold is active the harness unpauses and restores the speed 2 s after any pause it did not make itself.
float g_holdSpeed = 0;
DWORD g_holdPausedAt = 0;
int g_holdResumes = 0;

void HoldSpeedTick(GameWorld *world) {
  if (g_holdSpeed <= 0 || !Valid(world))
    return;
  // Never resume during a save load / menu (4080 b31: resumed 2 s into a load, then the game crashed in it).
  unsigned long pausedAt = g_holdPausedAt;
  const HoldAction act = HoldSpeedDecide(g_holdSpeed, Phase(world), world->isPaused(), GetTickCount(), pausedAt);
  g_holdPausedAt = pausedAt;
  if (act != HOLD_RESUME)
    return;
  world->userPause(false);
  world->setGameSpeed(g_holdSpeed, false);
  world->setFrameSpeedMultiplier(g_holdSpeed);
  g_holdPausedAt = 0;
  ++g_holdResumes;
  Log("KAH: speed hold: the game paused itself, resumed at " + Num(g_holdSpeed) + " (resume " + Int(g_holdResumes) + ")");
}

} // namespace

// GunClass::shoot hook (Plugin.cpp) -> per-turret shot counts for "turret".
// "turret <b> aim <npc>": every frame (Plugin.cpp).
void KeepTurretAim() {
  try {
    KeepTurretAimImpl();
  } catch (...) {
  }
}

void RecordGunShot(GunClass *gun, Character *me, RootObject *target, int stat) {
  try {
    RecordGunShotImpl(gun, me, target, stat);
  } catch (...) {
  }
}

void RecordRangedShot(GunClass *gun, Character *me, RootObject *target, int stat) {
  try {
    RecordRangedShotImpl(gun, me, target, stat);
  } catch (...) {
  }
}

void SampleProduction(GameWorld *world) {
  try {
    SampleTracked(world);
  } catch (...) {
  }
}

// chatter off: no NPC speech bubbles (barks) over video takes. Every world tick zeroes both speech timers on
// every character in the update list (as Stobe's ClearCharacterSpeechBubble); a bubble whose timer was still
// running counts as one muted bubble.
bool g_chatterOff = false;
unsigned long g_chatterMuted = 0;

void ChatterTick(GameWorld *world) {
  if (!g_chatterOff || !Valid(world) || Phase(world) != "world")
    return;
  const ogre_unordered_set<Character *>::type &chars = world->getCharacterUpdateList();
  for (ogre_unordered_set<Character *>::type::const_iterator it = chars.begin(); it != chars.end(); ++it) {
    Character *c = *it;
    try {
      if (!Valid(c) || !Valid(c->dialogue))
        continue;
      if (ChatterBubbleShowing(c->dialogue->speechTextTimer, c->dialogue->speechTextTimer_forced))
        ++g_chatterMuted;
      c->dialogue->speechTextTimer = 0.0f;
      c->dialogue->speechTextTimer_forced = 0.0f;
    } catch (...) {
    }
  }
}

void ImportMenuTick();

void KeepWalkTimers() {
  try {
    WalkTick(ou);
  } catch (...) {
  }
  try {
    ImportMenuTick();
  } catch (...) {
  }
  try {
    BalanceTick(ou);
  } catch (...) {
  }
  try {
    AccelTick(ou);
  } catch (...) {
  }
  try {
    PinTick(ou);
  } catch (...) {
  }
  try {
    HoldSpeedTick(ou);
  } catch (...) {
  }
  try {
    ChatterTick(ou);
  } catch (...) {
  }
  try {
    StealTick(ou);
  } catch (...) {
  }
  try {
    HitTick(ou);
  } catch (...) {
  }
  try {
    RangedTick(ou);
  } catch (...) {
  }
}

void KeepProtected() {
  try {
    ProtectTick();
  } catch (...) {
  }
}

void KeepSuppliedPowered() {
  try {
    TopUpSupplied();
  } catch (...) {
  }
}

// The character editor's CONFIRM button: name ends in "ConfirmButton"
// (Kenshi_CharacterEditor.layout; MyGUI may prefix it) or caption CONFIRM.
MyGUI::Widget *FindConfirmButton(MyGUI::Widget *w, int depth) {
  if (!w || depth > 40 || !w->getInheritedVisible())
    return nullptr;
  const std::string name = Lower(w->getName());
  const std::string key = "confirmbutton";
  if ((name.size() >= key.size() && name.compare(name.size() - key.size(), key.size(), key) == 0) ||
      Lower(Caption(w)) == "confirm")
    return w;
  for (size_t i = 0; i < w->getChildCount(); ++i) {
    MyGUI::Widget *found = FindConfirmButton(w->getChildAt(i), depth + 1);
    if (found)
      return found;
  }
  return nullptr;
}

// Visible button-like widgets (name ends in "Button" or has a caption), for the log when CONFIRM
// isn't found: "name 'caption'" joined by " | ", at most `max`.
void ListConfirmCandidates(MyGUI::Widget *w, int depth, std::string &out, int &n, int max) {
  if (!w || depth > 40 || n >= max || !w->getInheritedVisible())
    return;
  const std::string name = Lower(w->getName());
  const std::string caption = Caption(w);
  if ((name.size() >= 6 && name.compare(name.size() - 6, 6, "button") == 0) || !caption.empty()) {
    out += (n ? " | " : "") + w->getName() + " '" + OneLine(caption) + "'";
    ++n;
  }
  for (size_t i = 0; i < w->getChildCount() && n < max; ++i)
    ListConfirmCandidates(w->getChildAt(i), depth + 1, out, n, max);
}

// Every frame (via WatchLoads) while a harness newgame is pending: report
// what the game is doing every 10 s, and confirm the character editor.
void WatchNewGame() {
  if (!g_newGamePending)
    return;
  GameWorld *world = ou;
  const DWORD now = GetTickCount();
  bool open = CharEditorOpen(world);
  if (now - g_newGameLastReport >= 10000) {
    g_newGameLastReport = now;
    int signal = -1;
    bool loading = false, modal = false;
    try {
      SaveManager *sm = SaveManager::getSingleton();
      if (Valid(sm))
        signal = sm->signal;
      if (Valid(world))
        loading = world->isLoadingFromASaveGame();
      modal = MessageBoxManager::hasModalMessage();
    } catch (...) {
    }
    Log("KAH: newgame waiting: phase=" + Phase(world) + " signal=" + Int(signal) + " loading=" +
        (loading ? "1" : "0") + " squad=" + Int(InWorld(world) ? world->player->playerCharacters.size() : 0) +
        " chargen=" + (open ? "1" : "0") + " modal_box=" + (modal ? "1" : "0") + " step=" + Int(g_chargenStep));
  }
  if (!open) {
    if (g_chargenStep > 0) {
      Log("KAH: newgame character editor closed (step " + Int(g_chargenStep) + ")");
      g_chargenStep = 0;
      g_chargenAt = 0;
    }
    // In the world with the editor gone: the new game is running.
    if (Phase(world) == "world") {
      Log("KAH: newgame in the world");
      g_newGamePending = false;
    }
    return;
  }
  if (!g_newGameAuto)
    return;
  if (g_chargenAt == 0) {
    g_chargenAt = now;
    Log("KAH: newgame character editor open");
    return;
  }
  // PG 132/133/240 (pg-58): the editor reported open 2 s before its widgets existed; 3 tries 2 s apart
  // all missed ConfirmButton, which was there (and worked with `click`) a few seconds later. Keep trying
  // every 2 s for 2 minutes, logging the visible buttons now and then
  const int kConfirmTries = 60;
  if (g_chargenStep == 0 && now - g_chargenAt >= 2000) { // let the editor finish building
    if (g_chargenTries >= kConfirmTries) {
      if (g_chargenTries == kConfirmTries) {
        Log("KAH: newgame could not confirm the character editor after " + Int(kConfirmTries) +
            " tries; ui/click it");
        ++g_chargenTries;
      }
      return;
    }
    ++g_chargenTries;
    MyGUI::Gui *mg = MyGUI::Gui::getInstancePtr();
    MyGUI::Widget *b = nullptr;
    if (mg) {
      MyGUI::EnumeratorWidgetPtr roots = mg->getEnumerator();
      while (!b && roots.next())
        b = FindConfirmButton(roots.current(), 0);
    }
    if (!b) {
      std::string seen;
      if (mg && (g_chargenTries == 1 || g_chargenTries % 10 == 0 || g_chargenTries == kConfirmTries)) {
        int n = 0;
        MyGUI::EnumeratorWidgetPtr all = mg->getEnumerator();
        while (all.next() && n < 25)
          ListConfirmCandidates(all.current(), 0, seen, n, 25);
        seen = " visible buttons: " + (seen.empty() ? std::string("none") : seen);
      }
      Log("KAH: newgame no CONFIRM button visible (try " + Int(g_chargenTries) + ")" + seen);
      g_chargenAt = now;
      return;
    }
    Log("KAH: newgame click " + b->getName() + " '" + Caption(b) + "' (try " + Int(g_chargenTries) + ")");
    b->eventMouseButtonClick(b);
    g_chargenStep = 1;
    g_chargenAt = now;
    return;
  }
  if (g_chargenStep == 1 && now - g_chargenAt >= 1000) {
    // The "are you sure" box: hideMessageBox(true) = Enter, its accept
    // button; false when no box is open (CONFIRM may not ask).
    bool modal = false, hid = false;
    try {
      modal = MessageBoxManager::hasModalMessage();
      hid = MessageBoxManager::hideMessageBox(true);
    } catch (...) {
    }
    Log(std::string("KAH: newgame confirm box modal=") + (modal ? "1" : "0") + " accepted=" + (hid ? "1" : "0"));
    g_chargenStep = 2;
    g_chargenAt = now;
    return;
  }
  if (g_chargenStep == 2 && now - g_chargenAt >= 5000) { // still open: start over
    g_chargenStep = 0;
    g_chargenAt = now;
  }
}

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
      if (!g_protected.empty()) {
        Log("KAH: protect list cleared by the load (" + Int(g_protected.size()) + ")");
        g_protected.clear();
      }
    }
    if (signal != g_lastSignal) {
      // Import is only safe into a fresh new game (KAH 23): remember
      // whether the current world came from New Game.
      if (signal == SaveManager::NEWGAME)
        g_freshNewGame = true;
      else if (signal == SaveManager::LOADGAME || signal == SaveManager::IMPORTGAME)
        g_freshNewGame = false;
      if (signal == SaveManager::NEWGAME || signal == SaveManager::IMPORTGAME)
        Log(std::string("KAH: game signalled ") + (signal == SaveManager::NEWGAME ? "new game" : "import"));
      if (signal == SaveManager::LOADGAME || signal == SaveManager::IMPORTGAME)
        g_newGamePending = false; // a load replaces the new game
    }
    g_lastSignal = signal;
  } catch (...) {
  }
  WatchNewGame();
}

// import <save> [flags] menu (PG 132): the game's own Import dialog instead of a direct
// SaveManager::import. ImportGameMenu::importPress (1.0.65 Steam, disassembled) only reads the
// list's selected row, refuses names starting "ERROR", ORs IMPORT_SQUAD into getOptions() (the
// option checkbox at index k adds bit k) and calls SaveManager::import(games[row], flags); so
// this opens the dialog (SaveManager::showImport), sets the checkboxes and the row a frame
// later, then clicks its Import button like the player. Each step is logged.
struct ImportMenuJob {
  std::string id, save, method, options;
  int flags;  // -1 = keep the dialog's own checkboxes
  int step;   // 0 idle, 1 dialog opening, 2 row selected, 3 clicked
  DWORD at;
};
ImportMenuJob g_importMenu = {"", "", "", "", -1, 0, 0};

MyGUI::Widget *FindImportButton(MyGUI::Widget *w, ImportGameMenu *menu, bool exact, int depth) {
  if (!w || depth > 40 || !w->getInheritedVisible())
    return nullptr;
  bool isOption = false;
  for (uint32_t k = 0; k < menu->options.size(); ++k)
    if ((MyGUI::Widget *)menu->options.stuff[k] == w)
      isOption = true;
  if (!isOption && w->castType<MyGUI::Button>(false)) {
    const std::string c = Lower(Caption(w));
    if (exact ? c == "import" : c.find("import") != std::string::npos)
      return w;
  }
  for (size_t i = 0; i < w->getChildCount(); ++i) {
    MyGUI::Widget *found = FindImportButton(w->getChildAt(i), menu, exact, depth + 1);
    if (found)
      return found;
  }
  return nullptr;
}

void FinishImportMenu(bool ok, const std::string &detail) {
  Log(std::string("KAH: import menu ") + (ok ? "done: " : "failed: ") + detail);
  WriteOutbox(g_importMenu.id, ok, detail);
  g_importMenu.step = 0;
}

void ImportMenuTick() {
  if (g_importMenu.step == 0)
    return;
  const DWORD now = GetTickCount();
  SaveManager *sm = SaveManager::getSingleton();
  if (!Valid(sm)) {
    FinishImportMenu(false, "no SaveManager");
    return;
  }
  ImportGameMenu *menu = sm->importMenu;
  if (g_importMenu.step == 1) {
    if (now - g_importMenu.at < 700)
      return;
    if (!menu || !menu->list) {
      FinishImportMenu(false, "the Import dialog did not open (SaveManager::importMenu is null)");
      return;
    }
    int row = -1;
    for (uint32_t i = 0; i < menu->games.size() && row < 0; ++i)
      if (menu->games.stuff[i].name == g_importMenu.save)
        row = (int)i;
    for (uint32_t i = 0; i < menu->games.size() && row < 0; ++i)
      if (Lower(menu->games.stuff[i].name) == Lower(g_importMenu.save))
        row = (int)i;
    const size_t rows = menu->list->getItemCount();
    if (row < 0 || (size_t)row >= rows) {
      FinishImportMenu(false, "save " + g_importMenu.save + " is not in the Import dialog (" +
                                  Int(menu->games.size()) + " saves, " + Int((long long)rows) + " rows)");
      return;
    }
    std::string opts;
    int covered = 0;
    for (uint32_t k = 0; k < menu->options.size(); ++k) {
      MyGUI::Button *b = menu->options.stuff[k];
      if (!b)
        continue;
      covered |= (int)k;
      if (g_importMenu.flags >= 0)
        b->setStateSelected((g_importMenu.flags & (int)k) != 0);
      opts += (opts.empty() ? "" : ",") + ImportFlagNames((int)k) + "=" + (b->getStateSelected() ? "1" : "0");
    }
    g_importMenu.options = opts.empty() ? std::string("none") : opts;
    std::string missing;
    if (g_importMenu.flags >= 0 && (g_importMenu.flags & ~covered & ~0x2))
      missing = " no_checkbox_for=" + ImportFlagNames(g_importMenu.flags & ~covered & ~0x2);
    menu->list->setIndexSelected((size_t)row);
    Log("KAH: import menu step 2: row " + Int(row) + "/" + Int((long long)rows) + " = " +
        menu->games.stuff[row].name + " options " + g_importMenu.options + missing);
    g_importMenu.options += missing;
    g_importMenu.step = 2;
    g_importMenu.at = now;
    return;
  }
  if (g_importMenu.step == 2) {
    if (now - g_importMenu.at < 500)
      return;
    if (!menu || !menu->list) {
      FinishImportMenu(false, "the Import dialog closed before the click");
      return;
    }
    const size_t sel = menu->list->getIndexSelected();
    if (sel >= menu->games.size() || Lower(menu->games.stuff[sel].name) != Lower(g_importMenu.save)) {
      FinishImportMenu(false, "the dialog's selected row is not " + g_importMenu.save + " (row " +
                                  Int((long long)sel) + ")");
      return;
    }
    MyGUI::Widget *b = FindImportButton(menu->mMainWidget, menu, true, 0);
    if (!b)
      b = FindImportButton(menu->mMainWidget, menu, false, 0);
    if (b) {
      g_importMenu.method = "button " + b->getName() + " '" + OneLine(Caption(b)) + "'";
      Log("KAH: import menu step 3: click " + g_importMenu.method);
      b->eventMouseButtonClick(b);
    } else {
      g_importMenu.method = "importPress (no Import button found)";
      Log("KAH: import menu step 3: no Import button visible, calling ImportGameMenu::importPress");
      menu->importPress(nullptr);
    }
    g_importMenu.step = 3;
    g_importMenu.at = now;
    return;
  }
  if (g_importMenu.step == 3) {
    const int signal = sm->signal;
    if (signal == SaveManager::IMPORTGAME || g_lastSignal == SaveManager::IMPORTGAME) {
      g_freshNewGame = false;
      g_loadedSave = "import:" + g_importMenu.save;
      g_loadPending = true;
      g_loadSawEmpty = false;
      g_loadStarted = now;
      g_loadOldLeader = FirstPlayerCharacter(ou);
      FinishImportMenu(true, "importing " + g_importMenu.save + " via the game's Import dialog (" +
                                 g_importMenu.method + "; options " + g_importMenu.options +
                                 "; the game always adds squad); wait-world, then status");
    } else if (now - g_importMenu.at > 3000) {
      FinishImportMenu(false, "the dialog's Import did nothing within 3 s (signal=" + Int(signal) + ", " +
                                  g_importMenu.method + ")");
    }
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
  if (g_newGamePending && CharEditorOpen(world))
    return "chargen";
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


// teleport: did he land? Flat distance to the target, 10 m tolerance (buildings push him out).
float TeleportOff(Character *c, const Ogre::Vector3 &to) {
  Ogre::Vector3 d = c->getPosition() - to;
  d.y = 0;
  return d.length();
}

// Character::teleport sometimes leaves him where he was (m19-4080: Avarek in the Full-Base save, after some game
// time at the base, never moved again by teleport, paused or not). Then the movement controller's own
// set-position-and-teleport is tried. Returns the method that landed (or "none").
std::string TeleportRobust(GameWorld *world, Character *c, const Ogre::Vector3 &to) {
  c->teleport(to, Ogre::Quaternion::IDENTITY);
  if (TeleportOff(c, to) < 10.0f)
    return "teleport";
  // Lying in a bed (or using any furniture) pins him there even when inSomething says IN_NOTHING
  // (m19-4080: Avarek in the Full-Base Bed): leave it the game's way, then teleport again.
  std::string left;
  try {
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, c->getPosition(), 3.0f, BUILDING, 16, nullptr);
    for (uint32_t i = 0; i < nearby.size(); ++i) {
      UseableStuff *u = dynamic_cast<UseableStuff *>(nearby.stuff[i]);
      if (!Valid(u) || !(u->getOccupant() == c->getHandle() || u->getPosition().distance(c->getPosition()) < 1.5f))
        continue;
      u->stopOperating(c->getHandle());
      c->setBedMode(false, u);
      left = u->getName();
    }
  } catch (...) {
  }
  if (!left.empty()) {
    c->teleport(to, Ogre::Quaternion::IDENTITY);
    if (TeleportOff(c, to) < 10.0f)
      return "left " + left + " + teleport";
  }
  CharMovement *m = c->movement;
  if (Valid(m)) {
    try {
      m->_setPositionDirectionAndTeleport(to, Ogre::Quaternion::IDENTITY);
    } catch (...) {
    }
    if (TeleportOff(c, to) < 10.0f)
      return "movement";
    try {
      m->_setPositionSimple(to);
    } catch (...) {
    }
    if (TeleportOff(c, to) < 10.0f)
      return "position";
  }
  return "none";
}

std::string TeleportMoved(Character *c, const Ogre::Vector3 &to, const std::string &method) {
  const float off = TeleportOff(c, to);
  return std::string(" moved=") + (off < 10.0f ? "1" : "0") + " off_target=" + Num(off) + " method=" + method;
}

// ---- sync_flash: video sync marker (animlab T6, 2026-10-10) -----------------------------------------------
// A take's labels file is written by the script's clock, the video by ffmpeg: the burned labels led the screen by
// 0.4-1.3 s, not constant (turret-fp). sync_flash covers the whole game view with one flat magenta panel (top layer,
// no mouse/key focus) for >= ms AND >= 2 rendered frames, then hides it; take-sample.sh's take_mark sends it with every
// label and frames.py syncmarks finds the flashes in the video, so takecheck can measure each label's real lag.
MyGUI::Widget *g_syncFlash = nullptr;
DWORD g_syncFlashOn = 0;
unsigned g_syncFlashMs = 0;
int g_syncFlashFrames = -1; // frames rendered since shown; -1 = hidden
int g_syncFlashN = 0;
bool g_syncFlashHooked = false;

void SyncFlashFrame(float) {
  if (g_syncFlashFrames < 0 || !g_syncFlash)
    return;
  ++g_syncFlashFrames;
  if (g_syncFlashFrames >= 3 && GetTickCount() - g_syncFlashOn >= g_syncFlashMs) {
    try {
      g_syncFlash->setVisible(false);
    } catch (...) {
    }
    Log("KAH: sync flash n=" + Int(g_syncFlashN) + " off after " + Int(GetTickCount() - g_syncFlashOn) + " ms " +
        Int(g_syncFlashFrames - 1) + " frames");
    g_syncFlashFrames = -1;
  }
}

// ---- stamp: frame-exact video sync code (frame-stamp, 2026-10-10) -----------------------------------------------
// Flash sync matched to a sampled event log lagged under PC load (tur-b-2, e6r7: label lag + sampler gaps while the
// game ran fine). `stamp on` draws a black/white cell grid in the top-left corner of the view EVERY rendered frame:
// render-frame counter + last sync mark + a 48-bit mod payload (KenshiFP: FP state, stroke, view, weapon class,
// table hash; exported KAH_StampSet), layout in FrameStamp.h. tools/animlab/stamp.py reads it from every
// video frame (video frame -> game frame, state; dropped/duplicated frames exact). While the stamp is on, sync_flash
// sets the mark (no magenta flash unless `stamp on .. flash`). Off by default; nothing is drawn or hooked until used.
//   stamp on [cell px 4..32, default 8] [flash] [log <file>]   log = <HarnessDir>\<file>: one line per payload/mark
//                                                               change `<fc>\t<epoch>\t<lo hex>\t<hi hex>\t<mark>\t<flags>`
//   stamp off | status
double EpochNow();
std::string EpochStr(double t);
struct StampState {
  bool on, hooked, flash;
  int cell;
  unsigned fc, mark, lo, hi, setsSince, frames, sets, syncPaints;
  bool paintedOnSet;
  DWORD thread;
  MyGUI::Widget *back;
  MyGUI::Widget *cells[FrameStamp::ROWS * FrameStamp::COLS];
  unsigned char shown[FrameStamp::ROWS * FrameStamp::COLS];
  std::string logPath, logBuf;
  unsigned lastLo, lastHi, lastMark;
  bool logged;
  CRITICAL_SECTION lock;
  StampState()
      : on(false), hooked(false), flash(false), cell(8), fc(0), mark(0), lo(0), hi(0), setsSince(0), frames(0),
        sets(0), syncPaints(0), paintedOnSet(false), thread(0), back(nullptr), lastLo(0), lastHi(0), lastMark(0),
        logged(false) {
    InitializeCriticalSection(&lock);
    for (int i = 0; i < FrameStamp::ROWS * FrameStamp::COLS; ++i) {
      cells[i] = nullptr;
      shown[i] = 2;
    }
  }
};
StampState g_stamp;

void StampFlushLog() {
  if (g_stamp.logPath.empty() || g_stamp.logBuf.empty())
    return;
  std::ofstream f(g_stamp.logPath.c_str(), std::ios::app | std::ios::binary);
  f << g_stamp.logBuf;
  g_stamp.logBuf.clear();
}

void StampPaint(unsigned flags) {
  if (!g_stamp.on || !g_stamp.back)
    return;
  unsigned char bits[FrameStamp::BITS];
  EnterCriticalSection(&g_stamp.lock);
  const unsigned lo = g_stamp.lo, hi = g_stamp.hi;
  LeaveCriticalSection(&g_stamp.lock);
  FrameStamp::Encode(g_stamp.fc, g_stamp.mark, flags, lo, hi, bits);
  try {
    for (int r = 0; r < FrameStamp::ROWS; ++r)
      for (int c = 0; c < FrameStamp::COLS; ++c) {
        const int i = r * FrameStamp::COLS + c;
        const unsigned char v = r == 0 ? (unsigned char)((c & 1) == 0) : bits[i - FrameStamp::COLS];
        if (g_stamp.shown[i] != v && g_stamp.cells[i]) {
          const float x = v ? 1.0f : 0.0f;
          g_stamp.cells[i]->setColour(MyGUI::Colour(x, x, x));
          g_stamp.shown[i] = v;
        }
      }
  } catch (...) {
  }
  if (!g_stamp.logPath.empty() &&
      (!g_stamp.logged || lo != g_stamp.lastLo || hi != g_stamp.lastHi || g_stamp.mark != g_stamp.lastMark)) {
    char b[160];
    sprintf_s(b, sizeof b, "%u\t%.3f\t%08x\t%04x\t%u\t%u\n", g_stamp.fc, EpochNow(), lo, hi & 0xffff,
              g_stamp.mark, flags);
    g_stamp.logBuf += b;
    g_stamp.lastLo = lo;
    g_stamp.lastHi = hi;
    g_stamp.lastMark = g_stamp.mark;
    g_stamp.logged = true;
  }
}

void StampFrame(float) {
  if (!g_stamp.on)
    return;
  g_stamp.thread = GetCurrentThreadId();
  ++g_stamp.fc;
  ++g_stamp.frames;
  const unsigned fresh = g_stamp.setsSince > 0 ? 1u : 0u;
  g_stamp.setsSince = 0;
  g_stamp.paintedOnSet = false;
  StampPaint(fresh);
  if ((g_stamp.frames & 31) == 0)
    StampFlushLog();
}

// Exported for mods (KAH_Api.stampOn / stampSet): the mod sets its payload every frame right after it poses the
// view; on the render thread the cells are repainted at once (this frame shows this payload), else at frame start.
extern "C" __declspec(dllexport) int KAH_StampOn() { return g_stamp.on ? 1 : 0; }
extern "C" __declspec(dllexport) void KAH_StampSet(unsigned lo, unsigned hi) {
  if (!g_stamp.on)
    return;
  EnterCriticalSection(&g_stamp.lock);
  g_stamp.lo = lo;
  g_stamp.hi = hi & 0xffff;
  LeaveCriticalSection(&g_stamp.lock);
  ++g_stamp.sets;
  ++g_stamp.setsSince;
  if (g_stamp.thread && GetCurrentThreadId() == g_stamp.thread) {
    StampPaint(3);
    ++g_stamp.syncPaints;
    g_stamp.paintedOnSet = true;
  }
}

std::string StampStatus() {
  return std::string("stamp ") + (g_stamp.on ? "on" : "off") + " cell=" + Int(g_stamp.cell) + " fc=" +
         Int(g_stamp.fc) + " frames=" + Int(g_stamp.frames) + " sets=" + Int(g_stamp.sets) + " sync_paints=" +
         Int(g_stamp.syncPaints) + " mark=" + Int(g_stamp.mark) + " flash=" + (g_stamp.flash ? "1" : "0") +
         " log=" + (g_stamp.logPath.empty() ? std::string("none") : g_stamp.logPath) + " epoch=" +
         EpochStr(EpochNow());
}

std::string Stamp(const std::vector<std::string> &f, bool &ok) {
  const std::string sub = f.size() > 2 ? Lower(f[2]) : "status";
  if (sub == "status") {
    ok = true;
    return StampStatus();
  }
  if (sub == "off") {
    g_stamp.on = false;
    try {
      if (g_stamp.back)
        g_stamp.back->setVisible(false);
    } catch (...) {
    }
    StampFlushLog();
    ok = true;
    Log("KAH: stamp off frames=" + Int(g_stamp.frames) + " sets=" + Int(g_stamp.sets));
    return StampStatus();
  }
  if (sub != "on")
    return "usage: stamp on [cell px 4..32, default 8] [flash] [log <file>] | stamp off | stamp status";
  int cell = 8;
  bool flash = false;
  std::string logName;
  for (size_t i = 3; i < f.size(); ++i) {
    const std::string a = Lower(f[i]);
    if (a == "flash")
      flash = true;
    else if (a == "log" && i + 1 < f.size())
      logName = f[++i];
    else if (atoi(a.c_str()) >= 4 && atoi(a.c_str()) <= 32)
      cell = atoi(a.c_str());
    else
      return "usage: stamp on [cell px 4..32, default 8] [flash] [log <file>]";
  }
  if (!logName.empty() && logName.find_first_of("\\/:") != std::string::npos)
    return "stamp: log <file> is a plain name (written in the harness folder)";
  MyGUI::Gui *g = MyGUI::Gui::getInstancePtr();
  if (!g)
    return "no MyGUI";
  try {
    const int C = cell, W = (FrameStamp::COLS + 2) * C, H = (FrameStamp::ROWS + 2) * C;
    if (g_stamp.back && g_stamp.cell != cell) {
      g->destroyWidget(g_stamp.back); // children go with it
      g_stamp.back = nullptr;
    }
    if (!g_stamp.back) {
      const char *layer = MyGUI::LayerManager::getInstance().isExist("Top") ? "Top" : "Popup";
      g_stamp.back = g->createWidgetT("Widget", "WhiteSkin", MyGUI::IntCoord(0, 0, W, H), MyGUI::Align::Default,
                                      layer, "KAH_Stamp");
      g_stamp.back->setNeedMouseFocus(false);
      g_stamp.back->setNeedKeyFocus(false);
      g_stamp.back->setColour(MyGUI::Colour(0.0f, 0.0f, 0.0f));
      g_stamp.back->setAlpha(1.0f);
      for (int r = 0; r < FrameStamp::ROWS; ++r)
        for (int c = 0; c < FrameStamp::COLS; ++c) {
          const int i = r * FrameStamp::COLS + c;
          MyGUI::Widget *w = g_stamp.back->createWidgetT("Widget", "WhiteSkin",
                                                         MyGUI::IntCoord((c + 1) * C, (r + 1) * C, C, C),
                                                         MyGUI::Align::Default);
          w->setNeedMouseFocus(false);
          w->setNeedKeyFocus(false);
          w->setColour(MyGUI::Colour(0.0f, 0.0f, 0.0f));
          w->setAlpha(1.0f);
          g_stamp.cells[i] = w;
          g_stamp.shown[i] = 0;
        }
    }
    if (!g_stamp.hooked) {
      g->eventFrameStart += MyGUI::newDelegate(&StampFrame);
      g_stamp.hooked = true;
    }
    g_stamp.cell = cell;
    g_stamp.flash = flash;
    g_stamp.back->setCoord(0, 0, W, H);
    g_stamp.back->setVisible(true);
    MyGUI::LayerManager::getInstance().upLayerItem(g_stamp.back);
    StampFlushLog();
    g_stamp.logPath = logName.empty() ? std::string() : HarnessDir() + "\\" + logName;
    if (!g_stamp.logPath.empty())
      DeleteFileA(g_stamp.logPath.c_str());
    g_stamp.logged = false;
    g_stamp.mark = 0;
    g_stamp.frames = 0;
    g_stamp.sets = 0;
    g_stamp.syncPaints = 0;
    g_stamp.on = true;
    StampPaint(0);
    Log("KAH: stamp on cell=" + Int(cell) + " flash=" + Int(flash ? 1 : 0) + " log=" + g_stamp.logPath);
    ok = true;
    return StampStatus();
  } catch (...) {
    return "stamp failed (MyGUI exception)";
  }
}

std::string SyncFlash(const std::vector<std::string> &f, bool &ok) {
  const int ms = f.size() >= 3 ? atoi(f[2].c_str()) : 150;
  const int n = f.size() >= 4 ? atoi(f[3].c_str()) : 0;
  if (ms < 30 || ms > 2000)
    return "usage: sync_flash [ms 30..2000, default 150] [n]";
  if (g_stamp.on) { // the stamp carries the mark, exact to the frame; the full-view flash only with `stamp on .. flash`
    // No paint here: commands run after this frame's render, so a mark painted now first shows on frame fc+1 while the
    // log said fc (proof 60-stamp-proof-1010-2231: every mark one frame late vs the log). The next StampFrame paints
    // and logs it at the frame that really shows it.
    g_stamp.mark = (unsigned)n & 0xff;
    Log("KAH: sync mark n=" + Int(n) + " stamp fc=" + Int(g_stamp.fc + 1));
    if (!g_stamp.flash) {
      ok = true;
      return "sync_flash n=" + Int(n) + " stamp mark fc=" + Int(g_stamp.fc + 1);
    }
  }
  MyGUI::Gui *g = MyGUI::Gui::getInstancePtr();
  if (!g)
    return "no MyGUI";
  try {
    const MyGUI::IntSize vs = MyGUI::RenderManager::getInstance().getViewSize();
    if (!g_syncFlash) {
      const char *layer = MyGUI::LayerManager::getInstance().isExist("Top") ? "Top" : "Popup";
      g_syncFlash = g->createWidgetT("Widget", "WhiteSkin", MyGUI::IntCoord(0, 0, vs.width, vs.height),
                                     MyGUI::Align::Default, layer, "KAH_SyncFlash");
      g_syncFlash->setNeedMouseFocus(false);
      g_syncFlash->setNeedKeyFocus(false);
      g_syncFlash->setColour(MyGUI::Colour(1.0f, 0.0f, 1.0f));
      g_syncFlash->setAlpha(1.0f);
    }
    if (!g_syncFlashHooked) {
      g->eventFrameStart += MyGUI::newDelegate(&SyncFlashFrame);
      g_syncFlashHooked = true;
    }
    g_syncFlash->setCoord(0, 0, vs.width, vs.height);
    g_syncFlash->setVisible(true);
    MyGUI::LayerManager::getInstance().upLayerItem(g_syncFlash);
    g_syncFlashOn = GetTickCount();
    g_syncFlashMs = (unsigned)ms;
    g_syncFlashFrames = 0;
    g_syncFlashN = n;
    Log("KAH: sync flash n=" + Int(n) + " on ms=" + Int(ms) + " view=" + Int(vs.width) + "x" + Int(vs.height));
    ok = true;
    return "sync_flash n=" + Int(n) + " ms=" + Int(ms) + " view=" + Int(vs.width) + "x" + Int(vs.height);
  } catch (...) {
    return "sync_flash failed (MyGUI exception)";
  }
}

// ---- sampler: game-thread evidence sampler for video takes (take_sample.py, 2026-10-10) ------------------------
// take_sample.py polled 5 queries through the inbox every 0.6 s from WSL; at WSL load 23-60 its reads came 1.0-1.7 s
// apart while the game ran smoothly (op-blkK: vmrec dense, ev gaps), so takecheck's cover rule failed takes for the
// sampler's lateness. Here the harness runs the queries itself on the game thread every <ms> and appends
// `<epoch s>\t<query index>\t<reply>` lines to <HarnessDir>\<file>: a gap in the file is a real game stall.
// sampler start <ms 50..5000> <file> <query>...   (one tab field per query, e.g. "fp_keys state", "where Axima")
// sampler stop | status                           (status/stop reply epoch=<harness clock> for the client's offset)
struct TakeSampler {
  bool on;
  DWORD everyMs, last;
  std::string path;
  std::vector<std::vector<std::string> > queries;
  int ticks;
  TakeSampler() : on(false), everyMs(300), last(0), ticks(0) {}
};
TakeSampler g_sampler;

double EpochNow() {
  FILETIME ft;
  GetSystemTimeAsFileTime(&ft);
  ULARGE_INTEGER u;
  u.LowPart = ft.dwLowDateTime;
  u.HighPart = ft.dwHighDateTime;
  return (double)(u.QuadPart - 116444736000000000ULL) / 1e7;
}

std::string EpochStr(double t) {
  char b[64];
  sprintf_s(b, sizeof b, "%.3f", t);
  return b;
}

void SamplerTick(GameWorld *world) {
  if (!g_sampler.on)
    return;
  DWORD now = GetTickCount();
  if (g_sampler.ticks > 0 && now - g_sampler.last < g_sampler.everyMs)
    return;
  g_sampler.last = now;
  const std::string t = EpochStr(EpochNow());
  std::string out;
  for (size_t i = 0; i < g_sampler.queries.size(); ++i) {
    std::vector<std::string> f;
    f.push_back("smp");
    for (size_t j = 0; j < g_sampler.queries[i].size(); ++j)
      f.push_back(g_sampler.queries[i][j]);
    bool ok = false, pending = false;
    std::string r;
    try {
      r = RunCommand(world, f, ok, pending);
    } catch (...) {
      r = "exception";
    }
    if (pending)
      r = "pending";
    for (size_t k = 0; k < r.size(); ++k)
      if (r[k] == '\n' || r[k] == '\r' || r[k] == '\t')
        r[k] = ' ';
    out += t + "\t" + Int((long long)i) + "\t" + r + "\n";
  }
  std::ofstream f(g_sampler.path.c_str(), std::ios::app | std::ios::binary);
  f << out;
  ++g_sampler.ticks;
}

std::string Sampler(const std::vector<std::string> &f, bool &ok) {
  const std::string sub = f.size() > 2 ? Lower(f[2]) : "status";
  if (sub == "stop" || sub == "status") {
    if (sub == "stop")
      g_sampler.on = false;
    ok = true;
    return std::string("sampler ") + (g_sampler.on ? "on" : "off") + " samples=" + Int(g_sampler.ticks) +
           " epoch=" + EpochStr(EpochNow()) + " file=" + g_sampler.path;
  }
  if (sub != "start" || f.size() < 6)
    return "usage: sampler start <ms 50..5000> <file> <query>... | sampler stop | sampler status";
  int ms = atoi(f[3].c_str());
  const std::string name = f[4];
  if (ms < 50 || ms > 5000 || name.empty() || name.find_first_of("\\/:") != std::string::npos)
    return "usage: sampler start <ms 50..5000> <file (plain name, in the harness folder)> <query>...";
  g_sampler.queries.clear();
  for (size_t i = 5; i < f.size(); ++i) {
    std::vector<std::string> q;
    std::string w;
    for (size_t k = 0; k <= f[i].size(); ++k) {
      if (k == f[i].size() || f[i][k] == ' ') {
        if (!w.empty())
          q.push_back(w);
        w.clear();
      } else {
        w += f[i][k];
      }
    }
    if (!q.empty()) {
      if (Lower(q[0]) == "sampler")
        return "sampler: a query may not be sampler";
      g_sampler.queries.push_back(q); // SamplerTick prepends a dummy f[0]: RunCommand reads the command from f[1]
    }
  }
  g_sampler.path = HarnessDir() + "\\" + name;
  DeleteFileA(g_sampler.path.c_str());
  g_sampler.everyMs = (DWORD)ms;
  g_sampler.ticks = 0;
  g_sampler.last = 0;
  g_sampler.on = true;
  ok = true;
  return "sampler on ms=" + Int(ms) + " queries=" + Int((long long)g_sampler.queries.size()) + " epoch=" +
         EpochStr(EpochNow()) + " file=" + g_sampler.path;
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

  if (cmd == "sync_flash") // sync_flash [ms] [n]: full-view magenta marker for video sync (any phase)
    return SyncFlash(f, ok);
  if (cmd == "stamp") // stamp on [cell] [flash] [log <file>] | off | status: per-frame sync code (any phase)
    return Stamp(f, ok);
  if (cmd == "sampler") // sampler start <ms> <file> <query>... | stop | status (game-thread take sampler, any phase)
    return Sampler(f, ok);

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
    // b31/b32-4080: a load issued while the game was still loading (streaming a far zone after a character was
    // flung 80 km) crashed Kenshi at exe+0x37f665 both times. Refuse; the caller waits for phase=world first.
    {
      bool busy = false;
      try {
        busy = Valid(world) && world->isLoadingFromASaveGame();
      } catch (...) {
      }
      if (busy) {
        Log("KAH: load save=" + f[2] + " refused: the game is still loading");
        return "busy: the game is still loading (wait-world, then load again)";
      }
    }
    Log("KAH: load save=" + f[2] + " phase=" + Phase(world));
    sm->load(f[2]);
    g_freshNewGame = false;
    g_newGamePending = false;
    g_loadedSave = f[2];
    g_loadPending = true;
    g_loadSawEmpty = false;
    g_loadStarted = GetTickCount();
    g_loadOldLeader = FirstPlayerCharacter(world);
    ok = true;
    return "loading " + f[2];
  }

  if (cmd == "newgame") { // newgame <start name|sid>: the game's New Game with that start (KAH 21)
    if (f.size() < 3 || f[2].empty())
      return "usage: newgame <start name|sid> [edit] (find start <text> lists starts)";
    if (!Valid(world))
      return "the game is not ready yet (phase=starting)";
    SaveManager *sm = SaveManager::getSingleton();
    if (!Valid(sm))
      return "no SaveManager";
    // Names as "find start" prints them ("Wanderer"), with or without a
    // leading "The" ("The Wanderer"), any case, or the sid (KAH 23).
    std::string error;
    GameData *start = FindData(world, NEW_GAME_STARTOFF, f[2], error);
    if (!start) {
      std::string alt, altError;
      const std::string low = Lower(f[2]);
      alt = low.compare(0, 4, "the ") == 0 ? f[2].substr(4) : "The " + f[2];
      start = FindData(world, NEW_GAME_STARTOFF, alt, altError);
      if (!start)
        return error + " (also tried '" + alt + "'; find start <text> lists the starts)";
    }
    const bool edit = f.size() >= 4 && Lower(f[3]) == "edit";
    const int signalBefore = sm->signal;
    Log("KAH: newgame start=" + start->name + " (" + start->stringID + ") phase=" + Phase(world) +
        " signal=" + Int(signalBefore) + (edit ? " edit" : " auto-confirm"));
    sm->newGame(start->stringID);
    // SaveManager::newGame only sets signal=NEWGAME (the game acts on it a
    // frame later) and does nothing while another save/load is queued.
    if (sm->signal != SaveManager::NEWGAME && sm->signal == signalBefore)
      return "the game didn't take the new game (SaveManager busy, signal=" + Int(sm->signal) +
             "); try again in a few seconds";
    g_newGamePending = true;
    g_newGameAuto = !edit;
    g_chargenStep = 0;
    g_chargenTries = 0;
    g_chargenAt = 0;
    g_newGameLastReport = GetTickCount();
    g_freshNewGame = true;
    g_loadedSave = "newgame:" + start->name;
    g_loadPending = true;
    g_loadSawEmpty = false;
    g_loadStarted = GetTickCount();
    g_loadOldLeader = FirstPlayerCharacter(world);
    ok = true;
    return "starting a new game: " + start->name + " (" + start->stringID + "); " +
           (edit ? "the character editor stays open (phase=chargen) for ui/click; "
                 : "the harness confirms the character editor; ") +
           "wait-world, then status";
  }

  if (cmd == "import") { // import <save> [squad,buildings,research,npcs,relations,reset] [menu]: the game's Import (KAH 21)
    if (f.size() < 3 || f[2].empty())
      return "usage: import <save> [flags: squad,buildings,research,npcs,relations,reset | all] [menu]";
    SaveManager *sm = SaveManager::getSingleton();
    if (!Valid(sm))
      return "no SaveManager";
    int flags = SaveManager::IMPORT_SQUAD | SaveManager::IMPORT_BUILDINGS | SaveManager::IMPORT_RESEARCH |
                SaveManager::IMPORT_NPC_STATES | SaveManager::IMPORT_RELATIONS;
    bool viaMenu = false;
    std::string flagText;
    for (size_t k = 3; k < f.size(); ++k) {
      if (Lower(f[k]) == "menu")
        viaMenu = true;
      else if (flagText.empty())
        flagText = f[k];
      else
        return "usage: import <save> [flags: squad,buildings,research,npcs,relations,reset | all] [menu]";
    }
    if (!flagText.empty()) {
      std::string bad;
      const int parsed = ParseImportFlags(flagText, bad);
      if (parsed < 0)
        return "unknown import flag: " + bad + " (squad,buildings,research,npcs,relations,reset,all)";
      flags = parsed;
    }
    // The game offers Import only from New Game; importing into a world
    // loaded from a save crashed the game ~2 s later in town code (KAH 23,
    // kenshi_x64.exe+0x94d6db reading +0x270 of a null pointer). PG 132 (m36):
    // the same crash also follows an import into a fresh new game (0.6 s after
    // the import signal, inside GameWorld::mainLoop_GPUSensitiveStuff ->
    // ResourceLoader / Building / TownBase code, no plugin frame), so this
    // guard is not enough on its own: the cause is still open.
    if (!g_freshNewGame)
      return "refused: import works only right after a new game (newgame <start>, wait-world, then "
             "import); the current world came from a save (" +
             (g_loadedSave.empty() ? std::string("?") : g_loadedSave) + ")";
    if (Phase(world) != "world")
      return "refused: wait until the new game has started (phase=" + Phase(world) + ")";
    lektor<SaveInfo> saves;
    sm->scanGames(saves, false);
    int at = -1;
    for (uint32_t i = 0; i < saves.size() && at < 0; ++i)
      if (saves.stuff[i].name == f[2])
        at = (int)i;
    for (uint32_t i = 0; i < saves.size() && at < 0; ++i)
      if (Lower(saves.stuff[i].name) == Lower(f[2]))
        at = (int)i;
    if (at < 0)
      return "no save named: " + f[2] + " (" + Int(saves.size()) + " saves in " + sm->getSavePath() + ")";
    if (viaMenu) {
      if (g_importMenu.step != 0)
        return "refused: an import through the menu is already running";
      g_importMenu.id = f[0];
      g_importMenu.save = saves.stuff[at].name;
      g_importMenu.flags = flagText.empty() ? -1 : flags;
      g_importMenu.method.clear();
      g_importMenu.options.clear();
      Log("KAH: import menu step 1: showImport save=" + g_importMenu.save + " flags=" +
          (flagText.empty() ? std::string("dialog defaults") : ImportFlagNames(flags)) + " phase=" + Phase(world) +
          " paused=" + (world->isPaused() ? "1" : "0"));
      sm->showImport();
      g_importMenu.step = 1;
      g_importMenu.at = GetTickCount();
      pending = true; // answered by ImportMenuTick after the click
      ok = true;
      return "";
    }
    Log("KAH: import save=" + saves.stuff[at].name + " flags=" + ImportFlagNames(flags) + " phase=" +
        Phase(world));
    sm->import(saves.stuff[at], flags);
    g_freshNewGame = false; // one import per new game
    g_loadedSave = "import:" + saves.stuff[at].name;
    g_loadPending = true;
    g_loadSawEmpty = false;
    g_loadStarted = GetTickCount();
    g_loadOldLeader = FirstPlayerCharacter(world);
    ok = true;
    return "importing " + saves.stuff[at].name + " (" + ImportFlagNames(flags) +
           ") into the current game; wait-world, then status";
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

  if (cmd == "chatter") { // chatter off|on|status: mute NPC speech bubbles (video takes)
    const ChatterArg a = ChatterParse(f.size() >= 3 ? f[2] : std::string());
    if (a == CHATTER_BAD)
      return "usage: chatter off|on|status";
    if (a != CHATTER_STATUS && (a == CHATTER_OFF) != g_chatterOff) {
      g_chatterOff = a == CHATTER_OFF;
      Log(std::string("KAH: chatter ") + (g_chatterOff ? "off" : "on"));
    }
    ok = true;
    if (a == CHATTER_STATUS)
      return std::string("status: chatter=") + (g_chatterOff ? "off" : "on") + " muted=" + Int((int)g_chatterMuted);
    return std::string("chatter ") + (g_chatterOff ? "off" : "on") + " (muted " + Int((int)g_chatterMuted) +
           " bubbles so far)";
  }

  if (cmd == "speed") { // speed <0|0.5..50> [hold]: 0 pauses; hold = resume after the game's own pauses
    float v = f.size() >= 3 ? (float)atof(f[2].c_str()) : -1.0f;
    if (!(v == 0.0f || (v >= 0.5f && v <= 50.0f)))
      return "usage: speed <0|0.5..50> [hold]";
    const bool hold = v > 0.0f && f.size() >= 4 && Lower(f[3]) == "hold";
    g_holdSpeed = hold ? v : 0.0f;
    g_holdPausedAt = 0;
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
    return "speed " + Num(before) + " -> " + Num(after) + " paused=" + (paused ? "1" : "0") +
           (hold ? " hold=1 resumes_so_far=" + Int(g_holdResumes) : std::string(""));
  }

  {
    std::string reply;
    if (RunWorldCommand(world, f, origin, ok, reply))
      return reply;
    if (RunTurretCommand(world, f, origin, ok, reply))
      return reply;
    if (RunBalanceWorldCommand(world, f, origin, ok, reply))
      return reply;
  }

  if (cmd == "chars") { // chars [radius] [filter]: filter = '|'-separated case-insensitive substrings of the line
    float radius = f.size() >= 3 ? (float)atof(f[2].c_str()) : 100.0f;
    // stobe raid guard (m26): Full-Base has more than 40 characters within 1500 m, so the cap hid the raiders;
    // a filter applies before the 40 cap
    std::vector<std::string> alts;
    if (f.size() >= 4) {
      std::string flt;
      for (size_t k = 3; k < f.size(); ++k)
        flt += (k > 3 ? " " : "") + f[k];
      std::string cur;
      for (size_t k = 0; k <= flt.size(); ++k) {
        if (k == flt.size() || flt[k] == '|') {
          if (!cur.empty())
            alts.push_back(cur);
          cur.clear();
        } else
          cur += (char)tolower((unsigned char)flt[k]);
      }
    }
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
      std::string d = Describe(c, &origin);
      if (!alts.empty()) {
        std::string ld = d;
        for (size_t k = 0; k < ld.size(); ++k)
          ld[k] = (char)tolower((unsigned char)ld[k]);
        // `!text` excludes lines containing text; `!ko` / `!dead` exclude by state (rel-enslaved m33: the
        // knocked-out nearest 40 filled the cap and hid the awake guards behind them)
        bool hit = false, pos = false, drop = false;
        for (size_t k = 0; k < alts.size() && !drop; ++k) {
          if (alts[k][0] == '!') {
            std::string x = alts[k].substr(1);
            bool dead = c->isDead(), ko = !dead && c->isUnconcious();
            drop = x == "ko" ? ko : x == "dead" ? dead : (!x.empty() && ld.find(x) != std::string::npos);
          } else {
            pos = true;
            hit = hit || ld.find(alts[k]) != std::string::npos;
          }
        }
        if (drop || (pos && !hit))
          continue;
      }
      out += (n ? " | " : "") + d + " race=" + RaceName(c);
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
      return "usage: find <character|squad|item|weapon|armour|container|research|start> <text>";
    const std::string kind = Lower(f[2]);
    itemType type = kind == "squad" ? SQUAD_TEMPLATE
                    : kind == "item" ? ITEM
                    : kind == "weapon" ? WEAPON
                    : kind == "armour" ? ARMOUR
                    : kind == "container" ? CONTAINER
                    : kind == "research" ? RESEARCH
                    : kind == "start" ? NEW_GAME_STARTOFF
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
             "[target <npc>] [race <substr>|!<substr>...]";
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
          return NotFound(targetName);
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
    // "race <a|b|!c>" (PG 199): the template rolls a random race; a spawned character whose race
    // doesn't pass the filter is destroyed and rolled again, up to 20 tries per character
    const std::string raceSpec = Option(f, 4, "race", "");
    const RaceFilter raceFilter = ParseRaceFilter(raceSpec);
    const int kRaceTries = 20;
    int made = 0, rerolls = 0;
    bool raceFailed = false;
    std::string names, rejected;
    for (int i = 0; i < count && !raceFailed; ++i) {
      Ogre::Vector3 at = pos;
      at.z += 2.0f * i;
      Character *c = nullptr;
      std::string race;
      for (int tries = 1;; ++tries) {
        RootObject *obj = world->theFactory->createRandomCharacter(faction, at, nullptr,
                                                                   charData, nullptr, -1.0f);
        c = dynamic_cast<Character *>(obj);
        if (!Valid(c))
          break;
        race = RaceName(c);
        if (RaceFilterMatches(raceFilter, race))
          break;
        if (rejected.find("," + race + ",") == std::string::npos)
          rejected += (rejected.empty() ? "," : "") + race + ",";
        world->destroy(c, false, "KAH spawn race reroll");
        c = nullptr;
        if (tries >= kRaceTries) {
          raceFailed = true;
          break;
        }
        ++rerolls;
      }
      if (!Valid(c))
        break;
      ++made;
      names += (made > 1 ? ", " : "") + c->getName() + " " +
               FormatCharacterRef(c->getHandle().serial, c->getHandle().index) + " race=" + race;
    }
    std::string extra;
    if (!raceFilter.empty())
      extra += " rerolls=" + Int(rerolls);
    if (raceFailed)
      extra += " race-failed: no race matching '" + raceSpec + "' in " + Int(kRaceTries) +
               " tries (rolled " + rejected.substr(1, rejected.empty() ? 0 : rejected.size() - 2) + ")";
    Log("KAH: spawn character=" + charData->name + " faction=" + faction->getName() +
        " made=" + Int(made) + " " + names + extra);
    ok = made > 0 && !raceFailed;
    return "spawned " + Int(made) + "/" + Int(count) + " " + charData->name + ": " + names + extra;
  }

  if (cmd == "benches") { // benches [radius] [crafts] [near <npc|x y z>]: crafting benches, their queue and inventory
    float radius = 0;
    std::string radiusError;
    if (!ParseSearchRadius(f, 2, 2, kDefaultSearchRadius, radius, radiusError))
      return radiusError;
    // near <npc>: search around that character, not the first squad member (m24-4080 pg-56: at speed 50 the
    // squad leader walked off and "benches 60" found no bench while the smith was still crafting)
    Ogre::Vector3 center = origin;
    for (size_t i = 2; i < f.size(); ++i)
      if (Lower(f[i]) == "near" && !ResolvePosition(world, f, i + 1, center, radiusError))
        return radiusError;
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, center, radius, BUILDING, 512, nullptr);
    std::string out;
    int n = 0;
    for (uint32_t i = 0; i < nearby.size() && n < 30; ++i) {
      CraftingBuilding *b = dynamic_cast<CraftingBuilding *>(nearby.stuff[i]);
      if (!Valid(b))
        continue;
      ++n;
      out += " || " + b->getName() + " dist=" + Num(b->getPosition().distance(center)) +
             " queue=" + Int((long long)b->crafting.size());
      if (!b->crafting.empty())
        out += " (first: " + b->crafting.front().name + " " +
               Fine(b->crafting.front().progress01 * 100.0f) + "%)";
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
      return "usage: research <research name> | research start|stop <name> | research status "
             "(find research <text> lists names)";
    Research *tech = Tech(world);
    if (!tech)
      return "no player research";
    const std::string sub = Lower(f[2]);
    if (sub == "status") { // queue with progress, rate, researchers, benches (KAH 14)
      ok = true;
      return ResearchStatus(world, tech, origin);
    }
    if (sub == "start" && f.size() >= 4 && Lower(f[3]) == "any") {
      // research start any [n]: queue up to n (default 1) startable techs, longest research time first,
      // so a balance window measures one tech instead of hand-picked names that are done/unpayable per save.
      const int want = f.size() >= 5 ? (std::max)(1, atoi(f[4].c_str())) : 1;
      std::vector<std::pair<float, GameData *> > cands;
      std::set<GameData *> seen;
      const int desk = tech->getResearchDeskLevel();
      const lektor<std::string> &cats = tech->getCategories();
      int rejDone = 0, rejQueued = 0, rejReq = 0, rejBench = 0, rejCost = 0, rejErr = 0;
      for (uint32_t ci = 0; ci < cats.size(); ++ci) {
        lektor<GameData *> avail;
        try {
          tech->getAvailableResearch(avail, cats.stuff[ci]);
        } catch (...) {
          continue;
        }
        for (uint32_t i = 0; i < avail.size(); ++i) {
          GameData *d = avail.stuff[i];
          if (!Valid(d) || seen.count(d))
            continue;
          seen.insert(d);
          try {
            // count why techs are skipped, so "candidates=0" names the cause (m23-4080: pg54 had 0, no reason)
            if (tech->isFinished(d)) { ++rejDone; continue; }
            if (tech->isInQueue(d)) { ++rejQueued; continue; }
            if (!tech->checkRequirements(d, false, false)) { ++rejReq; continue; }
            if (tech->needsATechBench(d) > desk) { ++rejBench; continue; }
            if (!tech->canPayCosts(d)) { ++rejCost; continue; }
          } catch (...) {
            ++rejErr;
            continue;
          }
          float t = 0.0f;
          if (d->fdata.find("time") != d->fdata.end())
            t = d->fdata["time"];
          else if (d->idata.find("time") != d->idata.end())
            t = (float)d->idata["time"];
          cands.push_back(std::make_pair(t, d));
        }
      }
      std::sort(cands.begin(), cands.end(),
                [](const std::pair<float, GameData *> &a, const std::pair<float, GameData *> &b) {
                  return a.first > b.first;
                });
      std::string out = "candidates=" + Int((long long)cands.size()) + " skipped(done=" + Int(rejDone) +
                        " queued=" + Int(rejQueued) + " reqs=" + Int(rejReq) + " bench=" + Int(rejBench) +
                        " cost=" + Int(rejCost) + " err=" + Int(rejErr) + ")";
      int started = 0;
      for (size_t i = 0; i < cands.size() && started < want; ++i) {
        bool okOne = false;
        try {
          okOne = tech->startResearch(cands[i].second) && tech->isInQueue(cands[i].second);
        } catch (...) {
        }
        out += " [" + cands[i].second->name + " time=" + Num(cands[i].first) + (okOne ? " queued" : " refused") + "]";
        if (okOne)
          ++started;
      }
      ok = started > 0;
      Log("KAH: research start any started=" + Int(started) + " " + out);
      return "started=" + Int(started) + " " + out + " | " + ResearchStatus(world, tech, origin);
    }
    if ((sub == "start" || sub == "stop") && f.size() >= 4) { // real research at a bench (KAH 14)
      std::string error;
      GameData *d = FindData(world, RESEARCH, f[3], error);
      if (!d)
        return error;
      if (sub == "stop") {
        const bool queued = tech->isInQueue(d);
        tech->stopResearch(d);
        ok = queued && !tech->isInQueue(d);
        Log("KAH: research stop " + d->name + " ok=" + (ok ? "1" : "0"));
        return d->name + (queued ? (ok ? ": stopped" : ": still queued") : ": was not queued") + " | " +
               ResearchStatus(world, tech, origin);
      }
      if (tech->isFinished(d))
        return d->name + " is already finished";
      bool started = tech->isInQueue(d);
      // startResearch throws on some techs whose requirements are missing or that can't be paid
      // (m21-4080: "exception" for Crossbow Bolts / Hydroponics / Advanced Cooking): only call it when both hold.
      if (!started && tech->checkRequirements(d, false, false) && tech->canPayCosts(d))
        started = tech->startResearch(d);
      ok = started && tech->isInQueue(d);
      std::string why;
      if (!ok) {
        why = " requirements=" + std::string(tech->checkRequirements(d, false, false) ? "ok" : "missing") +
              " can_pay=" + (tech->canPayCosts(d) ? "1" : "0") +
              " paid=" + (tech->hasPaidFor(d) ? "1" : "0") +
              " needs_bench_level=" + Int(tech->needsATechBench(d)) +
              " desk_level=" + Int(tech->getResearchDeskLevel()) +
              " (give the cost items to the bench or squad, build a research bench of that level)";
      }
      Log("KAH: research start " + d->name + " ok=" + (ok ? "1" : "0") + why);
      return d->name + (ok ? ": queued, in progress" : ": NOT started") + why + " | " +
             ResearchStatus(world, tech, origin);
    }
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
    const itemType types[] = {WEAPON, ARMOUR, ITEM, CONTAINER, ARTIFACTS};
    for (int t = 0; t < 5 && !data; ++t)
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
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, ARTIFACTS};
    for (int t = 0; t < 5 && !data; ++t)
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
    return NotFound(f[2]);
  if (cmd == "stealth") { // stealth <npc> on|off: sneak mode (KAH 22)
    const std::string mode = f.size() >= 4 ? Lower(f[3]) : "";
    if (mode != "on" && mode != "off")
      return "usage: stealth <npc> on|off";
    c->setStealthMode(mode == "on");
    ok = c->isStealthMode() == (mode == "on");
    Log("KAH: stealth " + c->getName() + " " + mode);
    return c->getName() + " stealth_mode=" + (c->isStealthMode() ? "1" : "0");
  }

  if (cmd == "crime" && f.size() >= 4 && Lower(f[3]) == "commit") {
    // crime <npc> commit <crime> against <owner npc> [witnessed]: KAH 23. Puts him in the game's own
    // "committing a crime" state against the owner's faction (BountyManager::setCrime), so the owner and his
    // faction react through their own AI (theft: HUNT_MY_THIEF); `witnessed` also books it as seen
    // (notifyCrimeWitnessed: bounty). For tests where the game's sight check never raises the alarm.
    const int crime = f.size() >= 5 ? ParseCrimeName(Lower(f[4])) : -1;
    if (crime < 0 || f.size() < 7 || Lower(f[5]) != "against")
      return "usage: crime <npc> commit <stealing|looting|assault|...> against <owner npc> [witnessed]";
    Character *owner = FindCharacter(world, f[6]);
    if (!owner)
      return NotFound(f[6]);
    Faction *fac = owner->getFaction();
    if (!Valid(fac))
      return "error: " + owner->getName() + " has no faction";
    const bool witnessed = f.size() >= 8 && Lower(f[7]) == "witnessed";
    const hand oh = owner->getHandle();
    bool set = false;
    try {
      set = c->crimes.setCrime((CrimeEnum)crime, fac, oh);
      if (witnessed)
        c->crimes.notifyCrimeWitnessed(fac, oh, 30, (CrimeEnum)crime);
    } catch (...) {
      return "error: setCrime threw";
    }
    ok = c->crimes.isCommittingCrime();
    Log("KAH: crime commit " + c->getName() + " " + BountyManager::crimeToStr((CrimeEnum)crime) + " against " +
        owner->getName() + " [" + FactionName(fac) + "] set=" + (set ? "1" : "0") + (witnessed ? " witnessed" : ""));
    return std::string("set=") + (set ? "1" : "0") + (witnessed ? " witnessed" : "") + " | " + CrimeReport(world, c, 200);
  }
  if (cmd == "crime") { // crime <npc> [radius <m>]: bounty, crime, who hunts him (KAH 22)
    float radius = (float)atof(Option(f, 3, "radius", "200").c_str());
    if (!(radius > 0) || radius > 1000)
      radius = 200;
    ok = true;
    return CrimeReport(world, c, radius);
  }

  if (cmd == "pickup") { // owned items (or "order"): the player's PICKUP order, answered when done (KAH 22)
    bool forceOrder = false, forceNow = false;
    for (size_t i = 4; i < f.size(); ++i) {
      if (Lower(f[i]) == "order")
        forceOrder = true;
      if (Lower(f[i]) == "now")
        forceNow = true;
    }
    if (f.size() >= 4 && !forceNow) {
      Ogre::Vector3 center = c->getPosition();
      const std::string nearName = Option(f, 4, "near", "");
      if (!nearName.empty()) {
        Character *nc = FindCharacter(world, nearName);
        float bd = 0;
        Building *nb = nc ? nullptr : FindBuilding(world, origin, nearName, kDefaultSearchRadius, bd);
        if (nc)
          center = nc->getPosition();
        else if (nb)
          center = nb->getPosition();
        else
          return "near: no character or building named " + nearName;
      }
      float radius = (float)atof(Option(f, 4, "radius", nearName.empty() ? "20" : "30").c_str());
      if (!(radius > 0) || radius > 300)
        radius = 20;
      std::string why;
      Item *item = FindGroundItem(world, center, f[3], radius, why);
      if (!item)
        return why;
      Faction *ownerF = item->getFaction();
      // A plain drop keeps the game's empty faction "No Faction": not owned (to-do 19).
      Faction *emptyF = nullptr;
      try {
        if (Valid(world->factionMgr))
          emptyF = world->factionMgr->getEmptyFaction();
      } catch (...) {
      }
      const bool owned = OwnedByOtherFaction(Valid(ownerF), Valid(ownerF) && ownerF == emptyF,
                                             ownerF == c->getFaction(), FactionName(ownerF));
      if (owned || forceOrder) {
        OrdersReceiver *orders = c->getOrdersReciever();
        if (!Valid(orders))
          return c->getName() + " takes no orders";
        StealTimer s;
        s.id = f[0];
        s.who = c->getHandle();
        s.item = item->getHandle();
        s.name = c->getName();
        s.itemName = item->getName();
        s.owner = FactionName(ownerF);
        s.stolenBefore = StolenCount(c);
        s.startTick = GetTickCount();
        Log("KAH: pickup(order) " + s.name + " -> " + s.itemName + " owner=" + s.owner + " stolen_before=" +
            Int(s.stolenBefore) + " item_stolen_before=" + (item->isStolen(false) ? "1" : "0") +
            " stealth=" + (c->isStealthMode() ? "1" : "0"));
        // What a player's right-click on the item gives: he walks over and
        // picks it up, and the game runs its own theft checks.
        orders->addOrder(PICKUP, item->getHandle(), item->getPosition(), true, false);
        g_steals.push_back(s);
        pending = true; // StealTick answers when it is in his inventory (or after 120 s)
        ok = true;
        return "";
      }
    }
    // unowned: the instant same-instance pickup (RunCharacterCommand)
  }

  if (cmd == "runspeed") { // runspeed <npc>: movement speeds the game uses now (KAH 19)
    CharMovement *m = c->movement;
    if (!Valid(m))
      return c->getName() + " has no movement";
    static const char *const speeds[] = {"walk", "jog", "run", "grouped", "no_change"};
    const int so = (int)m->speedOrders;
    ok = true;
    return c->getName() + " movement_speed=" + Num(c->getMovementSpeed()) +
           " max_speed=" + Num(m->getMaxSpeed()) + " current_speed=" + Num(m->currentSpeed) +
           " desired_speed=" + Num(m->desiredSpeed) + " walk_speed=" + Num(m->walkSpeed) +
           " speed_orders=" + (so >= 0 && so < 5 ? speeds[so] : "?") + RunSpeedStats(c) +
           " (m/s at game speed 1; walktime measures a real walk)";
  }

  if (cmd == "walktime") { // walktime <npc> <dist> [+x|-x|+z|-z] [walk|run]: timed walk, answered on arrival (KAH 19)
    const float dist = f.size() >= 4 ? (float)atof(f[3].c_str()) : 0.0f;
    if (!(dist >= 2.0f && dist <= 500.0f))
      return "usage: walktime <npc> <dist 2..500> [+x|-x|+z|-z] [walk|run] (he walks that far along the axis, "
             "default +x)";
    // PG 254: an axis like swimtime (pg-74 batch Y: 300 along +x from the home spot was never walked)
    std::string mode, axis = "+x";
    Ogre::Vector3 dir(1, 0, 0);
    for (size_t k = 4; k < f.size(); ++k) {
      const std::string a = Lower(f[k]);
      if (a == "walk" || a == "run")
        mode = a;
      else if (a == "+x" || a == "x")
        axis = "+x", dir = Ogre::Vector3(1, 0, 0);
      else if (a == "-x")
        axis = "-x", dir = Ogre::Vector3(-1, 0, 0);
      else if (a == "+z" || a == "z")
        axis = "+z", dir = Ogre::Vector3(0, 0, 1);
      else if (a == "-z")
        axis = "-z", dir = Ogre::Vector3(0, 0, -1);
      else
        return "walktime: unknown option " + f[k] + " (+x|-x|+z|-z, walk|run)";
    }
    if (c->isUnconcious() || c->isDead())
      return c->getName() + " can't walk (KO or dead)";
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders))
      return c->getName() + " takes no orders";
    CharMovement *m = c->movement;
    if (Valid(m) && (mode == "walk" || mode == "run"))
      m->setDesiredSpeedOrders(mode == "walk" ? WALK : RUN);
    WalkTimer w;
    w.id = f[0];
    w.who = c->getHandle();
    w.name = c->getName();
    w.start = c->getPosition();
    w.target = w.start + dir * dist;
    w.dist = dist;
    w.axis = axis;
    // the game's own navmesh test of the target point (-1 unknown): reported with every reply
    w.targetOnNav = -1;
    try {
      if (Valid(world) && world->navmesh)
        w.targetOnNav = world->navmesh->getPositionValid(w.target) ? 1 : 0;
    } catch (...) {
    }
    w.simSeconds = 0;
    w.startTick = w.lastTick = GetTickCount();
    w.startGameHours = world->getTimeStamp_inGameHours().getTotalHours();
    w.topSpeed = 0;
    w.moving = false;
    w.lastPos = w.start;
    orders->clearOrders();
    orders->addOrder(MOVE_CUS_ORDERED, hand(), w.target, true, false);
    for (size_t i = 0; i < g_walks.size(); ++i)
      if (SameHandle(g_walks[i].who, w.who)) {
        WriteOutbox(g_walks[i].id, false, "replaced by a new walktime for " + w.name);
        g_walks.erase(g_walks.begin() + i);
        break;
      }
    g_walks.push_back(w);
    Log("KAH: walktime " + w.name + " dist=" + Num(dist) + " axis=" + axis + " mode=" +
        (mode.empty() ? "as is" : mode) + " paused=" + (world->isPaused() ? "1" : "0") + " start=" +
        Num(w.start.x) + "," + Num(w.start.y) + "," + Num(w.start.z) + " target_on_navmesh=" + Int(w.targetOnNav));
    pending = true; // answered by WalkTick when he arrives
    ok = true;
    return "";
  }

  if (cmd == "acceltime") { // acceltime <npc> <dist> [+x|-x|+z|-z] [walk|run] [stopat <d>] [halt]: PG 254 / Shay D4
    const float dist = f.size() >= 4 ? (float)atof(f[3].c_str()) : 0.0f;
    if (!(dist >= 10.0f && dist <= 500.0f))
      return "usage: acceltime <npc> <dist 10..500> [+x|-x|+z|-z] [walk|run] [stopat <d>] [halt] [follow] (he runs toward a "
             "point dist along the axis; at stopat (default dist/2) he is stopped; reply: start_delay t50 t90 "
             "cruise_speed stop_dist stop_seconds)";
    std::string mode, axis = "+x", stopMode = "order";
    Ogre::Vector3 dir(1, 0, 0);
    float stopAt = dist * 0.5f;
    bool follow = false;
    for (size_t k = 4; k < f.size(); ++k) {
      const std::string a = Lower(f[k]);
      if (a == "follow")
        follow = true;
      else if (a == "walk" || a == "run")
        mode = a;
      else if (a == "halt" || a == "order")
        stopMode = a;
      else if (a == "stopat" && k + 1 < f.size())
        stopAt = (float)atof(f[++k].c_str());
      else if (a == "+x" || a == "x")
        axis = "+x", dir = Ogre::Vector3(1, 0, 0);
      else if (a == "-x")
        axis = "-x", dir = Ogre::Vector3(-1, 0, 0);
      else if (a == "+z" || a == "z")
        axis = "+z", dir = Ogre::Vector3(0, 0, 1);
      else if (a == "-z")
        axis = "-z", dir = Ogre::Vector3(0, 0, -1);
      else
        return "acceltime: unknown option " + f[k] + " (+x|-x|+z|-z, walk|run, stopat <d>, halt|order, follow)";
    }
    if (!(stopAt >= 5.0f && stopAt < dist))
      return "acceltime: stopat must be 5 .. below dist";
    if (c->isUnconcious() || c->isDead())
      return c->getName() + " can't run (KO or dead)";
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders))
      return c->getName() + " takes no orders";
    CharMovement *m = c->movement;
    if (Valid(m) && (mode == "walk" || mode == "run"))
      m->setDesiredSpeedOrders(mode == "walk" ? WALK : RUN);
    AccelTimer a;
    a.id = f[0];
    a.who = c->getHandle();
    a.name = c->getName();
    a.start = c->getPosition();
    a.dir = dir;
    a.target = a.start + dir * dist;
    a.dist = dist;
    a.stopAt = stopAt;
    a.axis = axis;
    a.stopMode = stopMode;
    a.sim = 0;
    QueryPerformanceCounter(&a.last);
    a.startTick = GetTickCount();
    a.stopSim = a.peakSim = 0;
    a.peak = 0;
    a.stopIndex = 0;
    a.stopGiven = false;
    a.topSpeed = 0;
    a.follow = follow;
    a.ordered = a.moved = false;
    a.onFrames = a.offFrames = a.refollows = 0;
    a.onSinceTick = 0;
    if (follow) {
      CameraClass *cam = GameCamera(world);
      if (!cam)
        return "acceltime follow: no game camera";
      a.prevFollow = cam->getFollowObject();
      CameraFollow(world, c);
      orders->clearOrders(); // stand still until the camera has him; the order goes out in AccelTick
    } else {
      AccelOrder(a, c);
    }
    for (size_t i = 0; i < g_accels.size(); ++i)
      if (SameHandle(g_accels[i].who, a.who)) {
        WriteOutbox(g_accels[i].id, false, "replaced by a new acceltime for " + a.name);
        g_accels.erase(g_accels.begin() + i);
        break;
      }
    g_accels.push_back(a);
    Log("KAH: acceltime " + a.name + " dist=" + Num(dist) + " stopat=" + Num(stopAt) + " axis=" + axis + " mode=" +
        (mode.empty() ? "as is" : mode) + " stop=" + stopMode + " follow=" + (follow ? "1" : "0") +
        " paused=" + (world->isPaused() ? "1" : "0"));
    pending = true; // answered by AccelTick after the stop
    ok = true;
    return "";
  }

  if (cmd == "camfollow") { // camfollow <npc> [on|off]: the game camera follows him (CameraClass::followObject)
    const std::string onOff = f.size() >= 4 ? Lower(f[3]) : "on";
    if (onOff != "on" && onOff != "off")
      return "usage: camfollow <npc> [on|off]";
    CameraClass *cam = GameCamera(world);
    if (!cam)
      return "camfollow: no game camera";
    if (onOff == "on")
      CameraFollow(world, c);
    else if (SameHandle(cam->getFollowObject(), c->getHandle()))
      cam->stopFollowing();
    ok = true;
    return c->getName() + " camfollow=" + onOff + " following=" +
           (SameHandle(cam->getFollowObject(), c->getHandle()) ? "1" : "0") +
           " on_screen=" + (c->isOnScreen ? "1" : "0");
  }

  if (cmd == "hit") { // hit <attacker> <victim> <part> <damage>: a credited wound, no fight (REL B 55)
    if (f.size() < 6)
      return "usage: hit <attacker> <victim> <part 0-6|head|chest|stomach|left_arm|right_arm|left_leg|right_leg> "
             "<cut damage 0..500>";
    Character *v = FindCharacter(world, f[3]);
    if (!v)
      return "no victim named: " + f[3];
    if (v == c)
      return "attacker and victim are the same character";
    if (v->isDead())
      return v->getName() + " is dead";
    const int part = ParsePart(f[4]);
    if (part < 0)
      return "unknown body part: " + f[4];
    const float dmg = (float)atof(f[5].c_str());
    if (!HitDamageValid(dmg))
      return "damage must be > 0 and <= 500";
    MedicalSystem::HealthPartStatus *p = v->medical.getPart((unsigned __int64)part);
    if (!Valid(p))
      return "no body part " + f[4];
    HitTimer h;
    h.id = f[0];
    h.victim = v->getHandle();
    h.attacker = c->getHandle();
    h.victimName = v->getName();
    h.attackerName = c->getName();
    h.partName = f[4];
    h.part = part;
    h.before = p->flesh;
    // Credit first (Stobe reads lastGuyWhoDefeatedMe), then the wound; no
    // attackingYou / attack order, so no combat or hostility starts.
    v->lastGuyWhoDefeatedMe = c->getHandle();
    p->applyDamage(Damages(dmg, 0.0f, 0.0f, dmg, 0.0f));
    h.afterHit = p->flesh;
    h.simSeconds = 0;
    h.koReal = -1;
    h.startTick = h.lastTick = GetTickCount();
    for (size_t i = 0; i < g_hits.size(); ++i)
      if (SameHandle(g_hits[i].victim, h.victim)) {
        WriteOutbox(g_hits[i].id, false, "replaced by a new hit on " + h.victimName);
        g_hits.erase(g_hits.begin() + i);
        break;
      }
    g_hits.push_back(h);
    Log("KAH: hit " + c->getName() + " -> " + v->getName() + " part=" + f[4] + " cut=" + Num(dmg) + " flesh " +
        Num(h.before) + " -> " + Num(h.afterHit));
    pending = true; // HitTick answers after the knockout window
    ok = true;
    return "";
  }

  {
    std::string reply;
    if (RunBalanceCommand(world, f, c, origin, ok, pending, reply))
      return reply;
    if (RunRangedCommand(world, f, c, ok, pending, reply))
      return reply;
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
    std::string packPath;
    if (!Valid(pack)) // a pack inside another pack (PG 120 nested case, to-do 19)
      pack = FindPack(c->getInventory(), Lower(f[3]), 0, packPath);
    if (!Valid(pack))
      return "no container item matching: " + f[3] + " (also searched packs inside packs)";
    if (packPath.empty())
      packPath = pack->getName();
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, ARTIFACTS};
    for (int t = 0; t < 5 && !data; ++t)
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
    Log("KAH: packput " + c->getName() + " pack=" + packPath +
        " item=" + data->name + " added=" + Int(added));
    return "packput " + Int(added) + "/" + Int(count) + " " + data->name +
           " into " + packPath;
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
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, ARTIFACTS};
    for (int t = 0; t < 5 && !data; ++t)
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
    CharStats *stats = c->getStats();
    if (!Valid(stats))
      return "no stats";
    if (Lower(f[3]) == "all") {
      ok = true;
      return c->getName() + " base(effective):" + AllStats(stats);
    }
    StatsEnumerated st = STAT_NONE;
    if (!ParseStatName(f[3], st))
      return "unknown stat: " + f[3] + " (stat <npc> all lists them)";
    float base = stats->getStat(st, true);
    float effective = stats->getStat(st, false);
    ok = true;
    // The game's own condition multiplier on this stat (MedicalSystem::getHealthStatModifier) and each
    // factor alone: balance windows must run under the same conditions (pg m28: a base-50 worker read 27.5
    // early and 12.5 later in the same file, so night/hunger/wounds/weather drift looked like skill noise).
    std::string mods;
    try {
      MedicalSystem *med = c->getMedical();
      if (Valid(med)) {
        mods = " mod=" + Fine(med->getHealthStatModifier(st, true, true, true, true, true, true)) +
               " hunger=" + Fine(med->getHealthStatModifier(st, true, false, false, false, false, false)) +
               " wounds=" + Fine(med->getHealthStatModifier(st, false, true, false, false, false, false)) +
               " dark=" + Fine(med->getHealthStatModifier(st, false, false, true, false, false, false)) +
               " robot=" + Fine(med->getHealthStatModifier(st, false, false, false, true, false, false)) +
               " weather=" + Fine(med->getHealthStatModifier(st, false, false, false, false, true, false)) +
               " gear=" + Fine(med->getHealthStatModifier(st, false, false, false, false, false, true)) +
               " light=" + Fine(c->getLightLevel());
      }
    } catch (...) {
      mods = " mod=error";
    }
    return c->getName() + " " + f[3] + " base=" + Num(base) + " effective=" + Num(effective) + mods;
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
      // m29-5090 (PG gate 89): a spawned NPC already wearing something in that slot (a bandit's own hat) makes
      // equipItem fail: move every other worn item of the same slot type to the main inventory, then retry
      std::string replaced;
      if (!ok) {
        std::vector<Item *> worn;
        lektor<InventorySection *> &sections = inv->sectionsInSearchOrder;
        for (uint32_t s = 0; s < sections.size(); ++s) {
          InventorySection *section = sections[s];
          if (!Valid(section))
            continue;
          const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
          for (uint32_t i = 0; i < items.size(); ++i) {
            Item *other = items[i].item;
            if (Valid(other) && other != item && other->isEquipped && other->slotType == item->slotType)
              worn.push_back(other);
          }
        }
        InventorySection *main = inv->getSection("main");
        for (size_t i = 0; i < worn.size(); ++i) {
          const std::string name = worn[i]->getName();
          const int qty = worn[i]->quantity > 0 ? worn[i]->quantity : 1;
          Item *moved = inv->removeItemDontDestroy_returnsItem(worn[i], qty, false);
          if (!Valid(moved))
            continue;
          if (!(Valid(main) && main->addItem(moved, qty)))
            inv->dropItem(moved);
          replaced += (replaced.empty() ? "" : ",") + name;
        }
        if (!replaced.empty()) {
          equipped = inv->equipItem(item);
          ok = equipped && item->isEquipped;
        }
      }
      // PG 199: on a failure say the wearer's race and whether the game's own race checks allow the item
      // (RaceLimiter: the item's "races"/"races exclude" lists; RaceData noHats/noShirts/noShoes)
      std::string why;
      if (!ok) {
        why = " race=" + RaceName(c);
        try {
          RaceLimiter *limiter = RaceLimiter::getSingleton();
          if (limiter && item->data)
            why += std::string(" race_ok=") + (limiter->canEquip(item->data, c) ? "1" : "0");
          RaceData *r = c->getRace();
          if (r && ((item->slotType == ATTACH_HAT && r->noHats) || (item->slotType == ATTACH_SHIRT && r->noShirts) ||
                    (item->slotType == ATTACH_BOOTS && r->noShoes)))
            why += " race_no_slot=1";
        } catch (...) {
        }
      }
      Log("KAH: equip " + c->getName() + " " + DescribeItem(item) + " ok=" + (ok ? "1" : "0") +
          (replaced.empty() ? "" : " replaced=" + replaced) + why);
      return std::string(ok ? "equipped " : "equip failed ") + DescribeItem(item) +
             (replaced.empty() ? "" : " replaced=" + replaced) + why;
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
        // remembered like a `drop`, so `pickup` finds it at once (even before its physics object exists)
        g_dropped.push_back(moved->getHandle());
        if (g_dropped.size() > 64)
          g_dropped.erase(g_dropped.begin());
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

  if (cmd == "hp" && f.size() >= 4 && Lower(f[3]) == "detail") {
    // hp <npc> detail: every HealthPartStatus field per part plus the
    // medical summary fields, to see what a wounds factor reads.
    MedicalSystem &med = c->medical;
    std::string out;
    int count = med.getPartCount();
    for (int i = 0; i < count; ++i) {
      MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)i);
      if (!Valid(part))
        continue;
      out += " | " + Int(i) + " type=" + Int((long long)part->whatAmI) + " flesh=" + Num(part->flesh) +
             " stun=" + Num(part->fleshStun) + " band=" + Num(part->bandaging) +
             " jury=" + Num(part->juryRigging) + " wear=" + Num(part->wearDamage) +
             " maxH()=" + Num(part->maxHealth()) + " _max=" + Num(part->_maxHealth) +
             " hpmult=" + Num(part->HPMult) + " age=" + Num(part->age) +
             " derived%=" + Num(part->derivedFleshHealthPercent) + (part->isRobotic() ? " robot" : "");
    }
    ok = true;
    return c->getName() + " worstDamage=" + Num(med.worstDamage) + " bestArm=" + Num(med.partBestArm) +
           " head=" + Num(med.partHead) + " worstTorso=" + Num(med.partWorstTorso) +
           " firstAid=" + Num(med.needsFirstAidScoreTotal_fleshy) + " wounds=" + Int((long long)med.wounds.size()) +
           " wfactor=" + Num(med.getHealthStatModifier(STAT_SMITHING_WEAPON, false, true, false, false, false, false)) +
           " parts" + out;
  }

  if (cmd == "hp" && f.size() >= 6 && Lower(f[3]) == "set") {
    // hp <npc> set <flesh|stun|band|derived> <value|max>: write one field on
    // every part (diagnostics for the protect/health wounds factor).
    const std::string field = Lower(f[4]);
    const bool toMax = Lower(f[5]) == "max";
    const float v = (float)atof(f[5].c_str());
    MedicalSystem &med = c->medical;
    int count = med.getPartCount(), n = 0;
    for (int i = 0; i < count; ++i) {
      MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)i);
      if (!Valid(part))
        continue;
      const float val = toMax ? part->maxHealth() : v;
      if (field == "flesh")
        part->flesh = val;
      else if (field == "stun")
        part->fleshStun = val;
      else if (field == "band")
        part->bandaging = val;
      else if (field == "derived")
        part->derivedFleshHealthPercent = val;
      else
        return "usage: hp <npc> set <flesh|stun|band|derived> <value|max>";
      ++n;
    }
    ok = true;
    return "set " + field + " on " + Int(n) + " parts of " + c->getName();
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
      const float health = PartHealthFraction(part->flesh, part->fleshStun, maxHp);
      if (maxHp > 0.0f && health < worst)
        worst = health;
      out += " " + Int(i) + ":" + Num(part->flesh) + "/" + Num(maxHp);
      if (part->fleshStun > 0.0f)
        out += "(stun " + Num(part->fleshStun) + ")";
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
      const std::string method = TeleportRobust(world, c, to);
      ok = true;
      Log("KAH: teleport " + Describe(c, nullptr) + " to " + b->getName() + " method=" + method);
      return "teleported next to " + b->getName() + " (" + Num(dist) + " from the player): " +
             Describe(c, &origin) + TeleportMoved(c, to, method);
    }
    if (!ResolvePosition(world, f, 3, to, error))
      return error;
    to.x += (float)atof(Option(f, 3, "dist", "0").c_str());
    const std::string method = TeleportRobust(world, c, to);
    ok = true;
    Log("KAH: teleport " + Describe(c, nullptr) + " method=" + method);
    return "teleported: " + Describe(c, &origin) + TeleportMoved(c, to, method);
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
      return NotFound(f[3]);
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
      return NotFound(f[3]);
    int price = atoi(f[5].c_str());
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, ARTIFACTS};
    for (int t = 0; t < 5 && !data; ++t)
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
    // CROSSBOW: crossbows are their own item type (m46: "give Malzin Toothpick" found the bolts instead)
    const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, ARTIFACTS, CROSSBOW};
    data = FindDataTypes(world, types, 6, f[3], error);
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
    // giveprobe4080 (2026-10-10): weapons are created now but most don't fit the main inventory, so a character with
    // both weapon slots taken refuses every weapon. Free one slot the way `equip` does (the worn weapon goes to the main
    // inventory, else on the ground next to him), then add again; the reply names it (`replaced=`).
    std::string replaced, room;
    // Any type: one more try with a fresh item, so a refusal reports the item size and every section's room.
    const bool weapon = data->type == WEAPON || data->type == CROSSBOW;
    if (added < count && error.empty()) {
      Item *probe = MakeItem(world, data, f, 4, nullptr, error);
      if (Valid(probe)) {
        room = " item=" + Int(probe->itemWidth) + "x" + Int(probe->itemHeight) + " slot=" + Int((int)probe->slotType);
        lektor<InventorySection *> &sections = inv->sectionsInSearchOrder;
        for (uint32_t s = 0; s < sections.size(); ++s) {
          InventorySection *section = sections[s];
          if (Valid(section))
            room += " " + section->name + ":" + Int(section->width) + "x" + Int(section->height) +
                    ",lim=" + Int((int)section->limitedSlot) + ",n=" + Int((int)section->getItems().size()) +
                    ",room=" + (section->hasRoomForItem(data, 1) ? "1" : "0");
        }
        // the worn weapon to move out: one of another kind first (giveprobe5090: swapping a worn Chisa Katana for a
        // new one left the count unchanged), else the same kind
        Item *worn = nullptr, *same = nullptr;
        for (uint32_t s = 0; weapon && s < sections.size() && !worn; ++s) {
          InventorySection *section = sections[s];
          if (!Valid(section) || !section->isAnEquippedItemSection)
            continue;
          const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
          for (uint32_t i = 0; i < items.size() && !worn; ++i)
            if (Valid(items[i].item) && items[i].item->isEquipped && items[i].item->slotType == probe->slotType) {
              if (items[i].item->data != data)
                worn = items[i].item;
              else if (!same)
                same = items[i].item;
            }
        }
        if (!worn)
          worn = same;
        if (worn) {
          const std::string name = worn->getName();
          const int qty = worn->quantity > 0 ? worn->quantity : 1;
          Item *moved = inv->removeItemDontDestroy_returnsItem(worn, qty, false);
          if (Valid(moved)) {
            InventorySection *main = inv->getSection("main");
            std::string where = "main";
            if (!(Valid(main) && main->addItem(moved, qty))) {
              inv->dropItem(moved);
              where = "ground";
              g_dropped.push_back(moved->getHandle());
              if (g_dropped.size() > 64)
                g_dropped.erase(g_dropped.begin());
            }
            replaced = name + "(" + where + ")";
          }
        }
        if (inv->addItem(probe, 1, false, true)) {
          ++added;
          for (int i = added; i < count; ++i) {   // a second weapon may take the other slot
            Item *item = MakeItem(world, data, f, 4, nullptr, error);
            if (!Valid(item) || !inv->addItem(item, 1, false, true))
              break;
            ++added;
          }
        }
      }
    }
    if (added == 0 && !error.empty())
      return error;
    if (added == 0)   // addItem(destroyOnFail) refused it: no room (full inventory / no fitting slot)
      return "ERROR: no room for " + data->name + " in " + c->getName() + "'s inventory (" +
             Int(CountAllSections(inv, data)) + " already there)" + (replaced.empty() ? "" : " replaced=" + replaced) +
             room;
    // addItem can report success for items that don't stay: report what really arrived.
    int real = CountAllSections(inv, data) - countBefore;
    Log("KAH: give " + c->getName() + " item=" + data->name + " added=" + Int(added) +
        " real=" + Int(real) + " now=" + Int(countBefore + real));
    ok = real > 0;
    return c->getName() + " got " + Int(real) + "/" + Int(count) + " " + data->name +
           " (now " + Int(countBefore + real) + ")" + (replaced.empty() ? "" : " replaced=" + replaced);
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
    // The game keeps "enemies" (FactionRelations::setEnemy, set when a member is attacked,
    // e.g. an unprovoked attack order or a sneak knockout) apart from the relation value: a
    // faction attacked once stays an enemy at relation 20 (fresh spawns of it attack the
    // player, PlayerInterface::isEnemy true). A value >= 0 also ends that state both ways.
    bool enemyBefore = theirs->relations->isEnemy(ours) || ours->relations->isEnemy(theirs);
    if (v >= 0 && enemyBefore) {
      theirs->relations->setNoLongerEnemies(ours);
      ours->relations->setNoLongerEnemies(theirs);
    }
    theirs->relations->setRelation(ours, v);
    ours->relations->setRelation(theirs, v);
    bool enemyAfter = theirs->relations->isEnemy(ours) || ours->relations->isEnemy(theirs);
    std::string en = std::string(" enemy=") + (enemyBefore ? "1" : "0") + "->" + (enemyAfter ? "1" : "0");
    ok = true;
    Log("KAH: relation " + theirs->getName() + " <-> " + ours->getName() + " " +
        Num(before) + " -> " + Num(v) + en);
    return theirs->getName() + " <-> " + ours->getName() + ": " + Num(before) + " -> " +
           Num(theirs->relations->getFactionRelation(ours)) + en;
  }

  return "unknown command: " + cmd;
}

// For other mods' commands (include/KenshiAutomationHarness.h,
// api.findCharacter): the harness's own character lookup, so a mod command
// takes the same <npc> forms as the built-ins (name, #serial/index, #serial,
// @player, @selected). Game thread only (call it from your command
// handler). Returns a Character*, or NULL with the reason in error.
extern "C" __declspec(dllexport) void *KAH_FindCharacter(const char *ref, char *error,
                                                        int errorSize) {
  std::string why;
  Character *c = nullptr;
  try {
    c = ref ? FindCharacter(ou, ref) : nullptr;
    if (!c)
      why = ref ? NotFound(ref) : "no character reference";
  } catch (...) {
    c = nullptr;
    why = "lookup failed";
  }
  if (error && errorSize > 0) {
    strncpy_s(error, errorSize, why.c_str(), _TRUNCATE);
  }
  return c;
}
