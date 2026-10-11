#!/usr/bin/env python3
"""mocapref.py -- openly licensed human motion capture (CMU ASF/AMC, BVH) as a REFERENCE for first-person viewmodel
motions: read the clip, re-express it as the first-person view sees it (torso-stabilised, FP camera numbers: x right,
y up, z forward, decimetres, the clip's shoulder placed on the FP body's shoulder and scaled to its arm length), find the
strikes / kicks / holds, and measure them with the same quantities the lab checks use (phase timing, wrist path, elbow
angle, wrist bend, wrist share, forearm roll rate, torso share, two-hand spacing). Docs: docs/animlab/USAGE.md
"Reference motion (mocap)".

Data is read only (untrusted input: plain-text parsing, nothing executed); no motion data lives in this repo.

  mocapref.py info    <clip> [--asf file.asf]                        skeleton, frames, fps, mapped joints
  mocapref.py measure <clip> [--asf A] [--kind strike|kick|hold|twohand] [--side R|L|auto] [--body REC --body-frame N]
                      [--from t --to t] [--json out.json] [--traj out.txt]
  clip = .amc (needs --asf, default <dir>/<subject>.asf) or .bvh
"""
import argparse, json, math, os, re, sys

import numpy as np

UP = np.array([0.0, 1.0, 0.0])
CMU_SCALE = (1.0 / 0.45) * 2.54 / 100.0   # ASF/AMC length units -> metres (CMU FAQ)


