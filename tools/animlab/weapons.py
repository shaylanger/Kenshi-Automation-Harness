#!/usr/bin/env python3
"""weapons.py -- animation lab: every weapon the game can load (base data + active mods) as lab props.

  animlab.py weapons --catalog --config CFG [-o DIR]
      reads the game's load order (data/gamedata.base, Newwworld.mod, rebirth.mod, Dialogue.mod, then data/mods.cfg:
      each mod from <game>/mods/<name>/ or the Steam workshop folder), every melee WEAPON record (type 2, player skill
      categories 0-4, 8) and every crossbow (type 107), resolves each mesh (game dir, then every mod folder) and measures
      it (Ogre mesh, dm; Kenshi weapon meshes: grip = mesh origin, blade along +Y), applies the item's scale fields and
      writes DIR/weapons.csv, weapons.json (the lab's per-weapon props) and weapons.md (per-class summary + flags).
      Rerun after any mod change: new mods are picked up from mods.cfg.
  animlab.py weapons --run ...    see run_matrix() (phase 3: replays through every check per weapon prop)

Config keys used (native.json): game_dir, workshop_dir (default <game_dir>/../../workshop/content/233860).
Flags (column `flags`): mod-new / mod-changed (source), anim-override=<class> (the item plays another class's
techniques), no-mesh / mesh-missing, axis=<X|Z> (long axis not +Y: grip convention differs), grip-off (origin not in the
lower half: the hand would hold the blade), scaled (scale fields != 1), long / short (effective length outside 0.7..1.35 x
the class median of the base game), odd-class (category outside the FP melee set).
"""
import csv, json, math, os, re, sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'visual'))
import native  # noqa: E402
import ogre  # noqa: E402

BASE_FILES = ['data/gamedata.base', 'data/Newwworld.mod', 'data/rebirth.mod', 'data/Dialogue.mod']
T_WEAPON, T_CROSSBOW, T_TECH = 2, 107, 17
MELEE = {0: 'katanas', 1: 'sabre', 2: 'blunt', 3: 'heavy weapons', 4: 'hackers', 8: 'polearm'}
CLASSNAME = dict(native.SKILL_CATEGORY)
NO_OVERRIDE = 21
# lab geometry kind per class: what the checks measure at the far end (edge = edged blade, head = blunt/axe head)
KIND = {0: 'edge', 1: 'edge', 4: 'edge', 2: 'head', 3: 'head', 8: 'head', 6: 'crossbow'}
TWO_HAND = {3, 8}          # native techniques of these classes hold the weapon with both hands
REF = {0: '5022626-Universal Wasteland Expansion.mod', 1: '53643-rebirth.mod'}   # weapons the fixture takes use: Chisa Katana (UWE, Malzin's), Oldworld Bow MkII
SIZE_BUCKETS = ((0, 11.5, 'S'), (11.5, 15.5, 'M'), (15.5, 99, 'L'))   # effective length dm (katana05 ~12.8)


def weight_class(kg):
    return 'light' if kg <= 3 else 'medium' if kg <= 8 else 'heavy'


def size_bucket(L):
    for a, b, n in SIZE_BUCKETS:
        if a <= L < b:
            return n
    return '?'


# ---------------- load order ----------------
def load_order(cfg):
    gd = cfg['game_dir']
    ws = cfg.get('workshop_dir') or os.path.normpath(os.path.join(gd, '..', '..', 'workshop', 'content', '233860'))
    out = [dict(file=os.path.join(gd, f), mod='base:' + os.path.basename(f), folder=gd, base=True) for f in BASE_FILES]
    wsmods = {}
    if os.path.isdir(ws):
        for d in sorted(os.listdir(ws)):
            p = os.path.join(ws, d)
            if os.path.isdir(p):
                for f in os.listdir(p):
                    if f.lower().endswith('.mod'):
                        wsmods.setdefault(f.lower(), p)
    cfgp = os.path.join(gd, 'data', 'mods.cfg')
    names = [l.strip() for l in open(cfgp, encoding='utf-8', errors='replace')] if os.path.exists(cfgp) else []
    for n in names:
        if not n:
            continue
        d = os.path.join(gd, 'mods', n[:-4] if n.lower().endswith('.mod') else n)
        f = os.path.join(d, n)
        if not os.path.exists(f):
            w = wsmods.get(n.lower())
            d, f = (w, os.path.join(w, n)) if w else (None, None)
        out.append(dict(file=f, mod=n[:-4], folder=d, base=False))
    return out


