// Offline test of the protect rules (src/ProtectRules.h, item 122).
// Build and run: tests\run_tests.bat
#include "ProtectRules.h"

#include <cstdio>
#include <cstring>
#include <limits>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  Check(!ProtectNeedsFood(3.0f), "hunger 300: not fed");
  Check(!ProtectNeedsFood(2.0f), "hunger 200: not fed");
  Check(ProtectNeedsFood(1.99f), "hunger 199: fed");
  Check(ProtectNeedsFood(0.0f) && ProtectNeedsFood(-0.5f), "starved/negative: fed");
  Check(ProtectNeedsFood(std::numeric_limits<float>::quiet_NaN()), "NaN hunger: fed");
  Check(kProtectHungerFull > kProtectHungerFloor, "a feed lifts hunger above the floor (no feed every frame)");
  Check(strcmp(ProtectKoCause(0.2f, 100, 100, false), "starving") == 0, "hunger 20 KO: starving");
  Check(strcmp(ProtectKoCause(2.5f, 30, 100, false), "blood loss") == 0, "low blood KO: blood loss");
  Check(strcmp(ProtectKoCause(2.5f, 100, 100, true), "blood loss") == 0, "blood trauma KO: blood loss");
  Check(strcmp(ProtectKoCause(2.5f, 100, 100, false), "damage or other") == 0, "fed, full blood: other");
  Check(!ProtectStuck(true, 1000, 3999, false), "down 2999 ms: not stuck yet");
  Check(ProtectStuck(true, 1000, 4000, false), "down 3000 ms: stuck");
  Check(!ProtectStuck(true, 1000, 9000, true), "stuck logged once");
  Check(!ProtectStuck(false, 1000, 9000, false), "up: not stuck");
  Check(ProtectStuck(true, 0xFFFFF000UL, 0x00000BB8UL + 0x1000UL, false), "tick wrap handled");
  // Part health (wounds bug): full health = flesh at max and NO stun damage.
  float flesh = -1, stun = -1;
  PartHealthTarget(100.0f, 1.0f, flesh, stun);
  Check(flesh == 100.0f && stun == 0.0f, "health 100: flesh=max, stun damage 0");
  Check(PartHealthFraction(flesh, stun, 100.0f) == 1.0f, "health 100: derived health 1.0");
  PartHealthTarget(80.0f, 0.3f, flesh, stun);
  Check(std::fabs(PartHealthFraction(flesh, stun, 80.0f) - 0.3f) < 1e-5f, "health 30: derived 0.3");
  PartHealthTarget(100.0f, -2.0f, flesh, stun);
  Check(PartHealthFraction(flesh, stun, 100.0f) == -2.0f, "kill: derived -2.0");
  Check(PartHealthFraction(100.0f, 100.0f, 100.0f) == 0.0f, "old bug: stun=max -> derived 0");
  Check(PartHealthFraction(100.0f, 50.0f, 100.0f) == 0.5f, "stun 50 -> derived 0.5 (live)");
  printf(g_failed ? "protect_rules_test: %d FAILED\n" : "protect_rules_test: all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
