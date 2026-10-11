#!/usr/bin/env python3
"""autoreview.py -- automatic frame review: per-frame image checks on EVERY frame of a take video; the reviewer looks only at
the flagged frames (Shay 2026-10-10: judging sheets one at a time was slow and burned context).

  autoreview.py run <video> <out-dir> [--ev ev.txt] [--vmrec R] [--stamp S] [--offset S] [--weapon W] [--refs DIR]
                    [--name N] [--checks oneview,fragments,occluder,weapon,overlay,cursor,openground] [--no-crops]
  autoreview.py backfill <out-root> <video> [<video> ...] [--workers N] [--checks ...]   (one `run` per video)
  autoreview.py ref add <video> <weapon> [--ev ev.txt] [--offset S] [--states ready,aim,...] [--refs DIR]
  autoreview.py ref list [--refs DIR]
  autoreview.py selftest [--corpus DIR] [--workers N]   every corpus MANIFEST row of check `autoreview:<check>`

Sidecars next to the video are found by name: <stem>.ev.txt, <stem>.vmrec.txt, <stem>.stamp.txt (and ts.txt / vmrec*.txt in
the same dir when there is one video). Output in <out-dir>:
  flags.tsv      `frame  t  check  what  crop`: one row per flagged event (run of flagged frames of one check), t = video s
  crops/         <check>-<frame>.jpg: prev | FLAG (full resolution source) | next, flagged cells boxed red
  metrics.tsv    per frame: t, view, state, changed cells, foreground share (what the checks saw; for tuning)
  states.tsv     per frame state (review-pack.py takes its per-state samples from it)
  autoreview.txt one line per check + the RESULT line
Last stdout line: `RESULT <name>-autoreview PASS|FAIL flags=<n> <check>=<n> ... frames=<n> list=<flags.tsv>`
(FAIL = frames to look at; flags are review pointers, the reviewer judges them).

Frames: every encoded frame (VFR passthrough, presentation time from the packet pts: the recorder drops frames under load
and a constant-rate decode would duplicate a one-frame glitch into two), 256x144, judged on an 8 px cell grid over the
scene (13 rows = 0.72 H, down to Kenshi's bottom UI panel); harness sync-flash frames are dropped first.
View per frame (FP / band / 3P): --stamp (frame-stamp agent: `<frame> key=value ...` or `<t> key=value ...`, keys
zoom / band_hidden / on / view / st) or the take's fp_vm rec (zoom >= 1.5 dm or on=0 = 3P, band_hidden=1 = band) aligned to
the video by the offset that puts the rec's view changes on the video's frame changes. No view source = image-only mode.
Checks:
  oneview    exactly one view at each switch (2E66CB37 zoom sweeps: both / neither / misplaced single frames). Frames next
             to a cut (>= CUT changed cells) are flagged when (a) `both`: a cluster of >= TR_MIN cells shows content seen in
             neither neighbour while the neighbours agree there (stray 3P parts, floating viewmodel piece), or (b)
             `intermediate`: the cut is followed (preceded) by a second change of >= IM_MIN cells that settles at once
             (>= 2.5 x the next step): `neither` (empty frame, then the body) or `misplaced` (viewmodel elsewhere for one
             frame). Judged only within +-0.5 s of a view change when a view source exists; image-only it needs a quiet
             side (median change <= QUIET cells over the 4 frames before or after), so fast arm swings (fists) do not count.
  fragments  no stray body parts while the body is hidden (Z1 fade band: hat-brim shard + neck/shoulder slivers, 9C9ECB01
             5.90-6.47 s; C00ADF99 45.9 s): frames of a band span (view source) or of an image-only intermediate view
             (a quiet frame change, a static view < BAND_MAX s, a second frame change) may hold no floating object (not
             touching the frame sides/top) that was not in the last frame before the span. Object = luma far from the
             local background (|L - box blur 17 px| >= OBJ_DL).
  occluder   no arm / body part across the lens (FIST-badpunch: forearm across a third of the frame, ma_chudan hollow
             sleeve, ma_2strike torso armour on a kick): foreground vs the take plate (per-pixel median of the frames of a
             camera segment, each frame registered by phase correlation on the sky/horizon band, so FP head bob is
             followed) touching the frame edge covers more than OCC_MAX[weapon] of the scene. 3P hand-at-head stays the
             vmrec PT29 check (fp-viewmodel.sh VMQUICK).
  weapon     viewmodel weapon complete (crossbow without stock/body: 9C9ECB01 shay-xbow.png): the frame is compared with
             the references of its weapon + state (autoreview-refs/<weapon>/<state>/*.npz from `ref add` on accepted
             takes: foreground mask vs that take's plate + colours); a reference pixel counts as present when the frame
             shows foreground there or the reference colour (+-2 px shift, best reference = phase); flag when < WEAPON_MIN
             is present and the absent part is a block of >= 6 cells.
  overlay, cursor, openground: frames.py's checks (cached, not duplicated); their spans become flags.
Started at nice 15 by review-pack.py; backfill uses <= 16 workers.
"""
import argparse, glob, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

W, H, CS = 256, 144, 8
SR = 13                       # scene cell rows: 13 x 8 px = 104 px = 0.72 H (Kenshi's bottom UI panel starts at 0.70 H, its
#                               static top edge never changes; a viewmodel low behind the HUD, zsxbs-off 30.50 s, is seen)
NC = W // CS                  # 32 cell columns
T_CELL = 12.0                 # mean abs RGB difference for a changed cell
CUT = 60                      # changed cells (of 416) for a cut
TR_MIN = 5                    # transient cluster cells for `both`
IM_MIN = 8                    # second change for `intermediate`
QUIET = 6                     # image-only: median changed cells on the quiet side of a judged cut
EV_MIN = 12                   # changed cells for a view event in a quiet scene (image-only fragments)
BAND_MAX = 1.5                # s
PRE_DIL = 2                   # px (256x144): last pre-band objects grown by this before "new" is judged
BAND_MIN = 0.25               # s: image-only band at least this long (fade band 0.4-0.9 s; a 4-frame viewmodel jitter, 2E66 27.87 s, is not one)
LESS = 0.8                    # image-only band: central objects during <= LESS x min(before, after)
OBJ_DL = 45
FRAG_MIN = 40                 # new floating object px (256x144) for a fragment flag
FG_T = 34                     # plate foreground: max abs RGB difference
OCC_MAX = {'fists': 0.15, 'sword': 0.12, 'crossbow': 0.15, None: 0.15}   # accepted sword/xbow takes p99 0.05-0.10; fist arm-across 0.15-0.25
WEAPON_MIN = 0.70
ZFP = 1.5                     # dm: rec zoom at or above = 3P / band
HUDBOX = (0.43, 0.505, 0.60, 0.565)   # KenshiFP HUD text box (frames.OV_ZONES)
REFS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'autoreview-refs')


