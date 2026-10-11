#!/usr/bin/env python3
"""takecheck.py -- judge a labelled video take against game state sampled while it was recorded.

A take = a video (optional), a labels file and one or more evidence files:
  labels    lines `<t> <text>` (t = seconds from the recording start; the last label must be `end`)
  evidence  lines `<t> [tag] key=value key=value ...` (anything else on the line, `|` separators included, is
            ignored; lines whose first token is not a number are skipped). Keys may come from different
            samplers at different times: every key is its own time series.
  rules     one rule per line (shell-like quoting, `#` comments):
    claim <label regex> <cond> [<cond> ...]  every sample of each cond's key inside the label's segment
              [t_label + grace, t_next_label] must satisfy it, and the samples must cover the whole segment
              (no gap > maxgap, segment edges included): a label true for 1 s of a 5 s segment fails
    pre <label regex> <cond> [...]           the last sample at or before t_label + grace must satisfy it
              (setup checks, e.g. loaded before an aim segment)
    forbid <cond> [label regex]               no sample in the take (or only in the matching segments) may
              satisfy it (combat messages, bystanders near the camera, ...)
    sparse <key>[,<key>...]                   event keys that appear only when something happens (forbid on
              them passes when never sampled; pair them with a `cover`ed counter)
    cover <key>[,<key>...]                    these keys must be sampled across the whole take (no gap > maxgap)
    set grace|maxgap|endslack|offset <value>
  cond = <key><op><value>, op one of = != ~ !~ >= <= > < ; `=`/`!=` take `a|b` alternatives; `~` is a regex
  search; numbers compare numerically.
Video: the take must end at the `end` label: video length - (end + offset) within [-0.2, endslack] s (offset = the
measured T0 sync-flash time when the take has one, else `set offset`; `set trim 1` first cuts a longer tail at
end + 0.3 s in place, only with a measured offset), and no
frame may show the Windows mouse cursor (frames.py cursor at 5 fps; `--no-cursor` skips it) or a foreign overlay
(speech bar, name tag, damage number, hint list, popup: frames.py overlay at 2 fps; `--no-overlay` skips it).
Sync (T6 label lag): when the evidence has `sync=<n>` lines (take-sample.sh take_mark, sent with every label), the
video's sync flashes (frames.py syncmarks) are paired with them: every label needs its flash and no flash may reach the
screen more than `synclag` (default 0.15 s) earlier/later than the take's T0 flash; `set sync 1` makes take_mark
mandatory; `--synced-out F` writes the labels at their measured video times (burn-in); `--no-sync` skips it.
Frame stamp (harness `stamp on`, stamp.py; `--stamp auto|on|off`, default auto = when the video has one): every video
frame carries its game frame, FP state and the last label mark. Then labels sit at the frame their mark first shows, the
stamp keys (ui_state hud_text loaded stroke view zoomb wcls vm gf mark) replace the sampled ones (one sample per video
frame), the rest of the evidence moves by the measured T0 (mark 0), everything is judged on the video clock and the
sync line becomes `sync PASS|FAIL stamp frames=.. dup=.. skip_max=.. marks=k/n t0=..` (FAIL = a label mark never shown).

KenshiFP log (`--kfplog LOG [--log-t0 HH:MM:SS.ms]`): every free block / free swing in the take must have run its native
animation (`... end: ... live=1`); a press whose progress never went live (fb_lives 0, p 1.010) fails `animlive`.

Usage: takecheck.py --labels L --ev E [--ev E2 ...] --rules R [--video V [--no-cursor] [--no-overlay] | --video-len S] [--kfplog LOG
       [--log-t0 T]] [--name take]
Exit 0 = PASS or PASS-REC. Prints one line per check, then `RESULT <name> PASS|PASS-REC|FAIL <failed checks>`.

PRODUCT vs RECORDING checks (Shay 2026-10-10: no refilms caused only by PC load; tur-b-2 T6 passed review but FAILed on a
1.1 s sampler gap, a 0.45 s short video and 0.55 s label lag at WSL load 60). PRODUCT = what the game showed: claim values,
pre, forbid, cursor, overlay, animlive (+ the wrapper's openground/moves/look checks). RECORDING = how well the take was
captured: claim/cover sampler gaps, video length, sync flash lag. When only recording checks fail the take is judged on
what was recorded: `RESULT <name> PASS-REC <n> checks rec-warn=<which>`. A recording failure still FAILs (`rec-hid=`) when
it hides a whole state, because a state with no evidence is not judged:
  claim gap   >= half the segment, > 3 x maxgap, or < 2 samples in it
  cover gap   > 3 x maxgap, or a gap that contains a whole labelled segment
  video       shorter than the start of the last state + grace (the last state has no frames)
  sync        no flash paired at all, or a label lag beyond 1.0 s
"""
import argparse, re, shlex, subprocess, sys

