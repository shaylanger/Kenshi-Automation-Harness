#pragma once
// "#serial" and "#serial/index" character references (no game types, so the
// offline tests cover it). Run m15: serials alone are not unique (a spawned
// bandit and a far-away Outlaw Watch shared one), so the harness prints
// "#serial/index" (serial first, so scripts that capture #(\d+) still get
// the serial) and resolves that form by the full handle.

#include <cstdio>
#include <cstdlib>
#include <string>

struct CharacterRef {
  bool isRef;    // text starts with '#'
  bool valid;    // well formed
  bool hasIndex; // "#serial/index"
  unsigned long serial;
  unsigned long index;
  CharacterRef() : isRef(false), valid(false), hasIndex(false), serial(0), index(0) {}
};

inline bool RefNumber(const std::string &text, unsigned long &out) {
  if (text.empty() || text.size() > 10)
    return false;
  for (size_t i = 0; i < text.size(); ++i)
    if (text[i] < '0' || text[i] > '9')
      return false;
  out = strtoul(text.c_str(), nullptr, 10);
  return true;
}

inline CharacterRef ParseCharacterRef(const std::string &text) {
  CharacterRef r;
  if (text.empty() || text[0] != '#')
    return r;
  r.isRef = true;
  const std::string body = text.substr(1);
  const size_t slash = body.find('/');
  if (slash == std::string::npos) {
    r.valid = RefNumber(body, r.serial);
    return r;
  }
  r.hasIndex = true;
  r.valid = RefNumber(body.substr(0, slash), r.serial) && RefNumber(body.substr(slash + 1), r.index);
  return r;
}

// The printed form: "#<serial>/<index>".
inline std::string FormatCharacterRef(unsigned long serial, unsigned long index) {
  char buf[48];
  sprintf_s(buf, "#%lu/%lu", serial, index);
  return buf;
}
