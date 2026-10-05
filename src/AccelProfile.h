#pragma once
// "acceltime" (PG 254, Shay D4): how fast a character gets up to speed and how far he slides when he stops.
// The command records (sim seconds, distance covered along the axis) every frame; this pure analysis turns the
// samples into the numbers (offline test: tests/accel_profile_test.cpp).
#include <vector>

struct AccelSample {
  double t; // sim seconds since the order
  float d;  // distance covered along the axis (signed: walking back lowers it)
};

// Speed over the window that ends at sample i: from the newest sample at least `win` seconds older
// (or the first sample). 0 when no time passed.
inline float AccelWindowSpeed(const std::vector<AccelSample> &s, size_t i, double win) {
  if (i >= s.size())
    return 0;
  size_t j = i;
  while (j > 0 && s[i].t - s[j].t < win)
    --j;
  const double dt = s[i].t - s[j].t;
  return dt > 0 ? (float)((s[i].d - s[j].d) / dt) : 0.0f;
}

struct AccelResult {
  bool started;       // he moved at all before the stop
  double startT;      // sim seconds from the order to the last sample before he moved
  float cruise;       // mean speed over the last `cruiseWin` seconds before the stop
  bool reached50, reached90;
  double t50, t90;    // sim seconds from the first movement until the window speed reached 50% / 90% of cruise
  float d90;          // distance covered when 90% was reached
  bool stopped;       // a stop was given (stopIndex valid)
  float stopDist;     // farthest point after the stop minus the point at the stop
  double stopSeconds; // sim seconds from the stop until that farthest point was first reached (within kAccelPeakEps)
};

const float kAccelMoveEps = 0.05f;  // units covered that count as moving
const float kAccelPeakEps = 0.01f;  // units below the farthest point that count as there
const float kAccelStillEps = 0.005f; // units covered that still count as standing at the start
const double kAccelSpeedWin = 0.15; // window of the speed estimate, sim seconds

// stopIndex = the first sample at or after the stop order (s.size() = no stop).
inline AccelResult AnalyzeAccel(const std::vector<AccelSample> &s, size_t stopIndex, double cruiseWin) {
  AccelResult r;
  r.started = r.reached50 = r.reached90 = r.stopped = false;
  r.startT = r.t50 = r.t90 = r.stopSeconds = 0;
  r.cruise = r.d90 = r.stopDist = 0;
  const size_t end = stopIndex < s.size() ? stopIndex : s.size(); // samples before the stop
  if (end < 2)
    return r;
  size_t first = 0;
  for (; first < end; ++first)
    if (s[first].d > kAccelMoveEps)
      break;
  if (first >= end)
    return r;
  r.started = true;
  // movement began after the last sample he still stood at the start
  size_t still = first;
  while (still > 0 && s[still].d > kAccelStillEps)
    --still;
  r.startT = s[still].t;
  const size_t last = end - 1;
  size_t j = last;
  while (j > 0 && s[last].t - s[j].t < cruiseWin)
    --j;
  const double cdt = s[last].t - s[j].t;
  r.cruise = cdt > 0 ? (float)((s[last].d - s[j].d) / cdt) : 0.0f;
  if (r.cruise > 0) {
    for (size_t i = first; i <= last; ++i) {
      const float v = AccelWindowSpeed(s, i, kAccelSpeedWin);
      if (!r.reached50 && v >= 0.5f * r.cruise) {
        r.reached50 = true;
        r.t50 = s[i].t - r.startT;
      }
      if (v >= 0.9f * r.cruise) {
        r.reached90 = true;
        r.t90 = s[i].t - r.startT;
        r.d90 = s[i].d;
        break;
      }
    }
  }
  if (stopIndex < s.size()) {
    r.stopped = true;
    const float d0 = s[stopIndex].d;
    float peak = d0;
    for (size_t i = stopIndex; i < s.size(); ++i)
      if (s[i].d > peak)
        peak = s[i].d;
    r.stopDist = peak - d0;
    for (size_t i = stopIndex; i < s.size(); ++i)
      if (s[i].d >= peak - kAccelPeakEps) {
        r.stopSeconds = s[i].t - s[stopIndex].t;
        break;
      }
  }
  return r;
}