def read_all(order):
    """merge records in load order; keep the defining file and every file that changed it."""
    db = {}
    for L in order:
        if not L['file'] or not os.path.exists(L['file']):
            L['missing'] = True
            continue
        try:
            recs = native.fcs_read(os.path.realpath(L['file']))
        except Exception as e:   # noqa: BLE001
            L['error'] = str(e)
            continue
        L['records'] = len(recs)
        for r in recs:
            c = db.get(r['sid'])
            if c is None:
                r['src'] = L['mod']; r['changed_by'] = []; r['src_folder'] = L['folder']
                db[r['sid']] = r
                continue
            before = {k: dict(c[k]) for k in ('ints', 'files', 'floats')}
            for k in ('bools', 'floats', 'ints', 'strings', 'files'):
                c[k].update(r[k])
            for k, v in r.get('refs', {}).items():
                c.setdefault('refs', {})[k] = list(dict.fromkeys(c.get('refs', {}).get(k, []) + v))
            if r['name']:
                c['name'] = r['name']
            if not L['base'] and any(c[k] != before[k] for k in before):
                c['changed_by'].append(L['mod'])
            elif L['base']:
                c['src'] = c['src'] if c['src'].startswith('base:') else L['mod']
    return db


# ---------------- meshes ----------------
def resolve(cfg, order, rel, src_folder=None):
    if not rel:
        return None
    p = rel.replace('\\', '/')
    p = p[2:] if p.startswith('./') else p.lstrip('/')
    cands = [os.path.join(cfg['game_dir'], p)]
    m = re.match(r'(?i)mods/([^/]+)/(.*)', p)
    folders = ([src_folder] if src_folder else []) + [L['folder'] for L in order if L.get('folder') and not L['base']]
    for f in folders:
        if m:
            cands.append(os.path.join(f, m.group(2)))
        cands.append(os.path.join(f, p))
        if p.lower().startswith('data/'):
            cands.append(os.path.join(f, p[5:]))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


_MCACHE = {}


