#pragma once
// "pickup" (KAH 22, to-do 19): is a ground item owned by someone else, so
// picking it up is theft and goes through the player's PICKUP order? An item
// a character drops keeps a faction object, and for most drops that is the
// game's empty faction "No Faction" (m18-4080: pickup sent a PICKUP order for
// a plain drop, which never finished while paused). Only a real faction other
// than the picker's owns it. Pure logic for the offline tests.

#include <string>

std::string Lower(const std::string &value);

inline bool IsNoFactionName(const std::string &name) {
  const std::string n = Lower(name);
  return n.empty() || n == "no faction" || n == "none";
}

// hasFaction: the item has a faction object; isEmptyFaction: it is the
// game's FactionManager::getEmptyFaction(); sameAsPicker: it is the picker's.
inline bool OwnedByOtherFaction(bool hasFaction, bool isEmptyFaction, bool sameAsPicker,
                                const std::string &factionName) {
  if (!hasFaction || isEmptyFaction || sameAsPicker)
    return false;
  return !IsNoFactionName(factionName);
}