OPS = ('!~', '!=', '>=', '<=', '=', '~', '>', '<')
DEFAULTS = dict(grace=0.6, maxgap=1.0, endslack=1.0, offset=0.0)


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_cond(s):
    for op in OPS:
        k, sep, v = s.partition(op)
        if sep and k and re.match(r'^[A-Za-z_][\w.]*$', k):
            return (k, op, v)
    raise ValueError('bad condition %r' % s)


def cond_ok(c, val):
    k, op, v = c
    if op in ('~', '!~'):
        m = re.search(v, val) is not None
        return m if op == '~' else not m
    if op in ('=', '!='):
        alts = v.split('|')
        m = any(val == a or (_num(val) is not None and _num(a) is not None and _num(val) == _num(a)) for a in alts)
        return m if op == '=' else not m
    a, b = _num(val), _num(v)
    if a is None or b is None:
        return False
    return {'>=': a >= b, '<=': a <= b, '>': a > b, '<': a < b}[op]


def fmt_cond(c):
    return '%s%s%s' % c


def read_labels(path):
    L = []
    for line in open(path, encoding='utf-8', errors='replace'):
        p = line.strip().split(None, 1)
        if len(p) == 2 and _num(p[0]) is not None:
            L.append((float(p[0]), p[1].strip()))
        elif len(p) == 1 and _num(p[0]) is None:
            continue
    L.sort(key=lambda x: x[0])
    return L


def read_ev(paths):
    """{key: [(t, value)]} sorted by t."""
    S = {}
    for path in paths:
        for line in open(path, encoding='utf-8', errors='replace'):
            tok = line.split()
            if not tok or _num(tok[0]) is None:
                continue
            t = float(tok[0])
            for x in tok[1:]:
                k, sep, v = x.partition('=')
                if sep and re.match(r'^[A-Za-z_][\w.]*$', k):
                    S.setdefault(k, []).append((t, v))
    for k in S:
        S[k].sort(key=lambda x: x[0])
    return S


def read_rules(path):
    R, cfg = [], dict(DEFAULTS)
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        a = shlex.split(line, comments=True)
        kind = a[0]
        if kind == 'set':
            cfg[a[1]] = float(a[2])
        elif kind in ('claim', 'pre'):
            R.append((kind, re.compile(a[1]), [parse_cond(x) for x in a[2:]], n))
        elif kind == 'forbid':
            R.append((kind, re.compile(a[2]) if len(a) > 2 else None, [parse_cond(a[1])], n))
        elif kind == 'sparse':
            R.append((kind, None, a[1].split(','), n))
        elif kind == 'cover':
            R.append((kind, None, a[1].split(','), n))
        else:
            raise ValueError('rules line %d: unknown rule %r' % (n, kind))
    return R, cfg


def segments(L, early=None):
    """[(t0, t1, text)] per label (the `end` label closes the last one and has no segment). early {(t, text): t'}:
    frame stamp, the next label's earliest video time (observation labels: the state changed before their mark)."""
    out = []
    for i, (t, txt) in enumerate(L):
        if txt.lower() == 'end':
            break
        t1 = L[i + 1][0] if i + 1 < len(L) else None
        if t1 is not None and early:
            t1 = max(t, min(t1, early.get(tuple(L[i + 1][:2]), t1)))
        out.append((t, t1, txt))
    return out


def coverage(samples, a, b):
    """largest gap (s) in [a, b] not covered by samples (segment edges count as gaps to the first/last sample)."""
    ts = [t for t, _ in samples if a <= t <= b]
    if not ts:
        return b - a
    pts = [a] + ts + [b]
    return max(pts[i + 1] - pts[i] for i in range(len(pts) - 1))


