#!/usr/bin/env python3
"""render.py -- animation lab, phase 3 (VISUAL LAB): render first-person arms + weapon from solved/recorded poses.

Meshes and skeleton are read from the game install at run time (Ogre binary, tools/animlab/visual/ogre.py); nothing is
committed. Poses come from joint positions (camera numbers: x right, y up, z forward, dm):
  render.py frames <pose> --config CFG -o DIR [--every N] [--from A] [--to B] [--mp4 out.mp4] [--size 800x450]
  render.py still  <pose> --config CFG -o out.png [--frame N] [--bg game.png] [--size 1600x900]
  render.py compare <state.txt> <game.png> --config CFG -o side.png     side by side + overlay vs a real game frame
  --weapons R,L overrides the config weapon_sides (which hands draw a weapon mesh).
<pose> = a game/replay recording (`fp_vm rec dump`), a phase-2 drive/merged pose file (metricslab pose.txt /
solved_*.txt) or an `fp_vm state` dump (key=value line, one frame); the format is detected.

CFG (JSON, solver/game specific; KenshiFP's is components/KenshiFP/animlab/visual.json):
  game_dir, skeleton, body_mesh, weapon_mesh {"R": path, "L": path}, weapon_sides ["R"], prop_axes [[f,u] per class]
  (prop-local axis codes 1..3 = X,Y,Z, negative = flipped), prop_local_q {"0": [w,x,y,z], "1": [...]} (hand -> prop
  rotation per weapon class), prop_roll_deg {"0": deg} (extra roll about the blade axis), prop_mirror {"L": {q_sign, roll_sign, roll_add}} (off hand: prop local q * q_sign, roll -> roll * roll_sign + roll_add), weapon_offset {"R": [x,y,z]}
  (weapon mesh origin in prop-local dm), bones {"L": [clavicle, upperarm, forearm, hand, prop], "R": [...]}, fov [tan_x, tan_y],
  near (dm), colors.
Posing: upper arm / forearm X along the solved bone, roll from the elbow hinge (sign from the bind pose: flexion
toward the toes); hand = prop pose x prop_local^-1 when the side holds a prop pose, else the forearm with the bind
wrist; bone length change = scale along the bone; every other bone follows the torso (shoulder line + up).
Camera numbers are a mirrored (left-handed) frame: posing runs in (-x, y, z) and projects back.
"""
import argparse, json, math, os, subprocess, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ogre  # noqa: E402

FLIP = np.array([-1.0, 1.0, 1.0])


def nz(v):
    v = np.asarray(v, dtype=float); n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def frame(X, Zhint):
    X = nz(X); Z = nz(Zhint - X * np.dot(Zhint, X)); Y = np.cross(Z, X)
    return np.column_stack([X, Y, Z])


def axis(code):
    v = np.zeros(3); v[abs(code) - 1] = 1.0 if code > 0 else -1.0
    return v


# ---------------- pose sources ----------------
def _v3(s): return np.array([float(x) for x in s.split(',')])


def parse_state(path):
    kv = {}
    for tok in open(path).read().split():
        if '=' in tok:
            k, v = tok.split('=', 1); kv[k] = v
    f = dict(t=0.0, up=None, sides={}, cls=0 if kv.get('class', 'melee') == 'melee' else 1)
    wh = 'R' if kv.get('hand', 'R') == 'R' else 'L'
    for s in 'LR':
        d = dict(sh=_v3(kv[s + 'sh']), el=_v3(kv[s + 'el']), wr=_v3(kv[s + 'wr']))
        if s == wh:
            d.update(pp=_v3(kv['mp']), pf=_v3(kv['mf']), pu=_v3(kv['mu']))
            if 'mh' in kv:
                d['hx'] = _v3(kv['mh'])
        f['sides'][s] = d
    if 'nk' in kv and 'sp' in kv:
        f['up'] = nz(_v3(kv['nk']) - _v3(kv['sp']))
    return [f]


