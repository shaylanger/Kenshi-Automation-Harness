#!/usr/bin/env python3
"""Offline test of the inbox protocol (KAH 9): several kah.py clients send at
once while a fake harness consumes inbox.txt the way Plugin.cpp does
(rename to inbox.txt.reading, read, delete, append replies). Every command
must be answered exactly once. Run: python tests/kah_inbox_test.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KAH = os.path.join(HERE, '..', 'client', 'kah.py')
CLIENTS, PER_CLIENT = 4, 15


def fake_harness(d, stop, seen):
    inbox, taken = os.path.join(d, 'inbox.txt'), os.path.join(d, 'inbox.txt.reading')
    outbox = os.path.join(d, 'outbox.txt')
    while not stop.is_set():
        if os.path.exists(inbox):
            try:
                os.replace(inbox, taken)
            except OSError:
                time.sleep(0.01)
                continue
            with open(taken, encoding='utf-8') as f:
                lines = [l.rstrip('\n') for l in f if l.strip()]
            os.remove(taken)
            with open(outbox, 'a', encoding='utf-8', newline='\n') as f:
                for line in lines:
                    fields = line.split('\t')
                    seen.append(fields[0])
                    f.write('%s\tok\techo %s\n' % (fields[0], ' '.join(fields[1:])))
        time.sleep(0.02)


def client(d, n, results):
    for i in range(PER_CLIENT):
        r = subprocess.run([sys.executable, KAH, '--dir', d, 'status', 'c%d' % n, str(i)],
                           capture_output=True, text=True)
        results.append((n, i, r.returncode, r.stdout.strip() + r.stderr.strip()))


def main():
    d = tempfile.mkdtemp(prefix='kah_inbox_')
    failed = 0
    try:
        open(os.path.join(d, 'enabled.flag'), 'w').close()
        stop, seen, results = threading.Event(), [], []
        h = threading.Thread(target=fake_harness, args=(d, stop, seen))
        h.start()
        threads = [threading.Thread(target=client, args=(d, n, results)) for n in range(CLIENTS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stop.set()
        h.join()
        bad = [r for r in results if r[2] != 0 or ('echo status c%d %d' % (r[0], r[1])) not in r[3]]
        for r in bad[:5]:
            print('FAIL client %d cmd %d: exit %d %s' % r)
        total = CLIENTS * PER_CLIENT
        ok = not bad and len(results) == total
        print('%s every concurrent command answered (%d/%d)' % ('PASS' if ok else 'FAIL',
                                                                 len(results) - len(bad), total))
        failed += not ok
        ok = len(seen) == total and len(set(seen)) == total
        print('%s each command reached the harness once, ids unique (%d seen, %d unique)' %
              ('PASS' if ok else 'FAIL', len(seen), len(set(seen))))
        failed += not ok
        left = [n for n in os.listdir(d) if n.startswith('inbox')]
        print('%s no inbox, lock or temp files left (%s)' % ('PASS' if not left else 'FAIL', left))
        failed += bool(left)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print('%d FAILED' % failed if failed else 'all inbox protocol tests passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
