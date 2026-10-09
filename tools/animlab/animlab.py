#!/usr/bin/env python3
"""animlab.py -- offline animation lab, phase 1 (REPLAY): replay recorded viewmodel frames through a solver adapter,
report the in-game metrics per pose state, compare variants side by side. Docs: docs/animlab/USAGE.md.

  animlab.py metrics <rec>                                   per-state metrics of one recording (game or replay)
  animlab.py compare <real> <sim> [--skip N]                 per-frame replay error + metrics side by side
  animlab.py replay  <rec> --adapter CMD [--set k=v]... [-o out.txt] [--skip N]
  animlab.py sweep   <rec> --adapter CMD [--variant 'name[@CMD]: adapter args']... [--metrics a,b] [-j N] [--keep DIR]
  animlab.py gate    <rec>... --adapter CMD [--tol tol.json] [--skip N]

An adapter is any command `CMD <rec.txt> <out.txt> [args]` that replays the recording through a solver and writes
its own recording in the same format; it may print `calib ...` (passed on to the variants as --calib so all
variants share one skeleton calibration).
"""
import argparse, json, os, shlex, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recfmt
from recfmt import sub, ln, ang
import metrics as M

DEFAULT_TOL = dict(   # faithfulness gate (docs/animlab/USAGE.md "Faithfulness gate")
    grip_p95=0.25, elbow_p95=0.35, wrist_p95=0.25, blade_p95=3.0, edge_p95=4.0, wb_p95=4.0,
    m_wb_p95=4.0, m_elb_h_max=0.4, m_st_max=0.08, m_edge_mean=0.06, m_jit_p95=2.0, min_frames=100)


def run_adapter(cmd, rec, out, args):
    full = shlex.split(cmd) + [rec, out] + list(args)
    p = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    calib = None
    for l in p.stdout.splitlines():
        if l.startswith('calib '):
            calib = l.split()[1]
    if p.returncode != 0 or not os.path.exists(out):
        raise RuntimeError('adapter failed (%d): %s\n%s' % (p.returncode, ' '.join(full), p.stderr[-2000:]))
    return calib


