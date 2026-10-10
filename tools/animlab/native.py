#!/usr/bin/env python3
"""native.py -- animation lab, phase 4 (NATIVE): use a game's own skeletal animations offline.

Reads the animations inside an Ogre .skeleton (tools/animlab/visual/ogre.py: SK_ANIMATION tracks, Ogre linear /
shortest-path nlerp interpolation, keyframes applied to the bind pose), renders them third person, extracts hand /
weapon trajectories in first-person camera numbers and turns them into a phase-2 motion ("adapted native motion")
that runs through the real viewmodel solver (metricslab drive adapter) and every recording check of animlab.py.
Docs: docs/animlab/USAGE.md "Phase 4". Game files are read at run time (config game_dir); nothing is copied.

  native.py list   --config CFG [--filter s] [--skeleton PATH]       name, length s, tracks, keys
  native.py sample --config CFG <anim> [--t T | --fps N] [--bones a,b] [--loop]   derived (model space) bone poses, dm
  native.py render --config CFG <anim> -o DIR [--weapon NAME|none] [--views side,front] [--fps 30] [--size 480x540]
                   [--mp4 out.mp4] [--sheet out.png] [--from T] [--to T] [--speed K]   third-person render
  native.py traj   --config CFG <anim> [--body REC --body-frame N] [--fps 30] [--eye fixed|head] [--anchor shoulder|none]
                   [--target weapon|hand] [-o traj.txt]       grip / tip / wrists in camera numbers of the FP eye
  native.py adapt  --config CFG <anim> --body REC --body-frame N -o motion.json [traj options] [--weapon NAME]
                   [--phases t_top,t_end] [--from T] [--to T] [--speed K]    adapted native motion (metricslab JSON)
  native.py run    --config CFG <anim> --adapter CMD --body REC --body-frame N --out DIR [adapt options]
                   [--visual VCFG] [--no-video] [--args='...']   adapt + solve + checks + FP render + side-by-side video
  native.py catalog --config CFG [--data FILE ...] [-o catalog.md]   native anims grouped by weapon class (FCS game data)
  native.py fists  --config CFG <anim>[,<anim>...] --body REC --body-frame N --adapter CMD --out DIR [--visual VCFG]
                   [--guard-anim A --guard-t T] [--no-video]   unarmed techniques -> FP key tables (both fists) + NA1 checks

CFG (JSON; KenshiFP's: components/KenshiFP/animlab/native.json): game_dir, skeleton, body_meshes [paths], head_bone,
eye_from_head [x,y,z] (camera numbers, dm: eye -> head bone; a body recording's `hd` overrides it), bones
{"R": [clavicle, upperarm, forearm, hand, prop], "L": [...]}, weapons {name: {mesh, bone, class (0 sword-like /
1 crossbow), blade (dm along f from the grip), hands ("R" or "RL" = two-handed: the off hand follows the native left
wrist), offset [x,y,z] prop-local dm, mirror_x}}, default_weapon {"<category>": name}, prop_axes / prop_local_q /
prop_roll_deg (as the visual lab: KenshiFP prop target convention), fov_3p (tan of the vertical half angle), colors.
Camera numbers: x right, y up, z forward (dm), relative to the eye, a mirrored frame of the right-handed Ogre world.
"""
import argparse, difflib, json, math, os, shlex, shutil, subprocess, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'visual'))
import ogre  # noqa: E402

UP = np.array([0.0, 1.0, 0.0])
FWD = np.array([0.0, 0.0, 1.0])   # Ogre model facing: Kenshi characters face +Z (toes), left = +X


def nz(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


# ---------------- config / data ----------------
def load_cfg(path):
    with open(path) as f:
        cfg = json.load(f)
    gd = os.environ.get('ANIMLAB_GAME_DIR')
    if gd:
        cfg['game_dir'] = gd
    return cfg


def gpath(cfg, p):
    p = p.replace('\\', '/')
    if p.startswith('./'):
        p = p[2:]
    return p if os.path.isabs(p) else os.path.join(cfg.get('game_dir', ''), p)


class Native:
    """skeleton + its animations (decoded once)."""
    def __init__(self, cfg, skeleton=None):
        self.cfg = cfg
        self.path = skeleton or gpath(cfg, cfg['skeleton'])
        self.sk = ogre.load_skeleton(self.path)
        self.anims = ogre.load_animations(self.path)

    def anim(self, name):
        if name in self.anims:
            return self.anims[name]
        low = {k.lower(): k for k in self.anims}
        if name.lower() in low:
            return self.anims[low[name.lower()]]
        near = difflib.get_close_matches(name, list(self.anims), 5, 0.4)
        raise KeyError('animation %r not in %s (close: %s)' % (name, os.path.basename(self.path), ', '.join(near) or '-'))

    def h(self, bone):
        return self.sk.by_name[bone].h

    def pose(self, anim, t, loop=False):
        return ogre.sample_pose(self.sk, anim, t, loop)


def times_of(length, fps, t0=0.0, t1=None):
    t1 = length if t1 is None else min(t1, length)
    n = max(1, int(round((t1 - t0) * fps)))
    return [t0 + (t1 - t0) * i / n for i in range(n + 1)]


# ---------------- list / sample ----------------
def cmd_list(a):
    N = Native(load_cfg(a.config), a.skeleton)
    for n in sorted(N.anims, key=str.lower):
        an = N.anims[n]
        if a.filter and a.filter.lower() not in n.lower():
            continue
        print('%-30s %7.3f s  tracks %2d  keys %5d%s' % (n, an.length, len(an.tracks), an.nkeys(),
                                                       '  base=%s@%g' % an.base if an.base else ''))
    print('%d animations, %d bones (%s)' % (len(N.anims), len(N.sk.bones), N.path))
    return 0


def cmd_sample(a):
    N = Native(load_cfg(a.config), a.skeleton)
    an = N.anim(a.anim)
    bones = [b.strip() for b in a.bones.split(',')] if a.bones else [b.name for b in sorted(N.sk.bones.values(), key=lambda b: b.h)]
    ts = [a.t] if a.t is not None else times_of(an.length, a.fps)
    print('# %s length %.4f s; per bone: derived position (dm, model space: y up, z = facing) and orientation w,x,y,z' % (an.name, an.length))
    for t in ts:
        P = N.pose(an, t, a.loop)
        for b in bones:
            h = N.h(b)
            print('%.4f %-20s %8.4f,%8.4f,%8.4f  %7.4f,%7.4f,%7.4f,%7.4f' % ((t, b) + tuple(P.dpos[h]) + tuple(P.dq[h])))
    return 0


# ---------------- weapons ----------------
def weapon_spec(cfg, name):
    if not name or name == 'none':
        return None
    W = cfg.get('weapons') or {}
    if name not in W:
        raise KeyError('weapon %r not in config (have: %s)' % (name, ', '.join(sorted(W))))
    w = dict(W[name]); w['name'] = name
    return w


_MESH = {}


def weapon_mesh(cfg, w):
    p = gpath(cfg, w['mesh'])
    if p not in _MESH:
        m = ogre.load_mesh(p)
        V, T = [], []
        for pos, _, tris, _ in m.triangles():
            T.append(tris + sum(len(x) for x in V)); V.append(pos)
        V = np.vstack(V).astype(float)
        _MESH[p] = (V, np.vstack(T))
    V, T = _MESH[p]
    V = V + np.array(w.get('offset', [0, 0, 0]), float)
    if w.get('mirror_x'):
        V = V * np.array([-1.0, 1, 1]); T = T[:, ::-1]
    return V, T


def guess_weapon(cfg, anim_name, cats):
    """default weapon for an animation from its technique categories (catalog) or the config's default_weapon map."""
    dw = cfg.get('default_weapon') or {}
    for c in cats or ():
        if c in dw:
            return dw[c]
    return dw.get('*', 'none')


# ---------------- third-person render ----------------
class Body:
    def __init__(self, N):
        cfg, sk = N.cfg, N.sk
        self.N = N
        nb = max(sk.bones) + 1
        P, T, W = [], [], []
        for mp in cfg.get('body_meshes', []):
            m = ogre.load_mesh(gpath(cfg, mp))
            for pos, _, tris, bw in m.triangles():
                wt = np.zeros((len(pos), nb))
                for v, b, w in bw:
                    if b < nb:
                        wt[v, b] += w
                wt /= np.maximum(wt.sum(1, keepdims=True), 1e-9)
                T.append(tris + sum(len(x) for x in P)); P.append(pos.astype(float)); W.append(wt)
        self.P, self.T, self.W = np.vstack(P), np.vstack(T), np.vstack(W)
        self.used = [h for h in range(nb) if self.W[:, h].max() > 0]

    def verts(self, pose):
        V = np.zeros_like(self.P)
        for h in self.used:
            pn, A = pose.skin(h)
            pb = self.N.sk.bones[h].dpos
            V += self.W[:, h][:, None] * (pn + (self.P - pb) @ A.T)
        return V


def weapon_world(N, pose, w):
    """weapon mesh vertices (model space) attached to its bone (default Bip01 Prop2), plus grip/tip points."""
    V, T = weapon_mesh(N.cfg, w)
    h = N.h(w.get('bone', N.cfg['bones']['R'][4]))
    R = pose.mat(h) * pose.dscale[h]
    return pose.dpos[h] + V @ R.T, T


VIEWS = {   # camera direction D (world), up: side = from the character's right, front = facing it
    'side': np.array([1.0, 0, 0]), 'front': np.array([0, 0, -1.0]), 'back': np.array([0, 0, 1.0]),
    'left': np.array([-1.0, 0, 0]), 'top': np.array([0, -1.0, 0.0001])}


ZOOM, FOV_FP = 25.0, 0.70   # zoomed-out view: fp_camera distance (dm), game vertical half-angle tan (visual lab fov)


def cam_axes(D, U=UP):
    D = nz(D); R = nz(np.cross(D, U)); U2 = np.cross(R, D)
    return R, U2, D


def to_cam(V, E, axes):
    R, U, D = axes
    X = V - E
    return np.column_stack([X @ R, X @ U, X @ D])


def label(img, lines, xy=(6, 4), size=15):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', size)
    except Exception:
        font = ImageFont.load_default()
    y = xy[1]
    for ln in lines:
        d.text((xy[0] + 1, y + 1), ln, fill=(0, 0, 0), font=font)
        d.text((xy[0], y), ln, fill=(255, 255, 210), font=font)
        y += size + 3
    return np.asarray(im)


class Render3P:
    def __init__(self, N, anim, weapon, views=('side', 'front'), size=(480, 540), t0=0.0, t1=None):
        from render import raster   # visual/render.py
        self.raster = raster
        self.N, self.anim, self.w, self.views, self.size = N, anim, weapon, views, size
        self.body = Body(N)
        # one fixed camera per view over the whole clip: frame the box of the body bones (grip included; the rest of a
        # long weapon may leave the frame) with a margin
        ts = times_of(anim.length, 15, t0, t1)
        skip = {N.h(N.cfg['bones']['L'][4])} if N.cfg['bones']['L'][4] in N.sk.by_name else set()   # Prop1: off-body in Kenshi clips
        pts = []
        for t in ts:
            P = N.pose(anim, t)
            pts += [P.dpos[h] for h in P.dpos if h not in skip]
        pts = np.array(pts)
        lo, hi = pts.min(0) - 2.5, pts.max(0) + 2.5
        lo[1] = min(lo[1], -0.5)
        self.center = (lo + hi) / 2
        self.ext = hi - lo
        self.tan = float(N.cfg.get('fov_3p', 0.45))
        self.cams = {}
        asp = size[0] / float(size[1])
        for v in views:
            if v == 'z25':   # the game zoomed out: camera ZOOM dm straight behind the FP eye (orbit 0), follows the pelvis
                axes, hd = fp_camera(N, anim, t0)
                P0 = N.pose(anim, t0)
                self.pelvis = N.h(N.cfg.get('pelvis_bone', 'Bip01 Pelvis'))
                self.pel0 = P0.dpos[self.pelvis].copy()
                self.cams[v] = (eye_at(N, P0, axes, hd) - axes[2] * ZOOM, axes)
                continue
            axes = cam_axes(VIEWS[v])
            R, U, D = axes
            half_w = 0.5 * float(np.abs(R) @ self.ext)
            half_h = 0.5 * float(np.abs(U) @ self.ext)
            depth = 0.5 * float(np.abs(D) @ self.ext)
            dist = max(half_h / self.tan, half_w / (self.tan * asp)) + depth
            self.cams[v] = (self.center - D * dist, axes)

    def frame(self, t, extra=()):
        N, size = self.N, self.size
        P = N.pose(self.anim, t)
        Vb = self.body.verts(P)
        Vs, Ts, parts = [Vb], [self.body.T], [np.zeros(len(self.body.T), int)]
        if self.w:
            Vw, Tw = weapon_world(N, P, self.w)
            Ts.append(Tw + len(Vb)); Vs.append(Vw); parts.append(np.ones(len(Tw), int))
        V, T, part = np.vstack(Vs), np.vstack(Ts), np.concatenate(parts)
        cols = N.cfg.get('colors', [[205, 160, 130], [190, 195, 205]])
        tiles = []
        asp = size[0] / float(size[1])
        for v in self.views:
            E, axes = self.cams[v]
            tan = self.tan
            if v == 'z25':
                d = P.dpos[self.pelvis] - self.pel0; d[1] = 0.0
                E = E + d; tan = FOV_FP
            C = to_cam(V, E, axes)
            img, _, _ = self.raster(C, T, part, size, (tan * asp, tan), 0.5, cols, np.full((size[1], size[0], 3), 48, np.float32))
            if v != 'z25':
                self._ground(img, E, axes)
            img = label(img, ['%s  %s' % (self.anim.name, v), 't %.2f / %.2f s' % (t, self.anim.length)] + list(extra))
            tiles.append(img)
        return np.concatenate(tiles, 1)

    def _ground(self, img, E, axes):
        """mark the ground line (y = 0) through the clip's centre so root motion / jumps read."""
        asp = self.size[0] / float(self.size[1])
        R = axes[0]
        for x in np.linspace(-40, 40, 321):
            c = to_cam((self.center * np.array([1.0, 0, 1.0]) + R * x)[None], E, axes)[0]
            if c[2] < 0.5:
                continue
            sx = int(self.size[0] / 2 + self.size[0] / 2 * c[0] / c[2] / (self.tan * asp))
            sy = int(self.size[1] / 2 - self.size[1] / 2 * c[1] / c[2] / self.tan)
            if 0 <= sx < self.size[0] and 1 <= sy < self.size[1]:
                img[sy - 1:sy + 1, sx] = (110, 140, 90)


def save_png(img, path):
    from PIL import Image
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)


