#!/usr/bin/env python3
"""stamp.py -- read the harness frame stamp from every frame of a take video (frame-exact sync, 2026-10-10).

The harness (`stamp on`, src/FrameStamp.h) draws a black/white grid in the top-left corner of the game view every rendered
frame: row 0 = sync row (even columns white), rows 1..4 = 96 data cells (MSB first, row-major):
  fc 24 (render-frame counter) | mark 8 (last `sync_flash n`) | flags 4 (bit0 payload fresh, bit1 painted on set,
  bits2-3 version 1) | lo 32 | hi 16 | spare 4 (0) | crc8 (poly 0x07 over the first 88 bits)
KenshiFP payload (kfp-frame-stamp patch, kfp_stamp_frame):
  lo: ui 5 | stroke+1 3 | phase 2 | view 2 | zoomb 3 | wcls 3 | vm_on 1 | tab 6 (table hash bits 0-5) | kseq 7
  hi: loaded 2 | swings 4 | hold 1 | ui_open 1 | tab hi 8 (table hash bits 6-13)
So every video frame maps to the exact game render frame and FP state shown: duplicated frames (same fc), skipped game
frames (fc step > 1), label marks to the frame, no sampled event log and no magenta flash needed.

Usage (WSL python3, ffmpeg on PATH):
  stamp.py <video> [--out table.tsv] [--ev ev.txt] [--labels L --labels-out L2] [--log stamp.log]
                  [--cell 8] [--view-w 1600] [--name take]
  stamp.py --selftest            (layout vector + synthetic x264 video round trip incl. a downscaled copy)
  --out        per-frame TSV: vf t ok fc dfc mark flags ui stroke phase view zoomb wcls vm tab kseq loaded swings hold
               uiopen  (ok=0: no readable stamp in that frame, other fields '-')
  --ev         takecheck evidence, one line per decoded frame at VIDEO time:
               `<t> stamp ui_state=.. hud_text=.. stroke=.. view=.. zoomb=.. wcls=.. vm=.. loaded=.. gf=.. mark=..`
  --labels     the take's labels file (`<t> <text>`, last `end`): --labels-out gets the same labels at their VIDEO time,
               label k (k-th non-end line, 1-based) = the first frame showing mark k (take-sample.sh take_mark sends
               sync_flash k with it; mark 0 = T0); `end` = its script time shifted like the last mark. Prints
               `label k t_script -> t_video gf` lines; a label whose mark never shows = `label k MISSING`.
  --log        the harness stamp log (`stamp on .. log <file>`: `<fc> <epoch> <lo> <hi> <mark> <flags>` per change):
               agreement check: every logged change inside the decoded fc range must show in the video at exactly that
               fc, or at the first decoded fc after it when the game frame was not captured (counted, not a fail);
               a decoded frame whose payload/mark differs from the log's value at its fc = disagreement (FAIL).
Last line: `RESULT <name> PASS|FAIL frames=.. ok=.. dup=.. skip_max=.. marks=.. [agree=..]`.
"""
import argparse, json, os, subprocess, sys

COLS, ROWS, DATA = 24, 5, 96
UI = ['off', 'none', 'down', 'holstered', 'reloading', 'aiming', 'ready', 'swinging', 'staggered', 'recovering',
      'blocking', 'turret_no_power', 'turret_reload', 'turret_loaded', 'turret_empty']
VIEW = ['off', 'eye', 'zoom', 'freecam']
PHASE = ['normal', 'draw', 'lower', 'p3']
WCLS = ['melee', 'ranged', 'fists', 'c3', 'c4', 'c5', 'c6', 'none']
HUD = {'turret_no_power': 'no_power', 'turret_reload': 'reload', 'turret_loaded': 'loaded', 'turret_empty': 'empty'}


def crc8(data):
    c = 0
    for d in data:
        c ^= d
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xff if c & 0x80 else (c << 1) & 0xff
    return c


