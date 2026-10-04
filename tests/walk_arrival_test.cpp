// Offline test of the walktime arrival rule (src/WalkArrival.h).
// Build and run: tests\run_tests.bat
#include "WalkArrival.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

// Walks `dist` m along +x at `speed` m/s for `moveSeconds`, then stands
// still; frames of 1/60 s. Returns the verdict and the frame time it came at.
WalkVerdict Simulate(float dist, float speed, double moveSeconds, double maxSeconds, bool pausedWhileStill,
                     double &at, WalkProgress &p) {
  const double dt = 1.0 / 60.0;
  float x = 0;
  for (double t = 0; t < maxSeconds; t += dt) {
    float step = 0;
    if (t < moveSeconds) {
      step = (float)(speed * dt);
      x += step;
    }
    const bool paused = pausedWhileStill && t >= moveSeconds;
    float left = dist - x;
    if (left < 0)
      left = -left;
    WalkVerdict v = WalkUpdate(p, dist, x, left, step, dt, t, paused);
    if (v != WALK_GOING) {
      at = t;
      return v;
    }
  }
  at = maxSeconds;
  return WALK_GOING;
}

int main() {
  Check(WalkArrivalRadius(40) == 10.0f, "40 m walk: 10 m arrival radius");
  Check(WalkArrivalRadius(4) == 3.0f, "short walk: at least 3 m");
  Check(WalkArrivalRadius(500) == 15.0f, "long walk: at most 15 m");

  double at = 0;
  {
    WalkProgress p;
    Check(Simulate(40, 8, 10, 60, false, at, p) == WALK_ARRIVED && at < 5.1, "full walk arrives");
  }
  {
    // m18-4080: covered 31.4 of 40 m, then stood still (8.6 m short)
    WalkProgress p;
    WalkVerdict v = Simulate(40, 8, 31.4 / 8, 60, false, at, p);
    Check(v == WALK_STOPPED_NEAR, "stopped 8.6 m short of 40: arrived");
    Check(at > 31.4 / 8 + 1.4 && at < 31.4 / 8 + 1.7, "  noticed ~1.5 s after the stop");
    Check(p.simAtLastMove < 31.4 / 8 + 0.05, "  walk time = time of the last move, not of the notice");
    Check(p.coveredAtLastMove > 31.3f && p.coveredAtLastMove < 31.5f, "  covered at the stop");
  }
  {
    WalkProgress p;
    Check(Simulate(40, 8, 20.0 / 8, 60, false, at, p) == WALK_STOPPED_FAR && at > 20.0 / 8 + 9.9,
          "stopped 20 m short of 40: blocked after 10 s");
  }
  {
    WalkProgress p;
    Check(Simulate(40, 8, 0, 60, false, at, p) == WALK_GOING, "never moved: keeps waiting (180 s timeout)");
  }
  {
    WalkProgress p;
    Check(Simulate(40, 8, 31.4 / 8, 60, true, at, p) == WALK_GOING, "paused after the stop: still waiting");
  }
  {
    // a short stop (under 1.5 s) mid-walk is not the end
    WalkProgress p;
    WalkVerdict v = WALK_GOING;
    const double dt = 1.0 / 60.0;
    float x = 0;
    double t = 0;
    for (; t < 30 && v == WALK_GOING; t += dt) {
      const bool still = t > 2 && t < 3; // 1 s break at 16 m
      const float step = still ? 0.0f : (float)(8 * dt);
      x += step;
      v = WalkUpdate(p, 40, x, 40 - x, step, dt, t, false);
    }
    Check(v == WALK_ARRIVED, "1 s break mid-walk: walks on and arrives");
  }
  printf(g_failed ? "%d FAILED\n" : "all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
