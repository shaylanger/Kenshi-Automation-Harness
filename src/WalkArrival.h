#pragma once
// "walktime" arrival (KAH 19, to-do 19): MOVE_CUS_ORDERED often ends a few
// metres short of the point (m18-4080: 31-36 of 40 m, then she stood still
// and the walk timed out after 180 s). A walk counts as arrived when he
// reaches the point, or when he has moved, then stood still for a moment
// within WalkArrivalRadius of it. Standing still farther away ends the walk
// early as a failure (blocked path) instead of waiting out the 180 s.
// Pure logic so the offline tests cover it (tests/walk_arrival_test.cpp).

enum WalkVerdict {
  WALK_GOING = 0,
  WALK_ARRIVED,      // reached the point (within 1 m of the distance or 1.5 m of the point)
  WALK_STOPPED_NEAR, // moved, then stopped within the arrival radius: counts as arrived
  WALK_STOPPED_FAR,  // moved, then stood still far from the point: blocked
  WALK_NEVER_STARTED // never moved at all (target unreachable / order ignored)
};

// 25% of the distance, at least 3 m, at most 15 m (40 m walk -> 10 m).
inline float WalkArrivalRadius(float dist) {
  float r = dist * 0.25f;
  if (r < 3.0f)
    r = 3.0f;
  if (r > 15.0f)
    r = 15.0f;
  return r;
}

const double kWalkStillSeconds = 1.5;     // real, unpaused seconds without moving = stopped
const double kWalkStillFarSeconds = 10.0; // stopped this long far from the point = blocked
// PG 254 (pg-74 batch Y): an order to a point he can't path to leaves him standing (covered 0.0 for the
// whole 180 s); after this many real unpaused seconds without a single move the walk fails
const double kWalkNeverStartedSeconds = 20.0;
const float kWalkMoveEpsilon = 0.05f;     // metres per frame that count as moving

struct WalkProgress {
  bool moved;           // has moved at all since the order
  double stillReal;     // real seconds (unpaused) without moving
  double simAtLastMove; // sim seconds when he last moved (the walk time on a stop)
  float coveredAtLastMove;
  WalkProgress() : moved(false), stillReal(0), simAtLastMove(0), coveredAtLastMove(0) {}
};

// One frame: `step` = metres moved since the last frame, `covered` = metres
// from the start (flat), `left` = metres to the point (flat), `dtReal` = real
// seconds since the last frame, `simNow` = sim seconds so far.
inline WalkVerdict WalkUpdate(WalkProgress &p, float dist, float covered, float left, float step,
                              double dtReal, double simNow, bool paused) {
  if (covered >= dist - 1.0f || left < 1.5f) {
    p.simAtLastMove = simNow;
    p.coveredAtLastMove = covered;
    return WALK_ARRIVED;
  }
  if (paused)
    return WALK_GOING;
  if (step > kWalkMoveEpsilon) {
    p.moved = true;
    p.stillReal = 0;
    p.simAtLastMove = simNow;
    p.coveredAtLastMove = covered;
    return WALK_GOING;
  }
  p.stillReal += dtReal;
  if (!p.moved)
    return p.stillReal >= kWalkNeverStartedSeconds ? WALK_NEVER_STARTED : WALK_GOING;
  if (p.stillReal < kWalkStillSeconds)
    return WALK_GOING;
  if (left <= WalkArrivalRadius(dist))
    return WALK_STOPPED_NEAR;
  return p.stillReal >= kWalkStillFarSeconds ? WALK_STOPPED_FAR : WALK_GOING;
}
