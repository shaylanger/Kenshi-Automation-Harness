// "rangedtest" (PG Perception, ranged accuracy): a shooter (personal crossbow
// or turret operator) fires at one target; per shot the accuracy inputs the
// game's own shot code uses, plus hits and misses. Included into Commands.cpp
// inside its anonymous namespace, after TurretCommands.inc. Formula and native
// addresses: RangedShots.h.
//
// Per shot (GunClass::shoot hook, before the original runs): the shot stat
// and Perception through CharStats::getStat, unmodified (base) and modified
// (effective: the value the shot code reads, gear bonuses included), acc01 =
// 0.005 x (weapon + perception), and the spread from the game's own
// GunClass::calculateAccuracyDeviationAngle(acc01) (dev_formula = the same
// from RangedShots.h, as a cross-check). The hook may run off the main
// thread: it only appends to g_rangedShots / g_rangedByShooter under
// g_rangedLock; the sessions live on the main thread (RangedTick drains the
// queue under the lock, then works without it).

struct RangedShotInfo {
  int stat;
  float weaponBase, weaponEff, percBase, percEff, acc01, dev, devFormula, devBase, range, dist;
  bool turret;
  int loaded, loadedMax; // GunClass::numShotsCurrent/numShotsMax as the shot starts (loaded bolts)
  std::string target;
  unsigned long shooterSerial, targetSerial;
  RangedShotInfo()
      : stat(-1), weaponBase(-1), weaponEff(-1), percBase(-1), percEff(-1), acc01(-1), dev(-1), devFormula(-1),
        devBase(-1), range(-1), dist(-1), turret(false), loaded(-1), loadedMax(-1), shooterSerial(0),
        targetSerial(0) {}
};

struct RangedShooterLog {
  int shots;
  RangedShotInfo last;
  RangedShooterLog() : shots(0) {}
};

struct RangedSession {
  std::string id;
  hand shooter, target;
  std::string shooterName, targetName;
  unsigned long shooterSerial, targetSerial;
  int wantShots;
  double window;
  float timeoutReal;
  bool heal, aim, rangedSet;
  int rangedBefore; // CharStats+0x129 before the session (-1 not touched)
  SimClock clock;
  RangedTally tally;
  float lastWounds;
  int newShots; // from the hook, not yet taken by the tick
  int aimSets, heals;
  int reloads, prevLoaded; // shots that needed a reload after the previous one emptied the gun
  // sums over this session's shots
  double sumAcc, sumDev, sumDevFormula, sumDist, sumWEff, sumPEff;
  float minDev, maxDev;
  RangedShotInfo last;
};

CRITICAL_SECTION g_rangedLock;
struct RangedLockInit {
  RangedLockInit() { InitializeCriticalSection(&g_rangedLock); }
} g_rangedLockInit;
std::map<unsigned long, RangedShooterLog> g_rangedByShooter; // key: shooter handle serial
std::vector<RangedShotInfo> g_rangedShots;                   // hook -> RangedTick (drained each frame)
std::vector<RangedSession> g_rangedSessions;                 // main thread only

// RE (1.0.65, Character::shouldUseRangedWeapons 0x7F1CA0): the first test is
// the byte at CharStats+0x129, the "use ranged weapons" toggle of the orders panel.
const size_t kUseRangedOffset = 0x129;
unsigned char *UseRangedFlag(Character *c) {
  CharStats *s = c ? c->getStats() : nullptr;
  return Valid(s) ? (unsigned char *)s + kUseRangedOffset : nullptr;
}

