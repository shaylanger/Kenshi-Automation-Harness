#!/usr/bin/env python3
"""weapon_matrix.py -- animation lab: every viewmodel recording through the weapon-dependent checks, once per weapon.

  animlab.py weapons --run [--weapons-json DIR/weapons.json] [--recs REC ... | @list] [--adapter CMD] [--all | --only a,b]
                     [--sheet] [-o DIR]

The FP viewmodel poses the weapon PROP (grip = prop bone origin = weapon mesh origin, f/u = prop axes): the arm motion
does not depend on which weapon is held (KenshiFP has one melee path and one crossbow path, see
components/KenshiFP/animlab/weapons/FP_COVERAGE.md). What changes per weapon is the geometry around the grip, so each
recording is re-judged with each weapon's REAL mesh (weapons.py catalog: mesh, item scale fields) placed on the
recorded prop pose (mp, mf, mu):
  near   (all)   on zoom-0 viewmodel frames no part of the weapon is cut by the 3 dm near clip inside the view and nothing
                 comes within 1.2 dm of the eye (long handles / pommels / polearm butts into the camera; class C2 'grey
                 cylinder cut by the near clip'). Gate: <= NEAR_SHARE of each state's frames.
  vis    (all)   ready / block / aim at zoom 0: >= VIS_PART of the striking part (mesh Y > 0.6 x tip; crossbow: whole bow)
                 on screen in >= VIS_SHARE of the frames (weapon visible, Shay 2026-10-09).
  twohand(3, 8)  R2H-1 (Shay 2026-10-10: two-handed weapons are held two-handed in FP): item skill category 3 heavy weapons /
                 8 polearm: the off-hand wrist within TWO_D dm of the shaft (pommel end .. grip + 0.6 tip) on >= TWO_SHARE of
                 ready / block / swing frames.
  twosp  (3, 8)  R2H-2 (inferred from the native stances, animlab native.py 2026-10-10: heavy guard6 off wrist 2.3 dm BEHIND
                 the weapon wrist toward the pommel, polearm guard pole 7.1 dm AHEAD toward the head): wrist-to-wrist distance
                 along the shaft (off - weapon, + = toward the tip) inside TWO_SP[class] on >= TWO_SHARE of the frames the off
                 hand is on the shaft.
  With --adapter, a 2H weapon's recordings are replayed with `--set wcat=<skill category>` (what the game reads per
  weapon, kfp-two-hand), so the matrix judges the source's two-hand path; one-handed weapons use the plain replay.
  arc    (flat edged weapons)  E1 edge-leads-the-arc gate (metrics.arc_gate) with the mid-blade point at 0.5 x tip.
  seen   (flat edged weapons)  E6 blade visibility (metrics.blade_check) with the seen length scaled to the blade
                 (katana: SEE_L 7 dm of 10.4 dm tip -> 0.67 x tip).
Weapon-independent checks (churn, hinge, inline, branch, spike, guard, moves, stroke tables) give the same result for
every weapon: they run once in the normal gate, not here.
Output: one line per weapon `WEAPON <sid> PASS|FAIL <class> <name> near=.. vis=.. twohand=.. arc=.. seen=..`,
DIR/matrix.tsv, and `RESULT WEAPON-MATRIX PASS|FAIL weapons=<n> fail=<n> (base <n>, mod <n>)`.
--sheet: DIR/sheets/<sid>.png per weapon (visual lab render of the first zoom-0 recording with that weapon's mesh).
"""
import json, math, os, shlex, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labcache  # noqa: E402

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'visual'))
import metrics as M  # noqa: E402
import ogre  # noqa: E402
import recfmt  # noqa: E402

