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
          with arc >= 0.7, arc_p05 = 5th percentile. Only in the stroke (ARC_U0 <= swing u < ARC_U1): in the wind-up the edge
          faces the coming strike, i.e. away from the backswing motion, so arc < 0 there is correct; Shay 2026-10-09: the edge
          must line up from the stroke start and lead through it, the wind-up / follow-through may be off-line
States: ready, swing, block, swing->block (a block entered straight from a swing), aim, reload (crossbow),
draw / lower (blends), native (viewmodel faded out by zoom, zf < 0.99), off (no viewmodel). Hitch frames (dt > 0.07 s, or next to one) are left out of jit/step.
"""
import math
from recfmt import sub, add, mul, dot, ln, nz, ang, remap, cross

W_PX, H_PX, TX, TY = 1600.0, 900.0, 1.245, 0.70   # Kenshi FP view: tan half-angles (vmcheck onscr)
BLADE = {0: 8.0, 1: 5.85}
ARC_MID, ARC_SPEED = 4.0, 8.0   # edge_arc: point on the blade (dm from the grip), minimum perpendicular speed (dm/s)
ARC_U0 = 0.28                   # edge_arc: swing u where the wind-up ends (KenshiFP swing key 1, g_vm_swk_u[1])
ARC_U1 = 0.58                   # edge_arc: swing u where the stroke ends (key 4); Shay 2026-10-09: only the stroke is gated
STATE_ORDER = ('ready', 'swing', 'block', 'swing->block', 'aim', 'reload', 'settle', 'draw', 'lower', 'native')
STROKE_ONLY = None   # E6: set (animlab --stroke n) -> swings of other strokes are labelled 'swing_x' (out of every swing gate)
NATIVE_ZF = 0.99   # zoom fade below this = the body plays the native animation (viewmodel faded, PT29)
# Frames that play the NATIVE animation (no solver pose on screen): zoom-faded (`native`), viewmodel off (`off`) and the
# draw/lower blends. Shay 2026-10-10: the wrist-bend limit applies to solver-posed frames only; native frames are exempt.
NATIVE_STATES = ('native', 'off', 'draw', 'lower')


def rec_setting(meta, key, default=None):
    """last value of a `# set <frame> <key> <value>` comment line (KenshiFP / replay --set) for key, else default."""
    v = default
    for m in meta or ():
        t = m.split()
        if len(t) >= 4 and t[0] == 'set' and t[2] == key:
            try:
                v = float(t[3])
            except ValueError:
                pass
    return v


def native_reload(meta):
    """crossbow reload plays the native two-hand reload (KenshiFP g_vm_rlnat, default 1; Shay accepted it 2026-10-10,
    rejected the scripted rlnat 0 reload): unless the recording sets rlnat 0, its crossbow reload frames are native."""
    return rec_setting(meta, 'rlnat', 1.0) != 0


def is_native(r):
    """record r plays the native animation: viewmodel off / not fully weighted, or faded by the zoom."""
    return (not r['on']) or r['w'] < 0.99 or r.get('zf', 1.0) < NATIVE_ZF


def label_states(F):
    lab, prev_sw, swb = [], False, False
    for r in F:
        if r['on'] and r['w'] >= 0.99 and r.get('zf', 1.0) < NATIVE_ZF:
            s = 'native'
        elif not r['on'] or r['w'] < 0.99:
            s = 'draw' if r['phase'] == 1 else 'lower' if r['phase'] == 2 else 'off'
        elif r['cls'] == 0:
            if r['swing']:
                s = 'swing' if STROKE_ONLY is None or r.get('stroke') in (None, -1, STROKE_ONLY) else 'swing_x'
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
            if ln(vp) > ARC_SPEED and ARC_U0 <= F[i].get("swu", 1.0) < ARC_U1:
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


ARC_OK, ARC_SHARE, ARC_WB = 0.7, 0.85, 50.0   # E1 gate: per-frame edge_arc >= ARC_OK on >= ARC_SHARE of fast frames, wrist bend <= ARC_WB (50 = vmcheck wrist limit; Shay accepted E1 wb36, 2026-10-09)


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
SROLL_DU, SROLL_MAX, SROLL_STEP = 0.15, 45.0, 12.0   # E1: stroke start (u0..u0+DU): max roll (deg), max step (deg per 1/60 s)


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


def churn_check(S, rev_max=CHURN_REV, grip_max=CHURN_GRIP, tw=CHURN_T, win=CHURN_WIN, skip=CHURN_SKIP, roll_max=ROLL_MAX, u0=ARC_U0,
                sroll_max=SROLL_MAX, sroll_step=SROLL_STEP, sroll_du=SROLL_DU, sroll_gate=False):
    """E1 arm churn (Shay: the arm moves around a ton while the sword barely moves).
    (b) gate: the visible forearm end goes out and comes back by more than rev_max px within tw s while the grip stays
        within grip_max px; worst window = rev px @ frames start-turn-end, grip extent.
    (a) info: (visible forearm end + forearm mid) screen path / (grip + tip) path over win s (arm path >= 150 px).
    (d) gate: hand roll about the forearm axis in each swing's wind-up (first swing frame .. swu < u0): max |cumulative
        twist| of the blade up vector <= roll_max deg.
    (e) gate with sroll_gate (else info; the current game swing rolls ~150 deg here): stroke start (u0 .. u0+sroll_du): the hand may roll only a little and gradually: max |cumulative twist|
        <= sroll_max deg, largest step <= sroll_step deg per 1/60 s."""
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
    rolls, srolls = [], []
    for i in range(1, n):
        if S[i] and S[i]['st'] == 'swing' and S[i - 1] and S[i - 1]['st'] != 'swing':
            cum, mx, k = 0.0, 0.0, i
            while k < n and S[k] and S[k]['st'] == 'swing' and S[k]['swu'] < u0:
                cum += _twist(S[k]['ax'], S[k - 1]['B'], S[k]['B'])
                mx = max(mx, abs(cum)); k += 1
            if k > i:
                rolls.append((mx, S[i]['i'], S[k - 1]['i']))
            cum, smx, stp, k0 = 0.0, 0.0, 0.0, k
            while k < n and S[k] and S[k - 1] and S[k]['st'] == 'swing' and S[k]['swu'] < u0 + sroll_du:
                t = _twist(S[k]['ax'], S[k - 1]['B'], S[k]['B']); cum += t; smx = max(smx, abs(cum))
                stp = max(stp, abs(t) / max(S[k]['t'] - S[k - 1]['t'], 1e-3) / 60.0); k += 1
            if k > k0:
                srolls.append((smx, stp, S[k0]['i'], S[k - 1]['i']))
    worst_roll = max(rolls) if rolls else None
    ok_rev = rev[0] <= rev_max
    ok_roll = worst_roll is None or worst_roll[0] <= roll_max
    ws = max(srolls) if srolls else None; wstep = max(srolls, key=lambda r: r[1]) if srolls else None
    ok_sroll = ws is None or (ws[0] <= sroll_max and wstep[1] <= sroll_step)
    txt = ['rev=%.0fpx/%.0f%s' % (rev[0], rev_max, '' if ok_rev else ':BAD')]
    if rev[1]:
        txt[-1] += '@%d-%d-%d,grip=%.0fpx,%s' % rev[1]
    txt.append('windup_roll=%s/%.0f%s' % ('%.1fdeg@%d-%d' % worst_roll if worst_roll else 'none', roll_max, '' if ok_roll else ':BAD'))
    txt.append('stroke_roll=%s/%.0f,step=%s/%.0f%s' % ('%.1fdeg@%d-%d' % (ws[0], ws[2], ws[3]) if ws else 'none', sroll_max,
               '%.1f@%d' % (wstep[1], wstep[2]) if wstep else '-', sroll_step,
               ('' if ok_sroll else ':BAD') if sroll_gate else ('(info)' if ok_sroll else '(info:over,gate off)')))
    txt.append('ratio=%.2f(info)' % ratio[0] + ('@%d-%d,arm=%.0f,wep=%.0f,%s' % ratio[1] if ratio[1] else ''))
    return ok_rev and ok_roll and (ok_sroll or not sroll_gate), txt, dict(rev=rev, ratio=ratio, rolls=rolls, srolls=srolls)


# E1 inline (Shay 2026-10-09, reference photos e1*.png vs Chivalry): the blade stays roughly in line with the forearm through the
# wind-up and stroke, the arc comes from the shoulder/elbow, the wrist does little.
SWING_PHASES = ((ARC_U0, 'windup'), (0.58, 'stroke'), (0.78, 'follow'), (9.0, 'recov'))   # swing u ends (KenshiFP g_vm_swk_u 1, 4, 5)
INL_FB_MED, INL_FB_MAX, INL_SC_MAX, INL_WR = 30.0, 40.0, 40.0, 0.6   # gate: forearm-blade deg (median, max), screen max, wrist share
INL_GATE, INL_WR_GATE = ('windup', 'stroke'), ('stroke',)   # the wind-up moves the hand from the ready grip into line: wrist share gated in the stroke only


def swing_phase(st, u):
    if st != 'swing':
        return st
    return next(n for e, n in SWING_PHASES if u < e)


def _rot_min(a, b, v):
    """v rotated by the minimal rotation taking unit a to unit b (no twist about the forearm: pronation stays 'wrist')."""
    x = cross(a, b); s = ln(x)
    if s < 1e-9:
        return v
    k = mul(x, 1 / s); t = math.atan2(s, dot(a, b))
    return add(add(mul(v, math.cos(t)), mul(cross(k, v), math.sin(t))), mul(k, dot(k, v) * (1 - math.cos(t))))


def _scr_ang(a0, a1, b0, b1):
    """screen angle (deg) between the projected segments a0->a1 and b0->b1 (None if off screen / too short)."""
    p = [proj(x) for x in (a0, a1, b0, b1)]
    if not all(p):
        return None
    v1, v2 = (p[1][0] - p[0][0], p[1][1] - p[0][1]), (p[3][0] - p[2][0], p[3][1] - p[2][1])
    if math.hypot(*v1) <= 3 or math.hypot(*v2) <= 3:
        return None
    return abs(math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], dot(v1 + (0,), v2 + (0,)))))


def inline_series(F, P):
    """per rendered melee frame: phase, elbow el, wrist wr, grip mp, blade mf, tip (camera numbers, dm)."""
    S = []
    for i in range(len(P)):
        b = P[i]
        if not b['wih'] or F[i]['cls'] != 0 or b['state'] == 'off':
            S.append(None); continue
        S.append(dict(i=i, ph=swing_phase(b['state'], F[i].get('swu', 0.0)), el=b['J'][4], wr=b['J'][5], mp=b['mp'], mf=b['mf'], tip=b['tip']))
    return S


def inline_table(S):
    """{phase: dict(n, fb_med, fb_max, sc_med, sc_max, wr)}.
    fb = 3D angle forearm (elbow -> wrist) vs blade (0 = in line); sc = the same angle on screen (forearm drawn back from the
    wrist, blade forward from the grip); wr = wrist share of the tip motion: sum |tip - where it would be if the blade had
    stayed rigid with the forearm (minimal rotation, so forearm twist counts as wrist)| / sum |tip step|, over consecutive
    frames of the same phase. ~0 = the arm carries the blade, ~1 = the wrist turns it."""
    A, C, W = {}, {}, {}
    for k, s in enumerate(S):
        if not s:
            continue
        fa = nz(sub(s['wr'], s['el']))
        A.setdefault(s['ph'], []).append(math.degrees(math.acos(max(-1.0, min(1.0, dot(fa, s['mf']))))))
        sc = _scr_ang(sub(s['wr'], mul(fa, 0.5)), s['wr'], s['mp'], add(s['mp'], mul(s['mf'], 0.5)))
        if sc is not None:
            C.setdefault(s['ph'], []).append(sc)
        a = S[k - 1] if k else None
        if a and a['ph'] == s['ph']:
            fa0 = nz(sub(a['wr'], a['el']))
            rig = add(s['wr'], _rot_min(fa0, fa, sub(a['tip'], a['wr'])))
            w = W.setdefault(s['ph'], [0.0, 0.0]); w[0] += ln(sub(s['tip'], rig)); w[1] += ln(sub(s['tip'], a['tip']))
    out = {}
    for ph, xs in A.items():
        xs = sorted(xs); cs = sorted(C.get(ph, [])); w = W.get(ph)
        out[ph] = dict(n=len(xs), fb_med=xs[len(xs) // 2], fb_max=xs[-1], sc_med=cs[len(cs) // 2] if cs else float('nan'),
                       sc_max=cs[-1] if cs else float('nan'), wr=w[0] / w[1] if w and w[1] > 1e-6 else float('nan'))
    return out


def inline_check(T, phases=INL_GATE, fb_med=INL_FB_MED, fb_max=INL_FB_MAX, sc_max=INL_SC_MAX, wr=INL_WR, wr_phases=INL_WR_GATE):
    """E1 inline gate: in each swing phase of `phases` the forearm-blade angle (median <= fb_med, max <= fb_max, screen max
    <= sc_max), in each of `wr_phases` also the wrist share (<= wr). Other phases are printed as info. Returns (ok, [text])."""
    ok, txt = True, []
    for ph in ('windup', 'stroke', 'follow', 'recov', 'ready', 'block'):
        m = T.get(ph)
        if not m:
            if ph in phases:
                ok = False; txt.append(ph + ':MISSING')
            continue
        g = ph in phases
        good = not g or (m['fb_med'] <= fb_med and m['fb_max'] <= fb_max and not m['sc_max'] > sc_max and (ph not in wr_phases or not m['wr'] > wr))
        ok = ok and good
        txt.append('%s:fb=%.0f/%.0f,sc=%.0f/%.0f,wr=%.2f%s' % (ph, m['fb_med'], m['fb_max'], m['sc_med'], m['sc_max'], m['wr'],
                                                             ('' if good else ':BAD') if g else '(info)'))
    return ok, ['limits fb<=%.0f/%.0f,sc<=%.0f,wr<=%.2f(%s)' % (fb_med, fb_max, sc_max, wr, '+'.join(wr_phases))] + txt


BR_ROLL, BR_ELB, BR_TAIL = 45.0, 2.0, 5   # sword ready branch gate: edge roll about the blade (deg), elbow (dm), frames before exit


def ready_runs(F, P, tail=BR_TAIL, min_n=3):
    """Sword ready runs (contiguous melee 'ready' frames, >= min_n) that end in a swing or block: per run the pose that state
    starts from (median of the last `tail` frames): elbow, blade mf, edge mu. [(first, last, elb, mf, mu)]. Runs ending in
    lower/off/end of recording are left out (the tail is the lowering, not a ready pose)."""
    out, i, N = [], 0, len(P)
    while i < N:
        if P[i]['state'] != 'ready' or F[i]['cls'] != 0:
            i += 1; continue
        j = i
        while j + 1 < N and P[j + 1]['state'] == 'ready' and F[j + 1]['cls'] == 0:
            j += 1
        if j - i + 1 >= min_n and j + 1 < N and P[j + 1]['state'] in ('swing', 'block', 'swing->block'):
            ps = [p for p in P[max(i, j - tail + 1):j + 1] if p.get('elb') and p.get('mu')]
            if ps:
                md = lambda key: tuple(_med([p[key][k] for p in ps]) for k in range(3))
                out.append((i, j, md('elb'), nz(md('mf')), nz(md('mu'))))
        i = j + 1
    return out


def _roll(f, u0, u1):
    """Angle (deg) between two edge directions about the blade axis f (components along f removed)."""
    return _ang(sub(u0, mul(f, dot(u0, f))), sub(u1, mul(f, dot(u1, f))))


def ready_branch(R, ref=None, roll_max=BR_ROLL, elb_max=BR_ELB):
    """Sword ready elbow branch (lab 2026-10-09: replays found a second ready solution B, elbow far right + edge rolled ~100
    deg vs A, which the game recordings never show; a swing from B cannot line the edge up without a wind-up roll).
    Every ready run a swing/block starts from must match the reference pose: the majority branch of `ref` (ready runs of a
    known-good recording) when given, else of this recording (self-consistency: all runs on one branch; ties -> earliest).
    FAIL when the edge roll about the blade differs by > roll_max deg or the elbow by > elb_max dm. Returns (ok, [text])."""
    if not R:
        return False, ['ready:MISSING']
    Q = ref or R
    near = lambda x, y: _roll(nz(add(x[3], y[3])), x[4], y[4]) <= roll_max and ln(sub(x[2], y[2])) <= elb_max
    r0 = max(Q, key=lambda x: (sum(1 for y in Q if near(x, y)), -x[0]))
    ok, txt = True, ['ref %s run@%d elb=%.1f,%.1f,%.1f' % ('given' if ref else 'self', r0[0], r0[2][0], r0[2][1], r0[2][2])]
    for (a, b, el, f, u) in R:
        ro, de = _roll(nz(add(f, r0[3])), u, r0[4]), ln(sub(el, r0[2]))
        good = ro <= roll_max and de <= elb_max
        ok = ok and good
        txt.append('%d-%d:roll=%.0f,elb=%.1f%s' % (a, b, ro, de, '' if good else ':BAD'))
    return ok, ['limits roll<=%.0f,elb<=%.1f' % (roll_max, elb_max)] + txt


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


# E5 arm roll (Shay 2026-10-09, anim-sword-z0 swing 3: the forearm rolled ~180 deg mid-stroke, bracer on top, hand palm-under,
# while swings 2/4 with the same input looked right). Cause: the IK rotated the NATIVE upper arm / forearm minimally onto the
# target, so the bones' roll came from whichever native attack variant played. Per weapon-arm (right) frame: roll of each bone
# about itself = signed angle (deg) from the bend-plane normal (shoulder->elbow x elbow->wrist) to the bone's elbow-hinge axis.
#   recordings with group H (E5 builds): measured hinge axes (rendered pose); gate upper-arm |roll| <= HINGE_ABS (elbow bent)
#   older recordings: estimated by carrying the native pose's hinge onto the target with the minimal rotation (what the old
#   IK did; assumes the native anim bends about the hinge)
# Gate (both): swings from ready get identical input, so at equal swing u each bone's roll must match the median of the
# swings within HINGE_DEV deg.
HINGE_ABS, HINGE_DEV, HINGE_BENT = 25.0, 45.0, 0.4   # deg, deg, min sin(elbow bend) for a defined bend plane
HINGE_U = tuple(i / 20.0 for i in range(1, 20))


def _rot_about(axis, a, b):
    """signed angle (deg) about axis from a to b (both taken perpendicular to the axis); None if degenerate"""
    ax = nz(axis)
    a = sub(a, mul(ax, dot(a, ax))); b = sub(b, mul(ax, dot(b, ax)))
    if ln(a) < 1e-4 or ln(b) < 1e-4:
        return None
    a, b = nz(a), nz(b)
    return math.degrees(math.atan2(dot(cross(a, b), ax), dot(a, b)))


def hinge_series(F, P):
    """per frame: dict(st, swu, ua, fa, src) = upper-arm / forearm roll vs the bend plane (deg), or None"""
    S = []
    for i in range(len(P)):
        r, b = F[i], (F[i + 1] if i + 1 < len(F) else None)
        out = None
        if r['cls'] == 0 and r['on'] and r['w'] >= 0.99:
            if b is not None and b.get('hua') and ln(b['hua']) > 0.5:   # measured: record i+1 holds what frame i rendered
                J = P[i]['J']; S_, E_, H_ = J[3], J[4], J[5]
                u1, u2 = sub(E_, S_), sub(H_, E_); n = cross(u2, u1)   # camera numbers are left-handed: bend normal sign flips
                if ln(n) > HINGE_BENT * ln(u1) * ln(u2):
                    hu, hf = nz(remap(b['hua'], r, b, 0)), nz(remap(b['hfa'], r, b, 0))
                    ua, fa = _rot_about(u1, n, hu), _rot_about(u2, n, hf)
                    if ua is not None and fa is not None:
                        out = dict(ua=ua, fa=fa, src='meas')
            elif r.get('nat'):   # estimate from the native pose of this apply (old IK: minimal rotation native -> target)
                n_ = r['nat']; S_, E_, H_ = r['Rsh'], r['Rel'], r['Rwr']; Sn, En, Hn = n_['Rsh'], n_['Rel'], n_['Rwr']
                u1, u2, v1, v2 = sub(E_, S_), sub(H_, E_), sub(En, Sn), sub(Hn, En)
                hn, ht = cross(v1, v2), cross(u1, u2)
                if ln(hn) > HINGE_BENT * ln(v1) * ln(v2) and ln(ht) > HINGE_BENT * ln(u1) * ln(u2):
                    h1 = _rot_min(nz(v1), nz(u1), nz(hn))
                    h2 = _rot_min(nz(_rot_min(nz(v1), nz(u1), v2)), nz(u2), h1)
                    ua, fa = _rot_about(u1, ht, h1), _rot_about(u2, ht, h2)
                    if ua is not None and fa is not None:
                        out = dict(ua=ua, fa=fa, src='est')
        if out:
            out.update(i=i, st=P[i]['state'], swu=r.get('swu', 0.0), stk=r.get('stroke'))
        S.append(out)
    return S


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


HINGE_FAITH = 5.0   # deg: replay vs game, median per-frame bone roll error (E5 hinge replay miss: 58 deg before the rig roll model)


def hinge_faith(Sg, Sr, lim=HINGE_FAITH):
    """replay faithfulness of the bone roll: per frame where both have a roll, |game - replay| (deg) of forearm / upper arm.
    Gate: forearm median <= lim (p95 / max: info; isolated blade-roll divergences show there). Returns (ok, text)."""
    d = [(abs(_wrap(g['fa'] - r['fa'])), abs(_wrap(g['ua'] - r['ua'])), g['i']) for g, r in zip(Sg, Sr) if g and r]
    if not d:
        return False, 'faith n=0:BAD'
    fa, ua = sorted(x[0] for x in d), sorted(x[1] for x in d); w = max(d)
    q = lambda a, p: a[min(len(a) - 1, int(p * len(a)))]
    ok = q(fa, 0.5) <= lim
    return ok, 'faith n=%d fa_med=%.1f/%.0f%s fa_p95=%.1f fa_max=%.0f@%d ua_med=%.1f' % (
        len(d), q(fa, 0.5), lim, '' if ok else ':BAD', q(fa, 0.95), w[0], w[2], q(ua, 0.5))


def hinge_check(S, P, dev_max=HINGE_DEV, abs_max=HINGE_ABS, grid=HINGE_U):
    """E5 gate: (1) per swing from ready, at each u of the grid, upper-arm and forearm roll within dev_max deg of the median of
    all swings from ready; (2) measured upper-arm roll (group H) within abs_max deg of the bend plane in every swing frame
    (the forearm also carries its share of the wrist twist: gated by (1) only).
    Returns (ok, [text], detail)."""
    N = len(P)
    sw, i = [], 0
    while i < N:
        if P[i]['state'] == 'swing' and i > 0 and P[i - 1]['state'] == 'ready':
            j = i
            while j + 1 < N and P[j + 1]['state'] == 'swing':
                j += 1
            sw.append((i, j)); i = j + 1
        else:
            i += 1
    samp = []   # per swing: {u: (ua, fa)}
    for a, b in sw:
        d = {}
        for u in grid:
            best = None
            for k in range(a, b + 1):
                s = S[k]
                if s and (best is None or abs(s['swu'] - u) < abs(S[best]['swu'] - u)):
                    best = k
            if best is not None and abs(S[best]['swu'] - u) <= 0.04:
                d[u] = (S[best]['ua'], S[best]['fa'])
        samp.append(d)
    stk = []   # E6: stroke of each swing (first frame with one); medians are per stroke
    for a, b in sw:
        ks = [S[k]['stk'] for k in range(a, b + 1) if S[k] and S[k].get('stk') is not None and S[k]['stk'] >= 0]
        stk.append(ks[0] if ks else None)
    worst = (0.0, None)
    for u in grid:
        for bone in (0, 1):
          for g in sorted(set(stk), key=lambda x: -1 if x is None else x):
            vals = [(n, d[u][bone]) for n, d in enumerate(samp) if u in d and stk[n] == g]
            if len(vals) < 3:
                continue
            ref = vals[0][1]
            md = _med([ref + _wrap(v - ref) for _, v in vals])
            for n, v in vals:
                e = abs(_wrap(v - md))
                if e > worst[0]:
                    worst = (e, (n + 1, sw[n][0], u, 'ua' if bone == 0 else 'fa', v, md))
    meas = [s for s in S if s and s['src'] == 'meas' and s['st'] == 'swing']
    am = max(meas, key=lambda s: abs(s['ua'])) if meas else None   # forearm: + its share of the wrist twist, consistency only
    amv = abs(am['ua']) if am else 0.0
    ok_dev = len(sw) >= 3 and worst[0] <= dev_max
    ok_abs = amv <= abs_max
    src = 'meas' if meas else 'est'
    txt = ['src=%s swings_from_ready=%d' % (src, len(sw)) + ('' if set(stk) <= {None} else ' strokes=%s' % ','.join('-' if x is None else str(x) for x in stk))]
    txt.append('dev=%.0f/%.0f%s' % (worst[0], dev_max, '' if ok_dev else ':BAD') +
               ('@swing%d(frame%d),u=%.2f,%s=%.0f,median=%.0f' % worst[1] if worst[1] else ''))
    if len(sw) < 3:
        txt.append('need>=3 swings from ready:BAD')
    txt.append(('abs=%.0f/%.0f%s@%d' % (amv, abs_max, '' if ok_abs else ':BAD', am['i'])) if am else 'abs=n/a(no group H)')
    return ok_dev and ok_abs, txt, dict(swings=sw, samples=samp)


# ---- E6 blade visibility (Misses 2026-10-10, anim-e6 stroke 2): one-frame wind-up snap + one-frame end-on blade ----
# Both were seen in a 30 fps video and missed by the windowed checks (vis median over u .38-.62, churn steps per game
# frame). Judged per frame / per video-frame window instead.
SNAP_WIN, SNAP_U, SNAP_MAX = 0.034, 0.10, 22.0   # s (one 30 fps video frame), u after the wind-up top, deg
SEE_L, SEE_U0, SEE_U1, SEE_MIN = 7.0, 0.45, 0.95, 0.05   # dm blade seen past the grip, gated u range, min visible blade
# seen counts an edge-on crossing between two frames as 0 (sampling-independent: a 30 fps video catches it at random)


def _bframe(p):
    f = nz(p['mf']); s = nz(cross(f, p['mu'])); return f, nz(cross(s, f)), s


def blade_rot(a, b):
    """rotation angle (deg) between the sword frames (blade, edge) of two rendered frames."""
    A, B = _bframe(a), _bframe(b)
    tr = sum(dot(A[k], B[k]) for k in range(3))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2))))


# ---- one-frame weapon snap / flick (Misses 2026-10-10 "PT30 follow-through edge roll spikes" + mutation gaps
# rec-one-frame-snap / rec-one-frame-jump; class: roll spike / one-frame pose jump). Per rendered frame of the viewmodel
# (w >= .99, weapon in hand, not zoom-faded / band-hidden, on screen; hitch frames and their neighbours skipped):
#   flick: frame i shows a weapon orientation its neighbours skip: rot(i-1,i) + rot(i,i+1) - rot(i-1,i+1) > SPK_FLICK
#   step:  one rendered frame turns the weapon > SPK_STEP deg and > SPK_RATIO x both neighbour steps (per animation step
#          min(dt, maxdt), PT30-FLIP time base)
#   pos:   the grip jumps out and back in one frame (both steps > SPK_POS dm, the two-frame step < half of them)
# Calibrated on the corpus 2026-10-10: Shay/coordinator-accepted recs (f28, f23, e6-anim, spec-swing-A, e6fix, crossbow
# recs) flick <= 37 (f28 164), step <= 36 (e6-anim 989), pos 0; game pt30-sword frame 284 step 77; taste rejects f14-e0 /
# e1k-cand / vmq85a7-sw step 93-104, f13-sw0 flick 257; mutants: snap flick 69, jump pos 1.5.
SPK_FLICK, SPK_STEP, SPK_RATIO, SPK_POS, SPK_MAXDT = 45.0, 60.0, 2.5, 0.5, 0.05


def spike_check(F, P, flick=SPK_FLICK, step=SPK_STEP, ratio=SPK_RATIO, pos=SPK_POS, maxdt=SPK_MAXDT):
    """(ok|None, parts): one-frame snap/flick of the rendered weapon pose (see SPK_* above)."""
    N = len(P)
    if N < 5:
        return None, ['spike n/a (short rec)']
    dts = sorted(F[i]['dt'] for i in range(N))
    dth = max(0.045, 3 * dts[N // 2])   # hitch: > 3x the median frame time (vmcheck DTH)
    up = [F[i]['w'] >= 0.99 and P[i]['wih'] and F[i].get('zf', 1.0) > 0.99 and not F[i].get('band_hidden')
          and P[i]['tpx'] is not None for i in range(N)]
    adt = lambda i: max(min(F[i]['dt'], maxdt), 1e-4)
    rs, ps = [None] * N, [None] * N
    for i in range(1, N):
        if up[i] and up[i - 1]:
            rs[i] = blade_rot(P[i - 1], P[i]); ps[i] = sub(P[i]['mp'], P[i - 1]['mp'])
    bad, n, mx = [], 0, dict(flick=(0.0, -1), step=(0.0, -1), pos=(0.0, -1))
    for i in range(2, N - 1):
        if rs[i] is None or rs[i - 1] is None or rs[i + 1] is None or max(F[j]['dt'] for j in (i - 1, i, i + 1)) > dth:
            continue
        n += 1
        st = P[i].get('state') or F[i]['st']
        d = rs[i] + rs[i + 1] - blade_rot(P[i - 1], P[i + 1])
        nb = max(rs[i - 1] * adt(i) / adt(i - 1), rs[i + 1] * adt(i) / adt(i + 1))
        pa, pb = ln(ps[i]), ln(ps[i + 1])
        pd = min(pa, pb) if ln(add(ps[i], ps[i + 1])) < 0.5 * min(pa, pb) else 0.0
        for k, v, b_ in (('flick', d, d > flick), ('step', rs[i], rs[i] > step and rs[i] > ratio * nb), ('pos', pd, pd > pos)):
            if v > mx[k][0]:
                mx[k] = (v, i)
            if b_:
                bad.append('%s@%d:%s=%.1f' % (st, i, k, v))
    if not n:
        return None, ['spike n/a (no viewmodel frames)']
    txt = ['%d frames flick_max=%.0f@%d/%.0f step_max=%.0f@%d/%.0f pos_max=%.2f@%d/%.2f' % (
        n, mx['flick'][0], mx['flick'][1], flick, mx['step'][0], mx['step'][1], step, mx['pos'][0], mx['pos'][1], pos)]
    return not bad, txt + bad[:6]


def blade_seen(p, L=SEE_L, zn=3.0, n=40):
    """visible blade proxy: on-screen length (x/z units) of grip..grip+L*blade (samples nearer than zn dm or outside the
    view dropped) times |flat normal . view ray| (an edge-on katana is a hairline: the 3.68 s / 13.67 s anim-e6 frames)."""
    mp, mf = p['mp'], nz(p['mf']); pts = []
    for i in range(n + 1):
        c = add(mp, mul(mf, L * i / n))
        if c[2] >= zn and abs(c[1] / c[2]) <= .85 and abs(c[0] / c[2]) <= 1.5:
            pts.append((c[0] / c[2], c[1] / c[2]))
    sl = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)))
    w = dot(nz(cross(mf, p['mu'])), nz(add(mp, mul(mf, L / 2))))   # signed: a sign change = the blade rolled through edge-on
    return sl * abs(w), sl, w


def swings(F, P):
    """[[frame index, ...] per swing] over frames labelled 'swing' (STROKE_ONLY respected)."""
    out, cur = [], None
    for i, p in enumerate(P):
        if p['state'] == 'swing' and p['wih']:
            if cur is None:
                cur = []; out.append(cur)
            cur.append(i)
        else:
            cur = None
    return out


def blade_check(F, P, snap_max=SNAP_MAX, see_min=SEE_MIN, win=SNAP_WIN, snap_u=SNAP_U, u0=SEE_U0, u1=SEE_U1):
    """E6 per swing: (1) snap = max sword rotation over one video frame (win s) in [top, top+snap_u], top = slowest
    window of the wind-up end (u ARC_U0-.1 .. ARC_U0+.12); (2) seen = per-frame min blade_seen over u [u0, u1]."""
    txt, ok, ws, wv = [], True, None, None
    for k, idx in enumerate(swings(F, P)):
        rate = []
        for n, i in enumerate(idx):
            j = n
            while j > 0 and F[idx[n]]['t'] - F[idx[j - 1]]['t'] <= win:
                j -= 1
            if j < n:
                rate.append((F[i]['swu'], blade_rot(P[idx[j]], P[i]), i))
        top = [r for r in rate if ARC_U0 - 0.1 <= r[0] <= ARC_U0 + 0.12]
        if top:
            ut = min(top, key=lambda r: r[1])[0]
            mx = max((r for r in rate if ut <= r[0] <= ut + snap_u), key=lambda r: r[1])
            if ws is None or mx[1] > ws[1]:
                ws = (k, mx[1], mx[0], mx[2], ut)
        g = [(blade_seen(P[i]), F[i]['swu'], i) for i in idx if u0 <= F[i]['swu'] <= u1]
        seen = [(x[0][0], x[1], x[2]) for x in g]
        # between frames: a flat-facing sign change means the blade passed edge-on (seen 0) whatever frames were sampled
        seen += [(0.0, g[n + 1][1], g[n + 1][2]) for n in range(len(g) - 1) if g[n][0][2] * g[n + 1][0][2] < 0]
        if seen:
            mn = min(seen)
            if wv is None or mn[0] < wv[1]:
                wv = (k, mn[0], mn[1], mn[2])
    if ws:
        good = ws[1] <= snap_max; ok = ok and good
        txt.append('snap=%.0f/%.0f%s@swing%d(frame%d),u=%.2f,top=%.2f' % (ws[1], snap_max, '' if good else ':BAD', ws[0], ws[3], ws[2], ws[4]))
    else:
        ok = False; txt.append('snap=n/a(no swing):BAD')
    if wv:
        good = wv[1] >= see_min; ok = ok and good
        txt.append('seen=%.3f/%.2f%s@swing%d(frame%d),u=%.2f' % (wv[1], see_min, '' if good else ':BAD', wv[0], wv[3], wv[2]))
    return ok, txt


# ---- E6 stroke readability (Misses 2026-10-10, anim-sword-e6 A2C2E8AC): stroke 1 blade foreshortened into the screen,
# stroke 2 overhead read as a diagonal. inline/blade passed both: inline measures 0.5 dm straight segments at the grip
# (sc 3-22 deg) and the 3D forearm-blade angle (~30), but a blade pointing into the screen (mf.z ~0.9) is drawn as a short
# curved stub whose visible shape no longer follows the forearm; blade 'seen' gates only the end-on facing, not the length.
STK_LEN_U, STK_LEN_MIN = (0.40, 0.78), 240.0   # u window (stroke + follow), min on-screen blade length px (1600 wide)
STK_OH_U, STK_OH_TILT, STK_OH_PATH = (0.28, 0.78), 35.0, 20.0   # overhead: u window, max blade tilt and mid-path angle from vertical


def _uproj(c):
    """screen px of a camera-numbers point, not clipped to the view (None behind / at the eye)."""
    if c[2] < 0.3:
        return None
    return (W_PX / 2 + W_PX / 2 * (c[0] / c[2]) / TX, H_PX / 2 - H_PX / 2 * (c[1] / c[2]) / TY)


def stroke_series(F, P, L=7.0):
    """per swing: [(u, frame, len_px, tilt_deg, mid_px)]: grip -> grip + L*blade on screen (unclipped); tilt = blade angle
    from screen vertical (+ = tip right); mid = the blade point ARC_MID dm from the grip."""
    out = []
    for idx in swings(F, P):
        S = []
        for i in idx:
            p = P[i]; g = _uproj(p['mp']); t = _uproj(add(p['mp'], mul(p['mf'], L))); m = _uproj(add(p['mp'], mul(p['mf'], ARC_MID)))
            if g and t:
                dx, dy = t[0] - g[0], t[1] - g[1]
                S.append((F[i]['swu'], i, math.hypot(dx, dy), math.degrees(math.atan2(dx, -dy)), m))
        out.append((F[idx[0]].get('stroke'), S))
    return out


def stroke_check(F, P, overhead=(), len_min=STK_LEN_MIN, len_u=STK_LEN_U, tilt_max=STK_OH_TILT, path_max=STK_OH_PATH, oh_u=STK_OH_U):
    """E6 per swing: (1) len = min on-screen blade length over len_u >= len_min px (a blade foreshortened into the screen
    reads as a stub at an odd angle to the forearm); (2) strokes in `overhead` (scripted stroke ids): blade tilt from
    screen vertical <= tilt_max over oh_u and the blade-middle path from the first to the last frame of the stroke
    (u ARC_U0..ARC_U1) within path_max of straight down."""
    txt, ok = [], True
    sw = stroke_series(F, P)
    if not sw:
        return False, ['no swing:BAD']
    for k, (stk, S) in enumerate(sw):
        L = [s for s in S if len_u[0] <= s[0] <= len_u[1]]
        parts = []
        if L:
            m = min(L, key=lambda s: s[2]); g = m[2] >= len_min; ok = ok and g
            parts.append('len=%.0f/%.0f%s@u%.2f(frame%d)' % (m[2], len_min, '' if g else ':BAD', m[0], m[1]))
        else:
            ok = False; parts.append('len=n/a:BAD')
        if stk is not None and stk in overhead:
            T = [s for s in S if oh_u[0] <= s[0] <= oh_u[1]]
            M_ = [s[4] for s in S if ARC_U0 <= s[0] <= ARC_U1 and s[4]]
            if T and len(M_) > 1:
                w = max(T, key=lambda s: abs(s[3])); dx, dy = M_[-1][0] - M_[0][0], M_[-1][1] - M_[0][1]
                pa = math.degrees(math.atan2(abs(dx), dy)) if dy > 0 else 180.0
                g1, g2 = abs(w[3]) <= tilt_max, pa <= path_max; ok = ok and g1 and g2
                parts.append('overhead tilt=%.0f/%.0f%s@u%.2f(frame%d) path=%.0f/%.0f%s(%+.0f,%+.0f px)' % (
                    abs(w[3]), tilt_max, '' if g1 else ':BAD', w[0], w[1], pa, path_max, '' if g2 else ':BAD', dx, dy))
            else:
                ok = False; parts.append('overhead n/a:BAD')
        txt.append('swing%d%s:%s' % (k, '' if stk is None else '(stroke%d)' % stk, ','.join(parts)))
    return ok, txt


# ---- guard readability (Miss 2026-10-10 sword-z25-block.mp4, orbit 3.0: the zoom-25 block guard showed the blade hanging
# straight down with the hilt at the face, a stick in front of the body). Judged in the world frame (camera-independent):
# blade elevation above the horizontal per block frame; info: hilt distance from the head bone.
GUARD_ELEV = -60.0   # deg: median blade elevation over block frames must be above this (a hanging guard is ~-80..-90)


def guard_series(F, P):
    """[(frame, elev_deg, hilt_head_dm)] over rendered block frames (state block / swing->block, or the recorded UI
    state blocking: zoomed-out frames are labelled native)."""
    out = []
    for i, p in enumerate(P):
        r = F[i]
        if not p['wih'] or not (p['state'] in ('block', 'swing->block') or r['st'] == 'blocking' or r['ti'] == 3):
            continue
        U = nz((r['rt'][1], r['up'][1], r['fw'][1])) if r.get('rt') else (0.0, 1.0, 0.0)
        e = math.degrees(math.asin(max(-1.0, min(1.0, dot(nz(p['mf']), U)))))
        hd = F[i + 1].get('hd') if i + 1 < len(F) else None
        out.append((i, e, ln(sub(p['mp'], hd)) if hd else float('nan')))
    return out


GUARD_GAP, GUARD_SETTLE = 3, 0.3   # frames between presses; share of each press skipped while the guard rises


def guard_presses(S, gap=GUARD_GAP):
    """block presses = runs of block frames (frame numbers at most `gap` apart) -> [[(frame, elev, hilt_head)], ...]."""
    out = []
    for x in S:
        if out and x[0] - out[-1][-1][0] <= gap:
            out[-1].append(x)
        else:
            out.append([x])
    return out


def guard_check(S, elev_min=GUARD_ELEV, min_n=5, settle=GUARD_SETTLE):
    """EVERY block press must hold a readable guard (Miss 2026-10-10 blk-survey: the free block picks a native block
    technique per press, 2 raise the blade and 3 hang it, so a median over the whole recording passed a take with
    hanging presses): per press, median elevation over its settled frames (after the first `settle` share) >= elev_min."""
    if len(S) < min_n:
        return False, ['block frames=%d < %d:BAD' % (len(S), min_n)]
    pr = guard_presses(S)
    bad, meds = [], []
    for k, p in enumerate(pr):
        q = p[int(len(p) * settle):] or p
        es = sorted(x[1] for x in q); med = es[len(es) // 2]
        meds.append(med)
        if med < elev_min:
            bad.append('press%d@frame%d:elev%.0f' % (k, p[0][0], med))
    lo = min(S, key=lambda s: s[1])
    hh = sorted(s[2] for s in S if s[2] == s[2])
    ok = not bad
    return ok, ['presses=%d hanging=%d%s' % (len(pr), len(bad), '' if ok else ':BAD'), 'elev_press_min=%.0f/%.0f' % (min(meds), elev_min),
                'elev_min=%.0f@frame%d' % (lo[1], lo[0]), 'hilt_head_med=%.1fdm(info)' % (hh[len(hh) // 2] if hh else float('nan')),
                'block_frames=%d' % len(S)] + (bad[:8] if bad else [])


def guard_table_check(rows, elev_min=GUARD_ELEV):
    """per-press survey rows [(label, elev_deg, tech)] (blk-survey blk-table.tsv: one `fp_vm state` sample per press)."""
    bad = ['%s:%s:elev%.0f' % (lb, tech, e) for lb, e, tech in rows if e < elev_min]
    techs = {}
    for lb, e, tech in rows:
        techs.setdefault(tech, []).append(e)
    ok = bool(rows) and not bad
    return ok, ['presses=%d hanging=%d%s' % (len(rows), len(bad), '' if ok else ':BAD'),
                'per_tech=' + ','.join('%s:%.0f' % (t, sorted(v)[len(v) // 2]) for t, v in sorted(techs.items()))] + bad[:6]


# ---- zoom band body check (Miss 2026-10-10 zoom-sweep.mp4, Z1 crossfade 2-8 dm: own headless torso/shoulders, a floating
# hand and an oversized hand on the stock in frame). The zoom camera sits `zoom` dm behind the eye along the view axis
# (KenshiFP fp_view_apply, orbit 0) and the head stays hidden below head_show dm: anything of the own torso the camera
# sees in that band is a headless body part. Judged from the recorded neck/spine/shoulder/elbow positions.
ZB_EYE, ZB_HEAD_SHOW, ZB_NEAR = 0.05, 16.0, 0.3   # dm: eye limit, KenshiFP g_cfg_head_show_dm, camera near plane
ZB_PARTS = ('nk', 'sp', 'Lsh', 'Rsh', 'Lel', 'Rel', 'Lwr', 'Rwr', 'chest')   # wrists: the floating hand


def zoomband_series(F, head_show=ZB_HEAD_SHOW, eye=ZB_EYE, near=ZB_NEAR):
    """[(frame, zoom, [(part, x_ndc, y_ndc, depth)])] for frames whose camera distance is in (eye, head_show): own body
    parts inside the zoomed camera's view (|x| <= 1, |y| <= 1 in screen units, depth > near)."""
    out = []
    for i, r in enumerate(F):
        d = r.get('zoom', 0.0)
        if not (eye < d < head_show) or r.get('nk') is None or r.get('band_hidden'):
            continue   # band_hidden: KenshiFP hides the whole character + weapon in the band (joints still move, nothing drawn)
        pts = dict(nk=r['nk'], sp=r['sp'], Lsh=r['Lsh'], Rsh=r['Rsh'], Lel=r['Lel'], Rel=r['Rel'], Lwr=r['Lwr'], Rwr=r['Rwr'])
        pts['chest'] = mul(add(add(r['Lsh'], r['Rsh']), r['sp']), 1.0 / 3.0)
        seen = []
        for k in ZB_PARTS:
            if k[1:] in ('el', 'wr') and r.get('zf', 1.0) >= NATIVE_ZF:
                continue   # full viewmodel (zf 1, below zf0): the FP arms in view are the intended first-person hands
            p = pts[k]; z = p[2] + d
            if z > near:
                x, y = p[0] / z / TX, p[1] / z / TY
                if abs(x) <= 1.0 and abs(y) <= 1.0:
                    seen.append((k, x, y, z))
        out.append((i, d, seen))
    return out


