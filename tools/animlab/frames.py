#!/usr/bin/env python3
"""frames.py -- checks on the frames of a recorded video (what the viewer actually sees), no game state needed.

  openground <video> [--fps 2] [--min-sky 0.08] [--share 0.9] [--band 0.08,0.62] [--from s] [--to s]
      Judgeable take = open ground with the horizon in view (Shay 2026-10-09; miss 2026-10-10 sword-z25-block.mp4: a
      steep slope filled the frame for the first half while the setup check had passed). Per sampled frame: share of
      sky pixels (blue-dominant: b > r + 12, b >= g - 4, b > 70) in the scene band (rows band[0]..band[1] of the
      height, 6% side margins: below the title label, above Kenshi's bottom UI panel). A frame is open when the share
      >= min-sky; the take passes when >= share of its frames are open. Night / fog (no blue sky) fails too: takes
      must be filmed in daylight. Prints the closed spans.
  cursor <video> [--fps 5] [--from s] [--to s]
      No Windows mouse cursor in any frame (Shay 2026-10-10, ticket A: sword-z25-block.mp4 shows the arrow at ~7 s,
      12-16 s, 35-36 s). Full-resolution frames at fps; arrow shape test at any cursor size (find_cursor). Prints the
      spans where it shows. takecheck.py runs it on every take given with --video.
Needs ffmpeg on PATH. Exit 0 = PASS. Last line: `RESULT <name> PASS|FAIL ...`.
"""
import argparse, subprocess, sys

W, H = 160, 90


