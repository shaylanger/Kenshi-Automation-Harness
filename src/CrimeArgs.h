// Crime names for `crime <npc> commit <crime> against <owner>` (KAH 23). Values follow
// KenshiLib's CrimeEnum (kenshi/Bounty.h); kept free of game headers for the offline test.
#pragma once
#include <string>

// Lower-case crime name -> CrimeEnum value, or -1. Accepts the enum suffix ("stealing") and
// the short forms "theft"/"steal".
inline int ParseCrimeName(const std::string &name) {
  static const char *names[] = {"none",      "enslaving", "lockpicking",   "stealing",     "murder",
                                "assault",   "assault_vip", "slave_freeing", "smuggling",  "terrorism",
                                "looting",   "tresspassing", "escape_prison", "fencing",   "farm_eating",
                                "kidnapping", "uniform_theft"};
  if (name == "theft" || name == "steal")
    return 3;
  if (name == "trespassing")
    return 11;
  for (int i = 1; i < (int)(sizeof(names) / sizeof(names[0])); ++i)
    if (name == names[i])
      return i;
  return -1;
}
