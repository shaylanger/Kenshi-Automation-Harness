// World commands (TEST ONLY): AI orders and fights, jobs, buildings (power,
// inputs, production), game time, trading, character state (name, faction,
// sleep, wounds, shackles, cages) and UI inspection. Included by
// Commands.cpp inside its anonymous namespace (uses its helpers).

#include "TaskNames.inc"

const int kTaskCount = (int)(sizeof(kTaskNames) / sizeof(kTaskNames[0]));

// A TaskType by name (case-insensitive, e.g. first_aid_order) or number.
bool ParseTask(const std::string &text, TaskType &out) {
  char *end = nullptr;
  long n = strtol(text.c_str(), &end, 10);
  if (!text.empty() && end && !*end) {
    if (n < 0 || n >= kTaskCount)
      return false;
    out = (TaskType)n;
    return true;
  }
  const std::string wanted = Lower(text);
  for (int i = 0; i < kTaskCount; ++i)
    if (Lower(kTaskNames[i]) == wanted) {
      out = (TaskType)i;
      return true;
    }
  return false;
}

std::string TaskName(int t) {
  return t >= 0 && t < kTaskCount ? std::string(kTaskNames[t]) : "task " + Int(t);
}

// Nearest building whose name contains `name` (an exact name wins) within
// `radius` of `at`; with `cls` the building must also be that class.
template <class T>
T *FindBuildingT(GameWorld *world, const Ogre::Vector3 &at, const std::string &name, float radius,
                 float &dist) {
  lektor<RootObject *> nearby;
  world->getObjectsWithinSphere(nearby, at, radius, BUILDING, 1024, nullptr);
  const std::string wanted = Lower(name);
  T *exact = nullptr, *partial = nullptr;
  float exactDist = 0, partialDist = 0;
  for (uint32_t i = 0; i < nearby.size(); ++i) {
    T *b = dynamic_cast<T *>(nearby.stuff[i]);
    if (!Valid(b))
      continue;
    std::string bn;
    float d = 0;
    try {
      bn = Lower(b->getName());
      d = b->getPosition().distance(at);
    } catch (...) {
      continue;
    }
    if (bn == wanted) {
      if (!exact || d < exactDist) {
        exact = b;
        exactDist = d;
      }
    } else if (wanted.empty() || bn.find(wanted) != std::string::npos) {
      if (!partial || d < partialDist) {
        partial = b;
        partialDist = d;
      }
    }
  }
  dist = exact ? exactDist : partialDist;
  return exact ? exact : partial;
}

Building *FindBuilding(GameWorld *world, const Ogre::Vector3 &at, const std::string &name,
                       float radius, float &dist) {
  return FindBuildingT<Building>(world, at, name, radius, dist);
}

// "power <building> supply": buildings kept at full power (test cheat, KAH
// 10). Topped up after every power-grid update of a town (hook in
// Plugin.cpp) and every frame, so the grid's own reset can't undo it.
std::vector<hand> g_supplied;

// "protect <npc> on": characters kept alive and standing (test cheat, KAH
// 11). Every frame: all body parts and blood to max; a knockout is cleared
// at once. Nothing about factions or aggro changes, so a fight stays a fight.
struct Protected {
  hand h;
  std::string name;
  bool wasDown;
  int revives;
};
std::vector<Protected> g_protected;

void ProtectTick() {
  for (size_t i = 0; i < g_protected.size(); ++i) {
    Protected &p = g_protected[i];
    Character *c = nullptr;
    try {
      c = p.h.getCharacter();
    } catch (...) {
      c = nullptr;
    }
    if (!Valid(c) || c->isDead())
      continue;
    MedicalSystem &med = c->medical;
    SetAllParts(c, 1.0f);
    const float maxBlood = med.getMaxBlood();
    if (med.blood < maxBlood)
      med.blood = maxBlood;
    if (c->isUnconcious()) {
      med.knockoutTimer = 0.0f;
      c->playerWantsMeToGetUp = true;
      med.reassessCollapseMode(false, false);
      if (!p.wasDown) {
        ++p.revives;
        Log("KAH: protect revived " + c->getName() + " (revive " + Int(p.revives) + ")");
      }
      p.wasDown = true;
    } else {
      p.wasDown = false;
    }
  }
}

// The power a consumer wants at most (0: it uses no power).
float PowerWanted(UseableStuff *u) {
  float want = 0;
  try {
    want = u->howMuchPowerDoYouWantMax();
    const float maxp = u->getMaxPower();
    if (maxp > want)
      want = maxp;
  } catch (...) {
    want = 0;
  }
  return want;
}

int TopUpSupplied() {
  int n = 0;
  for (size_t i = 0; i < g_supplied.size(); ++i) {
    Building *b = nullptr;
    try {
      b = g_supplied[i].getBuilding();
    } catch (...) {
      b = nullptr;
    }
    UseableStuff *u = Valid(b) ? dynamic_cast<UseableStuff *>(b) : nullptr;
    if (!Valid(u))
      continue;
    const float want = PowerWanted(u);
    if (want > 0 && u->currentPower < want)
      u->currentPower = want;
    ++n;
  }
  return n;
}

bool SameHandle(const hand &a, const hand &b) {
  return a.serial == b.serial && a.index == b.index && a.type == b.type;
}

// Which town's power grid a building belongs to, its role there, and the
// grid's totals (why a bench reads out_of_power=1).
std::string GridInfo(Building *b) {
  std::string out;
  try {
    UseableStuff *u = dynamic_cast<UseableStuff *>(b);
    if (Valid(u))
      out += " current_power=" + Num(u->currentPower) + " wants=" + Num(PowerWanted(u)) +
             " wants_now=" + Num(u->howMuchPowerDoYouWantNow()) +
             " needs_power_now=" + (u->needPowerRightNow() ? "1" : "0") +
             " operators=" + Int(u->currentOperators.size()) + "/" + Int(u->numOperatorsMax) +
             " needs_operating=" + (u->needsOperating ? "1" : "0") +
             " battery_fed=" + (u->_recievesBatteryPower ? "1" : "0");
    Town *t = b->getRealTown();
    if (!Valid(t))
      return out + " grid=none (not in a town)";
    const hand h = b->getHandle();
    std::string role;
    for (size_t i = 0; i < t->powerInList.size(); ++i)
      if (SameHandle(t->powerInList[i], h))
        role += "+consumer";
    for (ogre_unordered_set<hand>::type::const_iterator it = t->powerOutList.begin();
         it != t->powerOutList.end(); ++it)
      if (SameHandle(*it, h))
        role += "+generator";
    for (ogre_unordered_set<hand>::type::const_iterator it = t->batteryList.begin();
         it != t->batteryList.end(); ++it)
      if (SameHandle(*it, h))
        role += "+battery";
    out += " grid=\"" + t->getName() + "\" grid_role=" + (role.empty() ? "none" : role.substr(1)) +
           " grid_power=" + Num(t->power_Stat) + "/" + Num(t->maxPower_Stat) +
           " grid_needed=" + Num(t->neededPowerTotal_Stat) +
           " grid_battery=" + Num(t->batteryCharge_Stat) + "/" + Num(t->batteryChargeMax_Stat) +
           " grid_members=" + Int(t->powerInList.size()) + "in/" + Int(t->powerOutList.size()) +
           "out/" + Int(t->batteryList.size()) + "bat" +
           " player_town=" + (t->playerHasBuildingsInThisTown ? "1" : "0");
  } catch (...) {
    out += " grid=?";
  }
  return out;
}

std::string BuildingInfo(Building *b, const Ogre::Vector3 &origin) {
  std::string out = b->getName() + " dist=" + Num(b->getPosition().distance(origin));
  UseableStuff *u = dynamic_cast<UseableStuff *>(b);
  try {
    out += " power_on=" + std::string(b->isPowerOn() ? "1" : "0");
    if (Valid(u)) {
      out += " has_power=" + std::string(u->hasPower() ? "1" : "0") +
             " out_of_power=" + Num(u->isOutOfPower());
      if (u->isBattery())
        out += " battery=" + Num(u->getBatteryCharge()) + "/" + Num(u->getBatteryChargeMax());
      if (u->getPowerOutput() > 0.0f)
        out += " power_output=" + Num(u->getPowerOutput());
    }
    out += " broken=" + std::string(b->isBroken() ? "1" : "0");
  } catch (...) {
  }
  out += GridInfo(b);
  for (size_t i = 0; i < g_supplied.size(); ++i)
    if (SameHandle(g_supplied[i], b->getHandle()))
      out += " supplied=1";
  StorageBuilding *s = dynamic_cast<StorageBuilding *>(b);
  if (Valid(s)) {
    try {
      GameData *pd = s->getProductionItemData();
      out += " product=" + (Valid(pd) ? pd->name : std::string("-")) +
             " qty=" + Int(s->getCurrentProductionQuantity()) +
             " full=" + (s->isProductionFull() ? "1" : "0");
      for (int i = 0; i < s->getNumConsumtionItems() && i < 6; ++i) {
        StorageBuilding::ConsumptionItem *ci = s->getConsumtionItems(i);
        if (Valid(ci))
          out += " uses[" + (Valid(ci->item) ? ci->item->name : std::string("?")) + " " +
                 Num(ci->amount) + "/" + Num(ci->maxCapacity) + "]";
      }
    } catch (...) {
    }
  }
  ProductionBuilding *p = dynamic_cast<ProductionBuilding *>(b);
  if (Valid(p)) {
    static const char *const states[] = {"STARVED", "FULL", "NORMAL", "IMPOSSIBLE"};
    try {
      int st = (int)p->productionState;
      out += " state=" + std::string(st >= 0 && st < 4 ? states[st] : "?") +
             " output_rate=" + Num(p->getOutput());
    } catch (...) {
    }
  }
  FarmBuilding *farm = dynamic_cast<FarmBuilding *>(b);
  if (Valid(farm))
    out += " farm[grown=" + Num(farm->grown) + " died=" + Num(farm->died) +
           " hydroponic=" + (farm->isHydroponic ? "1" : "0") + "]";
  Inventory *inv = nullptr;
  try {
    inv = b->getInventory();
  } catch (...) {
  }
  if (Valid(inv)) {
    lektor<InventorySection *> &sections = inv->getAllSections();
    for (uint32_t si = 0; si < sections.size(); ++si) {
      InventorySection *section = sections.stuff[si];
      if (!Valid(section))
        continue;
      out += " | " + section->name + ":";
      const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
      for (size_t k = 0; k < items.size() && k < 10; ++k)
        if (Valid(items[k].item))
          out += " [" + items[k].item->getName() + " x" + Int(items[k].item->quantity) + "]";
    }
  }
  return out;
}

// ---- UI (MyGUI) ----------------------------------------------------------

std::string Caption(MyGUI::Widget *w) {
  MyGUI::TextBox *t = w->castType<MyGUI::TextBox>(false);
  if (!t)
    return "";
  try {
    return t->getCaption().asUTF8();
  } catch (...) {
    return "";
  }
}

void ListWidgets(MyGUI::Widget *w, const std::string &filter, bool all, int depth,
                 std::string &out, int &n) {
  if (!w || n >= 120 || depth > 40)
    return;
  bool visible = w->getInheritedVisible();
  if (!visible && !all)
    return;
  const std::string name = w->getName();
  const std::string caption = OneLine(Caption(w));
  if (filter.empty() || Lower(name).find(filter) != std::string::npos ||
      Lower(caption).find(filter) != std::string::npos) {
    const MyGUI::IntCoord c = w->getAbsoluteCoord();
    out += " | " + (name.empty() ? std::string("-") : name) +
           (caption.empty() ? std::string() : " '" + caption.substr(0, 80) + "'") + " " +
           Int(c.left) + "," + Int(c.top) + " " + Int(c.width) + "x" + Int(c.height) +
           (visible ? "" : " hidden");
    ++n;
  }
  for (size_t i = 0; i < w->getChildCount(); ++i)
    ListWidgets(w->getChildAt(i), filter, all, depth + 1, out, n);
}