ZB_HIDE_EYE = 0.65   # dm: KenshiFP KFP_VIEW_EYE_LIMIT (fp_view_band: band hide on for eye limit <= applied zoom < head_show)


def flag_lag(F, flag, expect):
    """CLASS recorded state label vs rendered state (Misses 2026-10-10 Z1 zoomband: the rec wrote band_hidden before the
    hide it describes, so the first band frame of every wheel-out was labelled unhidden and the lab judged a stale label).
    A recorded flag whose rule is known from the same frame's other fields must agree with it on that frame: frames where
    flag != expect(frame) but == expect(previous frame) = the label lags the state change by a frame.
    Returns [(frame, recorded, expected)]."""
    out = []
    for i in range(1, len(F)):
        v, e, ep = F[i].get(flag), expect(F[i]), expect(F[i - 1])
        if v is None or e is None:
            continue
        if bool(v) != e and bool(v) == ep:
            out.append((i, int(bool(v)), int(e)))
    return out


def band_expect(F, head_show=ZB_HEAD_SHOW, eye=ZB_HIDE_EYE):
    """expect(frame) for band_hidden (None when the rec never hides: band_hide off / older build)."""
    if not any(r.get('band_hidden') for r in F):
        return lambda r: None
    return lambda r: eye <= r.get('zoom', 0.0) < head_show


