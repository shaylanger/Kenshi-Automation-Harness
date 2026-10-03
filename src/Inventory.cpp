// "inv": a character's items (worn, carried and in the backpack; works on
// bodies) as a JSON array, same-kind items grouped.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include "Harness.h"

#include <kenshi/Character.h>
#include <kenshi/GameData.h>
#include <kenshi/Inventory.h>
#include <kenshi/Item.h>

#include <map>

namespace {

bool Valid(const void *p) { return p && (uintptr_t)p > 0x10000; }

std::string Json(const std::string &s) {
  std::string out = "\"";
  for (size_t i = 0; i < s.size(); ++i) {
    unsigned char ch = (unsigned char)s[i];
    if (ch == '"' || ch == '\\') {
      out += '\\';
      out += (char)ch;
    } else if (ch < 0x20) {
      char buf[8];
      sprintf_s(buf, "\\u%04x", ch);
      out += buf;
    } else {
      out += (char)ch;
    }
  }
  return out + "\"";
}

void CollectItems(Inventory *inv, std::vector<Item *> &out) {
  if (!Valid(inv))
    return;
  lektor<InventorySection *> &sections = inv->sectionsInSearchOrder;
  for (uint32_t s = 0; s < sections.size(); ++s) {
    InventorySection *section = sections[s];
    if (!Valid(section))
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
    for (uint32_t i = 0; i < items.size(); ++i)
      if (Valid(items[i].item))
        out.push_back(items[i].item);
  }
}

struct Entry {
  std::string name, itemId, model;
  int count, valueEach, level;
  bool equipped;
};

} // namespace

bool BuildInventoryJson(Character *c, std::string &json, int &count) {
  json = "[]";
  count = 0;
  if (!Valid(c))
    return false;
  std::vector<Item *> items;
  try {
    CollectItems(c->getInventory(), items);
    ContainerItem *backpack = c->hasABackpackOn();
    if (Valid(backpack))
      CollectItems(backpack->inventory, items);
  } catch (...) {
    return false;
  }

  // Grouped by base item, quality level, maker and worn state.
  std::map<std::string, Entry> grouped;
  for (size_t i = 0; i < items.size(); ++i) {
    Item *item = items[i];
    Entry e;
    try {
      e.name = item->getName();
      e.itemId = Valid(item->data) ? item->data->stringID : "";
      e.model = (item->isWeapon() || item->isCrossbow()) && Valid(item->manufacturerData)
                    ? item->manufacturerData->name
                    : "";
      e.level = (item->isArmour() || item->isLockedArmour()) ? item->getLevel() : -1;
      e.count = item->quantity > 0 ? item->quantity : 1;
      e.valueEach = item->getValueSingle(false);
      e.equipped = item->isEquipped;
    } catch (...) {
      continue;
    }
    if (e.name.empty())
      continue;
    const std::string key = Lower(e.itemId.empty() ? e.name : e.itemId) + "|" +
                            Int(e.level) + "|" + Lower(e.model) + "|" +
                            (e.equipped ? "1" : "0");
    std::map<std::string, Entry>::iterator it = grouped.find(key);
    if (it == grouped.end())
      grouped[key] = e;
    else
      it->second.count += e.count;
  }

  json = "[";
  for (std::map<std::string, Entry>::const_iterator it = grouped.begin();
       it != grouped.end() && count < 200; ++it, ++count) {
    const Entry &e = it->second;
    json += count ? ",{" : "{";
    json += "\"name\":" + Json(e.name) + ",\"count\":" + Int(e.count) +
            ",\"equipped\":" + (e.equipped ? "true" : "false");
    if (!e.itemId.empty())
      json += ",\"item_id\":" + Json(e.itemId);
    if (e.valueEach > 0)
      json += ",\"value_each\":" + Int(e.valueEach);
    if (e.level >= 0)
      json += ",\"quality_level\":" + Int(e.level);
    if (!e.model.empty())
      json += ",\"weapon_model\":" + Json(e.model);
    json += "}";
  }
  json += "]";
  return true;
}
