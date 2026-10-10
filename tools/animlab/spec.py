#!/usr/bin/env python3
"""spec.py -- spec-first lab checks: every standing pose/presentation rule as a check, run on a candidate BEFORE review.

  spec.py map     <rules.tsv> [--md]                         rule -> check map (covered / partial / missing / out of reach)
  spec.py run     <rules.tsv> --checks <checks.json> --class C <rec>... [--set k=v]   every rule of class C on recordings
  spec.py unarmed <cand>... [--rules rules.tsv]              unarmed (fists) spec on metricslab/native.py fist candidates (the
                                                             technique name = the candidate dir; shotei/palm names get U17)
  spec.py restedge <rec>                                     sword edge never toward the camera in the rest states
  spec.py stilljit <rec> [--states aim --max 1.5]            still-state weapon jitter (px at 1600x900)
  spec.py wrist    <rec> [--hold 30 --swing 50]              wrist bend limit per state (holds vs swings)
  spec.py blade    <rec> [--only-stroke N --snap 32 --run .067]  R17 blade, native reference (snap at the wind-up top,
                                                             longest end-on stretch in the follow-through)
                                                            on solver-posed frames only (native frames exempt, Shay 2026-10-10)

Rules file (TSV, '#' comments): id, class (comma list: sword,crossbow,unarmed,take,all), rule, source, owner
(shay | coord | native | inferred), checks (comma list of check ids; '-' none), status (covered | partial | missing |
out-of-reach), note. Owner `native` = thresholds/shape measured on the game's own animations (Shay 2026-10-10: "use the
native in-game animations to guide you"; numbers in the note + STATUS.md "Native reference"): a hard rule.
Owner `inferred` = a rule nobody has confirmed yet: its verdict is reported apart (questions for the owner).
Checks file (JSON): {"vars": {name: value}, "checks": {id: {"cmd": template, "line": regex, "fail": regex,
"num": [field, "max"|"min", limit], "pass": regex}}}. Template fields: {rec}, {L} (this directory), {vars}, item options
({pre}, {ref}, {mode}, ...; missing options expand to ''). A check FAILS when the first output line matching `line`
matches `fail` (or `num` is out of limit, or `pass` does not match); no matching line = ERROR (not a verdict).
Docs: docs/animlab/USAGE.md "Spec and taste".
"""
import argparse, json, math, os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---------------------------------------------------------------- rules / checks files

def read_rules(path):
    R = []
    with open(path, encoding='utf-8') as fh:
        lines = fh.readlines()
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        c = (line.rstrip('\n').split('\t') + [''] * 8)[:8]
        if c[0] == 'id':
            continue
        R.append(dict(id=c[0], cls=[x.strip() for x in c[1].split(',') if x.strip()], rule=c[2], source=c[3], owner=c[4],
                      checks=[x.strip() for x in c[5].split(',') if x.strip() and x.strip() != '-'], status=c[6], note=c[7]))
    return R


def read_checks(path):
    with open(path, encoding='utf-8') as fh:
        d = json.load(fh)
    return d.get('vars', {}), d['checks']


class _Fmt(dict):
    def __missing__(self, k):
        return ''


_CACHE = {}


def run_cmd(cmd, cache_dir=None):
    """run a shell command once per process (and per cache_dir key across runs); returns stdout+stderr text."""
    if cmd in _CACHE:
        return _CACHE[cmd]
    key = None
    if cache_dir:
        import hashlib
        files = [w for w in shlex.split(cmd) if os.path.isfile(w)]
        h = hashlib.sha1((cmd + '|' + '|'.join('%s:%d:%d' % (f, os.path.getsize(f), int(os.path.getmtime(f))) for f in files)).encode()).hexdigest()
        key = os.path.join(cache_dir, h + '.txt')
        if os.path.exists(key):
            _CACHE[cmd] = open(key, encoding='utf-8').read()
            return _CACHE[cmd]
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    out = p.stdout
    _CACHE[cmd] = out
    if key:
        os.makedirs(cache_dir, exist_ok=True)
        with open(key, 'w', encoding='utf-8') as f:
            f.write(out)
    return out


def run_check(cid, spec, rec, opts, vars_, cache_dir=None):
    """-> (verdict PASS|FAIL|ERROR, evidence line)."""
    f = _Fmt(vars_)
    f.update(L=HERE, rec=rec)
    f.update(opts)
    cmd = spec['cmd'].format_map(f)
    out = run_cmd(cmd, cache_dir)
    rx = re.compile(spec.get('line', '.'))
    line = next((l for l in out.splitlines() if rx.search(l)), None)
    if line is None:
        return 'ERROR', 'no line /%s/ from: %s | %s' % (spec.get('line'), cmd, out.strip().splitlines()[-1:] or '')
    bad = False
    if spec.get('fail') and re.search(spec['fail'], line):
        bad = True
    if spec.get('pass') and not re.search(spec['pass'], line):
        bad = True
    if spec.get('num'):
        fld, how, lim = spec['num']
        m = re.search(r'\b%s=([-0-9.]+)' % re.escape(fld), line)
        if not m:
            return 'ERROR', 'no %s= in: %s' % (fld, line)
        v = float(m.group(1))
        bad = bad or (v > lim if how == 'max' else v < lim)
    return ('FAIL' if bad else 'PASS'), line.strip()


# ---------------------------------------------------------------- recording checks (sword / crossbow)

REST_STATES = ('ready', 'block', 'swing->block')
REST_EDGE_P05 = 0.0     # S1 (Shay): the sword edge never faces the camera at rest: p05 of cos(edge, eye->wrist) per rest state
STILL_JIT = 1.5         # X1 (Shay): crossbow shakes in still poses; aim jit_p95 px (accepted 0.9-1.0, rejected vmq-f8c 2.1)
WB_HOLD, WB_SWING = 30.0, 50.0   # PT17-W / PT30 holds; swings 50 (Shay accepted E1 wb36; metrics.ARC_WB)