# ---- band leak (Misses 2026-10-10 ZOOMSWEEP-zs-sword-fade-on 9C9ECB01: hat-brim shard + neck/shoulder slivers for ~0.55 s in
# the zoom-out ease tail with band_hidden=1; zoomband skipped those frames as "nothing drawn" and PASSed body_in_frame=0/0).
# CLASS: band_hidden is a visibility flag, not proof nothing renders (worn pieces re-shown, mask holes, attachments the hide
# misses). On a band_hidden frame every own-body part the zoomed camera has in view must lie inside the camera near clip
# (KenshiFP kfp-zband-clip e4bb536: near = applied + band_clip_dm while the band hide is on), so nothing can leak.
# Near clip: the rec's nc column (kfp-vmrec-nc builds), else the build rule given as band_clip (dm; 0 = builds before
# e4bb536, near = ZB_NEAR), else not judged (SKIP).
ZB_CLIP_MARGIN = 1.0   # dm: mesh extent past the recorded joint (hat brim, pauldron, sleeve) that must be clipped too
ZB_HAT_UP = 1.2        # dm: hat crown/brim above the head bone (camera up)
ZB_LEAK_PARTS = ('nk', 'sp', 'Lsh', 'Rsh', 'chest', 'hd', 'hat')   # head + torso, where the worn pieces leaked (hat brim,
# neck/shoulder slivers). Elbows/wrists are not judged: in swings the hands reach up to 1.4 dm past applied + 5 dm
# (8b3f, 4080 recs) and rendered clean (8B3F339C every-frame review): the arm meshes are covered by the band hide itself.