def nz(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _rx(a):
    c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


ROT = {'x': _rx, 'y': _ry, 'z': _rz}


def euler_xyz(ax, ay, az):   # ASF/AMC convention: v' = Rz Ry Rx v (degrees)
    return _rz(math.radians(az)) @ _ry(math.radians(ay)) @ _rx(math.radians(ax))


class Clip:
    """positions P[name] -> (n, 3) metres, world Y up; R[name] -> (n, 3, 3) world rotation of the joint's frame;
    fps; source tag. Names are the file's own; JOINTS maps them to the lab's roles."""
    def __init__(self, fps, P, R, src, roles):
        self.fps, self.P, self.R, self.src, self.roles = fps, P, R, src, roles
        self.n = len(next(iter(P.values())))
        self.t = np.arange(self.n) / float(fps)

    def p(self, role):
        return self.P[self.roles[role]]


# ---------------- CMU ASF / AMC ----------------
def read_asf(path):
    bones, hier, root = {}, {}, {}
    sec, cur = None, None
    with open(path, errors='replace') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith(':'):
                sec = line.split()[0][1:]
                if sec == 'root':
                    root = {}
                continue
            tok = line.split()
            if sec == 'root':
                root[tok[0]] = tok[1:]
            elif sec == 'bonedata':
                if tok[0] == 'begin':
                    cur = dict(dof=[], direction=np.zeros(3), length=0.0, axis=np.eye(3))
                elif tok[0] == 'end':
                    bones[cur['name']] = cur; cur = None
                elif cur is not None and tok[0] == 'name':
                    cur['name'] = tok[1]
                elif cur is not None and tok[0] == 'direction':
                    cur['direction'] = np.array([float(x) for x in tok[1:4]])
                elif cur is not None and tok[0] == 'length':
                    cur['length'] = float(tok[1])
                elif cur is not None and tok[0] == 'axis':
                    cur['axis'] = euler_xyz(*[float(x) for x in tok[1:4]])
                elif cur is not None and tok[0] == 'dof':
                    cur['dof'] = [x.lower() for x in tok[1:]]
            elif sec == 'hierarchy':
                if tok[0] in ('begin', 'end'):
                    continue
                hier[tok[0]] = tok[1:]
    return bones, hier, root


def read_amc(path):
    frames, cur = [], None
    with open(path, errors='replace') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#') or line.startswith(':'):
                continue
            if re.fullmatch(r'\d+', line):
                cur = {}; frames.append(cur); continue
            tok = line.split()
            if cur is not None:
                cur[tok[0]] = [float(x) for x in tok[1:]]
    return frames


CMU_ROLES = dict(pelvis='root', chest='lowerneck', neck='upperneck', head='head',
                 Rsh='rhumerus', Rel='rhumerus.end', Rwr='rwrist.end', Rhand='rfingers.end', Rthumb='rthumb.end',
                 Lsh='lhumerus', Lel='lhumerus.end', Lwr='lwrist.end', Lhand='lfingers.end', Lthumb='lthumb.end',
                 Rhip='rfemur', Rknee='rfemur.end', Rank='rtibia.end', Rtoe='rtoes.end',
                 Lhip='lfemur', Lknee='lfemur.end', Lank='ltibia.end', Ltoe='ltoes.end')


def load_amc(amc, asf=None, fps=None):
    if asf is None:
        d, b = os.path.split(amc)
        asf = os.path.join(d, b.split('_')[0] + '.asf')
    bones, hier, root = read_asf(asf)
    order = [x.lower() for x in root.get('order', ['TX', 'TY', 'TZ', 'RX', 'RY', 'RZ'])]
    rC = euler_xyz(*[float(x) for x in root.get('orientation', ['0', '0', '0'])])
    F = read_amc(amc)
    n = len(F)
    P, R = {}, {}

    def put(name, i, pos, rot):
        if name not in P:
            P[name] = np.zeros((n, 3)); R[name] = np.zeros((n, 3, 3))
        P[name][i] = pos; R[name][i] = rot

    for i, fr in enumerate(F):
        rv = fr.get('root', [0.0] * 6)
        val = dict(zip(order, rv))
        rpos = np.array([val.get('tx', 0.0), val.get('ty', 0.0), val.get('tz', 0.0)])
        rrot = rC @ euler_xyz(val.get('rx', 0.0), val.get('ry', 0.0), val.get('rz', 0.0)) @ rC.T
        put('root', i, rpos, rrot)
        stack = [('root', c) for c in hier.get('root', [])]
        while stack:
            par, name = stack.pop()
            b = bones[name]
            v = fr.get(name, [])
            ang = {'rx': 0.0, 'ry': 0.0, 'rz': 0.0}
            for k, x in zip(b['dof'], v):
                ang[k] = x
            C = b['axis']
            Rw = R[par][i] @ C @ euler_xyz(ang['rx'], ang['ry'], ang['rz']) @ C.T
            pstart = P[par + '.end'][i] if par != 'root' else P['root'][i]
            put(name, i, pstart, Rw)
            put(name + '.end', i, pstart + b['length'] * (Rw @ b['direction']), Rw)
            for c in hier.get(name, []):
                stack.append((name, c))
    for k in P:
        P[k] = P[k] * CMU_SCALE
    return Clip(fps or 120.0, P, R, 'cmu:' + os.path.basename(amc), CMU_ROLES)


# ---------------- BVH ----------------
def load_bvh(path, roles=None, unit=0.01):
    joints, stack, order = {}, [], []
    with open(path, errors='replace') as f:
        lines = f.read().split('\n')
    i = 0
    cur = None
    while i < len(lines):
        tok = lines[i].split()
        i += 1
        if not tok:
            continue
        if tok[0] in ('ROOT', 'JOINT'):
            cur = dict(name=tok[1], parent=stack[-1] if stack else None, offset=np.zeros(3), ch=[])
            joints[cur['name']] = cur; order.append(cur['name'])
        elif tok[0] == 'End':
            cur = dict(name=stack[-1] + '.end', parent=stack[-1], offset=np.zeros(3), ch=[])
            joints[cur['name']] = cur; order.append(cur['name'])
        elif tok[0] == '{':
            stack.append(cur['name'])
        elif tok[0] == '}':
            stack.pop()
        elif tok[0] == 'OFFSET':
            cur['offset'] = np.array([float(x) for x in tok[1:4]])
        elif tok[0] == 'CHANNELS':
            cur['ch'] = tok[2:2 + int(tok[1])]
        elif tok[0] == 'MOTION':
            break
    nfr = int(lines[i].split(':')[1]); ft = float(lines[i + 1].split(':')[1]); i += 2
    data = []
    while len(data) < nfr and i < len(lines):
        if lines[i].strip():
            data.append([float(x) for x in lines[i].split()])
        i += 1
    data = np.array(data)
    n = len(data)
    P = {k: np.zeros((n, 3)) for k in order}; R = {k: np.zeros((n, 3, 3)) for k in order}
    for fi in range(n):
        c = 0
        for k in order:
            j = joints[k]
            t = j['offset'].copy(); M = np.eye(3)
            for chn in j['ch']:
                v = data[fi, c]; c += 1
                ax = chn[0].lower()
                if chn.endswith('position'):
                    t['xyz'.index(ax)] = v
                else:
                    M = M @ ROT[ax](math.radians(v))
            if k.endswith('.end') and np.linalg.norm(t) < 1e-6:   # zero end site (Bandai hands/head): continue the
                pj = joints[j['parent']]['offset']                    # joint's own bone direction, 40% of its length
                t = 0.4 * pj
            if j['parent'] is None:
                P[k][fi] = t; R[k][fi] = M
            else:
                pr = R[j['parent']][fi]
                P[k][fi] = P[j['parent']][fi] + pr @ t; R[k][fi] = pr @ M
    for k in P:
        P[k] = P[k] * unit
    if roles is None:
        roles = BANDAI_ROLES if 'UpperArm_R' in joints else {}
    return Clip(1.0 / ft, P, R, 'bvh:' + os.path.basename(path), roles)


BANDAI_ROLES = dict(pelvis='Hips', chest='Chest', neck='Neck', head='Head.end',
                    Rsh='UpperArm_R', Rel='LowerArm_R', Rwr='Hand_R', Rhand='Hand_R.end',
                    Lsh='UpperArm_L', Lel='LowerArm_L', Lwr='Hand_L', Lhand='Hand_L.end',
                    Rhip='UpperLeg_R', Rknee='LowerLeg_R', Rank='Foot_R', Rtoe='Toes_R.end',
                    Lhip='UpperLeg_L', Lknee='LowerLeg_L', Lank='Foot_L', Ltoe='Toes_L.end')


def load(path, asf=None):
    return load_bvh(path) if path.lower().endswith('.bvh') else load_amc(path, asf)


# ---------------- first-person view of a clip ----------------
def chest_frame(c, i):
    """chest axes (columns: right, up, forward) at frame i; forward from right x up, sign fixed by the feet."""
    r = nz(c.p('Rsh')[i] - c.p('Lsh')[i])
    u = nz(c.p('neck')[i] - c.p('pelvis')[i]); u = nz(u - r * (u @ r))
    f = np.cross(r, u)
    toe = (c.p('Rtoe')[i] - c.p('Rank')[i]) + (c.p('Ltoe')[i] - c.p('Lank')[i])
    if f @ toe < 0:
        f = -f
    return np.stack([r, u, f], axis=1)


def cam_axes(c, i):
    """FP camera axes at frame i: right = horizontal shoulder line, up = world up (Y), forward = facing (feet sign)."""
    Cf = chest_frame(c, i)
    f = Cf[:, 2].copy(); f[1] = 0.0; f = nz(f)
    r = nz(np.cross(UP, f)) if np.cross(UP, f) @ Cf[:, 0] > 0 else -nz(np.cross(UP, f))
    return np.stack([r, UP, f], axis=0)   # rows: camera x, y, z in world


def arm_len(c, s, i=None):
    sh, el, wr = c.p(s + 'sh'), c.p(s + 'el'), c.p(s + 'wr')
    L1 = np.linalg.norm(el - sh, axis=1); L2 = np.linalg.norm(wr - el, axis=1)
    return float(np.median(L1)), float(np.median(L2))


def fp_view(c, t_ref=0, stab='torso', side='R', body=None):
    """per role: (n, 3) positions in FP camera numbers (dm) and hand axes. stab torso: every frame re-expressed in the
    chest frame at t_ref (lean/twist/steps drop out, as the fixed FP camera sees the arms); pelvis: ground travel of the
    pelvis removed (turns kept); world: as captured. The `side` shoulder at t_ref is moved onto the FP body's shoulder
    (body dict Rsh/Lsh, dm, or the origin) and all positions are scaled by FP arm length / clip arm length."""
    i0 = int(t_ref)
    A = cam_axes(c, i0)
    C0 = chest_frame(c, i0)
    ch = c.p('chest'); pv = c.p('pelvis')
    L1, L2 = arm_len(c, side)
    fpL = (body or {}).get('L', None)
    s = (fpL / (L1 + L2)) if fpL else 10.0   # metres -> dm when no body
    S = np.asarray((body or {}).get(side + 'sh', np.zeros(3)), float)
    out = {}
    roles = [r for r in c.roles if r not in ('Rhip', 'Lhip') or True]
    Ms = np.zeros((c.n, 3, 3)); org = np.zeros((c.n, 3))
    for i in range(c.n):
        if stab == 'torso':
            Ms[i] = C0 @ chest_frame(c, i).T; org[i] = ch[i]
        elif stab == 'pelvis':
            Ms[i] = np.eye(3); d = pv[i] - pv[i0]; d[1] = 0.0; org[i] = ch[i0] + d
        else:
            Ms[i] = np.eye(3); org[i] = ch[i0]
    base = None
    for r in roles:
        X = c.p(r)
        W = np.einsum('nij,nj->ni', Ms, X - (ch if stab == 'torso' else org)) + ch[i0]
        if stab == 'pelvis':
            W = X - (org - ch[i0])
        out[r] = (W - ch[i0]) @ A.T
    base = out[side + 'sh'][i0].copy()
    for r in out:
        out[r] = S + s * (out[r] - base)
    out['_scale'] = s; out['_A'] = A; out['_M'] = Ms
    return out


# ---------------- measurements ----------------
def speed(X, fps, smooth=0.05):
    v = np.r_[0.0, np.linalg.norm(np.diff(X, axis=0), axis=1) * fps]
    w = max(1, int(round(smooth * fps)))
    if w > 1:
        v = np.convolve(v, np.ones(w) / w, mode='same')
    return v


def angle(a, b):
    a, b = nz(a), nz(b)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b)))))


