// Rules of "protect <npc> on" (KAH 11), free of game types so tests/
// protect_rules_test.cpp can check them offline.
//
// Item 122 (pg-09-soak, 50x): the squad starved. Hunger 300 lasts only ~5-6
// game hours; below that Kenshi knocks a character out again and again (no
// attacker), a revive can't keep him up, and at the end he dies. Healing
// parts and blood alone never stopped that, so protect also feeds.
#pragma once

#include <cmath>

// Game values (the UI shows them x100: hunger 300 = 3.0).
const float kProtectHungerFull = 3.0f;
const float kProtectHungerFloor = 2.0f; // fed back to full below hunger 200
const float kProtectStarving = 0.5f;    // below hunger 50: a knockout is starvation

// A knockout protect could not clear within this many real ms is logged once.
const unsigned long kProtectStuckMs = 3000;

inline bool ProtectNeedsFood(float hunger) {
  return !(hunger >= kProtectHungerFloor); // NaN counts as hungry
}

// Most likely reason for a knockout without an attacker, for the log.
inline const char *ProtectKoCause(float hunger, float blood, float maxBlood, bool bloodTrauma) {
  if (!(hunger >= kProtectStarving))
    return "starving";
  if (bloodTrauma || (maxBlood > 0 && blood < maxBlood * 0.5f))
    return "blood loss";
  return "damage or other";
}

// True once per knockout: down for kProtectStuckMs and not reported yet.
inline bool ProtectStuck(bool down, unsigned long downSinceMs, unsigned long nowMs, bool reported) {
  return down && !reported && nowMs - downSinceMs >= kProtectStuckMs;
}
