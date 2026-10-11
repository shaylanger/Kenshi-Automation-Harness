"""recfmt.py -- reader for KenshiFP viewmodel recordings (`fp_vm rec dump`), one record per camera frame.

Line format (groups separated by '|'):
  0  n t dt st ti cls on w swing swu prog kick fire omode yaw pitch zoom
  1  out.p out.f out.u (commanded weapon pose) oc (off-hand target) mp mf mu (measured weapon grip/forward/edge)
     Lsh Lel Lwr Rsh Rel Rwr (measured arm joints)          -- all "camera numbers": x right, y up, z forward, dm,
  2  eye rt up fw (world)                                      from the unzoomed eye
  3  rootf roota napply phase wih stretch
  4  wb mh mfx zf head neck spine [hy hz]   (wrist bend deg, hand X axis, forearm X axis, zoom fade, head/neck/spine)
     [nc]: camera near clip applied this frame (world dm, -1 = none; KenshiFP kfp-vmrec-nc), r['nc'] (None in older recordings)
  5  [nok natLsh natLel natLwr natRsh natRel natRwr nhxL nhyL nhxR nhyR nlpL nlqL nlpR nlqR]  native (pre-IK) pose of
     this frame's apply, camera numbers of this record (KenshiFP builds with the rec-native patch); r['nat'] = joints
  7  [F hxL hyL hxR hyR]  measured hand bone X/Y axes of both hands, camera numbers (KenshiFP kfp-fist-native); r['fh']
  6  [H hinge_upperarm hinge_forearm]  E5: rendered elbow-hinge axis of the weapon-arm upper arm / forearm bone, camera
     numbers (KenshiFP builds with the E5 hinge patch); r['hua'], r['hfa'] (None in older recordings)
     [stroke band_hidden]: E6 scripted stroke (-1 = none); Z1 band_hidden 1 = body + weapon not drawn (KenshiFP 3AFB09A4+)
Measured values in record n are what frame n-1 rendered (the camera callback runs before the next apply).
Comment lines `# set <frame> <key> <value>` / `# build ...` (newer KenshiFP builds) are kept in Rec.meta.
"""
import math

JOINTS = ('Lsh', 'Lel', 'Lwr', 'Rsh', 'Rel', 'Rwr')
VECS1 = ('out_p', 'out_f', 'out_u', 'oc', 'mp', 'mf', 'mu') + JOINTS
TI = {-1: 'none', 0: 'ready', 1: 'aim', 2: 'reload', 3: 'block'}


def v3(s):
    return tuple(float(x) for x in s.split(','))


class Rec(object):
    def __init__(self, frames, meta):
        self.frames, self.meta = frames, meta

    def __len__(self):
        return len(self.frames)


def parse(path):
    frames, meta = [], []
    with open(path) as fh:
        for line in fh:
            if line.startswith('#'):
                if not line.startswith('# n '):
                    meta.append(line[1:].strip())
                continue
            if '|' not in line:
                continue
            pa = line.split('|')
            h = pa[0].split()
            if len(h) < 17:
                continue
            r = dict(n=int(h[0]), t=float(h[1]), dt=float(h[2]), st=h[3], ti=int(h[4]), cls=int(h[5]), on=int(h[6]),
                     w=float(h[7]), swing=int(h[8]), swu=float(h[9]), prog=float(h[10]), kick=float(h[11]), fire=float(h[12]),
                     omode=int(h[13]), yaw=float(h[14]), pitch=float(h[15]), zoom=float(h[16]))
            v = [v3(x) for x in pa[1].split()]
            if len(v) < 13:
                continue
            for k, name in enumerate(VECS1):
                r[name] = v[k]
            cam = [v3(x) for x in pa[2].split()] if len(pa) > 2 else []
            r['eye'], r['rt'], r['up'], r['fw'] = cam if len(cam) == 4 else (None,) * 4
            r['phase'], r['wih'], r['stch'], r['napp'] = 0, 1, 1.0, None
            if len(pa) > 3:
                x = pa[3].split()
                if len(x) >= 6:
                    r['phase'], r['wih'], r['stch'], r['napp'] = int(x[3]), int(x[4]), float(x[5]), int(x[2])
            r['wb'], r['zf'], r['nc'] = None, 1.0, None
            if len(pa) > 4:
                x = pa[4].split()
                if len(x) >= 3:
                    r['wb'], r['mh'], r['mfx'] = float(x[0]), v3(x[1]), v3(x[2])
                if len(x) >= 7:
                    r['zf'], r['hd'], r['nk'], r['sp'] = float(x[3]), v3(x[4]), v3(x[5]), v3(x[6])
                if len(x) >= 9:
                    r['hy'], r['hz'] = v3(x[7]), v3(x[8])
                if len(x) >= 10:
                    r['nc'] = float(x[9])   # Z1 band clip: camera near clip applied (kfp-vmrec-nc), -1 = none
            r['nat'] = None
            if len(pa) > 5:
                x = pa[5].split()
                if len(x) >= 15 and x[0] == '1':
                    r['nat'] = dict(zip(JOINTS, [v3(t) for t in x[1:7]]))
            r['hua'] = r['hfa'] = None   # E5: rendered weapon-arm elbow-hinge axes (upper arm, forearm bone), group 'H'
            r['stroke'] = None           # E6: scripted stroke of the current swing (H 4th token, -1 = no swing)
            r['band_hidden'] = 0         # Z1: character + weapon hidden while the camera is in the head-hidden band (H 5th token)
            r['fh'] = None               # U25: measured hand X/Y axes of both hands (group 'F': LX LY RX RY; KenshiFP kfp-fist-native)
            for g in pa[5:]:
                x = g.split()
                if len(x) >= 5 and x[0] == 'F':
                    r['fh'] = tuple(v3(t) for t in x[1:5])
                if len(x) >= 3 and x[0] == 'H':
                    r['hua'], r['hfa'] = v3(x[1]), v3(x[2])
                    if len(x) >= 4 and x[3].lstrip('-').isdigit():
                        r['stroke'] = int(x[3])
                    if len(x) >= 5:
                        r['band_hidden'] = int(x[4])
            frames.append(r)
    return Rec(frames, meta)


# ---- small vector helpers (tuples) ----
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def ln(a): return math.sqrt(dot(a, a))
def nz(a):
    l = ln(a)
    return mul(a, 1.0 / l) if l > 1e-9 else a
def ang(a, b):
    la, lb = ln(a), ln(b)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b) / la / lb))))


def remap(c, a, b, pos):
    """camera numbers of record b -> camera numbers of record a (through world)."""
    if a['eye'] is None or b['eye'] is None:
        return c
    w = add(add(mul(b['rt'], c[0]), mul(b['up'], c[1])), mul(b['fw'], c[2]))
    if pos:
        w = add(w, b['eye'])
        d = sub(w, a['eye'])
    else:
        d = w
    return (dot(d, a['rt']), dot(d, a['up']), dot(d, a['fw']))
