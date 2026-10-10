#!/usr/bin/env python3
"""Offline tests for tools/animlab/takecheck.py (labelled video take vs sampled game state). Synthetic data only.
Run: python3 tests/animlab/test_takecheck.py   (exit 0 = all pass)."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
import takecheck as T  # noqa: E402

RULES = '''set grace 0.5
set maxgap 1.0
set endslack 1.0
cover ui,near
claim "(?i)aim \\(RMB\\)" ui=aiming
pre "(?i)aim \\(RMB\\)" loaded>=1
claim "(?i)ready back" ui=ready
forbid near>0
forbid msg~(?i)is_attacking
sparse msg
'''


def run(labels, ev, vlen=None, rules=RULES):
    d = tempfile.mkdtemp()
    p = lambda n, s: (open(os.path.join(d, n), 'w').write(s), os.path.join(d, n))[1]
    L = T.read_labels(p('l.txt', labels)); S = T.read_ev([p('e.txt', ev)]); R, cfg = T.read_rules(p('r.txt', rules))
    return T.check(L, S, R, cfg, vlen)


def samples(t0, t1, fmt, dt=0.25):
    out, t = [], t0
    while t <= t1 + 1e-9:
        out.append('%.2f %s' % (t, fmt(t))); t += dt
    return '\n'.join(out) + '\n'


LAB = '0.0 start\n2.0 Crossbow aim (RMB)\n6.0 W: ready back\n9.0 end\n'


def good(t):
    return 'ui=%s loaded=1 near=0 msgs=0' % ('aiming' if 2.3 <= t < 6.0 else 'ready')


class TakeCheck(unittest.TestCase):
    def test_good_take_passes(self):
        ok, lines, fails = run(LAB, samples(0, 9, good), vlen=9.4)
        self.assertTrue(ok, lines)

    def test_aim_label_on_a_reload_fails(self):   # zoom-sweep miss: "Crossbow aim (RMB)" showed a reload, crossbow unloaded
        ev = samples(0, 9, lambda t: good(t).replace('aiming', 'reloading').replace('loaded=1', 'loaded=0'))
        ok, lines, fails = run(LAB, ev, vlen=9.4)
        self.assertFalse(ok); self.assertIn('claim:Crossbow aim (RMB)', fails); self.assertIn('pre:Crossbow aim (RMB)', fails)

    def test_claim_must_hold_the_whole_segment(self):   # turret-fp miss: "READY back" true for ~1 s only
        ev = samples(0, 9, lambda t: good(t).replace('ui=ready', 'ui=holstered') if t >= 7.0 else good(t))
        ok, lines, fails = run(LAB, ev, vlen=9.4)
        self.assertFalse(ok); self.assertTrue(any('W: ready back' in x and '7.00' in x for x in lines), lines)

    def test_sparse_evidence_is_unverified(self):   # one sample per label proves nothing about the rest of the segment
        ev = '0.1 ui=ready near=0\n2.6 ui=aiming loaded=1 near=0\n6.6 ui=ready near=0\n'
        ok, lines, fails = run(LAB, ev, vlen=9.0)
        self.assertFalse(ok); self.assertTrue(any('unverified' in x for x in lines), lines); self.assertIn('cover:ui', fails)

    def test_bystander_and_combat_message_fail(self):   # turret-fp: NPCs walk into frame, "X is attacking!"
        ev = samples(0, 9, lambda t: good(t).replace('near=0', 'near=2') if 7 <= t <= 8 else good(t))
        ev += '4.10 msgs=1 msg=Tassilo_is_attacking!\n'
        ok, lines, fails = run(LAB, ev, vlen=9.4)
        self.assertFalse(ok); self.assertIn('forbid:near>0', fails); self.assertIn('forbid:msg~(?i)is_attacking', fails)

    def test_unsampled_forbid_key_fails(self):
        ok, lines, fails = run(LAB, samples(0, 9, lambda t: good(t).replace(' near=0', '')), vlen=9.4)
        self.assertFalse(ok); self.assertIn('forbid-unsampled:near', fails)

    def test_video_past_end_label_fails(self):   # turret-fp refilm: video ~7 s past `end`
        ok, lines, fails = run(LAB, samples(0, 9, good), vlen=16.5)
        self.assertFalse(ok); self.assertEqual(fails, ['video-length'])
        ok, lines, fails = run(LAB.replace('9.0 end\n', ''), samples(0, 9, good))
        self.assertIn('no-end-label', fails)

    def test_cond_ops(self):
        c = T.parse_cond
        self.assertTrue(T.cond_ok(c('a=x|y'), 'y')); self.assertFalse(T.cond_ok(c('a!=x|y'), 'y'))
        self.assertTrue(T.cond_ok(c('n>=1'), '1.0')); self.assertFalse(T.cond_ok(c('n>=1'), 'none'))
        self.assertTrue(T.cond_ok(c('h~^rel'), 'reload')); self.assertTrue(T.cond_ok(c('h!~^rel'), 'loaded'))
        self.assertTrue(T.cond_ok(c('n=1'), '1.00'))


    def test_animlive(self):   # miss 2026-10-10 fb_lives 0: free block progress never live while the body showed the pose
        log = """[10:30:55.380] [controls] PT34 free block start tech=000000014b9b27b0 dir=1 f=50.0 org=0
