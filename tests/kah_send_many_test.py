#!/usr/bin/env python3
"""Offline test for client/kah.py send_many (several commands in one inbox write) against a fake harness thread that
behaves like Plugin.cpp ProcessInbox: takes one inbox per 250 ms poll (rename, read all lines, delete), answers each
line in the outbox. Run: python3 tests/kah_send_many_test.py   (exit 0 = pass)."""
import importlib.util, os, shutil, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('kah', os.path.join(HERE, '..', 'client', 'kah.py'))
kah = importlib.util.module_from_spec(spec); spec.loader.exec_module(kah)


class FakeHarness(threading.Thread):
    def __init__(self, d, poll=0.25, per_cmd=0.01):
        super().__init__(daemon=True); self.d, self.poll, self.per_cmd, self.stop, self.polls_used = d, poll, per_cmd, False, 0

    def run(self):
        inbox = os.path.join(self.d, 'inbox.txt')
        while not self.stop:
            time.sleep(self.poll)
            if not os.path.exists(inbox):
                continue
            os.replace(inbox, inbox + '.reading')
            lines = [x for x in open(inbox + '.reading').read().split('\n') if x]
            os.remove(inbox + '.reading'); self.polls_used += 1
            with open(os.path.join(self.d, 'outbox.txt'), 'a') as o:
                for ln in lines:
                    f = ln.split('\t'); time.sleep(self.per_cmd)
                    o.write('%s\tok\techo %s\n' % (f[0], ' '.join(f[1:])))


class SendMany(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); open(os.path.join(self.d, 'enabled.flag'), 'w').close()
        self.h = FakeHarness(self.d); self.h.start()

    def tearDown(self):
        self.h.stop = True; self.h.join(1); shutil.rmtree(self.d, True)

    def test_one_poll_for_all(self):
        t = time.time()
        R = kah.send_many(self.d, [('fp_keys', ['state']), ('chars', ['80']), ('messages', ['20'])], timeout=5)
        dt = time.time() - t
        self.assertEqual([r[1] for r in R], ['echo fp_keys state', 'echo chars 80', 'echo messages 20'])
        self.assertTrue(all(r[0] for r in R)); self.assertEqual(self.h.polls_used, 1); self.assertLess(dt, 0.6)

    def test_matches_send(self):
        ok, detail = kah.send(self.d, 'status', [])
        self.assertTrue(ok); self.assertEqual(detail, 'echo status')


if __name__ == '__main__':
    unittest.main(verbosity=1)