def find_events(sp, fps, min_peak, min_gap=0.35, rel=0.4):
    """strike-like events on a speed curve: local maxima >= max(min_peak, rel * clip max), >= min_gap apart; each with
    (w0 rest before, a fast start (>= 35% of its peak), k peak, b fast end, c settle (< 15%))."""
    thr = max(min_peak, rel * float(sp.max()))
    g = int(min_gap * fps); ev = []
    k = 1
    while k < len(sp) - 1:
        if sp[k] >= thr and sp[k] >= sp[k - 1] and sp[k] >= sp[k + 1] and sp[k] == sp[max(0, k - g):k + g + 1].max():
            pk = sp[k]
            a = k
            while a > 0 and sp[a - 1] >= 0.35 * pk:
                a -= 1
            b = k
            while b < len(sp) - 1 and sp[b + 1] >= 0.35 * pk:
                b += 1
            w0 = a
            while w0 > 0 and sp[w0 - 1] >= 0.15 * pk and not (sp[w0 - 1] < sp[w0] and sp[w0 - 1] < 0.2 * pk):
                w0 -= 1
            # wind-up: back from the fast start to the last local speed minimum below 25% (the reversal at the top
            # of a wind-up is a minimum; before it the hand travelled back/up)
            top = a
            j = a
            while j > 1 and sp[j - 1] <= sp[j]:
                j -= 1
            top = j
            st = top
            while st > 0 and (sp[st - 1] >= 0.15 * pk or sp[st - 1] > sp[st]) and (top - st) < 1.2 * fps:
                st -= 1
            c_ = b
            while c_ < len(sp) - 1 and sp[c_ + 1] >= 0.15 * pk:
                c_ += 1
            ev.append(dict(start=st, top=top, a=a, k=k, b=b, c=c_, peak=float(pk)))
            k = b + 1
        else:
            k += 1
    return ev