def parse_rec(path):
    import recfmt
    F = recfmt.parse(path).frames
    out = []
    for i in range(len(F) - 1):
        a, b = F[i], F[i + 1]
        J = {k: np.array(recfmt.remap(b[k], a, b, 1)) for k in recfmt.JOINTS}
        wh = 'R'
        f = dict(t=a['t'], i=i, cls=a['cls'], w=a['w'], zf=b.get('zf', 1.0), sides={},
                 up=np.array((a['rt'][1], a['up'][1], a['fw'][1])) if a['rt'] else None)
        for s in 'LR':
            f['sides'][s] = dict(sh=J[s + 'sh'], el=J[s + 'el'], wr=J[s + 'wr'])
        f['sides'][wh].update(pp=np.array(recfmt.remap(b['mp'], a, b, 1)), pf=np.array(recfmt.remap(b['mf'], a, b, 0)),
                              pu=np.array(recfmt.remap(b['mu'], a, b, 0)))
        if b.get('mh'):
            f['sides'][wh]['hx'] = np.array(recfmt.remap(b['mh'], a, b, 0))
        out.append(f)
    return out


def parse_drive(path):
    import metricslab
    rows, _ = metricslab.parse_solved(path)
    out = []
    for r in rows:
        f = dict(t=r['t'], i=r['i'], cls=0, sides={}, up=np.array((r['rt'][1], r['up'][1], r['fw'][1])))
        for s in 'LR':
            a = r[s]
            f['sides'][s] = dict(sh=np.array(a['sh']), el=np.array(a['el']), wr=np.array(a['wr']), hx=np.array(a['hx']),
                                 pp=np.array(a['pp']), pf=np.array(a['pf']), pu=np.array(a['pu']))
        out.append(f)
    return out


def load_pose(path):
    with open(path) as fh:
        head = fh.read(4096)
    if head.startswith('vm ') or ' Lsh=' in head:
        return parse_state(path)
    first = next((l for l in head.splitlines() if l and not l.startswith('#')), '')
    g = first.split('|')
    if len(g) == 5 and len(g[0].split()) == 2:
        return parse_drive(path)
    return parse_rec(path)


