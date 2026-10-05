// "turret" (KAH 25): a manned turret's real state, for the Turrets skill test
// (PG row 192). pg-55 once "passed" with three untouched dummies and once
// measured melee damage (the operator left the turret): the test needs proof
// that the turret itself fired at the dummy. Included into Commands.cpp inside
// its anonymous namespace, after BalanceCommands.inc.
//
// Shots: GunClass::shoot is hooked (Plugin.cpp); RecordGunShot counts every
// turret shot per gun and per target character (handle serial), with the
// shooter, the stat passed to the shot and the gun's userSkill01 at that time.

struct TurretShotStats {
  int shots;
  std::string lastTarget;
  std::string lastShooter;
  float lastSkill01;
  int lastStat;
  TurretShotStats() : shots(0), lastSkill01(-1), lastStat(-1) {}
};
std::map<GunClass *, TurretShotStats> g_turretShots;
std::map<unsigned long, int> g_shotsAtSerial;
int g_turretShotsTotal = 0;

void RecordGunShotImpl(GunClass *gun, Character *me, RootObject *target, int stat) {
  if (!gun || !gun->isTurret())
    return;
  TurretShotStats &s = g_turretShots[gun];
  ++s.shots;
  ++g_turretShotsTotal;
  s.lastStat = stat;
  s.lastSkill01 = gun->userSkill01;
  s.lastShooter = Valid(me) ? me->getName() : std::string("none");
  Character *tc = dynamic_cast<Character *>(target);
  if (Valid(tc)) {
    s.lastTarget = tc->getName() + " " + FormatCharacterRef(tc->getHandle().serial, tc->getHandle().index);
    ++g_shotsAtSerial[tc->getHandle().serial];
  } else {
    s.lastTarget = target ? "non-character" : "none";
  }
}

// "turret <b> aim <npc>": the operator's target. A passive dummy is never
// picked by the turret's own targeting (PG 192 probes: ranged=WAITING,
// ranged_target=none), and an `attack` order makes the operator leave the
// turret to melee it. Every frame (KeepTurretAim) each operator on that turret
// whose ranged combat target is not the character gets
// RangedCombatClass::setTarget(character) (forced_sets counts them); aiming,
// the shot check, accuracy, reload and damage stay the game's own. (A hook on
// RangedCombatClass::updateT made the game exit at the menu twice: dropped.)
struct TurretAim {
  bool on;
  hand turret;
  hand target;
  std::string targetName;
  int forcedSets;
  int updates;
  TurretAim() : on(false), forcedSets(0), updates(0) {}
};
// heap, not a global object: no game `hand` constructor runs while the DLL loads
TurretAim *g_turretAim = nullptr;

void KeepTurretAimImpl() {
  if (!g_turretAim || !g_turretAim->on)
    return;
  TurretBuilding *tb = dynamic_cast<TurretBuilding *>(g_turretAim->turret.getBuilding());
  Character *t = g_turretAim->target.getCharacter();
  if (!Valid(tb) || !Valid(t))
    return;
  for (auto it = tb->currentOperators.begin(); it != tb->currentOperators.end(); ++it) {
    Character *o = it->getCharacter();
    if (!Valid(o) || !SameHandle(o->isUsingTurret, g_turretAim->turret))
      continue;
    RangedCombatClass *rc = o->rangedCombat;
    if (!rc)
      continue;
    ++g_turretAim->updates;
    if (rc->currentTarget.getCharacter() != t) {
      rc->setTarget(t);
      ++g_turretAim->forcedSets;
    }
  }
}

const char *RangedStateName(int s) {
  static const char *const names[] = {"SHOOTING", "MOVING", "RELOADING", "WAITING", "THINKING"};
  return s >= 0 && s < 5 ? names[s] : "?";
}

std::string CharLabel(Character *c) {
  if (!Valid(c))
    return "none";
  try {
    return c->getName() + " " + FormatCharacterRef(c->getHandle().serial, c->getHandle().index);
  } catch (...) {
    return "?";
  }
}