MyGUI::Widget *FindWidget(MyGUI::Widget *w, const std::string &wanted, int depth) {
  if (!w || depth > 40 || !w->getInheritedVisible())
    return nullptr;
  if (Lower(w->getName()) == wanted || Lower(Caption(w)) == wanted)
    return w;
  for (size_t i = 0; i < w->getChildCount(); ++i) {
    MyGUI::Widget *found = FindWidget(w->getChildAt(i), wanted, depth + 1);
    if (found)
      return found;
  }
  return nullptr;
}

// Commands that work in every phase (menu too).
bool RunAnyPhaseCommand(const std::vector<std::string> &f, bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
  if (cmd == "fps") { // fps [reset]: frame times since launch or the last reset
    const bool reset = f.size() >= 3 && Lower(f[2]) == "reset";
    if (f.size() >= 3 && !reset) {
      out = "usage: fps [reset]";
      return true;
    }
    out = FpsReport(reset) + (reset ? " (reset)" : "");
    ok = true;
    return true;
  }
  if (cmd == "tasks") { // tasks [filter]: AI task names for "order"
    const std::string filter = f.size() >= 3 ? Lower(f[2]) : "";
    int n = 0;
    out = "";
    for (int i = 0; i < kTaskCount; ++i)
      if (filter.empty() || Lower(kTaskNames[i]).find(filter) != std::string::npos) {
        out += (n++ ? " " : "") + Int(i) + ":" + kTaskNames[i];
      }
    ok = true;
    out = Int(n) + " tasks: " + out;
    return true;
  }
  if (cmd == "ui") { // ui [filter] [all]: visible widgets (name, caption, position)
    MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
    if (!gui) {
      out = "no MyGUI";
      return true;
    }
    bool all = false;
    std::string filter;
    for (size_t i = 2; i < f.size(); ++i) {
      if (Lower(f[i]) == "all")
        all = true;
      else
        filter = Lower(f[i]);
    }
    int n = 0;
    std::string list;
    MyGUI::EnumeratorWidgetPtr roots = gui->getEnumerator();
    while (roots.next())
      ListWidgets(roots.current(), filter, all, 0, list, n);
    ok = true;
    out = Int(n) + " widget(s)" + (n >= 120 ? " (first 120; narrow the filter)" : "") + list;
    return true;
  }
  if (cmd == "click") { // click <widget name or caption>: fire its click event
    if (f.size() < 3) {
      out = "usage: click <widget name or exact caption>";
      return true;
    }
    MyGUI::Gui *gui = MyGUI::Gui::getInstancePtr();
    if (!gui) {
      out = "no MyGUI";
      return true;
    }
    const std::string wanted = Lower(f[2]);
    MyGUI::Widget *w = nullptr;
    MyGUI::EnumeratorWidgetPtr roots = gui->getEnumerator();
    while (!w && roots.next())
      w = FindWidget(roots.current(), wanted, 0);
    if (!w) {
      out = "no visible widget named or captioned: " + f[2];
      return true;
    }
    w->eventMouseButtonClick(w);
    ok = true;
    Log("KAH: click " + w->getName() + " '" + Caption(w) + "'");
    out = "clicked " + w->getName() + " '" + OneLine(Caption(w)) + "'";
    return true;
  }
  if (cmd == "messages") { // messages [n]: last on-screen player messages
    ok = true;
    out = RecentMessages(f.size() >= 3 ? atoi(f[2].c_str()) : 10);
    return true;
  }
  if (cmd == "screenshot") { // screenshot [name]: the game's own frame, HUD included
    std::string name = f.size() >= 3 ? f[2] : "";
    out = TakeScreenshot(name, ok);
    return true;
  }
  return false;
}

// World commands that don't start with a character.
// Buildings made by "build" this session (unbuild only removes these).
std::vector<hand> g_built;

// Terrain height at x,z; false when the query gives nothing usable.
bool TerrainHeight(float x, float z, float &h) {
  try {
    h = UtilityT::getTerrainHeight(x, z);
  } catch (...) {
    return false;
  }
  return h == h && fabs(h) < 1.0e6f;
}

float HorizontalDistance(const Ogre::Vector3 &a, const Ogre::Vector3 &b) {
  const float dx = a.x - b.x, dz = a.z - b.z;
  return sqrt(dx * dx + dz * dz);
}

// Why "build" must not make this building (KAH 12), or "" if it may.
std::string BuildRefusal(GameData *data) {
  if (BuildDeniedSid(data->stringID))
    return "is on the deny list: it crashes the game (KAH 12)";
  bool hasFunction = false, hasInvKnown = false, hasInv = true;
  int function = -1;
  try {
    const Ogre::vector<GameDataReference>::type *funcs =
        data->getReferenceListIfExists("functionality");
    if (funcs && !funcs->empty()) {
      GameData *fd = (*funcs)[0].ptr;
      if (Valid(fd) && fd->idata.find("function") != fd->idata.end()) {
        hasFunction = true;
        function = fd->idata.find("function")->second;
      }
    }
    if (data->bdata.find("has inventory") != data->bdata.end()) {
      hasInvKnown = true;
      hasInv = data->bdata.find("has inventory")->second;
    }
  } catch (...) {
    return "";
  }
  if (StorageWithoutInventory(hasFunction, function, hasInvKnown, hasInv))
    return "is a storage building whose template has no inventory: the game crashes on it (KAH 12)";
  return "";
}

Building *CreateBuilding(GameWorld *world, GameData *data, const Ogre::Vector3 &pos, Faction *owner) {
  return world->theFactory->createBuilding(data, pos, nullptr, owner, Ogre::Quaternion::IDENTITY,
                                           nullptr, nullptr, nullptr, nullptr, nullptr, false, true,
                                           false, 0, false);
}

// Production buildings "produced" watches: output quantity sampled every
// frame (SampleProduction), rises counted as produced, drops as removed.
struct TrackedProduction {
  ProductionKey key; // handle index + serial: the lookup key
  hand building;     // to resolve the building for sampling
  std::string name;
  ProductionCounter counter;
};
std::vector<TrackedProduction> g_tracked;
const size_t kMaxTracked = 32;

double GameHours(GameWorld *world) {
  return world->getTimeStamp_inGameHours().getTotalHours();
}

StorageBuilding *ProductionOf(const hand &h) {
  Building *b = h.getBuilding();
  StorageBuilding *s = dynamic_cast<StorageBuilding *>(b);
  return Valid(s) ? s : nullptr;
}

void SampleTracked(GameWorld *world) {
  if (g_tracked.empty())
    return;
  if (!InWorld(world)) { // a load or the main menu: the handles mean nothing now
    g_tracked.clear();
    Log("KAH: produced: tracking cleared (no game loaded)");
    return;
  }
  for (size_t i = 0; i < g_tracked.size(); ++i) {
    try {
      StorageBuilding *s = ProductionOf(g_tracked[i].building);
      if (s)
        g_tracked[i].counter.Sample(s->getCurrentProductionQuantity());
    } catch (...) {
    }
  }
}

// A detached item handed to a character: in an inventory now, or on the ground.
// The ground object is built over the next frames (creatingPhysical /
// physicalShouldExist come first, _isPhysical later), so a drop that is still
// being built counts too; treating it as failed made "trade" refund and put
// the item back while the game was still dropping it.
// pendingBefore: those flags were already set before the attempt (then they
// prove nothing).
bool PlacedOrDropping(Item *item, bool pendingBefore) {
  if (!Valid(item))
    return false;
  if (item->isInInventory || item->_isPhysical)
    return true;
  return !pendingBefore && (item->creatingPhysical || item->physicalShouldExist);
}

// --- weight / packweight (KAH 18): owners that are characters, buildings
// or the ground, and packs nested in packs.
void ItemsOf(Inventory *inv, std::vector<Item *> &out) {
  if (!Valid(inv))
    return;
  lektor<InventorySection *> &sections = inv->getAllSections();
  for (uint32_t si = 0; si < sections.size(); ++si) {
    InventorySection *section = sections.stuff[si];
    if (!Valid(section))
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
    for (size_t k = 0; k < items.size(); ++k)
      if (Valid(items[k].item))
        out.push_back(items[k].item);
  }
}

// Depth-first: the first container matching `needle` (name or sid) inside
// `inv` or in containers inside it; `path` = "Outer > Inner".
ContainerItem *FindPack(Inventory *inv, const std::string &needle, int depth, std::string &path) {
  if (!Valid(inv) || depth > 4)
    return nullptr;
  std::vector<Item *> items;
  ItemsOf(inv, items);
  ContainerItem *partial = nullptr;
  std::string partialPath;
  for (size_t i = 0; i < items.size(); ++i) {
    ContainerItem *ci = dynamic_cast<ContainerItem *>(items[i]);
    if (!Valid(ci))
      continue;
    const std::string n = Lower(ci->getName());
    const std::string sid = Valid(ci->data) ? Lower(ci->data->stringID) : "";
    if (n == needle || sid == needle) {
      path = ci->getName();
      return ci;
    }
    if (!partial && n.find(needle) != std::string::npos) {
      partial = ci;
      partialPath = ci->getName();
    }
  }
  if (partial) {
    path = partialPath;
    return partial;
  }
  for (size_t i = 0; i < items.size(); ++i) {
    ContainerItem *ci = dynamic_cast<ContainerItem *>(items[i]);
    if (!Valid(ci))
      continue;
    std::string inner;
    ContainerItem *found = FindPack(ci->getInventory(), needle, depth + 1, inner);
    if (found) {
      path = ci->getName() + " > " + inner;
      return found;
    }
  }
  return nullptr;
}

// <owner> = a character, else a building (its inventory) within 300 of the
// player, else "ground" (packs lying around). label = what was found.
Inventory *OwnerInventory(GameWorld *world, const std::string &owner, const Ogre::Vector3 &origin,
                          std::string &label, std::string &why) {
  if (Lower(owner) == "ground") {
    label = "ground";
    return nullptr;
  }
  Character *c = FindCharacter(world, owner);
  if (c) {
    label = c->getName();
    return c->getInventory();
  }
  const std::string charWhy = NotFound(owner);
  float dist = 0;
  Building *b = FindBuilding(world, origin, owner, kDefaultSearchRadius, dist);
  if (b) {
    label = b->getName() + " (building, " + Num(dist) + " away)";
    Inventory *inv = b->getInventory();
    if (!Valid(inv))
      why = b->getName() + " has no inventory";
    return inv;
  }
  why = charWhy + ", and no building matching '" + owner + "' within " + Num(kDefaultSearchRadius);
  return nullptr;
}

std::string PackLine(ContainerItem *pack) {
  Inventory *pinv = pack->getInventory();
  std::vector<Item *> items;
  ItemsOf(pinv, items);
  float raw = 0;
  int packs = 0;
  for (size_t i = 0; i < items.size(); ++i) {
    raw += items[i]->getItemWeight();
    if (dynamic_cast<ContainerItem *>(items[i]))
      ++packs;
  }
  float total = 0;
  if (Valid(pinv)) {
    pinv->recalculateTotalWeight();
    total = pinv->getTotalWeight();
  }
  const hand h = pack->getHandle();
  return "pack=" + pack->getName() + " " + FormatCharacterRef(h.serial, h.index) +
         " equipped=" + (pack->isEquipped ? "1" : "0") + " in_inventory=" +
         (pack->isInInventory ? "1" : "0") + " items=" + Int(items.size()) +
         " nested_packs=" + Int(packs) + " raw=" + Num(raw) + " total=" + Num(total) +
         " weight_as_item=" + Num(pack->getItemWeight()) +
         " own_weight=" + Num(pack->getItemWeightSingle());
}

