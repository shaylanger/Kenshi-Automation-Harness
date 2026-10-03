#pragma once
// Frame-time accumulator for the "fps" command (no game types, so the
// offline tests cover it). Plugin.cpp feeds it one delta per Ogre frame.

#include <cstdio>
#include <string>

struct FrameStats {
  long long frames;
  double seconds;  // sum of frame deltas
  double worstSec; // longest single frame
  FrameStats() { Reset(); }
  void Reset() {
    frames = 0;
    seconds = 0.0;
    worstSec = 0.0;
  }
  void Add(double deltaSec) {
    if (!(deltaSec > 0.0) || deltaSec > 3600.0) // clock glitch: ignore
      return;
    ++frames;
    seconds += deltaSec;
    if (deltaSec > worstSec)
      worstSec = deltaSec;
  }
  double AverageFps() const { return seconds > 0.0 ? frames / seconds : 0.0; }
  double MinFps() const { return worstSec > 0.0 ? 1.0 / worstSec : 0.0; }
  // "avg=59.8 min=41.2 worst_ms=24.3 frames=3590 seconds=60.0"
  std::string Report() const {
    char buf[160];
    sprintf_s(buf, "avg=%.1f min=%.1f worst_ms=%.1f frames=%lld seconds=%.1f", AverageFps(),
              MinFps(), worstSec * 1000.0, frames, seconds);
    return buf;
  }
};
