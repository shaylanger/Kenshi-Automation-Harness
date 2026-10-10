#!/usr/bin/env python3
"""animlab.py -- offline animation lab, phase 1 (REPLAY): replay recorded viewmodel frames through a solver adapter,
report the in-game metrics per pose state, compare variants side by side. Docs: docs/animlab/USAGE.md.

  animlab.py metrics <rec> [--require S,..] [--arc S:share]  per-state metrics + moves (C1) / arc (E1) gates
  animlab.py bolt    <rec> [--dev D --step S]                 C3: loaded bolt rigid on the crossbow (<rec>.bolt sidecar)
  animlab.py reload  <rec> [--up .5 --elev -10]               crossbow reload upright, nose not down (every reload)
  animlab.py compare <real> <sim> [--skip N]                 per-frame replay error + metrics side by side
  animlab.py replay  <rec> --adapter CMD [--set k=v]... [-o out.txt] [--skip N]
  animlab.py sweep   <rec> --adapter CMD [--variant 'name[@CMD]: adapter args']... [--metrics a,b] [-j N] [--keep DIR]
  animlab.py gate    <rec>... --adapter CMD [--tol tol.json] [--skip N]

An adapter is any command `CMD <rec.txt> <out.txt> [args]` that replays the recording through a solver and writes
its own recording in the same format; it may print `calib ...` (passed on to the variants as --calib so all
variants share one skeleton calibration).
"""
import argparse, atexit, json, os, shlex, shutil, signal, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recfmt
from recfmt import sub, ln, ang
import metrics as M

_TMP = []   # temp dirs made without --keep: removed at exit, also on error / SIGTERM (cleanup-audit 2026-10-10: 2104 leaked
            # /tmp/animlab-pool-* dirs = 31 GB in one day)


def tmpdir(prefix):
    d = tempfile.mkdtemp(prefix=prefix); _TMP.append(d); return d


def _cleanup():
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


atexit.register(_cleanup)


def kept(a, d, what='replays'):
    return '%s in %s' % (what, d) if a.keep else '%s removed at exit, --keep DIR keeps them' % what

DEFAULT_TOL = dict(   # faithfulness gate (docs/animlab/USAGE.md "Faithfulness gate")
    grip_p95=0.25, elbow_p95=0.35, wrist_p95=0.25, blade_p95=3.0, edge_p95=4.0, wb_p95=4.0,
    m_wb_p95=4.0, m_elb_h_max=0.4, m_st_max=0.08, m_edge_mean=0.06, m_jit_p95=2.0, min_frames=100,
    # gated states: the steady holds. Swing (sword) and reload (crossbow) follow the NATIVE animation (free swing
    # tracks the native progress/prop, reload blends the native arms), and recordings made before the rec-native
    # patch hold only the post-IK skeleton, so the replay cannot know the native pose there: those states and the
    # first settle_s seconds after them are reported (info) but not gated. See docs/animlab/USAGE.md.
    states=['ready', 'block', 'aim'], settle_s=0.3)
SETTLE_AFTER = ('swing', 'reload', 'swing->block', 'draw', 'lower', 'native', 'off')