// --- walktime (KAH 19): a timed walk, answered when he arrives.
struct WalkTimer {
  std::string id;   // inbox id: the reply is written when the walk ends
  hand who;
  std::string name;
  Ogre::Vector3 start, target;
  float dist;
  double simSeconds;  // real frame time x game speed while unpaused
  DWORD startTick, lastTick;
  double startGameHours;
  float topSpeed;     // highest CharMovement current speed seen
  bool moving;        // has started to move
};
std::vector<WalkTimer> g_walks;

void WalkTick(GameWorld *world) {
  if (g_walks.empty())
    return;
  const DWORD now = GetTickCount();
  for (size_t i = 0; i < g_walks.size();) {
    WalkTimer &w = g_walks[i];
    const double dt = (now - w.lastTick) / 1000.0;
    w.lastTick = now;
    bool paused = true;
    float mult = 0;
    try {
      paused = world->isPaused();
      mult = world->getFrameSpeedMultiplier();
    } catch (...) {
    }
    if (!paused)
      w.simSeconds += dt * mult;
    Character *c = nullptr;
    try {
      c = w.who.getCharacter();
    } catch (...) {
      c = nullptr;
    }
    std::string done;
    bool okDone = false;
    if (!Valid(c)) {
      done = w.name + " is gone (unloaded or a load)";
    } else {
      const Ogre::Vector3 p = c->getPosition();
      Ogre::Vector3 flat = p - w.start;
      flat.y = 0;
      const float covered = flat.length();
      CharMovement *m = c->movement;
      if (Valid(m) && m->currentSpeed > w.topSpeed)
        w.topSpeed = m->currentSpeed;
      Ogre::Vector3 left = w.target - p;
      left.y = 0;
      if (covered >= w.dist - 1.0f || left.length() < 1.5f) {
        okDone = true;
        const double gameMin = (world->getTimeStamp_inGameHours().getTotalHours() - w.startGameHours) * 60.0;
        done = w.name + " walked " + Num(covered) + " m seconds=" + Num((float)w.simSeconds) +
               " speed=" + Num(w.simSeconds > 0 ? (float)(covered / w.simSeconds) : 0.0f) +
               " m/s real_seconds=" + Num((now - w.startTick) / 1000.0f) +
               " game_minutes=" + Num((float)gameMin) + " top_speed=" + Num(w.topSpeed);
      } else if (now - w.startTick > 180000) {
        done = w.name + " did not arrive within 180 s (covered " + Num(covered) + " of " + Num(w.dist) +
               " m, seconds=" + Num((float)w.simSeconds) + "): blocked path, paused game or KO?";
      }
    }
    if (!done.empty()) {
      Log("KAH: walktime " + done);
      WriteOutbox(w.id, okDone, done);
      g_walks.erase(g_walks.begin() + i);
    } else {
      ++i;
    }
  }
}

// --- theft (KAH 22): crime readout and the player-style pickup order.
std::string FactionName(Faction *f) { return Valid(f) ? f->getName() : std::string("none"); }

int StolenCount(Character *c) {
  Inventory *inv = Valid(c) ? c->getInventory() : nullptr;
  if (!Valid(inv))
    return 0;
  lektor<Item *> stolen;
  inv->getAllStolenItems(stolen, false);
  return (int)stolen.size();
}

// Bounty/wanted state of `c` and who is going after him: characters within
// `radius` whose current goal targets him (HUNT_MY_THIEF and anything else).
std::string CrimeReport(GameWorld *world, Character *c, float radius) {
  std::string out;
  try {
    BountyManager &b = c->crimes;
    out = c->getName() + " committing_crime=" +
          (b.isCommittingCrime() ? BountyManager::crimeToStr(b.committingCrime) : std::string("none")) +
          " against=" + FactionName(b.crimeAgainstFaction) + " crime_expiry=" + Num(b.crimeExpiry) +
          " total_bounty=" + Int(b.getTotalBounty());
    for (ogre_unordered_map<Faction *, Bounty>::type::const_iterator it = b.bounties.begin();
         it != b.bounties.end(); ++it)
      if (it->second.amount != 0 || it->second.crimes != 0)
        out += " bounty[" + FactionName(it->first) + "]=" + Int(it->second.amount);
    out += " stolen_items=" + Int(StolenCount(c));
    std::vector<Character *> around;
    CollectCharacters(world, c->getPosition(), radius, around);
    const hand me = c->getHandle();
    std::string hunters, others;
    int nh = 0, no = 0;
    for (size_t i = 0; i < around.size(); ++i) {
      Character *o = around[i];
      if (o == c)
        continue;
      OrdersReceiver *orders = o->getOrdersReciever();
      if (!Valid(orders))
        continue;
      const TaskMatch &g = orders->currentGoal;
      if (!g.taskData)
        continue;
      const TaskType key = g.key();
      const bool onMe = SameHandle(g.subject, me);
      if (key == HUNT_MY_THIEF) {
        RootObjectBase *t = nullptr;
        try {
          t = g.subject.getRootObjectBase();
        } catch (...) {
          t = nullptr;
        }
        hunters += std::string(nh++ ? "; " : "") + o->getName() + " [" + FactionName(o->getFaction()) +
                   "] HUNT_MY_THIEF -> " + (Valid(t) ? t->getName() : std::string("?"));
      } else if (onMe && no < 12) {
        others += std::string(no++ ? "; " : "") + o->getName() + " " + TaskName((int)key);
      }
    }
    out += " hunters=" + Int(nh) + (nh ? " {" + hunters + "}" : "");
    if (no)
      out += " targeting_him={" + others + "}";
  } catch (...) {
    out += " (unreadable)";
  }
  return out;
}

struct StealTimer {
  std::string id;
  hand who, item;
  std::string name, itemName, owner;
  int stolenBefore;
  DWORD startTick;
};
std::vector<StealTimer> g_steals;

void StealTick(GameWorld *world) {
  if (g_steals.empty())
    return;
  const DWORD now = GetTickCount();
  for (size_t i = 0; i < g_steals.size();) {
    StealTimer &s = g_steals[i];
    Character *c = nullptr;
    Item *it = nullptr;
    try {
      c = s.who.getCharacter();
      it = s.item.getItem();
    } catch (...) {
    }
    std::string done;
    bool okDone = false;
    if (!Valid(c)) {
      done = s.name + " is gone";
    } else {
      const int stolen = StolenCount(c);
      const bool inHisInv = Valid(it) && it->isInInventory &&
                            SameHandle(it->getInventoryWeAreIn(), c->getHandle());
      const bool merged = !Valid(it) && stolen > s.stolenBefore;
      if (inHisInv || merged) {
        okDone = true;
        done = s.name + " picked up " + s.itemName + " (owner faction " + s.owner + ")" +
               (merged ? " (merged into a stack)" : "") + " item_stolen=" +
               (inHisInv ? (it->isStolen(false) ? "1" : "0") : "?") + " has_stolen_items=" +
               (Valid(c->getInventory()) && c->getInventory()->hasStolenItems() ? "1" : "0") +
               " stolen_items " + Int(s.stolenBefore) + " -> " + Int(stolen) +
               " seconds=" + Num((now - s.startTick) / 1000.0f) + " | " + CrimeReport(world, c, 200.0f);
      } else if (now - s.startTick > 120000) {
        done = s.name + " did not pick up " + s.itemName + " within 120 s (path, KO, or someone took it) | " +
               CrimeReport(world, c, 200.0f);
      }
    }
    if (!done.empty()) {
      Log("KAH: pickup(order) " + done);
      WriteOutbox(s.id, okDone, done);
      g_steals.erase(g_steals.begin() + i);
    } else {
      ++i;
    }
  }
}

// Squads "unload" streamed out this session (for "reload").
struct Unloaded {
  std::string name;
  hand platoon;
  hand character;
  int members;
};
std::vector<Unloaded> g_unloaded;

// Items "drop" put on the ground this session (searched first by "pickup").
std::vector<hand> g_dropped;

// "Rattan Hat x1 #serial/index pos=x,y,z dist=d on_ground=1"
std::string GroundItemLine(Item *item, const Ogre::Vector3 &from) {
  if (!Valid(item))
    return "invalid item";
  const hand h = item->getHandle();
  const Ogre::Vector3 p = item->getPosition();
  return item->getName() + " x" + Int(item->quantity) + " " + FormatCharacterRef(h.serial, h.index) +
         " pos=" + Num(p.x) + "," + Num(p.y) + "," + Num(p.z) + " dist=" + Num(p.distance(from)) +
         " in_inventory=" + (item->isInInventory ? "1" : "0") +
         " physical=" + (item->_isPhysical ? "1" : "0");
}

bool OnGround(Item *item) {
  return Valid(item) && !item->isInInventory &&
         (item->_isPhysical || item->creatingPhysical || item->physicalShouldExist);
}

// A ground item near `at`: "#serial/index", "nearest", or a name/sid (nearest
// match). Items "drop" made are checked first, then the world's items.
Item *FindGroundItem(GameWorld *world, const Ogre::Vector3 &at, const std::string &wanted,
                     float radius, std::string &why) {
  std::vector<Item *> found;
  for (size_t i = 0; i < g_dropped.size(); ++i) {
    Item *it = nullptr;
    try {
      it = dynamic_cast<Item *>(g_dropped[i].getRootObject());
    } catch (...) {
      it = nullptr;
    }
    if (OnGround(it))
      found.push_back(it);
  }
  const itemType types[] = {ITEM, WEAPON, ARMOUR, CONTAINER, BLUEPRINT};
  for (int t = 0; t < 5; ++t) {
    lektor<RootObject *> nearby;
    try {
      world->getObjectsWithinSphere(nearby, at, radius, types[t], 256, nullptr);
    } catch (...) {
      continue;
    }
    for (uint32_t i = 0; i < nearby.size(); ++i) {
      Item *it = dynamic_cast<Item *>(nearby.stuff[i]);
      if (OnGround(it) && std::find(found.begin(), found.end(), it) == found.end())
        found.push_back(it);
    }
  }
  const std::string needle = Lower(wanted);
  const CharacterRef ref = ParseCharacterRef(needle);
  const bool byRef = ref.isRef;
  if (byRef && !ref.valid) {
    why = "malformed item reference: " + wanted + " (use #serial/index or #serial)";
    return nullptr;
  }
  Item *best = nullptr;
  float bestDist = 0;
  for (size_t i = 0; i < found.size(); ++i) {
    Item *it = found[i];
    const hand h = it->getHandle();
    if (byRef) {
      if (h.serial != ref.serial || (ref.hasIndex && h.index != ref.index))
        continue;
    } else if (needle != "nearest") {
      const std::string n = Lower(it->getName());
      const std::string sid = Valid(it->data) ? Lower(it->data->stringID) : "";
      if (n.find(needle) == std::string::npos && sid != needle)
        continue;
    }
    const float d = it->getPosition().distance(at);
    if (byRef || !best || d < bestDist) { // a #ref is exact: any distance
      best = it;
      bestDist = d;
    }
  }
  if (!best)
    why = "no item on the ground matching '" + wanted + "' within " + Num(radius) + " (" +
          Int(found.size()) + " ground items seen)";
  return best;
}

