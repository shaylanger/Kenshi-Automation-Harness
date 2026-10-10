"""metrics.py -- viewmodel metrics of a recording (game or replay), per pose state.

Rendered pose of frame i = the skeleton measured in record i+1, re-expressed in frame i's camera (the camera
callback measures what the previous apply rendered). Per frame:
  wb      wrist bend, deg: weapon forearm (elbow->wrist) vs hand bone X axis (the in-game vmcheck / fp_vm `wb`)
  elb     weapon elbow, camera numbers (dm); elb_h = elbow height above the shoulder along world up (dm)
  st      upper-arm stretch of the weapon arm (fp_vm `stretch`, 1 = native length)
  edge    cos(blade edge, eye->wrist): +1 = edge faces away from the camera (melee)
  jit     weapon tip screen jitter, px at 1600x900: distance of the tip from where uniform motion between its
          neighbours puts it (time-weighted midpoint); motion at constant speed = 0
  step    tip screen step per frame, px
  arc     edge_arc (E1, melee): cos(blade edge mu, mid-blade velocity perpendicular to the blade), frames where that speed
          > 8 dm/s; +1 = the edge leads the arc, -1 = the back of the blade leads. Per state: arc_ok = share of fast frames
          with arc >= 0.7, arc_p05 = 5th percentile. Only after the wind-up (swing u >= ARC_U0): in the wind-up the edge
          faces the coming strike, i.e. away from the backswing motion, so arc < 0 there is correct
States: ready, swing, block, swing->block (a block entered straight from a swing), aim, reload (crossbow),
draw / lower (blends), native (viewmodel faded out by zoom, zf < 0.99), off (no viewmodel). Hitch frames (dt > 0.07 s, or next to one) are left out of jit/step.
"""
import math
from recfmt import sub, add, mul, dot, ln, nz, ang, remap, cross

W_PX, H_PX, TX, TY = 1600.0, 900.0, 1.245, 0.70   # Kenshi FP view: tan half-angles (vmcheck onscr)
BLADE = {0: 8.0, 1: 5.85}
ARC_MID, ARC_SPEED = 4.0, 8.0   # edge_arc: point on the blade (dm from the grip), minimum perpendicular speed (dm/s)
ARC_U0 = 0.28                   # edge_arc: swing u where the wind-up ends (KenshiFP swing key 1, g_vm_swk_u[1])
STATE_ORDER = ('ready', 'swing', 'block', 'swing->block', 'aim', 'reload', 'settle', 'draw', 'lower', 'native')
NATIVE_ZF = 0.99   # zoom fade below this = the body plays the native animation (viewmodel faded, PT29)


def label_states(F):
    lab, prev_sw, swb = [], False, False
    for r in F:
        if r['on'] and r['w'] >= 0.99 and r.get('zf', 1.0) < NATIVE_ZF:
            s = 'native'
        elif not r['on'] or r['w'] < 0.99:
            s = 'draw' if r['phase'] == 1 else 'lower' if r['phase'] == 2 else 'off'
        elif r['cls'] == 0:
            if r['swing']:
                s = 'swing'
            elif r['st'] == 'blocking' or r['ti'] == 3:
                if not swb and prev_sw:
                    swb = True
                s = 'swing->block' if swb else 'block'
            else:
                s = 'ready'
        else:
            # C1: aim only while the UI state says aiming (a reload that starts from the aim target is reload, the
            # frames between are settle): a ti=1 label alone let a never-shown aim pass
            s = {1: 'aim', 2: 'reload'}.get(r['ti'], 'ready')
            if s == 'aim' and r['st'] != 'aiming':
                s = 'reload' if r['st'] == 'reloading' else 'settle'
        if s not in ('block', 'swing->block'):
            swb = False
        prev_sw = s == 'swing'
        lab.append(s)
    return lab