[10:30:57.140] [controls] PT34 free block end: 1760 ms p=1.010 pmin=9.000 live=0
[10:31:00.000] [controls] free swing end: 1359 ms steps=95 pmin=0.010 live=1 why=done
[10:31:05.000] [controls] PT34 free block start tech=000000014b9b1500 dir=1 f=50.0 org=0
[10:31:06.000] [controls] PT34 free block end: 900 ms p=1.010 pmin=0.050 live=1
"""
        with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False) as f:
            f.write(log)
        try:
            ok, t = T.animlive_check(f.name); self.assertFalse(ok, t); self.assertIn('never_live=1:BAD', t); self.assertIn('tech=9b27b0', t)
            ok, t = T.animlive_check(f.name, T.wall('10:30:59'), T.wall('10:31:10')); self.assertTrue(ok, t); self.assertIn('ends=2', t)
        finally:
            os.unlink(f.name)


class Sync(unittest.TestCase):   # T6 label lag 2026-10-10: labels led the screen by 0.4-1.3 s, not constant (turret-fp)
    LAB = [(0.0, 'start'), (2.0, 'aim'), (6.0, 'ready back'), (9.0, 'end')]

    def ev(self, sends):
        return {'sync': [(t, str(n)) for n, t in enumerate(sends)]}

    def test_constant_offset_passes(self):
        ok, t, synced = T.sync_check(self.LAB, self.ev([0.0, 2.0, 6.0, 9.0]), [0.80, 2.85, 6.78, 9.83])
        self.assertTrue(ok, t); self.assertIn('t0_offset=0.80', t)
        self.assertEqual([round(x, 2) for x, _ in synced], [0.80, 2.85, 6.78, 9.83])

    def test_late_label_fails(self):   # one state reached the screen 0.4 s later than the rest
        ok, t, _ = T.sync_check(self.LAB, self.ev([0.0, 2.0, 6.0, 9.0]), [0.80, 3.20, 6.80, 9.80])
        self.assertFalse(ok); self.assertIn('lag>0.15s at n=1(+0.40)', t)

    def test_missing_flash_and_unmarked_label_fail(self):
        ok, t, _ = T.sync_check(self.LAB, self.ev([0.0, 2.0, 6.0, 9.0]), [0.80, 2.80, 9.80])
        self.assertFalse(ok); self.assertIn('no flash for n=2', t); self.assertIn('label without flash: ready back', t)
        ok, t, _ = T.sync_check(self.LAB, self.ev([0.0, 2.0, 9.0]), [0.80, 2.80, 9.80])
        self.assertFalse(ok); self.assertIn('label without flash: ready back', t)

    def test_stray_flash_fails(self):
        ok, t, _ = T.sync_check(self.LAB, self.ev([0.0, 2.0, 6.0, 9.0]), [0.80, 2.80, 4.10, 6.80, 9.80])
        self.assertFalse(ok); self.assertIn('flash without take_mark at 4.10', t)

    def test_no_take_mark_skips_unless_required(self):
        ok, t, _ = T.sync_check(self.LAB, {}, [])
        self.assertTrue(ok); self.assertTrue(t.startswith('SKIP'))
        ok, t, _ = T.sync_check(self.LAB, {'sync_off': [(0.0, 'harness-without-sync_flash')]}, [], require=True)
        self.assertFalse(ok); self.assertIn('take_mark off', t)
        ok, t, _ = T.sync_check(self.LAB, self.ev([0.0, 2.0]), [])
        self.assertFalse(ok); self.assertIn('flashes=0', t)


if __name__ == '__main__':
    unittest.main(verbosity=1)