def bandleak_series(F, head_show=ZB_HEAD_SHOW, eye=ZB_HIDE_EYE, band_clip=None, near=ZB_NEAR):
    """[(frame, zoom, nc, [(part, x_ndc, y_ndc, depth)])] for band_hidden band frames; parts in view whose far extent
    (depth + ZB_CLIP_MARGIN) lies beyond the near clip. nc None = near clip unknown (frame not judged)."""
    out = []
    for i, r in enumerate(F):
        d = r.get('zoom', 0.0)
        if not r.get('band_hidden') or not (eye <= d < head_show) or r.get('nk') is None:
            continue
        nc = r.get('nc')
        if nc is None or nc < 0:
            nc = None if band_clip is None else max(near, d + band_clip if band_clip > 0 else near)
        pts = dict(nk=r['nk'], sp=r['sp'], Lsh=r['Lsh'], Rsh=r['Rsh'], Lel=r['Lel'], Rel=r['Rel'], Lwr=r['Lwr'], Rwr=r['Rwr'])
        pts['chest'] = mul(add(add(r['Lsh'], r['Rsh']), r['sp']), 1.0 / 3.0)
        if r.get('hd') is not None:
            pts['hd'] = r['hd']; pts['hat'] = add(r['hd'], (0.0, ZB_HAT_UP, 0.0))
        seen = []
        if nc is not None:
            for k in ZB_LEAK_PARTS:
                p = pts.get(k)
                if p is None:
                    continue
                z = p[2] + d
                if z <= 0.05 or z + ZB_CLIP_MARGIN <= nc:
                    continue
                x, y = p[0] / z / TX, p[1] / z / TY
                if abs(x) <= 1.0 and abs(y) <= 1.0:
                    seen.append((k, x, y, z))
        out.append((i, d, nc, seen))
    return out


