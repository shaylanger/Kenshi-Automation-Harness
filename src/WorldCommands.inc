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
bool RunWorldCommand(GameWorld *world, const std::vector<std::string> &f, const Ogre::Vector3 &origin,
                     bool &ok, std::string &out) {
  const std::string cmd = Lower(f[1]);
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
        out = "no character named: " + nearName;
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
  if (cmd == "power") { // power <building> on|off|charge [radius <m>]
    if (f.size() < 4) {
      out = "usage: power <building> on|off|charge [radius <m>]";
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
    } else {
      out = "usage: power <building> on|off|charge";
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
        out = "no character named: " + targetName;
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
        out = "no character named: " + ownerName;
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
      out = "no character named: " + f[3];
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
    const int price = item->getValueSingle(true);
    GameData *itemData = item->data;
    Inventory *buyerInv = c->getInventory();
    const int countBefore = (Valid(buyerInv) && itemData) ? CountAllSections(buyerInv, itemData) : 0;
    Item *bought = from->buyItem(item, c);
    ok = Valid(bought);
    // buyItem takes the money and hands the item back detached (no inventory, not on the
    // ground): place it like the trade window does, into the buyer's inventory or at her feet.
    std::string placed = "already";
    if (ok && !bought->isInInventory && !bought->_isPhysical) {
      bool given = false;
      try {
        given = c->giveItem(bought, true, false);
      } catch (...) {
        given = false;
      }
      placed = given ? (bought->isInInventory ? "inventory" : (bought->_isPhysical ? "ground" : "unknown"))
                     : "failed";
    }
    const int arrived = (Valid(buyerInv) && itemData) ? CountAllSections(buyerInv, itemData) - countBefore : 0;
    Log("KAH: trade " + c->getName() + " <- " + trader->getName() + " (" + fromName + ") " + itemName +
        " ok=" + (ok ? "1" : "0") + " placed=" + placed + " arrived=" + Int(arrived) + " buyer " +
        Int(buyerBefore) + " -> " + Int(c->getMoney()) + " trader " + Int(traderBefore) + " -> " +
        Int(trader->getMoney()));
    out = std::string(ok ? "bought " : "trade failed: ") + itemName + " from " + fromName +
          " (value " + Int(price) + ") arrived=" + Int(arrived) + " placed=" + placed + ", buyer cats " +
          Int(buyerBefore) + " -> " + Int(c->getMoney()) + ", trader cats " + Int(traderBefore) + " -> " +
          Int(trader->getMoney());
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
