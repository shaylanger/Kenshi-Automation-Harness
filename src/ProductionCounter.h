#pragma once

#include <vector>
// Counts what a production building made, from samples of its output
// quantity (no game types, so the offline tests cover it): a rise is
// production, a drop is hauling/taking. Sampled every frame, so hauling
// does not hide output; only a haul and a production step in the very same
// frame would net out (they are counted as their difference).

struct ProductionCounter {
  bool have;          // a first sample was taken
  int last;           // last sampled output quantity
  long long produced; // sum of rises
  long long removed;  // sum of drops
  double startHours;  // game hours at the (re)start
  long long samples;  // samples taken since the (re)start (shows the per-frame sampling runs)
  ProductionCounter() { Reset(0.0); }
  void Reset(double gameHours) {
    have = false;
    last = 0;
    produced = 0;
    removed = 0;
    startHours = gameHours;
    samples = 0;
  }
  // A reset keeps counting from the current quantity (no jump).
  void ResetKeepLevel(double gameHours) {
    const bool had = have;
    const int level = last;
    Reset(gameHours);
    have = had;
    last = level;
  }
  void Sample(int quantity) {
    if (quantity < 0)
      return;
    ++samples;
    if (!have) {
      have = true;
      last = quantity;
      return;
    }
    const int d = quantity - last;
    if (d > 0)
      produced += d;
    else if (d < 0)
      removed += -d;
    last = quantity;
  }
  double Hours(double nowHours) const {
    return nowHours > startHours ? nowHours - startHours : 0.0;
  }
  double PerGameHour(double nowHours) const {
    const double h = Hours(nowHours);
    return h > 0.0 ? produced / h : 0.0;
  }
};

// Stable key of a tracked building: its handle's index and serial. Run m13:
// comparing whole hand objects (hand::operator==) never matched, so every
// call started a new entry; the plain numbers do.
struct ProductionKey {
  unsigned int index;
  unsigned int serial;
  ProductionKey() : index(0), serial(0) {}
  ProductionKey(unsigned int i, unsigned int s) : index(i), serial(s) {}
  bool operator==(const ProductionKey &o) const { return index == o.index && serial == o.serial; }
};

// Index of the entry with this key in a vector of anything with a `key`
// member, or -1.
template <class Entry>
int FindProductionEntry(const std::vector<Entry> &entries, const ProductionKey &key) {
  for (size_t i = 0; i < entries.size(); ++i)
    if (entries[i].key == key)
      return (int)i;
  return -1;
}