def _states(rec):
    import recfmt, metrics as M
    P = M.frame_metrics(recfmt.parse(rec))
    by = {}
    for p in P:
        if p['state'] in ('off',) or not p['wih']:
            continue
        by.setdefault(p['state'], []).append(p)
    return M, by


def restedge(rec, p05=REST_EDGE_P05, states=REST_STATES, min_n=10):
    M, by = _states(rec)
    ok, parts = True, []
    for s in states:
        ps = by.get(s, [])
        if len(ps) < min_n:
            continue
        v = M.pct([p['edge'] for p in ps], .05)
        b = v < p05
        ok = ok and not b
        parts.append('%s:p05=%.2f/%.2f,n=%d%s' % (s, v, p05, len(ps), ':BAD' if b else ''))
    if not parts:
        return False, 'no rest frames:BAD'
    return ok, ' '.join(parts)


def stilljit(rec, states=('aim',), lim=STILL_JIT, min_n=20):
    M, by = _states(rec)
    ok, parts = True, []
    for s in states:
        js = [p['jit'] for p in by.get(s, []) if p['jit'] is not None]
        if len(js) < min_n:
            parts.append('%s:n=%d(skip)' % (s, len(js)))
            continue
        v = M.pct(js, .95)
        b = v > lim
        ok = ok and not b
        parts.append('%s:jit_p95=%.2f/%.1f%s' % (s, v, lim, ':BAD' if b else ''))
    if not any('jit_p95' in x for x in parts):
        return False, ' '.join(parts) + ' no still state measured:BAD'
    return ok, ' '.join(parts)


def wrist(rec, hold=WB_HOLD, swing=WB_SWING):
    M, by = _states(rec)
    ok, parts = True, []
    for s, ps in by.items():
        if s in M.NATIVE_STATES or s == 'settle':   # Shay 2026-10-10: native-animation frames are exempt from the limit
            continue
        wb = [p['wb'] for p in ps if p['wb'] is not None]
        if not wb:
            continue
        lim = swing if s == 'swing' else hold
        v = max(wb)
        b = v > lim
        ok = ok and not b
        parts.append('%s:wb_max=%.1f/%.0f%s' % (s, v, lim, ':BAD' if b else ''))
    return ok, ' '.join(sorted(parts)) or 'no wrist data'


# R17 blade, NATIVE REFERENCE (Shay 2026-10-10: "use the native in-game animations to guide you"). Measured on the game's
# own katana attacks (native.py trajectory, katana, anchor fit, torso stab, 30 fps x the technique's anim speed mult;
# numbers in docs/animlab/STATUS.md "Native reference"): rotation per 33 ms video frame after the wind-up top 7-32 deg
# (downward combo 32 @1.2, chop down 15, bigchopv2 14, heavy downcut 10, desperate attack 7; chop left 47 starts AT the
# top, its first frames are the engine's crossfade from the stance: not counted); the follow-through passes near edge-on
# (on-screen visible blade < 0.05) for up to two video frames in the enabled attacks (bigchopv2 67 ms seen 0.038,
# desperate attack 33 ms seen 0.001, downward combo / heavy downcut 0; the disabled chop down 100 ms, chop down static
# 533 ms in its resting tail). So: snap <= 32, and an end-on stretch (on-screen visible blade < 0.05, or a facing sign
# change between two frames) lasts at most 67 ms (two 30 fps video frames).
NAT_SNAP, NAT_SEEN, NAT_RUN = 32.0, 0.05, 0.067   # deg per 33 ms; visible blade; s


def blade_native(F, P, snap_max=NAT_SNAP, see_min=NAT_SEEN, run_max=NAT_RUN):
    """per swing: snap (as metrics.blade_check) and the longest end-on stretch over u .45-.95 (on-screen frames only:
    a blade out of view is stroke.len's business). A run = consecutive frames below see_min; its length in time is
    last - first + one frame interval; a facing sign change between frames counts as a one-frame run."""
    import metrics as M
    ws, wr, ok, txt = None, None, True, []
    for k, idx in enumerate(M.swings(F, P)):
        rate = []
        for n, i in enumerate(idx):
            j = n
            while j > 0 and F[idx[n]]['t'] - F[idx[j - 1]]['t'] <= M.SNAP_WIN:
                j -= 1
            if j < n:
                rate.append((F[i]['swu'], M.blade_rot(P[idx[j]], P[i]), i))
        top = [r for r in rate if M.ARC_U0 - 0.1 <= r[0] <= M.ARC_U0 + 0.12]
        if top:
            ut = min(top, key=lambda r: r[1])[0]
            mx = max((r for r in rate if ut <= r[0] <= ut + M.SNAP_U), key=lambda r: r[1])
            if ws is None or mx[1] > ws[1]:
                ws = (k, mx[1], mx[0])
        g = [(M.blade_seen(P[i]), F[i]['t'], F[i]['swu']) for i in idx if M.SEE_U0 <= F[i]['swu'] <= M.SEE_U1]
        dt = min((g[n + 1][1] - g[n][1] for n in range(len(g) - 1)), default=1 / 60.0)
        best, run0, prev = (0.0, None, 1.0), None, None
        for n, (s, t, u) in enumerate(g):
            low = s[1] > 0 and s[0] < see_min
            flip = prev is not None and s[1] > 0 and prev[2] * s[2] < 0
            if low:
                run0 = run0 if run0 is not None else t
                ln = t - run0 + dt
                if ln > best[0]:
                    best = (ln, u, s[0])
            else:
                run0 = None
                if flip and dt > best[0]:
                    best = (dt, u, 0.0)
            prev = s
        if best[1] is not None and (wr is None or best[0] > wr[1]):
            wr = (k, best[0], best[1], best[2])
    if ws:
        b = ws[1] > snap_max; ok = ok and not b
        txt.append('snap=%.0f/%.0f%s@swing%d,u=%.2f' % (ws[1], snap_max, ':BAD' if b else '', ws[0], ws[2]))
    else:
        ok = False; txt.append('snap=n/a(no swing):BAD')
    if wr:
        b = wr[1] > run_max + 1e-6; ok = ok and not b
        txt.append('endon=%.0fms/%.0f%s@swing%d,u=%.2f,seen=%.3f' % (wr[1] * 1000, run_max * 1000, ':BAD' if b else '', wr[0], wr[2], wr[3]))
    else:
        txt.append('endon=0ms/%.0f' % (run_max * 1000))
    return ok, ' '.join(txt)


