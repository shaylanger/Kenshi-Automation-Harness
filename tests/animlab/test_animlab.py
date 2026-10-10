#!/usr/bin/env python3
"""Offline regression tests for tools/animlab (phase 1, REPLAY): rec parser, metrics, gate logic.
No game, no recordings, no solver: synthetic recordings + a copy-through fake adapter.
Run: python3 tests/animlab/test_animlab.py   (exit 0 = all pass). Run before every animlab commit."""
import math, os, shutil, subprocess, sys, tempfile, unittest

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

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

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

    def test_agree_rows(self):
        # lab agreement: a rec judged against itself agrees on every check; a block press that hangs only in the
        # "game" rec is a guard disagreement (f059 z25: game -75, replay re-solved +44)
        lines = [rec_line(i, mp=smooth(i)) for i in range(40)]
        lines += [rec_line(i, mp=smooth(i), st='blocking', ti=3) for i in range(40, 60)] + [rec_line(i, mp=smooth(i)) for i in range(60, 80)]
        write_rec(self.p('g.txt'), lines)
        R = recfmt.parse(self.p('g.txt'))
        rows = M.agree_rows(R, R)
        self.assertTrue(rows and all(r[3] for r in rows), rows)
        self.assertIn('guard', [r[0] for r in rows])
        H = recfmt.parse(self.p('g.txt'))
        for f in H.frames[40:61]:
            f['mf'] = (0.0, -1.0, 0.05)
        g = {r[0]: r for r in M.agree_rows(H, R)}
        self.assertFalse(g['guard'][1]); self.assertTrue(g['guard'][2]); self.assertFalse(g['guard'][3])

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

    def test_wrist_native_frames_exempt(self):   # Shay 2026-10-10: native-animation frames are exempt from the wrist limit
        import spec as S
        base = [rec_line(i, mp=smooth(i), wb=10.0) for i in range(60)]
        # measured values in record n are what frame n-1 rendered: the first native record still measures the ready pose
        write_rec(self.p('wn.txt'), base + [rec_line(i, mp=smooth(i), zf=0.5, wb=10.0 if i == 60 else 90.0) for i in range(60, 80)]
                  + [rec_line(i, mp=smooth(i), w=0.0, wb=90.0) for i in range(80, 90)])
        ok, txt = S.wrist(self.p('wn.txt'))
        self.assertTrue(ok, txt)
        write_rec(self.p('ws.txt'), base + [rec_line(i, mp=smooth(i), wb=45.0) for i in range(60, 80)])
        ok, txt = S.wrist(self.p('ws.txt'))   # solver-posed ready frames keep the 30 deg hold limit
        self.assertFalse(ok, txt)
        R = recfmt.parse(self.p('wn.txt'))
        self.assertEqual([M.is_native(r) for r in (R.frames[5], R.frames[70], R.frames[85])], [False, True, True])

    def test_reload_upright_and_native_wrist(self):   # Shay 2026-10-10 xbow-reload: upright two-hand reload, not nose-down
        import spec as S
        lines = [rec_line(i, mp=smooth(i), cls=1, wb=10.0) for i in range(40)]
        lines += [rec_line(i, mp=smooth(i), cls=1, ti=2, st='reloading', wb=40.0 if i > 40 else 10.0) for i in range(40, 80)]
        lines += [rec_line(i, mp=smooth(i), cls=1, wb=10.0) for i in range(80, 100)]
        write_rec(self.p('rl.txt'), lines)
        F = recfmt.parse(self.p('rl.txt')).frames; lab = M.label_states(F)
        ok, txt = M.reload_check(F, lab)
        self.assertTrue(ok, txt)                      # bow up (mu y 1), nose level
        for i in range(40, 80):                       # bow on its side, nose down 30 deg
            F[i]['mu'] = (1.0, 0.1, 0.0); F[i]['mf'] = (0.0, -0.5, 0.866)
        ok, txt = M.reload_check(F, lab)
        self.assertFalse(ok, txt); self.assertIn('reload@40', ' '.join(txt))
        self.assertTrue(S.wrist(self.p('rl.txt'))[0])   # native reload (rlnat 1 default): wrist-exempt
        write_rec(self.p('rl0.txt'), lines, meta=('set -1 rlnat 0',))
        ok, txt = S.wrist(self.p('rl0.txt'))           # scripted reload (rlnat 0): solver-posed, hold limit 30
        self.assertFalse(ok, txt); self.assertIn('reload:wb_max=40.0', txt)

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
        self.assertTrue(ok, txt); self.assertTrue(txt[2].endswith('(info:over,gate off)'), txt[2])   # over the limit, not gated: says so (E6-e6r5 review)
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

    def test_ready_branch(self):   # sword ready elbow branch (lab 2026-10-09): replays found a 2nd ready solution, edge rolled ~100 deg
        A = ((1.4, -4.4, 3.0), (-0.35, 0.85, 0.40), (0.42, -0.24, 0.88)); B = ((5.1, -4.1, 5.0), (-0.35, 0.85, 0.40), (0.79, 0.50, -0.37))
        def runs(seq, n=20, gap=10):
            F, P = [], []
            for br, nxt in seq:
                for k in range(n + gap):
                    st = 'ready' if k < n else nxt
                    F.append(dict(cls=0)); P.append(dict(state=st, elb=br[0], mf=M.nz(br[1]), mu=M.nz(br[2])))
            return M.ready_runs(F, P)
        R = runs([(A, 'swing'), (A, 'block'), (A, 'swing')])
        self.assertEqual(len(R), 3); ok, txt = M.ready_branch(R); self.assertTrue(ok, txt)
        R = runs([(B, 'swing'), (A, 'swing'), (A, 'block'), (A, 'lower')])   # first swing from B (f13-sw0 replay); the lowering run is left out
        self.assertEqual(len(R), 3); ok, txt = M.ready_branch(R); self.assertFalse(ok)
        self.assertTrue(txt[2].endswith(':BAD') and not txt[3].endswith(':BAD'), txt)   # majority reference = A
        ok, txt = M.ready_branch(runs([(B, 'swing'), (B, 'swing')]), runs([(A, 'swing')]))   # all on B, game reference on A
        self.assertFalse(ok)

    def test_hinge_faith(self):
        # E5 hinge replay miss: replay forearm roll a constant ~60 deg off the game = FAIL; within a few deg (+ one outlier) = PASS
        G = [dict(i=i, fa=10.0 * math.sin(i / 7.0), ua=0.0) for i in range(100)] + [None]
        ok, t = M.hinge_faith(G, [dict(g, fa=g['fa'] + 60) if g else None for g in G]); self.assertFalse(ok, t)
        R = [dict(g, fa=g['fa'] + (90 if g['i'] == 50 else 1)) if g else None for g in G]
        ok, t = M.hinge_faith(G, R); self.assertTrue(ok, t); self.assertIn('fa_max=90@50', t)
        ok, t = M.hinge_faith(G, [None] * len(G)); self.assertFalse(ok)

    def test_stroke_check(self):
        # E6 misses 2026-10-10: a blade pointing into the screen is a short stub (len FAIL); an overhead whose blade lays
        # over to the side (tilt) or whose middle travels sideways (path) reads as a diagonal
        def swing(mf_at, stroke=2, n=40):
            F = [dict(swu=k / (n - 1.0), stroke=stroke, t=k * 0.02) for k in range(n)]
            P = [dict(state='swing', wih=1, mp=(0.0, 3.0 - 6.0 * k / (n - 1.0), 6.0), mf=M.nz(mf_at(k / (n - 1.0)))) for k in range(n)]
            return F, P
        up = lambda u: (0.0, 1.0, 0.3)
        ok, t = M.stroke_check(*swing(up), overhead=(2,)); self.assertTrue(ok, t)
        ok, t = M.stroke_check(*swing(lambda u: (0.0, 0.15, 1.0))); self.assertFalse(ok, t); self.assertIn('len=', t[0]); self.assertIn(':BAD', t[0])
        ok, t = M.stroke_check(*swing(lambda u: (-u, 1.0 - u * 0.5, 0.3)), overhead=(2,)); self.assertFalse(ok, t); self.assertIn('tilt=', t[0])
        ok, t = M.stroke_check(*swing(lambda u: (-u, 1.0 - u * 0.5, 0.3)), overhead=()); self.assertTrue(ok, t)   # only declared overheads
        F, P = swing(up)
        for k, p in enumerate(P):
            p['mp'] = (-3.0 * k / 39.0, p['mp'][1], 6.0)   # middle moves left as much as down
        ok, t = M.stroke_check(F, P, overhead=(2,)); self.assertFalse(ok, t); self.assertIn('path=', t[0]); self.assertIn(':BAD(', t[0])
    def test_guard_check(self):
        # miss 2026-10-10 sword-z25-block orbit 3.0: block guard with the blade hanging straight down, hilt at the face
        def take(mf):
            F = [dict(st='blocking', ti=3, rt=(1, 0, 0), up=(0, 1, 0), fw=(0, 0, 1), hd=(0, -1.5, -0.7)) for _ in range(11)]
            P = [dict(state='native', wih=1, mf=M.nz(mf), mp=(0.5, -2.0, 0.0)) for _ in range(10)]
            return M.guard_series(F, P)
        ok, t = M.guard_check(take((0.1, -1.0, 0.05))); self.assertFalse(ok, t); self.assertIn(':BAD', t[0])
        ok, t = M.guard_check(take((0.2, 0.6, 0.8))); self.assertTrue(ok, t)
        ok, t = M.guard_check([]); self.assertFalse(ok)
        # miss 2026-10-10 blk-survey: 2 raised presses + 1 hanging press = FAIL (the whole-take median was raised)
        S = [(i, 40.0, 3.0) for i in range(0, 12)] + [(i, -78.0, 3.0) for i in range(30, 40)] + [(i, 55.0, 3.0) for i in range(60, 72)]
        ok, t = M.guard_check(S); self.assertFalse(ok, t); self.assertIn('presses=3 hanging=1:BAD', t[0]); self.assertIn('press1@frame30', ' '.join(t))
        ok, t = M.guard_check([x for x in S if not 30 <= x[0] < 40]); self.assertTrue(ok, t)
        ok, t = M.guard_table_check([('a', 59.6, '228c60'), ('b', -74.6, '226e50')]); self.assertFalse(ok, t)
        ok, t = M.guard_table_check([('a', 59.6, '228c60'), ('b', 45.7, '223cc0')]); self.assertTrue(ok, t)
    def test_pool_predict(self):
        # miss 2026-10-10 E6 kfx-b2: one swing per stroke predicted PASS; the game's random native variants failed the take
        def sw(g, n=12, wb=40.0, blade=True, churn=True): return dict(frame=0, arc_good=g, arc_n=n, wb_max=wb, full=True, ok=dict(blade=blade, stroke=True, churn=churn))
        good = [sw(12) for _ in range(9)]
        ok, t = M.pool_predict(good); self.assertTrue(ok, t)
        ok, t = M.pool_predict([sw(12)] + [sw(5)] * 3); self.assertFalse(ok, t); self.assertIn('arc:take=0.00', ' '.join(t))
        ok, t = M.pool_predict(good + [sw(12, blade=False)]); self.assertFalse(ok, t)   # 9/45 takes hold the bad swing
        ok, t = M.pool_predict([sw(12)]); self.assertFalse(ok, t)                       # fewer full swings than a take
        ok, t = M.pool_predict(good + [sw(12, churn=False)]); self.assertFalse(ok, t)   # Misses 2026-10-10: stroke-start roll (R3) pooled too
        self.assertIn('churn:', ' '.join(t))
        # free block: per-press guard over the native techniques (f059 z25: press 0 hanging -75)
        S = [(i, 40.0, 3.0) for i in range(0, 12)] + [(i, -78.0, 3.0) for i in range(30, 40)]
        V = M.guard_press_verdicts(S); self.assertEqual([v['ok']['guard'] for v in V], [True, False])
        ok, t = M.pool_predict(V + M.guard_press_verdicts([(i, 50.0, 3.0) for i in range(12)]), ('guard',)); self.assertFalse(ok, t)
    def test_zoomband_check(self):
        # miss 2026-10-10 zoom-sweep Z1 crossfade: own headless torso / floating hand in frame between eye and head-show distance
        def fr(d):
            return dict(zoom=d, zf=0.5, nk=(0, -2.7, -1.7), sp=(0, -8.6, -0.9), Lsh=(-1.8, -3.4, -1.8), Rsh=(1.8, -3.4, -1.8),
                        Lel=(-2.2, -6.2, -1.8), Rel=(2.2, -6.2, -1.8), Lwr=(-2.8, -9.1, -0.8), Rwr=(2.8, -9.1, -0.8))
        ok, t = M.zoomband_check(M.zoomband_series([fr(0.0)] * 5 + [fr(25.0)] * 5)); self.assertTrue(ok, t)   # eye / far: not the band
        ok, t = M.zoomband_check(M.zoomband_series([fr(0.0)] * 5 + [fr(8.0)] * 3)); self.assertFalse(ok, t)
        self.assertIn('body_in_frame=3/0:BAD', ' '.join(t)); self.assertIn('nk(', t[-1])
        far = dict(fr(1.0), nk=(0, -50, 1), sp=(0, -50, 1), Lsh=(0, -50, 1), Rsh=(0, -50, 1), Lel=(0, -50, 1), Rel=(0, -50, 1), Lwr=(0, -50, 1), Rwr=(0, -50, 1))
        ok, t = M.zoomband_check(M.zoomband_series([far] * 4)); self.assertTrue(ok, t)   # band frames with nothing in view pass
        ok, t = M.zoomband_check(M.zoomband_series([dict(fr(8.0), band_hidden=1)] * 3)); self.assertTrue(ok, t)   # hidden body: nothing drawn

    def test_flag_lag(self):   # Misses 2026-10-10 Z1 zoomband: band_hidden recorded a frame after the hide (stale label)
        z = lambda d, bh: dict(zoom=d, band_hidden=bh)
        good = [z(0.0, 0), z(4.8, 1), z(8.0, 1), z(16.0, 0), z(0.0, 0)]
        self.assertEqual(M.flag_lag(good, 'band_hidden', M.band_expect(good)), [])
        late = [z(0.0, 0), z(4.8, 0), z(8.0, 1), z(16.0, 1), z(17.0, 0), z(3.0, 0), z(3.5, 1), z(0.0, 1), z(0.0, 0)]
        self.assertEqual(M.flag_lag(late, 'band_hidden', M.band_expect(late)), [(1, 0, 1), (3, 1, 0), (5, 0, 1), (7, 1, 0)])
        never = [z(0.0, 0), z(4.8, 0), z(8.0, 0)]   # band hide off / older build: no rule, no lag
        self.assertEqual(M.flag_lag(never, 'band_hidden', M.band_expect(never)), [])
        ok, t = M.zoomband_check([], 0, [(1, 0, 1)]); self.assertFalse(ok); self.assertIn('label_lag=1:BAD@1(bh0,want1)', ' '.join(t))

    def test_spike_check(self):
        # Misses 2026-10-10 PT30 follow-through edge roll spike + mutations rec-one-frame-snap / -jump
        import math as _m
        def pose(i, roll=0.0, dx=0.0):
            a = _m.radians(i * 2.0 + roll)   # edge turns 2 deg per frame about the blade (+z)
            return dict(mf=(0.0, 0.0, 1.0), mu=(_m.sin(a), _m.cos(a), 0.0), mp=(2.0 + dx + 0.01 * i, -1.5, 4.4), wih=1,
                        tpx=(800.0, 450.0), state='swing')
        def run(P):
            F = [dict(dt=0.016, w=1.0, zf=1.0, st='swinging') for _ in P]
            return M.spike_check(F, P)
        ok, t = run([pose(i) for i in range(30)]); self.assertTrue(ok, t)
        P = [pose(i) for i in range(30)]; P[15] = pose(15, roll=50.0)            # one-frame flick out and back
        ok, t = run(P); self.assertFalse(ok, t); self.assertIn('flick', ' '.join(t))
        P = [pose(i, roll=(70.0 if i >= 15 else 0.0)) for i in range(30)]        # one 70 deg step that stays
        ok, t = run(P); self.assertFalse(ok, t); self.assertIn('step', ' '.join(t))
        P = [pose(i) for i in range(30)]; P[10] = pose(10, dx=1.5)                # grip jumps 1.5 dm for one frame
        ok, t = run(P); self.assertFalse(ok, t); self.assertIn('pos', ' '.join(t))
        P = [pose(i, roll=(40.0 if i >= 15 else 0.0)) for i in range(30)]        # 40 deg step: below the limit
        ok, t = run(P); self.assertTrue(ok, t)

if __name__ == '__main__':
    unittest.main(verbosity=1)