# ---------------- rig ----------------
class Rig:
    def __init__(self, cfg):
        self.cfg = cfg
        gd = cfg.get('game_dir', '')
        self.sk = ogre.load_skeleton(os.path.join(gd, cfg['skeleton']))
        body = ogre.load_mesh(os.path.join(gd, cfg['body_mesh']))
        self.B = cfg['bones']
        arm = {self.sk.by_name[n].h for s in 'LR' for n in self.B[s][1:4]}
        P, T, W = [], [], []
        nb = max(self.sk.bones) + 1
        for pos, _, tris, bw in body.triangles():
            wt = np.zeros((len(pos), nb))
            for v, b, w in bw:
                if b < nb:
                    wt[v, b] += w
            wt /= np.maximum(wt.sum(1, keepdims=True), 1e-9)
            keep = np.array([max(wt[t][:, sorted(arm)].sum(1)) >= 0.5 for t in tris])
            off = sum(len(p) for p in P)
            P.append(pos); W.append(wt); T.append(tris[keep] + off)
        self.P, self.W, self.T = np.vstack(P), np.vstack(W), np.vstack(T)
        used = np.unique(self.T)
        self.used_bones = [h for h in range(nb) if self.W[used, h].max() > 0] if len(used) else []
        self.weap = {}
        for s, p in (cfg.get('weapon_mesh') or {}).items():
            m = ogre.load_mesh(os.path.join(gd, p))
            wp, wt = [], []
            for pos, _, tris, _ in m.triangles():
                wt.append(tris + sum(len(x) for x in wp)); wp.append(pos)
            self.weap[s] = (np.vstack(wp), np.vstack(wt))
        # hinge sign: flexion turns the forearm toward the toes (bind facing)
        b = self.sk.by_name
        toe = [n for n in b if n.endswith('Toe0')]
        foot = [n for n in b if n.endswith('Foot')]
        F = nz((b[toe[0]].dpos - b[foot[0]].dpos) * np.array([1, 0, 1])) if toe and foot else np.array([0, 0, 1.0])
        self.hinge = {}
        for s in 'LR':
            fa = b[self.B[s][2]]; R = ogre.qmat(fa.dq)
            self.hinge[s] = 1.0 if np.dot(np.cross(R[:, 0], F), R[:, 2]) >= 0 else -1.0
        self.facing = F

    def bind(self, name):
        bo = self.sk.by_name[name]
        return bo.dpos, ogre.qmat(bo.dq)

    def pose(self, f):
        """per bone handle: (P_now, A) with v_now = P_now + A (v - P_bind), all in flipped (right-handed) space."""
        cfg, sk, B = self.cfg, self.sk, self.B
        S = {s: {k: (v * FLIP if isinstance(v, np.ndarray) else v) for k, v in f['sides'][s].items()} for s in 'LR'}
        up = nz(f['up'] * FLIP) if f.get('up') is not None else np.array([0, 1.0, 0])
        bL, bR = self.bind(B['L'][1])[0], self.bind(B['R'][1])[0]
        Rb = frame(bR - bL, np.array([0, 1.0, 0]))
        Rb = np.column_stack([Rb[:, 0], Rb[:, 2], -Rb[:, 1]]) if False else Rb
        Xn = S['R']['sh'] - S['L']['sh']
        Rn = frame(Xn, up)
        Rbody = Rn @ Rb.T
        mid_b, mid_n = (bL + bR) / 2, (S['L']['sh'] + S['R']['sh']) / 2
        M = {}
        for h, bo in sk.bones.items():   # default: rigid with the torso
            M[h] = (mid_n + Rbody @ (bo.dpos - mid_b), Rbody @ np.eye(3))
        for s in 'LR':
            d = S[s]
            names = B[s]
            ua, fa, ha = (sk.by_name[n] for n in names[1:4])
            Xu, Xf = d['el'] - d['sh'], d['wr'] - d['el']
            hz = np.cross(nz(Xu), nz(Xf))
            if np.linalg.norm(hz) < 0.05:   # straight arm: keep the torso's idea of the hinge
                hz = Rbody @ ogre.qmat(fa.dq)[:, 2] * self.hinge[s]
            Z = self.hinge[s] * nz(hz)
            for bo, X, j0, j1 in ((ua, Xu, d['sh'], d['el']), (fa, Xf, d['el'], d['wr'])):
                Rnow = frame(X, Z); Rbd = ogre.qmat(bo.dq)
                L_b = np.linalg.norm(sk.bones[[c.h for c in sk.children(bo.h) if c.name in names][0]].dpos - bo.dpos)
                sc = np.diag([np.linalg.norm(X) / max(L_b, 1e-6), 1.0, 1.0])
                M[bo.h] = (j0, Rnow @ sc @ Rbd.T)
            Rh = None
            if 'pf' in d:
                c = f.get('cls', 0)
                ax = cfg['prop_axes'][c]
                Rp = np.zeros((3, 3)); fa_, ua_ = axis(ax[0]), axis(ax[1])
                Fv, Uv = nz(d['pf']), nz(d['pu'] - nz(d['pf']) * np.dot(d['pu'], nz(d['pf'])))
                # prop local basis e_i -> world: e_fa -> F, e_ua -> U, third by right-handedness
                third = np.cross(fa_, ua_); Tv = np.cross(Fv, Uv)
                Lm = np.column_stack([fa_, ua_, third]); Wm = np.column_stack([Fv, Uv, Tv])
                Rp = Wm @ Lm.T
                q = np.array(cfg["prop_local_q"][str(c)], float)
                roll = math.radians(float((cfg.get("prop_roll_deg") or {}).get(str(c), 0.0)))
                mq = (cfg.get("prop_mirror") or {}).get(s)   # off side: biped mirror of the prop local
                if mq:
                    q = q * np.array(mq.get("q_sign", [1, 1, 1, 1]), float)
                    roll = roll * float(mq.get("roll_sign", 1)) + math.radians(float(mq.get("roll_add", 0)))
                Rl = ogre.qmat(q)
                if roll:   # grip roll about the blade axis, applied after the prop local (prop = hand * local * roll)
                    k = axis(ax[0]); Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
                    Rl = Rl @ (np.eye(3) + math.sin(roll) * Kx + (1 - math.cos(roll)) * Kx @ Kx)
                Rh = Rp @ Rl.T
                d['_Rp'] = Rp
            if Rh is None:
                Rh = M[fa.h][1] @ np.linalg.inv(np.diag([1, 1, 1.0])) if False else frame(Xf, Z) @ (ogre.qmat(fa.dq).T @ ogre.qmat(ha.dq))
            M[ha.h] = (d['wr'], Rh @ ogre.qmat(ha.dq).T)
            for c in sk.children(ha.h):   # fingers / prop follow the hand rigidly
                if c.name not in names:
                    M[c.h] = (d['wr'] + M[ha.h][1] @ (c.dpos - ha.dpos), M[ha.h][1])
        return M, S

    def hand_x_err(self, f):
        """deg between the posed hand X axis and the measured one (convention check), per side that has both."""
        M, S = self.pose(f)
        out = {}
        for s in 'LR':
            if 'hx' in S[s] and 'pf' in S[s]:
                ha = self.sk.by_name[self.B[s][3]]
                hx = M[ha.h][1] @ ogre.qmat(ha.dq)[:, 0]
                out[s] = math.degrees(math.acos(max(-1, min(1, np.dot(nz(hx), nz(S[s]['hx']))))))
        return out

    def geometry(self, f):
        """(vertices Nx3 camera numbers, triangles Mx3, part id per triangle: 0 arm, 1 weapon)."""
        M, S = self.pose(f)
        V = np.zeros_like(self.P)
        for h in self.used_bones:
            w = self.W[:, h]
            if not w.any():
                continue
            pn, A = M[h]
            pb = self.sk.bones[h].dpos
            V += w[:, None] * (pn + (self.P - pb) @ A.T)
        verts, tris, part = [V], [self.T], [np.zeros(len(self.T), int)]
        off = len(V)
        for s in self.cfg.get('weapon_sides', ['R']):
            if s not in self.weap or '_Rp' not in S[s]:
                continue
            wp, wt = self.weap[s]
            wo = np.array((self.cfg.get('weapon_offset') or {}).get(s, [0.0, 0.0, 0.0]))
            verts.append(S[s]['pp'] + (wp + wo) @ S[s]['_Rp'].T)
            tris.append(wt + off); part.append(np.ones(len(wt), int)); off += len(wp)
        return np.vstack(verts) * FLIP, np.vstack(tris), np.concatenate(part)


