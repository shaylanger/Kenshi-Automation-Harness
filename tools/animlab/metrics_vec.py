"""metrics_vec.py -- batched, array-module-generic versions of the judge's per-frame hot path (gpu-lab 2026-10-11,
Shay: the lab judge goes to the GPU). Same numbers as recfmt.parse + metrics.rendered + metrics.frame_metrics, for a
BATCH of recordings / replays of equal frame count, as arrays [N, F, ...]; xp = numpy (CPU) or cupy (GPU, Windows-native).

  A = load(paths)                         parse every file (numpy text parse, CPU) -> dict of [N, F, ...] arrays + labels
  R = frame_metrics_vec(A, xp)            rendered() + frame_metrics() for all N at once (device arrays when xp=cupy)
  P = to_P(R, A, k)                       replay k as the list of dicts metrics.frame_metrics returns (downstream checks)
  python3 metrics_vec.py agree <files..> [--xp numpy|cupy]   one line: max abs difference vs the per-frame python + timings

GPU runs follow the GPU SAFETY RULE in components/KenshiFP/animlab/gpu/kfpgpu.py (first run 4080 only, lanes held,
compute-sanitizer, small N). Rows whose recording lacks the camera group (eye None) are not batched (load() refuses).
"""
import math, sys, time
import numpy as np
import recfmt, metrics

JN = ('Lsh', 'Lel', 'Lwr', 'Rsh', 'Rel', 'Rwr')


def load(paths):
    """parse files into arrays; every file must have the same frame count (replays of one recording)"""
    recs = [recfmt.parse(p) for p in paths]   # TODO(judge-vec): numpy text parse; per-frame python parse kept as the reference
    return from_recs(recs)


def from_recs(recs):
    F0 = len(recs[0].frames)
    if any(len(r.frames) != F0 for r in recs): raise ValueError('batch needs equal frame counts')
    A = {}
    def col(key): return np.array([[f[key] for f in r.frames] for r in recs], dtype=np.float64)
    for k in ('dt', 'cls', 'stch', 'wih', 'swu'):
        A[k] = col(k)
    A['wb'] = np.array([[np.nan if f['wb'] is None else f['wb'] for f in r.frames] for r in recs])
    for k in JN + ('mp', 'mf', 'mu', 'eye', 'rt', 'up', 'fw'):
        if any(f[k] is None for r in recs for f in r.frames): raise ValueError('frame without %s: not batched' % k)
        A[k] = np.array([[f[k] for f in r.frames] for r in recs], dtype=np.float64)
    A['labels'] = [metrics.label_states(r.frames) for r in recs]
    A['wb_none'] = np.array([[f['wb'] is None for f in r.frames] for r in recs])
    return A


def _dot(a, b): return a[..., 0] * b[..., 0] + a[..., 1] * b[..., 1] + a[..., 2] * b[..., 2]


def _mul(a, k): return a * k[..., None]


def _ln(a, xp): return xp.sqrt(_dot(a, a))


def _nz(a, xp):
    l = _ln(a, xp)
    ok = l > 1e-9
    return xp.where(ok[..., None], a * (1.0 / xp.where(ok, l, 1.0))[..., None], a)


def remap(c, a, b, pos, xp):
    w = (b['rt'] * c[..., 0:1] + b['up'] * c[..., 1:2]) + b['fw'] * c[..., 2:3]
    d = (w + b['eye']) - a['eye'] if pos else w
    return xp.stack([_dot(d, a['rt']), _dot(d, a['up']), _dot(d, a['fw'])], axis=-1)


def proj(c, xp):
    W, H, TX, TY = metrics.W_PX, metrics.H_PX, metrics.TX, metrics.TY
    ok = c[..., 2] >= 0.5
    z = xp.where(ok, c[..., 2], 1.0)
    x = W / 2 + W / 2 * (c[..., 0] / z) / TX
    y = H / 2 - H / 2 * (c[..., 1] / z) / TY
    return xp.stack([x, y], axis=-1), ok


