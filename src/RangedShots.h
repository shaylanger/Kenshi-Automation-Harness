#pragma once
// "rangedtest" (PG Perception, ranged accuracy): pure logic for the offline tests.
//
// Native shot code, Kenshi 1.0.65 (RE_Kenshi exe / Steam RVAs; GOG/SDK header RVAs in brackets):
// GunClass::shoot 0x43A390 [0x439FB0] inlines CharStats::getRangedAccuracyMult 0x434DC0 [0x4349E0]:
//   acc01 = 0.005 * getStat(<shot stat>, false) + 0.005 * getStat(STAT_PERCEPTION, false)
// (call sites 0x43A5A3 and 0x43A5BD, both through the getStat thunk to CharStats::getStat 0x883BF0,
// i.e. the modified value that gear hooks raise), then inlines
// GunClass::calculateAccuracyDeviationAngle 0x434E10 [0x434A30]:
//   dev = max(0, lerp(acc01, accuracyDeviationBase, 0)) = max(0, base * (1 - acc01))
// and fires along aimDir.randomDeviant(random01 * dev) (Ogre::Vector3::randomDeviant import).
// The shot stat is STAT_CROSSBOWS for a personal crossbow and STAT_TURRETS for a turret, so
// Perception counts the same as the weapon skill for both.

#include <deque>

const float kRangedAccPerPoint = 0.005f;

inline float RangedAcc01(float weaponStat, float perception) {
  return kRangedAccPerPoint * weaponStat + kRangedAccPerPoint * perception;
}

inline float RangedDeviation(float deviationBase, float acc01) {
  const float d = deviationBase + (0.0f - deviationBase) * acc01;
  return d > 0.0f ? d : 0.0f;
}

// Hit accounting. A shot (from the GunClass::shoot hook) waits up to `window`
// sim seconds; a rise of the target's missing flesh (sum over body parts)
// in that time is that shot's hit (oldest waiting shot first), after which the
// harness heals the target so the next hit shows again. A shot that waited
// out its window is a miss. Damage with no waiting shot is counted apart
// (other_damage: melee, a stray hit), never as a hit.
struct RangedPending {
  double t; // sim seconds at the shot
};

struct RangedTally {
  std::deque<RangedPending> pending;
  int shots, hits, misses, otherDamage;
  double hitDamage; // flesh lost on the hits (sum; the reply's mean_hit_damage)
  RangedTally() : shots(0), hits(0), misses(0), otherDamage(0), hitDamage(0) {}

  void Shot(double now) {
    RangedPending p;
    p.t = now;
    pending.push_back(p);
    ++shots;
  }
  // damage seen this frame (amount = flesh lost): attribute to the oldest waiting shot
  void Damage(float amount = 0) {
    if (pending.empty()) {
      ++otherDamage;
      return;
    }
    pending.pop_front();
    ++hits;
    hitDamage += amount;
  }
  // expire waiting shots older than the window
  void Expire(double now, double window) {
    while (!pending.empty() && now - pending.front().t > window) {
      pending.pop_front();
      ++misses;
    }
  }
  int Resolved() const { return hits + misses; }
};

// The damage threshold: a bolt does far more; stun/bleed jitter does less.
const float kRangedHitMinDamage = 0.5f;
inline bool RangedDamageSeen(float woundsBefore, float woundsNow) {
  return woundsNow > woundsBefore + kRangedHitMinDamage;
}