def gaps(samples, a, b, mg):
    """[(g0, g1)] unsampled intervals in [a, b] longer than mg (edges count, like coverage)."""
    pts = [a] + sorted(t for t, _ in samples if a <= t <= b) + [b]
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i + 1] - pts[i] > mg]


REC_HOLE = 3.0      # a recording gap > REC_HOLE x maxgap hides too much to judge (FAIL rec-hid)
SYNC_HIDE = 1.0     # a label lag beyond this (s) can put a short state on the wrong frames (FAIL rec-hid)


def sync_check(L, S, marks, maxlag=0.15, require=False, pair_win=1.0, label_win=0.25):
    """T6 label lag (2026-10-10): pair the take's `sync=<n>` evidence lines (take_mark send times, script clock) with
    the sync flashes found in the video (`marks`, video clock). lag_i = (mark_i - send_i) - (mark_0 - send_0): how
    much later/earlier than the take's first (T0) marker this one reached the screen. FAIL when any |lag| > maxlag,
    a send has no flash, a flash has no send, or a label has no take_mark within label_win s.
    Returns (ok, text, synced) with synced = [(video t, label text)] (the label at its own flash, else at
    t + T0 offset) for the burn-in. No take_mark in the take: ok (SKIP) unless require."""
    sends = [(t, v) for t, v in S.get('sync', [])]
    if not sends:
        why = ('take_mark off: ' + S['sync_off'][0][1]) if S.get('sync_off') else 'no take_mark in the take'
        return (not require), ('SKIP ' if not require else '') + why + (':BAD' if require else ''), None
    if not marks:
        return False, 'sends=%d flashes=0 (no sync flash in the video):BAD' % len(sends), None
    best = None
    if len(marks) == len(sends):   # one flash per send, both in send order: pair by order (any lag shows)
        best = (None, [(st, n, mm) for (st, n), mm in zip(sends, marks)], set(range(len(marks))))
    for m in (marks if best is None else []):   # else: the offset that pairs the most sends with flashes
        for s, _ in sends:
            off = m - s
            used, pairs = set(), []
            for st, n in sends:
                cand = [(abs(mm - st - off), j) for j, mm in enumerate(marks) if j not in used and abs(mm - st - off) <= pair_win]
                if cand:
                    j = min(cand)[1]; used.add(j); pairs.append((st, n, marks[j]))
            key = (len(pairs), -sum(abs(mm - st - off) for st, _, mm in pairs))
            if best is None or key > best[0]:
                best = (key, pairs, used)
    _, pairs, used = best
    bad = []
    paired = {n for _, n, _ in pairs}
    miss = [n for _, n in sends if n not in paired]
    extra = [marks[j] for j in range(len(marks)) if j not in used]
    if miss:
        bad.append('no flash for n=' + ','.join(miss[:8]))
    if extra:
        bad.append('flash without take_mark at ' + ','.join('%.2f' % x for x in extra[:8]))
    lags = []
    if pairs:
        s0, _, m0 = pairs[0]
        off0 = m0 - s0
        lags = [(n, (mm - st) - off0, st) for st, n, mm in pairs]
        over = [(n, d) for n, d, _ in lags if abs(d) > maxlag]
        if over:
            bad.append('lag>%.2fs at n=' % maxlag + ','.join('%s(%+.2f)' % x for x in over[:8]))
    else:
        off0 = 0.0
    synced, nolab = [], []
    for t, txt in L:
        c = [(abs(st - t), mm) for st, _, mm in pairs if abs(st - t) <= label_win]
        if c:
            synced.append((min(c)[1], txt))
        else:
            synced.append((t + off0, txt))
            if txt.lower() != 'end':   # take_mark sends none for `end` (the video stops there)
                nolab.append(txt)
    if nolab:
        bad.append('label without flash: ' + '|'.join(nolab[:4]))
    txt = 'sends=%d flashes=%d paired=%d t0_offset=%.2f' % (len(sends), len(marks), len(pairs), off0)
    if lags:
        txt += ' lag=%+.2f..%+.2f' % (min(d for _, d, _ in lags), max(d for _, d, _ in lags))
    if bad:
        txt += ' ' + '; '.join(bad) + ':BAD'
    return not bad, txt, synced


def video_len(path):
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except Exception:
        return None