# ---------------- rasteriser ----------------
def raster(V, T, part, size, fov, near, colors, bg=None):
    Wd, Ht = size
    img = np.zeros((Ht, Wd, 3), np.float32) if bg is None else np.asarray(bg, np.float32).copy()
    zb = np.full((Ht, Wd), np.inf, np.float32)
    mask = np.zeros((Ht, Wd), np.int8) - 1
    z = V[:, 2]
    sx = Wd / 2 + Wd / 2 * (V[:, 0] / np.maximum(z, 1e-6)) / fov[0]
    sy = Ht / 2 - Ht / 2 * (V[:, 1] / np.maximum(z, 1e-6)) / fov[1]
    L = nz(np.array([-0.4, 0.8, -0.5]))
    for k, t in enumerate(T):
        if (z[t] < near).any():
            continue
        x0, y0 = sx[t], sy[t]
        xa, xb = int(max(0, math.floor(x0.min()))), int(min(Wd - 1, math.ceil(x0.max())))
        ya, yb = int(max(0, math.floor(y0.min()))), int(min(Ht - 1, math.ceil(y0.max())))
        if xa > xb or ya > yb:
            continue
        den = (y0[1] - y0[2]) * (x0[0] - x0[2]) + (x0[2] - x0[1]) * (y0[0] - y0[2])
        if abs(den) < 1e-9:
            continue
        X, Y = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        l0 = ((y0[1] - y0[2]) * (X - x0[2]) + (x0[2] - x0[1]) * (Y - y0[2])) / den
        l1 = ((y0[2] - y0[0]) * (X - x0[2]) + (x0[0] - x0[2]) * (Y - y0[2])) / den
        l2 = 1 - l0 - l1
        ins = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not ins.any():
            continue
        iz = l0 / z[t[0]] + l1 / z[t[1]] + l2 / z[t[2]]
        zz = 1.0 / np.maximum(iz, 1e-9)
        sub = zb[ya:yb + 1, xa:xb + 1]
        upd = ins & (zz < sub)
        if not upd.any():
            continue
        n = nz(np.cross(V[t[1]] - V[t[0]], V[t[2]] - V[t[0]]))
        if np.dot(n, V[t[0]]) > 0:
            n = -n
        shade = 0.35 + 0.65 * abs(np.dot(n, L))
        col = np.array(colors[part[k]], np.float32) * shade
        sub[upd] = zz[upd]
        img[ya:yb + 1, xa:xb + 1][upd] = col
        mask[ya:yb + 1, xa:xb + 1][upd] = part[k]
    return img, mask, (sx, sy)


def load_cfg(path, weapons=None):
    with open(path) as f:
        cfg = json.load(f)
    if weapons:
        cfg["weapon_sides"] = [s.strip().upper() for s in weapons.split(",") if s.strip()]
    gd = os.environ.get('ANIMLAB_GAME_DIR')
    if gd:
        cfg['game_dir'] = gd
    return cfg