def mp4(frames_dir, fps, out, pattern='f%05d.png'):
    r = subprocess.run(['ffmpeg', '-nostdin', '-y', '-loglevel', 'error', '-framerate', str(fps), '-i', os.path.join(frames_dir, pattern),
                        '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', out])
    return r.returncode


def sheet(imgs, cols, out, scale=0.5):
    from PIL import Image
    ims = [Image.fromarray(np.clip(i, 0, 255).astype(np.uint8)) for i in imgs]
    w, h = int(ims[0].width * scale), int(ims[0].height * scale)
    rows = (len(ims) + cols - 1) // cols
    S = Image.new('RGB', (w * cols, h * rows), (20, 20, 20))
    for k, im in enumerate(ims):
        S.paste(im.resize((w, h)), ((k % cols) * w, (k // cols) * h))
    S.save(out)


def parse_size(s):
    w, h = s.lower().split('x'); return int(w), int(h)


def cmd_render(a):
    cfg = load_cfg(a.config)
    N = Native(cfg, a.skeleton)
    an = N.anim(a.anim)
    w = weapon_spec(cfg, a.weapon)
    t0, t1 = a.from_t or 0.0, a.to_t
    R = Render3P(N, an, w, tuple(a.views.split(',')), parse_size(a.size), t0, t1)
    os.makedirs(a.o, exist_ok=True)
    ts = times_of(an.length, a.fps / max(a.speed, 1e-3), t0, t1)
    imgs = []
    for k, t in enumerate(ts):
        img = R.frame(t, ['weapon %s' % (w['name'] if w else 'none')])
        save_png(img, os.path.join(a.o, 'f%05d.png' % k)); imgs.append(img)
    print('%d frames -> %s' % (len(ts), a.o))
    rc = 0
    if a.mp4:
        rc = mp4(a.o, a.fps, a.mp4); print('mp4 %s rc=%d' % (a.mp4, rc))
    if a.sheet:
        n = min(a.sheet_n, len(imgs))
        sel = [imgs[int(round(i * (len(imgs) - 1) / max(1, n - 1)))] for i in range(n)]
        sheet(sel, a.sheet_cols, a.sheet, 0.5); print('sheet %s (%d tiles)' % (a.sheet, n))
    return rc


# ---------------- trajectories in FP camera numbers ----------------
def body_ref(path, frame):
    """the FP body a motion is solved on: shoulders, head (camera numbers), world up in camera numbers."""
    import recfmt
    F = recfmt.parse(path).frames
    r = F[frame]
    upw = np.array((r['rt'][1], r['up'][1], r['fw'][1])) if r.get('rt') else UP.copy()
    out = dict(Rsh=np.array(r['Rsh']), Lsh=np.array(r['Lsh']), upw=nz(upw), mp=np.array(r['mp']) if r.get('mp') else None)
    if r.get('hd') and any(abs(x) > 1e-6 for x in r['hd']):
        out['hd'] = np.array(r['hd'])
    return out


def fp_camera(N, anim, t_ref, body=None, yaw_deg=0.0):
    """native FP eye: level (or the body frame's pitch) camera facing the model's +Z, placed so the head bone sits where
    it sits in the FP view (body recording `hd`, else config eye_from_head)."""
    cfg = N.cfg
    hd = (body or {}).get('hd')
    if hd is None:
        hd = np.array(cfg.get('eye_from_head', [0.0, -1.5, -0.72]), float)
    upw = (body or {}).get('upw', UP)
    yw = math.radians(yaw_deg)
    Fh = np.array([math.sin(yw), 0.0, math.cos(yw)])
    b, c = float(upw[1]), float(upw[2])   # world up in camera numbers (0, b, c): pitch
    s = math.hypot(b, c) or 1.0; b, c = b / s, c / s
    D = nz(c * UP + b * Fh)
    U = nz(b * UP - c * Fh)
    Rx = nz(np.cross(D, U))
    axes = (Rx, U, D)
    return axes, hd


def eye_at(N, P, axes, hd):
    h = N.h(N.cfg.get('head_bone', 'Bip01 Head'))
    R, U, D = axes
    return P.dpos[h] - (hd[0] * R + hd[1] * U + hd[2] * D)


def cam_pt(v, E, axes):
    R, U, D = axes; x = np.asarray(v) - E
    return np.array([x @ R, x @ U, x @ D])


def cam_dir(v, axes):
    R, U, D = axes; v = np.asarray(v)
    return np.array([v @ R, v @ U, v @ D])


def prop_local_R(cfg, cls, side='R'):
    """rotation prop-local -> hand-local of the solver's prop convention (visual lab: prop = hand * q * roll)."""
    from render import axis
    ax = cfg['prop_axes'][cls]
    q = np.array(cfg['prop_local_q'][str(cls)], float)
    roll = math.radians(float((cfg.get('prop_roll_deg') or {}).get(str(cls), 0.0)))
    mq = (cfg.get('prop_mirror') or {}).get(side)   # off side: the drive's mirrored left grip (visual lab prop_mirror)
    if mq:
        q = q * np.array(mq.get('q_sign', [1, 1, 1, 1]), float)
        roll = roll * float(mq.get('roll_sign', 1)) + math.radians(float(mq.get('roll_add', 0)))
    Rl = ogre.qmat(q)
    if roll:
        k = axis(ax[0]); K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        Rl = Rl @ (np.eye(3) + math.sin(roll) * K + (1 - math.cos(roll)) * K @ K)
    return Rl


def rot_between(a, b):
    """smallest rotation matrix taking direction a onto direction b."""
    a, b = nz(a), nz(b)
    v = np.cross(a, b); c = float(a @ b); s = np.linalg.norm(v)
    if s < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]) / s
    th = math.atan2(s, c)
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


ANCHORS = ('fit', 'ready', 'shoulder', 'none')
FIT_NEAR = 4.0     # dm: an on-screen arm point nearer the eye than this = arm in the face (framing penalty)


def rot_x(deg):
    """rotation about the camera x axis (right) lifting forward (+z) toward up (+y) for deg > 0."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1.0, 0, 0], [0, c, s], [0, -s, c]])


def _onscreen(c, near=3.0):
    return c[2] > near and abs(c[0] / c[2]) < 1.245 and abs(c[1] / c[2]) < 0.70


def _in_face(r, S, R):
    """an on-screen point of either arm (shoulder-elbow-wrist) nearer the eye than FIT_NEAR."""
    for s in 'LR':
        J = [S + R @ (r[k + s] - S) for k in ('sh', 'el', 'wr')]
        for a, b in ((J[0], J[1]), (J[1], J[2])):
            for u in (0.25, 0.5, 0.75, 1.0):
                c = a + (b - a) * u
                if np.linalg.norm(c) < FIT_NEAR and _onscreen(c, 0.3):
                    return True
    return False


def framing_score(raw, S, R, blade):
    """how well a framing shows the motion: share of frames with the grip or the blade middle on screen, minus twice
    the share with an arm in the face (_in_face)."""
    on = near = 0
    for r in raw:
        g = S + R @ (r['p'] - S); f = R @ r['f']
        mid = g + f * (blade * 0.5)
        on += _onscreen(g) or _onscreen(mid)
        near += _in_face(r, S, R)
    return (on - 2.0 * near) / float(len(raw))


def grip_vec(f, u, d):
    """wrist - grip in camera numbers for a prop frame (f, u) and a prop-frame offset d = (along f, along u, along f x u)."""
    F = nz(f); U = nz(np.asarray(u, float) - F * float(np.dot(u, F))); T = np.cross(F, U)
    return d[0] * F + d[1] * U + d[2] * T


def trajectory(N, anim, ts, body=None, eye='fixed', anchor='fit', target='weapon', weapon=None, side='R',
               t_ref=None, yaw=0.0, lift=None, gain=1.0, stab='torso', grip=None):
    """per time: dict(t, p, f, u, tip, wr{L,R}, el{L,R}, sh{L,R}, hx{L,R}, delta, rot) in FP camera numbers.
    target hand also gives p/f/u{L,R} for both hands (left = the drive's mirrored grip). grip {side: d}: the solver's
    wrist in its prop frame (measure_grip on a solved run); p is then placed so the SOLVED wrist lands on the native
    wrist (the bind prop offset of the skeleton differs from the solver's by ~1.7 dm).
    target weapon: p/f/u = the native prop bone (grip) and its prop axes (the weapon follows the native weapon);
    target hand: the solver's own prop convention applied to the native hand (the hand follows the native hand).
    Framing (anchor; all but none need a body recording): the native weapon-side shoulder at t_ref is moved onto the
    body's shoulder (shoulder), then the motion is turned about that shoulder (keeps reach):
      ready = take the native shoulder->grip direction at t_ref onto the body frame's (its measured grip mp);
      fit   = a lift about the shoulder's camera-x axis, scanned -30..90 deg, that shows the weapon on screen in the
              most frames without the arm in the face (framing_score); a 3P clip starts with the weapon at the hip,
              far below the FP view, so some lift is nearly always needed;
      lift  = explicit lift in deg (overrides ready/fit); gain = scale of all positions about the shoulder.
    stab torso (default): every frame is first re-expressed in the chest bone's frame at t_ref (config chest_bone), so
    the native body's lean, twist and steps drop out and only the arms move against the chest, as in first person
    (the FP camera and shoulders stay put); pelvis: only the pelvis' ground-plane travel (steps, lunges) is removed,
    the torso turn stays (martial-arts punches turn the torso ~90 deg: torso-stabilised they point sideways);
    world = the clip as seen by a camera fixed in the world."""
    from render import axis
    cfg = N.cfg
    cls = int((weapon or {}).get('class', 0))
    ax = cfg['prop_axes'][cls]
    fa, ua = axis(ax[0]), axis(ax[1])
    B = cfg['bones']
    blade = float((weapon or {}).get('blade', 1.0 if weapon is None else 8.0))
    t_ref = ts[0] if t_ref is None else t_ref
    axes, hd = fp_camera(N, anim, t_ref, body, yaw)
    P0 = N.pose(anim, t_ref)
    E0 = eye_at(N, P0, axes, hd)
    hp = N.h(B[side][4])
    S = np.zeros(3); delta = np.zeros(3)
    if anchor != 'none' and body is not None:
        S = body[side + 'sh']
        delta = S - cam_pt(P0.dpos[N.h(B[side][1])], E0, axes)
    Rls = {s: prop_local_R(cfg, cls, s) for s in 'LR'}
    hc = N.h(cfg.get('chest_bone', 'Bip01 Spine2'))
    lp_bind = {}
    for s in 'LR':
        bh, bp = N.sk.bones[N.h(B[s][3])], N.sk.bones[N.h(B[s][4])]
        lp_bind[s] = ogre.qmat(bh.dq).T @ (bp.dpos - bh.dpos)
    hands = 'LR' if target == 'hand' else side
    hpl = N.h(cfg.get('pelvis_bone', 'Bip01 Pelvis'))
    raw = []
    for t in ts:
        P = N.pose(anim, t)
        if stab == 'torso':   # world -> chest at t -> chest at t_ref
            M = P0.mat(hc) @ P.mat(hc).T
            wp = lambda h: P0.dpos[hc] + M @ (P.dpos[h] - P.dpos[hc])
            E = E0
        elif stab == 'pelvis':   # steps / lunges removed (pelvis ground-plane travel), body turns kept: the FP view of a punch
            M = np.eye(3)
            dpl = P.dpos[hpl] - P0.dpos[hpl]; dpl[1] = 0.0
            wp = lambda h: P.dpos[h] - dpl
            E = E0
        else:
            M = np.eye(3)
            wp = lambda h: P.dpos[h]
            E = eye_at(N, P, axes, hd) if eye == 'head' else E0
        r = dict(t=t)
        for s in 'LR':
            for k, bi in (('sh', 1), ('el', 2), ('wr', 3)):
                r[k + s] = cam_pt(wp(N.h(B[s][bi])), E, axes) + delta
            r['hx' + s] = cam_dir(M @ P.mat(N.h(B[s][3]))[:, 0], axes)
            r['hz' + s] = cam_dir(M @ P.mat(N.h(B[s][3]))[:, 2], axes)   # hand Z: the fingers curl toward -Z (palm normal)
        for s in hands:
            hh = N.h(B[s][3])
            if target == 'hand':   # the prop bone is parked anywhere in unarmed clips: grip = hand + bind prop offset
                Rp = M @ (P.mat(hh) @ Rls[s])
                r['p' + s] = cam_pt(wp(hh) + M @ P.mat(hh) @ lp_bind[s], E, axes) + delta
            else:
                Rp = M @ P.mat(hp)
                r['p' + s] = cam_pt(wp(hp), E, axes) + delta
            r['f' + s] = nz(cam_dir(Rp @ fa, axes)); r['u' + s] = nz(cam_dir(Rp @ ua, axes))
        r['p'], r['f'], r['u'] = r['p' + side], r['f' + side], r['u' + side]
        raw.append(r)
    Rr = np.eye(3)
    if lift is not None:
        Rr = rot_x(lift)
    elif anchor == 'ready' and body is not None and body.get('mp') is not None:
        Rr = rot_between(raw[0]['p'] - S, body['mp'] - S)
    elif anchor == 'fit' and body is not None:
        best = max((framing_score(raw, S, rot_x(d), blade), -abs(d), d) for d in range(-30, 91, 5))
        Rr = rot_x(best[2])
    rot = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(Rr) - 1) / 2))))
    score = framing_score(raw, S, Rr, blade) if body is not None else float('nan')
    out = []
    for r in raw:
        q = dict(t=r['t'], delta=delta, rot=rot, score=score)
        for k, v in r.items():
            if k == 't':
                continue
            if k[0] in 'fu' or k.startswith('hx') or k.startswith('hz'):
                q[k] = Rr @ v
            else:
                q[k] = S + gain * (Rr @ (v - S))
        for s in hands:
            if target == 'hand' and grip and grip.get(s) is not None:
                q['p' + s] = q['wr' + s] - grip_vec(q['f' + s], q['u' + s], grip[s])
        q['p'] = q['p' + side]
        q['tip'] = q['p'] + q['f'] * blade
        out.append(q)
    return out


STROKE_WIN, STROKE_LATE = 0.2, 0.75   # s window of tip path; a later window with >= 75% of the best path wins


def phases(tr, t_top=None, t_end=None):
    """swing phase times (t0, t_top, t_end, t_follow, t1) from the tip path: the stroke is the 0.2 s window with the
    longest tip path, or the LAST window with >= 75% of it (a fast wind-up raise often precedes the cut); then the
    fast part around that window's peak speed (>= 35% of it), wind-up top = its start, follow = until the speed drops
    below 15%. --phases t_top,t_end overrides."""
    T = np.array([r['t'] for r in tr]); X = np.array([r['tip'] for r in tr])
    if len(T) < 3:
        return (T[0], T[0], T[-1], T[-1], T[-1])
    dt = np.maximum(np.diff(T), 1e-6)
    sp = np.r_[0, np.linalg.norm(np.diff(X, axis=0), axis=1) / dt]
    w = max(1, int(round(STROKE_WIN / float(np.median(dt)))))
    path = np.array([sp[i:i + w].sum() for i in range(len(sp))])
    best = path.max() or 1.0
    i0 = int(max(i for i in range(len(path)) if path[i] >= STROKE_LATE * best))
    k = i0 + int(np.argmax(sp[i0:i0 + w])); pk = sp[k] or 1.0
    a = k
    while a > 1 and sp[a - 1] >= 0.35 * pk:
        a -= 1
    b = k
    while b < len(sp) - 1 and sp[b + 1] >= 0.35 * pk:
        b += 1
    c = b
    while c < len(sp) - 1 and sp[c + 1] >= 0.15 * pk:
        c += 1
    ta = T[a - 1] if a > 0 else T[0]
    tb, tc = T[b], max(T[c], T[b])
    if t_top is not None:
        ta = t_top
    if t_end is not None:
        tb = t_end; tc = max(tc, tb)
    return (float(T[0]), float(ta), float(tb), float(tc), float(T[-1]))


SWU = (0.0, 0.28, 0.58, 0.78, 1.0)   # KenshiFP swing keys: wind-up end, stroke end, follow end (metrics.SWING_PHASES)


def swu_of(t, ph):
    for i in range(4):
        if t <= ph[i + 1] or i == 3:
            d = ph[i + 1] - ph[i]
            u = (t - ph[i]) / d if d > 1e-9 else 1.0
            return SWU[i] + (SWU[i + 1] - SWU[i]) * min(max(u, 0.0), 1.0)
    return 1.0


def write_traj(tr, path, ph=None):
    with open(path, 'w') as f:
        f.write('# t swu | p f u tip | Rsh Rel Rwr | Lsh Lel Lwr   (camera numbers, dm)\n')
        for r in tr:
            v = lambda x: '%.4f,%.4f,%.4f' % tuple(x)
            f.write('%.4f %.3f | %s %s %s %s | %s %s %s | %s %s %s\n' % (r['t'], swu_of(r['t'], ph) if ph else 0.0,
                    v(r['p']), v(r['f']), v(r['u']), v(r['tip']), v(r['shR']), v(r['elR']), v(r['wrR']), v(r['shL']), v(r['elL']), v(r['wrL'])))


def _traj_args(a, cfg, N, an):
    w = weapon_spec(cfg, a.weapon) if a.weapon else None
    body = body_ref(a.body, a.body_frame) if a.body else None
    target = a.target or ('weapon' if w else 'hand')
    t0, t1 = a.from_t or 0.0, a.to_t
    ts = times_of(an.length, a.key_fps, t0, t1)
    tr = trajectory(N, an, ts, body, a.eye, a.anchor, target, w, 'R', t0, a.yaw, a.lift, a.gain, a.stab, getattr(a, 'grip', None))
    ph = phases(tr, *(a.phases or (None, None)))
    return w, body, target, tr, ph


def cmd_traj(a):
    cfg = load_cfg(a.config); N = Native(cfg, a.skeleton); an = N.anim(a.anim)
    w, body, target, tr, ph = _traj_args(a, cfg, N, an)
    write_traj(tr, a.o, ph)
    print('%s: %d frames, phases t0 %.3f top %.3f end %.3f follow %.3f t1 %.3f, anchor delta %s rot %.1f deg' % (
        a.o, len(tr), *ph, np.round(tr[0]['delta'], 2).tolist(), tr[0]['rot']))
    return 0


# ---------------- adapted native motion ----------------
def adapt(N, an, tr, ph, w, body_path, body_frame, target, speed=1.0, name=None, off_hand=None):
    """metricslab motion JSON from a trajectory; native time / speed = motion time."""
    t0 = tr[0]['t']
    two = off_hand if off_hand is not None else ('L' in (w or {}).get('hands', 'R'))
    keys, off = [], []
    for r in tr:
        t = round((r['t'] - t0) / speed, 5)
        keys.append(dict(t=t, p=[round(x, 4) for x in r['p']], f=[round(x, 5) for x in r['f']], u=[round(x, 5) for x in r['u']]))
        off.append(dict(t=t, p=[round(x, 4) for x in r['wrL']]))
    blade = float((w or {}).get('blade', 1.0 if w is None else 8.0))
    m = dict(name=name or 'native-' + an.name.replace(' ', '_'), fps=60, interp='linear', preroll=0.5,
             body=dict(rec=body_path, frame=body_frame),
             hands=dict(R=dict(weapon='crossbow' if int((w or {}).get('class', 0)) == 1 else 'sword', blade=blade, keys=keys,
                               off=off if two else 'rest')),
             native=dict(anim=an.name, length=an.length, t0=t0, t1=tr[-1]['t'], speed=speed, weapon=(w or {}).get('name', 'none'),
                         target=target, phases=[round((x - t0) / speed, 4) for x in ph], delta=[round(x, 3) for x in tr[0]['delta']], rot_deg=round(tr[0]['rot'], 2), framing=round(tr[0]['score'], 3),
                         two_handed=bool(two)))
    if w is None or blade < 3:   # fists: no blade to measure against the camera / other arm
        m['limits'] = dict(head_min=0.0, clip_frames=10 ** 6)
    return m


def cmd_adapt(a):
    cfg = load_cfg(a.config); N = Native(cfg, a.skeleton); an = N.anim(a.anim)
    w, body, target, tr, ph = _traj_args(a, cfg, N, an)
    m = adapt(N, an, tr, ph, w, a.body, a.body_frame, target, a.speed, a.name, a.off_hand)
    m['native'].update(anchor=a.anchor, lift=a.lift, gain=a.gain, eye=a.eye, stab=a.stab)
    with open(a.o, 'w') as f:
        json.dump(m, f, indent=1)
    print('%s: %d keys %.2f s, target %s, weapon %s, phases %s, delta %s' % (a.o, len(m['hands']['R']['keys']),
          m['hands']['R']['keys'][-1]['t'], target, m['native']['weapon'], m['native']['phases'], m['native']['delta']))
    return 0


def synth_rec(m, solved_rows, frames, path):
    """a KenshiFP-format recording (recfmt) of a solved adapted motion, so every animlab.py recording check runs on it:
    record i+1 holds what frame i rendered (measured groups), st/swing/swu from the native phases, H = bone hinges
    (drive output group 5, when the adapter writes it)."""
    import metricslab as ML
    ph = m['native']['phases']
    n0 = sum(1 for x in frames if x[0] < -1e-9)
    rows = solved_rows[n0:]
    fr = frames[n0:]
    v = lambda x: '%.5f,%.5f,%.5f' % tuple(x)
    lines = ['# build animlab native %s (synthetic recording of an adapted native motion)' % m['native']['anim'],
             '# n t dt st ti cls on w swing swu prog kick fire omode yaw pitch zoom | ...']
    prev = None
    for i in range(len(rows) + 1):
        r = rows[max(0, i - 1)]          # measured = what frame i-1 rendered
        t, cls, p, f, u, o, seg = fr[min(i, len(fr) - 1)]
        tt = t if i < len(fr) else t + 1.0 / m['fps']
        dt = (tt - prev) if prev is not None else 1.0 / m['fps']
        prev = tt
        sw = 1 if ph[0] - 1e-6 <= tt <= ph[4] + 1e-6 else 0
        swu = swu_of(tt, ph) if sw else 0.0
        st = 'swinging' if sw else 'ready'
        A = r['R']; Lr = r['L']
        oc = o if o is not None else (0.0, 0.0, 0.0)
        wb = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(nz(np.subtract(A['wr'], A['el'])), nz(A['hx'])))))))
        mfx = nz(np.subtract(A['wr'], A['el']))
        g0 = '%d %.5f %.5f %s 0 %d 1 1.000 %d %.4f %.4f 0 0 0 0 0 0' % (i, tt, dt, st, cls, sw, swu, swu)
        g1 = ' '.join(v(x) for x in (p, f, u, oc, A['pp'], A['pf'], A['pu'], Lr['sh'], Lr['el'], Lr['wr'], A['sh'], A['el'], A['wr']))
        g2 = ' '.join(v(x) for x in (r['eye'], r['rt'], r['up'], r['fw']))
        g3 = '0,0,0 0,0,0 %d 0 1 %.4f' % (i, r['stR'])
        g4 = '%.3f %s %s 1.000 0,0,0 0,0,0 0,0,0' % (wb, v(A['hx']), v(mfx))
        g5 = '0'
        grp = [g0, g1, g2, g3, g4, g5]
        if r.get('H'):
            grp.append('H %s %s %d' % (v(r['H'][0]), v(r['H'][1]), 0 if sw else -1))
        lines.append(' | '.join(grp))
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def parse_hinges(path):
    """optional drive output group 5 `H ua fa` (weapon-arm bone hinge axes) -> list per row (None if absent)."""
    out = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                continue
            g = line.split('|')
            if len(g) < 5:
                continue
            h = None
            if len(g) > 5:
                x = g[5].split()
                if len(x) >= 3 and x[0] == 'H':
                    h = (tuple(float(y) for y in x[1].split(',')), tuple(float(y) for y in x[2].split(',')))
            out.append(h)
    return out


def measure_grip(rows, side, n0=0):
    """the solver's wrist in its prop frame (f, u, f x u), median over solved rows (constant per solver build/class)."""
    D = []
    for r in rows[n0:]:
        A = r[side]
        F = nz(A['pf']); U = nz(np.asarray(A['pu'], float) - F * float(np.dot(A['pu'], F))); T = np.cross(F, U)
        D.append(np.array([F, U, T]) @ (np.asarray(A['wr'], float) - np.asarray(A['pp'], float)))
    return np.median(np.array(D), 0) if D else None


CHECKS = ('metrics', 'churn', 'inline', 'hinge', 'blade', 'stroke')


def run_checks(rec, fists=False):
    """animlab.py recording checks on the synthetic recording -> {check: (PASS|FAIL|INFO|N/A, line)}."""
    res = {}
    for c in CHECKS:
        cmd = [sys.executable, os.path.join(HERE, 'animlab.py'), c, rec]
        p = subprocess.run(cmd, capture_output=True, text=True)
        txt = (p.stdout + p.stderr).strip().splitlines()
        if c == 'metrics':
            for k in ('arc', 'moves'):
                ln = next((l for l in txt if l.startswith(k + ' ')), None)
                if ln:
                    res[k] = (ln.split()[1], ln)
            continue
        ln = next((l for l in txt if l.startswith(c + ' ')), (txt[-1] if txt else 'no output'))
        v = ln.split()[1] if ln.startswith(c + ' ') and len(ln.split()) > 1 else 'N/A'
        if fists and c in ('blade', 'stroke', 'inline') and v in ('PASS', 'FAIL'):
            v = 'INFO'   # no blade: the blade-reading checks only describe the forearm/hand line
        res[c] = (v, ln)
    res.pop('moves', None)   # no ready/block pair in a single adapted swing
    return res


def compose(left, right, h=None):
    from PIL import Image
    a = Image.fromarray(np.clip(left, 0, 255).astype(np.uint8)); b = Image.fromarray(np.clip(right, 0, 255).astype(np.uint8))
    h = h or a.height
    a = a.resize((int(a.width * h / a.height), h)); b = b.resize((int(b.width * h / b.height), h))
    S = Image.new('RGB', (a.width + b.width, h)); S.paste(a, (0, 0)); S.paste(b, (a.width, 0))
    return np.asarray(S)


def cmd_run(a):
    import metricslab as ML
    cfg = load_cfg(a.config); N = Native(cfg, a.skeleton); an = N.anim(a.anim)
    w, body, target, tr, ph = _traj_args(a, cfg, N, an)
    m = adapt(N, an, tr, ph, w, a.body, a.body_frame, target, a.speed, a.name, a.off_hand)
    os.makedirs(a.out, exist_ok=True)
    if target == 'hand':   # calibration solve: the solver's wrist in its prop frame, so the solved wrist = the native wrist
        cd = os.path.join(a.out, '_cal'); os.makedirs(cd, exist_ok=True)
        with open(os.path.join(cd, 'motion.json'), 'w') as f:
            json.dump(m, f)
        mc = ML.load_motion(os.path.join(cd, 'motion.json'))
        sv, frm = ML.run_motion(mc, a.adapter, a.body, a.body_frame, cd, shlex.split(a.args or ''), True)
        grip = {'R': measure_grip(sv['R'][0], 'R', sum(1 for x in frm['R'] if x[0] < -1e-9))}
        shutil.rmtree(cd, ignore_errors=True)
        a.grip = grip
        w, body, target, tr, ph = _traj_args(a, cfg, N, an)
        m = adapt(N, an, tr, ph, w, a.body, a.body_frame, target, a.speed, a.name, a.off_hand)
        m['native']['grip'] = [round(float(x), 4) for x in grip['R']]
    m['native'].update(anchor=a.anchor, lift=a.lift, gain=a.gain, eye=a.eye, stab=a.stab)
    mp = os.path.join(a.out, 'motion.json')
    with open(mp, 'w') as f:
        json.dump(m, f, indent=1)
    write_traj(tr, os.path.join(a.out, 'traj.txt'), ph)
    m = ML.load_motion(mp)
    solved, frames = ML.run_motion(m, a.adapter, a.body, a.body_frame, a.out, shlex.split(a.args or ''), True)
    P, rows, v = ML.evaluate(m, solved, frames)
    with open(os.path.join(a.out, 'report.txt'), 'w') as f:
        ML.print_report(m, rows, v, f)
    res_line = open(os.path.join(a.out, 'report.txt')).read().splitlines()[-1]
    H = parse_hinges(os.path.join(a.out, 'solved_R.txt'))
    srows = solved['R'][0]
    for r, h in zip(srows, H):
        r['H'] = h
    rec = synth_rec(m, srows, frames['R'], os.path.join(a.out, 'adapted.rec.txt'))
    fists = w is None or float(m['hands']['R'].get('blade', 8)) < 3
    res = run_checks(rec, fists)
    with open(os.path.join(a.out, 'checks.txt'), 'w') as f:
        f.write(res_line + '\n')
        for k, (vv, ln) in res.items():
            f.write('%s %s | %s\n' % (k, vv, ln))
    bad = [k for k, (vv, _) in res.items() if vv == 'FAIL']
    hand_err = hand_error(m, tr, srows, frames['R'])
    summ = 'RESULT native-%s %s solver=%s checks: %s hand_err_p95=%.1fdeg%s' % (
        an.name.replace(' ', '_'), 'PASS' if v['ok'] and not bad else 'FAIL', 'PASS' if v['ok'] else 'FAIL',
        ' '.join('%s=%s' % (k, vv) for k, (vv, _) in res.items()), hand_err, (' fails=' + ','.join(bad)) if bad else '')
    with open(os.path.join(a.out, 'checks.txt'), 'a') as f:
        f.write(summ + '\n')
    print(res_line)
    for k, (vv, ln) in res.items():
        print('  %-7s %-4s %s' % (k, vv, ln[:150]))
    if not a.no_video:
        video(a, cfg, N, an, w, m, os.path.join(a.out, 'pose.txt'))
    print(summ)
    return 0 if 'PASS' in summ.split()[2] else 1


def hand_error(m, tr, srows, fr):
    """p95 angle (deg) between the native hand X axis and the solved hand X axis (target weapon: grip convention
    difference shows here; target hand: should be ~0)."""
    n0 = sum(1 for x in fr if x[0] < -1e-9)
    T = np.array([r['t'] for r in tr]) - tr[0]['t']
    sp = float(m['native'].get('speed', 1.0))
    e = []
    for r, f in zip(srows[n0:], fr[n0:]):
        k = int(np.argmin(np.abs(T / sp - f[0])))
        hx = nz(tr[k]['hxR']); sx = nz(r['R']['hx'])
        e.append(math.degrees(math.acos(max(-1.0, min(1.0, float(hx @ sx))))))
    return float(np.percentile(e, 95)) if e else float('nan')


def video(a, cfg, N, an, w, m, pose_path):
    """side-by-side: native third person (side + front) | adapted first person (solver + visual lab), same timeline."""
    import render as VR
    vcfg = VR.load_cfg(a.visual, 'R' if w else 'none')
    if w:
        vcfg.setdefault('weapon_mesh', {})['R'] = w['mesh'].replace('\\', '/').lstrip('./') if not os.path.isabs(w['mesh']) else w['mesh']
        vcfg['weapon_offset'] = {'R': w.get('offset', [0, 0, 0])}
    rig = VR.Rig(vcfg)
    Pf = VR.load_pose(pose_path)
    fps = a.video_fps
    sp = float(m['native'].get('speed', 1.0))
    t0n = m['native']['t0']
    R3 = Render3P(N, an, w, ('side', 'front'), parse_size(a.size), t0n, m['native']['t1'])
    vd = os.path.join(a.out, 'video'); os.makedirs(vd, exist_ok=True)
    T = np.array([f['t'] for f in Pf])
    dur = m['hands']['R']['keys'][-1]['t']
    ts = np.arange(0.0, dur + 1e-6, 1.0 / fps)
    ph = m['native']['phases']
    imgs = []
    for k, t in enumerate(ts):
        nat = R3.frame(t0n + t * sp, ['native 3P (speed x%.2g)' % (1 / sp) if sp != 1 else 'native 3P'])
        i = int(np.argmin(np.abs(T - t)))
        img, _, _ = VR.render_frame(rig, Pf[i], (800, 450))
        phase = 'swu %.2f %s' % (swu_of(t, ph), _phase_name(swu_of(t, ph)))
        img = label(img, ['adapted FP (KenshiFP solver)', 't %.2f s  %s' % (t, phase)])
        frame = compose(nat, img, nat.shape[0])
        save_png(frame, os.path.join(vd, 'f%05d.png' % k)); imgs.append(frame)
    out = a.mp4 or os.path.join(a.out, 'native-vs-fp.mp4')
    rc = mp4(vd, fps, out)
    n = min(12, len(imgs))
    sel = [imgs[int(round(i * (len(imgs) - 1) / max(1, n - 1)))] for i in range(n)]
    sheet(sel, 3, os.path.join(a.out, 'native-vs-fp-sheet.png'), 0.5)
    print('video %s (%d frames @ %d fps) rc=%d; sheet %s' % (out, len(ts), fps, rc, os.path.join(a.out, 'native-vs-fp-sheet.png')))


def _phase_name(u):
    return 'windup' if u < 0.28 else 'stroke' if u < 0.58 else 'follow' if u < 0.78 else 'recov'


# ---------------- keyed viewmodel path (KenshiFP vm_swing_at) ----------------
def pose_norm(p, f, u):
    f = nz(f); u = nz(np.asarray(u, float) - f * float(np.dot(f, u)))
    return np.asarray(p, float), f, u


def _cr(p0, p1, p2, p3, t0, t1, t2, t3, t):
    """vm_cr: Catmull-Rom with non-uniform key times (segment t1..t2)."""
    d12 = t2 - t1
    if d12 < 1e-4:
        return p1
    s = (t - t1) / d12
    m1 = (p2 - p0) * (d12 / max(t2 - t0, 1e-4))
    m2 = (p3 - p1) * (d12 / max(t3 - t1, 1e-4))
    s2, s3 = s * s, s * s * s
    return p1 * (2 * s3 - 3 * s2 + 1) + m1 * (s3 - 2 * s2 + s) + p2 * (-2 * s3 + 3 * s2) + m2 * (s3 - s2)


def keyed_at(start, keys, end, ku, u):
    """KenshiFP vm_swing_at: start pose -> keys (at ku, len(keys)) -> end pose; poses (p, f, u); phantom end keys give a
    zero tangent at the rest poses. f/u interpolate per component, then pose_norm (as the game)."""
    K = [pose_norm(*start)] + [pose_norm(*k) for k in keys] + [pose_norm(*end)]
    t = [0.0] + list(ku) + [1.0]
    n = len(K)
    if u <= 0.0:
        return K[0]
    if u >= 1.0:
        return K[-1]
    i = 0
    while i < n - 2 and u > t[i + 1]:
        i += 1
    a = i - 1 if i > 0 else i
    d = i + 2 if i + 2 < n else i + 1
    ta = t[a] if i > 0 else t[i] - (t[i + 1] - t[i])
    td = t[d] if i + 2 < n else t[i + 1] + (t[i + 1] - t[i])
    ka, kd = K[a], K[d]
    if i == 0:
        ka = K[i + 1]; ta = t[i + 1] - 2.0 * (t[i + 1] - t[i])
    if i + 2 >= n:
        kd = K[i]; td = t[i] + 2.0 * (t[i + 1] - t[i])
    return pose_norm(*[_cr(ka[j], K[i][j], K[i + 1][j], kd[j], ta, t[i], t[i + 1], td, u) for j in range(3)])


def fit_keys(dense, start, end, nkeys=5, min_gap=0.04, sweeps=6, wdir=1.0):
    """key times (shared by all hands) for the keyed path that best reproduces dense = {side: [(u, p, f, u)]}:
    coordinate descent over the dense samples' u (values = the dense pose there). Returns (ku, err_p95 dm, err_max dm)."""
    sides = sorted(dense)
    U = np.array([x[0] for x in dense[sides[0]]])
    inner = [k for k in range(len(U)) if min_gap <= U[k] <= 1 - min_gap]

    def keys_at(idx, s):
        return [dense[s][k][1:] for k in idx]

    def err(idx, full=False):
        e = []
        ku = [U[k] for k in idx]
        for s in sides:
            ks = keys_at(idx, s)
            for x in dense[s]:
                p, f, uu = keyed_at(start[s], ks, end[s], ku, x[0])
                e.append(float(np.sum((p - x[1]) ** 2) + wdir * (np.sum((f - x[2]) ** 2) + 0.25 * np.sum((uu - x[3]) ** 2))))
        if full:
            return e
        return float(np.sum(e))
    idx = [inner[int(round(i * (len(inner) - 1) / (nkeys - 1)))] for i in range(nkeys)]
    best = err(idx)
    for _ in range(sweeps):
        moved = False
        for j in range(nkeys):
            lo = U[idx[j - 1]] + min_gap if j > 0 else min_gap
            hi = U[idx[j + 1]] - min_gap if j < nkeys - 1 else 1 - min_gap
            for k in inner:
                if not (lo <= U[k] <= hi) or k == idx[j]:
                    continue
                c = idx[:j] + [k] + idx[j + 1:]
                e = err(c)
                if e < best - 1e-9:
                    best, idx, moved = e, c, True
        if not moved:
            break
    pe = []
    ku = [U[k] for k in idx]
    for s in sides:
        ks = keys_at(idx, s)
        for x in dense[s]:
            pe.append(float(np.linalg.norm(keyed_at(start[s], ks, end[s], ku, x[0])[0] - x[1])))
    return idx, ku, float(np.percentile(pe, 95)), float(max(pe))


def vp(p, f, u):
    return 'VP(%.3ff, %.3ff, %.3ff, %.3ff, %.3ff, %.3ff, %.3ff, %.3ff, %.3ff)' % (tuple(p) + tuple(f) + tuple(u))


# ---------------- fists: per-technique FP key tables from native unarmed clips ----------------
# Geometry for the game's unarmed FP body (vmrec-fist-z0-a.txt frame 100, 4080 2026-10-10: the unarmed stance turns the
# torso, R shoulder 2.4 dm / L 1.4 dm behind the eye; arm reach 7.1 dm): strikes at <= 6.8 dm from the shoulder, guards
# on screen (y/z >= -.62) and bent (~5.1-5.7 dm). The sword-ready proxy used guard z 4.2 / strike z 5.5 (out of reach here).
FIST_DEFAULTS = dict(guard={'R': [1.7, -2.0, 3.3], 'L': [-1.7, -2.1, 3.7]},     # FP guard wrists (camera numbers, dm)
                     strike={'R': [0.5, -1.1, 4.1], 'L': [-0.5, -1.0, 4.8]},    # where a full punch puts the wrist
                     chamber={'R': [0.3, -0.7, -0.3], 'L': [-0.3, -0.7, -0.3]},  # full wind-up offset from the guard (down, back)
                     chamber_e=0.25,   # native extension (fraction of the strike, negative = pulled back) that maps to the full chamber
                     res_scale=0.35, res_max=0.5,   # native off-line wrist motion kept (scale, clamp dm), turned onto the FP strike line
                     off_scale=0.4, off_max=0.6,   # non-striking hand: its native motion scaled + clamped (dm) about its guard
                     end_blend=0.15,   # share of the clip over which the path eases back onto the guard
                     # fist roll: palm normal (-hand Z) at the guard / at full extension. Native reference: the unarmed
                     # stances hold the palms down (badpunch, ma 2strike, shoteiL start -y .83-.97) and the one straight
                     # punch (ma 2punchie) lands palm down (-y .78-.97). Palm-in guards showed the palm + open fingers to
                     # the FP camera (a claw, review 2026-10-10), so both stay palm down, a little turned in.
                     palm_guard={'R': [-0.4, -0.9, 0.0], 'L': [0.4, -0.9, 0.0]},
                     palm_strike={'R': [-0.15, -1.0, 0.0], 'L': [0.15, -1.0, 0.0]},
                     # palmar flex (deg, hand X turned toward the palm about the hand's thumb axis), guard / strike: the
                     # FP shoulders sit below and behind the eye, so a forearm reaching the view centre rises ~20 deg
                     # above the line of sight; a dead-straight hand then stands up with the (fixed, half-open) fingers
                     # curling toward the camera = a palm-up reach. A small flex puts the knuckles in front (fist read).
                     flex_guard=18.0, flex_strike=22.0,
                     strikers={'badpunch': ['L']},   # per technique striking hands (native: badpunch strikes with L only)
                     strike_min=1.5, stab='pelvis', guard_anim='ma idle1', guard_t=0.0,
                     nearclip=1.5,   # the game's FP near plane in fist mode (sheets render with it)
                     near=2.0,   # KenshiFP fist mode lowers the camera near clip to 1.5 while the fists are shown (as the crossbow, X2 g_vm_nc); 0.5 margin
                     nkeys=[4, 12],
                     sets=['wroll=0', 'edgeclamp=0', 'wfix=0', 'hroll=0', 'e1inl=0', 'hinge=0', 'elb=0'],
                     center=[0.30, 0.35], wb_max=30.0, wr_err_max=0.35, path_err_max=0.5, eye_min=2.5, above_max=0.5,
                     y_max=0.0, z_min=3.0)   # path clamps: wrist never above y_max (eye level), never nearer than z_min


def fist_cfg(cfg):
    c = dict(FIST_DEFAULTS)
    c.update(cfg.get('fists') or {})
    return c


def _clampn(v, m):
    n = float(np.linalg.norm(v))
    return v * (m / n) if n > m else v


def fist_path(tr, ref, fc, s, force=None):
    """FP wrist path of hand s from the native clip (profile model). A striking hand (wrist travels >= strike_min dm
    forward of its start) keeps the native TIMING: its extension along the native strike direction e(t) (1 = the
    furthest point) drives guard -> strike point; e < 0 (pulled back before the punch) drives guard -> chamber (down and
    back, never toward the eye); the native off-line motion is kept scaled/clamped and turned onto the FP strike line.
    A non-striking hand keeps its native motion scaled + clamped about its guard. Clamps: never above y_max, never
    nearer than z_min, eases back onto the guard over the last end_blend. Returns (positions [n,3], striker, info)."""
    W = np.array([r['wr' + s] for r in tr]) - ref[s]
    G = np.asarray(fc['guard'][s], float)
    T = np.asarray(fc['strike'][s], float) - G
    C = np.asarray(fc['chamber'][s], float)
    k = int(np.argmax(W[:, 2]))
    D = W[k]
    if (D[2] < fc['strike_min'] if force is None else not force):
        P = np.array([G + _clampn(w * fc['off_scale'], fc['off_max']) for w in W])
        striker, info = False, dict(peak=float(D[2]))
        E = np.zeros(len(W))
    else:
        n = float(np.linalg.norm(D)); d = D / n
        e = W @ d / n
        Rm = rot_between(d, T)
        P = []
        for i in range(len(W)):
            res = _clampn(Rm @ (W[i] - e[i] * n * d) * fc['res_scale'], fc['res_max'])
            ei = float(e[i])
            base = G + min(ei, 1.0) * T if ei >= 0 else G + min(-ei / fc['chamber_e'], 1.0) * C
            P.append(base + res)
        P = np.array(P)
        E = np.clip(e, 0.0, 1.0)
        striker, info = True, dict(peak=float(D[2]), u_peak=k / max(len(W) - 1, 1), e_min=float(e.min()))
    m = len(P)
    for i in range(m):
        u = i / max(m - 1, 1)
        if u > 1.0 - fc['end_blend']:
            w = (u - (1.0 - fc['end_blend'])) / fc['end_blend']; w = w * w * (3 - 2 * w)
            P[i] = (1 - w) * P[i] + w * G
            E[i] *= 1 - w
        P[i][1] = min(P[i][1], fc['y_max'])
        P[i][2] = max(P[i][2], fc['z_min'])
    return P, striker, info, E


def fist_hand(r, s, fa_to, fc, e):
    """fist hand frame: hand X on the solved forearm fa_to (straight wrist), rolled about it so the palm (-hand Z) faces
    the palm normal blended guard -> strike by the extension e (0..1). The native hand only supplies the prop axes'
    relation to the hand bone. Returns (f, u, hx)."""
    f, u, hx = straight_hand(r, s, fa_to)
    fa_n = nz(r['wr' + s] - r['el' + s])
    hz = rot_between(fa_n, fa_to) @ rot_between(r['hx' + s], fa_n) @ r['hz' + s]
    pn = nz((1 - e) * np.asarray(fc['palm_guard'][s], float) + e * np.asarray(fc['palm_strike'][s], float))
    a = nz(-hz - hx * float(hx @ -hz)); b = pn - hx * float(hx @ pn)
    if np.linalg.norm(b) >= 1e-3:
        Q = rot_between(a, nz(b))
        f, u, hx, a = Q @ f, Q @ u, Q @ hx, Q @ a
    fl = math.radians((1 - e) * float(fc.get('flex_guard', 0.0)) + e * float(fc.get('flex_strike', 0.0)))
    if abs(fl) > 1e-6:   # palmar flex: hand X toward the palm normal a, about the thumb axis hx x a
        k = nz(np.cross(hx, a))
        Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        Q = np.eye(3) + math.sin(fl) * Kx + (1 - math.cos(fl)) * Kx @ Kx
        f, u, hx = Q @ f, Q @ u, Q @ hx
    return f, u, hx


def straight_hand(r, s, fa_to):
    """the native hand frame of r (f, u, hx of side s) with the wrist straightened (hand X onto the native forearm,
    smallest turn: the twist about the forearm is kept), then carried by the smallest turn native forearm -> fa_to.
    Returns (f, u, hx)."""
    fa_n = nz(r['wr' + s] - r['el' + s])
    Q = rot_between(fa_n, fa_to) @ rot_between(r['hx' + s], fa_n)
    return Q @ r['f' + s], Q @ r['u' + s], Q @ r['hx' + s]


def _onscr(c, near, m=0.95):
    return c[2] > near and abs(c[0] / c[2]) < 1.245 * m and abs(c[1] / c[2]) < 0.70 * m


def fist_checks(fc, solved, frames, n0, key_wr, dense_err, ku, strikers, mvrows, verdict, dur):
    """NA1 rows on the solved keyed path (both arms). dur = the technique's clip length (the motion's hold after it is
    at u > 1). Returns [(name, PASS|FAIL|INFO, text)]."""
    res = []
    near = fc['near']
    sides = sorted(solved)
    rows = {s: solved[s][0][n0:] for s in sides}
    fr = {s: frames[s][n0:] for s in sides}
    n = min(len(rows[s]) for s in sides)
    T = np.array([x[0] for x in fr[sides[0]]][:n])
    U = T / max(dur, 1e-9)
    # guard: both fists (wrist + grip) on screen at the start / end
    gk = [k for k in range(n) if U[k] <= 0.02 or U[k] >= 0.98]
    bad = [(s, round(float(U[k]), 2)) for k in gk for s in sides
           if not (_onscr(np.asarray(rows[s][k][s]['wr']), near) and _onscr(np.asarray(rows[s][k][s]['pp']), near))]
    res.append(('guard_view', 'PASS' if gk and not bad else 'FAIL', 'both fists on screen at u<=.02/>=.98: %d frames%s' % (
        len(gk), (' off=' + ','.join('%s@%.2f' % b for b in bad[:6])) if bad else '')))
    # striking fist crosses the view centre
    cx, cy = fc['center']
    for s in strikers:
        best = min((abs(np.asarray(rows[s][k][s]['pp'])[0] / max(rows[s][k][s]['pp'][2], 1e-3)) +
                    abs(np.asarray(rows[s][k][s]['pp'])[1] / max(rows[s][k][s]['pp'][2], 1e-3)), k) for k in range(n))
        pp = np.asarray(rows[s][best[1]][s]['pp'])
        sx, sy = pp[0] / pp[2], pp[1] / pp[2]
        ok = abs(sx) <= cx and abs(sy) <= cy and pp[2] > near
        res.append(('strike_%s' % s, 'PASS' if ok else 'FAIL', 'fist nearest the centre x/z %.2f y/z %.2f z %.1f @u%.2f (|x|<=%.2f |y|<=%.2f)' % (
            sx, sy, pp[2], U[best[1]], cx, cy)))
    if not strikers:
        res.append(('strike', 'FAIL', 'no hand travels >= %.1f dm forward (not a punch)' % fc['strike_min']))
    # no hand at / above / behind the eye; forearm + fist not cut by the near plane while on screen
    emin, above, cut = 1e9, -1e9, []
    for k in range(n):
        for s in sides:
            A = rows[s][k][s]
            el, wr, pp = (np.asarray(A[x], float) for x in ('el', 'wr', 'pp'))
            for c in [el + (wr - el) * v for v in (0.5, 0.75, 1.0)] + [wr + (pp - wr) * v for v in (0.5, 1.0)]:
                emin = min(emin, float(np.linalg.norm(c)))
                if _onscr(c, 0.05, 1.0) and c[2] < near:
                    cut.append((s, round(float(U[k]), 2)))
            above = max(above, float(wr[1]), float(pp[1]))
    res.append(('eye', 'PASS' if emin >= fc['eye_min'] and above <= fc['above_max'] else 'FAIL',
                'forearm/fist min distance to the eye %.2f dm (>= %.1f), highest wrist/fist y %.2f dm (<= %.1f)' % (emin, fc['eye_min'], above, fc['above_max'])))
    res.append(('nearcut', 'PASS' if not cut else 'FAIL', 'on-screen forearm/fist points nearer than %.1f dm: %d%s' % (
        near, len(cut), (' at ' + ','.join('%s@%.2f' % c for c in sorted(set(cut))[:6])) if cut else '')))
    # wrist limit (PT30) and solver limits from the metricslab report
    wb = {r['side']: r['wb_max'] for r in mvrows if r['seg'] == '*all*'}
    res.append(('wrist', 'PASS' if all(v <= fc['wb_max'] for v in wb.values()) else 'FAIL',
                'wb_max %s (<= %.0f, PT30)' % (' '.join('%s %.1f' % kv for kv in sorted(wb.items())), fc['wb_max'])))
    res.append(('solver', 'PASS' if verdict['ok'] else 'FAIL', 'metricslab limits (terr, reach, ikfail, wb, fist/arm clearance)%s' % (
        (' fails=' + ','.join(verdict.get('fails', []))) if not verdict['ok'] else '')))
    # fidelity: solved wrist vs the keyed target wrist at the same clip time; keyed path vs the dense adapted path
    we = []
    for k in range(n):
        for s in sides:
            j = min(max(int(round(U[k] * (len(key_wr[s]) - 1))), 0), len(key_wr[s]) - 1)
            we.append(float(np.linalg.norm(np.asarray(rows[s][k][s]['wr']) - key_wr[s][j])))
    w95 = float(np.percentile(we, 95)) if we else float('nan')
    res.append(('reach', 'PASS' if w95 <= fc['wr_err_max'] else 'FAIL', 'solved wrist vs keyed target p95 %.2f dm (<= %.2f)' % (w95, fc['wr_err_max'])))
    res.append(('keys', 'PASS' if dense_err[0] <= fc['path_err_max'] else 'FAIL', 'keyed path vs adapted path p95 %.2f max %.2f dm (<= %.2f), key u %s' % (
        dense_err[0], dense_err[1], fc['path_err_max'], ','.join('%.2f' % x for x in ku))))
    return res


def fist_rec_checks(m, solved, frames, s, dur, t_peak, path):
    """the animlab.py recording checks on hand s's solved keyed path (synthetic recording, swing window = start ->
    the strike peak; an L hand is mirrored onto the R slot). Only churn gates a fist; arc/inline/blade/stroke read a
    sword edge/blade and hinge needs >= 3 swings + drive hinge output: INFO. Returns [(name, PASS|FAIL|INFO, text)]."""
    import copy
    rows, fr = solved[s][0], frames[s]
    if s == 'L':
        X = np.array([-1.0, 1.0, 1.0])
        mir = lambda v: list(np.asarray(v, float) * X) if v is not None and len(v) == 3 else v
        R2 = []
        for r in rows:
            q = copy.deepcopy(r)
            q['R'] = {k: mir(v) for k, v in r['L'].items()}; q['L'] = {k: mir(v) for k, v in r['R'].items()}
            for k in ('eye', 'up', 'fw'):
                q[k] = mir(r[k])
            q['rt'] = list(-np.asarray(mir(r['rt'])))
            R2.append(q)
        rows = R2
        fr = [(t, c, mir(p), mir(f), mir(u), o, sg) for (t, c, p, f, u, o, sg) in fr]
    mm = dict(m, native=dict(anim=m['name'], phases=[0.0, t_peak * 0.4, t_peak * 0.7, t_peak, min(dur, t_peak + 0.05 * dur)]))
    rec = synth_rec(mm, rows, fr, path)
    out = []
    for k, (v, ln) in run_checks(rec, True).items():
        out.append(('%s_%s' % (k, s), v if k == 'churn' else 'INFO', ln[:160]))
    return out


def _crosshair(img):
    img = np.array(img, copy=True)
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    img[cy - 1:cy + 1, cx - 12:cx - 4] = 230; img[cy - 1:cy + 1, cx + 4:cx + 12] = 230
    img[cy - 12:cy - 4, cx - 1:cx + 1] = 230; img[cy + 4:cy + 12, cx - 1:cx + 1] = 230
    return img


def fist_render(a, cfg, N, an, pose_path, fc, ku, t_end, out, tag, n=12, orbit=60.0):
    """labelled sheets, full-resolution 800x450 tiles (no downscale): FP zoom 0 (visual lab, both arms solved, crosshair =
    screen centre) and zoom 25 (what the game shows zoomed out: KenshiFP fades the viewmodel out beyond zf1 = 8 dm, so
    the body plays the native third-person clip; camera 25 dm from the eye orbited `orbit` deg round to the side so the
    arm motion is not hidden behind the body)."""
    import render as VR
    vcfg = VR.load_cfg(a.visual, 'none')
    vcfg['near'] = float(fc.get('nearclip', vcfg.get('near', 0.5)))
    rig = VR.Rig(vcfg)
    Pf = VR.load_pose(pose_path)
    T = np.array([f['t'] for f in Pf])
    ts = [t_end * i / (n - 1) for i in range(n)]
    z0, z25 = [], []
    R3 = Render3P(N, an, None, ('z25',), (800, 450), 0.0, an.length)
    E, (Rx, U, D) = R3.cams['z25']
    pel = R3.pel0 + np.array([0.0, 9.0, 0.0])   # orbit about the chest height above the pelvis
    th = math.radians(orbit)
    rot = lambda v: np.array([v[0] * math.cos(th) + v[2] * math.sin(th), v[1], -v[0] * math.sin(th) + v[2] * math.cos(th)])
    R3.cams['z25'] = (pel + rot(E - pel), (rot(Rx), rot(U), rot(D)))
    for t in ts:
        i = int(np.argmin(np.abs(T - t)))
        img, _, _ = VR.render_frame(rig, Pf[i], (800, 450), np.full((450, 800, 3), 40, np.float32))
        u = t / max(t_end, 1e-9)
        kmark = ' KEY' if any(abs(u - k) < 0.5 / (n - 1) for k in ku) else ''
        z0.append(label(_crosshair(img), ['%s  FP zoom 0 (lab: KenshiFP solver, both arms)' % an.name, 't %.2f s  u %.2f%s' % (t, u, kmark), tag]))
        z25.append(R3.frame(t * an.length / max(t_end, 1e-9), ['zoom 25: viewmodel faded out, native 3P clip', 'camera orbit %.0f deg' % orbit, tag]))
    sheet(z0, 4, os.path.join(out, 'sheet-z0.png'), 1.0)
    sheet(z25, 4, os.path.join(out, 'sheet-z25.png'), 1.0)
    return os.path.join(out, 'sheet-z0.png'), os.path.join(out, 'sheet-z25.png')


def cmd_fists(a):
    """per technique: native clip -> both-hands trajectory (pelvis-stabilised, solver grip calibrated) -> profile model
    (fist_path: native timing, FP guard/strike/chamber geometry) -> straight wrist on the solved forearm (straight_hand)
    -> shared key times fitted on the game's keyed path -> keyed path solved on the body through the drive adapter (both
    arms, natural 2-bone IK: elb=0, sword roll features off) -> NA1 checks + key tables (VP, KenshiFP format) + sheets."""
    import metricslab as ML
    cfg = load_cfg(a.config); N = Native(cfg, a.skeleton); fc = fist_cfg(cfg)
    body = body_ref(a.body, a.body_frame)
    extra = shlex.split(a.args or '') + sum([['--set', x] for x in fc['sets']], [])
    os.makedirs(a.out, exist_ok=True)
    ga = N.anim(a.guard_anim or fc['guard_anim']); gt = fc['guard_t'] if a.guard_t is None else a.guard_t
    names = [x.strip() for x in a.anim.split(',') if x.strip()]

    def traj(an, ts, grip):
        return trajectory(N, an, ts, body, 'fixed', 'shoulder', 'hand', None, 'R', ts[0], 0.0, None, 1.0, fc['stab'], grip)

    def motion(name, keys):
        return dict(name=name, fps=60, interp='linear', preroll=0.5, hold=0.3, body=dict(rec=a.body, frame=a.body_frame),
                    hands={s: dict(weapon='sword', blade=1.0, keys=keys[s]) for s in 'RL'},
                    limits=dict(head_min=0.0, clip_frames=10 ** 6))

    def solve(m, out):
        os.makedirs(out, exist_ok=True)
        mp = os.path.join(out, 'motion.json')
        with open(mp, 'w') as f:
            json.dump(m, f, indent=1)
        m = ML.load_motion(mp)
        solved, frames = ML.run_motion(m, a.adapter, a.body, a.body_frame, out, extra, True)
        return m, solved, frames

    def key(t, p, f, u):
        return dict(t=round(float(t), 5), p=[float(x) for x in p], f=[float(x) for x in f], u=[float(x) for x in u])

    def solved_fa(sv, frm, times):
        """per side: solved forearm direction at each of `times` (motion clock)."""
        n0 = sum(1 for x in frm['R'] if x[0] < -1e-9)
        Ta = np.array([x[0] for x in frm['R']])
        out = {s: [] for s in 'RL'}
        for t in times:
            k = max(int(np.argmin(np.abs(Ta - t))), n0)
            for s in 'RL':
                A = sv[s][0][k][s]
                out[s].append(nz(np.asarray(A['wr'], float) - np.asarray(A['el'], float)))
        return out
    # 1. the solver's grip offset (one calibration solve on the guard clip, then fixed)
    gts = times_of(ga.length, 10, gt, min(ga.length, gt + 0.5))
    gtr = traj(ga, gts, None)
    keys = {s: [key(r['t'] - gts[0], r['p' + s], r['f' + s], r['u' + s]) for r in gtr] for s in 'RL'}
    _, sv, frm = solve(motion('grip-cal', keys), os.path.join(a.out, '_cal'))
    n0 = sum(1 for x in frm['R'] if x[0] < -1e-9)
    grip = {s: measure_grip(sv[s][0], s, n0) for s in 'RL'}
    # 2. guard pose: the FP guard wrists, hands straight on the solved forearm (native unarmed stance twist)
    gref = traj(ga, [gt], grip)[0]
    gfu = {s: fist_hand(gref, s, nz(gref['wr' + s] - gref['el' + s]), fc, 0.0)[:2] for s in 'RL'}
    G = {s: np.asarray(fc['guard'][s], float) for s in 'RL'}
    gk = {s: [key(t, G[s] - grip_vec(gfu[s][0], gfu[s][1], grip[s]), gfu[s][0], gfu[s][1]) for t in (0.0, 0.2)] for s in 'RL'}
    _, sv, frm = solve(motion('guard', gk), os.path.join(a.out, '_guard'))
    fa = solved_fa(sv, frm, [0.1])
    gpose = {}
    for s in 'RL':
        f, u, _ = fist_hand(gref, s, fa[s][0], fc, 0.0)
        gpose[s] = pose_norm(G[s] - grip_vec(f, u, grip[s]), f, u)
    summary = []
    tables = ['/* KenshiFP fist key tables (candidate, NOT installed): animlab native.py fists, %s.' % ', '.join(names),
              ' * Poses VP(p, f, u) in camera numbers (dm), KenshiFP prop target convention for the weapon class 0 path; L rows',
              ' * are in the drive\'s --side L convention (mirrored grip, as dual wield). Guard = start/end pose of every technique.',
              ' * Key u = per technique (the swing clock runs over the native clip length / anim speed mult).',
              ' * Wrists straight (hand X on the solved forearm); fingers: the game hand mesh has no finger bones (fixed hand).',
              ' * Solver settings the lab used: fp_vm set %s */' % ' '.join(fc['sets'])]
    tables.append('static VmPose g_vm_fist_guard[2] = { %s,   /* R */\n                                     %s }; /* L */' % (vp(*gpose['R']), vp(*gpose['L'])))
    for name in names:
        an = N.anim(name)
        tag = name.replace(' ', '_')
        od = os.path.join(a.out, tag)
        os.makedirs(od, exist_ok=True)
        ts = times_of(an.length, a.key_fps, 0.0, an.length)
        tr = traj(an, ts, grip)
        ref = {s: tr[0]['wr' + s] for s in 'LR'}
        dur = ts[-1] - ts[0]
        paths, strikers, info = {}, [], {}
        sov = (fc.get('strikers') or {}).get(name)
        for s in 'RL':
            paths[s], st, info[s], ew = fist_path(tr, ref, fc, s, None if sov is None else s in sov)
            info[s]['ew'] = ew
            if st:
                strikers.append(s)
        strikers.sort()
        # hands straight: first on the native forearm (any orientation: the solver's elbow does not depend on it with
        # elb=0, the wrist is held), solve, then on the solved forearm
        dk = {s: [] for s in 'RL'}
        for i, r in enumerate(tr):
            for s in 'RL':
                f, u, _ = fist_hand(r, s, nz(r['wr' + s] - r['el' + s]), fc, info[s]['ew'][i])
                dk[s].append(key(r['t'] - ts[0], paths[s][i] - grip_vec(f, u, grip[s]), f, u))
        _, sv, frm = solve(motion('align', dk), os.path.join(a.out, '_align'))
        fa = solved_fa(sv, frm, [r['t'] - ts[0] for r in tr])
        shutil.rmtree(os.path.join(a.out, '_align'), ignore_errors=True)
        dense = {s: [] for s in 'RL'}
        for i, r in enumerate(tr):
            for s in 'RL':
                f, u, _ = fist_hand(r, s, fa[s][i], fc, info[s]['ew'][i])
                p = paths[s][i] - grip_vec(f, u, grip[s])
                dense[s].append(((r['t'] - ts[0]) / dur,) + tuple(pose_norm(p, f, u)))
        for nk in range(fc['nkeys'][0], fc['nkeys'][1] + 1):
            idx, ku, e95, emax = fit_keys(dense, gpose, gpose, nkeys=nk)
            if e95 <= fc['path_err_max'] * 0.8:
                break
        kp = {s: [dense[s][k][1:] for k in idx] for s in 'RL'}
        # keyed path as the game would play it, dense at 60 fps over the clip length
        nfr = max(2, int(round(dur * 60)))
        mkeys, key_wr = {s: [] for s in 'RL'}, {s: [] for s in 'RL'}
        for i in range(nfr + 1):
            u = i / float(nfr)
            for s in 'RL':
                p, f, uu = keyed_at(gpose[s], kp[s], gpose[s], ku, u)
                mkeys[s].append(dict(t=round(u * dur, 5), p=[round(x, 4) for x in p], f=[round(x, 5) for x in f], u=[round(x, 5) for x in uu]))
                key_wr[s].append(p + grip_vec(f, uu, grip[s]))
        m, solved, frames = solve(motion('fist-' + tag, mkeys), od)
        P, rows, v = ML.evaluate(m, solved, frames)
        with open(os.path.join(od, 'report.txt'), 'w') as f:
            ML.print_report(m, rows, v, f)
        n0 = sum(1 for x in frames['R'] if x[0] < -1e-9)
        res = fist_checks(fc, solved, frames, n0, key_wr, (e95, emax), ku, strikers, rows, v, dur)
        for s in strikers:
            res += fist_rec_checks(m, solved, frames, s, dur, info[s]['u_peak'] * dur, os.path.join(od, 'check_%s.rec.txt' % s))
        bad = [r[0] for r in res if r[1] == 'FAIL']
        line = 'RESULT fist-%s %s strikers=%s keys=%d %s' % (tag, 'PASS' if not bad else 'FAIL', ''.join(strikers) or '-', len(ku),
               ' '.join('%s=%s' % (r[0], r[1]) for r in res if r[1] != 'INFO')) + ((' fails=' + ','.join(bad)) if bad else '')
        with open(os.path.join(od, 'checks.txt'), 'w') as f:
            for r in res:
                f.write('%-9s %-4s %s\n' % r)
            f.write(line + '\n')
        for r in res:
            if r[1] != 'INFO':
                print('  %-9s %-4s %s' % r)
        print(line)
        summary.append(line)
        cid = ''.join(c if c.isalnum() else '_' for c in an.name.lower())
        tables.append('/* %s (native %.2f s; strikers %s; key path p95 %.2f dm; %s) */' % (an.name, an.length, ''.join(strikers) or '-', e95, 'PASS' if not bad else 'FAIL ' + ','.join(bad)))
        tables.append('static float g_vm_fist_u_%s[%d] = { 0.0f, %s, 1.0f };' % (cid, len(ku) + 2, ', '.join('%.3ff' % x for x in ku)))
        tables.append('static VmPose g_vm_fist_%s[2][%d] = {\n    { %s },   /* R */\n    { %s } }; /* L */' % (
            cid, len(ku), ',\n      '.join(vp(*k) for k in kp['R']), ',\n      '.join(vp(*k) for k in kp['L'])))
        with open(os.path.join(od, 'keys.json'), 'w') as f:
            json.dump(dict(anim=an.name, length=an.length, ku=ku, guard={s: [list(map(float, x)) for x in gpose[s]] for s in 'RL'},
                           keys={s: [[list(map(float, x)) for x in k] for k in kp[s]] for s in 'RL'},
                           info={s: {k: v for k, v in info[s].items() if k != 'ew'} for s in 'RL'},
                           strikers=strikers, near=fc['near'], grip={s: grip[s].tolist() for s in 'RL'}, sets=fc['sets'], result=line), f, indent=1)
        if not a.no_video:
            s0, s25 = fist_render(a, cfg, N, an, os.path.join(od, 'pose.txt'), fc, ku, dur, od, 'candidate %s' % ('PASS' if not bad else 'FAIL'))
            print('  sheets %s %s' % (s0, s25))
    with open(os.path.join(a.out, 'fist_keys.inc'), 'w') as f:
        f.write('\n'.join(tables) + '\n')
    for d in ('_cal', '_guard'):
        shutil.rmtree(os.path.join(a.out, d), ignore_errors=True)
    print('keys %s' % os.path.join(a.out, 'fist_keys.inc'))
    return 0 if all(' PASS ' in x for x in summary) else 1


# ---------------- catalogue ----------------
CATS = (('unarmed', 5), ('katanas', 0), ('sabre', 1), ('hackers', 4), ('heavy weapons', 3), ('blunt', 2), ('polearm', 8))
SKILL_CATEGORY = {0: 'katanas', 1: 'sabre', 2: 'blunt', 3: 'heavy weapons', 4: 'hackers', 5: 'unarmed', 6: 'crossbow',
                  7: 'turret', 8: 'polearm'}   # weapon item 'skill category' (KEP ItemExtension / WeaponCategory)


def fcs_read(path):
    """minimal Kenshi FCS (.base/.mod) reader: records with type, name, sid, bools, floats, ints, strings."""
    import struct
    with open(path, 'rb') as fh:
        b = fh.read()
    p = [0]

    def i():
        v = struct.unpack_from('<i', b, p[0])[0]; p[0] += 4; return v

    def f():
        v = struct.unpack_from('<f', b, p[0])[0]; p[0] += 4; return v

    def s():
        n = i(); v = b[p[0]:p[0] + n].decode('utf-8', 'replace'); p[0] += n; return v
    ft = i()
    if ft == 17:
        hs = i(); p[0] += hs   # header size (read first: `p[0] += i()` adds to the pre-read offset)
    elif ft == 16:
        i(); s(); s(); s(); s()
    else:
        raise ValueError('%s: FCS file type %d' % (path, ft))
    i(); n = i(); out = []
    for _ in range(n):
        i()
        r = dict(type=i(), id=i(), name=s(), sid=s()); i()
        r['bools'] = {}
        for _ in range(i()):
            k = s(); r['bools'][k] = b[p[0]] != 0; p[0] += 1
        r['floats'] = {s(): f() for _ in range(i())}
        r['ints'] = {s(): i() for _ in range(i())}
        for _ in range(i()):
            s(); p[0] += 12
        for _ in range(i()):
            s(); p[0] += 16
        r['strings'] = {s(): s() for _ in range(i())}
        r['files'] = {s(): s() for _ in range(i())}
        for _ in range(i()):
            s()
            for _ in range(i()):
                s(); p[0] += 12
        for _ in range(i()):
            s(); s(); p[0] += 28
            for _ in range(i()):
                s()
        out.append(r)
    return out


def game_data(cfg, files=None):
    files = files or [gpath(cfg, x) for x in cfg.get('game_data', ['data/gamedata.base'])]
    db = {}
    for fp in files:
        if not os.path.exists(fp):
            continue
        for r in fcs_read(fp):
            c = db.get(r['sid'])
            if c is None:
                db[r['sid']] = r; continue
            for k in ('bools', 'floats', 'ints', 'strings', 'files'):
                c[k].update(r[k])
            if r['name']:
                c['name'] = r['name']
    return db


T_ITEM_WEAPON, T_ANIMATION, T_COMBAT_TECHNIQUE = 2, 24, 17


def catalog(N, db):
    techs, anims, weapons = [], [], []
    for r in db.values():
        if r['bools'].get('REMOVED'):
            continue
        if r['type'] == T_COMBAT_TECHNIQUE:
            techs.append(r)
        elif r['type'] == T_ANIMATION:
            anims.append(r)
        elif r['type'] == T_ITEM_WEAPON and 'skill category' in r['ints']:
            weapons.append(r)
    return techs, anims, weapons


def cmd_catalog(a):
    cfg = load_cfg(a.config); N = Native(cfg, a.skeleton)
    db = game_data(cfg, a.data)
    techs, anims, weapons = catalog(N, db)
    have = {k.lower(): k for k in N.anims}
    L = []
    L.append('# Native animation catalogue (%s: %d animations)' % (os.path.basename(N.path), len(N.anims)))
    L.append('')
    L.append('Generated by `tools/animlab/native.py catalog` from the game data (%s). How the game picks: a weapon item\'s '
             '`skill category` (0 katanas, 1 sabre, 2 blunt, 3 heavy weapons, 4 hackers, 5 unarmed, 6 crossbow, 7 turret, '
             '8 polearm) selects its WeaponCategory; `CharStats::chooseAttacks` scores every COMBAT_TECHNIQUE whose category '
             'flag is set and whose min/max skill, max encumbrance and prone state fit (score ~ distance fit x medical x '
             '`chance`; x0.02 under `attack distance min vs static`, x0.2 for the same move twice; KEP AnimationExtension.cpp '
             'reimplements it). Blocks/dodges are techniques with `is block`/`is dodge`. Stances/idles/walks are ANIMATION '
             'records with the same category flags (layer upper/all, `is combat mode`, `has weapon L/R`). Times: native '
             'clip length; the game plays attacks at `anim speed mult` x the skill/attack-speed factor (not modelled). '
             '"missing" = the technique names an animation this skeleton does not have (animal skeletons, or mod-only).' % ', '.join(
                 os.path.basename(x) for x in (a.data or cfg.get('game_data', ['data/gamedata.base']))))
    L.append('')
    by = {c: [] for c, _ in CATS}
    other = []
    for r in sorted(techs, key=lambda r: r['name'].lower()):
        cats = [c for c, _ in CATS if r['bools'].get(c)]
        for c in cats:
            by[c].append(r)
        if not cats:
            other.append(r)
    used = set()
    for c, k in CATS:
        wl = sorted({w['name'] for w in weapons if w['ints'].get('skill category') == k})
        L.append('## %s (skill category %d)' % (c, k))
        L.append('')
        if wl:
            L.append('Weapons (%d): %s' % (len(wl), ', '.join(wl[:25]) + (' ...' if len(wl) > 25 else '')))
            L.append('')
        L.append('| technique | animation | length s | speed | kind | arms | skill | dist | hits |')
        L.append('|---|---|---|---|---|---|---|---|---|')
        for r in by[c]:
            an = r['strings'].get('anim name', '')
            used.add(an.lower())
            ln = '%.2f' % N.anims[have[an.lower()]].length if an.lower() in have else 'missing'
            b = r['bools']; fl = r['floats']; it = r['ints']
            kind = 'dodge' if b.get('is dodge') else 'block' if b.get('is block') else 'attack'
            arms = ('R' if b.get('use R arm') else '') + ('L' if b.get('use L arm') else '') or '-'
            L.append('| %s | %s | %s | %.2f | %s%s | %s | %g..%g | %g | %d |' % (r['name'], an, ln, fl.get('anim speed mult', 1), kind,
                     ' (disabled)' if b.get('disabled') else '', arms, fl.get('min skill', -100), fl.get('max skill', 999),
                     fl.get('attack distance', 0), it.get('num techniques', 1)))
        st = sorted({(r['strings'].get('anim name', ''), r['name']) for r in anims if r['bools'].get(c) and r['ints'].get('is combat mode')
                     and not r['bools'].get('disabled')})
        if st:
            L.append('')
            L.append('Combat-mode stances/idles: ' + ', '.join('%s (%s)' % (x, y) if x != y else x for x, y in st))
        L.append('')
    L.append('## techniques without a weapon category (animals)')
    L.append('')
    L.append(', '.join('%s -> %s' % (r['name'], r['strings'].get('anim name', '')) for r in other))
    L.append('')
    ref = {r['strings'].get('anim name', '').lower() for r in anims} | used
    un = sorted(n for n in N.anims if n.lower() not in ref)
    L.append('## animations in the skeleton not referenced by any technique or ANIMATION record (%d)' % len(un))
    L.append('')
    L.append(', '.join('%s (%.2f)' % (n, N.anims[n].length) for n in un))
    L.append('')
    txt = '\n'.join(L)
    if a.o:
        with open(a.o, 'w') as f:
            f.write(txt)
        print('%s: %d techniques, %d animation records, %d weapons' % (a.o, len(techs), len(anims), len(weapons)))
    else:
        print(txt)
    return 0


def technique_cats(cfg, anim_name, db=None):
    db = db if db is not None else game_data(cfg)
    return sorted({c for r in db.values() if r['type'] == T_COMBAT_TECHNIQUE and r['strings'].get('anim name', '').lower() == anim_name.lower()
                   for c, _ in CATS if r['bools'].get(c)})


# ---------------- CLI ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)

    def common(p, anim=True):
        p.add_argument('--config', required=True); p.add_argument('--skeleton', help='override the config skeleton')
        if anim:
            p.add_argument('anim')
        return p

    def trajopts(p):
        p.add_argument('--weapon', help='config weapon name or none (default: none = fists, target hand)')
        p.add_argument('--body', help='FP body recording (shoulders, head offset, pitch)'); p.add_argument('--body-frame', type=int, default=100)
        p.add_argument('--eye', choices=('fixed', 'head'), default='fixed', help='--stab world only: fixed = eye at the clip start; head = follows the head bone')
        p.add_argument('--stab', choices=('torso', 'pelvis', 'world'), default='torso', help='torso: arms relative to the chest (body lean/twist/steps removed); world: as a world-fixed camera sees it')
        p.add_argument('--anchor', choices=ANCHORS, default='fit', help='framing: fit (scan a lift about the shoulder), ready (start grip onto the body grip), shoulder (translate only), none (raw eye frame)')
        p.add_argument('--lift', type=float, help='explicit lift about the shoulder, deg (overrides fit/ready)'); p.add_argument('--gain', type=float, default=1.0, help='scale positions about the shoulder')
        p.add_argument('--target', choices=('weapon', 'hand'), help='weapon: follow the native prop bone; hand: the native hand (default: weapon if armed)')
        p.add_argument('--phases', type=lambda s: tuple(float(x) for x in s.split(',')), help='t_top,t_end (s, native time): override the detected stroke')
        p.add_argument('--from', dest='from_t', type=float); p.add_argument('--to', dest='to_t', type=float)
        p.add_argument('--speed', type=float, default=1.0, help='playback speed (technique anim speed mult, e.g. 1.4)')
        p.add_argument('--key-fps', type=float, default=30.0); p.add_argument('--yaw', type=float, default=0.0)
        p.add_argument('--off-hand', type=lambda s: s.lower() in ('1', 'yes', 'on', 'true'), help='off hand follows the native left wrist (default: weapon hands RL)')
        p.add_argument('--name')

    common(sp.add_parser('list'), False).add_argument('--filter')
    p = common(sp.add_parser('sample')); p.add_argument('--t', type=float); p.add_argument('--fps', type=float, default=10)
    p.add_argument('--bones'); p.add_argument('--loop', action='store_true')
    p = common(sp.add_parser('render')); p.add_argument('-o', required=True); p.add_argument('--weapon', default='none')
    p.add_argument('--views', default='side,front'); p.add_argument('--fps', type=float, default=30); p.add_argument('--size', default='480x540')
    p.add_argument('--mp4'); p.add_argument('--sheet'); p.add_argument('--sheet-n', type=int, default=12); p.add_argument('--sheet-cols', type=int, default=4)
    p.add_argument('--from', dest='from_t', type=float); p.add_argument('--to', dest='to_t', type=float); p.add_argument('--speed', type=float, default=1.0)
    p = common(sp.add_parser('traj')); trajopts(p); p.add_argument('-o', required=True)
    p = common(sp.add_parser('adapt')); trajopts(p); p.add_argument('-o', required=True)
    p = common(sp.add_parser('run')); trajopts(p); p.add_argument('--adapter', required=True); p.add_argument('--out', required=True)
    p.add_argument('--args', default='--quiet'); p.add_argument('--visual', help='visual lab config (FP render)'); p.add_argument('--no-video', action='store_true')
    p.add_argument('--video-fps', type=int, default=30); p.add_argument('--size', default='400x450'); p.add_argument('--mp4')
    p = common(sp.add_parser('catalog'), False); p.add_argument('--data', nargs='*'); p.add_argument('-o')
    p = common(sp.add_parser('fists')); p.add_argument('--body', required=True); p.add_argument('--body-frame', type=int, default=100)
    p.add_argument('--adapter', required=True); p.add_argument('--out', required=True); p.add_argument('--args', default='--quiet')
    p.add_argument('--visual', help='visual lab config (sheets)'); p.add_argument('--no-video', action='store_true')
    p.add_argument('--guard-anim'); p.add_argument('--guard-t', type=float); p.add_argument('--key-fps', type=float, default=30.0)
    a = ap.parse_args(argv)
    if a.cmd == 'run' and not a.no_video and not a.visual:
        ap.error('run: --visual VCFG (or --no-video)')
    if a.cmd == 'fists' and not a.no_video and not a.visual:
        ap.error('fists: --visual VCFG (or --no-video)')
    if a.cmd in ('run',) and not a.body:
        ap.error('run: --body REC')
    return {'list': cmd_list, 'sample': cmd_sample, 'render': cmd_render, 'traj': cmd_traj, 'adapt': cmd_adapt,
            'run': cmd_run, 'catalog': cmd_catalog, 'fists': cmd_fists}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
