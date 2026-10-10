// Offline test of the chatter command parsing (src/Chatter.h).
// Build and run: tests\run_tests.bat
#include "Chatter.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int main() {
  Check(ChatterParse("off") == CHATTER_OFF && ChatterParse("OFF") == CHATTER_OFF, "off (any case)");
  Check(ChatterParse("on") == CHATTER_ON && ChatterParse("On") == CHATTER_ON, "on (any case)");
  Check(ChatterParse("status") == CHATTER_STATUS && ChatterParse("") == CHATTER_STATUS, "status / no argument");
  Check(ChatterParse("mute") == CHATTER_OFF && ChatterParse("unmute") == CHATTER_ON, "mute/unmute aliases");
  Check(ChatterParse("maybe") == CHATTER_BAD && ChatterParse("offf") == CHATTER_BAD, "unknown argument refused");
  Check(!ChatterBubbleShowing(0, 0), "no timers: no bubble");
  Check(ChatterBubbleShowing(3.5f, 0) && ChatterBubbleShowing(0, 1.0f), "either timer: bubble showing");
  Check(!ChatterBubbleShowing(-1.0f, 0), "negative timer: no bubble");
  printf(g_failed ? "chatter_test: %d FAILED\n" : "chatter_test: all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
