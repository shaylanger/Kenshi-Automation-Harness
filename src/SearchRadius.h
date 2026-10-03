#pragma once
// Search radius arguments of the building commands (no game types, so the
// offline tests cover it): "radius <m>" anywhere after `from`, or a bare
// number at f[positional] (0 = no positional form).

#include <cstdlib>
#include <string>
#include <vector>

std::string Lower(const std::string &value);
std::string Num(double v);

const float kDefaultSearchRadius = 300.0f;
const float kMaxSearchRadius = 5000.0f;

inline bool IsNumber(const std::string &text) {
  if (text.empty())
    return false;
  char *end = nullptr;
  strtod(text.c_str(), &end);
  return end && !*end;
}

// out = the radius (fallback when none is given). False with `error` when
// the value is not a number in (0, kMaxSearchRadius].
inline bool ParseSearchRadius(const std::vector<std::string> &f, size_t from, size_t positional,
                              float fallback, float &out, std::string &error) {
  out = fallback;
  std::string text;
  for (size_t i = from; i + 1 < f.size(); ++i)
    if (Lower(f[i]) == "radius") {
      text = f[i + 1];
      break;
    }
  if (text.empty() && positional > 0 && positional < f.size() && IsNumber(f[positional]))
    text = f[positional];
  if (text.empty())
    return true;
  double v = IsNumber(text) ? strtod(text.c_str(), nullptr) : -1.0;
  if (!(v > 0.0) || v > kMaxSearchRadius) {
    error = "radius must be a number above 0 and at most " + Num(kMaxSearchRadius) + ": " + text;
    return false;
  }
  out = (float)v;
  return true;
}
