// FrameStamp.h -- bit layout of the harness `stamp` code (frame-exact video sync, 2026-10-10).
// A grid in the top-left corner of the game view, drawn every rendered frame while `stamp on`:
//   row 0      sync row: column c white when c is even (decoder threshold + geometry check)
//   rows 1..4  96 data cells, row-major, MSB first: fc 24 | mark 8 | flags 4 | lo 32 | hi 16 | spare 4 (0) | crc 8
//   fc    harness render-frame counter (MyGUI frame start), mark = last `sync_flash n` (n & 255) while the stamp is on,
//   flags bit0 = a mod set the payload within the last frame, bit1 = painted on the set (same thread, before render),
//         bits2-3 = layout version (1), lo/hi = mod payload (KAH_StampSet; KenshiFP: FP state, see tools/animlab/stamp.py),
//   crc   CRC-8 (poly 0x07, init 0) over the first 88 bits as 11 bytes.
// Cells are black (0) / white (1) on a black backing one cell wider on every side. Pure logic, unit-tested
// (tests/frame_stamp_test.cpp); tools/animlab/stamp.py mirrors it.
#ifndef KAH_FRAME_STAMP_H
#define KAH_FRAME_STAMP_H

namespace FrameStamp {

enum { COLS = 24, DATA_ROWS = 4, ROWS = 5, BITS = 96, VERSION = 1 };

inline unsigned char Crc8(const unsigned char *d, int n) {
  unsigned c = 0;
  for (int i = 0; i < n; ++i) {
    c ^= d[i];
    for (int b = 0; b < 8; ++b)
      c = (c & 0x80) ? ((c << 1) ^ 0x07) & 0xff : (c << 1) & 0xff;
  }
  return (unsigned char)c;
}

inline void Put(unsigned char *bits, int &k, unsigned v, int n) {
  for (int i = n - 1; i >= 0; --i)
    bits[k++] = (unsigned char)((v >> i) & 1);
}

inline unsigned Get(const unsigned char *bits, int &k, int n) {
  unsigned v = 0;
  for (int i = 0; i < n; ++i)
    v = (v << 1) | (bits[k++] & 1);
  return v;
}

inline unsigned char CrcOfBits(const unsigned char *bits) {
  unsigned char by[11];
  for (int i = 0; i < 11; ++i) {
    unsigned v = 0;
    for (int j = 0; j < 8; ++j)
      v = (v << 1) | (bits[i * 8 + j] & 1);
    by[i] = (unsigned char)v;
  }
  return Crc8(by, 11);
}

// bits[BITS] = 0/1 per data cell.
inline void Encode(unsigned fc, unsigned mark, unsigned flags, unsigned lo, unsigned hi, unsigned char *bits) {
  int k = 0;
  Put(bits, k, fc & 0xffffff, 24);
  Put(bits, k, mark & 0xff, 8);
  Put(bits, k, (flags & 3) | (VERSION << 2), 4);
  Put(bits, k, lo, 32);
  Put(bits, k, hi & 0xffff, 16);
  Put(bits, k, 0, 4);
  Put(bits, k, CrcOfBits(bits), 8);
}

// true when the crc, the spare bits and the version match.
inline bool Decode(const unsigned char *bits, unsigned &fc, unsigned &mark, unsigned &flags, unsigned &lo,
                   unsigned &hi) {
  int k = 0;
  fc = Get(bits, k, 24);
  mark = Get(bits, k, 8);
  flags = Get(bits, k, 4);
  lo = Get(bits, k, 32);
  hi = Get(bits, k, 16);
  const unsigned spare = Get(bits, k, 4);
  const unsigned crc = Get(bits, k, 8);
  return spare == 0 && (flags >> 2) == VERSION && crc == CrcOfBits(bits);
}

} // namespace FrameStamp

#endif
