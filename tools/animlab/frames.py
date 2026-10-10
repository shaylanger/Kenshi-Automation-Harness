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
  overlay <video> [--fps 2] [--from s] [--to s]
      No foreign overlay over the scene (class of the cursor miss, Shay 2026-10-10): NPC speech bars, name tags, damage
      numbers, hint/notification lists, dialog popups, stray strings. Frames scaled to 1600x900, 16x10 px cells: text
      cells (outlined thin text or text on a flat dark panel, >= 3 glyph strokes) forming a line of >= 3 cells, or a flat
      neutral UI panel (rectangle with straight edges, >= 6x4 cells). Panel cells in >= 80% of the frames are the take's
      own HUD (baseline); text has NO baseline (a name tag shown in every frame is still foreign, Misses 2026-10-10
      persistent tag); expected zones: centred label band (x .15-.85, top 20%), Kenshi's bottom UI panel (bottom 30%) and
      the KenshiFP HUD text box (at W/2-90, H/2+20: LOADED / RELOAD n / NO POWER). takecheck.py runs it on every take given with --video.
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
def iter_frames_full(video, fps, t0=None, t1=None, size=None):
    """(t, HxWx3 int frame) at the video's own resolution (or size=(w, h)), streamed (a full-res take does not fit in memory)."""
    import numpy as np
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                         '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(pr[0]), int(pr[1])
    if size:
        w, h = size
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error']
    if t0:
        cmd += ['-ss', str(t0)]
    cmd += ['-i', video]
    if t1:
        cmd += ['-t', str(t1 - (t0 or 0))]
    cmd += ['-vf', ('fps=%g' % fps) + (',scale=%d:%d' % size if size else ''), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
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


KC_CENTRE = 6   # px: the game draws its own target cursor at the screen centre in FP view = the FP crosshair (accepted)


def find_kcursor(f, a0=5, a1=11, con=25, bright=90, share=0.8):
    """Kenshi's own target/move cursor (4 thin 1-px arrows pointing at a centre gap, ~25 px across): list of (x, y)
    centres. Misses 2026-10-10 "cursor variants": the harness-parked mouse showed as this cursor at (1278,719) in
    anim-xbow-z25 7-37 s and vm-rework anim-sword/xbow-z0, where the arrow test (find_cursor) saw nothing. Per centre:
    each arm (offsets a0..a1 px) is a thin line (brighter than the pixels 2 px to either side) on >= share of its
    pixels, the arrows stop short of the centre (a plain cross / grid line runs through) and every arm has arrowhead
    pixels beside the line (a UI grid line has none)."""
    import numpy as np
    L = f.min(2).astype(np.int16)
    Hh, Ww = L.shape
    Pd = np.pad(L, 2, mode='edge')
    V = (L - np.maximum(Pd[2:-2, :-4], Pd[2:-2, 4:]) > con) & (L > bright)
    Hm = (L - np.maximum(Pd[:-4, 2:-2], Pd[4:, 2:-2]) > con) & (L > bright)
    B = L > bright
    m = a1 + 2
    def sl(A, dy, dx):
        return A[m + dy:Hh - m + dy, m + dx:Ww - m + dx].astype(np.int16)
    need = int(np.ceil(share * (a1 - a0 + 1)))
    c = np.ones((Hh - 2 * m, Ww - 2 * m), bool)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        A = V if dx == 0 else Hm
        c &= sum(sl(A, dy * k, dx * k) for k in range(a0, a1 + 1)) >= need
        c &= sum(sl(B, dy * k + dx * s_, dx * k + dy * s_) for k in range(a0, a1 + 1) for s_ in (-1, 1)) >= 2
    c &= (sum(sl(V, k, 0) for k in range(-2, 3)) <= 1) & (sum(sl(Hm, 0, k) for k in range(-2, 3)) <= 1)
    ys, xs = np.nonzero(c)
    return [(int(x + m), int(y + m)) for y, x in zip(ys, xs)]


def cursor_check(video, fps=5.0, t0=None, t1=None, name='take'):
    """(ok, text): no frame (sampled at fps) may show the mouse cursor. Prints the spans where it shows."""
    hits = []
    nfr = 0
    for t, f in iter_frames_full(video, fps, t0, t1):
        nfr += 1
        c = find_cursor(f)
        if not c:   # Kenshi's own cursor anywhere but the screen centre (there it is the FP crosshair)
            Hh, Ww = f.shape[:2]
            c = [(x, y, 0) for x, y in find_kcursor(f) if abs(x - Ww / 2) > KC_CENTRE or abs(y - Hh / 2) > KC_CENTRE]
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


# ---------------- foreign overlays: text / UI panels over the scene (class of the cursor miss, 2026-10-10) ----------------
# CLASS: anything drawn over the game scene that is not the take's own label/HUD: NPC speech bars, name tags ([Malzin]),
# damage numbers, hint/notification lists, dialog popups, stray debug strings (turret-fp.mp4 speech/name tag/damage,
# sword-z25-block-f36 [Malzin], anim-xbow-z25 hint list + [Axima]; mutation vid-popup-overlay = a flat grey dialog box).
OW, OH, CW, CH = 1600, 900, 16, 10            # analysis frame size and cell grid (100 x 90 cells)
OV_BASE_TEXT, OV_BASE_PANEL = None, 0.8       # panel cells in >= this share of frames = the take's own HUD (baseline);
#   text has no baseline (was 0.4): the 5090-operator's op-b1 blkG / op-probe takes show the [Axima] name tag in every
#   frame (KenshiFP picks the own character at the screen centre at zoom 25) and the baseline hid it (Misses 2026-10-10)
OV_ZONES = ((0.15, 0.0, 0.85, 0.20), (0.0, 0.70, 1.0, 1.0), (0.43, 0.505, 0.60, 0.565))   # + KenshiFP HUD text box
#   (kfp_controls.inc g_widget_setpos(vw/2-90, vh/2+20): LOADED / RELOAD n.n / NO POWER under the crosshair)   # x0 y0 x1 y1: centred title/state label band (down to
#   0.2 H: anim-sword-e6 "stroke 0"), Kenshi's bottom UI panel. The top corners (stray debug strings) stay checked.


def _ogrid(a):
    return a.reshape(OH // CH, CH, OW // CW, CW).transpose(0, 2, 1, 3).reshape(OH // CH, OW // CW, CH * CW)


def _strokes(m):
    """per cell: max over pixel rows of rising edges of mask m (glyph strokes; text has several per 16 px, an edge one)."""
    import numpy as np
    r = m[:, 1:] & ~m[:, :-1]
    r = np.concatenate([r, np.zeros((OH, 1), bool)], 1)
    return r.reshape(OH // CH, CH, OW // CW, CW).sum(3).max(1)


def text_cells(f):
    """(T, A, B) cell masks of text in a 1600x900 frame. B: outlined thin text floating over the scene (name tags, damage
    numbers): neutral-bright or red core pixels with a much darker pixel within 3 px on both sides; A: text on a flat dark
    panel (speech bars, hint lists, debug boxes): dark flat background + low-saturation brighter glyphs. Both need >= 3
    glyph strokes per cell."""
    import numpy as np
    g = f.mean(-1)
    mx, mn = f.max(-1), f.min(-1)
    spread = mx - mn
    core = ((mn >= 165) & (spread <= 35)) | ((f[..., 0] >= 190) & (f[..., 0] - f[..., 1] >= 90) & (f[..., 2] <= 130))

    def dk(dirs):
        m = np.zeros(g.shape, bool)
        for dy, dx in dirs:
            m |= np.roll(np.roll(g, dy, 0), dx, 1) <= g - 90
        return m
    thin = (dk([(0, -1), (0, -2), (0, -3)]) & dk([(0, 1), (0, 2), (0, 3)])) | (dk([(-1, 0), (-2, 0), (-3, 0)]) & dk([(1, 0), (2, 0), (3, 0)]))
    tc = core & thin
    B = (_ogrid(tc).sum(-1) >= 6) & (_strokes(tc) >= 3)
    G, S = _ogrid(g), _ogrid(spread)
    p20 = np.percentile(G, 20, axis=-1)
    p97 = np.percentile(G, 97, axis=-1)
    flat = (np.abs(G - p20[..., None]) <= 10).mean(-1)
    glyph = G > (p20[..., None] + 50)
    gs = np.where(glyph, S, 0).sum(-1) / np.maximum(glyph.sum(-1), 1)
    A = (p20 <= 35) & (flat >= 0.45) & (p97 - p20 >= 60) & (glyph.sum(-1) >= 6) & (gs <= 40)
    A &= _strokes(g > (np.repeat(np.repeat(p20, CH, 0), CW, 1) + 50)) >= 3
    return A | B, A, B


def flat_cells(f, std_max=3.0, sat_max=25):
    """(flat, cell mean grey): cells of a flat neutral fill (UI panel / dialog body / title bar): grey std <= std_max,
    mean colour spread <= sat_max."""
    G = _ogrid(f.mean(-1))
    return (G.std(-1) <= std_max) & (_ogrid(f.max(-1) - f.min(-1)).mean(-1) <= sat_max), G.mean(-1)


def panel_rects(F, M=None, min_w=6, min_h=4, tol=1, uni=2.0, step=15.0):
    """axis-aligned rectangles of flat cells (a UI panel has straight vertical edges): runs of >= min_w flat cells per
    cell row, not touching the frame's left/right edge (open sky / fog spans the width), stacked over >= min_h rows with
    the same start/end (+-tol). With the cell means M: the fill is one colour (std of the cell means <= uni; sky
    gradients, sand and armour vary) and both side edges are a step (mean |inside - outside| cell >= step).
    Returns [(x0, y0, x1, y1)] in cells (x1/y1 exclusive)."""
    import numpy as np
    nr, nc = F.shape
    runs = []
    for y in range(nr):
        x, rr = 0, []
        while x < nc:
            if F[y, x]:
                x0 = x
                while x < nc and F[y, x]:
                    x += 1
                if x - x0 >= min_w and x0 > 0 and x < nc:
                    rr.append((x0, x))
            else:
                x += 1
        runs.append(rr)
    out, used = [], set()
    for y in range(nr):
        for a, b in runs[y]:
            if (y, a) in used:
                continue
            y1 = y + 1
            while y1 < nr:
                m = [(c, d) for c, d in runs[y1] if abs(c - a) <= tol and abs(d - b) <= tol]
                if not m:
                    break
                used.add((y1, m[0][0])); y1 += 1
            if y1 - y >= min_h:
                if M is not None:
                    r = M[y:y1, a:b]
                    if r.std() > uni:
                        continue
                    if min(np.abs(M[y:y1, a] - M[y:y1, a - 1]).mean(), np.abs(M[y:y1, b - 1] - M[y:y1, b]).mean()) < step:
                        continue
                out.append((a, y, b, y1))
    return out


def zone_mask(zones):
    import numpy as np
    Z = np.zeros((OH // CH, OW // CW), bool)
    for x0, y0, x1, y1 in zones:
        Z[int(y0 * OH) // CH:-(-int(y1 * OH) // CH), int(x0 * OW) // CW:-(-int(x1 * OW) // CW)] = True
    return Z


def overlay_check(video, fps=2.0, t0=None, t1=None, zones=OV_ZONES, frames=None):
    """(ok, text): no foreign overlay in any sampled frame. A text line (>= 3 adjacent text cells in a cell row) or a
    flat UI panel (>= 12 cells) outside the expected zones and outside the take's baseline (its own HUD) = FAIL.
    `frames` = iterable of (t, 1600x900 frame) instead of reading the video (tests)."""
    import numpy as np
    if frames is None:
        frames = iter_frames_full(video, fps, t0, t1, size=(OW, OH))
    Z = zone_mask(zones)
    ts, TX, AX, PX = [], [], [], []
    for t, f in frames:
        T, A, _ = text_cells(f)
        P = np.zeros_like(T)
        for x0, y0, x1, y1 in panel_rects(*flat_cells(f)):
            P[y0:y1, x0:x1] = True
        ts.append(t); TX.append(T); AX.append(A); PX.append(P)
    if not ts:
        return False, 'no frames:BAD'
    TX, AX, PX = np.stack(TX), np.stack(AX), np.stack(PX)
    bt = TX.mean(0) >= OV_BASE_TEXT if OV_BASE_TEXT else np.zeros(TX.shape[1:], bool)
    bp = PX.mean(0) >= OV_BASE_PANEL
    hits = []
    for k, t in enumerate(ts):
        fo = TX[k] & ~bt & ~Z
        ln = fo[:, :-2] & fo[:, 1:-1] & fo[:, 2:]
        pa = PX[k] & ~bp & ~Z
        if ln.any() or pa.sum() >= 12:
            if ln.any():
                ys, xs = np.nonzero(ln)
                kind = 'text-panel' if (AX[k] & ~bt & ~Z)[ys, xs + 1].any() else 'text'
            else:
                ys, xs = np.nonzero(pa); kind = 'panel'
            hits.append((t, kind, int(xs.min()) * CW, int(ys.min()) * CH))
    spans = []
    for t, kind, x, y in hits:
        if spans and t - spans[-1][1] <= 1.5 / fps and spans[-1][2] == kind:
            spans[-1][1] = t
        else:
            spans.append([t, t, kind, x, y])
    txt = 'frames=%d overlay_frames=%d%s' % (len(ts), len(hits), ':BAD' if hits else '')
    if spans:
        txt += ' at=' + ','.join('%.1f-%.1fs(%s x%d,y%d)' % tuple(s) for s in spans[:10]) + ('...' if len(spans) > 10 else '')
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
    p = sp.add_parser('overlay'); p.add_argument('video'); p.add_argument('--fps', type=float, default=2.0)
    p.add_argument('--from', dest='t0', type=float); p.add_argument('--to', dest='t1', type=float)
    p.add_argument('--name', default='take')
    a = ap.parse_args()
    if a.cmd == 'overlay':
        ok, txt = overlay_check(a.video, a.fps, a.t0, a.t1)
        print('RESULT %s %s overlay %s' % (a.name, 'PASS' if ok else 'FAIL', txt))
        return 0 if ok else 1
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
