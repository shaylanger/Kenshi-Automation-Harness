// frame_stamp_test.cpp -- FrameStamp.h layout: round trip, crc rejects any single flipped cell, and a fixed vector
// that tools/animlab/stamp.py --selftest checks too (both sides must agree on every bit).
#include "FrameStamp.h"
#include <stdio.h>
#include <string.h>

static int g_fail = 0;
#define CHECK(c)                                                                                                       \
  do {                                                                                                                 \
    if (!(c)) {                                                                                                        \
      printf("FAIL line %d: %s\n", __LINE__, #c);                                                                      \
      ++g_fail;                                                                                                        \
    }                                                                                                                  \
  } while (0)

int main() {
  unsigned char bits[FrameStamp::BITS];
  unsigned fc, mark, flags, lo, hi;
  FrameStamp::Encode(0x123456, 0xAB, 1, 0xDEADBEEF, 0xCAFE, bits);
  CHECK(FrameStamp::Decode(bits, fc, mark, flags, lo, hi));
  CHECK(fc == 0x123456 && mark == 0xAB && (flags & 3) == 1 && (flags >> 2) == 1 && lo == 0xDEADBEEF && hi == 0xCAFE);
  char s[FrameStamp::BITS + 1];
  for (int i = 0; i < FrameStamp::BITS; ++i)
    s[i] = (char)('0' + bits[i]);
  s[FrameStamp::BITS] = 0;
  // same vector in stamp.py selftest
  const char *want = "000100100011010001010110101010110101110111101010110110111110111011111100101011111110"
                     "000011010110";
  CHECK(strlen(want) == FrameStamp::BITS);
  if (strcmp(s, want)) {
    printf("vector %s\n  want %s\n", s, want);
    ++g_fail;
  }
  for (int i = 0; i < FrameStamp::BITS; ++i) {
    bits[i] ^= 1;
    CHECK(!FrameStamp::Decode(bits, fc, mark, flags, lo, hi));
    bits[i] ^= 1;
  }
  FrameStamp::Encode(0x1000005, 300, 7, 0, 0x12345, bits); // fc / mark / flags / hi masked to their widths
  CHECK(FrameStamp::Decode(bits, fc, mark, flags, lo, hi));
  CHECK(fc == 5 && mark == 300 % 256 && (flags & 3) == 3 && hi == 0x2345);
  printf(g_fail ? "frame_stamp_test FAILED (%d)\n" : "frame_stamp_test ok\n", g_fail);
  return g_fail ? 1 : 0;
}
