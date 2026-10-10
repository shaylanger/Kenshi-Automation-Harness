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

    def test_kenshi_cursor(self):   # Misses 2026-10-10 cursor variants: Kenshi's 4-arrow target cursor
        f = np.zeros((900, 1600, 3), int); f[...] = (40, 40, 40)
        def kc(f, x, y):
            for k in range(4, 13):   # 4 thin arms, gap at the centre, arrowhead near each tip
                f[y - k, x] = f[y + k, x] = f[y, x - k] = f[y, x + k] = 140
            for d in (-1, 1):
                f[y - 7, x + d] = f[y + 7, x + d] = f[y + d, x - 7] = f[y + d, x + 7] = 140
        kc(f, 1278, 719)
        self.assertEqual(FR.find_kcursor(f), [(1278, 719)])
        g = np.zeros((900, 1600, 3), int); g[...] = (40, 40, 40)
        g[700:740, 1278] = 140; g[719, 1258:1300] = 140   # a plain UI grid cross (no gap, no heads): not a cursor
        self.assertEqual(FR.find_kcursor(g), [])

    def test_no_cursor(self):
        f = np.zeros((900, 1600, 3), int); f[...] = (190, 150, 100)
        self.assertEqual(FR.find_cursor(f), [])
        f[40:70, 650:950] = 0   # title label with bold glyph stems (white on black): not a cursor
        for x in range(660, 940, 14):
            f[46:66, x:x + 5] = 255
        f[48:51, 660:940] = 255
        self.assertEqual(FR.find_cursor(f), [])



def scene(seed=0):
    """1600x900 textured desert scene (sky band + noisy sand): no flat cells, no text."""
    r = np.random.RandomState(seed)
    f = np.zeros((900, 1600, 3), int); f[...] = (190, 150, 100); f[:300] = (90, 140, 200)
    return np.clip(f + r.randint(-14, 15, (900, 1600, 1)), 0, 255)


def tag(f, x, y, word='[Malzin]', dark_panel=False):
    """draw outlined thin text (a Kenshi name tag) or light text on a flat dark panel (a speech bar) at x, y."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.fromarray(f.astype(np.uint8)); d = ImageDraw.Draw(im)
    try:
        fn = ImageFont.load_default(size=15)   # game UI text height (~15 px at 1600x900)
    except TypeError:
        fn = ImageFont.load_default()
    if dark_panel:
        d.rectangle([x - 10, y - 6, x + 9 * len(word) + 10, y + 18], fill=(20, 20, 20))
        d.text((x, y), word, fill=(200, 200, 200), font=fn)
    else:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            d.text((x + dx, y + dy), word, fill=(0, 0, 0), font=fn)
        d.text((x, y), word, fill=(235, 235, 235), font=fn)
    return np.asarray(im).astype(int)


class Overlay(unittest.TestCase):   # class of the cursor miss: nothing foreign drawn over the scene (2026-10-10)
    def run_(self, fs):
        return FR.overlay_check(None, frames=[(k * 0.5, f) for k, f in enumerate(fs)])

    def test_clean_take_passes(self):
        ok, txt = self.run_([scene(k) for k in range(6)])
        self.assertTrue(ok, txt)

    def test_name_tag_and_speech_fail(self):
        fs = [scene(k) for k in range(8)]
        fs[3] = tag(fs[3], 700, 350, '[Malzin] [Axima]')
        ok, txt = self.run_(fs)
        self.assertFalse(ok, txt); self.assertIn('1.5-1.5s', txt)
        fs = [scene(k) for k in range(8)]
        fs[5] = tag(fs[5], 600, 400, 'Still chewing on that bandit, or is it something else', dark_panel=True)
        ok, txt = self.run_(fs)
        self.assertFalse(ok, txt); self.assertIn('2.5-2.5s', txt)

    def test_popup_panel_fails(self):   # mutation vid-popup-overlay: flat grey dialog box, no text
        fs = [scene(k) for k in range(10)]
        for k in range(3, 7):
            fs[k][270:585, 480:1120] = 64; fs[k][270:315, 480:1120] = 200
        ok, txt = self.run_(fs)
        self.assertFalse(ok, txt); self.assertIn('panel', txt)

    def test_hud_and_label_zones_pass(self):
        fs = [tag(scene(k), 1300, 400, 'LOADED') for k in range(6)]   # the take's own HUD in every frame = baseline
        fs = [tag(f, 700, 30, 'Katana ready, zoom 0') for f in fs]    # title label band
        fs[2] = tag(fs[2], 700, 120, 'stroke 0')                        # centred label down to 0.2 H
        ok, txt = self.run_(fs)
        self.assertTrue(ok, txt)
        fs[4] = tag(fs[4], 40, 40, 'debug: x=12')                       # stray string in the top-left corner stays checked
        self.assertFalse(self.run_(fs)[0])


if __name__ == '__main__':
    unittest.main(verbosity=1)
