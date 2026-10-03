// Offline test of the import flag names (src/ImportFlags.h).
// Build and run: tests\run_tests.bat
#include "ImportFlags.h"

#include <algorithm>
#include <cctype>
#include <cstdio>

std::string Lower(const std::string &value) {
  std::string out = value;
  std::transform(out.begin(), out.end(), out.begin(), ::tolower);
  return out;
}

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  std::string bad;
  Check(ParseImportFlags("squad", bad) == 0x2, "squad");
  Check(ParseImportFlags("Squad,Buildings", bad) == 0x6, "two names, any case");
  Check(ParseImportFlags("all", bad) == 0x3E, "all = everything but reset");
  Check(ParseImportFlags("all,reset", bad) == 0x3F, "all plus reset");
  Check(ParseImportFlags("research,npcs,relations", bad) == 0x38, "research, npcs, relations");
  Check(ParseImportFlags("squad,,buildings", bad) == 0x6, "empty item skipped");
  Check(ParseImportFlags("squad,horses", bad) == -1 && bad == "horses", "unknown name refused");
  Check(ParseImportFlags("", bad) == -1, "empty list refused");
  Check(ImportFlagNames(0x3E) == "squad,buildings,research,npcs,relations", "names of all");
  Check(ImportFlagNames(0x1) == "reset", "name of reset");
  Check(ImportFlagNames(0) == "none", "no flags");
  printf(g_failed ? "%d FAILED\n" : "all import flag tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