def wrist_share(V, s, i0, i1):
    """U10: share of the hand point's motion that comes from the wrist (vs a hand rigid on the forearm)."""
    num = den = 0.0
    for k in range(i0 + 1, i1 + 1):
        el0, wr0, h0 = V[s + 'el'][k - 1], V[s + 'wr'][k - 1], V[s + 'hand'][k - 1]
        el1, wr1, h1 = V[s + 'el'][k], V[s + 'wr'][k], V[s + 'hand'][k]
        fa, fb = nz(wr0 - el0), nz(wr1 - el1)
        Rm = rot_between(fa, fb)
        rig = wr1 + Rm @ (h0 - wr0)
        num += np.linalg.norm(h1 - rig); den += np.linalg.norm(h1 - h0)
    return num / den if den > 1e-9 else 0.0


def rot_between(a, b):
    a, b = nz(a), nz(b); v = np.cross(a, b); c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def _frame(x, y):
    x = nz(x); y = nz(y - x * (y @ x)); return np.stack([x, y, np.cross(x, y)], axis=1)


def _twist(Rm, axis):
    """swing-twist: the angle (deg) of rotation matrix Rm about `axis` (the rest is swing)."""
    w = math.sqrt(max(0.0, 1.0 + Rm[0, 0] + Rm[1, 1] + Rm[2, 2])) / 2.0
    v = np.array([Rm[2, 1] - Rm[1, 2], Rm[0, 2] - Rm[2, 0], Rm[1, 0] - Rm[0, 1]]) / (4.0 * w) if w > 1e-6 else np.zeros(3)
    return abs(math.degrees(2.0 * math.atan2(float(v @ nz(axis)), w)))