def blade_rec(rec, snap_max=NAT_SNAP, see_min=NAT_SEEN, run_max=NAT_RUN):
    import recfmt, metrics as M
    r = recfmt.parse(rec)
    return blade_native(r.frames, M.frame_metrics(r), snap_max, see_min, run_max)


# ---------------------------------------------------------------- unarmed spec (fist candidates, metricslab pose.txt)

ARM = ('sh', 'el', 'wr', 'hx', 'pp', 'pf', 'pu')
TX, TY = 1.245, 0.70          # screen half-extent tangents (16:9, KenshiFP fov; = native.py _onscr)
W, H = 1600, 900
# Unarmed limits. NATIVE REFERENCE (Shay 2026-10-10: the game's own unarmed animations guide the inferred rules): measured
# with these same checks on the native clips (native.py trajectory, target hand, pelvis stab, shoulder anchor on the FP
# body, 30 fps x the technique's anim speed mult); numbers per rule in docs/animlab/STATUS.md "Native reference".
#   U1 guard_y 0: native stance hands are below the eye (ma idle1 wrists y -3.8 / -8.5 dm) -> FP guard in the lower half
#   U4 center x .30, y -.35..+.05: native strikes land at |x/z| <= .29, y/z -.28..-.09 (at / below the centre)
#   U6 windup_rise 0.1: native wrist/fist is highest AT the strike, the wind-up never rises above it (rise 0.00, all)
#   U10 wshare .45: native striking hands .04-.41 (palm strikes .40/.41, straight punches .04-.25)
#   U11 twist 40: native fist roll per 33 ms on straight-wrist frames (wb <= 30) up to 37 (ma 2strike L)
U = dict(near=3.0, eye_min=2.5, above_max=0.5, center=(0.30, 0.35), center_y=(-0.35, 0.05), guard_y=0.0, wb_max=30.0,
         ret=0.5, move_dm=1.0, strike_min=1.5, rev=450.0, grip_px=250.0, win=0.4, wshare=0.45, twist=40.0, twist_dt=1 / 30.0,
         twist_wb=30.0, windup_rise=0.1, strike_band=0.5,
         xel_max=30.0, pcam_max=0.0, pup_max=0.2, pfwd_max=0.6, pcam_guard=0.0, cross_px=250.0, knuckle=1.2, contact_band=0.05)
# U19/U20 hand frame: KenshiFP prop convention for the weapon-class-0 target (visual.json prop_axes/prop_local_q/
# prop_roll_deg/prop_mirror, as render.py Rig.pose): hand axes = Rp Rl^T in render's flipped space (x negated)
PROP = dict(axes=(2, 3), q=(0.600, 0.267, 0.724, -0.211), roll=60.0,
            mirror={'L': dict(q_sign=(1, -1, -1, 1), roll_sign=-1, roll_add=180)})


def read_pose(path):
    F = []
    with open(path) as fh:
        lines = fh.readlines()
    for line in lines:
        if line.startswith('#') or '|' not in line:
            continue
        pa = [x.strip() for x in line.split('|')]
        h = pa[0].split()
        r = dict(i=int(h[0]), t=float(h[1]))
        for side, blk in (('L', pa[1]), ('R', pa[2])):
            v = [tuple(float(c) for c in x.split(',')) for x in blk.split()]
            r[side] = dict(zip(ARM, v))
        st = pa[3].split()
        r['ikfail'] = int(st[2]) if len(st) > 2 else 0
        F.append(r)
    return F


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _ln(a): return math.sqrt(_dot(a, a))


def _ang(a, b):
    la, lb = _ln(a), _ln(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(a, b) / la / lb))))


def _onscr(c, near=3.0, m=1.0):
    return c[2] > near and abs(c[0] / c[2]) < TX * m and abs(c[1] / c[2]) < TY * m


def _px(c):
    return (W / 2 + W / 2 * (c[0] / c[2]) / TX, H / 2 - H / 2 * (c[1] / c[2]) / TY)


def _d2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _vis_forearm(el, wr, near):
    """the forearm point nearest the elbow that is on screen (the visible forearm end), or None."""
    for k in range(11):
        c = _add(el, _mul(_sub(wr, el), k / 10.0))
        if _onscr(c, near):
            return _px(c)
    return None


def set_prop(visual_json):
    """load the class-0 prop convention from a visual.json (KenshiFP: components/KenshiFP/animlab/visual.json)."""
    with open(visual_json) as fh:
        v = json.load(fh)
    PROP.update(axes=tuple(v['prop_axes'][0]), q=tuple(v['prop_local_q']['0']),
                roll=float((v.get('prop_roll_deg') or {}).get('0', 0.0)), mirror=v.get('prop_mirror') or {})


