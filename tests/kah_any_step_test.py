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
print('%d failed' % failed)
sys.exit(1 if failed else 0)