def roll_rate(V, s, i0, i1, fps, straight=165.0):
    """max forearm roll (pronation/supination) per 33 ms: the hand frame expressed in the forearm frame (forearm axis +
    elbow-plane normal), its change between frames decomposed swing-twist about the forearm axis (wrist flexion /
    deviation = swing, not counted). Hand frame = hand axis (<side>hx direction, else hand point - wrist) + a hand-fixed
    lateral (<side>lat direction, else <side>thumb point - wrist); frames with a near-straight elbow (> `straight` deg:
    no elbow plane) are skipped; nan when no lateral exists."""
    if s + 'lat' in V:
        latv = lambda j: V[s + 'lat'][j]
    elif s + 'thumb' in V:
        latv = lambda j: V[s + 'thumb'][j] - V[s + 'wr'][j]
    else:
        return float('nan')
    hax = (lambda j: V[s + 'hx'][j]) if s + 'hx' in V else (lambda j: V[s + 'hand'][j] - V[s + 'wr'][j])

    def rel(j):
        up, fo = V[s + 'el'][j] - V[s + 'sh'][j], V[s + 'wr'][j] - V[s + 'el'][j]
        if angle(-up, fo) > straight:
            return None
        F = _frame(fo, np.cross(up, fo))
        return F.T @ _frame(hax(j), latv(j))
    out = 0.0; step = max(1, int(round(fps / 30.0)))
    X = np.array([1.0, 0.0, 0.0])
    for k in range(i0 + step, i1 + 1):
        r0, r1 = rel(k - step), rel(k)
        if r0 is None or r1 is None:
            continue
        out = max(out, _twist(r1 @ r0.T, X))
    return out


def yaw_of(A, i0, M):   # deg of chest yaw change (camera y) represented by M (chest at i -> chest at i0)
    f = M[:, 2]
    return math.degrees(math.atan2(f[0], f[2]))


def strike_metrics(c, side='R', body=None, ev_from=None, ev_to=None, min_peak=12.0, hand='hand'):
    """per event on the `side` wrist (torso-stabilised, FP dm): timing, positions, elbow, wrist bend, wrist share, roll
    rate, torso share (world vs torso-stabilised wrist path), chest yaw over the stroke."""
    fps = c.fps
    i0 = 0 if ev_from is None else int(ev_from * fps)
    i1 = c.n - 1 if ev_to is None else min(c.n - 1, int(ev_to * fps))
    V = fp_view(c, i0, 'torso', side, body)
    Vw = fp_view(c, i0, 'pelvis', side, body)
    V[side + 'hand'] = V[side + hand]
    Vw[side + 'hand'] = Vw[side + hand]
    L = (body or {}).get('L') or 10.0 * sum(arm_len(c, side))

    def yawfn(j0, j1):
        Mt = chest_frame(c, j1) @ chest_frame(c, j0).T
        return abs(math.degrees(math.atan2(Mt[0, 2], Mt[2, 2])))
    rows, sp = strike_rows(V, Vw, fps, side, L, min_peak, i0, i1, yawfn)
    return rows, V, sp


def curve(sp, st, cc, n=21):
    """speed profile st..cc resampled to n points, normalised to its peak (the shape of a strike in time)."""
    x = np.linspace(st, cc, n)
    y = np.interp(x, np.arange(len(sp)), sp)
    return (y / (y.max() or 1.0)).round(3).tolist()