def proj(c):
    if c[2] < 0.5:
        return None
    return (W_PX / 2 + W_PX / 2 * (c[0] / c[2]) / TX, H_PX / 2 - H_PX / 2 * (c[1] / c[2]) / TY)


def rendered(F):
    """per frame i (0..N-2): the pose frame i showed, in frame i's camera numbers."""
    out = []
    for i in range(len(F) - 1):
        a, b = F[i], F[i + 1]
        J = [remap(x, a, b, 1) for x in (b[k] for k in ('Lsh', 'Lel', 'Lwr', 'Rsh', 'Rel', 'Rwr'))]
        p = dict(J=J, mp=remap(b['mp'], a, b, 1), mf=nz(remap(b['mf'], a, b, 0)), mu=nz(remap(b['mu'], a, b, 0)),
                 wb=b['wb'], st=b['stch'], wih=b['wih'])
        upw = (a['rt'][1], a['up'][1], a['fw'][1]) if a['rt'] else (0.0, 1.0, 0.0)
        p['elb'] = J[4]
        p['elb_h'] = dot(sub(J[4], J[3]), nz(upw))
        p['edge'] = dot(p['mu'], nz(J[5])) if ln(J[5]) > 1e-6 else 0.0
        cls = a['cls']
        tip = add(p['mp'], mul(p['mf'], BLADE[cls]))
        if cls == 1:
            tip = add(tip, mul(p['mu'], 0.84))
        p['tip'] = tip
        p['tpx'] = proj(tip)
        out.append(p)
    return out


def pct(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(math.ceil(q * len(xs))) - 1 if q > 0 else 0)]