def check(L, S, R, cfg, vlen=None, rec=None, early=None):
    """returns (ok, [lines], [failed short names]). `rec` (dict, optional) gets {failed name: 'warn'|'hid'} for every
    failure that is a RECORDING check (sampler gap / video length): 'hid' = it hides a whole state (see grade())."""
    lines, fails = [], []
    rec = {} if rec is None else rec
    prod = set()
    g, mg = cfg['grace'], cfg['maxgap']
    end = next((t for t, x in L if x.lower() == 'end'), None)
    segs = segments(L, early)
    if end is None:
        fails.append('no-end-label'); lines.append('end FAIL no `end` label: take length unknown')
    t_first = L[0][0] if L else 0.0
    sparse = set(k for kind, _, ks, _ in R if kind == 'sparse' for k in ks)
    t_last = end if end is not None else (L[-1][0] if L else 0.0)
    for kind, rx, conds, n in R:
        if kind in ('claim', 'pre'):
            hit = [s for s in segs if rx.search(s[2])]
            for t0, t1, txt in hit:
                t1 = t_last if t1 is None else t1
                for c in conds:
                    sm = S.get(c[0], [])
                    if kind == 'pre':
                        prev = [x for x in sm if x[0] <= t0 + g]
                        if not prev:
                            msg = 'no sample of %s before %.2f' % (c[0], t0 + g)
                        elif not cond_ok(c, prev[-1][1]):
                            msg = '%s=%s at %.2f' % (c[0], prev[-1][1], prev[-1][0])
                        else:
                            lines.append('pre PASS "%s" %s (%s=%s at %.2f)' % (txt, fmt_cond(c), c[0], prev[-1][1], prev[-1][0])); continue
                        fails.append('pre:%s' % txt[:30]); lines.append('pre FAIL "%s" wants %s: %s' % (txt, fmt_cond(c), msg)); continue
                    a, b = t0 + g, t1
                    ins = [x for x in sm if a <= x[0] < b]   # half-open: a sample at the next label belongs to it
                    bad = [x for x in ins if not cond_ok(c, x[1])]
                    gap = coverage(sm, a, b) if b > a else 0.0
                    if bad:
                        good_s = sum(1 for x in ins if cond_ok(c, x[1]))
                        why = '%s=%s at %.2f (%d/%d samples hold)' % (c[0], bad[0][1], bad[0][0], good_s, len(ins))
                    elif not ins and b > a:
                        why = 'no sample of %s in %.2f..%.2f' % (c[0], a, b)
                    elif gap > mg:
                        why = 'unverified %.1f s (max gap %.1f s, %d samples in %.1f s)' % (gap, mg, len(ins), b - a)
                        # recording: every sample holds, only the sampler left a hole; whole-state holes stay FAIL
                        hid = gap >= 0.5 * (b - a) or gap > REC_HOLE * mg or len(ins) < 2
                        rec['claim:%s' % txt[:30]] = 'hid' if hid else rec.get('claim:%s' % txt[:30], 'warn')
                        why += ' [rec-%s]' % ('hid' if hid else 'warn')
                    else:
                        lines.append('claim PASS "%s" %s over %.2f..%.2f (%d samples)' % (txt, fmt_cond(c), a, b, len(ins))); continue
                    if bad or not ins:
                        prod.add('claim:%s' % txt[:30])   # a wrong value / no sample at all: product, never PASS-REC
                    fails.append('claim:%s' % txt[:30]); lines.append('claim FAIL "%s" wants %s over %.2f..%.2f: %s' % (txt, fmt_cond(c), a, b, why))
        elif kind == 'forbid':
            c = conds[0]
            spans = [(s[0], t_last if s[1] is None else s[1]) for s in segs if rx is None or rx.search(s[2])]
            sm = S.get(c[0], [])
            hits = [x for x in sm if any(a <= x[0] <= b for a, b in spans) and cond_ok(c, x[1])]
            if hits:
                fails.append('forbid:%s' % fmt_cond(c)[:30])
                lines.append('forbid FAIL %s: %d samples, first %s=%s at %.2f' % (fmt_cond(c), len(hits), c[0], hits[0][1], hits[0][0]))
            elif not sm and c[0] not in sparse:
                fails.append('forbid-unsampled:%s' % c[0]); lines.append('forbid FAIL %s: key %s never sampled (no evidence)' % (fmt_cond(c), c[0]))
            else:
                lines.append('forbid PASS %s' % fmt_cond(c))
        elif kind == 'cover':
            for k in conds:
                gap = coverage(S.get(k, []), t_first, t_last)
                if gap > mg:
                    # recording check; it hides a state when a hole is huge or swallows a whole labelled segment
                    holes = gaps(S.get(k, []), t_first, t_last, mg)
                    hidden = [s[2] for s in segs for g0, g1 in holes
                              if g0 <= s[0] and (t_last if s[1] is None else s[1]) <= g1]
                    hid = gap > REC_HOLE * mg or bool(hidden)
                    rec['cover:%s' % k] = 'hid' if hid else 'warn'
                    fails.append('cover:%s' % k); lines.append('cover FAIL %s: largest unsampled gap %.1f s (max %.1f) over %.2f..%.2f [rec-%s%s]' % (
                        k, gap, mg, t_first, t_last, 'hid' if hid else 'warn', (': hides "%s"' % hidden[0][:40]) if hidden else ''))
                else:
                    lines.append('cover PASS %s' % k)
    if vlen is not None and end is not None:
        over = vlen - (end + cfg['offset'])
        if over > cfg['endslack'] or over < -0.2:
            fails.append('video-length')
            # recording check; a video that ends before the last state (+ grace) has no frames of it: hid
            last = segs[-1][0] if segs else 0.0
            hid = over < 0 and vlen < last + cfg['offset'] + g
            rec['video-length'] = 'hid' if hid else 'warn'
            lines.append('end FAIL video %.2f s vs end label %.2f + offset %.2f: %+.2f s %s [rec-%s]' % (vlen, end, cfg['offset'], over,
                         'past the end label' if over > 0 else 'short', 'hid' if hid else 'warn'))
        else:
            lines.append('end PASS video %.2f s, end label %.2f (%+.2f s)' % (vlen, end, over))
    for n in prod:
        rec.pop(n, None)
    return not fails, lines, fails