def bandleak_check(S, max_frames=0):
    """['band_leak=...'] term for zoomband: FAIL when more than max_frames band_hidden frames leave an own body part in
    view beyond the near clip; SKIP when no band_hidden frame has a known near clip."""
    J = [s for s in S if s[2] is not None]
    if not J:
        return True, ['band_leak=SKIP(%d band_hidden frames, no nc: pass --band-clip <dm>)' % len(S)]
    bad = [s for s in J if s[3]]
    ok = len(bad) <= max_frames
    txt = ['band_leak=%d/%d%s' % (len(bad), len(J), '' if ok else ':BAD')]
    if bad:
        w = max(bad, key=lambda s: len(s[3]))
        txt.append('leak_worst=frame%d,zoom=%.1f,nc=%.1f,%s' % (w[0], w[1], w[2], '+'.join('%s(z%.1f)' % (p[0], p[3]) for p in w[3])))
    return ok, txt


def zoomband_check(S, max_frames=0, lag=None):
    """FAIL when more than max_frames band frames show an own body part, or (lag = flag_lag result) the band_hidden label
    lags the zoom. Prints the band frames, the zoom range seen and the worst frame (most parts, nearest)."""
    bad = [s for s in S if s[2]]
    txt = ['band_frames=%d' % len(S)]
    if S:
        txt.append('zoom=%.1f..%.1f' % (min(s[1] for s in S), max(s[1] for s in S)))
    ok = len(bad) <= max_frames
    txt.append('body_in_frame=%d/%d%s' % (len(bad), max_frames, '' if ok else ':BAD'))
    if lag is not None:
        txt.append('label_lag=%d%s' % (len(lag), (':BAD@' + ','.join('%d(bh%d,want%d)' % x for x in lag[:6])) if lag else ''))
        ok = ok and not lag
    if bad:
        w = max(bad, key=lambda s: (len(s[2]), -min(p[3] for p in s[2])))
        txt.append('worst=frame%d,zoom=%.1f,%s' % (w[0], w[1], '+'.join('%s(z%.1f)' % (p[0], p[3]) for p in w[2])))
    return ok, txt


