#!/usr/bin/env python3
"""Offline tests for phase 4 (NATIVE): Ogre skeleton animation reader + sampling (tools/animlab/visual/ogre.py),
tools/animlab/native.py (trajectory frames, left grip mirror, solver grip offset, keyed viewmodel path, key fit, FCS
game-data reader). Synthetic binaries written here; no game install. Run: python3 tests/animlab/test_native.py."""
import math, os, struct, sys, tempfile, unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'animlab', 'visual'))
import ogre  # noqa: E402
import native as NT  # noqa: E402
from test_visual import chunk, write_skeleton  # noqa: E402


def qaxis(axis, deg):
    a = np.asarray(axis, float); a = a / np.linalg.norm(a); h = math.radians(deg) / 2
    return (math.cos(h),) + tuple(a * math.sin(h))


def anim_chunk(name, length, tracks):
    """tracks {handle: [(t, (w,x,y,z), (dx,dy,dz))]} -> SK_ANIMATION chunk (keyframes with scale)."""
    body = name.encode() + b'\n' + struct.pack('<f', length)
    for h, keys in tracks.items():
        kb = b''
        for t, q, d in keys:
            w, x, y, z = q
            kb += chunk(ogre.SK_ANIMATION_TRACK_KEYFRAME, struct.pack('<f4f3f3f', t, x, y, z, w, *d, 1, 1, 1))
        body += chunk(ogre.SK_ANIMATION_TRACK, struct.pack('<H', h) + kb)
    return chunk(ogre.SK_ANIMATION, body)


# a small biped: root, chest, head, both arms (Bip01 names so native.py's defaults apply)
I = (1, 0, 0, 0)
FLIPY = (0.0, 0.0, 1.0, 0.0)
BONES = [('Bip01 Pelvis', 0, -1, (0, 10, 0), I), ('Bip01 Spine2', 1, 0, (0, 3, 0), I), ('Bip01 Head', 2, 1, (0, 3, 0), I),
         ('Bip01 R Clavicle', 3, 1, (-0.5, 2, 0), FLIPY), ('Bip01 R UpperArm', 4, 3, (1, 0, 0), I),
         ('Bip01 R Forearm', 5, 4, (2.8, 0, 0), I), ('Bip01 R Hand', 6, 5, (2.8, 0, 0), I), ('Bip01 Prop2', 7, 6, (0.8, 0, 0), I),
         ('Bip01 L Clavicle', 8, 1, (0.5, 2, 0), I), ('Bip01 L UpperArm', 9, 8, (1, 0, 0), I),
         ('Bip01 L Forearm', 10, 9, (2.8, 0, 0), I), ('Bip01 L Hand', 11, 10, (2.8, 0, 0), I), ('Bip01 Prop1', 12, 11, (0.8, 0, 0), I)]


class Fixture:
    def __init__(self, d):
        self.d = d
        p = os.path.join(d, 'sk.skeleton')
        write_skeleton(p, BONES)
        # 'raise': right upper arm turns 90 deg about Z over 1 s; 'move': pelvis steps +2 along Z (root motion)
        anims = anim_chunk('raise', 1.0, {4: [(0.0, I, (0, 0, 0)), (1.0, qaxis((0, 0, 1), 90), (0, 0, 0))]}) + \
            anim_chunk('move', 2.0, {0: [(0.0, I, (0, 0, 0)), (1.0, I, (0, 0, 2)), (2.0, I, (0, 0, 0))]})
        with open(p, 'ab') as f:
            f.write(anims)
        self.cfg = dict(game_dir=d, skeleton='sk.skeleton', body_meshes=[], head_bone='Bip01 Head',
                        eye_from_head=[0.0, -1.0, -0.5], bones={s: ['Bip01 %s Clavicle' % s, 'Bip01 %s UpperArm' % s,
                                                                    'Bip01 %s Forearm' % s, 'Bip01 %s Hand' % s,
                                                                    'Bip01 Prop%d' % (2 if s == 'R' else 1)] for s in 'LR'},
                        prop_axes=[[2, 3]], prop_local_q={'0': [1, 0, 0, 0]}, prop_roll_deg={'0': 0},
                        prop_mirror={'L': {'q_sign': [1, -1, -1, 1], 'roll_sign': -1, 'roll_add': 180}})


class TestAnimReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.fx = Fixture(self.tmp.name)
        self.path = os.path.join(self.tmp.name, 'sk.skeleton')

    def tearDown(self):
        self.tmp.cleanup()

    def test_read(self):
        A = ogre.load_animations(self.path)
        self.assertEqual(sorted(A), ['move', 'raise'])
        self.assertAlmostEqual(A['raise'].length, 1.0)
        self.assertEqual(A['raise'].nkeys(), 2)
        self.assertEqual(list(ogre.load_animations(self.path, ['move'])), ['move'])
        sk = ogre.load_skeleton(self.path)   # bones still read with animation chunks after them
        self.assertEqual(len(sk.bones), len(BONES))

    def test_track_interp(self):
        tr = ogre.load_animations(self.path)['move'].tracks[0]
        r, d, s = ogre.track_at(tr, 0.5, 2.0, loop=False)
        np.testing.assert_allclose(d, (0, 0, 1), atol=1e-6)
        r, d, s = ogre.track_at(tr, 2.5, 2.0, loop=False)   # clamped past the end: holds the last key
        np.testing.assert_allclose(d, (0, 0, 0), atol=1e-6)
        r, d, s = ogre.track_at(tr, 2.5, 2.0, loop=True)    # wraps to 0.5
        np.testing.assert_allclose(d, (0, 0, 1), atol=1e-6)
        q = ogre.nlerp(np.array(I, float), np.array(qaxis((0, 0, 1), 90)), 0.5)
        self.assertAlmostEqual(2 * math.degrees(math.acos(q[0])), 45.0, places=4)   # nlerp mid of 0..90 deg

    def test_sample_pose(self):
        sk = ogre.load_skeleton(self.path); A = ogre.load_animations(self.path)
        P0 = ogre.sample_pose(sk, A['raise'], 0.0, loop=False)
        P1 = ogre.sample_pose(sk, A['raise'], 1.0, loop=False)
        h = sk.by_name['Bip01 R Hand'].h; ua = sk.by_name['Bip01 R UpperArm'].h
        np.testing.assert_allclose(P0.dpos[h], sk.bones[h].dpos, atol=1e-5)   # t=0 = bind pose
        v0, v1 = P0.dpos[h] - P0.dpos[ua], P1.dpos[h] - P1.dpos[ua]
        self.assertAlmostEqual(float(np.linalg.norm(v0)), float(np.linalg.norm(v1)), places=4)   # rigid arm
        ang = math.degrees(math.acos(float(v0 @ v1) / float(np.linalg.norm(v0) * np.linalg.norm(v1))))
        self.assertAlmostEqual(ang, 90.0, places=3)


