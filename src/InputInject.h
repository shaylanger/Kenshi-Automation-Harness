#pragma once
// Input isolation (InputIsolation.cpp): the pure parts, testable offline
// (tests/input_inject_test.cpp). Key names -> virtual key / DirectInput key
// code, the injected key/button state, and the per-device event queues that
// stand in for DirectInput's buffered data while isolation is on.

#include <cstdlib>
#include <cstring>
#include <string>

namespace inject {

// Same layout as DIDEVICEOBJECTDATA (dinput.h, DIRECTINPUT_VERSION 0x0800).
struct ObjData {
  unsigned long dwOfs;
  unsigned long dwData;
  unsigned long dwTimeStamp;
  unsigned long dwSequence;
  size_t uAppData;
};

// DirectInput mouse data offsets (DIMOFS_*).
const unsigned long kMouseX = 0, kMouseY = 4, kMouseZ = 8, kMouseButton0 = 12;

inline std::string LowerAscii(const std::string &s) {
  std::string out(s);
  for (size_t i = 0; i < out.size(); ++i)
    if (out[i] >= 'A' && out[i] <= 'Z')
      out[i] = (char)(out[i] - 'A' + 'a');
  return out;
}

// "0xDD" / "221" / "a" / "f10" / "esc" / "backslash" / ";" -> virtual key.
// Single punctuation characters use the US layout. Mouse buttons are not
// keys here (mouse_inject). Returns false for unknown names.
inline bool ParseKeyName(const std::string &raw, int &vk) {
  const std::string s = LowerAscii(raw);
  vk = 0;
  if (s.empty())
    return false;
  if (s.size() > 2 && s[0] == '0' && s[1] == 'x') {
    char *end = nullptr;
    long v = strtol(s.c_str() + 2, &end, 16);
    if (*end || v <= 0 || v > 0xFE)
      return false;
    vk = (int)v;
    return true;
  }
  if (s.size() >= 2 && s.size() <= 3 && s[0] >= '0' && s[0] <= '9') {
    long v = strtol(s.c_str(), nullptr, 10);
    if (v <= 0 || v > 0xFE)
      return false;
    vk = (int)v;
    return true;
  }
  if (s.size() == 1) {
    char c = s[0];
    if (c >= 'a' && c <= 'z') { vk = 'A' + (c - 'a'); return true; }
    if (c >= '0' && c <= '9') { vk = c; return true; }
    const char *punct = ";=,-./`[\\]'";
    const int vks[] = {0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE};
    const char *p = strchr(punct, c);
    if (p) { vk = vks[p - punct]; return true; }
    return false;
  }
  if (s[0] == 'f' && s.size() <= 3) {
    long n = strtol(s.c_str() + 1, nullptr, 10);
    if (n >= 1 && n <= 12) { vk = 0x70 + (int)n - 1; return true; }
  }
  struct Name { const char *name; int vk; };
  static const Name names[] = {
      {"esc", 0x1B}, {"escape", 0x1B}, {"enter", 0x0D}, {"return", 0x0D}, {"space", 0x20},
      {"tab", 0x09}, {"backspace", 0x08}, {"shift", 0x10}, {"lshift", 0xA0}, {"rshift", 0xA1},
      {"ctrl", 0x11}, {"lctrl", 0xA2}, {"rctrl", 0xA3}, {"alt", 0x12}, {"lalt", 0xA4},
      {"ralt", 0xA5}, {"altgr", 0xA5}, {"up", 0x26}, {"down", 0x28}, {"left", 0x25}, {"right", 0x27},
      {"home", 0x24}, {"end", 0x23}, {"pgup", 0x21}, {"pgdn", 0x22}, {"insert", 0x2D},
      {"delete", 0x2E}, {"backslash", 0xDC}, {"slash", 0xBF}, {"semicolon", 0xBA},
      {"quote", 0xDE}, {"lbracket", 0xDB}, {"rbracket", 0xDD}, {"minus", 0xBD},
      {"equals", 0xBB}, {"comma", 0xBC}, {"period", 0xBE}, {"grave", 0xC0}, {"tilde", 0xC0},
      {"pause", 0x13}, {"capslock", 0x14}};
  for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
    if (s == names[i].name) {
      vk = names[i].vk;
      return true;
    }
  return false;
}

// Keys whose DirectInput code is the extended form (scan code | 0x80).
inline bool IsExtendedVk(int vk) {
  switch (vk) {
  case 0xA3: case 0xA5: // right ctrl / alt
  case 0x21: case 0x22: case 0x23: case 0x24: case 0x25: case 0x26: case 0x27: case 0x28:
  case 0x2D: case 0x2E: case 0x6F: case 0x90: case 0x5B: case 0x5C: case 0x5D:
    return true;
  }
  return false;
}

// DirectInput key code (DIK_*) for a virtual key, given the key's scan code
// (MapVirtualKey(vk, MAPVK_VK_TO_VSC)). The generic VK_SHIFT/CONTROL/MENU
// map to the left keys.
inline int VkToDik(int vk, int scan) {
  if (vk == 0x10 || vk == 0xA0) return 0x2A;
  if (vk == 0xA1) return 0x36;
  if (vk == 0x11 || vk == 0xA2) return 0x1D;
  if (vk == 0x12 || vk == 0xA4) return 0x38;
  if (vk == 0x13) return 0xC5; // pause
  scan &= 0x7F;
  if (!scan)
    return 0;
  return IsExtendedVk(vk) ? (scan | 0x80) : scan;
}

// The generic modifier for a left/right modifier key (VK_LSHIFT -> VK_SHIFT), else 0.
inline int GenericModifier(int vk) {
  if (vk == 0xA0 || vk == 0xA1) return 0x10;
  if (vk == 0xA2 || vk == 0xA3) return 0x11;
  if (vk == 0xA4 || vk == 0xA5) return 0x12;
  return 0;
}

// Buffered events for one device (a fixed ring; the oldest is dropped when full).
struct EventQueue {
  enum { kSize = 256 };
  ObjData items[kSize];
  int head, count;
  unsigned long dropped;
  EventQueue() : head(0), count(0), dropped(0) {}
  void Push(const ObjData &d) {
    if (count == kSize) {
      head = (head + 1) % kSize;
      --count;
      ++dropped;
    }
    items[(head + count) % kSize] = d;
    ++count;
  }
  void Clear() { head = count = 0; }
  // Fills up to *n entries of cbObjectData bytes each (DirectInput's
  // GetDeviceData contract): *n becomes the number written. out == nullptr:
  // *n becomes the number pending (and the queue is flushed unless peek).
  void Take(unsigned long cbObjectData, void *out, unsigned long *n, bool peek) {
    if (!out) {
      *n = (unsigned long)count;
      if (!peek)
        Clear();
      return;
    }
    unsigned long want = *n, done = 0;
    unsigned char *dst = (unsigned char *)out;
    size_t copy = cbObjectData < sizeof(ObjData) ? cbObjectData : sizeof(ObjData);
    for (; done < want && (int)done < count; ++done) {
      unsigned char *slot = dst + (size_t)done * cbObjectData;
      memset(slot, 0, cbObjectData);
      memcpy(slot, &items[(head + done) % kSize], copy);
    }
    if (!peek) {
      head = (head + (int)done) % kSize;
      count -= (int)done;
    }
    *n = done;
  }
};

// Injected state: keys and mouse buttons held, relative mouse motion not yet
// read by GetDeviceState consumers.
struct HeldState {
  unsigned char vk[256];  // 1 = held (virtual keys, incl. VK_LBUTTON..)
  unsigned char dik[256]; // 1 = held (DirectInput key codes)
  unsigned char button[8];
  HeldState() { Reset(); }
  void Reset() {
    memset(vk, 0, sizeof(vk));
    memset(dik, 0, sizeof(dik));
    memset(button, 0, sizeof(button));
  }
};

// GetDeviceState for a keyboard (256 bytes, 0x80 = down).
inline void FillKeyboardState(const HeldState &h, void *buf, unsigned long cb) {
  memset(buf, 0, cb);
  unsigned char *b = (unsigned char *)buf;
  for (unsigned long i = 0; i < cb && i < 256; ++i)
    if (h.dik[i])
      b[i] = 0x80;
}

// GetDeviceState for a mouse: DIMOUSESTATE (16 bytes, 4 buttons) or
// DIMOUSESTATE2 (20 bytes, 8 buttons): lX, lY, lZ then the button bytes.
inline void FillMouseState(const HeldState &h, long dx, long dy, long dz, void *buf, unsigned long cb) {
  memset(buf, 0, cb);
  if (cb < 12)
    return;
  long *axes = (long *)buf;
  axes[0] = dx;
  axes[1] = dy;
  axes[2] = dz;
  unsigned char *btn = (unsigned char *)buf + 12;
  for (unsigned long i = 0; i < 8 && 12 + i < cb; ++i)
    btn[i] = h.button[i] ? 0x80 : 0;
}

} // namespace inject
