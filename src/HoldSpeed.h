#pragma once
// "speed <x> hold" resume rule (Commands.cpp HoldSpeedTick). The hold unpauses the game 2 s after a pause it did
// not make, but only while the world is up: 4080 b31 crashed inside a save load (kenshi_x64+0x37f665, zone
// array NULL) 2 s after the hold resumed the game mid-load ("the game paused itself, resumed at 1.0" at load+2 s).
// While the phase is not "world" (loading, menu, chargen, starting) the pause timer is cleared, so the 2 s count
// starts again only once the world is in.
// Pure logic so the offline tests cover it (tests/hold_speed_test.cpp).
#include <string>

enum HoldAction {
  HOLD_IDLE = 0, // nothing to do (no hold, not paused, or still waiting)
  HOLD_RESUME    // unpause and restore the held speed now
};

// pausedAt: tick of the first paused frame seen (0 = none), updated in place.
inline HoldAction HoldSpeedDecide(float holdSpeed, const std::string &phase, bool paused, unsigned long now,
                                  unsigned long &pausedAt) {
  if (holdSpeed <= 0)
    return HOLD_IDLE;
  if (phase != "world" || !paused) {
    pausedAt = 0;
    return HOLD_IDLE;
  }
  if (!pausedAt) {
    pausedAt = now ? now : 1;
    return HOLD_IDLE;
  }
  if (now - pausedAt < 2000)
    return HOLD_IDLE;
  pausedAt = 0;
  return HOLD_RESUME;
}
