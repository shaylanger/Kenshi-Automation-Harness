// Offline test of the "produced" counter (src/ProductionCounter.h).
// Build and run: tests\run_tests.bat
#include "ProductionCounter.h"

#include <string>

#include <cmath>
#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  ProductionCounter c;
  c.Reset(10.0);
  c.Sample(5); // first sample: baseline only
  Check(c.produced == 0 && c.removed == 0, "first sample is the baseline");
  c.Sample(6);
  c.Sample(7);
  c.Sample(7);
  Check(c.produced == 2, "rises count as produced");
  c.Sample(0); // a worker hauls everything
  Check(c.produced == 2 && c.removed == 7, "hauling counts as removed, not hiding output");
  c.Sample(1);
  c.Sample(3); // fast game speed: two units in one frame
  Check(c.produced == 5, "production after hauling and multi-unit steps");
  c.Sample(-1);
  Check(c.produced == 5 && c.last == 3, "negative quantity ignored");
  Check(fabs(c.Hours(12.5) - 2.5) < 1e-9, "game hours since start");
  Check(fabs(c.PerGameHour(12.5) - 2.0) < 1e-9, "units per game hour");
  Check(c.PerGameHour(10.0) == 0.0 && c.Hours(9.0) == 0.0, "no time passed: rate 0");

  c.ResetKeepLevel(20.0);
  Check(c.produced == 0 && c.removed == 0 && c.startHours == 20.0, "reset clears counts");
  c.Sample(4);
  Check(c.produced == 1, "after a reset counting continues from the last level (3 -> 4)");

  ProductionCounter fresh;
  fresh.ResetKeepLevel(1.0);
  fresh.Sample(9);
  Check(fresh.produced == 0, "reset before any sample: next sample is the baseline");

  Check(c.samples == 1, "samples counted since the reset");

  // Two consecutive "produced" calls for the same building must hit the
  // same entry (run m13: every call made a new one).
  struct Entry {
    ProductionKey key;
    std::string name;
  };
  std::vector<Entry> table;
  Entry mine = {ProductionKey(1234, 374267584), "Stone Mine"};
  Check(FindProductionEntry(table, mine.key) == -1, "unknown building: no entry");
  table.push_back(mine);
  Entry other = {ProductionKey(1235, 99), "Iron Refinery"};
  table.push_back(other);
  Check(FindProductionEntry(table, ProductionKey(1234, 374267584)) == 0, "first call's key found again");
  Check(FindProductionEntry(table, ProductionKey(1234, 374267584)) == 0, "second call hits the same entry");
  Check(FindProductionEntry(table, ProductionKey(1235, 99)) == 1, "other building, own entry");
  Check(FindProductionEntry(table, ProductionKey(1234, 1)) == -1, "same index, new serial: a different building");

  printf(g_failed ? "%d FAILED\n" : "all production counter tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
