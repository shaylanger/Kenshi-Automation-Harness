// Measurement commands for skill-balance tests (KAH 24): the game's own
// chances (stealth KO, kidnap, lockpick, steal), sneaking detection timers,
// construction progress, first-aid timing and swimming. Included into
// Commands.cpp inside its anonymous namespace, after WorldCommands.inc.
//
// Character commands: RunBalanceCommand (f[2] already resolved as c).
// World commands:     RunBalanceWorldCommand.
// Timers (answered later, like walktime): BalanceTick, every frame.

// Simulated seconds: real frame time x game speed while unpaused.
struct SimClock {
  DWORD startTick, lastTick;
  double sim;
  void Start() {
    startTick = lastTick = GetTickCount();
    sim = 0;
  }
  void Tick(GameWorld *world) {
    const DWORD now = GetTickCount();
    const double dt = (now - lastTick) / 1000.0;
    lastTick = now;
    bool paused = true;
    float mult = 0;
    try {
      paused = world->isPaused();
      mult = world->getFrameSpeedMultiplier();
    } catch (...) {
    }
    if (!paused)
      sim += dt * mult;
  }
  float Real() const { return (GetTickCount() - startTick) / 1000.0f; }
};

const char *const kSeeStates[] = {"no", "yes", "maybe"};

std::string SeeState(int key) { return key >= 0 && key < 3 ? kSeeStates[key] : "?"; }

// The sneaker's detection entry for one observer (nullptr: none yet).
Character::WhoSeesMe *SeesMeEntry(Character *sneaker, const hand &observer) {
  ogre_unordered_map<hand, Character::WhoSeesMe>::type &m = sneaker->whoSeesMeSneaking;
  for (ogre_unordered_map<hand, Character::WhoSeesMe>::type::iterator it = m.begin(); it != m.end(); ++it)
    if (SameHandle(it->first, observer))
      return &it->second;
  return nullptr;
}

float FlatDistance(const Ogre::Vector3 &a, const Ogre::Vector3 &b) {
  const float dx = a.x - b.x, dz = a.z - b.z;
  return sqrt(dx * dx + dz * dz);
}

// --- detecttime: time until an observer notices a sneaking character.
struct DetectTimer {
  std::string id;
  hand sneaker, observer;
  std::string sName, oName;
  SimClock clock;
  double timeout;   // simulated seconds
  double firstMaybe, firstSeen;
  float maxProgress;
  float startDist;
};
std::vector<DetectTimer> g_detects;

// --- healtime: a medic's first aid on a patient, timed.
struct HealTimer {
  std::string id;
  hand medic, patient;
  std::string mName, pName;
  SimClock clock;
  double timeout;
  float needStart, bandStart, bandLast;
  double firstRise, lastRise;  // sim seconds of the first / last bandaging increase
};
std::vector<HealTimer> g_heals;

// --- swimtime: a timed move along an axis, with the water level sampled.
struct SwimTimer {
  std::string id;
  hand who;
  std::string name;
  Ogre::Vector3 start, target, lastPos;
  float dist;
  SimClock clock;
  double deepSeconds, wetSeconds;  // DEEP_WATER / any water
  float deepDist;                  // distance covered while in deep water
  int levelAtStart;
};
std::vector<SwimTimer> g_swims;

// Construction sites "construct" made this session.
std::vector<hand> g_sites;

float BandagingSum(Character *c) {
  float sum = 0;
  MedicalSystem &med = c->medical;
  const int count = med.getPartCount();
  for (int i = 0; i < count; ++i) {
    MedicalSystem::HealthPartStatus *p = med.getPart((unsigned __int64)i);
    if (Valid(p))
      sum += p->bandaging;
  }
  return sum;
}

float WoundSum(Character *c) {
  float sum = 0;
  MedicalSystem &med = c->medical;
  const int count = med.getPartCount();
  for (int i = 0; i < count; ++i) {
    MedicalSystem::HealthPartStatus *p = med.getPart((unsigned __int64)i);
    if (Valid(p)) {
      const float missing = p->maxHealth() - p->flesh;
      if (missing > 0)
        sum += missing;
    }
  }
  return sum;
}

float WaterDepth(float x, float z) {
  float ground = 0, top = 0;
  try {
    ground = UtilityT::getTerrainHeight(x, z);
    top = UtilityT::getTerrainWithWaterHeight(x, z);
  } catch (...) {
    return 0;
  }
  const float d = top - ground;
  return d == d && d > 0 && d < 1.0e5f ? d : 0.0f;
}

bool InWater(float x, float z) {
  try {
    return UtilityT::getPositionInWater(x, z);
  } catch (...) {
    return false;
  }
}