def frame_metrics(rec):
    F = rec.frames
    lab = label_states(F)
    P = rendered(F)
    N = len(P)
    for i in range(N):
        P[i]['state'] = lab[i]
        P[i]['jit'] = P[i]['step'] = None
        P[i]["arc"] = None
    for i in range(1, N - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        if F[i]["cls"] == 0 and max(F[i - 1]["dt"], F[i]["dt"], F[i + 1]["dt"]) <= 0.07:   # E1 edge_arc (melee)
            mid = lambda q: add(q["mp"], mul(q["mf"], ARC_MID))
            vel = mul(sub(mid(c), mid(a)), 1.0 / max(F[i]["dt"] + F[i + 1]["dt"], 1e-4))
            vp = sub(vel, mul(b["mf"], dot(vel, b["mf"])))
            if ln(vp) > ARC_SPEED and F[i].get("swu", 1.0) >= ARC_U0:
                b["arc"] = dot(b["mu"], nz(vp))
        if not (a['tpx'] and b['tpx'] and c['tpx']) or max(F[i - 1]['dt'], F[i]['dt'], F[i + 1]['dt']) > 0.07:
            continue
        if lab[i - 1] != lab[i] or lab[i + 1] != lab[i]:
            continue
        d1, d2 = max(F[i]['dt'], 1e-4), max(F[i + 1]['dt'], 1e-4)
        u = d1 / (d1 + d2)
        ex = (a['tpx'][0] + (c['tpx'][0] - a['tpx'][0]) * u, a['tpx'][1] + (c['tpx'][1] - a['tpx'][1]) * u)
        b['jit'] = math.hypot(b['tpx'][0] - ex[0], b['tpx'][1] - ex[1])
        b['step'] = math.hypot(b['tpx'][0] - a['tpx'][0], b['tpx'][1] - a['tpx'][1])
    return P


def state_table(P, skip=0):
    """{state: {metric: value}} over frames >= skip."""
    T = {}
    for i, p in enumerate(P):
        if i < skip or p['state'] == 'off' or not p['wih']:
            continue
        T.setdefault(p['state'], []).append(p)
    out = {}
    for s, ps in T.items():
        wb = [p['wb'] for p in ps if p['wb'] is not None]
        ed = [p['edge'] for p in ps]
        ar = [p["arc"] for p in ps if p.get("arc") is not None]
        out[s] = dict(n=len(ps), wb_p95=pct(wb, .95), wb_max=max(wb) if wb else float('nan'),
                      elb_h_max=max(p['elb_h'] for p in ps), elb_h_mean=sum(p['elb_h'] for p in ps) / len(ps),
                      elb_x=sum(p['elb'][0] for p in ps) / len(ps), elb_y=sum(p['elb'][1] for p in ps) / len(ps),
                      elb_z=sum(p['elb'][2] for p in ps) / len(ps),
                      st_max=max(p['st'] for p in ps), st_p95=pct([p['st'] for p in ps], .95),
                      edge_mean=sum(ed) / len(ed), edge_max=max(ed),
                      jit_p95=pct([p['jit'] for p in ps if p['jit'] is not None], .95),
                      step_p95=pct([p['step'] for p in ps if p['step'] is not None], .95),
                      arc_ok=sum(1 for x in ar if x >= 0.7) / len(ar) if ar else float("nan"), arc_p05=pct(ar, .05), arc_n=len(ar),
                      move_dm=float('nan'), move_deg=float('nan'))
    # C1 (KenshiFP 2026-10-09: the crossbow aim stayed in the ready pose and passed): how far each state moves the weapon
    # from the median ready pose. Held states (aim, block) by their median pose, paths (swing, reload, ...) by their
    # largest frame. move_dm = grip displacement (dm), move_deg = blade/stock axis angle (deg). See moves_ok().
    if T.get('ready'):
        rp, rf = _mpose(T['ready'])
        for s, ps in T.items():
            if s == 'ready':
                continue
            if s in HELD_STATES:
                mp, mf = _mpose(ps)
                out[s]['move_dm'], out[s]['move_deg'] = ln(sub(mp, rp)), _ang(mf, rf)
            else:
                out[s]['move_dm'] = max(ln(sub(p['mp'], rp)) for p in ps)
                out[s]['move_deg'] = max(_ang(p['mf'], rf) for p in ps)
    return out


HELD_STATES = ('aim', 'block')
MOVE_DM, MOVE_DEG = 1.0, 15.0


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


def _mpose(ps):
    return (tuple(_med([p['mp'][k] for p in ps]) for k in range(3)), tuple(_med([p['mf'][k] for p in ps]) for k in range(3)))


def _ang(a, b):
    la, lb = ln(a), ln(b)
    if la < 1e-6 or lb < 1e-6:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b) / la / lb))))


def moves_ok(table, required):
    """C1 gate: every required state (e.g. ('aim', 'reload') for the crossbow, ('block', 'swing') for the sword) must
    exist and move the weapon visibly from ready (move_dm >= MOVE_DM or move_deg >= MOVE_DEG).
    Returns (ok, [text per state])."""
    ok, txt = True, []
    for s in required:
        m = table.get(s)
        if not m or 'move_dm' not in m:
            ok = False
            txt.append(s + ':MISSING')
            continue
        still = m['move_dm'] < MOVE_DM and m['move_deg'] < MOVE_DEG
        ok = ok and not still
        txt.append('%s:%.1fdm/%.0fdeg%s' % (s, m['move_dm'], m['move_deg'], ':STILL' if still else ''))
    return ok, txt


ARC_OK, ARC_SHARE, ARC_WB = 0.7, 0.85, 30.0   # E1 gate: per-frame edge_arc >= ARC_OK on >= ARC_SHARE of fast frames, wrist bend <= ARC_WB


