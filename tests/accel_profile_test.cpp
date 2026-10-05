// Offline test of the acceltime analysis (src/AccelProfile.h). Build and run: tests\run_tests.bat
#include "AccelProfile.h"

#include <cmath>
#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}
bool Near(double a, double b, double tol) { return std::fabs(a - b) <= tol; }

// The game's rule: velocity moves toward the desired speed by at most accel x dt per frame. Waits `delay`
// seconds, runs toward `top` until `stopAt` units, then the desired speed is 0 (braking at the same accel).
std::vector<AccelSample> Simulate(float top, float accel, double delay, float stopAt, size_t &stopIndex) {
  std::vector<AccelSample> s;
  const double dt = 1.0 / 60.0;
  double v = 0, x = 0;
  bool stopped = false;
  stopIndex = (size_t)-1;
  for (double t = 0; t < 30; t += dt) {
    AccelSample a;
    a.t = t;
    a.d = (float)x;
    if (!stopped && x >= stopAt) {
      stopped = true;
      stopIndex = s.size();
    }
    s.push_back(a);
    if (t < delay)
      continue;
    const double want = stopped ? 0.0 : top;
    double dv = want - v;
    const double maxStep = accel * dt;
    if (dv > maxStep)
      dv = maxStep;
    if (dv < -maxStep)
      dv = -maxStep;
    v += dv;
    x += v * dt;
    if (stopped && v <= 0 && t > 0)
      break;
  }
  if (stopIndex == (size_t)-1)
    stopIndex = s.size();
  return s;
}

int main() {
  size_t si = 0, sa = 0;
  std::vector<AccelSample> a = Simulate(20.0f, 10.0f, 0.5, 100.0f, si);
  sa = si;
  AccelResult r = AnalyzeAccel(a, sa, 1.0);
  Check(r.started && Near(r.startT, 0.5, 0.034), "start delay 0.5 s");
  Check(Near(r.cruise, 20.0, 0.05), "cruise = top speed");
  // v = a t: 90% of 20 at 1.8 s (window lag ~0.075 s)
  Check(r.reached90 && Near(r.t90, 1.8 + kAccelSpeedWin / 2, 0.06), "t90 = 0.9 top / accel");
  Check(r.reached50 && Near(r.t50, 1.0 + kAccelSpeedWin / 2, 0.06), "t50 = 0.5 top / accel");
  // braking v^2 / 2a = 20 units in 2 s
  Check(r.stopped && Near(r.stopDist, 20.0, 0.5), "stop distance v^2/2a");
  Check(Near(r.stopSeconds, 2.0, 0.06), "stop time v/a");

  std::vector<AccelSample> b = Simulate(20.0f, 15.0f, 0.5, 100.0f, si);
  AccelResult q = AnalyzeAccel(b, si, 1.0);
  Check(Near(q.t90 / r.t90, 1 / 1.5, 0.05), "x1.5 accel: t90 x1/1.5");
  Check(Near(q.stopDist / r.stopDist, 1 / 1.5, 0.03), "x1.5 accel: stop distance x1/1.5");

  // walks back after overshooting: the farthest point still counts
  std::vector<AccelSample> c = a;
  const float peak = c.back().d;
  for (int k = 1; k <= 60; ++k) {
    AccelSample x;
    x.t = c.back().t + 1.0 / 60.0;
    x.d = peak - 0.1f * k;
    c.push_back(x);
  }
  AccelResult w = AnalyzeAccel(c, sa, 1.0);
  Check(Near(w.stopDist, r.stopDist, 0.001) && Near(w.stopSeconds, r.stopSeconds, 0.001), "walk back ignored");

  // never moved / no stop
  std::vector<AccelSample> still(100);
  for (size_t i = 0; i < still.size(); ++i) {
    still[i].t = i / 60.0;
    still[i].d = 0;
  }
  AccelResult n = AnalyzeAccel(still, still.size(), 1.0);
  Check(!n.started && !n.stopped, "never moved");
  AccelResult ns = AnalyzeAccel(a, a.size(), 1.0);
  Check(ns.started && !ns.stopped, "no stop given");
  Check(AccelWindowSpeed(a, 0, 0.15) == 0 && AccelWindowSpeed(a, a.size(), 0.15) == 0, "window speed edges");

  if (g_failed) {
    printf("accel_profile_test: %d FAILED\n", g_failed);
    return 1;
  }
  printf("accel_profile_test: all passed\n");
  return 0;
}
