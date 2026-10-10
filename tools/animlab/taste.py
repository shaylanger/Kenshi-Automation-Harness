#!/usr/bin/env python3
"""taste.py -- score the lab against human accept/reject decisions (the "taste set").

  taste.py score <taste.tsv> --rules <rules.tsv> --checks <checks.json> --root <dir> [--md out.md] [--only R1,R2] [--cache dir]

taste.tsv (TSV, '#' comments): id, path (relative to --root: recording, video or take dir), rule (id in rules.tsv), label
(accept | reject | open | superseded), source, opts ("k=v;k=v": template options for checks.json, plus `checks=a,b` to
judge only those checks of the rule, e.g. the part of the rule a rejection was about), evidence (where the decision is
recorded). Sources and weights: shay 1.0 (Shay's own verdict on this recording / video), shay-sym 0.75 (the recording shows a
symptom Shay rejected, from a build before its fix), shay-fix 0.75 (recording of the fix that went into a build Shay
accepted), coord 0.5 (coordinator review verdict). open / superseded rows are listed, never scored.

Per item the rule's checks run (spec.run_check); the rule FAILS when any judged check fails; a check that cannot judge the
item (ERROR: e.g. no swing) is n/a. Confusion per rule: TP = rejected and lab FAIL, TN = accepted and lab PASS,
FN = rejected but lab PASS (lab missed it), FP = accepted but lab FAIL (false alarm). Every FN / FP is a disagreement:
printed as `DISAGREE ...` (one Misses row each, class "taste"). Last line: RESULT taste PASS|FAIL items=.. agree=..
(weighted) disagree=<ids>. Exit 0 when nothing disagrees.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spec as S

WEIGHT = {'shay': 1.0, 'shay-sym': 0.75, 'shay-fix': 0.75, 'coord': 0.5}


def read_taste(path):
    T = []
    with open(path, encoding='utf-8') as fh:
        lines = fh.readlines()
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        c = (line.rstrip('\n').split('\t') + [''] * 7)[:7]
        if c[0] == 'id':
            continue
        opts = {}
        for kv in c[5].split(';'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                opts[k.strip()] = v.strip()
        T.append(dict(id=c[0], path=c[1], rule=c[2], label=c[3], source=c[4], opts=opts, evidence=c[6]))
    return T


def judge(item, rule, C, vars_, root, cache):
    sel = [x for x in item['opts'].get('checks', '').split(',') if x] or rule['checks']
    opts = {k: (v.replace('{root}', root)) for k, v in item['opts'].items() if k != 'checks'}
    path = os.path.join(root, item['path'])
    res = []
    for cid in sel:
        if cid not in C:
            res.append((cid, 'ERROR', 'no check %s in checks file' % cid))
            continue
        if not os.path.exists(path):
            res.append((cid, 'ERROR', 'missing %s' % path))
            continue
        v, ev = S.run_check(cid, C[cid], path, opts, vars_, cache)
        res.append((cid, v, ev))
    judged = [r for r in res if r[1] in ('PASS', 'FAIL')]
    if not judged:
        return 'n/a', res
    return ('FAIL' if any(r[1] == 'FAIL' for r in judged) else 'PASS'), res


def cell(lab, v):
    if lab == 'reject':
        return 'TP' if v == 'FAIL' else 'FN'
    return 'TN' if v == 'PASS' else 'FP'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('score'); p.add_argument('taste'); p.add_argument('--rules', required=True); p.add_argument('--checks', required=True)
    p.add_argument('--root', required=True); p.add_argument('--md'); p.add_argument('--only'); p.add_argument('--cache')
    a = ap.parse_args()
    if a.cmd != 'score':
        ap.print_help()
        return 2
    R = {r['id']: r for r in S.read_rules(a.rules)}
    vars_, C = S.read_checks(a.checks)
    items = read_taste(a.taste)
    only = set(a.only.split(',')) if a.only else None
    conf, cconf, dis, listed = {}, {}, [], []
    wsum = wagree = 0.0
    for it in items:
        if only and it['rule'] not in only:
            continue
        rule = R.get(it['rule'])
        if rule is None:
            print('%-4s %-5s ERROR unknown rule %s' % (it['id'], it['rule'], it['rule']))
            continue
        if it['label'] not in ('accept', 'reject'):
            listed.append(it)
            print('%-4s %-4s %-10s %-11s %-8s (not scored) %s' % (it['id'], it['rule'], it['label'], it['source'], '', it['path']))
            continue
        v, res = judge(it, rule, C, vars_, a.root, a.cache)
        ev = ' | '.join('%s %s: %s' % (c, x, e[:110]) for c, x, e in res)
        if v == 'n/a':
            print('%-4s %-4s %-6s %-8s lab n/a  %s :: %s' % (it['id'], it['rule'], it['label'], it['source'], it['path'], ev))
            continue
        k = cell(it['label'], v)
        w = WEIGHT.get(it['source'], 0.5)
        wsum += w
        wagree += w if k in ('TP', 'TN') else 0.0
        d = conf.setdefault(it['rule'], dict(TP=0, TN=0, FP=0, FN=0, n=0))
        d[k] += 1; d['n'] += 1
        for c, x, e in res:
            if x in ('PASS', 'FAIL'):
                cc = cconf.setdefault((it['rule'], c), dict(TP=0, TN=0, FP=0, FN=0))
                cc[cell(it['label'], x)] += 1
        print('%-4s %-4s %-6s %-8s lab %-4s %s  %s :: %s' % (it['id'], it['rule'], it['label'], it['source'], v, k, it['path'], ev))
        if k in ('FP', 'FN'):
            dis.append((it, k, v, ev))
    print()
    rows = []
    for rid in sorted(conf, key=lambda x: (x[0], int(''.join(ch for ch in x[1:] if ch.isdigit()) or 0))):
        d = conf[rid]
        rows.append((rid, R[rid]['rule'][:70], d['n'], d['TP'], d['TN'], d['FN'], d['FP']))
    print('%-4s %-70s %3s %3s %3s %3s %3s' % ('rule', 'text', 'n', 'TP', 'TN', 'FN', 'FP'))
    for r in rows:
        print('%-4s %-70s %3d %3d %3d %3d %3d' % r)
    print('per check (TP/TN/FN/FP): ' + ' '.join('%s:%s=%d/%d/%d/%d' % (r, c, d['TP'], d['TN'], d['FN'], d['FP']) for (r, c), d in sorted(cconf.items())))
    for it, k, v, ev in dis:
        print('DISAGREE %s %s %s %s label=%s(%s) lab=%s :: %s' % (it['id'], it['rule'], k, it['path'], it['label'], it['source'], v, ev[:300]))
    n = sum(d['n'] for d in conf.values())
    agree = wagree / wsum if wsum else float('nan')
    if a.md:
        with open(a.md, 'w', encoding='utf-8') as f:
            f.write('| rule | n | TP (rej+FAIL) | TN (acc+PASS) | FN (lab missed) | FP (false alarm) |\n|---|---|---|---|---|---|\n')
            for r in rows:
                f.write('| %s %s | %d | %d | %d | %d | %d |\n' % r)
            f.write('\nItems %d scored (+%d open/superseded listed), weighted agreement %.2f. Disagreements: %s\n' % (
                n, len(listed), agree, ', '.join('%s (%s %s %s)' % (it['id'], it['rule'], k, os.path.basename(it['path'])) for it, k, v, ev in dis) or 'none'))
    print('RESULT taste %s items=%d listed=%d agree=%.2f(weighted) disagree=%s' % ('PASS' if not dis else 'FAIL', n, len(listed), agree,
          ','.join('%s:%s:%s' % (it['id'], it['rule'], k) for it, k, v, ev in dis) or '-'))
    return 0 if not dis else 1


if __name__ == '__main__':
    sys.exit(main())