def strike_rows(V, Vw, fps, side, L, min_peak, i0=0, i1=None, yawfn=None):
    """strike measurements on a view dict V (FP camera numbers, dm: <side>sh/el/wr/hand, optional <side>hx = hand X
    axis, <side>thumb); Vw = the same arm with torso turns kept (None = no torso). Works for a mocap view and for a
    solved KenshiFP path alike."""
    n = len(V[side + 'wr']); i1 = n - 1 if i1 is None else i1
    sp = speed(V[side + 'wr'], fps)
    sp[:i0] = 0; sp[i1 + 1:] = 0
    ev = find_events(sp, fps, min_peak)
    # an event inside a later event's wind-up (start .. top) IS that wind-up (a raise before an overhead cut)
    ev = [e for e in ev if not any(e2 is not e and e2['start'] <= e['k'] < e2['top'] for e2 in ev)]
    # wrist share on a hand point at a FIXED lever (0.15 arm along the hand axis) so a long prop offset (a sword grip
    # point) and a short mocap hand segment are judged alike
    hd = V[side + 'hx'] if side + 'hx' in V else V[side + 'hand'] - V[side + 'wr']
    Vh = dict(V); Vh[side + 'hand'] = V[side + 'wr'] + 0.15 * L * (hd / np.maximum(np.linalg.norm(hd, axis=1), 1e-9)[:, None])
    rows = []
    for e in ev:
        st, top, a, b, cc, k = e['start'], e['top'], e['a'], e['b'], e['c'], e['k']
        el = lambda j: angle(V[side + 'sh'][j] - V[side + 'el'][j], V[side + 'wr'][j] - V[side + 'el'][j])
        if side + 'hx' in V:
            wb = lambda j: angle(V[side + 'wr'][j] - V[side + 'el'][j], V[side + 'hx'][j])
        else:
            wb = lambda j: angle(V[side + 'wr'][j] - V[side + 'el'][j], V[side + 'hand'][j] - V[side + 'wr'][j])
        W = V[side + 'wr']
        path = float(np.sum(np.linalg.norm(np.diff(W[top:b + 1], axis=0), axis=1)))
        pathw = float(np.sum(np.linalg.norm(np.diff(Vw[side + 'wr'][top:b + 1], axis=0), axis=1))) if Vw else path
        yaw = yawfn(top, b) if yawfn else 0.0
        tot = max(cc - st, 1)
        rows.append(dict(
            frac_windup=(top - st) / tot, frac_stroke=(b - top) / tot, frac_follow=(cc - b) / tot,
            total=(cc - st) / fps, curve=curve(sp, st, cc),
            t_top=top / fps, t_peak=k / fps,
            windup=(top - st) / fps, stroke=(b - top) / fps, fast=(b - a) / fps, follow=(cc - b) / fps,
            peak_dm_s=e['peak'], peak_armlen_s=e['peak'] / L,
            p_start=V[side + 'wr'][st].round(2).tolist(), p_top=W[top].round(2).tolist(), p_end=W[b].round(2).tolist(),
            guard_out_x=float(W[st][0] * (1 if side == 'R' else -1)), guard_y=float(W[st][1]), guard_z=float(W[st][2]),
            path_dm=path, path_armlen=path / L, torso_share=max(0.0, 1.0 - path / pathw) if pathw > 1e-6 else 0.0,
            chest_yaw_deg=yaw,
            elbow_top=el(top), elbow_min=min(el(j) for j in range(top, b + 1)), elbow_end=el(b),
            reach_end=float(np.linalg.norm(W[b] - V[side + 'sh'][b]) / L),
            wb_top=wb(top), wb_max_stroke=max(wb(j) for j in range(top, b + 1)), wb_end=wb(b), wb_start=wb(st),
            wb_delta=max(wb(j) for j in range(top, b + 1)) - wb(st), elbow_ext=el(b) - min(el(j) for j in range(top, b + 1)),
            wshare=wrist_share(Vh, side, top, b), roll33=roll_rate(V, side, top, b, fps),
            rise_dm=float(W[top][1] - W[b][1])))
    return rows, sp


