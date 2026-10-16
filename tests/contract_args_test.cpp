// Offline test of the `contract-bodyguard` argument parser (src/ContractArgs.h).
// Build and run: tests\run_tests.bat
#include "ContractArgs.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

static std::vector<std::string> Cmd(const char *a = 0, const char *b = 0, const char *c = 0, const char *d = 0,
                                    const char *e = 0) {
  std::vector<std::string> f;
  f.push_back("t");
  f.push_back("contract-bodyguard");
  f.push_back("Malzin");
  const char *rest[] = {a, b, c, d, e};
  for (int i = 0; i < 5; ++i)
    if (rest[i])
      f.push_back(rest[i]);
  return f;
}

int main() {
  ContractArgs a = ParseContractArgs(Cmd());
  Check(a.error.empty() && a.mode == "hire" && a.hirer == "@player" && a.package == "Bodyguard" && a.hours == 0 &&
            !a.own && !a.replace,
        "defaults: hire by @player, package Bodyguard, game default hours");
  a = ParseContractArgs(Cmd("Shay"));
  Check(a.error.empty() && a.hirer == "Shay", "bare word = hirer");
  a = ParseContractArgs(Cmd("Shay", "48"));
  Check(a.error.empty() && a.hirer == "Shay" && a.hours == 48, "hirer + bare number = hours");
  a = ParseContractArgs(Cmd("hours", "12", "own", "replace"));
  Check(a.error.empty() && a.hours == 12 && a.own && a.replace && a.hirer == "@player", "keywords hours/own/replace");
  a = ParseContractArgs(Cmd("package", "5090-gamedata.base", "hirer", "#7"));
  Check(a.error.empty() && a.package == "5090-gamedata.base" && a.hirer == "#7", "package + hirer keywords");
  a = ParseContractArgs(Cmd("end"));
  Check(a.error.empty() && a.mode == "end", "end");
  a = ParseContractArgs(Cmd("STATUS"));
  Check(a.error.empty() && a.mode == "status", "status is case-insensitive");
  a = ParseContractArgs(Cmd("hours"));
  Check(!a.error.empty(), "hours without value is an error");
  a = ParseContractArgs(Cmd("hours", "0"));
  Check(!a.error.empty(), "hours 0 rejected");
  a = ParseContractArgs(Cmd("hours", "99999"));
  Check(!a.error.empty(), "hours too large rejected");
  a = ParseContractArgs(Cmd("Shay", "Cind"));
  Check(!a.error.empty(), "two hirers rejected");
  printf(g_failed ? "%d FAILED\n" : "ALL PASS\n", g_failed);
  return g_failed ? 1 : 0;
}
