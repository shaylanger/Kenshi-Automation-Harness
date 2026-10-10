#!/usr/bin/env python3
"""Offline tests for tools/animlab/spec.py (rule map, check runner, unarmed spec) and taste.py (confusion scoring).
Synthetic data only. Run: python3 tests/animlab/test_spec.py   (exit 0 = all pass)."""
import io, json, math, os, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
import spec as S  # noqa: E402
import taste as T  # noqa: E402


def V(v):
    return '%.5f,%.5f,%.5f' % tuple(v)


def lerp(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def arm(sh, wr, hx_bend=0.0, up=(0, 1, 0), side=None, palm=(0, -1, 0)):
    """straight-ish arm: elbow midway and dropped 1.5 dm, fist 0.8 dm past the wrist along the forearm; hand X along the
    forearm turned by hx_bend deg (wrist bend) about the up axis."""
    el = (sh[0] + (wr[0] - sh[0]) * .5, sh[1] + (wr[1] - sh[1]) * .5 - 1.5, sh[2] + (wr[2] - sh[2]) * .5)
    fa = tuple(wr[i] - el[i] for i in range(3)); n = math.sqrt(sum(x * x for x in fa)); fa = tuple(x / n for x in fa)
    b = math.radians(hx_bend)
    hx = (fa[0] * math.cos(b) + fa[2] * math.sin(b), fa[1], -fa[0] * math.sin(b) + fa[2] * math.cos(b))
    pp = tuple(wr[i] + fa[i] * 0.8 for i in range(3))
    if side:   # prop target that poses a palm-down fist (KenshiFP prop convention, as the game), knuckles leading:
        # hand X flexed 22 deg toward the palm (the fixed candidates' flex_strike)
        pn = S._nz(S._sub(palm, S._mul(hx, S._dot(palm, hx))))
        f = math.radians(22.0)
        hx = S._nz(S._add(S._mul(hx, math.cos(f)), S._mul(pn, math.sin(f))))
        fa, up = S.prop_from_hand(hx, palm, side)
    return [sh, el, wr, hx, pp, fa, up]


def pose_file(frames):
    """frames: list of (t, Lwr, Rwr, opts) -> metricslab pose.txt text."""
    out = ['# synthetic pose']
    for i, (t, lw, rw, o) in enumerate(frames):
        L = arm((-2.0, -2.0, -0.5), lw, o.get('bL', 0.0), o.get('upL', (0, 1, 0)), None if 'upL' in o else 'L', o.get('palmL', (0, -1, 0)))
        R = arm((2.0, -2.0, -0.5), rw, o.get('bR', 0.0), o.get('upR', (0, 1, 0)), None if 'upR' in o else 'R', o.get('palmR', (0, -1, 0)))
        out.append('%d %.5f | %s | %s | 1.0 1.0 0 0 | 0,0,0 1,0,0 0,1,0 0,0,1' % (i, t, ' '.join(V(x) for x in L), ' '.join(V(x) for x in R)))
    return '\n'.join(out) + '\n'


GL, GR, HIT = (-2.0, -2.0, 4.0), (2.0, -2.0, 4.0), (0.3, -1.0, 6.5)


def punch(n=60, dur=1.0, peak=None, opts=lambda k, u: {}):
    fr = []
    for k in range(n):
        u = k / (n - 1.0)
        a = math.sin(math.pi * u) if peak is None else peak(u)
        fr.append((dur * u, GL, lerp(GR, HIT, a), opts(k, u)))
    return [(-0.2, GL, GR, {})] + fr


def checks(F):
    return {r[0] + (r[2].split(':')[0] if r[0] in ('U4', 'U6', 'U10') else ''): r[1] for r in S.unarmed_checks(S.read_pose(F))}


def tmp(text, suffix='.txt'):
    f = tempfile.NamedTemporaryFile('w', suffix=suffix, delete=False)
    f.write(text); f.close()
    return f.name


class TestUnarmed(unittest.TestCase):
    def test_clean_punch_passes(self):
        res = S.unarmed_checks(S.read_pose(tmp(pose_file(punch()))))
        bad = [r for r in res if r[1] not in ('PASS', 'INFO')]
        self.assertFalse(bad, bad)
        self.assertTrue(any(r[0] == 'U4' and 'strike R' in r[2] for r in res))

    def test_fist_above_eye(self):
        hi = (0.3, 1.5, 6.0)
        fr = [(-0.2, GL, GR, {})] + [(u / 59.0, GL, lerp(GR, hi, math.sin(math.pi * u / 59.0)), {}) for u in range(60)]
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(fr))))}
        self.assertEqual(res['U5'][1], 'FAIL', res['U5'])
        self.assertEqual(res['U6'][1], 'PASS', res['U6'])   # native reference: highest AT the strike is the native shape

    def test_windup_above_strike(self):
        # U6 (native reference): the fist rises 1 dm above the later strike point during the wind-up
        up = (2.0, -0.4, 4.0)
        fr = [(-0.2, GL, GR, {})]
        for k in range(60):
            u = k / 59.0
            w = lerp(GR, up, u / 0.4) if u < 0.4 else lerp(up, HIT, (u - 0.4) / 0.3) if u < 0.7 else lerp(HIT, GR, (u - 0.7) / 0.3)
            fr.append((u, GL, w, {}))
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(fr))))}
        self.assertEqual(res['U6'][1], 'FAIL', res['U6'])
        self.assertEqual(res['U5'][1], 'PASS', res['U5'])

    def test_wrist_fold(self):
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(punch(opts=lambda k, u: {'bR': 60.0 * math.sin(math.pi * u)})))))}
        self.assertEqual(res['U8'][1], 'FAIL', res['U8'])
        self.assertRegex(res['U8'][2], r'R (5\d|6\d)\.\d')

    def test_no_return_and_no_move(self):
        fr = [(-0.2, GL, GR, {})] + [(u / 59.0, GL, lerp(GR, (2.0, -2.0, 4.6), u / 59.0), {}) for u in range(60)]
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(fr))))}
        self.assertEqual(res['U2'][1], 'FAIL')
        self.assertEqual(res['U3'][1], 'FAIL')
        self.assertEqual(res['U4'][1], 'FAIL')   # no striking hand

    def test_roll_snap(self):
        def o(k, u):
            return {'upR': (0, 1, 0) if u < 0.5 else (1, 0, 0)}   # 90 deg roll of the fist in one frame
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(punch(opts=o)))))}
        self.assertEqual(res['U11'][1], 'FAIL', res['U11'])

    def test_guard_off_screen(self):
        fr = [(-0.2, (-6.0, -2.0, 2.0), GR, {})] + [(u / 59.0, (-6.0, -2.0, 2.0), lerp(GR, HIT, math.sin(math.pi * u / 59.0)), {}) for u in range(60)]
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(fr))))}
        self.assertEqual(res['U1'][1], 'FAIL', res['U1'])

    def test_palm_heel_straight_wrist(self):
        P = S.read_pose(tmp(pose_file(punch(opts=lambda k, u: {'bR': 60.0 * math.sin(math.pi * u)}))))
        r = {x[0]: x for x in S.unarmed_checks(P, name='shoteiL')}
        self.assertEqual(r['U17'][1], 'FAIL', r['U17'])
        self.assertNotIn('U17', {x[0] for x in S.unarmed_checks(P, name='ma_chudan')})
        r = {x[0]: x for x in S.unarmed_checks(S.read_pose(tmp(pose_file(punch()))), name='shoteiL')}
        self.assertEqual(r['U17'][1], 'PASS', r['U17'])

    # U19/U20 fixtures: ma chudan frames (corpus fists/fail-20261010 = coordinator review FAIL 2026-10-10, open claw +
    # palm-up reach; fists/pass-20261010 = the fixed candidate): guard (t 0) and the R contact (t 1.25)
    FAIL_GUARD = '30 0.00000 | -1.84380,-3.52586,-0.54716 -3.02570,-4.17953,1.89688 -1.89996,-2.29966,4.20052 0.35409,0.59138,0.72455 -1.92650,-1.97880,5.90650 0.03185,-0.14815,0.98850 -0.70118,0.70149,0.12773 | 1.49220,-3.19612,-1.66817 1.88201,-2.99758,1.09871 1.90001,-2.29969,4.20050 0.00565,0.21962,0.97562 1.28000,-1.22371,5.41370 -0.26199,0.84444,0.46731 -0.80743,-0.45702,0.37313 | 1.0000 1.0031 0 0'
    FAIL_HIT = '105 1.25000 | -1.84380,-3.52586,-0.54716 -3.43647,-4.53695,1.51160 -2.64616,-2.80952,4.06099 0.24978,0.54416,0.80100 -2.85402,-2.63528,5.77577 -0.05511,-0.22932,0.97184 -0.74776,0.65448,0.11203 | 1.49220,-3.19612,-1.66817 1.50089,-2.39354,2.24840 1.08460,-1.30277,5.20566 -0.10447,0.33610,0.93607 -0.04152,-0.67203,6.36666 -0.72829,0.55401,0.40338 -0.31059,-0.79157,0.52635 | 1.0000 1.4317 0 0'
    PASS_GUARD = '30 0.00000 | -1.84380,-3.52586,-0.54716 -3.02575,-4.17954,1.89685 -1.90002,-2.29964,4.20047 0.52072,0.33376,0.78583 -1.99060,-1.86790,5.87959 -0.21423,-0.04590,0.97575 -0.15458,0.98795,0.01253 | 1.49220,-3.19612,-1.66817 1.88201,-2.99759,1.09864 1.90000,-2.29972,4.20044 -0.12243,-0.06547,0.99037 0.73580,-2.27856,5.48811 -0.77202,0.28260,0.56935 -0.22552,-0.95928,0.17032 | 1.0000 1.0031 0 0'
    PASS_HIT = '105 1.25000 | -1.84380,-3.52586,-0.54716 -3.43643,-4.53695,1.51163 -2.64621,-2.80961,4.06111 0.40754,0.28255,0.86843 -2.96632,-2.48127,5.73555 -0.34497,-0.10469,0.93281 -0.15864,0.98602,0.05199 | 1.49220,-3.19612,-1.66817 1.50088,-2.39331,2.26007 1.08457,-1.30397,5.21785 -0.21800,-0.00873,0.97596 -0.20055,-1.39810,6.38124 -0.86812,0.17816,0.46331 -0.06992,-0.96801,0.24120 | 1.0000 1.4358 0 0'

    def _fr(self, line):
        return S.read_pose(tmp(line + '\n'))[0]

    def test_hand_axes_match_pose_hx(self):
        for line in (self.FAIL_GUARD, self.FAIL_HIT, self.PASS_GUARD, self.PASS_HIT):
            f = self._fr(line)
            for s in 'LR':
                hx, _ = S.hand_axes(f[s], s)
                self.assertLess(S._ang(hx, f[s]['hx']), 0.5)

    def test_knuckles_lead_and_palm_hidden(self):
        c = S.U
        fg, fh, pg, ph = (self._fr(x) for x in (self.FAIL_GUARD, self.FAIL_HIT, self.PASS_GUARD, self.PASS_HIT))
        self.assertGreater(S.hand_metrics(fh['R'], 'R')['xel'], c['xel_max'])          # rejected: hand stands up = reach
        self.assertLessEqual(S.hand_metrics(ph['R'], 'R')['xel'], c['xel_max'] - 5)     # fixed: knuckles lead
        self.assertGreater(S.hand_metrics(fg['L'], 'L')['pcam'], c['pcam_guard'])        # rejected guard shows the palm
        for s in 'LR':
            self.assertLess(S.hand_metrics(pg[s], s)['pcam'], c['pcam_guard'])
            self.assertLess(S.hand_metrics(ph[s], s)['pup'], c['pup_max'])

    def test_arms_cross(self):
        self.assertEqual(checks(tmp(pose_file(punch())))['U21'], 'PASS')
        # left fist driven across onto the right arm (badpunch class: forearm over the other hand mid-screen)
        fr = punch(opts=lambda k, u: {})
        fr = [(t, lerp(GL, (1.6, -1.6, 4.4), math.sin(math.pi * k / (len(fr) - 1.0))), rw, o) for k, (t, lw, rw, o) in enumerate(fr)]
        self.assertEqual(checks(tmp(pose_file(fr)))['U21'], 'FAIL')

    def test_cmd_unarmed_dir_skips_helpers(self):
        d = tempfile.mkdtemp()
        for n in ('jab', '_cal'):
            os.makedirs(os.path.join(d, n))
            open(os.path.join(d, n, 'pose.txt'), 'w').write(pose_file(punch()))
        self.assertEqual([os.path.basename(os.path.dirname(p)) for p in S.find_cands([d])], ['jab'])


