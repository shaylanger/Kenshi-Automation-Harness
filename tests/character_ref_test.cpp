// Offline test of #serial / #serial/index references (src/CharacterRef.h).
// Build and run: tests\run_tests.bat
#include "CharacterRef.h"

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  CharacterRef r = ParseCharacterRef("Hungry Bandit");
  Check(!r.isRef, "a name is no reference");
  r = ParseCharacterRef("#374267584");
  Check(r.isRef && r.valid && !r.hasIndex && r.serial == 374267584UL, "#serial");
  r = ParseCharacterRef("#374267584/1234");
  Check(r.isRef && r.valid && r.hasIndex && r.serial == 374267584UL && r.index == 1234UL,
        "#serial/index");
  Check(!ParseCharacterRef("#").valid, "# alone is malformed");
  Check(!ParseCharacterRef("#12a").valid, "letters are malformed");
  Check(!ParseCharacterRef("#12/").valid, "missing index is malformed");
  Check(!ParseCharacterRef("#/12").valid, "missing serial is malformed");
  Check(!ParseCharacterRef("#1/2/3").valid, "two slashes are malformed");
  Check(!ParseCharacterRef("#-5").valid, "negative is malformed");
  Check(!ParseCharacterRef("#12345678901").valid, "too long is malformed");

  const std::string printed = FormatCharacterRef(374267584UL, 1234UL);
  Check(printed == "#374267584/1234", "printed form: serial first, then index");
  r = ParseCharacterRef(printed);
  Check(r.valid && r.hasIndex && r.serial == 374267584UL && r.index == 1234UL,
        "the printed form parses back to the same handle");

  printf(g_failed ? "%d FAILED\n" : "all character reference tests passed\n", g_failed);
  return g_failed ? 1 : 0;
}
