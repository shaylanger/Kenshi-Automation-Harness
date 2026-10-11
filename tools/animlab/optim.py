#!/usr/bin/env python3
"""optim.py -- parameter search for lab climbs / fits instead of brute-force grids and random-mutation climbs
(Shay 2026-10-10: cut the 5090's CPU without slowing anything down). Same objective, far fewer evaluations, stops as soon
as the target margin is reached.

  from optim import minimize
  r = minimize(f, x0, step, method='cma'|'nm'|'cf', target=None, maxevals=300, bounds=None, batch=None, workers=None,
               maximize=False, tol=1e-3, round_to=1e-3, log=print)
  r.x, r.f, r.evals, r.reason ('target' | 'converged' | 'maxevals')

  f(x) -> float               one evaluation (x = list of floats); or
  batch(list of x) -> floats  evaluate a whole population at once (e.g. one `animlab.py sweep` with N variants, which
                              replays them in parallel through labnice's budget); used for CMA populations, the NM start
                              simplex / shrink steps and the CF probes.
  method  cma  CMA-ES (small population, lambda = 4 + 3 ln n, default): robust on noisy / multi-modal climbs (E1/E6 keys)
          nm   Nelder-Mead (adaptive coefficients): smooth low-dimensional fits (calibration, 2-4 table values)
          cf   coarse-to-fine compass search: probe +-step on every coordinate, move to the best, halve the step when
               nothing improves (replaces an n-D grid: O(n) evaluations per level instead of k^n)
  target  stop as soon as the objective reaches it (minimize: f <= target; maximize: f >= target)
  bounds  [(lo, hi)] per coordinate (clipped); round_to: evaluations are memoised on x rounded to this (no re-evaluating
          a point the search already visited; the lab result cache labcache.py also skips identical replays)
  workers parallel f() calls when no batch function is given (default LABNICE_J or 4)

CLI (any command that prints the objective): optim.py run --x0 0.1,0.2 --step 0.05,0.05 [--method cma] [--target T]
  [--maximize] [--maxevals N] [--bounds lo:hi,lo:hi] [--regex 'score=([-0-9.e]+)'] -- <command with {0} {1} ...>
  prints one `eval <n> f=<v> x=<..>` line per evaluation and `OPTIM <reason> f=<v> x=<..> evals=<n>` at the end.
"""
import math, os, re, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor


class Result:
    def __init__(self, x, f, evals, reason, history):
        self.x, self.f, self.evals, self.reason, self.history = x, f, evals, reason, history

    def __repr__(self):
        return 'OPTIM %s f=%.6g x=%s evals=%d' % (self.reason, self.f, ','.join('%.6g' % v for v in self.x), self.evals)


class _Stop(Exception):
    pass