def frame_metrics_vec(A, xp=np):
    """metrics.rendered + metrics.frame_metrics numbers for every replay of the batch: dict of arrays [N, F-1, ...]"""
    g = {k: xp.asarray(v) for k, v in A.items() if k not in ('labels',)}
    a = {k: v[:, :-1] for k, v in g.items()}; b = {k: v[:, 1:] for k, v in g.items()}
    J = xp.stack([remap(b[k], a, b, 1, xp) for k in JN], axis=2)          # [N, F-1, 6, 3]
    mp = remap(b['mp'], a, b, 1, xp); mf = _nz(remap(b['mf'], a, b, 0, xp), xp); mu = _nz(remap(b['mu'], a, b, 0, xp), xp)
    upw = xp.stack([a['rt'][..., 1], a['up'][..., 1], a['fw'][..., 1]], axis=-1)
    elb_h = _dot(J[:, :, 4] - J[:, :, 3], _nz(upw, xp))
    j5 = J[:, :, 5]; l5 = _ln(j5, xp)
    edge = xp.where(l5 > 1e-6, _dot(mu, _nz(j5, xp)), 0.0)
    cls = a['cls']
    blade = xp.where(cls == 1, metrics.BLADE[1], metrics.BLADE[0])
    tip = mp + _mul(mf, blade)
    tip = xp.where((cls == 1)[..., None], tip + mu * 0.84, tip)
    tpx, tok = proj(tip, xp)
    q, qok = proj(j5, xp)
    wvis = qok & (q[..., 0] >= 0) & (q[..., 0] <= metrics.W_PX) & (q[..., 1] >= 0) & (q[..., 1] <= metrics.H_PX)
    # frame_metrics: edge arc + jitter/step on interior frames i = 1..N-2 (P index), F index i
    N1 = J.shape[1]
    dt = g['dt']; Fi = slice(1, N1 - 1)
    dmax = xp.maximum(xp.maximum(dt[:, 0:N1 - 2], dt[:, 1:N1 - 1]), dt[:, 2:N1])
    mid = mp + mf * metrics.ARC_MID
    vel = _mul(mid[:, 2:] - mid[:, :-2], 1.0 / xp.maximum(dt[:, 1:N1 - 1] + dt[:, 2:N1], 1e-4))
    mfb = mf[:, Fi]
    vp = vel - _mul(mfb, _dot(vel, mfb))
    swu = g['swu'][:, 1:N1 - 1]
    arc_ok = (g['cls'][:, 1:N1 - 1] == 0) & (dmax <= 0.07) & (_ln(vp, xp) > metrics.ARC_SPEED) & (swu >= metrics.ARC_U0) & (swu < metrics.ARC_U1)
    arc = xp.where(arc_ok, _dot(mu[:, Fi], _nz(vp, xp)), xp.nan)
    lab = xp.asarray(np.array([[hash(s) for s in L[:N1]] for L in A['labels']], dtype=np.int64))
    same = (lab[:, 0:N1 - 2] == lab[:, 1:N1 - 1]) & (lab[:, 2:N1] == lab[:, 1:N1 - 1])
    jok = tok[:, 0:N1 - 2] & tok[:, 1:N1 - 1] & tok[:, 2:N1] & (dmax <= 0.07) & same
    d1 = xp.maximum(dt[:, 1:N1 - 1], 1e-4); d2 = xp.maximum(dt[:, 2:N1], 1e-4); u = d1 / (d1 + d2)
    ta, tb, tc = tpx[:, 0:N1 - 2], tpx[:, 1:N1 - 1], tpx[:, 2:N1]
    ex = ta + (tc - ta) * u[..., None]
    jit = xp.where(jok, xp.hypot(tb[..., 0] - ex[..., 0], tb[..., 1] - ex[..., 1]), xp.nan)
    step = xp.where(jok, xp.hypot(tb[..., 0] - ta[..., 0], tb[..., 1] - ta[..., 1]), xp.nan)
    return dict(J=J, mp=mp, mf=mf, mu=mu, elb_h=elb_h, edge=edge, tip=tip, tpx=tpx, tok=tok, wvis=wvis, arc=arc, jit=jit, step=step,
                wb=b['wb'], st=b['stch'], wih=b['wih'])