def sync_grade(stxt):
    """'warn' | 'hid' for a failed sync check text: no flash paired at all, or a lag beyond SYNC_HIDE, hides states.
    Frame stamp: a label whose mark never showed keeps an estimated time (warn); no mark shown at all = hid."""
    m = re.search(r'^stamp .* marks=(\d+)/', stxt)
    if m:
        return 'warn' if int(m.group(1)) > 0 else 'hid'
    m = re.search(r'paired=(\d+)', stxt)
    if not m or int(m.group(1)) == 0:
        return 'hid'
    lag = re.search(r'lag=([-+\d.]+)\.\.([-+\d.]+)', stxt)
    if lag and max(abs(float(lag.group(1))), abs(float(lag.group(2)))) > SYNC_HIDE:
        return 'hid'
    return 'warn'


def grade(fails, rec):
    """(verdict, rec_warn, rec_hid): PASS / PASS-REC (only recording checks failed, none hides a state) / FAIL."""
    if not fails:
        return 'PASS', [], []
    warn = [f for f in fails if rec.get(f) == 'warn']
    hid = [f for f in fails if rec.get(f) == 'hid']
    product = [f for f in fails if f not in rec]
    return ('FAIL' if product or hid else 'PASS-REC'), warn, hid


# ---- native animation liveness from the KenshiFP log (Misses 2026-10-10 fb_lives: fb_lives stayed 0 over 90+ free
# blocks, progress p=1.010 / pmin 9.000 the whole time, while the body showed the block pose; nothing in the vm rec or the
# sampled evidence shows it). CLASS: a native animation the take relies on never ran (progress never live). Judged from
# the log lines `PT34 free block start tech=..` / `PT34 free block end: .. pmin=.. live=N` and `free swing end: .. live=N`.
LOGT = re.compile(r'^\[(\d+):(\d+):(\d+(?:\.\d+)?)\]')