# ---- native swing pool (Misses 2026-10-10 E6 kfx-b2 e6fix, KenshiFP F0595751): the game plays a native attack variant per
# swing and the solver's rendered stroke depends on it (same commanded keys: stroke 1 arc_ok 0.83 in one swing, 0.42 in the
# next). The offline "prediction" replayed ONE old recording with one swing per stroke (arc 1.00) and the game failed.
# Predict a take instead from every native swing in a pool of recordings (each replayed with the stroke forced).
# CLASS: any check on a motion the game plays with a random native variant (swing strokes, free-block techniques, ...)
# predicts over the variant pool (pool_predict), never from one recording.
POOL_RATE, POOL_TAKE, POOL_MIN_ARC_N = 0.95, 2, 6   # min predicted take pass rate, swings per take, arc frames of a full swing


def swing_verdicts(F, P, overhead=()):
    """per swing of a recording: arc counts, wrist bend, blade + stroke checks judged on that swing alone; churn = the
    swing's wind-up roll (<= ROLL_MAX) and stroke-start roll (<= SROLL_MAX, step <= SROLL_STEP; R3, gated like the
    scripted-stroke check_suite: Misses 2026-10-10 "pool does not run every gated per-stroke rule", e6r5 s1 51 deg passed
    the pool). The arm-churn reversal (rev) is not per swing and stays in the recording checks."""
    out = []
    _, _, cd = churn_check(churn_series(F, P), sroll_gate=True)
    for k, idx in enumerate(swings(F, P)):
        keep = set(idx)
        rl = [r for r in cd['rolls'] if r[1] in keep]; sr = [r for r in cd['srolls'] if r[2] in keep]
        cok = all(r[0] <= ROLL_MAX for r in rl) and all(r[0] <= SROLL_MAX and r[1] <= SROLL_STEP for r in sr)
        ctxt = 'windup_roll=%s stroke_roll=%s' % ('%.0f' % max(r[0] for r in rl) if rl else '-',
                                                 '%.0f/step%.1f' % (max(r[0] for r in sr), max(r[1] for r in sr)) if sr else '-')
        Pm = [p if p['state'] != 'swing' or i in keep else dict(p, state='swing_x') for i, p in enumerate(P)]
        ar = [P[i]['arc'] for i in idx if P[i].get('arc') is not None]
        wb = [P[i]['wb'] for i in idx if P[i]['wb'] is not None]
        bok, btxt = blade_check(F, Pm)
        sok, stxt = stroke_check(F, Pm, overhead)
        us = [F[i]['swu'] for i in idx]
        out.append(dict(k=k, frame=idx[0], stroke=F[idx[0]].get('stroke'), arc_good=sum(1 for x in ar if x >= 0.7), arc_n=len(ar),
                        wb_max=max(wb) if wb else 0.0, ok=dict(blade=bok, stroke=sok, churn=cok), btxt=btxt, stxt=stxt, ctxt=ctxt,
                        full=us[0] <= 0.1 and us[-1] >= 0.9 and len(ar) >= POOL_MIN_ARC_N))
    return out


