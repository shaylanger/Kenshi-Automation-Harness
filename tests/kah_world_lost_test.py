#!/usr/bin/env python3
"""Offline test of the scenario runner's world-lost stop (item 122): once the
game was in the world, a step that finds it at the main menu ends the run
(the rest is FAIL "not run"), a long @sleep notices it early, and a scenario
that loads or starts a new game itself is not stopped.
Run: python tests/kah_world_lost_test.py"""
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


class FakeGame:
    """Answers like the harness; the squad 'dies' after <die_after> status calls."""

    def __init__(self, die_after=None):
        self.phase = 'world'
        self.die_after = die_after
        self.statuses = 0
        self.sent = []

    def send(self, d, cmd, args, timeout=None):
        self.sent.append(cmd)
        if cmd == 'status':
            self.statuses += 1
            if self.die_after is not None and self.statuses > self.die_after:
                self.phase = 'menu'
            return True, 'phase=%s save=x paused=0' % self.phase
        if cmd in ('load', 'newgame'):
            self.phase = 'menu'
            return True, 'started'
        if cmd == 'die':
            self.phase = 'menu'
            return True, 'ok'
        if self.phase != 'world':
            return False, 'no game loaded (phase=%s)' % self.phase
        return True, cmd + ' done'


def run(text, game):
    kah.send = game.send
    kah.WATCH_SLEEP_MIN = 0.05
    kah.WATCH_EVERY = 0.01
    fd, path = tempfile.mkstemp(suffix='.txt')
    os.close(fd)
    csv = path + '.csv'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    out = io.StringIO()
    with redirect_stdout(out):
        rc = kah.run_scenario('unused', path, csv)
    with open(csv, encoding='utf-8') as f:
        rows = f.read()
    os.remove(path)
    os.remove(csv)
    return rc, out.getvalue(), rows


check(kah.world_lost('no game loaded (phase=menu)') == 'menu', 'error reply at the menu: lost')
check(kah.world_lost('phase=menu save=x') == 'menu', 'status at the menu: lost')
check(kah.world_lost('phase=loading save=x') is None, 'loading: not lost')
check(kah.world_lost('no game loaded (phase=chargen)') is None, 'chargen: not lost')

# The squad dies mid-run: the step that sees the menu aborts, the rest is not run.
rc, out, rows = run('status ~ phase=world\nhunger Shay 300\ndie\nhunger Shay 300\n@sleep 0.2\nstatus ~ phase=world\n',
                    FakeGame())
check(rc == 1, 'world lost: run fails')
check('ABORT at line 4' in out and '2 steps not run' in out, 'one ABORT line names the step and the count')
check(rows.count('not run: the game left the world at line 4') == 2, 'remaining steps in the CSV as not run')
check(out.count('FAIL') == 1, 'only the aborting step is printed as FAIL')

# The squad dies during a long sleep: the sleep ends early and fails.
game = FakeGame(die_after=3)
rc, out, rows = run('@wait-world 5\n@sleep 30\nstatus ~ phase=world\n', game)
check(rc == 1 and 'game left the world during the sleep' in out, 'long sleep notices the menu')
check(game.statuses <= 6, 'and ends early (%d status calls, not 30 s)' % game.statuses)
check('ABORT at line 2' in out, 'aborted at the sleep')

# A scenario that loads itself: the menu after "load" is not a loss.
rc, out, rows = run('status ~ phase=world\nload kah-x\n! hunger Shay 300\n@sleep 0.1\nstatus\n', FakeGame())
check('ABORT' not in out and 'not run' not in rows, 'menu after a load: no abort')

# Never in the world (a menu scenario): no abort either.
game = FakeGame()
game.phase = 'menu'
rc, out, rows = run('hunger Shay 300\nstatus\n', game)
check('ABORT' not in out, 'never saw the world: no abort')

print('%d FAILED' % failed if failed else 'all world-lost tests passed')
sys.exit(1 if failed else 0)