def kick_metrics(c, side='R', body=None, min_peak=20.0):
    """kicks: toe speed events (pelvis-stabilised); per kick: phases, toe height over the hip (leg lengths), head travel
    (dm, FP scale) and wrist travel vs the chest (U14), knee chamber."""
    fps = c.fps
    V = fp_view(c, 0, 'pelvis', side, body)
    Vt = fp_view(c, 0, 'torso', side, body)
    sp = speed(V[side + 'toe'], fps)
    ev = find_events(sp, fps, min_peak)
    leg = float(np.median(np.linalg.norm(c.p(side + 'hip') - c.p(side + 'knee'), axis=1) +
                          np.linalg.norm(c.p(side + 'knee') - c.p(side + 'ank'), axis=1))) * V['_scale']
    rows = []
    for e in ev:
        st, b, cc, k = e['start'], e['b'], e['c'], e['k']
        T = V[side + 'toe']
        hi = int(st + np.argmax(T[st:cc + 1, 1]))
        H = V['head']
        rows.append(dict(t_peak=k / fps, chamber=(e['top'] - st) / fps, extend=(b - e['top']) / fps, retract=(cc - b) / fps,
                         total=(cc - st) / fps, toe_height_leg=float((T[hi, 1] - V[side + 'hip'][hi, 1]) / leg),
                         head_travel_dm=float(np.max(np.linalg.norm(H[st:cc + 1] - H[st], axis=1))),
                         head_drop_dm=float(H[st, 1] - H[st:cc + 1, 1].min()),
                         head_back_dm=float(H[st, 2] - H[st:cc + 1, 2].min()),
                         wrist_travel_dm={s: float(np.max(np.linalg.norm(Vt[s + 'wr'][st:cc + 1] - Vt[s + 'wr'][st], axis=1)))
                                          for s in 'LR'}))
    return rows


def twohand_metrics(c, body=None, lead='R', min_peak=12.0):
    """two-handed swings: wrist-to-wrist distance (FP dm) at the top / strike / median over the stroke, which hand is
    nearer the head of the weapon (further along the swing direction), plus the strike metrics of the lead hand."""
    rows, V, sp = strike_metrics(c, lead, body, min_peak=min_peak)
    fps = c.fps
    for r in rows:
        top = int(round(r['t_top'] * fps)); b = int(round((r['t_top'] + r['stroke']) * fps))
        d = np.linalg.norm(V['Rwr'] - V['Lwr'], axis=1)
        r['hands_dm_top'] = float(d[top]); r['hands_dm_end'] = float(d[min(b, c.n - 1)])
        r['hands_dm_med'] = float(np.median(d[top:b + 1]))
    return rows


