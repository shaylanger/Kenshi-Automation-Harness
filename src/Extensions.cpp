// Commands and hooks other mods register through the exported C API
// (include/KenshiAutomationHarness.h).
#include "Harness.h"

#include "../include/KenshiAutomationHarness.h"

#include <windows.h>
#include <map>

namespace {

struct ExtensionCommand {
  std::string usage;
  KAH_CommandFn fn;
  void *user;
};

struct AttackHook {
  KAH_AttackFn fn;
  void *user;
};

// Registration may come from another plugin's startPlugin thread; commands
// run on the game thread.
CRITICAL_SECTION g_lock;
struct LockInit {
  LockInit() { InitializeCriticalSection(&g_lock); }
} g_lockInit;

std::map<std::string, ExtensionCommand> g_commands;
std::vector<AttackHook> g_attackHooks;
// Ids a handler answered with KAH_PENDING and hasn't completed yet.
std::map<std::string, std::string> g_pending; // id -> command

void AppendReply(KAH_Reply *reply, const char *text) {
  if (reply && reply->impl && text)
    *static_cast<std::string *>(reply->impl) += text;
}

bool ValidName(const std::string &name) {
  if (name.empty() || name.size() > 64)
    return false;
  for (size_t i = 0; i < name.size(); ++i) {
    char ch = name[i];
    if (!(isalnum((unsigned char)ch) || ch == '_' || ch == '-' || ch == '.'))
      return false;
  }
  return true;
}

} // namespace

bool HasExtensionCommand(const std::string &name) {
  EnterCriticalSection(&g_lock);
  bool found = g_commands.find(name) != g_commands.end();
  LeaveCriticalSection(&g_lock);
  return found;
}

std::string RunExtensionCommand(const std::vector<std::string> &f, bool &ok, bool &pending) {
  ok = false;
  pending = false;
  ExtensionCommand command;
  EnterCriticalSection(&g_lock);
  std::map<std::string, ExtensionCommand>::const_iterator it = g_commands.find(Lower(f[1]));
  bool found = it != g_commands.end();
  if (found)
    command = it->second;
  LeaveCriticalSection(&g_lock);
  if (!found)
    return "unknown command: " + f[1];

  std::vector<const char *> argv;
  for (size_t i = 1; i < f.size(); ++i)
    argv.push_back(f[i].c_str());
  std::string text;
  KAH_Reply reply;
  reply.impl = &text;
  reply.append = &AppendReply;
  // Marked pending before the call: the mod may complete it (from another
  // thread) before the handler even returns.
  EnterCriticalSection(&g_lock);
  g_pending[f[0]] = f[1];
  LeaveCriticalSection(&g_lock);
  int result = KAH_ERROR;
  try {
    result = command.fn(f[0].c_str(), (int)argv.size(), &argv[0], &reply, command.user);
  } catch (...) {
    result = KAH_ERROR;
    text = "exception in extension command " + f[1];
  }
  if (result == KAH_PENDING) {
    pending = true; // KAH_Complete writes the reply
    return "";
  }
  EnterCriticalSection(&g_lock);
  g_pending.erase(f[0]);
  LeaveCriticalSection(&g_lock);
  ok = result == KAH_OK;
  return text;
}

void RunBeforeAttack(Character *attacker, Character *target) {
  EnterCriticalSection(&g_lock);
  std::vector<AttackHook> hooks = g_attackHooks;
  LeaveCriticalSection(&g_lock);
  for (size_t i = 0; i < hooks.size(); ++i) {
    try {
      hooks[i].fn(attacker, target, hooks[i].user);
    } catch (...) {
      Log("KAH: exception in a before-attack hook");
    }
  }
}

std::string ExtensionCommandList() {
  std::string out;
  EnterCriticalSection(&g_lock);
  for (std::map<std::string, ExtensionCommand>::const_iterator it = g_commands.begin();
       it != g_commands.end(); ++it)
    out += (out.empty() ? " Mods: " : " | ") +
           (it->second.usage.empty() ? it->first : it->second.usage);
  LeaveCriticalSection(&g_lock);
  return out;
}

extern "C" {

__declspec(dllexport) int KAH_ApiVersion() { return KAH_API_VERSION; }

__declspec(dllexport) int KAH_RegisterCommand(const char *name, const char *usage,
                                              KAH_CommandFn fn, void *user) {
  const std::string key = Lower(name ? name : "");
  if (!fn || !ValidName(key) || IsBuiltinCommand(key)) {
    Log("KAH: register command refused: " + key);
    return 0;
  }
  ExtensionCommand command;
  command.usage = usage ? usage : "";
  command.fn = fn;
  command.user = user;
  EnterCriticalSection(&g_lock);
  bool taken = g_commands.find(key) != g_commands.end();
  if (!taken)
    g_commands[key] = command;
  LeaveCriticalSection(&g_lock);
  Log("KAH: register command " + key + (taken ? " refused (taken)" : ""));
  return taken ? 0 : 1;
}

__declspec(dllexport) int KAH_RegisterBeforeAttack(KAH_AttackFn fn, void *user) {
  if (!fn)
    return 0;
  AttackHook hook;
  hook.fn = fn;
  hook.user = user;
  EnterCriticalSection(&g_lock);
  g_attackHooks.push_back(hook);
  LeaveCriticalSection(&g_lock);
  Log("KAH: register before-attack hook");
  return 1;
}

__declspec(dllexport) void KAH_Complete(const char *id, int ok, const char *text) {
  const std::string key = id ? id : "";
  EnterCriticalSection(&g_lock);
  std::map<std::string, std::string>::iterator it = g_pending.find(key);
  bool known = it != g_pending.end();
  if (known)
    g_pending.erase(it);
  LeaveCriticalSection(&g_lock);
  if (!known) {
    Log("KAH: complete for an unknown or already answered id: " + key);
    return;
  }
  WriteOutbox(key, ok == KAH_OK, text ? text : "");
}

__declspec(dllexport) void KAH_Log(const char *message) {
  Log(std::string("EXT: ") + (message ? message : ""));
}

} // extern "C"
