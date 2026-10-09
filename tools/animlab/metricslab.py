#!/usr/bin/env python3
"""metricslab.py -- offline animation lab, phase 2 (METRICS LAB): author a motion (time-keyed weapon/hand targets, JSON),
solve it through a viewmodel solver adapter on a real recorded body, report the viewmodel metrics, reach limits and
weapon/weapon, weapon/arm and weapon/camera intersections per segment. Docs: docs/animlab/USAGE.md "Phase 2".

  metricslab.py sample <motion.json> [-o frames_dir]           interpolate only (no solver): writes frames_<side>.txt
  metricslab.py run    <motion.json> --adapter CMD [--body REC] [--body-frame N] [--out DIR] [--args='...'] [--quiet]
  metricslab.py report <motion.json> <solved_R.txt> [<solved_L.txt>]   metrics of already solved output
  metricslab.py fromrec <rec> <from> <to> [-o motion.json]   a motion from a recorded segment (start authoring from it)
  metricslab.py faithful <rec> <from> <to> --adapter CMD [--tol 0.25]   drive the recorded commanded poses of a steady
                         segment (fixed camera) and compare the solved arm with the game's measured arm (drive gate)

Drive adapter contract (phase-1 adapters are untouched; this is a separate entry point):
  CMD <body_rec.txt> <frames.txt> <out.txt> --body-frame N [--side R|L] [args]
  frames.txt  one line per frame: `t cls px,py,pz fx,fy,fz ux,uy,uz ox,oy,oz` (camera numbers: x right, y up, z forward,
              dm; p/f/u = weapon pose of the solved side, o = off-hand target or nan,nan,nan = solver rest point)
  out.txt     `# header`, then `i t | <L arm> | <R arm> | stL stR ikfail eclamp | eye rt up fw` with each arm =
              `sh el wr handX propP propF propU` (camera numbers of the body frame, after the solve; ikfail/eclamp are
              running counts). The adapter may print `calib L1R,L2R,L1L,L2L,K` on stdout (arm lengths, dm).
Dual wielding: one run per armed side (the other arm rests); the report merges each side's own arm.
"""
import argparse, json, math, os, shlex, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recfmt import sub, add, mul, dot, cross, ln, nz
import metrics as M

WEAPONS = {'sword': (0, 8.0), 'crossbow': (1, 5.85)}   # class, blade/stock length from the grip along f (dm)
DEFAULT_LIMITS = dict(wb_max=30.0,       # wrist fold (forearm vs hand X), deg: fp-viewmodel.sh WB_MAX
                      terr_max=0.30,     # solved grip vs authored grip, dm: above = target out of reach / clamped
                      ferr_max=10.0,     # solved blade direction vs authored, deg
                      reach_max=1.5,     # shoulder->wrist / (L1+L2): > 1 = stretched arm (game ready max ~1.49)
                      ww_min=0.0,        # weapon/weapon clearance, dm (< 0 = blades intersect)
                      warm_min=0.0,      # weapon/other-arm clearance, dm
                      head_min=1.0,      # blade distance to the eye, dm (weapon in the head)
                      clip_frames=0,     # frames with a visible blade part cut by the near plane
                      jit_p95=2.0)       # tip screen jitter, px
DEFAULT_GEOM = dict(blade_r=0.15, arm_r=0.35, near=3.0, samples=24)


# ---------------- motion file -> per-frame targets ----------------
def _lerp(a, b, u): return tuple(a[k] + (b[k] - a[k]) * u for k in range(3))


