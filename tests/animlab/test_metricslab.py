#!/usr/bin/env python3
"""Offline tests for tools/animlab/metricslab.py (phase 2, METRICS LAB): motion interpolation, geometry, intersection
and reach checks, the drive-adapter contract (a fake adapter that puts the weapon exactly on the target).
No game, no solver, no recordings. Run: python3 tests/animlab/test_metricslab.py (exit 0 = all pass)."""
import json, math, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', '..', 'tools', 'animlab')
sys.path.insert(0, TOOLS)
import metricslab as ML  # noqa: E402

FAKE = r'''
import sys
args = sys.argv[1:]
body, frames, out = args[0], args[1], args[2]
side = args[args.index('--side') + 1] if '--side' in args else 'R'
V = lambda v: '%.5f,%.5f,%.5f' % tuple(v)
def arm(sx, p=None, f=None, u=None):
    sh = (sx * 2.0, -3.0, -1.0)
    if p is None:
        p, f, u = (sx * 2.5, -6.0, 2.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    wr = tuple(p[k] - 0.4 * f[k] for k in range(3))
    el = ((sh[0] + wr[0]) / 2 + sx * 1.0, (sh[1] + wr[1]) / 2 - 1.0, (sh[2] + wr[2]) / 2)
    d = [wr[k] - el[k] for k in range(3)]; n = sum(x * x for x in d) ** 0.5
    hx = tuple(x / n for x in d)
    return ' '.join(V(x) for x in (sh, el, wr, hx, p, f, u))
print('calib 2.8,3.2,2.8,3.2,1.05')
with open(out, 'w') as o:
    o.write('# fake side=%s calib=2.8,3.2,2.8,3.2,1.05\n' % side)
    for i, line in enumerate(l for l in open(frames) if not l.startswith('#')):
        x = line.split(); t = float(x[0])
        p, f, u = (tuple(float(c) for c in x[k].split(',')) for k in (2, 3, 4))
        L = arm(-1, p, f, u) if side == 'L' else arm(-1)
        R = arm(1, p, f, u) if side == 'R' else arm(1)
        o.write('%d %.5f | %s | %s | 1.0 1.0 0 0 | 0,0,0 -1,0,0 0,1,0 0,0,1\n' % (i, t, L, R))
'''


def motion(R=None, L=None, **kw):
    m = dict(name='t', fps=30, preroll=0.1, hands={})
    if R:
        m['hands']['R'] = dict(weapon='sword', keys=R)
    if L:
        m['hands']['L'] = dict(weapon='sword', keys=L)
    m.update(kw)
    return m


def key(t, p, f=(0, 1, 0.2), u=(0, -0.2, 1), **kw):
    return dict(t=t, p=list(p), f=list(f), u=list(u), **kw)


class Interp(unittest.TestCase):
    def test_keys_hit_and_hold(self):
        keys = [key(0, (0, 0, 5)), key(1, (2, 0, 5)), key(2, (2, 2, 5))]
        for mode in ('linear', 'smooth', 'spline'):
            self.assertEqual(ML.sample_track(keys, 1.0, mode), (2, 0, 5))
            self.assertEqual(ML.sample_track(keys, 9.0, mode), (2, 2, 5))
            self.assertEqual(ML.sample_track(keys, -1.0, mode), (0, 0, 5))
        self.assertAlmostEqual(ML.sample_track(keys, 0.5, 'linear')[0], 1.0)

    def test_direction_slerp_unit(self):
        keys = [key(0, (0, 0, 5), f=(1, 0, 0)), key(1, (0, 0, 5), f=(0, 1, 0))]
        f = ML.sample_track(keys, 0.5, 'linear', 'f')
        self.assertAlmostEqual(math.hypot(*f), 1.0, places=6)
        self.assertAlmostEqual(f[0], f[1], places=6)

    def test_frames_preroll_and_orthonormal(self):
        fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
        json.dump(motion(R=[key(0, (2, 0, 5)), key(1, (0, 0, 5), u=(0, 0.5, 1))]), open(path, 'w'))
        m = ML.load_motion(path)
        fr = ML.frames_for(m, 'R')
        self.assertEqual(sum(1 for x in fr if x[0] < 0), 3)       # 0.1 s pre-roll at 30 fps
        self.assertEqual(len(fr), 3 + 31)
        for t, cls, p, f, u, o, seg in fr:
            self.assertAlmostEqual(ML.dot(f, u), 0.0, places=6)

    def test_bad_motion(self):
        fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
        json.dump(motion(R=[key(0, (2, 0, 5), f=(0, 1, 0), u=(0, 1, 0))]), open(path, 'w'))
        with self.assertRaises(ValueError):
            ML.load_motion(path)