def _qmat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def _mm(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _tr(A):
    return tuple(tuple(A[j][i] for j in range(3)) for i in range(3))


def _axis(code):
    v = [0.0, 0.0, 0.0]; v[abs(code) - 1] = 1.0 if code > 0 else -1.0
    return tuple(v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _nz(a):
    n = _ln(a)
    return _mul(a, 1.0 / n) if n > 1e-9 else a


def hand_axes(A, side):
    """(hand X, hand Z) in camera numbers from one side's prop target (pf, pu), as the game/render poses the hand bone."""
    fl = lambda v: (-v[0], v[1], v[2])
    Fv = _nz(fl(A['pf'])); pu = fl(A['pu'])
    Uv = _nz(_sub(pu, _mul(Fv, _dot(pu, Fv)))); Tv = _cross(Fv, Uv)
    fa, ua = _axis(PROP['axes'][0]), _axis(PROP['axes'][1]); th = _cross(fa, ua)
    Rp = _mm(_tr((Fv, Uv, Tv)), _tr(_tr((fa, ua, th))))
    q, roll = list(PROP['q']), PROP['roll']
    mq = (PROP.get('mirror') or {}).get(side)
    if mq:
        q = [a * b for a, b in zip(q, mq.get('q_sign', (1, 1, 1, 1)))]
        roll = roll * float(mq.get('roll_sign', 1)) + float(mq.get('roll_add', 0))
    Rl = _qmat(q)
    if roll:
        k = fa; r = math.radians(roll); sn, cs = math.sin(r), 1 - math.cos(r)
        K = ((0, -k[2], k[1]), (k[2], 0, -k[0]), (-k[1], k[0], 0)); KK = _mm(K, K)
        Rl = _mm(Rl, tuple(tuple((1.0 if i == j else 0.0) + sn * K[i][j] + cs * KK[i][j] for j in range(3)) for i in range(3)))
    Rh = _mm(Rp, _tr(Rl))
    col = lambda j: fl((Rh[0][j], Rh[1][j], Rh[2][j]))
    return col(0), col(2)



def prop_from_hand(hx, palm, side):
    """inverse of hand_axes: the prop target (pf, pu) that poses the hand with X = hx and the palm (-Z) toward palm."""
    fl = lambda v: (-v[0], v[1], v[2])
    X = _nz(fl(hx)); Z = _mul(fl(palm), -1.0)
    Z = _nz(_sub(Z, _mul(X, _dot(Z, X)))); Y = _cross(Z, X)
    Rh = _tr((X, Y, Z))
    fa, ua = _axis(PROP['axes'][0]), _axis(PROP['axes'][1])
    q, roll = list(PROP['q']), PROP['roll']
    mq = (PROP.get('mirror') or {}).get(side)
    if mq:
        q = [a * b for a, b in zip(q, mq.get('q_sign', (1, 1, 1, 1)))]
        roll = roll * float(mq.get('roll_sign', 1)) + float(mq.get('roll_add', 0))
    Rl = _qmat(q)
    if roll:
        k = fa; r = math.radians(roll); sn, cs = math.sin(r), 1 - math.cos(r)
        K = ((0, -k[2], k[1]), (k[2], 0, -k[0]), (-k[1], k[0], 0)); KK = _mm(K, K)
        Rl = _mm(Rl, tuple(tuple((1.0 if i == j else 0.0) + sn * K[i][j] + cs * KK[i][j] for j in range(3)) for i in range(3)))
    Rp = _mm(Rh, Rl)
    ap = lambda M, v: tuple(sum(M[i][j] * v[j] for j in range(3)) for i in range(3))
    return fl(ap(Rp, fa)), fl(ap(Rp, ua))

def hand_metrics(A, side):
    """xel: hand X elevation above the eye->wrist sight line (deg; high = the hand stands up and the fixed half-open
    fingers curl toward the camera: a palm-up reach); pcam: palm normal (-hand Z) toward the camera (> 0 = palm + open
    fingers shown = claw); pup: palm normal up; pfwd: palm normal along the sight line (palm-heel strike)."""
    hx, hz = hand_axes(A, side)
    ray = _nz(A['wr'])
    pn = _mul(hz, -1.0)
    xel = math.degrees(math.asin(max(-1.0, min(1.0, hx[1])))) - math.degrees(math.asin(max(-1.0, min(1.0, ray[1]))))
    return dict(xel=xel, pcam=-_dot(pn, ray), pup=pn[1], pfwd=_dot(pn, ray), hx=hx, pn=pn)


def arm_px(A, near, knuckle=1.2):
    """screen polyline (px) of the visible forearm + hand: elbow->wrist sampled, then wrist->knuckles along hand X."""
    pts = [_add(A['el'], _mul(_sub(A['wr'], A['el']), v / 10.0)) for v in range(11)] + [_add(A['wr'], _mul(_nz(A['hx']), knuckle))]
    return [_px(p) for p in pts if p[2] > near and abs(p[0] / p[2]) < TX * 1.2 and abs(p[1] / p[2]) < TY * 1.2]


def _seg_x(p, q, r, s):
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    if abs(d) < 1e-9:
        return False
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    v = ((r[0] - p[0]) * (q[1] - p[1]) - (r[1] - p[1]) * (q[0] - p[0])) / d
    return 0.0 <= t <= 1.0 and 0.0 <= v <= 1.0


def _pt_seg(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]; L = ax * ax + ay * ay
    t = 0.0 if L < 1e-9 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L))
    return math.hypot(p[0] - a[0] - t * ax, p[1] - a[1] - t * ay)