void RecordRangedShotImpl(GunClass *gun, Character *me, RootObject *target, int stat) {
  if (!Valid(gun) || !Valid(me))
    return;
  RangedShotInfo info;
  info.stat = stat;
  info.turret = gun->isTurret() != nullptr;
  info.devBase = gun->accuracyDeviationBase;
  info.loaded = gun->numShotsCurrent;
  info.loadedMax = gun->numShotsMax;
  info.range = gun->maxRange;
  CharStats *s = me->getStats();
  if (Valid(s)) {
    info.weaponBase = s->getStat((StatsEnumerated)stat, true);
    info.weaponEff = s->getStat((StatsEnumerated)stat, false);
    info.percBase = s->getStat(STAT_PERCEPTION, true);
    info.percEff = s->getStat(STAT_PERCEPTION, false);
    info.acc01 = RangedAcc01(info.weaponEff, info.percEff);
    info.dev = gun->calculateAccuracyDeviationAngle(info.acc01);
    info.devFormula = RangedDeviation(info.devBase, info.acc01);
  }
  Character *tc = dynamic_cast<Character *>(target);
  if (Valid(tc)) {
    info.target = tc->getName();
    info.targetSerial = tc->getHandle().serial;
    info.dist = me->getPosition().distance(tc->getPosition());
  } else {
    info.target = target ? "non-character" : "none";
  }
  info.shooterSerial = me->getHandle().serial;
  EnterCriticalSection(&g_rangedLock);
  RangedShooterLog &l = g_rangedByShooter[info.shooterSerial];
  ++l.shots;
  l.last = info;
  if (g_rangedShots.size() < 4096) // drained every frame by RangedTick
    g_rangedShots.push_back(info);
  LeaveCriticalSection(&g_rangedLock);
}

void RangedAddShot(RangedSession &r, const RangedShotInfo &info) {
  ++r.newShots;
  if (r.prevLoaded >= 0 && r.prevLoaded <= 1 && info.loaded >= 1)
    ++r.reloads; // the previous shot emptied the gun, this one fired loaded again
  r.prevLoaded = info.loaded;
  r.sumAcc += info.acc01;
  r.sumDev += info.dev;
  r.sumDevFormula += info.devFormula;
  r.sumDist += info.dist;
  r.sumWEff += info.weaponEff;
  r.sumPEff += info.percEff;
  if (info.dev < r.minDev)
    r.minDev = info.dev;
  if (info.dev > r.maxDev)
    r.maxDev = info.dev;
  r.last = info;
}

std::string RangedShotLine(const RangedShotInfo &s) {
  return " stat=" + Int(s.stat) + " gun=" + (s.turret ? "turret" : "personal") + " weapon_base=" + Fine(s.weaponBase) +
         " weapon_eff=" + Fine(s.weaponEff) + " perception_base=" + Fine(s.percBase) +
         " perception_eff=" + Fine(s.percEff) + " acc01=" + Fine(s.acc01) + " dev=" + Fine(s.dev) +
         " dev_formula=" + Fine(s.devFormula) + " dev_base=" + Fine(s.devBase) + " range=" + Num(s.range) +
         " dist=" + Num(s.dist) + " loaded=" + Int(s.loaded) + "/" + Int(s.loadedMax) + " target=" + s.target;
}

std::string RangedReply(const RangedSession &r, bool complete) {
  const int n = r.tally.shots;
  const double d = n > 0 ? (double)n : 1.0;
  std::string out = r.shooterName + " rangedtest target=" + r.targetName + " complete=" + (complete ? "1" : "0") +
                    " shots=" + Int(n) + " hits=" + Int(r.tally.hits) + " misses=" + Int(r.tally.misses) + " reloads=" + Int(r.reloads) +
                    " pending=" + Int((long long)r.tally.pending.size()) +
                    " hit_rate=" + Fine(r.tally.Resolved() > 0 ? (double)r.tally.hits / r.tally.Resolved() : 0.0) +
                    " other_damage=" + Int(r.tally.otherDamage) + " mean_acc01=" + Fine(r.sumAcc / d) +
                    " mean_dev=" + Fine(r.sumDev / d) + " mean_dev_formula=" + Fine(r.sumDevFormula / d) +
                    " min_dev=" + Fine(n > 0 ? r.minDev : -1) + " max_dev=" + Fine(n > 0 ? r.maxDev : -1) +
                    " mean_weapon_eff=" + Fine(r.sumWEff / d) + " mean_perception_eff=" + Fine(r.sumPEff / d) +
                    " mean_dist=" + Num(r.sumDist / d) + " heals=" + Int(r.heals) + " aim_sets=" + Int(r.aimSets) +
                    " seconds=" + Num(r.clock.sim) + " real_seconds=" + Num(r.clock.Real()) + " | last:";
  return out + RangedShotLine(r.last);
}

