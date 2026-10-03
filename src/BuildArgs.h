#pragma once
// Arguments of "build <building name|sid> [near <npc> [dist m] | at x y z]
// [faction <f>]" (no game types, so the offline tests cover it).
// f = id, command, then the arguments.

#include <cstdlib>
#include <string>
#include <vector>

std::string Lower(const std::string &value);

struct BuildArgs {
  std::string name;
  std::string nearName; // empty = near the player's first squad member
  bool at;              // at x y z
  float x, y, z;
  float dist; // along x from the npc
  std::string faction; // empty = the player's
  BuildArgs() : at(false), x(0), y(0), z(0), dist(10.0f) {}
};

inline bool BuildNumber(const std::string &text, float &out) {
  if (text.empty())
    return false;
  char *end = nullptr;
  double v = strtod(text.c_str(), &end);
  if (!end || *end)
    return false;
  out = (float)v;
  return true;
}

inline bool ParseBuildArgs(const std::vector<std::string> &f, BuildArgs &a, std::string &error) {
  const char *usage =
      "usage: build <building name|sid> [near <npc> [dist m] | at x y z] [faction <f>]";
  if (f.size() < 3 || f[2].empty()) {
    error = usage;
    return false;
  }
  a = BuildArgs();
  a.name = f[2];
  bool hasNear = false, hasDist = false;
  for (size_t i = 3; i < f.size(); ++i) {
    const std::string key = Lower(f[i]);
    if (key == "near" && i + 1 < f.size()) {
      a.nearName = f[++i];
      hasNear = true;
    } else if (key == "dist" && i + 1 < f.size()) {
      if (!BuildNumber(f[++i], a.dist) || a.dist < 0.0f || a.dist > 200.0f) {
        error = "dist must be a number 0..200: " + f[i];
        return false;
      }
      hasDist = true;
    } else if (key == "at" && i + 3 < f.size()) {
      if (!BuildNumber(f[i + 1], a.x) || !BuildNumber(f[i + 2], a.y) ||
          !BuildNumber(f[i + 3], a.z)) {
        error = "at needs three numbers: x y z";
        return false;
      }
      a.at = true;
      i += 3;
    } else if (key == "faction" && i + 1 < f.size()) {
      a.faction = f[++i];
    } else {
      error = "unexpected argument '" + f[i] + "'; " + usage;
      return false;
    }
  }
  if (a.at && (hasNear || hasDist)) {
    error = "use either near <npc> [dist m] or at x y z";
    return false;
  }
  return true;
}
