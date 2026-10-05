// Offline test of the `spawn ... race <filter>` matcher (src/RaceFilter.h).
// Build and run: tests\run_tests.bat
#include "RaceFilter.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  RaceFilter none = ParseRaceFilter("");
  Check(none.empty() && RaceFilterMatches(none, "Hive Worker Drone"), "empty filter matches all");
  RaceFilter ex = ParseRaceFilter("!Reptiloid|!sharkoloid|!DRAGOLOID");
  Check(ex.want.empty() && ex.reject.size() == 3, "three exclusions parsed");
  Check(!RaceFilterMatches(ex, "Reptiloid"), "excluded race rejected (case-insensitive)");
  Check(!RaceFilterMatches(ex, "Dragoloid"), "second excluded race rejected");
  Check(RaceFilterMatches(ex, "Greenlander"), "other race kept");
  RaceFilter in = ParseRaceFilter("green|scorch");
  Check(RaceFilterMatches(in, "Scorchlander") && RaceFilterMatches(in, "Greenlander"), "plain alternatives match");
  Check(!RaceFilterMatches(in, "Shek"), "race outside the plain list rejected");
  RaceFilter mix = ParseRaceFilter("hive|!soldier");
  Check(RaceFilterMatches(mix, "Hive Worker Drone"), "include + exclude: worker kept");
  Check(!RaceFilterMatches(mix, "Hive Soldier Drone"), "include + exclude: soldier rejected");
  Check(!RaceFilterMatches(mix, "Shek"), "include + exclude: non-hive rejected");
  RaceFilter bang = ParseRaceFilter("!||");
  Check(bang.empty(), "lone ! and empty parts ignored");
  printf(g_failed ? "%d FAILED\n" : "ALL PASS\n", g_failed);
  return g_failed ? 1 : 0;
}
