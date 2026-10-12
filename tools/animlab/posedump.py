#!/usr/bin/env python3
"""posedump.py -- flat per-bone comparison of a KenshiFP viewmodel pose dump (game) with the lab's prediction.

The game writes `fp_posedump <file> [frames N] [warm W]` (KenshiFP patch kfp-posedump): <file> = per-bone pose lines,
<file>.rec = the `fp_vm rec` recording around it. The lab replays <file>.rec with kfpvm_replay --posedump (same writer,
vm_pd_write, compiled from the same client source) at the dumped records and this script prints flat per-bone deltas.

  posedump.py compare <game.pd> [--rec <rec>] [--lab-bin <kfpvm_replay with posedump>] [--lab <lab.pd>] [--tables <file>]
                      [--pos-tol 0.5] [--ang-tol 15] [--row POSEDUMP] [--out <dir>] [--skip N]
      --skip N = leave out the first N records (warm-up: solver state from before the recording settles).
      --zoom-skip Z = leave out records whose game S line has zoom >= Z (default 8 = metrics.AGREE_ZOOM_SKIP, env
      ANIMLAB_AGREE_ZOOM; 0 = keep all): zoomed-out records are measured from the zoomed camera, not agreement frames
      (every zoom-25 half showed as 60-140 deg and hid the real 139 cleaver ready-roll gap). Counted as zoom_skipped=.
      --lab given = compare two existing dumps (no replay). Else replays --rec (default <game.pd>.rec).
  posedump.py fromrec <rec.txt> <out.pd> [--frames a,b,c-d] [--all]
      (default: only records where the viewmodel is fully up, on + w=1, this and the previous record; --all = every one)
      a game-side dump from an EXISTING recording (no new game run): the measured arm joints (upper arm, forearm,
      hand positions), the weapon prop position and both hands' X/Y axes the rec stores per record. Compare it with the
      lab replay of that same recording: `compare <out.pd> --rec <rec.txt>`.
  posedump.py selftest
Dump format: `S <frame> st ti cls swing stroke prog zoom w phase` and
`B <frame> <bone> p=x,y,z [X=.. Y=.. Z=..]` (camera numbers from the unzoomed eye: x right, y up, z forward, dm).
Axes are compared only for arm bones (uarm farm hand prop): the lab places spine/neck/head/clavicles without rotation.
Output: one line per frame x bone, a per-bone max table, then ONE line `RESULT <row> PASS|FAIL ...`. Exit 0 PASS, 1 FAIL.
Default lab binary: $KFPVM_POSEDUMP or /root/animlab-build/kfpvm_posedump (build: components/KenshiFP/animlab/build.sh
--src /root/KenshiFP/client --patch pending-fixes/kfp-posedump.py --out /root/animlab-build/kfpvm_posedump; drop
--patch once kfp-posedump is in /root/KenshiFP).
"""
import math
import os
import subprocess
import sys
import tempfile

ARM = ('uarmL', 'uarmR', 'farmL', 'farmR', 'handL', 'handR', 'prop1', 'prop2')


def v3(s):
    return tuple(float(x) for x in s.split(','))


def parse(path):
    """-> dict(tables=hash|None, who=, S={frame: fields}, B={frame: {bone: {'p':..,'X':..}}})"""
    d = dict(tables=None, who=None, S={}, B={})
    with open(path) as fh:
        for line in fh:
            if line.startswith('# fp_posedump'):
                t = line.split()
                for k, x in enumerate(t):
                    if x.startswith('who='):
                        d['who'] = x[4:]
                    if x == 'tables' and k + 1 < len(t):
                        d['tables'] = t[k + 1]
                continue
            t = line.split()
            if len(t) >= 3 and t[0] == 'S':
                d['S'][int(t[1])] = t[2:]
            elif len(t) >= 4 and t[0] == 'B':
                b = {}
                for x in t[3:]:
                    k, _, v = x.partition('=')
                    b[k] = v3(v)
                d['B'].setdefault(int(t[1]), {})[t[2]] = b
    return d


