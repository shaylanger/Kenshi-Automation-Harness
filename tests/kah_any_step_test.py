#!/usr/bin/env python3
"""Offline test of the scenario `@any <step> ~ re || <step> ~ re` step: alternatives run in order until one
passes (pg-51: a crafted item is either still in the bench output or already hauled by the worker).
Run: python tests/kah_any_step_test.py"""
import importlib.util
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('kah', os.path.join(HERE, '..', 'client', 'kah.py'))
kah = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kah)

failed = 0


def check(cond, what):
    global failed
    print('%s %s' % ('PASS' if cond else 'FAIL', what))
    if not cond:
        failed += 1


REPLIES = {'take': (False, 'bench has no item matching: Sickle'), 'info': (True, 'Sickle key=pgp1 equipped=1'),
           'echo': (True, 'hello world')}
sent = []


def send(d, cmd, args, timeout=None):
    sent.append(cmd)
    return REPLIES.get(cmd, (True, cmd + ' done'))


def run(text):
    kah.send = send
    del sent[:]
    fd, path = tempfile.mkstemp(suffix='.txt')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    out = io.StringIO()
    with redirect_stdout(out):
        rc = kah.run_scenario('unused', path, None)
    os.remove(path)
    return rc, out.getvalue()


rc, out = run(r'@any take A "Weapon" "Sickle" ~ to A: || info A "Sickle" ~ key=pgp\S+' + '\n')
check(rc == 0 and 'PASS' in out and 'alt 2:' in out and sent == ['take', 'info'], 'second alternative passes')
rc, out = run('@any echo hi ~ hello || info A ~ key\n')
check(rc == 0 and 'alt 1:' in out and sent == ['echo'], 'first alternative passes, the rest is not sent')
rc, out = run('@any take A x || info A ~ nomatch\n')
check(rc == 1 and 'no alternative matched' in out and 'alt 1:' in out and 'alt 2:' in out, 'none passes: FAIL lists every reply')
rc, out = run('@set V echo x ~ (world)\n@any info ${V} ~ equipped=1\n')
check(rc == 0 and out.count('PASS') == 2, 'variables are substituted, a single alternative works')
# m31: an @log / @log-wait alternative (wait for progress, else re-issue the order); only lines added since the run
# started count, and its offset is noted before the run like a plain @log step
fd, logp = tempfile.mkstemp(suffix='.log')
os.close(fd)
with open(logp, 'w') as f:
    f.write('chained=1->0 old line\n')
rc, out = run('@any @log-wait 1 %s ~ chained=1->0 || info A ~ key\n' % logp)
check(rc == 0 and 'alt 2:' in out and sent == ['info'], 'log alternative: an old line does not count, the order alternative runs')
with open(logp, 'a') as f:
    f.write('x\n')
appender = lambda: open(logp, 'a').write('slave state chained=1->0 new\n')
import threading
threading.Timer(0.5, appender).start()
rc, out = run('@any @log-wait 5 %s ~ chained=1->0 || info A ~ key\n' % logp)
check(rc == 0 and 'alt 1: matched' in out and sent == [], 'log alternative: a new line passes, the rest is not sent')
rc, out = run('@any @log %s ~ nomatch || take A x\n' % logp)
check(rc == 1 and 'no new line matching' in out, 'log alternative: none passes lists the log miss')
os.remove(logp)
print('%d failed' % failed)
sys.exit(1 if failed else 0)
