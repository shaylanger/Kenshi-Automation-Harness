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


def arm(sh, wr, hx_bend=0.0, up=(0, 1, 0)):
    """straight-ish arm: elbow midway and dropped 1.5 dm, fist 0.8 dm past the wrist along the forearm; hand X along the
    forearm turned by hx_bend deg (wrist bend) about the up axis."""
    el = (sh[0] + (wr[0] - sh[0]) * .5, sh[1] + (wr[1] - sh[1]) * .5 - 1.5, sh[2] + (wr[2] - sh[2]) * .5)
    fa = tuple(wr[i] - el[i] for i in range(3)); n = math.sqrt(sum(x * x for x in fa)); fa = tuple(x / n for x in fa)
    b = math.radians(hx_bend)
    hx = (fa[0] * math.cos(b) + fa[2] * math.sin(b), fa[1], -fa[0] * math.sin(b) + fa[2] * math.cos(b))
    pp = tuple(wr[i] + fa[i] * 0.8 for i in range(3))
    return [sh, el, wr, hx, pp, fa, up]


def pose_file(frames):
    """frames: list of (t, Lwr, Rwr, opts) -> metricslab pose.txt text."""
    out = ['# synthetic pose']
    for i, (t, lw, rw, o) in enumerate(frames):
        L = arm((-2.0, -2.0, -0.5), lw, o.get('bL', 0.0), o.get('upL', (0, 1, 0)))
        R = arm((2.0, -2.0, -0.5), rw, o.get('bR', 0.0), o.get('upR', (0, 1, 0)))
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
        bad = [r for r in res if r[1] != 'PASS']
        self.assertFalse(bad, bad)
        self.assertTrue(any(r[0] == 'U4' and 'strike R' in r[2] for r in res))

    def test_fist_above_eye(self):
        hi = (0.3, 1.5, 6.0)
        fr = [(-0.2, GL, GR, {})] + [(u / 59.0, GL, lerp(GR, hi, math.sin(math.pi * u / 59.0)), {}) for u in range(60)]
        res = {r[0]: r for r in S.unarmed_checks(S.read_pose(tmp(pose_file(fr))))}
        self.assertEqual(res['U5'][1], 'FAIL', res['U5'])
        self.assertEqual(res['U6'][1], 'FAIL', res['U6'])

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

    def test_cmd_unarmed_dir_skips_helpers(self):
        d = tempfile.mkdtemp()
        for n in ('jab', '_cal'):
            os.makedirs(os.path.join(d, n))
            open(os.path.join(d, n, 'pose.txt'), 'w').write(pose_file(punch()))
        self.assertEqual([os.path.basename(os.path.dirname(p)) for p in S.find_cands([d])], ['jab'])


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