class TestBladeNative(unittest.TestCase):
    @staticmethod
    def swing(endon_frames, snap=10.0, n=61):
        # blade turning about the view axis at a steady rate; the flat faces the camera except endon_frames frames at u .7
        F, P = [], []
        for k in range(n):
            u = k / (n - 1.0); a = math.radians(snap * k * 0.5)
            mf = (math.sin(a), math.cos(a), 0.0)
            edge = k >= 42 and k < 42 + endon_frames
            mid = (3.5 * mf[0], -2.0 + 3.5 * mf[1], 5.0)   # the flat edge-on to the view ray through the blade middle
            mu = mid if edge else (math.cos(a), -math.sin(a), 0.0)
            F.append(dict(t=u, swu=u)); P.append(dict(mp=(0.0, -2.0, 5.0), mf=mf, mu=mu, state='swing', wih=1))
        return F, P

    def test_one_frame_endon_passes(self):
        ok, txt = S.blade_native(*self.swing(1))
        self.assertTrue(ok, txt)

    def test_long_endon_fails(self):
        ok, txt = S.blade_native(*self.swing(6))
        self.assertFalse(ok, txt)
        self.assertIn('endon=', txt)


RULES = '''# comment
id\tclass\trule\tsource\towner\tchecks\tstatus\tnote
R1\tsword\tedge leads\tmem\tshay\tc.ok\tcovered\t
R2\tsword\tnum rule\tmem\tcoord\tc.num\tpartial\tsee
R3\tall\tfingers\tmem\tshay\t-\tout-of-reach\tno bones
'''