bool RunTurretCommand(GameWorld *world, const std::vector<std::string> &f, const Ogre::Vector3 &origin,
                      bool &ok, std::string &out) {
  if (Lower(f[1]) != "turret")
    return false;
  // turret <building> [radius <m>] [target <npc>] [front <m>] [aim <npc>|off]
  if (f.size() < 3) {
    out = "usage: turret <building> [radius <m>] [target <npc>] [front <m>] [aim <npc>|off]";
    return true;
  }
  const float radius = (float)atof(Option(f, 3, "radius", "1500").c_str());
  float dist = 0;
  TurretBuilding *t = FindBuildingT<TurretBuilding>(world, origin, f[2], radius, dist);
  if (!Valid(t)) {
    out = "no turret matching '" + f[2] + "' within " + Num(radius) + " of the player";
    return true;
  }
  const Ogre::Vector3 tp = t->getPosition();
  out = t->getName() + " dist=" + Num(dist) + " pos=" + Num(tp.x) + "," + Num(tp.y) + "," + Num(tp.z);
  GunClass *g = t->gunClass;
  if (Valid(g)) {
    Character *user = g->user.getCharacter();
    out += " gun_active=" + std::string(g->isActive() ? "1" : "0") + " range=" + Num(g->maxRange) +
           " loaded=" + Int(g->numShotsCurrent) + "/" + Int(g->numShotsMax) +
           " reloading=" + (g->isReloading() ? "1" : "0") + " gun_user=" + CharLabel(user) +
           " skill01=" + Fine(g->userSkill01);
  } else {
    out += " gun=none";
  }
  out += " aim_err_deg=" + Num(t->aimDistInDegrees) + " root_dir=" + Fine(t->rootAimDir.x) + "," +
         Fine(t->rootAimDir.y) + "," + Fine(t->rootAimDir.z) + " aim_target=" + Num(t->currentAimTarget.x) + "," +
         Num(t->currentAimTarget.y) + "," + Num(t->currentAimTarget.z);

  // Operators: on the turret (Character::isUsingTurret), their ranged combat state and target.
  Character *op = nullptr;
  out += " operators=" + Int(t->currentOperators.size()) + "/" + Int(t->numOperatorsMax);
  for (auto it = t->currentOperators.begin(); it != t->currentOperators.end(); ++it) {
    Character *o = it->getCharacter();
    if (!Valid(o))
      continue;
    const bool on = SameHandle(o->isUsingTurret, t->getHandle());
    if (on && !op)
      op = o;
    out += " {op=" + o->getName() + " on_turret=" + (on ? "1" : "0") +
           " op_dist=" + Num(o->getPosition().distance(tp));
    RangedCombatClass *rc = o->rangedCombat;
    if (rc) {
      out += " ranged=" + std::string(RangedStateName((int)rc->state)) +
             " combat_mode=" + (rc->combatMode ? "1" : "0") + " ranged_target=" + CharLabel(rc->currentTarget.getCharacter());
    }
    out += " attack_target=" + CharLabel(o->getAttackTarget().getCharacter()) + "}";
  }
  out += " on_turret=" + std::string(op ? "1" : "0");

  TurretShotStats s;
  if (Valid(g) && g_turretShots.count(g))
    s = g_turretShots[g];
  out += " fired=" + Int(s.shots) + " last_shot_target=" + (s.shots ? s.lastTarget : "none") +
         " last_shot_by=" + (s.shots ? s.lastShooter : "none") + " last_shot_stat=" + Int(s.lastStat) +
         " last_shot_skill01=" + Fine(s.lastSkill01) + " all_turret_shots=" + Int(g_turretShotsTotal);

  const std::string aimArg = Option(f, 3, "aim", "");
  if (Lower(aimArg) == "off") {
    delete g_turretAim;
    g_turretAim = nullptr;
    out += " aim=off";
  } else if (!aimArg.empty()) {
    Character *x = FindCharacter(world, aimArg);
    if (!Valid(x)) {
      out += " aim=" + NotFound(aimArg);
      return true;
    }
    delete g_turretAim;
    g_turretAim = new TurretAim();
    g_turretAim->on = true;
    g_turretAim->turret = t->getHandle();
    g_turretAim->target = x->getHandle();
    g_turretAim->targetName = CharLabel(x);
  }
  if (g_turretAim && g_turretAim->on && SameHandle(g_turretAim->turret, t->getHandle()))
    out += " aim=" + g_turretAim->targetName +
           " aim_frames=" + Int(g_turretAim->updates) + " forced_sets=" + Int(g_turretAim->forcedSets);
  const std::string frontArg = Option(f, 3, "front", "");
  if (!frontArg.empty()) {
    const float m = (float)atof(frontArg.c_str());
    Ogre::Vector3 d(t->rootAimDir.x, 0, t->rootAimDir.z);
    if (d.length() < 0.01f)
      d = Ogre::Vector3(1, 0, 0);
    d.normalise();
    Ogre::Vector3 p = tp + d * m;
    float h = 0;
    if (TerrainHeight(p.x, p.z, h))
      p.y = h;
    out += " front=" + Num(p.x) + "," + Num(p.y) + "," + Num(p.z);
  }

  const std::string targetName = Option(f, 3, "target", "");
  if (!targetName.empty()) {
    Character *x = FindCharacter(world, targetName);
    if (!Valid(x)) {
      out += " target=" + NotFound(targetName);
      ok = true;
      return true;
    }
    const Ogre::Vector3 xp = x->getPosition();
    Ogre::Vector3 to(xp.x - tp.x, 0, xp.z - tp.z), root(t->rootAimDir.x, 0, t->rootAimDir.z);
    float angle = -1;
    if (to.length() > 0.01f && root.length() > 0.01f) {
      to.normalise();
      root.normalise();
      float c = to.dotProduct(root);
      if (c > 1)
        c = 1;
      if (c < -1)
        c = -1;
      angle = acos(c) * 57.29578f;
    }
    float ground = 0;
    const bool haveGround = TerrainHeight(xp.x, xp.z, ground);
    out += " target=" + CharLabel(x) + " target_dist=" + Num(xp.distance(tp)) + " target_dy=" + Num(xp.y - tp.y) +
           " target_above_ground=" + (haveGround ? Num(xp.y - ground) : std::string("?")) +
           " target_angle_deg=" + Num(angle);
    if (op && op->rangedCombat) {
      bool inRange = false;
      try {
        inRange = op->rangedCombat->isInRange(xp);
      } catch (...) {
      }
      out += " in_range=" + std::string(inRange ? "1" : "0");
    }
    out += " shots_at_target=" + Int(g_shotsAtSerial.count(x->getHandle().serial) ? g_shotsAtSerial[x->getHandle().serial] : 0);
    // Nearest player character to the target (a melee hit needs one next to it).
    PlayerInterface *pl = Player(world);
    float best = 1.0e9f;
    std::string bestName = "none";
    if (pl) {
      for (uint32_t i = 0; i < pl->playerCharacters.size(); ++i) {
        Character *pc = pl->playerCharacters[i];
        if (!Valid(pc))
          continue;
        const float d = pc->getPosition().distance(xp);
        if (d < best) {
          best = d;
          bestName = pc->getName();
        }
      }
    }
    out += " squad_nearest=" + bestName + " squad_dist=" + Num(best);
  }
  ok = true;
  return true;
}