def _cr(p0, p1, p2, p3, u):   # Catmull-Rom (uniform)
    u2, u3 = u * u, u * u * u
    return tuple(0.5 * (2 * p1[k] + (p2[k] - p0[k]) * u + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * u2
                        + (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * u3) for k in range(3))


def _slerp(a, b, u):
    a, b = nz(a), nz(b)
    c = max(-1.0, min(1.0, dot(a, b)))
    th = math.acos(c)
    if th < 1e-4:
        return nz(_lerp(a, b, u))
    if th > math.pi - 1e-3:   # opposite: go round any perpendicular
        return nz(_lerp(a, b, u))
    s = math.sin(th)
    return nz(add(mul(a, math.sin((1 - u) * th) / s), mul(b, math.sin(u * th) / s)))


def _ease(u, mode):
    return u * u * (3 - 2 * u) if mode == 'smooth' else u


def sample_track(keys, t, interp='spline', field='p'):
    """value of one keyed field at time t (keys sorted by t; holds before the first / after the last key)."""
    if t <= keys[0]['t']:
        return tuple(keys[0][field])
    if t >= keys[-1]['t']:
        return tuple(keys[-1][field])
    i = max(j for j in range(len(keys) - 1) if keys[j]['t'] <= t)
    k0, k1 = keys[i], keys[i + 1]
    u = (t - k0['t']) / max(1e-9, k1['t'] - k0['t'])
    mode = k0.get('ease', interp)
    if field != 'p':
        return _slerp(k0[field], k1[field], _ease(u, 'smooth' if mode == 'smooth' else 'linear'))
    if mode == 'spline':
        pm = keys[i - 1][field] if i > 0 else k0[field]
        pp = keys[i + 2][field] if i + 2 < len(keys) else k1[field]
        return _cr(pm, k0[field], k1[field], pp, u)
    return _lerp(k0[field], k1[field], _ease(u, mode))


def segment_of(keys, t):
    i = 0
    for j, k in enumerate(keys):
        if k['t'] <= t + 1e-9:
            i = j
    return keys[i].get('label', 'k%d' % i)


def load_motion(path):
    with open(path) as f:
        m = json.load(f)
    hands = m.get('hands') or {}
    if not hands or any(s not in ('R', 'L') for s in hands):
        raise ValueError('motion: "hands" needs R and/or L')
    for s, h in hands.items():
        w = h.get('weapon', 'sword')
        if w not in WEAPONS:
            raise ValueError('motion: hand %s weapon %r (sword|crossbow)' % (s, w))
        keys = h.get('keys') or []
        if not keys:
            raise ValueError('motion: hand %s has no keys' % s)
        for k in keys:
            for fld in ('t', 'p', 'f', 'u'):
                if fld not in k:
                    raise ValueError('motion: hand %s key missing %r: %s' % (s, fld, k))
            if abs(dot(nz(k['f']), nz(k['u']))) > 0.98:
                raise ValueError('motion: hand %s key t=%s: f and u (nearly) parallel' % (s, k['t']))
        keys.sort(key=lambda k: k['t'])
        off = h.get('off', 'rest')
        if off != 'rest':
            off.sort(key=lambda k: k['t'])
    m.setdefault('fps', 60)
    m.setdefault('name', os.path.splitext(os.path.basename(path))[0])
    return m


def duration(m):
    return max(h['keys'][-1]['t'] for h in m['hands'].values()) + float(m.get('hold', 0.0))


def frames_for(m, side):
    """[(t, cls, p, f, u, o, segment)] for one armed side; u is re-orthogonalised to f."""
    h = m['hands'][side]
    cls = WEAPONS[h.get('weapon', 'sword')][0]
    interp = m.get('interp', 'spline')
    n = int(round(duration(m) * m['fps'])) + 1
    pre = int(round(float(m.get('preroll', 0.5)) * m['fps']))   # hold key 0 first: the solver's smoothing settles
    ts = [i / float(m['fps']) for i in range(-pre, 0)] + (list(m['times']) if m.get('times') else
                                                         [i / float(m['fps']) for i in range(n)])
    out = []
    for t in ts:   # 'times' (optional): explicit frame times instead of the fps grid (faithful: the recorded times)
        p = sample_track(h['keys'], t, interp, 'p')
        f = nz(sample_track(h['keys'], t, interp, 'f'))
        u = sample_track(h['keys'], t, interp, 'u')
        u = nz(sub(u, mul(f, dot(u, f))))
        off = h.get('off', 'rest')
        o = None if off == 'rest' else sample_track(off, t, interp, 'p')
        out.append((t, cls, p, f, u, o, segment_of(h['keys'], t)))
    return out


def write_frames(path, fr):
    V = lambda v: '%.5f,%.5f,%.5f' % tuple(v)
    with open(path, 'w') as f:
        f.write('# t cls p f u o (camera numbers, dm)\n')
        for t, cls, p, fw, u, o, _ in fr:
            f.write('%.5f %d %s %s %s %s\n' % (t, cls, V(p), V(fw), V(u), 'nan,nan,nan' if o is None else V(o)))


# ---------------- solved output ----------------
ARM = ('sh', 'el', 'wr', 'hx', 'pp', 'pf', 'pu')


def parse_solved(path):
    rows, hdr = [], ''
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                hdr = line[1:].strip()
                continue
            g = line.split('|')
            if len(g) < 5:
                continue
            i, t = g[0].split()
            r = dict(i=int(i), t=float(t))
            for s, gi in (('L', 1), ('R', 2)):
                v = [tuple(float(x) for x in w.split(',')) for w in g[gi].split()]
                r[s] = dict(zip(ARM, v))
            x = g[3].split()
            r['stL'], r['stR'], r['ikfail'], r['eclamp'] = float(x[0]), float(x[1]), int(x[2]), int(x[3])
            cam = [tuple(float(x) for x in w.split(',')) for w in g[4].split()]
            r['eye'], r['rt'], r['up'], r['fw'] = cam
            rows.append(r)
    calib = None
    for tok in hdr.split():
        if tok.startswith('calib='):
            calib = [float(x) for x in tok[6:].split(',')]
    return rows, calib


# ---------------- geometry ----------------
def seg_seg(p1, q1, p2, q2):
    """minimum distance between segments p1q1 and p2q2."""
    d1, d2, r = sub(q1, p1), sub(q2, p2), sub(p1, p2)
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a < 1e-12 and e < 1e-12:
        return ln(r)
    if a < 1e-12:
        s, t = 0.0, max(0.0, min(1.0, f / e))
    else:
        c = dot(d1, r)
        if e < 1e-12:
            t, s = 0.0, max(0.0, min(1.0, -c / a))
        else:
            b = dot(d1, d2)
            den = a * e - b * b
            s = max(0.0, min(1.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0:
                t, s = 0.0, max(0.0, min(1.0, -c / a))
            elif t > 1:
                t, s = 1.0, max(0.0, min(1.0, (b - c) / a))
    return ln(sub(add(p1, mul(d1, s)), add(p2, mul(d2, t))))


def pt_seg(p, a, b):
    d = sub(b, a)
    u = max(0.0, min(1.0, dot(sub(p, a), d) / max(1e-12, dot(d, d))))
    return ln(sub(p, add(a, mul(d, u))))


def near_clipped(a, b, near, n):
    """a blade part that would be on screen but lies in front of the near plane (0 < z < near)."""
    for k in range(n + 1):
        p = _lerp(a, b, k / float(n))
        if 0.0 < p[2] < near and abs(p[0]) <= p[2] * M.TX and abs(p[1]) <= p[2] * M.TY:
            return True
    return False


def blade(arm, cls, length):
    tip = add(arm['pp'], mul(arm['pf'], length))
    if cls == 1:
        tip = add(tip, mul(arm['pu'], 0.84))   # crossbow: same tip point as metrics.rendered
    return arm['pp'], tip


# ---------------- report ----------------
def evaluate(m, solved, frames, geom=None, limits=None):
    """solved: {side: rows}, frames: {side: frame list}. Returns (per-frame list, per-segment table, verdict dict)."""
    g = dict(DEFAULT_GEOM, **(m.get('geom') or {}), **(geom or {}))
    lim = dict(DEFAULT_LIMITS, **(m.get('limits') or {}), **(limits or {}))
    sides = sorted(solved)
    n0 = sum(1 for x in frames[sides[0]] if x[0] < -1e-9)   # pre-roll frames: solved but not reported
    n = min(len(solved[s][0]) for s in sides)
    calib = {s: solved[s][1] for s in sides}
    P = []
    for i in range(n0, n):
        q = {}
        for s in sides:
            r = solved[s][0][i]
            arm = r[s]
            t, cls, pa, fa, ua, o, seg = frames[s][i]
            length = float(m['hands'][s].get('blade', WEAPONS[m['hands'][s].get('weapon', 'sword')][1]))
            upw = nz((r['rt'][1], r['up'][1], r['fw'][1]))
            c = calib[s]
            L12 = (c[0] + c[1]) if (c and s == 'R') else ((c[2] + c[3]) if c else float('nan'))
            ik_prev = solved[s][0][i - 1]['ikfail'] if i else 0
            b0, b1 = blade(arm, cls, length)
            q[s] = dict(seg=seg, cls=cls, arm=arm, blade=(b0, b1),
                        wb=math.degrees(math.acos(max(-1.0, min(1.0, dot(nz(sub(arm['wr'], arm['el'])), nz(arm['hx'])))))),
                        elb_h=dot(sub(arm['el'], arm['sh']), upw),
                        st=r['st' + s], reach=ln(sub(arm['wr'], arm['sh'])) / L12 if L12 == L12 else float('nan'),
                        terr=ln(sub(arm['pp'], pa)),
                        ferr=math.degrees(math.acos(max(-1.0, min(1.0, dot(nz(arm['pf']), fa))))),
                        edge=dot(arm['pu'], nz(arm['wr'])) if ln(arm['wr']) > 1e-6 else 0.0,
                        tpx=M.proj(b1), apx=M.proj(blade(dict(pp=pa, pf=fa, pu=ua), cls, length)[1]), ik=r['ikfail'] - ik_prev,
                        head=pt_seg((0.0, 0.0, 0.0), b0, b1) - g['blade_r'],
                        clip=near_clipped(b0, b1, g['near'], int(g['samples'])))
        if len(sides) == 2:
            R, L = q['R'], q['L']
            ww = seg_seg(R['blade'][0], R['blade'][1], L['blade'][0], L['blade'][1]) - 2 * g['blade_r']
            R['ww'] = L['ww'] = ww
            for a, b in (('R', 'L'), ('L', 'R')):   # blade of a vs the other arm (upper arm + forearm) of b
                ab, ob = q[a]['blade'], q[b]['arm']
                q[a]['warm'] = min(seg_seg(ab[0], ab[1], ob['sh'], ob['el']), seg_seg(ab[0], ab[1], ob['el'], ob['wr'])) \
                    - g['blade_r'] - g['arm_r']
        P.append(q)
    for s in sides:   # tip jitter the SOLVER adds (px): second difference of (solved tip - authored tip) on screen, so a
        for q in P:   # fast authored arc is not counted, only frame-to-frame wobble around it
            q[s]['jit'] = None
            q[s]['e'] = (q[s]['tpx'][0] - q[s]['apx'][0], q[s]['tpx'][1] - q[s]['apx'][1]) if q[s]['tpx'] and q[s]['apx'] else None
        for i in range(1, len(P) - 1):
            a, b, c = (P[k][s]['e'] for k in (i - 1, i, i + 1))
            if a and b and c:
                P[i][s]['jit'] = math.hypot(b[0] - (a[0] + c[0]) / 2, b[1] - (a[1] + c[1]) / 2)
    rows = []
    order = []
    for q in P:
        for s in sides:
            key = (s, q[s]['seg'])
            if key not in order:
                order.append(key)
    for s, seg in order + [(s, '*all*') for s in sides]:
        X = [q[s] for q in P if seg == '*all*' or q[s]['seg'] == seg]
        col = lambda k: [x[k] for x in X if x.get(k) is not None and x[k] == x[k]]
        mx = lambda k: max(col(k)) if col(k) else float('nan')
        mn = lambda k: min(col(k)) if col(k) else float('nan')
        rows.append(dict(side=s, seg=seg, n=len(X), wb_p95=M.pct(col('wb'), 0.95), wb_max=mx('wb'), elb_h_max=mx('elb_h'),
                         st_max=mx('st'), reach_max=mx('reach'), terr_max=mx('terr'), ferr_max=mx('ferr'),
                         edge_mean=sum(col('edge')) / max(1, len(col('edge'))), jit_p95=M.pct(col('jit'), 0.95),
                         ww_min=mn('ww'), warm_min=mn('warm'), head_min=mn('head'), clip_frames=sum(1 for x in X if x['clip']),
                         ikfail=sum(x['ik'] for x in X)))
    fails = []
    for r in rows:
        if r['seg'] != '*all*':
            continue
        for k in ('wb_max', 'terr_max', 'ferr_max', 'reach_max', 'clip_frames', 'jit_p95'):
            if r[k] == r[k] and r[k] > lim[k] + 1e-9:
                fails.append('%s.%s=%.2f>%g' % (r['side'], k, r[k], lim[k]))
        for k in ('ww_min', 'warm_min', 'head_min'):
            if r[k] == r[k] and r[k] < lim[k] - 1e-9:
                fails.append('%s.%s=%.2f<%g' % (r['side'], k, r[k], lim[k]))
        if r['ikfail']:
            fails.append('%s.ikfail=%d' % (r['side'], r['ikfail']))
    fails = sorted(set(fails))
    return P, rows, dict(ok=not fails, fails=fails, limits=lim, geom=g)


COLS = ('n', 'wb_p95', 'wb_max', 'elb_h_max', 'st_max', 'reach_max', 'terr_max', 'ferr_max', 'edge_mean', 'jit_p95',
        'ww_min', 'warm_min', 'head_min', 'clip_frames', 'ikfail')


def print_report(m, rows, verdict, out=sys.stdout):
    w = max(12, max(len(r['seg']) for r in rows) + 3)
    out.write('%-*s' % (w, 'side:segment') + ''.join('%10s' % c for c in COLS) + '\n')
    for r in rows:
        out.write('%-*s' % (w, '%s:%s' % (r['side'], r['seg'])) + ''.join('%10s' % M.fmt(r[c]) for c in COLS) + '\n')
    a = {r['side']: r for r in rows if r['seg'] == '*all*'}
    ev = ' '.join('%s:wb_max=%.1f,terr_max=%.2f,ww_min=%s,head_min=%.2f,clip=%d' % (s, a[s]['wb_max'], a[s]['terr_max'],
                  M.fmt(a[s]['ww_min']), a[s]['head_min'], a[s]['clip_frames']) for s in sorted(a))
    out.write('RESULT %s %s %s%s\n' % (m['name'], 'PASS' if verdict['ok'] else 'FAIL', ev,
                                       '' if verdict['ok'] else ' fails=' + ','.join(verdict['fails'])))


def merge_pose(solved, sides, path):
    """one pose file in the drive output format, each arm taken from its own side's run (input for the visual lab)."""
    base = solved[sides[0]][0]
    with open(path, 'w') as f:
        f.write('# metricslab merged pose: arms ' + ','.join('%s<-run %s' % (s, s) for s in sides) + '\n')
        for i in range(min(len(solved[s][0]) for s in sides)):   # (includes the pre-roll frames, t < 0)
            r = base[i]
            arms = {s: (solved[s][0][i][s] if s in solved else r[s]) for s in ('L', 'R')}
            st = {s: (solved[s][0][i]['st' + s] if s in solved else r['st' + s]) for s in ('L', 'R')}
            V = lambda v: '%.5f,%.5f,%.5f' % tuple(v)
            f.write('%d %.5f |' % (i, r['t']) + ' |'.join(' ' + ' '.join(V(arms[s][k]) for k in ARM) for s in ('L', 'R'))
                    + ' | %.4f %.4f %d %d | %s\n' % (st['L'], st['R'], sum(solved[s][0][i]['ikfail'] for s in sides),
                                                     sum(solved[s][0][i]['eclamp'] for s in sides),
                                                     ' '.join(V(r[k]) for k in ('eye', 'rt', 'up', 'fw'))))


# ---------------- commands ----------------
def cmd_sample(a):
    m = load_motion(a.motion)
    os.makedirs(a.o, exist_ok=True)
    for s in sorted(m['hands']):
        fr = frames_for(m, s)
        write_frames(os.path.join(a.o, 'frames_%s.txt' % s), fr)
        print('frames_%s.txt %d frames %.2f s' % (s, len(fr), fr[-1][0]))
    return 0


def run_motion(m, adapter, body, body_frame, out, extra=(), quiet=False):
    sides = sorted(m['hands'])
    solved, frames = {}, {}
    os.makedirs(out, exist_ok=True)
    for s in sides:
        fr = frames_for(m, s)
        fp, op = os.path.join(out, 'frames_%s.txt' % s), os.path.join(out, 'solved_%s.txt' % s)
        write_frames(fp, fr)
        cmd = shlex.split(adapter) + [body, fp, op, '--body-frame', str(body_frame), '--side', s] + list(extra)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError('adapter failed (%d): %s\n%s' % (p.returncode, ' '.join(cmd), p.stderr[-2000:]))
        rows, calib = parse_solved(op)
        if calib is None:
            for line in p.stdout.splitlines():
                if line.startswith('calib '):
                    calib = [float(x) for x in line.split()[1].split(',')]
        solved[s], frames[s] = (rows, calib), fr
    merge_pose(solved, sides, os.path.join(out, 'pose.txt'))
    return solved, frames


def cmd_run(a):
    m = load_motion(a.motion)
    body = a.body or (m.get('body') or {}).get('rec')
    bf = a.body_frame if a.body_frame is not None else (m.get('body') or {}).get('frame')
    if not body or bf is None:
        print('metricslab: need --body REC and --body-frame N (or "body": {"rec","frame"} in the motion)', file=sys.stderr)
        return 2
    out = a.out or ('ml-' + m['name'])
    solved, frames = run_motion(m, a.adapter, body, bf, out, shlex.split(a.args or ''), a.quiet)
    P, rows, v = evaluate(m, solved, frames)
    with open(os.path.join(out, 'report.txt'), 'w') as f:
        print_report(m, rows, v, f)
    with open(os.path.join(out, 'report.json'), 'w') as f:
        json.dump(dict(name=m['name'], verdict=v, segments=rows), f, indent=1, default=str)
    if a.quiet:
        with open(os.path.join(out, 'report.txt')) as f:
            sys.stdout.write(f.read().splitlines()[-1] + '\n')
    else:
        print_report(m, rows, v)
    return 0 if v['ok'] else 1


def cmd_report(a):
    m = load_motion(a.motion)
    paths = {'R': a.solved[0]} if len(a.solved) == 1 else dict(zip(('R', 'L'), a.solved))
    if len(a.solved) == 1 and sorted(m['hands']) == ['L']:
        paths = {'L': a.solved[0]}
    solved = {s: parse_solved(p) for s, p in paths.items()}
    frames = {s: frames_for(m, s) for s in solved}
    P, rows, v = evaluate(m, solved, frames)
    print_report(m, rows, v)
    return 0 if v['ok'] else 1


def motion_from_rec(F, a, b, name, measured=False):
    """keys = the weapon pose (+ off-hand target) of every record a..b, times relative to record a: the commanded pose
    (out, oc), or with measured=True what the game rendered (record i+1: mp/mf/mu + the off hand's wrist, the
    plugin's own `fp_vm replay n` path)."""
    side = 'R'
    if measured:
        G = [F[min(i + 1, len(F) - 1)] for i in range(a, b + 1)]
        keys = [dict(t=round(F[i]['t'] - F[a]['t'], 5), p=list(g['mp']), f=list(g['mf']), u=list(g['mu'])) for i, g in zip(range(a, b + 1), G)]
        offk = 'Lwr' if F[a]['cls'] == 0 else 'Lwr'
        off = [dict(t=k['t'], p=list(g[offk])) for k, g in zip(keys, G)]
    else:
        keys = [dict(t=round(F[i]['t'] - F[a]['t'], 5), p=list(F[i]['out_p']), f=list(F[i]['out_f']), u=list(F[i]['out_u']))
                for i in range(a, b + 1)]
        off = [dict(t=k['t'], p=list(F[a + j]['oc'])) for j, k in enumerate(keys)]
    w = 'crossbow' if F[a]['cls'] == 1 else 'sword'
    return dict(name=name, fps=60, interp='linear', preroll=0.5, body=dict(frame=a),
                hands={side: dict(weapon=w, keys=keys, off=off)})


def cmd_fromrec(a):
    import recfmt
    F = recfmt.parse(a.rec).frames
    m = motion_from_rec(F, a.a, a.b, a.name or 'rec-%d-%d' % (a.a, a.b))
    m['body']['rec'] = a.rec
    with open(a.o, 'w') as f:
        json.dump(m, f, indent=1)
    print('%s: %d keys %.2f s' % (a.o, len(m['hands']['R']['keys']), m['hands']['R']['keys'][-1]['t']))
    return 0


def cmd_faithful(a):
    """the drive path must solve the arm the game solved: the weapon pose the game rendered (record i+1) as the target,
    solved arm vs the game's measured arm, on frames with a still body (eye within 0.3 dm of record a, full viewmodel)."""
    import recfmt
    F = recfmt.parse(a.rec).frames
    m = motion_from_rec(F, a.a, a.b, 'faithful', measured=True)
    m['times'] = [F[i]['t'] - F[a.a]['t'] for i in range(a.a, a.b + 1)]
    out = a.out or '/tmp/ml-faithful'
    solved, frames = run_motion(m, a.adapter, a.rec, a.a, out, shlex.split(a.args or ''))
    rows = solved['R'][0]
    n0 = sum(1 for x in frames['R'] if x[0] < -1e-9)
    err = dict(grip=[], elbow=[], wrist=[], shoulder=[])
    for k in range(n0, len(rows)):
        i = a.a + k - n0
        if i + 1 >= len(F):
            continue
        g, s = F[i + 1], rows[k]['R']
        if ln(sub(F[i]['eye'], F[a.a]['eye'])) > 0.3 or ln(sub(g['eye'], F[a.a]['eye'])) > 0.3 or min(F[i]['w'], g['zf']) < 0.99                 or F[i]['swing'] or F[i]['st'] != F[a.a]['st']:
            continue
        err['grip'].append(ln(sub(g['mp'], s['pp'])))
        err['elbow'].append(ln(sub(g['Rel'], s['el'])))
        err['wrist'].append(ln(sub(g['Rwr'], s['wr'])))
        err['shoulder'].append(ln(sub(g['Rsh'], s['sh'])))
    p95 = {k: M.pct(v, 0.95) for k, v in err.items()}
    ok = len(err['grip']) >= 50 and all(v <= a.tol for v in p95.values())
    print('RESULT faithful-drive %s %s frames=%d grip95=%.3f elbow95=%.3f wrist95=%.3f shoulder95=%.3f tol=%.2f' % (
        'PASS' if ok else 'FAIL', os.path.basename(a.rec), len(err['grip']), p95['grip'], p95['elbow'], p95['wrist'],
        p95['shoulder'], a.tol))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('sample'); p.add_argument('motion'); p.add_argument('-o', default='.')
    p = sp.add_parser('run'); p.add_argument('motion'); p.add_argument('--adapter', required=True)
    p.add_argument('--body'); p.add_argument('--body-frame', type=int); p.add_argument('--out')
    p.add_argument('--args', default=''); p.add_argument('--quiet', action='store_true')
    p = sp.add_parser('report'); p.add_argument('motion'); p.add_argument('solved', nargs='+')
    p = sp.add_parser('fromrec'); p.add_argument('rec'); p.add_argument('a', type=int); p.add_argument('b', type=int)
    p.add_argument('-o', default='motion.json'); p.add_argument('--name')
    p = sp.add_parser('faithful'); p.add_argument('rec'); p.add_argument('a', type=int); p.add_argument('b', type=int)
    p.add_argument('--adapter', required=True); p.add_argument('--tol', type=float, default=0.25)
    p.add_argument('--args', default=''); p.add_argument('--out')
    a = ap.parse_args()
    return dict(sample=cmd_sample, run=cmd_run, report=cmd_report, fromrec=cmd_fromrec, faithful=cmd_faithful)[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