# ================================================================ decode
def probe_pts(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time',
                          '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.split()
    return sorted(float(x.strip(',')) for x in out if x.strip(',') not in ('', 'N/A'))


def load(video, w=W, h=H):
    """(frames uint8 (N,h,w,3), t (N,) s from the first frame): every encoded frame (passthrough). An image = 1 frame.
    Passthrough decode (framecache.frames resamples to a constant fps, which duplicates dropped-frame gaps) with
    framecache's NVDEC args. Not stored on disk: 256x144 x every frame is ~110 KB/frame (220 MB for a 70 s take, slower to
    write to /mnt/c than to decode again); the take's other checks share framecache's own caches."""
    import numpy as np
    if video.lower().endswith(('.png', '.jpg', '.jpeg')):
        from PIL import Image
        im = np.asarray(Image.open(video).convert('RGB').resize((w, h), Image.BILINEAR))
        return im[None].copy(), np.zeros(1)
    try:
        import framecache as fc
        hw = fc.hwdec()
    except ImportError:
        hw = []
    return _decode(video, w, h, hw)


def _decode(video, w, h, hw):
    import numpy as np
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error'] + hw + ['-i', video, '-vf', 'scale=%d:%d' % (w, h),
                                                              '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    r = subprocess.run(cmd, capture_output=True)
    if hw and (r.returncode or not r.stdout):   # NVDEC refused: software decode
        r = subprocess.run([c for c in cmd if c not in hw], capture_output=True)
    raw = r.stdout
    F = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    T = probe_pts(video)
    if len(T) < len(F):
        base = T[-1] if T else 0.0
        T = list(T) + [base + (k + 1) / 30.0 for k in range(len(F) - len(T))]
    t = np.array(T[:len(F)], float)
    return F, (t - t[0]) if len(t) else t


def full_frame(video, t):
    import numpy as np
    if video.lower().endswith(('.png', '.jpg', '.jpeg')):
        from PIL import Image
        return np.asarray(Image.open(video).convert('RGB'))
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                         '-of', 'csv=p=0', video], capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(pr[0]), int(pr[1])
    raw = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-ss', '%.3f' % max(0.0, t), '-i', video,
                          '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    if len(raw) < w * h * 3:
        return None
    return np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3)


def is_flash(f):
    r, g, b = f[..., 0].astype(int), f[..., 1].astype(int), f[..., 2].astype(int)
    return float(((r > 170) & (b > 170) & (g < 90)).mean()) >= 0.85