NEAR, EYE_MIN, NEAR_SHARE = 3.0, 1.2, 0.02
NEARC = {0: NEAR, 1: 1.5}   # KenshiFP near plane: g_cfg_nearclip 3.0 (melee), g_vm_nc 1.5 while the ranged viewmodel shows (X2)
VIS_PART, VIS_SHARE = 0.50, 0.90
TWO_D, TWO_SHARE = 1.5, 0.80
TWO_CLS = (3, 8)                # item skill categories held two-handed (R2H-1)
TWO_SP = {3: (-3.5, -0.5), 8: (3.0, 7.5)}   # R2H-2 wrist-to-wrist along the shaft, dm (heavy: down to hands together on short handles)
FLAT_MIN = 1.8                  # width/thickness ratio: a flat (edged) weapon
SEE_RATIO = M.SEE_L / 10.42     # katana05 tip 10.42 dm
from weapons import REF   # noqa: E402  (reference weapons: the ones the fixture takes use)
PROP_AXES = {0: (2, 3), 1: (2, -1)}   # KenshiFP g_vm_ax (f, u) per viewmodel class: melee, ranged
MELEE_STATES = ('ready', 'swing', 'block', 'swing->block')
CORPUS = os.environ.get('ANIMLAB_CORPUS', '/mnt/c/KenshiTestRuns/corpus')
DEFAULT_RECS = {0: ['agree/rec/q-sword-z0-a-f059.txt', 'pools/block-guard/q-sword-z25-f059.txt', 'pools/sword-swing/e6fix.txt',
                    'rec/spec-swing-A.txt'],
                1: ['agree/rec/q-crossbow-z0-f059.txt', 'agree/rec/q-crossbow-z25-f059.txt', 'rec/spec-xbow-A.txt']}


def axis(code):
    v = np.zeros(3); v[abs(code) - 1] = 1.0 if code > 0 else -1.0
    return v


