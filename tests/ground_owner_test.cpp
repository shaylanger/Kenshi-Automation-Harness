// Offline test of the pickup ownership rule (src/GroundOwner.h).
// Build and run: tests\run_tests.bat
#include "GroundOwner.h"

#include <algorithm>
#include <cctype>
#include <cstdio>

std::string Lower(const std::string &value) {
  std::string out = value;
  std::transform(out.begin(), out.end(), out.begin(), ::tolower);
  return out;
}

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  Check(!OwnedByOtherFaction(false, false, false, ""), "no faction object: not owned");
  Check(!OwnedByOtherFaction(true, true, false, "No Faction"), "the game's empty faction: not owned");
  Check(!OwnedByOtherFaction(true, false, false, "No Faction"), "a faction named No Faction: not owned");
  Check(!OwnedByOtherFaction(true, false, false, "no faction"), "  any case");
  Check(!OwnedByOtherFaction(true, false, true, "Nameless"), "the picker's own faction: not owned");
  Check(OwnedByOtherFaction(true, false, false, "Holy Nation"), "another faction: owned");
  Check(OwnedByOtherFaction(true, false, false, "Drifters"), "a drop with drop ... owned (Drifters): owned");
  printf(g_failed ? "%d FAILED\n" : "all ground owner tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