def read_frames(video, fps, t0=None, t1=None):
    import numpy as np
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error']
    if t0:
        cmd += ['-ss', str(t0)]
    cmd += ['-i', video]
    if t1:
        cmd += ['-t', str(t1 - (t0 or 0))]
    cmd += ['-vf', 'fps=%g,scale=%d:%d' % (fps, W, H), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(int)


def sky_share(f, band=(0.08, 0.62)):
    sc = f[int(H * band[0]):int(H * band[1]), int(W * 0.06):int(W * 0.94)]
    r, g, b = sc[..., 0], sc[..., 1], sc[..., 2]
    return float(((b > r + 12) & (b >= g - 4) & (b > 70)).mean())


def openground(shares, fps, t0=0.0, min_sky=0.08, share=0.9):
    """(ok, text): shares = per-frame sky share at fps starting at t0."""
    if not shares:
        return False, 'no frames:BAD'
    good = [s >= min_sky for s in shares]
    frac = sum(good) / float(len(good))
    spans, st = [], None
    for k, g in enumerate(good + [True]):
        if not g and st is None:
            st = k
        elif g and st is not None:
            spans.append((t0 + st / fps, t0 + k / fps, min(shares[st:k]))); st = None
    ok = frac >= share
    txt = 'open=%.2f/%.2f%s frames=%d min_sky=%.2f sky_min=%.2f' % (frac, share, '' if ok else ':BAD', len(shares), min_sky, min(shares))
    if spans:
        txt += ' closed=' + ','.join('%.1f-%.1fs(sky %.2f)' % s for s in spans[:8]) + ('...' if len(spans) > 8 else '')
    return ok, txt


# ---------------- mouse cursor in frame (Shay 2026-10-10, ticket A) ----------------
def iter_frames_full(video, fps, t0=None, t1=None):
    """(t, HxWx3 int frame) at the video's own resolution, streamed (a full-res take does not fit in memory)."""
    import numpy as np
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                         '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(pr[0]), int(pr[1])
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error']
    if t0:
        cmd += ['-ss', str(t0)]
    cmd += ['-i', video]
    if t1:
        cmd += ['-t', str(t1 - (t0 or 0))]
    cmd += ['-vf', 'fps=%g' % fps, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n, k = w * h * 3, 0
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                break
            yield (t0 or 0.0) + k / fps, np.frombuffer(b, np.uint8).reshape(h, w, 3).astype(np.int16)
            k += 1
    finally:
        p.stdout.close(); p.wait()


def find_cursor(f, white=200, dark=110):
    """Windows arrow cursors in frame f (HxWx3): list of (x, y, size) = left outline column, tip row, length of the
    white run down the arrow's left edge (px; ~14 at 100% cursor size, ~37 at Shay's size). Shape test, any scale:
    tip pixel dark, a white run down the next column with a dark outline left of it, and a filled white right
    triangle whose row width grows 1 px per row (45 deg hypotenuse) over the head (55% of the run), not white just
    right of the hypotenuse. Text glyphs (constant stroke width) and UI edges fail the width profile."""
    import numpy as np
    W = f.min(2) > white
    D = f.max(2) < dark
    Hh, Ww = W.shape
    P = 8
    Wp = np.zeros((Hh + P, Ww + P), bool); Wp[:Hh, :Ww] = W
    Dp = np.zeros((Hh + P, Ww + P), bool); Dp[:Hh, :Ww] = D

    def s(A, dy, dx):
        return A[dy:dy + Hh, dx:dx + Ww]
    c = s(Dp, 0, 0) & s(Wp, 3, 1) & s(Wp, 6, 1) & s(Wp, 6, 3) & s(Dp, 4, 0) & ~s(Wp, 2, 5)
    out, seen = [], set()
    for y, x in zip(*np.nonzero(c)):
        if (x, y - 1) in seen or (x, y - 2) in seen:
            seen.add((x, y)); continue
        L, yy, gap = 0, y + 1, 0
        while yy < Hh and x + 1 < Ww and (W[yy, x + 1] or gap < 1):
            gap += not W[yy, x + 1]; L += 1; yy += 1
        h = int(0.55 * L)
        if L < 12 or L > 120 or h < 7 or y + h >= Hh:
            continue
        ins = tot = outw = outt = dk = prof = 0
        ws = []
        for r in range(2, h + 1):
            row = W[y + r, x + 1:x + 1 + 2 * r + 6]
            x1 = max(1, int(0.85 * r) - 1)
            ins += row[:x1].sum(); tot += x1
            o = W[y + r, x + r + 3:x + r + 6]; outw += o.sum(); outt += o.size
            dk += D[y + r, x]
            wr = int(np.argmin(row)) if not row.all() else row.size
            prof += abs(wr - r) <= max(1.5, 0.2 * r); ws.append(wr)
        n = h - 1
        grow = ws[-1] - ws[0] >= 0.7 * (h - 2) and ws[0] <= 3   # sharp tip, 45 deg growth (a glyph stem stays wide)
        if grow and ins >= 0.9 * tot and outt and outw <= 0.2 * outt and dk >= 0.7 * n and prof >= 0.8 * n:
            out.append((int(x), int(y), int(L))); seen.add((x, y))
    return out


def cursor_check(video, fps=5.0, t0=None, t1=None, name='take'):
    """(ok, text): no frame (sampled at fps) may show the mouse cursor. Prints the spans where it shows."""
    hits = []
    nfr = 0
    for t, f in iter_frames_full(video, fps, t0, t1):
        nfr += 1
        c = find_cursor(f)
        if c:
            hits.append((t, c[0]))
    if not nfr:
        return False, 'no frames:BAD'
    spans = []
    for t, c in hits:
        if spans and t - spans[-1][1] <= 1.5 / fps:
            spans[-1][1] = t
        else:
            spans.append([t, t, c])
    txt = 'frames=%d cursor_frames=%d%s' % (nfr, len(hits), ':BAD' if hits else '')
    if spans:
        txt += ' at=' + ','.join('%.1f-%.1fs(x%d,y%d)' % (a, b, c[0], c[1]) for a, b, c in spans[:10]) + ('...' if len(spans) > 10 else '')
    return not hits, txt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('openground'); p.add_argument('video'); p.add_argument('--fps', type=float, default=2.0)
    p.add_argument('--min-sky', type=float, default=0.08); p.add_argument('--share', type=float, default=0.9)
    p.add_argument('--band', default='0.08,0.62'); p.add_argument('--from', dest='t0', type=float); p.add_argument('--to', dest='t1', type=float)
    p.add_argument('--name', default='take')
    p = sp.add_parser('cursor'); p.add_argument('video'); p.add_argument('--fps', type=float, default=5.0)
    p.add_argument('--from', dest='t0', type=float); p.add_argument('--to', dest='t1', type=float)
    p.add_argument('--name', default='take')
    a = ap.parse_args()
    if a.cmd == 'cursor':
        ok, txt = cursor_check(a.video, a.fps, a.t0, a.t1)
        print('RESULT %s %s cursor %s' % (a.name, 'PASS' if ok else 'FAIL', txt))
        return 0 if ok else 1
    if a.cmd != 'openground':
        ap.print_help(); return 2
    band = tuple(float(x) for x in a.band.split(','))
    fr = read_frames(a.video, a.fps, a.t0, a.t1)
    ok, txt = openground([sky_share(f, band) for f in fr], a.fps, a.t0 or 0.0, a.min_sky, a.share)
    print('RESULT %s %s openground %s' % (a.name, 'PASS' if ok else 'FAIL', txt))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
