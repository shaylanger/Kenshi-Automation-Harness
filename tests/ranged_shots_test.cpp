// Offline test of rangedtest's accuracy formula and hit accounting (src/RangedShots.h).
// Build and run: tests\run_tests.bat
#include "RangedShots.h"

#include <cmath>
#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}
bool Near(float a, float b) { return std::fabs(a - b) < 1e-4f; }

int main() {
  // Crossbows 50: Perception 25 / 90 / 25 + 50% gear (37.5)
  const float a = RangedAcc01(50, 25), b = RangedAcc01(50, 90), c = RangedAcc01(50, 37.5f);
  Check(Near(a, 0.375f) && Near(b, 0.70f) && Near(c, 0.4375f), "acc01 = 0.005 x (weapon + perception)");
  Check(Near(RangedDeviation(10, a), 6.25f), "dev = base x (1 - acc01)");
  Check(RangedDeviation(10, b) < RangedDeviation(10, c) && RangedDeviation(10, c) < RangedDeviation(10, a),
        "more perception, less spread");
  Check(RangedDeviation(10, 1.2f) == 0.0f, "acc01 above 1 clamps the spread at 0");

  RangedTally t;
  t.Shot(0.0);
  t.Shot(0.5);
  t.Damage(); // first shot hits
  t.Expire(2.0, 3.0);
  Check(t.hits == 1 && t.misses == 0 && t.pending.size() == 1, "hit goes to the oldest waiting shot");
  t.Expire(3.6, 3.0);
  Check(t.misses == 1 && t.pending.empty(), "shot past its window is a miss");
  t.Damage();
  Check(t.otherDamage == 1 && t.hits == 1, "damage with no waiting shot is not a hit");
  Check(t.shots == 2 && t.Resolved() == 2, "all shots resolved");
  Check(RangedDamageSeen(0, 12) && !RangedDamageSeen(3, 3.3f), "damage threshold");
  printf(g_failed ? "%d FAILED\n" : "all ranged shots tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
