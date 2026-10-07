// Offline test of the input isolation pure parts (src/InputInject.h): key
// names, DirectInput key codes, the buffered event queue (GetDeviceData
// contract) and the GetDeviceState fills.
// Build and run: tests\run_tests.bat
#include "InputInject.h"

#include <cstdio>

int g_failed = 0;
void Check(bool cond, const char *what) {
  printf("%s %s\n", cond ? "PASS" : "FAIL", what);
  if (!cond)
    ++g_failed;
}

int Vk(const char *name) {
  int vk = -1;
  return inject::ParseKeyName(name, vk) ? vk : -1;
}

inject::ObjData Ev(unsigned long ofs, unsigned long data) {
  inject::ObjData e;
  e.dwOfs = ofs;
  e.dwData = data;
  e.dwTimeStamp = 0;
  e.dwSequence = ofs;
  e.uAppData = 0;
  return e;
}

int main() {
  Check(sizeof(inject::ObjData) == 4 * sizeof(unsigned long) + sizeof(size_t), "ObjData = DIDEVICEOBJECTDATA layout");
  // key names: the CS rows' keys and the kenshi-key.ps1 hex form
  Check(Vk("0xDD") == 0xDD && Vk("0xdb") == 0xDB, "hex vk");
  Check(Vk("]") == 0xDD && Vk("[") == 0xDB && Vk(";") == 0xBA && Vk("'") == 0xDE && Vk("\\") == 0xDC, "punctuation");
  Check(Vk("a") == 'A' && Vk("W") == 'W' && Vk("7") == '7', "letters and digits");
  Check(Vk("f10") == 0x79 && Vk("F1") == 0x70 && Vk("f12") == 0x7B, "function keys");
  Check(Vk("esc") == 0x1B && Vk("ralt") == 0xA5 && Vk("backslash") == 0xDC && Vk("space") == 0x20, "names");
  Check(Vk("") == -1 && Vk("bogus") == -1 && Vk("0x1FF") == -1 && Vk("f13") == -1, "unknown names refused");
  // DIK codes (scan codes as MapVirtualKey returns them on a US keyboard)
  Check(inject::VkToDik('W', 0x11) == 0x11, "W -> DIK_W");
  Check(inject::VkToDik(0xDD, 0x1B) == 0x1B, "] -> DIK_RBRACKET");
  Check(inject::VkToDik(0xA5, 0x38) == 0xB8, "right alt -> DIK_RMENU (extended)");
  Check(inject::VkToDik(0x26, 0x48) == 0xC8, "up -> DIK_UP (extended)");
  Check(inject::VkToDik(0x10, 0x2A) == 0x2A && inject::VkToDik(0xA1, 0x36) == 0x36, "shift / right shift");
  Check(inject::VkToDik(0x79, 0x44) == 0x44, "F10 -> DIK_F10");
  Check(inject::GenericModifier(0xA5) == 0x12 && inject::GenericModifier(0x41) == 0, "generic modifier");
  // queue: order, partial reads, peek, count query, flush, overflow
  inject::EventQueue q;
  q.Push(Ev(0x1B, 0x80));
  q.Push(Ev(0x1B, 0));
  q.Push(Ev(0x11, 0x80));
  inject::ObjData out[4];
  unsigned long n = 2;
  q.Take(sizeof(inject::ObjData), out, &n, true);
  Check(n == 2 && q.count == 3 && out[0].dwData == 0x80 && out[1].dwData == 0, "peek: down then up, nothing removed");
  n = 2;
  q.Take(sizeof(inject::ObjData), out, &n, false);
  Check(n == 2 && q.count == 1, "read 2 of 3");
  n = 4;
  q.Take(sizeof(inject::ObjData), out, &n, false);
  Check(n == 1 && out[0].dwOfs == 0x11 && q.count == 0, "read the rest");
  n = 4;
  q.Take(sizeof(inject::ObjData), out, &n, false);
  Check(n == 0, "empty queue: 0 items");
  q.Push(Ev(1, 1));
  q.Push(Ev(2, 1));
  n = 0xFFFFFFFF;
  q.Take(sizeof(inject::ObjData), 0, &n, true);
  Check(n == 2 && q.count == 2, "count query (no buffer, peek)");
  n = 0xFFFFFFFF;
  q.Take(sizeof(inject::ObjData), 0, &n, false);
  Check(q.count == 0, "flush (no buffer)");
  // DX3-size records (16 bytes): no uAppData written past the record
  unsigned char small[3 * 16 + 1];
  memset(small, 0xEE, sizeof(small));
  q.Push(Ev(5, 0x80));
  q.Push(Ev(6, 0x80));
  q.Push(Ev(7, 0x80));
  n = 3;
  q.Take(16, small, &n, false);
  Check(n == 3 && small[16] == 6 && small[32] == 7 && small[48] == 0xEE, "16-byte records stay in bounds");
  for (int i = 0; i < inject::EventQueue::kSize + 5; ++i)
    q.Push(Ev((unsigned long)i, 0));
  n = 1;
  q.Take(sizeof(inject::ObjData), out, &n, false);
  Check(q.dropped == 5 && out[0].dwOfs == 5, "overflow drops the oldest");
  // state fills
  inject::HeldState h;
  h.dik[0x1B] = 1;
  unsigned char kb[256];
  inject::FillKeyboardState(h, kb, 256);
  Check(kb[0x1B] == 0x80 && kb[0x11] == 0, "keyboard state: injected key down only");
  h.button[1] = 1;
  unsigned char ms2[20];
  inject::FillMouseState(h, 3, -4, 120, ms2, 20);
  const long *ax = (const long *)ms2;
  Check(ax[0] == 3 && ax[1] == -4 && ax[2] == 120 && ms2[12] == 0 && ms2[13] == 0x80 && ms2[19] == 0,
        "DIMOUSESTATE2: deltas + right button");
  unsigned char ms1[16];
  inject::FillMouseState(h, 0, 0, 0, ms1, 16);
  Check(ms1[13] == 0x80 && ms1[12] == 0, "DIMOUSESTATE: 4 buttons");
  h.Reset();
  inject::FillKeyboardState(h, kb, 256);
  Check(kb[0x1B] == 0, "reset releases everything");
  printf(g_failed ? "input_inject_test: %d FAILED\n" : "input_inject_test: all passed\n", g_failed);
  return g_failed ? 1 : 0;
}
