#!/usr/bin/env python3
"""Offline test of the scenario `@log <file> ~ <regex>` step (to-do 19): the
file may contain spaces (quoted or not) and Windows backslashes.
Run: python tests/kah_log_step_test.py"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import threading
import time

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


check(kah.log_step_path(r'@log C:\Kenshi Mods\x.log ~ hello') == r'C:\Kenshi Mods\x.log', 'unquoted path with a space')
check(kah.log_step_path(r'@log "C:\Kenshi Mods\x.log" ~ hello') == r'C:\Kenshi Mods\x.log', 'double-quoted path')
check(kah.log_step_path(r"@log 'C:\Kenshi Mods\x.log'") == r'C:\Kenshi Mods\x.log', 'single-quoted, regex already split off')
check(kah.log_step_path(r'  @log   C:\a\b.log   ~ x ~ y') == r'C:\a\b.log', 'plain path, first " ~ " ends it')

# End to end: a scenario whose log lives in a folder with spaces (and a quote).
root = tempfile.mkdtemp(prefix='kah log test ')
try:
    logdir = os.path.join(root, "Shay's mods dir")
    os.makedirs(logdir)
    log = os.path.join(logdir, 'game log.txt')
    with open(log, 'w') as f:
        f.write('old line: hello\n')
    scen = os.path.join(root, 'scen.txt')
    with open(scen, 'w', encoding='utf-8') as f:
        f.write('@sleep 1\n')
        f.write('@log %s ~ new line: hello\n' % log)
        f.write('@log "%s" ~ new line: hello\n' % log)
        f.write('@log %s ~ old line\n' % log)  # before the run: must not match

    def append():
        time.sleep(0.3)
        with open(log, 'a') as f:
            f.write('new line: hello\n')

    t = threading.Thread(target=append)
    t.start()
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        rc = kah.run_scenario(root, scen)
    finally:
        sys.stdout = old
    t.join()
    text = out.getvalue()
    check(text.count('PASS') == 3 and text.count('FAIL') == 1, 'run: unquoted + quoted match, old line not counted')
    check('2 failed' not in text and '3 passed, 1 failed' in text, 'run summary')
    if failed:
        print(text)

    # @log-wait: polls until a line written ~1.5 s later matches; times out on a line that never comes
    check(kah.log_step_path(r'@log-wait 5 C:\Kenshi Mods\x.log ~ hi') == r'C:\Kenshi Mods\x.log', 'log-wait path')
    scen2 = os.path.join(root, 'scen2.txt')
    with open(scen2, 'w', encoding='utf-8') as f:
        f.write('@log-wait 6 %s ~ late line\n' % log)
        f.write('@log-wait 1 "%s" ~ never written\n' % log)

    def append_late():
        time.sleep(1.5)
        with open(log, 'a') as f:
            f.write('late line\n')

    t = threading.Thread(target=append_late)
    t.start()
    out = io.StringIO()
    sys.stdout = out
    try:
        rc = kah.run_scenario(root, scen2)
    finally:
        sys.stdout = old
    t.join()
    text = out.getvalue()
    check('1 passed, 1 failed' in text, 'log-wait: late line matched, missing line timed out')
    if '1 passed, 1 failed' not in text:
        print(text)
finally:
    shutil.rmtree(root, ignore_errors=True)

print('%d FAILED' % failed if failed else 'all log step tests passed')
sys.exit(1 if failed else 0)
