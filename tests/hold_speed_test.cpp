// Offline test of the speed-hold resume rule (src/HoldSpeed.h).
// Build and run: tests\run_tests.bat
#include "HoldSpeed.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

// Runs frames of 16 ms from t0 for `ms` in `phase`, paused; returns the tick it resumed at (0 = never).
unsigned long Run(const char *phase, unsigned long t0, unsigned long ms, unsigned long &pausedAt) {
  for (unsigned long t = t0; t < t0 + ms; t += 16)
    if (HoldSpeedDecide(1.0f, phase, true, t, pausedAt) == HOLD_RESUME)
      return t;
  return 0;
}

int main() {
  unsigned long at = 0;
  Check(Run("world", 1000, 3000, at) >= 3000, "world pause: resumed after 2 s");
  at = 0;
  Check(Run("loading", 1000, 10000, at) == 0, "save load (b31 crash): never resumed while loading");
  Check(at == 0, "loading clears the pause timer");
  at = 0;
  Check(Run("menu", 1000, 10000, at) == 0, "menu: never resumed");
  at = 0;
  Check(Run("chargen", 1000, 10000, at) == 0 && Run("starting", 1000, 10000, at) == 0, "chargen/starting: never resumed");
  // Paused through a 5 s load, then the world is in: the 2 s count starts at the world, not at the pause.
  at = 0;
  Run("loading", 1000, 5000, at);
  unsigned long r = Run("world", 6000, 5000, at);
  Check(r >= 8000 && r < 8100, "after the load: resumed 2 s after the world came in");
  at = 0;
  Check(HoldSpeedDecide(0, "world", true, 5000, at) == HOLD_IDLE && at == 0, "no hold: idle");
  at = 1234;
  Check(HoldSpeedDecide(1.0f, "world", false, 5000, at) == HOLD_IDLE && at == 0, "unpaused: timer cleared");
  printf(g_failed ? "hold_speed_test: %d FAILED\n" : "hold_speed_test: all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
