// Arguments of `contract-bodyguard <npc> [<hirer>] [hours <n>] [own] [replace] [package <name|sid>] | end | status`
// (imm26 row 18-a: a squad needs a native Bodyguard contract on its Blackboard). Free of game headers so the
// offline test (tests\contract_args_test.cpp) can build it. f[0] is the client tag, f[1] the command, f[2] the npc.
#pragma once
#include <cstdlib>
#include <string>
#include <vector>

struct ContractArgs {
  std::string mode;    // "hire" | "end" | "status"
  std::string hirer;   // character reference; default "@player"
  std::string package; // AI_PACKAGE name or stringID; default "Bodyguard"
  int hours;           // 0 = the game's own default length
  bool own;            // separate the npc into an own squad first (needed for a player-squad member)
  bool replace;        // end an existing contract first
  std::string error;   // non-empty = bad arguments
  ContractArgs() : mode("hire"), hirer("@player"), package("Bodyguard"), hours(0), own(false), replace(false) {}
};

inline std::string ContractLower(std::string s) {
  for (size_t i = 0; i < s.size(); ++i)
    if (s[i] >= 'A' && s[i] <= 'Z')
      s[i] = (char)(s[i] - 'A' + 'a');
  return s;
}

inline bool ContractIsNumber(const std::string &s) {
  if (s.empty())
    return false;
  for (size_t i = 0; i < s.size(); ++i)
    if (s[i] < '0' || s[i] > '9')
      return false;
  return true;
}

inline ContractArgs ParseContractArgs(const std::vector<std::string> &f) {
  ContractArgs a;
  bool hirerSet = false;
  for (size_t i = 3; i < f.size(); ++i) {
    const std::string t = ContractLower(f[i]);
    if (t == "end" || t == "status") {
      a.mode = t;
    } else if (t == "own") {
      a.own = true;
    } else if (t == "replace") {
      a.replace = true;
    } else if (t == "hours" || t == "package" || t == "hirer") {
      if (i + 1 >= f.size() || f[i + 1].empty()) {
        a.error = "missing value after " + t;
        return a;
      }
      const std::string &v = f[++i];
      if (t == "hours") {
        if (!ContractIsNumber(v) || atoi(v.c_str()) < 1 || atoi(v.c_str()) > 2000) {
          a.error = "hours must be 1..2000";
          return a;
        }
        a.hours = atoi(v.c_str());
      } else if (t == "package") {
        a.package = v;
      } else {
        a.hirer = v;
        hirerSet = true;
      }
    } else if (ContractIsNumber(t)) {
      if (atoi(t.c_str()) < 1 || atoi(t.c_str()) > 2000) {
        a.error = "hours must be 1..2000";
        return a;
      }
      a.hours = atoi(t.c_str());
    } else if (!hirerSet) {
      a.hirer = f[i];
      hirerSet = true;
    } else {
      a.error = "unexpected argument: " + f[i];
      return a;
    }
  }
  return a;
}