def ang(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if na < 1e-6 or nb < 1e-6:
        return None
    c = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def compare(g, l, pos_tol, ang_tol, out=sys.stdout):
    """flat per-bone deltas; returns (ok, summary dict)"""
    frames = sorted(set(g['B']) & set(l['B']))
    worst = dict(dp=(0.0, None), da=(0.0, None))
    per = {}
    nbad = 0
    out.write('# frame bone dp(dm) dx dy dz dX dY dZ(deg)  (lab - game, camera numbers)\n')
    for f in frames:
        for bone in sorted(set(g['B'][f]) & set(l['B'][f])):
            gb, lb = g['B'][f][bone], l['B'][f][bone]
            if 'p' not in gb or 'p' not in lb:
                continue
            dv = tuple(b - a for a, b in zip(gb['p'], lb['p']))
            dp = math.sqrt(sum(x * x for x in dv))
            das = []
            if bone in ARM:
                for ax in 'XYZ':
                    if ax in gb and ax in lb:
                        das.append((ax, ang(gb[ax], lb[ax])))
            dmax = max([a for _, a in das if a is not None] or [0.0])
            bad = dp > pos_tol or dmax > ang_tol
            nbad += bad
            pb = per.setdefault(bone, [0.0, 0.0, 0])
            pb[0] = max(pb[0], dp); pb[1] = max(pb[1], dmax); pb[2] += 1
            if dp > worst['dp'][0]:
                worst['dp'] = (dp, '%s@%d' % (bone, f))
            if dmax > worst['da'][0]:
                worst['da'] = (dmax, '%s@%d' % (bone, f))
            ad = ' '.join('d%s=%s' % (ax, '-' if a is None else '%.1f' % a) for ax, a in das)
            out.write('%d %s dp=%.3f d=%.3f,%.3f,%.3f %s%s\n' % (f, bone, dp, dv[0], dv[1], dv[2], ad, ' BAD' if bad else ''))
    out.write('# per bone: bone max_dp(dm) max_dang(deg) frames\n')
    for bone in sorted(per):
        out.write('# %s %.3f %.1f %d\n' % (bone, per[bone][0], per[bone][1], per[bone][2]))
    return nbad == 0 and frames, dict(frames=len(frames), nbad=nbad, worst=worst, per=per)


def lab_bin():
    return os.environ.get('KFPVM_POSEDUMP', '/root/animlab-build/kfpvm_posedump')


def run_lab(rec, frames, tables, outpd):
    fl = ','.join(str(f) for f in frames)
    with tempfile.TemporaryDirectory(prefix='animlab-posedump-') as td:
        cmd = [lab_bin(), rec, os.path.join(td, 'replay.txt'), '--quiet', '--posedump', outpd, '--pd-frames', fl]
        if tables:
            cmd += ['--tables', tables]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if p.returncode != 0:
            raise RuntimeError('lab replay failed (%d): %s' % (p.returncode, (p.stderr or p.stdout).strip()[-300:]))


def cmd_compare(a):
    game = a[0]
    o = dict(rec=game + '.rec', lab=None, tables=None, pos_tol=0.5, ang_tol=15.0, row='POSEDUMP', out=None, skip=0,
             zoom_skip=float(os.environ.get('ANIMLAB_AGREE_ZOOM', '8')))
    i = 1
    while i < len(a):
        k = a[i].lstrip('-').replace('-', '_')
        if k == 'lab_bin':
            os.environ['KFPVM_POSEDUMP'] = a[i + 1]
        elif k in o:
            o[k] = a[i + 1] if k not in ('pos_tol', 'ang_tol', 'skip', 'zoom_skip') else (int(a[i + 1]) if k == 'skip' else float(a[i + 1]))
        else:
            sys.exit('posedump.py: unknown arg %s' % a[i])
        i += 2
    row = o['row']
    g = parse(game)
    if not g['B']:
        print('RESULT %s FAIL setup: no B lines in %s' % (row, game)); return 1
    labpd = o['lab']
    if not labpd:
        if not os.path.exists(o['rec']):
            print('RESULT %s FAIL setup: no recording %s' % (row, o['rec'])); return 1
        if o['out']:
            os.makedirs(o['out'], exist_ok=True)
        labpd = (os.path.join(o['out'], os.path.basename(game) + '.lab') if o['out'] else game + '.lab')
        try:
            run_lab(o['rec'], sorted(g['B']), o['tables'], labpd)
        except Exception as e:  # noqa
            print('RESULT %s FAIL lab: %s' % (row, e)); return 1
    l = parse(labpd)
    if o['skip'] and g['B']:   # warm-up records (solver history from before the recording: swing/roll settle)
        f0 = min(g['B'])
        for f in [f for f in g['B'] if f < f0 + o['skip']]:
            del g['B'][f]
    zsk = zoom_skip(g, o['zoom_skip'])
    out = sys.stdout
    if o['out']:
        os.makedirs(o['out'], exist_ok=True)
        out = open(os.path.join(o['out'], 'posedump-delta.txt'), 'w')
    ok, s = compare(g, l, o['pos_tol'], o['ang_tol'], out)
    if out is not sys.stdout:
        out.close()
    known = lambda h: bool(h) and len(h) == 8 and all(c in '0123456789abcdef' for c in h.lower())  # noqa: E731
    # older recordings have no `# tables` header: hash unknown, not a mismatch
    hash_ok = not (known(g['tables']) and known(l['tables']) and g['tables'] != l['tables'] and not o['tables'])
    w = s['worst']
    ev = 'frames=%d zoom_skipped=%d bad=%d worst_dp=%.3f(%s) worst_dang=%.1f(%s) tol=%.2fdm/%.0fdeg tables game=%s lab=%s lab_dump=%s' % (
        s['frames'], zsk, s['nbad'], w['dp'][0], w['dp'][1], w['da'][0], w['da'][1], o['pos_tol'], o['ang_tol'],
        g['tables'], l['tables'], labpd)
    if not s['frames']:
        print('RESULT %s FAIL no common frames %s' % (row, ev)); return 1
    if not hash_ok:
        print('RESULT %s FAIL tables hash mismatch %s' % (row, ev)); return 1
    print('RESULT %s %s %s' % (row, 'PASS' if ok else 'FAIL', ev))
    return 0 if ok else 1


S_ZOOM = 6   # index of zoom in an S line's fields (after `S <frame>`): st ti cls swing stroke prog zoom w phase


def zoom_skip(g, lim):
    """drop game records whose S line says zoom >= lim (or the S line of the record before: record n measures what
    frame n-1 rendered); returns how many were dropped."""
    if lim <= 0:
        return 0
    def z(f):
        t = g['S'].get(f)
        try:
            return float(t[S_ZOOM]) if t and len(t) > S_ZOOM else 0.0
        except ValueError:
            return 0.0
    drop = [f for f in g['B'] if z(f) >= lim or z(f - 1) >= lim]
    for f in drop:
        del g['B'][f]
    return len(drop)


def want(fl, i):
    if not fl:
        return True
    for part in fl.split(','):
        a, _, b = part.partition('-')
        if int(a) <= i <= int(b or a):
            return True
    return False


def cmd_fromrec(a):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import recfmt
    rec, outp = a[0], a[1]
    fl = a[a.index('--frames') + 1] if '--frames' in a else None
    allf = '--all' in a   # default: only frames with the viewmodel fully up (on, w=1) and the prev frame too
    r = recfmt.parse(rec)
    tab = None
    for m in r.meta:
        if m.startswith('tables '):
            tab = m.split()[1]
    n = 0
    with open(outp, 'w') as fo:
        fo.write('# fp_posedump v1 who=fromrec src=%s tables %s\n' % (os.path.basename(rec), tab or '-'))
        for k, f in enumerate(r.frames):
            if not want(fl, f['n']) or (not allf and (not f['on'] or f['w'] < 0.999 or not k
                                                       or not r.frames[k - 1]['on'] or r.frames[k - 1]['w'] < 0.999)):
                continue
            # record n measured what frame n-1 rendered = what the lab writes at record n (posedump after vm_frame)
            fo.write('S %d %s %d %d %d -1 %.4f %.2f %.3f %d\n' % (f['n'], f['st'], f['ti'], f['cls'], f['swing'], f['prog'],
                                                                   f['zoom'], f['w'], f['phase']))
            P = lambda v: '%.4f,%.4f,%.4f' % tuple(v)  # noqa
            for bone, key in (('uarmL', 'Lsh'), ('farmL', 'Lel'), ('handL', 'Lwr'), ('uarmR', 'Rsh'), ('farmR', 'Rel'), ('handR', 'Rwr')):
                extra = ''
                fh = f.get('fh')
                if fh and bone.startswith('hand'):
                    s = 0 if bone == 'handL' else 1
                    extra = ' X=%s Y=%s' % (P(fh[2 * s]), P(fh[2 * s + 1]))
                fo.write('B %d %s p=%s%s\n' % (f['n'], bone, P(f[key]), extra))
            n += 1
        fo.write('# end done\n')
    print('fromrec %s -> %s frames=%d tables=%s' % (rec, outp, n, tab))
    return 0 if n else 1


def cmd_selftest():
    import io
    g = dict(tables='aaaa', S={}, B={5: {'handR': {'p': (1, 2, 3), 'X': (1, 0, 0)}, 'spine': {'p': (0, 0, 0), 'X': (1, 0, 0)}}})
    l = dict(tables='aaaa', S={}, B={5: {'handR': {'p': (1.1, 2, 3), 'X': (math.cos(0.1), math.sin(0.1), 0)},
                                       'spine': {'p': (0, 0, 0.2), 'X': (0, 1, 0)}}})
    ok, s = compare(g, l, 0.5, 15, io.StringIO())
    assert ok and s['nbad'] == 0, s                      # within tolerance; spine axes ignored (lab places them unrotated)
    l['B'][5]['handR']['X'] = (0, 1, 0)
    ok, s = compare(g, l, 0.5, 15, io.StringIO())
    assert not ok and s['worst']['da'][1] == 'handR@5', s
    l['B'][5]['handR']['X'] = (1, 0, 0); l['B'][5]['handR']['p'] = (1, 2, 4)
    ok, s = compare(g, l, 0.5, 15, io.StringIO())
    assert not ok and s['worst']['dp'][1] == 'handR@5', s
    ok, s = compare(g, dict(tables='a', S={}, B={6: {}}), 0.5, 15, io.StringIO())
    assert not ok and s['frames'] == 0
    # zoomed-out records leave the comparison (zoom >= 8 on the record or the one before), zoom 0 ones stay
    z = dict(S={f: ['ready', '0', '0', '0', '-1', '0', zz, '1', '0'] for f, zz in ((1, '0'), (2, '25'), (3, '0'), (4, '7.9'))},
             B={1: {}, 2: {}, 3: {}, 4: {}})
    assert zoom_skip(z, 8) == 2 and sorted(z['B']) == [1, 4], z['B']
    z['B'] = {1: {}, 2: {}, 3: {}}
    assert zoom_skip(z, 0) == 0 and len(z['B']) == 3
    print('posedump selftest PASS')
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    c, rest = sys.argv[1], sys.argv[2:]
    sys.exit(cmd_compare(rest) if c == 'compare' else cmd_fromrec(rest) if c == 'fromrec' else
             cmd_selftest() if c == 'selftest' else 2)
