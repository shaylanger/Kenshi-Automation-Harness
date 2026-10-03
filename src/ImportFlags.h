#pragma once
// "import <save> [flags]" (KAH 21): flag names <-> SaveManager::Flags bits
// (values copied from the SDK so the offline tests cover it without game
// headers: RESET_POSITION 1, IMPORT_SQUAD 2, IMPORT_BUILDINGS 4,
// IMPORT_RESEARCH 8, IMPORT_NPC_STATES 16, IMPORT_RELATIONS 32).

#include <string>

std::string Lower(const std::string &value);

struct ImportFlagName {
  const char *name;
  int bit;
};
const ImportFlagName kImportFlags[] = {{"reset", 0x1},    {"squad", 0x2},      {"buildings", 0x4},
                                       {"research", 0x8}, {"npcs", 0x10},      {"relations", 0x20}};
const int kImportAll = 0x2 | 0x4 | 0x8 | 0x10 | 0x20; // everything but reset

// "squad,buildings" -> bits; "all" = kImportAll (may be combined: "all,reset").
// Returns -1 and the bad word in `bad` for an unknown name or an empty list.
inline int ParseImportFlags(const std::string &text, std::string &bad) {
  int flags = 0;
  size_t start = 0;
  const std::string t = Lower(text);
  while (start <= t.size()) {
    size_t comma = t.find(',', start);
    if (comma == std::string::npos)
      comma = t.size();
    const std::string word = t.substr(start, comma - start);
    start = comma + 1;
    if (word.empty())
      continue;
    if (word == "all") {
      flags |= kImportAll;
      continue;
    }
    bool known = false;
    for (size_t i = 0; i < sizeof(kImportFlags) / sizeof(kImportFlags[0]); ++i)
      if (word == kImportFlags[i].name) {
        flags |= kImportFlags[i].bit;
        known = true;
      }
    if (!known) {
      bad = word;
      return -1;
    }
  }
  if (flags == 0) {
    bad = text;
    return -1;
  }
  return flags;
}

inline std::string ImportFlagNames(int flags) {
  std::string out;
  for (size_t i = 0; i < sizeof(kImportFlags) / sizeof(kImportFlags[0]); ++i)
    if (flags & kImportFlags[i].bit)
      out += (out.empty() ? "" : ",") + std::string(kImportFlags[i].name);
  return out.empty() ? "none" : out;
}
