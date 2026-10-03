// Offline test of the "build" arguments (src/BuildArgs.h).
// Build and run: tests\run_tests.bat
#include "BuildArgs.h"

#include <cctype>
#include <cstdio>

std::string Lower(const std::string &value) {
  std::string out = value;
  for (size_t i = 0; i < out.size(); ++i)
    out[i] = (char)tolower((unsigned char)out[i]);
  return out;
}

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

// "1", "build", then the space-free arguments of `line` (| separates fields).
std::vector<std::string> Args(const std::string &line) {
  std::vector<std::string> f;
  f.push_back("1");
  f.push_back("build");
  size_t start = 0;
  while (start <= line.size()) {
    size_t bar = line.find('|', start);
    if (bar == std::string::npos)
      bar = line.size();
    if (bar > start)
      f.push_back(line.substr(start, bar - start));
    start = bar + 1;
  }
  return f;
}

int main() {
  BuildArgs a;
  std::string err;

  Check(ParseBuildArgs(Args("Bed"), a, err) && a.name == "Bed" && !a.at && a.nearName.empty() &&
            a.dist == 10.0f && a.faction.empty(),
        "name only: near the player, dist 10, player faction");
  Check(ParseBuildArgs(Args("Prisoner Cage|near|Shay|dist|15"), a, err) &&
            a.name == "Prisoner Cage" && a.nearName == "Shay" && a.dist == 15.0f,
        "near npc with dist");
  Check(ParseBuildArgs(Args("Bed|at|100.5|20|-300|faction|Drifters"), a, err) && a.at &&
            a.x == 100.5f && a.y == 20.0f && a.z == -300.0f && a.faction == "Drifters",
        "at x y z with faction");
  Check(ParseBuildArgs(Args("Bed|FACTION|Nameless|NEAR|Malzin"), a, err) &&
            a.faction == "Nameless" && a.nearName == "Malzin",
        "keywords are case-insensitive, any order");

  Check(!ParseBuildArgs(Args(""), a, err) && err.find("usage") != std::string::npos,
        "missing name refused");
  Check(!ParseBuildArgs(Args("Bed|near|Shay|at|1|2|3"), a, err), "near and at together refused");
  Check(!ParseBuildArgs(Args("Bed|at|1|2|x"), a, err), "at with a non-number refused");
  Check(!ParseBuildArgs(Args("Bed|at|1|2"), a, err), "at with two numbers refused");
  Check(!ParseBuildArgs(Args("Bed|dist|-1"), a, err), "negative dist refused");
  Check(!ParseBuildArgs(Args("Bed|dist|500"), a, err), "dist above 200 refused");
  Check(!ParseBuildArgs(Args("Bed|near"), a, err), "near without a name refused");
  Check(!ParseBuildArgs(Args("Bed|rotate|90"), a, err) &&
            err.find("rotate") != std::string::npos,
        "unknown option refused");

  printf(g_failed ? "%d FAILED\n" : "all build argument tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