def crc_bits(bits):
    by = [int(''.join(str(b) for b in bits[i * 8:i * 8 + 8]), 2) for i in range(11)]
    return crc8(by)


def encode(fc, mark, flags, lo, hi):
    s = '{:024b}{:08b}{:04b}{:032b}{:016b}0000'.format(fc & 0xffffff, mark & 0xff, (flags & 3) | 4, lo & 0xffffffff,
                                                         hi & 0xffff)
    bits = [int(c) for c in s]
    return bits + [int(c) for c in '{:08b}'.format(crc_bits(bits))]


def decode_bits(bits):
    s = ''.join(str(b) for b in bits)
    fc, mark, flags = int(s[0:24], 2), int(s[24:32], 2), int(s[32:36], 2)
    lo, hi, spare, crc = int(s[36:68], 2), int(s[68:84], 2), int(s[84:88], 2), int(s[88:96], 2)
    if spare or flags >> 2 != 1 or crc != crc_bits(bits):
        return None
    return dict(fc=fc, mark=mark, flags=flags & 3, lo=lo, hi=hi)


def kfp_fields(lo, hi):
    ui = lo & 31
    return dict(ui=UI[ui] if ui < len(UI) else 'u%d' % ui, stroke=((lo >> 5) & 7) - 1, phase=PHASE[(lo >> 8) & 3],
                view=VIEW[(lo >> 10) & 3], zoomb=(lo >> 12) & 7, wcls=WCLS[(lo >> 15) & 7], vm=(lo >> 18) & 1,
                tab=((lo >> 19) & 63) | (((hi >> 8) & 255) << 6), kseq=(lo >> 25) & 127, loaded=hi & 3,
                swings=(hi >> 2) & 15, hold=(hi >> 6) & 1, uiopen=(hi >> 7) & 1)


def probe(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                          '-of', 'json', video], capture_output=True, text=True, check=True).stdout
    st = json.loads(out)['streams'][0]
    pts = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time',
                          '-of', 'csv=p=0', video], capture_output=True, text=True, check=True).stdout.split()
    t = sorted(float(x) for x in pts if x not in ('', 'N/A'))
    return st['width'], st['height'], t


def read_corner(video, cw, ch):
    import numpy as np
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', video, '-vf', 'crop=%d:%d:0:0,format=gray' % (cw, ch),
           '-fps_mode', 'passthrough', '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (cw * ch)
    return np.frombuffer(raw[:n * cw * ch], dtype=np.uint8).reshape(n, ch, cw)


def cell_means(img, C):
    import numpy as np
    out = np.zeros((ROWS, COLS))
    for r in range(ROWS):
        y0, y1 = (r + 1) * C + C * 0.25, (r + 1) * C + C * 0.75
        for c in range(COLS):
            x0, x1 = (c + 1) * C + C * 0.25, (c + 1) * C + C * 0.75
            out[r, c] = img[int(round(y0)):max(int(round(y1)), int(round(y0)) + 1),
                            int(round(x0)):max(int(round(x1)), int(round(x0)) + 1)].mean()
    return out


def read_stamp(img, C):
    m = cell_means(img, C)
    sync = m[0]
    wh, bl = sync[0::2], sync[1::2]
    if wh.min() - bl.max() < 40:
        return None
    th = (wh.mean() + bl.mean()) / 2
    bits = [1 if v > th else 0 for v in m[1:].ravel()]
    return decode_bits(bits)