def minimize(f=None, x0=(), step=(), method='cma', target=None, maxevals=300, bounds=None, batch=None, workers=None,
             maximize=False, tol=1e-3, round_to=1e-3, log=None, seed=1):
    n = len(x0)
    step = list(step) if hasattr(step, '__len__') else [float(step)] * n
    sgn = -1.0 if maximize else 1.0
    memo, hist = {}, []
    best = [None, math.inf]   # internal (minimised) value
    workers = workers or int(os.environ.get('LABNICE_J') or 4)

    def clip(x):
        if not bounds:
            return list(x)
        return [min(max(v, lo), hi) for v, (lo, hi) in zip(x, bounds)]

    def key(x):
        return tuple(round(v / round_to) for v in x) if round_to else tuple(x)

    def ev(xs):
        """evaluate a list of points (memoised, batched), raise _Stop at target / budget."""
        xs = [clip(x) for x in xs]
        todo = []
        for x in xs:
            if key(x) not in memo and key(x) not in [key(t) for t in todo]:
                todo.append(x)
        room = maxevals - len(memo)
        todo = todo[:max(room, 0)]
        if todo:
            if batch:
                vals = list(batch(todo))
            elif len(todo) == 1 or workers <= 1:
                vals = [f(x) for x in todo]
            else:
                with ThreadPoolExecutor(min(workers, len(todo))) as ex:
                    vals = list(ex.map(f, todo))
            for x, v in zip(todo, vals):
                v = float(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else math.inf * sgn
                memo[key(x)] = sgn * v
                hist.append((list(x), v))
                if sgn * v < best[1]:
                    best[0], best[1] = list(x), sgn * v
                if log:
                    log('eval %d f=%.6g x=%s' % (len(memo), v, ','.join('%.4g' % t for t in x)))
        out = [memo.get(key(x), math.inf) for x in xs]
        if target is not None and best[1] <= sgn * target:
            raise _Stop('target')
        if len(memo) >= maxevals:
            raise _Stop('maxevals')
        return out

    reason = 'converged'
    try:
        if method == 'nm':
            _nm(ev, clip(x0), step, tol)
        elif method == 'cf':
            _cf(ev, clip(x0), step, tol)
        elif method == 'cma':
            _cma(ev, clip(x0), step, tol, seed)
        else:
            raise ValueError('method: cma | nm | cf')
    except _Stop as e:
        reason = str(e)
    if best[0] is None:
        best[0] = list(x0)
    return Result(best[0], sgn * best[1], len(memo), reason, hist)


def _nm(ev, x0, step, tol):
    n = len(x0)
    a, g, r, s = 1.0, 1.0 + 2.0 / n, 0.75 - 1.0 / (2 * n), 1.0 - 1.0 / n   # adaptive Nelder-Mead (Gao & Han)
    P = [list(x0)] + [[x0[j] + (step[i] if j == i else 0.0) for j in range(n)] for i in range(n)]
    F = ev(P)
    for _ in range(100000):
        o = sorted(range(n + 1), key=lambda i: F[i])
        P, F = [P[i] for i in o], [F[i] for i in o]
        if max(abs(P[i][j] - P[0][j]) / (abs(step[j]) or 1) for i in range(1, n + 1) for j in range(n)) < tol:
            return
        c = [sum(P[i][j] for i in range(n)) / n for j in range(n)]
        xr = [c[j] + a * (c[j] - P[-1][j]) for j in range(n)]
        fr, = ev([xr])
        if fr < F[0]:
            xe = [c[j] + g * (xr[j] - c[j]) for j in range(n)]
            fe, = ev([xe])
            P[-1], F[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < F[-2]:
            P[-1], F[-1] = xr, fr
        else:
            if fr < F[-1]:
                xc = [c[j] + r * (xr[j] - c[j]) for j in range(n)]
            else:
                xc = [c[j] + r * (P[-1][j] - c[j]) for j in range(n)]
            fc, = ev([xc])
            if fc < min(fr, F[-1]):
                P[-1], F[-1] = xc, fc
            else:
                P = [P[0]] + [[P[0][j] + s * (P[i][j] - P[0][j]) for j in range(n)] for i in range(1, n + 1)]
                F = [F[0]] + ev(P[1:])


def _cf(ev, x0, step, tol):
    x, st = list(x0), list(step)
    fx, = ev([x])
    st0 = list(step)
    while max(abs(s) / (abs(s0) or 1) for s, s0 in zip(st, st0)) >= tol:
        probes = []
        for i in range(len(x)):
            for d in (1, -1):
                p = list(x)
                p[i] += d * st[i]
                probes.append(p)
        fp = ev(probes)
        i = min(range(len(probes)), key=lambda k: fp[k])
        if fp[i] < fx:
            x, fx = probes[i], fp[i]
        else:
            st = [s / 2 for s in st]


def _cma(ev, x0, step, tol, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    n = len(x0)
    scale = np.array([abs(s) or 1.0 for s in step])   # search in units of step: sigma 1 = one step per coordinate
    m = np.zeros(n)
    sigma = 1.0
    lam = 4 + int(3 * math.log(n)) if n > 1 else 4
    mu = lam // 2
    w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    w /= w.sum()
    mueff = 1.0 / (w ** 2).sum()
    cc = (4 + mueff / n) / (n + 4 + 2 * mueff / n)
    cs = (mueff + 2) / (n + mueff + 5)
    c1 = 2 / ((n + 1.3) ** 2 + mueff)
    cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0, math.sqrt((mueff - 1) / (n + 1)) - 1) + cs
    pc, ps, C = np.zeros(n), np.zeros(n), np.eye(n)
    chin = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
    x0 = np.array(x0, dtype=float)
    ev([list(x0)])
    for gen in range(100000):
        D2, B = np.linalg.eigh(C)
        D = np.sqrt(np.maximum(D2, 1e-20))
        Z = rng.standard_normal((lam, n))
        Y = Z * D @ B.T
        X = m + sigma * Y
        F = ev([list(x0 + xi * scale) for xi in X])
        o = np.argsort(F)
        yw = (Y[o[:mu]] * w[:, None]).sum(0)
        m = m + sigma * yw
        Cinvh = B @ np.diag(1 / D) @ B.T
        ps = (1 - cs) * ps + math.sqrt(cs * (2 - cs) * mueff) * (Cinvh @ yw)
        hs = np.linalg.norm(ps) / math.sqrt(1 - (1 - cs) ** (2 * (gen + 1))) < (1.4 + 2 / (n + 1)) * chin
        pc = (1 - cc) * pc + hs * math.sqrt(cc * (2 - cc) * mueff) * yw
        C = (1 - c1 - cmu) * C + c1 * (np.outer(pc, pc) + (1 - hs) * cc * (2 - cc) * C) + \
            cmu * sum(w[i] * np.outer(Y[o[i]], Y[o[i]]) for i in range(mu))
        sigma *= math.exp((cs / damps) * (np.linalg.norm(ps) / chin - 1))
        if sigma * math.sqrt(max(D2.max(), 1e-20)) < tol:
            return


def main(argv):
    if not argv or argv[0] != 'run' or '--' not in argv:
        print(__doc__)
        return 2
    i = argv.index('--')
    opts, cmd = argv[1:i], argv[i + 1:]
    o = {'--method': 'cma', '--regex': r'([-+0-9.eE]+)\s*$', '--maxevals': '200'}
    flags = set()
    k = 0
    while k < len(opts):
        if opts[k] in ('--maximize',):
            flags.add(opts[k])
            k += 1
        else:
            o[opts[k]] = opts[k + 1]
            k += 2
    x0 = [float(v) for v in o['--x0'].split(',')]
    step = [float(v) for v in o['--step'].split(',')]
    bounds = [tuple(float(t) for t in b.split(':')) for b in o['--bounds'].split(',')] if '--bounds' in o else None
    rx = re.compile(o['--regex'], re.M)

    def f(x):
        c = [a.format(*['%.6g' % v for v in x]) for a in cmd]
        out = subprocess.run(c, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True).stdout
        mm = rx.findall(out)
        return float(mm[-1]) if mm else math.nan

    r = minimize(f, x0, step, method=o['--method'], target=float(o['--target']) if '--target' in o else None,
                 maxevals=int(o['--maxevals']), bounds=bounds, maximize='--maximize' in flags, log=lambda s: print(s, flush=True))
    print(r)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
