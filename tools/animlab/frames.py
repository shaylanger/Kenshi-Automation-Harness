#!/usr/bin/env python3
"""frames.py -- checks on the frames of a recorded video (what the viewer actually sees), no game state needed.

  openground <video> [--fps 2] [--min-sky 0.08] [--share 0.9] [--band 0.08,0.62] [--from s] [--to s]
      Judgeable take = open ground with the horizon in view (Shay 2026-10-09; miss 2026-10-10 sword-z25-block.mp4: a
      steep slope filled the frame for the first half while the setup check had passed). Per sampled frame: share of
      sky pixels (blue-dominant: b > r + 12, b >= g - 4, b > 70) in the scene band (rows band[0]..band[1] of the
      height, 6% side margins: below the title label, above Kenshi's bottom UI panel). A frame is open when the share
      >= min-sky; the take passes when >= share of its frames are open. Night / fog (no blue sky) fails too: takes
      must be filmed in daylight. Prints the closed spans.
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('openground'); p.add_argument('video'); p.add_argument('--fps', type=float, default=2.0)
    p.add_argument('--min-sky', type=float, default=0.08); p.add_argument('--share', type=float, default=0.9)
    p.add_argument('--band', default='0.08,0.62'); p.add_argument('--from', dest='t0', type=float); p.add_argument('--to', dest='t1', type=float)
    p.add_argument('--name', default='take')
    a = ap.parse_args()
    if a.cmd != 'openground':
        ap.print_help(); return 2
    band = tuple(float(x) for x in a.band.split(','))
    fr = read_frames(a.video, a.fps, a.t0, a.t1)
    ok, txt = openground([sky_share(f, band) for f in fr], a.fps, a.t0 or 0.0, a.min_sky, a.share)
    print('RESULT %s %s openground %s' % (a.name, 'PASS' if ok else 'FAIL', txt))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
