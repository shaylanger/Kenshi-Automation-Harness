#!/usr/bin/env python3
"""Offline tests for tools/animlab/frames.py (video frame checks). Synthetic frames only.
Run: python3 tests/animlab/test_frames.py   (exit 0 = all pass)."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
import numpy as np  # noqa: E402
import frames as FR  # noqa: E402


def frame(sky_rows):
    """160x90 frame: the top `sky_rows` rows blue sky, the rest sand."""
    f = np.zeros((FR.H, FR.W, 3), int); f[...] = (190, 150, 100); f[:sky_rows] = (90, 140, 200)
    return f


class Frames(unittest.TestCase):
    def test_sky_share(self):
        self.assertEqual(FR.sky_share(frame(0)), 0.0)
        self.assertGreater(FR.sky_share(frame(30)), 0.3)
        night = np.full((FR.H, FR.W, 3), 20, int)
        self.assertEqual(FR.sky_share(night), 0.0)   # no daylight sky = not judgeable

    def test_openground(self):   # miss 2026-10-10 sword-z25-block: slope fills the frame for the first half
        sh = [FR.sky_share(frame(10))] * 10 + [FR.sky_share(frame(30))] * 10
        ok, txt = FR.openground(sh, 2.0)
        self.assertFalse(ok, txt); self.assertIn('closed=0.0-5.0s', txt)
        ok, txt = FR.openground([FR.sky_share(frame(30))] * 19 + [0.0], 2.0)
        self.assertTrue(ok, txt)   # one closed frame of 20 (camera move) is tolerated
        self.assertFalse(FR.openground([], 2.0)[0])

ARROW = ["X", "XX", "X.X", "X..X", "X...X", "X....X", "X.....X", "X......X", "X.......X", "X........X", "X.........X",
         "X......XXXXX", "X...X..X", "X..XX..X", "X.X  X..X", "XX   X..X", "X     X..X", "      X..X", "       XX"]


def cursor_frame(x0, y0, scale, bg=(190, 150, 100), size=(900, 1600)):
    """full-res frame with the classic Windows arrow (X outline 1 px, . white) drawn at `scale`."""
    f = np.zeros(size + (3,), int); f[...] = bg
    for r, row in enumerate(ARROW):
        for c, ch in enumerate(row):
            if ch == ' ':
                continue
            ys, xs = y0 + int(r * scale), x0 + int(c * scale)
            ye, xe = y0 + int((r + 1) * scale), x0 + int((c + 1) * scale)
            f[ys:max(ye, ys + 1), xs:max(xe, xs + 1)] = (255, 255, 255) if ch == '.' else (0, 0, 0)
    for r in range(len(ARROW)):   # 1 px outline as on a high-DPI cursor: left edge stays dark
        f[y0 + int(r * scale):y0 + int((r + 1) * scale), x0] = 0
    return f


class Cursor(unittest.TestCase):   # Shay 2026-10-10 ticket A: no mouse cursor in a take
    def test_arrow_any_scale(self):
        for sc in (1.0, 1.5, 2.25, 3.0):
            c = FR.find_cursor(cursor_frame(500, 300, sc))
            self.assertTrue(c, 'scale %g' % sc); self.assertLessEqual(abs(c[0][0] - 500), 1.5 * sc); self.assertLessEqual(abs(c[0][1] - 300), 1.5 * sc)

    def test_no_cursor(self):
        f = np.zeros((900, 1600, 3), int); f[...] = (190, 150, 100)
        self.assertEqual(FR.find_cursor(f), [])
        f[40:70, 650:950] = 0   # title label with bold glyph stems (white on black): not a cursor
        for x in range(660, 940, 14):
            f[46:66, x:x + 5] = 255
        f[48:51, 660:940] = 255
        self.assertEqual(FR.find_cursor(f), [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
