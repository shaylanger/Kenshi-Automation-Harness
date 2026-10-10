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


if __name__ == '__main__':
    unittest.main(verbosity=1)