def mark_settle(Pr, Ps, F, settle_s):
    """relabel frames within settle_s seconds after a non-steady state (game labels) as 'settle' in both."""
    t_last = None
    lab = [p['state'] for p in Pr]
    for i, p in enumerate(Pr):
        if lab[i] in SETTLE_AFTER:
            t_last = F[i]['t']
            continue
        if i + 1 < len(lab) and lab[i + 1] in SETTLE_AFTER:   # rendered pose of i = record i+1: already the next state
            p['state'] = 'settle'
            if i < len(Ps):
                Ps[i]['state'] = 'settle'
            continue
        if t_last is not None and F[i]['t'] - t_last < settle_s:
            p['state'] = 'settle'
            if i < len(Ps):
                Ps[i]['state'] = 'settle'


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
    P = M.frame_metrics(recfmt.parse(a.rec))
    T = M.state_table(P, a.skip)
    print_table([[s] + [M.fmt(T[s][c]) for c in M.METRIC_COLS] for s in states_of(T)], ('state',) + M.METRIC_COLS)
    req = getattr(a, 'require', None)
    if req is None:   # weapon from the states seen: crossbow aim + reload, sword block + swing
        req = ('aim', 'reload') if ('aim' in T or 'reload' in T) else ('block', 'swing') if ('block' in T or 'swing' in T) else ()
    else:
        req = tuple(x for x in req.split(',') if x)
    if req:
        ok, txt = M._both(M.moves_ok(T, req), M.moves_each(P[a.skip:], req))   # pooled + every occurrence
        print('moves %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
    arc = getattr(a, 'arc', None)
    if arc is None:   # E1: melee recordings with a swing get the edge-leads-the-arc gate by default
        arc = 'swing:%g' % M.ARC_SHARE if 'swing' in T else ''
    spec = {k: float(v or M.ARC_SHARE) for k, _, v in (x.partition(':') for x in arc.split(',') if x)}
    if spec:
        ok, txt = M.arc_gate(T, spec, a.wb_max)
        print('arc %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


NOCMP = ('off', 'draw', 'lower', 'native', 'settle')   # not compared: blends + native animation (no solver output on screen)


def frame_errors(Pr, Ps, Fr, skip):
    """per-frame errors replay vs game on frames where both show the full viewmodel."""
    E = {}
    for i in range(skip, min(len(Pr), len(Ps))):
        r, s = Pr[i], Ps[i]
        if r['state'] in NOCMP or s['state'] in NOCMP or not r['wih']:
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
    tol = tol or DEFAULT_TOL
    if tol.get('settle_s'):
        mark_settle(Pr, Ps, Rr.frames, tol['settle_s'])
    gated = tol.get('states') or M.STATE_ORDER
    E = frame_errors(Pr, Ps, Rr.frames, skip)
    Tr, Ts = M.state_table(Pr, skip), M.state_table(Ps, skip)
    fails, rows = [], []
    for s in states_of(E):
        e = E[s]
        row = [s if s in gated else s + '(info)', e['n'], '%.0f%%' % (100.0 * e['match'] / max(1, e['n']))]
        for k in ('grip', 'elbow', 'wrist', 'blade', 'edge', 'wb'):
            v = M.pct(e[k], .95)
            row.append(M.fmt(v))
            if s in gated and e['n'] >= 10 and v == v and v > tol[k + '_p95']:
                fails.append('%s %s_p95=%.2f>%.2f' % (s, k, v, tol[k + '_p95']))
        row.append(M.fmt(max(e['elbow'])) if e['elbow'] else '-')
        rows.append(row)
    if not quiet:
        print_table(rows, ('state', 'n', 'same', 'grip95', 'elb95', 'wr95', 'blade95', 'edge95', 'wb95', 'elb_max'),
                    'per-frame replay error (dm / deg, p95) vs the game:')
    mrows = []
    for s in states_of(Tr, Ts):
        if s in NOCMP:
            continue
        r, m = Tr.get(s), Ts.get(s)
        cells = [s if s in gated else s + '(info)']
        for c in ('wb_p95', 'elb_h_max', 'st_max', 'edge_mean', 'jit_p95'):
            rv = r[c] if r else float('nan')
            sv = m[c] if m else float('nan')
            cells.append('%s/%s' % (M.fmt(rv), M.fmt(sv)))
            lim = tol.get('m_' + c)
            if lim is not None and s in gated and r and m and r['n'] >= 10 and rv == rv and sv == sv and abs(rv - sv) > lim:
                fails.append('%s %s game=%.2f replay=%.2f (|d|>%.2f)' % (s, c, rv, sv, lim))
        mrows.append(cells)
    if not quiet:
        print_table(mrows, ('state', 'wb_p95', 'elb_h_max', 'st_max', 'edge_mean', 'jit_p95'), 'metrics game/replay:')
    nfull = sum(e['n'] for s, e in E.items() if s in gated)
    if nfull < tol['min_frames']:
        fails.append('only %d comparable frames (< %d)' % (nfull, tol['min_frames']))
    return fails, nfull


def cmd_bolt(a):
    """C3: the loaded bolt must stay rigid on the crossbow (game recording + its <rec>.bolt sidecar)."""
    labels = M.label_states(recfmt.parse(a.rec).frames)
    B = M.read_bolt(a.bolt or a.rec + '.bolt', a.source)
    ok, txt = M.bolt_ok(M.bolt_table(B, labels), a.dev, a.step)
    print('bolt %s %s src=%s' % ('PASS' if ok else 'FAIL', ' '.join(txt), M.read_bolt.used))


def cmd_churn(a):
    """E1 arm churn + wind-up hand roll (see metrics.churn_check)."""
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    ok, txt, _ = M.churn_check(M.churn_series(rec.frames, P), a.rev, a.grip, roll_max=a.roll, sroll_gate=a.stroke)
    print('churn %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


def cmd_hinge(a):
    """E5 arm roll: same swing input -> same upper-arm / forearm roll; measured roll on the bend plane (see metrics.hinge_check)."""
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    S = M.hinge_series(rec.frames, P)
    ok, txt, _ = M.hinge_check(S, P, a.dev, a.abs)
    if a.vs:   # replay faithfulness vs the game recording (same frames)
        g = recfmt.parse(a.vs); okf, t = M.hinge_faith(M.hinge_series(g.frames, M.frame_metrics(g)), S, a.faith)
        ok = ok and okf; txt.append(t)
    print('hinge %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


def cmd_inline(a):
    """E1 inline: blade in line with the forearm, arm-driven arc (see metrics.inline_table / inline_check)."""
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    kw = dict(phases=tuple(x for x in a.phases.split(',') if x), fb_med=a.fb_med, fb_max=a.fb_max, sc_max=a.sc_max, wr=a.wr)
    # pooled over all swings + every swing on its own (a bad swing must not hide in the pooled median)
    ok, txt = M._both(M.inline_check(M.inline_table(M.inline_series(rec.frames, P)), **kw), M.inline_each(rec.frames, P, **kw))
    print('inline %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


def cmd_blade(a):
    """E6 blade visibility per swing: one-video-frame snap at the wind-up top and per-frame end-on blade (metrics.blade_check)."""
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    ok, txt = M.blade_check(rec.frames, P, a.snap, a.seen)
    print('blade %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok else 1


def cmd_stroke(a):
    """E6 stroke readability per swing: on-screen blade length, overhead strokes descend vertically (metrics.stroke_check)."""
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    oh = tuple(int(x) for x in a.overhead.split(',') if x.strip()) if a.overhead else ()
    ok, txt = M.stroke_check(rec.frames, P, oh, a.len, tilt_max=a.tilt, path_max=a.path)
    print('stroke %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok else 1


def cmd_guard(a):
    """block guard readability: blade not hanging straight down in ANY block press (metrics.guard_check); a .tsv with a
    blade_elev_deg column (blk-survey per-press table) is judged per row (metrics.guard_table_check)."""
    if a.rec.endswith('.tsv'):
        import re
        rows = []
        with open(a.rec) as f:
            hdr = f.readline().rstrip('\n').split('\t')
            for line in f:
                c = dict(zip(hdr, line.rstrip('\n').split('\t')))
                m = re.search(r'tech=0*([0-9a-fA-F]+)', c.get('evidence', ''))
                rows.append(('%s/%s/%s' % (c.get('view', ''), c.get('dir', ''), c.get('org', '')), float(c['blade_elev_deg']),
                             m.group(1)[-6:] if m else '?'))
        ok, txt = M.guard_table_check(rows, a.elev)
        print('guard %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
        return 0 if ok else 1
    rec = recfmt.parse(a.rec); P = M.frame_metrics(rec)
    ok, txt = M.guard_check(M.guard_series(rec.frames, P), a.elev)
    print('guard %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok else 1


def cmd_zoomband(a):
    """own body parts in frame while the camera is between the eye and the head-show distance (metrics.zoomband_check)."""
    rec = recfmt.parse(a.rec)
    ok, txt = M.zoomband_check(M.zoomband_series(rec.frames, a.head_show), a.max_frames)
    print('zoomband %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok else 1


def cmd_branch(a):
    """Sword ready elbow branch: every ready run on the reference branch (--ref recording's first ready run, else this
    recording's first run): edge roll about the blade <= --roll deg, elbow <= --elb dm (see metrics.ready_branch)."""
    rec = recfmt.parse(a.rec); R = M.ready_runs(rec.frames, M.frame_metrics(rec))
    ref = None
    if a.ref:
        rr = recfmt.parse(a.ref); ref = M.ready_runs(rr.frames, M.frame_metrics(rr)) or None
    ok, txt = M.ready_branch(R, ref, a.roll, a.elb)
    print('branch %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


def cmd_stock(a):
    """C2: crossbow stock low on screen (stock top <= --max % from the bottom in ready) and, with --ref, ready orientation
    within --ori deg of a known-good recording."""
    F = recfmt.parse(a.rec).frames; lab = M.label_states(F)
    ref = None
    if a.ref:
        RF = recfmt.parse(a.ref).frames; ref = M.pose_dirs(RF, M.label_states(RF))
    ok, txt = M.stock_ok(M.stock_table(F, lab, a.h), M.pose_dirs(F, lab), ref, a.max, a.ori)
    print('stock %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt)))


def cmd_reload(a):
    """crossbow reload posture: every reload keeps the bow upright, nose not down (Shay 2026-10-10)."""
    F = recfmt.parse(a.rec).frames
    ok, txt = M.reload_check(F, M.label_states(F), a.up, a.elev)
    print('reload %s %s' % ('n/a' if ok is None else 'PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok is not False else 1


def cmd_spike(a):
    """one-frame weapon snap / flick / grip jump on every viewmodel frame (Misses 2026-10-10 PT30 roll spikes)."""
    rec = recfmt.parse(a.rec)
    ok, txt = M.spike_check(rec.frames, M.frame_metrics(rec), a.flick, a.step)
    print('spike %s %s' % ('n/a' if ok is None else 'PASS' if ok else 'FAIL', ' '.join(txt)))
    return 0 if ok is not False else 1


def cmd_compare(a):
    fails, n = compare(a.real, a.sim, a.skip)
    print('GATE %s frames=%d %s' % ('PASS' if not fails else 'FAIL', n, '; '.join(fails[:8])))
    ok, txt = M.jitter_faithful(M.state_table(M.frame_metrics(recfmt.parse(a.real)), a.skip),
                                M.state_table(M.frame_metrics(recfmt.parse(a.sim)), a.skip))
    print('jitter %s %s' % ('PASS' if ok else 'FAIL', ' '.join(txt) or 'no state above %.1f px' % M.JIT_MIN))


def adapter_args(a):
    x = []
    for s in a.set or []:
        x += ['--set', s]
    return x


def cmd_replay(a):
    out = a.o or os.path.join(tmpdir('animlab-'), 'replay.txt')
    calib = run_adapter(a.adapter, a.rec, out, adapter_args(a) + shlex.split(a.args or ''))
    print('replay -> %s (calib %s)' % (out, calib))
    fails, n = compare(a.rec, out, a.skip)
    print('GATE %s frames=%d %s' % ('PASS' if not fails else 'FAIL', n, '; '.join(fails[:8])))


def cmd_pool(a):
    """Prediction over native variants (CLASS: random native variant per swing / block press). swing: E6 stroke prediction: replay every recording with the stroke forced, judge every swing
    on its own and predict the take pass rate (metrics.swing_verdicts / pool_predict). Recordings: paths or @listfile."""
    recs = []
    for r in a.rec:
        if r.startswith('@'):   # list file: one rec per line, relative paths from the list's directory
            d = os.path.dirname(os.path.abspath(r[1:]))
            recs += [os.path.join(d, l.strip()) for l in open(r[1:]) if l.strip() and not l.startswith('#')]
        else:
            recs.append(r)
    keep = a.keep or tmpdir('animlab-pool-')
    os.makedirs(keep, exist_ok=True)
    if a.motion == 'swing' and (a.stroke is None or not a.adapter) or a.replay and not a.adapter:
        raise SystemExit('pool: --motion swing needs --stroke N and --adapter; --replay needs --adapter')
    extra = (shlex.split(a.stroke_args.format(stroke=a.stroke)) if a.motion == 'swing' else []) + shlex.split(a.args or '')
    def one(rec):
        out = os.path.join(keep, '%s%s-%s' % (a.motion, '' if a.stroke is None else a.stroke, os.path.basename(rec)))
        run_adapter(a.adapter, rec, out, extra)
        return rec, out
    if a.motion == 'block' and not a.replay:
        # the zoomed-out block is the native technique pose: the replay re-solves it (f059 z25 press 0: game -75 deg,
        # replay +44), so the recordings are judged as recorded unless --replay
        res = [(r, r) for r in recs]; keep = '-'
    else:
        with ThreadPoolExecutor(max_workers=a.j) as ex:
            res = list(ex.map(one, recs))
    if a.motion == 'block':   # free block: the native technique per press (chooseBlock) -> per-press guard verdicts
        V = []
        for rec, out in res:
            r = recfmt.parse(out)
            for v in M.guard_press_verdicts(M.guard_series(r.frames, M.frame_metrics(r))):
                v['rec'] = os.path.splitext(os.path.basename(rec))[0]; V.append(v)
                if a.verbose:
                    print('  %s@%d full=%d elev=%.0f guard=%d' % (v['rec'], v['frame'], v['full'], v['elev'], v['ok']['guard']))
        ok, txt = M.pool_predict(V, ('guard',), a.take, a.rate)
        print('pool block %s %s (%s)' % ('PASS' if ok else 'FAIL', ' '.join(txt), kept(a, keep)))
        return 0 if ok else 1
    oh = tuple(int(x) for x in a.overhead.split(',') if x.strip()) if a.overhead else ()
    V = []
    for rec, out in res:
        r = recfmt.parse(out)
        for v in M.swing_verdicts(r.frames, M.frame_metrics(r), oh):
            v['rec'] = os.path.splitext(os.path.basename(rec))[0]
            if v['stroke'] in (None, -1, a.stroke):
                V.append(v)
    if a.verbose:
        for v in V:
            print('  %s@%d full=%d arc=%d/%d wb=%.1f blade=%d stroke=%d %s' % (v['rec'], v['frame'], v['full'], v['arc_good'], v['arc_n'],
                  v['wb_max'], v['ok']['blade'], v['ok']['stroke'], ' '.join(v['btxt'])))
    ok, txt = M.pool_predict(V, tuple(c for c in a.checks.split(',') if c), a.take, a.rate)
    print('pool stroke %d %s %s (%s)' % (a.stroke, 'PASS' if ok else 'FAIL', ' '.join(txt), kept(a, keep)))
    return 0 if ok else 1


def cmd_agree(a):
    """Lab vs game agreement: every game rec of the manifest (lines `<rec> <adapter> [adapter args]`, rec path relative to
    the manifest, adapter = the solver of the rec's build) is replayed and every check of metrics.check_suite runs on both;
    per-frame faithfulness = the `gate` row. Prints the table; --status writes the summary into STATUS.md."""
    base = os.path.dirname(os.path.abspath(a.manifest))
    jobs = []
    for line in open(a.manifest):
        if not line.strip() or line.startswith('#'):
            continue
        t = shlex.split(line)
        rec = t[0] if os.path.isabs(t[0]) else os.path.join(base, t[0])
        jobs.append((rec, t[1], t[2:]))
    keep = a.keep or tmpdir('animlab-agree-')
    os.makedirs(keep, exist_ok=True)

    def one(j):
        rec, ad, args = j
        name = os.path.splitext(os.path.basename(rec))[0]
        if not os.path.exists(rec) or not os.path.exists(shlex.split(ad)[0]):
            return name, None, 'missing %s' % (rec if not os.path.exists(rec) else ad)
        out = os.path.join(keep, name + '.replay.txt')
        try:
            run_adapter(ad, rec, out, args)
        except RuntimeError as e:
            return name, None, 'adapter failed: %s' % str(e).splitlines()[0][:120]
        return name, (rec, out), os.path.basename(shlex.split(ad)[0])
    with ThreadPoolExecutor(max_workers=a.j) as ex:   # replays in parallel, checks below in this thread (metrics.STROKE_ONLY)
        res = list(ex.map(one, jobs))
    for k, (name, ro, info) in enumerate(res):
        if ro is None:
            continue
        rec, out = ro
        fails, n = compare(rec, out, quiet=True)
        # gate = per-frame replay error; no viewmodel frames (zoomed out: native animation) = not comparable, no row
        rows = [('gate', True, not fails, not fails, 'frames=%d %s' % (n, '; '.join(fails[:2])))] if n else []
        res[k] = (name, rows + M.agree_rows(recfmt.parse(rec), recfmt.parse(out)), info)
    tab, summ, dis = [], {}, []
    for name, rows, info in res:
        if rows is None:
            tab.append([name, '-', '-', '-', '-', info])
            continue
        for c, g, r, ag, d in rows:
            tab.append([name, c, 'PASS' if g else 'FAIL', 'PASS' if r else 'FAIL', 'yes' if ag else 'NO', d[:90]])
            k = c.split('[')[0]
            s = summ.setdefault(k, [0, 0])
            s[0] += 1
            s[1] += ag
            if not ag:
                dis.append('%s %s: game %s, replay %s (%s; adapter %s)' % (name, c, 'PASS' if g else 'FAIL', 'PASS' if r else 'FAIL', d, info))
    print_table(tab, ('rec', 'check', 'game', 'replay', 'agree', 'game/replay values'))
    line = ', '.join('%s %d/%d' % (k, v[1], v[0]) for k, v in sorted(summ.items()))
    print('agree %s recs=%d checks: %s disagreements=%d' % ('PASS' if not dis else 'FAIL', len(res), line, len(dis)))
    for x in dis:
        print('  DISAGREE ' + x)
    if a.status:
        import datetime
        md = ['<!-- agree:begin (written by `animlab.py agree --status`, do not edit by hand) -->',
              '%s, manifest `%s`: %d recs; agreement per check (agree/compared): %s; disagreements %d (each one has an open Misses row):'
              % (datetime.date.today().isoformat(), a.manifest, len(res), line, len(dis)), '']
        full = os.path.splitext(os.path.abspath(a.manifest))[0] + '-table.md'
        with open(full, 'w') as f:   # the full per-rec table next to the manifest (STATUS keeps summary + disagreements)
            f.write('| rec | check | game | replay | agree | game/replay values |\n|---|---|---|---|---|---|\n')
            f.write(''.join('| %s |\n' % ' | '.join(str(c).replace('|', '/') for c in r) for r in tab))
        md += ['- %s' % x for x in dis] + ['', 'Full table: `%s`' % full, '<!-- agree:end -->']
        txt = open(a.status).read()
        blk = '\n'.join(md)
        if '<!-- agree:begin' in txt:
            i = txt.index('<!-- agree:begin')
            j = txt.index('<!-- agree:end -->') + len('<!-- agree:end -->')
            txt = txt[:i] + blk + txt[j:]
        else:
            txt = txt.rstrip('\n') + '\n\n## Lab agreement (lab replay vs game, per check)\n' + blk + '\n'
        open(a.status, 'w').write(txt)
    return 0 if not dis else 1


def parse_variant(v, default_cmd):
    name, _, rest = v.partition(':')
    cmd = default_cmd
    if '@' in name:
        name, cmd = name.split('@', 1)
    return name.strip(), cmd, shlex.split(rest)


def cmd_sweep(a):
    keep = a.keep or tmpdir('animlab-sweep-')
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
    print_table(rows, ['state metric'] + names, 'sweep %s (%s):' % (os.path.basename(a.rec), kept(a, keep, 'outputs')))


def cmd_gate(a):
    tol = dict(DEFAULT_TOL)
    if a.tol:
        tol.update(json.load(open(a.tol)))
    allok = True
    for rec in a.rec:
        out = os.path.join(tmpdir('animlab-gate-'), 'replay.txt')
        run_adapter(a.adapter, rec, out, shlex.split(a.args or ''))
        print('== %s' % rec)
        fails, n = compare(rec, out, a.skip, tol, quiet=a.quiet)
        print('GATE %s %s frames=%d %s' % ('PASS' if not fails else 'FAIL', os.path.basename(rec), n, '; '.join(fails[:8])))
        allok = allok and not fails
    return 0 if allok else 1


def cmd_weapons(a):
    import weapons
    return weapons.cmd(a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('metrics'); p.add_argument('rec'); p.add_argument('--skip', type=int, default=0)
    p.add_argument('--require', help='states that must move visibly from ready, comma list (default: aim,reload or block,swing by the states seen)')
    p.add_argument('--arc', help="E1 edge-leads-the-arc gate, 'state[:share],...' (default swing:0.85 when a swing is seen; '' = off)")
    p.add_argument('--wb-max', type=float, default=M.ARC_WB, help='wrist bend limit (deg) for the arc gate (default %(default)s)')
    p = sp.add_parser('bolt'); p.add_argument('rec'); p.add_argument('--bolt', help='sidecar (default <rec>.bolt)')
    p.add_argument('--dev', type=float, default=0.1); p.add_argument('--step', type=float, default=0.05)
    p.add_argument('--source', choices=('sl', 'bl'), help='sidecar column group: sl = post-IK Prop2 frame (default when present), bl = weapon frame')
    p = sp.add_parser('churn'); p.add_argument('rec'); p.add_argument('--rev', type=float, default=M.CHURN_REV)
    p.add_argument('--grip', type=float, default=M.CHURN_GRIP); p.add_argument('--roll', type=float, default=M.ROLL_MAX)
    p.add_argument('--stroke', action='store_true', help='also gate the stroke-start roll (E1 fix: small + gradual)')
    p = sp.add_parser('hinge'); p.add_argument('rec'); p.add_argument('--dev', type=float, default=M.HINGE_DEV)
    p.add_argument('--abs', type=float, default=M.HINGE_ABS)
    p.add_argument('--vs', help='game recording this rec replays: also gate the per-frame bone roll error (metrics.hinge_faith)')
    p.add_argument('--faith', type=float, default=M.HINGE_FAITH)
    p = sp.add_parser('inline'); p.add_argument('rec'); p.add_argument('--phases', default=','.join(M.INL_GATE))
    p.add_argument('--fb-med', type=float, default=M.INL_FB_MED); p.add_argument('--fb-max', type=float, default=M.INL_FB_MAX)
    p.add_argument('--sc-max', type=float, default=M.INL_SC_MAX); p.add_argument('--wr', type=float, default=M.INL_WR)
    p = sp.add_parser('branch'); p.add_argument('rec'); p.add_argument('--ref', help='known-good recording (e.g. the game recording of a replay)')
    p.add_argument('--roll', type=float, default=M.BR_ROLL); p.add_argument('--elb', type=float, default=M.BR_ELB)
    p = sp.add_parser('blade'); p.add_argument('rec'); p.add_argument('--snap', type=float, default=M.SNAP_MAX, help='max sword rotation (deg) in one 30 fps video frame after the wind-up top')
    p.add_argument('--seen', type=float, default=M.SEE_MIN, help='min visible blade (screen length x flat facing) per frame, u .45-.95')
    p = sp.add_parser('stroke'); p.add_argument('rec')
    p.add_argument('--len', type=float, default=M.STK_LEN_MIN, help='min on-screen blade length px over u .40-.78')
    p.add_argument('--overhead', help='scripted stroke ids that must descend vertically, comma list (E6: 2)')
    p.add_argument('--tilt', type=float, default=M.STK_OH_TILT); p.add_argument('--path', type=float, default=M.STK_OH_PATH)
    p = sp.add_parser('guard'); p.add_argument('rec'); p.add_argument('--elev', type=float, default=M.GUARD_ELEV, help='min median blade elevation (deg) over block frames')
    p = sp.add_parser('zoomband'); p.add_argument('rec'); p.add_argument('--head-show', type=float, default=M.ZB_HEAD_SHOW, help='dm: head hidden below this camera distance (KenshiFP head_show_dm)')
    p.add_argument('--max-frames', type=int, default=0)
    p = sp.add_parser('stock'); p.add_argument('rec'); p.add_argument('--ref', help='known-good recording for the orientation check')
    p.add_argument('--max', type=float, default=M.STOCK_MAX); p.add_argument('--ori', type=float, default=M.ORI_MAX)
    p.add_argument('--h', type=float, default=M.STOCK_H, help='stock top above the bolt axis (dm)')
    p = sp.add_parser('reload'); p.add_argument('rec'); p.add_argument('--up', type=float, default=M.RELOAD_UP_MIN)
    p.add_argument('--elev', type=float, default=M.RELOAD_ELEV_MIN)
    p = sp.add_parser('spike'); p.add_argument('rec'); p.add_argument('--flick', type=float, default=M.SPK_FLICK)
    p.add_argument('--step', type=float, default=M.SPK_STEP)
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
    p = sp.add_parser('pool'); p.add_argument('rec', nargs='+', help='recordings with native swings (or @listfile)')
    p.add_argument('--adapter', help='replay adapter (required for swing and block --replay)'); p.add_argument('--stroke', type=int, help='swing: scripted stroke forced on every native swing')
    p.add_argument('--motion', choices=('swing', 'block'), default='swing', help='block = per-press guard over the native block techniques')
    p.add_argument('--replay', action='store_true', help='block: replay the recordings (default: judge them as recorded)')
    p.add_argument('--stroke-args', default='--no-rec-sets --set stroke={stroke}', help='adapter args forcing the stroke (KenshiFP kfpvm_replay default)')
    p.add_argument('--args', help='extra adapter args'); p.add_argument('--overhead', help='overhead stroke ids (stroke check)')
    p.add_argument('--checks', default='arc,blade,stroke'); p.add_argument('--take', type=int, default=M.POOL_TAKE)
    p.add_argument('--rate', type=float, default=M.POOL_RATE, help='min predicted take pass rate')
    p.add_argument('-j', type=int, default=os.cpu_count() or 4); p.add_argument('--keep'); p.add_argument('-v', dest='verbose', action='store_true')
    p = sp.add_parser('agree'); p.add_argument('manifest', help='lines `<game rec> <adapter of its build> [adapter args]`')
    p.add_argument('--status', help='STATUS.md to write the summary into'); p.add_argument('--keep'); p.add_argument('-j', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--only-stroke', dest='only_stroke', type=int, help='E6: judge only swings of this scripted stroke (others -> swing_x)')
    p = sp.add_parser('weapons', help='weapon catalogue (base + mods) / per-weapon check matrix (weapons.py)')
    p.add_argument('--config', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'components', 'KenshiFP', 'animlab', 'native.json'))
    p.add_argument('--catalog', action='store_true'); p.add_argument('--run', action='store_true')
    p.add_argument('-o', default='weapons-out', help='output dir (catalog: weapons.csv/json/md)')
    p.add_argument('--weapons-json', help='catalog weapons.json for --run (default: build it now)')
    p.add_argument('--recs', nargs='*', default=[], help='recordings / candidates to replay per weapon (or @listfile)')
    p.add_argument('--adapter', help='metricslab adapter command for replays (default: plain recordings only)')
    p.add_argument('--all', action='store_true', help='every catalog weapon, not only the representatives')
    p.add_argument('--only', help='comma list of sids / names'); p.add_argument('--sheet', action='store_true', help='--run: render one sheet per weapon')
    a = ap.parse_args()
    if a.only_stroke is not None:
        M.STROKE_ONLY = a.only_stroke
    if not a.cmd:
        ap.print_help(); return 2
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # SIGTERM -> SystemExit: atexit removes the temp dirs
    return {'blade': cmd_blade, 'bolt': cmd_bolt, 'branch': cmd_branch, 'churn': cmd_churn, 'hinge': cmd_hinge, 'inline': cmd_inline, 'stock': cmd_stock, 'reload': cmd_reload, 'spike': cmd_spike, 'zoomband': cmd_zoomband, 'guard': cmd_guard, 'stroke': cmd_stroke, 'metrics': cmd_metrics, 'compare': cmd_compare, 'replay': cmd_replay, 'sweep': cmd_sweep, 'gate': cmd_gate, 'pool': cmd_pool, 'agree': cmd_agree, 'weapons': cmd_weapons}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