def nz(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


_PTS = {}


def mesh_points(w, nmax=2500):
    key = (w['mesh_path'], w['scale_length'], w['scale_width'], w['scale_thickness'])
    if key not in _PTS:
        m = ogre.load_mesh(os.path.realpath(w['mesh_path']))
        V = np.vstack([x[0] for x in m.triangles()])
        V = np.unique(np.round(V, 3), axis=0)
        if len(V) > nmax:
            keep = set(np.argsort(V[:, 1])[[0, -1]])   # always keep both ends
            idx = sorted(set(np.linspace(0, len(V) - 1, nmax).astype(int)) | keep)
            V = V[idx]
        _PTS[key] = V * np.array([w['scale_thickness'], w['scale_length'], w['scale_width']])
    return _PTS[key]


def cam_basis(cls, mf, mu):
    """rotation mesh -> camera numbers for a recorded prop frame (camera numbers are a mirrored frame: cross flips)."""
    fa, ua = PROP_AXES[cls]
    fm, um = axis(fa), axis(ua); sm = np.cross(fm, um)
    f = nz(mf); u = nz(np.asarray(mu) - f * np.dot(mu, f)); s = -np.cross(f, u)
    return np.column_stack([f, u, s]) @ np.vstack([fm, um, sm])


def onscreen(C, zmin=NEAR):
    z = C[:, 2]
    with np.errstate(divide='ignore', invalid='ignore'):
        return (z >= zmin) & (np.abs(C[:, 0] / z) <= M.TX) & (np.abs(C[:, 1] / z) <= M.TY)


def seg_dist(p, a, b):
    ab = b - a; t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def judge(w, path):
    """weapon-dependent checks of one recording with weapon w. Returns {check: (ok|None, text)}."""
    R = recfmt.parse(path); F = R.frames
    P = M.frame_metrics(R)
    cls = 1 if w['type'] == 'crossbow' else 0
    V = mesh_points(w); tip = max(float(V[:, 1].max()), 1e-3); pom = max(float(-V[:, 1].min()), 0.0)
    strike = V[:, 1] > (0.0 if cls == 0 else -1e9)   # blade / shaft past the grip (crossbow: whole bow)
    out = {}
    near = {}; vis = {}; two = [0, 0]; sp = [0, 0]
    for i, p in enumerate(P):
        st = p['state']; r = F[i]
        if r['cls'] != cls or not p.get('wih'):
            continue
        if cls == 0 and st not in MELEE_STATES:
            continue
        if cls == 1 and st not in ('ready', 'aim', 'reload'):
            continue
        Rm = cam_basis(cls, p['mf'], p['mu']); C = np.asarray(p['mp']) + V @ Rm.T
        if r.get('zoom', 0.0) < 0.5:
            z = C[:, 2]
            with np.errstate(divide='ignore', invalid='ignore'):
                inview = (z > 0.05) & (np.abs(C[:, 0] / z) <= M.TX) & (np.abs(C[:, 1] / z) <= M.TY)
            cut = int(((z < NEARC[cls]) & inview).sum()); eye = float(np.linalg.norm(C, axis=1).min()) if cls == 0 else 99.0   # crossbow aim: stock at the cheek by design
            n = near.setdefault(st, [0, 0, 0.0, 99.0]); n[0] += 1; n[1] += (cut >= 3 or eye < EYE_MIN)
            n[2] = max(n[2], cut / len(V)); n[3] = min(n[3], eye)
            if st in ('ready', 'block', 'aim'):
                s = vis.setdefault(st, [0, 0]); s[0] += 1
                s[1] += onscreen(C[strike], NEARC[cls]).mean() >= VIS_PART
        if cls == 0 and w['cls'] in TWO_CLS and st in MELEE_STATES:
            wr = np.asarray(p['J'][2])   # weapon hand R (KenshiFP g_vm_whand default): off hand = L wrist
            a = np.asarray(p['mp']) - nz(p['mf']) * pom; b = np.asarray(p['mp']) + nz(p['mf']) * 0.6 * tip
            on = seg_dist(wr, a, b) <= TWO_D
            two[0] += 1; two[1] += on
            if on:
                d = float(np.dot(wr - np.asarray(p['J'][5]), nz(p['mf']))); lo, hi = TWO_SP[two_kind(w)]
                sp[0] += 1; sp[1] += lo <= d <= hi
    if near:
        bad = {s: v for s, v in near.items() if v[1] > NEAR_SHARE * v[0]}
        worst = max(near.items(), key=lambda kv: kv[1][1] / kv[1][0])
        out['near'] = (not bad, '%s %d/%d cut%%=%.0f eye=%.1f' % (worst[0], worst[1][1], worst[1][0], 100 * worst[1][2], worst[1][3]),
                       sum(v[1] for v in near.values()))
    if vis:
        bad = {s: v for s, v in vis.items() if v[1] < VIS_SHARE * v[0]}
        worst = min(vis.items(), key=lambda kv: kv[1][1] / kv[1][0])
        out['vis'] = (not bad, '%s %d/%d' % (worst[0], worst[1][1], worst[1][0]), -sum(v[1] for v in vis.values()))
    if two[0]:
        out['twohand'] = (two[1] >= TWO_SHARE * two[0], '%d/%d' % (two[1], two[0]), two[0] - two[1])
        out['twosp'] = (sp[0] > 0 and sp[1] >= TWO_SHARE * sp[0], '%d/%d(inferred)' % (sp[1], sp[0]), sp[0] - sp[1])
    if cls == 0 and w.get('flat', 0) >= FLAT_MIN and any(p['state'] == 'swing' for p in P):
        old = M.ARC_MID
        try:
            M.ARC_MID = 0.5 * tip
            P2 = M.frame_metrics(R); T = M.state_table(P2)
            ok, txt = M.arc_gate(T, {'swing': M.ARC_SHARE})
            out['arc'] = (ok, (txt[0] if txt else '').replace(' ', '_')[:40], 0 if ok else 1)
        finally:
            M.ARC_MID = old
        orig = M.blade_seen
        try:
            M.blade_seen = lambda q, L=SEE_RATIO * tip, **k: orig(q, L=L, **k)
            ok, txt = M.blade_check(F, P)
            out['seen'] = (ok, (txt[0] if txt else '').replace(' ', '_')[:40], 0 if ok else 1)
        finally:
            M.blade_seen = orig
    return out


def two_kind(w):
    """2H grip kind (TWO_SP key): polearm (8), or heavy (3); a heavy weapon with no handle behind the grip (mesh starts at
    or ahead of the hand, e.g. Crab Maul, native anim class polearm) is held like a polearm (KenshiFP g_vm_2hk, wpom < 0.5)"""
    return 8 if w['cls'] == 8 or two_dims(w)[0] < 0.5 else 3


def two_dims(w):
    """handle end behind / tip ahead of the grip along the blade axis, unscaled mesh units (dm) = what KenshiFP's 2H path
    reads in game (Mesh::getBounds; item scale fields not applied)"""
    V = mesh_points(w) / np.array([w['scale_thickness'], w['scale_length'], w['scale_width']])
    return max(float(-V[:, 1].min()), 0.0), float(V[:, 1].max())


_TMP = []


def _tmpdir(prefix):
    """self-cleaning temp dir: removed at exit, also on error / SIGTERM (animlab.py turns SIGTERM into SystemExit).
    Coordinator 2026-10-10: leaked /tmp/animlab-wm-replay-* dirs (~205 MB each) filled 11 GB. Replays themselves live in
    the result cache (labcache.py), so nothing reusable is lost. Leftovers of killed runs (> 6 h untouched) are swept."""
    import glob, shutil, time
    for old in glob.glob(os.path.join(tempfile.gettempdir(), prefix + '*')):
        try:
            if time.time() - os.path.getmtime(old) > 6 * 3600:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    d = tempfile.mkdtemp(prefix=prefix)
    if not _TMP:
        import atexit
        atexit.register(lambda: [shutil.rmtree(x, ignore_errors=True) for x in _TMP])
    _TMP.append(d)
    return d


def load_weapons(a, cfg):
    if a.weapons_json:
        W = json.load(open(a.weapons_json))['weapons']
        for w in W:   # WSL game paths -> this host's (ANIMLAB_PATHMAP, 4080 rig); no-op without the env
            if w.get('mesh_path'):
                w['mesh_path'] = ogre.hostpath(w['mesh_path'])
        return W
    import weapons
    d = _tmpdir('animlab-weapons-')
    rows = weapons.write(cfg, d)
    return rows


def recs_for(a, cls):
    if a.recs:
        L = []
        for x in a.recs:
            L += [l.strip() for l in open(x[1:]) if l.strip() and not l.startswith('#')] if x.startswith('@') else [x]
        return L
    return [os.path.join(CORPUS, x) for x in DEFAULT_RECS[cls] if os.path.exists(os.path.join(CORPUS, x))]


def rec_class(path):
    with open(path) as fh:
        for line in fh:
            if '|' in line and not line.startswith('#'):
                h = line.split('|')[0].split()
                if len(h) >= 17 and int(h[6]) and float(h[7]) >= 0.99:
                    return int(h[5])
    return None


def sheet(w, rec, out, vcfg):
    c = json.load(open(vcfg))
    c['weapon_mesh'] = {'R': w['mesh_path']}
    c['weapon_scale'] = {'R': [w['scale_thickness'], w['scale_length'], w['scale_width']]}
    tmp = os.path.join(os.path.dirname(out), '.vcfg-%s.json' % w['sid'].replace('/', '_'))
    json.dump(c, open(tmp, 'w'))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'visual', 'render.py'), 'sheet', rec, '--config', tmp, '-o', out,
                        '--every', '12', '--cols', '8', '--labels', '%s %s' % (w['cls_name'], w['name'])],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    os.remove(tmp)
    return r.returncode == 0