void RangedRestore(RangedSession &r) {
  if (!r.rangedSet || r.rangedBefore < 0)
    return;
  try {
    Character *c = r.shooter.getCharacter();
    unsigned char *flag = UseRangedFlag(c);
    if (flag)
      *flag = (unsigned char)r.rangedBefore;
  } catch (...) {
  }
}

void RangedTick(GameWorld *world) {
  std::vector<RangedShotInfo> shots;
  EnterCriticalSection(&g_rangedLock);
  shots.swap(g_rangedShots);
  LeaveCriticalSection(&g_rangedLock);
  for (size_t k = 0; k < shots.size(); ++k)
    for (size_t i = 0; i < g_rangedSessions.size(); ++i) {
      RangedSession &r = g_rangedSessions[i];
      if (r.shooterSerial == shots[k].shooterSerial && shots[k].targetSerial && r.targetSerial == shots[k].targetSerial)
        RangedAddShot(r, shots[k]);
    }
  for (size_t i = 0; i < g_rangedSessions.size();) {
    RangedSession &r = g_rangedSessions[i];
    r.clock.Tick(world);
    Character *s = nullptr, *t = nullptr;
    try {
      s = r.shooter.getCharacter();
      t = r.target.getCharacter();
    } catch (...) {
    }
    std::string done;
    bool okDone = false;
    if (!Valid(s) || !Valid(t)) {
      done = "rangedtest: shooter or target is gone (unloaded, killed or a load) after " + Int(r.tally.shots) +
             " shots, " + Int(r.tally.hits) + " hits";
    } else {
      for (; r.newShots > 0; --r.newShots)
        r.tally.Shot(r.clock.sim);
      const float wounds = WoundSum(t);
      if (RangedDamageSeen(r.lastWounds, wounds)) {
        r.tally.Damage();
        if (r.heal) {
          SetAllParts(t, 1.0f);
          t->medical.blood = t->medical.getMaxBlood();
          ++r.heals;
        }
        r.lastWounds = WoundSum(t);
      } else if (wounds < r.lastWounds) {
        r.lastWounds = wounds; // healed by something else
      }
      r.tally.Expire(r.clock.sim, r.window);
      if (r.aim) {
        RangedCombatClass *rc = s->rangedCombat;
        if (Valid(rc) && rc->currentTarget.getCharacter() != t) {
          rc->setTarget(t);
          ++r.aimSets;
        }
      }
      if (r.tally.Resolved() >= r.wantShots) {
        okDone = true;
        done = RangedReply(r, true);
      } else if (r.clock.Real() > r.timeoutReal) {
        okDone = true; // the counts so far are the evidence; complete=0 says it did not finish
        done = RangedReply(r, false) + " (timeout " + Num(r.timeoutReal) + " s real)";
      }
    }
    if (!done.empty()) {
      RangedRestore(r);
      Log("KAH: rangedtest " + done);
      WriteOutbox(r.id, okDone, done);
      g_rangedSessions.erase(g_rangedSessions.begin() + i);
    } else {
      ++i;
    }
  }
}

// rangedtest <shooter> <target> [shots <n>] [window <s>] [timeout <s>] [noheal] [noaim] [attack] [keepranged]
// rangedtest <shooter> last
std::string HandLine(const hand &h) {
  return "type=" + Int((int)h.type) + " index=" + Int((int)h.index) + " serial=" + Int((int)h.serial);
}