bool RunWorldCommand(GameWorld *world, const std::vector<std::string> &f, const Ogre::Vector3 &origin,
                     bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
  if (cmd == "produced") { // produced <building> [reset] [radius <m>]: output made since the last reset
    if (f.size() < 3) {
      out = "usage: produced <building> [reset] [radius <m>]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 3, 0, kDefaultSearchRadius, radius, out))
      return true;
    bool reset = false;
    for (size_t i = 3; i < f.size(); ++i)
      if (Lower(f[i]) == "reset")
        reset = true;
    Building *b = FindBuilding(world, origin, f[2], radius, dist);
    if (!b) {
      out = "no building matching '" + f[2] + "' within " + Num(radius) + " of the player";
      return true;
    }
    StorageBuilding *s = dynamic_cast<StorageBuilding *>(b);
    GameData *product = Valid(s) ? s->getProductionItemData() : nullptr;
    if (!Valid(product)) {
      out = b->getName() + " has no production output (not a production building)";
      return true;
    }
    const double now = GameHours(world);
    const int level = s->getCurrentProductionQuantity();
    const hand &bh = b->getHandle();
    const ProductionKey key(bh.index, bh.serial);
    const int found = FindProductionEntry(g_tracked, key);
    TrackedProduction *t = found >= 0 ? &g_tracked[found] : nullptr;
    if (!t) {
      if (g_tracked.size() >= kMaxTracked) {
        out = "already tracking " + Int((long long)kMaxTracked) + " buildings";
        return true;
      }
      TrackedProduction fresh;
      fresh.key = key;
      fresh.building = bh;
      fresh.name = b->getName();
      fresh.counter.Reset(now);
      fresh.counter.Sample(level);
      g_tracked.push_back(fresh);
      ok = true;
      Log("KAH: produced track key=" + Int(key.index) + "/" + Int(key.serial) + " " + b->getName() +
          " output=" + Int(level) + " entries=" + Int((long long)g_tracked.size()));
      out = "tracking " + b->getName() + " product=" + product->name + " output_now=" + Int(level) +
            " from game hour " + Num(now) + " (ask again later; a load clears tracking)";
      return true;
    }
    t->counter.Sample(level);
    const ProductionCounter &c = t->counter;
    char rate[32];
    sprintf_s(rate, "%.2f", c.PerGameHour(now));
    char hours[32];
    sprintf_s(hours, "%.3f", c.Hours(now));
    out = b->getName() + " product=" + product->name + " produced=" + Int(c.produced) +
          " removed=" + Int(c.removed) + " output_now=" + Int(level) + " game_hours=" + hours +
          " per_game_hour=" + rate + " samples=" + Int(c.samples);
    if (reset) {
      t->counter.ResetKeepLevel(now);
      out += " (reset)";
    }
    ok = true;
    return true;
  }
  if (cmd == "build") { // build <name|sid> [near <npc> [dist m] | at x y z] [faction <f>]
    BuildArgs a;
    if (!ParseBuildArgs(f, a, out))
      return true;
    std::string error;
    GameData *data = FindData(world, BUILDING, a.name, error);
    if (!data) {
      out = error;
      return true;
    }
    {
      std::string why = BuildRefusal(data);
      if (!why.empty()) {
        Log("KAH: build refused " + data->name + " (" + data->stringID + "): " + why);
        out = "refused: " + data->name + " (" + data->stringID + ") " + why;
        return true;
      }
    }
    Ogre::Vector3 pos;
    if (a.at) {
      pos = Ogre::Vector3(a.x, a.y, a.z);
    } else {
      Character *n = a.nearName.empty() ? FirstPlayerCharacter(world) : FindCharacter(world, a.nearName);
      if (!n) {
        out = NotFound(a.nearName);
        return true;
      }
      pos = n->getPosition();
      pos.x += a.dist;
    }
    Faction *owner = a.faction.empty() ? world->player->getFaction() : FindFaction(world, a.faction);
    if (!Valid(owner)) {
      out = "no faction named: " + a.faction;
      return true;
    }
    // Target height: the npc's (or the given) y, or the terrain there when
    // that is within 20 of it. Run m9: the factory adds the terrain height to
    // the y it gets (a bed asked for at y 641 stood at 1283), so the y passed
    // is the wanted height minus the terrain height, and the result is
    // checked: if it is still off by more than 5, it is rebuilt once with
    // the measured offset taken out.
    const float wantY = pos.y;
    float terrain = 0;
    const bool haveTerrain = TerrainHeight(pos.x, pos.z, terrain);
    const float targetY = haveTerrain && fabs(terrain - wantY) <= 20.0f ? terrain : wantY;
    pos.y = haveTerrain ? targetY - terrain : targetY;
    Building *b = CreateBuilding(world, data, pos, owner);
    if (!Valid(b)) {
      out = "the game could not create " + data->name;
      return true;
    }
    std::string note;
    float offBy = b->getPosition().y - targetY;
    if (fabs(offBy) > 5.0f) {
      Log("KAH: build " + data->name + " off by " + Num(offBy) + " in height, rebuilding");
      world->destroy(b, false, "KAH build height fix");
      pos.y -= offBy;
      b = CreateBuilding(world, data, pos, owner);
      if (!Valid(b)) {
        out = "the game could not create " + data->name + " (second try for the height)";
        return true;
      }
      note = " (rebuilt once: first try was " + Num(offBy) + " off in height)";
      offBy = b->getPosition().y - targetY;
      if (fabs(offBy) > 5.0f)
        note += " WARNING still " + Num(offBy) + " off the target height " + Num(targetY);
    }
    g_built.push_back(b->getHandle());
    const Ogre::Vector3 bp = b->getPosition();
    ok = true;
    Log("KAH: build " + b->getName() + " serial=" + Int(b->getHandle().serial) + " y=" + Num(bp.y) +
        " target=" + Num(targetY) + " terrain=" + (haveTerrain ? Num(terrain) : std::string("?")));
    out = "built " + b->getName() + " serial=" + Int(b->getHandle().serial) + " pos=" + Num(bp.x) +
          "," + Num(bp.y) + "," + Num(bp.z) + " [" + owner->getName() + "] dist=" +
          Num(bp.distance(origin)) + note;
    return true;
  }
  if (cmd == "unbuild") { // unbuild <name> [radius]: destroy the nearest building "build" made
    if (f.size() < 3) {
      out = "usage: unbuild <name> [radius]";
      return true;
    }
    float radius = 0;
    if (!ParseSearchRadius(f, 3, 3, kDefaultSearchRadius, radius, out))
      return true;
    const std::string wanted = Lower(f[2]);
    Building *best = nullptr;
    size_t bestIndex = 0;
    float bestDist = 0;
    for (size_t i = 0; i < g_built.size(); ++i) {
      Building *b = nullptr;
      try {
        b = g_built[i].getBuilding();
      } catch (...) {
        b = nullptr;
      }
      if (!Valid(b))
        continue;
      const float d = HorizontalDistance(b->getPosition(), origin); // x,z only
      if (d > radius || Lower(b->getName()).find(wanted) == std::string::npos)
        continue;
      if (!best || d < bestDist) {
        best = b;
        bestIndex = i;
        bestDist = d;
      }
    }
    if (!best) {
      out = "no building made by build matching '" + f[2] + "' within " + Num(radius) +
            " of the player";
      return true;
    }
    const std::string name = best->getName();
    g_built.erase(g_built.begin() + bestIndex);
    ok = world->destroy(best, false, "KAH unbuild");
    Log("KAH: unbuild " + name + " ok=" + (ok ? "1" : "0"));
    out = std::string(ok ? "destroyed " : "destroy refused: ") + name + " (" + Num(bestDist) +
          " from the player)";
    return true;
  }
  if (cmd == "weight") { // weight <npc|building>: total inventory weight (KAH 18: buildings too)
    if (f.size() < 3) {
      out = "usage: weight <npc|building>";
      return true;
    }
    std::string label, why;
    Inventory *inv = OwnerInventory(world, f[2], origin, label, why);
    if (!Valid(inv)) {
      out = why.empty() ? "usage: weight <npc|building>" : why;
      return true;
    }
    inv->recalculateTotalWeight();
    std::vector<Item *> items;
    ItemsOf(inv, items);
    ok = true;
    out = label + " inventory_weight=" + Num(inv->getTotalWeight()) + " items=" + Int(items.size());
    return true;
  }
  if (cmd == "packweight") { // packweight <npc|building|ground> <pack>: a pack's weight, nested packs found (KAH 18)
    if (f.size() < 4) {
      out = "usage: packweight <npc|building|ground> <pack name|stringID>";
      return true;
    }
    const std::string needle = Lower(f[3]);
    std::string label, why, path;
    ContainerItem *pack = nullptr;
    if (Lower(f[2]) == "ground") {
      std::string gwhy;
      Item *g = FindGroundItem(world, origin, f[3], 300.0f, gwhy);
      pack = dynamic_cast<ContainerItem *>(g);
      label = "ground";
      if (!Valid(pack)) {
        out = Valid(g) ? g->getName() + " is not a pack" : gwhy;
        return true;
      }
      path = pack->getName();
    } else {
      Inventory *inv = OwnerInventory(world, f[2], origin, label, why);
      if (!Valid(inv)) {
        out = why;
        return true;
      }
      pack = FindPack(inv, needle, 0, path);
      if (!pack) {
        out = "no pack matching '" + f[3] + "' in " + label + " (packs inside packs are searched too)";
        return true;
      }
    }
    ok = true;
    out = label + " path=" + path + " " + PackLine(pack);
    return true;
  }
  if (cmd == "unload") { // unload <npc>: stream his squad out like the game does far away (KAH 17)
    if (f.size() < 3) {
      out = "usage: unload <npc>";
      return true;
    }
    Character *uc = FindCharacter(world, f[2]);
    if (!uc) {
      out = NotFound(f[2]);
      return true;
    }
    ActivePlatoon *ap = uc->getPlatoon();
    if (!Valid(ap) || !Valid(ap->me)) {
      out = uc->getName() + " has no squad to unload";
      return true;
    }
    if (Valid(ap->isPlayer)) {
      out = uc->getName() + " is in the player's squad (can't be unloaded)";
      return true;
    }
    Platoon *p = ap->me;
    Unloaded u = {uc->getName(), p->getHandle(), uc->getHandle(), 0};
    try {
      u.members = p->getCharacterCount();
    } catch (...) {
    }
    const std::string name = u.name;
    const hand ch = u.character;
    // The character objects are destroyed now: don't touch uc after this.
    p->deactivate(nullptr);
    const bool unloaded = !Valid(p->getActivePlatoon());
    for (size_t i = 0; i < g_unloaded.size(); ++i)
      if (SameHandle(g_unloaded[i].platoon, u.platoon)) {
        g_unloaded.erase(g_unloaded.begin() + i);
        break;
      }
    g_unloaded.push_back(u);
    ok = unloaded;
    Log("KAH: unload " + name + " squad_members=" + Int(u.members) + " ok=" + (ok ? "1" : "0"));
    out = std::string(ok ? "unloaded " : "unload failed: ") + name + " " +
          FormatCharacterRef(ch.serial, ch.index) + " with his squad (" + Int(u.members) +
          " characters); \"reload " + name + "\" brings them back (the game also reloads a squad "
          "on its own when the player is near)";
    return true;
  }
  if (cmd == "reload") { // reload <name>: load a squad "unload" streamed out (KAH 17)
    if (f.size() < 3) {
      std::string list;
      for (size_t i = 0; i < g_unloaded.size(); ++i)
        list += (i ? ", " : "") + g_unloaded[i].name;
      out = "usage: reload <name> (unloaded: " + (list.empty() ? std::string("none") : list) + ")";
      return true;
    }
    const std::string wanted = Lower(f[2]);
    size_t at = g_unloaded.size();
    for (size_t i = 0; i < g_unloaded.size() && at == g_unloaded.size(); ++i)
      if (Lower(g_unloaded[i].name) == wanted)
        at = i;
    for (size_t i = 0; i < g_unloaded.size() && at == g_unloaded.size(); ++i)
      if (Lower(g_unloaded[i].name).find(wanted) != std::string::npos)
        at = i;
    if (at == g_unloaded.size()) {
      out = "nobody named '" + f[2] + "' was unloaded by unload";
      return true;
    }
    const Unloaded u = g_unloaded[at];
    Platoon *p = nullptr;
    try {
      p = u.platoon.getPlatoon();
    } catch (...) {
      p = nullptr;
    }
    if (!Valid(p)) {
      g_unloaded.erase(g_unloaded.begin() + at);
      out = "the squad of " + u.name + " is gone (destroyed or the game was loaded)";
      return true;
    }
    const bool wasActive = Valid(p->getActivePlatoon());
    if (!wasActive)
      p->activate();
    Character *back = nullptr;
    try {
      back = u.character.getCharacter();
    } catch (...) {
      back = nullptr;
    }
    ok = Valid(p->getActivePlatoon());
    if (ok)
      g_unloaded.erase(g_unloaded.begin() + at);
    Log("KAH: reload " + u.name + " ok=" + (ok ? "1" : "0") + (wasActive ? " (was already loaded)" : ""));
    out = std::string(ok ? "reloaded " : "reload failed: ") + u.name +
          (wasActive ? " (the game had already reloaded him)" : "") + " | " +
          (Valid(back) ? Describe(back, &origin)
                       : std::string("character not resolvable by his old handle yet (chars lists who is near)"));
    return true;
  }
  if (cmd == "protect") { // protect [<npc> on|off]: keep a character healed and awake (cheat)
    if (f.size() == 2) {
      std::string list;
      for (size_t i = 0; i < g_protected.size(); ++i) {
        Character *pc = nullptr;
        try {
          pc = g_protected[i].h.getCharacter();
        } catch (...) {
          pc = nullptr;
        }
        list += (i ? " | " : "") + g_protected[i].name + " #" + Int(g_protected[i].h.serial) + "/" +
                Int(g_protected[i].h.index) + " revives=" + Int(g_protected[i].revives) +
                (!Valid(pc) ? " (gone)" : pc->isDead() ? " DEAD" : pc->isUnconcious() ? " KO" : "");
      }
      ok = true;
      out = g_protected.empty() ? "nobody is protected" : Int(g_protected.size()) + " protected: " + list;
      return true;
    }
    const std::string mode = f.size() >= 4 ? Lower(f[3]) : "";
    if (f.size() != 4 || (mode != "on" && mode != "off")) {
      out = "usage: protect [<npc> on|off]";
      return true;
    }
    Character *pc = FindCharacter(world, f[2]);
    if (!pc) {
      out = NotFound(f[2]);
      return true;
    }
    const hand h = pc->getHandle();
    for (size_t i = 0; i < g_protected.size(); ++i)
      if (SameHandle(g_protected[i].h, h)) {
        g_protected.erase(g_protected.begin() + i);
        break;
      }
    if (mode == "on") {
      if (pc->isDead()) {
        out = pc->getName() + " is dead (protect can't revive the dead)";
        return true;
      }
      Protected p = {h, pc->getName(), false, 0};
      g_protected.push_back(p);
      ProtectTick();
    }
    ok = true;
    Log("KAH: protect " + pc->getName() + " " + mode);
    out = pc->getName() + " protect=" + mode + (pc->isUnconcious() ? " (still KO this frame)" : "") +
          " protected=" + Int(g_protected.size());
    return true;
  }
  if (cmd == "time") { // time: game time
    TimeOfDay t = world->getTimeStamp_inGameHours();
    double hours = t.getTotalHours();
    double hourOfDay = fmod(hours, 24.0);
    int hh = (int)hourOfDay, mm = (int)((hourOfDay - hh) * 60.0);
    char buf[64];
    sprintf_s(buf, "%.4f", hours);
    out = std::string("game_hours=") + buf + " day=" + Int((long long)t.getTotalDays()) + " time=" +
          (hh < 10 ? "0" : "") + Int(hh) + ":" + (mm < 10 ? "0" : "") + Int(mm) +
          " speed=" + Num(world->getFrameSpeedMultiplier()) +
          " paused=" + (world->isPaused() ? "1" : "0");
    ok = true;
    return true;
  }
  if (cmd == "building" || cmd == "production") { // building <name> [radius]: state, power, production, inventory
    if (f.size() < 3) {
      out = "usage: " + cmd + " <building name> [radius]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 3, 3, kDefaultSearchRadius, radius, out))
      return true;
    Building *b = FindBuilding(world, origin, f[2], radius, dist);
    if (!b) {
      out = "no building matching '" + f[2] + "' within " + Num(radius) + " of the player";
      return true;
    }
    ok = true;
    out = BuildingInfo(b, origin);
    return true;
  }
  if (cmd == "buildings") { // buildings [radius] [filter] [near <npc>]
    float radius = 0;
    if (!ParseSearchRadius(f, f.size(), 2, 100.0f, radius, out)) // positional only
      return true;
    const std::string filter = f.size() >= 4 && Lower(f[3]) != "near" ? Lower(f[3]) : "";
    Ogre::Vector3 at = origin;
    const std::string nearName = Option(f, 3, "near", "");
    if (!nearName.empty()) {
      Character *n = FindCharacter(world, nearName);
      if (!n) {
        out = NotFound(nearName);
        return true;
      }
      at = n->getPosition();
    }
    lektor<RootObject *> nearby;
    world->getObjectsWithinSphere(nearby, at, radius, BUILDING, 1024, nullptr);
    int n = 0;
    out = "";
    for (uint32_t i = 0; i < nearby.size() && n < 60; ++i) {
      Building *b = dynamic_cast<Building *>(nearby.stuff[i]);
      if (!Valid(b))
        continue;
      std::string bn;
      try {
        bn = b->getName();
      } catch (...) {
        continue;
      }
      if (!filter.empty() && Lower(bn).find(filter) == std::string::npos)
        continue;
      Faction *bf = nullptr;
      try {
        bf = b->getFaction();
      } catch (...) {
      }
      Inventory *binv = nullptr;
      try {
        binv = b->getInventory();
      } catch (...) {
      }
      const Ogre::Vector3 bp = b->getPosition();
      out += " | " + bn + " dist=" + Num(bp.distance(at)) + " pos=" + Num(bp.x) + "," +
             Num(bp.y) + "," + Num(bp.z) + " [" +
             (Valid(bf) ? bf->getName() : std::string("-")) + "]" + (Valid(binv) ? " inv" : "");
      ++n;
    }
    ok = true;
    out = Int(n) + " buildings within " + Num(radius) + ":" + out;
    return true;
  }
  if (cmd == "power") { // power <building> on|off|charge|supply|unsupply [radius <m>]
    if (f.size() < 4) {
      out = "usage: power <building> on|off|charge|supply|unsupply [radius <m>]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 4, 0, kDefaultSearchRadius, radius, out))
      return true;
    Building *b = FindBuilding(world, origin, f[2], radius, dist);
    if (!b) {
      out = "no building matching '" + f[2] + "' within " + Num(radius) + " of the player";
      return true;
    }
    const std::string what = Lower(f[3]);
    if (what == "on" || what == "off") {
      b->switchPowerOn(what == "on");
    } else if (what == "charge") {
      UseableStuff *u = dynamic_cast<UseableStuff *>(b);
      if (!Valid(u) || !u->isBattery()) {
        out = b->getName() + " is not a battery";
        return true;
      }
      u->powerTimeStored = u->_powerTimeStoreMax;
    } else if (what == "supply" || what == "unsupply") {
      UseableStuff *u = dynamic_cast<UseableStuff *>(b);
      if (!Valid(u)) {
        out = b->getName() + " can't take power";
        return true;
      }
      const hand h = b->getHandle();
      for (size_t i = 0; i < g_supplied.size(); ++i)
        if (SameHandle(g_supplied[i], h)) {
          g_supplied.erase(g_supplied.begin() + i);
          break;
        }
      if (what == "supply") {
        if (PowerWanted(u) <= 0) {
          out = b->getName() + " uses no power (wants=0)" + GridInfo(b);
          return true;
        }
        g_supplied.push_back(h);
        TopUpSupplied();
      }
    } else {
      out = "usage: power <building> on|off|charge|supply|unsupply";
      return true;
    }
    ok = true;
    Log("KAH: power " + b->getName() + " " + what);
    out = BuildingInfo(b, origin);
    return true;
  }
  if (cmd == "fill") { // fill <building> <item> [n] [section <name>] [radius <m>]: put items in a building
    if (f.size() < 4) {
      out = "usage: fill <building> <item> [n] [section <name>] [radius <m>]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 4, 0, kDefaultSearchRadius, radius, out))
      return true;
    Building *b = FindBuilding(world, origin, f[2], radius, dist);
    if (!b) {
      out = "no building matching '" + f[2] + "' within " + Num(radius) + " of the player";
      return true;
    }
    Inventory *inv = b->getInventory();
    if (!Valid(inv)) {
      out = b->getName() + " has no inventory";
      return true;
    }
    int count = CountArg(f, 4);
    if (count < 1 || count > 100) {
      out = "count must be 1..100";
      return true;
    }
    std::string error;
    GameData *data = nullptr;
    const itemType types[] = {ITEM, ARMOUR, CONTAINER, WEAPON};
    for (int t = 0; t < 4 && !data; ++t)
      data = FindData(world, types[t], f[3], error);
    if (!data) {
      out = error;
      return true;
    }
    const std::string sectionName = Option(f, 4, "section", "");
    InventorySection *section = sectionName.empty() ? nullptr : inv->getSection(sectionName);
    if (!sectionName.empty() && !Valid(section)) {
      out = b->getName() + " has no section " + sectionName;
      return true;
    }
    const int before = CountAllSections(inv, data);
    error.clear();
    for (int i = 0; i < count; ++i) {
      Item *item = MakeItem(world, data, f, 4, nullptr, error);
      if (!item)
        break;
      bool placed = section ? section->addItem(item, 1) : inv->addItem(item, 1, false, true);
      if (!placed)
        break;
    }
    const int after = CountAllSections(inv, data);
    ok = after > before;
    Log("KAH: fill " + b->getName() + " " + data->name + " " + Int(before) + " -> " + Int(after));
    out = (ok ? "" : (error.empty() ? "nothing fitted: " : error + ": ")) + b->getName() + " " +
          data->name + " " + Int(before) + " -> " + Int(after) + " (" + Int(after - before) + " of " +
          Int(count) + " fitted)";
    return true;
  }
  return false;
}

// Body part by index (0..6) or name.
int ParsePart(const std::string &text) {
  static const char *const names[] = {"head", "chest", "stomach", "left_arm", "right_arm",
                                      "left_leg", "right_leg"};
  std::string t = Lower(text);
  t.erase(std::remove(t.begin(), t.end(), ' '), t.end());
  for (int i = 0; i < 7; ++i) {
    std::string joined = names[i];
    joined.erase(std::remove(joined.begin(), joined.end(), '_'), joined.end());
    if (t == names[i] || t == joined)
      return i;
  }
  char *end = nullptr;
  long n = strtol(text.c_str(), &end, 10);
  return (!text.empty() && end && !*end && n >= 0 && n < 7) ? (int)n : -1;
}

struct ShopSource {
  std::string name;
  Inventory *inv;
};

void InventoryItems(Inventory *inv, std::vector<Item *> &out) {
  if (!Valid(inv))
    return;
  lektor<InventorySection *> &sections = inv->getAllSections();
  for (uint32_t si = 0; si < sections.size(); ++si) {
    InventorySection *section = sections.stuff[si];
    if (!Valid(section))
      continue;
    const Ogre::vector<InventorySection::SectionItem>::type &items = section->getItems();
    for (size_t k = 0; k < items.size(); ++k)
      if (Valid(items[k].item))
        out.push_back(items[k].item);
  }
}

// A trader's goods: her own inventory, plus storage in her shop (buildings
// within `radius` of her that belong to her faction: Kenshi keeps shop stock
// there; traders walk around their shops, so the default is 60).
void CollectShopSources(GameWorld *world, Character *trader, float radius,
                        std::vector<ShopSource> &out) {
  ShopSource own = {trader->getName() + " (carried)", trader->getInventory()};
  out.push_back(own);
  Faction *fac = trader->getFaction();
  lektor<RootObject *> nearby;
  world->getObjectsWithinSphere(nearby, trader->getPosition(), radius, BUILDING, 256, nullptr);
  for (uint32_t i = 0; i < nearby.size(); ++i) {
    Building *b = dynamic_cast<Building *>(nearby.stuff[i]);
    if (!Valid(b))
      continue;
    try {
      if (b->getFaction() != fac || !Valid(b->getInventory()))
        continue;
      ShopSource src = {b->getName(), b->getInventory()};
      out.push_back(src);
    } catch (...) {
    }
  }
}

// World commands about one character (f[2] is the character, already resolved as c).
bool RunCharacterCommand(GameWorld *world, const std::vector<std::string> &f, Character *c,
                         const Ogre::Vector3 &origin, bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
  if (cmd == "drop") { // drop <npc> <item> [count]: put an inventory item on the ground (KAH 15)
    if (f.size() < 4) {
      out = "usage: drop <npc> <item> [count]";
      return true;
    }
    bool ambiguous = false;
    Item *item = FindInventoryItem(c, f[3], ambiguous);
    if (!item) {
      out = ambiguous ? "several items match '" + f[3] + "': use the full name or sid"
                      : c->getName() + " carries no " + f[3];
      return true;
    }
    if (f.size() >= 5 && atoi(f[4].c_str()) != item->quantity) {
      out = "drop takes the whole stack: " + item->getName() + " x" + Int(item->quantity) +
            " (give count " + Int(item->quantity) + " or none)";
      return true;
    }
    if (item->isEquipped) {
      out = item->getName() + " is worn: unequip it first";
      return true;
    }
    Inventory *inv = c->getInventory();
    const bool pendingBefore = item->creatingPhysical || item->physicalShouldExist;
    try {
      inv->dropItem(item);
    } catch (...) {
    }
    ok = Valid(item) && !item->isInInventory && PlacedOrDropping(item, pendingBefore);
    if (ok) {
      g_dropped.push_back(item->getHandle());
      if (g_dropped.size() > 64)
        g_dropped.erase(g_dropped.begin());
    }
    Log("KAH: drop " + c->getName() + " " + item->getName() + " ok=" + (ok ? "1" : "0"));
    out = std::string(ok ? "dropped " : "drop failed: ") + GroundItemLine(item, c->getPosition()) +
          (ok && !item->_isPhysical ? " (ground object still being built)" : "");
    return true;
  }
  if (cmd == "sever") { // sever <npc> <limb> [noitem] [ko]: the game's own amputation (KAH 20)
    static const char *const limbNames[] = {"left_arm", "right_arm", "left_leg", "right_leg"};
    static const char *const states[] = {"original", "stump", "replaced", "crushed"};
    int limb = -1;
    const std::string want = f.size() >= 4 ? Lower(f[3]) : "";
    for (int i = 0; i < 4; ++i)
      if (want == limbNames[i])
        limb = i;
    if (limb < 0) {
      out = "usage: sever <npc> left_arm|right_arm|left_leg|right_leg [noitem] [ko]";
      return true;
    }
    bool makeItem = true, knockout = false;
    for (size_t i = 4; i < f.size(); ++i) {
      if (Lower(f[i]) == "noitem")
        makeItem = false;
      if (Lower(f[i]) == "ko")
        knockout = true;
    }
    MedicalSystem &med = c->medical;
    const RobotLimbs::Limb l = (RobotLimbs::Limb)limb;
    const int before = (int)med.getLimbState(l);
    if (before == LIMB_STUMP || before == LIMB_CRUSHED) {
      out = c->getName() + " " + limbNames[limb] + " is already lost (" + states[before] + ")";
      return true;
    }
    med.amputate(l, makeItem, Ogre::Vector3::ZERO);
    // As after a real cut-off (and Stobe's own amputation): the limb part
    // reads as destroyed.
    MedicalSystem::HealthPartStatus *part =
        limb == 0 ? med.leftArm : limb == 1 ? med.rightArm : limb == 2 ? med.leftLeg : med.rightLeg;
    if (Valid(part)) {
      part->flesh = -100.0f;
      if (part->fleshStun > -100.0f)
        part->fleshStun = -100.0f;
      part->updateDerivedHealths();
    }
    if (knockout)
      med.knockoutForceTimer(8.0f);
    const int after = (int)med.getLimbState(l);
    ok = after == LIMB_STUMP || after == LIMB_CRUSHED;
    Log("KAH: sever " + c->getName() + " " + limbNames[limb] + " state " + Int(before) + " -> " + Int(after));
    out = c->getName() + " " + limbNames[limb] + " limb_state " +
          (before >= 0 && before < 4 ? states[before] : "?") + " -> " +
          (after >= 0 && after < 4 ? states[after] : "?") +
          (makeItem ? " (severed limb item dropped)" : "") + (knockout ? " KO 8 s" : "") +
          (ok ? "" : " (the game did not mark it lost)");
    return true;
  }
  if (cmd == "pickup") { // pickup <npc> <item|#serial/index|nearest> [radius <m>]: ground item into inventory (KAH 15)
    if (f.size() < 4) {
      out = "usage: pickup <npc> <item name|sid|#serial/index|nearest> [radius <m>]";
      return true;
    }
    Ogre::Vector3 center = c->getPosition();
    const std::string nearName = Option(f, 4, "near", "");
    if (!nearName.empty()) {
      Character *nc = FindCharacter(world, nearName);
      float bd = 0;
      Building *nb = nc ? nullptr : FindBuilding(world, origin, nearName, kDefaultSearchRadius, bd);
      if (nc)
        center = nc->getPosition();
      else if (nb)
        center = nb->getPosition();
    }
    float radius = (float)atof(Option(f, 4, "radius", nearName.empty() ? "20" : "30").c_str());
    if (!(radius > 0) || radius > 300)
      radius = 20;
    std::string why;
    Item *item = FindGroundItem(world, center, f[3], radius, why);
    if (!item) {
      out = why;
      return true;
    }
    const hand before = item->getHandle();
    const std::string itemName = item->getName();
    const int qty = item->quantity;
    const Ogre::Vector3 itemPos = item->getPosition();
    Inventory *inv = c->getInventory();
    bool given = false;
    try {
      given = c->giveItem(item, false, false);
    } catch (...) {
      given = false;
    }
    // A stackable item can merge into a stack he has and be destroyed: only
    // touch the instance while his inventory still holds it.
    const bool held = Valid(inv) && inv->hasItem(item);
    if (given && !held) {
      ok = true;
      Log("KAH: pickup " + c->getName() + " " + itemName + " merged into a stack");
      out = "picked up " + itemName + " x" + Int(qty) + " (merged into a stack: not the same instance)";
      return true;
    }
    ok = held && item->isInInventory;
    std::string how = "giveItem=" + std::string(given ? "1" : "0");
    if (!ok && !given) {
      // The game's own way: walk over and pick it up.
      OrdersReceiver *orders = c->getOrdersReciever();
      if (Valid(orders)) {
        orders->addOrder(PICKUP, before, itemPos, true, false);
        how += " -> ordered PICKUP (check inv after the walk)";
      }
    }
    const hand after = item->getHandle();
    Log("KAH: pickup " + c->getName() + " " + itemName + " ok=" + (ok ? "1" : "0") + " " + how);
    out = std::string(ok ? "picked up " : "not picked up yet: ") + itemName + " x" + Int(qty) +
          " handle " + FormatCharacterRef(before.serial, before.index) + " -> " +
          FormatCharacterRef(after.serial, after.index) +
          (before.serial == after.serial ? " (same instance)" : " (handle changed)") +
          " in_inventory=" + (item->isInInventory ? "1" : "0") + " " + how;
    return true;
  }
  if (cmd == "order") { // order <npc> <task> [target <npc>] [building <name>] [keep]
    if (f.size() < 4) {
      out = "usage: order <npc> <task name|number> [target <npc>] [building <name>] [keep]";
      return true;
    }
    TaskType task;
    if (!ParseTask(f[3], task)) {
      out = "unknown task: " + f[3] + " (tasks <filter> lists them)";
      return true;
    }
    RootObject *target = nullptr;
    const std::string targetName = Option(f, 4, "target", "");
    const std::string buildingName = Option(f, 4, "building", "");
    Character *targetChar = nullptr;
    if (!targetName.empty()) {
      targetChar = FindCharacter(world, targetName);
      if (!targetChar) {
        out = NotFound(targetName);
        return true;
      }
      target = targetChar;
    } else if (!buildingName.empty()) {
      float dist = 0;
      target = FindBuildingT<Building>(world, c->getPosition(), buildingName, 300.0f, dist);
      if (!target) {
        out = "no building matching '" + buildingName + "' within 300 of " + c->getName();
        return true;
      }
    }
    bool keep = false;
    for (size_t i = 4; i < f.size(); ++i)
      if (Lower(f[i]) == "keep")
        keep = true;
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders)) {
      out = c->getName() + " takes no orders";
      return true;
    }
    if (targetChar)
      RunBeforeAttack(c, targetChar); // harmless for non-attack tasks
    orders->addOrder(task, target ? target->getHandle() : hand(),
                     target ? target->getPosition() : c->getPosition(), !keep, keep);
    ok = true;
    Log("KAH: order " + c->getName() + " " + TaskName(task) +
        (target ? " -> " + target->getName() : std::string()));
    out = c->getName() + " ordered " + TaskName(task) +
          (target ? " -> " + target->getName() : std::string()) +
          " (has_orders=" + (orders->hasOrders() ? "1" : "0") + ")";
    return true;
  }
  if (cmd == "fight") { // fight <a> <b>: make two characters (of different factions) fight
    if (f.size() < 4) {
      out = "usage: fight <npc> <npc2>";
      return true;
    }
    Character *b = FindCharacter(world, f[3]);
    if (!b || b == c) {
      out = "no other character named: " + f[3];
      return true;
    }
    Faction *fa = c->getFaction(), *fb = b->getFaction();
    if (!Valid(fa) || !Valid(fb)) {
      out = "faction not found";
      return true;
    }
    if (fa == fb) {
      out = "same faction (" + fa->getName() + "): move one first with faction <npc> <faction>";
      return true;
    }
    if (Valid(fa->relations))
      fa->relations->setRelation(fb, -100.0f);
    if (Valid(fb->relations))
      fb->relations->setRelation(fa, -100.0f);
    Character *pair[2][2] = {{c, b}, {b, c}};
    for (int i = 0; i < 2; ++i) {
      RunBeforeAttack(pair[i][0], pair[i][1]);
      OrdersReceiver *orders = pair[i][0]->getOrdersReciever();
      if (Valid(orders))
        orders->addOrder(UNPROVOKED_FOCUSED_MELEE_ATTACK, pair[i][1]->getHandle(),
                         pair[i][1]->getPosition(), true, false);
      pair[i][0]->attackTarget(pair[i][1]);
    }
    ok = true;
    Log("KAH: fight " + c->getName() + " <-> " + b->getName());
    out = c->getName() + " [" + fa->getName() + "] and " + b->getName() + " [" + fb->getName() +
          "] fight (factions set to -100)";
    return true;
  }
  if (cmd == "job") { // job <npc> <building> [task <name>] [radius <m>]: add a permanent job
    if (f.size() < 4) {
      out = "usage: job <npc> <building> [task <name>] [radius <m>]";
      return true;
    }
    float radius = 0, dist = 0;
    if (!ParseSearchRadius(f, 4, 0, kDefaultSearchRadius, radius, out))
      return true;
    Building *b = FindBuildingT<Building>(world, c->getPosition(), f[3], radius, dist);
    if (!b) {
      out = "no building matching '" + f[3] + "' within " + Num(radius) + " of " + c->getName();
      return true;
    }
    TaskType task = b->getDefaultTask();
    const std::string taskName = Option(f, 4, "task", "");
    if (!taskName.empty() && !ParseTask(taskName, task)) {
      out = "unknown task: " + taskName;
      return true;
    }
    c->addJob(task, b, true, true, b->getPosition());
    OrdersReceiver *orders = c->getOrdersReciever();
    ok = Valid(orders) && orders->hasPermajob(task);
    Log("KAH: job " + c->getName() + " " + TaskName(task) + " at " + b->getName());
    out = std::string(ok ? "" : "job not recorded: ") + c->getName() + " job " + TaskName(task) +
          " at " + b->getName() + " (" + Num(dist) + " away)";
    return true;
  }
  if (cmd == "jobs") { // jobs <npc>: permanent jobs
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders)) {
      out = c->getName() + " takes no orders";
      return true;
    }
    out = c->getName() + " jobs=" + Int(orders->getPermajobCount()) + ":";
    for (int i = 0; i < orders->getPermajobCount(); ++i)
      out += " [" + TaskName((int)orders->getPermajob(i)) + " " + orders->getPermajobName(i) + "]";
    out += " has_orders=" + std::string(orders->hasOrders() ? "1" : "0");
    ok = true;
    return true;
  }
  if (cmd == "clearjobs") {
    c->clearPermajobs();
    ok = true;
    out = c->getName() + " jobs cleared";
    return true;
  }
  if (cmd == "setname") { // setname <npc> <new name>
    if (f.size() < 4 || f[3].empty()) {
      out = "usage: setname <npc> <new name>";
      return true;
    }
    const std::string before = c->getName();
    c->setName(f[3]);
    ok = c->getName() == f[3];
    Log("KAH: setname " + before + " -> " + c->getName());
    out = before + " -> " + c->getName();
    return true;
  }
  if (cmd == "faction") { // faction <npc> <faction>: move the character (own squad) to a faction
    if (f.size() < 4) {
      out = "usage: faction <npc> <faction name>";
      return true;
    }
    Faction *target = FindFaction(world, f[3]);
    if (!target) {
      out = "no faction named: " + f[3];
      return true;
    }
    Faction *before = c->getFaction();
    Platoon *own = c->separateIntoMyOwnSquad(true);
    if (!Valid(own)) {
      out = "could not separate " + c->getName() + " into an own squad";
      return true;
    }
    own->setFaction(target);
    // The squad's faction alone doesn't reach the member: set it on her too.
    if (c->getFaction() != target)
      c->setFaction(target, Valid(own->getActivePlatoon()) ? own->getActivePlatoon() : c->getPlatoon());
    ok = c->getFaction() == target;
    Log("KAH: faction " + c->getName() + " " + (Valid(before) ? before->getName() : "?") + " -> " +
        (Valid(c->getFaction()) ? c->getFaction()->getName() : "?"));
    // Moving to an own squad gives the character a new handle: report it.
    out = c->getName() + " faction " + (Valid(before) ? before->getName() : "?") + " -> " +
          (Valid(c->getFaction()) ? c->getFaction()->getName() : "?") + " now " + Describe(c, nullptr);
    return true;
  }
  if (cmd == "sleep" || cmd == "wake") { // sleep <npc> [bed <name>] | wake <npc>
    OrdersReceiver *orders = c->getOrdersReciever();
    if (!Valid(orders)) {
      out = c->getName() + " takes no orders";
      return true;
    }
    if (cmd == "wake") {
      orders->clearOrders();
      orders->addOrder(GET_OUT_OF_BED, hand(), c->getPosition(), true, false);
      out = c->getName() + " ordered GET_OUT_OF_BED";
    } else {
      const std::string bed = Option(f, 3, "bed", "");
      if (!bed.empty()) {
        float dist = 0;
        Building *b = FindBuildingT<Building>(world, c->getPosition(), bed, 300.0f, dist);
        if (!b) {
          out = "no building matching '" + bed + "' within 300";
          return true;
        }
        orders->addOrder(USE_BED_ORDER, b->getHandle(), b->getPosition(), true, false);
        out = c->getName() + " ordered USE_BED_ORDER -> " + b->getName();
      } else {
        orders->addOrder(SLEEP_ON_FLOOR, hand(), c->getPosition(), true, false);
        out = c->getName() + " ordered SLEEP_ON_FLOOR";
      }
    }
    ok = true;
    Log("KAH: " + out);
    out += " (in_bed_or_cage=" + Int((int)c->inSomething) + ")";
    return true;
  }
  if (cmd == "damage") { // damage <npc> <part> <cut> [blunt] [pierce]: a real wound (bleeds)
    if (f.size() < 5) {
      out = "usage: damage <npc> <part 0-6|head|chest|stomach|left_arm|right_arm|left_leg|right_leg> "
            "<cut> [blunt] [pierce] [bleed <x>]";
      return true;
    }
    int part = ParsePart(f[3]);
    if (part < 0) {
      out = "unknown body part: " + f[3];
      return true;
    }
    MedicalSystem::HealthPartStatus *p = c->medical.getPart((unsigned __int64)part);
    if (!Valid(p)) {
      out = "no body part " + f[3];
      return true;
    }
    float cut = (float)atof(f[4].c_str());
    float blunt = f.size() >= 6 && Lower(f[5]) != "bleed" ? (float)atof(f[5].c_str()) : 0.0f;
    float pierce = f.size() >= 7 && Lower(f[6]) != "bleed" && Lower(f[5]) != "bleed"
                       ? (float)atof(f[6].c_str())
                       : 0.0f;
    // Damages' 4th value is the bleeding the wound causes (default: as deep as the cut).
    float bleed = (float)atof(Option(f, 5, "bleed", Num(cut)).c_str());
    const float before = p->flesh;
    p->applyDamage(Damages(cut, blunt, pierce, bleed, 0.0f));
    ok = true;
    Log("KAH: damage " + c->getName() + " part=" + Int(part) + " cut=" + Num(cut) + " blunt=" +
        Num(blunt) + " pierce=" + Num(pierce) + " flesh " + Num(before) + " -> " + Num(p->flesh));
    out = c->getName() + " part " + Int(part) + " flesh " + Num(before) + " -> " + Num(p->flesh) +
          " bandaging=" + Num(p->bandaging) + " blood=" + Num(c->medical.blood) + "/" +
          Num(c->medical.getMaxBlood()) + " bleed_rate=" + Num(c->medical.currentBleedRate);
    return true;
  }
  if (cmd == "blood") { // blood <npc> <value | percent%>: set blood (low blood -> collapse)
    if (f.size() < 4) {
      out = "usage: blood <npc> <value|percent%>";
      return true;
    }
    const float maxBlood = c->medical.getMaxBlood();
    const float before = c->medical.blood;
    const std::string v = f[3];
    float value = (float)atof(v.c_str());
    if (!v.empty() && v[v.size() - 1] == '%')
      value = maxBlood * value / 100.0f;
    c->medical.blood = value;
    ok = true;
    Log("KAH: blood " + c->getName() + " " + Num(before) + " -> " + Num(value));
    out = c->getName() + " blood " + Num(before) + " -> " + Num(c->medical.blood) + "/" + Num(maxBlood) +
          " (collapse below " + Num(c->medical.pointOfCollapseBloodloss()) + ")";
    return true;
  }
  if (cmd == "shackle" || cmd == "unshackle") { // shackle <npc> [owner <npc>] | unshackle <npc>
    if (cmd == "unshackle") {
      c->setChainedMode(false, hand());
    } else {
      Character *owner = nullptr;
      const std::string ownerName = Option(f, 3, "owner", "");
      if (!ownerName.empty() && !(owner = FindCharacter(world, ownerName))) {
        out = NotFound(ownerName);
        return true;
      }
      c->setChainedMode(true, owner ? owner->getHandle() : hand());
    }
    ok = (cmd == "shackle") == c->isChainedMode();
    Log("KAH: " + cmd + " " + c->getName() + " chained=" + (c->isChainedMode() ? "1" : "0"));
    out = c->getName() + " chained=" + (c->isChainedMode() ? "1" : "0") +
          " slave_state=" + Int((int)c->isSlave());
    return true;
  }
  if (cmd == "cage" || cmd == "uncage") { // cage <npc> [cage name] | uncage <npc> [cage name]
    float dist = 0;
    const std::string cageName = f.size() >= 4 ? f[3] : "cage";
    UseableStuff *cage = FindBuildingT<UseableStuff>(world, c->getPosition(), cageName, 300.0f, dist);
    if (!cage) {
      out = "no cage matching '" + cageName + "' within 300 of " + c->getName();
      return true;
    }
    if (cmd == "cage") {
      c->teleport(cage->getPosition(), Ogre::Quaternion::IDENTITY);
      c->setPrisonMode(true, cage);
    } else {
      c->setPrisonMode(false, cage);
    }
    ok = (cmd == "cage") == (c->inSomething == IN_PRISON);
    Log("KAH: " + cmd + " " + c->getName() + " " + cage->getName() + " state=" + Int((int)c->inSomething));
    out = c->getName() + " " + cmd + " " + cage->getName() + " (" + Num(dist) +
          " away) state=" + Int((int)c->inSomething) + " (0 nothing, 1 bed, 2 prison)";
    return true;
  }
  if (cmd == "shopstock") { // shopstock <trader> [radius <m>]: goods for sale (own + shop storage)
    float radius = 0;
    if (!ParseSearchRadius(f, 3, 0, kDefaultShopRadius, radius, out, kMaxShopRadius))
      return true;
    std::vector<ShopSource> sources;
    CollectShopSources(world, c, radius, sources);
    out = c->getName() + " trader=" + (c->isATrader() ? "1" : "0") + " money=" + Int(c->getMoney());
    for (size_t i = 0; i < sources.size(); ++i) {
      out += " || " + sources[i].name + ":";
      std::vector<Item *> items;
      InventoryItems(sources[i].inv, items);
      for (size_t k = 0; k < items.size() && k < 40; ++k)
        out += " [" + items[k]->getName() + " x" + Int(items[k]->quantity) + " $" +
               Int(items[k]->getValueSingle(true)) + (items[k]->isEquipped ? " worn" : "") + "]";
    }
    ok = true;
    return true;
  }
  if (cmd == "trade") { // trade <buyer> <trader> <item> [radius <m>]: buy through the game's purchase path
    if (f.size() < 5) {
      out = "usage: trade <buyer> <trader> <item> [radius <m>]";
      return true;
    }
    float radius = 0;
    if (!ParseSearchRadius(f, 5, 0, kDefaultShopRadius, radius, out, kMaxShopRadius))
      return true;
    Character *trader = FindCharacter(world, f[3]);
    if (!trader) {
      out = NotFound(f[3]);
      return true;
    }
    std::vector<ShopSource> sources;
    CollectShopSources(world, trader, radius, sources);
    const std::string wanted = Lower(f[4]);
    Item *item = nullptr;
    Inventory *from = nullptr;
    std::string fromName;
    for (size_t i = 0; i < sources.size() && !item; ++i) {
      std::vector<Item *> items;
      InventoryItems(sources[i].inv, items);
      for (size_t k = 0; k < items.size(); ++k) {
        if (items[k]->isEquipped)
          continue;
        const std::string n = Lower(items[k]->getName());
        if (n == wanted || (!item && n.find(wanted) != std::string::npos)) {
          item = items[k];
          from = sources[i].inv;
          fromName = sources[i].name;
          if (n == wanted)
            break;
        }
      }
    }
    if (!item) {
      out = trader->getName() + " has no (unworn) " + f[4] + " for sale (shopstock lists the goods)";
      return true;
    }
    const int buyerBefore = c->getMoney(), traderBefore = trader->getMoney();
    const std::string itemName = item->getName();
    GameData *itemData = item->data;
    Inventory *buyerInv = c->getInventory();
    Inventory *traderInv = trader->getInventory();
    // Run m16: a full buyer (the Trader fixture's Shay, room=0 for every item)
    // made buyItem refuse or hand back an item nothing could place, and the
    // reply only said "placed=failed". Say why up front; nothing moves.
    bool buyerRoom = true;
    if (Valid(buyerInv) && itemData) {
      try {
        buyerRoom = buyerInv->hasRoomForItem(itemData);
      } catch (...) {
        buyerRoom = true;
      }
    }
    if (!buyerRoom) {
      Log("KAH: trade " + c->getName() + " <- " + trader->getName() + " (" + fromName + ") " +
          itemName + " refused: buyer has no room");
      out = "trade failed: " + c->getName() + " has no room for " + itemName +
            " (inventory full; nothing bought, no cats moved: free space or use another buyer)";
      return true;
    }
    std::vector<std::string> problems;
    std::string steps; // what happened, in order (reply + harness.log)
    // Shop storage (counters, barrels) is not something the game sells from:
    // its items read value 0 and buyItem there pays nobody (run m9). The
    // trader's own inventory is what the trade window sells, so the item moves
    // there first (the trader "takes it from the shelf"), then the normal
    // purchase runs. If the game still prices it at 0 (run m10: armour made
    // by fill/give), or the move equipped it on the trader, or buyItem
    // refuses, the item is sold by hand: taken out, the buyer pays the
    // fallback price (game value, else average price, else game data value),
    // the trader gets the cats, the item goes to the buyer.
    Inventory *storage = nullptr;
    if (from != traderInv) {
      if (!Valid(traderInv)) {
        out = "trade failed: " + trader->getName() + " has no inventory to sell " + itemName + " from";
        return true;
      }
      Item *moved = from->removeItemDontDestroy_returnsItem(item, 1, true);
      if (!Valid(moved)) {
        out = "trade failed: could not take " + itemName + " out of " + fromName;
        return true;
      }
      if (!traderInv->addItem(moved, 1, false, false)) {
        from->addItem(moved, 1, false, true);
        out = "trade failed: " + trader->getName() + "'s inventory has no room for " + itemName +
              " from " + fromName + " (item left in " + fromName + ")";
        return true;
      }
      storage = from;
      from = traderInv;
      // A stackable item may merge into a stack the trader has: find what
      // is there now (the moved instance if it still exists, else the stack).
      item = nullptr;
      std::vector<Item *> held;
      InventoryItems(traderInv, held);
      for (size_t k = 0; k < held.size(); ++k)
        if (held[k] == moved)
          item = moved;
      for (size_t k = 0; k < held.size() && !item; ++k)
        if (held[k]->data == itemData && !held[k]->isEquipped)
          item = held[k];
      if (!item) {
        out = "trade failed: " + itemName + " vanished after moving it from " + fromName + " to " +
              trader->getName();
        return true;
      }
      steps += " moved " + fromName + " -> " + trader->getName() + " (section '" +
               item->inventorySection + "'" + (item->isEquipped ? ", equipped" : "") + ")";
    }
    int price = item->getValueSingle(true);
    int fallbackPrice = price;
    if (price <= 0) {
      // Why the game says 0: the item's own numbers.
      std::string diag = "the game prices it at 0 (level=" + Int(item->getLevel()) +
                         " quality=" + Num(item->quality) +
                         " material=" + (Valid(item->materialData) ? item->materialData->name : std::string("-")) +
                         " maker=" + (Valid(item->manufacturerData) ? item->manufacturerData->name : std::string("-")) +
                         " stolen=" + (item->isStolen(false) ? "1" : "0");
      const int avg = item->getAvgPrice();
      int dataValue = 0;
      if (Valid(itemData)) {
        try {
          if (itemData->idata.find("value") != itemData->idata.end())
            dataValue = itemData->idata.find("value")->second;
        } catch (...) {
          dataValue = 0;
        }
      }
      diag += " avg_price=" + Int(avg) + " data_value=" + Int(dataValue) + ")";
      problems.push_back(diag);
      fallbackPrice = avg > 0 ? avg : (dataValue > 0 ? dataValue : 0);
    }
    const int countBefore = (Valid(buyerInv) && itemData) ? CountAllSections(buyerInv, itemData) : 0;
    Item *bought = nullptr;
    bool manual = item->isEquipped || price <= 0;
    if (!manual) {
      bought = from->buyItem(item, c);
      if (!Valid(bought)) {
        problems.push_back("buyItem refused (buyer cats " + Int(c->getMoney()) + ", price " + Int(price) + ")");
        manual = true;
      }
    }
    if (manual) {
      if (c->getMoney() < fallbackPrice) {
        problems.push_back("buyer can't afford " + Int(fallbackPrice));
      } else if (Valid(item) && item->isEquipped && !storage) {
        problems.push_back("the trader wears it");
      } else {
        Item *taken = from->removeItemDontDestroy_returnsItem(item, 1, true);
        if (Valid(taken)) {
          c->takeMoney(fallbackPrice);
          trader->takeMoney(-fallbackPrice);
          bought = taken;
          price = fallbackPrice;
          steps += " sold by hand for " + Int(fallbackPrice);
        } else {
          problems.push_back("could not take it out of " + trader->getName() + "'s inventory");
        }
      }
    }
    ok = Valid(bought);
    if (!ok && storage) { // put it back on the shelf
      Item *back = traderInv->removeItemDontDestroy_returnsItem(item, 1, true);
      if (Valid(back) && !storage->addItem(back, 1, false, false))
        traderInv->addItem(back, 1, false, true);
      steps += " returned to " + fromName;
    }
    // buyItem (and the hand sale) leave the item detached (no inventory, not on the ground).
    // Place it the way `give`/`transfer` do (Inventory::addItem, which works for hats where
    // giveItem did not: run m12), then Character::giveItem with drop-at-feet. If neither
    // takes it, the buyer is refunded and the item goes back where it came from.
    std::string placed = ok ? "already" : "-";
    if (ok && !bought->isInInventory && !bought->_isPhysical) {
      const int qty = bought->quantity > 0 ? bought->quantity : 1;
      steps += " placing (qty=" + Int(qty) + " room=" +
               (Valid(buyerInv) && itemData ? (buyerInv->hasRoomForItem(itemData) ? "1" : "0") : "?") +
               " equipped=" + (bought->isEquipped ? "1" : "0") + ")";
      const bool pendingBefore = bought->creatingPhysical || bought->physicalShouldExist;
      bool given = false;
      if (Valid(buyerInv)) {
        try {
          given = buyerInv->addItem(bought, qty, false, false);
        } catch (...) {
          given = false;
        }
        steps += std::string(" addItem=") + (given ? "1" : "0");
      }
      if (!given) {
        // giveItem with dropOnFail drops the item at her feet but still returns false
        // (run m12; Stobe's hand-over ignores its result for the same reason), so the
        // item's own state decides. Last resort: RootObject::dropItem.
        bool r = false;
        try {
          r = c->giveItem(bought, true, false);
        } catch (...) {
          r = false;
        }
        given = PlacedOrDropping(bought, pendingBefore);
        steps += std::string(" giveItem(drop)=") + (r ? "1" : "0") + (given ? " placed" : " not placed");
        if (!given) {
          try {
            c->dropItem(bought);
          } catch (...) {
          }
          given = PlacedOrDropping(bought, pendingBefore);
          steps += std::string(" dropItem=") + (given ? "placed" : "not placed");
        }
      }
      placed = given ? (bought->isInInventory ? "inventory" : "ground") : "failed";
      if (given && !bought->isInInventory && !bought->_isPhysical)
        steps += " (ground object still being built)";
      if (!given) {
        // No money lost: refund what moved and put the item back.
        const int paidNow = buyerBefore - c->getMoney(), receivedNow = trader->getMoney() - traderBefore;
        if (paidNow != 0)
          c->takeMoney(-paidNow);
        if (receivedNow != 0)
          trader->takeMoney(receivedNow);
        Inventory *home = storage ? storage : traderInv;
        bool back = false;
        try {
          back = Valid(home) && home->addItem(bought, qty, false, false);
          if (!back && storage && Valid(traderInv))
            back = traderInv->addItem(bought, qty, false, false);
        } catch (...) {
          back = false;
        }
        steps += " refunded " + Int(paidNow) + (back ? " and put back" : " (item could NOT be put back)");
        problems.push_back("the buyer's inventory refused the item and it could not be dropped; refunded");
        ok = false;
      }
    }
    const int arrived = (Valid(buyerInv) && itemData) ? CountAllSections(buyerInv, itemData) - countBefore : 0;
    const int paid = buyerBefore - c->getMoney(), received = trader->getMoney() - traderBefore;
    if (ok && price > 0 && paid != price)
      problems.push_back("buyer paid " + Int(paid) + " of " + Int(price));
    if (ok && paid > 0 && received != paid)
      problems.push_back("trader received " + Int(received) + " of " + Int(paid));
    if (ok && arrived <= 0 && placed != "ground")
      problems.push_back("nothing arrived in the buyer's inventory");
    std::string why;
    for (size_t i = 0; i < problems.size(); ++i)
      why += std::string(i ? "; " : " problems: ") + problems[i];
    const std::string source = storage ? fromName + " via " + trader->getName() : fromName;
    Log("KAH: trade " + c->getName() + " <- " + trader->getName() + " (" + source + ") " + itemName +
        " ok=" + (ok ? "1" : "0") + " placed=" + placed + " arrived=" + Int(arrived) + " buyer " +
        Int(buyerBefore) + " -> " + Int(c->getMoney()) + " trader " + Int(traderBefore) + " -> " +
        Int(trader->getMoney()) + " steps:" + steps + why);
    out = std::string(ok ? "bought " : "trade failed: ") + itemName + " from " + source +
          " (price " + Int(price) + ") arrived=" + Int(arrived) + " placed=" + placed + ", buyer cats " +
          Int(buyerBefore) + " -> " + Int(c->getMoney()) + ", trader cats " + Int(traderBefore) + " -> " +
          Int(trader->getMoney()) + " steps:" + (steps.empty() ? std::string(" buyItem") : steps) + why;
    return true;
  }
  if (cmd == "eat") { // eat <npc> <food item in inventory>
    if (f.size() < 4) {
      out = "usage: eat <npc> <food item>";
      return true;
    }
    bool ambiguous = false;
    Item *food = FindInventoryItem(c, f[3], ambiguous);
    if (!Valid(food)) {
      out = c->getName() + " has no " + f[3];
      return true;
    }
    const float before = c->medical.hunger * 100.0f;
    ok = c->eatItem(food, c->getInventory());
    out = c->getName() + (ok ? " ate " : " could not eat ") + f[3] + " hunger " + Num(before) +
          " -> " + Num(c->medical.hunger * 100.0f);
    return true;
  }
  return false;
}