def pool_predict(V, checks=('arc', 'blade', 'stroke', 'churn'), take=POOL_TAKE, rate=POOL_RATE, share=0.85, wb_lim=None):
    """V = swing_verdicts rows (+ 'rec'). A take of `take` swings draws native variants at random: predicted take pass rate =
    share of all `take`-combinations of full pool swings that pass (arc pooled over the take like the game's arc gate,
    blade/stroke = every swing passes). PASS when every check's rate >= `rate`."""
    import itertools
    wb_lim = ARC_WB if wb_lim is None else wb_lim
    full = [v for v in V if v['full']]
    if len(full) < take:
        return False, ['swings=%d full=%d < %d:BAD' % (len(V), len(full), take)]
    def one(v, c):
        if c == 'arc':
            return v['arc_good'] >= share * v['arc_n'] and v['wb_max'] <= wb_lim
        return v['ok'][c]
    def comb(cs, c):
        if c == 'arc':
            return sum(v['arc_good'] for v in cs) >= share * sum(v['arc_n'] for v in cs) and max(v['wb_max'] for v in cs) <= wb_lim
        return all(one(v, c) for v in cs)
    combos = list(itertools.combinations(full, take))
    ok, txt = True, ['swings=%d full=%d recs=%d takes=%d' % (len(V), len(full), len({v.get('rec') for v in full}), len(combos))]
    allpass = [True] * len(combos)
    for c in checks:
        r = [comb(cs, c) for cs in combos]
        allpass = [x and y for x, y in zip(allpass, r)]
        tr = sum(r) / float(len(r)); sw = sum(1 for v in full if one(v, c)) / float(len(full))
        good = tr >= rate; ok = ok and good
        bad = [v for v in full if not one(v, c)]
        if c == 'arc':
            bad.sort(key=lambda v: v['arc_good'] / float(v['arc_n']))
            worst = ','.join('%s@%d:%.2f' % (v.get('rec', '?'), v['frame'], v['arc_good'] / float(v['arc_n'])) for v in bad[:3])
        else:
            worst = ','.join('%s@%d' % (v.get('rec', '?'), v['frame']) for v in bad[:3])
        txt.append('%s:take=%.2f/%.2f,swing=%.2f%s%s' % (c, tr, rate, sw, '' if good else ':BAD', (',worst=' + worst) if bad else ''))
    txt.insert(1, 'take_all=%.2f' % (sum(allpass) / float(len(allpass))))
    return ok, txt


