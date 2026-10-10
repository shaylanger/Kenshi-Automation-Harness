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
Video: the take must end at the `end` label: video length - (end + offset) within [-0.2, endslack] s, and no
frame may show the Windows mouse cursor (frames.py cursor at 5 fps; `--no-cursor` skips it) or a foreign overlay
(speech bar, name tag, damage number, hint list, popup: frames.py overlay at 2 fps; `--no-overlay` skips it).

KenshiFP log (`--kfplog LOG [--log-t0 HH:MM:SS.ms]`): every free block / free swing in the take must have run its native
animation (`... end: ... live=1`); a press whose progress never went live (fb_lives 0, p 1.010) fails `animlive`.

Usage: takecheck.py --labels L --ev E [--ev E2 ...] --rules R [--video V [--no-cursor] [--no-overlay] | --video-len S] [--kfplog LOG
       [--log-t0 T]] [--name take]
Exit 0 = PASS. Prints one line per check, then `RESULT <name> PASS|FAIL <failed checks>`.
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


def segments(L):
    """[(t0, t1, text)] per label (the `end` label closes the last one and has no segment)."""
    out = []
    for i, (t, txt) in enumerate(L):
        if txt.lower() == 'end':
            break
        t1 = L[i + 1][0] if i + 1 < len(L) else None
        out.append((t, t1, txt))
    return out


def coverage(samples, a, b):
    """largest gap (s) in [a, b] not covered by samples (segment edges count as gaps to the first/last sample)."""
    ts = [t for t, _ in samples if a <= t <= b]
    if not ts:
        return b - a
    pts = [a] + ts + [b]
    return max(pts[i + 1] - pts[i] for i in range(len(pts) - 1))


def video_len(path):
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except Exception:
        return None


def check(L, S, R, cfg, vlen=None):
    """returns (ok, [lines], [failed short names])."""
    lines, fails = [], []
    g, mg = cfg['grace'], cfg['maxgap']
    end = next((t for t, x in L if x.lower() == 'end'), None)
    segs = segments(L)
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
                    else:
                        lines.append('claim PASS "%s" %s over %.2f..%.2f (%d samples)' % (txt, fmt_cond(c), a, b, len(ins))); continue
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
                    fails.append('cover:%s' % k); lines.append('cover FAIL %s: largest unsampled gap %.1f s (max %.1f) over %.2f..%.2f' % (k, gap, mg, t_first, t_last))
                else:
                    lines.append('cover PASS %s' % k)
    if vlen is not None and end is not None:
        over = vlen - (end + cfg['offset'])
        if over > cfg['endslack'] or over < -0.2:
            fails.append('video-length')
            lines.append('end FAIL video %.2f s vs end label %.2f + offset %.2f: %+.2f s %s' % (vlen, end, cfg['offset'], over,
                         'past the end label' if over > 0 else 'short'))
        else:
            lines.append('end PASS video %.2f s, end label %.2f (%+.2f s)' % (vlen, end, over))
    return not fails, lines, fails


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
    ap.add_argument('--kfplog', help='KenshiFP.log of the take: every free block / free swing must have run its native animation (live=1)')
    ap.add_argument('--log-t0', help='wall clock HH:MM:SS[.ms] of take t=0 in the log (default: judge the whole log)')
    a = ap.parse_args()
    L = read_labels(a.labels); S = read_ev(a.ev); R, cfg = read_rules(a.rules)
    for x in a.set:
        k, _, v = x.partition('='); cfg[k] = float(v)
    vlen = video_len(a.video) if a.video else a.video_len
    if a.video and vlen is None:
        print('video FAIL cannot read the length of %s' % a.video); return 1
    ok, lines, fails = check(L, S, R, cfg, vlen)
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
    if a.kfplog:
        t0 = wall(a.log_t0) if a.log_t0 else None
        t1 = t0 + (L[-1][0] if L else 0) + 1.0 if t0 is not None else None
        aok, atxt = animlive_check(a.kfplog, t0, t1)
        lines.append('animlive %s %s' % ('PASS' if aok else 'FAIL', atxt))
        if not aok:
            ok = False; fails.append('animlive')
    for x in lines:
        print(x)
    print('RESULT %s %s %s' % (a.name, 'PASS' if ok else 'FAIL', ' '.join(fails) if fails else '%d checks' % len(lines)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
