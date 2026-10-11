#!/usr/bin/env python3
"""Offline tests for tools/animlab/stamp.py (harness frame stamp decoder) and its use in takecheck.py / frames.py.
Synthetic x264 videos (needs ffmpeg + numpy). Run: python3 tests/animlab/test_stamp.py   (exit 0 = all pass)."""
import os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', '..', 'tools', 'animlab')
sys.path.insert(0, TOOLS)
import stamp as S  # noqa: E402

READY, AIMING = 6, 5


def lo(ui, stroke=-1, wcls=1, vm=1, kseq=0):
    return ui | (stroke + 1) << 5 | 1 << 10 | wcls << 15 | vm << 18 | (kseq & 127) << 25


class StampLayout(unittest.TestCase):
    def test_vector_matches_cpp(self):   # tests/frame_stamp_test.cpp holds the same vector
        self.assertEqual(''.join(map(str, S.encode(0x123456, 0xAB, 1, 0xDEADBEEF, 0xCAFE))),
                         '000100100011010001010110101010110101110111101010110110111110111011111100101011111110000011010110')

    def test_crc_rejects_flips(self):
        b = S.encode(77, 3, 1, lo(READY), 1)
        self.assertIsNotNone(S.decode_bits(b))
        for i in range(S.DATA):
            bb = list(b); bb[i] ^= 1
            self.assertIsNone(S.decode_bits(bb), i)

    def test_kfp_fields(self):
        k = S.kfp_fields(lo(AIMING, stroke=2, wcls=0), 1 | 5 << 2)
        self.assertEqual((k['ui'], k['stroke'], k['wcls'], k['view'], k['loaded'], k['swings']),
                         ('aiming', 2, 'melee', 'eye', 1, 5))


class StampTake(unittest.TestCase):
    """10.2 s take at 30 fps, game at 60 fps: T0 mark at 0.5 s, the aim label's mark 0.7 s late on the script clock,
    the sampled ui_state has a 2.5 s gap: with the stamp the take is judged on the video clock and passes."""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix='stamptest-')
        N, rows = 306, []
        for i in range(N):
            t = i / 30.0
            mark = 0 if t < 0.55 else 1 if t < 3.2 else 2 if t < 6.5 else 3
            ui = AIMING if 3.5 <= t < 6.8 else READY
            rows.append((5000 + 2 * i, mark, lo(ui), 1))
        cls.video = os.path.join(cls.d, 'take.mp4')
        S.synth(cls.video, rows)
        p = lambda n, s: (open(os.path.join(cls.d, n), 'w').write(s), os.path.join(cls.d, n))[1]
        cls.labels = p('l.txt', '0.0 start\n2.0 Crossbow aim (RMB)\n6.0 W: ready back\n9.0 end\n')
        ev = ['%.2f mark sync=%d' % (t, n) for t, n in ((0.0, 0), (0.0, 1), (2.0, 2), (6.0, 3))]
        ev += ['%.2f fp ui_state=%s loaded=1' % (t, 'ready' if t < 4 else 'aiming') for t in (0.0, 1.5, 4.0)]
        t = -0.5
        while t < 10.0:
            ev.append('%.2f world near=0 msgs=0' % t); t += 0.25
        cls.ev = p('e.txt', '\n'.join(ev) + '\n')
        cls.rules = p('r.txt', 'set grace 0.6\nset maxgap 1.0\nset endslack 1.0\ncover ui_state,near\n'
                      'claim "(?i)aim \\(RMB\\)" ui_state=aiming\npre "(?i)aim \\(RMB\\)" loaded>=1\n'
                      'claim "(?i)ready back" ui_state=ready\nforbid near>0\n')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def tc(self, *extra):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'takecheck.py'), '--labels', self.labels, '--ev', self.ev,
                            '--rules', self.rules, '--video', self.video, '--no-cursor', '--no-overlay', '--name', 't']
                           + list(extra), capture_output=True, text=True)
        return r.returncode, r.stdout

    def test_take_inputs_labels_on_marks(self):
        with open(self.labels) as f:
            L = [(float(x.split(None, 1)[0]), x.split(None, 1)[1].strip()) for x in f]
        ti = S.take_inputs(self.video, L)
        self.assertIsNotNone(ti)
        got = [round(t, 3) for t, _ in ti['labels']]
        self.assertEqual(got, [round(17 / 30.0, 3), round(96 / 30.0, 3), round(195 / 30.0, 3), round(195 / 30.0 + 3.0, 3)])
        self.assertAlmostEqual(ti['off0'], 0.0)
        self.assertEqual(ti['missing'], [])
        self.assertEqual(ti['series']['gf'][0][1], '5000')

    def test_takecheck_passes_with_stamp(self):
        rc, out = self.tc('--synced-out', os.path.join(self.d, 'synced.txt'))
        self.assertEqual(rc, 0, out)
        self.assertIn('RESULT t PASS', out)
        self.assertIn('sync PASS stamp frames=306 ok=306 dup=0 skip_max=2 marks=3/3 t0=0.000 payload=fp', out)
        with open(os.path.join(self.d, 'synced.txt')) as f:
            self.assertTrue(f.readline().startswith('0.567 start'))

    def test_takecheck_without_stamp_sees_the_gap(self):
        rc, out = self.tc('--stamp', 'off', '--no-sync')
        self.assertNotIn('RESULT t PASS ', out)

    def test_frames_overlay_ignores_stamp_corner(self):
        import numpy as np, frames
        fs = []
        for k in range(6):
            f = np.zeros((900, 1600, 3), np.int16); f[:, :] = (110, 150, 200); f[500:] = (90, 80, 60)
            bits = S.encode(100 + k, 0, 1, lo(READY, kseq=k), 1)
            f[:56, :208] = 0
            for r in range(S.ROWS):
                for c in range(S.COLS):
                    if (c % 2 == 0) if r == 0 else bits[(r - 1) * S.COLS + c]:
                        f[(r + 1) * 8:(r + 2) * 8, (c + 1) * 8:(c + 2) * 8] = 255
            self.assertTrue(frames.has_stamp(f))
            fs.append((k * 0.5, f))
        ok, txt = frames.overlay_check(None, frames=fs)
        self.assertTrue(ok, txt)

    def test_frames_cursor_ignores_stamp_corner(self):
        import frames
        ok, txt = frames.cursor_check(self.video, fps=2.0)
        self.assertTrue(ok, txt)


if __name__ == '__main__':
    unittest.main(verbosity=1)
