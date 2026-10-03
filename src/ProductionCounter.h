#pragma once
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
  ProductionCounter() { Reset(0.0); }
  void Reset(double gameHours) {
    have = false;
    last = 0;
    produced = 0;
    removed = 0;
    startHours = gameHours;
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