def _poly_dist(pts, poly):
    """min px distance from points to a polyline (1e9 when either is off screen)."""
    if not pts or len(poly) < 2:
        return 1e9
    return min(_pt_seg(p, poly[j], poly[j + 1]) for p in pts for j in range(len(poly) - 1))


def _poly_cross(a, b):
    return any(_seg_x(a[i], a[i + 1], b[j], b[j + 1]) for i in range(len(a) - 1) for j in range(len(b) - 1))


def unarmed_checks(F, strikers=None, c=U, name=''):
    """unarmed spec rows on a solved both-arm path. Returns [(rule id, PASS|FAIL|INFO, text)]."""
    F = [f for f in F if f['t'] >= 0.0]
    if len(F) < 5:
        return [('U0', 'FAIL', 'pose has %d frames >= t 0' % len(F))]
    T = [f['t'] for f in F]
    dur = max(T[-1], 1e-6)
    u = [t / dur for t in T]
    res = []
    sides = ('L', 'R')
    if strikers is None:   # a hand whose wrist moves >= strike_min forward of its start
        strikers = [s for s in sides if max(f[s]['wr'][2] for f in F) - F[0][s]['wr'][2] >= c['strike_min']]
    # U1 both fists on screen in the guard (start / end)
    gk = [k for k in range(len(F)) if u[k] <= .02 or u[k] >= .98]
    off = ['%s@%.2f' % (s, u[k]) for k in gk for s in sides if not (_onscr(F[k][s]['wr'], c['near'], .95) and _onscr(F[k][s]['pp'], c['near'], .95))]
    hi = ['%s@%.2f' % (s, u[k]) for k in gk for s in sides if max(F[k][s]['wr'][1], F[k][s]['pp'][1]) > c['guard_y']]
    gy = max([max(F[k][s]['wr'][1], F[k][s]['pp'][1]) for k in gk for s in sides] or [0.0])
    res.append(('U1', 'FAIL' if off or hi or not gk else 'PASS', 'guard: both fists on screen, below the eye line at u<=.02/>=.98 (%d frames, highest y %.2f dm <= %.1f)%s%s' % (
        len(gk), gy, c['guard_y'], ' off=' + ','.join(off[:6]) if off else '', ' high=' + ','.join(hi[:6]) if hi else '')))
    # U2 returns to the guard
    dd = max(_ln(_sub(F[-1][s]['wr'], F[0][s]['wr'])) for s in sides)
    res.append(('U2', 'PASS' if dd <= c['ret'] else 'FAIL', 'return to guard: end wrist vs start %.2f dm (<= %.1f)' % (dd, c['ret'])))
    # U3 state visibly plays: some hand moves >= move_dm from its start
    mv = {s: max(_ln(_sub(f[s]['pp'], F[0][s]['pp'])) for f in F) for s in sides}
    res.append(('U3', 'PASS' if max(mv.values()) >= c['move_dm'] else 'FAIL', 'moves: fist travel L %.1f R %.1f dm (>= %.1f)' % (mv['L'], mv['R'], c['move_dm'])))
    # U4 the striking fist reaches the view centre
    cx, cy = c['center']
    if not strikers:
        res.append(('U4', 'FAIL', 'no striking hand (wrist forward travel < %.1f dm)' % c['strike_min']))
    for s in strikers:
        k = min(range(len(F)), key=lambda k: abs(F[k][s]['pp'][0] / max(F[k][s]['pp'][2], 1e-3)) + abs(F[k][s]['pp'][1] / max(F[k][s]['pp'][2], 1e-3)))
        pp = F[k][s]['pp']
        sx, sy = pp[0] / pp[2], pp[1] / pp[2]
        y0, y1 = c.get('center_y') or (-cy, cy)
        okc = abs(sx) <= cx and y0 <= sy <= y1 and pp[2] > c['near']
        res.append(('U4', 'PASS' if okc else 'FAIL', 'strike %s: fist nearest the centre x/z %.2f y/z %.2f @u%.2f (|x|<=%.2f, y %.2f..%.2f)' % (s, sx, sy, u[k], cx, y0, y1)))
    # U5 clear of the eye: forearm/fist >= eye_min from the eye, never above eye level + above_max
    emin, top, topat = 1e9, -1e9, ''
    for k, f in enumerate(F):
        for s in sides:
            A = f[s]
            for p in [_add(A['el'], _mul(_sub(A['wr'], A['el']), v)) for v in (.5, .75, 1.0)] + [_add(A['wr'], _mul(_sub(A['pp'], A['wr']), v)) for v in (.5, 1.0)]:
                emin = min(emin, _ln(p))
            for p in (A['wr'], A['pp']):
                if p[1] > top:
                    top, topat = p[1], '%s@%.2f' % (s, u[k])
    res.append(('U5', 'PASS' if emin >= c['eye_min'] and top <= c['above_max'] else 'FAIL',
                'eye: forearm/fist min distance %.2f dm (>= %.1f), highest wrist/fist y %.2f dm @%s (<= %.1f)' % (emin, c['eye_min'], top, topat, c['above_max'])))
    # U6 (native reference) wind-up not above the strike: strike frames = the first stretch with the wrist within strike_band
    # dm of its furthest forward reach; the wrist/fist before it never rises more than windup_rise above the strike's
    # highest point (native: highest AT the strike in every clip). Hands at the head stay U5's (eye level + above_max).
    for s in strikers:
        hk = lambda k: max(F[k][s]['wr'][1], F[k][s]['pp'][1])
        zmax = max(f[s]['wr'][2] for f in F)
        k0 = next(k for k in range(len(F)) if F[k][s]['wr'][2] >= zmax - c['strike_band'])
        k1 = k0
        while k1 + 1 < len(F) and F[k1 + 1][s]['wr'][2] >= zmax - c['strike_band']:
            k1 += 1
        sh = max(hk(k) for k in range(k0, k1 + 1))
        if k0 == 0:
            res.append(('U6', 'PASS', 'wind-up %s: none (strike from the first frame)' % s))
            continue
        wu = max((hk(k), k) for k in range(k0))
        res.append(('U6', 'PASS' if wu[0] - sh <= c['windup_rise'] else 'FAIL', 'wind-up %s: highest wrist/fist y %.2f dm @u%.2f vs strike %.2f (u%.2f-%.2f): rise %.2f (<= %.1f)' % (
            s, wu[0], u[wu[1]], sh, u[k0], u[k1], wu[0] - sh, c['windup_rise'])))
    # U7 near-plane cut
    cut = sorted(set('%s@%.2f' % (s, u[k]) for k, f in enumerate(F) for s in sides
                     for p in [_add(f[s]['el'], _mul(_sub(f[s]['wr'], f[s]['el']), v)) for v in (.5, .75, 1.0)] + [_add(f[s]['wr'], _mul(_sub(f[s]['pp'], f[s]['wr']), v)) for v in (.5, 1.0)]
                     if abs(p[0] / max(p[2], 1e-3)) < TX * .95 and abs(p[1] / max(p[2], 1e-3)) < TY * .95 and 0.05 < p[2] < c['near']))
    res.append(('U7', 'PASS' if not cut else 'FAIL', 'near-plane cut: %d frames%s' % (len(cut), ' at ' + ','.join(cut[:6]) if cut else '')))
    # U8 wrist limit (forearm vs hand X axis, as metrics wb)
    wb = {s: max((_ang(_sub(f[s]['wr'], f[s]['el']), f[s]['hx']), u[k]) for k, f in enumerate(F)) for s in sides}
    res.append(('U8', 'PASS' if all(v[0] <= c['wb_max'] for v in wb.values()) else 'FAIL',
                'wrist: wb_max ' + ' '.join('%s %.1f@u%.2f' % (s, wb[s][0], wb[s][1]) for s in sides) + ' (<= %.0f)' % c['wb_max']))
    # U9 no arm churn: visible forearm end out-and-back > rev px within win s while the fist moves <= grip_px
    worst = (0.0, '')
    for s in sides:
        E = [(f['t'], _vis_forearm(f[s]['el'], f[s]['wr'], c['near']), _px(f[s]['pp']) if f[s]['pp'][2] > 0.5 else None) for f in F]
        for a in range(len(E)):
            b = a
            while b + 1 < len(E) and E[b + 1][0] - E[a][0] <= c['win']:
                b += 1
            seg = [e for e in E[a:b + 1] if e[1] is not None and e[2] is not None]
            if len(seg) < 3:
                continue
            ea, eb = seg[0][1], seg[-1][1]
            rev = max(_d2(e[1], ea) + _d2(e[1], eb) for e in seg) - _d2(ea, eb)
            ext = max(_d2(e[2], seg[0][2]) for e in seg)
            if ext <= c['grip_px'] and rev > worst[0]:
                worst = (rev, '%s@u%.2f fist=%.0fpx' % (s, E[a][0] / dur, ext))
    res.append(('U9', 'PASS' if worst[0] <= c['rev'] else 'FAIL', 'churn: forearm out-and-back %.0f px %s (<= %.0f while the fist moves <= %.0f px)' % (worst[0], worst[1], c['rev'], c['grip_px'])))
    # U10 arm-driven strike: share of fist motion that comes from the wrist (vs a fist rigid on the forearm), strikers
    for s in strikers:
        num = den = 0.0
        for k in range(1, len(F)):
            a, b = F[k - 1][s], F[k][s]
            dp = _sub(b['pp'], a['pp'])
            fa, fb = _sub(a['wr'], a['el']), _sub(b['wr'], b['el'])
            # fist carried rigidly by the forearm: previous wrist->fist offset turned with the forearm direction
            rig = _add(b['wr'], _rot(fa, fb, _sub(a['pp'], a['wr'])))
            num += _ln(_sub(b['pp'], rig))
            den += _ln(dp)
        sh = num / den if den > 1e-6 else 0.0
        res.append(('U10', 'PASS' if sh <= c['wshare'] else 'FAIL', 'arm-driven %s: wrist share of fist motion %.2f (<= %.2f)' % (s, sh, c['wshare'])))
    # U11 no sudden fist roll: twist of the hand's prop up axis about the forearm per video frame (33 ms); hand X runs
    # along the forearm (wb ~0 on a straight wrist), so it cannot measure the roll
    tw = (0.0, '')
    for s in sides:
        for k in range(1, len(F)):
            j = k
            while j > 0 and F[k]['t'] - F[j - 1]['t'] <= c['twist_dt'] + 1e-6:
                j -= 1
            if j == k:
                continue
            if max(_ang(_sub(F[i][s]['wr'], F[i][s]['el']), F[i][s]['hx']) for i in (j, k)) > c['twist_wb']:
                continue   # a bent wrist tilts the prop axis without a roll (U8 judges the bend)
            x0, x1 = _perp(F[j][s]['pu'], _sub(F[j][s]['wr'], F[j][s]['el'])), _perp(F[k][s]['pu'], _sub(F[k][s]['wr'], F[k][s]['el']))
            a = _ang(x0, x1)
            if a > tw[0]:
                tw = (a, '%s@u%.2f' % (s, u[k]))
    res.append(('U11', 'PASS' if tw[0] <= c['twist'] else 'FAIL', 'fist roll: max %.1f deg per 33 ms %s (<= %.0f, straight-wrist frames)' % (tw[0], tw[1], c['twist'])))
    # U17 (Shay 2026-10-10): palm-heel techniques become straight-wrist punches (wrist <= 30 on every frame); the native palm
    # strike (bent-back wrist, palm forward) is not kept. A palm technique is recognised by its name (shotei / palm).
    if re.search(r'(?i)shotei|palm', name or ''):
        res.append(('U17', 'PASS' if all(v[0] <= c['wb_max'] for v in wb.values()) else 'FAIL',
                    'palm-heel as a straight-wrist punch: wb_max ' + ' '.join('%s %.1f@u%.2f' % (s, wb[s][0], wb[s][1]) for s in sides) + ' (<= %.0f)' % c['wb_max']))
    # U18-U21 (review 2026-10-10: open claws, palm-up reach at contact, forearm crossing the other hand). Fist closure
    # is out of reach: the game skeleton has no finger bones and the body mesh's poses are face morphs only, so the hand
    # is the fixed half-open mesh in the game too; what FP controls is the hand frame, judged here (hand Z = palm side,
    # from the prop target through the KenshiFP prop convention, visual.json).
    res.append(('U18', 'INFO', 'fist closure: not controllable (no finger bones; mesh poses are face-only): hand frame judged by U19/U20'))
    for s in strikers:
        cd = [abs(F[k][s]['pp'][0] / max(F[k][s]['pp'][2], 1e-3)) + abs(F[k][s]['pp'][1] / max(F[k][s]['pp'][2], 1e-3)) for k in range(len(F))]
        ks = [k for k in range(len(F)) if cd[k] <= min(cd) + c['contact_band']]   # contact = the fist at the view centre (U4)
        worst = None
        for k in ks:
            m = hand_metrics(F[k][s], s)
            bad = (m['xel'] - c['xel_max']) / 10.0 + 10 * (max(0.0, m['pcam'] - c['pcam_max']) + max(0.0, m['pup'] - c['pup_max'])
                                                         + max(0.0, m['pfwd'] - c['pfwd_max']))
            if worst is None or bad > worst[0]:
                worst = (bad, k, m)
        _, k, m = worst
        ok = m['xel'] <= c['xel_max'] and m['pcam'] <= c['pcam_max'] and m['pup'] <= c['pup_max'] and m['pfwd'] <= c['pfwd_max']
        res.append(('U19', 'PASS' if ok else 'FAIL', 'knuckles lead at contact %s (u%.2f-%.2f, worst @u%.2f): hand X over the sight line %+.0f deg (<= %.0f), '
                    'palm to camera %+.2f (<= %.2f), palm up %+.2f (<= %.2f), palm forward %+.2f (<= %.2f)' % (
                        s, u[ks[0]], u[ks[-1]], u[k], m['xel'], c['xel_max'], m['pcam'], c['pcam_max'], m['pup'], c['pup_max'], m['pfwd'], c['pfwd_max'])))
    gk = [k for k in range(len(F)) if u[k] <= .02 or u[k] >= .98]
    pg = max([(hand_metrics(F[k][s], s)['pcam'], '%s@u%.2f' % (s, u[k])) for k in gk for s in sides] or [(0.0, '-')])
    res.append(('U20', 'PASS' if pg[0] <= c['pcam_guard'] else 'FAIL', 'guard palm hidden: palm to camera max %+.2f %s (<= %.2f; a palm shown to the camera = open claw)' % (
        pg[0], pg[1], c['pcam_guard'])))
    cr = []
    for k, f in enumerate(F):
        a, b = arm_px(f['L'], c['near'], c['knuckle']), arm_px(f['R'], c['near'], c['knuckle'])
        dmin = min(_poly_dist(a[-3:], b), _poly_dist(b[-3:], a))
        if _poly_cross(a, b) or dmin < c['cross_px']:
            cr.append('@u%.2f(%.0fpx)' % (u[k], dmin))
    res.append(('U21', 'PASS' if not cr else 'FAIL', 'arms cross on screen (forearm+fist polylines intersect, or a fist within %.0f px of the other arm): %d frames%s' % (
        c['cross_px'], len(cr), ' ' + ','.join(cr[:6]) if cr else '')))
    ik = sum(f['ikfail'] for f in F)
    res.append(('U15', 'PASS' if not ik else 'FAIL', 'solver: ikfail frames %d' % ik))
    return res