def render_frame(rig, f, size, bg=None):
    cfg = rig.cfg
    V, T, part = rig.geometry(f)
    return raster(V, T, part, size, cfg.get('fov', [1.245, 0.70]), cfg.get('near', 0.5),
                  cfg.get('colors', [[205, 160, 130], [190, 195, 205]]), bg)


def outline(mask, part):
    m = mask == part
    e = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    return e


def save(img, path):
    from PIL import Image
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)


def parse_size(s):
    w, h = s.lower().split('x'); return int(w), int(h)


def cmd_still(a):
    from PIL import Image
    rig = Rig(load_cfg(a.config, a.weapons)); P = load_pose(a.pose)
    f = P[min(a.frame, len(P) - 1)]
    size = parse_size(a.size)
    bg = np.asarray(Image.open(a.bg).convert('RGB').resize(size)) if a.bg else None
    img, mask, _ = render_frame(rig, f, size, bg)
    save(img, a.o)
    print('%s frame %d hand_x_err %s' % (a.o, a.frame, {k: round(v, 1) for k, v in rig.hand_x_err(f).items()}))
    return 0


def cmd_frames(a):
    rig = Rig(load_cfg(a.config, a.weapons)); P = load_pose(a.pose)
    os.makedirs(a.o, exist_ok=True)
    size = parse_size(a.size)
    sel = list(range(a.start, min(len(P), a.end if a.end is not None else len(P)), a.every))
    for k, i in enumerate(sel):
        img, _, _ = render_frame(rig, P[i], size)
        save(img, os.path.join(a.o, 'f%05d.png' % k))
    print('%d frames -> %s' % (len(sel), a.o))
    if a.mp4:
        fps = a.fps or max(1, round(len(sel) / max(1e-3, P[sel[-1]]['t'] - P[sel[0]]['t']))) if len(sel) > 1 else 30
        r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(fps), '-i', os.path.join(a.o, 'f%05d.png'),
                            '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', a.mp4])
        print('mp4 %s (%s fps) rc=%d' % (a.mp4, fps, r.returncode))
        return r.returncode
    return 0


def cmd_compare(a):
    """left: game frame, middle: render, right: game frame with the render's outlines (arm green, weapon red)."""
    from PIL import Image
    rig = Rig(load_cfg(a.config, a.weapons)); f = load_pose(a.state)[0]
    g = Image.open(a.game).convert('RGB'); size = g.size
    gnp = np.asarray(g, np.float32)
    img, mask, _ = render_frame(rig, f, size)
    ov = gnp.copy()
    ov[outline(mask, 0)] = (0, 255, 0); ov[outline(mask, 1)] = (255, 0, 0)
    ov[mask >= 0] = 0.75 * ov[mask >= 0] + 0.25 * img[mask >= 0]
    side = np.concatenate([gnp, img, ov], axis=1)
    sc = a.scale
    out = Image.fromarray(np.clip(side, 0, 255).astype(np.uint8))
    if sc != 1.0:
        out = out.resize((int(out.width * sc), int(out.height * sc)))
    out.save(a.o)
    hx = rig.hand_x_err(f)
    print('compare %s: arm px=%d weapon px=%d hand_x_err=%s' % (a.o, int((mask == 0).sum()), int((mask == 1).sum()),
                                                                {k: round(v, 1) for k, v in hx.items()}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('still'); p.add_argument('pose'); p.add_argument('--config', required=True); p.add_argument('-o', required=True)
    p.add_argument('--frame', type=int, default=0); p.add_argument('--bg'); p.add_argument('--size', default='1600x900')
    p = sp.add_parser('frames'); p.add_argument('pose'); p.add_argument('--config', required=True); p.add_argument('-o', required=True)
    p.add_argument('--every', type=int, default=1); p.add_argument('--from', dest='start', type=int, default=0)
    p.add_argument('--to', dest='end', type=int); p.add_argument('--mp4'); p.add_argument('--fps', type=int)
    p.add_argument('--size', default='800x450')
    p = sp.add_parser('compare'); p.add_argument('state'); p.add_argument('game'); p.add_argument('--config', required=True)
    p.add_argument('-o', required=True); p.add_argument('--scale', type=float, default=0.5)
    for p in sp.choices.values():
        p.add_argument("--weapons", help="override weapon_sides, e.g. R,L (dual wield)")
    a = ap.parse_args()
    return dict(still=cmd_still, frames=cmd_frames, compare=cmd_compare)[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