const char *const kWaterLevels[] = {"none", "very_shallow", "thigh_deep", "deep"};

int WaterLevelOf(Character *c) {
  try {
    return (int)c->getWaterLevel();
  } catch (...) {
    return -1;
  }
}

std::string WaterLevelName(int l) { return l >= 0 && l < 4 ? kWaterLevels[l] : "?"; }

std::string ConstructionLine(Building *b) {
  Building::ConstructionState *st = b->getBuildState();
  std::string out = b->getName() + " serial=" + Int(b->getHandle().serial);
  if (!Valid(st))
    return out + " no construction state";
  float hours = 0;
  try {
    hours = Building::ConstructionState::getBuildingTimeInHours(b->data);
  } catch (...) {
  }
  return out + " progress=" + Num(st->constructionProgress) + " complete=" + (st->isComplete ? "1" : "0") +
         " paused=" + (st->isPaused ? "1" : "0") + " mats=" + Num(st->getTotalMatsPresent()) + "/" +
         Num(st->getTotalMats()) + " needs_mats=" + (st->needMats() ? "1" : "0") +
         " builders_this_frame=" + Int(st->buildersThisFrame) + " build_time_mult=" + Num(st->buildTimeMult) +
         " build_hours=" + Num(hours);
}

// Puts every construction material in (the game's addMaterials, one unit per
// call), then any shortfall straight into the counters. Returns units added.
int FillConstruction(Building *b) {
  Building::ConstructionState *st = b->getBuildState();
  if (!Valid(st))
    return 0;
  int added = 0;
  for (uint32_t i = 0; i < st->mats.size(); ++i) {
    Building::ConstructionState::BuildMaterial *m = st->mats.stuff[i];
    if (!Valid(m) || !Valid(m->mat))
      continue;
    for (int guard = 0; guard < 500 && st->needsMat(m->mat) > 0; ++guard) {
      const float before = m->amountOfMaterials;
      st->addMaterials(m->mat);
      ++added;
      if (m->amountOfMaterials <= before)
        break;
    }
    if (m->amountOfMaterials < m->buildMatsTotal)
      m->amountOfMaterials = m->buildMatsTotal;
  }
  return added;
}

Building *FindSite(GameWorld *world, const Ogre::Vector3 &origin, const std::string &name, float radius,
                   float &dist) {
  const std::string needle = Lower(name);
  Building *best = nullptr;
  for (size_t i = 0; i < g_sites.size(); ++i) {
    Building *b = nullptr;
    try {
      b = g_sites[i].getBuilding();
    } catch (...) {
      b = nullptr;
    }
    if (!Valid(b) || Lower(b->getName()).find(needle) == std::string::npos)
      continue;
    const float d = FlatDistance(b->getPosition(), origin);
    if (d <= radius && (!best || d < dist)) {
      best = b;
      dist = d;
    }
  }
  if (best)
    return best;
  return FindBuildingT<Building>(world, origin, name, radius, dist);
}

// A lock to pick: a building's door lock, or locked gear (shackles) a character wears.
DoorLock *FindLock(GameWorld *world, Character *c, const std::string &target, float radius, std::string &label,
                   std::string &why) {
  Character *t = FindCharacter(world, target);
  if (t) {
    std::vector<Item *> items;
    ItemsOf(t->getInventory(), items);
    for (size_t i = 0; i < items.size(); ++i) {
      LockedArmour *la = dynamic_cast<LockedArmour *>(items[i]);
      if (Valid(la) && Valid(la->lock)) {
        label = t->getName() + " wearing " + la->getName();
        return la->lock;
      }
    }
    why = t->getName() + " wears nothing locked (shackle him first)";
    return nullptr;
  }
  float dist = 0;
  Building *b = FindBuildingT<Building>(world, c->getPosition(), target, radius, dist);
  if (!b) {
    why = NotFound(target) + ", and no building matching '" + target + "' within " + Num(radius);
    return nullptr;
  }
  if (!b->hasDoorLock() || !Valid(b->getDoorLock())) {
    why = b->getName() + " has no lock";
    return nullptr;
  }
  label = b->getName() + " (" + Num(dist) + " away)";
  return b->getDoorLock();
}