def arc_gate(table, spec, wb_lim=ARC_WB):
    """E1 gate (sword edge leads the arc): spec = {state: share}. Each state must exist with fast frames, have
    arc_ok >= share and a sane wrist (wb_max <= wb_lim deg; a patch that turns the edge by folding the wrist fails).
    Returns (ok, [text per state])."""
    ok, txt = True, []
    for s, share in spec.items():
        m = table.get(s)
        if not m or not m.get('arc_n'):
            ok = False
            txt.append(s + ':NO_FAST_FRAMES')
            continue
        good = m['arc_ok'] >= share and m['wb_max'] <= wb_lim
        ok = ok and good
        txt.append('%s:arc_ok=%.2f/%.2f,arc_p05=%.2f,n=%d,wb_max=%.1f/%.0f%s' % (
            s, m['arc_ok'], share, m['arc_p05'], m['arc_n'], m['wb_max'], wb_lim, '' if good else ':BAD'))
    return ok, txt



JIT_MIN, JIT_RATIO = 1.0, 2.5   # X1 jitter faithfulness: game jit_p95 (px) above JIT_MIN may be at most JIT_RATIO x the replay's


def jitter_faithful(game, replay, skip_states=('off', 'draw', 'lower', 'native', 'settle', 'swing')):
    """X1 check (game vs replay of the same recording): tip jitter the solver does not produce comes from outside it
    (e.g. the pre-e948f86 bone-world map). Per state with >= 10 frames and game jit_p95 > JIT_MIN: game/replay <= JIT_RATIO.
    Swings are skipped (fast motion: jit is dominated by the frame timing, not by noise). Returns (ok, [text])."""
    ok, txt = True, []
    for s, g in game.items():
        r = replay.get(s)
        if s in skip_states or not r or g.get('n', 0) < 10 or not g['jit_p95'] == g['jit_p95'] or g['jit_p95'] <= JIT_MIN:
            continue
        q = g['jit_p95'] / max(r['jit_p95'], 0.1) if r['jit_p95'] == r['jit_p95'] else float('inf')
        good = q <= JIT_RATIO
        ok = ok and good
        txt.append('%s:%.2f/%.2f=x%.1f%s' % (s, g['jit_p95'], r['jit_p95'], q, '' if good else ':BAD'))
    return ok, txt


METRIC_COLS = ('n', 'wb_p95', 'wb_max', 'elb_h_max', 'elb_h_mean', 'st_max', 'edge_mean', 'edge_max', 'jit_p95', 'step_p95',
               'move_dm', 'move_deg', "arc_ok", "arc_p05")


BOLT_DEV, BOLT_STEP = 0.1, 0.05   # C3: the loaded bolt is rigid on the weapon: drift from its median / per-frame step (dm)


def read_bolt(path, source=None):
    """`fp_vm rec dump` sidecar <rec>.bolt (KenshiFP C3): per record n ok vis | bl: bolt origin in the weapon frame (f u r) |
    bolt X | Y | Z | sl: bolt node in the post-IK Prop2 bone frame (xyz) + angle sa (column group 5, builds since the
    C3 pin; the header may still say "string node frame"). Returns {n: xyz} for frames with a measured, visible bolt,
    from sl when the sidecar has it (bl uses mp, measured at another time than the bolt: false drift on walk), else bl.
    source: None = auto, 'sl' or 'bl' to force. read_bolt.used = the group used."""
    out = {}
    rows = [[x.split() for x in l.split("|")] for l in open(path) if l.strip() and not l.startswith("#")]
    use = source or ("sl" if any(len(g) > 5 and len(g[5]) >= 3 for g in rows) else "bl")
    read_bolt.used = use
    for g in rows:
        n, ok, vis = (int(x) for x in g[0][:3])
        if ok and vis and (use == "bl" or len(g) > 5 and len(g[5]) >= 3):
            out[n] = tuple(float(x) for x in (g[5] if use == "sl" else g[1])[:3])
    return out


