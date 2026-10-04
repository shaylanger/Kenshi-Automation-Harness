// Offline test of the crime names for `crime <npc> commit` (src/CrimeArgs.h).
// Build and run: tests\run_tests.bat
#include "CrimeArgs.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  Check(ParseCrimeName("stealing") == 3, "stealing = CRIME_STEALING");
  Check(ParseCrimeName("theft") == 3 && ParseCrimeName("steal") == 3, "theft/steal = CRIME_STEALING");
  Check(ParseCrimeName("looting") == 10, "looting = CRIME_LOOTING");
  Check(ParseCrimeName("assault") == 5, "assault = CRIME_ASSAULT");
  Check(ParseCrimeName("trespassing") == 11 && ParseCrimeName("tresspassing") == 11, "trespassing both spellings");
  Check(ParseCrimeName("uniform_theft") == 16, "uniform_theft = 16");
  Check(ParseCrimeName("none") == -1, "none is no crime to commit");
  Check(ParseCrimeName("bogus") == -1, "unknown -> -1");
  printf(g_failed ? "%d FAILED\n" : "ALL PASS\n", g_failed);
  return g_failed ? 1 : 0;
}
