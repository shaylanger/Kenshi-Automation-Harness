// "steady" (KenshiFP R11-RACE, 2026-10-11): hold a shooting target's pose still between shots.
// A target hit by a bolt plays a hit reaction (stumble) and, hostile and shot at, drops into its combat stance:
// a Shek's head bone moved 18.7 -> 13.5..16.7 dm between the aim and the impact on 10 of 12 hits even while
// `pin` + `protect` + `combatmode passive` held it (xbf-r11d, R11-RACE SETUP FAIL pose_unstable). For a steady
// character the harness
//   - skips Character::_startStumble (hook in Plugin.cpp: the hit reaction never starts; count `blocked`),
//   - ends a stumble that started another way every frame (AnimationClass::endStumble; count `ended`),
//   - with `nocombat`, ends its combat mode every frame (Character::endCombatMode; count `combat_ended`), so it
//     stands in its idle pose, not the crouched combat stance.
// Damage, wounds, the hit part, KO and death are untouched (that is what the shooting rows judge); only the
// pose reaction is held. Not saved; the list is cleared on a load. Included into Commands.cpp inside its
// anonymous namespace, after RangedCommands.inc. The hook may run off the main thread: it reads the serial
// list under g_steadyLock and counts with Interlocked increments.

struct SteadyEntry {
  hand who;
  unsigned long serial;
  std::string name;
  bool nocombat;
  volatile LONG blocked; // _startStumble calls skipped (hook)
  int ended;             // stumbles ended by the tick
  int combatEnded;       // endCombatMode calls by the tick (nocombat)
};
std::vector<SteadyEntry *> g_steady; // pointers: the hook keeps one while the vector may grow
CRITICAL_SECTION g_steadyLock;
struct SteadyLockInit {
  SteadyLockInit() { InitializeCriticalSection(&g_steadyLock); }
} g_steadyLockInit;

bool SteadyBlocksStumbleImpl(Character *c) {
  if (!c)
    return false;
  unsigned long serial = 0;
  try {
    serial = c->getHandle().serial;
  } catch (...) {
    return false;
  }
  bool hit = false;
  EnterCriticalSection(&g_steadyLock);
  for (size_t i = 0; i < g_steady.size(); ++i)
    if (g_steady[i]->serial == serial) {
      InterlockedIncrement(&g_steady[i]->blocked);
      hit = true;
      break;
    }
  LeaveCriticalSection(&g_steadyLock);
  return hit;
}

std::string SteadyLine(const SteadyEntry &e, Character *c) {
  std::string s = e.name + " steady blocked=" + Int((int)e.blocked) + " ended=" + Int(e.ended) +
                  " combat_ended=" + Int(e.combatEnded) + " nocombat=" + Int(e.nocombat ? 1 : 0);
  if (Valid(c)) {
    bool stumbling = false, combat = false;
    try {
      AnimationClass *a = c->getAnimationClass();
      stumbling = Valid(a) && a->currentlyStumbling();
      combat = c->isInCombatMode(true, true);
    } catch (...) {
    }
    s += std::string(" stumbling=") + (stumbling ? "1" : "0") + " combat=" + (combat ? "1" : "0");
  }
  return s;
}

void SteadyTick(GameWorld *world) {
  for (size_t i = 0; i < g_steady.size();) {
    SteadyEntry *e = g_steady[i];
    Character *c = nullptr;
    try {
      c = e->who.getCharacter();
    } catch (...) {
      c = nullptr;
    }
    if (!Valid(c) || c->isDead()) {
      Log("KAH: steady " + e->name + " is gone or dead, dropped: " + SteadyLine(*e, nullptr));
      EnterCriticalSection(&g_steadyLock);
      g_steady.erase(g_steady.begin() + i);
      LeaveCriticalSection(&g_steadyLock);
      delete e;
      continue;
    }
    try {
      AnimationClass *a = c->getAnimationClass();
      if (Valid(a) && a->currentlyStumbling()) {
        a->endStumble();
        ++e->ended;
      }
      if (e->nocombat && c->isInCombatMode(true, true)) {
        c->endCombatMode();
        ++e->combatEnded;
      }
    } catch (...) {
    }
    ++i;
  }
}

void SteadyClearOnLoad() {
  if (g_steady.empty())
    return;
  Log("KAH: steady list cleared by the load (" + Int((int)g_steady.size()) + ")");
  EnterCriticalSection(&g_steadyLock);
  std::vector<SteadyEntry *> old;
  old.swap(g_steady);
  LeaveCriticalSection(&g_steadyLock);
  for (size_t i = 0; i < old.size(); ++i)
    delete old[i];
}

// steady <npc> [on [nocombat] | off]: no argument = the counts.
bool RunSteady(const std::vector<std::string> &f, Character *c, bool &ok, std::string &out) {
  const unsigned long serial = c->getHandle().serial;
  SteadyEntry *cur = nullptr;
  size_t at = 0;
  for (size_t i = 0; i < g_steady.size(); ++i)
    if (g_steady[i]->serial == serial) {
      cur = g_steady[i];
      at = i;
    }
  const std::string v = f.size() > 3 ? Lower(f[3]) : "";
  if (v.empty()) {
    out = cur ? SteadyLine(*cur, c) : c->getName() + " steady off";
    ok = true;
    return true;
  }
  if (v == "off") {
    if (!cur) {
      out = c->getName() + " was not steady";
      ok = true;
      return true;
    }
    out = SteadyLine(*cur, c) + " -> off";
    EnterCriticalSection(&g_steadyLock);
    g_steady.erase(g_steady.begin() + at);
    LeaveCriticalSection(&g_steadyLock);
    delete cur;
    Log("KAH: steady " + out);
    ok = true;
    return true;
  }
  if (v != "on" || (f.size() > 4 && Lower(f[4]) != "nocombat") || f.size() > 5) {
    out = "usage: steady <npc> [on [nocombat] | off]";
    return true;
  }
  const bool nocombat = f.size() > 4;
  if (cur) {
    cur->nocombat = nocombat;
  } else {
    cur = new SteadyEntry();
    cur->who = c->getHandle();
    cur->serial = serial;
    cur->name = c->getName() + " " + FormatCharacterRef(serial, c->getHandle().index);
    cur->nocombat = nocombat;
    cur->blocked = 0;
    cur->ended = 0;
    cur->combatEnded = 0;
    EnterCriticalSection(&g_steadyLock);
    g_steady.push_back(cur);
    LeaveCriticalSection(&g_steadyLock);
  }
  out = SteadyLine(*cur, c);
  Log("KAH: steady on " + out);
  ok = true;
  return true;
}