def to_P(R, A, k):
    """replay k of a (host) result as metrics.frame_metrics' list of dicts"""
    n = R['J'].shape[1]; P = []
    def t3(v): return (float(v[0]), float(v[1]), float(v[2]))
    for i in range(n):
        J = [t3(R['J'][k, i, j]) for j in range(6)]
        p = dict(J=J, mp=t3(R['mp'][k, i]), mf=t3(R['mf'][k, i]), mu=t3(R['mu'][k, i]),
                 wb=None if A['wb_none'][k, i + 1] else float(R['wb'][k, i]), st=float(R['st'][k, i]), wih=int(R['wih'][k, i]))
        p['elb'] = J[4]; p['elb_h'] = float(R['elb_h'][k, i]); p['edge'] = float(R['edge'][k, i]); p['tip'] = t3(R['tip'][k, i])
        p['tpx'] = (float(R['tpx'][k, i, 0]), float(R['tpx'][k, i, 1])) if R['tok'][k, i] else None
        p['wvis'] = bool(R['wvis'][k, i]); p['state'] = A['labels'][k][i]
        p['jit'] = p['step'] = None; p['arc'] = None
        if 1 <= i < n - 1:
            for key in ('jit', 'step', 'arc'):
                v = float(R[key][k, i - 1])
                if v == v: p[key] = v
        P.append(p)
    return P


def _cmp(P0, P1):
    """max abs difference of every number in two P lists; -1 = structure differs (None vs number, label)"""
    worst = 0.0
    for a, b in zip(P0, P1):
        for key, va in a.items():
            vb = b[key]
            if isinstance(va, list): pairs = [(x, y) for u, w in zip(va, vb) for x, y in zip(u, w)]
            elif isinstance(va, tuple): pairs = list(zip(va, vb))
            else: pairs = [(va, vb)]
            for x, y in pairs:
                if (x is None) != (y is None) or isinstance(x, str) and x != y or isinstance(x, bool) and x != y: return -1.0, key
                if isinstance(x, (int, float)) and not isinstance(x, bool): worst = max(worst, abs(x - y))
    return worst, None


def main():
    a = sys.argv[1:]
    if not a or a[0] != 'agree': print(__doc__); return 2
    xpn = 'numpy'
    if '--xp' in a: i = a.index('--xp'); xpn = a[i + 1]; del a[i:i + 2]
    xp = np
    if xpn == 'cupy':
        import cupy as xp
    paths = a[1:]
    t0 = time.time(); recs = [recfmt.parse(p) for p in paths]; t1 = time.time()
    ref = [metrics.frame_metrics(r) for r in recs]; t2 = time.time()
    A = from_recs(recs); t3 = time.time()
    R = frame_metrics_vec(A, xp)
    if xpn == 'cupy': xp.cuda.Device().synchronize()
    t4 = time.time()
    if xpn == 'cupy': R = {k: xp.asnumpy(v) for k, v in R.items()}
    t5 = time.time()
    worst = 0.0; bad = None
    for k in range(len(recs)):
        w, key = _cmp(ref[k], to_P(R, A, k))
        if w < 0: bad = (k, key); break
        worst = max(worst, w)
    t6 = time.time()
    ok = bad is None and worst <= 1e-6
    print('VECAGREE %s xp=%s n=%d frames=%d max_abs=%.3g%s parse=%.2fs python_judge=%.3fs pack=%.3fs vec=%.4fs download=%.3fs to_P=%.2fs' % (
        'PASS' if ok else 'FAIL', xpn, len(recs), len(recs[0].frames), worst, (' struct_diff=%s' % (bad,)) if bad else '',
        t1 - t0, t2 - t1, t3 - t2, t4 - t3, t5 - t4, t6 - t5))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