# ================================================================ grid helpers
def hud_cells():
    import numpy as np
    m = np.zeros((SR, NC), bool)
    x0, y0, x1, y1 = HUDBOX
    m[int(y0 * H) // CS:-(-int(y1 * H) // CS), int(x0 * W) // CS:-(-int(x1 * W) // CS)] = True
    return m


def cdiff(a, b):
    import numpy as np
    d = np.abs(a[:SR * CS].astype(np.int16) - b[:SR * CS].astype(np.int16)).mean(2)
    return d.reshape(SR, CS, NC, CS).mean((1, 3))


def clusters(m):
    """4-connected components of a small bool grid -> [(size, [(r, c), ...])], biggest first."""
    seen = set(); out = []
    R, C = m.shape
    for r in range(R):
        for c in range(C):
            if m[r, c] and (r, c) not in seen:
                st = [(r, c)]; seen.add((r, c)); cells = []
                while st:
                    y, x = st.pop(); cells.append((y, x))
                    for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= yy < R and 0 <= xx < C and m[yy, xx] and (yy, xx) not in seen:
                            seen.add((yy, xx)); st.append((yy, xx))
                out.append((len(cells), cells))
    out.sort(key=lambda s: -s[0])
    return out


def bbox(cells):
    ys = [c[0] for c in cells]; xs = [c[1] for c in cells]
    return (min(xs) * CS, min(ys) * CS, (max(xs) + 1) * CS, (max(ys) + 1) * CS)


def cl_mask(cl):
    import numpy as np
    m = np.zeros((SR * CS, W), bool)
    for _, cells in cl:
        for y, x in cells:
            m[y * CS:(y + 1) * CS, x * CS:(x + 1) * CS] = True
    return m


def dilate(m, r):
    out = m.copy()
    import numpy as np
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def step_counts(F):
    """cnt[i] = changed scene cells between frame i-1 and i (HUD text box ignored); steps[i] = the cell mask."""
    hb = hud_cells()
    cnt = [0]; steps = [None]
    for i in range(1, len(F)):
        d = cdiff(F[i], F[i - 1]); d[hb] = 0
        s = d > T_CELL
        steps.append(s); cnt.append(int(s.sum()))
    return cnt, steps


# ================================================================ view / state sources
def read_vmrec(path):
    """[(t, st, view)] from an fp_vm rec dump (columns n t dt st ti cls on ... zoom(16) | ... band_hidden(last))."""
    rows = []
    band_col = False
    for line in open(path, errors='replace'):
        if line.startswith('#'):
            band_col = band_col or 'band_hidden' in line
            continue
        p = line.split()
        if len(p) < 17:
            continue
        try:
            t, on, zoom = float(p[1]), p[6], float(p[16])
        except ValueError:
            continue
        band = band_col and p[-1] == '1'
        view = 'band' if band else ('3p' if (on == '0' or zoom >= ZFP) else 'fp')
        rows.append((t, p[3], view))
    return rows


def read_stamp(path):
    """[(key, byframe, kv)] from a frame-stamp file."""
    rows = []
    for line in open(path, errors='replace'):
        m = re.match(r'^\s*(f?)(\d+(?:\.\d+)?)\s+(.*)$', line)
        if not m:
            continue
        kv = dict(re.findall(r'(\w+)=(\S+)', m.group(3)))
        if kv:
            rows.append((float(m.group(2)), m.group(1) == 'f' or '.' not in m.group(2), kv))
    return rows


def stamp_view(kv):
    if 'view' in kv:
        return kv['view'].lower()
    if kv.get('band_hidden') == '1':
        return 'band'
    if 'zoom' in kv or 'on' in kv:
        try:
            return '3p' if (kv.get('on') == '0' or float(kv.get('zoom', 0)) >= ZFP) else 'fp'
        except ValueError:
            return None
    return None


def align(ev_times, cnt, t, lo=-6.0, hi=6.0):
    """offset (video t = rec t + offset) that puts the rec's view changes on the video's biggest frame changes."""
    import numpy as np
    if not ev_times or len(t) < 3:
        return None, 0.0
    c = np.array(cnt, float)
    best = (None, -1.0)
    for o in np.arange(lo, hi, 1.0 / 60):
        s = 0.0
        for e in ev_times:
            j = np.searchsorted(t, e + o)
            s += c[max(0, j - 2):j + 2].max() if j - 2 < len(c) else 0.0
        if s > best[1]:
            best = (float(o), s)
    return best[0], best[1] / len(ev_times)


def frame_views(t, cnt, stamp=None, vmrec=None):
    """per frame view ('fp'/'band'/'3p'/None), per frame rec state, list of view-change times, source text."""
    n = len(t)
    views = [None] * n; sts = [None] * n
    if stamp and os.path.exists(stamp):
        rows = read_stamp(stamp)
        if rows:
            byframe = all(r[1] for r in rows)
            j = 0
            for i in range(n):
                key = i if byframe else t[i]
                while j + 1 < len(rows) and rows[j + 1][0] <= key + 1e-6:
                    j += 1
                if rows[j][0] <= key + 1e-6:
                    kv = rows[j][2]
                    views[i] = stamp_view(kv); sts[i] = kv.get('st') or kv.get('ui_state')
            ch = [t[i] for i in range(1, n) if views[i] and views[i - 1] and views[i] != views[i - 1]]
            return views, sts, ch, 'stamp'
    if vmrec and os.path.exists(vmrec):
        rows = read_vmrec(vmrec)
        if rows:
            ev = [rows[k][0] for k in range(1, len(rows)) if rows[k][2] != rows[k - 1][2]]
            if not ev:
                for i in range(n):
                    views[i] = rows[0][2]
                return views, sts, [], 'vmrec(no view change)'
            off, sc = align(ev, cnt, t)
            if off is None or sc < 15:
                return views, sts, [], 'vmrec(no alignment, score %.0f)' % sc
            j = 0
            for i in range(n):
                tr = t[i] - off
                while j + 1 < len(rows) and rows[j + 1][0] <= tr:
                    j += 1
                if rows[j][0] <= tr + 0.05:
                    views[i] = rows[j][2]; sts[i] = rows[j][1]
            return views, sts, [e + off for e in ev], 'vmrec(offset %+.2f s, score %.0f)' % (off, sc)
    return views, sts, None, 'image-only'


def ev_states(t, ev, offset=None, video=None):
    """per frame ui_state from the ev log `fp ui_state=` samples (+ offset / sync flashes)."""
    n = len(t)
    out = [None] * n
    if not ev or not os.path.exists(ev):
        return out, None
    off = offset if offset is not None else sync_offset(ev, video)
    smp = []
    for line in open(ev, errors='replace'):
        m = re.match(r'^\s*([\d.]+)\s+fp\s+(.*)$', line)
        if m:
            kv = dict(re.findall(r'(\w+)=(\S+)', m.group(2)))
            s = kv.get('ui_state') or kv.get('fp_ui_state')
            if s:
                smp.append((float(m.group(1)) + off, s))
    smp.sort()
    j = 0
    for i in range(n):
        while j + 1 < len(smp) and smp[j + 1][0] <= t[i]:
            j += 1
        if smp and smp[j][0] <= t[i] + 0.3:
            out[i] = smp[j][1]
    return out, off


def sync_offset(ev, video):
    """video time of the first sync flash - ev time of the first `sync=` mark (0 when either is missing)."""
    evm = []
    for line in open(ev, errors='replace'):
        m = re.match(r'^\s*([\d.]+)\s+.*\bsync=(\d+)', line)
        if m:
            evm.append(float(m.group(1)))
    if not evm or not video:
        return 0.0
    try:
        import frames
        marks = frames.syncmarks(video)
    except Exception:
        return 0.0
    return (marks[0] - evm[0]) if marks else 0.0


# ================================================================ check: oneview
def check_oneview(F, t, cnt, steps, windows):
    """windows: list of (t0, t1) to judge (view source) or None = image-only (quiet-side rule)."""
    import numpy as np
    hb = hud_cells()
    n = len(F)
    flags = []

    def quiet(a, b):
        v = sorted(cnt[max(1, a):max(1, b)])
        return bool(v) and v[len(v) // 2] <= QUIET

    for g in range(1, n - 1):
        ga, gb = cnt[g], cnt[g + 1]
        if max(ga, gb) < CUT:
            continue
        if windows is not None:
            if not any(a - 0.5 <= t[g] <= b + 0.5 for a, b in windows):
                continue
        elif not (quiet(g - 4, g) or quiet(g + 2, g + 6)):
            continue
        Dab = cdiff(F[g - 1], F[g + 1]); Dab[hb] = 0
        tr = steps[g] & steps[g + 1] & (Dab < T_CELL / 2)
        cl = clusters(tr)
        if cl and cl[0][0] >= TR_MIN:
            flags.append((g, 'both: %d cells in neither neighbour (cut %d/%d)' % (cl[0][0], ga, gb), cl[0][1]))
            continue
        if ga >= CUT and ga >= gb:
            nxt = cnt[g + 2] if g + 2 < n else 0
            if gb >= IM_MIN and gb >= 2.5 * max(nxt, 3):
                flags.append((g, 'intermediate: cut %d, then %d cells change at once and settle (%d)' % (ga, gb, nxt),
                              [tuple(c) for c in np.argwhere(steps[g + 1])]))
        elif gb >= CUT:
            prv = cnt[g - 1] if g >= 2 else 0
            if ga >= IM_MIN and ga >= 2.5 * max(prv, 3):
                flags.append((g, 'intermediate: %d cells changed once (before: %d), then cut %d' % (ga, prv, gb),
                              [tuple(c) for c in np.argwhere(steps[g])]))
    return flags


# ================================================================ check: fragments
def objects(f):
    import numpy as np
    L = f[:SR * CS].astype(np.float32).mean(2)
    k = 17
    c = np.pad(np.pad(L, k // 2, mode='edge').cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    bl = (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    return np.abs(L - bl) >= OBJ_DL


def band_spans(t, cnt, views, objc=None):
    """(first, end) frame spans of the body-hidden band: from the view source, or image-only intermediate views."""
    n = len(t)
    spans = []
    if any(v is not None for v in views):
        i = 0
        while i < n:
            if views[i] == 'band':
                j = i
                while j + 1 < n and views[j + 1] == 'band':
                    j += 1
                e = j + 1
                while e < n and t[e] - t[j] <= 0.3 and cnt[e] < EV_MIN:   # the body appears a frame or two late
                    e += 1
                spans.append((i, min(e, n)))
                i = j + 1
            else:
                i += 1
        return spans, 'view source'
    # image-only: a band view is an intermediate view that shows LESS than both views around it (the viewmodel went, the
    # body is not there yet: 9C9ECB01 5.87-6.47 s central objects 426 -> 164..330 -> 655). Events = a frame change of
    # >= EV_MIN cells after a quiet stretch; events <= 2 frames apart are one event (a fade over two frames). The view
    # between two events may drift a little (slow ease-out tail: median <= QUIET, max <= 2 x EV_MIN changed cells).
    # A plain FP <-> 3P cut followed by a swing or a walk is not a band: the view after the cut shows as much as before.
    if objc is None:
        return spans, 'image-only (no frames)'
    cl = []                                   # runs of changing frames (gaps <= 2 frames merged)
    for i in range(1, n):
        if cnt[i] >= EV_MIN:
            if cl and i - cl[-1][1] <= 2:
                cl[-1] = (cl[-1][0], i)
            else:
                cl.append((i, i))
    ev = []                                   # view events: short runs (<= 3 frames) after a quiet stretch; a swing or a
    for a0, a1 in cl:                         # walk is a long run of changes, not a view switch (9C9ECB01 42.90 s)
        q = sorted(cnt[max(1, a0 - 3):a0])
        if a1 - a0 <= 2 and (not q or q[len(q) // 2] <= 4):
            ev.append((a0, a1))
    for (a0, a), (b, _) in zip(ev, ev[1:]):
        mid = sorted(cnt[a + 1:b])
        if b - a < 2 or t[b] - t[a] > BAND_MAX or mid[len(mid) // 2] > QUIET or mid[-1] > 2 * EV_MIN:
            continue
        before = objc[max(0, a0 - 1)]; after = objc[min(n - 1, b + 1)]
        during = sorted(objc[a:b])[(b - a) // 2]
        if os.environ.get("AR_DEBUG"): print("span", round(t[a], 2), round(t[b], 2), "cnt a,b", cnt[a0:a1 + 1] if False else cnt[a], cnt[b], "objc", before, during, after, file=sys.stderr)
        if during <= LESS * min(before, after) and t[b] - t[a] >= BAND_MIN:   # shorter = oneview's single-frame glitches
            spans.append((a, b))
    return spans, 'image-only'


def check_fragments(F, t, cnt, views):
    import numpy as np
    objc = [int(objects(f)[:, NC * CS // 4:3 * NC * CS // 4].sum()) for f in F] if not any(v is not None for v in views) else None
    spans, how = band_spans(t, cnt, views, objc)
    hudpx = np.zeros((SR * CS, W), bool)
    x0, y0, x1, y1 = HUDBOX
    hudpx[int(y0 * H):int(y1 * H) + 1, int(x0 * W):int(x1 * W) + 1] = True
    hudpx[:int(0.05 * H)] = True
    flags = []
    for a, b in spans:
        pre = dilate(objects(F[max(0, a - 1)]), PRE_DIL)   # a viewmodel that shifts a few px is not new (2E66 27.87 s)
        for i in range(a, b):
            new = objects(F[i]) & ~pre & ~hudpx
            cm = new.reshape(SR, CS, NC, CS).sum((1, 3)) >= 6
            cl = [c for c in clusters(cm) if not any(y == 0 or x == 0 or x == NC - 1 for y, x in c[1])]   # floating only
            npx = int((new & cl_mask(cl)).sum())
            if npx >= FRAG_MIN and cl and cl[0][0] >= 2:
                flags.append((i, 'fragments: %d px of floating objects while the body is hidden (%.2f-%.2f s, %s)' % (
                    npx, t[a], t[b - 1], how), [c for s in cl[:3] for c in s[1]]))
    return flags, [(round(float(t[a]), 2), round(float(t[b - 1]), 2)) for a, b in spans], how


# ================================================================ plates (camera segments, registered)
def band_luma(f):
    import numpy as np
    return f[4:64].astype(np.float32).mean(2)


def shift_of(a, b, win):
    """integer (dy, dx) with b ~ a shifted by (dy, dx) (phase correlation on the sky/horizon band)."""
    import numpy as np
    A = np.fft.fft2((a - a.mean()) * win); B = np.fft.fft2((b - b.mean()) * win)
    R = B * np.conj(A); R /= np.abs(R) + 1e-6
    r = np.fft.ifft2(R).real
    dy, dx = np.unravel_index(int(r.argmax()), r.shape)
    if dy > r.shape[0] // 2: dy -= r.shape[0]
    if dx > r.shape[1] // 2: dx -= r.shape[1]
    return int(dy), int(dx)


def shifted(img, dy, dx):
    import numpy as np
    return np.roll(np.roll(img, dy, 0), dx, 1)


def segments(F, maxshift=14, maxres=5.0, minlen=30):
    """camera segments: [(a, b, ref, shifts)] where every frame of a..b-1 registers on frame ref within maxshift px with a
    band residual <= maxres (median abs luma diff after the shift); shifts[i - a] = (dy, dx)."""
    import numpy as np
    n = len(F)
    if n == 0:
        return []
    win = np.outer(np.hanning(60), np.hanning(W)).astype(np.float32)
    segs = []
    a = 0; ref = band_luma(F[0]); sh = [(0, 0)]
    for i in range(1, n + 1):
        ok = False
        if i < n:
            b = band_luma(F[i])
            dy, dx = shift_of(ref, b, win)
            if abs(dy) <= maxshift and abs(dx) <= maxshift:
                res = float(np.percentile(np.abs(shifted(ref, dy, dx) - b)[maxshift:-maxshift, maxshift:-maxshift], 30))   # p30: an arm over most of the band still registers
                ok = res <= maxres
        if ok:
            sh.append((dy, dx)); continue
        if i - a >= minlen:
            segs.append((a, i, a, sh))
        if i < n:
            a = i; ref = band_luma(F[i]); sh = [(0, 0)]
    return segs


def still_plate(F, plate_path):
    """a still (screenshot) has no camera segment: its plate is a screenshot of the same spot without the viewmodel
    (e.g. XBMESH xbm-C-holstered.png), registered on the still by phase correlation on the sky/horizon band."""
    import numpy as np
    P = load(plate_path)[0][0].astype(np.int16)
    win = np.outer(np.hanning(60), np.hanning(W)).astype(np.float32)
    dy, dx = shift_of(band_luma(P), band_luma(F[0]), win)
    return [(0, 1, 0, [(dy, dx)])], [P]


def plate_of(F, seg, k=61):
    """per-pixel median of up to k registered frames of the segment, in the reference frame's coordinates."""
    import numpy as np
    a, b, _, sh = seg
    idx = np.linspace(a, b - 1, min(k, b - a)).astype(int)
    st = np.stack([shifted(F[i].astype(np.int16), -sh[i - a][0], -sh[i - a][1]) for i in idx])
    return np.median(st, axis=0).astype(np.int16)


def fg_of(f, plate, dy, dx, border=14):
    import numpy as np
    d = np.abs(f.astype(np.int16) - shifted(plate, dy, dx)).max(2) >= FG_T
    d[:, :border] = False; d[:, -border:] = False
    if dy > 0: d[:dy] = False
    if dy < 0: d[dy:] = False
    return d


# ================================================================ check: occluder
def check_occluder(F, t, segs, plates, views, weapon):
    import numpy as np
    flags = []
    occ = OCC_MAX.get(weapon, OCC_MAX[None])
    share_of = {}
    for s, P in zip(segs, plates):
        a, b, _, sh = s
        for i in range(a, b):
            if views[i] in ('3p', 'band'):
                continue
            fg = fg_of(F[i], P, *sh[i - a])[:SR * CS]
            cm = fg.reshape(SR, CS, NC, CS).mean((1, 3)) >= 0.5
            edge = np.zeros_like(cm); edge[0, :] = edge[-1, :] = True; edge[:, :2] = edge[:, -2:] = True
            cl = [c for c in clusters(cm) if any(edge[y, x] for y, x in c[1])]
            share = sum(c[0] for c in cl) / float(cm.size)
            share_of[i] = share
            if share > occ:
                flags.append((i, 'occluder: edge-connected foreground covers %.0f%% of the scene (max %.0f%%)' % (100 * share, 100 * occ),
                              [c for s_ in cl for c in s_[1]]))
    return flags, share_of


# ================================================================ check: weapon (references)
def load_refs(refs, weapon):
    import numpy as np
    lib = {}
    root = os.path.join(refs, weapon or '-')
    if not os.path.isdir(root):
        return lib
    for st in os.listdir(root):
        R = []
        for p in sorted(glob.glob(os.path.join(root, st, '*.npz'))):
            z = np.load(p)
            R.append((z['mask'], z['rgb'].astype(np.int16), os.path.basename(p)))
        if R:
            lib[st] = R
    return lib


def weapon_score(f16, fg, lib_st):
    import numpy as np  # noqa: F401
    best = (-1.0, None, None)
    for mask, rgb, name in lib_st:
        nm = int(mask.sum())
        if nm < 40:
            continue
        for dy in (-2, 0, 2):
            for dx in (-2, 0, 2):
                m2 = shifted(mask, dy, dx); r2 = shifted(rgb, dy, dx)
                pres = np.abs(f16 - r2).max(2) <= 40
                if fg is not None:
                    pres |= fg
                sc = float((pres & m2).sum()) / nm
                if sc > best[0]:
                    best = (sc, name, m2 & ~pres)
    return best


def check_weapon(F, t, segs, plates, views, sts, weapon, refs):
    import numpy as np
    lib = load_refs(refs, weapon)
    if not lib:
        return [], 'no references for %s' % weapon
    seg_of = {}
    for s, P in zip(segs, plates):
        for i in range(s[0], s[1]):
            seg_of[i] = (P, s[3][i - s[0]])
    flags = []
    n_scored = 0
    for i in range(len(F)):
        st = sts[i] or ('ready' if len(F) == 1 else None)
        if st not in lib or views[i] in ('3p', 'band') or (len(F) > 1 and i % 2):
            continue
        fg = None
        if i in seg_of:
            P, (dy, dx) = seg_of[i]
            fg = fg_of(F[i], P, dy, dx)
        sc, name, miss = weapon_score(F[i].astype(np.int16), fg, lib[st])
        n_scored += 1
        if name is None or sc >= WEAPON_MIN:
            continue
        cm = miss[:SR * CS].reshape(SR, CS, NC, CS).mean((1, 3)) >= 0.4
        cl = clusters(cm)
        if cl and cl[0][0] >= 6:
            flags.append((i, 'weapon: %.0f%% of the %s %s reference (%s) present, missing block %d cells' % (
                100 * sc, weapon, st, name, cl[0][0]), cl[0][1]))
    return flags, 'scored %d frames, states %s' % (n_scored, ','.join(sorted(lib)))


def ref_add(video, weapon, refs, ev=None, offset=None, stamp=None, vmrec=None, states_keep=None, every=0.5, plate=None):
    """store reference frames (foreground mask vs the take plate + colours) per state of an accepted take."""
    import numpy as np
    F, t = load(video)
    keep = [i for i in range(len(F)) if not is_flash(F[i])]
    F, t = F[keep], t[keep]
    cnt, _ = step_counts(F)
    stamp, vmrec, ev = sidecars(video, stamp, vmrec, ev)
    views, sts, _, src = frame_views(t, cnt, stamp, vmrec)
    es, _ = ev_states(t, ev, offset, video)
    sts = [es[i] or sts[i] for i in range(len(F))]
    if len(F) == 1:                       # a still: --plate (same spot, no viewmodel) + --states <its state>
        if not (plate and states_keep):
            print('ref add: a still needs --plate <image> and --states <state>'); return 0
        sts = [states_keep[0]]; segs, plates = still_plate(F, plate)
    else:
        segs = segments(F); plates = [plate_of(F, s) for s in segs]
    n = 0; last = {}
    for s, P in zip(segs, plates):
        a, b, _, sh = s
        for i in range(a, b):
            st = sts[i]
            if not st or views[i] in ('3p', 'band') or (states_keep and st not in states_keep) or t[i] - last.get(st, -9) < every:
                continue
            m = fg_of(F[i], P, *sh[i - a]); m[SR * CS:] = False
            if m.sum() < 60:
                continue
            last[st] = t[i]
            d = os.path.join(refs, weapon, st); os.makedirs(d, exist_ok=True)
            nm = '%s-%06.2f.npz' % (re.sub(r'\W+', '_', os.path.splitext(os.path.basename(video))[0]), t[i])
            np.savez_compressed(os.path.join(d, nm), mask=m, rgb=F[i])
            n += 1
    print('ref add: %d reference frames (%s) states=%s view=%s' % (n, weapon, ','.join(sorted(last)), src))
    return n


# ================================================================ reused frames.py checks
def reused_flags(video, t, which):
    out = []; info = {}
    try:
        import frames
    except Exception as e:
        return [], {'frames.py': 'import error %s' % e}
    for name in which:
        try:
            ok, txt = {'overlay': frames.overlay_check, 'cursor': frames.cursor_check,
                       'openground': frames.openground_check}[name](video)
        except Exception as e:
            info[name] = 'error %s' % e; continue
        info[name] = txt
        for a, b, rest in re.findall(r'([\d.]+)-([\d.]+)s\(([^)]*)\)', txt):
            i = int(abs(t - float(a)).argmin()) if len(t) else 0
            out.append((i, '%s: %s-%s s %s' % (name, a, b, rest), [], name))
    return out, info


# ================================================================ output
def write_crop(video, F, t, i, cells, path):
    from PIL import Image, ImageDraw
    tiles = []
    for j in (i - 1, i, i + 1):
        if not 0 <= j < len(F):
            continue
        ff = full_frame(video, t[j]) if j == i else None
        im = Image.fromarray(ff) if ff is not None else Image.fromarray(F[j])
        im = im.resize((640, 360), Image.BILINEAR)
        d = ImageDraw.Draw(im)
        if j == i and cells:
            x0, y0, x1, y1 = bbox(cells)
            s = 640.0 / W
            d.rectangle([x0 * s - 2, y0 * s - 2, x1 * s + 2, y1 * s + 2], outline=(255, 0, 0), width=3)
        d.rectangle([0, 0, 200, 16], fill=(0, 0, 0))
        d.text((4, 3), '%s %.3f s f%d' % ('FLAG' if j == i else ('prev' if j < i else 'next'), t[j], j), fill=(255, 255, 0))
        tiles.append(im)
    out = Image.new('RGB', (644 * len(tiles) - 4, 360))
    for k, im in enumerate(tiles):
        out.paste(im, (k * 644, 0))
    out.save(path, quality=85)


def merge(flags, t, gap=0.25):
    ev = []
    for i, what, cells, check in sorted(flags, key=lambda f: (f[3], f[0])):
        if ev and ev[-1]['check'] == check and t[i] - t[ev[-1]['last']] <= gap:
            ev[-1]['last'] = i; ev[-1]['n'] += 1
            continue
        ev.append(dict(check=check, first=i, last=i, n=1, what=what, cells=cells))
    ev.sort(key=lambda e: e['first'])
    return ev


def sidecars(video, stamp=None, vmrec=None, ev=None):
    d, stem = os.path.dirname(os.path.abspath(video)), os.path.splitext(os.path.basename(video))[0]
    def pick(given, names):
        if given:
            return given
        for nm in names:
            p = os.path.join(d, nm)
            if os.path.exists(p):
                return p
        return None
    stamp = pick(stamp, [stem + '.stamp.txt', stem + '.stamp'])
    vmrec = pick(vmrec, [stem + '.vmrec.txt'])
    ev = pick(ev, [stem + '.ev.txt'])
    if len(glob.glob(os.path.join(d, '*.mp4'))) == 1:
        ev = ev or pick(None, ['ts.txt', 'ev.txt'])
        if not vmrec:
            v = glob.glob(os.path.join(d, 'vmrec*.txt'))
            vmrec = v[0] if len(v) == 1 else None
    return stamp, vmrec, ev


def guess_weapon(video):
    b = os.path.basename(video).lower()
    return ('crossbow' if ('xbow' in b or 'crossbow' in b) else 'fists' if 'fist' in b else
            'sword' if ('sword' in b or 'e6' in b or 'katana' in b) else None)


ALL = ('oneview', 'fragments', 'occluder', 'weapon', 'overlay', 'cursor', 'openground')


def run(video, out, ev=None, vmrec=None, stamp=None, offset=None, weapon=None, refs=REFS, name=None, checks=ALL, crops=True,
        plate=None, state=None):
    import numpy as np
    name = name or os.path.splitext(os.path.basename(video))[0]
    os.makedirs(out, exist_ok=True)
    F, t = load(video)
    keep = [i for i in range(len(F)) if not is_flash(F[i])]
    F, t = F[keep], t[keep]
    weapon = guess_weapon(video) if weapon in (None, 'auto') else weapon
    stamp, vmrec, ev = sidecars(video, stamp, vmrec, ev)
    cnt, steps = step_counts(F)
    views, sts, changes, vsrc = frame_views(t, cnt, stamp, vmrec)
    es, eoff = ev_states(t, ev, offset, video)
    sts = [es[i] or sts[i] or state for i in range(len(F))]
    lines = ['video %s frames=%d length=%.2f s view=%s states=%s weapon=%s' % (
        video, len(F), t[-1] if len(t) else 0, vsrc, ('ev offset %.2f' % eoff) if eoff is not None else 'rec' if any(sts) else 'none', weapon)]
    allf = []
    if 'oneview' in checks and len(F) > 3:
        if changes is not None and not changes:
            lines.append('oneview: no view change in the take (%s)' % vsrc)
        else:
            win = None if changes is None else [(c, c) for c in changes]
            fl = check_oneview(F, t, cnt, steps, win)
            allf += [(i, w, c, 'oneview') for i, w, c in fl]
            lines.append('oneview: %s, cuts=%d, flags=%d' % ('image-only (quiet side)' if win is None else '%d view changes' % len(win),
                                                             sum(1 for c in cnt if c >= CUT), len(fl)))
    if 'fragments' in checks and len(F) > 3:
        fl, spans, how = check_fragments(F, t, cnt, views)
        allf += [(i, w, c, 'fragments') for i, w, c in fl]
        lines.append('fragments: band spans (%s) %s%s flags=%d' % (how, spans[:10], '...' if len(spans) > 10 else '', len(fl)))
    segs = segments(F) if len(F) > 1 and ('occluder' in checks or 'weapon' in checks) else []
    plates = [plate_of(F, s) for s in segs]
    if len(F) == 1 and plate:
        segs, plates = still_plate(F, plate)
    share = {}
    if 'occluder' in checks:
        fl, share = check_occluder(F, t, segs, plates, views, weapon)
        allf += [(i, w, c, 'occluder') for i, w, c in fl]
        cov = sum(s[1] - s[0] for s in segs)
        lines.append('occluder: camera segments %d covering %d/%d frames, flags=%d' % (len(segs), cov, len(F), len(fl)))
    if 'weapon' in checks:
        fl, info = check_weapon(F, t, segs, plates, views, sts, weapon, refs)
        allf += [(i, w, c, 'weapon') for i, w, c in fl]
        lines.append('weapon: %s, flags=%d' % (info, len(fl)))
    reuse = [c for c in ('overlay', 'cursor', 'openground') if c in checks]
    if reuse and len(F) > 1:
        fl, info = reused_flags(video, t, reuse)
        allf += fl
        for k, v in info.items():
            lines.append('%s (frames.py): %s' % (k, v))
    events = merge(allf, t)
    rows = ['frame\tt\tcheck\twhat\tcrop']
    if crops and events:
        os.makedirs(os.path.join(out, 'crops'), exist_ok=True)
    for e in events:
        crop = ''
        if crops:
            crop = os.path.join(out, 'crops', '%s-%05d.jpg' % (e['check'], e['first']))
            try:
                write_crop(video, F, t, e['first'], e['cells'], crop)
            except Exception as ex:
                crop = 'crop-error:%s' % ex
        span = '' if e['first'] == e['last'] else ' (to %.3f s, %d frames)' % (t[e['last']], e['n'])
        rows.append('%d\t%.3f\t%s\t%s%s\t%s' % (e['first'], t[e['first']], e['check'], e['what'], span, crop))
    open(os.path.join(out, 'flags.tsv'), 'w').write('\n'.join(rows) + '\n')
    with open(os.path.join(out, 'states.tsv'), 'w') as f:
        f.write('frame\tt\tstate\tview\n')
        for i in range(len(F)):
            f.write('%d\t%.3f\t%s\t%s\n' % (i, t[i], sts[i] or '-', views[i] or '-'))
    with open(os.path.join(out, 'metrics.tsv'), 'w') as f:
        f.write('frame\tt\tview\tstate\tchanged\tfg_edge_share\n')
        for i in range(len(F)):
            f.write('%d\t%.3f\t%s\t%s\t%d\t%s\n' % (i, t[i], views[i] or '-', sts[i] or '-', cnt[i] if i < len(cnt) else 0,
                                                  '%.3f' % share[i] if i in share else '-'))
    per = {}
    for e in events:
        per[e['check']] = per.get(e['check'], 0) + 1
    res = 'RESULT %s-autoreview %s flags=%d %sframes=%d list=%s' % (
        name, 'FAIL' if events else 'PASS', len(events), ''.join('%s=%d ' % kv for kv in sorted(per.items())), len(F),
        os.path.join(out, 'flags.tsv'))
    lines.append(res)
    open(os.path.join(out, 'autoreview.txt'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return events, t


# ================================================================ backfill / selftest
def _one(args):
    video, out, kw = args
    try:
        os.nice(15)
    except (AttributeError, OSError):
        pass
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            run(video, out, **kw)
    except Exception as e:
        return video, 'ERROR %r' % e
    return video, buf.getvalue().strip().splitlines()[-1]


def pool_map(jobs, workers):
    workers = max(1, min(16, workers, len(jobs) or 1))
    if workers == 1:
        return [_one(j) for j in jobs]
    from multiprocessing import Pool
    with Pool(workers) as p:
        return p.map(_one, jobs, chunksize=1)


def selftest(corpus, workers, refs):
    """MANIFEST rows `<file> video autoreview:<check> FAIL|PASS <build> <src> ok <notes>`; notes `at=t1,t2` = the frames a
    FAIL row must flag (+-0.25 s), `win=a-b` = the window judged (default whole video); a PASS row may flag nothing in it."""
    rows = []
    for line in open(os.path.join(corpus, 'MANIFEST.tsv'), errors='replace'):
        p = line.rstrip('\n').split('\t')
        if len(p) >= 7 and p[2].startswith('autoreview:') and p[6] in ('ok', 'kept') and p[3] in ('FAIL', 'PASS'):
            rows.append(p)
    tmp = '/tmp/autoreview-selftest'
    jobs = {}; extra = {}
    for p in rows:
        v = os.path.join(corpus, p[0])
        jobs.setdefault(v, os.path.join(tmp, re.sub(r'\W+', '_', p[0])))
        notes = p[7] if len(p) > 7 else ''
        for k in ('plate', 'state', 'weapon'):           # stills: plate=<corpus file> state=<state>; weapon=<class>
            m = re.search(r"(?:^|\s)%s=(\S+)" % k, notes)
            if m:
                extra.setdefault(v, {})[k] = os.path.join(corpus, m.group(1)) if k == 'plate' else m.group(1)
    res = dict(pool_map([(v, o, dict(refs=refs, crops=False, checks=('oneview', 'fragments', 'occluder', 'weapon'), **extra.get(v, {})))
                         for v, o in jobs.items()], workers))
    bad = 0
    for p in rows:
        v = os.path.join(corpus, p[0]); check = p[2].split(':', 1)[1]
        flags = []
        fp = os.path.join(jobs[v], 'flags.tsv')
        if os.path.exists(fp):
            flags = [float(q.split('\t')[1]) for q in open(fp).read().splitlines()[1:] if q.split('\t')[2] == check]
        notes = p[7] if len(p) > 7 else ''
        m = re.search(r'win=([\d.]+)-([\d.]+)', notes)
        a, b = (float(m.group(1)), float(m.group(2))) if m else (-1.0, 1e9)
        inwin = [x for x in flags if a - 0.25 <= x <= b + 0.25]
        m = re.search(r'at=([\d.,]+)', notes)
        at = [float(x) for x in m.group(1).split(',') if x] if m else []
        if p[3] == 'FAIL':
            got = [x for x in at if any(abs(x - y) <= 0.25 for y in flags)] if at else inwin[:1]
            ok = len(got) == (len(at) if at else 1)
            detail = 'caught %d/%d' % (len(got), len(at) if at else 1)
        else:
            ok = not inwin
            detail = 'flags in window %d' % len(inwin)
        bad += not ok
        print('%s %s %s expect %s: %s | %s' % ('ok ' if ok else 'BAD', p[0], check, p[3], detail, res.get(v, '')[:90]))
    print('RESULT AUTOREVIEW-SELFTEST %s rows=%d bad=%d' % ('PASS' if not bad else 'FAIL', len(rows), bad))
    return bad == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd')
    p = sp.add_parser('run'); p.add_argument('video'); p.add_argument('out')
    for k in ('ev', 'vmrec', 'stamp', 'weapon', 'name', 'labels'):
        p.add_argument('--' + k)
    p.add_argument('--offset', type=float); p.add_argument('--refs', default=REFS); p.add_argument('--no-crops', action='store_true')
    p.add_argument('--plate', help='still only: screenshot of the same spot without the viewmodel'); p.add_argument('--state', help='state of a still')
    p.add_argument('--checks', default=','.join(ALL))
    p = sp.add_parser('backfill'); p.add_argument('outroot'); p.add_argument('videos', nargs='+')
    p.add_argument('--workers', type=int, default=6); p.add_argument('--refs', default=REFS)
    p.add_argument('--checks', default='oneview,fragments,occluder,weapon'); p.add_argument('--no-crops', action='store_true')
    p = sp.add_parser('ref'); p.add_argument('action', choices=('add', 'list')); p.add_argument('video', nargs='?'); p.add_argument('weapon', nargs='?')
    p.add_argument('--ev'); p.add_argument('--stamp'); p.add_argument('--vmrec'); p.add_argument('--offset', type=float)
    p.add_argument('--states'); p.add_argument('--refs', default=REFS); p.add_argument('--plate')
    p = sp.add_parser('selftest'); p.add_argument('--corpus', default='/mnt/c/KenshiTestRuns/corpus')
    p.add_argument('--workers', type=int, default=6); p.add_argument('--refs', default=REFS)
    a = ap.parse_args()
    if a.cmd == 'run':
        run(a.video, a.out, a.ev, a.vmrec, a.stamp, a.offset, a.weapon, a.refs, a.name, tuple(a.checks.split(',')), not a.no_crops,
            a.plate, a.state)
    elif a.cmd == 'backfill':
        jobs = [(v, os.path.join(a.outroot, re.sub(r'\W+', '_', os.path.splitext(v.replace('/mnt/c/', ''))[0])[-90:]),
                 dict(refs=a.refs, checks=tuple(a.checks.split(',')), crops=not a.no_crops)) for v in a.videos]
        for v, r in pool_map(jobs, a.workers):
            print('%s\t%s' % (v, r))
    elif a.cmd == 'ref':
        if a.action == 'list':
            for d in sorted(glob.glob(os.path.join(a.refs, '*', '*'))):
                print('%s %d' % (os.path.relpath(d, a.refs), len(glob.glob(os.path.join(d, '*.npz')))))
        else:
            sys.exit(0 if ref_add(a.video, a.weapon, a.refs, a.ev, a.offset, a.stamp, a.vmrec, a.states and a.states.split(','), plate=a.plate) else 1)
    elif a.cmd == 'selftest':
        sys.exit(0 if selftest(a.corpus, a.workers, a.refs) else 1)
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
