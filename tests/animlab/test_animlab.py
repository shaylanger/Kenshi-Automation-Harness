#!/usr/bin/env python3
"""Offline regression tests for tools/animlab (phase 1, REPLAY): rec parser, metrics, gate logic.
No game, no recordings, no solver: synthetic recordings + a copy-through fake adapter.
Run: python3 tests/animlab/test_animlab.py   (exit 0 = all pass). Run before every animlab commit."""
import math, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', '..', 'tools', 'animlab')
sys.path.insert(0, TOOLS)
import recfmt, metrics as M, animlab  # noqa: E402

V = lambda v: '%.4f,%.4f,%.4f' % tuple(v)


def rec_line(i, st='ready', ti=0, cls=0, w=1.0, swing=0, zf=1.0, mp=(2.6, -1.5, 4.4), elb=(4.0, -4.0, 1.0), wb=10.0,
             napp=None, native=False):
    """one record, camera fixed at the origin looking +z (eye/rt/up/fw = world axes)."""
    t = i * 0.0139
    g0 = '%d %.4f %.4f %s %d %d 1 %.3f %d 0.0000 0.0000 0.000 0.000 0 0.00 0.00 0.00' % (i, t, 0.0139, st, ti, cls, w, swing)
    mf, mu = (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    J = [(-2, -3, -1), (-3, -6, -1), (-2.6, -5.5, 1.2), (1.6, -3.4, -1.9), elb, mp]
    g1 = ' '.join(V(x) for x in [mp, mf, mu, (-2.6, -5.5, 1.2), mp, mf, mu] + J)
    g2 = ' '.join(V(x) for x in [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    g3 = '0,0,0 0,0,0 %d 0 1 2.000' % (i if napp is None else napp)
    g4 = '%.1f 1,0,0 1,0,0 %.3f 0,-1.5,-0.7 0,-2.8,-1.5 0,-8.7,-0.7 0,1,0 0,0,1' % (wb, zf)
    s = '%s | %s | %s | %s | %s' % (g0, g1, g2, g3, g4)
    if native:
        s += ' | 1 ' + ' '.join(V(x) for x in J) + ' 1,0,0 0,1,0 1,0,0 0,1,0 0.7,0.2,-0.5 1,0,0,0 0.7,0.2,-0.5 1,0,0,0'
    return s + '\n'


def write_rec(path, lines, meta=()):
    with open(path, 'w') as f:
        f.write('# build test\n')
        for m in meta:
            f.write('# %s\n' % m)
        f.write('# n t dt ... (header)\n')
        f.writelines(lines)


def smooth(i):   # weapon grip moving at constant speed: zero jitter
    return (2.6 + 0.002 * i, -1.5, 4.4)


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='animlab-test-')

    def p(self, name):
        return os.path.join(self.d, name)

    def test_parse(self):
        write_rec(self.p('a.txt'), [rec_line(i, mp=smooth(i), native=(i == 3)) for i in range(5)], ['set -1 stretch 1.3', 'set 2 elb 0'])
        R = recfmt.parse(self.p('a.txt'))
        self.assertEqual(len(R), 5)
        self.assertIn('set -1 stretch 1.3', R.meta)
        f = R.frames[3]
        self.assertEqual(f['napp'], 3)
        self.assertAlmostEqual(f['zf'], 1.0)
        self.assertIsNotNone(f['nat'])
        self.assertIsNone(R.frames[2]['nat'])
        self.assertAlmostEqual(f['mp'][0], 2.606, places=3)

    def test_states_native_and_settle(self):
        lines = [rec_line(i, mp=smooth(i)) for i in range(10)]
        lines += [rec_line(i, mp=smooth(i), swing=1, st='swinging') for i in range(10, 20)]
        lines += [rec_line(i, mp=smooth(i)) for i in range(20, 80)]
        lines += [rec_line(i, mp=smooth(i), zf=0.5) for i in range(80, 90)]
        write_rec(self.p('s.txt'), lines)
        P = M.frame_metrics(recfmt.parse(self.p('s.txt')))
        self.assertEqual(P[5]['state'], 'ready')
        self.assertEqual(P[15]['state'], 'swing')
        self.assertEqual(P[85]['state'], 'native')
        R = recfmt.parse(self.p('s.txt'))
        Pr, Ps = M.frame_metrics(R), M.frame_metrics(R)
        animlab.mark_settle(Pr, Ps, R.frames, 0.3)
        self.assertEqual(Pr[21]['state'], 'settle')          # 0.3 s = 21 frames after the swing
        self.assertEqual(Pr[45]['state'], 'ready')

    def test_jitter_metric(self):
        write_rec(self.p('j0.txt'), [rec_line(i, mp=smooth(i)) for i in range(60)])
        noisy = [rec_line(i, mp=(2.6 + 0.002 * i + (0.01 if i % 2 else -0.01), -1.5, 4.4)) for i in range(60)]
        write_rec(self.p('j1.txt'), noisy)
        T0 = M.state_table(M.frame_metrics(recfmt.parse(self.p('j0.txt'))))
        T1 = M.state_table(M.frame_metrics(recfmt.parse(self.p('j1.txt'))))
        self.assertLess(T0['ready']['jit_p95'], 0.05)
        self.assertGreater(T1['ready']['jit_p95'], 1.0)

    def test_compare_identical_pass_and_perturbed_fail(self):
        write_rec(self.p('g.txt'), [rec_line(i, mp=smooth(i)) for i in range(150)])
        write_rec(self.p('r.txt'), [rec_line(i, mp=smooth(i), elb=(4.0, -3.0, 1.0)) for i in range(150)])
        fails, n = animlab.compare(self.p('g.txt'), self.p('g.txt'), quiet=True)
        self.assertEqual(fails, [])
        self.assertGreaterEqual(n, 100)
        fails, n = animlab.compare(self.p('g.txt'), self.p('r.txt'), quiet=True)
        self.assertTrue(any('elbow_p95' in f for f in fails), fails)

    def test_ungated_states_are_info_only(self):
        # a swing that differs a lot does not fail the gate (swing follows the native animation: info only)
        g = [rec_line(i, mp=smooth(i)) for i in range(130)] + [rec_line(i, mp=smooth(i), swing=1) for i in range(130, 160)]
        r = [rec_line(i, mp=smooth(i)) for i in range(130)] + [rec_line(i, mp=smooth(i), swing=1, elb=(0, 0, 2)) for i in range(130, 160)]
        write_rec(self.p('g.txt'), g)
        write_rec(self.p('r.txt'), r)
        fails, n = animlab.compare(self.p('g.txt'), self.p('r.txt'), quiet=True)
        self.assertEqual(fails, [])

    def test_too_few_frames_fails(self):
        write_rec(self.p('g.txt'), [rec_line(i, mp=smooth(i)) for i in range(40)])
        fails, n = animlab.compare(self.p('g.txt'), self.p('g.txt'), quiet=True)
        self.assertTrue(any('comparable frames' in f for f in fails))

    def test_gate_cli_with_copy_adapter(self):
        write_rec(self.p('g.txt'), [rec_line(i, mp=smooth(i)) for i in range(150)])
        ad = self.p('copy_adapter.py')
        with open(ad, 'w') as f:
            f.write('import shutil, sys\nshutil.copy(sys.argv[1], sys.argv[2])\nprint("calib 1,2,3,4,5")\n')
        cmd = [sys.executable, os.path.join(TOOLS, 'animlab.py'), 'gate', self.p('g.txt'), '--adapter', '%s %s' % (sys.executable, ad), '--quiet']
        p = subprocess.run(cmd, stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn('GATE PASS', p.stdout)


    def test_moves_gate(self):   # C1: a state that never shows or does not move from ready fails
        T = {'aim': dict(move_dm=3.8, move_deg=24.0), 'reload': dict(move_dm=0.2, move_deg=3.0)}
        ok, txt = M.moves_ok(T, ('aim', 'reload'))
        self.assertFalse(ok); self.assertIn('reload:0.2dm/3deg:STILL', txt)
        ok, txt = M.moves_ok({'reload': dict(move_dm=7.7, move_deg=106.0)}, ('aim', 'reload'))
        self.assertFalse(ok); self.assertIn('aim:MISSING', txt)
        self.assertTrue(M.moves_ok(T, ('aim',))[0])

    def test_arc_gate(self):   # E1: edge must lead on >= share of fast stroke frames, without folding the wrist
        good = dict(arc_ok=0.95, arc_p05=0.8, arc_n=80, wb_max=20.0)
        self.assertTrue(M.arc_gate({'swing': good}, {'swing': 0.85})[0])
        ok, txt = M.arc_gate({'swing': dict(good, arc_ok=0.5)}, {'swing': 0.85})
        self.assertFalse(ok); self.assertTrue(txt[0].endswith(':BAD'))
        self.assertFalse(M.arc_gate({'swing': dict(good, wb_max=107.0)}, {'swing': 0.85})[0])   # lead by wrist fold
        self.assertEqual(M.arc_gate({}, {'swing': 0.85}), (False, ['swing:NO_FAST_FRAMES']))

    def test_bolt_check(self):   # C3: a bolt that moves on the weapon fails, a rigid one passes
        lab = ['ready'] * 40
        rigid = {n: (5.9, 1.0, 0.0) for n in range(40)}
        self.assertTrue(M.bolt_ok(M.bolt_table(rigid, lab))[0])
        loose = {n: (5.9 + (0.3 if n % 2 else 0.0), 1.0, 0.0) for n in range(40)}
        ok, txt = M.bolt_ok(M.bolt_table(loose, lab))
        self.assertFalse(ok); self.assertTrue(txt[0].endswith(':BAD'))
        self.assertEqual(M.bolt_ok({}), (False, ['no visible bolt frames']))
        with tempfile.NamedTemporaryFile('w', suffix='.bolt', delete=False) as f:
            f.write('# n ok vis | o | x | y | z\n0 1 1 | 5.9 1.0 0.0 | 0 0 -1 | 0 -1 0 | 1 0 0\n1 0 1 | 0 0 0 | 0 0 0 | 0 0 0 | 0 0 0\n')
        try:
            self.assertEqual(M.read_bolt(f.name), {0: (5.9, 1.0, 0.0)}); self.assertEqual(M.read_bolt.used, 'bl')
            with open(f.name, 'a') as g:
                g.write('2 1 1 | 5.7 1.0 0.3 | 0 0 -1 | 0 -1 0 | 1 0 0 | -1.0 5.9 0.0 120.0' + chr(10))
            self.assertEqual(M.read_bolt(f.name), {2: (-1.0, 5.9, 0.0)}); self.assertEqual(M.read_bolt.used, 'sl')
            self.assertEqual(M.read_bolt(f.name, 'bl')[2], (5.7, 1.0, 0.3))
        finally:
            os.unlink(f.name)

    def test_stock_check(self):   # C2: stock high on screen fails; a rotated ready pose fails against the reference
        T = {'ready': dict(n=40, p50=20.0, p95=24.0, max=26.0)}
        self.assertTrue(M.stock_ok(T)[0])
        ok, txt = M.stock_ok({'ready': dict(T['ready'], p95=67.0)})
        self.assertFalse(ok); self.assertTrue(txt[0].endswith(':BAD'))
        ref = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)); c, s = math.cos(math.radians(24.5)), math.sin(math.radians(24.5))
        self.assertTrue(M.stock_ok(T, ref, ref)[0])
        ok, txt = M.stock_ok(T, ((0.0, -s, c), (0.0, c, s)), ref)
        self.assertFalse(ok); self.assertIn('fwd=24.5', txt[-1])
        self.assertEqual(M.stock_ok({}), (False, ['ready:NO_FRAMES']))
        lab = ['ready'] * 12   # stock behind a grip low in view: top below mid-screen
        F = [dict(cls=1, on=1, w=1.0, mp=(0.0, -2.0, 6.0), mf=(0.0, 0.0, 1.0), mu=(0.0, 1.0, 0.0))] * 12
        t = M.stock_table(F, lab)['ready']
        self.assertEqual(t['n'], 12); self.assertLess(t['p95'], 50.0)

    def test_jitter_faithful(self):   # X1: game jitter the replay does not show = noise from outside the solver
        g = {'ready': dict(n=50, jit_p95=1.74), 'reload': dict(n=50, jit_p95=0.8), 'swing': dict(n=50, jit_p95=60.0)}
        r = {'ready': dict(n=50, jit_p95=0.42), 'reload': dict(n=50, jit_p95=0.1), 'swing': dict(n=50, jit_p95=10.0)}
        ok, txt = M.jitter_faithful(g, r)
        self.assertFalse(ok); self.assertEqual(len(txt), 1); self.assertTrue(txt[0].startswith('ready:') and txt[0].endswith(':BAD'))
        self.assertTrue(M.jitter_faithful(g, dict(r, ready=dict(n=50, jit_p95=1.0)))[0])   # reload below 1 px, swing skipped

    def test_churn_check(self):   # E1: forearm out-and-back with the grip still fails; wind-up hand roll > 15 deg fails
        def series(vx, roll_step, n=40, stroke_step=0.0):
            S = []
            for i in range(n):
                a = math.radians(roll_step * max(0, i - 15) + stroke_step * max(0, i - 26))   # blade up rolls about the forearm axis x
                f, u = (1.0, 0.0, 0.0), (0.0, math.cos(a), math.sin(a))
                B = (f, u, M.cross(f, u))
                x = vx(i); st = 'swing' if i >= 15 else 'ready'
                S.append(dict(i=i, t=i / 60.0, st=st, swu=min(1.0, max(0.0, (i - 15) / 40.0)), v=(x, 600.0), vm=(x, 600.0),
                              w=(800.0, 600.0), g=(800.0, 500.0), tip=(900.0, 300.0), ax=(1.0, 0.0, 0.0), B=B))
            return S
        still = lambda i: 600.0
        ok, txt, d = M.churn_check(series(still, 1.0))   # 1 deg/frame over 11 wind-up frames (u < 0.28)
        self.assertTrue(ok, txt); self.assertTrue(txt[0].startswith('rev=0px')); self.assertIn('windup_roll=11.0deg', txt[1])
        ok, txt, d = M.churn_check(series(still, 3.0))
        self.assertFalse(ok); self.assertTrue(txt[1].endswith(':BAD')); self.assertIn('windup_roll=33.0deg', txt[1])
        out_back = lambda i: 600.0 + 30.0 * (10 - abs(i - 20)) if 10 <= i <= 30 else 600.0   # 300 px out and back in 0.33 s
        ok, txt, d = M.churn_check(series(out_back, 0.0))
        self.assertTrue(ok, txt)   # 300 px < 450
        big = lambda i: 600.0 + 60.0 * (10 - abs(i - 20)) if 10 <= i <= 30 else 600.0   # 600 px out and back
        ok, txt, d = M.churn_check(series(big, 0.0))
        self.assertFalse(ok); self.assertTrue(txt[0].startswith('rev=600px/450:BAD@10-20-30'), txt[0])
        ok, txt, d = M.churn_check(series(still, 0.0, stroke_step=20.0))   # wind-up still, 20 deg/frame at the stroke start
        self.assertTrue(ok, txt); self.assertTrue(txt[2].endswith('(info)'), txt[2])
        ok, txt, d = M.churn_check(series(still, 0.0, stroke_step=20.0), sroll_gate=True)
        self.assertFalse(ok); self.assertTrue(txt[2].startswith('stroke_roll=') and txt[2].endswith(':BAD'), txt[2])
        self.assertTrue(M.churn_check(series(still, 0.0, stroke_step=3.0), sroll_gate=True)[0])   # 3 deg/frame: small + gradual
        self.assertAlmostEqual(M._twist((0, 0, 1.0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((1, 0, 0), (0, 0, 1), (0, -1, 0))), 0.0)   # roll about x, not z

    def test_inline_check(self):   # E1 (Shay 2026-10-09): blade in line with the forearm, the arm (not the wrist) drives the arc
        def series(off, arm_turn, hand_turn, n=40):
            S = []
            for i in range(n):
                ph = 'windup' if i < 20 else 'stroke'
                ta = math.radians(arm_turn * i); tb = ta + math.radians(off + hand_turn * i)
                el = (0.0, -3.0, 10.0); fa = (math.sin(ta), math.cos(ta), 0.0)   # forearm turns about the elbow in the screen plane
                wr = M.add(el, M.mul(fa, 2.5)); mf = (math.sin(tb), math.cos(tb), 0.0)
                S.append(dict(i=i, ph=ph, el=el, wr=wr, mp=wr, mf=mf, tip=M.add(wr, M.mul(mf, 8.0))))
            return S
        T = M.inline_table(series(10.0, 2.0, 0.0))   # 10 deg off line, the whole arm turns: no wrist share
        self.assertAlmostEqual(T['stroke']['fb_med'], 10.0, 3); self.assertAlmostEqual(T['stroke']['sc_max'], 10.0, 1)
        self.assertLess(T['stroke']['wr'], 1e-6)
        ok, txt = M.inline_check(T); self.assertTrue(ok, txt)
        T = M.inline_table(series(80.0, 0.0, 2.0))   # blade 80-158 deg off the still forearm, turned by the wrist only
        self.assertAlmostEqual(T['stroke']['wr'], 1.0, 6); self.assertGreater(T['windup']['fb_med'], 80.0)
        ok, txt = M.inline_check(T); self.assertFalse(ok)
        self.assertTrue(txt[1].startswith('windup:') and txt[1].endswith(':BAD') and txt[2].endswith(':BAD'), txt)
        ok, txt = M.inline_check(M.inline_table(series(10.0, 1.0, 1.0)))   # in line at first, the wrist drifts it off 40+ deg
        self.assertFalse(ok); self.assertIn('stroke:', txt[2]); self.assertTrue(txt[2].endswith(':BAD'), txt)
        self.assertEqual(M.swing_phase('swing', 0.3), 'stroke'); self.assertEqual(M.swing_phase('swing', 0.1), 'windup')
        self.assertEqual(M.swing_phase('block', 0.3), 'block')


if __name__ == '__main__':
    unittest.main(verbosity=1)