def find_cell(frames, scale, hint):
    cands = [hint * scale] if hint else []
    cands += [c * scale for c in range(4, 33) if c != hint]
    for C in cands:
        hits = sum(1 for f in frames if (COLS + 2) * C <= f.shape[1] and read_stamp(f, C))
        if hits >= max(1, len(frames) // 3):
            return C
    return None


def decode_video(video, cell=8, view_w=None):
    w, h, pts = probe(video)
    scale = w / float(view_w or w)
    cw = min(w, int((COLS + 2) * 32 * scale) + 4) & ~1   # even: yuv420 crops round odd sizes down
    ch = min(h, int((ROWS + 2) * 32 * scale) + 4) & ~1
    F = read_corner(video, cw, ch)
    step = max(1, len(F) // 40)
    C = find_cell(F[::step][:40], scale, cell)
    rows = []
    for i, f in enumerate(F):
        d = read_stamp(f, C) if C else None
        t = pts[i] - pts[0] if i < len(pts) else (rows[-1]['t'] + 1 / 30.0 if rows else 0.0)
        rows.append(dict(vf=i, t=t, d=d))
    # unwrap fc (24 bits) and dfc
    prev, base = None, 0
    for r in rows:
        d = r['d']
        if not d:
            continue
        fc = d['fc'] + base
        if prev is not None and fc < prev - (1 << 23):
            base += 1 << 24
            fc += 1 << 24
        r['fc'] = fc
        r['dfc'] = fc - prev if prev is not None else 0
        prev = fc
    return rows, C


def map_marks(rows):
    """first video row per (unwrapped) mark value, in order of appearance"""
    marks, seen, k, last = {}, set(), 0, None
    for r in rows:
        d = r['d']
        if not d:
            continue
        m = d['mark']
        if m != last:
            # unwrap 8-bit marks: marks only count up
            while (k & ~255) + m < k:
                k += 256
            k = (k & ~255) + m
            if k not in marks:
                marks[k] = r
            last = m
    return marks


def write_table(rows, path):
    hdr = 'vf t ok fc dfc mark flags ui stroke phase view zoomb wcls vm tab kseq loaded swings hold uiopen'.split()
    with open(path, 'w') as o:
        o.write('\t'.join(hdr) + '\n')
        for r in rows:
            d = r['d']
            if not d:
                o.write('%d\t%.4f\t0' % (r['vf'], r['t']) + '\t-' * (len(hdr) - 3) + '\n')
                continue
            k = kfp_fields(d['lo'], d['hi'])
            o.write('\t'.join(str(x) for x in [r['vf'], '%.4f' % r['t'], 1, r['fc'], r['dfc'], d['mark'], d['flags'],
                                               k['ui'], k['stroke'], k['phase'], k['view'], k['zoomb'], k['wcls'],
                                               k['vm'], k['tab'], k['kseq'], k['loaded'], k['swings'], k['hold'],
                                               k['uiopen']]) + '\n')


def write_ev(rows, path):
    with open(path, 'w') as o:
        for r in rows:
            d = r['d']
            if not d:
                continue
            k = kfp_fields(d['lo'], d['hi'])
            o.write('%.4f stamp ui_state=%s hud_text=%s stroke=%d view=%s zoomb=%d wcls=%s vm=%d loaded=%d gf=%d '
                    'mark=%d\n' % (r['t'], k['ui'], HUD.get(k['ui'], k['ui']), k['stroke'], k['view'], k['zoomb'],
                                   k['wcls'], k['vm'], k['loaded'], r['fc'], d['mark']))


def relabel(rows, marks, labels, out):
    L = []
    for line in open(labels):
        p = line.rstrip('\n').split(None, 1)
        if len(p) == 2:
            try:
                L.append((float(p[0]), p[1]))
            except ValueError:
                pass
    res, k, shift, lines = [], 0, None, []
    m0 = marks.get(0)
    if m0:
        shift = m0['t']
    for t, text in L:
        if text.strip() == 'end':
            tv = t + (shift if shift is not None else 0.0)
            res.append((tv, text))
            continue
        k += 1
        r = marks.get(k)
        if r:
            res.append((r['t'], text))
            shift = r['t'] - t
            lines.append('label %d %.2f -> %.4f gf=%d %s' % (k, t, r['t'], r['fc'], text))
        else:
            res.append((t + (shift or 0.0), text))
            lines.append('label %d MISSING (mark %d never shown) %s' % (k, k, text))
    if out:
        with open(out, 'w') as o:
            for t, text in res:
                o.write('%.3f %s\n' % (t, text))
    return lines


def agree(rows, logpath):
    """compare decoded frames with the harness stamp log (changes): exact fc for every captured change"""
    ch = []
    for line in open(logpath):
        p = line.split('\t')
        if len(p) >= 6:
            ch.append((int(p[0]), int(p[2], 16), int(p[3], 16), int(p[4])))
    ch.sort()
    ok_rows = [r for r in rows if r['d']]
    if not ok_rows or not ch:
        return False, 'no decoded frames or empty log', 0, 0, 0
    # log fc is the raw 24-bit counter; decoded fc unwrapped: compare modulo 2^24
    import bisect
    keys = [c[0] for c in ch]
    bad, exact, late = [], 0, 0
    for r in ok_rows:
        fc = r['fc'] & 0xffffff
        i = bisect.bisect_right(keys, fc) - 1
        if i < 0:
            continue
        _, lo, hi, mk = ch[i]
        d = r['d']
        if (d['lo'], d['hi'], d['mark']) != (lo, hi & 0xffff, mk):
            bad.append('vf%d fc%d video lo=%08x hi=%04x mark=%d log lo=%08x hi=%04x mark=%d' % (
                r['vf'], fc, d['lo'], d['hi'], d['mark'], lo, hi, mk))
    fcs = sorted(r['fc'] & 0xffffff for r in ok_rows)
    lo_fc, hi_fc = fcs[0], fcs[-1]
    for c in ch:
        if lo_fc < c[0] <= hi_fc:
            j = bisect.bisect_left(fcs, c[0])
            if fcs[j] == c[0]:
                exact += 1
            else:
                late += 1
    return not bad, (bad[:5]), exact, late, len(bad)


STAMP_KEYS = ('ui_state', 'hud_text', 'loaded', 'stroke', 'view', 'zoomb', 'wcls', 'vm', 'gf', 'mark')


def ev_series(rows):
    """{key: [(video t, value)]} from the decoded frames (takecheck evidence form)"""
    S = {k: [] for k in STAMP_KEYS}
    for r in rows:
        d = r['d']
        if not d:
            continue
        k = kfp_fields(d['lo'], d['hi'])
        v = dict(ui_state=k['ui'], hud_text=HUD.get(k['ui'], k['ui']), loaded=str(k['loaded']), stroke=str(k['stroke']),
                 view=k['view'], zoomb=str(k['zoomb']), wcls=k['wcls'], vm=str(k['vm']), gf=str(r['fc']),
                 mark=str(d['mark']))
        for key in STAMP_KEYS:
            S[key].append((r['t'], v[key]))
    return S


def take_inputs(video, L, cell=8, view_w=None):
    """For takecheck / review-pack: None when the video has no stamp, else dict(
         labels=[(video t, text)]  (label k at the first frame showing mark k; `end` shifted like the last mark),
         off0 = video time of take T0 (mark 0; else derived from the first mark found) or None,
         series = stamp evidence {key: [(video t, value)]}, rows, marks, missing=[k...], text=one summary line,
         merge(S) -> evidence S in video time: the stamp keys replace the sampled ones, the rest shifted by off0,
                     the flash-sync keys (sync, sync_off) dropped)"""
    rows, C = decode_video(video, cell, view_w)
    ok = [r for r in rows if r['d']]
    if len(ok) < max(3, len(rows) // 2):
        return None
    marks = map_marks(rows)
    labels, k, shift, missing = [], 0, None, []
    off0 = marks[0]['t'] if 0 in marks else None
    if off0 is not None:
        shift = off0
    for t, text in L:
        if text.strip().lower() == 'end':
            labels.append((t + (shift or 0.0), text))
            continue
        k += 1
        r = marks.get(k)
        if r:
            if off0 is None:
                off0 = r['t'] - t
            shift = r['t'] - t
            labels.append((r['t'], text))
        else:
            missing.append(k)
            labels.append((t + (shift or 0.0), text))
    if off0 is None:
        off0 = 0.0
    series = ev_series(rows)
    # the FP keys only when a mod (KenshiFP kfp-frame-stamp) really filled the payload: else (old KenshiFP, payload 0)
    # the stamp gives frames + marks only and the sampled state keys stay
    fresh = sum(1 for r in ok if r['d']['flags'] & 1) / float(len(ok))
    if fresh < 0.5:
        series = {k: series[k] for k in ('gf', 'mark')}
    dup = sum(1 for r in ok[1:] if r['dfc'] == 0)
    skip = max([r['dfc'] for r in ok[1:]] or [0])
    text = 'stamp frames=%d ok=%d dup=%d skip_max=%d marks=%d/%d t0=%.3f payload=%s%s' % (
        len(rows), len(ok), dup, skip, k - len(missing), k, off0, 'fp' if fresh >= 0.5 else 'none(%.2f)' % fresh,
        (' missing=' + ','.join(map(str, missing))) if missing else '')

    def merge(S):
        out = {}
        for key, ser in S.items():
            if key in series or key in ('sync', 'sync_off'):
                continue
            out[key] = [(t + off0, v) for t, v in ser]
        for key, ser in series.items():
            out[key] = list(ser)
        return out
    return dict(labels=labels, off0=off0, series=series, rows=rows, marks=marks, missing=missing, text=text,
                merge=merge)


def pack_events(video, labels_path):
    """review-pack: [(video t, what)] for every stamp state switch (exact frame) + every label at its mark, or None"""
    L = []
    if labels_path and os.path.exists(labels_path):
        for line in open(labels_path, errors='replace'):
            p = line.strip().split(None, 1)
            if len(p) == 2:
                try:
                    L.append((float(p[0]), p[1]))
                except ValueError:
                    pass
    ti = take_inputs(video, L)
    if ti is None:
        return None
    ev, prev = [], None
    keys = ('ui_state', 'stroke', 'view', 'wcls', 'loaded')
    for r in ti['rows']:
        d = r['d']
        if not d:
            continue
        k = kfp_fields(d['lo'], d['hi'])
        cur = dict(ui_state=k['ui'], stroke=k['stroke'], view=k['view'], wcls=k['wcls'], loaded=k['loaded'])
        if prev is not None and cur != prev:
            ev.append((r['t'], ', '.join('%s %s->%s' % (x, prev[x], cur[x]) for x in keys if prev[x] != cur[x]) +
                       ' (gf %d)' % r['fc']))
        prev = cur
    for t, text in ti['labels']:
        ev.append((t, 'label: ' + text))
    ev.sort()
    return ev, ti['text']


def synth(path, payloads, W=1600, H=900, C=8, fps=30, crf=28, seed=1):
    """test video: noisy 8x8-block scene with the stamp of each (fc, mark, lo, hi) frame drawn like the harness"""
    import numpy as np
    rng = np.random.default_rng(seed)
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
                          '%dx%d' % (W, H), '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt',
                          'yuv420p', path], stdin=subprocess.PIPE)
    for fc, mark, lo, hi in payloads:
        img = np.ascontiguousarray(rng.integers(0, 255, (H // 8 + 1, W // 8, 3), dtype=np.uint8)
                                   .repeat(8, 0).repeat(8, 1)[:H])
        bits = encode(fc, mark, 1, lo, hi)
        img[:(ROWS + 2) * C, :(COLS + 2) * C] = 0
        for r in range(ROWS):
            for c in range(COLS):
                if ((c % 2 == 0) if r == 0 else bits[(r - 1) * COLS + c]):
                    img[(r + 1) * C:(r + 2) * C, (c + 1) * C:(c + 2) * C] = 255
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()


def selftest():
    import numpy as np, tempfile
    b = encode(0x123456, 0xAB, 1, 0xDEADBEEF, 0xCAFE)
    s = ''.join(map(str, b))
    print('vector', s)
    want = '000100100011010001010110101010110101110111101010110110111110111011111100101011111110000011010110'
    assert s == want, 'vector differs from tests/frame_stamp_test.cpp'
    d = decode_bits(b)
    assert d == dict(fc=0x123456, mark=0xAB, flags=1, lo=0xDEADBEEF, hi=0xCAFE), d
    for i in range(DATA):
        bb = list(b)
        bb[i] ^= 1
        assert decode_bits(bb) is None, i
    # synthetic take: 1600x900 noisy scene, 30 fps, game 60 fps (fc += 2, some dups / skips), x264 crf 28
    tmp = tempfile.mkdtemp(prefix='stampself-')
    N = 90
    fcs, fc = [], 1000
    for i in range(N):
        fc += [2, 2, 2, 0, 3, 2, 1][i % 7]
        fcs.append(fc)
    vid = os.path.join(tmp, 'syn.mp4')
    synth(vid, [(fcs[i], i // 30, (i % 15) | (((i % 4) + 1) << 5), 1) for i in range(N)])
    small = os.path.join(tmp, 'small.mp4')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', vid, '-vf', 'scale=1280:720', '-c:v', 'libx264',
                    '-crf', '30', small], check=True)
    for v, vw in ((vid, None), (small, 1600)):
        rows, Cf = decode_video(v, 8, vw)
        got = [r.get('fc') for r in rows]
        assert got == fcs, (v, Cf, got[:10], fcs[:10])
        assert [r['d']['mark'] for r in rows] == [i // 30 for i in range(N)]
        print('synthetic %s: %d/%d frames exact (cell %.1f px)' % (os.path.basename(v), len(got), N, Cf))
    subprocess.run(['rm', '-rf', tmp])
    print('RESULT stamp-selftest PASS')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video', nargs='?')
    ap.add_argument('--out')
    ap.add_argument('--ev')
    ap.add_argument('--labels')
    ap.add_argument('--labels-out')
    ap.add_argument('--log')
    ap.add_argument('--cell', type=int, default=8)
    ap.add_argument('--view-w', type=int)
    ap.add_argument('--name', default='stamp')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.video:
        ap.error('video required')
    rows, C = decode_video(a.video, a.cell, a.view_w)
    ok = [r for r in rows if r['d']]
    if a.out:
        write_table(rows, a.out)
    if a.ev:
        write_ev(rows, a.ev)
    marks = map_marks(rows)
    fails = []
    if not ok:
        fails.append('no-stamp')
    dup = sum(1 for r in ok[1:] if r['dfc'] == 0)
    back = sum(1 for r in ok[1:] if r['dfc'] < 0)
    skip_max = max([r['dfc'] for r in ok[1:]] or [0])
    bad = len(rows) - len(ok)
    if back:
        fails.append('fc-backwards=%d' % back)
    print('stamp cell=%s frames=%d ok=%d unreadable=%d dup=%d skip_max=%d fc=%s..%s marks=%s' % (
        '%.1f' % C if C else '-', len(rows), len(ok), bad, dup, skip_max, ok[0]['fc'] if ok else '-',
        ok[-1]['fc'] if ok else '-', ','.join('%d@%.3f' % (k, r['t']) for k, r in sorted(marks.items()))))
    if a.labels:
        for line in relabel(rows, marks, a.labels, a.labels_out):
            print(line)
            if 'MISSING' in line:
                fails.append('label-missing')
    extra = ''
    if a.log:
        good, info, exact, late, nbad = agree(rows, a.log)
        extra = ' agree=%s exact=%d uncaptured=%d mismatch=%d' % ('yes' if good else 'no', exact, late, nbad)
        for x in (info if isinstance(info, list) else [info]):
            print('agree:', x)
        if not good:
            fails.append('log-mismatch')
    res = 'FAIL ' + ','.join(sorted(set(fails))) if fails else 'PASS'
    print('RESULT %s %s frames=%d ok=%d dup=%d skip_max=%d marks=%d%s' % (a.name, res, len(rows), len(ok), dup,
                                                                          skip_max, len(marks), extra))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
