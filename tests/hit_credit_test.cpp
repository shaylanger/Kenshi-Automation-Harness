// Offline test of the hit command's window rule (src/HitCredit.h).
// Build and run: tests\run_tests.bat
#include "HitCredit.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  Check(HitDamageValid(30), "30 damage ok");
  Check(!HitDamageValid(0) && !HitDamageValid(-5), "zero/negative refused");
  Check(!HitDamageValid(501), "over 500 refused");
  Check(!HitWindowDone(1.0, 1.0, -1), "no KO, 1 s sim: still watching");
  Check(HitWindowDone(2.0, 2.0, -1), "no KO after 2 s sim: done");
  Check(!HitWindowDone(0.0, 10.0, -1), "paused, 10 s real: still watching");
  Check(HitWindowDone(0.0, 15.0, -1), "paused, 15 s real: done");
  Check(!HitWindowDone(0.5, 1.0, 0.5), "KO at 0.5 s: credit held");
  Check(HitWindowDone(4.0, 3.5, 0.5), "KO at 0.5 s, 3 s later: done");
  Check(!HitWindowDone(2.5, 2.5, 1.9), "KO near the end of the window: held 3 s past it");
  printf(g_failed ? "%d FAILED\n" : "all hit credit tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