class TestNative(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.fx = Fixture(self.tmp.name)
        self.N = NT.Native(self.fx.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_traj_stab(self):
        an = self.N.anim('move')
        ts = [0.0, 1.0]
        w = NT.trajectory(self.N, an, ts, None, 'fixed', 'none', 'hand', None, 'R', 0.0, stab='world')
        p = NT.trajectory(self.N, an, ts, None, 'fixed', 'none', 'hand', None, 'R', 0.0, stab='pelvis')
        self.assertAlmostEqual(float(np.linalg.norm(w[1]['wrR'] - w[0]['wrR'])), 2.0, places=4)   # world: the step shows
        self.assertAlmostEqual(float(np.linalg.norm(p[1]['wrR'] - p[0]['wrR'])), 0.0, places=4)   # pelvis: removed
        self.assertTrue(np.isfinite(w[0]['pL']).all() and np.isfinite(w[0]['fL']).all())       # both hands for target hand

    def test_left_mirror(self):
        Rr, Rl = NT.prop_local_R(self.fx.cfg, 0, 'R'), NT.prop_local_R(self.fx.cfg, 0, 'L')
        self.assertFalse(np.allclose(Rr, Rl))
        cfg = dict(self.fx.cfg); cfg.pop('prop_mirror')
        np.testing.assert_allclose(NT.prop_local_R(cfg, 0, 'L'), Rr)

    def test_grip(self):
        f, u = np.array([0.0, 0, 1]), np.array([0.0, 1, 0])
        d = np.array([-1.6, -0.5, -0.3])
        g = NT.grip_vec(f, u, d)
        wr = np.array([1.0, 2, 3]); pp = wr - g
        A = dict(wr=tuple(wr), pp=tuple(pp), pf=tuple(f), pu=tuple(u))
        np.testing.assert_allclose(NT.measure_grip([dict(R=A)] * 3, 'R'), d, atol=1e-9)

    def test_keyed_path(self):
        G = (np.zeros(3), np.array([0, 0, 1.0]), np.array([0, 1.0, 0]))
        K = [(np.array([0, 0, 2.0]), np.array([0, 0, 1.0]), np.array([0, 1.0, 0]))]
        self.assertTrue(np.allclose(NT.keyed_at(G, K, G, [0.5], 0.0)[0], 0))
        self.assertTrue(np.allclose(NT.keyed_at(G, K, G, [0.5], 0.5)[0], (0, 0, 2)))
        a = NT.keyed_at(G, K, G, [0.5], 0.01)[0][2]; b = NT.keyed_at(G, K, G, [0.5], 0.02)[0][2]
        self.assertLess(a, b - a + 1e-9 + a)   # eases out of the rest pose (zero tangent): tiny first step
        self.assertLess(a, 0.01)

    def test_fit_keys(self):
        # a path through two humps: 5 keys at the right times reproduce it closely
        G = (np.zeros(3), np.array([0, 0, 1.0]), np.array([0, 1.0, 0]))
        U = np.linspace(0, 1, 61)
        dense = {'R': [(u, np.array([0, 0, 3 * math.sin(2 * math.pi * u) ** 2]), G[1], G[2]) for u in U]}
        idx, ku, e95, emax = NT.fit_keys(dense, {'R': G}, {'R': G}, nkeys=5)
        self.assertEqual(len(ku), 5); self.assertTrue(all(b > a for a, b in zip(ku, ku[1:])))
        self.assertLess(e95, 0.3)

    def test_fcs_v17_header(self):
        # regression: `p[0] += i()` skipped the v17 header from the pre-read offset (rebirth.mod failed)
        def st(x):
            return struct.pack('<i', len(x)) + x.encode()
        hdr = struct.pack('<i', 1) + st('') + st('') + st('gamedata.base') + st('') + struct.pack('<i', 9) + b'\0' * 6
        rec = struct.pack('<iii', 0, 17, 0) + st('Punch') + st('1-x.mod') + struct.pack('<i', 0)
        rec += struct.pack('<i', 1) + st('is block') + b'\x01'
        rec += struct.pack('<i', 1) + st('min skill') + struct.pack('<f', 5.0)
        rec += struct.pack('<i', 0) * 2 + struct.pack('<i', 0)   # ints, vec3, vec4
        rec += struct.pack('<i', 1) + st('anim name') + st('kicklow') + struct.pack('<i', 0)   # strings, files
        rec += struct.pack('<i', 0) * 2   # refs, instances
        b = struct.pack('<ii', 17, len(hdr)) + hdr + struct.pack('<ii', 0, 1) + rec
        p = os.path.join(self.tmp.name, 'x.mod')
        with open(p, 'wb') as f:
            f.write(b)
        r = NT.fcs_read(p)
        self.assertEqual(len(r), 1); self.assertEqual(r[0]['name'], 'Punch'); self.assertEqual(r[0]['type'], 17)
        self.assertTrue(r[0]['bools']['is block']); self.assertEqual(r[0]['strings']['anim name'], 'kicklow')


if __name__ == '__main__':
    unittest.main(verbosity=1)
