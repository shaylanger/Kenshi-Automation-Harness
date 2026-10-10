#pragma once
// "chatter off|on|status": silence NPC speech bubbles (barks) for video takes (Commands.cpp ChatterTick).
// While off, every world tick zeroes Dialogue::speechTextTimer / speechTextTimer_forced on every character
// (as Stobe's ClearCharacterSpeechBubble), so no bark text stays over the frame.
// Pure logic so the offline tests cover it (tests/chatter_test.cpp).
#include <string>

enum ChatterArg {
  CHATTER_BAD = 0,
  CHATTER_OFF, // mute bubbles
  CHATTER_ON,  // normal game (default)
  CHATTER_STATUS
};

inline ChatterArg ChatterParse(const std::string &arg) {
  std::string a;
  for (size_t i = 0; i < arg.size(); ++i)
    a += (char)((arg[i] >= 'A' && arg[i] <= 'Z') ? arg[i] - 'A' + 'a' : arg[i]);
  if (a == "off" || a == "mute" || a == "0")
    return CHATTER_OFF;
  if (a == "on" || a == "unmute" || a == "1")
    return CHATTER_ON;
  if (a == "status" || a.empty())
    return CHATTER_STATUS;
  return CHATTER_BAD;
}

// A bubble counts as showing (one "muted" bubble) when either timer is still running.
inline bool ChatterBubbleShowing(float timer, float forced) { return timer > 0.0f || forced > 0.0f; }