def checks_file():
    return tmp(json.dumps({'vars': {'X': 'x'}, 'checks': {
        'c.ok': {'cmd': 'echo "c {rec} {flag}"', 'line': '^c ', 'fail': 'BAD'},
        'c.num': {'cmd': 'echo "n val={v}"', 'line': '^n ', 'num': ['val', 'max', 10]},
        'c.err': {'cmd': 'echo nothing', 'line': '^zzz '}}}), '.json')


class TestRunner(unittest.TestCase):
    def test_rules_and_map(self):
        R = S.read_rules(tmp(RULES, '.tsv'))
        self.assertEqual([r['id'] for r in R], ['R1', 'R2', 'R3'])
        self.assertEqual(R[2]['checks'], [])
        a = type('A', (), dict(rules=tmp(RULES, '.tsv'), md=True))
        buf = io.StringIO()
        with redirect_stdout(buf):
            S.cmd_map(a)
        self.assertIn('| R3 fingers | all |', buf.getvalue())
        self.assertIn('out-of-reach=1', buf.getvalue())

    def test_run_check(self):
        vars_, C = S.read_checks(checks_file())
        self.assertEqual(S.run_check('c.ok', C['c.ok'], 'r.txt', {'flag': 'fine'}, vars_)[0], 'PASS')
        self.assertEqual(S.run_check('c.ok', C['c.ok'], 'r.txt', {'flag': 'BAD'}, vars_)[0], 'FAIL')
        self.assertEqual(S.run_check('c.num', C['c.num'], 'r', {'v': '12.5'}, vars_)[0], 'FAIL')
        self.assertEqual(S.run_check('c.num', C['c.num'], 'r', {'v': '3'}, vars_)[0], 'PASS')
        self.assertEqual(S.run_check('c.err', C['c.err'], 'r', {}, vars_)[0], 'ERROR')