// rangedinfo <npc> [clearturret]: why a personal crossbow does (not) fire. Prints the turret hand, the
// ranged weapon, its GunClass (active, shots loaded, ammo type), hasAmmoFor, the ranged-mode flag and the
// RangedCombatClass state. clearturret empties Character::isUsingTurret when it holds no live turret.
bool RunRangedInfo(const std::vector<std::string> &f, Character *c, bool &ok, std::string &out) {
  std::string s = c->getName();
  bool turretLive = false;
  try {
    turretLive = c->isUsingTurret.getRootObject() != nullptr;
  } catch (...) {
  }
  s += " turret_hand={" + HandLine(c->isUsingTurret) + "} turret_valid=" + (c->isUsingTurret.isValid() ? "1" : "0") +
       " turret_live=" + (turretLive ? "1" : "0");
  bool cleared = false;
  if (f.size() > 3 && Lower(f[3]) == "clearturret" && !turretLive) {
    c->isUsingTurret = hand();
    cleared = true;
    s += " cleared_turret=1 turret_valid_now=" + std::string(c->isUsingTurret.isValid() ? "1" : "0");
  }
  Crossbow *bow = nullptr;
  try {
    bow = c->getRangedWeapon();
  } catch (...) {
  }
  s += " bow=" + std::string(Valid(bow) ? bow->getName() : "none");
  if (Valid(bow)) {
    GunClass *g = bow->gunClass;
    bool ammo = false;
    try {
      ammo = c->hasAmmoFor(bow);
    } catch (...) {
    }
    s += " has_ammo=" + std::string(ammo ? "1" : "0");
    if (g) {
      s += " gun_active=" + Int(g->active ? 1 : 0) + " shots=" + Int(g->numShotsCurrent) + "/" + Int(g->numShotsMax) +
           " ammo_type=" + (g->ammoType ? g->ammoType->name : std::string("none")) +
           " gun_user={" + HandLine(g->user) + "} reload_state=" + Fine(g->reloadState);
    } else
      s += " gun=null";
  }
  unsigned char *flag = UseRangedFlag(c);
  s += " ranged_mode=" + std::string(flag ? Int(*flag) : "?");
  try {
    s += " should_use_ranged=" + std::string(c->shouldUseRangedWeapons() ? "1" : "0") +
         " in_ranged_combat=" + (c->isInRangedCombatMode() ? "1" : "0");
  } catch (...) {
  }
  RangedCombatClass *rc = c->rangedCombat;
  if (rc)
    s += " rc_state=" + Int((int)rc->state) + " rc_gun=" + (rc->gun ? "set" : "null") +
         " rc_combat_mode=" + Int(rc->combatMode ? 1 : 0) + " rc_target={" + HandLine(rc->currentTarget) +
         "} rc_reloading=" + Int(rc->_isReloading ? 1 : 0);
  else
    s += " rc=null";
  CharStats *st = c->getStats();
  if (Valid(st))
    s += " crossbows=" + Fine(st->getStat(STAT_CROSSBOWS, true));
  Log("KAH: rangedinfo " + s);
  out = s;
  ok = true;
  (void)cleared;
  return true;
}