def bolt_table(B, labels):
    """C3 per state: dev95 = p95 distance of the bolt origin from the state's median (weapon frame, dm), step95 = p95
    frame-to-frame move, n. Rigid bolt = ~0; a bolt node updated out of step with the weapon drifts/jitters."""
    S = {}
    for n in sorted(B):
        if n < len(labels):
            S.setdefault(labels[n], []).append(n)
    T = {}
    for s, ns in S.items():
        m = [_med([B[n][k] for n in ns]) for k in range(3)]
        d = [math.dist(B[n], m) for n in ns]
        st = [math.dist(B[n], B[n - 1]) for n in ns if n - 1 in B and labels[n - 1] == s]
        T[s] = dict(n=len(ns), dev95=pct(d, .95), step95=pct(st, .95) if st else float('nan'))
    return T


def bolt_ok(T, dev=BOLT_DEV, step=BOLT_STEP, min_n=10):
    ok, txt = True, []
    for s, t in T.items():
        if t['n'] < min_n:
            continue
        good = t['dev95'] <= dev and not t['step95'] > step
        ok = ok and good
        txt.append('%s:dev95=%.3f,step95=%.3f,n=%d%s' % (s, t['dev95'], t['step95'], t['n'], '' if good else ':BAD'))
    return ok and bool(txt), txt or ['no visible bolt frames']


CHURN_REV, CHURN_GRIP, CHURN_T, CHURN_WIN, CHURN_SKIP = 450.0, 250.0, 0.4, 0.15, 10   # E1 arm churn (px, px, s, s, frames)
ROLL_MAX = 15.0   # E1: hand roll about the forearm axis during the wind-up (deg)


def _scr(c):
    return (W_PX / 2 + W_PX / 2 * (c[0] / c[2]) / TX, H_PX / 2 - H_PX / 2 * (c[1] / c[2]) / TY)


def _forearm_vis(wr, el, near=0.5):
    """screen end of the visible forearm: the elbow if on screen, else where wrist->elbow leaves the screen (None when
    the wrist is off screen). The elbow is first pulled in front of the near plane along the forearm."""
    if wr[2] < near:
        return None
    if el[2] < near:
        el = add(wr, mul(sub(el, wr), (wr[2] - near) / (wr[2] - el[2])))
    w, e = _scr(wr), _scr(el)
    if not (0 <= w[0] <= W_PX and 0 <= w[1] <= H_PX):
        return None
    t = 1.0
    for k, lim in ((0, 0.0), (0, W_PX), (1, 0.0), (1, H_PX)):
        de = e[k] - w[k]
        if abs(de) > 1e-9 and 0 < (lim - w[k]) / de < t:
            t = (lim - w[k]) / de
    return (w[0] + (e[0] - w[0]) * t, w[1] + (e[1] - w[1]) * t), w


def churn_series(F, P):
    """per rendered frame: v = visible forearm end (screen px; vm = median of 3 frames), w = wrist, g = grip, tip, ax =
    forearm axis, mu = blade up; None without a full viewmodel or with the wrist off screen."""
    S = []
    for i, p in enumerate(P):
        r = F[i]
        fv = _forearm_vis(p['J'][5], p['J'][4]) if r['on'] and r['w'] >= 0.99 else None
        if not fv:
            S.append(None); continue
        g = _scr(p['mp']) if p['mp'][2] > 0.5 else fv[1]
        tp = _scr(p['tip']) if p['tip'][2] > 0.5 else fv[1]
        S.append(dict(i=i, t=r['t'], st=p.get('state'), swu=r.get('swu', 1.0), v=fv[0], w=fv[1], g=g, tip=tp,
                      ax=nz(sub(p['J'][5], p['J'][4])), B=(p['mf'], p['mu'], nz(cross(p['mf'], p['mu'])))))
    for i in range(1, len(S) - 1):
        if S[i - 1] and S[i] and S[i + 1]:
            S[i]['vm'] = tuple(sorted(S[k]['v'][c] for k in (i - 1, i, i + 1))[1] for c in range(2))
    for s in S:
        if s and 'vm' not in s:
            s['vm'] = s['v']
    return S


