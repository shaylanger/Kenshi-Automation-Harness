#!/usr/bin/env python3
"""Offline tests for tools/animlab/labcache.py (result cache) and optim.py (climb search). Linux/WSL (fcntl).
Run: python3 tests/animlab/test_labcache.py   (exit 0 = all pass)."""
import os, shutil, stat, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
TMP = tempfile.mkdtemp(prefix='labcache-test-')
os.environ['ANIMLAB_CACHE_DIR'] = os.path.join(TMP, 'cache')
os.environ['LABNICE_EXEMPT'] = '1'
import labcache as LC  # noqa: E402
import optim  # noqa: E402

# fake adapter: counts its runs, writes out = rec content + args, and a sidecar
ADP = os.path.join(TMP, 'adp.sh')


def adapter(body):
    open(ADP, 'w').write('#!/bin/bash\necho run >> %s/count\nout=$2; { cat "$1"; shift 2; echo "%s $@"; } > "$out"; echo side > "$out.bolt"; echo calib 1,2\n' % (TMP, body))
    os.chmod(ADP, os.stat(ADP).st_mode | stat.S_IEXEC)


def runs():
    p = os.path.join(TMP, 'count')
    return sum(1 for _ in open(p)) if os.path.exists(p) else 0


class Cache(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(os.path.join(TMP, 'cache'), ignore_errors=True)
        if os.path.exists(os.path.join(TMP, 'count')):
            os.remove(os.path.join(TMP, 'count'))
        os.environ['ANIMLAB_CACHE'] = '1'
        self.rec = os.path.join(TMP, 'rec.txt')
        open(self.rec, 'w').write('frame 1\n')
        adapter('v1')

    def test_hit_restores_outputs_and_sidecars_under_a_new_name(self):
        o1, o2 = os.path.join(TMP, 'a.txt'), os.path.join(TMP, 'sub', 'b.txt')
        rc, so, _ = LC.replay([ADP], self.rec, o1, ['--quiet'])
        self.assertEqual((rc, runs()), (0, 1))
        rc2, so2, _ = LC.replay([ADP], self.rec, o2, ['--quiet'])
        self.assertEqual((rc2, so2, runs()), (0, so, 1))
        self.assertEqual(open(o1).read(), open(o2).read())
        self.assertTrue(os.path.exists(o2 + '.bolt'))

    def test_key_follows_content(self):
        o = os.path.join(TMP, 'c.txt')
        LC.replay([ADP], self.rec, o, [])
        open(self.rec, 'w').write('frame 2\n')      # same name, new content -> recompute
        LC.replay([ADP], self.rec, o, [])
        self.assertEqual(runs(), 2)
        adapter('v2')                                 # new adapter binary -> recompute
        LC.replay([ADP], self.rec, o, [])
        self.assertEqual(runs(), 3)
        LC.replay([ADP], self.rec, o, ['--set', 'x=1'])   # new args -> recompute
        self.assertEqual(runs(), 4)
        self.assertIn('v2 --set x=1', open(o).read())

    def test_off_and_verify(self):
        o = os.path.join(TMP, 'd.txt')
        os.environ['ANIMLAB_CACHE'] = '0'
        LC.replay([ADP], self.rec, o, [])
        LC.replay([ADP], self.rec, o, [])
        self.assertEqual(runs(), 2)
        os.environ['ANIMLAB_CACHE'] = '1'
        LC.replay([ADP], self.rec, o, [])
        os.environ['ANIMLAB_CACHE'] = 'verify'
        LC.replay([ADP], self.rec, o, [])             # recomputes, matches: no mismatch line
        self.assertEqual(runs(), 4)
        self.assertFalse(os.path.exists(os.path.join(TMP, 'cache', 'verify-mismatch.log')))

    def test_memo_call(self):
        n = []

        def fn():
            n.append(1)
            print('arc PASS 0.9')
            return 1
        self.assertEqual(LC.memo_call('check', ['k'], fn), 1)
        self.assertEqual(LC.memo_call('check', ['k'], fn), 1)
        self.assertEqual(len(n), 1)

    def test_prune_lru(self):
        o = os.path.join(TMP, 'e.txt')
        for i in range(5):
            LC.replay([ADP], self.rec, o, ['--i', str(i)])
        LC.MAX_MB = 1e-6
        LC.prune(quiet=True)
        LC.MAX_MB = 6000
        self.assertEqual(len(LC.entries()), 0)


class Optim(unittest.TestCase):
    def test_methods_reach_target_with_few_evals(self):
        f = lambda x: sum((v - 0.3 * i) ** 2 for i, v in enumerate(x))
        for m in ('cma', 'nm', 'cf'):
            r = optim.minimize(f, [0] * 4, [0.5] * 4, method=m, target=1e-2, maxevals=1000)
            self.assertEqual(r.reason, 'target', m)
            self.assertLess(r.evals, 300, m)

    def test_maximize_and_batch(self):
        calls = []

        def batch(xs):
            calls.append(len(xs))
            return [-(x[0] - 2) ** 2 for x in xs]
        r = optim.minimize(None, [0], [1], method='cf', batch=batch, maximize=True, tol=1e-3)
        self.assertAlmostEqual(r.x[0], 2, places=2)
        self.assertGreater(max(calls), 1)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