bool RunRangedCommand(GameWorld *world, const std::vector<std::string> &f, Character *c, bool &ok, bool &pending,
                      std::string &out) {
  if (Lower(f[1]) == "rangedinfo")
    return RunRangedInfo(f, c, ok, out);
  if (Lower(f[1]) != "rangedtest")
    return false;
  if (f.size() < 4) {
    out = "usage: rangedtest <shooter> <target> [shots <n>] [window <s>] [timeout <s>] [noheal] [noaim] [attack] "
          "[keepranged] | rangedtest <shooter> last";
    return true;
  }
  if (Lower(f[3]) == "last") {
    EnterCriticalSection(&g_rangedLock);
    std::map<unsigned long, RangedShooterLog>::const_iterator it = g_rangedByShooter.find(c->getHandle().serial);
    if (it == g_rangedByShooter.end())
      out = c->getName() + " has fired no shot since the game started";
    else {
      out = c->getName() + " shots=" + Int(it->second.shots) + " | last:" + RangedShotLine(it->second.last);
      ok = true;
    }
    LeaveCriticalSection(&g_rangedLock);
    return true;
  }
  Character *t = FindCharacter(world, f[3]);
  if (!Valid(t)) {
    out = NotFound(f[3]);
    return true;
  }
  if (t == c) {
    out = "rangedtest: shooter and target are the same character";
    return true;
  }
  RangedSession r;
  r.id = f[0];
  r.shooter = c->getHandle();
  r.target = t->getHandle();
  r.shooterName = c->getName();
  r.targetName = t->getName() + " " + FormatCharacterRef(t->getHandle().serial, t->getHandle().index);
  r.shooterSerial = c->getHandle().serial;
  r.targetSerial = t->getHandle().serial;
  r.wantShots = atoi(Option(f, 4, "shots", "10").c_str());
  r.window = atof(Option(f, 4, "window", "4").c_str());
  r.timeoutReal = (float)atof(Option(f, 4, "timeout", "240").c_str());
  if (r.wantShots < 1 || r.wantShots > 500 || !(r.window > 0.2 && r.window <= 30) ||
      !(r.timeoutReal >= 5 && r.timeoutReal <= 1800)) {
    out = "rangedtest: shots 1..500, window 0.2..30 sim s, timeout 5..1800 real s";
    return true;
  }
  r.heal = r.aim = true;
  bool attack = false, keepRanged = false;
  for (size_t k = 4; k < f.size(); ++k) {
    const std::string o = Lower(f[k]);
    if (o == "noheal")
      r.heal = false;
    else if (o == "noaim")
      r.aim = false;
    else if (o == "attack")
      attack = true;
    else if (o == "keepranged")
      keepRanged = true;
  }
  // hand::isValid() is true for an empty hand (type=11, serial 0): ask for the object instead.
  bool turretUser = false;
  try {
    turretUser = c->isUsingTurret.getRootObject() != nullptr;
  } catch (...) {
  }
  Crossbow *bow = nullptr;
  try {
    bow = c->getRangedWeapon();
  } catch (...) {
  }
  if (!turretUser && !Valid(bow)) {
    out = c->getName() + " has no crossbow (Character::getRangedWeapon) and is on no turret";
    return true;
  }
  r.rangedSet = false;
  r.rangedBefore = -1;
  unsigned char *flag = UseRangedFlag(c);
  std::string setup = " use_ranged_before=" + std::string(flag ? Int(*flag) : "?");
  if (!turretUser && !keepRanged && flag) {
    r.rangedBefore = *flag;
    *flag = 1;
    r.rangedSet = true;
  }
  try {
    setup += " should_use_ranged=" + std::string(c->shouldUseRangedWeapons() ? "1" : "0");
  } catch (...) {
  }
  if (attack) {
    RunBeforeAttack(c, t);
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!turretUser) {
      // a melee order (or Character::attackTarget) makes a crossbow user run in and fight unarmed
      if (Valid(orders))
        orders->addOrder(RANGED_ATTACK_FOCUSED_UNPROVOKED, t->getHandle(), t->getPosition(), true, false);
    } else {
      if (Valid(orders))
        orders->addOrder(UNPROVOKED_FOCUSED_MELEE_ATTACK, t->getHandle(), t->getPosition(), true, false);
      c->attackTarget(t);
    }
  }
  r.clock.Start();
  r.lastWounds = WoundSum(t);
  r.newShots = r.aimSets = r.heals = r.reloads = 0;
  r.prevLoaded = -1;
  r.sumAcc = r.sumDev = r.sumDevFormula = r.sumDist = r.sumWEff = r.sumPEff = 0;
  r.minDev = 1e9f;
  r.maxDev = -1;
  for (size_t i = 0; i < g_rangedSessions.size(); ++i)
    if (g_rangedSessions[i].shooterSerial == r.shooterSerial) {
      RangedRestore(g_rangedSessions[i]);
      WriteOutbox(g_rangedSessions[i].id, false, "replaced by a new rangedtest for " + r.shooterName);
      g_rangedSessions.erase(g_rangedSessions.begin() + i);
      break;
    }
  EnterCriticalSection(&g_rangedLock);
  g_rangedShots.clear(); // shots fired before this session don't count
  g_rangedSessions.push_back(r);
  LeaveCriticalSection(&g_rangedLock);
  Log("KAH: rangedtest " + r.shooterName + " -> " + r.targetName + " shots=" + Int(r.wantShots) +
      " window=" + Num(r.window) + " dist=" + Num(c->getPosition().distance(t->getPosition())) +
      " weapon=" + (turretUser ? std::string("turret") : bow->getName()) + setup + (attack ? " attack" : ""));
  pending = true; // answered by RangedTick
  ok = true;
  out = "";
  return true;
}