class Geometry(unittest.TestCase):
    def test_seg_seg(self):
        self.assertAlmostEqual(ML.seg_seg((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)), 1.0)
        self.assertAlmostEqual(ML.seg_seg((-1, 0, 0), (1, 0, 0), (0, -1, 1), (0, 1, 1)), 1.0)   # crossing, 1 apart
        self.assertAlmostEqual(ML.seg_seg((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)), 0.0)
        self.assertAlmostEqual(ML.seg_seg((0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0)), 2.0)

    def test_near_clip(self):
        self.assertTrue(ML.near_clipped((0, 0, 1.0), (0, 0, 6.0), 3.0, 24))     # straight at the eye
        self.assertFalse(ML.near_clipped((0, -8, 4.0), (0, -8, 9.0), 3.0, 24))  # far below the view
        self.assertFalse(ML.near_clipped((1, 0, -2.0), (1, 0, -1.0), 3.0, 24))  # behind the camera


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.fake = os.path.join(self.d, 'fake.py')
        open(self.fake, 'w').write(FAKE)
        open(os.path.join(self.d, 'body.txt'), 'w').write('# body\n')

    def run_m(self, m):
        path = os.path.join(self.d, 'm.json')
        json.dump(m, open(path, 'w'))
        m = ML.load_motion(path)
        solved, frames = ML.run_motion(m, '%s %s' % (sys.executable, self.fake), os.path.join(self.d, 'body.txt'), 0,
                                       os.path.join(self.d, 'out'))
        return m, ML.evaluate(m, solved, frames)

    def test_dual_pass_and_merge(self):
        m, (P, rows, v) = self.run_m(motion(
            R=[key(0, (3, -1, 5), label='guard'), key(0.5, (3.5, 0, 5), label='up')],
            L=[key(0, (-3, -1, 5)), key(0.5, (-3.5, 0, 5))]))
        self.assertTrue(v['ok'], v['fails'])
        a = {r['side']: r for r in rows if r['seg'] == '*all*'}
        self.assertLess(a['R']['terr_max'], 1e-3)
        self.assertGreater(a['R']['ww_min'], 0.5)
        self.assertEqual(sorted(r['seg'] for r in rows if r['side'] == 'R'), ['*all*', 'guard', 'up'])
        pose = [l for l in open(os.path.join(self.d, 'out', 'pose.txt')) if not l.startswith('#')]
        self.assertEqual(len(pose), len(ML.frames_for(m, 'R')))
        g = pose[-1].split('|')
        self.assertTrue(g[1].split()[4].startswith('-3.5'))   # left prop from the L run
        self.assertTrue(g[2].split()[4].startswith('3.5'))    # right prop from the R run

    def test_crossed_blades_fail(self):
        _, (P, rows, v) = self.run_m(motion(R=[key(0, (2, -1, 5), f=(-0.6, 0.8, 0), u=(0, 0, 1))],
                                            L=[key(0, (-2, -1, 5), f=(0.6, 0.8, 0), u=(0, 0, 1))]))
        self.assertFalse(v['ok'])
        self.assertTrue(any(f.startswith('R.ww_min') for f in v['fails']), v['fails'])

    def test_blade_in_face_fails(self):
        _, (P, rows, v) = self.run_m(motion(R=[key(0, (0.5, -0.5, 6), f=(0, 0, -1), u=(0, 1, 0))]))
        self.assertFalse(v['ok'])
        self.assertTrue(any(f.startswith('R.head_min') for f in v['fails']), v['fails'])
        self.assertTrue(any(f.startswith('R.clip_frames') for f in v['fails']), v['fails'])

    def test_limits_override(self):
        _, (P, rows, v) = self.run_m(motion(R=[key(0, (3, -1, 5))], limits=dict(wb_max=-1)))
        self.assertTrue(any(f.startswith('R.wb_max') for f in v['fails']), v['fails'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
