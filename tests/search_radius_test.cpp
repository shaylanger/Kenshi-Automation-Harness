// Offline test of the search radius arguments (src/SearchRadius.h) used by
// building, buildings, benches, power, fill, job and teleport ... building.
// Build and run: tests\run_tests.bat
#include "SearchRadius.h"

#include <cctype>
#include <cstdio>
#include <sstream>

std::string Lower(const std::string &value) {
  std::string out = value;
  for (size_t i = 0; i < out.size(); ++i)
    out[i] = (char)tolower((unsigned char)out[i]);
  return out;
}
std::string Num(double v) {
  std::ostringstream s;
  s << v;
  return s.str();
}

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

// f = id, command, then the arguments.
std::vector<std::string> Args(const char *a, const char *b = 0, const char *c = 0,
                              const char *d = 0, const char *e = 0, const char *g = 0) {
  std::vector<std::string> f;
  f.push_back("1");
  const char *all[] = {a, b, c, d, e, g};
  for (int i = 0; i < 6 && all[i]; ++i)
    f.push_back(all[i]);
  return f;
}

int main() {
  float r = 0;
  std::string err;

  Check(ParseSearchRadius(Args("building", "Stone Mine"), 3, 3, 300.0f, r, err) && r == 300.0f,
        "no radius -> default");
  Check(ParseSearchRadius(Args("building", "Stone Mine", "800"), 3, 3, 300.0f, r, err) &&
            r == 800.0f,
        "positional radius");
  Check(ParseSearchRadius(Args("building", "Stone Mine", "radius", "750.5"), 3, 3, 300.0f, r,
                          err) && r == 750.5f,
        "keyword radius");
  Check(ParseSearchRadius(Args("job", "Shay", "Stone Mine", "task", "OPERATE_MACHINERY"), 4, 0,
                          300.0f, r, err) && r == 300.0f,
        "job with task, no radius");
  Check(ParseSearchRadius(Args("job", "Shay", "Stone Mine", "radius", "900"), 4, 0, 300.0f, r,
                          err) && r == 900.0f,
        "job radius keyword");
  Check(ParseSearchRadius(Args("fill", "Generator", "Iron Plates", "3"), 4, 0, 300.0f, r, err) &&
            r == 300.0f,
        "fill count is not a radius (no positional form)");
  Check(ParseSearchRadius(Args("benches", "crafts"), 2, 2, 300.0f, r, err) && r == 300.0f,
        "benches crafts -> default");
  Check(ParseSearchRadius(Args("benches", "1200", "crafts"), 2, 2, 300.0f, r, err) && r == 1200.0f,
        "benches positional radius");
  Check(ParseSearchRadius(Args("buildings", "100", "radius"), 3, 2, 100.0f, r, err) &&
            r == 100.0f,
        "buildings: 'radius' as a filter word is no keyword without a value");
  Check(ParseSearchRadius(Args("building", "Mine", "5000"), 3, 3, 300.0f, r, err) && r == 5000.0f,
        "maximum allowed");

  err.clear();
  Check(!ParseSearchRadius(Args("building", "Mine", "5001"), 3, 3, 300.0f, r, err) &&
            err.find("5000") != std::string::npos,
        "above maximum refused");
  Check(!ParseSearchRadius(Args("building", "Mine", "radius", "0"), 3, 3, 300.0f, r, err),
        "zero refused");
  Check(!ParseSearchRadius(Args("building", "Mine", "radius", "-5"), 3, 3, 300.0f, r, err),
        "negative refused");
  Check(!ParseSearchRadius(Args("job", "Shay", "Mine", "RADIUS", "far"), 4, 0, 300.0f, r, err),
        "non-number refused (keyword is case-insensitive)");

  Check(ParseSearchRadius(Args("shopstock", "Abia"), 3, 0, kDefaultShopRadius, r, err,
                          kMaxShopRadius) && r == 60.0f,
        "shopstock default 60");
  Check(ParseSearchRadius(Args("trade", "Shay", "Abia", "Bandage", "radius"), 5, 0,
                          kDefaultShopRadius, r, err, kMaxShopRadius) && r == 60.0f,
        "trade: trailing 'radius' without a value is ignored");
  Check(ParseSearchRadius(Args("trade", "Shay", "Abia", "Bandage", "radius", "120"), 5, 0,
                          kDefaultShopRadius, r, err, kMaxShopRadius) && r == 120.0f,
        "trade radius keyword");
  Check(!ParseSearchRadius(Args("shopstock", "Abia", "radius", "301"), 3, 0, kDefaultShopRadius,
                           r, err, kMaxShopRadius) && err.find("300") != std::string::npos,
        "shop radius above 300 refused");

  printf(g_failed ? "%d FAILED\n" : "all search radius tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
