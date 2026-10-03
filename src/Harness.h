#pragma once
// Shared internals of AutomationHarness.dll.

#include <string>
#include <vector>

class Character;
class GameWorld;

// Folder of AutomationHarness.dll (the mod folder): the switch file, inbox,
// outbox, autoload.txt and harness.log live here.
const std::string &HarnessDir();
bool FileExists(const std::string &path);
// The harness only acts while <HarnessDir>\enabled.flag exists.
bool HarnessEnabled();

void Log(const std::string &msg);
// Appends "id<TAB>ok|error<TAB>detail" to outbox.txt (any thread).
void WriteOutbox(const std::string &id, bool ok, const std::string &detail);

std::string Lower(const std::string &value);
std::string OneLine(const std::string &value);
std::string Num(double v);
std::string Int(long long v);

// Commands.cpp: runs one inbox line (f[0] = id, f[1] = command, f[2..] = args).
// pending: a mod's handler answers later (KAH_Complete); write no reply now.
std::string RunCommand(GameWorld *world, const std::vector<std::string> &f, bool &ok,
                       bool &pending);
std::string Phase(GameWorld *world);
// Notices the end of a pending load (call every tick while one is pending).
bool LoadPending();

bool IsBuiltinCommand(const std::string &name);

// Extensions.cpp: commands and hooks registered by other mods.
bool HasExtensionCommand(const std::string &name);
std::string RunExtensionCommand(const std::vector<std::string> &f, bool &ok, bool &pending);
void RunBeforeAttack(Character *attacker, Character *target);
std::string ExtensionCommandList();

// Inventory.cpp: inventory incl. worn items and backpack, as a JSON array.
bool BuildInventoryJson(Character *c, std::string &json, int &count);
