// Offline test of the extension registry (src/Extensions.cpp) with the game
// parts stubbed: registration rules, ok/error replies, deferred replies.
// Build and run: tests\run_tests.bat
#include "Harness.h"
#include "../include/KenshiAutomationHarness.h"

#include <cstdio>
#include <map>

// --- stubs for what Extensions.cpp uses from the rest of the DLL ---
std::vector<std::string> g_log;
std::map<std::string, std::string> g_outbox; // id -> "ok|error detail"
void Log(const std::string &msg) { g_log.push_back(msg); }
void WriteOutbox(const std::string &id, bool ok, const std::string &detail) {
  g_outbox[id] = std::string(ok ? "ok " : "error ") + detail;
}
std::string Lower(const std::string &value) {
  std::string out = value;
  for (size_t i = 0; i < out.size(); ++i)
    out[i] = (char)tolower((unsigned char)out[i]);
  return out;
}
bool IsBuiltinCommand(const std::string &name) { return Lower(name) == "status"; }

extern "C" {
int KAH_ApiVersion();
int KAH_RegisterCommand(const char *, const char *, KAH_CommandFn, void *);
int KAH_RegisterBeforeAttack(KAH_AttackFn, void *);
void KAH_Complete(const char *, int, const char *);
}

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

std::vector<std::string> Line(const char *id, const char *cmd, const char *arg) {
  std::vector<std::string> f;
  f.push_back(id);
  f.push_back(cmd);
  if (arg)
    f.push_back(arg);
  return f;
}

int Echo(const char *, int argc, const char *const *argv, KAH_Reply *reply, void *) {
  if (argc < 2) {
    reply->append(reply, "usage: echo <text>");
    return KAH_ERROR;
  }
  reply->append(reply, "echo:");
  reply->append(reply, argv[1]);
  return KAH_OK;
}

std::string g_deferredId;
int Deferred(const char *id, int, const char *const *, KAH_Reply *, void *) {
  g_deferredId = id;
  return KAH_PENDING;
}

int Throws(const char *, int, const char *const *, KAH_Reply *, void *) { throw 1; }

int g_attacks = 0;
void OnAttack(void *, void *, void *user) { g_attacks += *(int *)user; }

int main() {
  Check(KAH_ApiVersion() == KAH_API_VERSION, "api version");
  Check(KAH_RegisterCommand("echo", "echo <text>", &Echo, nullptr) == 1, "register echo");
  Check(KAH_RegisterCommand("ECHO", "", &Echo, nullptr) == 0, "duplicate name refused");
  Check(KAH_RegisterCommand("status", "", &Echo, nullptr) == 0, "built-in name refused");
  Check(KAH_RegisterCommand("bad name", "", &Echo, nullptr) == 0, "invalid name refused");
  Check(KAH_RegisterCommand("nofn", "", nullptr, nullptr) == 0, "null handler refused");
  Check(KAH_RegisterCommand("later", "later", &Deferred, nullptr) == 1, "register later");
  Check(KAH_RegisterCommand("boom", "", &Throws, nullptr) == 1, "register boom");
  Check(HasExtensionCommand("echo") && !HasExtensionCommand("nope"), "lookup");

  bool ok = false, pending = false;
  std::string text = RunExtensionCommand(Line("1", "Echo", "hi"), ok, pending);
  Check(ok && !pending && text == "echo:hi", "ok reply (case-insensitive name)");
  text = RunExtensionCommand(Line("2", "echo", nullptr), ok, pending);
  Check(!ok && !pending && text == "usage: echo <text>", "error reply");
  text = RunExtensionCommand(Line("3", "boom", nullptr), ok, pending);
  Check(!ok && !pending && text.find("exception") != std::string::npos, "exception caught");

  text = RunExtensionCommand(Line("4", "later", nullptr), ok, pending);
  Check(pending && g_deferredId == "4" && g_outbox.count("4") == 0, "pending: no reply yet");
  KAH_Complete("4", KAH_OK, "done later");
  Check(g_outbox["4"] == "ok done later", "complete writes the reply");
  KAH_Complete("4", KAH_OK, "twice");
  Check(g_outbox["4"] == "ok done later", "second complete ignored");
  KAH_Complete("unknown", KAH_OK, "x");
  Check(g_outbox.count("unknown") == 0, "unknown id ignored");

  int weight = 2;
  Check(KAH_RegisterBeforeAttack(&OnAttack, &weight) == 1, "register attack hook");
  RunBeforeAttack(nullptr, nullptr);
  Check(g_attacks == 2, "attack hook called");
  Check(ExtensionCommandList().find("echo <text>") != std::string::npos, "help lists usage");

  printf(g_failed ? "%d FAILED\n" : "all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
