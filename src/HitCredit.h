#pragma once
// "hit <attacker> <victim> <part> <damage>" (REL B 55, accidental hits): a
// cut wound on the victim credited to the attacker, with no attack order,
// no combat and no hostility. The credit is the victim's
// Character::lastGuyWhoDefeatedMe, the first field Stobe's harm/knockout
// attribution reads (ResolveCombatAttribution: defeated_by). The harness
// keeps that field on the attacker for a short window so the game's own
// knockout handling (a frame or more later) can't leave it on someone else,
// then answers. Pure logic for the offline tests.

const float kHitMaxDamage = 500.0f;
const double kHitWindowSim = 2.0;      // sim seconds to watch for a knockout
const double kHitHoldAfterKoReal = 3.0; // real seconds the credit is held after the KO
const double kHitMaxReal = 15.0;       // answer by then even if paused

inline bool HitDamageValid(float damage) { return damage > 0.0f && damage <= kHitMaxDamage; }

// koReal < 0: no knockout seen yet.
inline bool HitWindowDone(double simElapsed, double realElapsed, double koReal) {
  if (koReal >= 0)
    return realElapsed - koReal >= kHitHoldAfterKoReal || realElapsed >= kHitMaxReal + kHitHoldAfterKoReal;
  return simElapsed >= kHitWindowSim || realElapsed >= kHitMaxReal;
}