class TestTaste(unittest.TestCase):
    def test_confusion(self):
        root = tempfile.mkdtemp()
        for n in ('a.txt', 'b.txt', 'c.txt', 'd.txt'):
            open(os.path.join(root, n), 'w').write('x')
        man = tmp('id\tpath\trule\tlabel\tsource\topts\tevidence\n'
                  't1\ta.txt\tR1\treject\tshay\tflag=BAD\tlab catches it\n'
                  't2\tb.txt\tR1\taccept\tshay\tflag=ok\tlab passes it\n'
                  't3\tc.txt\tR1\treject\tshay-sym\tflag=ok\tlab misses it\n'
                  't4\td.txt\tR2\taccept\tcoord\tv=20\tfalse alarm\n'
                  't5\td.txt\tR2\topen\tcoord\t\tnot scored\n', '.tsv')
        sys.argv = ['taste.py', 'score', man, '--rules', tmp(RULES, '.tsv'), '--checks', checks_file(), '--root', root]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = T.main()
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn('DISAGREE t3 R1 FN', out)
        self.assertIn('DISAGREE t4 R2 FP', out)
        self.assertIn('RESULT taste FAIL items=4 listed=1', out)
        # weighted agreement: (1 + 1) / (1 + 1 + 0.75 + 0.5)
        self.assertIn('agree=%.2f' % (2 / 3.25), out)


if __name__ == '__main__':
    unittest.main(verbosity=1)