def measure(path):
    """mesh geometry in the mesh frame (dm). Kenshi weapon meshes: grip at the origin, blade/shaft along +Y."""
    if path in _MCACHE:
        return _MCACHE[path]
    m = ogre.load_mesh(os.path.realpath(path))
    V = [x[0] for x in m.triangles()]
    if not V:
        _MCACHE[path] = None
        return None
    V = np.vstack(V)
    lo, hi = V.min(0), V.max(0); ext = hi - lo
    ax = int(np.argmax(ext))
    y = V[:, 1]
    # width profile along +Y (20 bins): the wide far part = blade / head start
    nb = 20; edges = np.linspace(max(lo[1], 0.0), hi[1], nb + 1)
    wid = []
    for i in range(nb):
        s = V[(y >= edges[i]) & (y <= edges[i + 1])]
        wid.append(float(max(np.ptp(s[:, 0]), np.ptp(s[:, 2]))) if len(s) else 0.0)
    wid = np.array(wid)
    med = float(np.median(wid[wid > 0])) if (wid > 0).any() else 0.0
    far = wid[nb // 2:]
    head_ratio = float(far.max() / med) if med > 0 else 0.0
    i0 = next((i for i in range(nb) if wid[i] > 1.6 * med), None) if med > 0 else None
    B = V[y > 0.35 * hi[1]] if hi[1] > 0 else V   # blade / shaft region (guard + handle excluded): flatness
    bx, bz = (float(np.ptp(B[:, 0])), float(np.ptp(B[:, 2]))) if len(B) else (float(ext[0]), float(ext[2]))
    r = dict(tip=float(hi[1]), pommel=float(-lo[1]), length=float(ext[1]), width_x=float(ext[0]), width_z=float(ext[2]),
             long_axis='XYZ'[ax], head_ratio=round(head_ratio, 2), blade_x=bx, blade_z=bz,
             head_y0=round(float(edges[i0]), 2) if i0 is not None else None,
             centroid_y=round(float(y.mean()), 2), verts=int(len(V)))
    _MCACHE[path] = r
    return r


# ---------------- catalog ----------------
def techniques(db):
    by = defaultdict(list)
    for r in db.values():
        if r['type'] != T_TECH or r['bools'].get('REMOVED') or r['bools'].get('disabled'):
            continue
        for c, k in native.CATS:
            if r['bools'].get(c):
                by[k].append(r)
    return by


def build(cfg):
    order = load_order(cfg)
    db = read_all(order)
    techs = techniques(db)
    rows = []
    for r in db.values():
        if r['bools'].get('REMOVED'):
            continue
        if r['type'] == T_WEAPON:
            k = r['ints'].get('skill category')
            if k is None or r['name'].startswith('_') or (k == 5):
                continue   # animal 'weapons', fists
        elif r['type'] == T_CROSSBOW:
            k = 6
        else:
            continue
        fl, it = r['floats'], r['ints']
        ov = it.get('skill category animation override', NO_OVERRIDE)
        anim_cls = k if ov in (NO_OVERRIDE, None) or ov not in CLASSNAME else ov
        mrel = r['files'].get('mesh', '')
        mp = resolve(cfg, order, mrel, r.get('src_folder'))
        g = None; err = ''
        if mp:
            try:
                g = measure(mp)
            except Exception as e:   # noqa: BLE001
                err = 'mesh-error'
        sL = fl.get('scale length', 1.0) * fl.get('overall scale', 1.0)
        sW = fl.get('scale width', 1.0) * fl.get('overall scale', 1.0)
        sT = fl.get('scale thickness', 1.0) * fl.get('overall scale', 1.0)
        row = dict(sid=r['sid'], name=r['name'], source=r['src'], changed_by=';'.join(dict.fromkeys(r['changed_by'])),
                   type='crossbow' if k == 6 else 'melee', cls=k, cls_name=CLASSNAME.get(k, '?%s' % k),
                   anim_cls=anim_cls, anim_cls_name=CLASSNAME.get(anim_cls, '?'), kind=KIND.get(anim_cls, '?'),
                   hands='RL' if anim_cls in TWO_HAND or k == 6 else 'R',
                   techniques=len(techs.get(anim_cls, [])) if k != 6 else 0,
                   game_length=it.get('length', ''), weight_kg=round(fl.get('weight kg', 0.0), 2),
                   weight_class=weight_class(fl.get('weight kg', 0.0)),
                   scale_length=round(sL, 3), scale_width=round(sW, 3), scale_thickness=round(sT, 3),
                   mesh=mrel.replace('\\', '/'), mesh_path=mp or '', err=err,
                   ammo=';'.join(db[x]['name'] for x in r.get('refs', {}).get('ammo', []) if x in db))
        if g:
            row.update(tip=round(g['tip'] * sL, 2), pommel=round(g['pommel'] * sL, 2), length=round(g['length'] * sL, 2),
                       width=round(max(g['width_x'] * sT, g['width_z'] * sW), 2),
                       flat=round(max(g['blade_x'] * sT, g['blade_z'] * sW) / max(1e-3, min(g['blade_x'] * sT, g['blade_z'] * sW)), 2),
                       long_axis=g['long_axis'],
                       head_ratio=g['head_ratio'], head_y0=None if g['head_y0'] is None else round(g['head_y0'] * sL, 2),
                       grip_y=0.0)
            row['size'] = size_bucket(row['length'])
        rows.append(row)
    # flags
    med = {}
    for k in set(x['cls'] for x in rows):
        L = [x['length'] for x in rows if x['cls'] == k and x['source'].startswith('base:') and x.get('length')]
        if L:
            med[k] = float(np.median(L))
    for x in rows:
        f = []
        if not x['source'].startswith('base:'):
            f.append('mod-new')
        if x['changed_by']:
            f.append('mod-changed')
        if x['anim_cls'] != x['cls']:
            f.append('anim-override=%s' % x['anim_cls_name'])
        if x['cls'] not in MELEE and x['cls'] != 6:
            f.append('odd-class')
        if not x['mesh']:
            f.append('no-mesh')
        elif not x['mesh_path']:
            f.append('mesh-missing')
        elif x['err']:
            f.append(x['err'])
        if x.get('long_axis') and x['long_axis'] != 'Y' and x['cls'] != 6:
            f.append('axis=%s' % x['long_axis'])
        if x.get('length') and x['cls'] != 6 and x['pommel'] > 0.5 * x['length']:
            f.append('grip-off')
        if abs(x['scale_length'] - 1) > 1e-3 or abs(x['scale_width'] - 1) > 1e-3 or abs(x['scale_thickness'] - 1) > 1e-3:
            f.append('scaled')
        if x.get('length') and x['cls'] in med:
            q = x['length'] / med[x['cls']]
            if q > 1.35:
                f.append('long(x%.2f)' % q)
            elif q < 0.7:
                f.append('short(x%.2f)' % q)
        x['flags'] = ' '.join(f)
    rows.sort(key=lambda x: (x['cls'], not x['source'].startswith('base:'), x['name'].lower()))
    return order, rows, techs, med


COLS = ['sid', 'name', 'source', 'changed_by', 'type', 'cls', 'cls_name', 'anim_cls_name', 'kind', 'hands', 'size', 'length',
        'tip', 'pommel', 'width', 'head_ratio', 'head_y0', 'flat', 'grip_y', 'long_axis', 'game_length', 'weight_kg', 'weight_class',
        'scale_length', 'scale_width', 'scale_thickness', 'techniques', 'ammo', 'mesh', 'flags']


def representatives(rows):
    """one weapon per (anim class, size bucket) from the base game + every mod weapon (new or changed)."""
    pick = {}
    for x in rows:
        if not x.get('length'):
            continue
        key = (x['anim_cls'], x['size'])
        if x['type'] == 'crossbow':   # few: every crossbow (one tuned ranged path, sizes differ)
            pick[('xb', x['sid'])] = x
        elif x['source'].startswith('base:') and key not in pick:
            pick[key] = x
    out = list(pick.values())
    seen = {(x['anim_cls'], x['mesh'], x['scale_length'], x['scale_width']) for x in out}
    for x in rows:   # every mod weapon, minus exact geometry + technique-set duplicates (same lab result)
        k = (x['anim_cls'], x['mesh'], x['scale_length'], x['scale_width'])
        if x.get('length') and (not x['source'].startswith('base:') or x['changed_by']) and k not in seen:
            seen.add(k); out.append(x)
    return out


def write(cfg, out):
    order, rows, techs, med = build(cfg)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'weapons.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, COLS, extrasaction='ignore'); w.writeheader()
        for x in rows:
            w.writerow(x)
    reps = {x['sid'] for x in representatives(rows)}
    for x in rows:
        x['representative'] = x['sid'] in reps
    with open(os.path.join(out, 'weapons.json'), 'w') as f:
        json.dump(dict(game_dir=cfg['game_dir'], load_order=[dict(mod=L['mod'], file=L['file'], missing=L.get('missing', False),
                  records=L.get('records', 0)) for L in order], weapons=rows), f, indent=1)
    L = ['# Weapon catalogue (%d weapons: %d melee, %d crossbows)' % (len(rows), sum(x['type'] == 'melee' for x in rows),
                                                                     sum(x['type'] == 'crossbow' for x in rows)), '',
         'Generated by `animlab.py weapons --catalog` from the load order below (rerun after mod changes). Lengths dm from the '
         'real mesh x the item scale fields (grip = mesh origin, blade +Y); `anim class` = the technique set the game plays '
         '(`skill category animation override`); `rep` = lab matrix representative (one per anim class x size + every mod '
         'weapon). Flags: see tools/animlab/weapons.py header.', '', '## Load order', '']
    for o in order:
        L.append('- %s%s' % (o['mod'], ' (MISSING)' if o.get('missing') else ' (%d records)' % o.get('records', 0)))
    L += ['', '## Per class', '', '| class | base | mod-new | mod-changed | anim override | lengths dm (min/med/max) | techniques (load order) |',
          '|---|---|---|---|---|---|---|']
    for k in sorted(set(x['cls'] for x in rows)):
        xs = [x for x in rows if x['cls'] == k]
        Ls = sorted(x['length'] for x in xs if x.get('length'))
        L.append('| %d %s | %d | %d | %d | %d | %s | %d |' % (
            k, CLASSNAME.get(k, '?'), sum(x['source'].startswith('base:') for x in xs), sum(not x['source'].startswith('base:') for x in xs),
            sum(bool(x['changed_by']) for x in xs), sum(x['anim_cls'] != x['cls'] for x in xs),
            '%.1f / %.1f / %.1f' % (Ls[0], Ls[len(Ls) // 2], Ls[-1]) if Ls else '-', len(techs.get(k, []))))
    # mod techniques (animation mods change the native reference set)
    modt = Counter()
    for k, ts in techs.items():
        for t in ts:
            if not t['src'].startswith('base:') or t['changed_by']:
                modt[(k, t['src'] if not t['src'].startswith('base:') else 'changed:' + ','.join(dict.fromkeys(t['changed_by'])))] += 1
    if modt:
        L += ['', '## Combat techniques added/changed by mods (native reference differs from vanilla)', '']
        for (k, s), n in sorted(modt.items()):
            L.append('- %s: %d from %s' % (CLASSNAME.get(k, k), n, s))
    L += ['', '## Weapons', '', '| class | name | sid | source | anim | size | len | tip | width | head | kg | rep | flags |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for x in rows:
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            x['cls_name'], x['name'], x['sid'], x['source'] + (' (chg: %s)' % x['changed_by'] if x['changed_by'] else ''),
            x['anim_cls_name'], x.get('size', '-'), x.get('length', '-'), x.get('tip', '-'), x.get('width', '-'),
            x.get('head_ratio', '-'), x['weight_kg'], 'yes' if x['representative'] else '', x['flags']))
    with open(os.path.join(out, 'sweep.list'), 'w') as f:   # fp-weapon-sweep.sh input: one game take per line
        f.write('# sid|name|type|anim class|ammo  (animlab.py weapons --catalog: representatives)\n')
        for x in sorted(rows, key=lambda x: x['sid'] not in REF.values()):   # reference weapons first
            if x['representative'] or x['sid'] in REF.values():
                f.write('%s|%s|%s|%s|%s\n' % (x['sid'], x['name'], x['type'], x['anim_cls_name'], x.get('ammo', '')))
    with open(os.path.join(out, 'weapons.md'), 'w') as f:
        f.write('\n'.join(L) + '\n')
    for k in sorted(set(x['cls'] for x in rows)):
        xs = [x for x in rows if x['cls'] == k]
        print('class %d %-13s base %2d  mod %2d  changed %d  flagged %d' % (k, CLASSNAME.get(k, '?'), sum(x['source'].startswith('base:') for x in xs),
              sum(not x['source'].startswith('base:') for x in xs), sum(bool(x['changed_by']) for x in xs), sum(bool(x['flags']) for x in xs)))
    print('weapons %d (representatives %d) -> %s' % (len(rows), len(reps), out))
    return rows


def cmd(a):
    cfg = native.load_cfg(a.config)
    if a.catalog:
        write(cfg, a.o)
        return 0
    if a.run:
        import weapon_matrix
        return weapon_matrix.run(a, cfg)
    print('weapons: give --catalog or --run'); return 2