def run(a, cfg):
    rows = load_weapons(a, cfg)
    sel = [x for x in rows if x.get('mesh_path') and x.get('length')]
    if a.only:
        keys = {k.strip().lower() for k in a.only.split(',')}
        sel = [x for x in sel if x['sid'].lower() in keys or x['name'].lower() in keys]
    elif not a.all:
        sel = [x for x in sel if x.get('representative', True) or x['sid'] in REF.values()]
    os.makedirs(a.o, exist_ok=True)
    recs = {c: recs_for(a, c) for c in (0, 1)}
    if a.recs:   # split the given recordings by viewmodel class
        allr = recs[0]; recs = {0: [], 1: []}
        for r in allr:
            k = rec_class(r)
            if k in recs:
                recs[k].append(r)
    rawrecs = {c: list(recs[c]) for c in recs}; rd = None; vrecs = {}
    if a.adapter:   # replay every recording through the current solver first (judge the current source)
        rd = _tmpdir('animlab-wm-replay-')
        for c in recs:
            L = []
            for r in recs[c]:
                o = os.path.join(rd, os.path.basename(r))
                labcache.run_cmd(shlex.split(a.adapter) + [r, o], [o], kind='replay')   # cached by content (labcache.py)
                if os.path.exists(o):
                    L.append(o)
            recs[c] = L

    def recs_of(w, c):
        """a 2H weapon's recordings replayed as the game would solve it (the source reads the skill category per weapon)"""
        if not a.adapter or c != 0 or w['cls'] not in TWO_CLS:
            return recs[c]
        pom, tip = two_dims(w)   # what the game reads per weapon (kfp-two-hand: mesh bounds, unscaled)
        k = (w['cls'], round(pom, 2), round(tip, 2))
        if k not in vrecs:
            L = []
            for r in rawrecs[c]:
                o = os.path.join(rd, 'wcat%d-%.2f-%.2f-%s' % (k + (os.path.basename(r),)))
                labcache.run_cmd(shlex.split(a.adapter) + [r, o, '--set', 'wcat=%d' % k[0], '--set', 'wpom=%.3f' % pom, '--set', 'wtip=%.3f' % tip],
                                 [o], kind='replay')
                if os.path.exists(o):
                    L.append(o)
            vrecs[k] = L or recs[c]   # a source without the two-hand path rejects wcat: judge its plain replay
        return vrecs[k]
    refs = {}
    for c, key in ((0, getattr(a, 'ref', None) or REF[0]), (1, getattr(a, 'ref_ranged', None) or REF[1])):
        m = [x for x in rows if x['sid'] == key or x['name'] == key]
        refs[c] = m[0] if m else None
    cache = {}

    def ref_result(c, r):
        if refs[c] is None:
            return {}
        if (c, r) not in cache:
            try:
                cache[(c, r)] = judge(refs[c], r)
            except Exception:   # noqa: BLE001
                cache[(c, r)] = {}
        return cache[(c, r)]
    print('reference weapons: melee %s, ranged %s' % (refs[0] and refs[0]['name'], refs[1] and refs[1]['name']))
    vcfg = os.path.join(os.path.dirname(a.config), 'visual.json')
    if getattr(a, 'sheet', False):
        os.makedirs(os.path.join(a.o, 'sheets'), exist_ok=True)
    tsv = open(os.path.join(a.o, 'matrix.tsv'), 'w')
    tsv.write('sid\tname\tsource\tclass\tanim_class\tverdict\trec\tcheck\tok\tdetail\n')
    nf = 0; nb = nm = fb = fm = 0
    for w in sel:
        c = 1 if w['type'] == 'crossbow' else 0
        res = {}
        for r in recs_of(w, c):
            try:
                J = judge(w, r)
            except Exception as e:   # noqa: BLE001
                J = {'error': (False, str(e)[:60], 1)}
            R0 = ref_result(c, r)
            if c == 0 and w["cls"] in TWO_CLS:
                # 2H: a new pose, judged strictly, except `seen` (blade snap at a fixed recording frame, e6fix swing0 frame
                # ~272: the reference katana fails it too = a property of the recording, not of the 2H grip)
                R0 = {k: v for k, v in R0.items() if k == 'seen'}
            for k, (ok, txt, bad) in J.items():
                # reference-relative: a check the reference weapon (the one the recording was made with) also fails is a
                # recording / pose problem, judged by the normal gate: the weapon fails it only when clearly worse
                rk = R0.get(k)
                v = 'PASS' if ok else 'FAIL'
                if not ok and rk is not None and not rk[0]:
                    v = 'FAIL' if bad > rk[2] + max(5, 0.1 * abs(rk[2])) else 'REF-FAIL'
                tsv.write('%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' % (w['sid'], w['name'], w['source'], w['cls_name'], w['anim_cls_name'],
                                                                     v, os.path.basename(r), k, 'PASS' if ok else 'FAIL', txt))
                cur = res.get(k); rank = {'PASS': 0, 'REF-FAIL': 1, 'FAIL': 2}
                if cur is None or rank[v] > rank[cur[0]]:
                    res[k] = (v, '%s:%s' % (os.path.basename(r)[:18], txt))
        ok = bool(res) and all(v[0] != 'FAIL' for v in res.values())
        base = w['source'].startswith('base:')
        nb += base; nm += not base
        if not ok:
            nf += 1; fb += base; fm += not base
        txt = ' '.join('%s=%s(%s)' % (k, {'PASS': 'ok', 'REF-FAIL': 'ref-fail'}.get(v[0], 'FAIL'), v[1])
                       for k, v in sorted(res.items())) or 'no-recordings'
        print('WEAPON %s %s %s/%s %s [%s] %s' % (w['sid'].replace(' ', '_'), 'PASS' if ok else 'FAIL', w['cls_name'].replace(' ', '_'),
                                                 w['anim_cls_name'].replace(' ', '_'), w['name'], w['source'], txt))
        sys.stdout.flush()
        if getattr(a, 'sheet', False) and recs_of(w, c):
            z0 = [r for r in recs_of(w, c) if 'z25' not in r] or recs_of(w, c)
            sheet(w, z0[0], os.path.join(a.o, 'sheets', '%s.png' % w['sid'].replace(' ', '_').replace('/', '_')), vcfg)
    tsv.close()
    print('RESULT WEAPON-MATRIX %s weapons=%d fail=%d (base %d/%d, mod %d/%d fail) recs=%d+%d out=%s' % (
        'PASS' if not nf else 'FAIL', len(sel), nf, fb, nb, fm, nm, len(recs[0]), len(recs[1]), a.o))
    return 0 if not nf else 1