def log_events(path, t0=None, t1=None):
    """[(wall s, kind, live, info)] for free block / free swing ends between wall clock t0..t1 (s of the day)."""
    out, tech = [], None
    for line in open(path, errors='replace'):
        m = LOGT.match(line)
        if not m:
            continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if (t0 is not None and t < t0) or (t1 is not None and t > t1):
            continue
        g = re.search(r'PT34 free block start tech=([0-9a-fA-F]+)', line)
        if g:
            tech = g.group(1).lstrip('0')[-6:]
            continue
        g = re.search(r'(PT34 free block end|free swing end):.*?pmin=([-0-9.]+).*?live=(\d)', line)
        if g:
            out.append((t, 'block' if 'block' in g.group(1) else 'swing', int(g.group(3)), 'pmin=%s%s' % (g.group(2), (' tech=' + tech) if tech and 'block' in g.group(1) else '')))
            tech = None
    return out


def wall(s):
    h, m, x = s.split(':'); return int(h) * 3600 + int(m) * 60 + float(x)


def animlive_check(path, t0=None, t1=None):
    E = log_events(path, t0, t1)
    dead = [e for e in E if not e[2]]
    ok = not dead
    txt = 'ends=%d (block %d swing %d) never_live=%d%s' % (len(E), sum(1 for e in E if e[1] == 'block'), sum(1 for e in E if e[1] == 'swing'),
                                                           len(dead), '' if ok else ':BAD')
    if dead:
        txt += ' ' + ' '.join('%s@%02d:%02d:%05.2f(%s)' % (e[1], e[0] // 3600, e[0] % 3600 // 60, e[0] % 60, e[3]) for e in dead[:6])
    return ok, txt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--labels', required=True); ap.add_argument('--ev', action='append', default=[])
    ap.add_argument('--rules', required=True); ap.add_argument('--video'); ap.add_argument('--video-len', type=float, help='known video length (s) instead of --video (archived takes)'); ap.add_argument('--name', default='take')
    ap.add_argument('--set', action='append', default=[], help='name=value, overrides a rules-file `set`')
    ap.add_argument('--no-cursor', action='store_true', help='skip the mouse-cursor frame check on --video')
    ap.add_argument('--no-overlay', action='store_true', help='skip the foreign-overlay frame check on --video')
    ap.add_argument('--no-sync', action='store_true', help='skip the sync-flash label lag check on --video')
    ap.add_argument('--synced-out', help='write the labels at their measured video times (sync flashes) here, for the burn-in')
    ap.add_argument('--kfplog', help='KenshiFP.log of the take: every free block / free swing must have run its native animation (live=1)')
    ap.add_argument('--log-t0', help='wall clock HH:MM:SS[.ms] of take t=0 in the log (default: judge the whole log)')
    ap.add_argument('--stamp', choices=('auto', 'on', 'off'), default='auto',
                    help='frame stamp (harness `stamp on`): auto = use it when the video has one, on = required, off = ignore')
    a = ap.parse_args()
    L = read_labels(a.labels); S = read_ev(a.ev); R, cfg = read_rules(a.rules)
    for x in a.set:
        k, _, v = x.partition('='); cfg[k] = float(v)
    vlen = video_len(a.video) if a.video else a.video_len
    if a.video and vlen is None:
        print('video FAIL cannot read the length of %s' % a.video); return 1
    sync_res, t0off = None, None
    # Frame stamp (frame-stamp, 2026-10-10): the video carries the game frame + FP state + label mark in every frame
    # (stamp.py). Labels move to the frame their mark shows (a claim window ends at the next label's mark or its
    # earliest time on the send clock, whichever is first: stamp.py `early`), the stamp keys (ui_state, hud_text, loaded, stroke, ...)
    # replace the sampled ones (one sample per video frame: a gap is a real capture/game gap), the other evidence is
    # shifted by the measured T0 (mark 0), so everything is judged on the video clock (offset 0) and the flash sync
    # check is replaced by the mark check (every label's mark shown).
    stamp = None
    if a.video and a.stamp != 'off':
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stamp as stampmod
        stamp = stampmod.take_inputs(a.video, L, sends=S.get('sync'))
        if stamp is None and a.stamp == 'on':
            print('stamp FAIL no frame stamp in %s' % a.video)
            print('RESULT %s FAIL stamp' % a.name)
            return 1
    if stamp is not None:
        L = sorted(stamp['labels'], key=lambda x: x[0]); S = stamp['merge'](S); t0off = 0.0
        sok = not stamp['missing']
        sync_res = (sok, stamp['text'] + ('' if sok else ':BAD'), L)
    elif a.video and not a.no_sync:   # T6 label lag: every label's sync flash within synclag of the T0 offset
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import frames
        marks = frames.syncmarks(a.video) if S.get('sync') else []
        sync_res = sync_check(L, S, marks, cfg.get('synclag', 0.15), bool(cfg.get('sync', 0)))
        m = re.search(r'paired=([1-9]\d*) t0_offset=([-\d.]+)', sync_res[1])
        t0off = float(m.group(2)) if m else None
    # E6 "stop lag" (op-e6c +2.1 s, 2026-10-10): the video starts before T0 (recorder launched first), so with no measured
    # offset the start gap counted as a tail. With a T0 sync flash the end check uses the measured offset; `set trim 1`
    # cuts a real tail (> endslack past the end label) at end + 0.3 s (stream copy, in place) before judging.
    ecfg = dict(cfg, offset=t0off) if t0off is not None else cfg
    end = next((t for t, x in L if x.lower() == 'end'), None)
    pre = []
    if a.video and t0off is not None:
        pre.append('end-offset T0 at video %.2f s (%s)' % (t0off, 'frame stamp: all times on the video clock' if stamp else 'sync flash 0'))
    if (a.video and cfg.get('trim', 0) and 'corpus' not in a.video.replace('\\', '/').lower().split('/') and t0off is not None and end is not None and vlen is not None
            and vlen - (end + t0off) > cfg['endslack']):
        cut = end + t0off + 0.3
        tmp = a.video + '.trim.mp4'
        r = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', a.video, '-t', '%.3f' % cut, '-c', 'copy',
                            '-f', 'mp4', tmp], capture_output=True, text=True)
        if r.returncode == 0 and video_len(tmp):
            import os
            os.replace(tmp, a.video)
            pre.append('trim video %.2f -> %.2f s (tail %+.2f s past the end label cut at end + 0.3)' % (vlen, video_len(a.video), vlen - (end + t0off)))
            vlen = video_len(a.video)
        else:
            pre.append('trim FAILED (%s), judged untrimmed' % (r.stderr.strip()[-120:] or 'no output'))
    rec = {}
    ok, lines, fails = check(L, S, R, ecfg, vlen, rec, stamp['early'] if stamp is not None else None)
    lines = pre + lines
    if a.video and not a.no_cursor:   # Shay 2026-10-10 ticket A: the mouse cursor must never show in a take
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import frames
        cok, ctxt = frames.cursor_check(a.video)
        lines.append('cursor %s %s' % ('PASS' if cok else 'FAIL', ctxt))
        if not cok:
            ok = False; fails.append('cursor')
    if a.video and not a.no_overlay:   # class of the cursor miss: nothing foreign drawn over the scene (2026-10-10)
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import frames
        vok, vtxt = frames.overlay_check(a.video)
        lines.append('overlay %s %s' % ('PASS' if vok else 'FAIL', vtxt))
        if not vok:
            ok = False; fails.append('overlay')
    if sync_res is not None:
        sok, stxt, synced = sync_res
        lines.append('sync %s %s' % (('PASS' if sok else 'FAIL') if not stxt.startswith('SKIP') else 'SKIP', stxt))
        if not sok:
            ok = False; fails.append('sync'); rec['sync'] = sync_grade(stxt)
        if synced and a.synced_out:
            with open(a.synced_out, 'w') as fh:
                for t, x in synced:
                    fh.write('%.3f %s\n' % (t, x))
    if a.kfplog:
        t0 = wall(a.log_t0) if a.log_t0 else None
        t1 = t0 + (L[-1][0] if L else 0) + 1.0 if t0 is not None else None
        aok, atxt = animlive_check(a.kfplog, t0, t1)
        lines.append('animlive %s %s' % ('PASS' if aok else 'FAIL', atxt))
        if not aok:
            ok = False; fails.append('animlive')
    for x in lines:
        print(x)
    verdict, warn, hid = grade(fails, rec)   # PASS-REC: only recording checks failed (judged on what was recorded)
    if verdict == 'PASS-REC':
        print('RESULT %s PASS-REC %d checks rec-warn=%s' % (a.name, len(lines), ','.join(warn)))
        return 0
    print('RESULT %s %s %s%s' % (a.name, 'PASS' if ok else 'FAIL', ' '.join(fails) if fails else '%d checks' % len(lines),
                                 (' rec-hid=' + ','.join(hid)) if hid else ''))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