bool RunBalanceWorldCommand(GameWorld *world, const std::vector<std::string> &f, const Ogre::Vector3 &origin,
                            bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
  if (cmd == "towns") { // towns [filter[,filter...]] [max <n>]: towns, nests, ruins nearest the player
    std::vector<std::string> needles;
    const std::string filter = f.size() >= 3 && Lower(f[2]) != "max" ? Lower(f[2]) : "";
    for (size_t a = 0, b; a <= filter.size(); a = b + 1) {
      b = filter.find(',', a);
      if (b == std::string::npos)
        b = filter.size();
      if (b > a)
        needles.push_back(filter.substr(a, b - a));
    }
    int maxN = atoi(Option(f, 2, "max", "20").c_str());
    if (maxN < 1 || maxN > 200)
      maxN = 20;
    if (!Valid(shou) || !Valid(shou->townList)) {
      out = "no town list";
      return true;
    }
    lektor<RootObject *> &all = shou->townList->getAllTowns();
    std::vector<std::pair<float, TownBase *> > found;
    for (uint32_t i = 0; i < all.size(); ++i) {
      TownBase *t = dynamic_cast<TownBase *>(all.stuff[i]);
      if (!Valid(t))
        continue;
      std::string name;
      try {
        name = t->getName();
        if (Valid(t->data))
          name += " / " + t->data->name;
      } catch (...) {
        continue;
      }
      bool match = needles.empty();
      for (size_t k = 0; k < needles.size() && !match; ++k)
        match = Lower(name).find(needles[k]) != std::string::npos;
      if (match)
        found.push_back(std::make_pair(FlatDistance(t->getPosition(), origin), t));
    }
    std::sort(found.begin(), found.end());
    out = Int(found.size()) + " of " + Int(all.size()) + " towns match";
    for (size_t i = 0; i < found.size() && (int)i < maxN; ++i) {
      TownBase *t = found[i].second;
      const Ogre::Vector3 p = t->getPosition();
      out += " | " + Int(i + 1) + ": " + t->getName() + (Valid(t->data) ? " [" + t->data->name + "]" : std::string()) +
             " pos=" + Num(p.x) + "," + Num(p.y) + "," + Num(p.z) + " dist=" + Num(found[i].first);
    }
    ok = true;
    return true;
  }
  if (cmd == "construction") { // construction <building> [reset] [fill] [radius <m>]
    if (f.size() < 3) {
      out = "usage: construction <building> [reset] [fill] [radius <m>]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 3, 0, kDefaultSearchRadius, radius, out))
      return true;
    Building *b = FindSite(world, origin, f[2], radius, dist);
    if (!b) {
      out = "no building matching '" + f[2] + "' within " + Num(radius);
      return true;
    }
    bool reset = false, fill = false;
    for (size_t i = 3; i < f.size(); ++i) {
      if (Lower(f[i]) == "reset")
        reset = true;
      if (Lower(f[i]) == "fill")
        fill = true;
    }
    std::string note;
    if (reset) {
      Building::ConstructionState *st = b->getBuildState();
      if (Valid(st) && st->isComplete) {
        out = b->getName() + " is complete: reset only works on an unfinished site (use construct)";
        return true;
      }
      b->setConstructionProgress(0.0f);
      note += " reset";
    }
    if (reset || fill)
      note += " filled=" + Int(FillConstruction(b));
    ok = true;
    out = ConstructionLine(b) + " dist=" + Num(dist) + note;
    if (reset || fill)
      Log("KAH: construction " + out);
    return true;
  }
  return false;
}

bool RunBalanceCommand(GameWorld *world, const std::vector<std::string> &f, Character *c,
                       const Ogre::Vector3 &origin, bool &ok, bool &pending, std::string &out) {
  const std::string cmd = Lower(f[1]);

  if (cmd == "chance") { // chance <npc> ko|kidnap|lockpick|steal <target> [item <name>] [radius <m>]
    if (f.size() < 5) {
      out = "usage: chance <npc> ko|kidnap <npc2> | lockpick <building|shackled npc> | steal <npc|building> "
            "[item <name>] [radius <m>]";
      return true;
    }
    const std::string kind = Lower(f[3]);
    float radius = 0;
    if (!ParseSearchRadius(f, 5, 0, kDefaultSearchRadius, radius, out))
      return true;
    if (kind == "ko" || kind == "kidnap") {
      Character *t = FindCharacter(world, f[4]);
      if (!t) {
        out = NotFound(f[4]);
        return true;
      }
      if (kind == "ko")
        out = c->getName() + " stealth_ko_chance=" + Num(c->getStealthKOChance(t, true)) +
              " no_factors=" + Num(c->getStealthKOChance(t, false));
      else
        out = c->getName() + " kidnap_chance=" + Num(c->getKidnappingChance(t));
      out += " target=" + t->getName() + " dist=" + Num(FlatDistance(c->getPosition(), t->getPosition())) +
             " sneaking=" + (c->isStealthMode() ? "1" : "0");
      ok = true;
      return true;
    }
    if (kind == "lockpick") {
      std::string label, why;
      DoorLock *lock = FindLock(world, c, f[4], radius, label, why);
      if (!lock) {
        out = why;
        return true;
      }
      out = c->getName() + " lockpick_chance=" + Num(c->getLockpickChance(lock)) + " lock=" + label;
      ok = true;
      return true;
    }
    if (kind == "steal") {
      RootObject *from = nullptr;
      Inventory *inv = nullptr;
      std::string label;
      Character *t = FindCharacter(world, f[4]);
      if (t) {
        from = t;
        inv = t->getInventory();
        label = t->getName();
      } else {
        float dist = 0;
        Building *b = FindBuildingT<Building>(world, c->getPosition(), f[4], radius, dist);
        if (!b) {
          out = NotFound(f[4]) + ", and no building matching '" + f[4] + "' within " + Num(radius);
          return true;
        }
        from = b;
        inv = b->getInventory();
        label = b->getName() + " (" + Num(dist) + " away)";
      }
      std::vector<Item *> items;
      ItemsOf(inv, items);
      const std::string wanted = Lower(Option(f, 5, "item", ""));
      Item *item = nullptr;
      for (size_t i = 0; i < items.size() && !item; ++i)
        if (wanted.empty() || Lower(items[i]->getName()).find(wanted) != std::string::npos)
          item = items[i];
      if (!item) {
        out = label + " has no item" + (wanted.empty() ? std::string("") : " matching '" + wanted + "'") +
              " (" + Int(items.size()) + " items)";
        return true;
      }
      Character *victim = nullptr;
      const float chance = c->getStealingSuccessChance(from, item, &victim);
      out = c->getName() + " steal_chance=" + Num(chance) + " item=" + item->getName() + " from=" + label +
            " victim=" + (Valid(victim) ? victim->getName() : std::string("none"));
      ok = true;
      return true;
    }
    out = "unknown chance kind: " + f[3] + " (ko, kidnap, lockpick, steal)";
    return true;
  }

  if (cmd == "detect") { // detect <sneaker>: who notices him sneaking, as the game tracks it
    std::string list;
    int n = 0;
    ogre_unordered_map<hand, Character::WhoSeesMe>::type &m = c->whoSeesMeSneaking;
    for (ogre_unordered_map<hand, Character::WhoSeesMe>::type::iterator it = m.begin(); it != m.end(); ++it) {
      Character *o = nullptr;
      try {
        o = it->first.getCharacter();
      } catch (...) {
        o = nullptr;
      }
      ++n;
      list += " {" + (Valid(o) ? o->getName() + " dist=" + Num(FlatDistance(o->getPosition(), c->getPosition()))
                               : std::string("?")) +
              " state=" + SeeState((int)it->second.seeState.key) + " progress=" + Num(it->second.progressOfMaybe) +
              " updated=" + Num(it->second.lastUpdated) + "}";
    }
    ok = true;
    out = c->getName() + " stealth_mode=" + (c->isStealthMode() ? "1" : "0") + " observers=" + Int(n) + list;
    return true;
  }

  if (cmd == "detecttime") { // detecttime <sneaker> <observer> [timeout <sim s>]
    if (f.size() < 4) {
      out = "usage: detecttime <sneaker> <observer> [timeout <game seconds, default 120>]";
      return true;
    }
    Character *o = FindCharacter(world, f[3]);
    if (!o) {
      out = NotFound(f[3]);
      return true;
    }
    if (o == c) {
      out = "sneaker and observer are the same character";
      return true;
    }
    DetectTimer d;
    d.id = f[0];
    d.sneaker = c->getHandle();
    d.observer = o->getHandle();
    d.sName = c->getName();
    d.oName = o->getName();
    d.timeout = atof(Option(f, 4, "timeout", "120").c_str());
    if (!(d.timeout > 0 && d.timeout <= 3600))
      d.timeout = 120;
    d.firstMaybe = d.firstSeen = -1;
    d.maxProgress = 0;
    d.startDist = FlatDistance(c->getPosition(), o->getPosition());
    c->setStealthMode(true);
    // An earlier sighting would end the timer at once: start from "not seen".
    Character::WhoSeesMe *e = SeesMeEntry(c, d.observer);
    if (e) {
      e->seeState.key = YesNoMaybe::NO;
      e->progressOfMaybe = 0;
    }
    d.clock.Start();
    for (size_t i = 0; i < g_detects.size(); ++i)
      if (SameHandle(g_detects[i].sneaker, d.sneaker)) {
        WriteOutbox(g_detects[i].id, false, "replaced by a new detecttime for " + d.sName);
        g_detects.erase(g_detects.begin() + i);
        break;
      }
    g_detects.push_back(d);
    Log("KAH: detecttime " + d.sName + " observer=" + d.oName + " dist=" + Num(d.startDist) +
        " entry_reset=" + (e ? "1" : "0"));
    pending = true;
    ok = true;
    return true;
  }

  if (cmd == "healtime") { // healtime <medic> <patient> [wound <cut>] [timeout <sim s>]
    if (f.size() < 4) {
      out = "usage: healtime <medic> <patient> [wound <cut per part>] [timeout <game seconds, default 600>]";
      return true;
    }
    Character *p = FindCharacter(world, f[3]);
    if (!p) {
      out = NotFound(f[3]);
      return true;
    }
    if (c->isUnconcious() || c->isDead()) {
      out = c->getName() + " can't treat anyone (KO or dead)";
      return true;
    }
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders)) {
      out = c->getName() + " takes no orders";
      return true;
    }
    const std::string wound = Option(f, 4, "wound", "");
    if (!wound.empty()) {
      // The same fixed wound every time: full health, no bandages, then a cut
      // on chest, left arm and right leg (no bleeding, blood full).
      const float cut = (float)atof(wound.c_str());
      if (!(cut > 0)) {
        out = "wound <cut> must be above 0";
        return true;
      }
      SetAllParts(p, 1.0f);
      MedicalSystem &med = p->medical;
      const int count = med.getPartCount();
      for (int i = 0; i < count; ++i) {
        MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)i);
        if (Valid(part))
          part->bandaging = 0;
      }
      const int parts[] = {1, 3, 6};
      for (int i = 0; i < 3; ++i) {
        MedicalSystem::HealthPartStatus *part = med.getPart((unsigned __int64)parts[i]);
        if (Valid(part))
          part->applyDamage(Damages(cut, 0.0f, 0.0f, 0.0f, 0.0f));
      }
      med.blood = med.getMaxBlood();
    }
    HealTimer h;
    h.id = f[0];
    h.medic = c->getHandle();
    h.patient = p->getHandle();
    h.mName = c->getName();
    h.pName = p->getName();
    h.timeout = atof(Option(f, 4, "timeout", "600").c_str());
    if (!(h.timeout > 0 && h.timeout <= 7200))
      h.timeout = 600;
    h.needStart = p->medical.scoreFirstAidNeed(false);
    h.bandStart = h.bandLast = BandagingSum(p);
    h.firstRise = h.lastRise = -1;
    h.clock.Start();
    orders->addOrder(FIRST_AID_ORDER, p->getHandle(), p->getPosition(), true, false);
    for (size_t i = 0; i < g_heals.size(); ++i)
      if (SameHandle(g_heals[i].medic, h.medic)) {
        WriteOutbox(g_heals[i].id, false, "replaced by a new healtime for " + h.mName);
        g_heals.erase(g_heals.begin() + i);
        break;
      }
    g_heals.push_back(h);
    Log("KAH: healtime " + h.mName + " -> " + h.pName + " need=" + Num(h.needStart) + " wounds=" +
        Num(WoundSum(p)) + " bandaging=" + Num(h.bandStart));
    pending = true;
    ok = true;
    return true;
  }

  if (cmd == "water") { // water <npc>: water level at him and the depth there
    const Ogre::Vector3 p = c->getPosition();
    ok = true;
    out = c->getName() + " water_level=" + WaterLevelName(WaterLevelOf(c)) + " depth=" + Num(WaterDepth(p.x, p.z)) +
          " in_water=" + (InWater(p.x, p.z) ? "1" : "0") + " pos=" + Num(p.x) + "," + Num(p.y) + "," + Num(p.z);
    return true;
  }

  if (cmd == "findwater") { // findwater <npc> [radius <m>] [depth <m>]: nearest deep water + straight runs
    const float radius = (float)atof(Option(f, 3, "radius", "1000").c_str());
    const float depth = (float)atof(Option(f, 3, "depth", "1.5").c_str());
    if (!(radius > 0 && radius <= 5000) || !(depth > 0)) {
      out = "usage: findwater <npc> [radius <m, 1..5000, default 1000>] [depth <m, default 1.5>]";
      return true;
    }
    const Ogre::Vector3 at = c->getPosition();
    const float step = radius / 150.0f > 4.0f ? radius / 150.0f : 4.0f;
    bool found = false;
    float bx = 0, bz = 0, bd = 0, best = 0;
    int samples = 0, wet = 0;
    for (float dx = -radius; dx <= radius; dx += step)
      for (float dz = -radius; dz <= radius; dz += step) {
        const float r = sqrt(dx * dx + dz * dz);
        if (r > radius || (found && r >= best))
          continue;
        ++samples;
        const float x = at.x + dx, z = at.z + dz;
        if (!InWater(x, z))
          continue;
        ++wet;
        const float d = WaterDepth(x, z);
        if (d >= depth) {
          found = true;
          best = r;
          bx = x;
          bz = z;
          bd = d;
        }
      }
    if (!found) {
      ok = true; // an answer, not a failure: there is no such water here
      out = "no water deeper than " + Num(depth) + " m within " + Num(radius) + " m of " + c->getName() +
            " (samples=" + Int(samples) + " wet=" + Int(wet) + ")";
      return true;
    }
    // Straight runs of deep-enough water from that point, 2 m steps, up to 500 m.
    static const float dirs[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
    static const char *const dirNames[4] = {"+x", "-x", "+z", "-z"};
    std::string runs;
    int bestDir = 0;
    float bestRun = -1;
    for (int k = 0; k < 4; ++k) {
      float len = 0;
      while (len < 500) {
        const float x = bx + dirs[k][0] * (len + 2), z = bz + dirs[k][1] * (len + 2);
        if (!InWater(x, z) || WaterDepth(x, z) < depth)
          break;
        len += 2;
      }
      runs += std::string(" ") + dirNames[k] + "=" + Num(len);
      if (len > bestRun) {
        bestRun = len;
        bestDir = k;
      }
    }
    float surface = 0;
    try {
      surface = UtilityT::getTerrainWithWaterHeight(bx, bz);
    } catch (...) {
    }
    ok = true;
    out = "water at " + Num(bx) + " " + Num(surface) + " " + Num(bz) + " depth=" + Num(bd) + " dist=" + Num(best) +
          " runs" + runs + " best=" + dirNames[bestDir] + " best_run=" + Num(bestRun) + " (teleport <npc> x y z there, then swimtime along the longest run)";
    return true;
  }

  if (cmd == "swimtime") { // swimtime <npc> <dist> [+x|-x|+z|-z] [walk|run]
    const float dist = f.size() >= 4 ? (float)atof(f[3].c_str()) : 0.0f;
    if (!(dist >= 2.0f && dist <= 500.0f)) {
      out = "usage: swimtime <npc> <dist 2..500> [+x|-x|+z|-z] [walk|run]";
      return true;
    }
    if (c->isUnconcious() || c->isDead()) {
      out = c->getName() + " can't swim (KO or dead)";
      return true;
    }
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders)) {
      out = c->getName() + " takes no orders";
      return true;
    }
    Ogre::Vector3 dir(1, 0, 0);
    std::string mode;
    for (size_t i = 4; i < f.size(); ++i) {
      const std::string a = Lower(f[i]);
      if (a == "+x" || a == "x")
        dir = Ogre::Vector3(1, 0, 0);
      else if (a == "-x")
        dir = Ogre::Vector3(-1, 0, 0);
      else if (a == "+z" || a == "z")
        dir = Ogre::Vector3(0, 0, 1);
      else if (a == "-z")
        dir = Ogre::Vector3(0, 0, -1);
      else if (a == "walk" || a == "run")
        mode = a;
    }
    CharMovement *m = c->movement;
    if (Valid(m) && !mode.empty())
      m->setDesiredSpeedOrders(mode == "walk" ? WALK : RUN);
    SwimTimer s;
    s.id = f[0];
    s.who = c->getHandle();
    s.name = c->getName();
    s.start = s.lastPos = c->getPosition();
    s.target = s.start + dir * dist;
    s.dist = dist;
    s.deepSeconds = s.wetSeconds = 0;
    s.deepDist = 0;
    s.levelAtStart = WaterLevelOf(c);
    s.clock.Start();
    orders->clearOrders();
    orders->addOrder(MOVE_CUS_ORDERED, hand(), s.target, true, false);
    for (size_t i = 0; i < g_swims.size(); ++i)
      if (SameHandle(g_swims[i].who, s.who)) {
        WriteOutbox(g_swims[i].id, false, "replaced by a new swimtime for " + s.name);
        g_swims.erase(g_swims.begin() + i);
        break;
      }
    g_swims.push_back(s);
    Log("KAH: swimtime " + s.name + " dist=" + Num(dist) + " water_level=" + WaterLevelName(s.levelAtStart));
    pending = true;
    ok = true;
    return true;
  }

  if (cmd == "construct") { // construct <npc> <building name|sid> [dist m] [faction <f>]
    if (f.size() < 4) {
      out = "usage: construct <npc> <building name|sid> [dist <m, default 12>]";
      return true;
    }
    std::string error;
    GameData *data = FindData(world, BUILDING, f[3], error);
    if (!data) {
      out = error;
      return true;
    }
    const std::string why = BuildRefusal(data);
    if (!why.empty()) {
      out = "refused: " + data->name + " (" + data->stringID + ") " + why;
      return true;
    }
    float dist = (float)atof(Option(f, 4, "dist", "12").c_str());
    if (!(dist >= 0 && dist <= 200))
      dist = 12;
    Faction *owner = world->player->getFaction();
    Ogre::Vector3 pos = c->getPosition();
    pos.x += dist;
    // Same height handling as "build": the factory adds the terrain height.
    const float wantY = pos.y;
    float terrain = 0;
    const bool haveTerrain = TerrainHeight(pos.x, pos.z, terrain);
    const float targetY = haveTerrain && fabs(terrain - wantY) <= 20.0f ? terrain : wantY;
    pos.y = haveTerrain ? targetY - terrain : targetY;
    Building *b = world->theFactory->createBuilding(data, pos, nullptr, owner, Ogre::Quaternion::IDENTITY, nullptr,
                                                    nullptr, nullptr, nullptr, nullptr, false, false, false, 0,
                                                    false);
    if (!Valid(b)) {
      out = "the game could not create a construction site for " + data->name;
      return true;
    }
    g_sites.push_back(b->getHandle());
    g_built.push_back(b->getHandle()); // unbuild may remove it
    const int filled = FillConstruction(b);
    c->addJob(BUILD, b, true, true, b->getPosition());
    OrdersReceiver *orders = c->getOrdersReciever();
    const bool job = Valid(orders) && orders->hasPermajob(BUILD);
    ok = true;
    const Ogre::Vector3 bp = b->getPosition();
    out = "site " + ConstructionLine(b) + " pos=" + Num(bp.x) + "," + Num(bp.y) + "," + Num(bp.z) +
          " filled=" + Int(filled) + " builder=" + c->getName() + " job=" + (job ? "BUILD" : "none");
    Log("KAH: construct " + out);
    return true;
  }

  return false;
}