def _perp(v, axis):
    n = _ln(axis)
    if n < 1e-9:
        return v
    a = _mul(axis, 1.0 / n)
    return _sub(v, _mul(a, _dot(v, a)))


def _rot(a, b, v):
    """rotate v by the minimal rotation taking direction a to direction b (Rodrigues)."""
    la, lb = _ln(a), _ln(b)
    if la < 1e-9 or lb < 1e-9:
        return v
    a, b = _mul(a, 1 / la), _mul(b, 1 / lb)
    ax = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    s, co = _ln(ax), _dot(a, b)
    if s < 1e-9:
        return v
    k = _mul(ax, 1 / s)
    kxv = (k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0])
    return _add(_add(_mul(v, co), _mul(kxv, s)), _mul(k, _dot(k, v) * (1 - co)))


def find_cands(paths):
    out = []
    for p in paths:
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isfile(os.path.join(p, 'pose.txt')):
            out.append(os.path.join(p, 'pose.txt'))
        elif os.path.isdir(p):
            for d in sorted(os.listdir(p)):
                if d.startswith('_'):   # helper runs (_cal, _guard), not techniques
                    continue
                q = os.path.join(p, d, 'pose.txt')
                if os.path.isfile(q):
                    out.append(q)
    return out


def cmd_unarmed(a):
    owners = {}
    if a.rules:
        for r in read_rules(a.rules):
            owners[r['id']] = r['owner']
    if getattr(a, 'visual', None):
        set_prop(a.visual)
    cands = find_cands(a.cand)
    if not cands:
        print('RESULT spec-unarmed FAIL no candidate pose.txt under %s' % ' '.join(a.cand))
        return 1
    allok = True
    for pose in cands:
        d = os.path.dirname(pose)
        name = os.path.basename(d) or pose
        strikers = None
        kj = os.path.join(d, 'keys.json')
        if os.path.isfile(kj):
            try:
                strikers = json.load(open(kj)).get('strikers')
            except ValueError:
                pass
        res = unarmed_checks(read_pose(pose), strikers, name=name)
        fails = {}
        for rid, v, txt in res:
            own = owners.get(rid, '?')
            print('%-4s %-5s [%s] %s' % (rid, v, own, txt))
            if v == 'FAIL':
                fails.setdefault(own, set()).add(rid)
        hard = sorted(set().union(*[v for k, v in fails.items() if k != 'inferred'])) if fails else []
        inf = sorted(fails.get('inferred', ()))
        ok = not hard and not inf
        allok = allok and ok
        print('RESULT spec-unarmed-%s %s fails=%s inferred_fails=%s %s' % (name, 'PASS' if ok else 'FAIL', ','.join(hard) or '-', ','.join(inf) or '-', pose))
    return 0 if allok else 1