def print_table(rows, cols, title=None):
    if title:
        print(title)
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c)) for i, c in enumerate(cols)]
    print('  '.join(str(c).rjust(w[i]) if i else str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in rows:
        print('  '.join(str(x).rjust(w[i]) if i else str(x).ljust(w[i]) for i, x in enumerate(r)))


def states_of(*tables):
    seen = set().union(*[set(t) for t in tables])
    return [s for s in M.STATE_ORDER if s in seen]


def cmd_metrics(a):
    T = M.state_table(M.frame_metrics(recfmt.parse(a.rec)), a.skip)
    print_table([[s] + [M.fmt(T[s][c]) for c in M.METRIC_COLS] for s in states_of(T)], ('state',) + M.METRIC_COLS)


def frame_errors(Pr, Ps, Fr, skip):
    """per-frame errors replay vs game on frames where both show the full viewmodel."""
    E = {}
    for i in range(skip, min(len(Pr), len(Ps))):
        r, s = Pr[i], Ps[i]
        if r['state'] in ('off', 'draw', 'lower') or s['state'] in ('off', 'draw', 'lower') or not r['wih']:
            continue
        e = E.setdefault(r['state'], dict(grip=[], elbow=[], wrist=[], blade=[], edge=[], wb=[], match=0, n=0))
        e['n'] += 1
        e['match'] += r['state'] == s['state']
        e['grip'].append(ln(sub(r['mp'], s['mp'])))
        e['elbow'].append(ln(sub(r['J'][4], s['J'][4])))
        e['wrist'].append(ln(sub(r['J'][5], s['J'][5])))
        e['blade'].append(ang(r['mf'], s['mf']))
        e['edge'].append(ang(r['mu'], s['mu']))
        if r['wb'] is not None and s['wb'] is not None:
            e['wb'].append(abs(r['wb'] - s['wb']))
    return E


def compare(real, sim, skip=0, tol=None, quiet=False):
    Rr, Rs = recfmt.parse(real), recfmt.parse(sim)
    Pr, Ps = M.frame_metrics(Rr), M.frame_metrics(Rs)
    E = frame_errors(Pr, Ps, Rr.frames, skip)
    Tr, Ts = M.state_table(Pr, skip), M.state_table(Ps, skip)
    tol = tol or DEFAULT_TOL
    fails, rows = [], []
    for s in states_of(E):
        e = E[s]
        row = [s, e['n'], '%.0f%%' % (100.0 * e['match'] / max(1, e['n']))]
        for k in ('grip', 'elbow', 'wrist', 'blade', 'edge', 'wb'):
            v = M.pct(e[k], .95)
            row.append(M.fmt(v))
            if e['n'] >= 10 and v == v and v > tol[k + '_p95']:
                fails.append('%s %s_p95=%.2f>%.2f' % (s, k, v, tol[k + '_p95']))
        row.append(M.fmt(max(e['elbow'])) if e['elbow'] else '-')
        rows.append(row)
    if not quiet:
        print_table(rows, ('state', 'n', 'same', 'grip95', 'elb95', 'wr95', 'blade95', 'edge95', 'wb95', 'elb_max'),
                    'per-frame replay error (dm / deg, p95) vs the game:')
    mrows = []
    for s in states_of(Tr, Ts):
        r, m = Tr.get(s), Ts.get(s)
        cells = [s]
        for c in ('wb_p95', 'elb_h_max', 'st_max', 'edge_mean', 'jit_p95'):
            rv = r[c] if r else float('nan')
            sv = m[c] if m else float('nan')
            cells.append('%s/%s' % (M.fmt(rv), M.fmt(sv)))
            lim = tol.get('m_' + c)
            if lim is not None and r and m and r['n'] >= 10 and rv == rv and sv == sv and abs(rv - sv) > lim:
                fails.append('%s %s game=%.2f replay=%.2f (|d|>%.2f)' % (s, c, rv, sv, lim))
        mrows.append(cells)
    if not quiet:
        print_table(mrows, ('state', 'wb_p95', 'elb_h_max', 'st_max', 'edge_mean', 'jit_p95'), 'metrics game/replay:')
    nfull = sum(e['n'] for e in E.values())
    if nfull < tol['min_frames']:
        fails.append('only %d comparable frames (< %d)' % (nfull, tol['min_frames']))
    return fails, nfull


def cmd_compare(a):
    fails, n = compare(a.real, a.sim, a.skip)
    print('GATE %s frames=%d %s' % ('PASS' if not fails else 'FAIL', n, '; '.join(fails[:8])))


def adapter_args(a):
    x = []
    for s in a.set or []:
        x += ['--set', s]
    return x


def cmd_replay(a):
    out = a.o or os.path.join(tempfile.mkdtemp(prefix='animlab-'), 'replay.txt')
    calib = run_adapter(a.adapter, a.rec, out, adapter_args(a) + shlex.split(a.args or ''))
    print('replay -> %s (calib %s)' % (out, calib))
    fails, n = compare(a.rec, out, a.skip)
    print('GATE %s frames=%d %s' % ('PASS' if not fails else 'FAIL', n, '; '.join(fails[:8])))


def parse_variant(v, default_cmd):
    name, _, rest = v.partition(':')
    cmd = default_cmd
    if '@' in name:
        name, cmd = name.split('@', 1)
    return name.strip(), cmd, shlex.split(rest)


def cmd_sweep(a):
    keep = a.keep or tempfile.mkdtemp(prefix='animlab-sweep-')
    os.makedirs(keep, exist_ok=True)
    base_out = os.path.join(keep, 'base.txt')
    calib = run_adapter(a.adapter, a.rec, base_out, shlex.split(a.args or ''))
    V = [parse_variant(v, a.adapter) for v in a.variant or []]
    cal = ['--calib', calib] if calib else []

    def one(v):
        name, cmd, args = v
        out = os.path.join(keep, 'v-%s.txt' % name)
        run_adapter(cmd, a.rec, out, cal + args)
        return name, out
    with ThreadPoolExecutor(max_workers=a.j) as ex:
        res = list(ex.map(one, V))
    names = ['game', 'base'] + [n for n, _ in res]
    tabs = [M.state_table(M.frame_metrics(recfmt.parse(p)), a.skip) for p in [a.rec, base_out] + [p for _, p in res]]
    cols = a.metrics.split(',')
    rows = []
    for s in states_of(*tabs):
        for c in cols:
            rows.append(['%s %s' % (s, c)] + [M.fmt(t[s][c]) if s in t else '-' for t in tabs])
    print_table(rows, ['state metric'] + names, 'sweep %s (outputs in %s):' % (os.path.basename(a.rec), keep))


def cmd_gate(a):
    tol = dict(DEFAULT_TOL)
    if a.tol:
        tol.update(json.load(open(a.tol)))
    allok = True
    for rec in a.rec:
        out = os.path.join(tempfile.mkdtemp(prefix='animlab-gate-'), 'replay.txt')
        run_adapter(a.adapter, rec, out, shlex.split(a.args or ''))
        print('== %s' % rec)
        fails, n = compare(rec, out, a.skip, tol, quiet=a.quiet)
        print('GATE %s %s frames=%d %s' % ('PASS' if not fails else 'FAIL', os.path.basename(rec), n, '; '.join(fails[:8])))
        allok = allok and not fails
    return 0 if allok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('metrics'); p.add_argument('rec'); p.add_argument('--skip', type=int, default=0)
    p = sp.add_parser('compare'); p.add_argument('real'); p.add_argument('sim'); p.add_argument('--skip', type=int, default=0)
    for name in ('replay', 'sweep', 'gate'):
        p = sp.add_parser(name)
        p.add_argument('rec', nargs='+' if name == 'gate' else None)
        p.add_argument('--adapter', required=True, help='adapter command (quoted), e.g. /root/animlab-build/kfpvm_replay')
        p.add_argument('--args', help='extra adapter args for every run (quoted)')
        p.add_argument('--skip', type=int, default=0, help='leave the first N frames out of the comparison')
        if name == 'replay':
            p.add_argument('--set', action='append', help='key=value (fp_vm set)'); p.add_argument('-o')
        if name == 'sweep':
            p.add_argument('--variant', action='append', help="'name[@adapter cmd]: adapter args'")
            p.add_argument('--metrics', default='wb_p95,wb_max,elb_h_max,st_max,edge_mean,jit_p95')
            p.add_argument('-j', type=int, default=os.cpu_count() or 4); p.add_argument('--keep')
        if name == 'gate':
            p.add_argument('--tol'); p.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help(); return 2
    return {'metrics': cmd_metrics, 'compare': cmd_compare, 'replay': cmd_replay, 'sweep': cmd_sweep, 'gate': cmd_gate}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