void BalanceTick(GameWorld *world) {
  for (size_t i = 0; i < g_detects.size();) {
    DetectTimer &d = g_detects[i];
    d.clock.Tick(world);
    Character *s = nullptr, *o = nullptr;
    try {
      s = d.sneaker.getCharacter();
      o = d.observer.getCharacter();
    } catch (...) {
    }
    std::string done;
    bool okDone = false;
    if (!Valid(s) || !Valid(o)) {
      done = "sneaker or observer is gone (unloaded or a load)";
    } else {
      Character::WhoSeesMe *e = SeesMeEntry(s, d.observer);
      if (e) {
        const int st = (int)e->seeState.key;
        if (e->progressOfMaybe > d.maxProgress)
          d.maxProgress = e->progressOfMaybe;
        if (st == YesNoMaybe::MAYBE && d.firstMaybe < 0)
          d.firstMaybe = d.clock.sim;
        if (st == YesNoMaybe::YES && d.firstSeen < 0) {
          d.firstSeen = d.clock.sim;
          if (d.firstMaybe < 0)
            d.firstMaybe = d.clock.sim;
        }
      }
      const bool timedOut = d.clock.sim >= d.timeout || d.clock.Real() > 180.0f;
      if (d.firstSeen >= 0 || timedOut) {
        okDone = true;
        float los = 0, pmult = 0;
        try {
          los = o->lineOfSightCheck(s);
          pmult = o->getPerceptionMult();
        } catch (...) {
        }
        done = d.sName + " seen_by=" + d.oName + " seen=" + (d.firstSeen >= 0 ? "1" : "0") +
               " seconds_to_seen=" + (d.firstSeen >= 0 ? Num((float)d.firstSeen) : std::string("none")) +
               " seconds_to_maybe=" + (d.firstMaybe >= 0 ? Num((float)d.firstMaybe) : std::string("none")) +
               " max_progress=" + Num(d.maxProgress) + " seconds=" + Num((float)d.clock.sim) +
               " timeout=" + Num((float)d.timeout) + " dist=" + Num(FlatDistance(s->getPosition(), o->getPosition())) +
               " start_dist=" + Num(d.startDist) + " stealth_mode=" + (s->isStealthMode() ? "1" : "0") +
               " los=" + Num(los) + " observer_perception_mult=" + Num(pmult) +
               " real_seconds=" + Num(d.clock.Real());
      }
    }
    if (!done.empty()) {
      Log("KAH: detecttime " + done);
      WriteOutbox(d.id, okDone, done);
      g_detects.erase(g_detects.begin() + i);
    } else {
      ++i;
    }
  }

  for (size_t i = 0; i < g_heals.size();) {
    HealTimer &h = g_heals[i];
    h.clock.Tick(world);
    Character *m = nullptr, *p = nullptr;
    try {
      m = h.medic.getCharacter();
      p = h.patient.getCharacter();
    } catch (...) {
    }
    std::string done;
    bool okDone = false;
    if (!Valid(m) || !Valid(p)) {
      done = "medic or patient is gone (unloaded or a load)";
    } else {
      const float band = BandagingSum(p);
      if (band > h.bandLast + 1e-4f) {
        if (h.firstRise < 0)
          h.firstRise = h.clock.sim;
        h.lastRise = h.clock.sim;
      }
      h.bandLast = band;
      const float need = p->medical.scoreFirstAidNeed(false);
      // Finished: bandaging rose and then stood still for 10 game seconds.
      const bool settled = h.firstRise >= 0 && h.clock.sim - h.lastRise >= 10.0;
      const bool timedOut = h.clock.sim >= h.timeout || h.clock.Real() > 180.0f;
      if (settled || timedOut) {
        okDone = h.firstRise >= 0;
        const double active = h.firstRise >= 0 ? h.lastRise - h.firstRise : 0;
        done = h.mName + " treated " + h.pName + " finished=" + (settled ? "1" : "0") +
               " seconds_to_first_bandage=" + (h.firstRise >= 0 ? Num((float)h.firstRise) : std::string("none")) +
               " seconds_bandaging=" + Num((float)active) + " bandaging " + Num(h.bandStart) + " -> " + Num(band) +
               " bandage_rate=" + Num(active > 0 ? (float)((band - h.bandStart) / active) : 0.0f) +
               " need " + Num(h.needStart) + " -> " + Num(need) + " wounds=" + Num(WoundSum(p)) +
               " seconds=" + Num((float)h.clock.sim) + " real_seconds=" + Num(h.clock.Real());
        if (!okDone)
          done += " (no bandaging at all: no first aid kit on the medic, or he never reached the patient?)";
      }
    }
    if (!done.empty()) {
      Log("KAH: healtime " + done);
      WriteOutbox(h.id, okDone, done);
      g_heals.erase(g_heals.begin() + i);
    } else {
      ++i;
    }
  }

  for (size_t i = 0; i < g_swims.size();) {
    SwimTimer &s = g_swims[i];
    const double before = s.clock.sim;
    s.clock.Tick(world);
    const double dt = s.clock.sim - before;
    Character *c = nullptr;
    try {
      c = s.who.getCharacter();
    } catch (...) {
    }
    std::string done;
    bool okDone = false;
    if (!Valid(c)) {
      done = s.name + " is gone (unloaded or a load)";
    } else {
      const Ogre::Vector3 p = c->getPosition();
      const int level = WaterLevelOf(c);
      const float step = FlatDistance(p, s.lastPos);
      s.lastPos = p;
      if (level >= 1)
        s.wetSeconds += dt;
      if (level == 3) {
        s.deepSeconds += dt;
        s.deepDist += step;
      }
      const float covered = FlatDistance(p, s.start);
      if (covered >= s.dist - 1.0f || FlatDistance(p, s.target) < 1.5f) {
        okDone = true;
        done = s.name + " swam " + Num(covered) + " m seconds=" + Num((float)s.clock.sim) +
               " speed=" + Num(s.clock.sim > 0 ? (float)(covered / s.clock.sim) : 0.0f) +
               " m/s deep_seconds=" + Num((float)s.deepSeconds) + " deep_dist=" + Num(s.deepDist) +
               " swim_speed=" + Num(s.deepSeconds > 0 ? (float)(s.deepDist / s.deepSeconds) : 0.0f) +
               " deep_fraction=" + Num(s.clock.sim > 0 ? (float)(s.deepSeconds / s.clock.sim) : 0.0f) +
               " wet_seconds=" + Num((float)s.wetSeconds) + " start_level=" + WaterLevelName(s.levelAtStart) +
               " end_level=" + WaterLevelName(level) + " real_seconds=" + Num(s.clock.Real());
      } else if (s.clock.Real() > 180.0f) {
        done = s.name + " did not arrive within 180 s (covered " + Num(covered) + " of " + Num(s.dist) +
               " m, seconds=" + Num((float)s.clock.sim) + ", deep_seconds=" + Num((float)s.deepSeconds) + ")";
      }
    }
    if (!done.empty()) {
      Log("KAH: swimtime " + done);
      WriteOutbox(s.id, okDone, done);
      g_swims.erase(g_swims.begin() + i);
    } else {
      ++i;
    }
  }
}