def guard_press_verdicts(S, elev_min=GUARD_ELEV, settle=GUARD_SETTLE, min_n=3):
    """per block press (guard_presses): settled median elevation; rows for pool_predict (check 'guard')."""
    out = []
    for k, p in enumerate(guard_presses(S)):
        q = p[int(len(p) * settle):] or p
        es = sorted(x[1] for x in q); med = es[len(es) // 2]
        out.append(dict(k=k, frame=p[0][0], elev=med, full=len(p) >= min_n, ok=dict(guard=med >= elev_min)))
    return out


# ---- check suite + lab/game agreement (the lab must predict the game: every check runs on the game rec and on its replay
# through the build's own solver; a pass/fail disagreement is a lab bug -> Misses row) ----
import re as _re


def _nums(txt):
    return [(k, float(v)) for k, v in _re.findall(r'([A-Za-z_]+)=(-?\d+(?:\.\d+)?)', txt)]


def _both(a, b):
    """pooled gate + every-occurrence gate: PASS only if both pass."""
    return a[0] and b[0], list(a[1]) + ['each:'] + list(b[1])


def check_suite(rec, overhead=(2,)):
    """[(check, ok, text)] for every check that applies to the recording; swing checks per scripted stroke (E6 recs)."""
    global STROKE_ONLY
    F = rec.frames
    strokes = sorted({f.get('stroke') for f in F if f.get('stroke') is not None and f.get('stroke') >= 0 and f['swing']})
    out = []

    def run(name, fn):
        try:
            r = fn()
            out.append((name, bool(r[0]), ' '.join(r[1])))
        except Exception as e:   # a check that cannot run on this rec is not a result
            out.append((name, None, 'n/a %s' % type(e).__name__))
    saved = STROKE_ONLY
    try:
        STROKE_ONLY = None
        P = frame_metrics(rec)
        T = state_table(P)
        req = ('aim', 'reload') if ('aim' in T or 'reload' in T) else ('block', 'swing') if ('block' in T or 'swing' in T) else ()
        if req:
            run('moves', lambda: _both(moves_ok(T, req), moves_each(P, req)))
        if 'ready' in T and F[0]['cls'] == 0:
            run('branch', lambda: ready_branch(ready_runs(F, P)))
        if 'ready' in T and any(f['cls'] == 1 for f in F):
            lab = label_states(F)
            run('stock', lambda: stock_ok(stock_table(F, lab), pose_dirs(F, lab)))
        G = guard_series(F, P)
        if G:
            run('guard', lambda: guard_check(G))
        sk = spike_check(F, P)
        if sk[0] is not None:
            run('spike', lambda: sk)
        for s in (strokes or [None]):
            STROKE_ONLY = s
            P = frame_metrics(rec)
            T = state_table(P)
            tag = '' if s is None else '[s%d]' % s
            if 'swing' not in T:
                continue
            run('arc' + tag, lambda: arc_gate(T, {'swing': ARC_SHARE}))   # arc_each not wired: taste R8 FP on accepted f28 (swings 0.75/0.62)
            # scripted E6 strokes are fitted to the stroke-start roll limit (R3 no sudden wrist/blade roll): gated there
            # (Misses 2026-10-10 E6-e6r5: stroke 1 rolled 51 deg in 4 frames, printed "(info)" and passed); the native
            # swing (s None, rolls ~150 deg) keeps it as info
            run('churn' + tag, lambda: churn_check(churn_series(F, P), sroll_gate=s is not None)[:2])
            run('inline' + tag, lambda: _both(inline_check(inline_table(inline_series(F, P))), inline_each(F, P)))
            run('blade' + tag, lambda: blade_check(F, P))
            run('stroke' + tag, lambda: stroke_check(F, P, overhead))
            if any(f.get('hua') for f in F):
                run('hinge' + tag, lambda: hinge_check(hinge_series(F, P), P)[:2])
    finally:
        STROKE_ONLY = saved
    return out


def agree_rows(game, replay):
    """[(check, game ok, replay ok, agree, deltas)] for the checks both runs could judge."""
    G = {c: (ok, t) for c, ok, t in check_suite(game)}
    R = {c: (ok, t) for c, ok, t in check_suite(replay)}
    rows = []
    for c in G:
        if c not in R or G[c][0] is None or R[c][0] is None:
            continue
        gn, rn = _nums(G[c][1]), _nums(R[c][1])
        if [k for k, _ in gn] != [k for k, _ in rn]:   # same text shape: pair values by position (keys repeat per phase)
            rd = dict(rn); rn = [(k, rd[k]) for k, _ in gn if k in rd]
        d = ['%s %g/%g' % (k, g, r) for (k, g), (_, r) in zip(gn, rn) if abs(g - r) > 1e-9][:3]
        rows.append((c, G[c][0], R[c][0], G[c][0] == R[c][0], ' '.join(d)))
    return rows


# ---- every occurrence (CLASS audit 2026-10-10, Shay via coordinator: a state check judges EVERY occurrence of its state in
# a rec/take, never one pooled value: the per-press guard miss showed a pooled median hiding a bad press). moves, arc and
# inline pooled all occurrences; these wrappers judge each run of the state / each swing and fail on the worst one.
OCC_MIN_ARC_N = 6   # arc frames a swing needs to be judged on its own (a cut-off swing at the rec edge is skipped)


def occurrences(P, state):
    """runs of consecutive frames labelled `state` (viewmodel in hand) -> [[frame index, ...], ...]."""
    out, cur = [], None
    for i, p in enumerate(P):
        if p['state'] == state and p['wih']:
            if cur is None:
                cur = []
                out.append(cur)
            cur.append(i)
        else:
            cur = None
    return out


def moves_each(P, required, min_n=3):
    """C1 per occurrence: every run (>= min_n frames) of each required state moves the weapon from the median ready pose
    (held states by the run's median pose, paths by its largest frame). Returns (ok, [text])."""
    R = [p for p in P if p['state'] == 'ready' and p['wih']]
    if not R:
        return False, ['ready:MISSING']
    rp, rf = _mpose(R)
    ok, txt = True, []
    for s in required:
        runs = [r for r in occurrences(P, s) if len(r) >= min_n]
        if not runs:
            ok = False
            txt.append(s + ':MISSING')
            continue
        still = []
        for r in runs:
            ps = [P[i] for i in r]
            if s in HELD_STATES:
                mp, mf = _mpose(ps)
                dm, dg = ln(sub(mp, rp)), _ang(mf, rf)
            else:
                dm, dg = max(ln(sub(p['mp'], rp)) for p in ps), max(_ang(p['mf'], rf) for p in ps)
            if dm < MOVE_DM and dg < MOVE_DEG:
                still.append('%s@%d:%.1fdm/%.0fdeg' % (s, r[0], dm, dg))
        ok = ok and not still
        txt.append('%s:%d/%d moved%s' % (s, len(runs) - len(still), len(runs), (':STILL ' + ','.join(still[:4])) if still else ''))
    return ok, txt


# ---- crossbow reload posture (Shay 2026-10-10, spec video xbow-reload.mp4: the two-hand upright reload, rlnat 1,
# ACCEPTED; the old scripted reload, bow tipped on its side with the nose down, rlnat 0, REJECTED). CLASS: weapon
# orientation in a state; judged on EVERY reload (each run of reload frames), not the take median.
RELOAD_UP_MIN, RELOAD_ELEV_MIN, RELOAD_MIN_N = 0.5, -10.0, 10   # median bow up.y (roll < 60 deg), median nose elevation deg


def reload_check(F, lab, up_min=RELOAD_UP_MIN, elev_min=RELOAD_ELEV_MIN, min_n=RELOAD_MIN_N):
    """(ok, parts): every crossbow reload (run of >= min_n reload frames) keeps the bow upright (median measured edge-up
    y >= up_min) and the nose not down (median elevation of the measured forward >= elev_min deg). Calibrated on the
    spec-video settings replayed through the current solver: rlnat 1 up .89 elev +22 (accept), rlnat 0 up .18 elev -21
    (reject)."""
    import math
    runs, cur = [], []
    for i, s in enumerate(lab):
        if s == 'reload' and F[i]['cls'] == 1:
            cur.append(i)
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    runs = [r for r in runs if len(r) >= min_n]
    if not runs:
        return None, ['reload n/a (no crossbow reload)']
    ok, parts = True, []
    for r in runs:
        up = sorted(F[i]['mu'][1] for i in r)[len(r) // 2]
        el = sorted(math.degrees(math.asin(max(-1.0, min(1.0, F[i]['mf'][1])))) for i in r)[len(r) // 2]
        b = up < up_min or el < elev_min
        ok = ok and not b
        parts.append('reload@%d:up=%.2f/%.2f,elev=%.0f/%.0f%s' % (r[0], up, up_min, el, elev_min, ':BAD' if b else ''))
    return ok, ['%d/%d reloads upright' % (sum(1 for x in parts if ':BAD' not in x), len(runs))] + parts


def arc_each(P, share=ARC_SHARE, wb_lim=ARC_WB, state='swing', min_n=OCC_MIN_ARC_N):
    """E1 arc per swing: every swing with >= min_n fast frames has arc_ok >= share and wb_max <= wb_lim."""
    ok, txt, bad, n = True, [], [], 0
    for r in occurrences(P, state):
        ar = [P[i]['arc'] for i in r if P[i].get('arc') is not None]
        if len(ar) < min_n:
            continue
        n += 1
        wb = max([P[i]['wb'] for i in r if P[i]['wb'] is not None] or [0.0])
        a = sum(1 for x in ar if x >= ARC_OK) / float(len(ar))
        if a < share or wb > wb_lim:
            bad.append('%s@%d:arc_ok=%.2f,wb=%.0f' % (state, r[0], a, wb))
    if not n:
        return False, ['%s:NO_FULL_SWING' % state]
    ok = not bad
    return ok, ['%s:each %d/%d swings arc_ok>=%.2f,wb<=%.0f%s' % (state, n - len(bad), n, share, wb_lim, '' if ok else ':BAD')] + bad[:4]


INL_EACH_SLACK = 5.0   # deg on the per-swing fb median: ~12 stroke frames per swing vs ~60 pooled; accepted f23/f28/e6-anim
                       # swings spread 25-31 around pooled 27-29 (taste R2), rejected f14-e0/f13-sw0 swings 43-54


def inline_each(F, P, slack=INL_EACH_SLACK, **kw):
    """E1 inline per swing: inline_check on each swing's own frames (ready/block frames stay in as info); the median limit
    gets `slack` deg for the smaller per-swing sample (the max / screen / wrist-share limits stay)."""
    kw = dict(kw); kw['fb_med'] = kw.get('fb_med', INL_FB_MED) + slack
    S = inline_series(F, P)
    res = []
    for k, idx in enumerate(swings(F, P)):
        keep = set(idx)
        Sk = [s if s and (s['i'] in keep or P[s['i']]['state'] != 'swing') else None for s in S]
        ok, txt = inline_check(inline_table(Sk), **kw)
        res.append((ok, k, idx[0], txt))
    if not res:
        return inline_check(inline_table(S), **kw)
    bad = [r for r in res if not r[0]]
    w = bad[0] if bad else res[0]
    return not bad, ['swings %d/%d inline%s' % (len(res) - len(bad), len(res), '' if not bad else ':BAD worst=swing%d@%d' % (w[1], w[2]))] + w[3]