def _d2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _twist(a, B0, B1):
    """twist (deg) about axis a of the rotation taking frame B0 to B1 (B = weapon f, u, f x u: rigid in the hand, so
    this is the hand's roll about the forearm; wrist flex/deviation, about axes across the forearm, is excluded)."""
    R = [[sum(B1[k][r] * B0[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    w = math.sqrt(max(0.0, 1.0 + R[0][0] + R[1][1] + R[2][2])) / 2
    v = ((R[2][1] - R[1][2]) / 4, (R[0][2] - R[2][0]) / 4, (R[1][0] - R[0][1]) / 4) if w > 1e-4 else (0.0, 0.0, 0.0)
    if w <= 1e-4:
        return 0.0
    v = (v[0] / w, v[1] / w, v[2] / w)   # quaternion (1, v) up to scale
    return math.degrees(2 * math.atan2(dot(v, a), 1.0))


def churn_check(S, rev_max=CHURN_REV, grip_max=CHURN_GRIP, tw=CHURN_T, win=CHURN_WIN, skip=CHURN_SKIP, roll_max=ROLL_MAX, u0=ARC_U0):
    """E1 arm churn (Shay: the arm moves around a ton while the sword barely moves).
    (b) gate: the visible forearm end goes out and comes back by more than rev_max px within tw s while the grip stays
        within grip_max px; worst window = rev px @ frames start-turn-end, grip extent.
    (a) info: (visible forearm end + forearm mid) screen path / (grip + tip) path over win s (arm path >= 150 px).
    (d) gate: hand roll about the forearm axis in each swing's wind-up (first swing frame .. swu < u0): max |cumulative
        twist| of the blade up vector <= roll_max deg."""
    n = len(S); rev = (0.0, None); ratio = (0.0, None)
    for i in range(skip, n):
        if not S[i]:
            continue
        j = i
        while j + 1 < n and S[j + 1] and S[j + 1]['t'] - S[i]['t'] <= tw:
            j += 1
        ge, k = 0.0, i
        for e in range(i + 1, j + 1):
            ge = max(ge, max(_d2(S[e]['g'], S[q]['g']) for q in range(i, e)))
            if ge > grip_max:
                break
            if _d2(S[e]['vm'], S[i]['vm']) > _d2(S[k]['vm'], S[i]['vm']):
                k = e
            r = min(_d2(S[k]['vm'], S[i]['vm']), _d2(S[k]['vm'], S[e]['vm']))
            if r > rev[0]:
                rev = (r, (S[i]['i'], S[k]['i'], S[e]['i'], ge, S[k]['st']))
        arm = wep = 0.0; q = i
        mid = lambda s: ((s['vm'][0] + s['w'][0]) / 2, (s['vm'][1] + s['w'][1]) / 2)
        while q + 1 < n and S[q + 1] and S[q + 1]['t'] - S[i]['t'] <= win:
            a, b = S[q], S[q + 1]
            arm += _d2(a['vm'], b['vm']) + _d2(mid(a), mid(b)); wep += _d2(a['g'], b['g']) + _d2(a['tip'], b['tip']); q += 1
        if arm >= 150 and arm / max(wep, 100.0) > ratio[0]:
            ratio = (arm / max(wep, 100.0), (S[i]['i'], S[q]['i'], arm, wep, S[i]['st']))
    rolls = []
    for i in range(1, n):
        if S[i] and S[i]['st'] == 'swing' and S[i - 1] and S[i - 1]['st'] != 'swing':
            cum, mx, k = 0.0, 0.0, i
            while k < n and S[k] and S[k]['st'] == 'swing' and S[k]['swu'] < u0:
                cum += _twist(S[k]['ax'], S[k - 1]['B'], S[k]['B'])
                mx = max(mx, abs(cum)); k += 1
            if k > i:
                rolls.append((mx, S[i]['i'], S[k - 1]['i']))
    worst_roll = max(rolls) if rolls else None
    ok_rev = rev[0] <= rev_max
    ok_roll = worst_roll is None or worst_roll[0] <= roll_max
    txt = ['rev=%.0fpx/%.0f%s' % (rev[0], rev_max, '' if ok_rev else ':BAD')]
    if rev[1]:
        txt[-1] += '@%d-%d-%d,grip=%.0fpx,%s' % rev[1]
    txt.append('windup_roll=%s/%.0f%s' % ('%.1fdeg@%d-%d' % worst_roll if worst_roll else 'none', roll_max, '' if ok_roll else ':BAD'))
    txt.append('ratio=%.2f(info)' % ratio[0] + ('@%d-%d,arm=%.0f,wep=%.0f,%s' % ratio[1] if ratio[1] else ''))
    return ok_rev and ok_roll, txt, dict(rev=rev, ratio=ratio, rolls=rolls)


STOCK_H, STOCK_BACK, STOCK_NEAR = 1.45, 8.0, 1.5   # C2: stock top above the bolt axis, stock length behind the grip, near clip (dm)
STOCK_MAX, ORI_MAX = 25.0, 3.0                     # C2 gate: stock top <= % of the screen from the bottom; ready orientation drift (deg)


def stock_table(F, labels, h=STOCK_H, back=STOCK_BACK, near=STOCK_NEAR):
    """C2 (ranged weapon, cls 1) per state: highest visible point of the stock top line mp - k*mf + h*mu (k 0..back dm
    behind the grip) as % of the screen height from the bottom (-1 = stock not on screen); p50/p95/max, n."""
    S = {}
    for r, s in zip(F, labels):
        if r['cls'] != 1 or not r['on'] or r['w'] < 0.99:
            continue
        best = -1.0
        for i in range(int(back * 10) + 1):
            q = add(sub(r['mp'], mul(r['mf'], i * 0.1)), mul(r['mu'], h))
            if q[2] <= near or abs(q[0] / q[2]) > TX:
                continue
            best = max(best, 50 + 50 * (q[1] / q[2]) / TY)
        S.setdefault(s, []).append(best)
    return {s: dict(n=len(v), p50=pct(v, .5), p95=pct(v, .95), max=max(v)) for s, v in S.items()}


def pose_dirs(F, labels, state='ready'):
    """Median weapon forward/up (camera numbers, normalised) over a state's frames, or None."""
    P = [r for r, s in zip(F, labels) if s == state and r['on'] and r['w'] >= 0.99]
    if not P:
        return None
    return tuple(nz(tuple(_med([r[k][i] for r in P]) for i in range(3))) for k in ('mf', 'mu'))


def stock_ok(T, dirs=None, ref=None, lim=STOCK_MAX, ori=ORI_MAX, states=('ready',), min_n=10):
    """C2 gate: stock top p95 <= lim % in each gated state; with a reference pose (ref = pose_dirs of a known-good
    recording) the ready forward/up must also stay within ori deg of it (C2 fixes must not rotate the weapon)."""
    ok, txt = True, []
    for s in states:
        t = T.get(s)
        if not t or t['n'] < min_n:
            ok = False; txt.append('%s:NO_FRAMES' % s); continue
        good = t['p95'] <= lim
        ok = ok and good
        txt.append('%s:p95=%.0f%%/%.0f,n=%d%s' % (s, t['p95'], lim, t['n'], '' if good else ':BAD'))
    if ref is not None:
        if dirs is None:
            ok = False; txt.append('ori:NO_FRAMES')
        else:
            df, du = _ang(dirs[0], ref[0]), _ang(dirs[1], ref[1])
            good = max(df, du) <= ori
            ok = ok and good
            txt.append('ori:fwd=%.1f,up=%.1fdeg/%.0f%s' % (df, du, ori, '' if good else ':BAD'))
    return ok, txt


def fmt(v):
    if isinstance(v, int):
        return '%d' % v
    if v != v:
        return '-'
    return '%.2f' % v