def hold_metrics(c, body=None, side="R", still=0.6, min_dur=0.25, min_rise=0.5):
    """aim / draw holds (scale-free, world numbers): both wrists slower than `still` arm lengths/s for >= min_dur s
    with both hands raised (wrist above the waist by >= min_rise x the shoulder-waist height... approximated as wrist
    above pelvis + 0.5 x (shoulder - pelvis)). Per hold: front hand (farther from the head) reach |sh-wr|/arm, elbow
    angles, hand spacing / arm, rear wrist to head / arm, front wrist height vs the shoulder / arm, jitter (rms of
    each wrist about its mean, mm), raise time (last time both hands were low -> hold start, s), aim yaw of the front
    arm vs the chest (deg: how far the torso turns away from the aim line)."""
    fps = c.fps
    L = sum(arm_len(c, 'R'))
    sp = {s: speed(c.p(s + 'wr'), fps, 0.1) / L for s in 'LR'}
    pv, sh = c.p('pelvis'), (c.p('Rsh') + c.p('Lsh')) / 2
    up = lambda s, i: c.p(s + 'wr')[i][1] > pv[i][1] + min_rise * (sh[i][1] - pv[i][1])
    ok = np.array([sp['R'][i] < still and sp['L'][i] < still and up('R', i) and up('L', i) for i in range(c.n)])
    el = lambda s, i: angle(c.p(s + 'sh')[i] - c.p(s + 'el')[i], c.p(s + 'wr')[i] - c.p(s + 'el')[i])
    rows, i = [], 0
    while i < c.n:
        if not ok[i]:
            i += 1; continue
        j = i
        while j + 1 < c.n and ok[j + 1]:
            j += 1
        if (j - i + 1) / fps >= min_dur:
            m = (i + j) // 2
            hd = c.p('head')[m]
            fr = max('LR', key=lambda s: np.linalg.norm(c.p(s + 'wr')[m] - hd)); rr = 'L' if fr == 'R' else 'R'
            jit = {s: float(np.sqrt(np.mean(np.sum((c.p(s + 'wr')[i:j + 1] - c.p(s + 'wr')[i:j + 1].mean(axis=0)) ** 2,
                                                   axis=1)))) * 1000.0 for s in 'LR'}
            k = i
            while k > 0 and (up('R', k) or up('L', k)) and (i - k) < 4 * fps:
                k -= 1
            aim = c.p(fr + 'wr')[m] - c.p(fr + 'sh')[m]; aim[1] = 0
            Cf = chest_frame(c, m)[:, 2].copy(); Cf[1] = 0
            rows.append(dict(t0=i / fps, dur=(j - i + 1) / fps, front=fr,
                             front_reach=float(np.linalg.norm(c.p(fr + 'wr')[m] - c.p(fr + 'sh')[m]) / L),
                             front_elbow=el(fr, m), rear_elbow=el(rr, m),
                             hands_arm=float(np.linalg.norm(c.p('Rwr')[m] - c.p('Lwr')[m]) / L),
                             rear_head_arm=float(np.linalg.norm(c.p(rr + 'wr')[m] - hd) / L),
                             front_height_arm=float((c.p(fr + 'wr')[m][1] - c.p(fr + 'sh')[m][1]) / L),
                             jitter_mm=jit, raise_s=(i - k) / fps if k > 0 else float('nan'),
                             aim_vs_chest_deg=angle(aim, Cf)))
        i = j + 1
    return rows


def body_from_rec(path, frame):
    """FP body numbers from a KenshiFP-style recording (recfmt): shoulders + arm length per side (dm)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import recfmt
    r = recfmt.parse(path).frames[frame]
    b = {}
    for s in 'LR':
        sh, el, wr = (np.array(r[s + k]) for k in ('sh', 'el', 'wr'))
        b[s + 'sh'] = sh; b[s + 'L'] = float(np.linalg.norm(el - sh) + np.linalg.norm(wr - el))
    b['L'] = b['RL']
    return b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('info'); p.add_argument('clip'); p.add_argument('--asf')
    p = sp.add_parser('measure'); p.add_argument('clip'); p.add_argument('--asf')
    p.add_argument('--kind', default='strike', choices=['strike', 'kick', 'hold', 'twohand'])
    p.add_argument('--side', default='R'); p.add_argument('--body'); p.add_argument('--body-frame', type=int, default=100)
    p.add_argument('--from', dest='t0', type=float); p.add_argument('--to', dest='t1', type=float)
    p.add_argument('--min-peak', type=float, default=None); p.add_argument('--json')
    a = ap.parse_args(argv)
    c = load(a.clip, a.asf)
    if a.cmd == 'info':
        print('%s: %d frames @ %.1f fps (%.2f s); arm R %.3f+%.3f m, L %.3f+%.3f m' % (c.src, c.n, c.fps, c.n / c.fps,
              *arm_len(c, 'R'), *arm_len(c, 'L')))
        print('roles: ' + ' '.join('%s=%s' % kv for kv in c.roles.items()))
        return 0
    body = body_from_rec(a.body, a.body_frame) if a.body else None
    if body and a.side == 'L':
        body['L'] = body['LL']
    if a.kind == 'strike':
        rows = strike_metrics(c, a.side, body, a.t0, a.t1, a.min_peak or 12.0)[0]
    elif a.kind == 'kick':
        rows = kick_metrics(c, a.side, body, a.min_peak or 20.0)
    elif a.kind == 'twohand':
        rows = twohand_metrics(c, body, a.side, a.min_peak or 12.0)
    else:
        rows = hold_metrics(c, body, a.side)
    for r in rows:
        print(' '.join('%s=%s' % (k, ('%.3f' % v) if isinstance(v, float) else v) for k, v in r.items() if k != 'curve'))
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(dict(src=c.src, kind=a.kind, side=a.side, rows=rows), f, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
