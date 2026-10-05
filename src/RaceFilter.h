// Race filter for `spawn ... race <substr>[|<substr>...]` (PG 199): '|'-separated, case-insensitive
// substrings of the race name; `!substr` excludes. A race passes when it contains none of the
// excluded substrings and (if any plain ones are given) at least one of them. Kept free of game
// headers for the offline test.
#pragma once
#include <cctype>
#include <string>
#include <vector>

struct RaceFilter {
  std::vector<std::string> want, reject;
  bool empty() const { return want.empty() && reject.empty(); }
};

inline std::string RaceFilterLower(const std::string &s) {
  std::string out = s;
  for (size_t i = 0; i < out.size(); ++i)
    out[i] = (char)tolower((unsigned char)out[i]);
  return out;
}

inline RaceFilter ParseRaceFilter(const std::string &spec) {
  RaceFilter r;
  std::string cur;
  for (size_t k = 0; k <= spec.size(); ++k) {
    if (k == spec.size() || spec[k] == '|') {
      std::string s = RaceFilterLower(cur);
      cur.clear();
      if (!s.empty() && s[0] == '!') {
        if (s.size() > 1)
          r.reject.push_back(s.substr(1));
      } else if (!s.empty())
        r.want.push_back(s);
    } else
      cur += spec[k];
  }
  return r;
}

inline bool RaceFilterMatches(const RaceFilter &r, const std::string &race) {
  const std::string l = RaceFilterLower(race);
  for (size_t i = 0; i < r.reject.size(); ++i)
    if (l.find(r.reject[i]) != std::string::npos)
      return false;
  if (r.want.empty())
    return true;
  for (size_t i = 0; i < r.want.size(); ++i)
    if (l.find(r.want[i]) != std::string::npos)
      return true;
  return false;
}