# ---------------------------------------------------------------- map / run

def cmd_map(a):
    R = read_rules(a.rules)
    if a.md:
        print('| rule | class | source | owner | check ids | status |')
        print('|---|---|---|---|---|---|')
        for r in R:
            print('| %s %s | %s | %s | %s | %s | %s%s |' % (r['id'], r['rule'], ','.join(r['cls']), r['source'], r['owner'],
                                                          ','.join(r['checks']) or '-', r['status'], (': ' + r['note']) if r['note'] else ''))
    else:
        for r in R:
            print('%-5s %-13s %-12s %-9s %-40s %s' % (r['id'], r['status'], r['owner'], ','.join(r['cls']), ','.join(r['checks']) or '-', r['rule']))
    n = {}
    for r in R:
        n[r['status']] = n.get(r['status'], 0) + 1
    print('# rules=%d %s' % (len(R), ' '.join('%s=%d' % kv for kv in sorted(n.items()))))


def cmd_run(a):
    R = [r for r in read_rules(a.rules) if a.cls in r['cls'] or 'all' in r['cls']]
    vars_, C = read_checks(a.checks)
    opts = dict(x.split('=', 1) for x in a.set or [])
    allok = True
    for rec in a.rec:
        fails = []
        for r in R:
            for cid in r['checks']:
                if cid not in C:
                    continue
                v, ev = run_check(cid, C[cid], rec, opts, vars_, a.cache)
                print('%-5s %-14s %-5s [%s] %s' % (r['id'], cid, v, r['owner'], ev[:200]))
                if v != 'PASS':
                    fails.append('%s:%s' % (r['id'], cid))
            if not any(c in C for c in r['checks']):
                print('%-5s %-14s %-5s [%s] %s' % (r['id'], '-', r['status'].upper(), r['owner'], r['rule']))
        allok = allok and not fails
        print('RESULT spec-%s-%s %s fails=%s' % (a.cls, os.path.basename(rec), 'PASS' if not fails else 'FAIL', ','.join(fails) or '-'))
    return 0 if allok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('map'); p.add_argument('rules'); p.add_argument('--md', action='store_true')
    p = sp.add_parser('run'); p.add_argument('rules'); p.add_argument('rec', nargs='+'); p.add_argument('--checks', required=True)
    p.add_argument('--class', dest='cls', required=True); p.add_argument('--set', action='append'); p.add_argument('--cache')
    p = sp.add_parser('unarmed'); p.add_argument('cand', nargs='+'); p.add_argument('--rules'); p.add_argument('--visual', help='visual.json with the prop convention (default: KenshiFP numbers)')
    p = sp.add_parser('restedge'); p.add_argument('rec'); p.add_argument('--p05', type=float, default=REST_EDGE_P05)
    p = sp.add_parser('stilljit'); p.add_argument('rec'); p.add_argument('--states', default='aim'); p.add_argument('--max', type=float, default=STILL_JIT)
    p = sp.add_parser('wrist'); p.add_argument('rec'); p.add_argument('--hold', type=float, default=WB_HOLD); p.add_argument('--swing', type=float, default=WB_SWING)
    p = sp.add_parser('blade'); p.add_argument('rec'); p.add_argument('--snap', type=float, default=NAT_SNAP)
    p.add_argument('--seen', type=float, default=NAT_SEEN); p.add_argument('--run', type=float, default=NAT_RUN)
    p.add_argument('--only-stroke', dest='only_stroke', type=int)
    a = ap.parse_args()
    if getattr(a, 'only_stroke', None) is not None:
        import metrics as M
        M.STROKE_ONLY = a.only_stroke
    if a.cmd == 'map':
        return cmd_map(a)
    if a.cmd == 'run':
        return cmd_run(a)
    if a.cmd == 'unarmed':
        return cmd_unarmed(a)
    if a.cmd == 'restedge':
        ok, txt = restedge(a.rec, a.p05)
    elif a.cmd == 'stilljit':
        ok, txt = stilljit(a.rec, tuple(a.states.split(',')), a.max)
    elif a.cmd == 'wrist':
        ok, txt = wrist(a.rec, a.hold, a.swing)
    elif a.cmd == 'blade':
        ok, txt = blade_rec(a.rec, a.snap, a.seen, a.run)
    else:
        ap.print_help()
        return 2
    print('%s %s %s' % (a.cmd, 'PASS' if ok else 'FAIL', txt))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
